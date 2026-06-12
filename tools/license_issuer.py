from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# pip install PyNaCl
from nacl.signing import SigningKey

PRODUCT = "BaSIM"

@dataclass
class LicensePayload:
    product: str
    customer: str
    edition: str
    machine: str
    expiry: str  # ISO-8601 UTC, e.g. 2026-12-31T23:59:59Z

    def to_dict(self) -> dict:
        return {
            "product": self.product,
            "customer": self.customer,
            "edition": self.edition,
            "machine": self.machine,
            "expiry": self.expiry,
        }


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def issue_license(private_key_hex: str, payload: LicensePayload) -> dict:
    sk = SigningKey(bytes.fromhex(private_key_hex))
    sig = sk.sign(canonical(payload.to_dict())).signature
    return {
        "payload": payload.to_dict(),
        "sig": base64.b64encode(sig).decode("ascii"),
    }


def main():
    import argparse

    p = argparse.ArgumentParser(description="BaSIM License Issuer (offline)")
    p.add_argument("request", help="Path to license_request.json from client")
    p.add_argument("--customer", required=True)
    p.add_argument("--edition", default="Enterprise")
    p.add_argument("--expiry", help="UTC expiry YYYY-MM-DD (end of day). If omitted, +365 days.")
    p.add_argument("--out", help="Output .lic file path", default="license.lic")
    p.add_argument("--private-key-hex", help="Ed25519 private key hex (32 bytes)")
    args = p.parse_args()

    req = json.loads(Path(args.request).read_text(encoding="utf-8"))
    machine = req.get("machine")
    if not machine:
        raise SystemExit("Request missing 'machine'")

    # Determine expiry
    if args.expiry:
        exp_dt = datetime.strptime(args.expiry, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    else:
        from datetime import timedelta
        exp_dt = datetime.now(timezone.utc) + timedelta(days=365)
    expiry_iso = exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Load private key
    priv = args.private_key_hex or os.environ.get("BASIM_ISSUER_PRIV")
    if not priv:
        raise SystemExit("Provide --private-key-hex or BASIM_ISSUER_PRIV env var")

    lic = issue_license(priv, LicensePayload(PRODUCT, args.customer, args.edition, machine, expiry_iso))
    # Ensure output directory exists (and is a directory)
    out_path = Path(args.out)
    parent = out_path.parent
    if parent.exists() and not parent.is_dir():
        raise SystemExit(f"Output parent path exists and is not a directory: {parent}")
    parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(lic, indent=2), encoding="utf-8")

    pub_hex = SigningKey(bytes.fromhex(priv)).verify_key.encode().hex()
    print("Wrote:", str(out_path))
    print("Public key (set BASIM_PUBKEY on clients):", pub_hex)


if __name__ == "__main__":
    main()
