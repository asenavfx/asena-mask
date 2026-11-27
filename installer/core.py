"""Installer engine (no Qt): downloads, unpacks and sets everything up. The window lives in setup_ui.py.

Layout created inside the install folder:
    Asena Mask.exe, _internal\\     the app window (PyInstaller build, from the app package)
    app\\                           python sources used by the processing worker
    engine\\ComfyUI\\               the engine code (from the app package)
    runtime\\                       private Python + PyTorch + libraries (installed here, nothing global)
    models\\checkpoints\\           the AI model
    install.json                   written last; its presence means "installed"
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


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

try:
    from . import config as C
except ImportError:  # run as a plain script / tests
    import config as C
from asenamask import release   # noqa: E402  (signature check for version.json, shared with the app)

CREATE_NO_WINDOW = 0x08000000
UA = "AsenaMaskInstaller/%s" % C.APP_VERSION
LOG_PATH = os.path.join(os.environ.get("TEMP", "."), "AsenaMaskSetup.log")


class InstallError(Exception):
    """A problem with a message that is safe to show to a normal user."""

    def __init__(self, friendly, technical=""):
        super().__init__(friendly)
        self.friendly = friendly
        self.technical = technical


class Cancelled(Exception):
    pass


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def default_install_dir():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return os.path.join(base, "Programs", C.APP_NAME)


def read_install(dirpath):
    try:
        with open(os.path.join(dirpath, "install.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def human_bytes(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return ("%.0f %s" if u in ("B", "KB") else "%.1f %s") % (n, u)
        n /= 1024.0


# ---------------------------------------------------------------- GPU check
def find_nvidia_smi():
    cands = ["nvidia-smi",
             os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe"),
             r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"]
    for c in cands:
        try:
            for q in ("name,driver_version,compute_cap", "name,driver_version"):     # old drivers cannot report compute_cap
                r = subprocess.run([c, "--query-gpu=" + q, "--format=csv,noheader"],
                                   capture_output=True, text=True, timeout=20, creationflags=CREATE_NO_WINDOW)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.strip().splitlines()
        except Exception:
            continue
    return None


def other_gpu_names():
    """Names of all graphics adapters (Windows), used for AMD / Intel detection."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
                           capture_output=True, text=True, timeout=40, creationflags=CREATE_NO_WINDOW)
        return [x.strip() for x in r.stdout.splitlines() if x.strip()]
    except Exception:
        return []


def classify_gpu(names):
    """-> ('amd'|'intel', name) for the best non-NVIDIA adapter, or (None, '')."""
    best = (None, "")
    for n in names:
        low = n.lower()
        if "amd" in low or "radeon" in low:
            if "radeon" in low and ("rx " in low or "pro w" in low or "ai pro" in low):
                return "amd", n               # a real Radeon card beats an integrated one
            best = best if best[0] else ("amd", n)
        elif "intel" in low and ("arc" in low or "iris" in low or "uhd" in low or "graphics" in low):
            if "arc" in low:
                return "intel", n
            best = best if best[0] else ("intel", n)
    return best


CAP = [0.0]           # compute capability of the NVIDIA card (set by check_gpu; 0 = unknown)


def check_gpu():
    """Returns (gpu_name, driver_float, backend). backend is 'cuda' (NVIDIA), or in the experimental build also
    'rocm' (AMD) / 'xpu' (Intel). Raises InstallError if there is no usable graphics card."""
    rows = find_nvidia_smi()
    if not rows:
        if C.EXPERIMENTAL:
            vendor, name = classify_gpu(other_gpu_names())
            if vendor == "amd":
                return name, 0.0, "rocm"
            if vendor == "intel":
                return name, 0.0, "xpu"
            raise InstallError("No NVIDIA, AMD Radeon or Intel Arc graphics card was found.\n\nThis experimental "
                               "build needs one of them with an up-to-date driver.", "no usable adapter")
        raise InstallError(
            "No NVIDIA graphics card was found.\n\nAsena Mask needs an NVIDIA GPU (GeForce RTX / GTX) with an "
            "up-to-date driver. If you have one, install the latest driver from nvidia.com and run this again.",
            "nvidia-smi gave no output")
    parts = [x.strip() for x in rows[0].split(",")]
    name, drv = parts[0], (parts[1] if len(parts) > 1 else "")
    CAP[0] = 0.0
    if len(parts) > 2:
        try:
            CAP[0] = float(parts[2])
        except ValueError:
            pass
    if 0 < CAP[0] < 5.0:
        raise InstallError("Your graphics card (%s) is too old for Asena Mask.\n\nIt needs a GeForce GTX 900 series "
                           "or newer." % name, "compute capability %.1f" % CAP[0])
    try:
        v = float(drv)
    except ValueError:
        v = 0.0
    if v and v < C.MIN_DRIVER:
        raise InstallError(
            "Your NVIDIA driver (%s) is too old.\n\nPlease update it from nvidia.com (version %d or newer) "
            "and run the installer again." % (drv, int(C.MIN_DRIVER)), "driver %s" % drv)
    return name, v, "cuda"


def check_disk(install_dir):
    p = Path(install_dir)
    while not p.exists() and p != p.parent:
        p = p.parent
    free = shutil.disk_usage(str(p)).free / 1024 ** 3
    if free < C.MIN_FREE_GB:
        raise InstallError("Not enough free space on that drive.\n\nAsena Mask needs about %d GB, "
                           "and only %.1f GB is free. Free up some space or choose another folder." % (
                               C.MIN_FREE_GB, free), "free %.1f GB" % free)


# ---------------------------------------------------------------- downloads
def _sha256(path, cancel=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
            if cancel and cancel.is_set():
                raise Cancelled()
    return h.hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def remote_meta(url):
    """(size, sha256_or_None) from the first response (Hugging Face reports the file hash in x-linked-etag)."""
    op = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        r = op.open(req, timeout=30)
        hd = r.headers
    except urllib.error.HTTPError as e:
        hd = e.headers
    except Exception:
        return None, None
    size = hd.get("x-linked-size") or hd.get("Content-Length")
    etag = (hd.get("x-linked-etag") or "").strip('"')
    sha = etag if re.fullmatch(r"[0-9a-f]{64}", etag or "") else None
    try:
        size = int(size) if size else None
    except ValueError:
        size = None
    return size, sha


def download(url, dest, cancel, on_bytes, expect_sha=None, expect_size=None, retries=6):
    """Resumable download to `dest` (uses dest + '.part'). on_bytes(done, total)."""
    dest = str(dest)
    part = dest + ".part"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.isfile(dest):
        if (expect_size is None or os.path.getsize(dest) == expect_size) and                 (not expect_sha or _sha256(dest, cancel).lower() == expect_sha.lower()):
            on_bytes(os.path.getsize(dest), os.path.getsize(dest))
            return
    last_err = None
    for attempt in range(retries):
        if cancel.is_set():
            raise Cancelled()
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        try:
            hd = {"User-Agent": UA}
            if have:
                hd["Range"] = "bytes=%d-" % have
            resp = open_url(urllib.request.Request(url, headers=hd), timeout=45)
            status = getattr(resp, "status", 200)
            clen = int(resp.headers.get("Content-Length") or 0)
            if have and status != 206:       # server ignored the range: start over
                have = 0
            total = (have + clen) if clen else (expect_size or 0)
            mode = "ab" if have else "wb"
            with open(part, mode) as f:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    have += len(chunk)
                    on_bytes(have, total)
                    if cancel.is_set():
                        raise Cancelled()
            if total and have < total:
                raise IOError("connection closed early (%d of %d bytes)" % (have, total))
            break
        except Cancelled:
            raise
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 416 and os.path.isfile(part):   # already complete
                break
            if e.code in (401, 403, 404):
                raise InstallError("A download was refused by the server (error %d).\n\nPlease try again later." % e.code,
                                   "%s -> %s" % (url, e))
            time.sleep(min(2 ** attempt, 20))
        except Exception as e:
            last_err = e
            log("download retry %d: %s" % (attempt + 1, e))
            for _ in range(min(2 ** attempt, 20) * 2):
                if cancel.is_set():
                    raise Cancelled()
                time.sleep(0.5)
    else:
        raise InstallError("The download kept failing. Please check your internet connection and run the installer "
                           "again - it will continue where it stopped.", "%s -> %s" % (url, last_err))
    if expect_size and os.path.getsize(part) != expect_size:
        raise InstallError("A downloaded file is incomplete. Please run the installer again.",
                           "size %d != %d" % (os.path.getsize(part), expect_size))
    if expect_sha:
        if _sha256(part, cancel).lower() != expect_sha.lower():
            os.remove(part)
            raise InstallError("A downloaded file did not pass its safety check (it may be damaged). "
                               "Please run the installer again.", "sha256 mismatch for %s" % url)
    os.replace(part, dest)


# ---------------------------------------------------------------- the installer
class Installer:
    """Runs the whole installation. Create it, call run() in a worker thread.

    on_step(index, title)  - a new step began
    on_progress(fraction 0..1 overall, detail text)
    """

    def __init__(self, install_dir, desktop_shortcut, on_step, on_progress, share_stats=False):
        self.dir = os.path.abspath(install_dir)
        self.share_stats = share_stats
        self.desktop = desktop_shortcut
        self.on_step, self.on_progress = on_step, on_progress
        self.cancel = threading.Event()
        self.proc = None
        self.cur = 0
        self.total_w = float(sum(s[2] for s in C.STEPS))
        self.gpu = ""
        self.backend = "cuda"
        self.selftest = {}
        self.py = os.path.join(self.dir, "runtime", "python.exe")

    # ----- progress helpers
    def _sub(self, frac, detail=""):
        frac = max(0.0, min(1.0, frac))
        before = sum(s[2] for s in C.STEPS[:self.cur])
        self.on_progress((before + C.STEPS[self.cur][2] * frac) / self.total_w, detail)

    def _begin(self, key):
        self.cur = [s[0] for s in C.STEPS].index(key)
        log("STEP %s" % key)
        self.on_step(self.cur, C.STEPS[self.cur][1])
        self._sub(0.0)

    def request_cancel(self):
        self.cancel.set()
        p = self.proc
        if p and p.poll() is None:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], creationflags=CREATE_NO_WINDOW,
                               capture_output=True)
            except Exception:
                pass

    def _chk(self):
        if self.cancel.is_set():
            raise Cancelled()

    # ----- subprocess with live output
    def _run(self, args, on_line=None, tick=None, cwd=None, env=None):
        log("RUN %s" % " ".join('"%s"' % a if " " in a else a for a in args))
        e = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PIP_DISABLE_PIP_VERSION_CHECK="1",
                 PYTHONUTF8="1")
        e.pop("PYTHONPATH", None)
        e.pop("PYTHONHOME", None)
        if env:
            e.update(env)
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", cwd=cwd, env=e,
                                     creationflags=CREATE_NO_WINDOW)
        lines = []
        stop = threading.Event()

        def pump():
            for ln in self.proc.stdout:
                ln = ln.rstrip()
                lines.append(ln)
                if len(lines) > 400:
                    del lines[:200]
                if on_line:
                    on_line(ln)
            stop.set()

        t = threading.Thread(target=pump, daemon=True)
        t.start()
        while not stop.wait(0.4):
            if tick:
                tick()
            if self.cancel.is_set():
                self.request_cancel()
        t.join(2)
        rc = self.proc.wait()
        for ln in lines:
            log("  " + ln)
        self._chk()
        return rc, "\n".join(lines[-30:])

    # ----- pip with a smooth progress bar
    def _pip(self, args, expected_bytes, detail, tau):
        st = {"done": 0, "cur": 0, "seen": 0, "t0": time.time(), "name": ""}
        rx_dl = re.compile(r"Downloading\s+(\S+)\s+\(([\d.]+)\s*(kB|KB|MB|GB)\)")
        rx_pg = re.compile(r"Progress\s+(\d+)\s+of\s+(\d+)")
        mult = {"kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9}

        def on_line(ln):
            m = rx_dl.search(ln)
            if m:
                st["done"] += st["cur"]
                st["cur"] = 0
                st["seen"] += float(m.group(2)) * mult[m.group(3)]
                st["name"] = m.group(1)
                return
            m = rx_pg.search(ln)
            if m:
                st["cur"] = int(m.group(1))

        def tick():
            real = (st["done"] + st["cur"]) / max(expected_bytes, st["seen"], 1.0)
            creep = 1 - 2.718 ** (-(time.time() - st["t0"]) / tau)
            f = max(real, 0.0 if st["seen"] else creep * 0.5)
            self._sub(min(f, 0.97), detail)

        rc, tail = self._run([self.py, "-m", "pip"] + args + [
            "--progress-bar", "raw", "--no-warn-script-location",
            "--cache-dir", os.path.join(self.dir, "cache")], on_line, tick)
        if rc != 0:
            raise InstallError("Setting up the engine failed. Please check your internet connection and run the "
                               "installer again.", tail)
        self._sub(1.0, detail)

    # ================================================================ steps
    def run(self):
        os.makedirs(self.dir, exist_ok=True)
        log("=== install to %s" % self.dir)
        self.step_check()
        self.step_app()
        self.start_model_download()
        self.step_python()
        self.step_torch()
        self.step_deps()
        self.step_model()
        self.step_verify()
        self.step_finish()

    def step_check(self):
        self._begin("check")
        if os.name == "nt" and not (os.environ.get("PROCESSOR_ARCHITECTURE", "").endswith("64")
                                    or os.environ.get("PROCESSOR_ARCHITEW6432")):
            raise InstallError("Asena Mask needs 64-bit Windows 10 or 11.")
        self.gpu, _, self.backend = check_gpu()
        self._sub(0.6, self.gpu)
        check_disk(self.dir)
        self._sub(1.0, self.gpu)

    def _package_path(self):
        here = [os.path.dirname(os.path.abspath(sys.executable))]
        if getattr(sys, "frozen", False):
            here.append(os.path.dirname(os.path.abspath(sys.argv[0])))
        here.append(os.path.dirname(os.path.abspath(__file__)))
        for d in here:
            try:
                found = sorted(f for f in os.listdir(d) if re.fullmatch(r"AsenaMask-app.*\.zip", f))
            except OSError:
                continue
            if found:
                return os.path.join(d, found[-1])
        return None

    def step_app(self):
        self._begin("app")
        pkg = self._package_path()
        url, sha = C.PACKAGE_URL, C.PACKAGE_SHA256
        if not pkg:
            info = fetch_version_info()
            if info:
                url, sha = info["url"], info["sha256"]
            if not url or not sha:
                raise InstallError("Could not find the app download. Please check your internet connection and run "
                                   "the installer again. If the log mentions a certificate error, make sure this PC's "
                                   "date, time and time zone are correct and that Windows is up to date.", "version.json unreachable and PACKAGE_URL empty")
            pkg = os.path.join(self.dir, "cache", "AsenaMask-app.zip")
            os.makedirs(os.path.dirname(pkg), exist_ok=True)
            download(url, pkg, self.cancel,
                     lambda d, t: self._sub(0.8 * d / max(t, 1), "Downloading %s" % human_bytes(d)),
                     expect_sha=sha or None)
        self._sub(0.8, "Unpacking")
        for d in ("_internal", "app", os.path.join("engine", "ComfyUI")):
            shutil.rmtree(os.path.join(self.dir, d), ignore_errors=True)
        try:
            with zipfile.ZipFile(pkg) as z:
                names = z.namelist()
                for i, n in enumerate(names):
                    self._chk()
                    z.extract(n, self.dir)
                    if i % 40 == 0:
                        self._sub(0.8 + 0.2 * i / max(len(names), 1), "Unpacking")
        except PermissionError as e:
            raise InstallError("Could not replace files. If Asena Mask is open, close it and try again.", str(e))
        except zipfile.BadZipFile as e:
            raise InstallError("The app package is damaged. Please download the installer again.", str(e))
        self._sub(1.0)

    def step_python(self):
        self._begin("python")
        if os.path.isfile(self.py) and self._pip_works():
            self._sub(1.0, "Already prepared")
            return
        rt = os.path.join(self.dir, "runtime")
        shutil.rmtree(rt, ignore_errors=True)
        os.makedirs(rt, exist_ok=True)
        zp = os.path.join(self.dir, "cache", "python-embed.zip")
        download(C.PYTHON_URL, zp, self.cancel, lambda d, t: self._sub(0.4 * d / max(t, 1), "Downloading (%s)" % human_bytes(d)),
                 expect_sha=C.PYTHON_SHA256)
        with zipfile.ZipFile(zp) as z:
            z.extractall(rt)
        # enable site-packages + our app folder, keep the runtime fully self-contained
        pth = os.path.join(rt, C.PYTHON_TAG + "._pth")
        with open(pth, "w", encoding="utf-8") as f:
            f.write("%s.zip\n.\nLib\\site-packages\n..\\app\nimport site\n" % C.PYTHON_TAG)
        os.makedirs(os.path.join(rt, "Lib", "site-packages"), exist_ok=True)
        gp = os.path.join(self.dir, "cache", "get-pip.py")
        download(C.GET_PIP_URL, gp, self.cancel, lambda d, t: self._sub(0.4 + 0.1 * d / max(t, 1)), expect_sha=C.GET_PIP_SHA256)
        self._sub(0.55, "Setting up")
        t0 = time.time()

        def creep():
            self._sub(0.55 + 0.42 * (1 - 2.718 ** (-(time.time() - t0) / 25.0)), "Setting up - this can take a minute")

        rc, tail = self._run([self.py, gp, "--no-warn-script-location", "--no-cache-dir"], tick=creep)
        if rc != 0:
            raise InstallError("Could not prepare the engine. Please check your internet connection and try again.", tail)
        self._sub(1.0)

    def _pip_works(self):
        try:
            r = subprocess.run([self.py, "-m", "pip", "--version"], capture_output=True, timeout=60,
                               creationflags=CREATE_NO_WINDOW)
            return r.returncode == 0
        except Exception:
            return False

    def step_torch(self):
        self._begin("torch")
        legacy = self.backend == "cuda" and 0 < CAP[0] < C.LEGACY_BELOW_CC
        want = {"cuda": "+cu126" if legacy else "+cu", "rocm": "+rocm", "xpu": "+xpu"}[self.backend]
        chk = subprocess.run([self.py, "-c", "import torch;print(torch.__version__)"], capture_output=True, text=True,
                             creationflags=CREATE_NO_WINDOW)
        if chk.returncode == 0 and want in chk.stdout:
            self._sub(1.0, "Already installed")
            return
        if self.backend == "cuda":
            if legacy:
                self._pip(["install", "--force-reinstall"] + C.TORCH_PACKAGES_LEGACY + ["--index-url", C.TORCH_INDEX_LEGACY],
                          C.TORCH_EXPECTED_BYTES, "This is the big one - a few minutes", 420.0)
            else:
                self._pip(["install"] + C.TORCH_PACKAGES + ["--index-url", C.TORCH_INDEX],
                          C.TORCH_EXPECTED_BYTES, "This is the big one - a few minutes", 420.0)
        elif self.backend == "xpu":
            self._pip(["install"] + C.TORCH_PACKAGES + ["--index-url", C.XPU_INDEX],
                      C.EXP_TORCH_EXPECTED_BYTES, "Intel Arc libraries - a few minutes", 420.0)
        else:   # AMD ROCm: the SDK first, then PyTorch built for it
            self._pip(["install"] + [C.ROCM_BASE + f for f in C.ROCM_SDK],
                      C.EXP_TORCH_EXPECTED_BYTES * 0.25, "AMD ROCm components", 200.0)
            self._pip(["install"] + [C.ROCM_BASE + f for f in C.ROCM_TORCH],
                      C.EXP_TORCH_EXPECTED_BYTES, "AMD Radeon libraries - a few minutes", 420.0)

    def step_deps(self):
        self._begin("deps")
        req = os.path.join(self.dir, "engine", "ComfyUI", "requirements.txt")
        keep = []
        if os.path.isfile(req):
            for ln in open(req, encoding="utf-8", errors="replace"):
                ln = ln.strip()
                name = re.split(r"[<>=!~\[; @]", ln, maxsplit=1)[0].lower().replace("_", "-")
                if not ln or ln.startswith("#") or name in ("torch", "torchvision", "torchaudio"):
                    continue     # torch comes from the GPU index in the previous step
                keep.append(ln)
        keep += ["imageio-ffmpeg", "pillow", "numpy", "av"]
        rf = os.path.join(self.dir, "cache", "engine-requirements.txt")
        os.makedirs(os.path.dirname(rf), exist_ok=True)
        with open(rf, "w", encoding="utf-8") as f:
            f.write("\n".join(keep) + "\n")
        self._pip(["install", "-r", rf], C.DEPS_EXPECTED_BYTES, "Almost there", 150.0)

    def start_model_download(self):
        """The model downloads in the background while PyTorch installs (network + disk work overlap)."""
        self._mdl = {"d": 0, "t": 0, "err": None, "done": False}
        dest = os.path.join(self.dir, "models", "checkpoints", C.MODEL_NAME)

        def work():
            st = self._mdl
            try:
                size, sha = remote_meta(C.MODEL_URL)
                if os.path.isfile(dest) and os.path.getsize(dest) >= C.MODEL_MIN_BYTES and (
                        size is None or os.path.getsize(dest) == size):
                    st["d"] = st["t"] = os.path.getsize(dest)
                else:
                    def cb(d, t):
                        st["d"], st["t"] = d, (t or size or 0)
                    download(C.MODEL_URL, dest, self.cancel, cb, expect_sha=sha, expect_size=size)
                    if os.path.getsize(dest) < C.MODEL_MIN_BYTES:
                        os.remove(dest)
                        raise InstallError("The AI model download was incomplete. Please run the installer again.")
            except BaseException as e:
                st["err"] = e
            st["done"] = True

        self._mdl_thread = threading.Thread(target=work, daemon=True)
        self._mdl_thread.start()

    def step_model(self):
        self._begin("model")
        st = self._mdl
        while not st["done"]:
            self._chk()
            t = st["t"] or 1
            self._sub(st["d"] / t, "%s of %s" % (human_bytes(st["d"]), human_bytes(st["t"])) if st["t"] else "Starting")
            time.sleep(0.4)
        self._chk()
        if st["err"]:
            raise st["err"]
        self._sub(1.0)

    def step_verify(self):
        self._begin("verify")
        code = ("import torch,sys;print('CUDA',torch.cuda.is_available());"
                "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else '');"
                "x=torch.ones(16,device='cuda') if torch.cuda.is_available() else None;"
                "print('KERNEL', float((x*2).sum()) if x is not None else 0)")
        if self.backend != "cuda":
            code = ("import sys;from asenamask.common import selftest;sys.exit(selftest())")
        rc, out = self._run([self.py, "-c", code])
        self._sub(0.4)
        if rc != 0 and re.search(r"DLL|dll|WinError 126|WinError 1114", out):
            # the Microsoft Visual C++ runtime is missing on this PC
            self._sub(0.45, "Installing a Windows component")
            vc = os.path.join(self.dir, "cache", "vc_redist.x64.exe")
            download(C.VC_REDIST_URL, vc, self.cancel, lambda d, t: None)
            self._run([vc, "/install", "/quiet", "/norestart"])
            rc, out = self._run([self.py, "-c", code])
        for ln in out.splitlines():
            if ln.startswith("SELFTEST "):
                try:
                    self.selftest = json.loads(ln[9:])
                except Exception:
                    pass
        if self.backend == "cuda":
            if "no kernel image" in out:
                raise InstallError("Your graphics card is older than the GPU libraries that were installed. Please send "
                                   "the log file to the developer.", out)
            if rc != 0:
                raise InstallError("The GPU libraries did not start correctly. Restart your PC and run the installer "
                                   "again. If it still fails, send the log file to support.", out)
            if "CUDA True" not in out:
                raise InstallError("Your graphics card could not be used. Please update your NVIDIA driver from "
                                   "nvidia.com, restart, and run the installer again.", out)
        elif rc != 0 or not self.selftest.get("ok"):
            raise InstallError("The libraries installed, but this graphics card could not run them. Please update "
                               "your graphics driver (AMD Adrenalin 26.2.2 or newer / latest Intel Arc driver), "
                               "restart, and try again. If it still fails, send the log file (button below) to "
                               "the developer - it shows exactly what your card supports.", out)
        self._sub(0.7, "Testing the engine")
        eng = os.path.join(self.dir, "engine", "ComfyUI")
        rc, out = self._run([self.py, "-c",
                             "import sys;sys.argv=['x'];sys.path.insert(0,r'%s');import folder_paths,comfy.utils;print('OK')" % eng],
                            cwd=eng)
        if rc != 0 or "OK" not in out:
            log("engine import check failed (non-fatal): %s" % out)
        self._sub(1.0)

    def step_finish(self):
        self._begin("finish")
        exe = os.path.join(self.dir, C.APP_NAME + ".exe")
        if not os.path.isfile(exe):
            raise InstallError("The app file is missing. Please download the installer again.", exe)
        # uninstaller = this same installer, run with --uninstall
        if getattr(sys, "frozen", False):
            try:
                shutil.copy2(sys.executable, os.path.join(self.dir, "Uninstall %s.exe" % C.APP_NAME))
            except Exception as e:
                log("uninstaller copy failed: %s" % e)
        self._sub(0.3)
        make_shortcuts(self.dir, self.desktop)
        write_stats_choice(self.share_stats)
        self._sub(0.6)
        ver = package_version(self.dir)
        register_uninstall(self.dir, ver)
        shutil.rmtree(os.path.join(self.dir, "cache"), ignore_errors=True)
        with open(os.path.join(self.dir, "install.json"), "w", encoding="utf-8") as f:
            json.dump({"version": ver, "gpu": self.gpu, "backend": self.backend,
                       "experimental": bool(C.EXPERIMENTAL), "selftest": self.selftest,
                       "installed": time.strftime("%Y-%m-%d %H:%M")}, f)
        self._sub(1.0)
        self.on_progress(1.0, "")


def fetch_version_info():
    """The website's version.json as a dict, or None (also when its signature or fields are not right)."""
    try:
        t = int(time.time())
        raw = open_url(urllib.request.Request("%s?t=%d" % (C.VERSION_URL, t), headers={"User-Agent": UA}), timeout=15).read()
        sig = open_url(urllib.request.Request("%s.sig?t=%d" % (C.VERSION_URL, t), headers={"User-Agent": UA}), timeout=15).read()
        return release.check(raw, sig.decode("ascii"))
    except Exception as e:
        log("version.json: %s" % e)
        return None


def package_version(install_dir):
    try:
        with open(os.path.join(install_dir, "package.json"), encoding="utf-8") as f:
            return str(json.load(f).get("version") or C.APP_VERSION)
    except Exception:
        return C.APP_VERSION


# ---------------------------------------------------------------- in-app update (run as: setup.exe --update ...)
UPDATE_ITEMS = ["_internal", "app", os.path.join("engine", "ComfyUI"), "LICENSES", "package.json",
                C.APP_NAME + ".exe"]


def wait_for_exit(pid, timeout=40):
    """Waits until the app (process id `pid`) has closed."""
    if not pid:
        return
    if os.name == "nt":
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, int(pid))     # SYNCHRONIZE
            if h:
                ctypes.windll.kernel32.WaitForSingleObject(h, int(timeout * 1000))
                ctypes.windll.kernel32.CloseHandle(h)
        except Exception as e:
            log("wait_for_exit: %s" % e)
            time.sleep(3)
    else:
        end = time.time() + timeout
        while time.time() < end:
            try:
                os.kill(int(pid), 0)
            except OSError:
                return
            time.sleep(0.3)


def _rm(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.lexists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def apply_update(zip_path, root, pid, info, on_progress):
    """Replaces the app files in `root` with the ones from `zip_path`. Keeps the runtime, the model and the
    settings. If anything fails the old files are put back. on_progress(fraction, text)."""
    root = os.path.abspath(root)
    stage = os.path.join(root, "update_new")
    old = os.path.join(root, "update_old")
    on_progress(0.02, "Waiting for Asena Mask to close")
    wait_for_exit(pid)
    time.sleep(0.6)
    _rm(stage)
    _rm(old)
    os.makedirs(stage)
    try:
        want = (info or {}).get("sha256") or ""
        on_progress(0.05, "Checking the download")
        if not want or _sha256(zip_path).lower() != want.lower():
            raise InstallError("The downloaded update did not pass its safety check. Nothing was changed. "
                               "Please try again later.", "sha256 missing or mismatch")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            for i, n in enumerate(names):
                z.extract(n, stage)
                if i % 60 == 0:
                    on_progress(0.08 + 0.5 * i / max(len(names), 1), "Unpacking")
        if not os.path.isfile(os.path.join(stage, C.APP_NAME + ".exe")):
            raise InstallError("The update package is incomplete. Nothing was changed.", "no exe in package")
    except zipfile.BadZipFile as e:
        _rm(stage)
        raise InstallError("The update package is damaged. Nothing was changed.", str(e))
    except BaseException:
        _rm(stage)
        raise

    on_progress(0.62, "Installing the new version")
    os.makedirs(old)
    moved = []
    try:
        for item in UPDATE_ITEMS:
            src_new = os.path.join(stage, item)
            cur = os.path.join(root, item)
            if os.path.lexists(cur):
                dst = os.path.join(old, item)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.replace(cur, dst)
                moved.append(item)
            if os.path.lexists(src_new):
                os.makedirs(os.path.dirname(cur), exist_ok=True)
                os.replace(src_new, cur)
                moved.append("+" + item)
    except Exception as e:
        log("update failed, rolling back: %s" % e)
        for item in reversed(moved):                 # undo, newest step first
            try:
                if item.startswith("+"):
                    _rm(os.path.join(root, item[1:]))
                else:
                    os.replace(os.path.join(old, item), os.path.join(root, item))
            except Exception as e2:
                log("rollback %s: %s" % (item, e2))
        _rm(stage)
        _rm(old)
        raise InstallError("The update could not be installed (a file may be in use). Your old version was kept. "
                           "Close everything related to Asena Mask and try again.", str(e))

    on_progress(0.92, "Finishing up")
    ver = package_version(root)
    meta = read_install(root) or {}
    meta.update({"version": ver, "updated": time.strftime("%Y-%m-%d %H:%M")})
    try:
        with open(os.path.join(root, "install.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f)
    except Exception as e:
        log("install.json: %s" % e)
    register_uninstall(root, ver)
    _rm(stage)
    _rm(old)
    on_progress(1.0, "Done")
    return ver


# ---------------------------------------------------------------- shortcuts / registry / uninstall
def _lnk(path, target, workdir, icon):
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';"
          "$s.WorkingDirectory='%s';$s.IconLocation='%s';$s.Save()") % (
        path.replace("'", "''"), target.replace("'", "''"), workdir.replace("'", "''"), icon.replace("'", "''"))
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=60)


def write_stats_choice(share):
    """The installer page told the user about anonymous usage stats; remember their choice for the app (settings.json)."""
    try:
        d = os.path.join(os.environ.get("APPDATA") or str(Path.home()), "AsenaMask")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "settings.json")
        cur = {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                cur = json.load(f)
            if not isinstance(cur, dict):
                cur = {}
        except Exception:
            cur = {}
        cur["telemetry"] = "on" if share else "off"
        cur["tm_notice_seen"] = True
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=2)
    except Exception as e:
        log("stats choice not saved: %s" % e)


def make_shortcuts(install_dir, desktop):
    exe = os.path.join(install_dir, C.APP_NAME + ".exe")
    sm = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
    try:
        os.makedirs(sm, exist_ok=True)
        _lnk(os.path.join(sm, C.APP_NAME + ".lnk"), exe, install_dir, exe)
        if desktop:
            dt = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
            _lnk(os.path.join(dt, C.APP_NAME + ".lnk"), exe, install_dir, exe)
    except Exception as e:
        log("shortcut error: %s" % e)


UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AsenaMask"


def register_uninstall(install_dir, version=None):
    try:
        import winreg
        exe = os.path.join(install_dir, C.APP_NAME + ".exe")
        un = os.path.join(install_dir, "Uninstall %s.exe" % C.APP_NAME)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            for name, val in (("DisplayName", C.APP_NAME), ("DisplayVersion", version or C.APP_VERSION),
                              ("Publisher", C.PUBLISHER), ("InstallLocation", install_dir), ("DisplayIcon", exe),
                              ("UninstallString", '"%s" --uninstall' % un)):
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
    except Exception as e:
        log("registry error: %s" % e)


def installed_dir_from_registry():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return winreg.QueryValueEx(k, "InstallLocation")[0]
    except Exception:
        return None


def uninstall(install_dir):
    """Removes shortcuts + registry entry now; the folder is deleted by a helper after this process exits."""
    sm = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs",
                      C.APP_NAME + ".lnk")
    dt = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", C.APP_NAME + ".lnk")
    for p in (sm, dt):
        try:
            os.remove(p)
        except Exception:
            pass
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except Exception:
        pass
    if not os.path.isfile(os.path.join(install_dir, "install.json")):   # never wipe a folder we did not install
        log("uninstall: no install.json in %s, folder left in place" % install_dir)
        return
    cmd = 'ping 127.0.0.1 -n 4 > nul & rmdir /s /q "%s"' % install_dir
    subprocess.Popen(["cmd", "/c", cmd], creationflags=CREATE_NO_WINDOW | 0x00000008, close_fds=True)


def launch_app(install_dir):
    exe = os.path.join(install_dir, C.APP_NAME + ".exe")
    subprocess.Popen([exe], cwd=install_dir, creationflags=0x00000008, close_fds=True)
