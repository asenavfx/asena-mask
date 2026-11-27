"""Anonymous, opt-in usage statistics for Asena Mask ("Asena Wrapped").

What this does
  * Always: keeps running totals ON THIS PC (jobs, frames, formats used ...) in %APPDATA%\\AsenaMask\\stats.json.
    The user can see them in Settings > Privacy & Wrapped. They never leave the PC unless sharing is switched on.
  * Off by default (opt-in). Only after the user switches it on (installer page or Settings > Privacy) does it send the
    NEW totals since the last send (plain numbers, no names) every ~10 minutes and when the app closes.
    Settings > Privacy switches it off at any time. (Older settings files that already say "on" keep their choice.)

Never collected: file names, folder paths, anything from inside videos / images, prompts, names, e-mails, IP addresses
(the receiving script does not store them), the text of error messages. The continent comes from the Windows region setting
on this PC and only the continent is sent (never the country).

Set the address of your receiver in DEFAULT_ENDPOINT (or "tm_endpoint" in settings.json). While it is empty nothing is sent
and no notice is shown.
"""
import json
import os
import platform
import threading
import time
import uuid
from datetime import date

from . import paths, APP_VERSION

WRAPPED_ENABLED = False                                  # keep False until you want users to see the Wrapped (the feature stays hidden and
                                                         # only the privacy switch is shown). Flip to True in the update that launches it.
DEFAULT_ENDPOINT = ""                                    # e.g. "https://asenatools.com/stats/"
COMMUNITY_URL = "https://asenatools.com/files/wrapped.json"   # the community Wrapped you publish when you want (see server\README)
SEND_EVERY = 600.0
SAVE_EVERY = 30.0
_MAX_KEY = 48

_CONT = {
    "Africa": "DZ AO BJ BW BF BI CV CM CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY MG MW ML MR MU MA MZ NA NE NG RW ST SN SC SL SO ZA SS SD TZ TG TN UG ZM ZW EH RE YT SH",
    "Asia": "AF AM AZ BH BD BT BN KH CN CY GE HK IN ID IR IQ IL JP JO KZ KW KG LA LB MO MY MV MN MM NP KP OM PK PS PH QA SA SG KR LK SY TW TJ TH TL TR TM AE UZ VN YE",
    "Europe": "AL AD AT BY BE BA BG HR CZ DK EE FO FI FR DE GI GR GG VA HU IS IE IM IT JE XK LV LI LT LU MT MD MC ME NL MK NO PL PT RO RU SM RS SK SI ES SE CH UA GB AX SJ",
    "North America": "AG BS BB BZ CA CR CU DM DO SV GD GT HT HN JM MX NI PA KN LC VC TT US AI AW BM BQ VG KY CW GL GP MQ MS PR BL MF PM SX TC VI",
    "South America": "AR BO BR CL CO EC GY PY PE SR UY VE FK GF",
    "Oceania": "AU FJ KI MH FM NR NZ PW PG WS SB TO TV VU AS CK NU NC PF GU MP TK WF PN NF CC CX",
    "Antarctica": "AQ",
}
_C2C = {c: k for k, v in _CONT.items() for c in v.split()}


def region_continent():
    """The continent of the Windows region setting (Settings > Time & language > Region). Only the continent is ever used."""
    code = ""
    try:
        if os.name == "nt":
            import ctypes
            buf = ctypes.create_unicode_buffer(16)
            if ctypes.windll.kernel32.GetUserDefaultGeoName(buf, 16) > 0:
                code = buf.value
    except Exception:
        pass
    if not code:
        try:
            import locale
            loc = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ""
            if "_" in loc and len(loc.split("_")[-1]) == 2:
                code = loc.split("_")[-1]
        except Exception:
            pass
    return _C2C.get(str(code).upper(), "Unknown")


def _clean_key(k):
    k = "".join(ch for ch in str(k) if ch.isalnum() or ch in "._-@:/ +x×")[:_MAX_KEY]
    return k or "?"


def res_bucket(w, h):
    s = min(int(w or 0), int(h or 0))
    if s <= 0:
        return "unknown"
    for lim, name in ((400, "under 480p"), (600, "480p"), (800, "720p"), (1200, "1080p"), (1600, "1440p"), (2400, "4K"), (99999, "above 4K")):
        if s < lim:
            return name
    return "above 4K"


def fail_bucket(text):
    """A fixed label for a failed job - the error text itself is never stored or sent."""
    t = (text or "").lower()
    for key, label in (("out of memory", "out_of_memory"), ("oom", "out_of_memory"), ("cuda", "gpu_error"),
                       ("engine is missing", "engine_missing"), ("model", "model_problem"), ("stopped unexpectedly", "engine_stopped"),
                       ("could not start", "engine_not_started"), ("ffmpeg", "video_codec"), ("decode", "video_codec")):
        if key in t:
            return label
    return "other"


class Telemetry:
    def __init__(self):
        self.lock = threading.Lock()
        self.path = None
        self.settings = None
        self.total = {"counters": {}, "maps": {}}
        self.sent = {"counters": {}, "maps": {}}
        self.first_seen = date.today().isoformat()
        self.install_id = uuid.uuid4().hex
        self._t_tick = time.time()
        self._t_save = 0.0
        self._t_send = 0.0
        self._dirty = False
        self._env = None
        self._sending = False

    # ------------------------------------------------------------------ setup
    def start(self, settings):
        self.settings = settings
        self.path = paths.data_dir() / "stats.json"
        first_time = not self.path.exists()
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.total = d.get("total", self.total)
            self.sent = d.get("sent", self.sent)
            self.install_id = d.get("id", self.install_id)
            self.first_seen = d.get("first", self.first_seen)
        except Exception:
            pass
        for t in (self.total, self.sent):
            t.setdefault("counters", {})
            t.setdefault("maps", {})
        if first_time:                          # people who used the app before this update keep their history on THIS PC only
            try:
                j, fr = int(settings.get("stat_jobs") or 0), int(settings.get("stat_frames") or 0)
                if j > 0:
                    for tgt in (self.total, self.sent):          # "sent" too: the history is never uploaded
                        tgt["counters"]["jobs"] = j
                        tgt["counters"]["frames_masked"] = fr
            except Exception:
                pass
        try:                                    # the notice was on screen in an earlier session -> they have been told
            if settings.get("tm_notice_shown") and not settings.get("tm_notice_seen"):
                settings.set("tm_notice_seen", True)
        except Exception:
            pass
        self._t_tick = time.time()
        self.count("sessions")
        self.count_map("look", settings.get("look"))
        self._save(force=True)

    # ------------------------------------------------------------------ counting (cheap, always local)
    def count(self, name, n=1):
        with self.lock:
            c = self.total["counters"]
            c[name] = c.get(name, 0) + n
            self._dirty = True

    def count_map(self, group, key, n=1):
        key = _clean_key(key)
        with self.lock:
            g = self.total["maps"].setdefault(group, {})
            if key not in g and len(g) >= 200:
                return
            g[key] = g.get(key, 0) + n
            self._dirty = True

    def job_done(self, params, info):
        """A finished mask job. `params` = the job settings, `info` = what the engine reported. Only numbers / fixed labels."""
        p, info = params or {}, info or {}
        self.count("jobs")
        self.count("frames_masked", int(info.get("frames") or 0))
        self.count("job_seconds", round(float(info.get("seconds") or 0), 1))
        self.count_map("input", p.get("kind", "video"))
        self.count_map("format", p.get("format", "?"))
        self.count_map("resolution", res_bucket(info.get("width"), info.get("height")))
        self.count_map("background", (p.get("bg") or {}).get("mode", "none"))
        self.count_map("pick_method", "click_on_subject" if p.get("selection") else "text_prompt")
        for key, on in (("trim", bool(p.get("trim"))), ("keep_audio", bool(p.get("keep_audio"))), ("split", bool(p.get("split"))),
                        ("fps_changed", bool(p.get("fps"))), ("edge_grow", bool(p.get("edge_grow"))),
                        ("edge_feather", bool(p.get("edge_feather")))):
            if on:
                self.count_map("options_used", key)
        self.count_map("gpu_load", self.settings.get("gpu_load") if self.settings else "normal")

    def job_failed(self, text):
        self.count("jobs_failed")
        self.count_map("fail_reason", fail_bucket(text))

    def error(self, etype, tb):
        where = "?"
        try:
            import traceback as _tb
            frames = _tb.extract_tb(tb) if tb is not None else []
            mine = [f for f in frames if "asenamask" in f.filename.replace("\\", "/")]
            f = (mine or frames or [None])[-1]
            if f is not None:
                where = "%s:%d" % (os.path.basename(f.filename), f.lineno)
        except Exception:
            pass
        self.count_map("errors", "%s@%s" % (getattr(etype, "__name__", "Error"), where))

    # ------------------------------------------------------------------ consent
    @property
    def endpoint(self):
        ep = str(self.settings.get("tm_endpoint") or "") if self.settings is not None else ""
        return ep or DEFAULT_ENDPOINT

    @property
    def available(self):
        return bool(self.endpoint)

    @property
    def enabled(self):
        return bool(self.settings is not None and self.settings.get("telemetry") != "off" and self.endpoint
                    and self.settings.get("tm_notice_seen"))

    @property
    def wanted(self):
        """The switch as the user sees it (on unless they turned it off)."""
        return bool(self.settings is not None and self.settings.get("telemetry") != "off")

    def should_notice(self):
        """Never: stats are opt-in, so consent only comes from the installer or Settings > Privacy switch, not from
        dismissing a banner."""
        return False

    def set_enabled(self, on):
        if self.settings is not None:
            self.settings.set("telemetry", "on" if on else "off")
            self.settings.set("tm_notice_seen", True)

    # ------------------------------------------------------------------ what gets sent
    def environment(self):
        if self._env is None:
            env = {"os": "%s %s" % (platform.system(), platform.release()), "region": region_continent()}
            try:
                from . import sysinfo
                g = sysinfo.gpu_info() or {}
                env["gpu"] = _clean_key(g.get("name", ""))
                env["vram_gb"] = g.get("vram_gb", 0)
                env["ram_gb"] = sysinfo.ram_gb()
            except Exception:
                pass
            self._env = env
        return dict(self._env)

    def _tick(self):
        now = time.time()
        mins = (now - self._t_tick) / 60.0
        self._t_tick = now
        if 0 < mins < 30:
            self.count("minutes_open", round(mins, 2))

    def delta(self):
        with self.lock:
            out = {"counters": {}, "maps": {}}
            for k, v in self.total["counters"].items():
                d = v - self.sent["counters"].get(k, 0)
                if d:
                    out["counters"][k] = round(d, 2)
            for g, m in self.total["maps"].items():
                for k, v in m.items():
                    d = v - self.sent["maps"].get(g, {}).get(k, 0)
                    if d:
                        out["maps"].setdefault(g, {})[k] = d
            return out

    def payload(self):
        self._tick()
        return {"v": 1, "app": "asenamask", "ver": APP_VERSION, "id": self.install_id, "day": date.today().isoformat(),
                "first": self.first_seen, "env": self.environment(), "delta": self.delta()}

    # ------------------------------------------------------------------ saving / sending
    def _save(self, force=False):
        if self.path is None:
            return
        now = time.time()
        if not force and (not self._dirty or now - self._t_save < SAVE_EVERY):
            return
        self._t_save = now
        self._dirty = False
        try:
            with self.lock:
                d = {"id": self.install_id, "first": self.first_seen, "total": self.total, "sent": self.sent}
            tmp = str(self.path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(tmp, str(self.path))
        except Exception:
            pass

    def poll(self):
        """Every few seconds from a UI timer: saves now and then, sends when it is time."""
        self._tick()
        self._save()
        if self.enabled and time.time() - self._t_send >= SEND_EVERY:
            self.flush()

    def flush(self, wait=False):
        self._save(force=True)
        if not self.enabled or self._sending:
            return False
        self._t_send = time.time()
        pl = self.payload()
        self._sending = True
        t = threading.Thread(target=self._post, args=(pl,), daemon=True)
        t.start()
        if wait:
            t.join(2.5)
        return True

    def _post(self, pl):
        try:
            import urllib.request
            body = json.dumps(pl).encode("utf-8")
            req = urllib.request.Request(self.endpoint, data=body, method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": "AsenaMask/%s" % APP_VERSION})
            try:
                from .updater import open_url           # same certificate-store fallback the update check uses
                r = open_url(req, timeout=6)
            except Exception:
                r = urllib.request.urlopen(req, timeout=6)
            with r:
                ok = 200 <= r.status < 300
            if ok:
                with self.lock:
                    for k, v in pl["delta"]["counters"].items():
                        self.sent["counters"][k] = self.sent["counters"].get(k, 0) + v
                    for g, m in pl["delta"]["maps"].items():
                        sg = self.sent["maps"].setdefault(g, {})
                        for k, v in m.items():
                            sg[k] = sg.get(k, 0) + v
                self._save(force=True)
        except Exception:
            pass                                     # offline / server down: sent next time
        finally:
            self._sending = False

    def shutdown(self):
        self._tick()
        self._save(force=True)
        if self.enabled:
            self.flush(wait=True)

    def summary(self):
        with self.lock:
            return {"counters": dict(self.total["counters"]), "maps": {g: dict(v) for g, v in self.total["maps"].items()},
                    "first": self.first_seen}


T = Telemetry()
