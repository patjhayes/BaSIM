import sys
import json
import re
from pathlib import Path
import numpy as np
import pandas as pd
from typing import Optional

try:
    # FloPy is already a project dependency
    from flopy.utils.binaryfile import CellBudgetFile
except Exception:
    CellBudgetFile = None

# Ensure src root on path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main_phase3_step32_time_varying import run_phase3_step32_with_config, read_ts1_file

def integrate_ts1(ts1_path: str, preferred_index: int = 0) -> float:
    df = read_ts1_file(ts1_path, preferred_column=preferred_index)
    t_sec = df['time_hours'].values * 3600.0
    q = df['flow_m3s'].values
    _trap = getattr(np, 'trapezoid', np.trapz)
    return float(_trap(q, t_sec))

def parse_lak_budget_txt(budget_path: Path, stress_periods: list[list[float]] | None = None) -> float:
    """Parse the LAK budget text and compute total inflow volume in m3.

    We expect each period block to have a comment with inflow in m3/day.
    We'll read those values in order and multiply by the corresponding
    stress period lengths (in days) to get volume. If stress_periods are
    not provided, we try to infer count and assume uniform length.
    """
    if not budget_path.exists():
        return float('nan')
    inflow_m3day = []
    pat_cmt = re.compile(r"inflow\s*=\s*([0-9eE+\-.]+)\s*m3/s\s*\(([0-9eE+\-.]+)\s*m3/day\)", re.IGNORECASE)
    pat_dayonly = re.compile(r"\(([0-9eE+\-.]+)\s*m3/day\)")
    with budget_path.open('r', encoding='utf-8', errors='ignore') as f:
        for ln in f:
            ln_low = ln.lower()
            if 'inflow' in ln_low:
                m = pat_cmt.search(ln)
                if m:
                    try:
                        inflow_m3day.append(float(m.group(2)))
                        continue
                    except Exception:
                        pass
                m2 = pat_dayonly.search(ln)
                if m2:
                    try:
                        inflow_m3day.append(float(m2.group(1)))
                        continue
                    except Exception:
                        pass
    if not inflow_m3day:
        return 0.0
    # determine period lengths in days
    if stress_periods:
        lengths_days = [float(sp[0]) / 24.0 for sp in stress_periods]
    else:
        # assume 1 period per entry and 1-hour steps
        lengths_days = [1.0/24.0] * len(inflow_m3day)
    total = 0.0
    for v_day, Ld in zip(inflow_m3day, lengths_days):
        total += max(0.0, v_day) * Ld
    return total

def parse_lak_input_for_inflow_volume(lak_path: Path, stress_periods: list[list[float]]) -> float:
    """Parse our generated .lak input file comments to compute inflow volume.

    We write lines like:
      # Stress period N: inflow = X m3/s (Y m3/day)
    We'll extract Y for each period and multiply by SP length (days).
    """
    if not lak_path.exists():
        return float('nan')
    vals = []
    pat = re.compile(r"Stress period\s+(\d+):\s*inflow\s*=\s*([0-9eE+\-.]+)\s*m3/s\s*\(([0-9eE+\-.]+)\s*m3/day\)", re.IGNORECASE)
    with lak_path.open('r', encoding='utf-8', errors='ignore') as f:
        for ln in f:
            m = pat.search(ln)
            if m:
                try:
                    spn = int(m.group(1))
                    m3day = float(m.group(3))
                    vals.append((spn, m3day))
                except Exception:
                    pass
    if not vals:
        return 0.0
    # Sort by SP number
    vals.sort(key=lambda x: x[0])
    total = 0.0
    for idx, (spn, m3day) in enumerate(vals):
        if idx >= len(stress_periods):
            break
        Lh = float(stress_periods[idx][0])
        Ld = Lh / 24.0
        total += max(0.0, m3day) * Ld
    return total

def integrate_lak_inflow_from_binary(budget_path: Path) -> Optional[float]:
    """Integrate LAK external inflow volume (m3) from a binary budget file.

    The LAK package's BUDGET FILEOUT is a binary budget. We sum the EXT-INFLOW
    rates (m3/day) over time, multiplying by dt (days) between recorded times.

    Returns None if the file or required reader isn't available.
    """
    if not budget_path.exists() or CellBudgetFile is None:
        return None
    try:
        cbf = CellBudgetFile(str(budget_path))
        times = cbf.get_times()  # model time in days
        if not times:
            return 0.0
        # Ensure strictly increasing
        times = sorted(times)
        wanted_labels = [
            b"EXT-INFLOW",  # common MF6 label for external inflow to LAK
            b"INFLOW",      # fallback label just in case
        ]
        def _get_rate_at_time(t):
            # Try each label until we find data; sum across all lakes
            for lab in wanted_labels:
                try:
                    recs = cbf.get_data(text=lab, totim=t)
                    if not recs:
                        continue
                    total_rate = 0.0
                    for arr in recs:
                        # arr can be a numpy recarray or ndarray
                        try:
                            # Many MF6 package budgets return a recarray with field 'q'
                            if hasattr(arr, 'dtype') and 'q' in arr.dtype.names:
                                total_rate += float(np.nansum(arr['q']))
                            else:
                                # Otherwise treat as numeric array
                                total_rate += float(np.nansum(np.asanyarray(arr)))
                        except Exception:
                            total_rate += float(np.nansum(np.asanyarray(arr)))
                    return total_rate
                except Exception:
                    continue
            return 0.0

        total_volume_m3 = 0.0
        prev_t = times[0]
        prev_rate = _get_rate_at_time(prev_t)
        for t in times[1:]:
            dt_days = float(t - prev_t)
            # Trapezoidal in time with available rates
            cur_rate = _get_rate_at_time(t)
            avg_rate = 0.5 * (prev_rate + cur_rate)  # m3/day
            total_volume_m3 += max(0.0, avg_rate) * dt_days
            prev_t, prev_rate = t, cur_rate
        return total_volume_m3
    except Exception:
        return None

def main(ts1_path: str, preferred_index: int = 0):
    ts1_path = str(Path(ts1_path))
    print(f"TS1: {ts1_path}")
    v_ts1 = integrate_ts1(ts1_path, preferred_index)
    print(f"TS1-integrated volume (m3): {v_ts1:.2f}")

    config = {
        "model_tag": "cli-check",
        "basin_geometry": {
            "length_floor": 50.0,
            "width_floor": 50.0,
            "max_depth": 2.0,
            "side_slope_hv": 2.0,
            "floor_elev": 5.0,
        },
        "infiltration": {
            "mode": "vertical",
            "bed_thickness_m": 0.5,
            "bed_k_mpd": 5.0,
            "side_k_mpd": None,
        },
        "ts1_column_index": int(preferred_index),
    }

    ok, summary, outdir = run_phase3_step32_with_config(ts1_path, config)
    print(f"Run OK: {ok}")
    print(json.dumps(summary, indent=2))
    out = Path(outdir)
    lak_txt = out / 'basin_budget.txt'
    # build stress periods again to align lengths
    # Note: importing here to avoid circulars
    from main_phase3_step32_time_varying import create_time_varying_stress_periods
    df = read_ts1_file(ts1_path, preferred_column=preferred_index)
    sps, inflows = create_time_varying_stress_periods(df, total_duration_hours=48, post_storm_step_hours=12)
    # Binary budget integration (LAK BUDGET FILEOUT is binary in MF6)
    v_lak_bin = integrate_lak_inflow_from_binary(lak_txt)
    if v_lak_bin is not None:
        print(f"LAK budget inflow volume (m3) from binary budget: {v_lak_bin:.2f}")
    else:
        # Fallback to comment-based text parsing (will be zero for binary files)
        v_lak = parse_lak_budget_txt(lak_txt, stress_periods=sps)
        print(f"LAK budget inflow volume (m3) from budget text: {v_lak:.2f}")
    # Also compute from .lak input comments
    lak_input = out / 'bas32_vert.lak'
    v_lak_input = parse_lak_input_for_inflow_volume(lak_input, sps)
    print(f"LAK input inflow volume (m3) from .lak comments: {v_lak_input:.2f}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python run_full_check.py <path-to-ts1> [preferred_index]')
        sys.exit(1)
    path = sys.argv[1]
    idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    main(path, idx)
