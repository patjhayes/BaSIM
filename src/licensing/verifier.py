from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from nacl.signing import VerifyKey  # type: ignore
    from nacl.exceptions import BadSignatureError  # type: ignore
    _NACL_OK = True
except Exception:
    _NACL_OK = False


PRODUCT = "BaSIM"
from src.core.paths import license_dir

# New unified user-writable location
LICENSE_DIR = license_dir()
LICENSE_PATH = LICENSE_DIR / "license.lic"

# Migration: pull from legacy locations if new path empty
_LEGACY_CANDIDATES = [
    Path(os.environ.get("ProgramData", r"C:\\ProgramData")) / "BaSIM" / "license" / "license.lic",
    Path.home() / '.basim' / 'license.json',  # legacy manager JSON
]
if not LICENSE_PATH.exists():
    for old in _LEGACY_CANDIDATES:
        try:
            if old.exists():
                data = old.read_text(encoding='utf-8')
                # If json trial license convert to signed license placeholder (leave content anyway)
                LICENSE_PATH.write_text(data, encoding='utf-8')
                break
        except Exception:
            pass

# Public key hex for license verification. Can be overridden via env BASIM_PUBKEY.
# If BASIM_PUBKEY is not set, the embedded default below is used.
PUBLIC_KEY_HEX = os.environ.get(
    "BASIM_PUBKEY",
    "8db92715cdc206244c3fe71906cb7a819c420024c77979739428b4e9925df052",
).strip()


@dataclass
class LicenseStatus:
    ok: bool
    message: str
    customer: Optional[str] = None
    edition: Optional[str] = None
    expiry_utc: Optional[datetime] = None
    days_left: Optional[int] = None


class LicenseVerifier:
    def __init__(self, pubkey_hex: Optional[str] = None):
        self.pubkey_hex = (pubkey_hex or PUBLIC_KEY_HEX or "").strip()

    # Windows machine ID hash (non-PII; stable)
    def machine_hash(self) -> str:
        try:
            import winreg  # type: ignore
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
                guid, _ = winreg.QueryValueEx(k, "MachineGuid")
            raw = str(guid).encode("utf-8")
        except Exception:
            # fallback: combine env hints
            raw = (
                os.getenv("COMPUTERNAME", "UNKNOWN")
                + "|"
                + os.getenv("PROCESSOR_IDENTIFIER", "")
            ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _canonical(self, payload: dict) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _verify(self, lic: dict) -> LicenseStatus:
        if not _NACL_OK:
            return LicenseStatus(False, "PyNaCl not installed; cannot verify license.")
        if not self.pubkey_hex:
            return LicenseStatus(False, "Public key not set. Set BASIM_PUBKEY or embed key.")

        payload = lic.get("payload")
        sig_b64 = lic.get("sig")
        if not isinstance(payload, dict) or not isinstance(sig_b64, str):
            return LicenseStatus(False, "Malformed license file.")

        # product check
        if str(payload.get("product", "")).lower() != PRODUCT.lower():
            return LicenseStatus(False, "License product mismatch.")

        # signature check
        try:
            vk = VerifyKey(bytes.fromhex(self.pubkey_hex))
            vk.verify(self._canonical(payload), base64.b64decode(sig_b64))
        except (BadSignatureError, ValueError, Exception):
            return LicenseStatus(False, "License signature invalid.")

        # machine binding
        mach = str(payload.get("machine", ""))
        if mach and mach != self.machine_hash():
            return LicenseStatus(False, "License not valid for this machine.")

        # expiry check
        expiry = str(payload.get("expiry", ""))
        try:
            exp_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return LicenseStatus(False, "License expiry invalid.")
        now = datetime.now(timezone.utc)
        if exp_dt < now:
            return LicenseStatus(False, "License expired.", expiry_utc=exp_dt, days_left=0)

        days_left = max(0, (exp_dt.date() - now.date()).days)
        return LicenseStatus(
            True,
            "License valid.",
            customer=str(payload.get("customer", "")) or None,
            edition=str(payload.get("edition", "")) or None,
            expiry_utc=exp_dt,
            days_left=days_left,
        )

    def validate_text(self, text: str) -> LicenseStatus:
        try:
            lic = json.loads(text)
        except Exception:
            return LicenseStatus(False, "License file is not valid JSON.")
        return self._verify(lic)

    def validate_file(self, path: Path) -> LicenseStatus:
        try:
            return self.validate_text(path.read_text(encoding="utf-8"))
        except Exception as e:
            return LicenseStatus(False, f"Cannot read license: {e}")

    def validate_installed(self) -> LicenseStatus:
        if LICENSE_PATH.exists():
            return self.validate_file(LICENSE_PATH)
        return LicenseStatus(False, f"No license found at {LICENSE_PATH}")

    def install_file(self, src: Path) -> LicenseStatus:
        LICENSE_DIR.mkdir(parents=True, exist_ok=True)
        data = src.read_text(encoding="utf-8")
        st = self.validate_text(data)
        if not st.ok:
            return st
        LICENSE_PATH.write_text(data, encoding="utf-8")
        return st

    def make_request(self, note: str = "") -> dict:
        return {
            "product": PRODUCT,
            "machine": self.machine_hash(),
            "note": note,
            "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
