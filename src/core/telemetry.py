"""Minimal opt-in telemetry (Phase 8).

Data (when enabled):
 - version (with build metadata)
 - machine hash (same algorithm as license verifier; non-PII)
 - platform (os name + arch)
 - license status summary (ok / missing / expired)

Opt-in mechanisms (any true enables):
 - Environment BASIM_TELEMETRY=1
 - File telemetry/opt_in.flag (presence)

Opt-out precedence: BASIM_TELEMETRY=0 always disables.

Network:
 - Simple POST (JSON) to endpoint (default placeholder). Timeout 2s.
 - Failures are silent; never raise.
"""
from __future__ import annotations

import json, os, platform, threading, urllib.request
from pathlib import Path
from typing import Optional

from .paths import telemetry_dir

DEFAULT_ENDPOINT = os.environ.get('BASIM_TELEMETRY_URL', 'https://telemetry.basim.example/collect')

def _opt_in_file() -> Path:
    return telemetry_dir() / 'opt_in.flag'

def is_enabled() -> bool:
    env = os.environ.get('BASIM_TELEMETRY')
    if env == '0':
        return False
    if env == '1':
        return True
    return _opt_in_file().exists()

def enable_persistent():
    try:
        _opt_in_file().write_text('1', encoding='utf-8')
    except Exception:
        pass

def disable_persistent():
    try:
        if _opt_in_file().exists():
            _opt_in_file().unlink()
    except Exception:
        pass

def _machine_hash_fallback() -> str:
    # Lightweight fallback if we cannot import verifier
    base = (platform.node() + '|' + platform.system() + '|' + platform.machine()).encode()
    import hashlib
    return hashlib.sha256(base).hexdigest()[:32]

def _collect_payload() -> dict:
    try:
        from src.version import full_version_string
        version = full_version_string()
    except Exception:
        version = '0.0.0'
    # Reuse license verifier if present
    lic_status = 'unknown'
    try:
        from src.licensing.verifier import LicenseVerifier
        lv = LicenseVerifier()
        st = lv.validate_installed()
        if st.ok:
            lic_status = 'valid'
        else:
            if 'expired' in st.message.lower():
                lic_status = 'expired'
            else:
                lic_status = 'missing'
        machine = lv.machine_hash()
    except Exception:
        machine = _machine_hash_fallback()
    return {
        'version': version,
        'machine': machine,
        'platform': f"{platform.system()}-{platform.release()}-{platform.machine()}",
        'license': lic_status,
    }

def send_once(timeout: float = 2.0):
    if not is_enabled():
        return
    payload = _collect_payload()
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(DEFAULT_ENDPOINT, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'basim-telemetry'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Best-effort; ignore body
            resp.read(0)
    except Exception:
        pass

def send_async():
    if not is_enabled():
        return
    threading.Thread(target=send_once, name='TelemetrySend', daemon=True).start()

__all__ = [
    'is_enabled','enable_persistent','disable_persistent','send_async'
]
