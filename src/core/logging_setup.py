"""BaSIM centralized logging setup (Phase 5).

Provides structured logging initialization that:
 - Writes to user-writable log directory (Documents/BaSIM/logs)
 - Optionally enables DEBUG verbosity via env BASIM_DEBUG=1 or --debug flag
 - Rotates log file when exceeding a size threshold (default 2 MB, keeps 5 backups)
 - Captures Python warnings and redirects them to logging
 - Enables faulthandler to dump tracebacks on hard crashes
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import warnings
import faulthandler
from pathlib import Path
from datetime import datetime
from typing import Optional

DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
DEFAULT_BACKUPS = 5

def user_log_dir() -> Path:
    docs = Path.home() / "Documents"
    base = docs / "BaSIM" / "logs"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Fallback to hidden home dir
        base = Path.home() / ".BaSIM" / "logs"
        base.mkdir(parents=True, exist_ok=True)
    return base

def build_log_file(debug: bool) -> Path:
    d = user_log_dir()
    name = "basim_debug.log" if debug else "basim.log"
    return d / name

def init_logging(debug: bool = False, max_bytes: int = DEFAULT_MAX_BYTES, backups: int = DEFAULT_BACKUPS) -> Path:
    """Initialize application logging and return primary log file path.

    Safe to call multiple times; it will no-op after first initialization.
    """
    if getattr(init_logging, "_initialized", False):  # type: ignore[attr-defined]
        return getattr(init_logging, "_log_path", Path("basim.log"))  # pragma: no cover

    log_level = logging.DEBUG if debug else logging.INFO
    log_file = build_log_file(debug)
    fmt = "%(asctime)s | %(levelname)-8s | %(threadName)s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = []
    try:
        rotating = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
        rotating.setFormatter(logging.Formatter(fmt, datefmt))
        handlers.append(rotating)
    except Exception:
        # Fallback to stderr only
        pass

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.WARNING if not debug else logging.DEBUG)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    handlers.append(console)

    logging.basicConfig(level=log_level, handlers=handlers)
    logging.getLogger("PyQt6").setLevel(logging.INFO)
    logging.captureWarnings(True)
    warnings.filterwarnings("default")

    # Enable faulthandler to write fatal crashes to separate file
    try:
        crash_file = user_log_dir() / "crash_traces.log"
        fh = open(crash_file, "a", encoding="utf-8")
        faulthandler.enable(fh)
    except Exception:
        pass

    logging.info("Logging initialized (debug=%s) file=%s", debug, log_file)
    setattr(init_logging, "_initialized", True)
    setattr(init_logging, "_log_path", log_file)
    return log_file

def install_global_exception_hook():
    """Install a sys.excepthook that logs uncaught exceptions."""
    import sys, traceback
    logger = logging.getLogger("basim.excepthook")

    def _hook(exc_type, exc, tb):
        if exc_type is KeyboardInterrupt:
            logger.info("KeyboardInterrupt received; exiting.")
            return sys.__excepthook__(exc_type, exc, tb)
        logger.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
        # Try minimal messagebox (avoid import loops)
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "BaSIM Crash", f"An unexpected error occurred: {exc}\nSee logs in: {user_log_dir()}")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook
