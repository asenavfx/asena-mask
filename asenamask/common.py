"""Helpers shared by the processing worker and the live-preview server. No Qt in here (runs in the engine Python)."""
import json
import math
import os
import sys

PREFIX = "@@ASENA@@"
_LOG = {"path": None}


def set_log(path):
    _LOG["path"] = path


def elog(msg):
    """Appends a timestamped line to the engine log (when one is set)."""
    p = _LOG["path"]
    if not p:
        return
    try:
        import time
        with open(p, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def emit(**kw):
    sys.stdout.write(PREFIX + json.dumps(kw) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------- devices
def device_of(torch):
    """The graphics card to use: CUDA (NVIDIA, and AMD ROCm builds also report as cuda), Intel XPU, or None."""
    try:
        if torch.cuda.is_available():
            return torch.device("cuda")
    except Exception:
        pass
    try:
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            return torch.device("xpu")
    except Exception:
        pass
    return None


def device_label(torch):
    """Human readable description of the accelerator, e.g. 'NVIDIA GeForce RTX 5070 (CUDA 12.8)'."""
    dev = device_of(torch)
    if dev is None:
        return "no supported GPU"
    try:
        if dev.type == "cuda":
            hip = getattr(torch.version, "hip", None)
            return "%s (%s)" % (torch.cuda.get_device_name(0), "ROCm " + hip if hip else "CUDA %s" % torch.version.cuda)
        return "%s (Intel XPU)" % torch.xpu.get_device_name(0)
    except Exception:
        return dev.type


NO_GPU_MESSAGE = ("No supported graphics card was found. Asena Mask needs an NVIDIA GPU "
                  "(or, in the experimental build, a recent AMD Radeon / Intel Arc).")


# ---------------------------------------------------------------- masks
def demo_masks(images_np, start_index, which=None):
    """Fake mask: a soft moving ellipse (`which` shifts it, so two fake subjects can be told apart). numpy only."""
    import numpy as np
    B, H, W, _ = images_np.shape
    yy, xx = np.mgrid[0:H, 0:W].astype("float32")
    out = np.zeros((B, H, W), dtype="float32")
    for i in range(B):
        t = (start_index + i) / 24.0
        cx = W * (0.5 + 0.12 * math.sin(t * 1.3)) + (0.0 if which is None else (which - 0.5) * W * 0.30)
        cy = H * 0.5
        rx, ry = W * 0.22, H * 0.38
        d = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
        out[i] = np.clip((1.0 - d) * 6.0, 0, 1)
    return out


def find_duplicates(frames, thresh=2.0, max_frac=0.002):
    """frames: list of HxWx3 uint8 arrays. Returns (keep, remap): keep = indices of frames worth processing, remap[i] = position in
    `keep` of the frame whose result frame i reuses. Anime is often drawn on 2s / 3s, so many consecutive frames are the same picture
    (up to video-compression noise); each frame is compared with the last KEPT frame, so a slow drift is never mistaken for a hold."""
    import numpy as np

    def small(a):
        h, w = a.shape[:2]
        sy, sx = max(1, h // 144), max(1, w // 256)
        return a[::sy, ::sx].astype("int16")
    keep, remap, last = [], [], None
    for i, f in enumerate(frames):
        s = small(f)
        if last is not None and s.shape == last.shape:
            d = np.abs(s - last)
            if d.mean() <= thresh and (d.max(axis=-1) > 14).mean() <= max_frac:
                remap.append(len(keep) - 1)
                continue
        keep.append(i)
        remap.append(len(keep) - 1)
        last = s
    return keep, remap


def defringe(rgb, alpha, level):
    """Removes the old background colour from the edge of a cut-out: pixels on the rim take the colour of the nearest solid
    pixel inside the subject. rgb: HxWx3 uint8, alpha: HxW float 0..1. level 1 = 1 px, 2 = 2 px (and a wider rim for soft masks).
    Returns a new rgb array. Only pixels that are part of the rim are touched."""
    import numpy as np
    level = int(level)
    if level <= 0:
        return rgb
    h, w = alpha.shape
    solid = alpha >= 0.98
    if not solid.any():
        return rgb
    rim = (alpha > 0.0) & ~solid
    k = level
    core = solid.copy()
    for _ in range(k):                                   # shrink the solid area: its own edge is contaminated too
        c = core.copy()
        c[1:, :] &= core[:-1, :]
        c[:-1, :] &= core[1:, :]
        c[:, 1:] &= core[:, :-1]
        c[:, :-1] &= core[:, 1:]
        core = c
    if not core.any():
        return rgb
    fix = (solid | rim) & ~core                          # outer band that gets recoloured
    if not fix.any():
        return rgb
    col = rgb.astype("float32") * core[..., None]
    known = core.astype("float32")
    ys, xs = np.nonzero(fix)                               # only the thin band is touched, so this stays fast on big frames
    todo = np.ones(len(ys), bool)
    for _ in range(k + 2):                                 # grow colours outward one pixel per step
        if not todo.any():
            break
        y, x = ys[todo], xs[todo]
        num = np.zeros((len(y), 3), "float32")
        den = np.zeros(len(y), "float32")
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                yy, xx = np.clip(y + dy, 0, h - 1), np.clip(x + dx, 0, w - 1)
                kn = known[yy, xx]
                num += col[yy, xx] * kn[:, None]
                den += kn
        ok = den > 0
        yo, xo = y[ok], x[ok]
        col[yo, xo] = num[ok] / den[ok][:, None]
        idx = np.nonzero(todo)[0][ok]
        todo[idx] = False
        known[yo, xo] = 1.0                                # set after the whole step, so each step moves one pixel only
    out = rgb.copy()
    done = ~todo
    out[ys[done], xs[done]] = np.clip(col[ys[done], xs[done]], 0, 255).round().astype("uint8")
    return out


def flag_frames(masks, min_area_frac=0.002):
    """masks: [N,h,w] numpy / tensor-like float. Returns frame indices where the mask area drops out or jumps compared with its
    neighbours (a likely tracking glitch). Adjacent flags are merged into one."""
    import numpy as np
    a = np.asarray(masks)
    n = a.shape[0]
    if n < 5:
        return []
    area = (a > 0.5).reshape(n, -1).mean(axis=1)
    bad = []
    for i in range(n):
        nb = np.concatenate([area[max(0, i - 3):i], area[i + 1:i + 4]])
        med = float(np.median(nb)) if len(nb) else 0.0
        if med < min_area_frac:
            continue
        if area[i] < 0.5 * med or area[i] > 1.6 * med:
            bad.append(i)
    out = []
    for i in bad:
        if not out or i - out[-1][-1] > 1:
            out.append([i])
        else:
            out[-1].append(i)
    return [g[0] for g in out]


def _shift_stack(x, d):
    """x[N,h,w] -> the frames shifted in time by d (edges repeat), same shape."""
    import numpy as np
    n = x.shape[0]
    idx = np.clip(np.arange(n) + d, 0, n - 1)
    return x[idx]


def _morph(x, r, grow):
    """Square max (grow) / min (shrink) filter of radius r on [N,h,w], separable shifts."""
    import numpy as np
    f = np.maximum if grow else np.minimum
    for axis in (1, 2):
        acc = x
        for d in range(1, r + 1):
            for sgn in (-1, 1):
                acc = f(acc, np.roll(x, sgn * d, axis=axis))
        x = acc
    return x


def stabilize_masks(m, level):
    """Cleans a tracked mask sequence [N,h,w] (torch tensor, values 0..1) before it is used:
      level 1  3-frame temporal median: a frame whose mask drops out or jumps for one frame (the flicker) is voted back
      level 2  + closing: fills small holes and torn notches along edges
      level 3  + 5-frame median and a larger closing
    The median only looks at neighbouring frames, so fast motion keeps its shape (no ghost trails)."""
    level = int(level)
    if level <= 0 or m.shape[0] < 3:
        return m
    import numpy as np
    import torch
    a = m.detach().cpu().float().numpy()
    N, h, w = a.shape
    out = np.empty_like(a)
    r = 0 if level < 2 else (1 if level == 2 else 2)
    r = max(r, 0) if r == 0 else max(1, int(round(r * min(h, w) / 560.0)))
    win = 5 if level >= 3 else 3
    half = win // 2
    B = 24                                                        # frames at a time, keeps memory small on long clips
    for s in range(0, N, B):
        e = min(N, s + B)
        lo, hi = max(0, s - half), min(N, e + half)
        seg = a[lo:hi]
        st = np.stack([_shift_stack(seg, d) for d in range(-half, half + 1)], axis=0)
        med = np.median(st, axis=0)[s - lo:e - lo]
        if r:
            med = _morph(_morph(med, r, True), r, False)
        out[s:e] = med
    return torch.from_numpy(out)


def clean_mask(a, island_frac=0.0002, hole_frac=0.0003):
    """Removes specks the model sometimes leaves on ONE mask (numpy 2D float 0..1): tiny floating islands and tiny
    pinholes inside the subject. Real parts of the subject (a hand behind a prop, gaps between hair or an arm and the
    body) are bigger than that and are kept. Used for the live preview and for the first-frame mask the tracking starts from,
    so what you see is what you get."""
    import numpy as np
    try:
        from scipy import ndimage as ndi
    except Exception:
        return a
    h, w = a.shape
    n = float(h * w)
    b = a > 0.5
    if not b.any():
        return a
    out = a.copy()
    lab, k = ndi.label(b)
    if k > 1:
        sizes = ndi.sum(b, lab, index=np.arange(1, k + 1))
        big = float(sizes.max())
        limit = max(24.0, island_frac * n)
        for i, sz in enumerate(sizes, start=1):
            if sz < limit and sz < 0.03 * big:
                out[lab == i] = 0.0
    inv = ~(out > 0.5)
    lab, k = ndi.label(inv)
    if k > 1:
        sizes = ndi.sum(inv, lab, index=np.arange(1, k + 1))
        edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist())
        limit = max(16.0, hole_frac * n)
        for i, sz in enumerate(sizes, start=1):
            if i not in edge and sz < limit:
                out[lab == i] = 1.0
    return out


def sharpen_alpha(t, level):
    """After a mask is scaled up, bilinear scaling leaves a fuzzy 2-3 px ramp on a hard edge. This steepens the ramp so the edge
    is crisp but still anti-aliased. t: tensor 0..1."""
    k = {0: 1.0, 1: 2.0}.get(int(level), 3.0)
    if k == 1.0:
        return t
    return ((t - 0.5) * k + 0.5).clamp(0, 1)


def edge_adjust(m, grow, feather, torch):
    """m: [B,H,W] float mask (torch tensor, or numpy in demo mode). Returns same kind, 0..1.
    grow > 0 expands the mask, grow < 0 shrinks it (pixels). feather softens the edge (pixels)."""
    grow, feather = int(grow), float(feather)
    if grow == 0 and feather <= 0:
        return m.cpu() if torch is not None else m
    if torch is None:                                  # demo mode: numpy/PIL
        import numpy as np
        from PIL import Image, ImageFilter
        out = np.empty_like(m)
        for i in range(m.shape[0]):
            im = Image.fromarray((m[i] * 255).astype("uint8"))
            k = 2 * abs(grow) + 1
            if grow > 0:
                im = im.filter(ImageFilter.MaxFilter(k))
            elif grow < 0:
                im = im.filter(ImageFilter.MinFilter(k))
            if feather > 0:
                im = im.filter(ImageFilter.GaussianBlur(feather / 2.0))
            out[i] = np.asarray(im).astype("float32") / 255.0
        return out
    F = torch.nn.functional
    dev = device_of(torch) or m.device
    x = m.to(dev).float()[:, None]
    k = abs(grow)
    if k:
        x = F.max_pool2d(x, 2 * k + 1, 1, k) if grow > 0 else -F.max_pool2d(-x, 2 * k + 1, 1, k)
    if feather > 0:
        sigma = feather / 2.0
        r = int(math.ceil(3 * sigma))
        t = torch.arange(-r, r + 1, device=dev, dtype=x.dtype)
        g = torch.exp(-(t ** 2) / (2 * sigma ** 2))
        g = g / g.sum()
        x = F.conv2d(F.pad(x, (r, r, 0, 0), mode="replicate"), g.view(1, 1, 1, -1))
        x = F.conv2d(F.pad(x, (0, 0, r, r), mode="replicate"), g.view(1, 1, -1, 1))
    return x[:, 0].clamp(0, 1).cpu()


# ---------------------------------------------------------------- loading the engine
class Engine:
    """Everything needed to run SAM 3 through the ComfyUI code. Created by load_engine()."""
    torch = model = clip = nodes = SAM3_Detect = device = inference_guard = None


def load_engine(job, say=None):
    """Imports ComfyUI + PyTorch and loads the SAM 3 model onto the graphics card."""
    base_say = say or (lambda t: emit(type="status", text=t))

    def say(t):
        elog(t)
        base_say(t)

    comfy_dir = os.path.abspath(job["comfy_dir"])
    if not os.path.isfile(os.path.join(comfy_dir, "main.py")):
        raise RuntimeError("ComfyUI folder not found: %s" % comfy_dir)
    ckpt_dir, ckpt = job["ckpt_dir"], job["ckpt_name"]
    if not os.path.isfile(os.path.join(ckpt_dir, ckpt)):
        raise RuntimeError("Model file not found: %s" % os.path.join(ckpt_dir, ckpt))
    sys.path.insert(0, comfy_dir)
    say("Loading the AI libraries…")
    import torch
    import folder_paths
    folder_paths.add_model_folder_path("checkpoints", ckpt_dir, is_default=True)
    import comfy.model_management  # noqa: F401
    import nodes
    from comfy_extras.nodes_sam3 import SAM3_Detect
    dev = device_of(torch)
    if dev is None:
        raise RuntimeError(NO_GPU_MESSAGE)
    elog("libraries loaded; device %s" % device_label(torch))
    _check_gpu_kernels(torch)
    say("Loading the model onto the graphics card…")
    # inference mode must stay ON for everything that follows. The guard object has to be kept alive: when a
    # local variable held it, it was freed as soon as this function returned and the mode silently switched off
    # ("Inference tensors do not track version counter").
    ctx = torch.inference_mode()
    ctx.__enter__()
    model, clip, _ = nodes.CheckpointLoaderSimple().load_checkpoint(ckpt)
    e = Engine()
    e.torch, e.model, e.clip, e.nodes, e.SAM3_Detect, e.device = torch, model, clip, nodes, SAM3_Detect, dev
    e.inference_guard = ctx
    return e


# ---------------------------------------------------------------- self test (used by the installer / bug reports)
LEGACY_FIX = ('"%s" -m pip install --force-reinstall torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 '
              '--index-url https://download.pytorch.org/whl/cu126')


def _check_gpu_kernels(torch):
    """An NVIDIA card older than the installed PyTorch build supports (for example a GTX 10-series with the CUDA 12.8 build) is
    reported as a working GPU, then every real call fails with 'no kernel image'. Catch that up front with a plain message."""
    try:
        if getattr(torch.version, "cuda", None) is None or not torch.cuda.is_available():
            return
        cap = torch.cuda.get_device_capability(0)
        ok = False
        for a in torch.cuda.get_arch_list():
            try:
                kind, num = a.split("_")
                maj, mnr = int(num[:-1]), int(num[-1])
            except Exception:
                continue
            if kind == "sm" and maj == cap[0] and mnr <= cap[1]:
                ok = True                                    # compiled code for this card (same generation)
            elif kind == "compute" and (maj, mnr) <= cap:
                ok = True                                    # PTX the driver can translate
        if ok:
            return
        name = torch.cuda.get_device_name(0)
        py = sys.executable
        raise RuntimeError(
            "Your graphics card (%s) is too old for the GPU libraries that are installed (they are built for newer "
            "cards).\n\nThis can be fixed: run the Asena Mask installer again and choose Repair / reinstall (newest "
            "version), or in PowerShell run:\n%s\n\nThen start Asena Mask again." % (name, LEGACY_FIX % py))
    except RuntimeError:
        raise
    except Exception:
        return


def selftest():
    """Prints what the installed GPU libraries can do. Safe to run on any PC."""
    out = {"python": sys.version.split()[0]}
    try:
        import torch
        out["torch"] = torch.__version__
        out["cuda"] = getattr(torch.version, "cuda", None)
        out["hip"] = getattr(torch.version, "hip", None)
        dev = device_of(torch)
        out["device"] = dev.type if dev else None
        out["name"] = device_label(torch)
        if dev is not None:
            a = torch.randn(256, 256, device=dev)
            b = (a @ a).sum().item()
            out["matmul"] = "ok" if b == b else "nan"
            try:
                a16 = a.half()
                out["fp16"] = "ok" if (a16 @ a16).float().sum().item() == (a16 @ a16).float().sum().item() else "nan"
            except Exception as e:
                out["fp16"] = "failed: %s" % e
            try:
                import torchvision
                from torchvision.ops import nms
                boxes = torch.tensor([[0, 0, 10, 10], [1, 1, 11, 11]], dtype=torch.float32, device=dev)
                scores = torch.tensor([0.9, 0.8], device=dev)
                out["nms"] = "ok" if len(nms(boxes, scores, 0.5)) == 1 else "unexpected"
                out["torchvision"] = torchvision.__version__
            except Exception as e:
                out["nms"] = "failed: %s" % e
            try:
                q = torch.randn(1, 4, 64, 32, device=dev)
                torch.nn.functional.scaled_dot_product_attention(q, q, q)
                out["attention"] = "ok"
            except Exception as e:
                out["attention"] = "failed: %s" % e
            out["ok"] = out.get("matmul") == "ok"
        else:
            out["ok"] = False
    except Exception as e:
        out["ok"] = False
        out["error"] = "%s: %s" % (e.__class__.__name__, e)
    sys.stdout.write("SELFTEST " + json.dumps(out) + "\n")
    sys.stdout.flush()
    return 0 if out.get("ok") else 1
