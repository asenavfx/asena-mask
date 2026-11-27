"""Looping video clips (decoded once with PyAV, played from memory)."""
import os
import threading

import numpy as np
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtGui import QImage

from .. import paths


class VideoLoop(QObject):
    ready = Signal()
    frame = Signal()

    def __init__(self, filename, max_w, blur=0.0, fps=24, parent=None):
        super().__init__(parent)
        self.path = paths.asset(filename)
        self.max_w, self.blur, self.fps = max_w, blur, fps
        self.frames = []
        self.idx = 0
        self._loading = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._pending = []     # frames delivered from the thread
        self.ready.connect(self._adopt)

    def load(self):
        if self._loading or self.frames or not os.path.isfile(self.path):
            return
        self._loading = True
        threading.Thread(target=self._decode, daemon=True).start()

    def _decode(self):
        try:
            import av
            from PIL import Image, ImageFilter
            out = []
            with av.open(self.path) as c:
                s = c.streams.video[0]
                if s.average_rate:
                    self.fps = float(s.average_rate)
                for f in c.decode(s):
                    im = f.to_image()
                    if im.width > self.max_w:
                        im = im.resize((self.max_w, round(im.height * self.max_w / im.width)), Image.BILINEAR)
                    if self.blur > 0:
                        im = im.filter(ImageFilter.GaussianBlur(self.blur))
                    a = np.asarray(im.convert("RGB"))
                    h, w, _ = a.shape
                    out.append(QImage(a.data, w, h, 3 * w, QImage.Format_RGB888).copy())
            self._pending = out
        except Exception:
            self._pending = []
        self.ready.emit()      # queued to the GUI thread

    def _adopt(self):
        self.frames, self._pending = self._pending, []
        self._loading = False
        self.idx = 0
        if self.timer.isActive() or self._want_play:
            self.start()
        self.frame.emit()

    _want_play = False

    def start(self):
        self._want_play = True
        if self.frames and not self.timer.isActive():
            self.timer.start(int(1000 / max(1.0, self.fps)))

    def stop(self):
        self._want_play = False
        self.timer.stop()

    def current(self):
        return self.frames[self.idx] if self.frames else None

    def _tick(self):
        if self.frames:
            self.idx = (self.idx + 1) % len(self.frames)
            self.frame.emit()


_logo = None


def logo_anim():
    global _logo
    if _logo is None:
        _logo = VideoLoop("logo_anim.mp4", max_w=520)
    return _logo
