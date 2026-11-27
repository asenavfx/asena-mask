"""Retro navigation: a horizontal icon row along the top, like an old console's main menu (PSP style).

The selected icon grows and shows its name; hovering one pops it up while the others shrink a little; clicking sends
a ring pulse out from the icon. Same signals as the Sidebar, so the app can use either.
"""
import time

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QRadialGradient, QBrush, QLinearGradient

from PySide6.QtWidgets import QWidget

from .theme import theme
from .sidebar import draw_icon
from .. import sound


class XmbBar(QWidget):
    navigate = Signal(str)
    queue_clicked = Signal()
    info_clicked = Signal()

    ITEMS = (("home", "Home"), ("project", "Project"), ("queue", "Queue"), ("settings", "Settings"), ("info", "About"))
    H = 108
    SPACING = 96

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.H)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        n = len(self.ITEMS)
        self.cur = "home"
        self.hover = -1
        self.scale = [1.0] * n
        self.sel = [0.0] * n                 # 1 for the selected item, eased
        self.pulse = [-1.0] * n              # click ring progress, -1 = none
        self.ux = None                       # eased x of the underline
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.clock = QTimer(self)
        self.clock.setInterval(15000)
        self.clock.timeout.connect(self.update)
        self.clock.start()
        theme.changed.connect(self.update)

    # ---- state
    def set_current(self, key):
        if key in dict(self.ITEMS):
            self.cur = key
            self._kick()

    def _kick(self):
        if not self.timer.isActive():
            self.timer.start()

    def _targets(self):
        out = []
        for i, (k, _) in enumerate(self.ITEMS):
            if self.hover >= 0:
                t = 1.4 if i == self.hover else (1.1 if k == self.cur else 0.86)
            else:
                t = 1.3 if k == self.cur else 1.0
            out.append(t)
        return out

    def _tick(self):
        busy = False
        tg = self._targets()
        for i, (k, _) in enumerate(self.ITEMS):
            self.scale[i] += (tg[i] - self.scale[i]) * 0.26
            want = 1.0 if k == self.cur else 0.0
            self.sel[i] += (want - self.sel[i]) * 0.22
            if abs(tg[i] - self.scale[i]) > 0.004 or abs(want - self.sel[i]) > 0.004:
                busy = True
            if self.pulse[i] >= 0:
                self.pulse[i] += 0.045
                if self.pulse[i] >= 1.0:
                    self.pulse[i] = -1.0
                else:
                    busy = True
        cx = self._centers()
        ci = [k for k, _ in self.ITEMS].index(self.cur)
        if self.ux is None:
            self.ux = cx[ci]
        self.ux += (cx[ci] - self.ux) * 0.25
        if abs(cx[ci] - self.ux) > 0.5:
            busy = True
        self.update()
        if not busy:
            self.timer.stop()

    def _centers(self):
        x = 52.0
        out = []
        for s in self.sel:
            w = self.SPACING + 26 * s
            out.append(x + w / 2)
            x += w
        return out

    def _index_at(self, pos):
        best, bd = -1, 1e9
        for i, c in enumerate(self._centers()):
            d = abs(pos.x() - c)
            if d < bd:
                best, bd = i, d
        return best if bd < self.SPACING / 2 and pos.y() < self.H - 4 else -1

    # ---- events
    def mouseMoveEvent(self, e):
        i = self._index_at(e.position())
        if i != self.hover:
            self.hover = i
            if i >= 0:
                sound.play("hover", 0.06)
            self._kick()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.hover = -1
        self._kick()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        i = self._index_at(e.position())
        if i < 0:
            return
        key = self.ITEMS[i][0]
        self.pulse[i] = 0.0
        self.scale[i] = 0.9                      # little squash, springs back
        self._kick()
        sound.play("small")
        if key == "queue":
            self.queue_clicked.emit()
        elif key == "info":
            self.info_clicked.emit()
        else:
            self.set_current(key)
            self.navigate.emit(key)

    # ---- painting
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        cy = 44.0
        centers = self._centers()
        # faint rail under the icons, brighter under the selected one
        p.setPen(QPen(QColor(255, 255, 255, 70), 1.0))
        p.drawLine(QPointF(0, H - 6.5), QPointF(W, H - 6.5))
        if self.ux is None:
            ci = [k for k, _ in self.ITEMS].index(self.cur)
            self.ux = centers[ci]
        g = QLinearGradient(self.ux - 150, 0, self.ux + 150, 0)
        g.setColorAt(0, QColor(255, 255, 255, 0))
        g.setColorAt(0.5, QColor(255, 255, 255, 235))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(QPen(QBrush(g), 2.0))
        p.drawLine(QPointF(self.ux - 150, H - 6.5), QPointF(self.ux + 150, H - 6.5))
        for i, (key, label) in enumerate(self.ITEMS):
            c = QPointF(centers[i], cy)
            sc = self.scale[i]
            act = max(self.sel[i], 1.0 if i == self.hover else 0.0)
            if act > 0.02:   # soft glow behind
                rg = QRadialGradient(c, 42 * sc)
                rg.setColorAt(0, QColor(255, 255, 255, int(95 * act)))
                rg.setColorAt(1, QColor(255, 255, 255, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(rg))
                p.drawEllipse(c, 42 * sc, 42 * sc)
            if self.pulse[i] >= 0:
                t = self.pulse[i]
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, int(210 * (1 - t))), 2.0))
                rr = 16 + 28 * t
                p.drawEllipse(c, rr, rr)
            s = 28.0 * sc
            col = QColor(255, 255, 255, int(150 + 105 * min(1.0, act + (sc - 0.86) * 0.5)))
            draw_icon(p, key, QRectF(c.x() - s / 2, c.y() - s / 2, s, s), col)
            if act > 0.05:
                p.setPen(QColor(255, 255, 255, int(255 * min(1.0, act))))
                f = theme.font(9, QFont.Normal)
                p.setFont(f)
                p.drawText(QRectF(c.x() - 60, cy + 24 * sc, 120, 20), Qt.AlignCenter, label)
        # date and time in the corner, like the handheld's status line
        now = time.localtime()
        txt = "%d/%d  %s" % (now.tm_mon, now.tm_mday, time.strftime("%I:%M%p", now).lstrip("0"))
        p.setPen(QColor(255, 255, 255, 235))
        p.setFont(theme.font(11, QFont.Normal))
        p.drawText(QRectF(W - 220, 10, 200, 24), Qt.AlignRight | Qt.AlignVCenter, txt)
