"""Left navigation bar: Home, Project, Queue, Settings (and Information at the bottom)."""
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPainterPath, QRadialGradient, QBrush
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton

from . import glass
from .theme import theme, mix
from .widgets import HoverMixin
from .. import sound


def draw_icon(p, key, box, col):
    """Small line icons drawn with the painter (no image files needed). box = QRectF of about 24 x 24."""
    pen = QPen(col, 1.7)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    x, y, w, h = box.x(), box.y(), box.width(), box.height()
    if key == "home":
        path = QPainterPath()
        path.moveTo(x + w * 0.12, y + h * 0.48)
        path.lineTo(x + w * 0.5, y + h * 0.12)
        path.lineTo(x + w * 0.88, y + h * 0.48)
        p.drawPath(path)
        body = QPainterPath()
        body.moveTo(x + w * 0.22, y + h * 0.42)
        body.lineTo(x + w * 0.22, y + h * 0.86)
        body.lineTo(x + w * 0.78, y + h * 0.86)
        body.lineTo(x + w * 0.78, y + h * 0.42)
        p.drawPath(body)
        p.drawLine(QPointF(x + w * 0.42, y + h * 0.86), QPointF(x + w * 0.42, y + h * 0.60))
        p.drawLine(QPointF(x + w * 0.58, y + h * 0.60), QPointF(x + w * 0.58, y + h * 0.86))
        p.drawLine(QPointF(x + w * 0.42, y + h * 0.60), QPointF(x + w * 0.58, y + h * 0.60))
    elif key == "project":
        p.drawRoundedRect(QRectF(x + w * 0.1, y + h * 0.2, w * 0.8, h * 0.6), 4, 4)
        tri = QPainterPath()
        tri.moveTo(x + w * 0.42, y + h * 0.36)
        tri.lineTo(x + w * 0.42, y + h * 0.64)
        tri.lineTo(x + w * 0.66, y + h * 0.5)
        tri.closeSubpath()
        p.drawPath(tri)
    elif key == "queue":
        for i in range(3):
            yy = y + h * (0.28 + 0.22 * i)
            p.drawLine(QPointF(x + w * 0.34, yy), QPointF(x + w * 0.9, yy))
            p.drawPoint(QPointF(x + w * 0.14, yy))
    elif key == "settings":
        c = QPointF(x + w / 2, y + h / 2)
        p.drawEllipse(c, w * 0.17, w * 0.17)
        p.drawEllipse(c, w * 0.34, w * 0.34)
        import math
        for k in range(8):
            a = k * math.pi / 4
            p.drawLine(QPointF(c.x() + math.cos(a) * w * 0.34, c.y() + math.sin(a) * w * 0.34),
                       QPointF(c.x() + math.cos(a) * w * 0.46, c.y() + math.sin(a) * w * 0.46))
    elif key == "folder":
        path = QPainterPath()
        path.moveTo(x + w * 0.1, y + h * 0.78)
        path.lineTo(x + w * 0.1, y + h * 0.24)
        path.lineTo(x + w * 0.4, y + h * 0.24)
        path.lineTo(x + w * 0.5, y + h * 0.36)
        path.lineTo(x + w * 0.9, y + h * 0.36)
        path.lineTo(x + w * 0.9, y + h * 0.78)
        path.closeSubpath()
        p.drawPath(path)
    elif key == "clock":
        c = QPointF(x + w / 2, y + h / 2)
        p.drawEllipse(c, w * 0.4, w * 0.4)
        p.drawLine(c, QPointF(c.x(), c.y() - h * 0.24))
        p.drawLine(c, QPointF(c.x() + w * 0.18, c.y() + h * 0.08))
    elif key == "info":
        c = QPointF(x + w / 2, y + h / 2)
        p.drawEllipse(c, w * 0.4, w * 0.4)
        p.drawLine(QPointF(c.x(), c.y() - h * 0.02), QPointF(c.x(), c.y() + h * 0.18))
        p.drawPoint(QPointF(c.x(), c.y() - h * 0.16))


class NavButton(HoverMixin, QPushButton):
    def __init__(self, key, label, checkable=True, parent=None):
        super().__init__(parent)
        self.key, self.label = key, label
        self.badge = False
        self._init_hover()
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(76, 66)
        self.setToolTip(label)
        theme.changed.connect(self.update)

    def set_badge(self, on):
        self.badge = bool(on)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        acc = theme.col("accent")
        r = QRectF(self.rect()).adjusted(5, 3, -5, -3)
        bg = QColor(0, 0, 0, 0)
        if on:
            bg = QColor(acc.red(), acc.green(), acc.blue(), 46)
        else:
            bg = mix(bg, theme.col("hover"), self._h)
        p.setPen(Qt.NoPen)
        if theme.look == "retro":
            if on or self._h > 0.02:
                g = QRadialGradient(QPointF(r.center().x(), r.center().y()), r.width() * 0.7)
                g.setColorAt(0, QColor(255, 255, 255, int((70 if on else 40) * max(self._h, 1.0 if on else 0))))
                g.setColorAt(1, QColor(255, 255, 255, 0))
                p.setBrush(QBrush(g))
                p.drawRoundedRect(r, 6, 6)
        elif theme.glass:
            if on:
                glass.button(p, r, 14, acc, self._h, False, strong=False)
            elif self._h > 0.02:
                glass.chip(p, r, 14, self._h)
        else:
            p.setBrush(bg)
            p.drawRoundedRect(r, 12, 12)
            if on:
                p.setBrush(acc)
                p.drawRoundedRect(QRectF(0, self.height() / 2 - 12, 3.2, 24), 1.6, 1.6)
        col = QColor(255, 255, 255) if (on and (theme.glass or theme.look == "retro")) else (acc if on else mix(theme.col("sub"), theme.col("text"), self._h))
        draw_icon(p, self.key, QRectF(self.width() / 2 - 11, 11, 22, 22), col)
        f = theme.font(8, QFont.DemiBold if on else QFont.Normal)
        p.setFont(f)
        p.setPen(theme.col("text") if on else col)
        p.drawText(QRectF(0, 38, self.width(), 20), Qt.AlignHCenter | Qt.AlignVCenter, self.label)
        if on and theme.look == "retro":
            p.setPen(QPen(QColor(255, 255, 255, 230), 1.6))
            p.drawLine(QPointF(12, 59), QPointF(self.width() - 12, 59))
        if self.badge:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.col("accent2"))
            p.drawEllipse(QPointF(self.width() / 2 + 14, 13), 4.5, 4.5)


class Sidebar(QWidget):
    navigate = Signal(str)        # home | project | settings
    queue_clicked = Signal()
    info_clicked = Signal()

    PAGES = (("home", "Home"), ("project", "Project"), ("settings", "Settings"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(84)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 8, 4, 12)
        lay.setSpacing(4)
        self.btns = {}
        for key, label in (("home", "Home"), ("project", "Project")):
            b = NavButton(key, label)
            b.clicked.connect(lambda _=False, k=key: self._go(k))
            lay.addWidget(b, 0, Qt.AlignHCenter)
            self.btns[key] = b
        self.queue_btn = NavButton("queue", "Queue", checkable=False)
        self.queue_btn.clicked.connect(lambda: (sound.play("small"), self.queue_clicked.emit()))
        lay.addWidget(self.queue_btn, 0, Qt.AlignHCenter)
        lay.addStretch(1)
        st = NavButton("settings", "Settings")
        st.clicked.connect(lambda: self._go("settings"))
        lay.addWidget(st, 0, Qt.AlignHCenter)
        self.btns["settings"] = st
        self.info_btn = NavButton("info", "About", checkable=False)
        self.info_btn.clicked.connect(lambda: (sound.play("small"), self.info_clicked.emit()))
        lay.addWidget(self.info_btn, 0, Qt.AlignHCenter)
        self.set_current("home")

    def _go(self, key):
        sound.play("small")
        self.set_current(key)
        self.navigate.emit(key)

    def set_current(self, key):
        for k, b in self.btns.items():
            b.setChecked(k == key)
