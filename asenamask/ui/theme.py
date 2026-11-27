"""Colors for dark / light mode and the global stylesheet."""
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

PALETTES = {
    "dark": {
        "bg1": (4, 3, 8, 255), "bg2": (9, 6, 16, 255), "bg3": (22, 11, 42, 255),
        "card": (255, 255, 255, 10), "card_border": (255, 255, 255, 22),
        "panel": (14, 11, 22, 252),
        "text": (243, 238, 255, 255), "sub": (168, 159, 196, 255),
        "accent": (139, 92, 246, 255), "accent2": (217, 70, 239, 255),
        "input": (0, 0, 0, 90), "input_border": (255, 255, 255, 30),
        "hover": (255, 255, 255, 22), "danger": (239, 68, 68, 255), "ok": (74, 222, 128, 255),
        "dim": (0, 0, 0, 170),
    },
    "light": {
        "bg1": (250, 247, 255, 255), "bg2": (237, 228, 253, 255), "bg3": (221, 205, 250, 255),
        "card": (255, 255, 255, 150), "card_border": (90, 60, 160, 40),
        "panel": (252, 250, 255, 252),
        "text": (29, 20, 51, 255), "sub": (103, 92, 133, 255),
        "accent": (124, 58, 237, 255), "accent2": (192, 38, 211, 255),
        "input": (255, 255, 255, 190), "input_border": (90, 60, 160, 50),
        "hover": (90, 60, 160, 28), "danger": (220, 38, 38, 255), "ok": (22, 163, 74, 255),
        "dim": (30, 20, 60, 110),
    },
}


# ---------------------------------------------------------------- looks (whole-UI styles)
# "aurora" is the original look (dark / light + accent colours). The others bring their own palette and shapes.
LOOKS = {
    "aurora": {"label": "Aurora", "blurb": "The classic Asena Mask look. Dark or light, with your accent colour."},
    "aero": {"label": "Frutiger Aero", "blurb": "Deep glass over a glowing blue sea, light rays and drifting bubbles."},
    "retro": {"label": "Retro", "blurb": "Old console menus: blue waves, drifting glass cubes and silver bevelled buttons."},
}

LOOK_PALETTES = {
    "aero": {
        "bg1": (22, 146, 204, 255), "bg2": (10, 96, 168, 255), "bg3": (5, 44, 104, 255),
        "card": (255, 255, 255, 30), "card_border": (255, 255, 255, 190),
        "panel": (12, 74, 136, 238),
        "text": (255, 255, 255, 255), "sub": (200, 232, 252, 255),
        "accent": (36, 150, 236, 255), "accent2": (96, 214, 255, 255),
        "input": (255, 255, 255, 228), "input_border": (255, 255, 255, 215),
        "hover": (255, 255, 255, 52), "danger": (255, 98, 98, 255), "ok": (128, 244, 168, 255),
        "dim": (0, 28, 70, 150),
    },
    "retro": {
        "bg1": (2, 3, 14, 255), "bg2": (7, 11, 38, 255), "bg3": (20, 26, 74, 255),
        "card": (255, 255, 255, 14), "card_border": (255, 255, 255, 120),
        "panel": (8, 12, 34, 246),
        "text": (246, 248, 255, 255), "sub": (160, 174, 214, 255),
        "accent": (150, 172, 255, 255), "accent2": (255, 255, 255, 255),
        "input": (255, 255, 255, 20), "input_border": (255, 255, 255, 110),
        "hover": (255, 255, 255, 26), "danger": (255, 110, 110, 255), "ok": (130, 240, 170, 255),
        "dim": (0, 0, 10, 190),
    },
}

# shape parameters per look ("glass" looks share the Frutiger Aero painting)
_AERO = {"radius": 1.0, "pill": True, "gloss": True, "flat": False, "scrim": (0, 30, 70),
         "logo_anim": False, "bar_h": 20, "caps": False, "mode": "dark", "glass": True, "font": "Segoe UI",
         "input_text": "#14324f"}
LOOK_PARAMS = {
    "aurora": {"radius": 1.0, "pill": False, "gloss": False, "flat": False, "bg": "aurora", "scrim": (0, 0, 0),
               "logo_anim": True, "bar_h": 14, "caps": False, "mode": None, "glass": False, "font": "Segoe UI",
               "input_text": None},
    "aero": dict(_AERO, bg="aqua"),
    "retro": {"radius": 0.25, "pill": False, "gloss": False, "flat": True, "bg": "retro", "scrim": (0, 20, 80),
              "logo_anim": False, "bar_h": 12, "caps": True, "mode": "dark", "glass": False, "font": "Segoe UI",
              "input_text": "#ffffff", "thin": True, "families": ["Bahnschrift", "Segoe UI"]},
}


ACCENTS = {   # name: (start, end)
    "Violet": ((139, 92, 246), (217, 70, 239)),
    "Ocean": ((56, 189, 248), (99, 102, 241)),
    "Sunset": ((251, 146, 60), (244, 63, 94)),
    "Emerald": ((52, 211, 153), (20, 184, 166)),
    "Rose": ((244, 114, 182), (168, 85, 247)),
    "Crimson": ((239, 68, 68), (249, 115, 22)),
    "Ice": ((125, 211, 252), (196, 181, 253)),
    "Mono": ((200, 200, 210), (120, 120, 140)),
}


class Theme(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.mode = "dark"          # the user's dark / light choice (used by the Aurora look)
        self.name = "dark"          # the mode actually in effect (looks can force one)
        self.look = "aurora"
        self.accent_name = "Violet"

    def param(self, key):
        return LOOK_PARAMS[self.look][key]

    @property
    def glass(self):
        return LOOK_PARAMS[self.look]["glass"]

    def font(self, size, weight=None):
        """A QFont in the current look's typeface. Glass looks use lighter weights, like the Windows 7 era."""
        from PySide6.QtGui import QFont
        f = QFont(LOOK_PARAMS[self.look]["font"], size)
        fam = LOOK_PARAMS[self.look].get("families")
        if fam:
            f.setFamilies(fam)
        w = QFont.DemiBold if weight is None else weight
        if self.glass or LOOK_PARAMS[self.look].get("thin"):
            if size >= 18:
                w = QFont.Light
            elif w in (QFont.Bold, QFont.DemiBold):
                w = QFont.Normal
        f.setWeight(w)
        return f

    def _effective(self):
        forced = LOOK_PARAMS[self.look]["mode"]
        return forced or self.mode

    def set_look(self, name):
        if name in LOOKS and name != self.look:
            self.look = name
            self.name = self._effective()
            self.changed.emit()

    def set_accent(self, name):
        if name in ACCENTS and name != self.accent_name:
            self.accent_name = name
            self.changed.emit()

    def _lookup(self, key):
        if self.look != "aurora":
            return LOOK_PALETTES[self.look][key]
        if key == "accent":
            return ACCENTS[self.accent_name][0] + (255,)
        if key == "accent2":
            return ACCENTS[self.accent_name][1] + (255,)
        return PALETTES[self.name][key]

    def set(self, name):
        if name in PALETTES and name != self.mode:
            self.mode = name
            self.name = self._effective()
            self.changed.emit()

    def tup(self, key):
        return self._lookup(key)

    def col(self, key, alpha=None):
        r, g, b, a = self._lookup(key)
        return QColor(r, g, b, a if alpha is None else alpha)

    def css(self, key):
        r, g, b, a = self._lookup(key)
        return "rgba(%d,%d,%d,%.3f)" % (r, g, b, a / 255.0)


theme = Theme()


def mix(c1: QColor, c2: QColor, t: float) -> QColor:
    return QColor(int(c1.red() + (c2.red() - c1.red()) * t), int(c1.green() + (c2.green() - c1.green()) * t),
                  int(c1.blue() + (c2.blue() - c1.blue()) * t), int(c1.alpha() + (c2.alpha() - c1.alpha()) * t))


def _retro_qss():
    """Retro: dark flat fields with a thin white outline, white text, console-style lists."""
    return """
    * { font-family: "Bahnschrift", "Segoe UI"; }
    QLineEdit, QPlainTextEdit, QComboBox { color: white; border-radius: 0px; border: 1px solid rgba(255,255,255,110);
        border-bottom: 2px solid rgba(255,255,255,200); background: rgba(255,255,255,20);
        selection-background-color: rgba(150,172,255,200); }
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:hover { border: 1px solid white; border-bottom: 2px solid white;
        background: rgba(255,255,255,34); }
    QComboBox::down-arrow { border-top: 6px solid white; }
    QComboBox QAbstractItemView { color: white; background: rgb(8,12,34); border: 1px solid rgba(255,255,255,200);
        border-radius: 0px; padding: 2px; outline: 0; selection-color: white; selection-background-color: rgba(255,255,255,46); }
    QComboBox QAbstractItemView::item { color: white; padding: 7px 12px; min-height: 22px; }
    QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected { color: white;
        background: rgba(255,255,255,46); border-left: 3px solid white; }
    QMenu { color: white; background: rgb(8,12,34); border: 1px solid rgba(255,255,255,200); border-radius: 0px; }
    QMenu::item { color: white; padding: 8px 24px 8px 14px; }
    QMenu::item:selected { color: white; background: rgba(255,255,255,46); }
    QToolTip { color: white; background: rgb(8,12,34); border: 1px solid rgba(255,255,255,200); }
    QSlider::groove:horizontal { height: 2px; background: rgba(255,255,255,90); }
    QSlider::sub-page:horizontal { background: white; }
    QSlider::handle:horizontal { width: 10px; height: 18px; margin: -8px 0; border: 1px solid white;
        background: rgb(8,12,34); }
    QSlider::handle:horizontal:hover { background: white; }
    QScrollBar:vertical { background: transparent; width: 6px; margin: 2px; }
    QScrollBar::handle:vertical { background: rgba(255,255,255,170); border-radius: 0px; min-height: 30px; }
    QListWidget { background: transparent; border: none; border-bottom: 1px solid rgba(255,255,255,90); }
    QListWidget::item { border-radius: 0; color: rgba(255,255,255,150); padding: 8px 14px; }
    QListWidget::item:hover { color: white; background: rgba(255,255,255,24); }
    QListWidget::item:selected { background: rgba(255,255,255,34); color: white; border-bottom: 2px solid white; }
    """


def _glass_qss():
    """Extra rules for the Frutiger Aero looks: bright glass inputs, glossy sliders, glass scrollbars."""
    if theme.look == "retro":
        return _retro_qss()
    if not theme.glass:
        return ""
    it = LOOK_PARAMS[theme.look]["input_text"]
    return """
    QLineEdit, QPlainTextEdit, QComboBox { color: %(it)s; border-radius: 9px; border: 1px solid rgba(255,255,255,235);
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(255,255,255,245), stop:0.5 rgba(236,246,255,232),
        stop:1 rgba(214,234,250,226)); selection-background-color: %%(accent)s; }
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:hover { border: 1px solid %%(accent2)s; }
    QComboBox::down-arrow { border-top: 6px solid %(it)s; }
    QComboBox QAbstractItemView { color: %(it)s; background: rgb(247,251,255); border: 1px solid white;
        border-radius: 10px; padding: 4px; outline: 0; selection-color: %(it)s;
        selection-background-color: rgb(166,212,250); }
    QComboBox QAbstractItemView::item { color: %(it)s; padding: 6px 10px; min-height: 22px; border-radius: 6px; }
    QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected { color: %(it)s;
        background: rgb(166,212,250); }
    QMenu { color: %(it)s; background: rgb(247,251,255); border: 1px solid white; }
    QMenu::item { color: %(it)s; }
    QMenu::item:selected { color: %(it)s; background: rgb(166,212,250); }
    QToolTip { color: #14324f; background: rgba(240,250,255,245); border: 1px solid white; }
    QSlider::groove:horizontal { height: 8px; border-radius: 4px; border: 1px solid rgba(255,255,255,200);
        background: rgba(0,30,70,70); }
    QSlider::sub-page:horizontal { border-radius: 4px; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 %%(accent2)s, stop:0.5 %%(accent)s, stop:0.52 %%(accent)s, stop:1 %%(accent2)s); }
    QSlider::handle:horizontal { width: 18px; height: 18px; margin: -6px 0; border-radius: 10px; border: 2px solid white;
        background: qradialgradient(cx:0.4,cy:0.3,radius:0.9,fx:0.35,fy:0.25, stop:0 white, stop:0.55 %%(accent2)s,
        stop:1 %%(accent)s); }
    QSlider::handle:horizontal:hover { background: qradialgradient(cx:0.4,cy:0.3,radius:0.9,fx:0.35,fy:0.25,
        stop:0 white, stop:0.4 white, stop:1 %%(accent2)s); }
    QScrollBar:vertical { background: rgba(255,255,255,40); border-radius: 6px; width: 12px; margin: 2px; }
    QScrollBar::handle:vertical { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(255,255,255,235),
        stop:1 rgba(190,225,250,215)); border: 1px solid white; border-radius: 5px; min-height: 30px; }
    QListWidget { background: rgba(255,255,255,34); border: 1px solid rgba(255,255,255,200); border-radius: 14px; }
    QListWidget::item { border-radius: 9px; border: 1px solid transparent; }
    QListWidget::item:hover { background: rgba(255,255,255,60); }
    QListWidget::item:selected { border: 1px solid rgba(255,255,255,235); background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 %%(accent2)s, stop:0.5 %%(accent)s, stop:0.52 %%(accent)s, stop:1 %%(accent2)s); color: white; }
    """ % {"it": it}


def stylesheet():
    t = theme
    return ("""
    QWidget { color: %(text)s; }
    QToolTip { background: %(panel)s; color: %(text)s; border: 1px solid %(cb)s; padding: 5px 8px; border-radius: 6px; }
    QLineEdit, QPlainTextEdit {
        background: %(input)s; border: 1px solid %(ib)s; border-radius: 10px; padding: 8px 12px;
        selection-background-color: %(accent)s; selection-color: white; }
    QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid %(accent)s; }
    QComboBox { background: %(input)s; border: 1px solid %(ib)s; border-radius: 10px; padding: 8px 12px; }
    QComboBox:hover { border: 1px solid %(accent)s; }
    QComboBox::drop-down { border: none; width: 28px; }
    QComboBox::down-arrow { image: none; border-left: 5px solid transparent; border-right: 5px solid transparent;
        border-top: 6px solid %(sub)s; margin-right: 10px; }
    QComboBox QAbstractItemView { background: %(panelsolid)s; border: 1px solid %(cb)s; border-radius: 8px; padding: 4px;
        selection-background-color: %(accent)s; selection-color: white; outline: 0; }
    QSlider::groove:horizontal { height: 6px; border-radius: 3px; background: %(input)s; }
    QSlider::sub-page:horizontal { border-radius: 3px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 %(accent)s, stop:1 %(accent2)s); }
    QSlider::handle:horizontal { width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; background: white; border: 2px solid %(accent)s; }
    QSlider::handle:horizontal:hover { background: %(accent)s; }
    QMenu { background: %(panelsolid)s; border: 1px solid %(cb)s; border-radius: 12px; padding: 6px; }
    QMenu::item { padding: 9px 26px 9px 16px; border-radius: 8px; }
    QMenu::item:selected { background: %(accent)s; color: white; }
    QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical { background: %(ib)s; border-radius: 4px; min-height: 30px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollArea { border: none; background: transparent; }
    QListWidget { background: %(input)s; border: 1px solid %(ib)s; border-radius: 12px; padding: 6px; outline: 0; }
    QListWidget::item { padding: 9px 10px; border-radius: 8px; }
    QListWidget::item:selected { background: %(accent)s; color: white; }
    QScrollArea, QAbstractScrollArea { background: transparent; }
    QScrollArea > QWidget > QWidget { background: transparent; }
    """ + _glass_qss()) % {
        "text": t.css("text"), "sub": t.css("sub"), "accent": t.css("accent"), "accent2": t.css("accent2"),
        "input": t.css("input"), "ib": t.css("input_border"), "cb": t.css("card_border"),
        "panel": t.css("panel"), "panelsolid": "rgb(%d,%d,%d)" % t.tup("panel")[:3],
    }
