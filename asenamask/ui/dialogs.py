"""Overlays: result preview + save, information, settings."""
import os
import shutil

import os
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget, QLabel, QSlider, QFileDialog, QLineEdit,
                               QScrollArea, QComboBox, QFrame)

from .. import APP_NAME, BUILD_LABEL, sysinfo, sound
from .preview import PreviewPlayer, BACKGROUNDS
from .theme import theme
from .widgets import Overlay, GlowButton, ToggleSwitch, SwatchRow, Card, title_label, restyle_labels

EXT = {"mov": ".mov", "webm": ".webm", "mp4": ".mp4", "image": ".png", "png": ""}
FILTERS = {"mov": "ProRes 4444 video (*.mov)", "webm": "WebM video (*.webm)", "mp4": "MP4 video (*.mp4)",
           "image": "PNG image (*.png)"}



def _dur(sec):
    sec = int(round(float(sec or 0)))
    if sec >= 3600:
        return "%d h %02d min" % (sec // 3600, (sec % 3600) // 60)
    if sec >= 60:
        return "%d min %02d s" % (sec // 60, sec % 60)
    return "%d s" % sec


class ResultOverlay(Overlay):
    saved = Signal(str)
    discarded = Signal()

    def __init__(self, host, source):
        super().__init__(host, source, frac=(0.9, 0.9), max_size=(1280, 860), closable=False)
        self.result = None
        self.outputs = []
        self.kind = "mov"
        self.default_name = "asena_output"
        self.start_dir = ""
        L = self.panel_layout
        head = QHBoxLayout()
        self.title = title_label("Your cutout is ready", 17, QFont.Bold)
        head.addWidget(self.title)
        head.addStretch(1)
        self.meta = title_label("", 10, QFont.Normal, sub=True)
        head.addWidget(self.meta)
        L.addLayout(head)

        self.player = PreviewPlayer()
        L.addWidget(self.player, 1)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(12)
        self.play_btn = GlowButton("Pause", "ghost")
        self.play_btn.setFixedWidth(92)
        self.play_btn.clicked.connect(self.player.toggle)
        ctrl.addWidget(self.play_btn)
        self.scrub = QSlider(Qt.Horizontal)
        self.scrub.valueChanged.connect(self._scrub)
        ctrl.addWidget(self.scrub, 1)
        L.addLayout(ctrl)
        self.player.frame_changed.connect(self._on_frame)
        self.player.play_state.connect(lambda on: self.play_btn.setText("Pause" if on else "Play"))

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(title_label("Background:", 10, QFont.Normal, sub=True))
        self.bg_btns = {}
        for name in BACKGROUNDS:
            b = GlowButton(name, "chip")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, n=name: self._set_bg(n))
            self.bg_btns[name] = b
            bottom.addWidget(b)
        self.bg_btns["Checker"].setChecked(True)
        bottom.addStretch(1)
        self.discard_btn = GlowButton("Discard", "ghost")
        self.discard_btn.setFixedWidth(130)
        self.discard_btn.clicked.connect(self._discard)
        bottom.addWidget(self.discard_btn)
        self.save_btn = GlowButton("Save", "primary")
        self.save_btn.setFixedWidth(190)
        self.save_btn.clicked.connect(self._save)
        bottom.addWidget(self.save_btn)
        L.addLayout(bottom)

    def show_result(self, info, default_name, start_dir):
        self.result, self.kind = info["result"], info["kind"]
        self.outputs = info.get("outputs") or [{"result": info["result"], "kind": info["kind"], "label": ""}]
        self.title.setText("Your cutout is ready" if len(self.outputs) < 2 else
                           "Your cutouts are ready  (%d subjects, shown together)" % len(self.outputs))
        self.default_name, self.start_dir = default_name, start_dir
        self.player.load(info["preview_dir"], info["preview_fps"])
        n = max(1, self.player.count())
        self.scrub.blockSignals(True)
        self.scrub.setRange(0, n - 1)
        self.scrub.setValue(0)
        self.scrub.blockSignals(False)
        what = "image" if info["kind"] == "image" else "%d frames" % info["frames"]
        self.meta.setText("%d × %d  ·  " % (info["width"], info["height"]) + what + "  ·  done in %s  ·  preview is scaled down, the saved file is full quality"
                          % _dur(info["seconds"]))
        self.open_overlay()

    def on_open(self):
        self.player.play()

    def on_close(self):
        self.player.stop()

    def _on_frame(self, i):
        self.scrub.blockSignals(True)
        self.scrub.setValue(i)
        self.scrub.blockSignals(False)

    def _scrub(self, v):
        self.player.stop()
        self.player.seek(v)

    def _set_bg(self, name):
        for n, b in self.bg_btns.items():
            b.setChecked(n == name)
        self.player.set_background(name)

    def _discard(self):
        self.close_overlay()
        self.discarded.emit()

    @staticmethod
    def _unique(path):
        base, ext = os.path.splitext(path)
        n, cand = 2, path
        while os.path.exists(cand):
            cand = "%s_%d%s" % (base, n, ext)
            n += 1
        return cand

    def _save_many(self):
        parent = QFileDialog.getExistingDirectory(self.window(), "Choose where to save the %d files" % len(self.outputs),
                                                  self.start_dir)
        if not parent:
            return
        for k, o in enumerate(self.outputs):
            tag = "_" + (o.get("label") or "Subject %d" % (k + 1)).replace(" ", "").lower()
            stem = os.path.join(parent, self.default_name + tag)
            if o["kind"] == "png":
                shutil.copytree(o["result"], self._unique(stem))
            else:
                shutil.copy2(o["result"], self._unique(stem + EXT.get(o["kind"], "." + o["kind"])))
        self.saved.emit(parent)

    def _save(self):
        if not self.result:
            return
        if len(self.outputs) > 1:
            self._save_many()
            return
        start = os.path.join(self.start_dir, self.default_name) if self.start_dir else self.default_name
        if self.kind == "png":
            parent = QFileDialog.getExistingDirectory(self.window(), "Choose where to save the PNG sequence", self.start_dir)
            if not parent:
                return
            dest = os.path.join(parent, self.default_name)
            n = 2
            while os.path.exists(dest):
                dest = os.path.join(parent, "%s_%d" % (self.default_name, n))
                n += 1
            shutil.copytree(self.result, dest)
            self.saved.emit(dest)
        else:
            path, _ = QFileDialog.getSaveFileName(self.window(), "Save", start + EXT[self.kind], FILTERS[self.kind])
            if not path:
                return
            if not path.lower().endswith(EXT[self.kind]):
                path += EXT[self.kind]
            shutil.copy2(self.result, path)
            self.saved.emit(path)


class InfoOverlay(Overlay):
    specs_ready = Signal(dict)

    def __init__(self, host, source):
        super().__init__(host, source, frac=(0.8, 0.88), max_size=(760, 720))
        self.specs_ready.connect(self._fill)
        self._loaded = False
        L = self.panel_layout
        row = QHBoxLayout()
        row.addWidget(title_label("Information", 17, QFont.Bold))
        row.addStretch(1)
        b = GlowButton("Close", "ghost")
        b.setFixedWidth(100)
        b.clicked.connect(self.close_overlay)
        row.addWidget(b)
        L.addLayout(row)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.viewport().setAutoFillBackground(False)
        body = QWidget()
        body.setAutoFillBackground(False)
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 8, 0)
        bl.setSpacing(6)

        def h(t):
            bl.addSpacing(10)
            bl.addWidget(title_label(t, 12, QFont.Bold))

        def para(t, sel=True):
            l = title_label(t, 10, QFont.Normal, sub=True)
            l.setWordWrap(True)
            if sel:
                l.setTextInteractionFlags(Qt.TextSelectableByMouse)
            bl.addWidget(l)
            return l

        h("About")
        para("%s  ·  %s" % (APP_NAME, BUILD_LABEL))
        para("A free tool that removes backgrounds from videos on your own graphics card. "
             "Your videos are never uploaded anywhere. Created by Asenavfx.")
        h("Your PC")
        self.gpu_l = para("GPU: checking…")
        self.vram_l = para("VRAM: …")
        self.cpu_l = para("CPU: …")
        self.ram_l = para("RAM: …")
        self.os_l = para("System: …")
        self.gpu_note = para("")
        h("Powered by")
        para("SAM 3.1 by Meta  ·  ComfyUI")
        para("Interface: Qt for Python (PySide6)  ·  Video: FFmpeg")
        h("Disclaimer")
        para("Asena Mask is an independent project. It is not affiliated with, endorsed by, or sponsored by "
             "Meta Platforms, Inc. or Comfy Org. Provided “as is”, without warranty of any kind.")
        para("© 2026 Asenavfx. Third-party components are used under their own licenses.")
        bl.addStretch(1)
        sc.setWidget(body)
        L.addWidget(sc, 1)

    def on_open(self):
        if not self._loaded:
            self._loaded = True
            threading.Thread(target=lambda: self.specs_ready.emit(sysinfo.collect()), daemon=True).start()

    def _fill(self, d):
        g = d.get("gpu")
        if g:
            self.gpu_l.setText("GPU: %s" % g["name"])
            self.vram_l.setText("VRAM: %s GB   ·   Driver %s" % (g["vram_gb"], g["driver"]) if g.get("vram_gb")
                                else "VRAM: –")
            if "nvidia" not in g["name"].lower():
                self.gpu_note.setText("Asena Mask is made for NVIDIA graphics cards. Other cards only work in the "
                                      "experimental build.")
        else:
            self.gpu_l.setText("GPU: none detected")
            self.vram_l.setText("VRAM: –")
            self.gpu_note.setText("Asena Mask needs an NVIDIA graphics card (RTX recommended).")
        self.cpu_l.setText("CPU: %s" % d.get("cpu", "?"))
        self.ram_l.setText("RAM: %s GB" % (d.get("ram") or "?"))
        self.os_l.setText("System: %s" % d.get("os", "?"))


class SettingsOverlay(Overlay):
    theme_changed = Signal(str)
    accent_changed = Signal(str)
    bg_toggled = Signal(bool)

    def __init__(self, host, source, settings):
        super().__init__(host, source, frac=(0.8, 0.9), max_size=(700, 800))
        self.s = settings
        L = self.panel_layout
        row = QHBoxLayout()
        row.addWidget(title_label("Settings", 17, QFont.Bold))
        row.addStretch(1)
        row.addWidget(title_label(BUILD_LABEL, 10, QFont.Normal, sub=True))
        row.addSpacing(10)
        cb = GlowButton("Close", "ghost")
        cb.setFixedWidth(100)
        cb.clicked.connect(self.close_overlay)
        row.addWidget(cb)
        L.addLayout(row)

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.viewport().setAutoFillBackground(False)
        body = QWidget()
        body.setAutoFillBackground(False)
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 8, 0)
        bl.setSpacing(14)

        def toggle_row(title, sub, checked):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(title_label(title, 11, QFont.DemiBold))
            if sub:
                col.addWidget(title_label(sub, 9, QFont.Normal, sub=True))
            h.addLayout(col, 1)
            t = ToggleSwitch(checked)
            h.addWidget(t)
            bl.addWidget(w)
            return t

        bl.addWidget(title_label("Appearance", 12, QFont.Bold))
        self.dark = toggle_row("Dark mode", "Turn off for the light look.", settings.get("theme") == "dark")
        self.dark.toggled.connect(lambda on: self.theme_changed.emit("dark" if on else "light"))
        bl.addWidget(title_label("Accent colour", 11, QFont.DemiBold))
        self.swatches = SwatchRow(settings.get("accent"))
        self.swatches.chosen.connect(self.accent_changed)
        bl.addWidget(self.swatches)
        self.animbg = toggle_row("Animated intro background", "The slowly moving glow on the welcome screen.",
                                 bool(settings.get("anim_bg")))
        self.animbg.toggled.connect(lambda on: (settings.set("anim_bg", on), self.bg_toggled.emit(on)))
        self.snd = toggle_row("Sound effects", "Small clicks and chimes.", bool(settings.get("sounds")))
        self.snd.toggled.connect(self._sound)

        bl.addSpacing(4)
        bl.addWidget(title_label("General", 12, QFont.Bold))
        bl.addWidget(title_label("Your name", 11, QFont.DemiBold))
        self.name = QLineEdit(settings.get("name"))
        self.name.setPlaceholderText("Optional")
        self.name.editingFinished.connect(lambda: settings.set("name", self.name.text().strip()))
        bl.addWidget(self.name)
        self.openf = toggle_row("Open the folder after saving", None, bool(settings.get("open_folder_after_save")))
        self.openf.toggled.connect(lambda on: settings.set("open_folder_after_save", on))
        bl.addWidget(title_label("GPU memory use", 11, QFont.DemiBold))
        self.gpu = QComboBox()
        self.gpu.addItems(["Low (4 frames at a time)", "Normal (8 frames at a time)", "High (16 frames at a time)"])
        self.gpu.setCurrentIndex({"low": 0, "normal": 1, "high": 2}.get(settings.get("gpu_load"), 1))
        self.gpu.currentIndexChanged.connect(lambda i: settings.set("gpu_load", ["low", "normal", "high"][i]))
        bl.addWidget(self.gpu)
        bl.addWidget(title_label("Lower this if you see out-of-memory errors.", 9, QFont.Normal, sub=True))

        if os.environ.get("ASENA_DEV") == "1":   # developer-only: engine file locations
            bl.addSpacing(6)
            bl.addWidget(title_label("Engine files (advanced)", 12, QFont.Bold))
            self.comfy = self._path_field(bl, "ComfyUI folder (contains main.py)", "comfy_dir", settings.comfy_dir())
            self.ckdir = self._path_field(bl, "Model folder", "ckpt_dir", settings.ckpt_dir())
            self.ckname = self._path_field(bl, "Model file name", "ckpt_name", settings.get("ckpt_name"))
        bl.addStretch(1)
        sc.setWidget(body)
        L.addWidget(sc, 1)

    def _sound(self, on):
        self.s.set("sounds", on)
        if not on:
            sound.play("small")   # last sound before going quiet
        sound.enabled = on

    def _path_field(self, layout, label, key, value):
        layout.addWidget(title_label(label, 10, QFont.Normal, sub=True))
        e = QLineEdit(value)
        e.editingFinished.connect(lambda: e.text().strip() != value and self.s.set(key, e.text().strip()))
        layout.addWidget(e)
        return e
