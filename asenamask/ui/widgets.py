"""Custom-painted widgets: buttons, cards, toggle, progress bar, toast, overlay."""
import math

from PySide6.QtCore import (Qt, QRectF, QPointF, QVariantAnimation, QEasingCurve, QTimer, Signal,
                            QPropertyAnimation, QSize)
from PySide6.QtGui import (QPainter, QColor, QLinearGradient, QPen, QBrush, QFont, QPainterPath, QPixmap)
from PySide6.QtWidgets import (QWidget, QPushButton, QFrame, QLabel, QVBoxLayout, QGraphicsOpacityEffect,
                               QSizePolicy)

from . import glass, retro
from .theme import theme, mix, ACCENTS
from .. import sound


def make_anim(owner, setter, duration=180):
    a = QVariantAnimation(owner)
    a.setDuration(duration)
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.valueChanged.connect(setter)
    return a


class HoverMixin:
    """Adds an animated 0..1 'hover' value."""

    def _init_hover(self):
        self._h = 0.0
        self._hanim = make_anim(self, self._set_h)

    def _set_h(self, v):
        self._h = float(v)
        self.update()

    def _go(self, target):
        self._hanim.stop()
        self._hanim.setStartValue(self._h)
        self._hanim.setEndValue(target)
        self._hanim.start()

    def enterEvent(self, e):
        self._go(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._go(0.0)
        super().leaveEvent(e)


class GlowButton(HoverMixin, QPushButton):
    """kind: 'primary' (purple gradient + glow), 'ghost' (outlined), 'chip' (small)."""

    def __init__(self, text="", kind="primary", parent=None):
        super().__init__(text, parent)
        self.kind = kind
        self._init_hover()
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        theme.changed.connect(self.update)
        self.clicked.connect(lambda: sound.play("small" if kind == "chip" else "button"))
        f = QFont("Segoe UI", 10 if kind == "chip" else 11)
        f.setWeight(QFont.DemiBold if kind != "chip" else QFont.Medium)
        self.setFont(f)
        self._flash = 1.0
        self._flash_anim = make_anim(self, self._set_flash, 460)
        self._flash_anim.setStartValue(0.0)
        self._flash_anim.setEndValue(1.0)
        self.pressed.connect(self._start_flash)
        self.breathe = False
        self._bphase = 0.0
        self._btimer = QTimer(self)
        self._btimer.setInterval(45)
        self._btimer.timeout.connect(self._btick)
        if kind == "primary":
            self.setMinimumHeight(56)
        elif kind == "ghost":
            self.setMinimumHeight(42)
        else:
            self.setMinimumHeight(30)

    def _set_flash(self, v):
        self._flash = float(v)
        self.update()

    def _start_flash(self):
        if theme.look == "retro":
            self._flash_anim.stop()
            self._flash_anim.start()

    def set_breathing(self, on):
        self.breathe = on
        if on:
            self._btimer.start()
        else:
            self._btimer.stop()
            self.update()

    def _btick(self):
        if self.isVisible() and self.isEnabled():
            self._bphase = (self._bphase + 0.025) % 1.0
            self.update()

    def sizeHint(self):
        w = self.fontMetrics().horizontalAdvance(self.text())
        pad = {"primary": 56, "ghost": 40, "chip": 24}[self.kind]
        return QSize(w + pad + (16 if self.kind == "primary" else 0), self.minimumHeight())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()
        m = 10 if self.kind == "primary" else 5
        r = QRectF(self.rect()).adjusted(m, m, -m, -m)
        r.translate(0, -1.5 * self._h)
        if self.isDown():
            r.translate(0, 1.5)
        pop = 1.0 + (0.075 if theme.look == "retro" else 0.035) * self._h - (0.04 if self.isDown() else 0.0)
        c0 = r.center()
        r = QRectF(c0.x() - r.width() * pop / 2, c0.y() - r.height() * pop / 2, r.width() * pop, r.height() * pop)
        r = r.intersected(QRectF(self.rect()).adjusted(2.5, 2.5, -2.5, -2.5))   # never draw past the widget edge
        look = theme.look
        rad = r.height() / 2 if (self.kind == "chip" or theme.param("pill")) else 12 * theme.param("radius")
        acc, acc2 = theme.col("accent"), theme.col("accent2")
        p.setOpacity(1.0 if enabled else 0.4)
        text_col = theme.col("text")
        if theme.look == "retro":
            col = retro.button(p, r, "primary" if self.kind == "primary" else "chip", self._h,
                               self.isDown())
            if self.isCheckable() and self.isChecked() and self.kind == "chip":
                p.setPen(QPen(QColor(255, 255, 255), 2.0))
                p.setBrush(Qt.NoBrush)
                p.drawPath(retro.tip_path(r, min(r.height() * 0.34, 13.0)))
            if self._flash < 1.0:   # a bright band sweeps across the button when it is pressed
                p.save()
                p.setClipPath(retro.tip_path(r, min(r.height() * 0.34, 13.0)))
                x = r.left() - 40 + (r.width() + 80) * self._flash
                gl = QLinearGradient(x - 30, 0, x + 30, 0)
                gl.setColorAt(0, QColor(255, 255, 255, 0))
                gl.setColorAt(0.5, QColor(255, 255, 255, int(210 * (1 - self._flash))))
                gl.setColorAt(1, QColor(255, 255, 255, 0))
                p.fillRect(r, QBrush(gl))
                p.restore()
            p.setFont(self.font())
            p.setPen(col)
            p.drawText(r, Qt.AlignCenter, self.text())
            return
        if theme.glass:
            if self.kind == "primary":
                if enabled and self._h > 0.01:
                    for i in range(6):
                        p.setPen(Qt.NoPen)
                        p.setBrush(QColor(acc2.red(), acc2.green(), acc2.blue(), int(30 * self._h * (1 - i / 6.0))))
                        p.drawRoundedRect(r.adjusted(-i * 1.3, -i * 1.3, i * 1.3, i * 1.3), rad + i, rad + i)
                glass.button(p, r, rad, acc, self._h, self.isDown())
            else:
                active = self.isCheckable() and self.isChecked()
                glass.chip(p, r, rad, self._h, acc if active else None, self.isDown())
            p.setFont(self.font())
            p.setPen(QColor(0, 40, 80, 90))
            p.drawText(r.translated(0, 1), Qt.AlignCenter, self.text())
            p.setPen(QColor(255, 255, 255))
            p.drawText(r, Qt.AlignCenter, self.text())
            return
        if self.kind == "primary":
            if enabled:
                pulse = (0.5 - 0.5 * math.cos(self._bphase * 6.2832)) * 0.45 if self.breathe else 0.0
                n = 4 if look == "xmb" else 7
                for i in range(n):
                    a = int(34 * max(self._h, pulse) * (1 - i / float(n)))
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), a))
                    p.drawRoundedRect(r.adjusted(-i * 1.1, -i * 1.1, i * 1.1, i * 1.1), rad + i, rad + i)
            if look == "xmb":
                p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), int(46 + 50 * self._h)))
                p.setPen(QPen(acc, 1.2))
                p.drawRoundedRect(r, rad, rad)
                text_col = QColor(255, 255, 255)
            else:
                g = QLinearGradient(r.topLeft(), r.bottomLeft() if look == "aero" else r.topRight())
                g.setColorAt(0, mix(acc, QColor(255, 255, 255), 0.12 * self._h + (0.25 if look == "aero" else 0.0)))
                g.setColorAt(1, mix(acc2 if look != "aero" else acc, QColor(255, 255, 255), 0.12 * self._h))
                if look == "aero":
                    g.setColorAt(0.5, mix(acc, QColor(0, 0, 0), 0.08))
                    g.setColorAt(1, mix(acc2, QColor(255, 255, 255), 0.1 * self._h))
                p.setPen(QPen(QColor(255, 255, 255, 190), 1.3) if look == "aero" else Qt.NoPen)
                p.setBrush(QBrush(g))
                p.drawRoundedRect(r, rad, rad)
                if look == "aero":
                    self._gloss(p, r, rad)
                text_col = QColor(255, 255, 255)
        else:
            active = self.isCheckable() and self.isChecked()
            if look == "aero":
                base = QColor(255, 255, 255, int(95 + 70 * self._h))
                if active:
                    base = QColor(acc.red(), acc.green(), acc.blue(), 150)
                p.setBrush(base)
                p.setPen(QPen(QColor(255, 255, 255, 230) if not active else acc, 1.3))
                p.drawRoundedRect(r, rad, rad)
                self._gloss(p, r, rad, 0.7)
            else:
                if active:
                    bg = QColor(acc.red(), acc.green(), acc.blue(), 70)
                    border = acc
                else:
                    bg = mix(QColor(0, 0, 0, 0), theme.col("hover"), self._h)
                    border = mix(theme.col("card_border"), acc, self._h)
                p.setBrush(bg)
                p.setPen(QPen(border, 1.2))
                p.drawRoundedRect(r, rad, rad)
        p.setPen(text_col)
        p.setFont(self.font())
        p.drawText(r, Qt.AlignCenter, self.text())

    @staticmethod
    def _gloss(p, r, rad, k=1.0):
        """The glassy highlight on the upper half of a button (Frutiger Aero)."""
        top = QRectF(r.left() + 2, r.top() + 1.5, r.width() - 4, r.height() * 0.5)
        g = QLinearGradient(top.topLeft(), top.bottomLeft())
        g.setColorAt(0, QColor(255, 255, 255, int(150 * k)))
        g.setColorAt(1, QColor(255, 255, 255, int(30 * k)))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(top, max(2.0, rad - 2), max(2.0, rad - 2))


class IconButton(HoverMixin, QPushButton):
    """Title-bar button: kind in min / max / restore / close / menu."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._init_hover()
        self.setFixedSize(46, 34)
        self.clicked.connect(lambda: sound.play("small"))
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        theme.changed.connect(self.update)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.kind == "close":
            hov = mix(QColor(0, 0, 0, 0), theme.col("danger"), self._h)
        else:
            hov = mix(QColor(0, 0, 0, 0), theme.col("hover"), self._h)
        p.setPen(Qt.NoPen)
        p.setBrush(hov)
        p.drawRoundedRect(r, 8, 8)
        col = QColor(255, 255, 255) if (self.kind == "close" and self._h > 0.5) else theme.col("text")
        pen = QPen(col, 1.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        c = self.rect().center()
        cx, cy = c.x() + 0.5, c.y() + 0.5
        k = self.kind
        if k == "min":
            p.drawLine(QPointF(cx - 5, cy + 3), QPointF(cx + 5, cy + 3))
        elif k == "max":
            p.drawRoundedRect(QRectF(cx - 5, cy - 5, 10, 10), 2, 2)
        elif k == "restore":
            p.drawRoundedRect(QRectF(cx - 5, cy - 2, 7.5, 7.5), 1.5, 1.5)
            p.drawLine(QPointF(cx - 2, cy - 5), QPointF(cx + 5, cy - 5))
            p.drawLine(QPointF(cx + 5, cy - 5), QPointF(cx + 5, cy + 3))
        elif k == "close":
            p.drawLine(QPointF(cx - 5, cy - 5), QPointF(cx + 5, cy + 5))
            p.drawLine(QPointF(cx + 5, cy - 5), QPointF(cx - 5, cy + 5))
        elif k == "menu":
            for dy in (-5, 0, 5):
                p.drawLine(QPointF(cx - 7, cy + dy), QPointF(cx + 7, cy + dy))


class Card(QFrame):
    def __init__(self, parent=None, radius=18, solid=False):
        super().__init__(parent)
        self.radius = radius
        self.solid = solid
        theme.changed.connect(self.update)
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = max(3.0, self.radius * theme.param("radius"))
        look = theme.look
        if theme.glass:
            dpr = self.devicePixelRatioF()
            key = (self.width(), self.height(), round(rad, 1), self.solid, dpr)
            if getattr(self, "_gkey", None) != key:   # glass is costly to draw, so keep the finished pane as a picture
                pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
                pm.setDevicePixelRatio(dpr)
                pm.fill(Qt.transparent)
                q = QPainter(pm)
                q.setRenderHint(QPainter.Antialiasing)
                glass.panel(q, r, rad, strong=self.solid)
                q.end()
                self._gkey, self._gpm = key, pm
            p.drawPixmap(0, 0, self._gpm)
            return
        if look == "retro":
            retro.panel(p, r, self.solid)
            return
        if look == "xmb":
            p.setBrush(theme.col("panel") if self.solid else theme.col("card"))
            p.setPen(QPen(theme.col("card_border"), 1))
            p.drawRoundedRect(r, rad, rad)
            hl = QLinearGradient(r.left(), r.top() + 0.5, r.right(), r.top() + 0.5)
            hl.setColorAt(0, QColor(255, 255, 255, 0))
            hl.setColorAt(0.5, QColor(255, 255, 255, 70))
            hl.setColorAt(1, QColor(255, 255, 255, 0))
            p.setPen(QPen(QBrush(hl), 1))
            p.drawLine(QPointF(r.left() + rad, r.top() + 0.5), QPointF(r.right() - rad, r.top() + 0.5))
            return
        p.setBrush(theme.col("panel") if self.solid else theme.col("card"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(r, rad, rad)
        # soft accent tint so cards match the gradient look instead of flat gray
        a1, a2 = theme.col("accent"), theme.col("accent2")
        k = 1.0 if self.solid else 1.4
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor(a1.red(), a1.green(), a1.blue(), int(30 * k)))
        g.setColorAt(1, QColor(a2.red(), a2.green(), a2.blue(), int(16 * k)))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(r, rad, rad)
        hl = QLinearGradient(r.left() + rad, r.top() + 0.5, r.right() - rad, r.top() + 0.5)
        hl.setColorAt(0, QColor(255, 255, 255, 0))
        hl.setColorAt(0.5, QColor(255, 255, 255, 46 if theme.name == "dark" else 120))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(QPen(QBrush(hl), 1))
        p.drawLine(QPointF(r.left() + rad, r.top() + 0.5), QPointF(r.right() - rad, r.top() + 0.5))
        bc = mix(theme.col("card_border"), a1, 0.35)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(bc, 1))
        p.drawRoundedRect(r, rad, rad)


class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._on = checked
        self._t = 1.0 if checked else 0.0
        self._anim = make_anim(self, self._set_t, 200)
        self.setFixedSize(46, 26)
        self.setCursor(Qt.PointingHandCursor)
        theme.changed.connect(self.update)

    def isChecked(self):
        return self._on

    def setChecked(self, v, animate=False):
        self._on = bool(v)
        self._t = 1.0 if v else 0.0
        self.update()

    def _set_t(self, v):
        self._t = float(v)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._on = not self._on
            self._anim.stop()
            self._anim.setStartValue(self._t)
            self._anim.setEndValue(1.0 if self._on else 0.0)
            self._anim.start()
            self.toggled.emit(self._on)
            sound.play("small")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        off = theme.col("input_border")
        if theme.glass:
            tr = QLinearGradient(r.topLeft(), r.bottomLeft())
            on_c = theme.col("accent2") if self._t > 0.5 else QColor(0, 40, 90)
            tr.setColorAt(0, mix(QColor(0, 40, 90, 120), theme.col("accent"), self._t))
            tr.setColorAt(1, mix(QColor(120, 190, 235, 150), theme.col("accent2"), self._t))
            p.setPen(QPen(QColor(255, 255, 255, 230), 1.3))
            p.setBrush(QBrush(tr))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            d = r.height() - 2
            x = r.left() + 1 + (r.width() - d - 2) * self._t
            glass.orb(p, QPointF(x + d / 2, r.center().y()), d, QColor(235, 245, 255), QColor(255, 255, 255))
            return
        p.setPen(Qt.NoPen)
        p.setBrush(mix(off, theme.col("accent"), self._t))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * self._t
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class ProgressStrip(QWidget):
    """Full-width loading bar. value 0..1, or busy (sliding shimmer)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(theme.param("bar_h"))
        theme.changed.connect(lambda: self.setFixedHeight(theme.param("bar_h")))
        self._v = 0.0
        self._shown = 0.0
        self._busy = False
        self._phase = 0.0
        self._anim = make_anim(self, self._set_shown, 350)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        theme.changed.connect(self.update)

    def _set_shown(self, v):
        self._shown = float(v)
        self.update()

    def set_value(self, v):
        self._v = max(0.0, min(1.0, v))
        self._anim.stop()
        self._anim.setStartValue(self._shown)
        self._anim.setEndValue(self._v)
        self._anim.start()

    def reset(self):
        self._anim.stop()
        self._v = self._shown = 0.0
        self.update()

    def set_busy(self, busy):
        self._busy = busy
        if busy:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 2, 0, -2)
        rad = r.height() / 2 if theme.glass else {"retro": 1.5}.get(theme.look, 5.0)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.col("input"))
        p.drawRoundedRect(r, rad, rad)
        if theme.glass:
            p.setBrush(QColor(0, 30, 70, 90))
            p.drawRoundedRect(r, rad, rad)
            p.setPen(QPen(QColor(255, 255, 255, 230), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, rad, rad)
            p.setPen(Qt.NoPen)
        acc, acc2 = theme.col("accent"), theme.col("accent2")
        if self._shown > 0.001:
            fr = QRectF(r.left(), r.top(), max(10.0, r.width() * self._shown), r.height())
            for k in range(4):   # soft glow under the filled part
                p.setBrush(QColor(acc2.red(), acc2.green(), acc2.blue(), 26 - k * 6))
                p.drawRoundedRect(fr.adjusted(-k, -k, k, k), rad + k, rad + k)
            g = QLinearGradient(fr.topLeft(), fr.topRight())
            g.setColorAt(0, acc)
            g.setColorAt(1, acc2)
            p.setBrush(QBrush(g))
            p.drawRoundedRect(fr, rad, rad)
            if theme.glass:
                gl = QLinearGradient(fr.topLeft(), fr.bottomLeft())
                gl.setColorAt(0, QColor(255, 255, 255, 150))
                gl.setColorAt(0.55, QColor(255, 255, 255, 20))
                gl.setColorAt(1, QColor(255, 255, 255, 0))
                p.setBrush(QBrush(gl))
                p.drawRoundedRect(fr.adjusted(1, 1, -1, -fr.height() * 0.4), rad, rad)
            if self._busy:  # moving highlight
                p.save()
                path = QPainterPath()
                path.addRoundedRect(fr, rad, rad)
                p.setClipPath(path)
                x = fr.left() - 120 + (fr.width() + 240) * self._phase
                sg = QLinearGradient(x, 0, x + 120, 0)
                sg.setColorAt(0, QColor(255, 255, 255, 0))
                sg.setColorAt(0.5, QColor(255, 255, 255, 90))
                sg.setColorAt(1, QColor(255, 255, 255, 0))
                p.setBrush(QBrush(sg))
                p.drawRect(fr)
                p.restore()
        elif self._busy:  # nothing measurable yet: sliding pill
            w = r.width() * 0.25
            x = r.left() + (r.width() + w) * self._phase - w
            g = QLinearGradient(x, 0, x + w, 0)
            g.setColorAt(0, QColor(acc.red(), acc.green(), acc.blue(), 0))
            g.setColorAt(0.5, acc2)
            g.setColorAt(1, QColor(acc.red(), acc.green(), acc.blue(), 0))
            p.setBrush(QBrush(g))
            p.drawRect(QRectF(x, r.top(), w, r.height()))


class Toast(QWidget):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self._text = ""
        self._kind = "info"
        self.hide()
        self._eff = QGraphicsOpacityEffect(self)
        self._eff.setOpacity(0)
        self.setGraphicsEffect(self._eff)
        self._fade = QPropertyAnimation(self._eff, b"opacity", self)
        self._fade.setDuration(250)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._hide)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def show_message(self, text, kind="info", ms=3500):
        self._text, self._kind = text, kind
        f = QFont("Segoe UI", 10)
        fm_w = self.fontMetrics().horizontalAdvance(text)
        w = min(max(260, fm_w + 56), max(300, self.host.width() - 60))
        self.resize(w, 46)
        self.move((self.host.width() - w) // 2, self.host.height() - 100)
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(self._eff.opacity())
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(ms)
        self.update()

    def _hide(self):
        self._fade.stop()
        self._fade.setStartValue(self._eff.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        col = {"ok": theme.col("ok"), "error": theme.col("danger")}.get(self._kind, theme.col("accent"))
        p.setBrush(theme.col("panel"))
        p.setPen(QPen(col, 1.5))
        p.drawRoundedRect(r, 14 * theme.param("radius"), 14 * theme.param("radius"))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(r.left() + 20, r.center().y()), 4.5, 4.5)
        p.setPen(theme.col("text"))
        p.drawText(r.adjusted(36, 0, -14, 0), Qt.AlignVCenter | Qt.AlignLeft, self._text)


def blurred_pixmap(widget, factor=10):
    pm = widget.grab()
    img = pm.toImage()
    w, h = max(1, img.width()), max(1, img.height())
    small = img.scaled(max(1, w // factor), max(1, h // factor), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    tiny = small.scaled(max(1, w // (factor * 2)), max(1, h // (factor * 2)), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return QPixmap.fromImage(tiny.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))


class Overlay(QWidget):
    """Full-window overlay: blurred + dimmed backdrop and a centered panel."""
    closed = Signal()

    def __init__(self, host, source, frac=(0.86, 0.86), max_size=(1100, 760), closable=True):
        super().__init__(host)
        self.host, self.source = host, source
        self.frac, self.max_size, self.closable = frac, max_size, closable
        self._bg = None
        self.panel = Card(self, radius=22, solid=True)
        self.panel_layout = QVBoxLayout(self.panel)
        self.panel_layout.setContentsMargins(26, 22, 26, 22)
        self.panel_layout.setSpacing(14)
        self._eff = QGraphicsOpacityEffect(self)
        self._eff.setOpacity(0)
        self.setGraphicsEffect(self._eff)
        self._fade = QPropertyAnimation(self._eff, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.finished.connect(self._after_fade)
        self._pop = QPropertyAnimation(self.panel, b"geometry", self)
        self._pop.setDuration(300)
        self._pop.setEasingCurve(QEasingCurve.OutBack)
        self._closing = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()

    def open_overlay(self):
        self._bg = blurred_pixmap(self.source)
        self._closing = False
        self.setGeometry(self.host.rect())
        self._place_panel()
        self.show()
        self.raise_()
        self.setFocus()
        self._fade.stop()
        self._fade.setStartValue(self._eff.opacity())
        self._fade.setEndValue(1.0)
        self._fade.start()
        g = self.panel.geometry()
        self._pop.stop()
        self._pop.setStartValue(g.adjusted(int(g.width() * 0.03), int(g.height() * 0.03),
                                           -int(g.width() * 0.03), -int(g.height() * 0.03)))
        self._pop.setEndValue(g)
        self._pop.start()
        self.on_open()

    def on_open(self):
        pass

    def close_overlay(self):
        if not self.isVisible() or self._closing:
            return
        self._closing = True
        self.on_close()
        self._fade.stop()
        self._fade.setStartValue(self._eff.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def on_close(self):
        pass

    def _after_fade(self):
        if self._closing:
            self.hide()
            self._closing = False
            self.closed.emit()

    def _place_panel(self):
        w = min(int(self.width() * self.frac[0]), self.max_size[0])
        h = min(int(self.height() * self.frac[1]), self.max_size[1])
        self.panel.setGeometry((self.width() - w) // 2, (self.height() - h) // 2, w, h)

    def resizeEvent(self, e):
        self._place_panel()
        super().resizeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rad = 0 if self.host.isMaximized() else 16
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), rad, rad)
        p.setClipPath(clip)
        if self._bg is not None:
            p.drawPixmap(self.rect(), self._bg)
        p.fillRect(self.rect(), theme.col("dim"))

    def mousePressEvent(self, e):
        if self.closable and not self.panel.geometry().contains(e.position().toPoint()):
            self.close_overlay()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.closable:
            self.close_overlay()
        else:
            super().keyPressEvent(e)


def title_label(text, size=16, weight=QFont.DemiBold, sub=False):
    l = QLabel(text)
    l.setFont(theme.font(size, weight))
    l.setProperty("fsize", size)
    l.setProperty("fweight", int(getattr(weight, "value", weight)))
    l.setStyleSheet("color: %s; background: transparent;" % theme.css("sub" if sub else "text"))
    l.setProperty("sub", sub)
    return l


def restyle_labels(root):
    """Re-apply label colors after a theme change."""
    from PySide6.QtWidgets import QLabel as _L
    for l in root.findChildren(_L):
        if l.property("fsize") is not None:
            ls = l.font().letterSpacing()
            f = theme.font(l.property("fsize"), QFont.Weight(l.property("fweight")))
            f.setLetterSpacing(QFont.AbsoluteSpacing, ls)
            l.setFont(f)
        if l.property("sub") is not None:
            l.setStyleSheet("color: %s; background: transparent;" % theme.css("sub" if l.property("sub") else "text"))


class SwatchRow(QWidget):
    """Round gradient swatches; hover pops one up and shows its name below."""
    chosen = Signal(str)

    def __init__(self, current="Violet", parent=None):
        super().__init__(parent)
        self.names = list(ACCENTS.keys())
        self.current = current
        self.hv = [0.0] * len(self.names)
        self.anims = []
        for i in range(len(self.names)):
            a = QVariantAnimation(self)
            a.setDuration(220)
            a.setEasingCurve(QEasingCurve.OutBack)
            a.valueChanged.connect(lambda v, i=i: self._set(i, v))
            self.anims.append(a)
        self.hover_i = -1
        self.setMouseTracking(True)
        self.setFixedHeight(92)
        self.setMinimumWidth(len(self.names) * 52)
        self.setCursor(Qt.PointingHandCursor)
        theme.changed.connect(self.update)

    def set_current(self, name):
        self.current = name
        self.update()

    def _set(self, i, v):
        self.hv[i] = float(v)
        self.update()

    def _slot(self):
        return self.width() / float(len(self.names))

    def _index_at(self, x, y):
        if y > 70:
            return -1
        i = int(x // self._slot())
        return i if 0 <= i < len(self.names) else -1

    def _animate(self, i, target):
        a = self.anims[i]
        a.stop()
        a.setStartValue(self.hv[i])
        a.setEndValue(target)
        a.start()

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position().x(), e.position().y())
        if i != self.hover_i:
            if self.hover_i >= 0:
                self._animate(self.hover_i, 0.0)
            if i >= 0:
                self._animate(i, 1.0)
            self.hover_i = i

    def leaveEvent(self, e):
        if self.hover_i >= 0:
            self._animate(self.hover_i, 0.0)
        self.hover_i = -1

    def mousePressEvent(self, e):
        i = self._index_at(e.position().x(), e.position().y())
        if i >= 0 and e.button() == Qt.LeftButton:
            self.current = self.names[i]
            sound.play("small")
            self.chosen.emit(self.current)
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        slot = self._slot()
        for i, name in enumerate(self.names):
            (r1, g1, b1), (r2, g2, b2) = ACCENTS[name]
            h = max(0.0, self.hv[i])
            cx = slot * i + slot / 2
            cy = 34 - 9 * h
            rad = 17 + 4 * h
            if h > 0.02:   # soft glow
                for k in range(5):
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(r1, g1, b1, int(40 * h * (1 - k / 5.0))))
                    p.drawEllipse(QPointF(cx, cy), rad + k * 2.2, rad + k * 2.2)
            g = QLinearGradient(cx - rad, cy - rad, cx + rad, cy + rad)
            g.setColorAt(0, QColor(r1, g1, b1))
            g.setColorAt(1, QColor(r2, g2, b2))
            p.setBrush(QBrush(g))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), rad, rad)
            if name == self.current:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(theme.col("text"), 2))
                p.drawEllipse(QPointF(cx, cy), rad + 4, rad + 4)
            if h > 0.02:   # name label fades in below
                col = theme.col("text")
                col.setAlpha(int(255 * min(1.0, h)))
                p.setPen(col)
                f = QFont("Segoe UI", 9)
                f.setWeight(QFont.DemiBold)
                p.setFont(f)
                p.drawText(QRectF(cx - slot / 2, 62, slot, 20), Qt.AlignCenter, name)
