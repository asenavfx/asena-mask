"""Your Asena Wrapped: the totals kept on this PC, the community Wrapped (when the developer has published one), and the
anonymous-sharing switch with a "show exactly what would be sent" box."""
import json
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QGridLayout, QScrollArea, QFrame, QWidget, QPlainTextEdit)

from .. import telemetry
from .widgets import Overlay, GlowButton, title_label
from .workspace import toggle_field

FORMAT_NAMES = {"mov": "ProRes 4444 (MOV)", "webm": "WebM", "mp4": "MP4", "png": "PNG sequence", "image": "PNG image", "matte": "Black & white matte"}


def _n(x):
    x = float(x or 0)
    if x >= 1e6:
        return "%.1fM" % (x / 1e6)
    if x >= 1e4:
        return "%.1fk" % (x / 1e3)
    return "{:,}".format(int(round(x)))


def _hours(minutes):
    m = float(minutes or 0)
    return "%d min" % round(m) if m < 90 else "%.1f h" % (m / 60.0)


def _tile(value, label):
    f = QFrame()
    f.setStyleSheet("QFrame{background:rgba(127,127,127,0.12);border-radius:12px;}")
    l = QVBoxLayout(f)
    l.setContentsMargins(14, 10, 14, 10)
    l.setSpacing(0)
    a = title_label(value, 17, QFont.Bold)
    a.setStyleSheet("background:transparent;")
    b = title_label(label, 9, QFont.Normal, sub=True)
    b.setStyleSheet("background:transparent;")
    l.addWidget(a)
    l.addWidget(b)
    return f


def fetch_community(callback):
    """Reads the community Wrapped file (only the developer's own published file) in the background."""
    def run():
        data = None
        try:
            import time
            import urllib.request
            from ..updater import open_url, UA
            req = urllib.request.Request("%s?t=%d" % (telemetry.COMMUNITY_URL, int(time.time())), headers={"User-Agent": UA})
            data = json.loads(open_url(req, timeout=8).read().decode("utf-8"))
            if not isinstance(data, dict) or not data.get("published"):
                data = None
        except Exception:
            data = None
        callback(data)
    threading.Thread(target=run, daemon=True).start()


class WrappedOverlay(Overlay):
    community_ready = Signal(object)

    def __init__(self, host, source, settings):
        super().__init__(host, source, frac=(0.86, 0.9), max_size=(820, 780))
        self.s = settings
        self.community = None
        self.community_ready.connect(self._community)
        L = self.panel_layout
        row = QHBoxLayout()
        self.title = title_label("Your Asena Wrapped" if telemetry.WRAPPED_ENABLED else "Anonymous stats", 18, QFont.Bold)
        row.addWidget(self.title)
        row.addStretch(1)
        b = GlowButton("Close", "ghost")
        b.setFixedWidth(100)
        b.clicked.connect(self.close_overlay)
        row.addWidget(b)
        L.addLayout(row)
        self.sc = QScrollArea()
        self.sc.setWidgetResizable(True)
        self.sc.setFrameShape(QFrame.NoFrame)
        self.sc.viewport().setAutoFillBackground(False)
        L.addWidget(self.sc, 1)

    def on_open(self):
        self.community = None
        self._build()
        fetch_community(lambda d: self.community_ready.emit(d))
        if self.community is not None:
            self.s.set("wrapped_seen", str(self.community.get("id", "")))

    def _community(self, d):
        self.community = d
        if d:
            self.s.set("wrapped_seen", str(d.get("id", "")))
        self._build()

    # ------------------------------------------------------------------ content
    def _build(self):
        T = telemetry.T
        sm = T.summary()
        c, m = sm["counters"], sm["maps"]
        body = QWidget()
        body.setAutoFillBackground(False)
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 8, 0)
        v.setSpacing(10)

        def head(t, sub=None):
            v.addSpacing(8)
            v.addWidget(title_label(t, 13, QFont.Bold))
            if sub:
                l = title_label(sub, 9, QFont.Normal, sub=True)
                l.setWordWrap(True)
                v.addWidget(l)

        def grid(tiles):
            g = QGridLayout()
            g.setSpacing(8)
            for i, (val, lab) in enumerate(tiles):
                g.addWidget(_tile(val, lab), i // 3, i % 3)
            v.addLayout(g)

        def top_list(title, mp, names=None, n=4):
            items = sorted((mp or {}).items(), key=lambda kv: -kv[1])[:n]
            if not items:
                return
            l = title_label(title, 10, QFont.DemiBold, sub=True)
            v.addWidget(l)
            for k, val in items:
                r = title_label("%s   ·   %s" % ((names or {}).get(k, k), _n(val)), 10, QFont.Normal)
                r.setContentsMargins(8, 0, 0, 0)
                v.addWidget(r)

        cm = self.community if telemetry.WRAPPED_ENABLED else None
        # ---- the community Wrapped (only when the developer has published one)
        if cm:
            tt = cm.get("totals") or {}
            head(cm.get("title") or "Asena Mask Wrapped", "Everyone who chose to share anonymous stats, added up.")
            grid([(_n(cm.get("people")), "people"), (_n(tt.get("jobs")), "cutouts made"), (_n(tt.get("frames")), "frames masked"),
                  ("%s h" % _n(tt.get("hours_of_ai_work")), "of AI work"), (_n(tt.get("saved")), "results saved"),
                  ("%s h" % _n(tt.get("hours_in_app")), "spent in the app")])
            top_list("Formats people export", cm.get("formats"), FORMAT_NAMES, 6)
            top_list("Where people are", cm.get("continents"), None, 7)
            top_list("Graphics cards", cm.get("top_gpus"), None, 5)
            top_list("Looks", cm.get("looks"), {"aurora": "Aurora", "aero": "Frutiger Aero", "retro": "Retro"}, 3)
            head("Yours")

        # ---- this PC (the Wrapped itself stays hidden until telemetry.WRAPPED_ENABLED is switched on)
        if telemetry.WRAPPED_ENABLED:
            if not cm:
                head("On this PC", "Counted here since %s. Only you can see this." % sm["first"])
            grid([(_n(c.get("jobs")), "cutouts made"), (_n(c.get("frames_masked")), "frames masked"), (_n(c.get("saved")), "results saved"),
                  (_hours(c.get("job_seconds", 0) / 60.0), "of AI work"), (_hours(c.get("minutes_open")), "in the app"),
                  (_n(c.get("sessions")), "times opened")])
            top_list("Your formats", m.get("format"), FORMAT_NAMES, 4)
            top_list("Your sizes", m.get("resolution"), None, 3)
            top_list("What you cut", m.get("input"), {"video": "videos", "image": "images", "folder": "image folders"}, 3)

        # ---- sharing
        head("Anonymous stats" if telemetry.WRAPPED_ENABLED else "What is sent")
        w, t = toggle_field("Share anonymous usage stats", "Totals like the ones above, plus your PC type (Windows, graphics card, "
                            "memory) and your continent. Never file names, folders, anything from your videos, prompts, your name, "
                            "e-mail or IP address." if T.available else "Sharing isn't set up in this build, so nothing leaves your PC.",
                            T.enabled)
        t.setEnabled(T.available)
        t.toggled.connect(self._share)
        v.addWidget(w)
        self.box = QPlainTextEdit()
        self.box.setReadOnly(True)
        self.box.setFixedHeight(190)
        self.box.setVisible(False)
        show = GlowButton("Show exactly what would be sent", "chip")
        show.clicked.connect(self._toggle_box)
        v.addWidget(show, 0, Qt.AlignLeft)
        v.addWidget(self.box)
        v.addStretch(1)
        self.sc.setWidget(body)

    def _toggle_box(self):
        on = not self.box.isVisible()
        if on:
            self.box.setPlainText(json.dumps(telemetry.T.payload(), indent=2))
        self.box.setVisible(on)

    def _share(self, on):
        telemetry.T.set_enabled(bool(on))
        if on:
            telemetry.T.flush()
