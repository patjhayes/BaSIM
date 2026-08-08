from __future__ import annotations

import os
from pathlib import Path
import tempfile


def get_app_dir() -> Path:
    root = Path(os.getenv("SOAKSIM_HOME", Path(tempfile.gettempdir()) / "soaksim"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_cache_dir() -> Path:
    cache_dir = get_app_dir() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_logs_dir() -> Path:
    logs_dir = get_app_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir
