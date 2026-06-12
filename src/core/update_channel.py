"""Phase 9 – Update Channel

Provides a richer update workflow than the earlier lightweight GitHub
release poll. Responsibilities:

1. Fetch a JSON manifest from a configurable URL (env BASIM_MANIFEST_URL)
   Default (placeholder) is https://example.com/basim/manifest.json
   Manifest schema (minimum):
       {
         "version": "1.0.1",
         "release_notes": "Optional multi-line text.",
         "url_windows_portable": "https://.../BaSIM_v1.0.1_Portable.zip",
         "sha256_windows_portable": "<HEX SHA256>",
         "url_windows_installer": "https://.../BaSIM_v1.0.1_Setup.exe",   # optional
         "sha256_windows_installer": "<HEX SHA256>"                        # optional
       }

2. Compare semantic versions (non‑strict); if newer, expose details to caller.
3. Download chosen artifact with progress callback (chunked, no external deps).
4. Verify SHA256 digest against manifest.
5. If a .zip portable build: extract to user updates directory (Documents/BaSIM/updates/BaSIM_<version>)
   without overwriting the currently running directory. User can then migrate.
6. If an installer (.exe / .msi): after verification, launch it (non-blocking) and return.

Design notes:
 - Never raises outwardly (wrap all top-level boundaries); return status dict.
 - Avoid heavy dependencies (no 'packaging'); provide a light version compare.
 - Safe for use inside PyInstaller onedir/onefile contexts.
 - Hash verification mandatory before any extraction/launch.

Limitations / Future Enhancements:
 - Delta patching, in-place self‑update of onedir not attempted (complex on Windows while running).
 - Signature verification (Authenticode) out of scope; rely on future code signing integration.
 - Streaming progress is coarse (bytes downloaded / content-length if provided).
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import hashlib
import zipfile
from pathlib import Path
from typing import Callable, Optional, Dict, Any

MANIFEST_ENV = "BASIM_MANIFEST_URL"
DEFAULT_MANIFEST_URL = "https://example.com/basim/manifest.json"  # Placeholder; override in production.

ProgressCallback = Callable[[int, Optional[int]], None]


def _user_updates_dir() -> Path:
    docs = Path.home() / "Documents"
    base = docs / "BaSIM" / "updates"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        # fallback hidden folder
        base = Path.home() / ".basim" / "updates"
        base.mkdir(parents=True, exist_ok=True)
    return base


def _fetch_manifest(url: str, timeout: float = 6.0) -> Optional[dict]:
    try:
        # Support file:// or plain path for offline testing
        if url.startswith("file://"):
            p = Path(url.replace("file://", ""))
            return json.loads(p.read_text(encoding="utf-8"))
        if os.path.isfile(url):
            return json.loads(Path(url).read_text(encoding="utf-8"))
        req = urllib.request.Request(url, headers={"User-Agent": "basim-updater"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = resp.read().decode("utf-8", errors="ignore")
        return json.loads(data)
    except Exception:
        return None


def _parse_parts(v: str):
    parts = []
    for p in (v or "").strip().split('.'):
        if p == '':
            continue
        try:
            parts.append(int(p))
        except ValueError:
            # Strip non-digit suffix (e.g., 1b -> 1) for ordering; fallback to 0
            num = ''
            for ch in p:
                if ch.isdigit():
                    num += ch
                else:
                    break
            parts.append(int(num) if num else 0)
    return parts or [0]


def is_newer(remote: str, current: str) -> bool:
    try:
        r = _parse_parts(remote)
        c = _parse_parts(current)
        # Compare lexicographically with length normalization
        L = max(len(r), len(c))
        r += [0] * (L - len(r))
        c += [0] * (L - len(c))
        return r > c
    except Exception:
        return False


def check_manifest(current_version: str) -> Dict[str, Any]:
    """Fetch manifest and determine update availability.

    Returns a dict with keys:
        ok: bool (manifest fetched)
        newer: bool (remote version > current)
        manifest: dict | None
        error: str | None
    """
    url = os.environ.get(MANIFEST_ENV, DEFAULT_MANIFEST_URL)
    manifest = _fetch_manifest(url)
    if not manifest:
        return {"ok": False, "newer": False, "manifest": None, "error": "Manifest fetch failed"}
    remote_v = str(manifest.get("version") or "").strip()
    if not remote_v:
        return {"ok": False, "newer": False, "manifest": manifest, "error": "Manifest missing version"}
    newer = is_newer(remote_v, current_version)
    return {"ok": True, "newer": newer, "manifest": manifest, "error": None}


def _download(url: str, dest: Path, progress: Optional[ProgressCallback] = None, timeout: float = 30.0) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "basim-updater"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = None
            try:
                total = int(resp.headers.get("Content-Length"))
            except Exception:
                total = None
            chunk = 64 * 1024
            downloaded = 0
            with open(dest, "wb") as fh:
                while True:
                    data = resp.read(chunk)
                    if not data:
                        break
                    fh.write(data)
                    downloaded += len(data)
                    if progress:
                        try:
                            progress(downloaded, total)
                        except Exception:
                            pass
        if progress:
            try:
                progress(downloaded, total)
            except Exception:
                pass
        return dest.exists() and dest.stat().st_size > 0
    except Exception:
        return False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(128 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def verify_hash(path: Path, expected_hex: str) -> bool:
    if not expected_hex:
        return False
    actual = _sha256(path).lower()
    return actual == expected_hex.lower().strip()


def apply_update(manifest: dict, choice: str = "portable") -> Dict[str, Any]:
    """Download and stage the selected artifact.

    Parameters:
        manifest: The manifest dict.
        choice: "portable" | "installer" (preferred artifact kind).

    Returns status dict:
        ok: bool
        staged_dir: Path | None  (for portable zips)
        downloaded_file: Path | None
        launched_installer: bool
        error: str | None
        progress_log: list[str]  (chronological human messages)
    """
    log = []
    def _log(msg: str):
        log.append(msg)

    try:
        version = str(manifest.get("version") or "").strip()
        if not version:
            return {"ok": False, "error": "Manifest missing version", "staged_dir": None, "downloaded_file": None, "launched_installer": False, "progress_log": log}

        updates_dir = _user_updates_dir()
        updates_dir.mkdir(parents=True, exist_ok=True)

        # Decide artifact based on choice with graceful fallback
        if choice == "installer":
            url = manifest.get("url_windows_installer") or manifest.get("url_windows_portable")
            expected = manifest.get("sha256_windows_installer") or manifest.get("sha256_windows_portable")
        else:
            url = manifest.get("url_windows_portable") or manifest.get("url_windows_installer")
            expected = manifest.get("sha256_windows_portable") or manifest.get("sha256_windows_installer")
        if not url or not expected:
            return {"ok": False, "error": "Manifest missing URL or SHA256 for chosen artifact", "staged_dir": None, "downloaded_file": None, "launched_installer": False, "progress_log": log}

        filename = os.path.basename(url.split('?')[0]) or f"BaSIM_{version}.bin"
        dest_file = updates_dir / filename
        _log(f"Downloading {filename}...")
        prog_state = {"last_pct": -1}

        def _cb(done: int, total: Optional[int]):
            if total and total > 0:
                pct = int(done * 100 / total)
                if pct != prog_state["last_pct"]:
                    prog_state["last_pct"] = pct
                    _log(f"Downloaded {pct}%")
            else:
                if done and done % (512*1024) < 65536:  # every ~512KB
                    _log(f"Downloaded {done//1024} KiB")

        ok = _download(url, dest_file, progress=_cb)
        if not ok:
            return {"ok": False, "error": "Download failed", "staged_dir": None, "downloaded_file": dest_file if dest_file.exists() else None, "launched_installer": False, "progress_log": log}
        _log("Download complete. Verifying hash...")
        if not verify_hash(dest_file, expected):
            return {"ok": False, "error": "SHA256 mismatch – file may be corrupted.", "staged_dir": None, "downloaded_file": dest_file, "launched_installer": False, "progress_log": log}
        _log("SHA256 verified.")

        staged_dir = None
        launched = False
        if dest_file.suffix.lower() == ".zip":
            # Extract to staging directory
            staged_dir = updates_dir / f"BaSIM_{version}"
            if staged_dir.exists():
                try:
                    shutil.rmtree(staged_dir)
                except Exception:
                    pass
            try:
                with zipfile.ZipFile(dest_file, 'r') as zf:
                    zf.extractall(staged_dir)
                _log(f"Extracted to {staged_dir}")
                _log("You can close the running application and launch the new version from the staging folder.")
            except Exception as e:
                return {"ok": False, "error": f"Extraction failed: {e}", "staged_dir": None, "downloaded_file": dest_file, "launched_installer": False, "progress_log": log}
        elif dest_file.suffix.lower() in (".exe", ".msi"):
            # Attempt to launch installer (non-blocking)
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(dest_file))  # type: ignore[attr-defined]
                    launched = True
                    _log("Installer launched. Follow the on-screen instructions.")
                else:
                    _log("Downloaded installer – manual launch required on this platform.")
            except Exception as e:
                _log(f"Could not launch installer automatically: {e}")
        else:
            _log("Downloaded artifact left in updates directory (unknown type).")

        return {"ok": True, "error": None, "staged_dir": staged_dir, "downloaded_file": dest_file, "launched_installer": launched, "progress_log": log}
    except Exception as e:
        return {"ok": False, "error": str(e), "staged_dir": None, "downloaded_file": None, "launched_installer": False, "progress_log": log}


__all__ = [
    "check_manifest",
    "apply_update",
    "is_newer",
    "verify_hash",
    "check_manifest_cached",
]


# --- Cached variant for silent background polling (avoids hitting server every launch) ---
def check_manifest_cached(current_version: str, *, max_age_hours: int = 12) -> Dict[str, Any]:
    """Cached wrapper around check_manifest.

    Cache file stored under the updates directory as manifest_cache.json with keys:
        { "fetched_ts": epoch_seconds, "manifest": {..}, "ok": bool }

    Returns the same shape as check_manifest plus:
        from_cache: bool
    """
    import time, json
    cache_path = _user_updates_dir() / "manifest_cache.json"
    now = time.time()
    # Attempt to use cache
    try:
        if cache_path.exists():
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            fetched_ts = float(data.get("fetched_ts", 0))
            if (now - fetched_ts) < max_age_hours * 3600:
                manifest = data.get("manifest")
                if manifest:
                    status = check_manifest(current_version)  # Re-run version comparison on cached manifest
                    # Override manifest & ok fields with cached values but keep computed newer
                    status.update({
                        "manifest": manifest,
                        "ok": bool(data.get("ok")),
                        "from_cache": True,
                        "error": data.get("error"),
                    })
                    return status
    except Exception:
        pass
    # Fresh fetch
    status = check_manifest(current_version)
    try:
        to_store = {
            "fetched_ts": now,
            "manifest": status.get("manifest"),
            "ok": status.get("ok"),
            "error": status.get("error"),
        }
        cache_path.write_text(json.dumps(to_store, indent=2), encoding="utf-8")
    except Exception:
        pass
    status["from_cache"] = False
    return status
