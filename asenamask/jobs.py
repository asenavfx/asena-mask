"""Runs the worker process and turns its output into Qt signals."""
import json
import os
import subprocess
import uuid

from PySide6.QtCore import QThread, Signal

from . import paths
from .worker import PREFIX


class JobThread(QThread):
    status = Signal(str)
    progress = Signal(int, int, float)   # done, total, eta seconds
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, job: dict, parent=None):
        super().__init__(parent)
        self.job = dict(job)
        self.work_dir = str(paths.work_root() / uuid.uuid4().hex[:10])
        os.makedirs(self.work_dir, exist_ok=True)
        self.job["out_dir"] = self.work_dir
        self._proc = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        p = self._proc
        if p and p.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                                   creationflags=0x08000000, capture_output=True)
                else:
                    p.kill()
            except Exception:
                pass

    def run(self):
        job_file = os.path.join(self.work_dir, "job.json")
        with open(job_file, "w", encoding="utf-8") as f:
            json.dump(self.job, f)
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        if paths.install_root():       # installed build: never pick up another Python from this PC
            for k in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
                env.pop(k, None)
        tail, got_end = [], False
        try:
            self._proc = subprocess.Popen(
                paths.worker_command(job_file), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env,
                creationflags=0x08000000 if os.name == "nt" else 0)
            for line in self._proc.stdout:
                line = line.rstrip()
                if line.startswith(PREFIX):
                    try:
                        m = json.loads(line[len(PREFIX):])
                    except Exception:
                        continue
                    t = m.get("type")
                    if t == "status":
                        self.status.emit(m.get("text", ""))
                    elif t == "progress":
                        self.progress.emit(int(m["done"]), int(m["total"]), float(m.get("eta", -1)))
                    elif t == "done":
                        got_end = True
                        self.finished_ok.emit(m)
                    elif t == "error":
                        got_end = True
                        self.failed.emit(m.get("text", "Unknown error"))
                elif line:
                    tail.append(line)
                    tail = tail[-25:]
            self._proc.wait()
        except Exception as e:  # could not even start
            self.failed.emit("Could not start the engine: %s" % e)
            return
        if self._cancelled:
            return
        if not got_end:
            self.failed.emit("The engine stopped unexpectedly.\n" + "\n".join(tail[-8:]))
