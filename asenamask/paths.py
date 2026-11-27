"""Folders used by Asena Mask."""
import os
import sys
import tempfile
from pathlib import Path

# Running from source: set ASENA_COMFY to your ComfyUI folder, or put ComfyUI in engine\ComfyUI next to main.py.
CANDIDATE_COMFY = [c for c in (os.environ.get("ASENA_COMFY", ""),
                               str(Path(__file__).resolve().parent.parent / "engine" / "ComfyUI")) if c]


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / "AsenaMask"
    p.mkdir(parents=True, exist_ok=True)
    return p


def work_root() -> Path:
    p = Path(tempfile.gettempdir()) / "AsenaMask"
    p.mkdir(parents=True, exist_ok=True)
    return p


def install_root():
    """Folder of the installed app (contains install.json), or None when running from source."""
    if getattr(sys, "frozen", False):
        p = Path(sys.executable).resolve().parent
        if (p / "install.json").is_file():
            return p
    return None


def default_comfy() -> str:
    r = install_root()
    if r:
        return str(r / "engine" / "ComfyUI")
    for c in CANDIDATE_COMFY:
        if os.path.isfile(os.path.join(c, "main.py")):
            return c
    return ""


def worker_command(job_file: str) -> list:
    """Command line that starts the worker process."""
    r = install_root()
    if r:   # installed build: the app's own private Python runtime, never anything else on the PC
        return [str(r / "runtime" / "python.exe"), str(r / "app" / "main.py"), "--worker", job_file]
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker", job_file]
    return [sys.executable, str(app_dir() / "main.py"), "--worker", job_file]


def server_command(cfg_file: str) -> list:
    """Command line that starts the live-preview server (keeps the model loaded)."""
    r = install_root()
    if r:
        return [str(r / "runtime" / "python.exe"), str(r / "app" / "main.py"), "--server", cfg_file]
    if getattr(sys, "frozen", False):
        return [sys.executable, "--server", cfg_file]
    return [sys.executable, str(app_dir() / "main.py"), "--server", cfg_file]


def asset(name: str) -> str:
    """Path of a file in asenamask/assets (may not exist)."""
    return str(app_dir() / "asenamask" / "assets" / name)
