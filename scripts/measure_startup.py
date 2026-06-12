#!/usr/bin/env python3
"""Phase 10 helper: measure import/startup time for BaSIM launcher.

Usage:
  python scripts/measure_startup.py --dist dist/BaSIM --out dist/startup_metrics.json

Strategy:
  1. Spawn the frozen BaSIM.exe with BASIM_EXIT_AFTER_IMPORT=1 (we add a guard in launcher if desired later).
     For now, simulate a cold import by measuring a Python process that imports 'basim' source script.
  2. Record wall clock for import + creating app object (without entering mainloop).
  3. Enumerate largest directories/files in the distribution for size focus.

If a frozen exe exists, we measure its process start time until it exits (with a timeout) using a light
wrapper that sets PYTHONPATH to src for a source-based measurement fallback.

Outputs JSON like:
  {
    "method": "source-import",
    "import_seconds": 1.234,
    "top_dirs": [ {"path": "PyQt6", "mb": 80.5}, ... ],
    "top_files": [ {"path": "PyQt6\Qt6\bin\Qt6Gui.dll", "mb": 28.4}, ... ]
  }

We avoid external deps; pure stdlib.
"""
from __future__ import annotations
import argparse, json, os, sys, time, subprocess, statistics
from pathlib import Path

COUNT = 3  # repeated runs for average


def measure_source_import(project_root: Path) -> float:
    env = os.environ.copy()
    code = (
        "import time,importlib; t0=time.time();\n"
        "import basim as B;\n"
        "elapsed=time.time()-t0; print(elapsed)\n"
    )
    exe = sys.executable
    total = []
    for _ in range(COUNT):
        p = subprocess.run([exe, '-c', code], cwd=str(project_root), capture_output=True, text=True)
        try:
            val = float(p.stdout.strip().splitlines()[-1])
            total.append(val)
        except Exception:
            pass
    return statistics.mean(total) if total else -1.0


def enumerate_sizes(root: Path, limit_dirs: int = 12, limit_files: int = 15):
    root = root.resolve()
    size_by_dir = {}
    all_files = []
    for path in root.rglob('*'):
        if path.is_file():
            try:
                sz = path.stat().st_size
            except Exception:
                continue
            rel_dir = path.parent.relative_to(root)
            top_key = str(rel_dir).split(os.sep)[0] if rel_dir != Path('.') else path.name
            size_by_dir[top_key] = size_by_dir.get(top_key, 0) + sz
            all_files.append((sz, path))
    dirs_sorted = sorted(size_by_dir.items(), key=lambda x: x[1], reverse=True)[:limit_dirs]
    files_sorted = sorted(all_files, key=lambda x: x[0], reverse=True)[:limit_files]
    def mb(b):
        return round(b / (1024*1024), 2)
    return (
        [ {"path": d, "mb": mb(sz)} for d, sz in dirs_sorted ],
        [ {"path": str(p.relative_to(root)), "mb": mb(sz)} for sz, p in files_sorted ]
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dist', required=True, help='Path to dist/BaSIM onedir root')
    ap.add_argument('--out', required=True, help='Output JSON metrics file')
    args = ap.parse_args()
    dist_root = Path(args.dist)
    if not dist_root.exists():
        print('Distribution path not found', file=sys.stderr)
        return 2
    project_root = Path(__file__).resolve().parents[1]

    import_time = measure_source_import(project_root)
    top_dirs, top_files = enumerate_sizes(dist_root)
    data = {
        'method': 'source-import',
        'samples': COUNT,
        'import_seconds': import_time,
        'top_dirs': top_dirs,
        'top_files': top_files,
    }
    try:
        Path(args.out).write_text(json.dumps(data, indent=2), encoding='utf-8')
    except Exception as e:
        print(f'Failed to write metrics: {e}', file=sys.stderr)
        return 3
    print(f"Wrote metrics to {args.out}")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
