"""Remembers recent clips: their trim, picked subject and main settings, plus a small thumbnail. No Qt in here."""
import hashlib
import json
import os
import time

from . import paths

MAX_KEEP = 40
KEEP_SETTINGS = ("prompt", "threshold", "refine", "edge_grow", "edge_feather", "fps", "format", "bg_mode",
                 "bg_color", "bg_image", "bg_grad", "stability", "defringe")


def _key(path):
    return os.path.normcase(os.path.abspath(path))


class ProjectStore:
    def __init__(self):
        self.dir = paths.data_dir()
        self.file = self.dir / "projects.json"
        self.thumbs = self.dir / "thumbs"
        self.items = {}
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.items = data
        except Exception:
            pass

    def _save(self):
        try:
            if len(self.items) > MAX_KEEP:
                keep = sorted(self.items.items(), key=lambda kv: kv[1].get("used", 0), reverse=True)[:MAX_KEEP]
                self.items = dict(keep)
            self.file.write_text(json.dumps(self.items, indent=1), encoding="utf-8")
        except Exception:
            pass

    def thumb_path(self, path):
        return str(self.thumbs / (hashlib.md5(_key(path).encode("utf-8")).hexdigest()[:16] + ".jpg"))

    @staticmethod
    def thumb_path_for(entry):
        """Thumbnail location of a stored entry (the file may not exist)."""
        try:
            return str(paths.data_dir() / "thumbs" / (hashlib.md5(_key(entry["path"]).encode("utf-8")).hexdigest()[:16] + ".jpg"))
        except Exception:
            return None

    def get(self, path):
        return self.items.get(_key(path))

    def touch(self, path, kind="video", info=None):
        """Marks a clip as just opened (creates the entry if it is new)."""
        k = _key(path)
        e = self.items.get(k) or {"path": os.path.abspath(path), "created": time.time()}
        e["kind"] = kind
        e["used"] = time.time()
        if info:
            e["w"], e["h"] = int(info.get("width", 0)), int(info.get("height", 0))
            e["frames"], e["fps"] = int(info.get("frames", 0)), float(info.get("fps", 0) or 0)
            e["duration"] = float(info.get("duration", 0) or 0)
        self.items[k] = e
        self._save()
        return e

    def update(self, path, trim=None, selection=None, settings=None):
        k = _key(path)
        e = self.items.get(k)
        if e is None:
            return
        e["trim"] = trim
        e["selection"] = selection
        if settings:
            e["settings"] = {a: settings.get(a) for a in KEEP_SETTINGS if a in settings}
        e["used"] = time.time()
        self._save()

    def save_thumb(self, path, rgb):
        """rgb: numpy uint8 array (h, w, 3)."""
        try:
            from PIL import Image
            self.thumbs.mkdir(parents=True, exist_ok=True)
            im = Image.fromarray(rgb)
            im.thumbnail((360, 220))
            dest = self.thumb_path(path)
            im.save(dest, quality=82)
            return dest
        except Exception:
            return None

    def recent(self, n=12):
        out = []
        for e in sorted(self.items.values(), key=lambda e: e.get("used", 0), reverse=True):
            if os.path.exists(e.get("path", "")):
                out.append(e)
            if len(out) >= n:
                break
        return out

    def forget(self, path):
        self.items.pop(_key(path), None)
        try:
            os.remove(self.thumb_path(path))
        except Exception:
            pass
        self._save()


def describe(e):
    """One short line about what is saved for a project, e.g. 'Subject picked · trimmed'."""
    bits = []
    if e.get("selection"):
        bits.append("subject picked")
    if e.get("trim"):
        bits.append("trimmed")
    if not bits:
        bits.append("not edited yet")
    return " · ".join(bits).capitalize()
