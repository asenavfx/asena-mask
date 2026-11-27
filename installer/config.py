"""Settings for the Asena Mask web installer. Edit this file, then rebuild the installer."""

APP_NAME = "Asena Mask"
APP_VERSION = "1.0.0"
PUBLISHER = "Asenavfx"

# Where the small app package (built by build\\build_app.ps1) is hosted, e.g. a GitHub release asset.
# If a file called AsenaMask-app.zip sits next to the installer, that file is used instead (handy for testing).
PACKAGE_URL = ""            # fallback only. Normally the installer reads VERSION_URL (below) to find the newest package.   e.g. "https://github.com/YOU/asena-mask/releases/download/v1.0.0/AsenaMask-app.zip"
PACKAGE_SHA256 = ""         # optional: hex SHA-256 of the zip (build_app.ps1 prints it)

# The website's version.json (the same file the app checks for updates). It names the newest app package.
VERSION_URL = "https://asenatools.com/files/version.json"

# "Experimental" build for AMD Radeon / Intel Arc. build_all.ps1 -Experimental writes installer\flavor.py.
try:
    from flavor import EXPERIMENTAL
except ImportError:
    try:
        from .flavor import EXPERIMENTAL
    except ImportError:
        EXPERIMENTAL = False

# Private Python runtime that is installed next to the app (never touches any Python on the PC).
PYTHON_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
PYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
PYTHON_TAG = "python312"
# get-pip.py pinned to one commit of github.com/pypa/get-pip (bootstrap.pypa.io/get-pip.py changes with every pip release,
# so a hash of it would break installs). To move on: pick a newer commit, download it, put its SHA-256 here.
GET_PIP_URL = "https://raw.githubusercontent.com/pypa/get-pip/8c427468071b5d15717839ffd76c53a96df8b703/public/get-pip.py"
GET_PIP_SHA256 = "356e0d0de21cdc348c3394084d90939b85e4246c4d14c76aee6ca4f46646ea98"

# GPU libraries. cu128 works with every NVIDIA card from GTX 900 up to RTX 50 (needs driver 570+).
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
# GTX 900 / GTX 10-series (Maxwell, Pascal: compute capability below 7.0) have no kernels in the cu128 builds, so they get the
# CUDA 12.6 build of PyTorch 2.8, which still ships them.
TORCH_INDEX_LEGACY = "https://download.pytorch.org/whl/cu126"
TORCH_PACKAGES_LEGACY = ["torch==2.8.0", "torchvision==0.23.0", "torchaudio==2.8.0"]
LEGACY_BELOW_CC = 7.0
TORCH_PACKAGES = ["torch", "torchvision", "torchaudio"]
MIN_DRIVER = 570.0

# Experimental build only. Intel Arc: PyTorch's own XPU wheels. AMD Radeon: AMD's ROCm-for-Windows wheels
# (Python 3.12, RX 7000 / 9000 series, Adrenalin 26.2.2 or newer).
XPU_INDEX = "https://download.pytorch.org/whl/xpu"
ROCM_BASE = "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/"
ROCM_SDK = ["rocm_sdk_core-7.2.1-py3-none-win_amd64.whl", "rocm_sdk_devel-7.2.1-py3-none-win_amd64.whl",
            "rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl", "rocm-7.2.1.tar.gz"]
ROCM_TORCH = ["torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
              "torchaudio-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
              "torchvision-0.24.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl"]
EXP_TORCH_EXPECTED_BYTES = 4_800_000_000
TORCH_EXPECTED_BYTES = 3_600_000_000     # only used to draw a smooth progress bar
DEPS_EXPECTED_BYTES = 450_000_000

# The AI model (downloaded straight from the official Hugging Face repository).
MODEL_URL = "https://huggingface.co/Comfy-Org/sam3.1/resolve/main/checkpoints/sam3.1_multiplex_fp16.safetensors"
MODEL_NAME = "sam3.1_multiplex_fp16.safetensors"
MODEL_MIN_BYTES = 1_500_000_000

VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
MIN_FREE_GB = 12

# Friendly step names shown in the installer: (key, title, weight in the overall bar)
STEPS = [
    ("check", "Checking your PC", 2),
    ("app", "Getting the app", 5),
    ("python", "Preparing the engine", 4),
    ("torch", "Installing GPU libraries", 33),
    ("deps", "Installing engine components", 9),
    ("model", "Downloading AI model", 38),
    ("verify", "Final checks", 6),
    ("finish", "Creating shortcuts", 3),
]
