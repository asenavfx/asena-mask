"""Talks to the live-preview server (a separate process that keeps the AI model loaded)."""
import json
import os
import subprocess
import uuid

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from . import paths
from .common import PREFIX

IDLE_MS = 10 * 60 * 1000       # the model is unloaded after 10 quiet minutes, to give the GPU memory back


class _Reader(QThread):
    message = Signal(dict)
    ended = Signal(str)

    def __init__(self, proc, parent=None):
        super().__init__(parent)
        self.proc = proc

    def run(self):
        tail = []
        try:
            for line in self.proc.stdout:
                line = line.rstrip()
                if line.startswith(PREFIX):
                    try:
                        self.message.emit(json.loads(line[len(PREFIX):]))
                    except Exception:
                        pass
                elif line:
                    tail.append(line)
                    tail = tail[-12:]
        except Exception:
            pass
        self.ended.emit("\n".join(tail[-6:]))


class EngineClient(QObject):
    """Starts the engine on demand. Usage: request(...) -> id; the answer arrives through the `result` signal."""
    state_changed = Signal(str)      # off | starting | ready | error
    status = Signal(str)
    result = Signal(dict)
    failed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self.state = "off"
        self.device = ""
        self.proc = None
        self.reader = None
        self._id = 0
        self._frame_n = 0
        self._pending = None
        self.work = str(paths.work_root() / ("live_" + uuid.uuid4().hex[:8]))
        os.makedirs(self.work, exist_ok=True)
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        self.idle.setInterval(IDLE_MS)
        self.idle.timeout.connect(self.stop)

    # ---- state
    def _set(self, st):
        if st != self.state:
            self.state = st
            self.state_changed.emit(st)

    def available(self):
        """(ok, reason) - whether the engine files exist at all."""
        if os.environ.get("ASENA_DEMO") == "1":
            return True, ""
        comfy, ckdir, ck = self.s.comfy_dir(), self.s.ckpt_dir(), self.s.get("ckpt_name")
        if not comfy or not os.path.isfile(os.path.join(comfy, "main.py")):
            return False, "The AI engine is not installed."
        if not os.path.isfile(os.path.join(ckdir, ck)):
            return False, "The AI model is not installed."
        return True, ""

    # ---- lifecycle
    def ensure_started(self):
        if self.state in ("starting", "ready"):
            return True
        ok, why = self.available()
        if not ok:
            self._set("error")
            self.failed.emit(why)
            return False
        cfg = {"comfy_dir": self.s.comfy_dir(), "ckpt_dir": self.s.ckpt_dir(), "ckpt_name": self.s.get("ckpt_name"),
               "demo": os.environ.get("ASENA_DEMO") == "1", "work_dir": self.work}
        cfg_file = os.path.join(self.work, "server.json")
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        if paths.install_root():
            for k in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
                env.pop(k, None)
        try:
            self.proc = subprocess.Popen(paths.server_command(cfg_file), stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         encoding="utf-8", errors="replace", env=env,
                                         creationflags=0x08000000 if os.name == "nt" else 0)
        except Exception as e:
            self._set("error")
            self.failed.emit("Could not start the engine: %s" % e)
            return False
        self._set("starting")
        self.status.emit("Warming up the AI engine…")
        self.reader = _Reader(self.proc, self)
        self.reader.message.connect(self._on_message)
        self.reader.ended.connect(self._on_ended)
        self.reader.start()
        return True

    def prewarm(self):
        """Starts the engine in the background (if it is not running) so the first live preview is quick."""
        if self.state in ("starting", "ready"):
            return
        try:
            self.idle.setInterval(max(1, int(self.s.get("idle_minutes") or 10)) * 60 * 1000)
        except Exception:
            pass
        self.idle.start()
        self.ensure_started()

    def stop(self):
        """Shuts the engine down and frees the GPU memory it was holding."""
        self.idle.stop()
        self._pending = None
        p, r = self.proc, self.reader
        self.proc = self.reader = None
        was = self.state
        self.state = "off"
        if p is not None:
            try:
                p.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                p.stdin.flush()
            except Exception:
                pass
            try:
                p.wait(1.5)
            except Exception:
                self._kill(p)
        if r is not None:
            try:
                r.message.disconnect()
                r.ended.disconnect()
            except Exception:
                pass
            r.wait(1500)
        if was != "off":
            self.state_changed.emit("off")

    @staticmethod
    def _kill(p):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], creationflags=0x08000000,
                               capture_output=True)
            else:
                p.kill()
        except Exception:
            pass

    # ---- requests
    def save_frame(self, jpeg_bytes):
        """Writes a preview frame where the engine can read it. Returns the file path."""
        self._frame_n = (self._frame_n + 1) % 4
        path = os.path.join(self.work, "frame_%d.jpg" % self._frame_n)
        with open(path, "wb") as f:
            f.write(jpeg_bytes)
        return path

    def request(self, **params):
        """Asks for a detection. Returns the request id (older answers are ignored by the caller)."""
        self._id += 1
        rid = self._id
        payload = dict(params, id=rid, cmd="detect")
        try:
            self.idle.setInterval(max(1, int(self.s.get("idle_minutes") or 10)) * 60 * 1000)
        except Exception:
            pass
        self.idle.start()
        if not self.ensure_started():
            return rid
        if self.state == "starting":
            self._pending = payload                  # only the newest request is kept while the model loads
        else:
            self._send(payload)
        return rid

    def _send(self, payload):
        try:
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
        except Exception:
            self._set("error")
            self.failed.emit("The engine stopped responding.")

    # ---- answers
    def _on_message(self, m):
        t = m.get("type")
        if t == "status":
            self.status.emit(m.get("text", ""))
        elif t == "ready":
            self.device = m.get("device", "")
            self._set("ready")
            self.status.emit("")
            if self._pending is not None:
                p, self._pending = self._pending, None
                self._send(p)
        elif t == "result":
            self.result.emit(m)
        elif t == "error":
            self.failed.emit(m.get("text", "Preview failed."))
        elif t == "fatal":
            self._set("error")
            self.failed.emit(m.get("text", "The engine could not start."))

    def _on_ended(self, tail):
        if self.state in ("starting", "ready"):          # it died on its own
            self._set("error")
            self.failed.emit("The engine stopped unexpectedly.\n" + tail)
        self.proc = None
