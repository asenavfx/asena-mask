"""Batch queue: several videos / pictures, one after another, with the current settings."""
import os
import shutil
import subprocess

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem, QFileDialog, QAbstractItemView

from .. import videoinfo, sound
from ..jobs import JobThread
from .widgets import Overlay, GlowButton, ProgressStrip, title_label

EXTS = videoinfo.SUPPORTED + videoinfo.IMAGE_EXTS
FILTER = "Videos and images (%s)" % " ".join("*" + e for e in EXTS)


class QueueOverlay(Overlay):
    saved_all = Signal(str)          # output folder

    def __init__(self, host, source, settings):
        super().__init__(host, source, frac=(0.88, 0.9), max_size=(900, 760), closable=False)
        self.s = settings
        self.items = []              # file paths
        self.states = []             # wait | run | ok | fail
        self.job = None
        self.running = False
        self.stopping = False
        self.idx = -1
        self.base = None
        self.ok = self.bad = 0
        self.out_dir = self.s.get("queue_out") or ""
        L = self.panel_layout

        row = QHBoxLayout()
        row.addWidget(title_label("Batch queue", 17, QFont.Bold))
        row.addStretch(1)
        self.close_btn = GlowButton("Close", "ghost")
        self.close_btn.setFixedWidth(100)
        self.close_btn.clicked.connect(self.close_overlay)
        row.addWidget(self.close_btn)
        L.addLayout(row)
        info = title_label("Add several videos or pictures. They run one after another with the settings from the main "
                           "screen (what to keep, format, background, edges…) and are saved automatically into the "
                           "folder you choose. Picked subjects and trims are not used in the queue.", 10, QFont.Normal, sub=True)
        info.setWordWrap(True)
        L.addWidget(info)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        L.addWidget(self.list, 1)

        add = QHBoxLayout()
        add.setSpacing(8)
        self.add_btn = GlowButton("Add files…", "chip")
        self.add_btn.clicked.connect(self._add_dialog)
        self.addf_btn = GlowButton("Add a folder…", "chip")
        self.addf_btn.clicked.connect(self._add_folder)
        self.rem_btn = GlowButton("Remove selected", "chip")
        self.rem_btn.clicked.connect(self._remove)
        self.clr_btn = GlowButton("Clear", "chip")
        self.clr_btn.clicked.connect(self._clear)
        for b in (self.add_btn, self.addf_btn, self.rem_btn, self.clr_btn):
            add.addWidget(b)
        add.addStretch(1)
        L.addLayout(add)

        out = QHBoxLayout()
        out.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(title_label("SAVE RESULTS TO", 8, QFont.DemiBold, sub=True))
        self.out_lbl = title_label("", 10, QFont.Normal)
        self.out_lbl.setWordWrap(True)
        col.addWidget(self.out_lbl)
        out.addLayout(col, 1)
        self.out_btn = GlowButton("Choose folder…", "chip")
        self.out_btn.clicked.connect(self._pick_out)
        out.addWidget(self.out_btn)
        L.addLayout(out)

        self.bar = ProgressStrip()
        L.addWidget(self.bar)
        self.status = title_label("", 10, QFont.Normal, sub=True)
        self.status.setTextFormat(Qt.PlainText)      # file names are shown as-is, never as rich text
        self.status.setWordWrap(True)
        L.addWidget(self.status)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.open_btn = GlowButton("Open the folder", "ghost")
        self.open_btn.setFixedWidth(170)
        self.open_btn.clicked.connect(self._open_out)
        self.open_btn.hide()
        bottom.addWidget(self.open_btn)
        bottom.addStretch(1)
        self.stop_btn = GlowButton("Stop", "ghost")
        self.stop_btn.setFixedWidth(120)
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.hide()
        self.start_btn = GlowButton("Start queue", "primary")
        self.start_btn.setFixedWidth(200)
        self.start_btn.clicked.connect(self._start)
        bottom.addWidget(self.stop_btn)
        bottom.addWidget(self.start_btn)
        L.addLayout(bottom)

    # ---- list handling
    def open_with(self, files=None):
        if files:
            self.add_files(files)
        self._refresh_out()
        if not self.running:
            self.status.setText("Add files, check the folder, then press Start queue." if self.items else
                                "Nothing here yet. Drop files on the main screen or press Add files….")
        self.open_overlay()

    def add_files(self, files):
        for f in files:
            f = os.path.normpath(f)
            if os.path.isdir(f):
                names = sorted(n for n in os.listdir(f) if os.path.splitext(n)[1].lower() in videoinfo.SUPPORTED)
                self.add_files([os.path.join(f, n) for n in names])
                continue
            if os.path.splitext(f)[1].lower() in EXTS and f not in self.items:
                self.items.append(f)
                self.states.append("wait")
        self._redraw()

    def _redraw(self):
        self.list.clear()
        icon = {"wait": "•", "run": "▶", "ok": "✓", "fail": "✗"}
        for f, st in zip(self.items, self.states):
            self.list.addItem(QListWidgetItem("%s   %s" % (icon[st], os.path.basename(f))))
        self.start_btn.setEnabled(bool(self.items) and not self.running)

    def _add_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self.window(), "Add videos or pictures", self.s.get("last_dir") or "", FILTER)
        if files:
            self.add_files(files)
            self._refresh_out()

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self.window(), "Add every video in a folder", self.s.get("last_dir") or "")
        if d:
            self.add_files([d])
            self._refresh_out()

    def _remove(self):
        rows = sorted({self.list.row(i) for i in self.list.selectedItems()}, reverse=True)
        for r in rows:
            del self.items[r]
            del self.states[r]
        self._redraw()

    def _clear(self):
        self.items, self.states = [], []
        self._redraw()

    def _default_out(self):
        if self.items:
            return os.path.join(os.path.dirname(self.items[0]), "Asena Output")
        return ""

    def _refresh_out(self):
        d = self.out_dir or self._default_out()
        self.out_lbl.setText(d or "(choose a folder)")

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self.window(), "Where should the results be saved?", self.out_dir or "")
        if d:
            self.out_dir = os.path.normpath(d)
            self.s.set("queue_out", self.out_dir)
            self._refresh_out()

    def _open_out(self):
        d = self.out_dir or self._default_out()
        if d and os.path.isdir(d) and os.name == "nt":
            subprocess.Popen(["explorer", os.path.normpath(d)])

    # ---- running
    def _set_running(self, on):
        self.running = on
        for w in (self.add_btn, self.addf_btn, self.rem_btn, self.clr_btn, self.out_btn, self.close_btn):
            w.setEnabled(not on)
        self.start_btn.setVisible(not on)
        self.stop_btn.setVisible(on)
        self.bar.set_busy(on)
        self._redraw()

    def _start(self):
        host = self.host
        if not self.items or self.running:
            return
        self.base = host.main.params()
        if not self.base["prompt"]:
            self.status.setText("Type what to keep in the main screen first (for example: person). "
                                "The queue uses the same prompt for every file.")
            return
        if not host.engine_ready():
            return
        self.out_dir = self.out_dir or self._default_out()
        try:
            os.makedirs(self.out_dir, exist_ok=True)
        except Exception as e:
            self.status.setText("Could not use that folder: %s" % e)
            return
        host.engine.stop()                         # give the GPU memory back for the real work
        self.states = ["wait"] * len(self.items)
        self.idx, self.ok, self.bad, self.stopping = -1, 0, 0, False
        self.open_btn.hide()
        self.bar.reset()
        self._set_running(True)
        self._next()

    def _stop(self):
        self.stopping = True
        if self.job:
            self.job.cancel()
            self.job.wait(3000)
            self._cleanup()
        self._finish()

    def _params_for(self, path):
        p = dict(self.base)
        is_img = videoinfo.is_image(path)
        fmt = p["format"]
        if is_img:
            fmt = "matte" if fmt == "matte" else "png"
        p.update(video=path, kind="image" if is_img else "video", files=[], selection=None, trim=None,
                 format=fmt, keep_audio=bool(p.get("keep_audio") and not is_img), split=False)
        return p

    def _next(self):
        self.idx += 1
        if self.idx >= len(self.items):
            self._finish()
            return
        self.states[self.idx] = "run"
        self._redraw()
        self.list.setCurrentRow(self.idx)
        name = os.path.basename(self.items[self.idx])
        self.status.setText("File %d of %d: %s — starting…" % (self.idx + 1, len(self.items), name))
        p = self._params_for(self.items[self.idx])
        self.job_params = p
        self.job = JobThread(self.host.make_job(p), self)
        self.job.status.connect(lambda t, n=name: self.status.setText("File %d of %d: %s — %s" % (
            self.idx + 1, len(self.items), n, t)))
        self.job.progress.connect(self._progress)
        self.job.finished_ok.connect(self._job_ok)
        self.job.failed.connect(self._job_failed)
        self.job.start()

    def _progress(self, done, total, eta):
        if total > 0:
            self.bar.set_value((self.idx + done / float(total)) / max(1, len(self.items)))

    def _unique(self, path):
        base, ext = os.path.splitext(path)
        n, cand = 2, path
        while os.path.exists(cand):
            cand = "%s_%d%s" % (base, n, ext)
            n += 1
        return cand

    def _job_ok(self, info):
        src = self.items[self.idx]
        base = os.path.basename(src.rstrip("/\\"))
        stem = os.path.splitext(base)[0]
        try:
            for o in info.get("outputs") or [{"result": info["result"], "kind": info["kind"], "label": ""}]:
                tag = ("_" + o["label"].replace(" ", "").lower()) if o.get("label") else ""
                name = "%s_%s%s" % (self.base["prefix"], stem, tag)
                if o["kind"] == "png":
                    shutil.copytree(o["result"], self._unique(os.path.join(self.out_dir, name)))
                else:
                    ext = {"image": ".png"}.get(o["kind"], "." + o["kind"])
                    shutil.copy2(o["result"], self._unique(os.path.join(self.out_dir, name + ext)))
            self.states[self.idx] = "ok"
            self.ok += 1
            try:
                from .. import telemetry
                telemetry.T.job_done(self.job_params, info)
                telemetry.T.count("saved")
                telemetry.T.count("batch_files")
            except Exception:
                pass
        except Exception as e:
            self.states[self.idx] = "fail"
            self.bad += 1
            self.status.setText("Could not save %s: %s" % (base, e))
        self._cleanup()
        self._next()

    def _job_failed(self, text):
        self.states[self.idx] = "fail"
        self.bad += 1
        try:
            from .. import telemetry
            telemetry.T.job_failed(text)
        except Exception:
            pass
        self._cleanup()
        self.status.setText("%s failed: %s" % (os.path.basename(self.items[self.idx]), text.splitlines()[0][:160]))
        self._next()

    def _cleanup(self):
        if self.job:
            shutil.rmtree(self.job.work_dir, ignore_errors=True)
            self.job = None

    def _finish(self):
        self._set_running(False)
        self.bar.set_value(1.0 if not self.stopping else self.bar._v)
        if self.stopping:
            self.status.setText("Stopped. %d saved, %d failed." % (self.ok, self.bad))
        else:
            self.status.setText("Finished: %d saved, %d failed. Results are in %s" % (self.ok, self.bad, self.out_dir))
            sound.finish()
        self.open_btn.setVisible(self.ok > 0)
        self.saved_all.emit(self.out_dir)

    def on_close(self):
        pass
