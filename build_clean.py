"""Clean build script for BaSIM"""

import shutil
import subprocess
import sys
from pathlib import Path

def clean_build():
    print("BaSIM Clean Build Process")
    print("=" * 50)
    
    # 1. Clean all old builds
    print("\n1. Cleaning old builds...")
    for dir in ['build', 'dist', '__pycache__']:
        if Path(dir).exists():
            shutil.rmtree(dir)
            print(f"   Removed {dir}/")
    
    # Remove spec files
    for spec in Path('.').glob('*.spec'):
        spec.unlink()
        print(f"   Removed {spec}")
    
    # 2. Create a new minimal spec
    print("\n2. Creating new spec file...")
    spec_content = '''# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['basim.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('logo', 'logo'),
        ('src', 'src'),
    ],
    hiddenimports=['customtkinter', 'PIL._tkinter_finder'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BaSIM',
    debug=True,  # Enable debug
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # Show console for errors
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BaSIM',
)
'''
    
    with open('basim_clean.spec', 'w') as f:
        f.write(spec_content)
    
    # 3. Build
    print("\n3. Building with PyInstaller...")
    cmd = [sys.executable, '-m', 'PyInstaller', 'basim_clean.spec', '--clean']
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("   ✓ Build successful!")
    else:
        print("   ✗ Build failed!")
        print(result.stderr)
        return False
    
    # 4. Check output
    print("\n4. Checking output...")
    exe_path = Path('dist/BaSIM/BaSIM.exe')
    if exe_path.exists():
        print(f"   ✓ Executable created: {exe_path}")
        
        # List contents
        dist_dir = Path('dist/BaSIM')
        files = list(dist_dir.glob('*'))
        print(f"\n   Contents ({len(files)} items):")
        for f in sorted(files)[:10]:
            size = f.stat().st_size / 1024 / 1024 if f.is_file() else 0
            print(f"     - {f.name} ({size:.1f} MB)")
    else:
        print("   ✗ Executable not found!")
        return False
    
    return True

if __name__ == "__main__":
    if clean_build():
        print("\n✅ Build complete! Run: dist\\BaSIM\\BaSIM.exe")
    else:
        print("\n❌ Build failed!")