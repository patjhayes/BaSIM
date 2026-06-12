# BaSIM Tools

## License Issuer (Admin)

Issue offline, node-locked licenses bound to a machine hash.

- Script: `tools/license_issuer.py`
- Depends on: `PyNaCl`

### Generate Ed25519 Keys
```python
from nacl.signing import SigningKey
sk = SigningKey.generate()
print('PRIVATE:', sk.encode().hex())
print('PUBLIC :', sk.verify_key.encode().hex())
```

Keep the private key secret. Provide the public key to clients via the `BASIM_PUBKEY` environment variable or embed it in `src/licensing/verifier.py`.

### Issue a License
```powershell
python tools\license_issuer.py .\license_request.json --customer "Acme" --edition Enterprise --out license.lic --private-key-hex <PRIVATE_HEX>
```

The output `license.lic` is a JSON with `{ payload, sig }`. The client installs it via the app: Help → License…

## WiX Installer Notes
- Creates `%ProgramData%\BaSIM\license` for system-wide license storage.
- Accepts MSI property `BASIMPUBKEY`. When set, installer writes `BASIM_PUBKEY` as a system environment variable.
- Silent install example:
```powershell
msiexec /i BasinSIM.msi BASIMPUBKEY=0123abcd... /qn
```
