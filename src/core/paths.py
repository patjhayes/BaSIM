"""Common path utilities (user-writable locations)."""
from __future__ import annotations

from pathlib import Path
import os

def user_base() -> Path:
    # Preference order: Documents/BaSIM -> ~/.BaSIM
    docs = Path.home() / 'Documents'
    target = docs / 'BaSIM'
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception:
        target = Path.home() / '.BaSIM'
        target.mkdir(parents=True, exist_ok=True)
    return target

def license_dir() -> Path:
    d = user_base() / 'license'
    d.mkdir(parents=True, exist_ok=True)
    return d

def telemetry_dir() -> Path:
    d = user_base() / 'telemetry'
    d.mkdir(parents=True, exist_ok=True)
    return d

__all__ = [
    'user_base',
    'license_dir',
    'telemetry_dir',
]
