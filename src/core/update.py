"""Update checking utilities (Phase 6).

Features:
 - Cached update check (default 12h) hitting GitHub Releases or override URL.
 - Safe, never raises; returns tuple.
 - Environment overrides:
     BASIM_DISABLE_UPDATE_CHECK=1 -> skip
     BASIM_RELEASES_URL=https://custom/api/latest -> alternate endpoint
     BASIM_UPDATE_CACHE_HOURS=6 -> adjust cache window
 - Caches state in user config directory (Documents/BaSIM/update_state.json)
"""
from __future__ import annotations

from dataclasses import dataclass
import json, os, time, urllib.request
from pathlib import Path
from typing import Optional, Tuple

DEFAULT_CACHE_HOURS = 12
DEFAULT_RELEASES_URL = "https://api.github.com/repos/basim/basim/releases/latest"


def _user_config_dir() -> Path:
    # Reuse logic pattern from launcher (avoid import cycle)
    docs = Path.home() / "Documents"
    base = docs / "BaSIM"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        base = Path.home() / ".BaSIM"
        base.mkdir(parents=True, exist_ok=True)
    return base


def _state_path() -> Path:
    return _user_config_dir() / "update_state.json"


def _load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_state(state: dict):
    try:
        with _state_path().open("w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
    except Exception:
        pass


def _now() -> float:
    return time.time()


def _should_check(last_ts: Optional[float], cache_hours: int) -> bool:
    if last_ts is None:
        return True
    return (_now() - last_ts) >= cache_hours * 3600


def _fetch_latest(url: str, timeout_sec: float = 4.0) -> Optional[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "basim-updater"})
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        if resp.status != 200:
            return None
        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    tag = str(data.get("tag_name") or "").lstrip("v").strip()
    return tag or None


def check_for_updates_cached(current_version: str, *, timeout_sec: float = 4.0) -> Tuple[bool, Optional[str], bool]:
    """Return (has_update, latest_version, skipped_due_to_cache).

    Never raises. Respects environment opt-outs.
    """
    if os.environ.get("BASIM_DISABLE_UPDATE_CHECK") == "1":
        return False, None, True

    url = os.environ.get("BASIM_RELEASES_URL", DEFAULT_RELEASES_URL)
    try:
        cache_hours = int(os.environ.get("BASIM_UPDATE_CACHE_HOURS", str(DEFAULT_CACHE_HOURS)))
    except Exception:
        cache_hours = DEFAULT_CACHE_HOURS

    state = _load_state()
    last_ts = state.get("last_check_ts")
    last_latest = state.get("last_latest")
    if not _should_check(last_ts, cache_hours):
        # Evaluate based on cached result if any
        if last_latest and last_latest > current_version:
            return True, last_latest, True
        return False, last_latest, True

    try:
        latest = _fetch_latest(url, timeout_sec=timeout_sec)
    except Exception:
        return False, last_latest, False

    if latest:
        state.update({"last_check_ts": _now(), "last_latest": latest})
        _save_state(state)
        return (latest > current_version), latest, False
    else:
        state.update({"last_check_ts": _now()})
        _save_state(state)
        return False, last_latest, False


__all__ = [
    "check_for_updates_cached",
]
