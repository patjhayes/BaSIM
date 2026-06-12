#!/usr/bin/env python3
"""
BaSIM - Infiltration Basin Design Tool (GUI Launcher)

Phase 3 enhancements:
 - Robust preflight checks (MODFLOW 6 binary, license verifier availability)
 - Early crash logging to a user-writable directory
 - Graceful fallback to legacy UI if PyQt6 fails
 - Minimal messagebox notification if GUI cannot start
"""

from __future__ import annotations

import os
import threading
import sys
import traceback
from pathlib import Path
from datetime import datetime
import logging

# Ensure 'src' directory is on sys.path early (before main/selftest) in frozen mode so 'utils.*' imports resolve
try:
    if getattr(sys, 'frozen', False):
        _meipass = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
        _src_dir = _meipass / 'src'
        if _src_dir.exists():
            sp = str(_src_dir)
            if sp not in sys.path:
                sys.path.insert(0, sp)
except Exception:
    pass


def _user_base() -> Path:
    # Mirrors logic used elsewhere but kept minimal here
    docs = Path.home() / "Documents"
    target = docs / "BaSIM"
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception:
        target = Path.home() / ".BaSIM"
        target.mkdir(parents=True, exist_ok=True)
    return target


def _log_path() -> Path:
    base = _user_base() / "model_output" / "_progress"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return base / "launcher_boot.log"


def _legacy_log_to_boot_file(msg: str):
    """Retained lightweight file append (used before logging init)."""
    try:
        p = _log_path()
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with p.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

def _log(msg: str, level: int = logging.INFO):  # adapter bridging old calls
    try:
        logging.log(level, msg)
    except Exception:
        _legacy_log_to_boot_file(msg)


def _show_messagebox(title: str, text: str):
    # Try PyQt6 first, then fallback to Tkinter if available, else print.
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, title, text)
    except Exception:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk(); root.withdraw()
            messagebox.showerror(title, text)
            root.destroy()
        except Exception:
            print(f"{title}: {text}")


def _preflight() -> list[str]:
    """Run non-fatal preflight checks; return list of warnings."""
    warnings: list[str] = []
    # (MODFLOW presence now handled in main() to centralize corporate policy messaging)
    # License verifier module availability
    try:
        __import__('src.licensing.verifier')
    except Exception as e:
        warnings.append(f"License verifier unavailable ({e.__class__.__name__}); application may start unlicensed.")
    return warnings


def main():
    # Ensure 'src' and its direct children are on sys.path when frozen so plain 'utils.*' imports work
    try:
        if getattr(sys,'frozen',False):
            meipass = Path(getattr(sys,'_MEIPASS', Path(sys.executable).parent))
            src_dir = meipass / 'src'
            if src_dir.exists() and str(src_dir) not in sys.path:
                sys.path.insert(0, str(src_dir))
    except Exception:
        pass
    # Lightweight self-test mode (run before heavy GUI init). Usage: BaSIM_debug.exe --selftest
    if '--selftest' in sys.argv:
        print('[SELFTEST] Starting BaSIM frozen diagnostic...')
        print(f"[SELFTEST] frozen={getattr(sys,'frozen',False)} _MEIPASS={getattr(sys,'_MEIPASS',None)} exe={sys.executable}")
        print('[SELFTEST] sys.path:')
        for p in sys.path:
            print('  -', p)
        # Explicit probe for expected src directory
        try:
            from pathlib import Path as _Pchk
            _src_expect = _Pchk(getattr(sys,'_MEIPASS', _Pchk(sys.executable).parent))/ 'src'
            print(f"[SELFTEST] src dir exists={_src_expect.exists()} path={_src_expect}")
        except Exception:
            pass
        errors = []
        def _attempt(label, fn):
            try:
                fn()
                print(f'[SELFTEST] OK: {label}')
            except Exception as e:
                print(f'[SELFTEST] FAIL: {label}: {e.__class__.__name__}: {e}')
                traceback.print_exc()
                errors.append((label, e))
        _attempt('import src.main_phase3_step32_time_varying', lambda: __import__('src.main_phase3_step32_time_varying'))
        _attempt('import flopy', lambda: __import__('flopy'))
        _attempt('import numpy', lambda: __import__('numpy'))
        _attempt('import pandas', lambda: __import__('pandas'))
        # Attempt mf6 location (mirror simplified logic in locator)
        def _mf6_probe():
            from pathlib import Path as _P
            cand = []
            exe_dir = _P(getattr(sys,'_MEIPASS', _P(sys.executable).parent))
            names = ['mf6.exe','mf6'] if os.name == 'nt' else ['mf6']
            for n in names:
                cand.append(exe_dir / n)
                cand.append(exe_dir / 'bin' / n)
            found = None
            for c in cand:
                if c.exists():
                    found = c; break
            if not found:
                raise FileNotFoundError(f'mf6 not found in candidates: {[str(c) for c in cand]}')
            st = found.stat()
            print(f'[SELFTEST] mf6 located: {found} size={st.st_size} bytes')
        _attempt('locate mf6', _mf6_probe)
        rc = 0 if not errors else 1
        print(f'[SELFTEST] Complete. rc={rc}')
        return rc
    # Initialize structured logging (Phase 5)
    debug_flag = (os.environ.get("BASIM_DEBUG") == "1") or ("--debug" in sys.argv)
    try:
        from src.core.logging_setup import init_logging, install_global_exception_hook
        log_path = init_logging(debug=debug_flag)
        install_global_exception_hook()
    except Exception:
        _legacy_log_to_boot_file("Failed to init structured logging; continuing with legacy logger.")
        log_path = _log_path()

    try:
        from src.version import VERSION, BUILD_METADATA
        _log(f"Launcher start (v{VERSION} {BUILD_METADATA or 'no-meta'} debug={debug_flag})")
    except Exception:
        _log("Launcher start (version import failed)")
    warnings = []
    try:
        warnings = _preflight()
        try:
            from src.gui.qt_app import launch_app  # Primary UI
            _log("Using PyQt6 GUI")
        except Exception as e:
            _log(f"PyQt6 import failed: {e}; falling back to legacy UI", logging.WARNING)
            from src.gui.main_app import launch_app  # Legacy Tk UI

    # Phase 6: async update check
        def _update_check():
            try:
                if os.environ.get("BASIM_DISABLE_UPDATE_CHECK") == "1":
                    return
                from src.version import VERSION
                try:
                    from src.core.update import check_for_updates_cached
                except Exception:
                    return
                has_update, latest, cached = check_for_updates_cached(VERSION)
                if has_update and latest:
                    _log(f"Update available: {latest} (current {VERSION}). Visit project releases page.", logging.WARNING)
                elif latest and not cached:
                    _log(f"Checked for updates; current version {VERSION} is latest ({latest}).")
            except Exception as ue:
                _log(f"Update check failed: {ue}", logging.DEBUG)

        try:
            threading.Thread(target=_update_check, name="UpdateCheck", daemon=True).start()
        except Exception:
            pass

        # Phase 8: telemetry (opt-in only)
        try:
            from src.core.telemetry import send_async as _telemetry_send
            _telemetry_send()
        except Exception:
            _log("Telemetry dispatch failed (ignored)", logging.DEBUG)

        # Corporate-friendly behavior: do NOT auto-download mf6 unless explicitly allowed
        # Locate mf6 in both onedir and onefile contexts. In onefile, PyInstaller extracts
        # bundled binaries to sys._MEIPASS; in onedir we expect mf6.exe alongside BaSIM.exe or in bin/.
        def _runtime_root() -> Path:
            if getattr(sys, 'frozen', False):
                # PyInstaller: onefile exposes _MEIPASS; onedir sets executable parent
                mp = getattr(sys, '_MEIPASS', None)
                if mp:
                    return Path(mp)
                return Path(sys.executable).parent
            return Path(__file__).resolve().parent

        exe_dir = _runtime_root()
        # Check common locations
        cand_paths = [
            exe_dir / ('mf6.exe' if os.name == 'nt' else 'mf6'),
            exe_dir / 'bin' / ('mf6.exe' if os.name == 'nt' else 'mf6'),
        ]
        mf6_path = None
        for c in cand_paths:
            if c.exists():
                mf6_path = c
                break
        if mf6_path is None:
            mf6_path = cand_paths[0]
        if not mf6_path.exists():
            # Remove prior behavior: we do not prompt automatically in corporate-friendly mode
            if os.environ.get('BASIM_ALLOW_MF6_DOWNLOAD') == '1':
                _log("mf6.exe missing; BASIM_ALLOW_MF6_DOWNLOAD=1 -> attempting download", logging.WARNING)
                try:
                    import runpy
                    script = exe_dir / 'scripts' / 'download_modflow.py'
                    if script.exists():
                        runpy.run_path(str(script))
                        if mf6_path.exists():
                            _log("MODFLOW 6 fetched successfully")
                        else:
                            warnings.append("Attempted download but mf6.exe still missing.")
                    else:
                        warnings.append("download_modflow.py script not packaged; cannot fetch mf6.exe.")
                except Exception as de:
                    warnings.append(f"MODFLOW 6 download attempt failed: {de}")
            else:
                msg = ("MODFLOW 6 binary (mf6.exe) not bundled. Corporate builds should include it in the bin/ folder.\n"
                       "Set BASIM_ALLOW_MF6_DOWNLOAD=1 before launch ONLY if policy permits network download.")
                warnings.append(msg)

        exit_code = launch_app()  # Assume launch_app returns int or None
        if exit_code is None:
            exit_code = 0
        for w in warnings:
            _log(w, logging.WARNING)
        _log(f"Launcher exit code {exit_code}; log file: {log_path}")
        return exit_code
    except Exception as e:
        tb = traceback.format_exc()
        _log("FATAL: " + repr(e), logging.CRITICAL)
        _log(tb, logging.CRITICAL)
        _show_messagebox("BaSIM Launch Error", f"A fatal error occurred before the GUI could start:\n{e}\n\nSee log:\n{_log_path()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
