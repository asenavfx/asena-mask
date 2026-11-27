"""Painting helpers for the Frutiger Aero ("glass") looks: glossy panels, buttons and orbs."""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QLinearGradient, QRadialGradient, QPen, QBrush, QPainterPath


_REFL = {}


def _c(r, g, b, a):
    return QColor(r, g, b, int(max(0, min(255, a))))


def panel(p, r, rad, strong=False, tint=None):
    """A pane of glass: translucent body, bright curved reflection on top, soft glow at the bottom, white rim."""
    rad = max(3.0, rad)
    body = QLinearGradient(r.topLeft(), r.bottomLeft())
    k = 1.7 if strong else 1.0
    body.setColorAt(0, _c(255, 255, 255, 58 * k))
    body.setColorAt(0.45, _c(255, 255, 255, 24 * k))
    body.setColorAt(1, _c(255, 255, 255, 40 * k))
    p.setPen(Qt.NoPen)
    # a deep-blue tint under the glass keeps white text readable over a bright background
    p.setBrush(_c(4, 52, 120, 82 if not strong else 150))
    p.drawRoundedRect(r, rad, rad)
    if tint is not None:
        p.setBrush(QColor(tint.red(), tint.green(), tint.blue(), 70 if not strong else 150))
        p.drawRoundedRect(r, rad, rad)
    p.setBrush(QBrush(body))
    p.drawRoundedRect(r, rad, rad)
    # curved reflection across the upper part (an ellipse whose lower edge bows downward)
    inset = 2.5
    top = r.top() + inset
    hh = min(r.height() * 0.46, 120.0)
    key = (round(r.left(), 1), round(r.top(), 1), round(r.width()), round(r.height()), round(rad, 1))
    refl = _REFL.get(key)
    if refl is None:   # path maths is slow, so each shape is worked out once
        hl = QPainterPath()
        hl.addRoundedRect(QRectF(r.left() + inset, top, r.width() - 2 * inset, hh), max(2.0, rad - 2), max(2.0, rad - 2))
        sweep = QPainterPath()
        sweep.addEllipse(QRectF(r.left() - r.width() * 0.25, top + hh * 0.35, r.width() * 1.5, hh * 1.3))
        refl = hl.subtracted(sweep)
        if len(_REFL) > 200:
            _REFL.clear()
        _REFL[key] = refl
    rg = QLinearGradient(0, top, 0, top + hh)
    rg.setColorAt(0, _c(255, 255, 255, 120))
    rg.setColorAt(1, _c(255, 255, 255, 14))
    p.setBrush(QBrush(rg))
    p.drawPath(refl)
    # glow gathering along the bottom edge
    bg = QRadialGradient(QPointF(r.center().x(), r.bottom()), r.width() * 0.55)
    bg.setColorAt(0, _c(255, 255, 255, 52))
    bg.setColorAt(1, _c(255, 255, 255, 0))
    p.setBrush(QBrush(bg))
    p.drawRoundedRect(r, rad, rad)
    # rims: dark hairline outside the white one, like Aero window frames
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(_c(0, 30, 70, 95), 1.0))
    p.drawRoundedRect(r.adjusted(-0.5, -0.5, 0.5, 0.5), rad + 0.5, rad + 0.5)
    p.setPen(QPen(_c(255, 255, 255, 215), 1.4))
    p.drawRoundedRect(r.adjusted(0.8, 0.8, -0.8, -0.8), rad - 0.8, rad - 0.8)
    p.setPen(QPen(_c(255, 255, 255, 60), 1.0))
    p.drawRoundedRect(r.adjusted(2.4, 2.4, -2.4, -2.4), max(2.0, rad - 2.4), max(2.0, rad - 2.4))


def button(p, r, rad, base, hover=0.0, down=False, strong=True):
    """A glossy Windows 7 style button: bright upper half with a crisp horizon, deeper lower half with a glow."""
    rad = max(3.0, rad)
    lift = 0.14 * hover
    dark = base.darker(150 if down else 138)
    mid = base.darker(112 if down else 100)
    light = base.lighter(int(138 + 40 * hover))
    body = QLinearGradient(r.topLeft(), r.bottomLeft())
    body.setColorAt(0, light)
    body.setColorAt(0.48, mid)
    body.setColorAt(0.5, dark)
    body.setColorAt(1, base.lighter(int(118 + 30 * hover)))
    p.setPen(QPen(_c(0, 30, 70, 150), 1.0))
    p.setBrush(QBrush(body))
    p.drawRoundedRect(r, rad, rad)
    # upper gloss
    top = QRectF(r.left() + 2, r.top() + 1.5, r.width() - 4, r.height() * 0.47)
    g = QLinearGradient(top.topLeft(), top.bottomLeft())
    g.setColorAt(0, _c(255, 255, 255, 190 + 40 * lift))
    g.setColorAt(1, _c(255, 255, 255, 55 + 60 * lift))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(top, max(2.0, rad - 2), max(2.0, rad - 2))
    # bottom glow
    bg = QRadialGradient(QPointF(r.center().x(), r.bottom() - 1), r.width() * 0.45)
    bg.setColorAt(0, _c(255, 255, 255, 120 if strong else 70))
    bg.setColorAt(1, _c(255, 255, 255, 0))
    p.setBrush(QBrush(bg))
    p.drawRoundedRect(r.adjusted(1, r.height() * 0.5, -1, -1), max(2.0, rad - 1), max(2.0, rad - 1))
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(_c(255, 255, 255, 235), 1.2))
    p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rad - 1, rad - 1)


def chip(p, r, rad, hover=0.0, active=None, down=False):
    """A light glass button (secondary actions)."""
    rad = max(3.0, rad)
    if active is not None:
        return button(p, r, rad, active, hover, down, strong=False)
    body = QLinearGradient(r.topLeft(), r.bottomLeft())
    body.setColorAt(0, _c(255, 255, 255, 120 + 60 * hover))
    body.setColorAt(0.5, _c(255, 255, 255, 52 + 40 * hover))
    body.setColorAt(0.52, _c(255, 255, 255, 30 + 40 * hover))
    body.setColorAt(1, _c(255, 255, 255, 66 + 40 * hover))
    p.setPen(QPen(_c(255, 255, 255, 230), 1.2))
    p.setBrush(QBrush(body))
    p.drawRoundedRect(r, rad, rad)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(_c(0, 30, 70, 70), 1.0))
    p.drawRoundedRect(r.adjusted(-0.6, -0.6, 0.6, 0.6), rad + 0.6, rad + 0.6)


def orb(p, c, d, base, light=None):
    """A glossy sphere (toggle knobs, logo badge, bullets)."""
    r = QRectF(c.x() - d / 2, c.y() - d / 2, d, d)
    g = QRadialGradient(QPointF(r.center().x(), r.bottom() - d * 0.2), d * 0.75)
    g.setColorAt(0, light if light is not None else base.lighter(160))
    g.setColorAt(0.6, base)
    g.setColorAt(1, base.darker(140))
    p.setPen(QPen(_c(255, 255, 255, 235), max(1.0, d * 0.05)))
    p.setBrush(QBrush(g))
    p.drawEllipse(r)
    hi = QRectF(r.left() + d * 0.16, r.top() + d * 0.06, d * 0.68, d * 0.42)
    hg = QLinearGradient(hi.topLeft(), hi.bottomLeft())
    hg.setColorAt(0, _c(255, 255, 255, 215))
    hg.setColorAt(1, _c(255, 255, 255, 25))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(hg))
    p.drawEllipse(hi)
