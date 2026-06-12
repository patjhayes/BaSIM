"""
Diagnose the BaSIM executable folder build.
Prints presence of critical files and attempts a short run.
"""
from __future__ import annotations

import sys
from pathlib import Path
import subprocess


def diagnose() -> None:
    print("BaSIM Executable Diagnostics")
    print("=" * 50)

    # Prefer new name; fall back to legacy for compatibility
    candidates = [Path("dist/BaSIM"), Path("dist/BaSIM")]
    dist_dir = next((p for p in candidates if p.exists()), candidates[0])
    if dist_dir.exists():
        print(f"\n✓ Dist folder exists: {dist_dir.absolute()}")

        exe_name = f"{dist_dir.name}.exe"
        critical = [exe_name, "python310.dll", "python311.dll", "python312.dll", "python3.dll", "_internal/base_library.zip"]
        for rel in critical:
            p = dist_dir / rel
            if p.exists():
                try:
                    size_mb = p.stat().st_size / (1024 * 1024)
                    print(f"  ✓ {rel}: {size_mb:.1f} MB")
                except Exception:
                    print(f"  ✓ {rel}")
            else:
                print(f"  ✗ {rel}: MISSING")

        dlls = list(dist_dir.glob("*.dll"))
        print(f"\nDLLs found: {len(dlls)}")
        for dll in dlls[:10]:
            print(f"  - {dll.name}")
    else:
        print(f"✗ Dist folder not found: {dist_dir.absolute()}")

    print(f"\nPython version: {sys.version}")
    print(f"Python executable: {sys.executable}")

    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print("✓ Running in virtual environment")
    else:
        print("✗ Not in virtual environment")

    exe_path = dist_dir / f"{dist_dir.name}.exe"
    if exe_path.exists():
        print(f"\nTrying to run {exe_path} briefly...")
        try:
            # Try a quick spawn that will time out if GUI waits
            result = subprocess.run([str(exe_path), "--version"], capture_output=True, text=True, timeout=5)
            print(f"Return code: {result.returncode}")
            if result.stdout:
                print(f"Stdout: {result.stdout}")
            if result.stderr:
                print(f"Stderr: {result.stderr}")
        except subprocess.TimeoutExpired:
            print("Executable timed out (likely waiting for GUI) — this is okay.")
        except FileNotFoundError as e:
            print(f"Error: {e}")
        except Exception as e:
            print(f"Error running exe: {e}")


if __name__ == "__main__":
    diagnose()
