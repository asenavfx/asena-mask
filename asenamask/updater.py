"""In-app updates: looks for a newer version.json on the website, downloads the package and hands over to the
updater (a copy of the installer run with --update) which replaces the app files while the app is closed."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import APP_NAME, APP_VERSION, UPDATE_URL, paths, release

def open_url(req, timeout=30):
    """urlopen that survives PCs with an out-of-date Windows certificate store: if the normal check fails with a
    certificate error, it tries again with the certificate list bundled in the app (certifi). Never skips the check."""
    import ssl
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except Exception as e:
        reason = getattr(e, "reason", e)
        if not isinstance(reason, ssl.SSLError) and "CERTIFICATE" not in str(e).upper():
            raise
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            raise e
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)


UA = "AsenaMask/%s" % APP_VERSION


def parse_version(v):
    out = []
    for part in str(v).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def is_newer(a, b):
    return parse_version(a) > parse_version(b)


class CheckThread(QThread):
    """Asks the website for version.json. Emits found(info) only when a newer version exists."""
    found = Signal(dict)
    none = Signal()

    def __init__(self, force=False, parent=None):
        super().__init__(parent)
        self.force = force

    def run(self):
        if not paths.install_root() and not self.force:       # running from source: never self-update
            self.none.emit()
            return
        try:
            t = int(time.time())
            raw = open_url(urllib.request.Request("%s?t=%d" % (UPDATE_URL, t), headers={"User-Agent": UA}), timeout=8).read()
            sig = open_url(urllib.request.Request("%s.sig?t=%d" % (UPDATE_URL, t), headers={"User-Agent": UA}), timeout=8).read()
            data = release.check(raw, sig.decode("ascii"))     # unsigned / tampered / malformed: no update offered
        except Exception:
            self.none.emit()
            return
        v = str(data.get("version", "")).strip()
        if v and data.get("url") and is_newer(v, APP_VERSION):
            self.found.emit(data)
        else:
            self.none.emit()


class DownloadThread(QThread):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        info = self.info
        d = Path(tempfile.gettempdir()) / "AsenaMaskUpdate"
        d.mkdir(parents=True, exist_ok=True)
        dest = d / ("AsenaMask-app-%s.zip" % info.get("version", "new"))
        part = str(dest) + ".part"
        try:
            req = urllib.request.Request(info["url"], headers={"User-Agent": UA})
            resp = open_url(req, timeout=30)
            total = int(resp.headers.get("Content-Length") or info.get("size") or 0)
            have = 0
            h = hashlib.sha256()
            with open(part, "wb") as f:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    if self._stop:
                        return
                    f.write(chunk)
                    h.update(chunk)
                    have += len(chunk)
                    self.progress.emit(have, total)
            if total and have < total:
                raise IOError("connection closed early")
            want = (info.get("sha256") or "").lower()
            if not want or h.hexdigest().lower() != want:
                os.remove(part)
                self.failed.emit("The download did not pass its safety check. Please try again in a few minutes.")
                return
            os.replace(part, dest)
        except Exception as e:
            self.failed.emit("Could not download the update (%s). Check your internet connection." % e)
            return
        self.done.emit(str(dest))


def launch_updater(zip_path, info):
    """Starts the updater (a copy of the installer) and returns. The caller must close the app right after."""
    root = paths.install_root()
    if not root:
        raise RuntimeError("Updates only work in the installed app.")
    helper = Path(root) / ("Uninstall %s.exe" % APP_NAME)
    if not helper.is_file():
        raise RuntimeError("The update helper is missing. Please run the Asena Mask installer again.")
    tmp = Path(tempfile.gettempdir()) / "AsenaMaskUpdater.exe"
    shutil.copy2(helper, tmp)
    info_file = Path(tempfile.gettempdir()) / "AsenaMaskUpdate" / "update.json"
    info = dict(info)
    info.pop("pip", None)          # older update helpers would pip-install whatever this lists
    with open(info_file, "w", encoding="utf-8") as f:
        json.dump(info, f)
    subprocess.Popen([str(tmp), "--update", str(zip_path), "--dir", str(root), "--pid", str(os.getpid()),
                      "--info", str(info_file)],
                     creationflags=0x00000008 | 0x00000200, close_fds=True)   # detached, own process group
