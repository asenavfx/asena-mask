"""Main screen: import card (left), settings panel (right), Run + loading bar (bottom)."""
import os

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QVariantAnimation
from PySide6.QtGui import (QPainter, QPen, QColor, QFont, QPixmap, QImage, QPainterPath, QLinearGradient, QBrush)
from PySide6.QtWidgets import (QInputDialog, QMessageBox, QScrollArea, QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QComboBox,
                               QSlider, QFileDialog, QGridLayout, QSpinBox, QSizePolicy, QStackedWidget, QColorDialog)

from .. import videoinfo
from ..presets import PresetStore, KEYS as PRESET_KEYS
from .editor import selection_keys
from .player import ClipPlayer
from .theme import theme, mix
from .psmenu import PsList
from .widgets import (GlowButton, Card, HoverMixin, ProgressStrip, ToggleSwitch, title_label, restyle_labels, make_anim)

FPS_CHOICES = [("Same as source", None), ("12", 12), ("15", 15), ("24", 24), ("25", 25), ("30", 30),
               ("48", 48), ("50", 50), ("60", 60)]
FORMAT_CHOICES = [("ProRes 4444 (.mov) – After Effects", "mov"),
                  ("PNG sequence (folder)", "png"),
                  ("WebM with alpha (.webm)", "webm"),
                  ("Matte only – black & white (.mp4)", "matte")]
STILL_FORMAT_CHOICES = [("PNG with transparency", "png"),
                        ("Matte only – black & white (.png)", "matte")]
BG_FORMAT_CHOICES = [("MP4 video (.mp4)", "mp4"),
                     ("PNG sequence (folder)", "png"),
                     ("Matte only – black & white (.mp4)", "matte")]
STILL_BG_FORMAT_CHOICES = [("PNG image", "png"),
                           ("Matte only – black & white (.png)", "matte")]
# (label, value): value is "none", a colour, "custom" or "image"
BG_CHOICES = [("Transparent", "none"), ("Green screen", "#00b140"), ("Blue screen", "#0047bb"),
              ("Black", "#000000"), ("White", "#ffffff"), ("Custom colour…", "custom"), ("Image…", "image"),
              ("Blurred original", "blur"), ("Gradient: Sunset", "grad:#ff9966:#ff5e62"),
              ("Gradient: Night", "grad:#0f2027:#2c5364"), ("Gradient: Studio grey", "grad:#f5f5f5:#9e9e9e")]
PRESETS = [("Character", "character, face, cloth, hands:2, hair"),
           ("Face + hair", "face, hair"),
           ("Person", "person")]
FILTER = "Videos and images (%s)" % " ".join("*" + e for e in videoinfo.SUPPORTED + videoinfo.IMAGE_EXTS)


class DropZone(HoverMixin, QWidget):
    file_chosen = Signal(str)
    files_dropped = Signal(list)       # several files dropped at once -> batch queue

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_hover()
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(380, 300)
        self._drag = 0.0
        self._dash = 0.0
        self._dash_anim = QVariantAnimation(self)
        self._dash_anim.setStartValue(0.0)
        self._dash_anim.setEndValue(10.0)
        self._dash_anim.setDuration(900)
        self._dash_anim.setLoopCount(-1)
        self._dash_anim.valueChanged.connect(self._set_dash)
        self.path = None
        self.info = None
        self.thumb = None
        theme.changed.connect(self.update)

    def _set_dash(self, v):
        self._dash = float(v)
        self.update()

    def enterEvent(self, e):
        self._dash_anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._dash_anim.stop()
        super().leaveEvent(e)

    def set_video(self, path, info, thumb_rgb):
        self.path, self.info = path, info
        self.thumb = None
        if thumb_rgb is not None:
            import numpy as np
            thumb_rgb = np.ascontiguousarray(thumb_rgb)
            h, w, _ = thumb_rgb.shape
            img = QImage(thumb_rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
            self.thumb = QPixmap.fromImage(img)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.browse()

    def browse(self):
        start = os.path.dirname(self.path) if self.path else ""
        f, _ = QFileDialog.getOpenFileName(self.window(), "Choose a video or image", start, FILTER + ";;All files (*.*)")
        if f:
            self.file_chosen.emit(f)

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
        good = []
        for u in e.mimeData().urls():
            f = u.toLocalFile()
            if f and (os.path.isdir(f) or os.path.splitext(f)[1].lower() in videoinfo.SUPPORTED + videoinfo.IMAGE_EXTS):
                good.append(f)
        if len(good) == 1:
            self.file_chosen.emit(good[0])
        elif good:
            self.files_dropped.emit(good)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        hv = max(self._h, self._drag)
        acc = theme.col("accent")
        acc2 = theme.col("accent2")
        gg = QLinearGradient(r.topLeft(), r.bottomRight())
        gg.setColorAt(0, mix(QColor(acc.red(), acc.green(), acc.blue(), 34), QColor(acc.red(), acc.green(), acc.blue(), 70), hv))
        gg.setColorAt(1, mix(QColor(acc2.red(), acc2.green(), acc2.blue(), 16), QColor(acc2.red(), acc2.green(), acc2.blue(), 42), hv))
        p.setBrush(QBrush(gg))
        pen = QPen(mix(theme.col("card_border"), acc, hv), 1.6)
        if not self.path:
            pen.setStyle(Qt.DashLine)
            pen.setDashPattern([5, 5])
            pen.setDashOffset(self._dash)
        p.setPen(pen)
        p.drawRoundedRect(r, 22, 22)
        if self.path:
            self._paint_loaded(p, r)
        else:
            self._paint_empty(p, r, hv)

    def _paint_empty(self, p, r, hv):
        cx = r.center().x()
        cy = r.center().y() - 38 - 4 * hv
        # folder icon
        acc, acc2 = theme.col("accent"), theme.col("accent2")
        g = QLinearGradient(cx - 40, cy - 30, cx + 40, cy + 30)
        g.setColorAt(0, acc)
        g.setColorAt(1, acc2)
        fp = QPainterPath()
        x, y, w, h = cx - 42, cy - 28, 84, 60
        fp.moveTo(x, y + 8)
        fp.quadTo(x, y, x + 8, y)
        fp.lineTo(x + 28, y)
        fp.lineTo(x + 36, y + 9)
        fp.lineTo(x + w - 8, y + 9)
        fp.quadTo(x + w, y + 9, x + w, y + 17)
        fp.lineTo(x + w, y + h - 8)
        fp.quadTo(x + w, y + h, x + w - 8, y + h)
        fp.lineTo(x + 8, y + h)
        fp.quadTo(x, y + h, x, y + h - 8)
        fp.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawPath(fp)
        # play triangle
        p.setBrush(QColor(255, 255, 255, 235))
        tri = QPainterPath()
        by = cy + 6.5          # vertical center of the folder body (below the tab)
        tri.moveTo(cx - 7, by - 12)
        tri.lineTo(cx - 7, by + 12)
        tri.lineTo(cx + 12, by)
        tri.closeSubpath()
        p.drawPath(tri)
        f = QFont("Segoe UI", 15)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(theme.col("text"))
        p.drawText(QRectF(r.left(), cy + 50, r.width(), 30), Qt.AlignHCenter | Qt.AlignVCenter,
                   "Click to import a video or image")
        f2 = QFont("Segoe UI", 10)
        p.setFont(f2)
        p.setPen(theme.col("sub"))
        p.drawText(QRectF(r.left(), cy + 80, r.width(), 22), Qt.AlignHCenter | Qt.AlignVCenter,
                   "or drag and drop a video, image or folder here")
        p.drawText(QRectF(r.left(), r.bottom() - 46, r.width(), 24), Qt.AlignHCenter | Qt.AlignVCenter,
                   "Videos: " + " ".join(e[1:].upper() for e in videoinfo.SUPPORTED) + "   ·   Images: " + " ".join(e[1:].upper() for e in videoinfo.IMAGE_EXTS))

    def _paint_loaded(self, p, r):
        inner = r.adjusted(22, 22, -22, -92)
        if self.thumb is not None:
            pm = self.thumb
            s = min(inner.width() / pm.width(), inner.height() / pm.height())
            w, h = pm.width() * s, pm.height() * s
            tr = QRectF(inner.center().x() - w / 2, inner.top() + (inner.height() - h) / 2, w, h)
            path = QPainterPath()
            path.addRoundedRect(tr, 12, 12)
            p.save()
            p.setClipPath(path)
            p.drawPixmap(tr, pm, QRectF(pm.rect()))
            p.restore()
        i = self.info or {}
        name = os.path.basename(self.path.rstrip("/\\")) or self.path
        f = QFont("Segoe UI", 12)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(theme.col("text"))
        fm = p.fontMetrics()
        p.drawText(QRectF(r.left() + 22, r.bottom() - 78, r.width() - 44, 26), Qt.AlignHCenter | Qt.AlignVCenter,
                   fm.elidedText(name, Qt.ElideMiddle, int(r.width() - 60)))
        p.setFont(QFont("Segoe UI", 10))
        p.setPen(theme.col("sub"))
        k = i.get("kind", "video")
        if k == "image":
            meta = "Image   ·   %d × %d" % (i.get("width", 0), i.get("height", 0))
        elif k == "folder":
            meta = "Folder   ·   %d images   ·   %d × %d" % (i.get("frames", 0), i.get("width", 0), i.get("height", 0))
        else:
            meta = "%d × %d   ·   %.3g fps   ·   %s   ·   %d frames" % (
                i.get("width", 0), i.get("height", 0), i.get("fps", 0),
                videoinfo.fmt_duration(i.get("duration", 0)), i.get("frames", 0))
        p.drawText(QRectF(r.left(), r.bottom() - 52, r.width(), 22), Qt.AlignHCenter | Qt.AlignVCenter, meta)
        p.setPen(mix(theme.col("sub"), theme.col("accent"), self._h))
        p.drawText(QRectF(r.left(), r.bottom() - 30, r.width(), 20), Qt.AlignHCenter | Qt.AlignVCenter,
                   "Click to choose something different")


class StepperRow(QWidget):
    """−  value  +  for refine iterations."""

    def __init__(self, lo, hi, val, parent=None):
        super().__init__(parent)
        self.lo, self.hi, self.v = lo, hi, val
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.minus = GlowButton("−", "chip")
        self.plus = GlowButton("+", "chip")
        for b in (self.minus, self.plus):
            b.setFixedWidth(40)
            b.setMinimumHeight(34)
        self.lbl = QLabel(str(val))
        self.lbl.setAlignment(Qt.AlignCenter)
        self.lbl.setMinimumWidth(36)
        self.lbl.setStyleSheet("background: transparent; font-size: 16px; font-weight: 600;")
        lay.addWidget(self.minus)
        lay.addWidget(self.lbl)
        lay.addWidget(self.plus)
        lay.addStretch(1)
        self.minus.clicked.connect(lambda: self.set(self.v - 1))
        self.plus.clicked.connect(lambda: self.set(self.v + 1))

    def set(self, v):
        self.v = max(self.lo, min(self.hi, v))
        self.lbl.setText(str(self.v))


def field(label, widget, hint=None):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)
    lab = title_label(label.upper(), 8, QFont.DemiBold, sub=True)
    f = lab.font()
    f.setLetterSpacing(QFont.AbsoluteSpacing, 1.3)
    lab.setFont(f)
    lay.addWidget(lab)
    lay.addWidget(widget)
    if hint:
        h = title_label(hint, 9, QFont.Normal, sub=True)
        h.setWordWrap(True)
        lay.addWidget(h)
    return w


def toggle_field(title, hint, checked):
    """Title + hint on the left, an on/off switch on the right. Returns (widget, switch)."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    col = QVBoxLayout()
    col.setSpacing(1)
    col.addWidget(title_label(title, 10, QFont.DemiBold))
    hl = title_label(hint, 9, QFont.Normal, sub=True)
    hl.setWordWrap(True)
    col.addWidget(hl)
    h.addLayout(col, 1)
    t = ToggleSwitch(checked)
    h.addWidget(t, 0, Qt.AlignTop)
    return w, t


class MainScreen(QWidget):
    def apply_look(self):
        """Retro puts the settings list on the left and the picture on the right, like an old console's menu."""
        from PySide6.QtWidgets import QBoxLayout
        retro = theme.look == "retro"
        self.top.setDirection(QBoxLayout.RightToLeft if retro else QBoxLayout.LeftToRight)
        if not getattr(self, "groups_ready", False) or retro == self._retro_on:
            return
        self._retro_on = retro
        if retro:
            for _n, w, _v in self.groups:
                self.pl_main.removeWidget(w)
                self.group_stack.addWidget(w)
            idx = max(0, min(int(self.cats.cur), len(self.groups) - 1))
            self.cats.cur = idx
            self.group_stack.setCurrentIndex(idx)
            for i, (_n, w, _v) in enumerate(self.groups):      # only the chosen section shows (they used to pile up on first open)
                w.setVisible(i == idx)
            self.scroll.hide()
            self.retro_row.show()
            self.panel.setFixedWidth(560)
        else:
            for i, (_n, w, _v) in enumerate(self.groups):
                self.group_stack.removeWidget(w)
                self.pl_main.insertWidget(1 + i, w)
                w.show()
            self.retro_row.hide()
            self.scroll.show()
            self.panel.setFixedWidth(356)

    run_requested = Signal()
    cancel_requested = Signal()
    queue_requested = Signal()
    queue_files = Signal(list)
    video_loaded = Signal(str)
    pick_requested = Signal()

    def __init__(self, settings, engine=None, parent=None):
        super().__init__(parent)
        self.s = settings
        self.setAcceptDrops(True)
        self.bg_mode = self.s.get("bg_mode") or "none"          # none | color | image
        self.bg_color = self.s.get("bg_color") or "#00b140"
        self.bg_image = self.s.get("bg_image") or ""
        self.bg_grad = self.s.get("bg_grad") or "#ff9966:#ff5e62"      # "colour1:colour2" of the chosen gradient
        self.busy = False
        self.video_path = None
        self.info = None
        self.kind = "video"
        self.files = []
        self._thumb_rgb = None

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 6, 26, 18)
        root.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(18)
        root.addLayout(top, 1)
        self.top = top
        theme.changed.connect(self.apply_look)
        self.apply_look()

        left = QVBoxLayout()
        left.setSpacing(10)
        self.view = QStackedWidget()
        self.drop = DropZone()
        self.drop.file_chosen.connect(self.load_video)
        self.drop.files_dropped.connect(self.queue_files)
        self.player = ClipPlayer()
        self.player.trim_changed.connect(self._player_trim)
        self.view.addWidget(self.drop)
        self.view.addWidget(self.player)
        left.addWidget(self.view, 1)
        under = QHBoxLayout()
        under.setSpacing(8)
        under.addStretch(1)
        self.change_btn = GlowButton("Choose another file…", "chip")
        self.change_btn.setMinimumHeight(34)
        self.change_btn.clicked.connect(self.drop.browse)
        self.change_btn.hide()
        self.folder_btn = GlowButton("Or choose a folder of images…", "chip")
        self.folder_btn.setMinimumHeight(34)
        self.folder_btn.clicked.connect(self.browse_folder)
        under.addWidget(self.change_btn)
        under.addWidget(self.folder_btn)
        under.addStretch(1)
        left.addLayout(under)
        top.addLayout(left, 1)

        # ----- settings panel
        self.panel = Card(radius=22)
        self.panel.setFixedWidth(356)
        outer = QVBoxLayout(self.panel)
        outer.setContentsMargins(4, 10, 4, 10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        inner = QWidget()
        inner.setAutoFillBackground(False)
        pl = QVBoxLayout(inner)
        pl.setContentsMargins(16, 8, 16, 8)
        pl.setSpacing(12)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self.scroll = scroll
        self.pl_main = pl
        self.panel_title = title_label("Settings", 15)
        pl.addWidget(self.panel_title)
        self.groups = []                      # (name, widget, layout): the panel's three sections

        def _group(name):
            w = QWidget()
            w.setAutoFillBackground(False)
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(12)
            self.groups.append((name, w, v))
            return v
        pl = _group("Subject")

        # presets: one click for a whole set of edge / threshold values
        self.presets = PresetStore()
        self.preset_box = QComboBox()
        self.preset_save = GlowButton("Save…", "chip")
        self.preset_del = GlowButton("Delete", "chip")
        self.preset_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.preset_box.setMinimumContentsLength(10)
        self.preset_box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        prow = QVBoxLayout()
        prow.setSpacing(6)
        prow.addWidget(self.preset_box)
        pbtn = QHBoxLayout()
        pbtn.setSpacing(6)
        pbtn.addWidget(self.preset_save)
        pbtn.addWidget(self.preset_del)
        pbtn.addStretch(1)
        prow.addLayout(pbtn)
        pw = QWidget()
        pw.setLayout(prow)
        prow.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(field("Preset", pw, "Edge, softness and threshold values in one click. Save your own."))

        self.prompt = QPlainTextEdit(self.s.get("prompt"))
        self.prompt.setFixedHeight(76)
        self.prompt.setPlaceholderText("What should it keep? e.g. person, hair, sword")
        pl.addWidget(field("What to keep (prompt)", self.prompt,
                           "Separate parts with commas. Add :2 to allow 2 of something (e.g. hands:2)."))
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for label, text in PRESETS:
            b = GlowButton(label, "chip")
            b.clicked.connect(lambda _=False, t=text: self.prompt.setPlainText(t))
            chips.addWidget(b)
        chips.addStretch(1)
        pl.addLayout(chips)

        # pick subject (boxes / points)
        self.selection = None
        self.trim = None
        self.pick_btn = GlowButton("Trim & pick subject…", "ghost")
        self.pick_btn.clicked.connect(self.pick_requested)
        pl.addWidget(self.pick_btn)
        self.sel_lbl = title_label("", 9, QFont.Normal, sub=True)
        self.sel_lbl.setWordWrap(True)
        pl.addWidget(self.sel_lbl)
        self.clear_sel = GlowButton("Clear trim & subject", "chip")
        self.clear_sel.clicked.connect(lambda: self.set_edit(None, None))
        pl.addWidget(self.clear_sel, 0, Qt.AlignLeft)
        self.set_edit(None, None)

        pl = _group("Output")
        self.fps = QComboBox()
        for label, _ in FPS_CHOICES:
            self.fps.addItem(label)
        saved = self.s.get("fps")
        for i, (_, v) in enumerate(FPS_CHOICES):
            if (v is None and saved == "same") or (v is not None and str(v) == str(saved)):
                self.fps.setCurrentIndex(i)
        self.fmt = QComboBox()
        self.fmt_choices = FORMAT_CHOICES
        self._fill_formats(self._format_choices(), self.s.get("format"))
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(field("Frame rate (FPS)", self.fps), 1)
        pl.addLayout(row)
        pl.addWidget(field("Output format", self.fmt))

        # background (transparent, a colour, or a picture)
        self.bg = QComboBox()
        for label, _v in BG_CHOICES:
            self.bg.addItem(label)
        self._bg_index = self._bg_index_from_state()
        self.bg.setCurrentIndex(self._bg_index)
        self._relabel_bg()
        self.bg.currentIndexChanged.connect(self._bg_changed)
        pl.addWidget(field("Background", self.bg, "Transparent keeps the cut-out for your editor. A colour or picture "
                                                  "gives a ready-made video."))

        # edge controls
        pl = _group("Edges")
        self.grow = QSlider(Qt.Horizontal)
        self.grow.setRange(-10, 10)
        self.grow.setValue(int(self.s.get("edge_grow") or 0))
        self.grow_lbl = title_label("", 10, QFont.DemiBold)
        self.grow.valueChanged.connect(lambda v: self.grow_lbl.setText("%+d px" % v if v else "0 px"))
        self.grow_lbl.setText("%+d px" % self.grow.value() if self.grow.value() else "0 px")
        self.grow_lbl.setMinimumWidth(48)
        gw = QWidget()
        grow_row = QHBoxLayout(gw)
        grow_row.setContentsMargins(0, 0, 0, 0)
        grow_row.addWidget(self.grow, 1)
        grow_row.addWidget(self.grow_lbl)
        pl.addWidget(field("Edge grow / shrink", gw, "Negative shrinks the cut-out (removes halos), positive grows it."))

        self.soft = QSlider(Qt.Horizontal)
        self.soft.setRange(0, 10)
        self.soft.setValue(int(self.s.get("edge_feather") or 0))
        self.soft_lbl = title_label("", 10, QFont.DemiBold)
        self.soft.valueChanged.connect(lambda v: self.soft_lbl.setText("%d px" % v))
        self.soft_lbl.setText("%d px" % self.soft.value())
        self.soft_lbl.setMinimumWidth(48)
        sw = QWidget()
        soft_row = QHBoxLayout(sw)
        soft_row.setContentsMargins(0, 0, 0, 0)
        soft_row.addWidget(self.soft, 1)
        soft_row.addWidget(self.soft_lbl)
        pl.addWidget(field("Edge softness", sw, "Blurs the edge slightly for a smoother blend."))

        self.defr = StepperRow(0, 2, int(self.s.get("defringe")))
        pl.addWidget(field("Edge cleanup", self.defr, "Removes leftover old-background colour from the edge of the cut-out. 0 = off, 2 = strongest."))

        # threshold
        self.thr = QSlider(Qt.Horizontal)
        self.thr.setRange(5, 95)
        self.thr.setValue(int(round(float(self.s.get("threshold")) * 100)))
        self.thr_lbl = title_label("", 10, QFont.DemiBold)
        self.thr.valueChanged.connect(lambda v: self.thr_lbl.setText("%.2f" % (v / 100.0)))
        self.thr_lbl.setText("%.2f" % (self.thr.value() / 100.0))
        trow = QHBoxLayout()
        trow.addWidget(self.thr, 1)
        trow.addWidget(self.thr_lbl)
        tw = QWidget()
        tw.setLayout(trow)
        trow.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(field("Threshold", tw, "Lower = catches more, higher = stricter."))

        self.refine = StepperRow(0, 4, int(self.s.get("refine")))
        pl.addWidget(field("Refine iterations", self.refine, "More = cleaner edges, slower."))

        self.stab = StepperRow(0, 3, int(self.s.get("stability")))
        pl.addWidget(field("Stability", self.stab, "Smooths flicker, holes and torn edges between frames. 0 = off, 3 = strongest."))

        self.prefix = QLineEdit(self.s.get("prefix"))
        self.prefix.setPlaceholderText("asena")
        self.groups[1][2].addWidget(field("File name prefix", self.prefix))
        for _n, gw, gv in self.groups:
            gv.addStretch(1)
            self.pl_main.addWidget(gw)
        self.pl_main.addStretch(1)
        top.addWidget(self.panel)

        # Retro look: a console-style menu of the three sections on the left, the chosen section next to it
        self.retro_row = QWidget()
        rr = QHBoxLayout(self.retro_row)
        rr.setContentsMargins(10, 12, 10, 12)
        rr.setSpacing(8)
        self.cats = PsList([g[0] for g in self.groups], row_h=58, size=12)
        self.cats.setFixedWidth(150)
        self.group_stack = QStackedWidget()
        self.cats.chosen.connect(self.group_stack.setCurrentIndex)
        rr.addWidget(self.cats, 0, Qt.AlignTop)
        self.group_scroll = QScrollArea()
        self.group_scroll.setWidgetResizable(True)
        self.group_scroll.setFrameShape(QFrame.NoFrame)
        self.group_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.group_scroll.viewport().setAutoFillBackground(False)
        self.group_stack.setAutoFillBackground(False)
        self.group_scroll.setWidget(self.group_stack)
        rr.addWidget(self.group_scroll, 1)
        outer.addWidget(self.retro_row)
        self.retro_row.hide()
        self._retro_on = False
        self.groups_ready = True
        self.apply_look()

        self._fill_presets(self.s.get("preset"))
        self.preset_box.activated.connect(self._preset_chosen)
        self.preset_save.clicked.connect(self._preset_save)
        self.preset_del.clicked.connect(self._preset_delete)

        # ----- bottom row
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        self.status = title_label("Import a video, image or folder to begin.", 11, QFont.Normal, sub=True)
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.queue_btn = GlowButton("Batch queue…", "ghost")
        self.queue_btn.setFixedWidth(150)
        self.queue_btn.clicked.connect(self.queue_requested)
        bottom.addWidget(self.queue_btn)
        self.cancel_btn = GlowButton("Cancel", "ghost")
        self.cancel_btn.setFixedWidth(120)
        self.cancel_btn.clicked.connect(self.cancel_requested)
        self.cancel_btn.hide()
        bottom.addWidget(self.cancel_btn)
        self.run_btn = GlowButton("Run", "primary")
        self.run_btn.setFixedWidth(190)
        self.run_btn.set_breathing(True)
        self.run_btn.clicked.connect(self.run_requested)
        bottom.addWidget(self.run_btn)
        root.addLayout(bottom)

        self.bar = ProgressStrip()
        root.addWidget(self.bar)

    # ----- background / formats
    def _bg_index_from_state(self):
        if self.bg_mode == "none":
            return 0
        if self.bg_mode == "image":
            return 6 if self.bg_image and os.path.isfile(self.bg_image) else 0
        if self.bg_mode == "blur":
            return 7
        if self.bg_mode == "gradient":
            for i, (_l, v) in enumerate(BG_CHOICES):
                if v == "grad:" + self.bg_grad:
                    return i
            return 0
        for i, (_l, v) in enumerate(BG_CHOICES[1:5], 1):
            if v.lower() == self.bg_color.lower():
                return i
        return 5

    def _relabel_bg(self):
        """Show the chosen custom colour / picture on its menu entry."""
        self.bg.setItemText(5, "Custom colour (%s)" % self.bg_color if self.bg.currentIndex() == 5 else "Custom colour…")
        self.bg.setItemText(6, "Image: %s" % os.path.basename(self.bg_image) if self.bg.currentIndex() == 6 and self.bg_image
                            else "Image…")

    def _bg_changed(self, idx):
        val = BG_CHOICES[idx][1]
        if val == "none":
            self.bg_mode = "none"
        elif val == "custom":
            c = QColorDialog.getColor(QColor(self.bg_color), self.window(), "Choose a background colour")
            if not c.isValid():
                self._revert_bg()
                return
            self.bg_mode, self.bg_color = "color", c.name()
        elif val == "image":
            start = os.path.dirname(self.bg_image) if self.bg_image else (self.s.get("last_dir") or "")
            f, _ = QFileDialog.getOpenFileName(self.window(), "Choose a background picture", start,
                                               "Pictures (*.png *.jpg *.jpeg *.webp *.bmp)")
            if not f:
                self._revert_bg()
                return
            self.bg_mode, self.bg_image = "image", f
        elif val == "blur":
            self.bg_mode = "blur"
        elif val.startswith("grad:"):
            self.bg_mode, self.bg_grad = "gradient", val[5:]
        else:
            self.bg_mode, self.bg_color = "color", val
        self._bg_index = idx
        self._relabel_bg()
        self._refresh_formats()
        self.player.canvas.update()

    def _revert_bg(self):
        self.bg.blockSignals(True)
        self.bg.setCurrentIndex(self._bg_index)
        self.bg.blockSignals(False)
        self._relabel_bg()

    def _format_choices(self):
        with_bg = self.bg_mode != "none"
        if self.kind == "video":
            return BG_FORMAT_CHOICES if with_bg else FORMAT_CHOICES
        return STILL_BG_FORMAT_CHOICES if with_bg else STILL_FORMAT_CHOICES

    def _refresh_formats(self):
        cur = self.fmt_choices[self.fmt.currentIndex()][1] if self.fmt.count() else self.s.get("format")
        want = cur if any(v == cur for _l, v in self._format_choices()) else None
        self._fill_formats(self._format_choices(), want)

    def bg_dict(self):
        c1, _, c2 = self.bg_grad.partition(":")
        return {"mode": self.bg_mode, "color": self.bg_color, "image": self.bg_image, "color1": c1, "color2": c2 or c1}

    def backdrop(self):
        """Colour the live preview is drawn on (None = checkerboard)."""
        if self.bg_mode == "color":
            return QColor(self.bg_color)
        return None

    # ----- API
    def _fill_formats(self, choices, want):
        self.fmt_choices = choices
        self.fmt.blockSignals(True)
        self.fmt.clear()
        idx = 0
        for i, (label, v) in enumerate(choices):
            self.fmt.addItem(label)
            if v == want:
                idx = i
        self.fmt.setCurrentIndex(idx)
        self.fmt.blockSignals(False)

    # ----- presets
    def _fill_presets(self, select=None):
        self.preset_box.blockSignals(True)
        self.preset_box.clear()
        names = ["Custom (current values)"] + self.presets.names()
        for n in names:
            self.preset_box.addItem(n)
        self.preset_box.setCurrentIndex(names.index(select) if select in names else 0)
        self.preset_box.blockSignals(False)
        self.preset_del.setEnabled(self.presets.is_user(select))

    def current_values(self):
        return {"threshold": self.thr.value() / 100.0, "refine": self.refine.v, "edge_grow": self.grow.value(),
                "edge_feather": self.soft.value(), "stability": self.stab.v, "defringe": self.defr.v}

    def apply_values(self, d):
        """Sets the edge / threshold controls from a dict (a preset or a restored project)."""
        if "threshold" in d:
            self.thr.setValue(int(round(float(d["threshold"]) * 100)))
        if "refine" in d:
            self.refine.set(int(d["refine"]))
        if "edge_grow" in d:
            self.grow.setValue(int(d["edge_grow"]))
        if "edge_feather" in d:
            self.soft.setValue(int(d["edge_feather"]))
        if "stability" in d:
            self.stab.set(int(d["stability"]))
        if "defringe" in d:
            self.defr.set(int(d["defringe"]))

    def _preset_chosen(self, i):
        name = self.preset_box.currentText()
        vals = self.presets.get(name)
        if vals:
            self.apply_values(vals)
            self.s.set("preset", name)
        self.preset_del.setEnabled(self.presets.is_user(name))

    def _preset_save(self):
        name, ok = QInputDialog.getText(self.window(), "Save preset", "Name for this preset:")
        if not ok or not name.strip():
            return
        saved = self.presets.save(name, self.current_values())
        if saved is None:
            QMessageBox.information(self.window(), "Preset", "Please pick a different name (that one is built in).")
            return
        self._fill_presets(saved)
        self.s.set("preset", saved)

    def _preset_delete(self):
        name = self.preset_box.currentText()
        if self.presets.is_user(name):
            self.presets.delete(name)
            self._fill_presets(None)

    def browse_folder(self):
        start = self.s.get("last_dir") or ""
        d = QFileDialog.getExistingDirectory(self.window(), "Choose a folder of images", start)
        if d:
            self.load_video(d)

    def load_video(self, path):
        try:
            if os.path.isdir(path):
                files = videoinfo.list_images(path)
                if not files:
                    self.status.setText("That folder has no images (PNG, JPG, WEBP, BMP).")
                    return
                info = videoinfo.probe_images(files, "folder")
                kind, thumb = "folder", videoinfo.load_image(files[0])
            else:
                files = []
                info = videoinfo.probe(path)
                kind = info.get("kind", "video")
                thumb = videoinfo.thumbnail(path)
        except Exception as e:
            self.status.setText("Could not read that file: %s" % e)
            return
        self.player.pause()
        self._thumb_rgb = thumb
        self.video_path, self.info, self.kind, self.files = path, info, kind, files
        self.view.setCurrentWidget(self.drop)          # the player takes over once the clip is decoded
        self.change_btn.hide()
        self.set_edit(None, None)
        self.drop.set_video(path, info, thumb)
        # adapt controls to the kind of input
        self._refresh_formats()
        self.fps.setEnabled(kind == "video")
        self.pick_btn.setText("Trim & pick subject…" if kind == "video" else "Pick subject…")
        self.pick_btn.setVisible(kind != "folder")
        self.status.setText(self.estimate_text())
        self.video_loaded.emit(path)

    def attach_proxy(self, loader):
        """Called once the clip starts decoding into preview frames: show the player with the trim bar."""
        if self.kind != "video" or not self.info:
            return
        self.player.set_source(loader, self.info)
        self.player.set_trim(self.trim)
        self.player.set_marks(self.selection)
        self.view.setCurrentWidget(self.player)
        self.change_btn.show()

    def set_edit(self, trim, sel):
        has_sel = bool(sel and (sel.get("boxes") or sel.get("pos")))
        self.selection = sel if has_sel else None
        self.trim = trim
        self.player.set_trim(trim)
        self.player.set_marks(self.selection)
        self._refresh_edit_text()

    def _player_trim(self):
        """The trim bar under the video was moved."""
        self.trim = self.player.get_trim()
        self._refresh_edit_text()

    def _refresh_edit_text(self):
        sel, trim = self.selection, self.trim
        has_sel = bool(sel)
        self.clear_sel.setVisible(has_sel or bool(trim))
        self.prompt.setEnabled(not has_sel)
        lines = []
        if trim:
            fps = (self.info or {}).get("fps") or 24.0
            n = trim["end"] - trim["start"] + 1
            lines.append("Section: frames %d–%d (%.1f s)." % (trim["start"] + 1, trim["end"] + 1, n / fps))
        if has_sel:
            keys = selection_keys(sel)
            boxes = sum(len(k.get("boxes", [])) for k in keys.values())
            pos = sum(len(k.get("pos", [])) for k in keys.values())
            neg = sum(len(k.get("neg", [])) for k in keys.values())
            txt = "Subject picked: %d box(es), %d include, %d exclude point(s)" % (boxes, pos, neg)
            if len(keys) > 1:
                txt += ", with %d correction frame(s)" % (len(keys) - 1)
            lines.append(txt + ". The text prompt is ignored. Works best on clips under ~400 frames.")
        if self.kind == "folder":
            lines = ["Every image in the folder is processed with the same prompt."]
        elif not lines:
            lines.append("Optional. Choose which part of the clip to process (drag the bar under the video), "
                         "or pick your subject with a box, points or the brush.")
        self.sel_lbl.setText("  ".join(lines))

    def estimate_text(self):
        if not self.info:
            return "Import a video or image to begin."
        if self.kind == "folder":
            return "Ready. %d images will be processed one by one." % len(self.files)
        return "Ready. Processing takes a few seconds per frame on your GPU."

    def preview_params(self):
        """Current settings, used by the live highlight / cutout preview."""
        return {"prompt": " ".join(self.prompt.toPlainText().split()), "selection": self.selection,
                "threshold": self.thr.value() / 100.0, "refine": self.refine.v,
                "grow": self.grow.value(), "feather": self.soft.value(), "backdrop": self.backdrop()}

    def params(self):
        fps_val = FPS_CHOICES[self.fps.currentIndex()][1]
        fmt = self.fmt_choices[self.fmt.currentIndex()][1]
        prompt = " ".join(self.prompt.toPlainText().split())
        video = self.kind == "video"
        d = {"video": self.video_path, "prompt": prompt, "fps": fps_val, "format": fmt,
             "threshold": self.thr.value() / 100.0, "refine": self.refine.v, "stability": self.stab.v,
             "defringe": self.defr.v, "prefix": self.prefix.text().strip() or "asena", "selection": self.selection,
             "trim": self.trim, "kind": self.kind, "files": self.files,
             "edge_grow": self.grow.value(), "edge_feather": self.soft.value(),
             "bg": self.bg_dict(), "keep_audio": video, "split": False}      # the sound is always kept when the clip has any
        # remember choices
        self.s.data.update({"prompt": prompt, "fps": "same" if fps_val is None else str(fps_val), "format": fmt,
                            "threshold": d["threshold"], "refine": d["refine"], "stability": d["stability"], "defringe": d["defringe"], "prefix": d["prefix"],
                            "edge_grow": d["edge_grow"], "edge_feather": d["edge_feather"],
                            "bg_mode": self.bg_mode, "bg_color": self.bg_color, "bg_image": self.bg_image,
                            "bg_grad": self.bg_grad})
        self.s.save()
        return d

    def set_busy(self, busy):
        self.busy = busy
        if busy:
            self.player.pause()
        for w in (self.drop, self.player, self.panel, self.folder_btn, self.change_btn, self.queue_btn):
            w.setEnabled(not busy)
        self.run_btn.setEnabled(not busy)
        self.cancel_btn.setVisible(busy)
        self.bar.set_busy(busy)
        if not busy:
            self.bar.reset()

    def set_status(self, text):
        self.status.setText(text)

    def set_progress(self, done, total, eta):
        if total > 0:
            self.bar.set_value(done / float(total))
        msg = "Running the model… frame %d of %d" % (done, total)
        if eta and eta > 1:
            m, s = divmod(int(eta), 60)
            msg += "   ·   about %s left" % (("%d min %02d s" % (m, s)) if m else ("%d s" % s))
        self.status.setText(msg)

    # ----- drag & drop anywhere on the screen
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and not self.busy:
            e.acceptProposedAction()

    def dropEvent(self, e):
        if self.busy:
            return
        good = []
        for u in e.mimeData().urls():
            f = u.toLocalFile()
            if f and (os.path.isdir(f) or os.path.splitext(f)[1].lower() in videoinfo.SUPPORTED + videoinfo.IMAGE_EXTS):
                good.append(f)
        if len(good) == 1:
            self.load_video(good[0])
        elif good:
            self.queue_files.emit(good)

    def refresh_theme(self):
        restyle_labels(self)
        self.update()
