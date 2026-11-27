"""A vertical console-style text menu (Retro look): big spaced capitals, the item under the cursor slides in and glows."""
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient, QBrush, QPainterPath
from PySide6.QtWidgets import QWidget

from .theme import theme
from .. import sound


class PsList(QWidget):
    chosen = Signal(int)
    hovered = Signal(int)          # -1 when the cursor leaves

    def __init__(self, items, row_h=52, sticky=True, size=12, parent=None):
        super().__init__(parent)
        self.items = list(items)
        self.row_h = row_h
        self.size = size
        self.sticky = sticky
        self.cur = 0 if sticky else -1
        self.hover = -1
        self.disabled = set()
        self.lvl = [0.0] * len(self.items)
        self.flash = [0.0] * len(self.items)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(row_h * len(self.items))
        self.setMinimumWidth(180)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        theme.changed.connect(self.update)

    def set_items(self, items):
        self.items = list(items)
        self.lvl = [0.0] * len(self.items)
        self.flash = [0.0] * len(self.items)
        self.setFixedHeight(self.row_h * len(self.items))
        self.update()

    def set_current(self, i):
        self.cur = i
        self._kick()

    def set_disabled(self, i, off=True):
        (self.disabled.add if off else self.disabled.discard)(i)
        self.update()

    def _kick(self):
        if not self.timer.isActive():
            self.timer.start()

    def _tick(self):
        busy = False
        for i in range(len(self.items)):
            want = 1.0 if (i == self.hover or i == self.cur) else 0.0
            self.lvl[i] += (want - self.lvl[i]) * 0.24
            if abs(want - self.lvl[i]) > 0.004:
                busy = True
            if self.flash[i] > 0:
                self.flash[i] = max(0.0, self.flash[i] - 0.05)
                busy = busy or self.flash[i] > 0
        self.update()
        if not busy:
            self.timer.stop()

    def _row(self, pos):
        i = int(pos.y() // self.row_h)
        return i if 0 <= i < len(self.items) else -1

    def mouseMoveEvent(self, e):
        i = self._row(e.position())
        if i != self.hover:
            self.hover = i
            if i >= 0 and i not in self.disabled:
                sound.play("hover", 0.06)
            self.hovered.emit(i)
            self._kick()

    def leaveEvent(self, e):
        self.hover = -1
        self.hovered.emit(-1)
        self._kick()

    def mousePressEvent(self, e):
        i = self._row(e.position())
        if e.button() != Qt.LeftButton or i < 0 or i in self.disabled:
            return
        if self.sticky:
            self.cur = i
        self.flash[i] = 1.0
        self._kick()
        sound.play("small")
        self.chosen.emit(i)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W = self.width()
        for i, text in enumerate(self.items):
            y = i * self.row_h
            lv = self.lvl[i]
            dis = i in self.disabled
            if lv > 0.02:   # light sweeping in from the left
                g = QLinearGradient(0, y, W, y)
                g.setColorAt(0, QColor(255, 255, 255, int(46 * lv)))
                g.setColorAt(1, QColor(255, 255, 255, 0))
                p.fillRect(QRectF(0, y + 4, W, self.row_h - 8), QBrush(g))
            if self.flash[i] > 0:
                fg = QLinearGradient(0, y, W, y)
                fg.setColorAt(0, QColor(255, 255, 255, int(120 * self.flash[i])))
                fg.setColorAt(1, QColor(255, 255, 255, 0))
                p.fillRect(QRectF(0, y + 4, W, self.row_h - 8), QBrush(fg))
            p.setPen(QPen(QColor(255, 255, 255, 38), 1.0))
            p.drawLine(QPointF(0, y + self.row_h - 0.5), QPointF(W * 0.9, y + self.row_h - 0.5))
            if lv > 0.05:   # pointer
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, int(255 * lv)))
                ax = 8 + 4 * lv
                tri = QPainterPath()
                cy = y + self.row_h / 2
                tri.moveTo(ax, cy - 6)
                tri.lineTo(ax + 9, cy)
                tri.lineTo(ax, cy + 6)
                tri.closeSubpath()
                p.drawPath(tri)
            f = theme.font(self.size * (1 + 0.14 * lv), QFont.Normal)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
            p.setFont(f)
            a = int((110 + 145 * lv) * (0.4 if dis else 1.0))
            p.setPen(QColor(255, 255, 255, a))
            p.drawText(QRectF(30 + 10 * lv, y, W - 40, self.row_h), Qt.AlignLeft | Qt.AlignVCenter, text.upper())
