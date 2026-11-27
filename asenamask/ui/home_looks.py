"""Home pages with their own layout for the Frutiger Aero and Retro looks (Aurora keeps home.HomeClassic)."""
import os
import random

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QScrollArea, QFrame)

from .. import videoinfo
from .home import HomeDrop, FILTER, _clip_files
from .homewidgets import GadgetRow, Thumb
from .infowidgets import ClockWidget, MetersWidget, WeekWidget, StatusOrb
from .psmenu import PsList
from .theme import theme
from .welcome import LogoMark, CubeLogo, TIPS, scrim
from .widgets import GlowButton, Card, title_label

ENGINE_TEXT = {
    "off": "Asleep. It wakes up when you need it and frees your GPU when idle.",
    "starting": "Warming up…",
    "ready": "Ready. Live selection answers in about a second.",
    "error": "Not available right now. Copy the system info in Settings → About if this keeps happening.",
}


class HomeBase(QWidget):
    open_clip = Signal(str)
    open_many = Signal(list)
    forget = Signal(str)
    dismiss_news = Signal()
    open_wrapped = Signal()
    dismiss_wrapped = Signal()
    queue_clicked = Signal()

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.s = settings
        self._last = None
        self._name = ""
        self._engine = "off"

    # ----- shared actions
    def _browse_file(self):
        f, _ = QFileDialog.getOpenFileName(self.window(), "Choose a video or image", "", FILTER + ";;All files (*.*)")
        if f:
            self.open_clip.emit(f)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self.window(), "Choose a folder of clips or frames")
        if d:
            self.open_many.emit([d])

    def _continue(self):
        if self._last:
            self.open_clip.emit(self._last["path"])

    def _news_card(self):
        card = Card(radius=18)
        nl = QHBoxLayout(card)
        nl.setContentsMargins(20, 12, 16, 12)
        col = QVBoxLayout()
        col.setSpacing(3)
        self.news_title = title_label("What's new", 11, QFont.Bold)
        self.news_text = title_label("", 10, QFont.Normal, sub=True)
        self.news_text.setWordWrap(True)
        col.addWidget(self.news_title)
        col.addWidget(self.news_text)
        nl.addLayout(col, 1)
        ok = GlowButton("Got it", "chip")
        ok.clicked.connect(self._news_ok)
        nl.addWidget(ok, 0, Qt.AlignTop)
        card.hide()
        self.news = card
        return card

    def show_news(self, version, notes):
        self.news_title.setText("What's new in %s" % version)
        self.news_text.setText(notes)
        self.news.show()

    def _news_ok(self):
        self.news.hide()
        self.dismiss_news.emit()

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

    # ----- data in (subclasses implement the _show_* hooks)
    def set_name(self, name):
        self._name = name or ""
        self._show_name()

    def set_recent(self, entries):
        self._last = entries[0] if entries else None
        self._show_recent(entries)

    def set_gpu(self, g):
        if g:
            detail = ("%s GB video memory  ·  driver %s" % (g["vram_gb"], g["driver"])) if g.get("vram_gb") else ""
            if "nvidia" not in g["name"].lower():
                detail = "Made for NVIDIA cards; this one may not work."
            self._show_gpu(g["name"], detail)
        else:
            self._show_gpu("No graphics card detected", "Asena Mask needs an NVIDIA graphics card.")

    def set_engine(self, state):
        self._engine = state if state in ("off", "starting", "ready", "error") else "off"
        self._show_engine(self._engine, ENGINE_TEXT.get(state, state))

    def set_stats(self, jobs, frames, days=None):
        self._show_stats(int(jobs or 0), int(frames or 0), days or {})

    # hooks
    def _show_name(self): ...
    def _show_recent(self, entries): ...
    def _show_gpu(self, name, detail): ...
    def _show_engine(self, state, text): ...
    def _show_stats(self, jobs, frames, days): ...


# ====================================================================== Frutiger Aero: a desktop of glass gadgets
class HomeAero(HomeBase):
    def __init__(self, settings=None, parent=None):
        super().__init__(settings, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 6, 26, 16)
        root.setSpacing(14)
        root.addWidget(self._news_card())
        root.addWidget(self._wrapped_card())

        mid = QHBoxLayout()
        mid.setSpacing(18)

        # left: a start-menu panel
        left = Card(radius=24)
        left.setFixedWidth(276)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 18, 14, 16)
        lv.setSpacing(2)
        lv.addWidget(self._small("START"))
        self.r_video = GadgetRow("project", "Open a video or image")
        self.r_video.clicked.connect(self._browse_file)
        self.r_folder = GadgetRow("folder", "Open a folder")
        self.r_folder.clicked.connect(self._browse_dir)
        self.r_queue = GadgetRow("queue", "Batch queue")
        self.r_queue.clicked.connect(self.queue_clicked)
        self.r_cont = GadgetRow("clock", "Continue last project", "Nothing opened yet")
        self.r_cont.clicked.connect(self._continue)
        for r in (self.r_video, self.r_folder, self.r_queue, self.r_cont):
            lv.addWidget(r)
        lv.addSpacing(14)
        lv.addWidget(self._small("YOUR PC"))
        self.gpu_l = title_label("Checking your graphics card…", 10, QFont.Normal)
        self.gpu_l.setWordWrap(True)
        self.vram_l = title_label("", 9, QFont.Normal, sub=True)
        self.vram_l.setWordWrap(True)
        lv.addWidget(self.gpu_l)
        lv.addWidget(self.vram_l)
        lv.addSpacing(8)
        er = QHBoxLayout()
        self.orb = StatusOrb()
        er.addWidget(self.orb, 0, Qt.AlignTop)
        self.engine_l = title_label(ENGINE_TEXT["off"], 9, QFont.Normal, sub=True)
        self.engine_l.setWordWrap(True)
        er.addWidget(self.engine_l, 1)
        lv.addLayout(er)
        lv.addStretch(1)
        mid.addWidget(left)

        # centre: the logo, a greeting and the drop area
        cen = QVBoxLayout()
        cen.setSpacing(10)
        cen.addStretch(1)
        cen.addWidget(LogoMark(120), 0, Qt.AlignHCenter)
        self.hello = title_label("Welcome", 34, QFont.Light)
        self.hello.setAlignment(Qt.AlignCenter)
        cen.addWidget(self.hello)
        sub = title_label("Remove a video's background on your own graphics card. Nothing leaves your PC.", 11,
                          QFont.Normal, sub=True)
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        cen.addWidget(sub)
        cen.addSpacing(6)
        self.drop = HomeDrop()
        self.drop.setMinimumSize(200, 220)
        self.drop.chosen.connect(self.open_clip)
        self.drop.chosen_many.connect(self.open_many)
        cen.addWidget(self.drop)
        cen.addStretch(1)
        mid.addLayout(cen, 1)

        # right: gadgets
        right = QVBoxLayout()
        right.setSpacing(14)
        for w in (ClockWidget(settings), MetersWidget(settings)):
            w.setFixedWidth(300)
            right.addWidget(w)
        self.week = WeekWidget()
        self.week.setFixedWidth(300)
        right.addWidget(self.week)
        right.addStretch(1)
        mid.addLayout(right)
        root.addLayout(mid, 1)

        # bottom: a dock with the recent clips
        self.dock = Card(radius=26)
        self.dock.setFixedHeight(124)
        dh = QHBoxLayout(self.dock)
        dh.setContentsMargins(20, 8, 20, 6)
        dh.setSpacing(12)
        dh.addWidget(self._small("RECENT"), 0, Qt.AlignVCenter)
        self.dock_row = QHBoxLayout()
        self.dock_row.setSpacing(10)
        dh.addLayout(self.dock_row)
        self.dock_empty = title_label("Clips you open show up here, with their trim and picked subject saved.", 10,
                                      QFont.Normal, sub=True)
        dh.addWidget(self.dock_empty)
        dh.addStretch(1)
        root.addWidget(self.dock)
        self._thumbs = []

    @staticmethod
    def _small(text):
        l = title_label(text, 8, QFont.DemiBold, sub=True)
        f = l.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.4)
        l.setFont(f)
        return l

    def _show_name(self):
        self.hello.setText(("Welcome back, %s" % self._name) if self._name else "Welcome back")

    def _show_gpu(self, name, detail):
        self.gpu_l.setText(name)
        self.vram_l.setText(detail)

    def _show_engine(self, state, text):
        self.orb.set_state(state)
        self.engine_l.setText(text)

    def _show_stats(self, jobs, frames, days):
        self.week.set_data(jobs, frames, days)

    def _show_recent(self, entries):
        for t in self._thumbs:
            self.dock_row.removeWidget(t)
            t.setParent(None)
            t.deleteLater()
        self._thumbs = []
        for e in entries[:9]:
            t = Thumb(e, 84, 74, "dock")
            t.opened.connect(self.open_clip)
            self.dock_row.addWidget(t)
            self._thumbs.append(t)
        self.dock_empty.setVisible(not entries)
        self.r_cont.setEnabled(bool(entries))
        self.r_cont.set_sub(os.path.basename(entries[0]["path"].rstrip("/\\")) if entries else "Nothing opened yet")


# ====================================================================== Retro: a console main menu
DESCRIPTIONS = (
    "Pick a video or an image. Trim it, click the subject you want to keep, and your GPU cuts out the rest.",
    "Choose a folder of videos or frames and process the whole lot in one go.",
    "Line up several clips and let them run one after another, even overnight.",
    "Go straight back to the last clip you worked on, with its trim and picked subject restored.",
)


class HomeRetro(HomeBase):
    def __init__(self, settings=None, parent=None):
        super().__init__(settings, parent)
        self.setAcceptDrops(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(46, 8, 46, 14)
        root.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(46)

        left = QVBoxLayout()
        left.setSpacing(2)
        self.title = title_label("ASENA MASK", 40, QFont.Light)
        f = self.title.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 9)
        self.title.setFont(f)
        trow = QHBoxLayout()
        trow.setSpacing(22)
        trow.addWidget(CubeLogo(104), 0, Qt.AlignVCenter)
        trow.addWidget(self.title, 0, Qt.AlignVCenter)
        trow.addStretch(1)
        left.addLayout(trow)
        self.hello = title_label("", 10, QFont.Normal, sub=True)
        f = self.hello.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        self.hello.setFont(f)
        left.addWidget(self.hello)
        left.addSpacing(26)
        self.menu = PsList(["Open a video", "Open a folder", "Batch queue", "Continue last project"], row_h=56,
                           sticky=False, size=13)
        self.menu.setMaximumWidth(420)
        self.menu.chosen.connect(self._menu_chosen)
        self.menu.hovered.connect(self._menu_hover)
        left.addWidget(self.menu)
        left.addStretch(1)
        top.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(14)
        right.addWidget(self._news_card())
        right.addWidget(self._wrapped_card())
        self.desc_card = Card(radius=14)
        self.desc_card.setMinimumHeight(120)
        dl = QVBoxLayout(self.desc_card)
        dl.setContentsMargins(22, 18, 22, 18)
        self.desc = title_label("", 11, QFont.Normal)
        self.desc.setWordWrap(True)
        dl.addWidget(self.desc)
        right.addWidget(self.desc_card)
        self.info_rows = {}
        for key, label in (("gpu", "GRAPHICS"), ("engine", "AI ENGINE"), ("stats", "SO FAR")):
            row = QHBoxLayout()
            row.setSpacing(12)
            k = title_label(label, 8, QFont.DemiBold, sub=True)
            kf = k.font()
            kf.setLetterSpacing(QFont.AbsoluteSpacing, 2.5)
            k.setFont(kf)
            k.setFixedWidth(96)
            v = title_label("", 10, QFont.Normal)
            v.setWordWrap(True)
            if key == "engine":
                self.orb = StatusOrb()
                self.orb.setFixedSize(30, 30)
                row.addWidget(k, 0, Qt.AlignTop)
                row.addWidget(self.orb, 0, Qt.AlignTop)
            else:
                row.addWidget(k, 0, Qt.AlignTop)
            row.addWidget(v, 1)
            self.info_rows[key] = v
            right.addLayout(row)
        self.tip = title_label("", 9, QFont.Normal, sub=True)
        self.tip.setWordWrap(True)
        right.addSpacing(6)
        right.addWidget(self.tip)
        right.addStretch(1)
        rw = QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(430)
        top.addWidget(rw)
        root.addLayout(top, 1)

        # recent clips as a film strip
        head = title_label("RECENT", 9, QFont.DemiBold)
        hf = head.font()
        hf.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        head.setFont(hf)
        root.addWidget(head)
        self.strip = QHBoxLayout()
        self.strip.setSpacing(14)
        self.strip.addStretch(1)
        root.addLayout(self.strip)
        self.strip_empty = title_label("Drop a video anywhere on this screen, or pick one from the menu.", 10,
                                       QFont.Normal, sub=True)
        root.addWidget(self.strip_empty)
        self._thumbs = []
        self._menu_hover(-1)
        self.tip.setText("TIP  ·  " + random.choice(TIPS).upper())
        self.menu.set_disabled(3, True)
        self._show_gpu("Checking…", "")
        self._show_stats(0, 0, {})
        self._show_engine("off", ENGINE_TEXT["off"])

    # ----- menu
    def _menu_chosen(self, i):
        (self._browse_file, self._browse_dir, self.queue_clicked.emit, self._continue)[i]()

    def _menu_hover(self, i):
        self.desc.setText(DESCRIPTIONS[i] if i >= 0 else
                          "Drop a video, an image or a folder anywhere on this screen, or choose an option on the left.")

    # ----- drops anywhere on the page
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        good = _clip_files(e.mimeData().urls())
        if len(good) == 1:
            self.open_clip.emit(good[0])
        elif good:
            self.open_many.emit(good)

    # ----- data
    def _show_name(self):
        self.hello.setText(("WELCOME BACK, %s" % self._name.upper()) if self._name else "WELCOME BACK")

    def _show_gpu(self, name, detail):
        self.info_rows["gpu"].setText(name + ("\n" + detail if detail else ""))

    def _show_engine(self, state, text):
        self.orb.set_state(state)
        self.info_rows["engine"].setText(text)

    def _show_stats(self, jobs, frames, days):
        self.info_rows["stats"].setText("{:,} cutouts made   ·   {:,} frames processed".format(jobs, frames))

    def _show_recent(self, entries):
        for t in self._thumbs:
            self.strip.removeWidget(t)
            t.setParent(None)
            t.deleteLater()
        self._thumbs = []
        for i, e in enumerate(entries[:8]):
            t = Thumb(e, 152, 92, "strip")
            t.opened.connect(self.open_clip)
            self.strip.insertWidget(i, t)
            self._thumbs.append(t)
        self.strip_empty.setVisible(not entries)
        self.menu.set_disabled(3, not entries)

    def paintEvent(self, e):
        pass
