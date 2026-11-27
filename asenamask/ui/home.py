"""Classic (Aurora) home page: big drop area, status card, widgets, 'what's new' and the recent projects."""
import os
import random

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QVariantAnimation
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPixmap, QPainterPath, QLinearGradient, QBrush
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QFrame, QFileDialog)

from .. import videoinfo, projects
from .theme import theme, mix
from . import glass
from .widgets import GlowButton, Card, HoverMixin, title_label
from .welcome import LogoMark, TIPS
from .infowidgets import ClockWidget, WeekWidget, MetersWidget, StatusOrb

FILTER = "Videos and images (%s)" % " ".join("*" + e for e in videoinfo.SUPPORTED + videoinfo.IMAGE_EXTS)
ACCEPT = tuple(videoinfo.SUPPORTED + videoinfo.IMAGE_EXTS)


def _clip_files(urls):
    out = []
    for u in urls:
        f = u.toLocalFile()
        if f and (os.path.isdir(f) or os.path.splitext(f)[1].lower() in ACCEPT):
            out.append(f)
    return out


class HomeDrop(HoverMixin, QWidget):
    chosen = Signal(str)
    chosen_many = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_hover()
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(420, 230)
        self._drag = 0.0
        self._dash = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(10.0)
        self._anim.setDuration(900)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._set_dash)
        theme.changed.connect(self.update)

    def _set_dash(self, v):
        self._dash = float(v)
        self.update()

    def enterEvent(self, e):
        self._anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._anim.stop()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            f, _ = QFileDialog.getOpenFileName(self.window(), "Choose a video or image", "", FILTER + ";;All files (*.*)")
            if f:
                self.chosen.emit(f)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag = 1.0
            self.update()

    def dragLeaveEvent(self, e):
        self._drag = 0.0
        self.update()

    def dropEvent(self, e):
        self._drag = 0.0
        self.update()
        good = _clip_files(e.mimeData().urls())
        if len(good) == 1:
            self.chosen.emit(good[0])
        elif good:
            self.chosen_many.emit(good)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        hv = max(self._h, self._drag)
        a1, a2 = theme.col("accent"), theme.col("accent2")
        if theme.glass:
            glass.panel(p, r.adjusted(1, 1, -1, -1), 24, strong=False, tint=a1 if hv > 0.05 else None)
            pen = QPen(QColor(255, 255, 255, int(150 + 90 * hv)), 1.8)
            pen.setStyle(Qt.DashLine)
            pen.setDashPattern([4, 4])
            pen.setDashOffset(self._dash)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(14, 14, -14, -14), 16, 16)
            return self._paint_drop_content(p, r, hv, a1)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, mix(QColor(a1.red(), a1.green(), a1.blue(), 34), QColor(a1.red(), a1.green(), a1.blue(), 70), hv))
        g.setColorAt(1, mix(QColor(a2.red(), a2.green(), a2.blue(), 16), QColor(a2.red(), a2.green(), a2.blue(), 42), hv))
        p.setBrush(QBrush(g))
        pen = QPen(mix(theme.col("card_border"), a1, hv), 1.6)
        pen.setStyle(Qt.DashLine)
        pen.setDashPattern([5, 5])
        pen.setDashOffset(self._dash)
        p.setPen(pen)
        p.drawRoundedRect(r, 22, 22)
        self._paint_drop_content(p, r, hv, a1)

    def _paint_drop_content(self, p, r, hv, a1):
        cx, cy = r.center().x(), r.center().y()
        # arrow into a tray
        ic = QPen(mix(theme.col("sub"), a1, 0.5 + 0.5 * hv), 2.4)
        ic.setCapStyle(Qt.RoundCap)
        ic.setJoinStyle(Qt.RoundJoin)
        p.setPen(ic)
        p.setBrush(Qt.NoBrush)
        p.drawLine(int(cx), int(cy - 52), int(cx), int(cy - 14))
        p.drawLine(int(cx - 12), int(cy - 26), int(cx), int(cy - 14))
        p.drawLine(int(cx + 12), int(cy - 26), int(cx), int(cy - 14))
        tray = QPainterPath()
        tray.moveTo(cx - 24, cy - 6)
        tray.lineTo(cx - 24, cy + 6)
        tray.lineTo(cx + 24, cy + 6)
        tray.lineTo(cx + 24, cy - 6)
        p.drawPath(tray)
        p.setFont(theme.font(15, QFont.DemiBold))
        p.setPen(theme.col("text"))
        p.drawText(QRectF(r.left(), cy + 18, r.width(), 30), Qt.AlignHCenter | Qt.AlignVCenter,
                   "Drop a video, image or folder here")
        p.setFont(theme.font(10, QFont.Normal))
        p.setPen(theme.col("sub"))
        p.drawText(QRectF(r.left(), cy + 48, r.width(), 22), Qt.AlignHCenter | Qt.AlignVCenter,
                   "or click to browse   ·   drop several clips to start a batch queue")


class RecentCard(HoverMixin, QWidget):
    opened = Signal(str)
    removed = Signal(str)
    W, H = 210, 178

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self._init_hover()
        self.e = entry
        self.path = entry["path"]
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(self.path)
        self.pm = None
        tp = projects.ProjectStore.thumb_path_for(entry)
        if tp and os.path.isfile(tp):
            pm = QPixmap(tp)
            self.pm = pm if not pm.isNull() else None
        theme.changed.connect(self.update)

    def _x_rect(self):
        return QRectF(self.W - 30, 8, 22, 22)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._h > 0.05 and self._x_rect().contains(e.position()):
            self.removed.emit(self.path)
        else:
            self.opened.emit(self.path)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        a1 = theme.col("accent")
        if theme.glass:
            glass.panel(p, r, 16, strong=self._h > 0.3)
        else:
            p.setBrush(mix(theme.col("card"), QColor(a1.red(), a1.green(), a1.blue(), 40), self._h))
            p.setPen(QPen(mix(theme.col("card_border"), a1, 0.2 + 0.6 * self._h), 1))
            p.drawRoundedRect(r, 16, 16)
        tr = QRectF(r.left() + 8, r.top() + 8, r.width() - 16, 104)
        clip = QPainterPath()
        clip.addRoundedRect(tr, 10, 10)
        p.save()
        p.setClipPath(clip)
        if self.pm is not None:
            s = max(tr.width() / self.pm.width(), tr.height() / self.pm.height())
            w, h = self.pm.width() * s, self.pm.height() * s
            p.drawPixmap(QRectF(tr.center().x() - w / 2, tr.center().y() - h / 2, w, h), self.pm,
                         QRectF(self.pm.rect()))
        else:
            p.fillRect(tr, QColor(0, 0, 0, 70))
        p.restore()
        f = QFont("Segoe UI", 10)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(theme.col("text"))
        name = os.path.basename(self.path.rstrip("/\\")) or self.path
        fm = p.fontMetrics()
        p.drawText(QRectF(r.left() + 10, r.top() + 116, r.width() - 20, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(name, Qt.ElideMiddle, int(r.width() - 24)))
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(theme.col("sub"))
        p.drawText(QRectF(r.left() + 10, r.top() + 138, r.width() - 20, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   projects.describe(self.e))
        if self._h > 0.05:                               # little "remove from list" cross
            xr = self._x_rect()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, int(150 * self._h)))
            p.drawEllipse(xr)
            pen = QPen(QColor(255, 255, 255, int(230 * self._h)), 1.6)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            c = xr.center()
            p.drawLine(QPointF(c.x() - 4, c.y() - 4), QPointF(c.x() + 4, c.y() + 4))
            p.drawLine(QPointF(c.x() + 4, c.y() - 4), QPointF(c.x() - 4, c.y() + 4))


STEPS = [
    ("1", "Open a clip", "Drop a video, an image or a whole folder."),
    ("2", "Trim & pick", "Trim the clip, then click the subject you want to keep."),
    ("3", "Choose a look", "Pick the output format, a background and the edge quality."),
    ("4", "Save", "Your cutout is made on your own GPU. Nothing is uploaded."),
]


class HomeClassic(QWidget):
    open_clip = Signal(str)
    open_many = Signal(list)
    forget = Signal(str)
    dismiss_news = Signal()
    open_wrapped = Signal()
    dismiss_wrapped = Signal()
    queue_clicked = Signal()

    COLS = 4
    MAXW = 1180

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 6, 26, 18)
        root.setSpacing(0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.viewport().setAutoFillBackground(False)
        outer = QWidget()
        outer.setAutoFillBackground(False)
        oh = QHBoxLayout(outer)
        oh.setContentsMargins(0, 0, 8, 0)
        body = QWidget()
        body.setAutoFillBackground(False)
        body.setMaximumWidth(self.MAXW)
        oh.addStretch(1)
        oh.addWidget(body, 100)
        oh.addStretch(1)
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(16)
        sc.setWidget(outer)
        root.addWidget(sc)
        self._secs = []

        # ---- hero
        hero = Card(radius=24)
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(26, 20, 26, 20)
        hl.setSpacing(20)
        hl.addWidget(LogoMark(86), 0, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.hello = title_label("Welcome", 26, QFont.Bold)
        col.addWidget(self.hello)
        sub = title_label("Remove a video's background on your own graphics card. Nothing leaves your PC.", 11,
                          QFont.Normal, sub=True)
        sub.setWordWrap(True)
        col.addWidget(sub)
        hl.addLayout(col, 1)
        for text, kind, slot in (("Open a video", "primary", self._browse_file), ("Open a folder", "ghost", self._browse_dir),
                                 ("Batch queue", "ghost", self.queue_clicked.emit)):
            b = GlowButton(text, kind)
            b.setMinimumHeight(44)
            b.setMinimumWidth(138)
            b.clicked.connect(lambda _=False, f=slot: f())
            hl.addWidget(b, 0, Qt.AlignVCenter)
        v.addWidget(hero)

        # ---- widgets
        strip = QHBoxLayout()
        strip.setSpacing(14)
        strip.addWidget(ClockWidget(settings), 1)
        strip.addWidget(MetersWidget(settings), 1)
        self.week = WeekWidget()
        strip.addWidget(self.week, 1)
        v.addLayout(strip)

        # ---- drop + status / stats
        top = QHBoxLayout()
        top.setSpacing(16)
        self.top_row = top
        self.drop = HomeDrop()
        self.drop.chosen.connect(self.open_clip)
        self.drop.chosen_many.connect(self.open_many)
        top.addWidget(self.drop, 3)

        side = QVBoxLayout()
        side.setSpacing(16)
        self.status = Card(radius=20)
        self.status.setMinimumWidth(300)
        sl = QVBoxLayout(self.status)
        sl.setContentsMargins(20, 16, 20, 16)
        sl.setSpacing(6)
        sl.addWidget(self._sec_small("YOUR PC"))
        self.gpu_l = title_label("Checking your graphics card…", 11, QFont.DemiBold)
        self.gpu_l.setWordWrap(True)
        sl.addWidget(self.gpu_l)
        self.vram_l = title_label("", 9, QFont.Normal, sub=True)
        self.vram_l.setWordWrap(True)
        sl.addWidget(self.vram_l)
        sl.addSpacing(4)
        sl.addWidget(self._sec_small("AI ENGINE"))
        er = QHBoxLayout()
        er.setSpacing(10)
        self.orb = StatusOrb()
        er.addWidget(self.orb, 0, Qt.AlignTop)
        self.engine_l = title_label("Asleep. It wakes up when you need it and frees your GPU when idle.", 10,
                                    QFont.Normal)
        self.engine_l.setWordWrap(True)
        er.addWidget(self.engine_l, 1)
        sl.addLayout(er)
        side.addWidget(self.status, 1)

        top.addLayout(side, 2)
        v.addLayout(top)

        # ---- continue strip
        self.cont = Card(radius=18)
        cl = QHBoxLayout(self.cont)
        cl.setContentsMargins(20, 12, 16, 12)
        self.cont_lbl = title_label("Nothing opened yet.", 10, QFont.Normal, sub=True)
        self.cont_lbl.setTextFormat(Qt.PlainText)
        cl.addWidget(self.cont_lbl, 1)
        self.cont_btn = GlowButton("Continue last project", "chip")
        self.cont_btn.setMinimumHeight(36)
        self.cont_btn.clicked.connect(self._continue)
        cl.addWidget(self.cont_btn)
        v.addWidget(self.cont)

        # ---- news
        self.news = Card(radius=18)
        nl = QHBoxLayout(self.news)
        nl.setContentsMargins(20, 14, 16, 14)
        ncol = QVBoxLayout()
        ncol.setSpacing(3)
        self.news_title = title_label("What's new", 11, QFont.Bold)
        self.news_text = title_label("", 10, QFont.Normal, sub=True)
        self.news_text.setWordWrap(True)
        ncol.addWidget(self.news_title)
        ncol.addWidget(self.news_text)
        nl.addLayout(ncol, 1)
        ok = GlowButton("Got it", "chip")
        ok.clicked.connect(self._news_ok)
        nl.addWidget(ok, 0, Qt.AlignTop)
        self.news.hide()
        v.addWidget(self.news)
        v.addWidget(self._wrapped_card())

        # ---- how it works
        v.addWidget(self._sec("How it works"))
        steps = QHBoxLayout()
        steps.setSpacing(14)
        for n, t, d in STEPS:
            c = Card(radius=18)
            c.setMinimumHeight(112)
            cv = QVBoxLayout(c)
            cv.setContentsMargins(18, 14, 18, 14)
            cv.setSpacing(4)
            num = title_label(n, 20, QFont.Bold)
            num.setStyleSheet("color: %s; background: transparent;" % theme.css("accent"))
            num.setProperty("sub", None)
            self._accent_labels = getattr(self, "_accent_labels", []) + [num]
            cv.addWidget(num)
            cv.addWidget(title_label(t, 11, QFont.DemiBold))
            dl = title_label(d, 9, QFont.Normal, sub=True)
            dl.setWordWrap(True)
            cv.addWidget(dl)
            cv.addStretch(1)
            steps.addWidget(c, 1)
        v.addLayout(steps)

        # ---- tip
        self.tipcard = Card(radius=18)
        tp = QHBoxLayout(self.tipcard)
        tp.setContentsMargins(20, 14, 16, 14)
        tcol = QVBoxLayout()
        tcol.setSpacing(3)
        tcol.addWidget(self._sec_small("TIP"))
        self.tip_l = title_label("", 10, QFont.Normal)
        self.tip_l.setWordWrap(True)
        tcol.addWidget(self.tip_l)
        tp.addLayout(tcol, 1)
        nb = GlowButton("Next tip", "chip")
        nb.clicked.connect(self._next_tip)
        tp.addWidget(nb, 0, Qt.AlignVCenter)
        v.addWidget(self.tipcard)
        self._tip_i = random.randrange(len(TIPS))
        self.tip_l.setText(TIPS[self._tip_i])

        # ---- recent
        self.recent_title = self._sec("Recent")
        v.addWidget(self.recent_title)
        self.grid_host = QWidget()
        self.grid_host.setAutoFillBackground(False)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)
        v.addWidget(self.grid_host)
        self.empty = Card(radius=18)
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(20, 22, 20, 22)
        e1 = title_label("No recent clips yet", 12, QFont.DemiBold)
        e1.setAlignment(Qt.AlignCenter)
        e2 = title_label("Clips you open show up here with their trim and picked subject saved.", 10, QFont.Normal,
                         sub=True)
        e2.setAlignment(Qt.AlignCenter)
        el.addWidget(e1)
        el.addWidget(e2)
        v.addWidget(self.empty)
        v.addStretch(1)
        self._last = None
        self._cards = []
        theme.changed.connect(self._apply_look)
        self._apply_look()

    # ----- small builders
    def _sec(self, text):
        l = title_label(text, 14, QFont.Bold)
        l.setProperty("sec", text)
        self._secs.append(l)
        return l

    def _sec_small(self, text):
        l = title_label(text, 8, QFont.DemiBold, sub=True)
        f = l.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.3)
        l.setFont(f)
        return l

    def _stat(self, lay, caption):
        n = title_label("0", 20, QFont.Bold)
        lay.addWidget(n)
        lay.addWidget(title_label(caption, 9, QFont.Normal, sub=True))
        return n

    def _apply_look(self):
        from PySide6.QtWidgets import QBoxLayout
        self.top_row.setDirection(QBoxLayout.RightToLeft if theme.look == "retro" else QBoxLayout.LeftToRight)
        caps = theme.param("caps")
        for l in self._secs:
            t = l.property("sec")
            l.setText(t.upper() if caps else t)
            f = l.font()
            f.setLetterSpacing(QFont.AbsoluteSpacing, 3 if caps else 0)
            l.setFont(f)
        for l in getattr(self, "_accent_labels", []):
            l.setStyleSheet("color: %s; background: transparent;" % theme.css("accent"))

    # ----- actions
    def _browse_file(self):
        f, _ = QFileDialog.getOpenFileName(self.window(), "Choose a video or image", "", FILTER + ";;All files (*.*)")
        if f:
            self.open_clip.emit(f)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self.window(), "Choose a folder of clips or frames")
        if d:
            self.open_many.emit([d])

    def _next_tip(self):
        self._tip_i = (self._tip_i + 1) % len(TIPS)
        self.tip_l.setText(TIPS[self._tip_i])

    # ----- data in
    def set_name(self, name):
        self.hello.setText(("Welcome back, %s" % name) if name else "Welcome back")

    def set_stats(self, jobs, frames, days=None):
        self.week.set_data(jobs, frames, days)

    def set_recent(self, entries):
        for c in self._cards:
            self.grid.removeWidget(c)
            c.setParent(None)
            c.deleteLater()
        self._cards = []
        for i, e in enumerate(entries):
            c = RecentCard(e)
            c.opened.connect(self.open_clip)
            c.removed.connect(self.forget)
            self.grid.addWidget(c, i // self.COLS, i % self.COLS, Qt.AlignLeft | Qt.AlignTop)
            self._cards.append(c)
        has = bool(entries)
        self.empty.setVisible(not has)
        self.grid_host.setVisible(has)
        self._last = entries[0] if has else None
        self.cont.setVisible(has)
        self.cont_btn.setEnabled(has)
        self.cont_lbl.setText(("Last project:  " + os.path.basename(entries[0]["path"].rstrip("/\\"))) if has
                              else "Nothing opened yet.")

    def set_gpu(self, g):
        if g:
            self.gpu_l.setText(g["name"])
            self.vram_l.setText("%s GB video memory  ·  driver %s" % (g["vram_gb"], g["driver"]) if g.get("vram_gb")
                                else "")
            if "nvidia" not in g["name"].lower():
                self.vram_l.setText("Asena Mask is made for NVIDIA cards; this one may not work.")
        else:
            self.gpu_l.setText("No graphics card detected")
            self.vram_l.setText("Asena Mask needs an NVIDIA graphics card.")

    def set_engine(self, state):
        self.orb.set_state(state if state in ("off", "starting", "ready", "error") else "off")
        self.engine_l.setText({
            "off": "Asleep. It wakes up when you need it and frees your GPU when idle.",
            "starting": "Warming up…",
            "ready": "Ready. Live selection will answer in about a second.",
            "error": "Not available right now. If this keeps happening, copy the system info in Settings → About.",
        }.get(state, state))

    # ----- the Wrapped banner (first launch after the update, and when the developer publishes the community Wrapped)
    def _wrapped_card(self):
        card = Card(radius=18)
        nl = QHBoxLayout(card)
        nl.setContentsMargins(20, 12, 16, 12)
        col = QVBoxLayout()
        col.setSpacing(3)
        self.wr_title = title_label("Your Asena Wrapped", 11, QFont.Bold)
        self.wr_text = title_label("", 10, QFont.Normal, sub=True)
        self.wr_text.setWordWrap(True)
        col.addWidget(self.wr_title)
        col.addWidget(self.wr_text)
        nl.addLayout(col, 1)
        go = GlowButton("See it", "primary")
        self.wr_go = go
        go.setMinimumHeight(36)
        go.clicked.connect(self._wr_go)
        nl.addWidget(go, 0, Qt.AlignTop)
        later = GlowButton("Later", "chip")
        later.clicked.connect(self._wr_later)
        nl.addWidget(later, 0, Qt.AlignTop)
        card.hide()
        self.wrapped_card = card
        return card

    def show_wrapped(self, title, text, button="See it"):
        self.wr_go.setText(button)
        self.wr_title.setText(title)
        self.wr_text.setText(text)
        self.wrapped_card.show()

    def _wr_go(self):
        self.wrapped_card.hide()
        self.dismiss_wrapped.emit()
        self.open_wrapped.emit()

    def _wr_later(self):
        self.wrapped_card.hide()
        self.dismiss_wrapped.emit()

    def show_news(self, version, notes):
        self.news_title.setText("What's new in %s" % version)
        self.news_text.setText(notes)
        self.news.show()

    def _news_ok(self):
        self.news.hide()
        self.dismiss_news.emit()

    def _continue(self):
        if self._last:
            self.open_clip.emit(self._last["path"])
