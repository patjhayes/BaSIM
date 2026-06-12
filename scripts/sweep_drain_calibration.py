import json
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from main_phase3_step32_time_varying import run_phase3_step32_with_config
import pandas as pd


def load_stage_csv(outdir: Path) -> pd.DataFrame:
    p = outdir / "bas32_full_lak_stage.csv"
    df = pd.read_csv(p)
    # Normalize headers
    cols = [c.strip().lower() for c in df.columns]
    df.columns = cols
    # Expect 'time' in days and 'lak_stage'
    if 'time' not in df.columns:
        # MF6 sometimes uses 't' or similar; fallback
        for c in cols:
            if c.startswith('time'):
                df.rename(columns={c: 'time'}, inplace=True)
                break
    if 'lak_stage' not in df.columns:
        for c in cols:
            if 'lak' in c and 'stage' in c:
                df.rename(columns={c: 'lak_stage'}, inplace=True)
                break
    return df[['time', 'lak_stage']]


def summarize_run(outdir: Path, crest: float, floor: float) -> dict:
    df = load_stage_csv(outdir)
    df = df.sort_values('time').reset_index(drop=True)
    peak = float(df['lak_stage'].max())
    end = float(df['lak_stage'].iloc[-1])
    # time to drop below crest (if it spilled) AFTER the peak
    t_below_crest = None
    if peak > crest:
        peak_idx = int(df['lak_stage'].idxmax())
        after_peak = df.iloc[peak_idx:]
        below = after_peak[after_peak['lak_stage'] <= crest]
        if not below.empty:
            t_below_crest = float(below['time'].iloc[0])
    # time to near floor (floor + 0.10 m) AFTER the peak
    target = floor + 0.10
    t_to_10cm = None
    peak_idx = int(df['lak_stage'].idxmax())
    after_peak = df.iloc[peak_idx:]
    near = after_peak[after_peak['lak_stage'] <= target]
    if not near.empty:
        t_to_10cm = float(near['time'].iloc[0])
    return {
        'peak_stage': peak,
        'end_stage': end,
        't_below_crest_days': t_below_crest,
        't_to_floor_plus_0p10_days': t_to_10cm,
    }


def main():
    parser = argparse.ArgumentParser(description="Sweep drainage calibration parameters and summarize drawdown speed.")
    parser.add_argument("--quick", action="store_true", help="Run a very small sweep for a fast check")
    parser.add_argument("--ts1", type=str, default=None, help="Path to a TS1 file to use (optional)")
    args = parser.parse_args()

    ts1_dir = ROOT / "model_input" / "ts1_files" / "uploads"
    ts1 = None
    if args.ts1:
        ts1 = args.ts1
    elif ts1_dir.exists():
        any_ts1 = next(iter(ts1_dir.glob("*.ts1")), None)
        if any_ts1:
            ts1 = str(any_ts1)

    base_cfg = {
        "scenario_title": "Sweep_FastDrain",
        "model_tag": "sweep",
        "basin_geometry": {"length_floor": 9.0, "width_floor": 11.0, "max_depth": 2.0, "side_slope_hv": 2.0, "floor_elev": 10.0},
        "infiltration": {"mode": "full", "bed_thickness_m": 0.1, "bed_k_mpd": 10.0, "side_k_mpd": 10.0},
        "post_storm_days": 5.0,
        "post_storm_step_hours": 6.0,
        "boundary_layers": "all",
        "lightweight_outputs": True,
        "cleanup_heavy": True,
    }

    combos = []
    if args.quick:
        # Two aggressive settings to test sensitivity quickly
        for kx in (60.0, 100.0):  # m/day
            combos.append((kx, 800.0, 4.0))
    else:
        for kx in (30.0, 60.0, 100.0):  # m/day
            for ghb_mult in (300.0, 800.0):
                for leak_mult in (2.0, 4.0):
                    combos.append((kx, ghb_mult, leak_mult))

    results = []
    for idx, (kx, ghb_mult, leak_mult) in enumerate(combos, start=1):
        cfg = json.loads(json.dumps(base_cfg))
        cfg["run_id"] = f"K{kx}_G{int(ghb_mult)}_L{int(leak_mult)}"
        cfg["aquifer"] = {"k_horizontal_mpd": kx, "k_vertical_mpd": kx, "sy": 0.07, "ss": 1e-7, "initial_head": -5.0, "bottom_elev": -24.0}
        cfg["boundary_conductance_multiplier"] = ghb_mult
        cfg["boundary_head_offset_m"] = 0.3
        cfg["bed_leak_multiplier"] = leak_mult

        print(f"\n[{idx}/{len(combos)}] Running K={kx} m/day, GHBx={ghb_mult}, leakx={leak_mult}...")
        ok, summary_or_sim, outdir = run_phase3_step32_with_config(ts1, cfg)
        outp = Path(outdir)
        meta = json.loads((outp / 'model_meta.json').read_text())
        crest = float(meta['crest_elev_mAHD'])
        floor = float(meta['floor_elev_mAHD'])
        summ = summarize_run(outp, crest, floor)
        rec = {"K": kx, "GHB_mult": ghb_mult, "leak_mult": leak_mult, **summ, "outdir": str(outdir)}
        results.append(rec)
        print(rec)

    # Sort by earliest time to within 0.1 m of floor, then by lowest end_stage
    results.sort(key=lambda r: (r['t_to_floor_plus_0p10_days'] if r['t_to_floor_plus_0p10_days'] is not None else 1e9, r['end_stage']))
    out_summary = ROOT / "model_output" / "phase3" / "step32" / "sweep_results.json"
    out_summary.write_text(json.dumps(results, indent=2))
    print(f"\nSweep complete. Summary -> {out_summary}")
    if results:
        best = results[0]
        print("\nSuggested settings for faster drain:")
        print(json.dumps(best, indent=2))


if __name__ == "__main__":
    main()
