"""Trim & pick editor: scrubbable video player, Medal-style trim handles, subject boxes / points / brush,
correction frames and a live highlight of what the AI selects."""
import io
import math
import time

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QThread, QTimer
from PySide6.QtGui import (QPainter, QPixmap, QImage, QColor, QPen, QFont, QPainterPath, QBrush, QLinearGradient)
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QSlider

from .. import videoinfo
from .theme import theme, mix
from .widgets import Overlay, GlowButton, title_label

PROXY_W = 800
BRUSH_UNIT = 0.006          # brush size slider step, as a fraction of the picture width


def fmt_time(frame, fps):
    t = frame / float(fps or 24)
    m, s = divmod(t, 60)
    return "%d:%05.2f" % (int(m), s)


# ---------------------------------------------------------------- selection helpers (pure python)
def sample_stroke(pts, spacing, aspect, cap=14):
    """Spreads at most `cap` points along a brush stroke (pts are fractions of the picture)."""
    if len(pts) == 1:
        return [list(pts[0])]
    segs, total = [], 0.0
    for a, b in zip(pts, pts[1:]):
        d = math.hypot(b[0] - a[0], (b[1] - a[1]) * aspect)
        segs.append(d)
        total += d
    n = max(2, min(cap, int(total / max(spacing, 1e-4)) + 1))
    out = []
    for k in range(n):
        target = total * k / (n - 1)
        acc = 0.0
        for (a, b), d in zip(zip(pts, pts[1:]), segs):
            if acc + d >= target:
                t = (target - acc) / d if d > 0 else 0.0
                out.append([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t])
                break
            acc += d
        else:
            out.append(list(pts[-1]))
    return out


def state_to_fractions(st, aspect):
    """Boxes, include points and exclude points of a canvas state, with brush strokes turned into points (fractions)."""
    pos = [list(p) for p in st.get("pos", [])]
    neg = [list(p) for p in st.get("neg", [])]
    for s in st.get("strokes", []):
        pts = sample_stroke(s["pts"], max(0.02, s["size"] * 0.9), aspect)
        (pos if s["kind"] == "pos" else neg).extend(pts)
    return {"boxes": [list(b) for b in st.get("boxes", [])], "pos": pos, "neg": neg}


def fractions_to_selection(fr, orig):
    ow, oh = orig
    return {"boxes": [[b[0] * ow, b[1] * oh, b[2] * ow, b[3] * oh] for b in fr["boxes"]],
            "pos": [[p[0] * ow, p[1] * oh] for p in fr["pos"]],
            "neg": [[p[0] * ow, p[1] * oh] for p in fr["neg"]]}


def selection_to_fractions(sel, orig):
    ow, oh = orig
    sel = sel or {}
    return {"boxes": [[b[0] / ow, b[1] / oh, b[2] / ow, b[3] / oh] for b in sel.get("boxes", [])],
            "pos": [[p[0] / ow, p[1] / oh] for p in sel.get("pos", [])],
            "neg": [[p[0] / ow, p[1] / oh] for p in sel.get("neg", [])]}


def selection_keys(sel):
    """{frame: selection dict} for the picked subject and all correction frames."""
    out = {}
    if not sel:
        return out
    if sel.get("boxes") or sel.get("pos"):
        out[int(sel.get("frame", 0))] = sel
    for k in sel.get("extra") or []:
        if k.get("boxes") or k.get("pos"):
            out.setdefault(int(k.get("frame", 0)), k)
    return out



def interpolate_fractions(keys, f):
    """Where the picked subject probably is on frame f. keys: {frame: fractions dict} (boxes / pos / neg in 0..1).
    Between two key frames the points and boxes glide from one to the other (so a subject walking across the picture is
    followed); with different numbers of points on the two frames the nearer frame's points are moved by how far the
    group's centre moves. Before the first / after the last key frame the nearest one is simply held."""
    if not keys:
        return None
    if f in keys:
        return keys[f]
    before = [k for k in keys if k < f]
    after = [k for k in keys if k > f]
    if not before or not after:
        return keys[max(before) if before else min(after)]
    a, b = max(before), min(after)
    A, B = keys[a], keys[b]
    t = (f - a) / float(b - a)

    def clamp(v):
        return min(1.0, max(0.0, v))

    if all(len(A[k]) == len(B[k]) for k in ("boxes", "pos", "neg")):
        return {"boxes": [[clamp(x + (y - x) * t) for x, y in zip(p, q)] for p, q in zip(A["boxes"], B["boxes"])],
                "pos": [[clamp(x + (y - x) * t) for x, y in zip(p, q)] for p, q in zip(A["pos"], B["pos"])],
                "neg": [[clamp(x + (y - x) * t) for x, y in zip(p, q)] for p, q in zip(A["neg"], B["neg"])]}

    def centre(fr):
        pts = [tuple(p) for p in fr["pos"]] + [(bx[0] + bx[2] / 2.0, bx[1] + bx[3] / 2.0) for bx in fr["boxes"]]
        if not pts:
            return 0.5, 0.5
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)

    ca, cb = centre(A), centre(B)
    src, cs = (A, ca) if t < 0.5 else (B, cb)
    dx = ca[0] + (cb[0] - ca[0]) * t - cs[0]
    dy = ca[1] + (cb[1] - ca[1]) * t - cs[1]
    return {"boxes": [[clamp(bx[0] + dx), clamp(bx[1] + dy), bx[2], bx[3]] for bx in src["boxes"]],
            "pos": [[clamp(p[0] + dx), clamp(p[1] + dy)] for p in src["pos"]],
            "neg": [[clamp(p[0] + dx), clamp(p[1] + dy)] for p in src["neg"]]}


_checker = {}


def checker_brush():
    key = theme.name
    br = _checker.get(key)
    if br is None:
        a, b = (QColor(60, 60, 68), QColor(84, 84, 94)) if theme.name != "light" else \
            (QColor(205, 205, 212), QColor(232, 232, 238))
        s = 12
        pm = QPixmap(s * 2, s * 2)
        q = QPainter(pm)
        q.fillRect(0, 0, s * 2, s * 2, a)
        q.fillRect(0, 0, s, s, b)
        q.fillRect(s, s, s, s, b)
        q.end()
        br = _checker[key] = QBrush(pm)
    return br


class ProxyLoader(QThread):
    """Decodes the whole clip once into small JPEGs so scrubbing is instant."""
    progress = Signal(int)
    finished_all = Signal(int)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.frames = []        # JPEG bytes, one per frame, in order
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            from PIL import Image
            for k, arr in enumerate(videoinfo.iter_frames(self.path)):
                if self._stop:
                    return
                im = Image.fromarray(arr)
                if im.width > PROXY_W:
                    im = im.resize((PROXY_W, round(im.height * PROXY_W / im.width)), Image.BILINEAR)
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=80)
                self.frames.append(buf.getvalue())
                if k % 6 == 0:
                    self.progress.emit(len(self.frames))
        except Exception:
            pass
        self.finished_all.emit(len(self.frames))


class FrameCanvas(QWidget):
    """Shows the current frame. In pick mode: drag = box, click = include point, right-click = exclude point,
    or paint with the brush. Optionally draws a highlight of the AI selection or the finished cutout."""
    changed = Signal()
    pressed = Signal()
    clicked = Signal()

    def __init__(self, parent=None, interactive=True):
        super().__init__(parent)
        self.interactive = interactive
        self.pix = None
        self.orig = (1920, 1080)
        self.boxes, self.pos, self.neg, self.strokes = [], [], [], []   # fractions (0..1) of the frame
        self.history = []
        self.mode = "point"                # point | brush_pos | brush_neg
        self.brush = 0.03                  # brush width, fraction of the picture width
        self.highlight = None              # QPixmap drawn over the frame (the AI selection)
        self.ghost = None                  # estimated points / boxes on a frame between two picked frames (fractions)
        self.cutout = None                 # QPixmap drawn over a backdrop instead of the frame
        self.backdrop = None               # QColor, or None for a checkerboard
        self.hint = ""
        self._start = self._cur = self._btn = None
        self._path = []
        self._hover = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor if interactive else Qt.PointingHandCursor)
        self.setMinimumSize(380 if interactive else 300, 220 if interactive else 170)

    # ---- content
    def set_pixmap(self, pm):
        self.pix = pm
        self.update()

    def set_orig(self, w, h):
        self.orig = (max(1, w), max(1, h))

    def set_mode(self, mode):
        self.mode = mode
        self._hover = None
        self.setCursor(Qt.CrossCursor if mode == "point" else Qt.BlankCursor)
        self.update()

    def set_highlight(self, pm):
        self.highlight = pm
        self.update()

    def set_cutout(self, pm, backdrop=None):
        self.cutout, self.backdrop = pm, backdrop
        self.update()

    def set_ghost(self, fr):
        self.ghost = fr
        self.update()

    # ---- state
    def get_state(self):
        return {"boxes": [list(b) for b in self.boxes], "pos": [list(p) for p in self.pos],
                "neg": [list(p) for p in self.neg],
                "strokes": [{"kind": s["kind"], "pts": [list(q) for q in s["pts"]], "size": s["size"]}
                            for s in self.strokes],
                "history": list(self.history)}

    def set_state(self, st):
        st = st or {}
        self.boxes = [list(b) for b in st.get("boxes", [])]
        self.pos = [list(p) for p in st.get("pos", [])]
        self.neg = [list(p) for p in st.get("neg", [])]
        self.strokes = [{"kind": s["kind"], "pts": [list(q) for q in s["pts"]], "size": s["size"]}
                        for s in st.get("strokes", [])]
        self.history = list(st.get("history") or (["box"] * len(self.boxes) + ["pos"] * len(self.pos)
                                                  + ["neg"] * len(self.neg) + ["stroke"] * len(self.strokes)))
        self.update()

    def set_selection(self, sel):
        self.set_state(selection_to_fractions(sel, self.orig) if sel else None)

    def fractions(self):
        return state_to_fractions(self.get_state(), self.orig[1] / float(self.orig[0]))

    def selection(self):
        return fractions_to_selection(self.fractions(), self.orig)

    def is_empty(self):
        return not (self.boxes or self.pos or self.neg or self.strokes)

    def clear(self, emit=True):
        self.boxes, self.pos, self.neg, self.strokes, self.history = [], [], [], [], []
        self.highlight = None
        self.update()
        if emit:
            self.changed.emit()

    def undo(self):
        if self.history:
            what = self.history.pop()
            {"box": self.boxes, "pos": self.pos, "neg": self.neg, "stroke": self.strokes}[what].pop()
            self.update()
            self.changed.emit()

    # ---- geometry
    def _rect(self):
        if self.pix is None or self.pix.isNull():
            return QRectF(self.rect())
        w, h = self.pix.width(), self.pix.height()
        s = min(self.width() / w, self.height() / h)
        return QRectF((self.width() - w * s) / 2, (self.height() - h * s) / 2, w * s, h * s)

    def _frac(self, pt):
        r = self._rect()
        return (min(max((pt.x() - r.left()) / r.width(), 0), 1), min(max((pt.y() - r.top()) / r.height(), 0), 1))

    def _wid(self, fx, fy):
        r = self._rect()
        return QPointF(r.left() + fx * r.width(), r.top() + fy * r.height())

    # ---- mouse
    def _brush_kind(self, btn):
        kind = "pos" if self.mode == "brush_pos" else "neg"
        if btn == Qt.RightButton:
            kind = "neg" if kind == "pos" else "pos"
        return kind

    def mousePressEvent(self, e):
        if self.pix is None:
            return
        if not self.interactive:
            if e.button() == Qt.LeftButton:
                self.clicked.emit()
            return
        if e.button() in (Qt.LeftButton, Qt.RightButton):
            self.pressed.emit()
            self._btn, self._start, self._cur = e.button(), e.position(), e.position()
            self._path = [self._frac(e.position())] if self.mode != "point" else []

    def mouseMoveEvent(self, e):
        if not self.interactive:
            return
        self._hover = e.position() if self.mode != "point" else None
        if self._start is not None:
            self._cur = e.position()
            if self.mode != "point":
                f = self._frac(e.position())
                last = self._path[-1]
                if abs(f[0] - last[0]) + abs(f[1] - last[1]) > 0.004:
                    self._path.append(f)
        self.update()

    def leaveEvent(self, e):
        self._hover = None
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if not self.interactive or self._start is None or e.button() != self._btn:
            return
        a, b = self._start, e.position()
        btn = self._btn
        path = self._path
        self._start = self._cur = self._btn = None
        self._path = []
        if self.mode != "point":
            if path:
                self.strokes.append({"kind": self._brush_kind(btn), "pts": path, "size": self.brush})
                self.history.append("stroke")
                self.update()
                self.changed.emit()
            return
        moved = abs(a.x() - b.x()) > 8 and abs(a.y() - b.y()) > 8
        if btn == Qt.LeftButton and moved:
            f1, f2 = self._frac(a), self._frac(b)
            self.boxes.append([min(f1[0], f2[0]), min(f1[1], f2[1]), abs(f1[0] - f2[0]), abs(f1[1] - f2[1])])
            self.history.append("box")
        else:
            f = self._frac(b)
            if btn == Qt.LeftButton:
                self.pos.append(list(f))
                self.history.append("pos")
            else:
                self.neg.append(list(f))
                self.history.append("neg")
        self.update()
        self.changed.emit()

    # ---- painting
    def _stroke_path(self, pts):
        path = QPainterPath()
        w0 = self._wid(*pts[0])
        path.moveTo(w0)
        if len(pts) == 1:
            path.lineTo(QPointF(w0.x() + 0.01, w0.y()))
        for q in pts[1:]:
            path.lineTo(self._wid(*q))
        return path

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self._rect()
        if self.pix is None or self.pix.isNull():
            p.setPen(theme.col("sub"))
            p.drawText(self.rect(), Qt.AlignCenter, "Loading preview…")
            return
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.save()
        p.setClipPath(path)
        if self.cutout is not None:
            if self.backdrop is not None:
                p.fillRect(r, self.backdrop)
            else:
                p.fillRect(r, checker_brush())
            p.drawPixmap(r, self.cutout, QRectF(self.cutout.rect()))
        else:
            p.drawPixmap(r, self.pix, QRectF(self.pix.rect()))
            if self.highlight is not None:
                p.drawPixmap(r, self.highlight, QRectF(self.highlight.rect()))
        p.restore()
        acc = theme.col("accent2")
        f = QFont("Segoe UI", 10)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        for s in self.strokes:
            col = QColor(60, 220, 120, 120) if s["kind"] == "pos" else QColor(240, 70, 70, 120)
            pen = QPen(col, max(3.0, s["size"] * r.width()), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(self._stroke_path(s["pts"]))
        if self._start is not None and self.mode != "point" and self._path:
            col = QColor(60, 220, 120, 120) if self._brush_kind(self._btn) == "pos" else QColor(240, 70, 70, 120)
            p.setPen(QPen(col, max(3.0, self.brush * r.width()), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(self._stroke_path(self._path))
        for i, (x, y, w, h) in enumerate(self.boxes):
            br = QRectF(self._wid(x, y), self._wid(x + w, y + h))
            p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), 40))
            p.setPen(QPen(acc, 2.5))
            p.drawRect(br)
            p.setBrush(acc)
            p.setPen(Qt.NoPen)
            tag = QRectF(br.left(), br.top() - 22, 24, 22)
            p.drawRoundedRect(tag, 5, 5)
            p.setPen(QColor(255, 255, 255))
            p.drawText(tag, Qt.AlignCenter, str(i + 1))
        for pts, col, minus in ((self.pos, QColor(60, 220, 120), False), (self.neg, QColor(240, 70, 70), True)):
            for fx, fy in pts:
                c = self._wid(fx, fy)
                p.setBrush(col)
                p.setPen(QPen(QColor(255, 255, 255), 2.5))
                p.drawEllipse(c, 8, 8)
                if minus:
                    p.drawLine(QPointF(c.x() - 4, c.y()), QPointF(c.x() + 4, c.y()))
        if self._start is not None and self.mode == "point" and self._btn == Qt.LeftButton and self._cur is not None:
            p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), 40))
            p.setPen(QPen(acc, 2, Qt.DashLine))
            p.drawRect(QRectF(self._start, self._cur).normalized())
        if self._hover is not None and self.mode != "point" and r.contains(self._hover):
            rad = max(2.0, self.brush * r.width() / 2)
            col = QColor(60, 220, 120) if self.mode == "brush_pos" else QColor(240, 70, 70)
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 40))
            p.setPen(QPen(QColor(255, 255, 255, 230), 1.6))
            p.drawEllipse(self._hover, rad, rad)
        if self.ghost and not (self.boxes or self.pos or self.neg or self.strokes):
            gp = QPen(QColor(255, 255, 255, 215), 2.0, Qt.DashLine)
            for (x, y, w, h) in self.ghost.get("boxes", []):
                br = QRectF(self._wid(x, y), self._wid(x + w, y + h))
                p.setBrush(Qt.NoBrush)
                p.setPen(gp)
                p.drawRect(br)
            for pts, col in ((self.ghost.get("pos", []), QColor(60, 220, 120)), (self.ghost.get("neg", []), QColor(240, 70, 70))):
                for fx, fy in pts:
                    c = self._wid(fx, fy)
                    p.setBrush(QColor(col.red(), col.green(), col.blue(), 70))
                    p.setPen(gp)
                    p.drawEllipse(c, 8, 8)
        if self.hint:
            f2 = QFont("Segoe UI", 10)
            f2.setWeight(QFont.DemiBold)
            p.setFont(f2)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(self.hint) + 24
            tr = QRectF(r.center().x() - tw / 2, r.bottom() - 40, tw, 28)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(tr, 14, 14)
            p.setPen(QColor(255, 255, 255))
            p.drawText(tr, Qt.AlignCenter, self.hint)


class Timeline(QWidget):
    """Filmstrip with a playhead and two trim handles (drag the ends to choose the section)."""
    seek = Signal(int)
    range_changed = Signal(int, int)

    PAD = 16
    HANDLE = 11

    def __init__(self, parent=None, height=84):
        super().__init__(parent)
        self.n, self.pos, self.a, self.b = 1, 0, 0, 0
        self.loaded = 0
        self.refs = []             # frames that carry a picked subject / correction
        self.strip = []
        self.drag = None
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        theme.changed.connect(self.update)

    def set_n(self, n):
        self.n = max(1, n)
        self.a = min(self.a, self.n - 1)
        self.b = min(self.b, self.n - 1)
        self.update()

    def set_range(self, a, b):
        self.a, self.b = a, b
        self.update()

    def _track(self):
        return QRectF(self.PAD, 22, self.width() - 2 * self.PAD, self.height() - 38)

    def x_of(self, i):
        t = self._track()
        return t.left() + t.width() * (i / float(max(1, self.n - 1)))

    def i_of(self, x):
        t = self._track()
        f = (x - t.left()) / max(1.0, t.width())
        return int(round(min(max(f, 0.0), 1.0) * (self.n - 1)))

    def _hit(self, x):
        xa, xb = self.x_of(self.a), self.x_of(self.b)
        if xa - self.HANDLE - 4 <= x <= xa + 3:
            return "a"
        if xb - 3 <= x <= xb + self.HANDLE + 4:
            return "b"
        return None

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        x = e.position().x()
        self.drag = self._hit(x) or "play"
        self._apply(x)

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self.drag:
            self._apply(x)
        else:
            self.setCursor(Qt.SizeHorCursor if self._hit(x) else Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        self.drag = None

    def _apply(self, x):
        i = self.i_of(x)
        if self.drag == "a":
            self.a = min(i, self.b - 1) if self.b > 0 else 0
            self.a = max(0, self.a)
            self.range_changed.emit(self.a, self.b)
            self.seek.emit(self.a)
        elif self.drag == "b":
            self.b = max(i, self.a + 1)
            self.b = min(self.n - 1, self.b)
            self.range_changed.emit(self.a, self.b)
            self.seek.emit(self.b)
        else:
            self.seek.emit(i)
        self.update()

    def set_in(self, i):
        """Start of the section = frame i."""
        if self.n < 2:
            return
        self.a = max(0, min(i, self.b - 1))
        self.range_changed.emit(self.a, self.b)
        self.update()

    def set_out(self, i):
        """End of the section = frame i."""
        if self.n < 2:
            return
        self.b = min(self.n - 1, max(i, self.a + 1))
        self.range_changed.emit(self.a, self.b)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        t = self._track()
        acc, acc2 = theme.col("accent"), theme.col("accent2")
        clip = QPainterPath()
        clip.addRoundedRect(t, 8, 8)
        p.save()
        p.setClipPath(clip)
        p.fillRect(t, theme.col("input"))
        if self.strip:
            w = t.width() / len(self.strip)
            for k, pm in enumerate(self.strip):
                tgt = QRectF(t.left() + k * w, t.top(), w + 1, t.height())
                s = max(tgt.width() / pm.width(), tgt.height() / pm.height())
                sw, sh = tgt.width() / s, tgt.height() / s
                src = QRectF((pm.width() - sw) / 2, (pm.height() - sh) / 2, sw, sh)
                p.drawPixmap(tgt, pm, src)
        if self.loaded < self.n:   # not decoded yet
            xl = self.x_of(max(0, self.loaded - 1))
            p.fillRect(QRectF(xl, t.top(), t.right() - xl, t.height()), QColor(0, 0, 0, 90))
        xa, xb = self.x_of(self.a), self.x_of(self.b)
        p.fillRect(QRectF(t.left(), t.top(), xa - t.left(), t.height()), QColor(0, 0, 0, 165))
        p.fillRect(QRectF(xb, t.top(), t.right() - xb, t.height()), QColor(0, 0, 0, 165))
        p.restore()
        # trim frame + handles
        g = QLinearGradient(xa, 0, xb, 0)
        g.setColorAt(0, acc)
        g.setColorAt(1, acc2)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QBrush(g), 3))
        p.drawRect(QRectF(xa, t.top() - 1, max(1.0, xb - xa), t.height() + 2))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        hh = t.height() + 8
        for x, left in ((xa, True), (xb, False)):
            hr = QRectF(x - self.HANDLE if left else x, t.top() - 4, self.HANDLE, hh)
            p.drawRoundedRect(hr, 4, 4)
            p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
            cx = hr.center().x()
            p.drawLine(QPointF(cx, hr.center().y() - 6), QPointF(cx, hr.center().y() + 6))
            p.setPen(Qt.NoPen)
        # subject / correction markers
        for k, ref in enumerate(self.refs):
            if 0 <= ref < self.n:
                x = self.x_of(ref)
                tri = QPainterPath()
                tri.moveTo(x - 6, 4)
                tri.lineTo(x + 6, 4)
                tri.lineTo(x, 15)
                tri.closeSubpath()
                p.setBrush(acc2 if k == 0 else QColor(255, 170, 60))
                p.drawPath(tri)
        # playhead
        x = self.x_of(self.pos)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawLine(QPointF(x, t.top() - 8), QPointF(x, t.bottom() + 8))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(x, t.bottom() + 10), 5, 5)


class EditorOverlay(Overlay):
    done = Signal(dict)

    def __init__(self, host, source):
        super().__init__(host, source, frac=(0.95, 0.95), max_size=(1500, 940), closable=False)
        self.loader = None
        self.engine = None
        self.get_params = lambda: {}
        self.fps = 24.0
        self.total = 1
        self.cur = 0
        self.keys = {}              # frame -> canvas state (picked subject first, then corrections)
        self.live = True
        self._req = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.hl_timer = QTimer(self)
        self.hl_timer.setSingleShot(True)
        self.hl_timer.setInterval(140)
        self.hl_timer.timeout.connect(self._send_highlight)
        self.wait_timer = QTimer(self)               # shows how long the engine has been working on the last request
        self.wait_timer.setInterval(1000)
        self.wait_timer.timeout.connect(self._wait_tick)
        self._t_req = 0.0
        self._wait_base = ""
        L = self.panel_layout
        L.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(title_label("Trim & pick your subject", 17, QFont.Bold))
        head.addStretch(1)
        self.status = title_label("", 10, QFont.Normal, sub=True)
        head.addWidget(self.status)
        L.addLayout(head)
        L.addWidget(title_label(
            "Scrub to a frame where your subject is clear. Drag a box around them, or click on them (right-click = "
            "not this). Brush is the same idea with paint: Brush + (green) on the subject, Brush − (red) on "
            "what must NOT be included. If tracking drifts later, go to that frame and pick the subject again.",
            10, QFont.Normal, sub=True))
        self.tool_hint = title_label("", 9, QFont.Normal, sub=True)
        L.addWidget(self.tool_hint)

        self.canvas = FrameCanvas()
        self.canvas.changed.connect(self._sel_changed)
        self.canvas.pressed.connect(self._pause)
        L.addWidget(self.canvas, 1)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.tool_btns = {}
        for key, label in (("point", "Box / point"), ("brush_pos", "Brush +"), ("brush_neg", "Brush −")):
            b = GlowButton(label, "chip")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self._set_tool(k))
            self.tool_btns[key] = b
            tools.addWidget(b)
        self.tool_btns["point"].setChecked(True)
        self.size_lbl = title_label("Size", 9, QFont.Normal, sub=True)
        tools.addSpacing(6)
        tools.addWidget(self.size_lbl)
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(1, 14)
        self.size.setValue(5)
        self.size.setFixedWidth(120)
        self.size.valueChanged.connect(lambda v: setattr(self.canvas, "brush", v * BRUSH_UNIT))
        self.canvas.brush = 5 * BRUSH_UNIT
        tools.addWidget(self.size)
        tools.addStretch(1)
        self.live_btn = GlowButton("Live highlight", "chip")
        self.live_btn.setCheckable(True)
        self.live_btn.setChecked(True)
        self.live_btn.clicked.connect(self._toggle_live)
        tools.addWidget(self.live_btn)
        self.engine_lbl = title_label("", 9, QFont.Normal, sub=True)
        tools.addWidget(self.engine_lbl)
        L.addLayout(tools)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self.play_btn = GlowButton("Play", "ghost")
        self.play_btn.setFixedWidth(92)
        self.play_btn.clicked.connect(self.toggle_play)
        ctrl.addWidget(self.play_btn)
        prev = GlowButton("‹ Frame", "chip")
        nxt = GlowButton("Frame ›", "chip")
        self.video_only = [self.play_btn, prev, nxt]
        prev.clicked.connect(lambda: self._step(-1))
        nxt.clicked.connect(lambda: self._step(1))
        ctrl.addWidget(prev)
        ctrl.addWidget(nxt)
        sin = GlowButton("Start here  I", "chip")
        sout = GlowButton("End here  O", "chip")
        sin.clicked.connect(lambda: self.timeline.set_in(self.cur))
        sout.clicked.connect(lambda: self.timeline.set_out(self.cur))
        ctrl.addWidget(sin)
        ctrl.addWidget(sout)
        self.video_only += [sin, sout]
        self.time_lbl = title_label("0:00.00", 11, QFont.DemiBold)
        ctrl.addSpacing(8)
        ctrl.addWidget(self.time_lbl)
        ctrl.addStretch(1)
        self.range_lbl = title_label("", 10, QFont.Normal, sub=True)
        ctrl.addWidget(self.range_lbl)
        L.addLayout(ctrl)

        self.timeline = Timeline()
        self.timeline.seek.connect(self._seek)
        self.timeline.range_changed.connect(self._range_changed)
        L.addWidget(self.timeline)
        self.video_only += [self.timeline, self.time_lbl, self.range_lbl]

        self.warn = title_label("", 10, QFont.DemiBold)
        L.addWidget(self.warn)

        row = QHBoxLayout()
        row.setSpacing(10)
        undo = GlowButton("Undo", "ghost")
        undo.setFixedWidth(96)
        undo.clicked.connect(self.canvas.undo)
        clr = GlowButton("Clear this frame", "ghost")
        clr.setFixedWidth(160)
        clr.clicked.connect(lambda: self.canvas.clear())
        clr_all = GlowButton("Clear all", "ghost")
        clr_all.setFixedWidth(110)
        clr_all.clicked.connect(self._clear_all)
        rst = GlowButton("Reset trim", "ghost")
        rst.setFixedWidth(120)
        rst.clicked.connect(self._reset_trim)
        self.video_only.append(rst)
        self.jump = GlowButton("Go to subject frame", "chip")
        self.jump.clicked.connect(lambda: self._seek(min(self.keys) if self.keys else 0))
        self.jump.hide()
        for w in (undo, clr, clr_all, rst, self.jump):
            row.addWidget(w)
        row.addStretch(1)
        cancel = GlowButton("Cancel", "ghost")
        cancel.setFixedWidth(120)
        cancel.clicked.connect(self.close_overlay)
        ok = GlowButton("Done", "primary")
        ok.setFixedWidth(180)
        ok.clicked.connect(self._done)
        row.addWidget(cancel)
        row.addWidget(ok)
        L.addLayout(row)

    # ---- opening
    def open_with(self, loader, info, trim, selection, engine=None, get_params=None, start=None):
        self.loader = loader
        self.engine = engine
        self.get_params = get_params or (lambda: {})
        still = info.get("kind") == "image"
        for w in self.video_only:
            w.setVisible(not still)
        self.fps = float(info.get("fps") or 24.0)
        self.total = max(1, int(info.get("frames") or len(loader.frames) or 1))
        n = max(self.total, len(loader.frames))
        self.canvas.set_orig(info["width"], info["height"])
        self.canvas.set_highlight(None)
        self.keys = {}
        for f, d in selection_keys(selection).items():
            self.keys[f] = {**self.canvas_state_from(d), "history": None}
        tl = self.timeline
        tl.set_n(n)
        a, b = (trim["start"], trim["end"]) if trim else (0, n - 1)
        tl.set_range(min(a, n - 1), min(b, n - 1))
        tl.strip = []
        tl.loaded = len(loader.frames)
        self.cur = min(self.keys) if self.keys else tl.a
        if start is not None:                       # open on the frame the main preview is showing
            self.cur = int(start)
        self.cur = max(0, min(self.cur, n - 1))
        tl.pos = self.cur
        self.canvas.set_state(self.keys.get(self.cur))
        loader.progress.connect(self._on_progress)
        loader.finished_all.connect(self._on_loaded)
        if self.engine is not None:
            self.engine.result.connect(self._on_result)
            self.engine.failed.connect(self._on_engine_failed)
            self.engine.state_changed.connect(self._on_engine_state)
            self.engine.status.connect(self._on_engine_status)
        self._refresh_marks()
        self._range_changed(tl.a, tl.b)
        if not loader.isRunning() and loader.frames:
            self._on_loaded(len(loader.frames))
        else:
            self.status.setText("Loading preview… %d frames" % len(loader.frames))
        self._show(self.cur, store=False)
        self.open_overlay()
        self._set_tool("point")
        self._request_highlight()

    def canvas_state_from(self, d):
        fr = selection_to_fractions(d, self.canvas.orig)
        return {"boxes": fr["boxes"], "pos": fr["pos"], "neg": fr["neg"], "strokes": []}

    def on_close(self):
        self._pause()
        self.hl_timer.stop()
        self.wait_timer.stop()
        try:
            self.loader.progress.disconnect(self._on_progress)
            self.loader.finished_all.disconnect(self._on_loaded)
        except Exception:
            pass
        if self.engine is not None:
            for sig, slot in ((self.engine.result, self._on_result), (self.engine.failed, self._on_engine_failed),
                              (self.engine.state_changed, self._on_engine_state),
                              (self.engine.status, self._on_engine_status)):
                try:
                    sig.disconnect(slot)
                except Exception:
                    pass

    # ---- loading
    def _on_progress(self, n):
        self.timeline.loaded = n
        self.status.setText("Loading preview… %d frames" % n)
        if n and self.canvas.pix is None:
            self._show(self.cur, store=False)
        self.timeline.update()

    def _on_loaded(self, n):
        self.status.setText("")
        tl = self.timeline
        old_n = tl.n
        tl.loaded = n
        if n and n != old_n:       # the real frame count is known now
            was_full = (tl.a == 0 and tl.b >= old_n - 1)
            tl.set_n(n)
            tl.set_range(tl.a, n - 1 if was_full else min(tl.b, n - 1))
            self.total = n
        strip = []
        frames = self.loader.frames
        for k in range(14 if n >= 14 else max(1, n)):
            idx = int((k + 0.5) * n / (14 if n >= 14 else max(1, n)))
            img = QImage()
            img.loadFromData(frames[min(idx, n - 1)], "JPG")
            strip.append(QPixmap.fromImage(img.scaledToHeight(64, Qt.SmoothTransformation)))
        tl.strip = strip
        self._range_changed(tl.a, tl.b)
        self._sel_changed(request=False)
        tl.update()

    # ---- keeping the picked prompts per frame
    def _store_current(self):
        if self.canvas.is_empty():
            self.keys.pop(self.cur, None)
        else:
            self.keys[self.cur] = self.canvas.get_state()

    def _refresh_marks(self):
        self.timeline.refs = sorted(self.keys)
        self.timeline.update()
        self.jump.setVisible(bool(self.keys))

    # ---- estimated position between picked frames
    def _ghost_fractions(self):
        """Estimated selection for the current frame when it has none of its own but other frames do."""
        if not self.keys or not self.canvas.is_empty():
            return None
        aspect = self.canvas.orig[1] / float(self.canvas.orig[0])
        keyed = {f: state_to_fractions(st, aspect) for f, st in self.keys.items() if f != self.cur}
        keyed = {f: fr for f, fr in keyed.items() if fr["boxes"] or fr["pos"]}
        return interpolate_fractions(keyed, self.cur)

    def _update_ghost(self):
        self.canvas.set_ghost(self._ghost_fractions())

    # ---- showing frames
    def _show(self, i, store=True):
        fr = self.loader.frames if self.loader else []
        if not fr:
            return
        i = max(0, min(len(fr) - 1, i))
        if store and i != self.cur:
            self._store_current()
            self.cur = i
            self.canvas.set_highlight(None)
            self.canvas.set_state(self.keys.get(i))
            self._update_ghost()
            self._update_status()
            self._refresh_marks()
            self._request_highlight()
        self.cur = i
        pm = QPixmap()
        pm.loadFromData(fr[i], "JPG")
        self.canvas.set_pixmap(pm)
        self.timeline.pos = i
        self.timeline.update()
        self.time_lbl.setText("%s   (frame %d)" % (fmt_time(i, self.fps), i + 1))
        self._update_status()

    def _seek(self, i):
        self._pause()
        self._show(i)

    def _step(self, d):
        self._pause()
        self._show(self.cur + d)

    def toggle_play(self):
        if self.timer.isActive():
            self._pause()
        else:
            tl = self.timeline
            if self.cur >= tl.b or self.cur < tl.a:
                self._show(tl.a)
            self.timer.start(int(1000 / max(1.0, self.fps)))
            self.play_btn.setText("Pause")

    def _pause(self):
        self.timer.stop()
        self.play_btn.setText("Play")

    def _tick(self):
        tl = self.timeline
        nxt = self.cur + 1
        if nxt > tl.b:
            nxt = tl.a
        if nxt >= len(self.loader.frames):     # not decoded yet: wait
            return
        self._show(nxt)

    # ---- tools
    def _set_tool(self, key):
        for k, b in self.tool_btns.items():
            b.setChecked(k == key)
        self.canvas.set_mode(key)
        brush = key != "point"
        self.size.setVisible(brush)
        self.size_lbl.setVisible(brush)
        self.tool_hint.setText({
            "point": "Box / point: drag to draw a box around the subject, or click on it. Right-click marks a spot to leave out.",
            "brush_pos": "Brush +: paint a few strokes over the subject (inside it, not around it). Hair, a cape or a weapon that "
                         "was missed? Paint over it.",
            "brush_neg": "Brush −: paint over anything that was wrongly included, like a background object or a second character."
        }.get(key, ""))

    def _clear_all(self):
        self.keys = {}
        self.canvas.clear(emit=False)
        self._sel_changed()

    def _toggle_live(self):
        self.live = self.live_btn.isChecked()
        if not self.live:
            self.canvas.set_highlight(None)
            self.engine_lbl.setText("")
        else:
            self._request_highlight()

    # ---- trim state
    def _range_changed(self, a, b):
        n = b - a + 1
        self.range_lbl.setText("Section: %s → %s   ·   %d frames  (%.1f s)" % (
            fmt_time(a, self.fps), fmt_time(b, self.fps), n, n / self.fps))
        self.warn.setText("")

    def _reset_trim(self):
        tl = self.timeline
        tl.set_range(0, tl.n - 1)
        self._range_changed(0, tl.n - 1)

    def _sel_changed(self, request=True):
        self._store_current()
        self._refresh_marks()
        self._update_ghost()
        self.warn.setText("")
        self._update_status()
        if request:
            self._request_highlight()

    def _update_status(self):
        if self.loader and self.loader.isRunning():
            return
        if self.keys:
            n = len(self.keys)
            first = min(self.keys)
            txt = "Subject set on %s" % fmt_time(first, self.fps)
            if n > 1:
                txt += "  ·  %d correction frame(s)" % (n - 1)
            if self.canvas.ghost:
                txt += "  ·  dashed markers = estimated position here, click to correct it"
            self.status.setText(txt)
        else:
            self.status.setText("")

    # ---- live highlight
    def _request_highlight(self):
        if self.live and self.engine is not None:
            self.hl_timer.start()

    def _send_highlight(self):
        if not (self.live and self.engine is not None and self.loader and self.loader.frames):
            return
        prm = self.get_params() or {}
        fr = self.canvas.fractions()
        if not (fr["boxes"] or fr["pos"]):
            gh = self._ghost_fractions()                 # between two picked frames: look where the subject probably is
            if gh and (gh["boxes"] or gh["pos"]):
                fr = gh
        has_sel = bool(fr["boxes"] or fr["pos"])
        prompt = (prm.get("prompt") or "").strip()
        if not has_sel and (not prompt or self.keys):
            # nothing to look for here (when other frames carry the picked subject, the text prompt is not used)
            self.canvas.set_highlight(None)
            self._req = -1
            self.engine_lbl.setText("")
            return
        img =self.engine.save_frame(self.loader.frames[max(0, min(self.cur, len(self.loader.frames) - 1))])
        self._req = self.engine.request(image=img, prompt="" if has_sel else prompt, sel=fr,
                                        threshold=prm.get("threshold", 0.5), refine=prm.get("refine", 2),
                                        grow=0, feather=0)
        self._wait_base = "Looking…"
        self._t_req = time.time()
        self.engine_lbl.setText(self._wait_base)
        self.wait_timer.start()

    def _wait_tick(self):
        if self._req < 0:
            self.wait_timer.stop()
            return
        t = int(time.time() - self._t_req)
        base = self._wait_base
        if t >= 3:
            base += "  %d s" % t
        if t >= 40:
            base += "  (the first one after opening can take a minute; later ones are quick)"
        self.engine_lbl.setText(base)

    def _on_result(self, m):
        if m.get("id") != self._req:
            return
        self.wait_timer.stop()
        pm = QPixmap(m.get("overlay", ""))
        self.canvas.set_highlight(pm if not pm.isNull() else None)
        n = int(m.get("count", 0))
        self.engine_lbl.setText("%d object%s selected  ·  %.1f s" % (n, "" if n == 1 else "s", m.get("ms", 0) / 1000.0)
                                if n else "Nothing selected here yet")

    def _on_engine_failed(self, text):
        self.wait_timer.stop()
        self._req = -1
        self.engine_lbl.setText("Live highlight unavailable: %s" % (text.splitlines()[0] if text else "error"))
        self.canvas.set_highlight(None)

    def _on_engine_state(self, st):
        if st == "starting":
            self.engine_lbl.setText("Warming up the AI engine…")
        elif st == "off" and self.live:
            self.engine_lbl.setText("")

    def _on_engine_status(self, text):
        if text:
            self._wait_base = text
            self.engine_lbl.setText(text)

    # ---- keyboard
    def keyPressEvent(self, e):
        k = e.key()
        step = 10 if e.modifiers() & Qt.ShiftModifier else 1
        if k == Qt.Key_Space:
            self.toggle_play()
        elif k == Qt.Key_Left:
            self._step(-step)
        elif k == Qt.Key_Right:
            self._step(step)
        elif k in (Qt.Key_I, Qt.Key_BracketLeft):
            self.timeline.set_in(self.cur)
        elif k in (Qt.Key_O, Qt.Key_BracketRight):
            self.timeline.set_out(self.cur)
        elif k == Qt.Key_Home:
            self._seek(self.timeline.a)
        elif k == Qt.Key_End:
            self._seek(self.timeline.b)
        elif k == Qt.Key_B:
            self._set_tool("brush_pos" if self.canvas.mode == "point" else "point")
        elif k == Qt.Key_Z and e.modifiers() & Qt.ControlModifier:
            self.canvas.undo()
        else:
            super().keyPressEvent(e)

    def _done(self):
        self._store_current()
        tl = self.timeline
        sel = None
        if self.keys:
            bad = [f for f in self.keys if not (tl.a <= f <= tl.b)]
            if bad:
                self.warn.setStyleSheet("color: %s; background: transparent;" % theme.css("danger"))
                self.warn.setText("A frame you picked the subject on (%s) is outside the chosen section. "
                                  "Drag the ends of the bar to include it." % fmt_time(bad[0], self.fps))
                return
            ordered = sorted(self.keys)
            aspect = self.canvas.orig[1] / float(self.canvas.orig[0])
            picks = []
            for f in ordered:
                d = fractions_to_selection(state_to_fractions(self.keys[f], aspect), self.canvas.orig)
                d["frame"] = int(f)
                if d["boxes"] or d["pos"]:
                    picks.append(d)
            if picks:
                sel = dict(picks[0])
                if len(picks) > 1:
                    sel["extra"] = picks[1:]
            elif self.keys:
                self.warn.setStyleSheet("color: %s; background: transparent;" % theme.css("danger"))
                self.warn.setText("Add a box, a point or a brush stroke that marks your subject (red marks alone are not enough).")
                return
        full = (tl.a == 0 and tl.b >= tl.n - 1)
        self.done.emit({"trim": None if full else {"start": int(tl.a), "end": int(tl.b)},
                        "selection": sel, "frames": tl.n, "frame": int(self.cur)})
        self.close_overlay()
