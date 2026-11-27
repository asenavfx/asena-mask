"""UI sound effects (Windows only; silently does nothing elsewhere).

Files in assets/sounds: welcome.wav, button.wav, small.wav, output.wav
"""
import os
import random
import time

from . import paths

try:
    import winsound
except Exception:  # not Windows
    winsound = None

enabled = True
look = "aurora"   # set by the app; a look can ship its own sounds
# only these may be overridden per look: clicks always use the standard sounds
LOOK_SOUNDS = ("welcome", "render_1", "render_2", "render_secret", "output", "hover")
_last = {}


def _find(name):
    """Look-specific sound first (assets/sounds/<look>/ or %APPDATA%/AsenaMask/sounds/<look>/), then the default."""
    cands = []
    if look and look != "aurora" and name in LOOK_SOUNDS:
        cands.append(paths.asset("sounds/%s/%s.wav" % (look, name)))
        try:
            cands.append(os.path.join(str(paths.data_dir()), "sounds", look, name + ".wav"))
        except Exception:
            pass
    cands.append(paths.asset("sounds/%s.wav" % name))
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def play(name, min_gap=0.0):
    """Play assets/sounds/<name>.wav without blocking."""
    if not enabled or winsound is None:
        return
    now = time.monotonic()
    if now - _last.get(name, 0) < min_gap:
        return
    _last[name] = now
    f = _find(name)
    if f:
        try:
            winsound.PlaySound(f, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:
            pass


def alt_held():
    """True while the Alt key is physically held down (works even if the window is not focused)."""
    try:
        if os.name == "nt":
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x12) & 0x8000)
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import Qt
        return bool(QGuiApplication.queryKeyboardModifiers() & Qt.AltModifier)
    except Exception:
        return False


def finish():
    """Played when a render or queue ends. A look with its own finish sounds picks one at random; if it also has a rare
    one, that plays 20% of the time, and always while Alt is held. Looks without them use the plain output sound."""
    if not enabled:
        return
    normal = [n for n in ("render_1", "render_2") if _find(n)]
    if not normal:
        return play("output")
    if _find("render_secret") and (alt_held() or random.random() < 0.2):
        return play("render_secret")
    play(random.choice(normal))
