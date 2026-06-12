import json
from pathlib import Path

# Ensure we can import from src
import sys
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from main_phase3_step32_time_varying import run_phase3_step32_with_config


def main():
    # Use one of the uploaded TS1 hydrographs
    ts1_dir = ROOT / "model_input" / "ts1_files" / "uploads"
    # Fallback to synthetic if none present
    ts1 = None
    if ts1_dir.exists():
        # Prefer a 1 hour or 3 hour burst for speed
        candidates = [
            next((p for p in ts1_dir.glob("*1 hour*Storm*.ts1")), None),
            next((p for p in ts1_dir.glob("*3 hour*Storm*.ts1")), None),
        ]
        for c in candidates:
            if c and c.exists():
                ts1 = str(c)
                break
        if ts1 is None:
            # pick any
            any_ts1 = next(iter(ts1_dir.glob("*.ts1")), None)
            if any_ts1:
                ts1 = str(any_ts1)

    # Build a config emphasizing faster post-storm drainage and stronger boundaries
    config = {
        "scenario_title": "Calibration_FastDrain",
        "model_tag": "calib",
        "basin_geometry": {
            # Keep a modest basin to keep runtime reasonable
            "length_floor": 9.0,
            "width_floor": 11.0,
            "max_depth": 2.0,
            "side_slope_hv": 2.0,
            "floor_elev": 10.0,
        },
        "aquifer": {
            # Keep K moderate; we'll use strong edge boundary to carry water away
            "k_horizontal_mpd": 10.0,
            "k_vertical_mpd": 10.0,
            "sy": 0.15,
            "ss": 1e-7,
            # Deep water table to stress infiltration; engine will auto-raise if too close to floor
            "initial_head": -5.0,
            "bottom_elev": -24.0,
        },
        "infiltration": {
            "mode": "full",  # bottom + banks
            "bed_thickness_m": 0.1,
            "bed_k_mpd": 10.0,
            "side_k_mpd": 10.0,
        },
        # Post-storm duration/resolution: longer and finer to observe recession
        "post_storm_days": 3.0,
        "post_storm_step_hours": 6.0,

        # Stronger edge boundary to avoid backpressure; slight head offset
        "boundary_conductance_multiplier": 400.0,
        "boundary_head_offset_m": 0.3,
        "boundary_layers": "all",

        # Increase effective lakebed/bank leakance
        "bed_leak_multiplier": 8.0,

        # Keep outputs light but preserve CSVs
        "lightweight_outputs": True,
        "cleanup_heavy": True,
    }

    ok, summary_or_sim, outdir = run_phase3_step32_with_config(ts1, config)
    # Save a quick run summary file if available
    if isinstance(summary_or_sim, dict):
        try:
            p = Path(outdir) / "run_summary.json"
            p.write_text(json.dumps(summary_or_sim, indent=2))
        except Exception:
            pass
    print(f"\nDone. Success={ok}. Outputs at: {outdir}")


if __name__ == "__main__":
    main()
