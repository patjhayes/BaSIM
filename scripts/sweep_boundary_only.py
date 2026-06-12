import json
from pathlib import Path
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
    cols = [c.strip().lower() for c in df.columns]
    df.columns = cols
    # Normalize headers to ['time','lak_stage']
    if 'time' not in df.columns:
        for c in cols:
            if c.startswith('time'):
                df.rename(columns={c: 'time'}, inplace=True)
                break
    if 'lak_stage' not in df.columns:
        for c in cols:
            if 'lak' in c and 'stage' in c:
                df.rename(columns={c: 'lak_stage'}, inplace=True)
                break
    return df[['time', 'lak_stage']].sort_values('time').reset_index(drop=True)


def summarize_run(outdir: Path, crest: float, floor: float) -> dict:
    df = load_stage_csv(outdir)
    peak = float(df['lak_stage'].max())
    end = float(df['lak_stage'].iloc[-1])
    peak_idx = int(df['lak_stage'].idxmax())
    post = df.iloc[peak_idx:]
    # time to drop below crest after peak
    t_below_crest = None
    if peak > crest:
        below = post[post['lak_stage'] <= crest]
        if not below.empty:
            t_below_crest = float(below['time'].iloc[0])
    # time to floor + 0.10 m after peak
    t_to_10cm = None
    target = floor + 0.10
    near = post[post['lak_stage'] <= target]
    if not near.empty:
        t_to_10cm = float(near['time'].iloc[0])
    return {
        'peak_stage': peak,
        'end_stage': end,
        't_below_crest_days': t_below_crest,
        't_to_floor_plus_0p10_days': t_to_10cm,
    }


def main():
    # Locate an uploaded TS1 if provided
    ts1_dir = ROOT / "model_input" / "ts1_files" / "uploads"
    ts1 = None
    if ts1_dir.exists():
        any_ts1 = next(iter(ts1_dir.glob("*.ts1")), None)
        if any_ts1:
            ts1 = str(any_ts1)

    base_cfg = {
        "scenario_title": "Sweep_BoundaryOnly",
        "model_tag": "sweepb",
        "basin_geometry": {"length_floor": 9.0, "width_floor": 11.0, "max_depth": 2.0, "side_slope_hv": 2.0, "floor_elev": 10.0},
        "infiltration": {"mode": "full", "bed_thickness_m": 0.1, "bed_k_mpd": 10.0, "side_k_mpd": 10.0},
        "post_storm_days": 5.0,
        "post_storm_step_hours": 6.0,
        "boundary_layers": "all",
        "lightweight_outputs": True,
        "cleanup_heavy": True,
        # Force no lakebed scaling to test boundary-only hypothesis
        "bed_leak_multiplier": 1.0,
    }

    runs = []
    ghb_list = [100.0, 300.0, 800.0, 1200.0]
    k_list = [60.0, 100.0]  # m/day

    for kx in k_list:
        for gmult in ghb_list:
            cfg = json.loads(json.dumps(base_cfg))
            cfg["run_id"] = f"K{kx}_G{int(gmult)}_L1"
            cfg["aquifer"] = {"k_horizontal_mpd": kx, "k_vertical_mpd": kx, "sy": 0.07, "ss": 1e-7, "initial_head": -5.0, "bottom_elev": -24.0}
            cfg["boundary_conductance_multiplier"] = gmult
            cfg["boundary_head_offset_m"] = 0.3

            print(f"\n▶ Running K={kx} m/day, GHBx={gmult}, leakx=1.0 ...")
            ok, summary_or_sim, outdir = run_phase3_step32_with_config(ts1, cfg)
            outp = Path(outdir)
            meta = json.loads((outp / 'model_meta.json').read_text())
            crest = float(meta['crest_elev_mAHD'])
            floor = float(meta['floor_elev_mAHD'])
            summ = summarize_run(outp, crest, floor)
            rec = {"K": kx, "GHB_mult": gmult, "leak_mult": 1.0, **summ, "outdir": str(outdir)}
            runs.append(rec)
            print(rec)

    runs.sort(key=lambda r: (r['t_to_floor_plus_0p10_days'] if r['t_to_floor_plus_0p10_days'] is not None else 1e9))
    out_summary = ROOT / "model_output" / "phase3" / "step32" / "sweep_boundary_only.json"
    out_summary.write_text(json.dumps(runs, indent=2))
    print(f"\nSaved summary -> {out_summary}")
    if runs:
        print("\nBest (fastest to floor+0.10m):")
        print(json.dumps(runs[0], indent=2))


if __name__ == "__main__":
    main()
