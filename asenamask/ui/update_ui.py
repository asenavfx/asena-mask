"""The "update available" window."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout

from .. import APP_VERSION, updater
from .widgets import Overlay, GlowButton, ProgressStrip, title_label


def human(n):
    return "%.0f MB" % (n / 1e6) if n >= 1e6 else "%.0f KB" % (n / 1e3)


class UpdateOverlay(Overlay):
    def __init__(self, host, source):
        super().__init__(host, source, frac=(0.8, 0.7), max_size=(640, 460))
        self.info = {}
        self.dl = None
        L = self.panel_layout
        L.setSpacing(12)
        self.title = title_label("A new version is ready", 18, QFont.Bold)
        L.addWidget(self.title)
        self.ver = title_label("", 11, QFont.DemiBold, sub=True)
        L.addWidget(self.ver)
        self.notes = title_label("", 11, QFont.Normal)
        self.notes.setTextFormat(Qt.PlainText)       # notes come from the server: never render them as HTML
        self.notes.setWordWrap(True)
        self.notes.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        L.addWidget(self.notes, 1)
        self.bar = ProgressStrip()
        self.bar.hide()
        L.addWidget(self.bar)
        self.status = title_label("", 10, QFont.Normal, sub=True)
        self.status.setWordWrap(True)
        L.addWidget(self.status)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        self.later = GlowButton("Later", "ghost")
        self.later.setFixedWidth(120)
        self.later.clicked.connect(self.close_overlay)
        self.go = GlowButton("Update now", "primary")
        self.go.setFixedWidth(200)
        self.go.clicked.connect(self._start)
        row.addWidget(self.later)
        row.addWidget(self.go)
        L.addLayout(row)

    def open_with(self, info):
        self.info = info
        self.ver.setText("Version %s  (you have %s)" % (info.get("version", "?"), APP_VERSION))
        self.notes.setText(info.get("notes") or "Improvements and fixes.")
        self.status.setText("Your settings are kept. The app restarts by itself when the update is done.")
        self.bar.hide()
        self.go.setEnabled(True)
        self.later.setEnabled(True)
        self.go.setText("Update now")
        self.open_overlay()

    def _start(self):
        self.go.setEnabled(False)
        self.later.setEnabled(False)
        self.bar.show()
        self.bar.set_busy(True)
        self.status.setText("Downloading…")
        self.dl = updater.DownloadThread(self.info, self)
        self.dl.progress.connect(self._progress)
        self.dl.done.connect(self._downloaded)
        self.dl.failed.connect(self._failed)
        self.dl.start()

    def _progress(self, have, total):
        if total:
            self.bar.set_value(have / float(total))
            self.status.setText("Downloading… %s of %s" % (human(have), human(total)))
        else:
            self.status.setText("Downloading… %s" % human(have))

    def _failed(self, text):
        self.bar.set_busy(False)
        self.bar.hide()
        self.status.setText(text)
        self.go.setEnabled(True)
        self.go.setText("Try again")
        self.later.setEnabled(True)

    def _downloaded(self, path):
        self.status.setText("Installing the update… the app closes and opens again in a moment.")
        try:
            updater.launch_updater(path, self.info)
        except Exception as e:
            self._failed(str(e))
            return
        self.host.close_for_update()
