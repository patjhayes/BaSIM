import sys
from pathlib import Path
import numpy as np
import pandas as pd

# Ensure src root on path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main_phase3_step32_time_varying import read_ts1_file

def main(ts1_path: str, preferred_index: int | None = 0):
    df = read_ts1_file(ts1_path, preferred_column=preferred_index)
    t_sec = df['time_hours'].values * 3600.0
    q = df['flow_m3s'].values
    _trap = getattr(np, 'trapezoid', np.trapz)
    vol = float(_trap(q, t_sec))
    print({
        'rows': int(len(df)),
        'duration_hr': float(df['time_hours'].max() if len(df) else 0.0),
        'peak_m3s': float(np.nanmax(q) if len(q) else 0.0),
        'volume_m3': vol,
        'file': ts1_path,
    })

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python ts1_check.py <path-to-ts1> [preferred_index]')
        sys.exit(1)
    path = sys.argv[1]
    idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    main(path, idx)
