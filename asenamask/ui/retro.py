"""Painting helpers for the Retro look: old console menus (silver bevelled buttons with pointed ends, blue panels)."""
import math

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QLinearGradient, QPen, QBrush, QPainterPath, QPolygonF


def _c(r, g, b, a=255):
    return QColor(r, g, b, int(max(0, min(255, a))))


def tip_path(r, tip):
    """A hexagon-like bar whose left and right ends come to a point."""
    cy = r.center().y()
    pg = QPolygonF([QPointF(r.left(), cy), QPointF(r.left() + tip, r.top()), QPointF(r.right() - tip, r.top()),
                    QPointF(r.right(), cy), QPointF(r.right() - tip, r.bottom()), QPointF(r.left() + tip, r.bottom())])
    path = QPainterPath()
    path.addPolygon(pg)
    path.closeSubpath()
    return path


def cut_path(r, cut):
    """A rectangle with chamfered corners."""
    cut = min(cut, r.height() / 2.0, r.width() / 2.0)
    pg = QPolygonF([QPointF(r.left() + cut, r.top()), QPointF(r.right() - cut, r.top()), QPointF(r.right(), r.top() + cut),
                    QPointF(r.right(), r.bottom() - cut), QPointF(r.right() - cut, r.bottom()),
                    QPointF(r.left() + cut, r.bottom()), QPointF(r.left(), r.bottom() - cut),
                    QPointF(r.left(), r.top() + cut)])
    path = QPainterPath()
    path.addPolygon(pg)
    path.closeSubpath()
    return path


def panel(p, r, strong=False):
    path = cut_path(r, 9)
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    k = 1.8 if strong else 1.0
    g.setColorAt(0, _c(120, 140, 230, 40 * k))
    g.setColorAt(1, _c(4, 8, 30, 150 * k))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(g))
    p.drawPath(path)
    # soft light edge along the top
    hl = QLinearGradient(r.topLeft(), r.bottomLeft())
    hl.setColorAt(0, _c(255, 255, 255, 46))
    hl.setColorAt(0.25, _c(255, 255, 255, 0))
    p.setBrush(QBrush(hl))
    p.drawPath(path)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(_c(255, 255, 255, 170), 1.2))
    p.drawPath(path)
    p.setPen(QPen(_c(0, 20, 80, 120), 1.0))
    p.drawPath(cut_path(r.adjusted(-1, -1, 1, 1), 10))


def button(p, r, kind, hover=0.0, down=False):
    """Returns the text colour to use."""
    tip = min(r.height() * 0.34, 13.0)
    path = tip_path(r, tip)
    if kind == "primary":
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, _c(150 + 60 * hover, 168 + 50 * hover, 255))
        g.setColorAt(0.5, _c(70, 84, 214))
        g.setColorAt(0.52, _c(34, 42, 150))
        g.setColorAt(1, _c(70, 84, 214))
        p.setPen(QPen(_c(255, 255, 255, 240), 1.4))
        p.setBrush(QBrush(g))
        p.drawPath(path)
        p.setPen(QPen(_c(0, 30, 110, 140), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(tip_path(r.adjusted(-1, -1, 1, 1), tip + 1))
        return _c(255, 255, 255)
    if kind == "chip":
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, _c(255, 255, 255, 80 + 70 * hover))
        g.setColorAt(1, _c(255, 255, 255, 28 + 50 * hover))
        p.setPen(QPen(_c(255, 255, 255, 220), 1.2))
        p.setBrush(QBrush(g))
        p.drawPath(path)
        return _c(255, 255, 255)
    # silver
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    lift = 8 * hover
    g.setColorAt(0, _c(252, 254, 255))
    g.setColorAt(0.46, _c(218 + lift, 226 + lift, 242))
    g.setColorAt(0.54, _c(178 + lift, 190 + lift, 214))
    g.setColorAt(1, _c(228 + lift, 236 + lift, 248))
    if down:
        g.setColorAt(0, _c(190, 202, 226))
        g.setColorAt(1, _c(236, 242, 252))
    p.setPen(QPen(_c(60, 78, 124, 230), 1.1))
    p.setBrush(QBrush(g))
    p.drawPath(path)
    p.setPen(QPen(_c(255, 255, 255, 230), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawPath(tip_path(r.adjusted(1.5, 1.5, -1.5, -1.5), max(2.0, tip - 1.5)))
    return _c(22, 42, 92)


def draw_cube(p, cx, cy, size, yaw, pitch, alpha):
    """A translucent glass cube (faces turned up are brighter), like the floating cubes of old console menus."""
    cy_, sy_ = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)

    def rot(v):
        x, y, z = v
        x, z = x * cy_ + z * sy_, -x * sy_ + z * cy_
        y, z = y * cp - z * sp, y * sp + z * cp
        return x, y, z
    verts = [rot((x, y, z)) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    pts = [QPointF(cx + v[0] * size, cy + v[1] * size) for v in verts]
    faces = ((0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5))
    for f in sorted(faces, key=lambda f: -sum(verts[i][2] for i in f)):
        lit = max(0.0, min(1.0, 0.5 - 0.5 * (sum(verts[i][1] for i in f) / 4.0)))
        fill = QColor(int(40 + 205 * lit), int(52 + 195 * lit), int(110 + 145 * lit), int(alpha * (0.35 + 0.55 * lit)))
        path = QPainterPath()
        path.moveTo(pts[f[0]])
        for i in f[1:]:
            path.lineTo(pts[i])
        path.closeSubpath()
        p.setBrush(fill)
        p.setPen(QPen(QColor(220, 230, 255, int(alpha * 0.45)), 1.0))
        p.drawPath(path)
