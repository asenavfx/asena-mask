"""Checks a downloaded version.json before anything in it is trusted: Ed25519 signature (version.json.sig, made by
tools/sign_release.py) over the exact bytes, then the fields the updater and installer rely on."""
import base64
import json
import re
from urllib.parse import urlparse

from . import RELEASE_PUBLIC_KEY, ed25519


def check(raw, sig_text):
    """version.json bytes + the text of version.json.sig -> dict. Raises ValueError if anything is off."""
    try:
        sig = base64.b64decode(sig_text.strip(), validate=True)
    except Exception:
        raise ValueError("unreadable signature")
    if not ed25519.verify(bytes.fromhex(RELEASE_PUBLIC_KEY), raw, sig):
        raise ValueError("bad signature")
    info = json.loads(raw.decode("utf-8"))
    if not isinstance(info, dict):
        raise ValueError("not an object")
    if not re.fullmatch(r"\d+(\.\d+){0,3}", str(info.get("version", ""))):
        raise ValueError("bad version")
    if urlparse(str(info.get("url", ""))).scheme != "https":
        raise ValueError("url is not https")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(info.get("sha256", ""))):
        raise ValueError("missing sha256")
    info.pop("pip", None)          # no longer supported: updates never install extra packages
    return info
