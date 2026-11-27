"""Small JSON settings store (no Qt needed)."""
import json
from . import paths

DEFAULTS = {
    "theme": "dark",
    "name": "",
    "first_run_done": False,
    "accent": "Violet",
    "sounds": True,
    "anim_bg": True,
    "comfy_dir": "",
    "ckpt_dir": "",
    "ckpt_name": "sam3.1_multiplex_fp16.safetensors",
    "gpu_load": "normal",          # low / normal / high -> batch size
    "open_folder_after_save": False,
    "last_dir": "",
    "prefix": "asena",
    "prompt": "",
    "threshold": 0.5,
    "refine": 2,
    "bg_grad": "#ff9966:#ff5e62",
    "defringe": 0,                  # 0 off, 1-2: removes the old background colour from cut-out edges
    "stability": 2,                 # 0 off, 1 light, 2 normal, 3 strong: smooths flicker / torn edges of tracked masks
    "format": "mov",
    "edge_grow": 0,
    "edge_feather": 0,
    "fps": "same",
    "bg_mode": "none",             # none | color | image
    "bg_color": "#00b140",
    "bg_image": "",
    "keep_audio": False,
    "split": False,
    "queue_out": "",
    "clock_24h": False,
    "look": "aurora",               # aurora | aero | retro
    "stat_jobs": 0,
    "stat_frames": 0,
    "stat_days": {},
    "start_page": "home",           # home | project
    "auto_update": True,
    "out_dir": "",                  # "" = remember the last folder
    "name_pattern": "{prefix}_{clip}",
    "idle_minutes": 10,             # the AI engine frees the GPU after this many idle minutes
    "live_default": True,
    "notify_done": True,
    "after_queue": "none",          # none | sleep | shutdown
    "seen_version": "",
    "preset": "Balanced (default)",
    "telemetry": "off",             # on | off   (anonymous usage stats, opt-in, see telemetry.py; the installer can set it)
    "tm_notice_seen": False,        # the user has been told (installer page or the one-time Home notice); sending starts after this
    "tm_notice_shown": False,       # the Home notice was displayed once
    "discord_presence": False,      # "Playing Asena Mask" in Discord like any game. Opt-in: Settings > Privacy (see discordrp.py)
    "tm_endpoint": "",
    "wrapped_seen": "",
    "wrapped_intro": False,         # the "Your Asena Wrapped is here" banner has been dismissed
}
BATCH = {"low": 4, "normal": 8, "high": 16}


class Settings:
    def __init__(self):
        self.path = paths.data_dir() / "settings.json"
        self.data = dict(DEFAULTS)
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            if self.data.get("prompt") == "anime character, face, cloth, hands:2, hair, armor":
                self.data["prompt"] = ""   # old built-in default, now empty
        except Exception:
            pass

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        try:
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except Exception:
            pass

    # helpers
    def comfy_dir(self):
        r = paths.install_root()
        if r:   # installed build ignores any developer paths saved in settings
            return str(r / "engine" / "ComfyUI")
        return self.get("comfy_dir") or paths.default_comfy()

    def ckpt_dir(self):
        r = paths.install_root()
        if r:
            return str(r / "models" / "checkpoints")
        d = self.get("ckpt_dir")
        if d:
            return d
        c = self.comfy_dir()
        return str(__import__("pathlib").Path(c) / "models" / "checkpoints") if c else ""

    def batch(self):
        return BATCH.get(self.get("gpu_load"), 8)
