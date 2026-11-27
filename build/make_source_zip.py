"""Makes release/AsenaMask-source.zip: the clean public source (what the website's "Download the source" gives).
Leaves out logs, caches, build output, your personal build/hosting notes, and replaces your own folder paths."""
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "release", "AsenaMask-source.zip")
SKIP_DIRS = {"__pycache__", "venv", ".venv", "release", "dist", "work", "work_setup", "stage", "comfy_src", ".git"}
SKIP_FILES = {"AsenaMaskSetup.log", "flavor.py", "BUILD_AND_RELEASE.txt", "RELEASE_NOTES.txt", "EXTRA_PIP.txt",
              "version.json", "UPLOAD-THESE.txt"}
SKIP_REL = ("asenamask/assets/",)   # your own sounds, logos and animation stay private
SKIP_EXT = (".pyc", ".log", ".zip", ".exe", ".spec")
TEXT_EXT = (".py", ".txt", ".ps1", ".md")
PLACEHOLDER = r"C:\path\to\ComfyUI"

BUILDING = """BUILDING ASENA MASK FROM SOURCE
================================
Run from source (needs a Python that has PyTorch + ComfyUI's requirements):
    python -m pip install PySide6-Essentials av pillow numpy imageio-ffmpeg
    python main.py
The app looks for ComfyUI (with the SAM 3 nodes) via asenamask/paths.py, or inside the installed app folder.
The AI model (sam3.1_multiplex_fp16.safetensors) goes into models/checkpoints next to it.

Build the installer on Windows:
    powershell -ExecutionPolicy Bypass -File build\\build_all.ps1 -ComfySource "C:\\path\\to\\ComfyUI"
The artwork, sounds and logo animation (asenamask/assets) are not part of the source release (all rights reserved).
The app runs without them (silent, drawn logo). To build the exe, put your own icon.ico and logo.png in asenamask/assets.
The app is licensed under the licences listed in build/THIRD_PARTY_NOTICES.txt (ComfyUI is GPL-3.0).
"""


def clean(text):
    text = re.sub(r"[A-Za-z]:\\[^\s\"'`]*Comfy[^\s\"'`]*", lambda m: PLACEHOLDER, text)
    text = re.sub(r"[A-Za-z]:\\AsenaMask", lambda m: r"C:\AsenaMask", text)
    return text


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    n = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f in SKIP_FILES or f.lower().endswith(SKIP_EXT):
                    continue
                p = os.path.join(base, f)
                rel = os.path.relpath(p, ROOT).replace("\\", "/")
                if rel.startswith(SKIP_REL):
                    continue
                if f.lower().endswith(TEXT_EXT) and f != "make_source_zip.py":
                    data = clean(open(p, encoding="utf-8", errors="replace").read()).encode("utf-8")
                    z.writestr(rel, data)
                else:
                    z.write(p, rel)
                n += 1
        z.writestr("BUILDING.txt", BUILDING)
    print("Source zip:", OUT, "(%d files)" % (n + 1))


if __name__ == "__main__":
    main()
