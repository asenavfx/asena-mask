"""Read basic info and a thumbnail from a video (PyAV, with an OpenCV fallback)."""
from fractions import Fraction

try:
    import av
except Exception:  # pragma: no cover
    av = None

SUPPORTED = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"]
IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp", ".bmp"]


def is_image(path):
    import os
    return os.path.splitext(str(path))[1].lower() in IMAGE_EXTS


def list_images(folder):
    import os
    names = sorted(f for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in IMAGE_EXTS)
    return [os.path.join(folder, f) for f in names]


def load_image(path):
    """RGB uint8 array (EXIF rotation applied)."""
    import numpy as np
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return np.asarray(im)


def probe_images(files, kind):
    from PIL import Image
    w, h = Image.open(files[0]).size
    return {"width": w, "height": h, "fps_num": 24, "fps_den": 1, "fps": 24.0, "frames": len(files),
            "duration": 0.0, "kind": kind}


def probe(path):
    if is_image(path):
        return probe_images([path], "image")
    if av is not None:
        with av.open(path) as c:
            s = c.streams.video[0]
            fps = s.average_rate or s.guessed_rate or Fraction(24, 1)
            dur = float(c.duration / 1_000_000) if c.duration else 0.0
            frames = s.frames or int(round(dur * float(fps)))
            return {"width": s.codec_context.width, "height": s.codec_context.height,
                    "fps_num": fps.numerator, "fps_den": fps.denominator, "fps": float(fps),
                    "frames": frames, "duration": dur or (frames / float(fps))}
    import cv2
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError("Cannot open video")
    fps = Fraction(cap.get(cv2.CAP_PROP_FPS) or 24).limit_denominator(1001)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    info = {"width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps_num": fps.numerator, "fps_den": fps.denominator, "fps": float(fps),
            "frames": frames, "duration": frames / float(fps)}
    cap.release()
    return info


def thumbnail(path):
    """First frame as an RGB uint8 numpy array (or None)."""
    try:
        if is_image(path):
            return load_image(path)
        if av is not None:
            with av.open(path) as c:
                for f in c.decode(c.streams.video[0]):
                    return f.to_ndarray(format="rgb24")
        import cv2
        cap = cv2.VideoCapture(path)
        ok, fr = cap.read()
        cap.release()
        return fr[:, :, ::-1].copy() if ok else None
    except Exception:
        return None


def iter_frames(path):
    """Yield RGB uint8 frames (a single image yields one frame)."""
    if is_image(path):
        yield load_image(path)
        return
    if av is not None:
        with av.open(path) as c:
            s = c.streams.video[0]
            s.thread_type = "AUTO"
            for f in c.decode(s):
                yield f.to_ndarray(format="rgb24")
        return
    import cv2
    cap = cv2.VideoCapture(path)
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        yield fr[:, :, ::-1].copy()
    cap.release()


def fmt_duration(sec):
    sec = int(round(sec))
    m, s = divmod(sec, 60)
    return "%d:%02d" % (m, s)


def iter_folder(files):
    for f in files:
        yield load_image(f)
