"""Small widgets shared by the Aero and Retro home pages."""
import os

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPixmap, QPainterPath, QBrush, QLinearGradient
from PySide6.QtWidgets import QWidget

from .. import projects
from . import glass, retro
from .sidebar import draw_icon
from .theme import theme
from .widgets import HoverMixin


class GadgetRow(HoverMixin, QWidget):
    """A start-menu style row: icon, text and an optional second line. Used by the Frutiger Aero home."""
    clicked = Signal()

    def __init__(self, icon, text, sub="", parent=None):
        super().__init__(parent)
        self._init_hover()
        self.icon, self.text, self.sub = icon, text, sub
        self.setFixedHeight(54)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        theme.changed.connect(self.update)

    def set_sub(self, sub):
        self.sub = sub
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 3, -4, -3)
        p.setOpacity(1.0 if self.isEnabled() else 0.4)
        if self._h > 0.02:
            glass.chip(p, r, 14, self._h)
        cy = r.center().y()
        draw_icon(p, self.icon, QRectF(r.left() + 12, cy - 12, 24, 24), QColor(255, 255, 255, int(200 + 55 * self._h)))
        p.setPen(theme.col("text"))
        p.setFont(theme.font(11, QFont.Normal))
        if self.sub:
            p.drawText(QRectF(r.left() + 48, r.top() + 4, r.width() - 56, 22), Qt.AlignLeft | Qt.AlignVCenter, self.text)
            p.setPen(theme.col("sub"))
            p.setFont(theme.font(8, QFont.Normal))
            fm = p.fontMetrics()
            p.drawText(QRectF(r.left() + 48, r.top() + 26, r.width() - 56, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(self.sub, Qt.ElideMiddle, int(r.width() - 60)))
        else:
            p.drawText(QRectF(r.left() + 48, r.top(), r.width() - 56, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       self.text)


class Thumb(HoverMixin, QWidget):
    """A recent clip as a small picture with its name underneath. style: 'dock' (Aero) or 'strip' (Retro).
    Hovering zooms the picture in (it stays inside the widget)."""
    opened = Signal(str)
    CAP = 22

    def __init__(self, entry, w, h, style, parent=None):
        super().__init__(parent)
        self._init_hover()
        self.e, self.path, self.style = entry, entry["path"], style
        self.setFixedSize(w, h + self.CAP)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(self.path)
        self.pm = None
        tp = projects.ProjectStore.thumb_path_for(entry)
        if tp and os.path.isfile(tp):
            pm = QPixmap(tp)
            self.pm = pm if not pm.isNull() else None
        theme.changed.connect(self.update)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.opened.emit(self.path)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        area = QRectF(0, 0, self.width(), self.height() - self.CAP)
        m = (7 if self.style == "dock" else 10) * (1 - self._h) + 1
        pr = area.adjusted(m, m, -m, -m)
        path = QPainterPath()
        if self.style == "dock":
            path.addRoundedRect(pr, 12, 12)
        else:
            path = retro.cut_path(pr, 7)
        p.save()
        p.setClipPath(path)
        if self.pm is not None:
            s = max(pr.width() / self.pm.width(), pr.height() / self.pm.height())
            w, h = self.pm.width() * s, self.pm.height() * s
            p.drawPixmap(QRectF(pr.center().x() - w / 2, pr.center().y() - h / 2, w, h), self.pm, QRectF(self.pm.rect()))
        else:
            p.fillRect(pr, QColor(0, 20, 50, 110))
        if self.style == "dock":   # glass reflection
            g = QLinearGradient(pr.topLeft(), pr.bottomLeft())
            g.setColorAt(0, QColor(255, 255, 255, 90))
            g.setColorAt(0.5, QColor(255, 255, 255, 10))
            g.setColorAt(0.52, QColor(255, 255, 255, 0))
            p.fillRect(pr, QBrush(g))
        p.restore()
        p.setBrush(Qt.NoBrush)
        if self.style == "dock":
            p.setPen(QPen(QColor(255, 255, 255, int(200 + 55 * self._h)), 1.6))
        else:
            p.setPen(QPen(QColor(255, 255, 255, int(120 + 135 * self._h)), 1.0 + self._h))
        p.drawPath(path)
        name = os.path.splitext(os.path.basename(self.path.rstrip("/\\")))[0] or self.path
        if self.style != "dock":
            name = name.upper()
        p.setPen(theme.col("text") if self._h > 0.3 else theme.col("sub"))
        f = theme.font(8, QFont.Normal)
        if self.style != "dock":
            f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        p.setFont(f)
        p.drawText(QRectF(2, self.height() - self.CAP + 2, self.width() - 4, self.CAP - 2), Qt.AlignHCenter | Qt.AlignTop,
                   p.fontMetrics().elidedText(name, Qt.ElideMiddle, self.width() - 6))
