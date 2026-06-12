"""License management for BaSIM - trial, WA gov free access, and paid keys."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any


class LicenseManager:
    """Manages software licensing with WA government free tier."""

    def __init__(self):
        from src.core.paths import license_dir
        self.license_file = license_dir() / 'license.json'
        self.license_file.parent.mkdir(parents=True, exist_ok=True)
        # Future API (unused for offline validation)
        self.license_server = "https://api.basim.com/v1/validate"
        # Privileged emails with perpetual access (bypass activation)
        self._privileged_emails = {"patrickjohnhayes@gmail.com"}

    def is_privileged_email(self, email: str) -> bool:
        return (email or '').strip().lower() in self._privileged_emails

    def ensure_privileged_seed(self):
        """If no license exists, seed a perpetual license for any privileged user.

        This bypasses the activation dialog on first run for whitelisted emails.
        """
        if self.license_file.exists():
            return
        # Seed the first privileged email (static list)
        try:
            email = next(iter(self._privileged_emails))
        except Exception:
            return
        data = {
            'email': email,
            'key': 'PERPETUAL',
            'type': 'Perpetual',
            'features': 'full',
            'perpetual': True,
            'machine_id': self._generate_machine_id(),
            'saved_at': datetime.now().isoformat(),
        }
        try:
            self.license_file.write_text(json.dumps(data, indent=2), encoding='utf-8')
        except Exception:
            pass

    def validate_license(self, email: str, key: Optional[str] = None) -> Dict[str, Any]:
        """Validate license key or check for free tier eligibility."""
        email = (email or '').strip().lower()

        # Perpetual access for privileged emails
        if self.is_privileged_email(email):
            return {
                'valid': True,
                'type': 'Perpetual',
                'expires': None,
                'features': 'full',
                'email': email,
                'message': 'Perpetual license (whitelisted)',
            }

        # Free for WA government agencies
        if self._is_wa_gov_email(email):
            return {
                'valid': True,
                'type': 'Government Agency',
                'expires': None,
                'features': 'full',
                'email': email,
                'message': 'Free access for WA Government',
            }

        # Validate paid license
        if key:
            return self._validate_key(email, key)

        # Trial period
        return self._check_trial(email)

    def _is_wa_gov_email(self, email: str) -> bool:
        patterns = [r'^.+@.+\.wa\.gov\.au$']
        for pat in patterns:
            if re.match(pat, email, re.IGNORECASE):
                return True
        return False

    def _generate_machine_id(self) -> str:
        node = uuid.getnode()
        system = platform.system()
        machine = platform.machine()
        processor = platform.processor()
        unique_str = f"{node}-{system}-{machine}-{processor}"
        return hashlib.sha256(unique_str.encode()).hexdigest()[:16]

    def _validate_key(self, email: str, key: str) -> Dict[str, Any]:
        key = (key or '').strip().upper().replace(' ', '')
        if not re.match(r'^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$', key):
            return {'valid': False, 'type': 'Invalid', 'expires': None, 'features': 'none', 'message': 'Invalid license key format'}
        # Demo: keys starting with BSIM are accepted
        if key.startswith('BSIM'):
            return {
                'valid': True,
                'type': 'Licensed',
                'expires': None,
                'features': 'full',
                'email': email,
                'key': key,
                'message': 'Valid license key',
            }
        return {'valid': False, 'type': 'Invalid', 'expires': None, 'features': 'none', 'message': 'Invalid license key'}

    def _check_trial(self, email: str) -> Dict[str, Any]:
        data = self.load_stored_license()
        if data and (data.get('email') or '').lower() == (email or '').lower():
            start = data.get('trial_start')
            if start:
                try:
                    start_dt = datetime.fromisoformat(start)
                    end_dt = start_dt + timedelta(days=30)
                    now = datetime.now()
                    if now <= end_dt:
                        days_left = (end_dt - now).days
                        return {'valid': True, 'type': 'Trial', 'expires': end_dt.isoformat(), 'features': 'full', 'email': email, 'message': f'Trial active - {days_left} days remaining'}
                    return {'valid': False, 'type': 'Expired', 'expires': end_dt.isoformat(), 'features': 'none', 'message': 'Trial period has expired'}
                except Exception:
                    pass
        # Start new trial
        now = datetime.now()
        end_dt = now + timedelta(days=30)
        trial_data = {
            'email': email,
            'trial_start': now.isoformat(),
            'trial_end': end_dt.isoformat(),
            'machine_id': self._generate_machine_id(),
        }
        self.save_license(email, None, trial_data)
        return {'valid': True, 'type': 'Trial', 'expires': end_dt.isoformat(), 'features': 'full', 'email': email, 'message': '30-day trial started'}

    def save_license(self, email: str, key: Optional[str] = None, extra_data: Optional[Dict] = None):
        data = {
            'email': email,
            'key': key,
            'machine_id': self._generate_machine_id(),
            'saved_at': datetime.now().isoformat(),
        }
        if extra_data:
            data.update(extra_data)
        self.license_file.write_text(json.dumps(data, indent=2), encoding='utf-8')

    def load_stored_license(self) -> Optional[Dict[str, Any]]:
        if not self.license_file.exists():
            return None
        try:
            return json.loads(self.license_file.read_text(encoding='utf-8'))
        except Exception:
            return None

    def clear_license(self):
        if self.license_file.exists():
            try:
                self.license_file.unlink()
            except Exception:
                pass
