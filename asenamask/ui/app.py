"""Main window: frameless, custom title bar, screens and overlays."""
import json
import math
import os
import subprocess
import sys
import threading
import time

from PySide6.QtCore import Qt, QPointF, QEvent, QRectF, QPoint, QPropertyAnimation, QTimer, Signal
from PySide6.QtGui import QPixmap, QPen, QImage, QRadialGradient, QBrush, QIcon, QPainter, QLinearGradient, QColor, QFont, QPainterPath, QCursor, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QMenu,
                               QGraphicsOpacityEffect, QMessageBox, QSystemTrayIcon)

from .. import APP_NAME, paths, sound, updater, sysinfo
from . import media
from ..engine import EngineClient
from ..jobs import JobThread
from ..projects import ProjectStore
from ..settings import Settings
from .batch_queue import QueueOverlay
from .dialogs import ResultOverlay, InfoOverlay
from .homepage import HomePage
from .settings_page import SettingsPage
from .. import telemetry
from .. import discordrp
from .wrapped import WrappedOverlay, fetch_community
from . import retro
from .xmbbar import XmbBar
from .sidebar import Sidebar
from .editor import EditorOverlay, ProxyLoader
from .. import videoinfo
from .theme import theme, stylesheet
from .update_ui import UpdateOverlay
from .welcome import WelcomeScreen, SplashScreen, LogoMark
from .widgets import IconButton, GlowButton, Toast, title_label, restyle_labels
from .workspace import MainScreen

EDGE = 7


class TitleBar(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setFixedHeight(46)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 6, 10, 4)
        lay.setSpacing(4)
        self.logo = LogoMark(30)
        lay.addWidget(self.logo)
        lay.addSpacing(6)
        self.title = title_label(APP_NAME, 11, QFont.DemiBold)
        lay.addWidget(self.title)
        lay.addStretch(1)
        self.update_btn = GlowButton("Update available", "chip")
        self.update_btn.clicked.connect(win.open_update)
        self.update_btn.hide()
        lay.addWidget(self.update_btn)
        self.menu_btn = IconButton("menu")
        self.min_btn = IconButton("min")
        self.max_btn = IconButton("max")
        self.close_btn = IconButton("close")
        for b in (self.menu_btn, self.min_btn, self.max_btn, self.close_btn):
            lay.addWidget(b)
        self.menu_btn.clicked.connect(self.show_menu)
        self.min_btn.clicked.connect(win.showMinimized)
        self.max_btn.clicked.connect(win.toggle_max)
        self.close_btn.clicked.connect(win.close)

    def show_menu(self):
        m = QMenu(self)
        a1 = m.addAction("Information")
        a2 = m.addAction("Settings")
        a3 = m.addAction("Check for updates")
        pos = self.menu_btn.mapToGlobal(QPoint(self.menu_btn.width() - 170, self.menu_btn.height() + 2))
        act = m.exec(pos)
        if act is a1:
            self.win.open_info()
        elif act is a2:
            self.win.open_settings()
        elif act is a3:
            self.win.check_updates(manual=True)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            h = self.win.windowHandle()
            if h:
                h.startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.win.toggle_max()


class MainWindow(QWidget):
    gpu_ready = Signal(object)
    wrapped_found = Signal(str)

    def __init__(self, settings):
        super().__init__()
        self.s = settings
        self.job = None
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.resize(1180, 760)
        self.setMinimumSize(900, 620)
        theme.set(settings.get("theme"))
        if settings.get("look") in ("leaf", "xmb"):
            settings.set("look", "aero" if settings.get("look") == "leaf" else "retro")
        theme.set_look(settings.get("look"))
        sound.look = theme.look

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.titlebar = TitleBar(self)
        lay.addWidget(self.titlebar)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        self.engine = EngineClient(settings, self)
        self.update_info = None
        self.welcome = WelcomeScreen(settings.get("name"))
        self.welcome.entered.connect(self.enter_app)
        self.splash = SplashScreen()
        self.splash.finished.connect(lambda: self.go_main(False))
        self.projects = ProjectStore()
        self.tray = None
        self._news_ver = ""
        self.main = MainScreen(settings, self.engine)
        self.main.run_requested.connect(self.start_job)
        self.main.cancel_requested.connect(self.cancel_job)
        self.home = HomePage(settings)
        self.settings_page = SettingsPage(settings)
        self.pages = QStackedWidget()
        for pg in (self.home, self.main, self.settings_page):
            self.pages.addWidget(pg)
        self.sidebar = Sidebar()
        self.xmb = XmbBar()
        self.shell = QWidget()
        sh = QVBoxLayout(self.shell)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(0)
        sh.addWidget(self.xmb)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.sidebar)
        body.addWidget(self.pages, 1)
        sh.addLayout(body, 1)
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.splash)
        self.stack.addWidget(self.shell)
        self.stack.setCurrentWidget(self.splash if settings.get("first_run_done") else self.welcome)

        self.result = ResultOverlay(self, self)
        self.result.saved.connect(self.on_saved)
        self.result.discarded.connect(self.on_discarded)
        self.info = InfoOverlay(self, self)
        self.wrapped = WrappedOverlay(self, self, settings)
        sp = self.settings_page
        sp.theme_changed.connect(self.set_theme)
        sp.accent_changed.connect(self.set_accent)
        sp.look_changed.connect(self.set_look)
        sp.bg_toggled.connect(lambda on: self.update_bg_playback())
        sp.check_updates.connect(lambda: self.check_updates(manual=True))
        sp.open_wrapped.connect(self.open_wrapped)
        sp.message.connect(lambda t: self.toast.show_message(t, "ok", 3000))
        self.sidebar.navigate.connect(self.show_page)
        self.sidebar.queue_clicked.connect(lambda: self.queue.open_with())
        self.sidebar.info_clicked.connect(self.open_info)
        self.xmb.navigate.connect(self.show_page)
        self.xmb.queue_clicked.connect(lambda: self.queue.open_with())
        self.xmb.info_clicked.connect(self.open_info)
        self.home.open_clip.connect(self.open_clip)
        self.home.queue_clicked.connect(lambda: self.queue.open_with())
        self.home.open_many.connect(lambda files: self.queue.open_with(files))
        self.home.forget.connect(self.forget_project)
        self.home.dismiss_news.connect(self._news_seen)
        self.home.open_wrapped.connect(self._banner_go)
        self.home.dismiss_wrapped.connect(self._wrapped_dismissed)
        self.gpu_ready.connect(self.home.set_gpu)
        self.wrapped_found.connect(self._wrapped_toast)
        self.engine.state_changed.connect(self.home.set_engine)
        threading.Thread(target=lambda: self.gpu_ready.emit(sysinfo.gpu_info()), daemon=True).start()
        self.editor = EditorOverlay(self, self)
        self.editor.done.connect(self._editor_done)
        self.queue = QueueOverlay(self, self, settings)
        self.queue.saved_all.connect(self.on_queue_done)
        self.main.queue_requested.connect(lambda: self.queue.open_with())
        self.main.queue_files.connect(lambda files: self.queue.open_with(files))
        self.update_ov = UpdateOverlay(self, self)
        self.checker = None
        self.main.pick_requested.connect(self.open_editor)
        self.main.video_loaded.connect(self.start_proxy)
        self.main.video_loaded.connect(self.on_video_loaded)
        self.proxy = None
        self.toast = Toast(self)

        theme.set_accent(settings.get("accent"))
        sound.enabled = bool(settings.get("sounds"))
        self._t0 = time.monotonic()
        self._popped, self._fx, self._hits = {}, [], []
        self.intro_timer = QTimer(self)
        self.intro_timer.setInterval(33)
        self.intro_timer.timeout.connect(self.update)
        theme.changed.connect(self.on_theme)
        self.stack.currentChanged.connect(lambda _: self.update_bg_playback())
        self.pages.currentChanged.connect(lambda _: self.update_bg_playback())
        QApplication.instance().installEventFilter(self)
        self._edge_cursor = False
        self.on_theme()

    # ---------- painting
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        look = theme.look
        rad = 0 if self.isMaximized() else max(4, int(16 * theme.param("radius")))
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), rad, rad)
        if look == "aurora":
            g = QLinearGradient(0, 0, self.width(), self.height())
            g.setColorAt(0.0, theme.col("bg1"))
            g.setColorAt(0.55, theme.col("bg2"))
            g.setColorAt(1.0, theme.col("bg3"))
            p.fillPath(path, g)
        else:
            p.drawPixmap(0, 0, self._static_layer())
        p.setClipPath(path)
        if look == "aurora":
            glow = QColor(theme.col("accent2"))
            glow.setAlpha(34 if theme.name == "dark" else 40)
            rg = QRadialGradient(self.width() * 0.85, self.height() * 0.05, self.width() * 0.5)
            rg.setColorAt(0, glow)
            rg.setColorAt(1, QColor(glow.red(), glow.green(), glow.blue(), 0))
            p.fillRect(self.rect(), rg)
            self._paint_intro_bg(p)
        elif theme.glass:
            self._paint_aero(p)
        else:
            self._paint_retro(p)
        p.setClipping(False)
        ac = theme.col("accent")
        p.setBrush(Qt.NoBrush)
        if theme.glass:
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.6))
        elif look == "retro":
            p.setPen(QPen(QColor(255, 255, 255, 150), 1.4))
        else:
            p.setPen(QPen(QColor(ac.red(), ac.green(), ac.blue(), 70 if theme.name == "dark" else 90), 1.2))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6), rad, rad)

    def _clock(self):
        return (time.monotonic() - self._t0) if self.s.get("anim_bg") else 0.0

    def _scene_cache(self):
        return self.__dict__.setdefault("_scene", {})

    def _static_layer(self):
        """The unmoving part of the Aero / Retro scenery, drawn once into a picture and reused every frame."""
        W, H = self.width(), self.height()
        dpr = self.devicePixelRatioF()
        key = (theme.look, W, H, dpr, self.isMaximized())
        c = self._scene_cache()
        if c.get("key") != key:
            pm = QPixmap(max(1, int(W * dpr)), max(1, int(H * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            rad = 0 if self.isMaximized() else max(4, int(16 * theme.param("radius")))
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, W, H), rad, rad)
            g = QLinearGradient(0, 0, 0, H)
            g.setColorAt(0.0, theme.col("bg1"))
            g.setColorAt(0.55, theme.col("bg2"))
            g.setColorAt(1.0, theme.col("bg3"))
            q.fillPath(path, g)
            q.setClipPath(path)
            if theme.glass:
                self._aero_static(q, W, H)
            else:
                self._retro_static(q, W, H)
            q.end()
            c["key"], c["pm"] = key, pm
        return c["pm"]

    def _aero_static(self, p, W, H):
        ox = W * 0.40
        glow = QRadialGradient(QPointF(ox, -H * 0.12), max(W, H) * 0.85)
        glow.setColorAt(0, QColor(190, 250, 255, 175))
        glow.setColorAt(0.35, QColor(80, 190, 235, 70))
        glow.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, 0, W, H), QBrush(glow))
        n = 9
        for k in range(n):
            f = (k + 0.5) / n
            ang = -0.62 + 1.24 * f
            wd = 0.05 + 0.05 * ((k * 37) % 7) / 7.0
            ray = QPainterPath()
            ray.moveTo(ox, -H * 0.12)
            ray.lineTo(ox + math.tan(ang - wd) * H * 1.3, H * 1.2)
            ray.lineTo(ox + math.tan(ang + wd) * H * 1.3, H * 1.2)
            ray.closeSubpath()
            rg = QLinearGradient(0, 0, 0, H)
            rg.setColorAt(0, QColor(255, 255, 255, 30 if k % 2 else 18))
            rg.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillPath(ray, QBrush(rg))
        p.setPen(Qt.NoPen)
        for i in range(7):
            rnd = ((i * 7919) % 97) / 97.0
            rnd2 = ((i * 104729) % 89) / 89.0
            c = QPointF(W * (0.08 + 0.84 * rnd), H * (0.12 + 0.7 * rnd2))
            r0 = 26 + 40 * rnd2
            bg = QRadialGradient(c, r0)
            bg.setColorAt(0, QColor(255, 255, 255, 40))
            bg.setColorAt(1, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(bg))
            p.drawEllipse(c, r0, r0)

    def _retro_static(self, p, W, H):
        lg = QRadialGradient(QPointF(W * 0.86, H * 0.45), max(W, H) * 0.55)
        lg.setColorAt(0, QColor(150, 170, 255, 70))
        lg.setColorAt(1, QColor(150, 170, 255, 0))
        p.fillRect(QRectF(0, 0, W, H), QBrush(lg))
        pen = QPen(QColor(255, 255, 255, 30), 2.2)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        sx = W * 0.055
        sz = min(H * 0.07, 44)
        for k in range(4):
            cy = H * (0.22 + 0.17 * k)
            if k == 0:
                tri = QPainterPath()
                tri.moveTo(sx, cy - sz)
                tri.lineTo(sx + sz, cy + sz * 0.7)
                tri.lineTo(sx - sz, cy + sz * 0.7)
                tri.closeSubpath()
                p.drawPath(tri)
            elif k == 1:
                p.drawEllipse(QPointF(sx, cy), sz, sz)
            elif k == 2:
                p.drawLine(QPointF(sx - sz, cy - sz), QPointF(sx + sz, cy + sz))
                p.drawLine(QPointF(sx + sz, cy - sz), QPointF(sx - sz, cy + sz))
            else:
                p.drawRect(QRectF(sx - sz, cy - sz, sz * 2, sz * 2))

    # ----- the moving parts, plus the pop-it Easter egg on the Home page
    def _alive(self, kind, i, now):
        """False while a popped bubble / cube is gone; fades it back in afterwards (returns opacity otherwise)."""
        t0 = self._popped.get((kind, i))
        if t0 is None:
            return 1.0
        gone = 5.0 if kind == "b" else 7.0
        age = now - t0
        if age < gone:
            return 0.0
        if age < gone + 1.2:
            return (age - gone) / 1.2
        del self._popped[(kind, i)]
        return 1.0

    def _paint_aero(self, p):
        W, H = self.width(), self.height()
        t = self._clock()
        now = time.monotonic()
        self._hits = []
        for i in range(3):   # slow ripples of light in the deep water
            y = H * (0.80 + 0.07 * i)
            path = QPainterPath()
            path.moveTo(0, y)
            for x in range(0, W + 30, 30):
                path.lineTo(x, y + math.sin(x * 0.012 + t * 0.5 + i) * 5)
            p.setPen(QPen(QColor(190, 240, 255, 34 - i * 8), 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        for i in range(10):
            op = self._alive("b", i, now)
            rnd = ((i * 7919) % 97) / 97.0
            rnd2 = ((i * 104729) % 89) / 89.0
            rad = 8 + 44 * rnd2 * rnd2
            speed = 0.008 + 0.014 * rnd
            y = H * (1.15 - ((rnd2 * 1.3 + t * speed) % 1.3))
            x = W * (0.03 + 0.94 * rnd) + math.sin(t * 0.4 + i) * 14
            if op <= 0:
                continue
            self._hits.append(("b", i, x, y, max(rad, 16)))
            c = QPointF(x, y)
            p.setOpacity(op)
            bg = QRadialGradient(c, rad)
            bg.setColorAt(0.0, QColor(255, 255, 255, 8))
            bg.setColorAt(0.8, QColor(200, 245, 255, 30))
            bg.setColorAt(1.0, QColor(255, 255, 255, 140))
            p.setBrush(QBrush(bg))
            p.setPen(QPen(QColor(255, 255, 255, 170), 1.0))
            p.drawEllipse(c, rad, rad)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 150))
            p.drawEllipse(QPointF(x - rad * 0.38, y - rad * 0.42), rad * 0.22, rad * 0.13)
            p.setOpacity(1.0)
        self._paint_fx(p, now)

    def _paint_retro(self, p):
        W, H = self.width(), self.height()
        t = self._clock()
        now = time.monotonic()
        self._hits = []
        for i in range(3):
            base = H * (0.35 + 0.2 * i)
            amp = 24 + 8 * i
            upper = [(x, base + amp * math.sin(x * 0.0036 + t * (0.16 + 0.03 * i) + i * 1.9)
                      + amp * 0.5 * math.sin(x * 0.0081 - t * 0.12 + i)) for x in range(-10, W + 40, 28)]
            ribbon = QPainterPath()
            ribbon.moveTo(*upper[0])
            for x, y in upper[1:]:
                ribbon.lineTo(x, y)
            for x, y in reversed(upper):
                ribbon.lineTo(x, y + 60 + 20 * i)
            ribbon.closeSubpath()
            rg = QLinearGradient(0, base - amp, 0, base + amp + 80)
            rg.setColorAt(0, QColor(120, 140, 255, 26))
            rg.setColorAt(1, QColor(120, 140, 255, 0))
            p.fillPath(ribbon, QBrush(rg))
        for i in range(16):
            op = self._alive("c", i, now)
            rnd = ((i * 7919) % 97) / 97.0
            rnd2 = ((i * 104729) % 89) / 89.0
            rnd3 = ((i * 15485863) % 83) / 83.0
            size = 10 + 46 * rnd2 * rnd2
            span = W * 0.55
            x = W * 0.45 + (span * rnd + t * (3 + 6 * rnd3)) % (span + 80) - 20 + (W * 0.1 if i % 3 == 0 else 0)
            y = H * (0.05 + 0.9 * rnd3) + math.sin(t * 0.25 + i) * 12
            if op <= 0:
                continue
            bright = 0.35 + 0.65 * (size / 56.0)
            self._hits.append(("c", i, x, y, size * 1.5))
            p.setOpacity(op)
            retro.draw_cube(p, x, y, size, t * (0.18 + 0.12 * rnd) + i, 0.5 + 0.4 * math.sin(t * 0.17 + i),
                            255 * bright)
            p.setOpacity(1.0)
        self._paint_fx(p, now)

    def _paint_fx(self, p, now):
        keep = []
        for fx in self._fx:
            age = now - fx["t0"]
            dur = 0.55 if fx["kind"] == "b" else 0.8
            if age >= dur:
                continue
            keep.append(fx)
            k = age / dur
            x, y, r = fx["x"], fx["y"], fx["r"]
            if fx["kind"] == "b":     # soap bubble: a ring bursts outward and droplets fly off
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, int(220 * (1 - k))), 2.0))
                p.drawEllipse(QPointF(x, y), r * (1 + 0.5 * k), r * (1 + 0.5 * k))
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, int(230 * (1 - k))))
                for j in range(9):
                    a = j * 0.698 + fx["seed"]
                    d = r * (0.9 + 1.3 * k)
                    rr = max(0.5, (2.6 + r * 0.05) * (1 - k))
                    p.drawEllipse(QPointF(x + math.cos(a) * d, y + math.sin(a) * d), rr, rr)
            else:                      # cube: it shatters into spinning glass shards
                if k < 0.3:
                    fl = QRadialGradient(QPointF(x, y), r * 1.2)
                    fl.setColorAt(0, QColor(255, 255, 255, int(190 * (1 - k / 0.3))))
                    fl.setColorAt(1, QColor(255, 255, 255, 0))
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(fl))
                    p.drawEllipse(QPointF(x, y), r * 1.2, r * 1.2)
                for j in range(14):
                    a = j * 0.449 + fx["seed"]
                    d = r * (0.2 + 2.4 * k) * (0.6 + 0.4 * ((j * 7) % 5) / 4.0)
                    sc = r * 0.55 * (1 - 0.7 * k)
                    rot = a * 3 + k * 9 * (1 if j % 2 else -1)
                    cx_, cy_ = x + math.cos(a) * d, y + math.sin(a) * d
                    tri = QPainterPath()
                    for m in range(3):
                        aa = rot + m * 2.094
                        pt = QPointF(cx_ + math.cos(aa) * sc, cy_ + math.sin(aa) * sc * 0.8)
                        tri.moveTo(pt) if m == 0 else tri.lineTo(pt)
                    tri.closeSubpath()
                    p.setBrush(QColor(200, 215, 255, int(200 * (1 - k))))
                    p.setPen(QPen(QColor(255, 255, 255, int(230 * (1 - k))), 1.0))
                    p.drawPath(tri)
        self._fx = keep

    def mousePressEvent(self, e):
        """Easter egg: on the Home page of the Aero / Retro looks you can pop the bubbles and shatter the cubes."""
        if e.button() == Qt.LeftButton and theme.look != "aurora" and self.stack.currentWidget() is self.shell \
                and self.pages.currentWidget() is self.home:
            pos = e.position()
            best, bd = None, 1e9
            for kind, i, x, y, r in self._hits:
                d = math.hypot(pos.x() - x, pos.y() - y)
                if d <= r and d < bd:
                    best, bd = (kind, i, x, y, r), d
            if best:
                kind, i, x, y, r = best
                now = time.monotonic()
                self._popped[(kind, i)] = now
                self._fx.append({"kind": kind, "x": x, "y": y, "r": r / (1.5 if kind == "c" else 1.0), "t0": now,
                                 "seed": (i * 1.7) % 6.28})
                sound.play("small", 0.05)
                self.intro_timer.start()
                QTimer.singleShot(900, self.update_bg_playback)
                self.update()
                e.accept()
                return
        super().mousePressEvent(e)

    def _on_intro(self):
        return self.stack.currentWidget() in (self.welcome, self.splash)

    def _dot_tile(self):
        if not hasattr(self, "_tile"):
            from PySide6.QtGui import QPixmap
            t = QPixmap(32, 32)
            t.fill(Qt.transparent)
            q = QPainter(t)
            q.setRenderHint(QPainter.Antialiasing)
            q.setPen(Qt.NoPen)
            q.setBrush(QColor(255, 255, 255, 22))
            q.drawEllipse(QPointF(16, 16), 1.1, 1.1)
            q.end()
            self._tile = t
        return self._tile

    def _paint_intro_bg(self, p):
        """Slow drifting accent glows + a faint dot grid, only on the welcome / loading screens."""
        if not self._on_intro():
            return
        t = self._clock()
        W, H = self.width(), self.height()
        a1, a2 = theme.col("accent"), theme.col("accent2")
        blobs = [
            (0.25 + 0.12 * math.sin(t * 0.21), 0.30 + 0.10 * math.cos(t * 0.17), 0.55, a1, 46),
            (0.78 + 0.10 * math.cos(t * 0.19), 0.70 + 0.12 * math.sin(t * 0.23), 0.60, a2, 40),
            (0.55 + 0.14 * math.sin(t * 0.13 + 2), 0.15 + 0.08 * math.cos(t * 0.29), 0.40, a1, 26),
        ]
        for fx, fy, fr, col, alpha in blobs:
            g = QRadialGradient(QPointF(W * fx, H * fy), W * fr)
            g.setColorAt(0, QColor(col.red(), col.green(), col.blue(), alpha))
            g.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
            p.fillRect(self.rect(), QBrush(g))
        # faint dot grid that slowly drifts, fading out toward the edges
        br = QBrush(self._dot_tile())
        from PySide6.QtGui import QTransform
        br.setTransform(QTransform.fromTranslate((t * 4) % 32, (t * 2.5) % 32))
        p.save()
        p.setOpacity(0.9)
        p.fillRect(self.rect(), br)
        vg = QRadialGradient(QPointF(W / 2, H / 2), max(W, H) * 0.6)
        vg.setColorAt(0.0, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, theme.col("bg1"))
        p.fillRect(self.rect(), QBrush(vg))
        p.restore()

    def update_bg_playback(self):
        living = theme.look != "aurora" and self.stack.currentWidget() is self.shell
        run = bool(self.s.get("anim_bg")) and (self._on_intro() or living)
        if run:
            self.intro_timer.start()
        else:
            self.intro_timer.stop()
        self.update()

    def toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange:
            self.titlebar.max_btn.kind = "restore" if self.isMaximized() else "max"
            self.titlebar.max_btn.update()
            self.update()
        super().changeEvent(e)

    def resizeEvent(self, e):
        for ov in (self.result, self.info, self.editor, self.queue, self.update_ov):
            if ov.isVisible():
                ov.setGeometry(self.rect())
        super().resizeEvent(e)

    # ---------- edge resize for the frameless window
    def _edges(self, global_pos):
        if self.isMaximized() or self.isFullScreen():
            return Qt.Edge(0)
        gp = self.mapFromGlobal(global_pos)
        r = self.rect()
        edges = Qt.Edge(0)
        if gp.x() <= EDGE:
            edges |= Qt.LeftEdge
        if gp.x() >= r.width() - EDGE:
            edges |= Qt.RightEdge
        if gp.y() <= EDGE:
            edges |= Qt.TopEdge
        if gp.y() >= r.height() - EDGE:
            edges |= Qt.BottomEdge
        return edges

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.MouseMove, QEvent.MouseButtonPress) and isinstance(obj, QWidget) and obj.window() is self:
            gp = ev.globalPosition().toPoint()
            edges = self._edges(gp)
            if t == QEvent.MouseMove and not (ev.buttons() & Qt.LeftButton):
                self._set_edge_cursor(edges)
            elif t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton and edges:
                h = self.windowHandle()
                if h:
                    h.startSystemResize(edges)
                    return True
        return super().eventFilter(obj, ev)

    def leaveEvent(self, e):
        self._set_edge_cursor(Qt.Edge(0))
        super().leaveEvent(e)

    def _set_edge_cursor(self, edges):
        if edges:
            horiz = bool(edges & (Qt.LeftEdge | Qt.RightEdge))
            vert = bool(edges & (Qt.TopEdge | Qt.BottomEdge))
            if horiz and vert:
                diag = (bool(edges & Qt.LeftEdge) == bool(edges & Qt.TopEdge))
                shape = Qt.SizeFDiagCursor if diag else Qt.SizeBDiagCursor
            else:
                shape = Qt.SizeHorCursor if horiz else Qt.SizeVerCursor
            if self._edge_cursor:
                QApplication.changeOverrideCursor(shape)
            else:
                QApplication.setOverrideCursor(shape)
                self._edge_cursor = True
        elif self._edge_cursor:
            QApplication.restoreOverrideCursor()
            self._edge_cursor = False

    # ---------- theme
    def set_theme(self, name):
        self.s.set("theme", name)
        theme.set(name)

    def set_accent(self, name):
        self.s.set("accent", name)
        theme.set_accent(name)

    def set_look(self, name):
        self.s.set("look", name)
        theme.set_look(name)
        sound.look = theme.look
        self.update_bg_playback()

    def on_theme(self):
        retro = theme.look == "retro"
        QApplication.setFont(theme.font(10, QFont.Normal))
        self.xmb.setVisible(retro)
        self.sidebar.setVisible(not retro)
        QApplication.instance().setStyleSheet(stylesheet())
        restyle_labels(self)
        self.update()

    # ---------- screens
    def enter_app(self, name):
        """Called after the first-run welcome screen."""
        self.s.set("name", name)
        self.s.set("first_run_done", True)
        sound.play("welcome")
        self.go_main(True, name)

    def go_main(self, greet, name=""):
        eff = QGraphicsOpacityEffect(self.shell)
        self.shell.setGraphicsEffect(eff)
        self.stack.setCurrentWidget(self.shell)
        self.show_page("project" if (self.s.get("start_page") == "project" and self.projects.recent(1)) else "home")
        self._maybe_news()
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(450)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.finished.connect(lambda: self.shell.setGraphicsEffect(None))
        anim.start()
        self._enter_anim = anim
        who = name or self.s.get("name")
        if who:
            self.toast.show_message("Welcome%s, %s!" % ("" if greet else " back", who), "info", 2200)

    def start_intro(self):
        if self.stack.currentWidget() is self.splash:
            self.splash.start()
        sound.play("welcome")

    def _close_all_overlays(self):
        for ov in (self.info,):
            if ov.isVisible():
                ov.hide()

    # ---------- pages / projects
    def show_page(self, key):
        if self.pages.currentWidget() is self.main and key != "project":
            self.main.player.pause()
            self.save_project()
        page = {"home": self.home, "project": self.main, "settings": self.settings_page}[key]
        if key == "home":
            self.refresh_home()
        self.pages.setCurrentWidget(page)
        self.sidebar.set_current(key)
        self.xmb.set_current(key)
        if theme.look == "retro":
            self._page_fade(page)

    def _page_fade(self, page):
        """Retro: pages fade up quickly when you switch, like a console menu."""
        eff = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(280)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.finished.connect(lambda: page.setGraphicsEffect(None))
        anim.start()
        self._page_anim = anim

    def refresh_home(self):
        self.home.set_name(self.s.get("name"))
        self.home.set_recent(self.projects.recent(12))
        self.home.set_engine(self.engine.state)
        self.home.set_stats(self.s.get("stat_jobs"), self.s.get("stat_frames"), self.s.get("stat_days"))

    def open_clip(self, path):
        if not os.path.exists(path):
            self.toast.show_message("That file is not there any more.", "error")
            self.projects.forget(path)
            self.refresh_home()
            return
        self.main.load_video(path)
        if self.main.video_path and os.path.abspath(self.main.video_path) == os.path.abspath(path):
            self.show_page("project")

    def forget_project(self, path):
        self.projects.forget(path)
        self.refresh_home()

    def on_video_loaded(self, path):
        """A clip was opened: remember it, and bring back its saved trim / subject / values."""
        m = self.main
        if self.s.get("live_default") and not (self.job is not None and self.job.isRunning()):
            QTimer.singleShot(1500, self.engine.prewarm)       # load the AI now, so the first live preview is quick
        self.projects.touch(path, m.kind, m.info)
        try:
            if m._thumb_rgb is not None and not os.path.isfile(self.projects.thumb_path(path)):
                self.projects.save_thumb(path, m._thumb_rgb)
        except Exception:
            pass
        e = self.projects.get(path) or {}
        if e.get("trim") or e.get("selection") or e.get("settings"):
            st = e.get("settings") or {}
            if st.get("prompt") is not None:
                m.prompt.setPlainText(st["prompt"])
            m.apply_values(st)
            m.set_edit(e.get("trim"), e.get("selection"))
            self.toast.show_message("Restored your trim and subject for this clip.", "info", 2600)

    def save_project(self):
        m = self.main
        if not m.video_path:
            return
        try:
            st = dict(m.current_values(), prompt=" ".join(m.prompt.toPlainText().split()))
            self.projects.update(m.video_path, m.trim, m.selection, st)
        except Exception:
            pass

    def _editor_done(self, r):
        self.main.set_edit(r["trim"], r["selection"])
        if r.get("frame") is not None:                 # the main preview continues where the editor stopped
            try:
                self.main.player._show(int(r["frame"]))
            except Exception:
                pass
        self.save_project()

    def _maybe_news(self):
        root = paths.install_root()
        if not root:
            return
        try:
            with open(os.path.join(str(root), "package.json"), encoding="utf-8") as f:
                pkg = json.load(f)
        except Exception:
            return
        ver, notes = str(pkg.get("version") or ""), (pkg.get("notes") or "").strip()
        seen = self.s.get("seen_version")
        if not ver or ver == seen:
            return
        if not seen or not notes:                    # fresh install, or nothing to say
            self.s.set("seen_version", ver)
            return
        self._news_ver = ver
        self.home.show_news(ver, notes)

    def _news_seen(self):
        if self._news_ver:
            self.s.set("seen_version", self._news_ver)

    # ---------- notifications / power
    def notify(self, text):
        """Flash the taskbar and show a Windows notification when the app is in the background."""
        if not self.s.get("notify_done") or self.isActiveWindow():
            return
        QApplication.alert(self, 0)
        try:
            if QSystemTrayIcon.isSystemTrayAvailable():
                if self.tray is None:
                    self.tray = QSystemTrayIcon(QApplication.windowIcon(), self)
                self.tray.show()
                self.tray.showMessage(APP_NAME, text, QSystemTrayIcon.Information, 7000)
        except Exception:
            pass

    def on_queue_done(self, folder):
        if getattr(self.queue, "stopping", False):
            return
        self.notify("Your batch queue finished.")
        mode = self.s.get("after_queue")
        if mode in ("sleep", "shutdown") and os.name == "nt":
            self.power_countdown(mode)

    def power_countdown(self, mode):
        word = "go to sleep" if mode == "sleep" else "shut down"
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Warning)
        box.setText("The batch queue is finished.")
        box.setStandardButtons(QMessageBox.Cancel)
        box.setModal(False)
        state = {"n": 60, "go": False}

        def text():
            box.setInformativeText("Your PC will %s in %d seconds. Press Cancel to stop that." % (word, state["n"]))

        def tick():
            state["n"] -= 1
            if state["n"] <= 0:
                state["go"] = True
                box.close()
            else:
                text()

        timer = QTimer(box)
        timer.setInterval(1000)
        timer.timeout.connect(tick)
        box.finished.connect(lambda _r: (timer.stop(), state["go"] and self._power(mode)))
        text()
        self._power_box = box
        box.show()
        timer.start()

    def _power(self, mode):
        try:
            if mode == "sleep":
                subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], creationflags=0x08000000)
            else:
                subprocess.Popen(["shutdown", "/s", "/t", "5"], creationflags=0x08000000)
        except Exception:
            pass

    def start_proxy(self, path):
        """Decode the clip into small preview frames in the background (for the editor)."""
        if self.proxy is not None:
            self.proxy.stop()
            self.proxy = None
        if os.path.isdir(path):
            return
        self.proxy = ProxyLoader(path)
        self.proxy.start()
        self.main.attach_proxy(self.proxy)

    def open_editor(self):
        m = self.main
        if not m.video_path or self.proxy is None or m.kind == "folder":
            self.toast.show_message("Import a video or image first.", "error")
            return
        m.player.pause()
        live = bool(self.s.get("live_default"))
        self.editor.live_btn.setChecked(live)
        self.editor.live = live
        self.editor.open_with(self.proxy, m.info, m.trim, m.selection, self.engine, m.preview_params,
                              start=getattr(m.player, "cur", None))

    def open_info(self):
        self._close_all_overlays()
        self.info.open_overlay()

    def open_settings(self):
        self._close_all_overlays()
        self.show_page("settings")

    # ---------- job
    def start_job(self):
        m = self.main
        if not m.video_path:
            self.toast.show_message("Import a video, image or folder first.", "error")
            return
        p = m.params()
        if not p["prompt"] and not p.get("selection"):
            self.toast.show_message("Type what to keep (for example: person), or pick a subject on the frame.", "error", 4500)
            return
        if p.get("selection") and m.kind == "video" and (m.info or {}).get("frames", 0) > 400:
            self.toast.show_message("Long clip: subject tracking uses a lot of memory. Try a shorter clip if it fails.", "info", 5000)
        if not self.engine_ready():
            return
        self.save_project()
        self.engine.stop()                    # the live preview gives its GPU memory back for the real run
        self.job_params = p
        self.job = JobThread(self.make_job(p), self)
        self.job.status.connect(m.set_status)
        self.job.progress.connect(m.set_progress)
        self.job.progress.connect(self._discord_progress)
        self._discord_since = int(time.time())
        self._job_t0 = time.time()                       # the clock starts when Run is pressed (model loading and tracking count)
        self.job.finished_ok.connect(self.on_job_done)
        self.job.failed.connect(self.on_job_failed)
        m.set_busy(True)
        self.update_bg_playback()
        m.set_status("Starting…")
        self.job.start()

    def _discord_progress(self, done, total, eta):
        if total > 0:
            discordrp.P.working("%d%% done (%d of %d frames)" % (int(100.0 * done / total), done, total), self._discord_since)

    def engine_ready(self):
        """True when the AI engine and model are installed (shows a message otherwise)."""
        if os.environ.get("ASENA_DEMO") == "1":
            return True
        comfy, ckdir, ck = self.s.comfy_dir(), self.s.ckpt_dir(), self.s.get("ckpt_name")
        if not comfy or not os.path.isfile(os.path.join(comfy, "main.py")):
            self.toast.show_message("The AI engine is missing. Run the Asena Mask installer again to repair it."
                                    if paths.install_root() else
                                    "AI engine files not found. Open Settings → Engine files.", "error", 6000)
            return False
        if not os.path.isfile(os.path.join(ckdir, ck)):
            self.toast.show_message("The AI model is missing. Run the Asena Mask installer again to repair it."
                                    if paths.install_root() else "Model file not found in: %s" % ckdir, "error", 6000)
            return False
        return True

    def make_job(self, p):
        return dict(p, comfy_dir=self.s.comfy_dir(), ckpt_dir=self.s.ckpt_dir(), ckpt_name=self.s.get("ckpt_name"),
                    batch=self.s.batch(), demo=os.environ.get("ASENA_DEMO") == "1")

    # ---------- updates
    def open_wrapped(self):
        self._close_all_overlays()
        self.wrapped.open_overlay()

    def show_stats_notice(self):
        """One-time, non-blocking Home banner for people who updated without running the installer (which tells them itself).
        Stats are only sent after this has been on screen once."""
        T = telemetry.T
        if not T.should_notice():
            return
        if not self.s.get("first_run_done") or (self.job is not None and self.job.isRunning()):
            QTimer.singleShot(30000, self.show_stats_notice)
            return
        self._wr_kind = "notice"
        self.home.show_wrapped("Anonymous usage stats are on",
                               "Asena Mask now counts simple totals (cutouts, frames, formats, PC type, continent) and sends them anonymously. "
                               "No videos, files, names or IP addresses. Turn it off any time in Settings > Privacy.",
                               "Settings")
        self.s.set("tm_notice_shown", True)

    def _banner_go(self):
        if getattr(self, "_last_kind", "") == "notice":
            self.open_settings()
        else:
            self.open_wrapped()

    def check_wrapped(self):
        """Home banner: (1) once after updating to this version, (2) whenever the developer publishes a community Wrapped
        this user has not seen yet. The button on the banner opens the Wrapped; it is also in Settings > Privacy & Wrapped."""
        self._wr_kind = ""
        if not self.s.get("wrapped_intro") and int(self.s.get("stat_jobs") or 0) > 0:      # not for brand-new users
            self._wr_kind = "intro"
            self.home.show_wrapped("Your Asena Wrapped is here",
                                   "See how many cutouts and frames you've made, your favourite formats and more. "
                                   "It's counted on your PC and only you can see it.")

        def got(d):
            if d and str(d.get("id", "")) != str(self.s.get("wrapped_seen") or ""):
                self.wrapped_found.emit(str(d.get("title") or "Asena Mask Wrapped"))
        fetch_community(got)

    def _wrapped_toast(self, title):
        self._wr_kind = "community"
        self.home.show_wrapped("%s is out!" % title, "See everyone's year in Asena Mask, added up, plus your own totals.")
        self.toast.show_message("%s is out! Open it from the Home page." % title, "info", 6000)

    def _wrapped_dismissed(self):
        kind = getattr(self, "_wr_kind", "")
        self._last_kind = kind
        self._wr_kind = ""
        if kind == "notice":
            self.s.set("tm_notice_seen", True)
            telemetry.T.flush()
        elif kind != "community":
            self.s.set("wrapped_intro", True)

    def check_updates(self, manual=False):
        if self.checker is not None and self.checker.isRunning():
            return
        self.checker = updater.CheckThread(force=os.environ.get("ASENA_UPDATE_TEST") == "1", parent=self)
        self.checker.found.connect(self.on_update_found)
        if manual:
            self.checker.none.connect(lambda: self.toast.show_message(
                "You are up to date." if paths.install_root() else "Updates only work in the installed app.", "info", 3000))
        self.checker.start()

    def on_update_found(self, info):
        self.update_info = info
        self.titlebar.update_btn.setText("Update %s available" % info.get("version", ""))
        self.titlebar.update_btn.show()
        self.toast.show_message("Version %s is available. Click “Update available” at the top." % info.get("version", ""),
                                "info", 5000)

    def open_update(self):
        if self.update_info:
            self._close_all_overlays()
            self.update_ov.open_with(self.update_info)

    def close_for_update(self):
        """The updater is waiting for this app to exit."""
        self.close()
        QApplication.quit()

    def cancel_job(self):
        if self.job:
            self.job.cancel()
            self.job.wait(3000)
            self._cleanup_job()
            telemetry.T.count("jobs_cancelled")
            discordrp.P.idle()
            self.main.set_busy(False)
            self.main.set_status("Cancelled.")
            self.job = None
            self.update_bg_playback()

    def on_job_done(self, info):
        try:
            info["seconds"] = max(0.0, time.time() - float(getattr(self, "_job_t0", 0) or 0)) if getattr(self, "_job_t0", 0) else info.get("seconds", 0)
        except Exception:
            pass
        discordrp.P.idle()
        if self.s.get("live_default"):
            QTimer.singleShot(2500, self.engine.prewarm)      # the render freed the GPU; get the preview engine back while they review
        self.main.set_busy(False)
        self.update_bg_playback()
        sound.finish()
        self.main.set_status("Done. Preview opened.")
        self.notify("Your cutout is ready.")
        try:
            telemetry.T.job_done(self.job_params, info)
        except Exception:
            pass
        try:
            self.s.set("stat_jobs", int(self.s.get("stat_jobs") or 0) + 1)
            self.s.set("stat_frames", int(self.s.get("stat_frames") or 0) + int(info.get("frames") or 0))
            days = dict(self.s.get("stat_days") or {})
            k = time.strftime("%Y-%m-%d")
            days[k] = int(days.get(k, 0)) + 1
            self.s.set("stat_days", dict(sorted(days.items())[-30:]))
            self.home.set_stats(self.s.get("stat_jobs"), self.s.get("stat_frames"), self.s.get("stat_days"))
        except Exception:
            pass
        vp = self.job_params["video"].rstrip("/\\")
        base = os.path.basename(vp) if os.path.isdir(vp) else os.path.splitext(os.path.basename(vp))[0]
        name = self._result_name(base)
        start = self.s.get("out_dir") or self.s.get("last_dir") or os.path.dirname(vp)
        self.result.show_result(info, name, start)
        fl = info.get("flagged") or []
        if fl:
            def tm(t):
                return "%d:%04.1f" % (int(t) // 60, float(t) % 60)
            self.toast.show_message("Check %d spot%s where the cutout may have glitched (%s). Open Trim & pick subject there and add "
                                    "a box or brush stroke, then run again." % (len(fl), "" if len(fl) == 1 else "s",
                                                                                ", ".join(tm(f["t"]) for f in fl[:4])
                                                                                + (" …" if len(fl) > 4 else "")), "info", 9000)

    def _result_name(self, clip):
        pat = self.s.get("name_pattern") or "{prefix}_{clip}"
        try:
            name = pat.format(prefix=self.job_params["prefix"], clip=clip, date=time.strftime("%Y-%m-%d"),
                              time=time.strftime("%H-%M"), format=self.job_params.get("format", ""))
        except Exception:
            name = "%s_%s" % (self.job_params["prefix"], clip)
        for ch in '<>:"/\\|?*':
            name = name.replace(ch, "_")
        return name.strip(" .") or "asena_%s" % clip

    def on_job_failed(self, text):
        discordrp.P.idle()
        self.main.set_busy(False)
        self.update_bg_playback()
        self.main.set_status("Something went wrong.")
        telemetry.T.job_failed(text)
        self._cleanup_job()
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Warning)
        box.setText("Asena Mask could not finish.")
        box.setInformativeText(text[:900])
        box.exec()

    def on_saved(self, path):
        telemetry.T.count("saved")
        self.s.set("last_dir", os.path.dirname(path))
        self.toast.show_message("Saved: %s" % os.path.basename(path), "ok")
        self.result.close_overlay()
        self.main.set_status("Saved. Import something else, or run again with new settings.")
        if self.s.get("open_folder_after_save") and os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        self._cleanup_job()

    def on_discarded(self):
        self.main.set_status("Discarded. Change settings and run again.")
        self._cleanup_job()

    def _cleanup_job(self):
        if self.job:
            import shutil
            shutil.rmtree(self.job.work_dir, ignore_errors=True)

    def closeEvent(self, e):
        try:
            telemetry.T.shutdown()
        except Exception:
            pass
        try:
            discordrp.P.shutdown()
            time.sleep(0.4)
        except Exception:
            pass
        self.save_project()
        self.engine.stop()
        if self.proxy is not None:
            self.proxy.stop()
            self.proxy.wait(2000)
        if self.job and self.job.isRunning():
            self.job.cancel()
            self.job.wait(3000)
        self._cleanup_job()
        super().closeEvent(e)


def run():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Asenavfx.AsenaMask")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    icon = paths.asset("icon.ico")
    if os.path.isfile(icon):
        app.setWindowIcon(QIcon(icon))
    st = Settings()
    telemetry.T.start(st)                  # local totals; sending starts once the user has been told (installer or Home notice)
    win = MainWindow(st)
    win.tm_timer = QTimer(win)             # saves the totals now and then and, only if the user agreed, sends them
    win.tm_timer.timeout.connect(telemetry.T.poll)
    win.tm_timer.start(5000)
    win.setWindowOpacity(0.0)
    win.show()
    fade = QPropertyAnimation(win, b"windowOpacity", win)
    fade.setDuration(450)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.start()
    win._fade_in = fade
    QTimer.singleShot(250, win.start_intro)
    win.update_bg_playback()
    if win.s.get("discord_presence"):
        discordrp.P.set_enabled(True)
        discordrp.P.idle()
    if win.s.get("auto_update"):
        QTimer.singleShot(4000, win.check_updates)
    QTimer.singleShot(7000, win.show_stats_notice)
    if telemetry.WRAPPED_ENABLED:
        QTimer.singleShot(12000, win.check_wrapped)
    return app.exec()
