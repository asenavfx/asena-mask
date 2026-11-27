"""Optional Discord activity ("Playing Asena Mask"). Off unless the user turns it on in Settings > Privacy.
Talks to the Discord desktop app on this PC through its local pipe; nothing goes over the internet from here and no file
names, folders or video content are ever put in the activity. If Discord is not running, nothing happens.
Standard library only, so it works in existing installs without installing anything."""
import json
import os
import struct
import sys
import threading
import time
import uuid

CLIENT_ID = "1556050179264610355"
LARGE_IMAGE = "logo"            # the art asset key uploaded in the Discord Developer Portal
SITE = "https://asenatools.com"
MIN_GAP = 6.0                   # seconds between activity updates (Discord allows about one per 15 s, extra ones are dropped)


class _Pipe:
    def __init__(self):
        self.f = None

    def connect(self):
        for i in range(10):
            try:
                if os.name == "nt":
                    self.f = open(r"\\?\pipe\discord-ipc-%d" % i, "r+b", buffering=0)
                else:
                    import socket
                    base = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
                    s = socket.socket(socket.AF_UNIX)
                    s.connect(os.path.join(base, "discord-ipc-%d" % i))
                    self.f = s
                return True
            except Exception:
                self.f = None
        return False

    def send(self, op, payload):
        data = json.dumps(payload).encode("utf-8")
        buf = struct.pack("<II", op, len(data)) + data
        if os.name == "nt":
            self.f.write(buf)
        else:
            self.f.sendall(buf)

    def _read(self, n):
        out = b""
        while len(out) < n:
            chunk = self.f.read(n - len(out)) if os.name == "nt" else self.f.recv(n - len(out))
            if not chunk:
                raise IOError("closed")
            out += chunk
        return out

    def recv(self):
        op, ln = struct.unpack("<II", self._read(8))
        return op, json.loads(self._read(ln).decode("utf-8") or "{}")

    def close(self):
        try:
            if self.f is not None:
                self.f.close()
        except Exception:
            pass
        self.f = None


class Presence:
    def __init__(self):
        self.enabled = False
        self._want = None             # (details, state, start_ts or None)
        self._sent = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread = None
        self._stop = False
        self._start = int(time.time())

    # ---- public (call from the UI thread, never blocks)
    def set_enabled(self, on):
        on = bool(on)
        if on == self.enabled:
            return
        self.enabled = on
        if on:
            self._stop = False
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="discord-presence", daemon=True)
                self._thread.start()
        else:
            with self._lock:
                self._want = None
        self._wake.set()

    def idle(self):
        self.update("Ready", "Removing video backgrounds", None)

    def working(self, text, since=None):
        self.update("Removing a background", text, since)

    def update(self, details, state, since=None):
        with self._lock:
            self._want = (details, state, since)
        self._wake.set()

    def shutdown(self):
        self._stop = True
        self.enabled = False
        self._wake.set()

    # ---- worker thread
    def _activity(self, want):
        details, state, since = want
        act = {"details": details, "state": state,
               "timestamps": {"start": int(since or self._start)},
               "assets": {"large_image": LARGE_IMAGE, "large_text": "Asena Mask"},
               "buttons": [{"label": "Get Asena Mask", "url": SITE}]}
        return act

    def _run(self):
        pipe = None
        last_send = 0.0
        while not self._stop:
            if not self.enabled:
                if pipe is not None:
                    self._clear(pipe)
                    pipe.close()
                    pipe = None
                    self._sent = None
                self._wake.wait(2.0)
                self._wake.clear()
                continue
            try:
                if pipe is None:
                    p = _Pipe()
                    if not p.connect():
                        self._wake.wait(15.0)       # Discord not open: try again in a while
                        self._wake.clear()
                        continue
                    p.send(0, {"v": 1, "client_id": CLIENT_ID})
                    p.recv()
                    pipe = p
                    self._sent = None
                with self._lock:
                    want = self._want
                if want is not None and want != self._sent and time.time() - last_send >= MIN_GAP:
                    pipe.send(1, {"cmd": "SET_ACTIVITY", "nonce": str(uuid.uuid4()),
                                  "args": {"pid": os.getpid(), "activity": self._activity(want)}})
                    pipe.recv()
                    self._sent = want
                    last_send = time.time()
            except Exception:
                if pipe is not None:
                    pipe.close()
                pipe = None
                self._sent = None
                self._wake.wait(10.0)
                self._wake.clear()
                continue
            self._wake.wait(MIN_GAP if want is not None and want != self._sent else 5.0)
            self._wake.clear()
        if pipe is not None:
            self._clear(pipe)
            pipe.close()

    @staticmethod
    def _clear(pipe):
        try:
            pipe.send(1, {"cmd": "SET_ACTIVITY", "nonce": str(uuid.uuid4()), "args": {"pid": os.getpid(), "activity": None}})
            pipe.recv()
        except Exception:
            pass


P = Presence()
