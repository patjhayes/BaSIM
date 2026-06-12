"""
Utilities to locate the MODFLOW 6 executable (mf6).

Search order:
- BASIM_MF6 / BASIM_MF6 environment variable (explicit override)
- Adjacent bin/mf6.exe (dev checkout)
- Frozen app data dir (PyInstaller sys._MEIPASS)/bin/mf6.exe
- Frozen app data dir root (sys._MEIPASS/mf6.exe)  [added for onefile builds packing binary to '.']
- User override in %USERPROFILE%/.basim/prefs.json under key "mf6_path"

Returns a string path or raises FileNotFoundError with a helpful message.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import json
import shutil


def _is_exe(p: Path) -> bool:
    """Return True if path looks like an executable file on this OS.

    On Windows, os.access(X_OK) is unreliable for PE executables. Treat common
    executable extensions (from PATHEXT or a safe default) as runnable if the
    file exists. On POSIX, require the execute bit.
    """
    try:
        if not p.is_file():
            return False
        if os.name == "nt":
            # Determine executable extensions on Windows
            pathext = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").lower().split(";")
            return p.suffix.lower() in pathext or p.name.lower().endswith(tuple(pathext))
        # POSIX: require execute permission
        return os.access(str(p), os.X_OK)
    except Exception:
        return p.is_file()


def _get_meipass_dir() -> Path | None:
    # When running under PyInstaller --onefile, data files are unpacked to sys._MEIPASS
    try:
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    except Exception:
        return None
    return None


def _read_user_override() -> Path | None:
    try:
        # Support multiple legacy/new locations for prefs after rebrand
        candidates = [
            Path.home() / ".basim" / "prefs.json",
            Path.home() / ".BaSIM" / "prefs.json",
            Path.home() / ".basim" / "prefs.json",
        ]
        for p in candidates:
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    mf6 = data.get("mf6_path")
                    if mf6:
                        cand = Path(mf6)
                        if _is_exe(cand):
                            return cand
                except Exception:
                    continue
    except Exception:
        return None
    return None


def find_exe(exe_name="mf6") -> str:
    exe_base = exe_name.replace(".exe", "")
    exe_file = f"{exe_base}.exe" if os.name == "nt" else exe_base
    
    # 1) Env var override (new + legacy)
    for key in (f"BASIM_{exe_base.upper()}", f"BASIM_{exe_base.upper()}"):
        env = os.environ.get(key)
        if env:
            cand = Path(env)
            if _is_exe(cand):
                return str(cand)

    # 2) Dev checkout bin/ (project root/bin)
    try:
        here = Path(__file__).resolve()
        proj_root = here.parents[2]
        dev = proj_root / "bin" / exe_file
        if _is_exe(dev):
            return str(dev)
            
        # Also check one level higher for BaSIM v2.0/bin
        higher_root = here.parents[3]
        higher_dev = higher_root / "bin" / exe_file
        if _is_exe(higher_dev):
            return str(higher_dev)
    except Exception:
        pass

    # 3) PyInstaller data dir (bin/ then root for onefile)
    meipass = _get_meipass_dir()
    if meipass:
        p_bin = meipass / "bin" / exe_file
        if _is_exe(p_bin):
            return str(p_bin)
        p_root = meipass / exe_file
        if _is_exe(p_root):
            return str(p_root)

    # 4) User override in prefs.json
    try:
        candidates = [
            Path.home() / ".basim" / "prefs.json",
            Path.home() / ".BaSIM" / "prefs.json",
            Path.home() / ".basim" / "prefs.json",
        ]
        for p in candidates:
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    pref_path = data.get(f"{exe_base}_path")
                    if pref_path:
                        cand = Path(pref_path)
                        if _is_exe(cand):
                            return str(cand)
                except Exception:
                    continue
    except Exception:
        pass

    # 5) System PATH
    try:
        which = shutil.which(exe_base)
        if which:
            return which
    except Exception:
        pass

    # Not found
    raise FileNotFoundError(
        f"Executable '{exe_file}' not found. Set BASIM_{exe_base.upper()} to the path, "
        f"or place {exe_file} under a 'bin' folder next to the app, or specify '{exe_base}_path' in %USERPROFILE%/.basim/prefs.json, or install it so it is on PATH."
    )

def find_mf6_exe() -> str:
    return find_exe("mf6")

def find_mfnwt_exe() -> str:
    return find_exe("mfnwt")

def find_mfusg_exe() -> str:
    return find_exe("mfusg")

def find_gridgen_exe() -> str:
    return find_exe("gridgen")

__all__ = ["find_mf6_exe", "find_mfnwt_exe", "find_mfusg_exe", "find_gridgen_exe", "find_exe"]
