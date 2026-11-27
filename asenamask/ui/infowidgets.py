"""Small, clean info widgets for the Home page: clock, calendar, system meters and an activity counter."""
import datetime
import math
import ctypes
import os
import shutil
import subprocess
import threading
import time

from PySide6.QtCore import Qt, QRectF, QTimer, QObject, Signal, QPointF, QVariantAnimation
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QLinearGradient
from PySide6.QtWidgets import QWidget

from .theme import theme
from .widgets import Card
from . import glass


def _acc():
    return theme.col("accent"), theme.col("accent2")


class ClockWidget(Card):
    """Large time and the date, like a desktop gadget."""

    def __init__(self, settings, parent=None):
        super().__init__(parent, radius=20)
        self.s = settings
        self.setMinimumHeight(150)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update)
        self.timer.start()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        now = time.localtime()
        r = QRectF(self.rect())
        h24 = bool(self.s.get("clock_24h"))
        hh = now.tm_hour if h24 else (now.tm_hour % 12 or 12)
        main = "%02d:%02d" % (hh, now.tm_min) if h24 else "%d:%02d" % (hh, now.tm_min)
        p.setPen(theme.col("text"))
        p.setFont(theme.font(34, QFont.Light if theme.glass else QFont.DemiBold))
        p.drawText(QRectF(r.left() + 18, r.top() + 14, r.width() - 36, 56), Qt.AlignLeft | Qt.AlignVCenter, main)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(main)
        p.setFont(theme.font(11, QFont.Normal))
        p.setPen(theme.col("sub"))
        if not h24:
            p.drawText(QRectF(r.left() + 24 + w, r.top() + 34, 60, 30), Qt.AlignLeft | Qt.AlignVCenter,
                       "AM" if now.tm_hour < 12 else "PM")
        p.setFont(theme.font(10, QFont.Normal))
        p.drawText(QRectF(r.left() + 18, r.top() + 74, r.width() - 36, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   time.strftime("%A, %d %B %Y", now))
        # day progress line
        frac = (now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec) / 86400.0
        bar = QRectF(r.left() + 18, r.bottom() - 30, r.width() - 36, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 50) if theme.name == "dark" else QColor(0, 0, 0, 30))
        p.drawRoundedRect(bar, 3, 3)
        a1, a2 = _acc()
        g = QLinearGradient(bar.topLeft(), bar.topRight())
        g.setColorAt(0, a1)
        g.setColorAt(1, a2)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(bar.left(), bar.top(), max(6.0, bar.width() * frac), bar.height()), 3, 3)
        p.setFont(theme.font(8, QFont.Normal))
        p.setPen(theme.col("sub"))
        p.drawText(QRectF(r.left() + 18, r.bottom() - 24, r.width() - 36, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "%d%% of today" % int(frac * 100))


# ---------------------------------------------------------------- system numbers
def _ram():
    """(used_gb, total_gb) of system memory, or None."""
    try:
        if os.name == "nt":
            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tot", ctypes.c_ulonglong),
                            ("av", ctypes.c_ulonglong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                            ("tv", ctypes.c_ulonglong), ("av2", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
            m = MS()
            m.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return (m.tot - m.av) / 2 ** 30, m.tot / 2 ** 30
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                info[k] = int(v.split()[0]) * 1024
        return (info["MemTotal"] - info["MemAvailable"]) / 2 ** 30, info["MemTotal"] / 2 ** 30
    except Exception:
        return None


def _gpu():
    """(used_gb, total_gb) of video memory via nvidia-smi, or None."""
    try:
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=4, **kw).stdout.strip().splitlines()[0]
        u, t = [float(x) for x in out.split(",")]
        return u / 1024.0, t / 1024.0
    except Exception:
        return None


class _Poll(QObject):
    got = Signal(object)


class MetersWidget(Card):
    """Video memory, system memory and free disk space as three slim bars. Polled only while visible."""

    def __init__(self, settings, parent=None):
        super().__init__(parent, radius=20)
        self.s = settings
        self.setMinimumHeight(150)
        self.vals = {"gpu": None, "ram": None, "disk": None}
        self._poll = _Poll()
        self._poll.got.connect(self._set)
        self.timer = QTimer(self)
        self.timer.setInterval(4000)
        self.timer.timeout.connect(self.refresh)
        self._busy = False
        self._old = {}
        self._t = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(800)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._step)

    def _step(self, v):
        self._t = float(v)
        self.update()

    def showEvent(self, e):
        self.refresh()
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        folder = self.s.get("out_dir") or self.s.get("last_dir") or os.path.expanduser("~")

        def work():
            d = None
            try:
                u = shutil.disk_usage(folder if os.path.isdir(folder) else os.path.expanduser("~"))
                d = ((u.total - u.free) / 2 ** 30, u.total / 2 ** 30)
            except Exception:
                pass
            self._poll.got.emit({"gpu": _gpu(), "ram": _ram(), "disk": d})
        threading.Thread(target=work, daemon=True).start()

    def _set(self, v):
        self._busy = False
        for k, val in self.vals.items():
            self._old[k] = max(0.0, min(1.0, val[0] / val[1])) if val and val[1] > 0 else 0.0
        self.vals = v
        self._anim.stop()
        self._anim.start()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(16, 10, -16, -8)
        p.setPen(theme.col("sub"))
        f = theme.font(8, QFont.DemiBold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.3)
        p.setFont(f)
        p.drawText(QRectF(r.left(), r.top(), r.width(), 18), Qt.AlignLeft | Qt.AlignVCenter, "THIS PC")
        a1, a2 = _acc()
        items = (("Video", "gpu"), ("Memory", "ram"), ("Disk", "disk"))
        cw = r.width() / 3.0
        top = r.top() + 20
        d = min(cw - 12, r.height() - 20 - 22)
        t = self._t
        for i, (name, key) in enumerate(items):
            v = self.vals.get(key)
            old = self._old.get(key, 0.0)
            tgt = (max(0.0, min(1.0, v[0] / v[1])) if v and v[1] > 0 else 0.0)
            frac = old + (tgt - old) * t
            c = QPointF(r.left() + cw * i + cw / 2, top + d / 2)
            ring = QRectF(c.x() - d / 2 + 4, c.y() - d / 2 + 4, d - 8, d - 8)
            pen = QPen(QColor(255, 255, 255, 55) if theme.name == "dark" else QColor(0, 0, 0, 36), 6)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawArc(ring, 0, 360 * 16)
            if v and frac > 0.003:
                col = theme.col("danger") if frac > 0.9 else (a1 if i != 1 else a2)
                pen = QPen(col, 6)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawArc(ring, 90 * 16, int(-360 * 16 * frac))
            p.setPen(theme.col("text"))
            p.setFont(theme.font(11, QFont.DemiBold))
            p.drawText(QRectF(ring.left(), ring.top(), ring.width(), ring.height()), Qt.AlignCenter,
                       ("%d%%" % round(frac * 100)) if v else "n/a")
            p.setPen(theme.col("sub"))
            p.setFont(theme.font(8, QFont.Normal))
            sub = name if not v else "%s  %.0f/%.0f GB" % (name, v[0], v[1])
            p.drawText(QRectF(r.left() + cw * i, top + d + 2, cw, 18), Qt.AlignCenter, sub)


class WeekWidget(Card):
    """Cutouts made over the last seven days as glossy bars, with the running totals underneath."""

    def __init__(self, parent=None):
        super().__init__(parent, radius=20)
        self.setMinimumHeight(150)
        self.days = {}
        self.jobs = 0
        self.frames = 0

    def set_data(self, jobs, frames, days):
        self.jobs, self.frames, self.days = int(jobs or 0), int(frames or 0), dict(days or {})
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(16, 10, -16, -8)
        today = datetime.date.today()
        keys = [(today - datetime.timedelta(days=6 - i)) for i in range(7)]
        vals = [int(self.days.get(k.isoformat(), 0)) for k in keys]
        total = sum(vals)
        f = theme.font(8, QFont.DemiBold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.3)
        p.setFont(f)
        p.setPen(theme.col("sub"))
        p.drawText(QRectF(r.left(), r.top(), r.width(), 18), Qt.AlignLeft | Qt.AlignVCenter, "THIS WEEK")
        p.setPen(theme.col("text"))
        p.setFont(theme.font(10, QFont.DemiBold))
        p.drawText(QRectF(r.left(), r.top(), r.width(), 18), Qt.AlignRight | Qt.AlignVCenter,
                   "%d cutout%s" % (total, "" if total == 1 else "s"))
        a1, a2 = _acc()
        base = r.bottom() - 34
        area_h = base - (r.top() + 26)
        mx = max(max(vals), 3)
        cw = r.width() / 7.0
        bw = min(22.0, cw * 0.56)
        for i, v in enumerate(vals):
            x = r.left() + i * cw + (cw - bw) / 2
            track = QRectF(x, r.top() + 26, bw, area_h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 36) if theme.name == "dark" else QColor(0, 0, 0, 22))
            p.drawRoundedRect(track, bw / 2, bw / 2)
            if v:
                h = max(bw, area_h * v / float(mx))
                bar = QRectF(x, base - h, bw, h)
                g = QLinearGradient(bar.topLeft(), bar.bottomLeft())
                g.setColorAt(0, a2 if i == 6 else a1.lighter(125))
                g.setColorAt(1, a1)
                p.setBrush(QBrush(g))
                p.drawRoundedRect(bar, bw / 2, bw / 2)
                if theme.glass:
                    gl = QRectF(bar.left() + 2, bar.top() + 2, bar.width() - 4, bar.height() * 0.42)
                    p.setBrush(QColor(255, 255, 255, 110))
                    p.drawRoundedRect(gl, bw / 2 - 2, bw / 2 - 2)
                p.setPen(theme.col("text"))
                p.setFont(theme.font(8, QFont.DemiBold))
                p.drawText(QRectF(x - 6, bar.top() - 14, bw + 12, 13), Qt.AlignCenter, str(v))
            p.setPen(theme.col("text") if i == 6 else theme.col("sub"))
            p.setFont(theme.font(8, QFont.DemiBold if i == 6 else QFont.Normal))
            p.drawText(QRectF(r.left() + i * cw, base + 3, cw, 14), Qt.AlignCenter, keys[i].strftime("%a")[:2])
        p.setPen(theme.col("sub"))
        p.setFont(theme.font(8, QFont.Normal))
        p.drawText(QRectF(r.left(), r.bottom() - 15, r.width(), 15), Qt.AlignLeft | Qt.AlignVCenter,
                   "All time: {:,} cutouts, {:,} frames".format(self.jobs, self.frames))


class StatusOrb(QWidget):
    """A small glowing orb for the AI engine: dim when asleep, pulsing while warming up, green when ready."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 44)
        self.state = "off"
        self._ph = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)

    def set_state(self, st):
        self.state = st
        self.update()

    def showEvent(self, e):
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def _tick(self):
        self._ph = (self._ph + (0.045 if self.state == "starting" else 0.018)) % 1.0
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        pulse = 0.5 - 0.5 * math.cos(self._ph * 6.2832)
        if self.state == "ready":
            col, k = theme.col("ok"), 0.5 + 0.5 * pulse
        elif self.state == "starting":
            col, k = theme.col("accent2"), 0.4 + 0.6 * pulse
        elif self.state == "error":
            col, k = theme.col("danger"), 1.0
        else:
            col, k = theme.col("sub"), 0.35
        from PySide6.QtGui import QRadialGradient
        g = QRadialGradient(c, 21)
        g.setColorAt(0, QColor(col.red(), col.green(), col.blue(), int(120 * k)))
        g.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(c, 21, 21)
        if theme.glass:
            glass.orb(p, c, 22, col if self.state != "off" else QColor(120, 170, 210))
        else:
            og = QRadialGradient(QPointF(c.x() - 3, c.y() - 4), 14)
            og.setColorAt(0, col.lighter(160))
            og.setColorAt(1, col.darker(130))
            p.setBrush(QBrush(og))
            p.drawEllipse(c, 9, 9)
