"""Inline clip player for the main screen: video, trim bar right underneath, and an optional live cutout preview."""
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from .editor import FrameCanvas, Timeline, fmt_time, selection_keys, interpolate_fractions, selection_to_fractions
from .widgets import GlowButton, title_label


class ClipPlayer(QWidget):
    trim_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loader = None
        self.engine = None
        self.provider = None          # () -> dict of the current settings (prompt, selection, threshold, ...)
        self.info = {}
        self.fps = 24.0
        self.cur = 0
        self.keys = {}                # frame -> picked-subject selection (pixel coordinates), shown read-only
        self.preview_on = False
        self._req = -1
        self._quiet = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.pv_timer = QTimer(self)
        self.pv_timer.setSingleShot(True)
        self.pv_timer.setInterval(170)
        self.pv_timer.timeout.connect(self._send_preview)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.canvas = FrameCanvas(interactive=False)
        self.canvas.clicked.connect(self._canvas_clicked)
        lay.addWidget(self.canvas, 1)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)
        self.play_btn = GlowButton("Play", "chip")
        self.play_btn.setMinimumWidth(70)
        self.play_btn.clicked.connect(self.toggle_play)
        prev = GlowButton("‹", "chip")
        nxt = GlowButton("›", "chip")
        for b in (prev, nxt):
            b.setFixedWidth(38)
        prev.clicked.connect(lambda: self._step(-1))
        nxt.clicked.connect(lambda: self._step(1))
        sin = GlowButton("Start  I", "chip")
        sout = GlowButton("End  O", "chip")
        sin.clicked.connect(lambda: self.timeline.set_in(self.cur))
        sout.clicked.connect(lambda: self.timeline.set_out(self.cur))
        self.time_lbl = title_label("0:00.00", 10, QFont.DemiBold)
        self.pv_btn = GlowButton("Preview cutout", "chip")
        self.pv_btn.setCheckable(True)
        self.pv_btn.clicked.connect(self._toggle_preview)
        for w in (self.play_btn, prev, nxt, sin, sout):
            ctrl.addWidget(w)
        ctrl.addSpacing(6)
        ctrl.addWidget(self.time_lbl)
        ctrl.addStretch(1)
        self.pv_btn.hide()                 # the cutout preview was removed (the editor shows the live selection)
        lay.addLayout(ctrl)

        self.timeline = Timeline(height=76)
        self.timeline.seek.connect(self._seek)
        self.timeline.range_changed.connect(self._range_changed)
        lay.addWidget(self.timeline)
        self.range_lbl = title_label("", 9, QFont.Normal, sub=True)
        lay.addWidget(self.range_lbl)

    # ---- wiring
    def set_engine(self, engine, provider):
        self.engine, self.provider = engine, provider
        engine.result.connect(self._on_result)
        engine.failed.connect(self._on_failed)

    def set_source(self, loader, info):
        self._pause()
        if self.loader is not None:
            try:
                self.loader.progress.disconnect(self._on_progress)
                self.loader.finished_all.disconnect(self._on_loaded)
            except Exception:
                pass
        self.loader, self.info = loader, info
        self.fps = float(info.get("fps") or 24.0)
        n = max(int(info.get("frames") or 1), len(loader.frames), 1)
        self.canvas.set_orig(info["width"], info["height"])
        tl = self.timeline
        tl.n, tl.pos, tl.a, tl.b = n, 0, 0, n - 1
        tl.strip, tl.loaded = [], len(loader.frames)
        self.cur = 0
        self.canvas.pix = None
        loader.progress.connect(self._on_progress)
        loader.finished_all.connect(self._on_loaded)
        if not loader.isRunning() and loader.frames:
            self._on_loaded(len(loader.frames))
        self._show(0)
        self._range_changed(tl.a, tl.b, emit=False)

    def get_trim(self):
        tl = self.timeline
        if tl.a == 0 and tl.b >= tl.n - 1:
            return None
        return {"start": int(tl.a), "end": int(tl.b)}

    def set_trim(self, trim):
        tl = self.timeline
        if trim:
            tl.set_range(max(0, min(trim["start"], tl.n - 1)), max(0, min(trim["end"], tl.n - 1)))
        else:
            tl.set_range(0, tl.n - 1)
        self._range_changed(tl.a, tl.b, emit=False)
        self._request_preview()

    def set_marks(self, selection):
        """Show the picked subject (and corrections) on the bar and on its frame."""
        self.keys = selection_keys(selection)
        self.timeline.refs = sorted(self.keys)
        self.timeline.update()
        self._show_marks()
        self._request_preview()

    # ---- loading
    def _on_progress(self, n):
        self.timeline.loaded = n
        if n and self.canvas.pix is None:
            self._show(self.cur)
        self.timeline.update()

    def _on_loaded(self, n):
        tl = self.timeline
        old_n = tl.n
        tl.loaded = n
        if n and n != old_n:
            was_full = (tl.a == 0 and tl.b >= old_n - 1)
            tl.n = n
            tl.a = min(tl.a, n - 1)
            tl.b = n - 1 if was_full else min(tl.b, n - 1)
        strip = []
        frames = self.loader.frames
        cnt = 14 if n >= 14 else max(1, n)
        for k in range(cnt):
            idx = int((k + 0.5) * n / cnt)
            img = QImage()
            img.loadFromData(frames[min(idx, n - 1)], "JPG")
            strip.append(QPixmap.fromImage(img.scaledToHeight(56, Qt.SmoothTransformation)))
        tl.strip = strip
        self._range_changed(tl.a, tl.b, emit=False)
        tl.update()

    # ---- showing frames
    def _show(self, i):
        fr = self.loader.frames if self.loader else []
        if not fr:
            return
        i = max(0, min(len(fr) - 1, i))
        changed = i != self.cur
        self.cur = i
        pm = QPixmap()
        pm.loadFromData(fr[i], "JPG")
        self.canvas.set_pixmap(pm)
        self.timeline.pos = i
        self.timeline.update()
        self.time_lbl.setText("%s   (frame %d)" % (fmt_time(i, self.fps), i + 1))
        self._show_marks()
        if changed and self.preview_on:
            self.canvas.set_cutout(None)
            self._request_preview()

    def _show_marks(self):
        d = self.keys.get(self.cur)
        self.canvas.set_selection(d) if d else self.canvas.set_state(None)

    def _seek(self, i):
        self._pause()
        self._show(i)

    def _step(self, d):
        self._pause()
        self._show(self.cur + d)

    def _canvas_clicked(self):
        self.setFocus()
        self.toggle_play()

    def toggle_play(self):
        if self.timer.isActive():
            self._pause()
        else:
            if not (self.loader and self.loader.frames):
                return
            tl = self.timeline
            if self.cur >= tl.b or self.cur < tl.a:
                self._show(tl.a)
            self.canvas.set_cutout(None)
            self.canvas.hint = ""
            self.timer.start(int(1000 / max(1.0, self.fps)))
            self.play_btn.setText("Pause")

    def _pause(self):
        was = self.timer.isActive()
        self.timer.stop()
        self.play_btn.setText("Play")
        if was:
            self._request_preview()

    def _tick(self):
        tl = self.timeline
        nxt = self.cur + 1
        if nxt > tl.b:
            nxt = tl.a
        if nxt >= len(self.loader.frames):
            return
        self._show(nxt)

    def pause(self):
        self._pause()

    # ---- trim
    def _range_changed(self, a, b, emit=True):
        n = b - a + 1
        self.range_lbl.setText("Section: %s → %s   ·   %d frames  (%.1f s)" % (
            fmt_time(a, self.fps), fmt_time(b, self.fps), n, n / self.fps))
        if emit:
            self.trim_changed.emit()
            self._request_preview()

    # ---- live cutout preview
    def _toggle_preview(self):
        self.preview_on = self.pv_btn.isChecked()
        self.canvas.hint = ""
        if self.preview_on:
            self._pause()
            self._request_preview()
        else:
            self.canvas.set_cutout(None)
            self.pv_timer.stop()
            self._req = -1
            self.canvas.update()

    def _request_preview(self):
        if self.preview_on and self.engine is not None and not self.timer.isActive():
            self.pv_timer.start()

    def _send_preview(self):
        if not (self.preview_on and self.engine is not None and self.provider and self.loader and self.loader.frames):
            return
        prm = self.provider() or {}
        keys = selection_keys(prm.get("selection"))
        sel, prompt = {}, ""
        if keys:
            size = (self.info.get("width", 1), self.info.get("height", 1))
            fr_keys = {f: selection_to_fractions(k, size) for f, k in keys.items()}
            sel = interpolate_fractions(fr_keys, self.cur)       # on a frame between picked frames: where the subject probably is
        else:
            prompt = (prm.get("prompt") or "").strip()
            if not prompt:
                self.canvas.set_cutout(None)
                self.canvas.hint = "Type what to keep (or pick a subject) to preview the cutout."
                self.canvas.update()
                return
        img = self.engine.save_frame(self.loader.frames[max(0, min(self.cur, len(self.loader.frames) - 1))])
        self._req = self.engine.request(image=img, prompt=prompt, sel=sel, threshold=prm.get("threshold", 0.5),
                                        refine=prm.get("refine", 2), grow=prm.get("grow", 0),
                                        feather=prm.get("feather", 0))
        self.canvas.hint = ("Previewing at the estimated position between your picked frames…" if keys and self.cur not in keys
                            else "Previewing… (the first one takes a moment)")
        self.canvas.update()

    def _on_result(self, m):
        if not self.preview_on or m.get("id") != self._req:
            return
        pm = QPixmap(m.get("cutout", ""))
        prm = (self.provider() or {}) if self.provider else {}
        self.canvas.set_cutout(pm if not pm.isNull() else None, prm.get("backdrop"))
        n = int(m.get("count", 0))
        self.canvas.hint = "" if n else "Nothing found on this frame."
        self.canvas.update()

    def _on_failed(self, text):
        if self.preview_on:
            self.canvas.set_cutout(None)
            self.canvas.hint = "Preview unavailable: %s" % (text.splitlines()[0] if text else "error")
            self.canvas.update()

    # ---- keyboard
    def keyPressEvent(self, e):
        k = e.key()
        step = 10 if e.modifiers() & Qt.ShiftModifier else 1
        if k == Qt.Key_Space:
            self.toggle_play()
        elif k == Qt.Key_Left:
            self._step(-step)
        elif k == Qt.Key_Right:
            self._step(step)
        elif k in (Qt.Key_I, Qt.Key_BracketLeft):
            self.timeline.set_in(self.cur)
        elif k in (Qt.Key_O, Qt.Key_BracketRight):
            self.timeline.set_out(self.cur)
        else:
            super().keyPressEvent(e)
