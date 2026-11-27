"""The branded installer window (PySide6). Logic lives in core.py."""
import os
import sys

from PySide6.QtCore import Qt, QThread, Signal, QRectF, QTimer, QPropertyAnimation
from PySide6.QtGui import QPainter, QLinearGradient, QColor, QPainterPath, QPen, QFont, QIcon, QRadialGradient
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QLabel,
                               QMessageBox, QFileDialog)

from asenamask import paths, sound
from asenamask.ui.theme import theme, stylesheet
from asenamask.ui.widgets import GlowButton, IconButton, ProgressStrip, ToggleSwitch, title_label, restyle_labels

try:
    from . import core
    from . import config as C
except ImportError:
    import core
    import config as C


class LogoMark(QWidget):
    def __init__(self, size=100, parent=None):
        super().__init__(parent)
        from PySide6.QtGui import QPixmap
        self.setFixedSize(size, size)
        f = paths.asset("logo.png")
        self.img = QPixmap(f) if os.path.isfile(f) else None

    def paintEvent(self, e):
        if self.img is None or self.img.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(QRectF(self.rect()), self.img, QRectF(self.img.rect()))


class Worker(QThread):
    step = Signal(int, str)
    progress = Signal(float, str)
    done = Signal()
    failed = Signal(str, str)
    cancelled = Signal()

    def __init__(self, install_dir, desktop, share_stats=False):
        super().__init__()
        self.inst = core.Installer(install_dir, desktop, self.step.emit, self.progress.emit, share_stats)

    def run(self):
        try:
            self.inst.run()
            self.done.emit()
        except core.Cancelled:
            self.cancelled.emit()
        except core.InstallError as e:
            core.log("ERROR: %s | %s" % (e.friendly, e.technical))
            self.failed.emit(e.friendly, e.technical)
        except PermissionError as e:
            core.log("ERROR perm: %s" % e)
            self.failed.emit("A file is in use. If Asena Mask is open, close it and try again.", str(e))
        except Exception as e:
            import traceback
            core.log("ERROR: " + traceback.format_exc())
            self.failed.emit("Something unexpected went wrong.", str(e))


class UpdateWorker(QThread):
    progress = Signal(float, str)
    done = Signal(str)
    failed = Signal(str, str)

    def __init__(self, upd):
        super().__init__()
        self.upd = upd

    def run(self):
        u = self.upd
        try:
            ver = core.apply_update(u["zip"], u["dir"], u.get("pid"), u.get("info"), self.progress.emit)
            self.done.emit(ver)
        except core.InstallError as e:
            core.log("UPDATE ERROR: %s | %s" % (e.friendly, e.technical))
            self.failed.emit(e.friendly, e.technical)
        except Exception as e:
            import traceback
            core.log("UPDATE ERROR: " + traceback.format_exc())
            self.failed.emit("The update could not be installed. Your old version was kept.", str(e))


def wrap_label(text, size=11, sub=True, align=Qt.AlignHCenter):
    l = title_label(text, size, QFont.Normal, sub=sub)
    l.setWordWrap(True)
    l.setAlignment(align | Qt.AlignTop)
    return l


class SetupWindow(QWidget):
    def __init__(self, uninstall_mode=False, update=None):
        super().__init__()
        self.upd = update
        self.setWindowTitle(C.APP_NAME + (" Setup (experimental)" if C.EXPERIMENTAL else " Setup"))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(680, 600)
        theme.set("dark")
        self.setStyleSheet(stylesheet())
        self.worker = None
        self.install_dir = core.default_install_dir()
        existing = core.installed_dir_from_registry()
        self.existing = existing if existing and core.read_install(existing) else None
        if self.existing:
            self.install_dir = self.existing
        self.busy = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(14, 10, 10, 0)
        bar.addStretch(1)
        mn, cl = IconButton("min"), IconButton("close")
        mn.clicked.connect(self.showMinimized)
        cl.clicked.connect(self.close)
        bar.addWidget(mn)
        bar.addWidget(cl)
        lay.addLayout(bar)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        self.p_welcome = self._build_welcome()
        self.p_progress = self._build_progress()
        self.p_done = self._build_done()
        self.p_uninst = self._build_uninstall()
        self.p_update = self._build_update()
        for p in (self.p_welcome, self.p_progress, self.p_done, self.p_uninst, self.p_update):
            self.stack.addWidget(p)
        self.stack.setCurrentWidget(self.p_uninst if uninstall_mode else self.p_welcome)
        if update:
            self.stack.setCurrentWidget(self.p_update)
            QTimer.singleShot(200, self.start_update)

    # ------------------------------------------------------------ painting / moving
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 18, 18)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0.0, theme.col("bg1"))
        g.setColorAt(0.55, theme.col("bg2"))
        g.setColorAt(1.0, theme.col("bg3"))
        p.fillPath(path, g)
        glow = QColor(theme.col("accent2"))
        glow.setAlpha(46)
        rg = QRadialGradient(self.width() * 0.5, 0, self.width() * 0.7)
        rg.setColorAt(0, glow)
        rg.setColorAt(1, QColor(glow.red(), glow.green(), glow.blue(), 0))
        p.setClipPath(path)
        p.fillRect(self.rect(), rg)
        p.setClipping(False)
        ac = theme.col("accent")
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(ac.red(), ac.green(), ac.blue(), 80), 1.2))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6), 18, 18)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 56:
            h = self.windowHandle()
            if h:
                h.startSystemMove()

    def closeEvent(self, e):
        if self.busy:
            if not self.confirm_cancel():
                e.ignore()
                return
            self.worker.inst.request_cancel()
            self.worker.wait(4000)
        e.accept()

    def confirm_cancel(self):
        box = QMessageBox(self)
        box.setWindowTitle(C.APP_NAME)
        box.setIcon(QMessageBox.Warning)
        box.setText("Stop installing Asena Mask?")
        box.setInformativeText("Asena Mask will not be ready to use. Your downloads are kept, so next time the "
                               "installer will continue where it stopped.")
        stop = box.addButton("Stop installing", QMessageBox.DestructiveRole)
        box.addButton("Keep installing", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is stop

    # ------------------------------------------------------------ screens
    def _page(self):
        w = QWidget()
        w.setAutoFillBackground(False)
        v = QVBoxLayout(w)
        v.setContentsMargins(52, 0, 52, 34)
        v.setSpacing(10)
        return w, v

    def _build_welcome(self):
        w, v = self._page()
        logo = LogoMark(104)
        v.addWidget(logo, 0, Qt.AlignHCenter)
        v.addSpacing(6)
        v.addWidget(self._center(title_label(C.APP_NAME, 26, QFont.Bold)))
        self.w_sub = wrap_label("Remove video backgrounds right on your GPU.", 12)
        v.addWidget(self.w_sub)
        v.addSpacing(10)
        if C.EXPERIMENTAL:
            self.w_sub.setText("EXPERIMENTAL build for AMD Radeon and Intel Arc")
            self.w_info = wrap_label(
                "This test version runs Asena Mask on AMD Radeon (RX 7000 / 9000, driver Adrenalin 26.2.2 or "
                "newer) or Intel Arc graphics cards. It is not guaranteed to work. If anything fails, press "
                "'Open log file' at the end and send that file to the developer. About 8 GB will be "
                "downloaded.", 10)
        else:
            self.w_info = wrap_label(
                "Setup will download the AI engine and model (about 6 GB) and set everything up for you. "
                "An NVIDIA graphics card is required.", 10)
        v.addWidget(self.w_info)
        v.addSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.dir_lbl = title_label(self.install_dir, 9, QFont.Normal, sub=True)
        self.dir_lbl.setWordWrap(True)
        cap = title_label("INSTALL FOLDER", 8, QFont.DemiBold, sub=True)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(cap)
        col.addWidget(self.dir_lbl)
        row.addLayout(col, 1)
        self.change_btn = GlowButton("Change…", "chip")
        self.change_btn.clicked.connect(self._pick_dir)
        row.addWidget(self.change_btn)
        v.addLayout(row)

        sc = QHBoxLayout()
        self.desk = ToggleSwitch(True)
        sc.addWidget(self.desk)
        sc.addWidget(title_label("Create a desktop shortcut", 10, QFont.Normal))
        sc.addStretch(1)
        v.addLayout(sc)

        st = QHBoxLayout()
        self.stats = ToggleSwitch(False)
        st.addWidget(self.stats, 0, Qt.AlignTop)
        stc = QVBoxLayout()
        stc.setSpacing(2)
        stc.addWidget(title_label("Share anonymous usage stats", 10, QFont.Normal))
        stc.addWidget(wrap_label("Simple totals only (cutouts, frames, formats, PC type, continent). Never your videos, files, "
                                 "names or IP address. Off unless you switch it on; change it any time in Settings > Privacy.", 8, align=Qt.AlignLeft))
        st.addLayout(stc, 1)
        v.addLayout(st)
        v.addStretch(1)

        self.lic = wrap_label("By installing you agree to the licenses of the included open-source components "
                              "and the SAM model licence.", 8)
        v.addWidget(self.lic)
        self.btn_row = QHBoxLayout()
        self.btn_row.setSpacing(10)
        self.install_btn = GlowButton("Install", "primary")
        self.install_btn.setMinimumHeight(46)
        self.install_btn.set_breathing(True)
        self.install_btn.clicked.connect(self.start_install)
        self.open_btn = GlowButton("Open Asena Mask", "primary")
        self.open_btn.setMinimumHeight(46)
        self.open_btn.clicked.connect(self._open_existing)
        self.reinstall_btn = GlowButton("Repair / reinstall", "ghost")
        self.reinstall_btn.setMinimumHeight(46)
        self.reinstall_btn.clicked.connect(self.start_install)
        self.remove_btn = GlowButton("Uninstall", "chip")
        self.remove_btn.clicked.connect(lambda: self.stack.setCurrentWidget(self.p_uninst))
        for b in (self.open_btn, self.reinstall_btn, self.install_btn):
            self.btn_row.addWidget(b)
        v.addLayout(self.btn_row)
        v.addWidget(self.remove_btn, 0, Qt.AlignHCenter)
        if self.existing:
            self.w_sub.setText("Asena Mask is already installed on this PC.")
            self.install_btn.hide()
            self.change_btn.hide()
            self.dir_lbl.setText(self.existing)
        else:
            self.open_btn.hide()
            self.reinstall_btn.hide()
            self.remove_btn.hide()
        return w

    def _center(self, widget):
        widget.setAlignment(Qt.AlignHCenter)
        return widget

    def _build_progress(self):
        w, v = self._page()
        v.addWidget(LogoMark(64), 0, Qt.AlignHCenter)
        v.addSpacing(8)
        self.step_title = self._center(title_label("Getting ready…", 20, QFont.Bold))
        v.addWidget(self.step_title)
        self.step_detail = wrap_label("", 11)
        v.addWidget(self.step_detail)
        v.addSpacing(8)
        self.bar = ProgressStrip()
        v.addWidget(self.bar)
        self.pct = self._center(title_label("0%", 10, QFont.DemiBold, sub=True))
        v.addWidget(self.pct)
        v.addSpacing(6)
        self.step_labels = []
        for _, title, _w in C.STEPS:
            l = title_label("○  " + title, 10, QFont.Normal, sub=True)
            l.setContentsMargins(120, 0, 0, 0)
            self.step_labels.append(l)
            v.addWidget(l)
        v.addStretch(1)
        self.cancel_btn = GlowButton("Cancel", "ghost")
        self.cancel_btn.setMinimumHeight(42)
        self.cancel_btn.clicked.connect(self.close)
        v.addWidget(self.cancel_btn, 0, Qt.AlignHCenter)
        self.cancel_btn.setFixedWidth(180)
        return w

    def _build_done(self):
        w, v = self._page()
        v.addStretch(1)
        v.addWidget(LogoMark(96), 0, Qt.AlignHCenter)
        v.addSpacing(8)
        self.done_title = self._center(title_label("You're all set", 24, QFont.Bold))
        v.addWidget(self.done_title)
        self.done_text = wrap_label("", 11)
        v.addWidget(self.done_text)
        v.addStretch(1)
        self.done_row = QHBoxLayout()
        self.done_row.setSpacing(10)
        self.done_primary = GlowButton("Open Asena Mask", "primary")
        self.done_primary.setMinimumHeight(46)
        self.done_secondary = GlowButton("Close", "ghost")
        self.done_secondary.setMinimumHeight(46)
        self.done_secondary.clicked.connect(self.close)
        self.log_btn = GlowButton("Open log file", "chip")
        self.log_btn.clicked.connect(lambda: os.startfile(core.LOG_PATH) if os.name == "nt" else None)
        self.done_row.addWidget(self.done_secondary)
        self.done_row.addWidget(self.done_primary)
        v.addLayout(self.done_row)
        v.addWidget(self.log_btn, 0, Qt.AlignHCenter)
        self.log_btn.hide()
        return w

    def _build_update(self):
        w, v = self._page()
        v.addStretch(1)
        v.addWidget(LogoMark(88), 0, Qt.AlignHCenter)
        v.addSpacing(8)
        v.addWidget(self._center(title_label("Updating Asena Mask", 22, QFont.Bold)))
        self.up_detail = wrap_label("Getting ready…", 11)
        v.addWidget(self.up_detail)
        v.addSpacing(10)
        self.up_bar = ProgressStrip()
        v.addWidget(self.up_bar)
        v.addStretch(1)
        return w

    def start_update(self):
        self.busy = False
        self.up_bar.set_busy(True)
        self.uworker = UpdateWorker(self.upd)
        self.uworker.progress.connect(lambda f, t: (self.up_bar.set_value(f), self.up_detail.setText(t)))
        self.uworker.done.connect(self.on_update_done)
        self.uworker.failed.connect(self.on_update_failed)
        self.uworker.start()

    def on_update_done(self, ver):
        self.up_bar.set_busy(False)
        self.up_detail.setText("Version %s is ready. Opening Asena Mask…" % ver)
        sound.play("output")
        core.launch_app(self.upd["dir"])
        QTimer.singleShot(1200, self.close)

    def on_update_failed(self, friendly, technical):
        self.up_bar.set_busy(False)
        self.done_title.setText("The update did not install")
        self.done_text.setText(friendly)
        self.done_primary.setText("Open Asena Mask")
        try:
            self.done_primary.clicked.disconnect()
        except Exception:
            pass
        self.done_primary.clicked.connect(self._open_updated_dir)
        self.log_btn.show()
        self.stack.setCurrentWidget(self.p_done)

    def _open_updated_dir(self):
        core.launch_app(self.upd["dir"])
        self.close()

    def _build_uninstall(self):
        w, v = self._page()
        v.addStretch(1)
        v.addWidget(LogoMark(88), 0, Qt.AlignHCenter)
        v.addSpacing(8)
        v.addWidget(self._center(title_label("Remove Asena Mask?", 22, QFont.Bold)))
        self.un_text = wrap_label("This deletes the app, its AI engine and the model from this PC. "
                                  "Your settings stay, so reinstalling is quick.", 11)
        v.addWidget(self.un_text)
        v.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(10)
        keep = GlowButton("Keep it", "ghost")
        keep.setMinimumHeight(46)
        keep.clicked.connect(self.close)
        self.un_btn = GlowButton("Uninstall", "primary")
        self.un_btn.setMinimumHeight(46)
        self.un_btn.clicked.connect(self.do_uninstall)
        row.addWidget(keep)
        row.addWidget(self.un_btn)
        v.addLayout(row)
        return w

    # ------------------------------------------------------------ actions
    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose where to install Asena Mask", os.path.dirname(self.install_dir))
        if d:
            d = os.path.normpath(d)
            if os.path.basename(d).lower() != C.APP_NAME.lower():
                d = os.path.join(d, C.APP_NAME)
            self.install_dir = d
            self.dir_lbl.setText(d)

    def _open_existing(self):
        core.launch_app(self.existing)
        self.close()

    def start_install(self):
        self.busy = True
        for l, (_, t, _w) in zip(self.step_labels, C.STEPS):
            l.setText("○  " + t)
        self.bar.reset()
        self.bar.set_busy(True)
        self.stack.setCurrentWidget(self.p_progress)
        self.worker = Worker(self.install_dir, self.desk.isChecked(), self.stats.isChecked())
        self.worker.step.connect(self.on_step)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.cancelled.connect(self.close)
        self.worker.start()

    def on_step(self, i, title):
        self.step_title.setText(title)
        for k, (l, (_, t, _w)) in enumerate(zip(self.step_labels, C.STEPS)):
            l.setText(("✓  " if k < i else "●  " if k == i else "○  ") + t)
            col = "text" if k == i else "sub"
            l.setStyleSheet("color: %s; background: transparent;" % theme.css(col))

    def on_progress(self, frac, detail):
        self.bar.set_value(frac)
        self.pct.setText("%d%%" % int(frac * 100))
        self.step_detail.setText(detail)

    def on_done(self):
        self.busy = False
        self.bar.set_busy(False)
        sound.play("output")
        self.done_title.setText("You're all set")
        self.done_text.setText("Asena Mask is installed. You can find it in your Start menu"
                               + (" and on your desktop." if self.desk.isChecked() else "."))
        self.done_primary.setText("Open Asena Mask")
        try:
            self.done_primary.clicked.disconnect()
        except Exception:
            pass
        self.done_primary.clicked.connect(self._open_new)
        self.done_primary.show()
        self.done_secondary.setText("Close")
        self.log_btn.hide()
        self.stack.setCurrentWidget(self.p_done)

    def _open_new(self):
        core.launch_app(self.install_dir)
        self.close()

    def on_failed(self, friendly, technical):
        self.busy = False
        self.bar.set_busy(False)
        self.done_title.setText("Setup could not finish")
        self.done_text.setText(friendly)
        self.done_primary.setText("Try again")
        try:
            self.done_primary.clicked.disconnect()
        except Exception:
            pass
        self.done_primary.clicked.connect(self.start_install)
        self.log_btn.show()
        self.stack.setCurrentWidget(self.p_done)

    def do_uninstall(self):
        d = self.existing or self.install_dir
        if getattr(sys, "frozen", False) and os.path.basename(sys.executable).lower().startswith("uninstall"):
            d = os.path.dirname(os.path.abspath(sys.executable))
        if not core.read_install(d) and not os.path.isdir(d):
            self.close()
            return
        core.uninstall(d)
        self.un_btn.setEnabled(False)
        self.done_title.setText("Asena Mask was removed")
        self.done_text.setText("Thanks for trying it. You can install it again any time.")
        self.done_primary.hide()
        self.done_secondary.setText("Close")
        self.stack.setCurrentWidget(self.p_done)


def run(uninstall_mode=False, update=None):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Asenavfx.AsenaMask.Setup")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(C.APP_NAME + " Setup")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    icon = paths.asset("icon.ico")
    if os.path.isfile(icon):
        app.setWindowIcon(QIcon(icon))
    win = SetupWindow(uninstall_mode, update)
    win.setWindowOpacity(0.0)
    win.show()
    fade = QPropertyAnimation(win, b"windowOpacity", win)
    fade.setDuration(400)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.start()
    win._fade = fade
    return app.exec()
