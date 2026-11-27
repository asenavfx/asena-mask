"""PC info for the Information tab (GPU via nvidia-smi, CPU, RAM, OS)."""
import ctypes
import os
import platform
import subprocess


def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=6,
                             creationflags=0x08000000 if os.name == "nt" else 0)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def gpu_names():
    """Names of all graphics adapters (Windows), e.g. for AMD / Intel cards that nvidia-smi cannot see."""
    if os.name != "nt":
        return []
    out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                "(Get-CimInstance Win32_VideoController).Name"])
    return [n.strip() for n in out.splitlines() if n.strip()]


def gpu_info():
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"])
    if not out:
        names = gpu_names()
        return {"name": names[0], "vram_gb": 0, "driver": ""} if names else None
    first = out.splitlines()[0]
    parts = [p.strip() for p in first.split(",")]
    try:
        return {"name": parts[0], "vram_gb": round(float(parts[1]) / 1024.0, 1), "driver": parts[2]}
    except Exception:
        return {"name": parts[0], "vram_gb": 0, "driver": ""}


def cpu_name():
    if os.name == "nt":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except Exception:
            pass
    return platform.processor() or "Unknown"


def ram_gb():
    if os.name == "nt":
        try:
            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.ullTotalPhys / 1024 ** 3)
        except Exception:
            pass
    return 0


def collect():
    g = gpu_info()
    return {"gpu": g, "cpu": cpu_name(), "ram": ram_gb(), "os": "%s %s" % (platform.system(), platform.release())}


def report(settings=None):
    """A plain-text block with everything needed to understand a bug report (no personal data)."""
    import json
    from . import APP_NAME, BUILD_LABEL, paths
    d = collect()
    g = d.get("gpu") or {}
    lines = ["%s  %s" % (APP_NAME, BUILD_LABEL),
             "GPU: %s  (VRAM %s GB, driver %s)" % (g.get("name", "none"), g.get("vram_gb", "?"), g.get("driver", "?")),
             "CPU: %s" % d.get("cpu"), "RAM: %s GB" % d.get("ram"), "System: %s" % d.get("os")]
    root = paths.install_root()
    if root:
        try:
            info = json.loads((root / "install.json").read_text(encoding="utf-8"))
            lines.append("Install: version %s, backend %s%s" % (info.get("version"), info.get("backend", "cuda"),
                                                                 ", EXPERIMENTAL" if info.get("experimental") else ""))
            st = info.get("selftest") or {}
            if st:
                lines.append("Self-test: " + ", ".join("%s=%s" % (k, v) for k, v in st.items()))
        except Exception:
            lines.append("Install: details unreadable")
    else:
        lines.append("Running from source")
    if settings is not None:
        lines.append("Engine folder: %s" % settings.comfy_dir())
        lines.append("GPU load: %s   idle unload: %s min" % (settings.get("gpu_load"), settings.get("idle_minutes")))
    return "\n".join(lines)
