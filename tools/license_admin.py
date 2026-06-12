from __future__ import annotations

"""
BaSIM License Admin Tool

Purpose:
- Generate an Ed25519 key pair
- Issue (sign) licenses that the app can validate
- Verify licenses

This matches the canonicalization + signature scheme used by `src/licensing/verifier.py`.

USAGE (PowerShell examples):
  # 1) Generate keys (store private key securely!)
  python tools/license_admin.py gen-keys --outdir secrets

  # 2) Issue a license from a saved request file
  python tools/license_admin.py issue --priv secrets/basim_private.hex --request license_request.json --customer "ACME Pty" --edition "Pro" --expiry 2026-12-31 --out license.lic

  # 3) Or issue by providing the Machine ID hash directly
  python tools/license_admin.py issue --priv secrets/basim_private.hex --machine 0123abcd... --customer "ACME Pty" --edition "Pro" --expiry 2026-12-31 --out license.lic

  # 4) Verify a license
  python tools/license_admin.py verify --pubhex <PUBLIC_KEY_HEX> --file license.lic

Embed the public key in your app by either:
- Setting environment variable BASIM_PUBKEY=<PUBLIC_KEY_HEX>, or
- Hard-coding PUBLIC_KEY_HEX in src/licensing/verifier.py

SECURITY: Store the private key offline and restrict access. Only the public key is distributed with the app.
"""

import argparse
import base64
import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from nacl.signing import SigningKey, VerifyKey

PRODUCT = "BaSIM"


# ----------------------------- helpers -----------------------------

def _canonical(obj: dict) -> bytes:
    """Canonical JSON encoding to match the verifier."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _write_text(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@dataclass
class KeyPair:
    priv: SigningKey
    pub_hex: str


def load_private_key_hex(path: Path) -> SigningKey:
    data = _read_text(path).strip()
    # Expect hex string for the 32-byte seed
    try:
        raw = bytes.fromhex(data)
    except ValueError as e:
        raise ValueError(f"Private key file is not valid hex: {path}") from e
    if len(raw) not in (32, 64):
        # 32 = seed; 64 would also be accepted by SigningKey but seed is recommended
        raise ValueError("Private key must be 32 bytes (hex-encoded)")
    return SigningKey(raw[:32])


def generate_keypair() -> KeyPair:
    sk = SigningKey.generate()
    vk = sk.verify_key
    return KeyPair(priv=sk, pub_hex=vk.encode().hex())


# ----------------------------- issuing -----------------------------

def make_expiry_iso(date_or_dt: str) -> str:
    """
    Accepts either YYYY-MM-DD or full ISO datetime. Returns ISO with Z (UTC).
    If only date is provided, expiry set to 23:59:59Z of that date.
    """
    s = date_or_dt.strip()
    try:
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            dt = datetime.strptime(s, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        else:
            # Try generic ISO
            dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception as e:
        raise ValueError("Invalid expiry format. Use YYYY-MM-DD or ISO 8601.") from e
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_payload(
    *,
    product: str,
    machine: str,
    customer: Optional[str],
    edition: Optional[str],
    expiry_iso_z: str,
    note: Optional[str] = None,
    features: Optional[dict] = None,
) -> dict:
    p: dict = {
        "product": product,
        "machine": machine,
        "expiry": expiry_iso_z,
    }
    if customer:
        p["customer"] = customer
    if edition:
        p["edition"] = edition
    if note:
        p["note"] = note
    if features:
        p["features"] = features
    return p


def sign_license(payload: dict, sk: SigningKey) -> dict:
    sig = sk.sign(_canonical(payload)).signature
    return {"payload": payload, "sig": base64.b64encode(sig).decode("ascii")}


def _make_license_id(payload: dict) -> str:
    """Stable license ID derived from canonical payload (non-secret)."""
    return hashlib.sha256(_canonical(payload)).hexdigest()[:16]


def _ledger_append_jsonl(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


# ----------------------------- CLI -----------------------------

def cmd_gen_keys(args: argparse.Namespace) -> int:
    kp = generate_keypair()
    priv_hex = kp.priv.encode().hex()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    priv_path = outdir / "basim_private.hex"
    pub_path = outdir / "basim_public.hex"
    _write_text(priv_path, priv_hex)
    _write_text(pub_path, kp.pub_hex)
    print(f"Private key (hex) -> {priv_path}")
    print(f"Public key  (hex) -> {pub_path}")
    print("IMPORTANT: Keep the private key secret and offline. Distribute ONLY the public key.")
    return 0


def cmd_issue(args: argparse.Namespace) -> int:
    # Load private key
    sk = load_private_key_hex(Path(args.priv))

    # Machine ID
    machine = args.machine
    note = None
    if args.request:
        req = json.loads(_read_text(Path(args.request)))
        machine = machine or str(req.get("machine", "")).strip()
        note = str(req.get("note", "")).strip() or None
        if not machine:
            raise SystemExit("Request file missing 'machine'.")

    if not machine:
        raise SystemExit("--machine or --request is required.")

    expiry_iso = make_expiry_iso(args.expiry)
    payload = build_payload(
        product=args.product or PRODUCT,
        machine=machine,
        customer=args.customer,
        edition=args.edition,
        expiry_iso_z=expiry_iso,
        note=note or args.note,
        features=json.loads(args.features) if args.features else None,
    )
    lic = sign_license(payload, sk)

    out = Path(args.out)
    _write_text(out, json.dumps(lic, indent=2))
    print(f"Wrote license -> {out}")
    print("Distribute this .lic to the user. They can import it via the License dialog, or place it at:")
    print(r"  C:\\ProgramData\\BaSIM\\license\\license.lic")
    # Append issuance to ledger if enabled
    ledger_path = getattr(args, "ledger", None)
    if ledger_path:
        try:
            lic_id = _make_license_id(payload)
            entry = {
                "license_id": lic_id,
                "issued_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "product": payload.get("product"),
                "customer": args.customer,
                "edition": args.edition,
                "machine": machine,
                "expiry": payload.get("expiry"),
                "note": (note or args.note) if (note or args.note) else None,
                "features": json.loads(args.features) if args.features else None,
                "request_file": str(args.request) if args.request else None,
                "output_file": str(out),
                "sig_b64": lic.get("sig"),
            }
            _ledger_append_jsonl(Path(ledger_path), entry)
            print(f"Ledger appended -> {ledger_path} (license_id={lic_id})")
        except Exception as e:
            print(f"Warning: failed to append ledger: {e}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    lic = json.loads(_read_text(Path(args.file)))
    try:
        payload = lic["payload"]
        sig_b64 = lic["sig"]
        vk = VerifyKey(bytes.fromhex(args.pubhex.strip()))
        vk.verify(_canonical(payload), base64.b64decode(sig_b64))
        print("License signature is VALID for the given public key.")
        exp = payload.get("expiry")
        if exp:
            try:
                from datetime import datetime, timezone
                exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00")).astimezone(timezone.utc)
                now = datetime.now(timezone.utc)
                days = (exp_dt.date() - now.date()).days
                status = "EXPIRED" if exp_dt < now else f"{days} days left"
                print(f"Expiry: {exp} UTC -> {status}")
            except Exception:
                pass
        print("Payload:")
        print(json.dumps(payload, indent=2))
        return 0
    except Exception as e:
        print(f"Invalid license: {e}")
        return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="BaSIM License Admin Tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("gen-keys", help="Generate a new Ed25519 key pair (hex files)")
    p_gen.add_argument("--outdir", default="secrets", help="Output directory for key files")
    p_gen.set_defaults(func=cmd_gen_keys)

    p_issue = sub.add_parser("issue", help="Issue (sign) a license")
    p_issue.add_argument("--priv", required=True, help="Path to private key hex file")
    src = p_issue.add_mutually_exclusive_group(required=True)
    src.add_argument("--request", help="Path to license_request.json from the user")
    src.add_argument("--machine", help="Machine ID hash (from the License dialog)")
    p_issue.add_argument("--customer", help="Customer name")
    p_issue.add_argument("--edition", help="Edition e.g. Trial/Standard/Pro")
    p_issue.add_argument("--expiry", required=True, help="Expiry date (YYYY-MM-DD) or ISO 8601")
    p_issue.add_argument("--product", default=PRODUCT, help="Product name (default BaSIM)")
    p_issue.add_argument("--note", help="Optional note to embed in the payload")
    p_issue.add_argument("--features", help="Optional JSON dict with feature flags")
    p_issue.add_argument("--out", required=True, help="Output license file path (e.g. license.lic)")
    p_issue.add_argument(
        "--ledger",
        default="secrets/licenses_ledger.jsonl",
        help="Append issuance record to this JSONL ledger file (default secrets/licenses_ledger.jsonl). Set empty to disable.",
    )
    p_issue.set_defaults(func=cmd_issue)

    p_ver = sub.add_parser("verify", help="Verify a license using a public key")
    p_ver.add_argument("--pubhex", required=True, help="Public key hex")
    p_ver.add_argument("--file", required=True, help="Path to license file to verify")
    p_ver.set_defaults(func=cmd_verify)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
