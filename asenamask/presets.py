"""Setting presets: a few built-in ones plus the user's own. No Qt in here."""
import json

from . import paths

KEYS = ("threshold", "refine", "edge_grow", "edge_feather", "stability", "defringe")
BUILTIN = {
    "Balanced (default)": {"threshold": 0.5, "refine": 2, "edge_grow": 0, "edge_feather": 0, "stability": 2, "defringe": 0},
    "Fast preview": {"threshold": 0.5, "refine": 1, "edge_grow": 0, "edge_feather": 0, "stability": 1, "defringe": 0},
    "Best quality": {"threshold": 0.5, "refine": 4, "edge_grow": 0, "edge_feather": 1, "stability": 3, "defringe": 1},
    "Clean anime edge": {"threshold": 0.5, "refine": 3, "edge_grow": 0, "edge_feather": 1, "stability": 2, "defringe": 1},
    "Soft hair / fur": {"threshold": 0.4, "refine": 3, "edge_grow": 1, "edge_feather": 3, "stability": 2, "defringe": 0},
    "Tight cut (no halo)": {"threshold": 0.6, "refine": 2, "edge_grow": -2, "edge_feather": 1, "stability": 2, "defringe": 2},
}


class PresetStore:
    def __init__(self):
        self.file = paths.data_dir() / "presets.json"
        self.user = {}
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                self.user = {k: v for k, v in d.items() if isinstance(v, dict)}
        except Exception:
            pass

    def names(self):
        return list(BUILTIN) + [n for n in self.user if n not in BUILTIN]

    def get(self, name):
        return self.user.get(name) or BUILTIN.get(name)

    def is_user(self, name):
        return name in self.user

    def save(self, name, values):
        name = " ".join(name.split())[:40]
        if not name or name in BUILTIN:
            return None
        self.user[name] = {k: values[k] for k in KEYS if k in values}
        self._write()
        return name

    def delete(self, name):
        if self.user.pop(name, None) is not None:
            self._write()

    def _write(self):
        try:
            self.file.write_text(json.dumps(self.user, indent=1), encoding="utf-8")
        except Exception:
            pass
