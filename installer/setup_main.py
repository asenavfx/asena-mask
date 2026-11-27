"""Entry point of "Asena Mask Setup.exe"."""
import os
import sys

if getattr(sys, "frozen", False):
    sys.path.insert(0, getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from setup_ui import run   # noqa: E402


def _arg(name):
    a = sys.argv
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else None


if __name__ == "__main__":
    if "--update" in sys.argv:
        info = {}
        try:
            import json
            with open(_arg("--info"), encoding="utf-8") as f:
                info = json.load(f)
        except Exception:
            pass
        sys.exit(run(update={"zip": _arg("--update"), "dir": _arg("--dir"), "pid": _arg("--pid"), "info": info}))
    sys.exit(run("--uninstall" in sys.argv))
