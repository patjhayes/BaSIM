"""
Grid Sensitivity Analyzer for BaSIM
-----------------------------------

Sweeps cell sizes and reports runtime and key metrics to help choose a default.

Usage (programmatic): call run_grid_sweep(config) from elsewhere.

Outputs:
- CSV summary under model_output/analysis/grid_sensitivity/<scenario>/summary.csv
- Optional plots (PNG) showing runtime vs. cell size and peak stage convergence.
"""
from __future__ import annotations

import time
from pathlib import Path
from dataclasses import dataclass
from typing import Iterable, Sequence
import sys

import numpy as np
import pandas as pd

# Ensure 'src' is on sys.path for imports when running this file directly
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC = _PROJECT_ROOT / 'src'
if str(_SRC) not in sys.path:
    sys.path.append(str(_SRC))

# Reuse the main runner
from main_phase3_step32_time_varying import run_phase3_step32_with_config


@dataclass
class SweepSpec:
    min_cell_sizes: Sequence[float] = (0.5, 1.0, 2.0, 3.0, 5.0)
    max_cell_size: float = 10.0
    refinement_zones: int = 3
    domain_factor: float | None = None  # default: use suggest_domain_factor


def _read_summary_json(model_dir: Path) -> dict:
    import json
    jf = model_dir / 'scenario_summary.json'
    if not jf.exists():
        return {}
    try:
        with open(jf, 'r') as fp:
            return json.load(fp)
    except Exception:
        return {}


def run_grid_sweep(
    ts1_path: str | None,
    base_config: dict,
    sweep: SweepSpec | None = None,
    out_dir: str | Path | None = None,
) -> Path:
    sweep = sweep or SweepSpec()
    scenario = str(base_config.get('scenario_title', 'Scenario 1'))
    project_root = Path(__file__).resolve().parents[2]
    analysis_root = Path(out_dir) if out_dir else (project_root / 'model_output' / 'analysis' / 'grid_sensitivity' / scenario)
    analysis_root.mkdir(parents=True, exist_ok=True)

    rows = []
    baseline_peak = None
    for msize in sweep.min_cell_sizes:
        msize = max(0.5, float(msize))  # enforce lower bound
        tag = f"min{msize:g}m"
        cfg = dict(base_config)
        cfg['grid'] = {
            'min_cell_size': float(msize),
            'max_cell_size': float(sweep.max_cell_size),
            'refinement_zones': int(sweep.refinement_zones),
            **({} if sweep.domain_factor is None else {'domain_factor': float(sweep.domain_factor)}),
        }
        cfg['lightweight_outputs'] = True
        cfg['cleanup_heavy'] = True
        cfg['output_variant_tag'] = tag

        t0 = time.perf_counter()
        ok, summary, model_dir = run_phase3_step32_with_config(ts1_path, cfg)
        dt = time.perf_counter() - t0
        if not ok:
            # still record the attempt
            rows.append({
                'min_cell_size_m': msize,
                'runtime_s': dt,
                'success': False,
            })
            continue
        s = _read_summary_json(Path(model_dir)) or (summary or {})
        peak = s.get('peak_stage_m')
        if peak is not None:
            peak = float(peak)
        if baseline_peak is None and peak is not None:
            baseline_peak = peak
        peak_delta = None
        if (baseline_peak is not None) and (peak is not None):
            peak_delta = float(peak - baseline_peak)

        rows.append({
            'min_cell_size_m': msize,
            'runtime_s': dt,
            'success': True,
            'peak_stage_m': peak,
            'peak_delta_m': peak_delta,
            'inflow_total_m3': s.get('inflow_total_m3'),
            'spill_detected': s.get('spill_detected'),
        })

    df = pd.DataFrame(rows).sort_values('min_cell_size_m')
    out_csv = analysis_root / 'summary.csv'
    df.to_csv(out_csv, index=False)

    # Optional plots
    try:
        import matplotlib as mpl
        mpl.use('Agg')
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 2, figsize=(11, 4))
        # runtime
        ax[0].plot(df['min_cell_size_m'], df['runtime_s'], 'o-', lw=2)
        ax[0].set_xlabel('Min cell size (m)')
        ax[0].set_ylabel('Runtime (s)')
        ax[0].grid(True, alpha=0.3)
        # peak convergence
        if 'peak_delta_m' in df.columns and df['peak_delta_m'].notna().any():
            ax[1].plot(df['min_cell_size_m'], df['peak_delta_m'], 's-', lw=2)
            ax[1].axhline(0.0, color='gray', ls='--', lw=1)
            ax[1].set_ylabel('Peak stage delta vs baseline (m)')
        else:
            ax[1].text(0.5, 0.5, 'No peak metrics available', ha='center', va='center', transform=ax[1].transAxes)
        ax[1].set_xlabel('Min cell size (m)')
        ax[1].grid(True, alpha=0.3)
        fig.suptitle('Grid Sensitivity')
        fig.tight_layout()
        fig.savefig(analysis_root / 'plots.png', dpi=150)
        plt.close(fig)
    except Exception:
        pass

    return out_csv


if __name__ == '__main__':
    # Minimal default run with synthetic storm if TS1 not provided
    scenario_cfg = {
        'scenario_title': 'Sensitivity Default',
        'model_tag': 'sens',
        'basin_geometry': {
            'length_floor': 50.0,
            'width_floor': 50.0,
            'max_depth': 2.0,
            'side_slope_hv': 2.0,
            'floor_elev': 5.0,
        },
        'aquifer': {
            'initial_head': 5.0,
            'k_horizontal_mpd': 20.0,
            'k_vertical_mpd': 5.0,
            'sy': 0.05,
            'ss': 1e-5,
        },
        'infiltration': {
            'mode': 'vertical',
            'bed_thickness_m': 0.5,
            'bed_k_mpd': 5.0,
        },
        # no output_variant_tag here; analyzer sets it per sweep item
    }
    run_grid_sweep(ts1_path=None, base_config=scenario_cfg)
