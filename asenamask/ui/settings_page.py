"""Settings page: sections on the left, the options of the chosen section on the right. Every change is saved at once."""
import os
import subprocess
import threading

from PySide6.QtCore import Qt, Signal, QUrl, QObject
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtWidgets import (QBoxLayout, QListView, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QStackedWidget, QScrollArea, QFrame,
                               QLineEdit, QComboBox, QFileDialog, QApplication, QSpinBox)

from .. import APP_NAME, BUILD_LABEL, APP_VERSION, discordrp, paths, sound, sysinfo, telemetry
from .theme import theme, LOOKS
from .widgets import GlowButton, Card, ToggleSwitch, SwatchRow, title_label
from .workspace import field, toggle_field

NAME_TOKENS = "{prefix} = your file name prefix   {clip} = the clip's name   {date} = 2026-10-02   {time} = 14-30   {format}"
SECTIONS = ["General", "Output", "Performance", "Notifications", "Updates", "Privacy", "About"]


class _Bridge(QObject):
    text = Signal(str)


def _open_path(path):
    try:
        if os.name == "nt":
            os.startfile(path)                       # noqa
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    look_changed = Signal(str)
    accent_changed = Signal(str)
    bg_toggled = Signal(bool)
    check_updates = Signal()
    open_wrapped = Signal()
    message = Signal(str)                            # short status text for the app's toast

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self.bridge = _Bridge()
        self.bridge.text.connect(self._copy_ready)
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 6, 26, 18)
        root.setSpacing(12)
        root.addWidget(title_label("Settings", 22, QFont.Bold))
        row = QHBoxLayout()
        row.setSpacing(16)
        root.addLayout(row, 1)

        self.row = row
        self.nav = QListWidget()
        self.nav.setFixedWidth(190)
        self.nav.setFocusPolicy(Qt.NoFocus)
        self.nav.addItems(SECTIONS)
        row.addWidget(self.nav)
        card = Card(radius=22)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(6, 10, 6, 10)
        self.stack = QStackedWidget()
        cl.addWidget(self.stack)
        row.addWidget(card, 1)

        for name in SECTIONS:
            self.stack.addWidget(self._scroll(getattr(self, "_build_" + name.lower())()))
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        theme.changed.connect(self.apply_look)
        self.apply_look()

    def apply_look(self):
        """Retro: the section list becomes a row of tabs along the top."""
        retro = theme.look == "retro"
        self.row.setDirection(QBoxLayout.TopToBottom if retro else QBoxLayout.LeftToRight)
        if retro:
            self.nav.setFlow(QListView.LeftToRight)
            self.nav.setWrapping(False)
            self.nav.setMinimumWidth(0)
            self.nav.setMaximumWidth(16777215)
            self.nav.setFixedHeight(54)
            self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        else:
            self.nav.setFlow(QListView.TopToBottom)
            self.nav.setMinimumHeight(0)
            self.nav.setMaximumHeight(16777215)
            self.nav.setFixedWidth(190)
            self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    # ----- helpers
    def _scroll(self, body):
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.viewport().setAutoFillBackground(False)
        body.setAutoFillBackground(False)
        sc.setWidget(body)
        return sc

    def _page(self, title, sub=None):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(20, 12, 20, 12)
        v.setSpacing(14)
        v.addWidget(title_label(title, 14, QFont.Bold))
        if sub:
            l = title_label(sub, 10, QFont.Normal, sub=True)
            l.setWordWrap(True)
            v.addWidget(l)
        return w, v

    def _toggle(self, v, title, hint, key, extra=None):
        w, t = toggle_field(title, hint, bool(self.s.get(key)))

        def changed(on):
            self.s.set(key, bool(on))
            if extra:
                extra(on)
        t.toggled.connect(changed)
        v.addWidget(w)
        return t

    def _combo(self, v, label, hint, key, choices):
        """choices: list of (text, value)."""
        c = QComboBox()
        cur = self.s.get(key)
        for i, (text, val) in enumerate(choices):
            c.addItem(text)
            if val == cur:
                c.setCurrentIndex(i)
        c.currentIndexChanged.connect(lambda i: self.s.set(key, choices[i][1]))
        v.addWidget(field(label, c, hint))
        return c

    def _path_row(self, v, label, value, open_it=True):
        e = QLineEdit(value)
        e.setReadOnly(True)
        v.addWidget(field(label, e))
        if open_it and value:
            b = GlowButton("Open folder", "chip")
            b.clicked.connect(lambda: _open_path(value if os.path.isdir(value) else os.path.dirname(value)))
            v.addWidget(b, 0, Qt.AlignLeft)
        return e

    # ----- sections
    def _build_general(self):
        w, v = self._page("General")
        v.addWidget(title_label("LOOK", 8, QFont.DemiBold, sub=True))
        self.look_combo = QComboBox()
        self._look_keys = list(LOOKS)
        for k in self._look_keys:
            self.look_combo.addItem(LOOKS[k]["label"])
        cur = self.s.get("look")
        self.look_combo.setCurrentIndex(self._look_keys.index(cur) if cur in self._look_keys else 0)
        self.look_blurb = title_label("", 9, QFont.Normal, sub=True)
        self.look_blurb.setWordWrap(True)
        v.addWidget(field("Style of the whole app", self.look_combo, None))
        v.addWidget(self.look_blurb)
        self.look_combo.currentIndexChanged.connect(self._look_picked)
        self.aurora_box = QWidget()
        ab = QVBoxLayout(self.aurora_box)
        ab.setContentsMargins(0, 0, 0, 0)
        ab.setSpacing(14)
        dark, t = toggle_field("Dark mode", "Turn off for the light look.", self.s.get("theme") == "dark")
        t.toggled.connect(lambda on: self.theme_changed.emit("dark" if on else "light"))
        ab.addWidget(dark)
        ab.addWidget(title_label("ACCENT COLOUR", 8, QFont.DemiBold, sub=True))
        sw = SwatchRow(self.s.get("accent"))
        sw.chosen.connect(self.accent_changed)
        ab.addWidget(sw)
        v.addWidget(self.aurora_box)
        self._look_ui(self._look_keys[self.look_combo.currentIndex()])
        self._toggle(v, "Animated intro background", "The slowly moving glow on the welcome screen.", "anim_bg",
                     lambda on: self.bg_toggled.emit(on))
        self._toggle(v, "Sound effects", "Small clicks and chimes.", "sounds", self._sound)
        self._toggle(v, "24-hour clock", "For the clock on the Home page.", "clock_24h",
                     lambda on: self.message.emit("Clock updated."))
        name = QLineEdit(self.s.get("name"))
        name.setPlaceholderText("Optional")
        name.editingFinished.connect(lambda: self.s.set("name", name.text().strip()))
        v.addWidget(field("Your name", name, "Used for the greeting on the Home page."))
        self._combo(v, "Open the app on", "Which page you see when Asena Mask starts.", "start_page",
                    [("Home", "home"), ("The last project", "project")])
        v.addStretch(1)
        return w

    def _look_ui(self, key):
        self.look_blurb.setText(LOOKS[key]["blurb"] + ("" if key == "aurora" else
                                "  Dark mode and accent colours belong to the Aurora look."))
        self.aurora_box.setVisible(key == "aurora")

    def _look_picked(self, i):
        key = self._look_keys[i]
        self._look_ui(key)
        self.s.set("look", key)
        self.look_changed.emit(key)

    def _sound(self, on):
        if not on:
            sound.play("small")
        sound.enabled = on

    def _build_output(self):
        w, v = self._page("Output", "Where results go and what they are called.")
        row = QHBoxLayout()
        self.out_dir = QLineEdit(self.s.get("out_dir"))
        self.out_dir.setPlaceholderText("Ask me each time (starts in the last folder you used)")
        self.out_dir.editingFinished.connect(lambda: self.s.set("out_dir", self.out_dir.text().strip()))
        row.addWidget(self.out_dir, 1)
        b = GlowButton("Choose…", "chip")
        b.setMinimumHeight(36)
        b.clicked.connect(self._pick_out)
        row.addWidget(b)
        rw = QWidget()
        rw.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        v.addWidget(field("Default save folder", rw, "The Save window opens here. Leave empty to use the last folder."))
        pat = QLineEdit(self.s.get("name_pattern"))
        pat.editingFinished.connect(lambda: self.s.set("name_pattern", pat.text().strip() or "{prefix}_{clip}"))
        v.addWidget(field("File name pattern", pat, NAME_TOKENS))
        self._toggle(v, "Open the folder after saving", "Shows the saved file in Explorer.", "open_folder_after_save")
        v.addStretch(1)
        return w

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self.window(), "Default save folder", self.s.get("out_dir") or "")
        if d:
            self.out_dir.setText(d)
            self.s.set("out_dir", d)

    def _build_performance(self):
        w, v = self._page("Performance", "Lower these if you see out-of-memory errors or want your PC free for other things.")
        self._combo(v, "GPU memory use", "How many frames are processed at once.", "gpu_load",
                    [("Low (4 frames at a time)", "low"), ("Normal (8 frames at a time)", "normal"),
                     ("High (16 frames at a time)", "high")])
        self._combo(v, "Free the GPU when idle after", "The AI engine goes to sleep and gives your video memory back.",
                    "idle_minutes", [("1 minute", 1), ("2 minutes", 2), ("5 minutes", 5), ("10 minutes", 10),
                                     ("30 minutes", 30)])
        self._toggle(v, "Live selection highlight on by default", "In the Trim & pick window, show what the AI selects "
                                                                   "while you click and paint.", "live_default")
        v.addStretch(1)
        return w

    def _build_notifications(self):
        w, v = self._page("Notifications")
        self._toggle(v, "Tell me when a job finishes", "A Windows notification and a flashing taskbar icon when you are "
                                                        "in another window.", "notify_done")
        self._combo(v, "When a batch queue finishes", "Handy for overnight batches.", "after_queue",
                    [("Do nothing", "none"), ("Put the PC to sleep", "sleep"), ("Shut the PC down", "shutdown")])
        v.addWidget(title_label("You get a 60 second warning with a Cancel button before anything happens.", 9,
                                QFont.Normal, sub=True))
        v.addStretch(1)
        return w

    def _build_updates(self):
        w, v = self._page("Updates")
        v.addWidget(title_label("You have version %s" % APP_VERSION, 11, QFont.DemiBold))
        self._toggle(v, "Check for updates when the app starts", "Only a tiny file is read from asenatools.com.",
                     "auto_update")
        b = GlowButton("Check now", "ghost")
        b.setMinimumHeight(40)
        b.clicked.connect(self.check_updates)
        v.addWidget(b, 0, Qt.AlignLeft)
        v.addStretch(1)
        return w

    def _build_privacy(self):
        w, v = self._page("Privacy", "Your videos, images and prompts never leave your PC.")
        T = telemetry.T
        hint = ("Totals like how many cutouts and frames you made, which formats you use, your PC type (Windows, graphics card, "
                "memory) and your continent. Never file names, folders, anything from your videos, your name, e-mail or IP address."
                if T.available else "Sharing isn't set up in this build, so nothing leaves your PC.")
        wt, t = toggle_field("Share anonymous usage stats", hint, T.wanted)
        t.setEnabled(T.available)
        t.toggled.connect(lambda on: (T.set_enabled(bool(on)), T.flush() if on else None))
        v.addWidget(wt)
        l = title_label("Combined totals from many people may be shown publicly, never anything about one person.", 9, QFont.Normal, sub=True)
        l.setWordWrap(True)
        v.addWidget(l)
        self._toggle(v, "Show \"Playing Asena Mask\" in Discord", "Only when the Discord app is open on this PC. Never your files or prompts.",
                     "discord_presence", lambda on: (discordrp.P.set_enabled(on), discordrp.P.idle() if on else None))
        b = GlowButton("Open Your Asena Wrapped" if telemetry.WRAPPED_ENABLED else "Show exactly what would be sent", "primary" if telemetry.WRAPPED_ENABLED else "chip")
        b.setMinimumHeight(42)
        b.setFixedWidth(260 if telemetry.WRAPPED_ENABLED else 280)
        b.clicked.connect(self.open_wrapped)
        v.addWidget(b, 0, Qt.AlignLeft)
        v.addStretch(1)
        return w

    def _build_about(self):
        w, v = self._page("About")
        v.addWidget(title_label("%s  ·  %s" % (APP_NAME, BUILD_LABEL), 11, QFont.DemiBold))
        l = title_label("A free tool that removes backgrounds from videos on your own graphics card. Your videos are never "
                        "uploaded anywhere. Created by Asenavfx.", 10, QFont.Normal, sub=True)
        l.setWordWrap(True)
        v.addWidget(l)
        row = QHBoxLayout()
        for text, url in (("Website", "https://asenatools.com"), ("Support on Ko-fi", "https://ko-fi.com/asenavfx")):
            b = GlowButton(text, "chip")
            b.setMinimumHeight(34)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        v.addSpacing(8)
        v.addWidget(title_label("Something not working?", 12, QFont.Bold))
        h = title_label("Press the button, then paste (Ctrl+V) into your message to the developer. It contains your PC's "
                        "graphics card, the app version and the engine status. No files, no personal data.", 10,
                        QFont.Normal, sub=True)
        h.setWordWrap(True)
        v.addWidget(h)
        self.copy_btn = GlowButton("Copy system info", "primary")
        self.copy_btn.setMinimumHeight(42)
        self.copy_btn.setFixedWidth(220)
        self.copy_btn.clicked.connect(self._copy_info)
        v.addWidget(self.copy_btn, 0, Qt.AlignLeft)
        lb = GlowButton("Open the log folder", "chip")
        lb.clicked.connect(lambda: _open_path(str(paths.work_root())))
        v.addWidget(lb, 0, Qt.AlignLeft)
        d = title_label("© 2026 Asenavfx. Independent project, not affiliated with Meta Platforms, Inc. or Comfy Org. "
                        "Provided “as is”, without warranty of any kind.", 9, QFont.Normal, sub=True)
        d.setWordWrap(True)
        v.addSpacing(10)
        v.addWidget(d)
        v.addStretch(1)
        return w

    def _copy_info(self):
        self.copy_btn.setEnabled(False)
        self.copy_btn.setText("Collecting…")
        threading.Thread(target=lambda: self.bridge.text.emit(sysinfo.report(self.s)), daemon=True).start()

    def _copy_ready(self, text):
        QApplication.clipboard().setText(text)
        self.copy_btn.setEnabled(True)
        self.copy_btn.setText("Copy system info")
        self.message.emit("System info copied. Paste it into your message.")
