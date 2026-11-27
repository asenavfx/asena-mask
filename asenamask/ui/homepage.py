"""The Home page: one layout per look (Aurora, Frutiger Aero, Retro), kept in sync and switched with the look."""
from PySide6.QtCore import Signal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStackedWidget, QScrollArea, QFrame

from .home import HomeClassic
from .home_looks import HomeAero, HomeRetro
from .theme import theme


class HomePage(QStackedWidget):
    open_clip = Signal(str)
    open_many = Signal(list)
    forget = Signal(str)
    dismiss_news = Signal()
    open_wrapped = Signal()
    dismiss_wrapped = Signal()
    queue_clicked = Signal()

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.pg = {"aurora": HomeClassic(settings), "aero": HomeAero(settings), "retro": HomeRetro(settings)}
        self.holder = {}
        for key, pg in self.pg.items():
            if key == "aurora":
                self.holder[key] = pg
            else:                      # these two have a fixed-size layout, so they scroll when the window is small
                sc = QScrollArea()
                sc.setWidgetResizable(True)
                sc.setFrameShape(QFrame.NoFrame)
                sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                sc.viewport().setAutoFillBackground(False)
                pg.setAutoFillBackground(False)
                sc.setWidget(pg)
                self.holder[key] = sc
            self.addWidget(self.holder[key])
            pg.open_clip.connect(self.open_clip)
            pg.open_many.connect(self.open_many)
            pg.forget.connect(self.forget) if hasattr(pg, "forget") else None
            pg.dismiss_news.connect(self.dismiss_news)
            pg.open_wrapped.connect(self.open_wrapped)
            pg.dismiss_wrapped.connect(self.dismiss_wrapped)
            pg.queue_clicked.connect(self.queue_clicked)
        theme.changed.connect(self._switch)
        self._switch()

    def _switch(self):
        self.setCurrentWidget(self.holder.get(theme.look, self.holder["aurora"]))

    def _all(self, name, *a):
        for pg in self.pg.values():
            getattr(pg, name)(*a)

    def set_name(self, name):
        self._all("set_name", name)

    def set_recent(self, entries):
        self._all("set_recent", entries)

    def set_gpu(self, g):
        self._all("set_gpu", g)

    def set_engine(self, state):
        self._all("set_engine", state)

    def set_stats(self, jobs, frames, days=None):
        self._all("set_stats", jobs, frames, days)

    def show_wrapped(self, title, text, button="See it"):
        self._all("show_wrapped", title, text, button)

    def show_news(self, version, notes):
        self._all("show_news", version, notes)
