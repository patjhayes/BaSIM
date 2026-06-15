#!/usr/bin/env python3
"""
Download and extract MODFLOW 6 (Windows 64-bit) into project bin/.

Usage: python scripts/download_modflow.py [version]
Default version: latest release at USGS (fallback to 6.6.0 if detection fails).

Notes: This script fetches the official USGS release zip and extracts mf6.exe
and required DLLs under bin/ so PyInstaller can bundle them.
"""
from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from pathlib import Path

try:
    import urllib.request as urlreq
    import urllib.error as urlerr
    import json as _json
except Exception:
    urlreq = None


def get_latest_version() -> str:
    # Prefer a pinned version if provided via env
    env = os.environ.get("BASIM_MF6_VERSION")
    if env:
        return env
    # Try to read from simple text in repo if present
    pin = Path(__file__).parents[1] / "scripts" / "mf6_version.txt"
    if pin.exists():
        try:
            v = pin.read_text(encoding="utf-8").strip()
            if v:
                return v
        except Exception:
            pass
    # Fallback
    return "6.6.0"


def get_asset_url(version: str | None) -> tuple[str, str]:
    """Return (version, asset_url) for Windows zip from GitHub Releases."""
    if urlreq is None:
        raise RuntimeError("urllib not available")
    base = "https://api.github.com/repos/MODFLOW-USGS/modflow6/releases"
    url = f"{base}/latest" if not version else f"{base}/tags/mf{version}"
    req = urlreq.Request(url, headers={"User-Agent": "basim-modflow-downloader"})
    with urlreq.urlopen(req) as resp:
        data = _json.loads(resp.read().decode("utf-8", "ignore"))
    tag = data.get("tag_name") or ""
    ver = tag.lstrip("mf") if tag else (version or get_latest_version())
    assets = data.get("assets") or []
    # Detect OS
    is_windows = sys.platform == "win32"
    is_mac = sys.platform == "darwin"
    
    # Prefer appropriate platform zip
    candidates = []
    for a in assets:
        name = (a.get("name") or "").lower()
        if is_windows and ("window" in name or "win" in name):
            if name.endswith('.zip'):
                candidates.append(a.get("browser_download_url"))
        elif is_mac and "mac" in name:
            if name.endswith('.zip'):
                candidates.append(a.get("browser_download_url"))
        elif not is_windows and not is_mac and "linux" in name:
            if name.endswith('.zip'):
                candidates.append(a.get("browser_download_url"))
    if not candidates and assets:
        # Fallback: any zip
        for a in assets:
            name = (a.get("name") or "").lower()
            if name.endswith('.zip'):
                candidates.append(a.get("browser_download_url"))
    if not candidates:
        raise RuntimeError("No downloadable assets found in the release")
    return ver, candidates[0]


def download_bytes(url: str) -> bytes:
    if urlreq is None:
        raise RuntimeError("urllib not available to download MODFLOW 6")
    with urlreq.urlopen(url) as resp:
        return resp.read()


def main():
    ver_arg = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        ver, url = get_asset_url(ver_arg)
    except Exception as e:
        print(f"Failed to resolve release via API: {e}")
        # Fallback to pinned URL pattern
        ver = ver_arg or get_latest_version()
        tag = f"mf{ver}"
        if sys.platform == "win32":
            os_slug = "win64"
        elif sys.platform == "darwin":
            os_slug = "mac"
        else:
            os_slug = "linux"
        url = f"https://github.com/MODFLOW-USGS/modflow6/releases/download/{tag}/{tag}_{os_slug}.zip"
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "bin"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading MODFLOW 6 {ver} from {url} ...")
    try:
        data = download_bytes(url)
    except Exception as e:
        print(f"Failed to download: {e}")
        sys.exit(1)
    print("Extracting to bin/ ...")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            extracted = []
            for m in z.infolist():
                name = Path(m.filename).name.lower()
                # On Windows look for .exe and .dll, on Linux/Mac look for binary with no extension or .so/.dylib
                if name == 'mf6.exe' or name == 'mf6' or name.endswith('.dll') or name.endswith('.so') or name.endswith('.dylib'):
                    target = out_dir / Path(m.filename).name
                    with z.open(m) as src, open(target, 'wb') as dst:
                        dst.write(src.read())
                    extracted.append(target.name)
            if not extracted:
                # Fallback, extract all and try to locate mf6.exe afterwards
                z.extractall(out_dir)
            else:
                for n in extracted:
                    print(f"  + {n}")
    except Exception as e:
        print(f"Extraction failed: {e}")
        sys.exit(1)
    # Sanity check and execution permissions
    mf6 = out_dir / ("mf6.exe" if sys.platform == "win32" else "mf6")
    if not mf6.exists():
        print(f"{mf6.name} not found after extraction; check the archive layout.")
        sys.exit(2)
        
    if sys.platform != "win32":
        try:
            mf6.chmod(mf6.stat().st_mode | 0o111)
            print(f"Made {mf6.name} executable.")
        except Exception as e:
            print(f"Warning: could not set executable bit on {mf6.name}: {e}")
            
    print(f"Done. mf6 at {mf6}")


if __name__ == "__main__":
    main()
