"""Lightweight global error reporting for BaSIM.

Captures unhandled exceptions, writes them to the rotating log, creates a
timestamped zip with recent logs, and shows a friendly message to the user.
"""
from __future__ import annotations

from pathlib import Path
import sys
import time
import traceback
import zipfile
import threading

try:
    import tkinter as tk
    from tkinter import messagebox
except Exception:  # pragma: no cover - headless
    tk = None
    messagebox = None


def _log_dir() -> Path:
    d = Path.home() / ".basim" / "logs"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _reports_dir() -> Path:
    d = Path.home() / ".basim" / "reports"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _package_recent_logs() -> Path | None:
    """Zip the latest app.log files into a timestamped archive and return its path."""
    try:
        log_dir = _log_dir()
        if not log_dir.exists():
            return None
        # Collect app.log and its rotations
        candidates = sorted([p for p in log_dir.glob("app.log*") if p.is_file()])
        if not candidates:
            return None
        ts = time.strftime("%Y%m%d_%H%M%S")
        zip_path = _reports_dir() / f"error_{ts}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in candidates:
                try:
                    zf.write(p, arcname=p.name)
                except Exception:
                    continue
        return zip_path
    except Exception:
        return None


def _format_exception(exc_type, exc, tb) -> str:
    try:
        return "".join(traceback.format_exception(exc_type, exc, tb))
    except Exception:
        return f"{exc_type.__name__}: {exc}"


def _show_dialog(msg: str, zip_path: Path | None):
    if messagebox is None:
        return
    try:
        extra = f"\n\nLogs: {zip_path}" if zip_path else ""
        messagebox.showerror(
            "BaSIM — Unexpected Error",
            f"An unexpected error occurred. The application can continue,\n"
            f"but some features may not work until restart.\n\n{msg}{extra}"
        )
    except Exception:
        pass


def install(app_window=None, logger=None):
    """Install global exception handlers for sys and Tkinter.

    - sys.excepthook: captures unhandled exceptions in main thread
    - threading.excepthook (3.8+): captures exceptions in other threads
    - Tkinter report_callback_exception: GUI callback exceptions
    """

    def _handle(exc_type, exc, tb):
        text = _format_exception(exc_type, exc, tb)
        try:
            if logger is not None:
                logger.error("Unhandled exception:\n%s", text)
        except Exception:
            pass
        z = _package_recent_logs()
        _show_dialog(text.splitlines()[-1] if text else str(exc), z)

    # sys
    try:
        sys.excepthook = _handle
    except Exception:
        pass

    # threads (Python >= 3.8)
    try:
        def _thread_hook(args: threading.ExceptHookArgs):
            _handle(args.exc_type, args.exc_value, args.exc_traceback)
        threading.excepthook = _thread_hook  # type: ignore[attr-defined]
    except Exception:
        pass

    # tkinter
    try:
        if app_window is not None and hasattr(app_window, "report_callback_exception"):
            def _tk_hook(exc, val, tb):
                _handle(exc, val, tb)
            app_window.report_callback_exception = _tk_hook  # type: ignore[assignment]
    except Exception:
        pass
