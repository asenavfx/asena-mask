"""Processing worker. Runs in its own process so Cancel can simply stop it.

Reads a job JSON file, prints progress lines starting with @@ASENA@@ (JSON).
Set "demo": true in the job (or ASENA_DEMO=1) to skip the AI and draw a fake mask (for UI testing).

Job fields (besides the obvious ones): selection {frame, boxes, pos, neg, extra:[{frame, boxes, pos, neg}]},
trim {start, end}, bg {mode: none|color|image, color, image}, keep_audio, split (one file per subject).
"""
import json
import math
import os
import subprocess
import sys
import time
import traceback
from fractions import Fraction

from .common import clean_mask, PREFIX, emit, demo_masks, edge_adjust, load_engine, device_of, stabilize_masks, sharpen_alpha, find_duplicates, defringe, flag_frames  # noqa: F401  (re-exported)

PREVIEW_W = 560
PREVIEW_MAX_FRAMES = 150
AUDIO_CODEC = {"mov": ["-c:a", "pcm_s16le"], "webm": ["-c:a", "libopus", "-b:a", "160k"],
               "mp4": ["-c:a", "aac", "-b:a", "192k"], "matte": ["-c:a", "aac", "-b:a", "192k"]}


def build_ffmpeg_cmd(ffmpeg, fmt, w, h, fps_arg, out_path, audio=None):
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
           "-s", "%dx%d" % (w, h), "-r", fps_arg, "-i", "-"]
    if audio:
        cmd += ["-ss", "%.6f" % audio["start"], "-t", "%.6f" % audio["dur"], "-i", audio["path"],
                "-map", "0:v:0", "-map", "1:a:0?"]
    if fmt in ("matte", "mp4"):
        cmd += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0", "-c:v", "libx264", "-crf", "14" if fmt == "matte" else "16",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    elif fmt == "mov":
        cmd += ["-vf", "scale=out_color_matrix=bt709", "-c:v", "prores_ks", "-profile:v", "4444",
                "-vendor", "apl0", "-pix_fmt", "yuva444p10le",
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    else:
        if w % 2 or h % 2:
            cmd += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:color=black@0"]
        cmd += ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-crf", "20", "-b:v", "0",
                "-auto-alt-ref", "0", "-row-mt", "1"]
    if audio:
        cmd += AUDIO_CODEC.get(fmt, AUDIO_CODEC["mp4"]) + ["-shortest"]
    cmd.append(out_path)
    return cmd


def _prompt_kwargs(d, scale=1.0):
    """SAM3_Detect keyword arguments for a box/points selection (coordinates given in original pixels)."""
    kw = {}
    if d.get("boxes"):
        kw["bboxes"] = [{"x": b[0] * scale, "y": b[1] * scale, "width": b[2] * scale, "height": b[3] * scale}
                        for b in d["boxes"]]
    if d.get("pos"):
        kw["positive_coords"] = json.dumps([{"x": int(round(p[0] * scale)), "y": int(round(p[1] * scale))}
                                            for p in d["pos"]])
    if d.get("neg"):
        kw["negative_coords"] = json.dumps([{"x": int(round(p[0] * scale)), "y": int(round(p[1] * scale))}
                                            for p in d["neg"]])
    return kw


def _hex_rgb(c):
    c = (c or "#00b140").lstrip("#")
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (0, 177, 64)


def run(job):
    import numpy as np
    from PIL import Image
    from asenamask import videoinfo

    demo = bool(job.get("demo")) or os.environ.get("ASENA_DEMO") == "1"
    kind = job.get("kind", "video")                 # video | image | folder
    files = job.get("files") or []
    video = job.get("video")
    out_dir = job["out_dir"]
    fmt = job["format"]
    matte = (fmt == "matte")
    grow, feather = int(job.get("edge_grow", 0)), float(job.get("edge_feather", 0))
    bgj = job.get("bg") or {}
    bg_mode = "none" if matte else bgj.get("mode", "none")
    if fmt == "mp4" and bg_mode == "none":          # an MP4 cannot hold transparency: use black instead
        bg_mode, bgj = "color", {"mode": "color", "color": "#000000"}
    os.makedirs(out_dir, exist_ok=True)
    prev_dir = os.path.join(out_dir, "preview")
    os.makedirs(prev_dir, exist_ok=True)

    if kind == "folder":
        info = videoinfo.probe_images(files, "folder")
    else:
        info = videoinfo.probe(video)

    def frame_iter():
        if kind == "folder":
            return videoinfo.iter_folder(files)
        return videoinfo.iter_frames(video)

    src = Fraction(info["fps_num"], info["fps_den"])
    tgt_val = job.get("fps")
    tgt = Fraction(str(tgt_val)).limit_denominator(1001) if tgt_val else src
    ratio = tgt / src
    trim = job.get("trim")
    i0 = int(trim["start"]) if trim else 0
    i1 = int(trim["end"]) if trim else None          # inclusive; None = until the end
    n_src = (i1 - i0 + 1) if trim else max(1, int(info["frames"]))
    total_out = max(1, math.ceil(n_src * ratio))
    sel_total = sum(1 for j in range(n_src) if math.ceil((j + 1) * ratio) - math.ceil(j * ratio) > 0)
    fps_arg = "%d/%d" % (tgt.numerator, tgt.denominator)
    prev_stride = max(1, math.ceil(total_out / PREVIEW_MAX_FRAMES))
    batch_size = int(job.get("batch", 8)) if kind == "video" else 1
    names = [os.path.splitext(os.path.basename(f))[0] + ".png" for f in files] if kind == "folder" else None
    if kind != "video":
        prev_stride = 1

    audio = None
    if job.get("keep_audio", True) and kind == "video" and not job.get("_no_audio"):
        sf = float(src)
        audio = {"path": video, "start": i0 / sf, "dur": n_src / sf}

    E = None
    torch = None
    sel = job.get("selection") or {}
    has_sel = bool(sel.get("boxes") or sel.get("pos"))
    track = kind == "video" and has_sel
    image_sel = (not demo) and kind == "image" and has_sel
    det_kw = _prompt_kwargs(sel) if image_sel else {}
    cond = None
    tracked_objs = None      # list of [N_selected_frames, h, w] float masks, one per subject (track mode)
    tracked_all = None       # union of them
    labels = [""]            # one output per label
    flagged = []             # [{"frame": source frame number, "t": seconds}] where the tracked mask looks wrong
    dfl = int(job.get("defringe", 0))

    if not demo:
        emit(type="status", text="Starting the engine…")
        E = load_engine(job)
        torch = E.torch
        if not (track or image_sel):
            cond = E.nodes.CLIPTextEncode().encode(E.clip, job["prompt"])[0]
    else:
        emit(type="status", text="Demo mode (no AI)…")
        time.sleep(0.3)

    if track and not demo:
        W0, H0 = info["width"], info["height"]
        scale = min(1.0, 1008.0 / max(W0, H0))
        ww, hh = max(8, round(W0 * scale)), max(8, round(H0 * scale))
        emit(type="status", text="Reading the clip…")
        work, abs_idx = [], []
        for i, frame in enumerate(frame_iter()):
            if i < i0:
                continue
            if i1 is not None and i > i1:
                break
            j = i - i0
            if math.ceil((j + 1) * ratio) - math.ceil(j * ratio) <= 0:
                continue
            abs_idx.append(i)
            im = Image.fromarray(frame)
            if scale < 1.0:
                im = im.resize((ww, hh), Image.BILINEAR)
            work.append(np.asarray(im))
        remap = None
        abs_full = list(abs_idx)
        if job.get("dedupe", True) and len(work) > 4:            # anime held frames: process each distinct picture once
            keep_i, remap_l = find_duplicates(work)
            if len(keep_i) <= 0.9 * len(work):
                emit(type="status", text="Skipping %d repeated frames…" % (len(work) - len(keep_i)))
                work = [work[i] for i in keep_i]
                abs_idx = [abs_idx[i] for i in keep_i]
                remap = torch.as_tensor(remap_l, dtype=torch.long)
        images = torch.from_numpy(np.stack(work)).float() / 255.0
        del work
        N = images.shape[0]

        # key frames: the subject you picked, plus any corrections you made on other frames
        keys = [sel] + [k for k in (sel.get("extra") or []) if (k.get("boxes") or k.get("pos"))]
        picked = {}
        for k in keys:
            ref_abs = int(k.get("frame", i0))
            r = min(range(N), key=lambda q: abs(abs_idx[q] - ref_abs))
            picked.setdefault(r, k)
        order = sorted(picked)
        spans = []                                   # (key frame, first frame it owns, last frame it owns)
        for n, r in enumerate(order):
            lo = 0 if n == 0 else (order[n - 1] + r) // 2 + 1
            hi = N - 1 if n == len(order) - 1 else (r + order[n + 1]) // 2
            spans.append((r, lo, hi))
        grand_total = sum((hi - r + 1) + (r - lo + 1 if r > lo else 0) for r, lo, hi in spans) + len(spans)
        offset = {"v": 0}
        try:
            import comfy.utils

            def _hook(value, total, *a, **k):
                emit(type="progress", done=int(offset["v"] + value), total=grand_total, eta=-1)
            comfy.utils.set_progress_bar_global_hook(_hook)
        except Exception:
            pass
        from comfy_extras.nodes_sam3 import SAM3_VideoTrack, SAM3_TrackToMask

        def _track(frames, init, objs):
            td = SAM3_VideoTrack.execute(images=frames, model=E.model, initial_mask=init, conditioning=None,
                                         detection_threshold=float(job["threshold"]), max_objects=int(init.shape[0]),
                                         detect_interval=1)[0]
            if objs is None:
                out = [SAM3_TrackToMask.execute(track_data=td, object_indices="")[0].float().cpu()]
            else:
                out = [SAM3_TrackToMask.execute(track_data=td, object_indices=str(o))[0].float().cpu() for o in objs]
            del td
            offset["v"] += int(frames.shape[0])
            return out

        segs = None
        for n, (r, lo, hi) in enumerate(spans):
            k = picked[r]
            emit(type="status", text="Finding your subject…" if len(spans) == 1 else
                 "Finding your subject (frame %d of %d corrections)…" % (n + 1, len(spans)))
            m0 = E.SAM3_Detect.execute(E.model, images[r:r + 1], conditioning=None, threshold=float(job["threshold"]),
                                       refine_iterations=int(job["refine"]), individual_masks=True,
                                       **_prompt_kwargs(k, scale))[0]
            m0 = m0.float().cpu()
            if m0.dim() == 2:
                m0 = m0[None]
            keep = [q for q in range(m0.shape[0]) if float(m0[q].sum()) > 0]
            if not keep:
                raise RuntimeError("Nothing was found at your selection on frame %d. "
                                   "Try drawing the box around the whole character." % (abs_idx[r] + 1))
            init = m0[keep].float()
            try:
                init = torch.from_numpy(np.stack([clean_mask(x) for x in init.numpy()]).astype("float32"))
            except Exception:
                pass
            init = (init > 0.5).float()
            offset["v"] += 1
            objs = list(range(len(keep))) if (job.get("split") and len(spans) == 1 and len(keep) > 1) else None
            emit(type="status", text="Tracking your selection…")
            fwd = _track(images[r:hi + 1], init, objs)
            if r > lo:
                back = _track(images[lo:r + 1].flip(0), init, objs)
                part = [torch.cat([b[1:].flip(0), f], dim=0) for b, f in zip(back, fwd)]
            else:
                part = fwd
            segs = part if segs is None else [torch.cat([a, b], dim=0) for a, b in zip(segs, part)]
        del images
        if remap is not None:                                    # repeated frames reuse the mask of the frame they repeat
            segs = [s[remap] for s in segs]
        stab = int(job.get("stability", 2))
        if stab > 0:
            emit(type="status", text="Smoothing flicker between frames…")
            segs = [stabilize_masks(s, stab) for s in segs]
        tracked_objs = segs
        tracked_all = segs[0] if len(segs) == 1 else torch.stack(segs).max(dim=0).values
        try:
            sf = float(src)
            flagged = [{"frame": int(abs_full[k]), "t": round(abs_full[k] / sf, 2)}
                       for k in flag_frames(tracked_all.cpu().numpy())][:12]
        except Exception:
            flagged = []
        if len(segs) > 1:
            labels = ["Subject %d" % (q + 1) for q in range(len(segs))]
        emit(type="progress", done=grand_total, total=grand_total, eta=0)
        emit(type="status", text="Saving the result…")
    elif track and demo and job.get("split"):
        labels = ["Subject 1", "Subject 2"]          # demo: exercise the multi-file path

    # ------------------------------------------------------------ background plates
    plate_cache = {}

    def plate(W, H):
        k = (W, H)
        if k not in plate_cache:
            plate_cache.clear()
            if bg_mode == "image" and bgj.get("image") and os.path.isfile(bgj["image"]):
                im = Image.open(bgj["image"]).convert("RGB")
                s = max(W / im.width, H / im.height)
                im = im.resize((max(W, round(im.width * s)), max(H, round(im.height * s))), Image.BILINEAR)
                x0, y0 = (im.width - W) // 2, (im.height - H) // 2
                arr = np.asarray(im.crop((x0, y0, x0 + W, y0 + H))).astype("float32")
            elif bg_mode == "gradient":
                c1, c2 = np.array(_hex_rgb(bgj.get("color1")), "float32"), np.array(_hex_rgb(bgj.get("color2")), "float32")
                t = np.linspace(0.0, 1.0, H, dtype="float32")[:, None, None]
                arr = np.broadcast_to(c1 * (1 - t) + c2 * t, (H, W, 3)).copy()
            else:
                arr = np.empty((H, W, 3), dtype="float32")
                arr[:] = _hex_rgb(bgj.get("color"))
            plate_cache[k] = arr
        return plate_cache[k]

    # ------------------------------------------------------------ one pass over the clip -> one output file (or just the preview)
    def render(tracked, demo_which, result, out_kind, make_preview, write_output, pass_no, passes):
        """tracked: [N,h,w] masks from tracking, or None to detect on every frame. Returns frames written."""
        st = {"out": 0, "prev": 0, "ptr": 0, "proc": None, "log": None}
        log_path = os.path.join(out_dir, "ffmpeg_%d.log" % pass_no)
        still = out_kind in ("image", "png")

        def write_frame(rgba, W, H):
            k = st["out"]
            if write_output:
                if still:
                    img = Image.fromarray(rgba[..., 3], "L") if matte else Image.fromarray(rgba, "RGBA")
                    if out_kind == "image":
                        img.save(result)
                    else:
                        nm = names[k] if names else "%05d.png" % (k + 1)
                        img.save(os.path.join(result, nm), compress_level=1)
                else:
                    if st["proc"] is None:
                        try:
                            import imageio_ffmpeg
                            ff = imageio_ffmpeg.get_ffmpeg_exe()
                        except Exception:
                            ff = "ffmpeg"
                        st["log"] = open(log_path, "w")
                        flags = 0x08000000 if os.name == "nt" else 0
                        st["proc"] = subprocess.Popen(build_ffmpeg_cmd(ff, fmt, W, H, fps_arg, result, audio),
                                                      stdin=subprocess.PIPE, stderr=st["log"], creationflags=flags)
                    st["proc"].stdin.write((np.concatenate([np.repeat(rgba[..., 3:4], 3, axis=-1),
                                                            np.full_like(rgba[..., 3:4], 255)], axis=-1) if matte
                                            else rgba).tobytes())
            if make_preview and k % prev_stride == 0:
                im = Image.fromarray(rgba, "RGBA")
                pw = min(PREVIEW_W, W)
                ph = max(1, round(H * pw / W))
                im.resize((pw, ph), Image.BILINEAR).save(
                    os.path.join(prev_dir, "%05d.png" % (st["prev"] + 1)), compress_level=1)
                st["prev"] += 1
            st["out"] = k + 1

        def process(buf, counts, start_idx):
            arr = np.stack(buf)
            B, H, W, _ = arr.shape
            if demo:
                if demo_which is None and len(labels) > 1:      # union of the demo subjects
                    ms = np.maximum(demo_masks(arr, start_idx, 0), demo_masks(arr, start_idx, 1))
                else:
                    ms = demo_masks(arr, start_idx, demo_which)
                masks = edge_adjust(ms, grow, feather, None)
                time.sleep(0.05)
            elif tracked is not None:
                t = tracked[st["ptr"]:st["ptr"] + B]
                st["ptr"] += B
                if t.shape[-2:] != (H, W):
                    t = torch.nn.functional.interpolate(t[:, None], size=(H, W), mode="bilinear",
                                                        align_corners=False)[:, 0]
                    t = sharpen_alpha(t, int(job.get("stability", 2)))
                masks = edge_adjust(t.clamp(0, 1), grow, feather, torch).numpy()
            else:
                images = torch.from_numpy(arr).float() / 255.0
                m = E.SAM3_Detect.execute(E.model, images, conditioning=cond, threshold=float(job["threshold"]),
                                          refine_iterations=int(job["refine"]), individual_masks=False, **det_kw)[0]
                masks = edge_adjust(m.float().clamp(0, 1), grow, feather, torch).numpy()
            alpha = (masks * 255.0).round().astype("uint8")
            for i in range(B):
                frame_rgb = arr[i]
                if dfl > 0 and not matte:
                    frame_rgb = defringe(arr[i], alpha[i].astype("float32") / 255.0, dfl)
                if bg_mode != "none":
                    a = (alpha[i][..., None].astype("float32")) / 255.0
                    if bg_mode == "blur":
                        from PIL import ImageFilter
                        pl = np.asarray(Image.fromarray(arr[i]).filter(ImageFilter.GaussianBlur(max(6, W / 70.0)))).astype("float32")
                    else:
                        pl = plate(W, H)
                    rgb = (frame_rgb.astype("float32") * a + pl * (1.0 - a)).round().astype("uint8")
                    rgba = np.concatenate([rgb, np.full((H, W, 1), 255, dtype="uint8")], axis=-1)
                else:
                    rgba = np.concatenate([frame_rgb, alpha[i][..., None]], axis=-1)
                rgba = np.ascontiguousarray(rgba)
                for _ in range(counts[i]):
                    write_frame(rgba, W, H)

        t0 = time.time()
        done_sel = 0
        buf, counts = [], []
        batch_start = 0
        show_progress = tracked is None
        try:
            for i, frame in enumerate(frame_iter()):
                if i < i0:
                    continue
                if i1 is not None and i > i1:
                    break
                j = i - i0
                c = math.ceil((j + 1) * ratio) - math.ceil(j * ratio)
                if c <= 0:
                    continue
                if not buf:
                    batch_start = i
                buf.append(frame)
                counts.append(c)
                if len(buf) == batch_size:
                    process(buf, counts, batch_start)
                    done_sel += len(buf)
                    buf, counts = [], []
                    if show_progress:
                        el = time.time() - t0
                        emit(type="progress", done=pass_no * sel_total + done_sel, total=max(passes * sel_total, 1),
                             eta=(el / done_sel) * (sel_total - done_sel + (passes - pass_no - 1) * sel_total)
                             if done_sel else -1)
            if buf:
                process(buf, counts, batch_start)
                done_sel += len(buf)
                if show_progress and pass_no == passes - 1:
                    emit(type="progress", done=max(passes * sel_total, 1), total=max(passes * sel_total, 1), eta=0)
        finally:
            if st["proc"] is not None:
                try:
                    st["proc"].stdin.close()
                except Exception:
                    pass
                st["proc"].wait()
            if st["log"]:
                st["log"].close()
        if st["out"] == 0:
            raise RuntimeError("No frames were read from the video.")
        if st["proc"] is not None and st["proc"].returncode != 0:
            tail = ""
            try:
                tail = open(log_path).read()[-600:]
            except Exception:
                pass
            raise RuntimeError("Video encoder failed. " + tail)
        return st["out"]

    # ------------------------------------------------------------ output paths
    def out_target(label_no):
        """(path, kind) of the output for subject number label_no (-1 = the only one)."""
        tag = "" if label_no < 0 else "_%d" % (label_no + 1)
        if kind == "image":
            return os.path.join(out_dir, "result%s.png" % tag), "image"
        if kind == "folder" or fmt == "png":
            d = os.path.join(out_dir, "result%s_png" % tag)
            os.makedirs(d, exist_ok=True)
            return d, "png"
        ext = {"mov": "mov", "webm": "webm", "matte": "mp4", "mp4": "mp4"}[fmt]
        return os.path.join(out_dir, "result%s.%s" % (tag, ext)), ext

    t_start = time.time()
    outputs = []
    n_labels = len(labels)
    multi = n_labels > 1
    passes = n_labels + (1 if multi else 0)
    frames_written = 0
    if multi:
        # pass 0: only the preview (all subjects together), then one file per subject
        render(tracked_all, None, None, "mp4", True, False, 0, passes)
    for q in range(n_labels):
        path, out_kind = out_target(q if multi else -1)
        pass_no = q + (1 if multi else 0)
        tr = None
        if tracked_objs is not None:
            tr = tracked_objs[q]
        frames_written = render(tr, q if multi else None, path, out_kind, not multi, True, pass_no, passes)
        outputs.append({"label": labels[q] or "", "result": path, "kind": out_kind})

    first = outputs[0]
    emit(type="done", result=first["result"], kind=first["kind"], outputs=outputs, preview_dir=prev_dir,
         preview_fps=(1.0 if kind == "image" else 2.0 if kind == "folder" else float(tgt) / prev_stride),
         frames=frames_written, seconds=time.time() - t_start, width=info["width"], height=info["height"],
         flagged=flagged)


def main(job_file):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        with open(job_file, "r", encoding="utf-8") as f:
            job = json.load(f)
        run(job)
        return 0
    except Exception as e:
        traceback.print_exc()
        emit(type="error", text=str(e) or e.__class__.__name__)
        return 1
