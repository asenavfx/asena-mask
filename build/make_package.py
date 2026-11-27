"""Builds release/AsenaMask-app.zip: the app window (PyInstaller output), the worker sources and the engine code.

Usage:  python build/make_package.py [--comfy-source DIR] [--comfy-version vX.Y.Z]
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(BUILD, "dist", "Asena Mask")
STAGE = os.path.join(BUILD, "stage")
RELEASE = os.path.join(ROOT, "release")
FILES_URL = "https://asenatools.com/files/"      # where you upload the zip and version.json
DEFAULT_COMFY = [r"C:\path\to\ComfyUI"]
SKIP_TOP = {"extra_model_paths.yaml", "extra_model_paths.yaml.example", "models", "custom_nodes", "input", "output", "temp", "user", "venv", ".venv", ".git", ".github",
            "tests", "tests-unit", "__pycache__", "script_examples", ".ci", "blueprints", "node_modules"}


def copy_engine(src, dst):
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        if name in SKIP_TOP or name.endswith((".pyc", ".bat")) or name.startswith("."):
            continue
        a, b = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isdir(a):
            shutil.copytree(a, b, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "tests-unit"))
        else:
            shutil.copy2(a, b)
    for d in ("custom_nodes", "input", "output", "temp", os.path.join("models", "checkpoints")):
        os.makedirs(os.path.join(dst, d), exist_ok=True)


def detect_version(src):
    try:
        t = open(os.path.join(src, "comfyui_version.py"), encoding="utf-8").read()
        return "v" + re.search(r'__version__\s*=\s*"([^"]+)"', t).group(1)
    except Exception:
        return None


def app_version():
    t = open(os.path.join(ROOT, "asenamask", "__init__.py"), encoding="utf-8").read()
    return re.search(r'APP_VERSION\s*=\s*"([^"]+)"', t).group(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy-source", default="")
    ap.add_argument("--comfy-version", default="")
    a = ap.parse_args()

    if not os.path.isfile(os.path.join(DIST, "Asena Mask.exe")):
        sys.exit("Build the app first (build_all.ps1 does this).")
    shutil.rmtree(STAGE, ignore_errors=True)
    os.makedirs(STAGE)

    # 1) the app window
    shutil.copytree(DIST, STAGE, dirs_exist_ok=True)

    # 2) worker sources (no UI, no artwork)
    app = os.path.join(STAGE, "app")
    os.makedirs(app)
    shutil.copy2(os.path.join(ROOT, "main.py"), os.path.join(app, "main.py"))
    shutil.copytree(os.path.join(ROOT, "asenamask"), os.path.join(app, "asenamask"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "ui", "assets"))

    # 3) engine code
    src = a.comfy_source or next((c for c in DEFAULT_COMFY if os.path.isfile(os.path.join(c, "main.py"))), "")
    eng = os.path.join(STAGE, "engine", "ComfyUI")
    if src:
        print("Engine code from your local ComfyUI:", src, "(%s)" % detect_version(src))
        copy_engine(src, eng)
        ver = detect_version(src)
    else:
        ver = a.comfy_version or "v0.38.1"
        url = "https://github.com/comfyanonymous/ComfyUI/archive/refs/tags/%s.zip" % ver
        print("Downloading engine code", url)
        data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "asena-build"})).read()
        tmp = os.path.join(BUILD, "comfy_src")
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(tmp)
        inner = os.path.join(tmp, os.listdir(tmp)[0])
        copy_engine(inner, eng)
        shutil.rmtree(tmp, ignore_errors=True)
    print("Engine version:", ver)

    # 4) licences
    lic = os.path.join(STAGE, "LICENSES")
    os.makedirs(lic, exist_ok=True)
    shutil.copy2(os.path.join(BUILD, "THIRD_PARTY_NOTICES.txt"), lic)
    if os.path.isfile(os.path.join(eng, "LICENSE")):
        shutil.copy2(os.path.join(eng, "LICENSE"), os.path.join(lic, "ComfyUI-LICENSE-GPL-3.0.txt"))

    # 5) version stamp inside the package, then the zip (the file name carries the version, so nothing is ever stale)
    version = app_version()
    notes_file = os.path.join(ROOT, "RELEASE_NOTES.txt")
    notes = open(notes_file, encoding="utf-8").read().strip() if os.path.isfile(notes_file) else ""
    json.dump({"version": version, "engine": ver, "notes": notes}, open(os.path.join(STAGE, "package.json"), "w",
              encoding="utf-8"))
    os.makedirs(RELEASE, exist_ok=True)
    zip_name = "AsenaMask-app-%s.zip" % version
    for old in os.listdir(RELEASE):
        if old.startswith("AsenaMask-app") and old.endswith(".zip"):
            os.remove(os.path.join(RELEASE, old))
    out = os.path.join(RELEASE, zip_name)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, _, files in os.walk(STAGE):
            for f in files:
                p = os.path.join(base, f)
                z.write(p, os.path.relpath(p, STAGE).replace("\\", "/"))
    h = hashlib.sha256(open(out, "rb").read()).hexdigest()
    print("\nPackage:", out, "(%.0f MB)" % (os.path.getsize(out) / 1e6))
    print("SHA-256:", h)
    open(os.path.join(RELEASE, "AsenaMask-app.sha256.txt"), "w").write(h + "\n")

    # 6) version.json (what the app and the installer read) + upload instructions
    pip_file = os.path.join(ROOT, "EXTRA_PIP.txt")
    pip = [x.strip() for x in open(pip_file, encoding="utf-8")] if os.path.isfile(pip_file) else []
    pip = [x for x in pip if x and not x.startswith("#")]
    meta = {"version": version, "url": FILES_URL + zip_name, "sha256": h, "size": os.path.getsize(out),
            "notes": notes, "pip": pip}
    json.dump(meta, open(os.path.join(RELEASE, "version.json"), "w", encoding="utf-8"), indent=2)
    open(os.path.join(RELEASE, "UPLOAD-THESE.txt"), "w", encoding="utf-8").write(
        "Upload these two files to public_html/files on Hostinger (File Manager):\n\n"
        "  1. %s\n  2. version.json\n\n"
        "Upload the zip FIRST, version.json LAST - the moment version.json is replaced, every installed copy\n"
        "of Asena Mask starts offering the update. (Old zips can be deleted a few days later.)\n"
        "Check: open %sversion.json in a browser and make sure it shows version %s.\n" % (
            zip_name, FILES_URL, version))
    print("version.json written for version", version)


if __name__ == "__main__":
    main()
