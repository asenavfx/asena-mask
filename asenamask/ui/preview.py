"""Preview player for the finished cutout (plays the small preview frames)."""
import glob
import os

from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import QPainter, QPixmap, QColor, QPainterPath
from PySide6.QtWidgets import QWidget

from .theme import theme

BACKGROUNDS = {
    "Checker": None,
    "Black": QColor(0, 0, 0),
    "White": QColor(255, 255, 255),
    "Green": QColor(0, 177, 64),
    "Purple": QColor(88, 40, 160),
}


class PreviewPlayer(QWidget):
    frame_changed = Signal(int)
    play_state = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames = []
        self.cache = {}
        self.idx = 0
        self.fps = 24.0
        self.bg = "Checker"
        self.playing = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._next)
        self.setMinimumSize(320, 200)
        self.setCursor(Qt.PointingHandCursor)
        theme.changed.connect(self.update)

    def load(self, folder, fps):
        self.stop()
        self.frames = sorted(glob.glob(os.path.join(folder, "*.png")))
        self.cache = {}
        self.idx = 0
        self.fps = max(1.0, float(fps))
        self.update()

    def count(self):
        return len(self.frames)

    def set_background(self, name):
        self.bg = name
        self.update()

    def play(self):
        if not self.frames:
            return
        self.playing = True
        self.timer.start(int(1000 / self.fps))
        self.play_state.emit(True)

    def stop(self):
        self.playing = False
        self.timer.stop()
        self.play_state.emit(False)

    def toggle(self):
        self.stop() if self.playing else self.play()

    def seek(self, i):
        if not self.frames:
            return
        self.idx = max(0, min(len(self.frames) - 1, i))
        self.update()

    def _next(self):
        if not self.frames:
            return
        self.idx = (self.idx + 1) % len(self.frames)
        self.frame_changed.emit(self.idx)
        self.update()

    def _pix(self, i):
        pm = self.cache.get(i)
        if pm is None:
            pm = QPixmap(self.frames[i])
            if len(self.cache) > 200:
                self.cache.clear()
            self.cache[i] = pm
        return pm

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.toggle()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        area = QRectF(self.rect())
        if not self.frames:
            return
        pm = self._pix(self.idx)
        if pm.isNull():
            return
        scale = min(area.width() / pm.width(), area.height() / pm.height())
        w, h = pm.width() * scale, pm.height() * scale
        vr = QRectF((area.width() - w) / 2, (area.height() - h) / 2, w, h)
        path = QPainterPath()
        path.addRoundedRect(vr, 10, 10)
        p.setClipPath(path)
        col = BACKGROUNDS.get(self.bg)
        if col is None:
            s = 14
            a, b = QColor(60, 60, 68), QColor(84, 84, 94)
            if theme.name == "light":
                a, b = QColor(205, 205, 212), QColor(232, 232, 238)
            x0, y0 = int(vr.left()), int(vr.top())
            for y in range(0, int(vr.height()) + s, s):
                for x in range(0, int(vr.width()) + s, s):
                    p.fillRect(x0 + x, y0 + y, s, s, a if ((x // s + y // s) % 2 == 0) else b)
        else:
            p.fillRect(vr, col)
        p.drawPixmap(vr, pm, QRectF(pm.rect()))
