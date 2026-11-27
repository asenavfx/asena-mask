"""First-run welcome screen, returning-user splash, and the logo widgets."""
import math
import os
import random
import time

from PySide6.QtCore import Qt, Signal, QRectF, QTimer, QVariantAnimation, QEasingCurve, QPointF
from PySide6.QtGui import (QPen, QPainter, QLinearGradient, QRadialGradient, QFont, QColor, QPixmap, QBrush, QPainterPath)
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QHBoxLayout

from .. import paths, APP_NAME, BUILD_LABEL
from . import media
from .theme import theme
from . import glass, retro
from .widgets import GlowButton, ProgressStrip, title_label, restyle_labels

TIPS = [
    "Draw a box around a character to keep only them when several people are on screen.",
    "ProRes 4444 (.mov) keeps transparency and opens straight in After Effects.",
    "Lower the threshold if parts of your character are missing. Raise it if extras sneak in.",
    "Add :2 after a word in the prompt, like hands:2, to allow two of them.",
    "Higher refine iterations give cleaner edges, but take longer.",
    "Every clip is processed on your own GPU. Nothing is uploaded anywhere.",
    "Use the Green background in the preview to spot leftover edges.",
    "Out of GPU memory? Lower the GPU memory use in Settings.",
    "Frame rate set to Same as source keeps your clip's original timing.",
    "You can change the accent colour any time in Settings.",
]


def draw_cube_badge(p, r):
    """Retro logo: one glass cube turning slowly in the middle of a thin ring. It never leaves the ring."""
    d = min(r.width(), r.height())
    c = r.center()
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 190), max(1.2, d * 0.012)))
    p.drawEllipse(c, d / 2, d / 2)
    p.setPen(QPen(QColor(255, 255, 255, 55), 1.0))
    p.drawEllipse(c, d / 2 * 0.86, d / 2 * 0.86)
    t = time.monotonic()
    size = d / 2 * 0.62 / 1.732          # the cube's furthest corner stays inside the ring
    retro.draw_cube(p, c.x(), c.y(), size, t * 0.7, 0.62, 255)


class CubeLogo(QWidget):
    """The Retro logo as a small widget of its own (used on the Home page)."""

    def __init__(self, size=96, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.update)

    def showEvent(self, e):
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        draw_cube_badge(p, QRectF(self.rect()).adjusted(2, 2, -2, -2))


class LogoMark(QWidget):
    """Static logo (asenamask/assets/logo.png), with a drawn fallback."""

    def __init__(self, size=120, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        f = paths.asset("logo.png")
        self.img = QPixmap(f) if os.path.isfile(f) else None
        ef = paths.asset("logo_aero.png")
        self.emoji = QPixmap(ef) if os.path.isfile(ef) else None
        theme.changed.connect(self.update)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if theme.glass:
            d = min(self.width(), self.height()) - 4
            r = QRectF(self.rect()).center()
            r = QRectF(r.x() - d / 2, r.y() - d / 2, d, d)
            if self.emoji is not None and not self.emoji.isNull():
                p.drawPixmap(r, self.emoji, QRectF(self.emoji.rect()))
                hi = QRectF(r.left() + d * 0.12, r.top() + d * 0.04, d * 0.76, d * 0.42)
                hg = QLinearGradient(hi.topLeft(), hi.bottomLeft())
                hg.setColorAt(0, QColor(255, 255, 255, 110))
                hg.setColorAt(1, QColor(255, 255, 255, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(hg))
                p.drawEllipse(hi)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 235), max(1.5, d * 0.035)))
                p.drawEllipse(r)
            return
        if theme.look == "retro":
            draw_cube_badge(p, QRectF(self.rect()).adjusted(2, 2, -2, -2))
            return
        if self.img is not None and not self.img.isNull():
            p.drawPixmap(QRectF(self.rect()), self.img, QRectF(self.img.rect()))
            return
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, theme.col("accent"))
        g.setColorAt(1, theme.col("accent2"))
        p.setBrush(QBrush(g))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(r, r.width() * 0.25, r.width() * 0.25)


class AnimatedLogo(QWidget):
    """Looping logo animation (black background blended away)."""

    def __init__(self, w=340, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, int(w * 0.75))
        self.loop = media.logo_anim()
        self.loop.frame.connect(self.update)
        self.static = LogoMark(10).img
        ef = paths.asset("logo_aero.png")
        self.emoji = QPixmap(ef) if os.path.isfile(ef) else None
        if theme.param("logo_anim"):
            self.loop.load()
        theme.changed.connect(self._look_changed)
        self.spin = QTimer(self)
        self.spin.setInterval(33)
        self.spin.timeout.connect(self.update)

    def _look_changed(self):
        if theme.param("logo_anim") and self.isVisible():
            self.loop.load()
            self.loop.start()
        else:
            self.loop.stop()
        if theme.look == "retro" and self.isVisible():
            self.spin.start()
        else:
            self.spin.stop()
        self.update()

    def showEvent(self, e):
        if theme.param("logo_anim"):
            self.loop.load()
            self.loop.start()
        if theme.look == "retro":
            self.spin.start()
        super().showEvent(e)

    def _paint_orb(self, p):
        """Static logo for the Aero / Pocket Console looks: a glossy glass orb or a thin ring badge."""
        d = min(self.width(), self.height()) * 0.86
        r = QRectF((self.width() - d) / 2, (self.height() - d) / 2, d, d)
        a1, a2 = theme.col("accent"), theme.col("accent2")
        if theme.glass and self.emoji is not None and not self.emoji.isNull():
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            for k in range(6):   # soft blue halo
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(a2.red(), a2.green(), a2.blue(), 26 - k * 4))
                p.drawEllipse(r.adjusted(-k * 3, -k * 3, k * 3, k * 3))
            p.drawPixmap(r, self.emoji, QRectF(self.emoji.rect()))
            hi = QRectF(r.left() + d * 0.12, r.top() + d * 0.04, d * 0.76, d * 0.42)
            hg = QLinearGradient(hi.topLeft(), hi.bottomLeft())
            hg.setColorAt(0, QColor(255, 255, 255, 110))
            hg.setColorAt(1, QColor(255, 255, 255, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(hg))
            p.drawEllipse(hi)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 235), 3))
            p.drawEllipse(r)
            return
        if theme.look == "retro":
            draw_cube_badge(p, r)
            return
        if theme.glass:
            glass.orb(p, r.center(), d, a1, a2)
        else:
            for k, a in ((0, 150), (1, 70), (2, 30)):
                pr = r.adjusted(k * d * 0.06, k * d * 0.06, -k * d * 0.06, -k * d * 0.06)
                p.setPen(QPen(QColor(a1.red(), a1.green(), a1.blue(), a), 1.4))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(pr)
        if self.static is not None and not self.static.isNull():
            s = d * (0.74 if theme.glass else 0.62)
            p.save()
            if theme.glass or theme.look == "retro":   # screen blend: the black background disappears
                p.setCompositionMode(QPainter.CompositionMode_Screen)
            p.drawPixmap(QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s), self.static,
                         QRectF(self.static.rect()))
            p.restore()

    def hideEvent(self, e):
        self.loop.stop()
        self.spin.stop()
        super().hideEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        if not theme.param("logo_anim"):
            self._paint_orb(p)
            return
        img = self.loop.current()
        if img is not None:
            r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            clip = QPainterPath()
            rad = self.width() * 0.09
            clip.addRoundedRect(r, rad, rad)
            p.setClipPath(clip)
            p.drawImage(r, img)
            p.setClipping(False)
            p.setPen(QPen(QColor(255, 255, 255, 40), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, rad, rad)
        elif self.static is not None:
            s = min(self.width(), self.height()) * 0.8
            p.setOpacity(0.7)
            p.drawPixmap(QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s), self.static,
                         QRectF(self.static.rect()))


def scrim(p, rect, strength=170):
    """Soft dark glow behind centered content so text stays readable over the animated background."""
    c = rect.center()
    sr, sg, sb = theme.param("scrim")
    g = QRadialGradient(c, min(rect.width(), rect.height()) * 0.62)
    g.setColorAt(0, QColor(sr, sg, sb, strength))
    g.setColorAt(0.6, QColor(sr, sg, sb, int(strength * 0.55)))
    g.setColorAt(1, QColor(sr, sg, sb, 0))
    p.fillRect(rect, QBrush(g))


class WelcomeScreen(QWidget):
    """Shown only the first time the app is opened."""
    entered = Signal(str)

    def __init__(self, name="", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(8)
        self.logo = AnimatedLogo(320)
        lay.addWidget(self.logo, 0, Qt.AlignHCenter)
        self.title = title_label("Welcome", 34, QFont.Bold)
        self.title.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.title)
        self.sub = title_label("Remove backgrounds from your videos, right on your GPU.", 11, QFont.Normal, sub=True)
        self.sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.sub)
        lay.addSpacing(16)
        ask = title_label("What should we call you?", 11, QFont.DemiBold, sub=True)
        ask.setAlignment(Qt.AlignCenter)
        lay.addWidget(ask)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("Type your name, then press Enter")
        self.name.setMaximumWidth(330)
        self.name.setMinimumHeight(44)
        self.name.setAlignment(Qt.AlignCenter)
        self.name.returnPressed.connect(self._go)
        lay.addWidget(self.name, 0, Qt.AlignHCenter)
        lay.addSpacing(6)
        self.btn = GlowButton("Get started", "primary")
        self.btn.setFixedWidth(240)
        self.btn.clicked.connect(self._go)
        lay.addWidget(self.btn, 0, Qt.AlignHCenter)

    def paintEvent(self, e):
        p = QPainter(self)
        scrim(p, QRectF(self.rect()))
        p.end()

    def _go(self):
        self.entered.emit(self.name.text().strip())


class SplashScreen(QWidget):
    """Shown on every later launch: logo, fake loading bar (~2.4 s) and a tip."""
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(8)
        self.logo = AnimatedLogo(300)
        lay.addWidget(self.logo, 0, Qt.AlignHCenter)
        self.title = title_label(APP_NAME, 26, QFont.Bold)
        self.title.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.title)
        theme.changed.connect(self._look)
        self.ver = title_label(BUILD_LABEL, 10, QFont.Normal, sub=True)
        self.ver.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.ver)
        lay.addSpacing(18)
        self.bar = ProgressStrip()
        self.bar.setFixedWidth(380)
        lay.addWidget(self.bar, 0, Qt.AlignHCenter)
        lay.addSpacing(10)
        self.tip = title_label("", 10, QFont.Normal, sub=True)
        self.tip.setAlignment(Qt.AlignCenter)
        self.tip.setWordWrap(True)
        self.tip.setFixedWidth(460)
        lay.addWidget(self.tip, 0, Qt.AlignHCenter)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(2400)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.anim.valueChanged.connect(lambda v: self.bar._set_shown(v))
        self.anim.finished.connect(lambda: QTimer.singleShot(150, self.finished.emit))

    def start(self):
        self._tip = random.choice(TIPS)
        self._look()
        self.anim.start()

    def _look(self):
        """Title / tip wording follows the look: plain, or capitals with spacing for the console style."""
        caps = theme.param("caps")
        f = self.title.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 6 if caps else 0)
        f.setWeight(QFont.Light if caps else QFont.Bold)
        self.title.setFont(f)
        self.title.setText(APP_NAME.upper() if caps else APP_NAME)
        tip = getattr(self, "_tip", random.choice(TIPS))
        if caps:
            self.tip.setText("TIP  ·  " + tip)
        elif theme.glass:
            self.tip.setText("✦  " + tip)
        else:
            self.tip.setText("Did you know?  " + tip)
        self.bar.setFixedWidth(300 if caps else 380)
        self.bar.update()

    def paintEvent(self, e):
        p = QPainter(self)
        scrim(p, QRectF(self.rect()))
        p.end()

    def refresh_theme(self):
        restyle_labels(self)
        self._look()
