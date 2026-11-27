"""Live-preview server. Runs in the engine Python (never inside the app window), keeps the model loaded and answers
"detect" requests quickly, so the app can highlight what you are selecting while you click.

Started as:  python main.py --server config.json
Talks JSON lines: requests on stdin, answers on stdout (lines starting with @@ASENA@@).

  {"id": 7, "cmd": "detect", "image": "frame.jpg", "prompt": "person", "sel": {"boxes": [[fx,fy,fw,fh]], "pos": [[fx,fy]], "neg": []},
   "threshold": 0.5, "refine": 2, "grow": 0, "feather": 0}
  -> {"type": "result", "id": 7, "overlay": "...png", "cutout": "...png", "count": 2, "size": [w, h], "ms": 410}
"""
import json
import os
import queue
import sys
import threading
import time
import traceback

from .common import emit, load_engine, edge_adjust, device_label, NO_GPU_MESSAGE, set_log, elog, clean_mask

MAX_SIDE = 1008
PALETTE = [(124, 92, 255), (255, 120, 80), (60, 220, 150), (255, 200, 60), (80, 180, 255), (255, 90, 170)]


def _demo_masks(w, h, sel, prompt):
    import numpy as np
    yy, xx = np.mgrid[0:h, 0:w].astype("float32")
    masks = []

    def ell(cx, cy, rx, ry):
        d = ((xx - cx) / max(rx, 1.0)) ** 2 + ((yy - cy) / max(ry, 1.0)) ** 2
        return np.clip((1.0 - d) * 6.0, 0, 1)

    boxes, pos, neg = sel.get("boxes") or [], sel.get("pos") or [], sel.get("neg") or []
    if boxes:
        for fx, fy, fw, fh in boxes:
            masks.append(ell((fx + fw / 2) * w, (fy + fh / 2) * h, fw * w / 2, fh * h / 2))
    elif pos:
        m = ell(pos[0][0] * w, pos[0][1] * h, 0.12 * min(w, h) * 1.5, 0.12 * min(w, h) * 2.0)
        for fx, fy in neg:
            m = m * (1.0 - ell(fx * w, fy * h, 0.05 * w, 0.05 * w))
        masks.append(m)
    elif prompt.strip():
        masks.append(ell(w * 0.32, h * 0.52, w * 0.16, h * 0.34))
        masks.append(ell(w * 0.68, h * 0.52, w * 0.16, h * 0.34))
    return masks


def _overlay(masks_bool, size):
    """Coloured highlight (soft fill + smooth anti-aliased outline) for each instance. masks_bool: list of [H,W] bool arrays.
    The outline is drawn from a slightly blurred copy of the mask, so it follows the shape smoothly instead of stair-stepping."""
    import numpy as np
    from PIL import Image, ImageFilter
    w, h = size
    out = np.zeros((h, w, 4), dtype=np.float32)
    for k, m in enumerate(masks_bool[:8]):
        col = np.array(PALETTE[k % len(PALETTE)], dtype=np.float32)
        g = np.asarray(Image.fromarray(m.astype("uint8") * 255).filter(ImageFilter.GaussianBlur(1.3)), dtype=np.float32) / 255.0
        fill = g * 105.0
        line = np.clip(1.0 - np.abs(g - 0.5) / 0.62, 0.0, 1.0) * 255.0
        a = np.maximum(fill, line)
        rgb = col[None, None, :]
        take = a > out[..., 3]
        out[..., :3] = np.where(take[..., None], rgb, out[..., :3])
        out[..., 3] = np.where(take, a, out[..., 3])
    return np.clip(out, 0, 255).round().astype(np.uint8)


class Detector:
    def __init__(self, cfg, engine):
        self.cfg, self.E = cfg, engine
        self.cond = {}
        self.work = cfg["work_dir"]
        os.makedirs(self.work, exist_ok=True)

    def _cond(self, prompt):
        c = self.cond.get(prompt)
        if c is None:
            c = self.E.nodes.CLIPTextEncode().encode(self.E.clip, prompt)[0]
            if len(self.cond) > 8:
                self.cond.clear()
            self.cond[prompt] = c
        return c

    def detect(self, req):
        import numpy as np
        from PIL import Image
        t0 = time.time()
        im = Image.open(req["image"]).convert("RGB")
        W0, H0 = im.size
        s = min(1.0, float(MAX_SIDE) / max(W0, H0))
        if s < 1.0:
            im = im.resize((max(8, round(W0 * s)), max(8, round(H0 * s))), Image.BILINEAR)
        arr = np.asarray(im)
        h, w = arr.shape[:2]
        sel = req.get("sel") or {}
        prompt = " ".join((req.get("prompt") or "").split())
        has_sel = bool(sel.get("boxes") or sel.get("pos"))
        thr, refine = float(req.get("threshold", 0.5)), int(req.get("refine", 2))
        grow, feather = int(req.get("grow", 0)), float(req.get("feather", 0))

        torch = None
        if self.E is None:                                    # demo mode: fake masks, no AI
            ms = _demo_masks(w, h, sel, prompt)
            inst = [m > 0.5 for m in ms]
            union = np.maximum.reduce(ms) if ms else np.zeros((h, w), dtype="float32")
            alpha = edge_adjust(union[None].astype("float32"), grow, feather, None)[0]
            time.sleep(0.05)
        else:
            E = self.E
            torch = E.torch
            if not has_sel and not prompt:
                inst, alpha = [], np.zeros((h, w), dtype="float32")
            else:
                images = torch.from_numpy(np.ascontiguousarray(arr)[None]).float() / 255.0
                kw = {}
                if has_sel:
                    cond = None
                    if sel.get("boxes"):
                        kw["bboxes"] = [{"x": b[0] * w, "y": b[1] * h, "width": b[2] * w, "height": b[3] * h}
                                        for b in sel["boxes"]]
                    if sel.get("pos"):
                        kw["positive_coords"] = json.dumps([{"x": int(round(p[0] * w)), "y": int(round(p[1] * h))}
                                                            for p in sel["pos"]])
                    if sel.get("neg"):
                        kw["negative_coords"] = json.dumps([{"x": int(round(p[0] * w)), "y": int(round(p[1] * h))}
                                                            for p in sel["neg"]])
                else:
                    cond = self._cond(prompt)
                try:
                    m = E.SAM3_Detect.execute(E.model, images, conditioning=cond, threshold=thr,
                                              refine_iterations=refine, individual_masks=True, **kw)[0]
                except Exception:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    raise
                m = m.float().cpu()
                if m.dim() == 2:
                    m = m[None]
                keep = [k for k in range(m.shape[0]) if float(m[k].sum()) > 0]
                if keep:
                    mk = m[keep]
                    mk = torch.from_numpy(np.stack([clean_mask(x) for x in mk.numpy()]).astype("float32"))
                    inst = [(mk[k].numpy() > 0.5) for k in range(mk.shape[0])]
                    union = mk.max(dim=0).values
                    alpha = edge_adjust(union[None], grow, feather, torch)[0].numpy()
                else:
                    inst, alpha = [], np.zeros((h, w), dtype="float32")

        rid = int(req.get("id", 0))
        ov_path = os.path.join(self.work, "ov_%d.png" % (rid % 6))
        cut_path = os.path.join(self.work, "cut_%d.png" % (rid % 6))
        Image.fromarray(_overlay(inst, (w, h)), "RGBA").save(ov_path, compress_level=1)
        a8 = (np.clip(alpha, 0, 1) * 255.0).round().astype("uint8")
        Image.fromarray(np.dstack([arr, a8]), "RGBA").save(cut_path, compress_level=1)
        return {"type": "result", "id": rid, "overlay": ov_path, "cutout": cut_path, "count": len(inst),
                "size": [w, h], "ms": int((time.time() - t0) * 1000)}


def warm_up(det, engine):
    """Runs two throw-away detections (a click and a text prompt) so GPU kernels, memory pools and the text encoder are
    already set up when the first real request arrives. Never fails the start-up."""
    try:
        import numpy as np
        from PIL import Image, ImageDraw
        t0 = time.time()
        emit(type="status", text="Warming up the AI engine…")
        im = Image.new("RGB", (960, 540), (40, 60, 90))
        ImageDraw.Draw(im).ellipse((380, 100, 580, 460), fill=(230, 200, 170))
        path = os.path.join(det.work, "warmup.jpg")
        im.save(path, quality=90)
        base = dict(image=path, threshold=0.5, refine=2, grow=0, feather=0)
        with engine.torch.inference_mode():
            det.detect(dict(base, id=-1, sel={"boxes": [], "pos": [[0.5, 0.5]], "neg": []}, prompt=""))
            det.detect(dict(base, id=-2, sel={}, prompt="person"))
        elog("warm-up done in %.1f s" % (time.time() - t0))
    except Exception:
        elog("warm-up skipped: " + traceback.format_exc())


def main(cfg_file):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    with open(cfg_file, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    demo = bool(cfg.get("demo")) or os.environ.get("ASENA_DEMO") == "1"
    try:
        os.makedirs(cfg["work_dir"], exist_ok=True)
        set_log(os.path.join(cfg["work_dir"], "engine.log"))
        open(os.path.join(cfg["work_dir"], "engine.log"), "w").close()
    except Exception:
        pass
    elog("engine server starting (demo=%s)" % demo)
    t_start = time.time()

    q = queue.Queue()

    def reader():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                q.put(json.loads(line))
            except Exception:
                continue
        q.put({"cmd": "quit"})

    engine = None
    try:
        emit(type="status", text="Starting the engine…")
        if not demo:
            engine = load_engine(cfg)
        det = Detector(cfg, engine)
        if engine is not None:
            warm_up(det, engine)                  # the first real click should not pay for the model's first-run set-up
        emit(type="ready", demo=demo, device="demo" if demo else device_label(engine.torch))
        elog("ready after %.1f s" % (time.time() - t_start))
    except Exception as e:
        traceback.print_exc()
        elog("FATAL " + traceback.format_exc())
        emit(type="fatal", text=str(e) or e.__class__.__name__)
        return 1
    # The stdin reader only starts now, after the heavy imports are finished. (Requests sent while the model was
    # loading simply wait in the pipe.) A thread blocked on stdin during "import torch" is the one thing the
    # full-job worker does not have, and it is the prime suspect for the engine never finishing its start-up.
    threading.Thread(target=reader, daemon=True).start()

    while True:
        req = q.get()
        while True:                                  # newest request wins: skip the ones that went stale
            try:
                nxt = q.get_nowait()
            except queue.Empty:
                break
            if nxt.get("cmd") == "quit":
                req = nxt
                break
            if req.get("cmd") == "detect" and nxt.get("cmd") == "detect":
                emit(type="skipped", id=req.get("id", 0))
            req = nxt
        cmd = req.get("cmd")
        if cmd == "quit":
            return 0
        if cmd == "detect":
            elog("detect #%s started" % req.get("id"))
            try:
                if engine is not None:
                    with engine.torch.inference_mode():       # belt and braces: always inside inference mode
                        res = det.detect(req)
                else:
                    res = det.detect(req)
                elog("detect #%s done in %d ms, %d object(s)" % (req.get("id"), res.get("ms", 0), res.get("count", 0)))
                emit(**res)
            except Exception as e:
                traceback.print_exc()
                elog("detect #%s FAILED " % req.get("id") + traceback.format_exc())
                emit(type="error", id=req.get("id", 0), text=str(e) or e.__class__.__name__)


def probe(args):
    """Diagnostic: python main.py --probe [picture.jpg]. Loads the engine once and runs two detections, printing
    how long every stage takes and the full error if something fails."""
    import tempfile
    from PIL import Image, ImageDraw
    from .settings import Settings
    s = Settings()
    t0 = time.time()

    def p(msg):
        print("[%5.1f s] %s" % (time.time() - t0, msg), flush=True)

    cfg = {"comfy_dir": s.comfy_dir(), "ckpt_dir": s.ckpt_dir(), "ckpt_name": s.get("ckpt_name"),
           "work_dir": os.path.join(tempfile.gettempdir(), "AsenaMask", "probe")}
    p("comfy folder: %s" % cfg["comfy_dir"])
    p("model: %s" % os.path.join(cfg["ckpt_dir"], cfg["ckpt_name"]))
    os.makedirs(cfg["work_dir"], exist_ok=True)
    img = args[0] if args and os.path.isfile(args[0]) else os.path.join(cfg["work_dir"], "probe.jpg")
    if not (args and os.path.isfile(args[0])):
        im = Image.new("RGB", (960, 540), (40, 60, 90))
        ImageDraw.Draw(im).ellipse((380, 100, 580, 460), fill=(230, 200, 170))
        im.save(img, quality=92)
        p("no picture given, using a drawn test picture")
    try:
        engine = load_engine(cfg, say=lambda t: p(t))
        p("engine ready on %s" % device_label(engine.torch))
        det = Detector(cfg, engine)
        tests = [("one click in the middle", {"sel": {"boxes": [], "pos": [[0.5, 0.5]], "neg": []}, "prompt": ""}),
                 ("text prompt 'person'", {"sel": {}, "prompt": "person"}),
                 ("same click again (warm)", {"sel": {"boxes": [], "pos": [[0.5, 0.5]], "neg": []}, "prompt": ""})]
        for i, (name, extra) in enumerate(tests):
            p("detection: %s ..." % name)
            req = dict(extra, image=img, id=i + 1, threshold=0.5, refine=2, grow=0, feather=0)
            with engine.torch.inference_mode():
                r = det.detect(req)
            p("   done in %d ms, %d object(s)" % (r["ms"], r["count"]))
        p("ALL GOOD")
        return 0
    except Exception:
        traceback.print_exc()
        p("FAILED - please send me the text above")
        return 1
