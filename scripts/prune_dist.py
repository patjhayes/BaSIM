#!/usr/bin/env python3
"""Post-build pruning script (Phase 6).

Removes test, example, demo, and heavy unused data directories from the PyInstaller onedir
bundle to reduce size. Run after PyInstaller build completes.

Actions:
 - Delete *tests* directories inside site-packages heavy libs (numpy, scipy, pandas, matplotlib, flopy)
 - Delete *example* or *examples* directories
 - Delete matplotlib sample_data
 - Summarize reclaimed bytes

Safe: Only removes clearly non-runtime assets.
"""
from __future__ import annotations
import os, sys, shutil
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]  # project root
DIST_BASE = ROOT / 'dist' / 'BaSIM'
INTERNAL = DIST_BASE / '_internal'

REMOVABLE_NAMES = [
    'tests', 'test', 'testing', 'Tests', 'Testing', 'examples', 'example', 'demo', 'demos', 'sample_data'
]
LIB_FOLDERS = ['numpy', 'scipy', 'pandas', 'matplotlib', 'flopy']

removed: list[tuple[Path,int]] = []

def dir_size(p: Path) -> int:
    total = 0
    for f in p.rglob('*'):
        if f.is_file():
            try:
                total += f.stat().st_size
            except Exception:
                pass
    return total


def should_remove(p: Path) -> bool:
    name = p.name.lower()
    return name in {n.lower() for n in REMOVABLE_NAMES}


def scan_and_remove(base: Path):
    if not base.exists():
        return
    for lib in LIB_FOLDERS:
        lp = base / lib
        if not lp.exists():
            continue
        for sub in lp.rglob('*'):
            if sub.is_dir() and should_remove(sub):
                try:
                    sz = dir_size(sub)
                    shutil.rmtree(sub, ignore_errors=True)
                    removed.append((sub, sz))
                except Exception:
                    pass


def main():
    if not INTERNAL.exists():
        print('internal folder not found, skipping prune', file=sys.stderr)
        return 0

    # Instead of fixed site-packages, libraries live directly under _internal
    pre_size = 0
    for f in INTERNAL.rglob('*'):
        if f.is_file():
            try:
                pre_size += f.stat().st_size
            except Exception:
                pass

    # Pass 1: targeted library subtrees
    scan_and_remove(INTERNAL)

    # Pass 2: generic pattern search (defensive — avoid nuking core code under src/)
    for d in list(INTERNAL.rglob('*')):
        if d.is_dir() and should_remove(d):
            # Skip if inside our application source tree
            if 'src' in d.parts:
                continue
            try:
                sz = dir_size(d)
                shutil.rmtree(d, ignore_errors=True)
                removed.append((d, sz))
            except Exception:
                pass

    post_size = 0
    for f in INTERNAL.rglob('*'):
        if f.is_file():
            try:
                post_size += f.stat().st_size
            except Exception:
                pass
    delta_mb = (pre_size - post_size)/1_048_576 if pre_size >= post_size else 0.0

    reclaimed = sum(sz for _, sz in removed)
    print(f"[prune] Removed {len(removed)} dirs; reclaimed {reclaimed/1_048_576:.2f} MB (delta scan {delta_mb:.2f} MB)")
    for p, sz in sorted(removed, key=lambda x: -x[1])[:20]:
        try:
            rel = p.relative_to(INTERNAL)
        except Exception:
            rel = p
        print(f"  - {rel} ({sz/1024:.1f} KB)")
    report_path = INTERNAL / 'PRUNE_REPORT.txt'
    try:
        with report_path.open('w', encoding='utf-8') as fh:
            fh.write('BaSIM Prune Report\n')
            fh.write('===================\n')
            fh.write(f'Total removed dirs: {len(removed)}\n')
            fh.write(f'Reclaimed (sum sizes): {reclaimed/1_048_576:.2f} MB\n')
            fh.write(f'Observed size delta: {delta_mb:.2f} MB\n')
            for p, sz in sorted(removed, key=lambda x: -x[1]):
                try:
                    rel = p.relative_to(INTERNAL)
                except Exception:
                    rel = p
                fh.write(f' - {rel} ({sz/1024:.1f} KB)\n')
    except Exception:
        pass
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
