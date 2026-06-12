#!/usr/bin/env python3
"""
BASIN INFILTRATION SIMULATOR (BaSIM)
Phase 3, Step 3.2: Time-Varying Inputs Integration

This module implements time-varying storm inputs using TS1 file data
integrated with the LAK (Lake) package for realistic storm event modeling.

Features:
- TS1 file reading and processing
- Time-varying inflow rates to LAK package
- Storm hydrograph integration
- Dynamic lake level modeling
- Enhanced convergence monitoring

Author: BaSIM Development Team
Date: August 2025
"""

import os
import sys
import numpy as np
# Avoid importing interactive pyplot at module import time; use Agg if needed
try:
    import matplotlib as _mpl
    _mpl.use('Agg')
    import matplotlib.pyplot as plt
except Exception:
    plt = None
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import flopy

# Add src directory to path for imports
src_dir = Path(__file__).parent
sys.path.append(str(src_dir))

# Import BaSIM modules
from utils.grid_builder import create_adaptive_refined_grid, visualize_grid_refinement
from utils.lak_utils import BasinGeometry, generate_tapered_laktab, write_laktab_file, suggest_domain_factor
from utils.visualization import BasinVisualizationSuite
from utils.mf6_locator import find_mf6_exe
from utils.outlet_hydraulics import create_outlet_from_config, apply_outlet_to_results

# --- Utilities for LAK all-observations output (CSV/Parquet) ---
def _read_lak_allobs_df(model_dir: str | Path, model_name: str):
    """Load the LAK all-observations table, preferring Parquet then CSV.

    Returns a pandas DataFrame or None if not found/parsable.
    """
    try:
        p = Path(model_dir)
        pq = p / f"{model_name}_lak_allobs.parquet"
        if pq.exists():
            try:
                return pd.read_parquet(pq)
            except Exception:
                pass
        csv = p / f"{model_name}_lak_allobs.csv"
        if csv.exists():
            try:
                return pd.read_csv(csv)
            except Exception:
                pass
        gz = p / f"{model_name}_lak_allobs.csv.gz"
        if gz.exists():
            try:
                return pd.read_csv(gz)
            except Exception:
                pass
        # Fallback: if naming varied, try glob
        try:
            any_pq = sorted(p.glob("*_lak_allobs.parquet"), key=lambda x: x.stat().st_mtime, reverse=True)
            if any_pq:
                return pd.read_parquet(any_pq[0])
            for pat in ("*_lak_allobs.csv", "*_lak_allobs.csv.gz"):
                any_csv = sorted(p.glob(pat), key=lambda x: x.stat().st_mtime, reverse=True)
                if any_csv:
                    return pd.read_csv(any_csv[0])
        except Exception:
            pass
    except Exception:
        pass
    return None

def validate_basin_configuration(basin_geom, initial_groundwater_head, bottom_elev: float | None):
    """Validate basin vs aquifer setup and return warnings list.

    - Warn if basin floor is too close to groundwater
    - Warn if basin depth is large relative to aquifer thickness
    - Warn if side-slope is steep
    - Warn if basin footprint is tiny (grid resolution issues)
    """
    warnings: list[str] = []
    try:
        # Floor vs GW
        if basin_geom.floor_elev <= float(initial_groundwater_head) + 0.3:
            warnings.append(
                f"Basin floor ({basin_geom.floor_elev:.2f} m) is close to groundwater ({float(initial_groundwater_head):.2f} m)."
            )
        # Depth vs aquifer thickness
        if bottom_elev is not None:
            try:
                basin_top = float(basin_geom.floor_elev + basin_geom.max_depth)
                aquifer_thk = float(basin_top - float(bottom_elev))
                if aquifer_thk > 0 and float(basin_geom.max_depth) > 0.4 * aquifer_thk:
                    warnings.append(
                        f"Basin depth ({float(basin_geom.max_depth):.2f} m) is >40% of aquifer thickness ({aquifer_thk:.2f} m)."
                    )
            except Exception:
                pass
        # Side slope
        if float(basin_geom.side_slope_hv) < 1.5:
            warnings.append(f"Steep side slope ({float(basin_geom.side_slope_hv):.1f}:1) may reduce stability.")
        # Small footprint
        area = float(basin_geom.length_floor) * float(basin_geom.width_floor)
        if area < 100.0:
            warnings.append(f"Small basin floor area ({area:.0f} m²) may cause numerical sensitivity.")
    except Exception:
        pass
    return warnings

def visualize_results(model_dir, model_name, nrow, ncol, delr, delc):
    """Create a stage time series plot from OBS CSV and max groundwater head contours from HDS."""
    import pandas as pd
    import matplotlib.pyplot as plt
    from pathlib import Path
    import flopy.utils.binaryfile as bf

    model_path = Path(model_dir)

    # Try to read model metadata for crest elevation and spill settings
    crest_elev = None
    try:
        meta = None
        meta_path = model_path / 'model_meta.json'
        if meta_path.exists():
            import json as _json
            with open(meta_path, 'r') as _fp:
                meta = _json.load(_fp)
        if meta:
            crest_elev = float(meta.get('crest_elev_mAHD'))
    except Exception:
        crest_elev = None

    # 1) Plot lake stage time series from CSV produced by OBS6
    obs_csv = model_path / f"{model_name}_lak_stage.csv"
    spill_detected = False
    spill_amount_max = 0.0
    if obs_csv.exists():
        try:
            df = pd.read_csv(obs_csv)
            # Expected columns: time, lak_stage
            # MF6 UTLOBS6 CSV header often: time, lak_stage
            time = df.iloc[:, 0]
            stage = df.iloc[:, 1]
            fig = plt.figure(figsize=(10, 5))
            plt.plot(time, stage, 'b-', lw=2, label='Stage (current)')
            # Spill annotation if crest is known
            if crest_elev is not None:
                try:
                    plt.axhline(crest_elev, color='tomato', ls='--', lw=1.5, label='Crest')
                    y_max = np.nanmax(stage.values.astype(float))
                    if y_max > crest_elev + 1e-6:
                        spill_detected = True
                        spill_amount_max = float(y_max - crest_elev)
                        plt.fill_between(time.values, crest_elev, y_max, color='red', alpha=0.08)
                except Exception:
                    pass
            prev = model_path / f"{model_name}_lak_stage_prev.csv"
            if prev.exists():
                try:
                    dfp = pd.read_csv(prev)
                    plt.plot(dfp.iloc[:,0], dfp.iloc[:,1], 'r--', lw=1.5, label='Stage (previous)')
                except Exception:
                    pass
            plt.xlabel('Time (days)')
            plt.ylabel('Lake Stage (m)')
            ttl = 'Basin Stage Time Series (LAK OBS)'
            if spill_detected:
                # Avoid emoji to prevent matplotlib font glyph warnings
                ttl += '  SPILL'
            plt.title(ttl)
            plt.legend()
            plt.grid(True, alpha=0.3)
            out_png = model_path / 'stage_timeseries.png'
            plt.savefig(out_png, dpi=200, bbox_inches='tight')
            fig.clf()
            plt.close(fig)
            print(f"   📈 Saved stage time series: {out_png.name}")
        except Exception as e:
            print(f"   ⚠️ Could not parse LAK OBS CSV: {e}")
    else:
        print(f"   ⚠️ LAK OBS CSV not found: {obs_csv.name}")

    # 1b) Combined inflow (m3/s) and stage (m) overlay using MODFLOW LAK observations
    dfs = _read_lak_allobs_df(model_path, model_name)
    if dfs is not None:
        try:
            # Normalize headers to upper for robust access
            dfs.columns = [str(c).strip().upper() for c in dfs.columns]
            # Use time, LAK_STAGE, and LAK_EXT_INFLOW from MODFLOW output for synchronized data
            ts = dfs['TIME'].values
            # Accept either LAK_STAGE or LAK_STAGE (normalized)
            stg = dfs.get('LAK_STAGE', dfs.iloc[:,1]).values
            # Use actual MODFLOW inflow (synchronized with stage)
            qi = dfs.get('LAK_EXT_INFLOW', None)
            if qi is None:
                raise KeyError('LAK_EXT_INFLOW column not found in allobs CSV')
            # LAK_EXT_INFLOW is reported in model length^3 / time units (m3/day)
            qi = qi.values / 86400.0
            
            fig = plt.figure(figsize=(10, 5))
            ax1 = plt.gca()
            l1 = ax1.plot(ts, stg, 'b-', lw=2, label='Stage (m)')
            ax1.set_xlabel('Time (days)')
            ax1.set_ylabel('Stage (m)', color='b')
            ax1.tick_params(axis='y', labelcolor='b')
            ax2 = ax1.twinx()
            l2 = ax2.plot(ts, qi, 'r--', lw=1.8, label='Inflow (m3/s)')
            ax2.set_ylabel('Inflow (m3/s)', color='r')
            ax2.tick_params(axis='y', labelcolor='r')
            # Crest and spill shading
            if crest_elev is not None:
                try:
                    ax1.axhline(crest_elev, color='tomato', ls='--', lw=1.5, label='Crest')
                    y_max = float(np.nanmax(stg.astype(float)))
                    if y_max > crest_elev + 1e-6:
                        spill_detected = True
                        spill_amount_max = max(spill_amount_max, y_max - crest_elev)
                        ax1.fill_between(ts, crest_elev, y_max, color='red', alpha=0.08)
                except Exception:
                    pass
            # build a combined legend
            lines = l1 + l2
            labels = [l.get_label() for l in lines]
            ax1.legend(lines, labels, loc='upper right')
            ttl = 'Inflow vs Stage (MODFLOW Output)'
            if spill_detected:
                # Avoid emoji to prevent matplotlib font glyph warnings
                ttl += '  SPILL'
            plt.title(ttl)
            plt.grid(True, alpha=0.3)
            out_png = model_path / 'inflow_stage_overlay.png'
            plt.savefig(out_png, dpi=200, bbox_inches='tight')
            fig.clf()
            plt.close(fig)
            print(f"   📊 Saved inflow+stage overlay (MODFLOW): {out_png.name}")
        except Exception as e:
            print(f"   ⚠️ Could not generate overlay plot from MODFLOW data: {e}")
    else:
        print(f"   ⚠️ LAK OBS table not found for overlay plot")

    # 1c) Simple timeseries plots from MODFLOW output data only
    try:
        if dfs is not None:
            # Read MODFLOW output data (time in days, stage in m AHD, inflow in m3/s)
            cols = {str(c).strip().upper(): c for c in dfs.columns}
            t_stage_days = dfs[cols.get('TIME')].values.astype(float)
            stage_col = cols.get('LAK_STAGE')
            inflow_col = cols.get('LAK_EXT_INFLOW')
            if stage_col is None or inflow_col is None:
                raise KeyError('Required columns not found in allobs CSV')
            stage_m = dfs[stage_col].values.astype(float)
            # LAK_EXT_INFLOW is in m3/day; convert to m3/s for plotting/logging
            q_m3s = dfs[inflow_col].values.astype(float) / 86400.0

            if len(t_stage_days) >= 2:
                
                # Time axis in hours for plotting
                th = t_stage_days * 24.0

                # Plot inflow vs stage - basic overlay for synchronization check
                fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
                
                # Inflow subplot
                ax1.plot(th, q_m3s, color='#1f77b4', lw=2.0, label='Inflow (MODFLOW)')
                ax1.set_ylabel('Inflow (m³/s)', color='#1f77b4')
                ax1.tick_params(axis='y', labelcolor='#1f77b4')
                ax1.grid(True, alpha=0.3)
                ax1.legend(loc='upper left')
                
                # Stage subplot
                ax2.plot(th, stage_m, color='#ff7f0e', lw=2.0, label='Stage (MODFLOW)')
                ax2.set_ylabel('Stage (m AHD)', color='#ff7f0e')
                ax2.tick_params(axis='y', labelcolor='#ff7f0e')
                ax2.set_xlabel('Time (hours)')
                ax2.grid(True, alpha=0.3)
                ax2.legend(loc='upper left')
                
                plt.title('Inflow and Stage Response (MODFLOW Output Only)')
                plt.tight_layout()
                out_png = model_path / 'inflow_stage_modflow_only.png'
                plt.savefig(out_png, dpi=200, bbox_inches='tight')
                fig.clf()
                plt.close(fig)
                print(f"   📈 Saved MODFLOW-only inflow/stage plot: {out_png.name}")

                # Diagnostic: peak timing lag between inflow and stage
                try:
                    i_q = int(np.nanargmax(q_m3s))
                    i_s = int(np.nanargmax(stage_m))
                    lag_hr = abs((th[i_s] - th[i_q]))
                    print(f"   🕒 Peak stage lags inflow by ~{lag_hr:.2f} hours (MODFLOW data)")
                    print(f"   📊 Peak inflow: {np.max(q_m3s):.3f} m³/s at {th[i_q]:.1f} hours")
                    print(f"   📊 Peak stage: {np.max(stage_m):.3f} m at {th[i_s]:.1f} hours")
                except Exception:
                    pass
    except Exception as e:
        print(f"   ⚠️ Could not generate MODFLOW-only plots: {e}")

    # 1d) If full LAK observations exist, export tidy timeseries and summary
    try:
        df_all = _read_lak_allobs_df(model_path, model_name)
        if df_all is not None:
            if df_all.shape[0] >= 1:
                # Normalize column names
                df_all.columns = [str(c).strip().lower().replace('-', '_') for c in df_all.columns]
                # Heuristic: MF6 UTLOBS6 usually has first column 'time'
                if 'time' not in df_all.columns and len(df_all.columns) > 0:
                    df_all.rename(columns={df_all.columns[0]: 'time'}, inplace=True)
                # Convert all columns that look numeric and sanitize MF6 sentinel values (e.g., 3e+30)
                for c in list(df_all.columns):
                    try:
                        df_all[c] = pd.to_numeric(df_all[c], errors='coerce')
                    except Exception:
                        pass
                # Replace absurd magnitudes with NaN (common in UTLOBS6 for N/A terms)
                try:
                    df_all = df_all.mask(df_all > 1.0e20, np.nan)
                    df_all = df_all.mask(df_all < -1.0e20, np.nan)
                except Exception:
                    pass
                # Add convenience conversions
                if 'time' in df_all.columns:
                    # Add derived time columns in a single operation to avoid fragmentation
                    _time_days = pd.to_numeric(df_all['time'], errors='coerce')
                    _time_hours = _time_days * 24.0
                    df_all = df_all.assign(time_days=_time_days, time_hours=_time_hours).copy()
                # Write tidy timeseries (changed to Parquet for better performance/storage)
                out_all = model_path / 'lak_observations_timeseries.parquet'
                df_all.to_parquet(out_all, index=False)
                # Build a small summary at final time for key terms
                key_cols = [c for c in df_all.columns if c.startswith('lak_') or c.startswith('wetted_area_') or c.startswith('conductance_')]
                if len(key_cols) > 0:
                    last = df_all.iloc[[max(0, len(df_all) - 1)]]
                    cols = (['time_days'] if 'time_days' in last.columns else []) + key_cols
                    last[cols].to_csv(model_path / 'lak_observations_summary.csv', index=False)
                print("   📄 Exported LAK observations timeseries and summary")
    except Exception as e:
        print(f"   ⚠️ Could not export LAK observation timeseries/summary: {e}")

    # 2) Compute and plot max groundwater head RISE (relative to baseline) over time
    hds_file = model_path / f"{model_name}.hds"
    if hds_file.exists():
        try:
            hds = bf.HeadFile(str(hds_file))
            times = hds.get_times()
            # Choose layer with most valid heads at first timestep
            data0 = hds.get_data(totim=times[0])
            best_layer = 0
            if data0.ndim == 3:
                counts = []
                for k in range(data0.shape[0]):
                    a0 = data0[k].astype(float)
                    a0[a0 <= -1e29] = np.nan
                    counts.append(np.count_nonzero(~np.isnan(a0)))
                if len(counts) > 0:
                    best_layer = int(np.argmax(counts))

            # Accumulate max head per cell across all times for selected layer
            max_head = None
            baseline = None
            for idx, t in enumerate(times):
                data = hds.get_data(totim=t)  # shape (nlay, nrow, ncol)
                layer_arr = data[best_layer]
                if idx == 0:
                    baseline = layer_arr.copy()
                if max_head is None:
                    max_head = layer_arr.copy()
                else:
                    max_head = np.maximum(max_head, layer_arr)

            # Compute head rise (mounding) relative to baseline at first time
            # Treat sentinel very negative heads as NaN and clip negative rises to 0
            # Build coordinate arrays; delr/delc may be scalars or 1D arrays
            delr_arr = np.array(delr) if hasattr(delr, '__len__') else np.full(ncol, delr)
            delc_arr = np.array(delc) if hasattr(delc, '__len__') else np.full(nrow, delc)
            x_edges = np.concatenate(([0.0], np.cumsum(delr_arr)))
            y_edges = np.concatenate(([0.0], np.cumsum(delc_arr)))
            xc = (x_edges[:-1] + x_edges[1:]) / 2.0  # length ncol
            yc = (y_edges[:-1] + y_edges[1:]) / 2.0  # length nrow
            XC, YC = np.meshgrid(xc, yc)

            fig = plt.figure(figsize=(8, 7))
            # Ensure arrays are (nrow, ncol)
            arr_max = np.array(max_head)
            arr_base = np.array(baseline)
            arr_max = np.where(arr_max <= -1e29, np.nan, arr_max)
            arr_base = np.where(arr_base <= -1e29, np.nan, arr_base)
            mound = arr_max - arr_base
            mound = np.where(np.isnan(mound), np.nan, np.maximum(0.0, mound))
            # Flip vertically so row 0 (top) maps to highest Y
            arr_plot = np.flipud(mound)
            # Choose robust color levels up to 95th percentile to avoid outliers
            try:
                vmax = float(np.nanpercentile(arr_plot, 95))
                if not np.isfinite(vmax) or vmax <= 0:
                    vmax = float(np.nanmax(arr_plot)) if np.nanmax(arr_plot) > 0 else 0.1
            except Exception:
                vmax = float(np.nanmax(arr_plot)) if np.nanmax(arr_plot) > 0 else 0.1
            levels = np.linspace(0.0, vmax, 20)
            cf = plt.contourf(XC, YC, arr_plot, levels=levels, cmap='viridis')
            cbar = plt.colorbar(cf)
            cbar.set_label('Max head rise (m)')
            plt.gca().set_aspect('equal', adjustable='box')
            plt.xlabel('x (m)')
            plt.ylabel('y (m)')
            plt.title('Max Groundwater Head Rise (selected wet layer)')
            out_png2 = model_path / 'max_head_contours.png'
            plt.savefig(out_png2, dpi=200, bbox_inches='tight')
            fig.clf()
            plt.close(fig)
            print(f"   🗺️ Saved max head contours: {out_png2.name}")
        except Exception as e:
            print(f"   ⚠️ Could not generate head contours: {e}")
    else:
        print(f"   ⚠️ Head file not found: {hds_file.name}")

    # 3) Update combined stages overlay at scenario level (all runs under outputs/)
    try:
        model_path = Path(model_dir)
        scen_outputs = model_path.parent  # outputs/<short>
        scen_root = scen_outputs         # outputs/
        # Collect all stage CSVs under outputs/*
        stage_csvs = list(scen_root.glob("*/" + "*lak_stage.csv"))
        if len(stage_csvs) >= 1:
            fig = plt.figure(figsize=(10, 6))
            for csv in stage_csvs:
                try:
                    df = pd.read_csv(csv)
                    t = df.iloc[:, 0].values.astype(float)
                    y = df.iloc[:, 1].values.astype(float)
                    label = csv.parent.name
                    plt.plot(t, y, lw=1.6, label=label)
                except Exception:
                    continue
            plt.xlabel('Time (days)')
            plt.ylabel('Stage (m)')
            plt.title('All Run Stages')
            plt.grid(True, alpha=0.3)
            try:
                plt.legend(loc='best', fontsize=8, ncol=2)
            except Exception:
                pass
            out_png = scen_root / 'combined_stages.png'
            plt.savefig(out_png, dpi=200, bbox_inches='tight')
            fig.clf()
            plt.close(fig)
            print(f"   🧩 Saved combined stages overlay: {out_png.name}")
    except Exception:
        pass

    # If spill detected, write a warning file for GUI and users
    try:
        if spill_detected:
            warn = model_path / 'spill_warning.txt'
            msg = (
                "Basin spill detected (stage exceeded crest).\n"
                "Results beyond crest are for numerical stability only.\n"
                "You cannot rely on these results for sizing/assessment.\n"
            )
            if crest_elev is not None:
                msg += f"Crest elevation: {crest_elev:.3f} m AHD. Max exceedance: {spill_amount_max:.3f} m.\n"
            with open(warn, 'w') as fp:
                fp.write(msg)
            print("   🌊 Spill warning written: spill_warning.txt")
    except Exception:
        pass

    try:
        if plt is not None:
            plt.close('all')
    except Exception:
        pass

def read_ts1_file(
    ts1_path,
    preferred_column: int | None = None,
    sum_columns: bool = False,
    _internal_fallback: bool = False,
    allow_synthetic: bool = False,
):
    """
    Parse a External TS1 file strictly per spec:
      - Find the header row containing 'Time (...)'
      - First column is time; remaining columns are hydrographs
      - Time units are taken from '(min)' or '(hr/hour)'
      - Flow units default to m3/s unless header says L/s
      - Select exactly one data column (no implicit summing)

    Returns: DataFrame with columns time_hours, flow_m3s, time_minutes, datetime.
    """
    print(f"📊 Reading TS1 storm data from: {os.path.basename(ts1_path)}")

    # Optional env overrides for column selection
    env_col = os.getenv("BASIM_TS1_COLUMN")
    env_col_name = os.getenv("BASIM_TS1_COLUMN_NAME")
    if preferred_column is None and env_col is not None:
        try:
            preferred_column = int(env_col)
        except Exception:
            preferred_column = None

    try:
        with open(ts1_path, 'r', encoding='utf-8', errors='ignore') as f:
            raw_lines = [ln.strip() for ln in f.readlines()]

        # Locate header line ('Time (...)', per TUFLOW TS1)
        import re as _re
        header_idx = None
        for i, ln in enumerate(raw_lines):
            if not ln:
                continue
            low = ln.lower()
            # example: Time (min)
            if _re.search(r"\btime\s*\(.*\)", low) and ("," in ln or "\t" in ln):
                header_idx = i
                break
        if header_idx is None:
            raise ValueError("TS1 header row not found (expected 'Time (...)' line)")

        header_line = raw_lines[header_idx]
        # Preserve empty header tokens (don't collapse)
        header_tokens = [tok.strip() for tok in header_line.replace("\t", ",").split(",")]
        col_names = [t for t in header_tokens]

        # Data lines follow header
        data_lines = [ln for ln in raw_lines[header_idx + 1:] if ln and not ln.strip().startswith('!')]

        # Helper: split CSV preserving empty fields; fallback to whitespace if no commas
        def _split_preserve(line: str) -> list[str]:
            if "," in line or "\t" in line:
                s = line.replace("\t", ",")
                return [tok.strip() for tok in s.split(",")]
            # fallback: whitespace tokens
            return [tok for tok in line.split()]

        # Parse into numeric matrix, treating empty tokens as NaN
        rows = []
        maxw_seen = 0
        for ln in data_lines:
            toks = _split_preserve(ln)
            if not toks:
                continue
            nums = []
            for t in toks:
                tt = t.strip()
                if tt == "":
                    nums.append(np.nan)
                else:
                    try:
                        nums.append(float(tt))
                    except Exception:
                        # Non-numeric in data row -> treat as NaN
                        nums.append(np.nan)
            if any(np.isfinite(x) for x in nums):
                rows.append(nums)
                if len(nums) > maxw_seen:
                    maxw_seen = len(nums)

        if not rows:
            raise ValueError("No numeric content")

        # Rectangularize to max width seen; keep NaNs for missing series values
        import math
        maxw = maxw_seen if maxw_seen > 0 else max(len(r) for r in rows)
        for r in rows:
            if len(r) < maxw:
                r.extend([math.nan] * (maxw - len(r)))
        arr = np.array(rows, dtype=float)

        if arr.shape[1] < 2:
            raise ValueError("TS1 contains only time values (no flow columns)")

        # First column is time
        time_vals = arr[:, 0]

        # Sort by time and drop NaNs/duplicates
        mask = np.isfinite(time_vals)
        time_vals = time_vals[mask]
        arr = arr[mask, :]
        order = np.argsort(time_vals)
        time_vals = time_vals[order]
        arr = arr[order, :]

        # Candidate data columns are 1..n-1 with >=3 finite values
        data_cols = [c for c in range(1, arr.shape[1]) if np.count_nonzero(np.isfinite(arr[:, c])) >= 3]
        if not data_cols:
            raise ValueError("Found time column but no data columns")

        # Time units (TS1 spec uses minutes by default)
        header_lower = ",".join(header_tokens).lower()
        time_is_minutes = ("(min" in header_lower) or ("min)" in header_lower)
        time_is_hours = ("(hr" in header_lower) or ("(hour" in header_lower) or ("hours)" in header_lower)
        if not time_is_minutes and not time_is_hours:
            # Default to minutes per TUFLOW TS1
            time_is_minutes = True

        # Column selection: by name or index among data columns
        selected_col = data_cols[0]
        if env_col_name and col_names:
            target = env_col_name.strip().lower()
            for c in data_cols:
                if c < len(col_names) and col_names[c].strip().lower() == target:
                    selected_col = c
                    break
        if preferred_column is not None and 0 <= preferred_column < len(data_cols):
            selected_col = data_cols[preferred_column]

        # Flow values
        flow_vals = arr[:, selected_col]

        # Flow units from header
        ht = ",".join(header_tokens).lower() if header_tokens else ""
        flow_unit_factor = 1.0
        if "l/s" in ht and "m3/s" not in ht:
            flow_unit_factor = 0.001  # L/s -> m3/s

        flow_m3s = np.where(np.isfinite(flow_vals), flow_vals, 0.0) * flow_unit_factor
        time_hours = time_vals / 60.0 if time_is_minutes else time_vals

        # Drop duplicate times (keep first occurrence)
        t_unique, idx = np.unique(time_hours, return_index=True)
        order_idx = np.sort(idx)
        time_hours = time_hours[order_idx]
        flow_m3s = flow_m3s[order_idx]

        df = pd.DataFrame({"time_hours": time_hours, "flow_m3s": flow_m3s})
        df["time_minutes"] = df["time_hours"] * 60.0
        try:
            step_min_med = max(1.0, float(pd.Series(df['time_minutes']).diff().dropna().median()))
            freq = f"{int(round(step_min_med))}min"
        except Exception:
            freq = 'min'
        df['datetime'] = pd.date_range(start='2025-01-01', periods=len(df), freq=freq)

        print(f"   ✅ Loaded {len(df)} time steps")
        print(f"   ⏰ Duration: {df['time_hours'].max():.2f} hours")
        print(f"   🌊 Peak flow: {np.nanmax(df['flow_m3s'].values):.3f} m³/s")
        try:
            t_sec = df['time_hours'].values * 3600.0
            q = df['flow_m3s'].values
            vol = float(np.trapezoid(q, t_sec)) if hasattr(np, 'trapezoid') else float(np.trapz(q, t_sec))
            print(f"   💧 Total volume: {vol:.2f} m³")
        except Exception:
            pass

        return df

    except Exception as e:
        # Attempt companion file only for missing data content
        msg = str(e)
        print(f"   ❌ Error reading TS1 file: {e}")
        try:
            if not _internal_fallback and ("only time" in msg.lower() or "no data columns" in msg.lower() or "no numeric content" in msg.lower()):
                comp = find_companion_ts1(ts1_path)
                if comp:
                    print(f"   🔎 Found companion TS1 with data: {os.path.basename(comp)}")
                    return read_ts1_file(comp, preferred_column=preferred_column, sum_columns=sum_columns, _internal_fallback=True)
        except Exception as e2:
            print(f"   ⚠️ Companion TS1 search failed: {e2}")
        if allow_synthetic:
            print("   🔄 Generating synthetic storm hydrograph (testing mode)...")
            return generate_synthetic_storm()
        raise

def find_companion_ts1(ts1_path: str) -> str | None:
    """Given a TS1 path that lacks data, try to locate a sibling with the same storm descriptor.

    Example: cat1_Pipes_6EY AEP, 6 hour burst, Storm 3.ts1 ->
             cat1_Catchments_6EY AEP, 6 hour burst, Storm 3.ts1
    Priority: Catchments, Channels, then any other matching prefix.
    """
    p = Path(ts1_path)
    folder = p.parent

    name = p.name
    # Split into three parts: prefix, category, rest
    parts = name.split("_", 2)
    if len(parts) < 3:
        return None
    prefix, category, rest = parts[0], parts[1], parts[2]
    # Candidate prefixes to try
    categories = ["Catchments", "Channels"]
    for pref in categories:
        cand = folder / f"{prefix}_{pref}_{rest}"
        if cand.exists():
            # Ensure it actually contains data columns beyond time
            try:
                # Read first 200 lines and check for a comma after Time header
                with open(cand, 'r', encoding='utf-8', errors='ignore') as f:
                    head = f.read(4096)
                if 'Time' in head and ',' in head:
                    return str(cand)
            except Exception:
                return str(cand)
    # Fallback: scan folder for any file with same suffix
    for other in folder.glob(f"*_{rest}"):
        if other.name == name:
            continue
        return str(other)
    return None

def inspect_ts1_columns(ts1_path: str) -> dict:
    """Inspect a TS1 file and return column info for user selection.

    Returns a dict with keys:
      - source_path: actual file parsed (may be companion)
      - time_col: int index of time column
      - data_cols: list[int] indices of candidate data columns
      - labels: dict[int,str] mapping column index to label/name
    Raises if no numeric content is found in original or companion.
    """
    p = Path(ts1_path)
    source_path = str(p)
    try:
        with open(source_path, 'r', encoding='utf-8', errors='ignore') as f:
            raw_lines = [ln.strip() for ln in f.readlines()]
    except Exception as e:
        raise

    # Parse similarly to read_ts1_file, but stop before building dataframe
    header_tokens = []
    col_names = None
    lines = []
    saw_index_marker = False
    for ln in raw_lines:
        if not ln:
            continue
        if ln.strip().startswith('!'):
            continue
        low = ln.lower()
        if low.startswith("start_index") or low.startswith("end_index"):
            saw_index_marker = True
            continue
        if ("time" in low) and ("(" in ln and ")" in ln):
            # Preserve empty header tokens
            header_tokens = [tok.strip() for tok in ln.replace("\t", ",").split(",")]
            col_names = [t for t in header_tokens]
            continue
        lines.append(ln)

    def _split_preserve(line: str) -> list[str]:
        if "," in line or "\t" in line:
            return [tok.strip() for tok in line.replace("\t", ",").split(",")]
        return [tok for tok in line.split()]

    rows = []
    maxw_seen = 0
    for ln in lines:
        toks = _split_preserve(ln)
        if not toks:
            continue
        nums = []
        for t in toks:
            tt = t.strip()
            if tt == "":
                nums.append(np.nan)
            else:
                try:
                    nums.append(float(tt))
                except ValueError:
                    nums.append(np.nan)
        if any(np.isfinite(x) for x in nums):
            rows.append(nums)
            if len(nums) > maxw_seen:
                maxw_seen = len(nums)

    if not rows:
        # try companion file
        comp = find_companion_ts1(source_path)
        if comp:
            source_path = comp
            with open(source_path, 'r', encoding='utf-8', errors='ignore') as f:
                raw_lines = [ln.strip() for ln in f.readlines()]
            header_tokens = []
            col_names = None
            lines = []
            saw_index_marker = False
            for ln in raw_lines:
                if not ln:
                    continue
                if ln.startswith('!'):
                    continue
                low = ln.lower()
                if low in {"start_index", "end_index"}:
                    saw_index_marker = True
                    continue
                if "time" in low and "(" in ln and ")" in ln:
                    header_tokens = [tok.strip() for tok in ln.replace("\t", ",").split(",") if tok.strip()]
                    col_names = [t for t in header_tokens]
                    continue
                lines.append(ln)
            rows = []
            for ln in lines:
                toks = [t for t in ln.replace("\t", ",").split(",") if t != ""]
                if len(toks) == 1:
                    toks = ln.split()
                nums = []
                for t in toks:
                    try:
                        nums.append(float(t))
                    except ValueError:
                        pass
                if nums:
                    rows.append(nums)
        if not rows:
            raise ValueError("No numeric content in TS1 or companion")

    # Normalize and trim
    import math
    maxw = maxw_seen if maxw_seen > 0 else max(len(r) for r in rows)
    for r in rows:
        if len(r) < maxw:
            r.extend([math.nan] * (maxw - len(r)))
    arr = np.array(rows, dtype=float)

    if saw_index_marker and arr.shape[0] >= 2 and arr.shape[1] >= 2:
        first_two_ints = np.all(np.isfinite(arr[0, :2])) and np.all(np.mod(arr[0, :2], 1.0) == 0.0)
        if first_two_ints:
            arr = arr[1:, :]

    # Determine time and data columns (TS1: first column is time)
    time_col = 0
    data_cols = [c for c in range(arr.shape[1]) if c != time_col]
    data_cols = [c for c in data_cols if np.count_nonzero(np.isfinite(arr[:, c])) >= 3]

    if len(data_cols) == 0:
        comp = find_companion_ts1(source_path)
        if comp and comp != source_path:
            # re-run on companion
            return inspect_ts1_columns(comp)
        raise ValueError("Found time column but no data columns in TS1")

    labels = {}
    if col_names:
        for c in data_cols:
            if c < len(col_names):
                labels[c] = col_names[c]
    # Fallback labels
    for c in data_cols:
        labels.setdefault(c, f"col{c}")

    return {
        "source_path": source_path,
        "time_col": int(time_col),
        "data_cols": [int(c) for c in data_cols],
        "labels": labels,
    }

def generate_synthetic_storm():
    """Generate synthetic storm hydrograph for testing"""
    # Create a realistic storm pattern (6-hour storm)
    duration_hours = 6
    time_step_minutes = 10
    total_steps = int(duration_hours * 60 / time_step_minutes)
    
    times = np.linspace(0, duration_hours, total_steps)
    
    # Double-peaked storm pattern
    peak1_time = 1.5  # hours
    peak2_time = 4.0  # hours
    peak1_intensity = 0.015  # m³/s
    peak2_intensity = 0.008  # m³/s
    
    flows = []
    for t in times:
        # Gaussian peaks
        flow1 = peak1_intensity * np.exp(-((t - peak1_time) / 0.5) ** 2)
        flow2 = peak2_intensity * np.exp(-((t - peak2_time) / 0.8) ** 2)
        base_flow = 0.001  # baseline infiltration
        total_flow = flow1 + flow2 + base_flow
        flows.append(max(0, total_flow))
    
    df = pd.DataFrame({
        'time_hours': times,
        'flow_m3s': flows,
        'time_minutes': times * 60,
    'datetime': pd.date_range(start='2025-01-01', periods=len(times), freq='10min')
    })
    
    print(f"   ✅ Generated synthetic storm: {len(df)} time steps")
    print(f"   🌊 Peak flow: {df['flow_m3s'].max():.3f} m³/s")
    
    return df

def create_time_varying_stress_periods(
    storm_data,
    total_duration_hours: float = 48,
    post_storm_step_hours: float = 1.0,
    *,
    # Pre-storm stabilization: a few short zero-inflow periods
    pre_storm_steps: int = 3,
    pre_storm_step_hours: float = 0.5,
    pre_storm_nstp: int = 5,
    # Adaptive refinement during steep hydrograph changes
    refine: bool = True,
    nstp_max: int = 12,
):
    """
    Create MODFLOW stress periods for time-varying inputs
    
    Parameters:
    -----------
    storm_data : pandas.DataFrame
        Storm hydrograph data
    total_duration_hours : float
        Total simulation duration
        
    Returns:
    --------
    list : Stress period data for MODFLOW
    """
    print(f"⏰ Creating time-varying stress periods for {storm_data.shape[0]} time steps...")
    
    # Create stress periods that match storm timing
    stress_periods: list[list[float | int]] = []
    # Aligned inflow per stress period (m3/s)
    inflow_m3s_per_sp: list[float] = []
    
    # Storm period (match hydrograph sample steps; assume uniform spacing if possible)
    times_h = np.asarray(storm_data['time_hours'].values, dtype=float)
    # sanitize: finite, sorted, unique
    times_h = times_h[np.isfinite(times_h)]
    if times_h.size == 0:
        raise ValueError("No valid time points for stress periods")
    times_h = np.sort(times_h)
    times_h = np.unique(times_h)
    storm_duration = float(times_h[-1])
    # compute step lengths from diffs and optional first step
    diffs = np.diff(times_h)
    step_lengths = [float(x) for x in diffs if x > 0]
    first = times_h[0]
    if first > 0:
        step_lengths.insert(0, float(first))
    
    storm_steps = len(step_lengths)
    print(f"   🌊 Storm period: {storm_duration:.1f} hours ({storm_steps} steps)")
    
    # Determine flow values aligned to each storm step (piecewise-constant per step)
    flows_h = np.asarray(storm_data['flow_m3s'].values, dtype=float)
    # Ensure flows are finite and aligned to sorted times
    if flows_h.size != times_h.size:
        # Fall back conservatively: truncate or pad with last value
        m = min(flows_h.size, times_h.size)
        flows_h = np.resize(flows_h[:m], times_h.size)

    # Build per-step flows and slopes
    per_step_flows: list[float] = []
    slopes: list[float] = []  # |dQ|/dt over each step (m3/s per hour)
    if first > 0:
        per_step_flows.append(float(flows_h[0]))
        # Slope from implicit 0 to first sample
        dq0 = abs(float(flows_h[0]) - 0.0)
        slopes.append(dq0 / max(first, 1e-9))
    for i, Lh in enumerate(diffs):
        if Lh <= 0:
            continue
        per_step_flows.append(float(flows_h[i]))  # flow at start of interval [t_i, t_{i+1}]
        dq = abs(float(flows_h[i+1]) - float(flows_h[i]))
        slopes.append(dq / max(float(Lh), 1e-9))

    # Adaptive nstp per storm step
    nstp_by_step: list[int] = []
    if refine and len(slopes) > 0 and np.nanmax(slopes) > 0:
        s = np.asarray(slopes, dtype=float)
        s = s[np.isfinite(s)]
        if s.size == 0 or np.nanmax(s) == 0:
            nstp_by_step = [1] * len(per_step_flows)
        else:
            p50 = float(np.percentile(s, 50))
            p70 = float(np.percentile(s, 70))
            p90 = float(np.percentile(s, 90))
            for val in slopes:
                if val >= p90 and nstp_max >= 6:
                    n = min(nstp_max, 6)
                elif val >= p70 and nstp_max >= 4:
                    n = min(nstp_max, 4)
                else:
                    n = min(nstp_max, 3)
                nstp_by_step.append(int(n))
    else:
        nstp_by_step = [1] * len(per_step_flows)

    # Pre-storm stabilization periods (zero inflow)
    pre_n = max(0, int(pre_storm_steps))
    pre_len_h = max(1e-6, float(pre_storm_step_hours))
    pre_nstp = max(1, int(pre_storm_nstp))
    for _ in range(pre_n):
        stress_periods.append([pre_len_h, pre_nstp, 1.0])
        inflow_m3s_per_sp.append(0.0)

    # Add storm stress periods with adaptive nstp
    for Lh, nstp_for_step, q_step in zip(step_lengths, nstp_by_step, per_step_flows):
        if Lh <= 0:
            continue
        stress_periods.append([float(Lh), int(max(1, nstp_for_step)), 1.0])  # [length, nsteps, multiplier]
        inflow_m3s_per_sp.append(float(max(0.0, q_step)))
    
    # Post-storm period (coarser resolution)
    remaining_time = float(total_duration_hours) - storm_duration
    if remaining_time > 0:
        # Use fixed step size for post-storm (e.g., 12-hour steps)
        step_h = float(post_storm_step_hours)
        post_storm_steps = max(1, int(np.floor(remaining_time / step_h)))
        remainder = max(0.0, remaining_time - post_storm_steps * step_h)

        print(f"   📉 Post-storm period: {remaining_time:.1f} hours ({post_storm_steps}×{step_h:.1f}h + {remainder:.1f}h)")

        for _ in range(post_storm_steps):
            stress_periods.append([step_h, 1, 1.0])
            inflow_m3s_per_sp.append(0.0)
        if remainder > 1e-6:
            stress_periods.append([remainder, 1, 1.0])
            inflow_m3s_per_sp.append(0.0)
    
    total_periods = len(stress_periods)
    print(f"   ✅ Created {total_periods} stress periods")
    print(f"   ⏱️ Total simulation time: {sum([sp[0] for sp in stress_periods]):.1f} hours")
    
    # Safety: align lengths
    if len(inflow_m3s_per_sp) != len(stress_periods):
        # Pad or trim to match
        if len(inflow_m3s_per_sp) < len(stress_periods):
            inflow_m3s_per_sp.extend([0.0] * (len(stress_periods) - len(inflow_m3s_per_sp)))
        else:
            inflow_m3s_per_sp = inflow_m3s_per_sp[:len(stress_periods)]

    return stress_periods, inflow_m3s_per_sp

def create_lak_with_time_series(
    basin_cells,
    storm_data,
    stress_periods,
    model_dir,
    model_name,
    basin_floor,
    lakebed_thickness,
    lake_initial_stage,
    laktab_rows=None,
    lake_surface_area_m2=2500.0,
    table_stage_max_offset=2.0,
    lakebed_k=1e-5,
    infiltration_mode: str = "vertical",
    side_k: float | None = None,
    delr=None,
    delc=None,
    nrow: int | None = None,
    ncol: int | None = None,
    layer_thickness: float | None = None,
    max_depth: float | None = None,
    aligned_inflows_m3s: list[float] | None = None,
    spill_linear_extension_m: float = 10.0,
    bed_leak_multiplier: float = 1.0,
    top: float = None,
    botm: list[float] = None,
    write_lak_budget: bool = True,
):
    """Create LAK package with time-varying inflow and stage–volume table.

    Parameters:
      - basin_cells: list[(k,i,j)] lake connection cells on the connection layer
      - lake_surface_area_m2: plan-view area used for LAKTAB (assumed constant)
      - table_stage_max_offset: meters above basin_floor to extend table
    """
    print(f"🌊 Creating LAK package with time-varying inflows...")

    lak_file = os.path.join(model_dir, f"{model_name}.lak")
    laktab_file = os.path.join(model_dir, f"{model_name}.laktab")
    # Clamp initial stage to safe range for current geometry
    try:
        lake_initial_stage = max(float(basin_floor), float(lake_initial_stage))
        if max_depth is not None:
            crest = float(basin_floor) + float(max_depth)
            if lake_initial_stage > crest:
                print(f"   ⚠️ Initial stage {lake_initial_stage:.3f} exceeds crest {crest:.3f}; resetting to basin floor")
                lake_initial_stage = float(basin_floor)
    except Exception:
        pass

    # Write LAKTAB file for stage–volume–area relation
    try:
        if laktab_rows is None:
            # Backward-compatible constant-area table
            nrows = 11
            stage_min = float(basin_floor)
            stage_max = float(basin_floor + max(0.5, table_stage_max_offset))
            stages = np.linspace(stage_min, stage_max, nrows)
            sarea = float(lake_surface_area_m2)
            rows = [(stg, max(0.0, stg - basin_floor) * sarea, sarea) for stg in stages]
        else:
            rows = list(laktab_rows)

        # Ensure strictly non-decreasing stage and volume
        rows.sort(key=lambda r: r[0])
        last_v = -1e30
        fixed_rows = []
        for stg, vol, area in rows:
            v = max(last_v, float(vol))
            fixed_rows.append((float(stg), v, float(area)))
            last_v = v

        # Linear extension above crest for stability (use last area)
        try:
            if spill_linear_extension_m and spill_linear_extension_m > 0 and len(fixed_rows) >= 2:
                stg_last, vol_last, area_last = fixed_rows[-1]
                ext_top = stg_last + float(spill_linear_extension_m)
                # Use ~21 steps for smoothness
                ext_n = max(2, int(min(101, max(21, spill_linear_extension_m * 2))))
                ext_stages = np.linspace(stg_last + 0.01, ext_top, ext_n)
                for s in ext_stages:
                    dv = (s - stg_last) * float(area_last)
                    fixed_rows.append((float(s), float(vol_last + dv), float(area_last)))
                print(f"   ⚠️ Extended LAKTAB linearly by {spill_linear_extension_m:.1f} m above crest for stability")
        except Exception:
            pass

        # Write
        from utils.lak_utils import write_laktab_file as _write
        _write(laktab_file, fixed_rows)
        print(f"   ✅ LAKTAB file created: {os.path.basename(laktab_file)}")
    except Exception as e:
        print(f"   ⚠️ Could not create LAKTAB file: {e}")
    # Pre-compute total number of connections (needed for PACKAGEDATA nlakeconn)
    nlakeconn = len(basin_cells)
    if str(infiltration_mode).lower() == "full":
        if delr is None or delc is None or nrow is None or ncol is None or layer_thickness is None:
            raise ValueError("Full infiltration requires delr, delc, nrow, ncol, and layer_thickness")
        footprint = {(r, c) for (_, r, c) in basin_cells}
        extra = 0
        for _, row, col in basin_cells:
            neighbors = [
                (row, col - 1),
                (row, col + 1),
                (row - 1, col),
                (row + 1, col),
            ]
            for nr, nc in neighbors:
                if 0 <= nr < nrow and 0 <= nc < ncol and (nr, nc) not in footprint:
                    extra += 1
        nlakeconn += extra

    with open(lak_file, 'w') as f:
        # Header
        f.write("# LAK Package with Time-Varying Inflows\n")
        f.write("# Generated by BaSIM Phase 3.2\n")
        f.write("# Storm-driven infiltration basin simulation\n\n")

        # Options
        f.write("BEGIN OPTIONS\n")
        f.write("  PRINT_INPUT\n")
        f.write("  PRINT_FLOWS\n")
        f.write("  MOVER\n")
        f.write("  STAGE FILEOUT basin_stages.txt\n")
        if write_lak_budget:
            f.write("  BUDGET FILEOUT basin_budget.txt\n")
        f.write(f"  OBS6 FILEIN {model_name}_lak.obs\n")
        f.write("END OPTIONS\n\n")

        # Dimensions
        f.write("BEGIN DIMENSIONS\n")
        f.write("  NLAKES 1\n")
        f.write("  NOUTLETS 1\n")
        f.write("  NTABLES 1\n")
        f.write("END DIMENSIONS\n\n")

        # Package data
        f.write("BEGIN PACKAGEDATA\n")
        f.write("# lakeno strt nlakeconn\n")
        f.write(f"  1 {lake_initial_stage} {nlakeconn}\n")
        f.write("END PACKAGEDATA\n\n")

        # Connection data
        f.write("BEGIN CONNECTIONDATA\n")
        f.write("# lakeno iconn cellid claktype bedleak belev telev connlen connwidth\n")
        iconn = 0
        # Compute leakance in 1/day (no external multiplier; tuning removed)
        if str(infiltration_mode).lower() == "full":
            bedleak_day = 0.0
        else:
            bedleak_day = (float(lakebed_k) / float(lakebed_thickness)) * 86400.0
        side_k_eff = float(side_k) if side_k is not None else float(lakebed_k)
        side_leak_day = (side_k_eff / float(lakebed_thickness)) * 86400.0

        # Helper for writing a connection
        def _write_conn(layer, row, col, claktype, bedleak, belev, telev, connlen, connwidth):
            nonlocal iconn
            iconn += 1
            f.write(
                f"  1 {iconn} {layer+1} {row+1} {col+1} {claktype} {bedleak} {belev} {telev} {connlen} {connwidth}\n"
            )

        # 1) Bottom (vertical) connections
        # For DEM mode (top is 2-D), use per-cell ground elevation instead of flat basin_floor
        _top_is_2d = isinstance(top, np.ndarray) and getattr(top, 'ndim', 0) == 2
        for layer, row, col in basin_cells:
            if _top_is_2d:
                _cell_ground = float(top[row, col])
            else:
                _cell_ground = float(basin_floor)
            belev = _cell_ground - lakebed_thickness
            # Ensure belev is not below the cell bottom (required by MODFLOW 6)
            cell_bottom = botm[layer]
            if belev < cell_bottom:
                belev = cell_bottom + 0.01  # Add small margin above cell bottom
            if layer == 0:
                cell_top = float(top[row, col]) if _top_is_2d else float(top)
            else:
                cell_top = float(botm[layer - 1])
            # Clamp telev slightly below cell top to avoid FloPy/MF6 precision
            # mismatch. Crucially, telev MUST be higher than the max lake stage
            # to prevent MF6 from clamping the vertical head difference to 0.0.
            telev = cell_top - 1e-4
            # Use full cell footprint for contact area (connlen x connwidth)
            dx = (delr[col] if hasattr(delr, '__len__') else float(delr or 2.0))
            dy = (delc[row] if hasattr(delc, '__len__') else float(delc or 2.0))
            connlen = float(dx)
            connwidth = float(dy)
            _write_conn(layer, row, col, "VERTICAL", bedleak_day, belev, telev, connlen, connwidth)

        # 2) Optional horizontal (side/bank) connections for 'full' mode
        if str(infiltration_mode).lower() == "full":
            # Ensure grid metrics are available
            if delr is None or delc is None or nrow is None or ncol is None or layer_thickness is None:
                raise ValueError("Full infiltration requires delr, delc, nrow, ncol, and layer_thickness")

            # build a set for quick lookup
            footprint = {(r, c) for (_, r, c) in basin_cells}

            # find perimeter cells (4-neighbour)
            for layer, row, col in basin_cells:
                neighbors = [
                    (row, col - 1, 'W'),
                    (row, col + 1, 'E'),
                    (row - 1, col, 'N'),
                    (row + 1, col, 'S'),
                ]
                for nr, nc, side in neighbors:
                    if nr < 0 or nr >= nrow or nc < 0 or nc >= ncol:
                        continue
                    if (nr, nc) in footprint:
                        continue  # internal neighbour
                    # This face is on the basin perimeter; add a HORIZONTAL connection on current cell
                    if side in ('W', 'E'):
                        # West/East face length spans the row cell size (north-south direction)
                        connlen = float(delc[row]) if hasattr(delc, '__len__') else float(delc or 2.0)
                    else:
                        # North/South face length spans the column cell size (east-west direction)
                        connlen = float(delr[col]) if hasattr(delr, '__len__') else float(delr or 2.0)
                    # No dampening: use full face length for side contact
                    connlen = float(connlen)
                    # Use full connection layer thickness for side leak face height
                    # (Area = connlen * connwidth; Conductance = bedleak * Area)
                    _thk = float(np.mean(layer_thickness)) if hasattr(layer_thickness, '__len__') else float(layer_thickness)
                    connwidth = float(max(0.01, _thk))
                    if _top_is_2d:
                        _side_ground = float(top[row, col])
                    else:
                        _side_ground = float(basin_floor)
                    belev = float(_side_ground - lakebed_thickness)
                    # Ensure belev is not below the cell bottom (required by MODFLOW 6)
                    cell_bottom = botm[layer]
                    if belev < cell_bottom:
                        belev = cell_bottom + 0.01  # Add small margin above cell bottom
                    

                    # Cap top of contact slightly below cell ground to avoid
                    # FloPy DIS vs LAK decimal-precision mismatch.
                    _write_conn(layer, row, col, "HORIZONTAL", side_leak_day, belev, telev, connlen, connwidth)

        f.write("END CONNECTIONDATA\n\n")

        # Tables
        f.write("BEGIN TABLES\n")
        f.write(f"  1 TAB6 FILEIN {os.path.basename(laktab_file)}\n")
        f.write("END TABLES\n\n")

        # Outlets - dummy outlet to satisfy MVR package
        f.write("BEGIN OUTLETS\n")
        f.write("# outletno lakein lakeout couttype invert width rough slope\n")
        f.write(f"  1 1 0 SPECIFIED 0.0 0.0 0.0 0.0\n")
        f.write("END OUTLETS\n\n")

        # Period data
        print("   📊 Creating time-varying inflow data...")
        storm_flows = storm_data['flow_m3s'].values
        for sp_idx, _sp in enumerate(stress_periods):
            sp_num = sp_idx + 1
            f.write(f"BEGIN PERIOD {sp_num}\n")
            # Use aligned inflow list if provided (handles pre/post-storm periods)
            if aligned_inflows_m3s is not None and sp_idx < len(aligned_inflows_m3s):
                inflow_m3s = float(aligned_inflows_m3s[sp_idx])
            else:
                # Fallback: storm flow during storm; zero after storm ends
                inflow_m3s = storm_flows[sp_idx] if sp_idx < len(storm_flows) else 0.0
            inflow_m3s = max(0.0, float(inflow_m3s))
            inflow_m3day = inflow_m3s * 86400.0
            f.write(f"# Stress period {sp_num}: inflow = {inflow_m3s:.6f} m3/s ({inflow_m3day:.3f} m3/day)\n")
            f.write(f"  1 INFLOW {inflow_m3day}\n")
            f.write(f"  1 OUTLET 1 RATE 0.0\n")
            f.write("END PERIOD\n\n")
            if sp_idx % 10 == 0 or sp_idx == len(stress_periods) - 1:
                progress = (sp_idx + 1) / len(stress_periods) * 100
                print(f"   📈 Progress: {progress:.1f}% ({sp_idx + 1}/{len(stress_periods)} periods)")

    print(f"   ✅ LAK file created: {os.path.basename(lak_file)}")
    print(f"   🌊 Lake connections: {len(basin_cells)}")
    print(f"   ⏰ Stress periods: {len(stress_periods)}")

    # LAK observations file
    obs_file = os.path.join(model_dir, f"{model_name}_lak.obs")
    with open(obs_file, 'w') as fo:
        fo.write("# LAK Observations (MF6 UTLOBS6)\n")
        # Minimal CSV with stage for existing plotters
        fo.write(f"BEGIN CONTINUOUS FILEOUT {model_name}_lak_stage.csv CSV\n")
        fo.write("  lak_stage stage 1\n")
        fo.write("END CONTINUOUS\n")
        # Full LAK observation set (per MF6 Table 16) to a separate CSV
        fo.write(f"BEGIN CONTINUOUS FILEOUT {model_name}_lak_allobs.csv CSV\n")
        # Use boundname for lake-level terms to avoid requiring iconn.
        _lake_bound = '1'
        # Base observation types that do not require outlet numbers
        _types_common = [
            'stage', 'ext-inflow', 'outlet-inflow', 'inflow', 'from-mvr',
            'rainfall', 'runoff', 'withdrawal', 'evaporation',
            'storage', 'constant', 'volume', 'surface-area',
        ]
        for _t in _types_common:
            _name = 'lak_' + _t.replace('-', '_')
            # All of these accept lakeno or boundname as ID; use boundname
            fo.write(f"  {_name} {_t} {_lake_bound}\n")
        # Skip outlet-related obs if there are no outlets in the package
        _noutlets = 0
        if _noutlets > 0:
            for _t in ('outlet', 'ext-outflow', 'to-mvr'):
                _name = 'lak_' + _t.replace('-', '_')
                # Example for outlet 1; projects with multiple outlets can extend
                fo.write(f"  {_name} {_t} 1\n")
        # Per-connection wetted-area and conductance
        try:
            for _iconn in range(1, nlakeconn + 1):
                fo.write(f"  wetted_area_c{_iconn} wetted-area 1 {_iconn}\n")
                fo.write(f"  conductance_c{_iconn} conductance 1 {_iconn}\n")
        except Exception:
            pass
        fo.write("END CONTINUOUS\n")
    print(f"   ✅ LAK OBS file created: {os.path.basename(obs_file)} -> {model_name}_lak_stage.csv")

    return lak_file


def create_uzf_package(
    basin_cells,
    stress_periods,
    model_dir,
    model_name,
    vks,
    thts=0.35,
    thtr=0.05,
    thti=0.10,
    eps=4.0,
    surfdep=0.001,
    write_budget=True,
):
    """Create UZF package file for basin floor cells.

    Parameters:
      - basin_cells: list[(k,i,j)] — connection-layer cells (same as LAK)
      - stress_periods: [[hours, nsteps, mult], ...]
      - model_dir: output directory
      - model_name: MF6 model name
      - vks: saturated vertical K in model length/time units (m/day)
      - thts, thtr, thti, eps: UZF soil parameters (Brooks-Corey)
      - write_budget: write budget file
    Returns path to UZF file.
    """
    print(f"   🌱 Creating UZF package ({len(basin_cells)} cells)...")

    uzf_file = os.path.join(model_dir, f"{model_name}.uzf")
    nuzfcells = len(basin_cells)

    with open(uzf_file, 'w') as f:
        f.write("# UZF Package — Unsaturated Zone Flow for basin infiltration\n")
        f.write("# Generated by BaSIM\n\n")

        # Options
        f.write("BEGIN OPTIONS\n")
        f.write("  PRINT_FLOWS\n")
        f.write("  MOVER\n")
        if write_budget:
            f.write("  BUDGET FILEOUT basin_uzf_budget.txt\n")
        f.write("END OPTIONS\n\n")

        # Dimensions
        f.write("BEGIN DIMENSIONS\n")
        f.write(f"  NUZFCELLS {nuzfcells}\n")
        f.write("  NTRAILWAVES 7\n")
        f.write("  NWAVESETS 40\n")
        f.write("END DIMENSIONS\n\n")

        # Package data
        f.write("BEGIN PACKAGEDATA\n")
        f.write("# ifno cellid landflag ivertcon surfdep vks thtr thts thti eps\n")
        for idx, (layer, row, col) in enumerate(basin_cells):
            ifno = idx + 1
            f.write(
                f"  {ifno}  {layer + 1} {row + 1} {col + 1}"
                f"  1  0  {surfdep}  {vks}  {thtr}  {thts}  {thti}  {eps}\n"
            )
        f.write("END PACKAGEDATA\n\n")

        # Period data — finf=0 for all cells (infiltration delivered via MVR)
        for sp_idx in range(len(stress_periods)):
            sp_num = sp_idx + 1
            f.write(f"BEGIN PERIOD {sp_num}\n")
            for idx in range(nuzfcells):
                ifno = idx + 1
                # finf pet extdp extwc ha hroot rootact
                f.write(f"  {ifno}  0.0  0.0  0.0  0.0  0.0  0.0  0.0\n")
            f.write(f"END PERIOD\n\n")

    print(f"   ✅ UZF file created: {os.path.basename(uzf_file)}")
    return uzf_file


def create_mvr_package(
    basin_cells,
    stress_periods,
    model_dir,
    model_name,
    delr,
    delc,
    vks=50.0,
    lak_pname="basin_lak",
    uzf_pname="basin_uzf",
):
    import os
    print(f"   ?? Creating MVR package ({len(basin_cells)}x2 movers)...")

    mvr_file = os.path.join(model_dir, f"{model_name}.mvr")
    nmovers = len(basin_cells) * 2

    def _cell_area(row, col):
        dx = float(delr[col]) if hasattr(delr, '__len__') else float(delr)
        dy = float(delc[row]) if hasattr(delc, '__len__') else float(delc)
        return dx * dy

    areas = [_cell_area(r, c) for (_, r, c) in basin_cells]
    total_area = sum(areas)
    fractions = [a / total_area for a in areas]

    with open(mvr_file, 'w') as f:
        f.write("# MVR Package - Water Mover: LAK seepage -> UZF -> LAK\n")
        f.write("# Generated by BaSIM\n\n")
        f.write("BEGIN OPTIONS\n")
        f.write("  PRINT_FLOWS\n")
        f.write("END OPTIONS\n\n")
        f.write("BEGIN DIMENSIONS\n")
        f.write(f"  MAXMVR {nmovers}\n")
        f.write("  MAXPACKAGES 2\n")
        f.write("END DIMENSIONS\n\n")
        f.write("BEGIN PACKAGES\n")
        f.write(f"  {lak_pname}\n")
        f.write(f"  {uzf_pname}\n")
        f.write("END PACKAGES\n\n")

        for sp_idx in range(len(stress_periods)):
            sp_num = sp_idx + 1
            f.write(f"BEGIN PERIOD {sp_num}\n")
            f.write("# pname1 id1 pname2 id2 mvrtype value\n")
            
            for idx in range(len(basin_cells)):
                uzf_id = idx + 1
                cell_rate = areas[idx] * vks
                f.write(f"  {lak_pname}  1  {uzf_pname}  {uzf_id}  RATE  {cell_rate:.8f}\n")
                
            for idx in range(len(basin_cells)):
                uzf_id = idx + 1
                f.write(f"  {uzf_pname}  {uzf_id}  {lak_pname}  1  FACTOR  1.00000000\n")
                
            f.write("END PERIOD\n\n")

    print(f"   ? MVR file created: {os.path.basename(mvr_file)}")
    return mvr_file


def run_phase3_step32_model():
    """Main function to run Phase 3 Step 3.2 model"""
    
    print("=" * 70)
    print("BASIN INFILTRATION SIMULATOR - PHASE 3 STEP 3.2")
    print("=" * 70)
    print("🌊 Time-Varying Storm Inputs with LAK Package")
    print("🎯 Realistic storm event modeling")
    print("📊 TS1 hydrograph integration")
    print("=" * 70)
    
    # Configuration (user-adjustable)
    # Infiltration mode and bed properties (env-overridable)
    infil_mode = os.getenv("BASIM_INFILTRATION_MODE", "vertical").strip().lower()
    try:
        bed_thickness_m = float(os.getenv("BASIM_BED_THICKNESS_M", "0.5"))
    except Exception:
        bed_thickness_m = 0.5
    try:
        bed_k_mpd = float(os.getenv("BASIM_BED_K_MPD", "5.0"))  # meters per day
    except Exception:
        bed_k_mpd = 5.0
    try:
        side_k_mpd = os.getenv("BASIM_SIDE_K_MPD")
        side_k_mpd = float(side_k_mpd) if side_k_mpd is not None else None
    except Exception:
        side_k_mpd = None

    # Build a short model name (MF6 limit is 16 chars)
    BASE_MODEL_NAME = "bas32"
    mode_suffix = "vert" if infil_mode.startswith("v") else ("full" if infil_mode.startswith("f") else infil_mode[:4])
    MODEL_NAME = f"{BASE_MODEL_NAME}_{mode_suffix}"[:16]
    PROJECT_ROOT = Path(__file__).parent.parent  # Go up from src to project root
    MODEL_DIR = PROJECT_ROOT / "model_output" / "phase3" / "step32"
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # User-configurable parameters (could be moved to a YAML/JSON later)
    basin_geom = BasinGeometry(
        length_floor=50.0,  # m
        width_floor=50.0,   # m
        max_depth=2.0,      # m water depth above floor
        side_slope_hv=2.0,  # 2H:1V side slope
        floor_elev=5.0,     # m AHD
    )
    initial_groundwater_head = 4.0  # m
    k_horizontal = 20.0  # m/day
    k_vertical = 5.0     # m/day
    sy = 0.05
    ss = 1e-5
    
    # Find TS1 file
    drains_dir = PROJECT_ROOT / "External" / "OUTPUT"
    if drains_dir.exists():
        ts1_files = [f for f in drains_dir.iterdir() if f.suffix == '.ts1']
    else:
        ts1_files = []
    
    if ts1_files:
        ts1_file = ts1_files[0]  # Use first TS1 file
        print(f"🎯 Using TS1 file: {ts1_file.name}")
    else:
        ts1_file = None
        print(f"⚠️ No TS1 files found, will use synthetic storm")
    
    # Read storm data
    if ts1_file and ts1_file.exists():
        storm_data = read_ts1_file(str(ts1_file), allow_synthetic=False)
    else:
        storm_data = generate_synthetic_storm()
    
    # Plot storm hydrograph
    plt.figure(figsize=(12, 6))
    plt.plot(storm_data['time_hours'], storm_data['flow_m3s'], 'b-', linewidth=2)
    plt.xlabel('Time (hours)')
    plt.ylabel('Inflow Rate (m³/s)')
    plt.title('Storm Hydrograph - Time-Varying Inflows')
    plt.grid(True, alpha=0.3)
    storm_plot_file = MODEL_DIR / 'storm_hydrograph.png'
    plt.savefig(storm_plot_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"   📊 Storm plot saved: {storm_plot_file.name}")

    # Save inflow time series CSV for downstream plots (hours, days, m3/s, m3/day)
    try:
        inflow_csv = MODEL_DIR / 'inflow_timeseries.csv'
        inflow_df = pd.DataFrame({
            'time_hours': storm_data['time_hours'].values,
            'time_days': storm_data['time_hours'].values / 24.0,
            'flow_m3s': storm_data['flow_m3s'].values,
            'flow_m3day': storm_data['flow_m3s'].values * 86400.0,
        })
        inflow_df.to_csv(inflow_csv, index=False)
        print(f"   💾 Saved inflow CSV: {inflow_csv.name}")
    except Exception as e:
        print(f"   ⚠️ Could not save inflow CSV: {e}")
    
    # Create model grid using geometry-driven domain sizing
    print(f"\n🏗️ Creating adaptive refined grid...")
    nlay = 8
    # Ensure the domain extends well beyond the basin to avoid boundary effects
    # Use a higher minimum factor and more gradations so the far field is coarse
    dom_factor = suggest_domain_factor(basin_geom, min_factor=12.0, pad_multiplier=4.0)
    grid_info = create_adaptive_refined_grid(
        basin_length=basin_geom.length_floor,
        basin_width=basin_geom.width_floor,
        domain_factor=dom_factor,
        refinement_zones=4,           # add an extra near/transition ring
        min_cell_size=2.0,
        max_cell_size=25.0,           # coarse far-field to keep cell count manageable
    )
    
    # Extract grid information
    nrow, ncol = grid_info['nrow'], grid_info['ncol']
    delr, delc = grid_info['delr'], grid_info['delc']
    basin_rows = grid_info['basin_rows']  # [start_row, end_row]
    basin_cols = grid_info['basin_cols']  # [start_col, end_col]
    
    # Create basin cell coordinates from the ranges
    basin_cells_2d = []
    for row in range(basin_rows[0], basin_rows[1]):
        for col in range(basin_cols[0], basin_cols[1]):
            basin_cells_2d.append((row, col))
    
    print(f"   📐 Grid dimensions: {nrow} × {ncol} × {nlay}")
    print(f"   📊 Total cells: {nrow * ncol * nlay:,}")
    
    # Create layer configuration
    layer_thickness = [2, 3, 5, 8, 10, 12, 15, 20]  # Progressive increase
    top = 10.0  # ground surface elevation (m)
    botm = [top - sum(layer_thickness[:i+1]) for i in range(nlay)]

    # Basin/lakebed parameters (consistent elevations)
    basin_floor = float(basin_geom.floor_elev)  # basin floor elevation (lakebed top)
    lakebed_thickness = bed_thickness_m      # lakebed thickness (m)
    lake_initial_stage = basin_floor  # initial lake stage at floor

    # Determine connection layer that spans the basin floor elevation
    conn_layer = None
    for k in range(nlay):
        lay_top = top if k == 0 else botm[k-1]
        lay_bot = botm[k]
        if lay_bot < basin_floor <= lay_top:
            conn_layer = k
            break
    if conn_layer is None:
        # Fallback: first layer with basin floor above its bottom
        for k in range(nlay):
            if basin_floor > botm[k]:
                conn_layer = k
                break
    if conn_layer is None:
        conn_layer = 0

    # Build 3D basin connection cells on the connection layer
    basin_cells = [(conn_layer, r, c) for (r, c) in basin_cells_2d]
    print(f"   🎯 Basin cells: {len(basin_cells)} (connection layer k={conn_layer})")
    
    # Create stress periods for time-varying inputs
    # Auto time: hydrograph length + 5 days of drawdown
    storm_duration_h = float(np.max(storm_data['time_hours'].values))
    total_sim_hours = storm_duration_h + 5.0 * 24.0
    stress_periods, inflow_per_sp = create_time_varying_stress_periods(
        storm_data,
        total_sim_hours,
        post_storm_step_hours=12.0,
    )
    # Guard: ensure aligned inflow list matches stress periods
    if len(inflow_per_sp) != len(stress_periods):
        raise RuntimeError(f"Aligned inflow list length {len(inflow_per_sp)} != stress periods {len(stress_periods)}")
    
    # Create MODFLOW 6 simulation
    print(f"\n🏗️ Creating MODFLOW 6 model with time-varying inputs...")
    
    # Time discretization
    tdis_data = []
    for sp_length, nsteps, mult in stress_periods:
        tdis_data.append([sp_length / 24.0, nsteps, mult])  # Convert hours to days
    
    # Simulation
    sim = flopy.mf6.MFSimulation(
        sim_name=MODEL_NAME,
        sim_ws=str(MODEL_DIR),
        exe_name=find_mf6_exe()
    )
    
    # Time discretization
    tdis = flopy.mf6.ModflowTdis(
        sim,
        time_units="DAYS",
        nper=len(stress_periods),
        perioddata=tdis_data
    )
    
    # Solver (robust settings for complex time-varying simulation)
    # Choose solver settings based on geometry difficulty
    needs_relax = (
        basin_geom.max_depth > 3.0 or
        basin_geom.side_slope_hv < 1.5 or
        abs(basin_geom.floor_elev - initial_groundwater_head) < 0.5
    )
    if needs_relax:
        print("   🔧 Challenging geometry detected → relaxed IMS settings")
        ims = flopy.mf6.ModflowIms(
            sim,
            print_option="SUMMARY",
            complexity="COMPLEX",
            outer_dvclose=2e-3,
            outer_maximum=800,
            under_relaxation="DBD",
            under_relaxation_theta=0.7,
            under_relaxation_kappa=0.15,
            linear_acceleration="BICGSTAB",
            inner_maximum=800,
            inner_dvclose=2e-5,
            rcloserecord=[0.02, "STRICT"],
            backtracking_number=20,
            backtracking_tolerance=2.0,
            backtracking_reduction_factor=0.2,
            backtracking_residual_limit=0.0,
        )
    else:
        ims = flopy.mf6.ModflowIms(
            sim,
            print_option="SUMMARY",
            complexity="COMPLEX",
            outer_dvclose=5e-4,
            outer_maximum=500,
            under_relaxation="DBD",
            linear_acceleration="BICGSTAB",
            inner_maximum=500,
            inner_dvclose=5e-6,
            rcloserecord=[0.005, "STRICT"],
            backtracking_number=10,
            backtracking_tolerance=1.0,
            backtracking_reduction_factor=0.3,
            backtracking_residual_limit=0.0,
        )
    
    # Groundwater flow model
    gwf = flopy.mf6.ModflowGwf(sim, modelname=MODEL_NAME, save_flows=True, newtonoptions="NEWTON UNDER_RELAXATION")
    
    # Discretization
    dis = flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=nlay,
        nrow=nrow,
        ncol=ncol,
        delr=delr,
        delc=delc,
        top=top,
        botm=botm
    )
    
    ic = flopy.mf6.ModflowGwfic(gwf, strt=initial_groundwater_head)
    
    # Node property flow: higher horizontal K to promote lateral drainage
    npf = flopy.mf6.ModflowGwfnpf(
        gwf,
        save_flows=True,
        icelltype=1,  # Convertible layers
        k=k_horizontal,
        k33=k_vertical  # Anisotropy: faster lateral drainage
    )
    
    # Storage
    sto = flopy.mf6.ModflowGwfsto(
        gwf,
        save_flows=True,
        iconvert=1,
        ss=ss,
        sy=sy  # lower specific yield to accelerate water table response
    )
    
    # Initial conditions — use user-specified groundwater head directly
    # General head boundaries (domain edges) with finite conductance
    # This allows natural gradients and drainage without fixing head exactly.
    boundary_head = float(initial_groundwater_head)

    def _as_array(v, n):
        import numpy as _np
        return _np.array(v) if hasattr(v, '__len__') else _np.full(n, v)

    delr_arr = _as_array(delr, ncol)
    delc_arr = _as_array(delc, nrow)

    # Build GHBs on all saturated layers to avoid edge artifacts.
    ghb_list = []
    K_edge = float(k_horizontal)  # horizontal aquifer K (m/day)
    ghb_mult = 100.0              # boost conductance for efficient drainage
    small = 1e-3
    for k in range(nlay):
        lay_top_k = top if k == 0 else botm[k - 1]
        lay_bot_k = botm[k]
        layer_thickness_k = float(lay_top_k - lay_bot_k)
        if layer_thickness_k <= 0:
            layer_thickness_k = 1.0
        # Only place GHB if boundary head is above the layer bottom
        if boundary_head <= float(lay_bot_k) + small:
            continue
        boundary_head_eff_k = max(boundary_head, float(lay_bot_k) + small)

        for i in range(nrow):
            for j in range(ncol):
                on_edge = (i == 0 or i == nrow - 1 or j == 0 or j == ncol - 1)
                if not on_edge:
                    continue
                # Determine face orientation and geometry
                if j == 0 or j == ncol - 1:
                    width = float(delc_arr[i])
                    distance = max(0.5 * float(delr_arr[j]), 1e-6)
                else:  # top/bottom edges
                    width = float(delr_arr[j])
                    distance = max(0.5 * float(delc_arr[i]), 1e-6)
                conductance = ghb_mult * (K_edge * width * layer_thickness_k / distance)
                ghb_list.append([k, i, j, boundary_head_eff_k, conductance])

    ghb = flopy.mf6.ModflowGwfghb(
        gwf,
        stress_period_data=ghb_list,
        save_flows=True,
    )

    # Symmetry diagnostics (non-fatal): verify mirrored grid and balanced GHB sums
    try:
        import numpy as _np
        _delr = _as_array(delr, ncol)
        _delc = _as_array(delc, nrow)
        left = _delr[: len(_delr)//2]
        right = _delr[-1: len(_delr)//2 - 1: -1]
        top = _delc[: len(_delc)//2]
        bottom = _delc[-1: len(_delc)//2 - 1: -1]
        grid_sym_ok = _np.allclose(left, right, rtol=1e-6, atol=1e-9) and _np.allclose(top, bottom, rtol=1e-6, atol=1e-9)
        cond_left = cond_right = cond_top = cond_bottom = 0.0
        for (lay, i, j, bh, c) in ghb_list:
            if j == 0:
                cond_left += c
            elif j == ncol - 1:
                cond_right += c
            elif i == 0:
                cond_top += c
            elif i == nrow - 1:
                cond_bottom += c
        print(f"   🔎 Symmetry check → grid: {'OK' if grid_sym_ok else 'MISMATCH'}; GHB ΣC left/right={cond_left:.3e}/{cond_right:.3e}, top/bottom={cond_top:.3e}/{cond_bottom:.3e}")
    except Exception:
        pass
    
    # Output control — avoid large .hds/.bud; in this path, default to lightweight
    lw = True
    if lw:
        oc = flopy.mf6.ModflowGwfoc(
            gwf,
            saverecord=[],
            printrecord=[],
        )
    else:
        oc = flopy.mf6.ModflowGwfoc(
            gwf,
            budget_filerecord=f"{MODEL_NAME}.bud",
            head_filerecord=f"{MODEL_NAME}.hds",
            saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
            printrecord=[("HEAD", "LAST"), ("BUDGET", "LAST")]
        )
    
    # Create LAK package with time-varying inputs (also writes OBS for stage CSV)
    # Build tapered LAKTAB rows from geometry (extend to floor + max_depth)
    laktab_rows = generate_tapered_laktab(basin_geom, nrows=41)

    lak_file = create_lak_with_time_series(
        basin_cells,
        storm_data,
        stress_periods,
        str(MODEL_DIR),
        MODEL_NAME,
        basin_floor,
        lakebed_thickness,
        lake_initial_stage,
        laktab_rows=laktab_rows,
        lake_surface_area_m2=basin_geom.length_floor * basin_geom.width_floor,
        table_stage_max_offset=basin_geom.max_depth,
        lakebed_k=(bed_k_mpd/86400.0),  # convert m/day -> m/s
        infiltration_mode=infil_mode,  # "vertical" or "full"
        side_k=(None if side_k_mpd is None else side_k_mpd/86400.0),  # banks m/day -> m/s
        aligned_inflows_m3s=inflow_per_sp,
        delr=delr,
        delc=delc,
        nrow=nrow,
        ncol=ncol,
        layer_thickness=(top - botm[conn_layer]),
        max_depth=basin_geom.max_depth,
        spill_linear_extension_m=10.0,
        top=top,
        botm=botm,
        write_lak_budget=(not lw),
    )

    # Write model metadata for plotting/QA (crest elevation, etc.)
    try:
        import json as _json
        crest_elev = float(basin_geom.floor_elev + basin_geom.max_depth)
        meta = {
            "floor_elev_mAHD": float(basin_geom.floor_elev),
            "crest_elev_mAHD": crest_elev,
            "max_depth_m": float(basin_geom.max_depth),
            "spill_extension_m": 10.0,
            "infiltration_mode": infil_mode,
        }
        with open(Path(MODEL_DIR) / 'model_meta.json', 'w') as _fp:
            _json.dump(meta, _fp, indent=2)
    except Exception:
        pass

    print(f"\n⚙️ Infiltration settings:")
    print(f"   Mode: {infil_mode}")
    print(f"   Bed thickness: {lakebed_thickness} m")
    print(f"   Bed K: {bed_k_mpd} m/day")
    if side_k_mpd is not None:
        print(f"   Bank K: {side_k_mpd} m/day")

    # If a previous OBS CSV exists, keep a copy for before/after comparison
    try:
        prev_csv = MODEL_DIR / f"{MODEL_NAME}_lak_stage_prev.csv"
        cur_csv = MODEL_DIR / f"{MODEL_NAME}_lak_stage.csv"
        if cur_csv.exists():
            if prev_csv.exists():
                prev_csv.unlink()
            cur_csv.rename(prev_csv)
            print(f"   💾 Preserved previous stage CSV as: {prev_csv.name}")
    except Exception as e:
        print(f"   ⚠️ Could not preserve previous stage CSV: {e}")
    
    # Write simulation
    print(f"\n📝 Writing model files...")
    sim.write_simulation()
    
    # Add LAK to name file manually
    gwf_nam_file = MODEL_DIR / f"{MODEL_NAME}.nam"
    with open(gwf_nam_file, 'r') as f:
        nam_lines = f.readlines()
    
    # Add LAK and ensure GHB is listed if missing
    add_lines = []
    need_write = False
    has_lak = any('LAK6' in line for line in nam_lines)
    for line in nam_lines:
        if 'OC6' in line:
            if not has_lak:
                add_lines.append(f"  LAK6  {Path(lak_file).name}\n")
                need_write = True
        add_lines.append(line)
    if need_write:
        with open(gwf_nam_file, 'w') as f:
            f.writelines(add_lines)
        print(f"   ✅ Added LAK package to model")
    
    # Run simulation
    print(f"\n🚀 Running MODFLOW 6 with time-varying inputs...")
    print(f"   📂 Working directory: {MODEL_DIR}")
    print(f"   ⏰ Stress periods: {len(stress_periods)}")
    print(f"   🌊 Storm duration: {storm_data['time_hours'].max():.1f} hours")
    
    try:
        success, buff = sim.run_simulation(silent=False)
        
        if success:
            print(f"\n🎉 SIMULATION COMPLETED SUCCESSFULLY!")
            print(f"\n📊 Phase 3 Step 3.2 - Time-Varying Inputs COMPLETE!")
            print(f"   ✅ Storm hydrograph successfully integrated")
            print(f"   ✅ Time-varying LAK package operational")
            print(f"   ✅ Dynamic infiltration modeling complete")
            
            # Post-process: visualize lake stage time series and max groundwater contours
            try:
                # Convert large allobs CSV to Parquet for space/perf, if possible
                try:
                    model_path = Path(MODEL_DIR)
                    csv_path = model_path / f"{MODEL_NAME}_lak_allobs.csv"
                    if csv_path.exists():
                        try:
                            import importlib.util as _ilus
                            if _ilus.find_spec('pyarrow') is None:
                                raise ImportError('pyarrow not installed')
                            df_conv = pd.read_csv(csv_path)
                            # Optional: downcast float64 to float32 to reduce size
                            try:
                                num_cols = [c for c in df_conv.columns if pd.api.types.is_float_dtype(df_conv[c]) or pd.api.types.is_integer_dtype(df_conv[c])]
                                for c in num_cols:
                                    if pd.api.types.is_float_dtype(df_conv[c]):
                                        df_conv[c] = df_conv[c].astype('float32')
                            except Exception:
                                pass
                            pq_path = model_path / f"{MODEL_NAME}_lak_allobs.parquet"
                            df_conv.to_parquet(pq_path, compression='snappy', index=False)
                            # Delete original CSV to save space
                            try:
                                csv_path.unlink()
                                print(f"   🗜️ Converted LAK allobs to Parquet: {pq_path.name} (removed CSV)")
                            except Exception:
                                print(f"   🗜️ Converted LAK allobs to Parquet: {pq_path.name}")
                        except ImportError:
                            # Fallback: gzip the CSV if pyarrow isn't available
                            try:
                                import gzip, shutil
                                gz = model_path / f"{MODEL_NAME}_lak_allobs.csv.gz"
                                with open(csv_path, 'rb') as f_in, gzip.open(gz, 'wb') as f_out:
                                    shutil.copyfileobj(f_in, f_out)
                                csv_path.unlink(missing_ok=True)
                                print(f"   🗜️ Compressed LAK allobs CSV: {gz.name}")
                            except Exception:
                                pass
                except Exception as _conv_err:
                    print(f"   ⚠️ LAK allobs Parquet conversion skipped: {_conv_err}")

                visualize_results(str(MODEL_DIR), MODEL_NAME, nrow, ncol, delr, delc)
            except Exception as e:
                print(f"   ⚠️ Visualization step encountered an issue: {e}")
            
            return True, sim
        else:
            print(f"\n❌ SIMULATION FAILED!")
            return False, None
            
    except Exception as e:
        print(f"\n💥 ERROR during simulation: {e}")
        return False, None

if __name__ == "__main__":
    success, simulation = run_phase3_step32_model()
    
    if success:
        print(f"\n🚀 Phase 3 Step 3.2 implementation complete!")
        print(f"📊 Time-varying storm inputs successfully integrated with LAK package")
    else:
        print(f"\n⚠️ Phase 3 Step 3.2 implementation encountered issues")


def run_phase3_step32_with_config(
    ts1_path: str | None,
    config: dict,
):
    """Run a single scenario using explicit inputs and write a summary JSON.

    config keys (all optional unless noted):
      - model_tag: short suffix for model/output naming
      - basin_geometry: {
            length_floor, width_floor, max_depth, side_slope_hv, floor_elev
        }
      - aquifer: {k_horizontal_mpd, k_vertical_mpd, sy, ss, initial_head}
      - infiltration: {mode, bed_thickness_m, bed_k_mpd, side_k_mpd}
      - post_storm_days: float (default 5)
      - post_storm_step_hours: float (default 12)
      - output_dir: optional absolute/relative path for outputs
    """
    from pathlib import Path
    import json
    import os, sys, traceback as _tb, datetime as _dt

    # Global trace (very early) so we know we entered the function even if we fail before directory creation.
    try:
        _trace_base = Path.home() / 'Documents' / 'BaSIM'
        _trace_base.mkdir(parents=True, exist_ok=True)
        _trace_file = _trace_base / 'onefile_trace.log'
        with _trace_file.open('a', encoding='utf-8') as _tf:
            _tf.write(f"[{_dt.datetime.utcnow().isoformat()}Z] ENTER run_phase3_step32_with_config ts1_path={ts1_path} frozen={getattr(sys,'frozen',False)} _MEIPASS={getattr(sys,'_MEIPASS',None)}\n")
    except Exception:
        pass

    # Wrap the entire body so ANY exception results in a scenario_summary + last_error persistence for GUI.
    try:
        return _run_phase3_body(ts1_path, config)
    except SystemExit:
        raise
    except Exception as _fatal:
        try:
            # Attempt to derive a minimal output directory to persist error if normal logic failed early
            scen = str(config.get('scenario_title','Scenario 1')).strip() or 'Scenario 1'
            # fallback base
            base_out = (Path.home()/ 'Documents' / 'BaSIM' / 'model_output' / 'phase3' / 'step32' / 'scenarios')
            base_out.mkdir(parents=True, exist_ok=True)
            scen_dir = base_out / scen
            scen_dir.mkdir(parents=True, exist_ok=True)
            # Write generic failure markers (no ts1 shortening because parsing may be cause)
            err_txt = f"FATAL (early) in run_phase3_step32_with_config: {_fatal}\n\n{_tb.format_exc()}"
            (scen_dir / 'last_error.txt').write_text(err_txt, encoding='utf-8')
            summary = {"success": False, "error": str(_fatal), "ts1_file": str(ts1_path), "scenario": scen, "model_name": "phase3_step32"}
            (scen_dir / 'scenario_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
            try:
                with _trace_file.open('a', encoding='utf-8') as _tf:
                    _tf.write(f"[{_dt.datetime.utcnow().isoformat()}Z] EARLY_FATAL persisted scenario_dir={scen_dir} error={_fatal}\n")
            except Exception:
                pass
            return False, summary, str(scen_dir)
        except Exception:
            # Last resort: global trace only
            try:
                with _trace_file.open('a', encoding='utf-8') as _tf:
                    _tf.write(f"[{_dt.datetime.utcnow().isoformat()}Z] EARLY_FATAL_NO_PERSIST error={_fatal}\n")
            except Exception:
                pass
            return False, {"success": False, "error": str(_fatal), "ts1_file": str(ts1_path)}, ''


def _run_phase3_body(ts1_path: str | None, config: dict):
    """Internal body of run_phase3_step32_with_config separated so outer wrapper can catch early fatals."""
    from pathlib import Path
    import json

    # Defaults
    model_tag = str(config.get("model_tag", "gui"))
    basin_cfg = config.get("basin_geometry", {})
    aquifer = config.get("aquifer", {})
    infil = config.get("infiltration", {})
    # Performance presets (fast/balanced/accurate)
    def _perf_defaults(mode: str | None) -> dict:
        m = str(mode or 'balanced').strip().lower()
        if m == 'fast':
            return {
                'grid': {'domain_factor': 10.0, 'refinement_zones': 3, 'min_cell_divisor': 15.0, 'min_floor_m': 1.5, 'max_cell_size': 30.0},
                'time': {'pre_storm_steps': 2, 'pre_storm_step_hours': 0.5, 'pre_storm_nstp': 3, 'post_storm_step_hours': 12.0, 'refine': True, 'nstp_max': 5},
                'solver': {'ims_outer_dvclose': 5e-3, 'ims_outer_max': 300, 'ims_inner_dvclose': 5e-5, 'ims_inner_max': 300, 'ims_rclose': 0.05, 'ims_under_relax': 'DBD', 'ims_reordering': 'rcm', 'ims_linear_accel': 'BICGSTAB'},
                'physics': {'xt3d': False},
            }
        if m == 'accurate':
            return {
                'grid': {'domain_factor': 16.0, 'refinement_zones': 5, 'min_cell_divisor': 45.0, 'min_floor_m': 0.5, 'max_cell_size': 20.0},
                'time': {'pre_storm_steps': 4, 'pre_storm_step_hours': 0.5, 'pre_storm_nstp': 6, 'post_storm_step_hours': 6.0, 'refine': True, 'nstp_max': 12},
                'solver': {'ims_outer_dvclose': 5e-4, 'ims_outer_max': 800, 'ims_inner_dvclose': 5e-6, 'ims_inner_max': 800, 'ims_rclose': 0.005, 'ims_under_relax': 'DBD', 'ims_reordering': 'rcm', 'ims_linear_accel': 'BICGSTAB'},
                'physics': {'xt3d': True},
            }
    
        # balanced default
        return {
            'grid': {'domain_factor': 12.0, 'refinement_zones': 4, 'min_cell_divisor': 25.0, 'min_floor_m': 1.0, 'max_cell_size': 25.0},
            'time': {'pre_storm_steps': 3, 'pre_storm_step_hours': 0.5, 'pre_storm_nstp': 5, 'post_storm_step_hours': 8.0, 'refine': True, 'nstp_max': 8},
            'solver': {'ims_outer_dvclose': 1e-3, 'ims_outer_max': 500, 'ims_inner_dvclose': 1e-5, 'ims_inner_max': 500, 'ims_rclose': 0.01, 'ims_under_relax': 'DBD', 'ims_reordering': 'rcm', 'ims_linear_accel': 'BICGSTAB'},
            'physics': {'xt3d': False},
        }

    perf_cfg = config.get('perf', {}) if isinstance(config.get('perf', {}), dict) else {}
    perf_mode = str(perf_cfg.get('mode', 'balanced'))
    _perf = _perf_defaults(perf_mode)

    # Default to 3 days post-storm unless overridden; use perf profile for step size
    post_days = float(config.get("post_storm_days", 3.0))
    post_step_h = float(config.get("post_storm_step_hours", _perf['time']['post_storm_step_hours']))
    scenario_title = str(config.get("scenario_title", "Scenario 1")).strip() or "Scenario 1"
    run_id = str(config.get("run_id", ""))
    lightweight_outputs = bool(config.get("lightweight_outputs", True))
    cleanup_heavy = bool(config.get("cleanup_heavy", True))
    # Optional per-run progress file for GUI polling
    progress_file = config.get("progress_file")

    # Determine basin source mode: DEM file vs manual geometry
    use_dem = basin_cfg.get("source") == "dem"
    dem_cfg = None
    if use_dem:
        from utils.dem_parser import parse_dem_file
        from utils.dem_model_builder import build_dem_model_config

        _dem_path = basin_cfg.get("dem_file", "")
        _dem_crest = float(basin_cfg.get("crest_elev", 10.0))
        _dem_min_cell = float(basin_cfg.get("min_cell_size_m", 0.0))
        print(f"📊 DEM Mode: parsing {Path(_dem_path).name}")
        dem_grid = parse_dem_file(_dem_path)
        if dem_grid.is_geographic:
            print("   ⚠️ DEM uses geographic (lat/lon) CRS — cell sizes in degrees, not metres.")
        dem_cfg = build_dem_model_config(dem_grid, crest_elev=_dem_crest,
                                         min_cell_size_m=_dem_min_cell)
        # Create a compatibility BasinGeometry so downstream code (IMS, metadata) works
        basin_geom = BasinGeometry(
            length_floor=dem_cfg.ncol * dem_cfg.cell_size_x,
            width_floor=dem_cfg.nrow * dem_cfg.cell_size_y,
            max_depth=dem_cfg.max_depth,
            side_slope_hv=2.0,  # not applicable for DEM but needed by dataclass
            floor_elev=dem_cfg.floor_elev,
        )
    else:
        basin_geom = BasinGeometry(
            length_floor=float(basin_cfg.get("length_floor", 50.0)),
            width_floor=float(basin_cfg.get("width_floor", 50.0)),
            max_depth=float(basin_cfg.get("max_depth", 2.0)),
            side_slope_hv=float(basin_cfg.get("side_slope_hv", 2.0)),
            floor_elev=float(basin_cfg.get("floor_elev", 5.0)),
        )

    initial_groundwater_head = float(aquifer.get("initial_head", 5.0))
    k_horizontal = float(aquifer.get("k_horizontal_mpd", 20.0))
    # If vertical not provided, default to horizontal (supports Overall K input)
    k_vertical = float(aquifer.get("k_vertical_mpd", k_horizontal))
    bottom_elev = aquifer.get("bottom_elev")
    sy = float(aquifer.get("sy", 0.05))
    ss = float(aquifer.get("ss", 1e-5))

    infil_mode = str(infil.get("mode", "vertical")).lower()
    bed_thk = float(infil.get("bed_thickness_m", 0.5))
    bed_k_mpd = float(infil.get("bed_k_mpd", 5.0))
    side_k_mpd = infil.get("side_k_mpd")
    side_k_mpd = float(side_k_mpd) if side_k_mpd is not None else None

    # Output directory structure:
    # <base_out>/<Scenario Title>/{inputs,outputs}/<short_ts1>
    PROJECT_ROOT = Path(__file__).parent.parent
    # Choose a writable default base output folder if not provided
    if config.get("output_dir"):
        base_out = Path(config["output_dir"])  # user-defined
    else:
        try:
            # Prefer Documents\BaSIM\model_output
            docs = Path.home() / 'Documents'
            base_out = docs / 'BaSIM' / 'model_output' / 'phase3' / 'step32' / 'scenarios'
            base_out.mkdir(parents=True, exist_ok=True)
        except Exception:
            base_out = PROJECT_ROOT / "model_output" / "phase3" / "step32" / "scenarios"
    scen_dir = base_out / scenario_title
    inputs_dir = scen_dir / "inputs"
    outputs_root = scen_dir / "outputs"
    # Shorten TS1 name to key tokens: ~s1 (AEP), ~s2 (duration), optional ~s3 (TP)
    # Robust to spaces/underscores and punctuation; also scan parent folders; fallback to first line of file; then to stem.
    def _short_ts1(name: str) -> str:
        import re
        from pathlib import Path as _Path

        def _extract_tokens(text: str):
            """Return (s1, s2, s3) from given text, case-insensitive.
            - s1: AEP like '1pct', '6EY', '1in100'
            - s2: duration like '1h', '45m', '2d'
            - s3: TP like 'TP10'
            """
            s1 = s2 = s3 = None
            t = text or ""

            # Normalize separators to spaces for easier regexing
            t_sp = re.sub(r"[_,]+", " ", t)

            # AEP patterns
            m_pct = re.search(r"\b(\d+)\s*%\b", t_sp, re.IGNORECASE)
            m_aep_pct = re.search(r"\baep\s*(\d+)\s*%\b", t_sp, re.IGNORECASE)
            m_pc = re.search(r"\b(\d+)\s*p(?:c|ct)\b", t_sp, re.IGNORECASE)
            m_ey = re.search(r"\b(\d+)\s*ey\b", t_sp, re.IGNORECASE)
            m_1inx = re.search(r"\b1\s*in\s*(\d+)\b", t_sp, re.IGNORECASE)
            # ARI patterns (e.g., ARI 100 yr)
            m_ari1 = re.search(r"\bari\s*(\d+)\s*(?:yr|year|years)?\b", t_sp, re.IGNORECASE)
            m_ari2 = re.search(r"\b(\d+)\s*(?:yr|year|years)\s*ari\b", t_sp, re.IGNORECASE)
            if m_pct:
                s1 = f"{m_pct.group(1)}pct"
            elif m_aep_pct:
                s1 = f"{m_aep_pct.group(1)}pct"
            elif m_pc:
                s1 = f"{m_pc.group(1)}pct"
            elif m_ey:
                s1 = f"{m_ey.group(1)}EY"
            elif m_1inx:
                s1 = f"1in{m_1inx.group(1)}"
            elif m_ari1:
                s1 = f"1in{m_ari1.group(1)}"
            elif m_ari2:
                s1 = f"1in{m_ari2.group(1)}"

            # Duration patterns
            m_h_word = re.search(r"\b(\d+)\s*h(?:our|r|rs)?\b", t_sp, re.IGNORECASE)
            m_m_word = re.search(r"\b(\d+)\s*m(?:in(?:ute)?s?)?\b", t_sp, re.IGNORECASE)
            m_d_word = re.search(r"\b(\d+)\s*d(?:ay)?s?\b", t_sp, re.IGNORECASE)
            # Also catch compact forms like '1h', '45m'
            m_h_compact = re.search(r"\b(\d+)h\b", t_sp, re.IGNORECASE)
            m_m_compact = re.search(r"\b(\d+)m\b", t_sp, re.IGNORECASE)
            m_d_compact = re.search(r"\b(\d+)d\b", t_sp, re.IGNORECASE)
            if m_h_word:
                s2 = f"{m_h_word.group(1)}h"
            elif m_h_compact:
                s2 = f"{m_h_compact.group(1)}h"
            elif m_m_word:
                s2 = f"{m_m_word.group(1)}m"
            elif m_m_compact:
                s2 = f"{m_m_compact.group(1)}m"
            elif m_d_word:
                s2 = f"{m_d_word.group(1)}d"
            elif m_d_compact:
                s2 = f"{m_d_compact.group(1)}d"

            # Temporal Pattern: TPxx, TPxxxx, or 'Storm 3' → TP3
            m_tp = re.search(r"\bTP\s*0*(\d+)\b", t_sp, re.IGNORECASE)
            m_storm = re.search(r"\bstorm\s*0*(\d+)\b", t_sp, re.IGNORECASE)
            if m_tp:
                s3 = f"TP{int(m_tp.group(1))}"
            elif m_storm:
                s3 = f"TP{int(m_storm.group(1))}"

            return s1, s2, s3

        p = _Path(name)
        stem = p.stem
        s1, s2, s3 = _extract_tokens(stem)

        # If ambiguous, try first few lines of file headers (to catch 'Storm 3' etc.)
        if not (s1 and s2):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    for _ in range(10):
                        ln = f.readline()
                        if not ln:
                            break
                        s1f, s2f, s3f = _extract_tokens(ln.strip())
                        s1 = s1 or s1f
                        s2 = s2 or s2f
                        s3 = s3 or s3f
                        if s1 and s2 and s3:
                            break
            except Exception:
                pass

        # If still missing AEP, scan parent folder names for tokens like AEP/ARI/1 in X
        if not s1:
            try:
                parts = [q for q in p.parts[-5:]]  # look up to 5 levels up
                for txt in reversed(parts):  # closest parents first
                    s1f, _, s3f = _extract_tokens(txt)
                    if s1f:
                        s1 = s1f
                        if not s3 and s3f:
                            s3 = s3f
                        break
            except Exception:
                pass

        # Build short name
        parts = []
        if s1:
            parts.append(s1)
        if s2:
            parts.append(s2)
        if s3:
            parts.append(s3)

        if parts:
            short = "_".join(parts)
        else:
            short = stem

        # Keep it short and filesystem-safe
        short = re.sub(r"[^A-Za-z0-9_]+", "", short)
        if len(short) > 40:
            short = short[:40]
        return short
    # Ultra-early trace around TS1 shortening (can be a failure point if file inaccessible)
    try:
        from pathlib import Path as _P2
        import datetime as _dt2, sys as _sys2
        _trace_base2 = _P2.home() / 'Documents' / 'BaSIM'
        _trace_file2 = _trace_base2 / 'onefile_trace.log'
        with _trace_file2.open('a', encoding='utf-8') as _tf2:
            _tf2.write(f"[{_dt2.datetime.utcnow().isoformat()}Z] TRACE before_shortening ts1_path={ts1_path} scenario_title={scenario_title} frozen={getattr(_sys2,'frozen',False)}\n")
    except Exception:
        pass
    ts1_short = _short_ts1(ts1_path) if ts1_path else "synthetic"
    try:
        from pathlib import Path as _P3, datetime as _dt3
        _trace_file3 = _P3.home() / 'Documents' / 'BaSIM' / 'onefile_trace.log'
        with _trace_file3.open('a', encoding='utf-8') as _tf3:
            _tf3.write(f"[{_dt3.datetime.utcnow().isoformat()}Z] TRACE after_shortening ts1_short={ts1_short}\n")
    except Exception:
        pass
    MODEL_DIR = outputs_root / ts1_short
    # Optional variant tag allows caller to separate runs (e.g., different grids)
    variant_tag = str(config.get("output_variant_tag", "")).strip()
    if variant_tag:
        MODEL_DIR = MODEL_DIR / variant_tag
    # Create directories
    inputs_dir.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from pathlib import Path as _P4, datetime as _dt4
        _trace_file4 = _P4.home() / 'Documents' / 'BaSIM' / 'onefile_trace.log'
        with _trace_file4.open('a', encoding='utf-8') as _tf4:
            _tf4.write(f"[{_dt4.datetime.utcnow().isoformat()}Z] TRACE dirs_created model_dir={MODEL_DIR}\n")
    except Exception:
        pass
    # Always drop a quick marker so we can verify run_phase3_step32_with_config started
    try:
        from datetime import datetime as _dt
        (Path(MODEL_DIR) / 'run_marker.txt').write_text(
            f"Run started at {_dt.utcnow().isoformat()}Z\n"
            f"ts1_path={ts1_path}\n"
            f"scenario_title={scenario_title}\n"
            f"cwd={os.getcwd()}\n"
            f"python_exe={sys.executable}\n"
            f"frozen={getattr(sys,'frozen',False)} _MEIPASS={getattr(sys,'_MEIPASS',None)}\n",
            encoding='utf-8'
        )
    except Exception:
        pass
    # EARLY progress file creation so GUI can discover model_dir even if we fail before meta init
    try:
        if progress_file and not os.path.exists(progress_file):
            import json as _json
            with open(progress_file, 'w', encoding='utf-8') as _pf_early:
                _json.dump({
                    "current": 0,
                    "total": 1,
                    "model_dir": str(MODEL_DIR),
                    "state": "initializing"
                }, _pf_early)
    except Exception:
        pass

    # Persist a per-run config snapshot inside the output folder
    config_hash = None
    try:
        import json as _json
        import hashlib as _hashlib
        cfg_snapshot = {
            "ts1_path": str(ts1_path),
            "scenario_title": scenario_title,
            "basin_geometry": basin_cfg,
            "aquifer": aquifer,
            "infiltration": infil,
            "perf": perf_cfg,
            "post_storm_days": post_days,
            "post_storm_step_hours": post_step_h,
        }
        cfg_text = _json.dumps(cfg_snapshot, sort_keys=True, indent=2)
        (Path(MODEL_DIR) / "config_used.json").write_text(cfg_text, encoding="utf-8")
        config_hash = _hashlib.sha256(cfg_text.encode("utf-8")).hexdigest()[:10]
    except Exception:
        config_hash = None

    # Helper to persist early errors so GUI/users see a reason in the output folder
    def _persist_error_and_summary(msg):
        try:
            from pathlib import Path as _P
            import traceback as _tb
            import json as _json
            p = _P(MODEL_DIR)
            # Compose detailed error text with optional traceback
            if isinstance(msg, BaseException):
                err_txt = f"{msg}\n\n{_tb.format_exc()}"
            else:
                err_txt = str(msg)
            # Attach quick context to help diagnose shape mismatches
            try:
                ctx = {
                    "storm_rows": int(len(storm_data)) if 'storm_data' in locals() and storm_data is not None else None,
                    "stress_periods": int(len(stress_periods)) if 'stress_periods' in locals() else None,
                    "inflow_per_sp": int(len(inflow_per_sp)) if 'inflow_per_sp' in locals() else None,
                    "nrow": int(nrow) if 'nrow' in locals() and nrow is not None else None,
                    "ncol": int(ncol) if 'ncol' in locals() and ncol is not None else None,
                    "delr_len": (int(len(delr)) if 'delr' in locals() and hasattr(delr, '__len__') else (1 if 'delr' in locals() and delr is not None else None)),
                    "delc_len": (int(len(delc)) if 'delc' in locals() and hasattr(delc, '__len__') else (1 if 'delc' in locals() and delc is not None else None)),
                    "basin_cells": (int(len(basin_cells)) if 'basin_cells' in locals() and basin_cells is not None else None),
                }
                err_txt += f"\n\n[context] {ctx}"
            except Exception:
                pass
            (p / 'last_error.txt').write_text(err_txt, encoding='utf-8')
            summary = {
                "success": False,
                "error": err_txt.splitlines()[0] if err_txt else "",
                "ts1_file": str(ts1_path),
                "scenario": scenario_title,
                "model_name": MODEL_NAME,
            }
            (p / 'scenario_summary.json').write_text(_json.dumps(summary, indent=2), encoding='utf-8')
        except Exception:
            pass

    # Model naming (<=16 chars)
    BASE_MODEL_NAME = "bas32"
    mode_suffix = "vert" if infil_mode.startswith("v") else ("full" if infil_mode.startswith("f") else infil_mode[:4])
    MODEL_NAME = f"{BASE_MODEL_NAME}_{mode_suffix}"[:16]

    # Read storm
    # Optional TS1 column preference
    ts1_col = config.get("ts1_column_index")
    storm_data = None
    total_inflow_ts1_m3 = None
    total_inflow_sp_m3 = None
    try:
        if ts1_path and Path(ts1_path).exists():
            storm_data = read_ts1_file(ts1_path, preferred_column=ts1_col, allow_synthetic=False)
    except Exception:
        storm_data = None
    if storm_data is None:
        # Fallback to synthetic hydrograph
        storm_data = generate_synthetic_storm()
    # Compute TS1 total inflow (m3) from the raw hydrograph
    try:
        t_sec = storm_data['time_hours'].values.astype(float) * 3600.0
        q = storm_data['flow_m3s'].values.astype(float)
        if hasattr(np, 'trapezoid'):
            total_inflow_ts1_m3 = float(np.trapezoid(q, t_sec))
        else:
            total_inflow_ts1_m3 = float(np.trapz(q, t_sec))
    except Exception:
        total_inflow_ts1_m3 = None
    # Save inflow CSV in outputs subfolder
    try:
        inflow_csv = MODEL_DIR / 'inflow_timeseries.csv'
        inflow_df = pd.DataFrame({
            'time_hours': storm_data['time_hours'].values,
            'time_days': storm_data['time_hours'].values / 24.0,
            'flow_m3s': storm_data['flow_m3s'].values,
            'flow_m3day': storm_data['flow_m3s'].values * 86400.0,
        })
        inflow_df.to_csv(inflow_csv, index=False)
    except Exception:
        pass
    # Save TS1 inputs (provenance + hydrograph) under inputs/<ts1_short>/
    try:
        from shutil import copy2
        ts1_in_dir = inputs_dir / ts1_short
        ts1_in_dir.mkdir(parents=True, exist_ok=True)
        # Copy original TS1 (or companion if detected)
        try:
            src_info = inspect_ts1_columns(ts1_path)
            src_used = src_info.get('source_path', ts1_path)
        except Exception:
            src_used = ts1_path
        try:
            copy2(src_used, ts1_in_dir / Path(src_used).name)
        except Exception:
            pass
        # Write parsed hydrograph CSV
        hydro_csv = ts1_in_dir / 'hydrograph.csv'
        pd.DataFrame({
            'time_hours': storm_data['time_hours'].values,
            'time_minutes': storm_data['time_hours'].values * 60.0,
            'flow_m3s': storm_data['flow_m3s'].values,
            'flow_m3day': storm_data['flow_m3s'].values * 86400.0,
        }).to_csv(hydro_csv, index=False)
        # Plot hydrograph image
        try:
            import matplotlib.pyplot as _plt
            fig, ax = _plt.subplots(figsize=(8, 4))
            ax.plot(storm_data['time_hours'].values, storm_data['flow_m3s'].values, 'b-', lw=2)
            ax.set_xlabel('Time (hours)')
            ax.set_ylabel('Flow (m3/s)')
            ax.set_title('Input Hydrograph')
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            fig.savefig(ts1_in_dir / 'hydrograph.png', dpi=150)
            _plt.close(fig)
        except Exception:
            pass
    except Exception:
        pass
    # Save inputs parameters as CSV and PNG under inputs/
    try:
        params_csv = inputs_dir / 'parameters.csv'
        param_rows = []
        def add_param(section, name, value):
            param_rows.append({"section": section, "name": name, "value": value})
        # Basin
        add_param("basin", "length_floor_m", basin_geom.length_floor)
        add_param("basin", "width_floor_m", basin_geom.width_floor)
        add_param("basin", "max_depth_m", basin_geom.max_depth)
        add_param("basin", "side_slope_hv", basin_geom.side_slope_hv)
        add_param("basin", "floor_elev_mAHD", basin_geom.floor_elev)
        # Aquifer
        add_param("aquifer", "initial_head_mAHD", initial_groundwater_head)
        add_param("aquifer", "k_horizontal_mpd", k_horizontal)
        add_param("aquifer", "k_vertical_mpd", k_vertical)
        add_param("aquifer", "sy", sy)
        add_param("aquifer", "ss", ss)
        add_param("aquifer", "bottom_elev_mAHD", (bottom_elev if bottom_elev is not None else ""))
        # Infiltration
        add_param("infiltration", "mode", infil.get("mode", "vertical"))
        add_param("infiltration", "bed_thickness_m", bed_thk)
        add_param("infiltration", "bed_k_mpd", bed_k_mpd)
        add_param("infiltration", "side_k_mpd", ("" if side_k_mpd is None else side_k_mpd))
        # Time control
        add_param("time", "post_storm_days", post_days)
        add_param("time", "post_storm_step_hours", post_step_h)
        pd.DataFrame(param_rows).to_csv(params_csv, index=False)
        # Render a styled table PNG
        try:
            from utils.style_guide import render_table_png, prettify_name
            # prettify labels
            rows = [[str(r['section']), prettify_name(str(r['name'])), r['value']] for r in param_rows]
            cols = ["section", "parameter", "value"]
            render_table_png(rows, cols, str(inputs_dir / 'parameters.png'), title='Model Parameters')
        except Exception:
            pass
    # 3D geometry snapshot removed to keep runs lightweight
    except Exception:
        pass

    # Grid setup
    try:
        laktab_rows_dem = None

        if use_dem and dem_cfg is not None:
            # ---- DEM-driven grid ----
            nlay = dem_cfg.nlay
            nrow = dem_cfg.nrow
            ncol = dem_cfg.ncol
            delr = dem_cfg.delr
            delc = dem_cfg.delc
            top = dem_cfg.top            # 2-D ndarray from DEM
            botm = dem_cfg.botm
            basin_floor = dem_cfg.floor_elev
            lakebed_thickness = bed_thk
            lake_initial_stage = basin_floor
            conn_layer = 0               # basin sits entirely in layer 0
            basin_rows_arr, basin_cols_arr = np.where(dem_cfg.basin_mask)
            basin_cells_2d = list(zip(basin_rows_arr.tolist(), basin_cols_arr.tolist()))
            basin_cells = [(conn_layer, r, c) for r, c in basin_cells_2d]
            laktab_rows_dem = dem_cfg.laktab_rows
            print(f"   ✅ DEM grid: {nrow}×{ncol}, {nlay} layers, "
                  f"{len(basin_cells)} basin cells")

        else:
            # ---- Manual geometry grid ----
            nlay = 8
            # Use preset domain factor so boundaries are far from the basin
            dom_factor = suggest_domain_factor(basin_geom, min_factor=float(_perf['grid']['domain_factor']), pad_multiplier=4.0)
            # Allow grid overrides via config["grid"]
            grid_cfg = config.get("grid", {}) if isinstance(config.get("grid", {}), dict) else {}
            refinement_zones = int(grid_cfg.get("refinement_zones", _perf['grid']['refinement_zones']))
            max_cell_size = float(grid_cfg.get("max_cell_size", _perf['grid']['max_cell_size']))
            # Domain factor override
            domain_factor_override = grid_cfg.get("domain_factor")
            if domain_factor_override is not None:
                try:
                    dom_factor = float(domain_factor_override)
                except Exception:
                    pass
            # If explicit min_cell_size not given, compute from performance profile
            if "min_cell_size" in grid_cfg:
                min_cell_size = float(grid_cfg.get("min_cell_size"))
            else:
                try:
                    from utils.performance_profiles import compute_min_cell_size_from_basin
                    # Allow overrides for divisor/floor; fallback to preset
                    perf_div = perf_cfg.get("divisor", _perf['grid']['min_cell_divisor'])
                    perf_floor = perf_cfg.get("min_floor_m", _perf['grid']['min_floor_m'])
                    min_cell_size = compute_min_cell_size_from_basin(
                        basin_length_m=basin_geom.length_floor,
                        basin_width_m=basin_geom.width_floor,
                        divisor=perf_div,
                        min_floor_m=perf_floor,
                        mode=perf_mode,
                    )
                except Exception:
                    min_cell_size = 2.0
            # Enforce lower bound of 0.5 m per user requirement
            if min_cell_size < 0.5:
                min_cell_size = 0.5
            grid_info = create_adaptive_refined_grid(
                basin_length=basin_geom.length_floor,
                basin_width=basin_geom.width_floor,
                domain_factor=float(dom_factor),
                refinement_zones=refinement_zones,
                min_cell_size=min_cell_size,
                max_cell_size=max_cell_size,
            )
            nrow, ncol = grid_info['nrow'], grid_info['ncol']
            delr, delc = grid_info['delr'], grid_info['delc']
            basin_rows = grid_info['basin_rows']
            basin_cols = grid_info['basin_cols']
            basin_cells_2d = [(r, c) for r in range(basin_rows[0], basin_rows[1]) for c in range(basin_cols[0], basin_cols[1])]

            layer_thickness = [2, 3, 5, 8, 10, 12, 15, 20]
            # Select a top that sits above basin floor + max depth and initial GW
            top_baseline = max(10.0, basin_geom.floor_elev + basin_geom.max_depth + 3.0, initial_groundwater_head + 2.0)
            top = float(top_baseline)
            if bottom_elev is not None:
                try:
                    bottom_elev = float(bottom_elev)
                    if bottom_elev >= top:
                        top = bottom_elev + 1.0
                    total_thk = top - bottom_elev
                    w = np.array(layer_thickness, dtype=float)
                    frac = w / np.sum(w)
                    thk_scaled = (frac * total_thk).tolist()
                    thk_scaled = [max(0.5, t) for t in thk_scaled]
                    diff = total_thk - sum(thk_scaled)
                    thk_scaled[-1] += diff
                    botm = [top - sum(thk_scaled[:i+1]) for i in range(nlay)]
                except Exception:
                    botm = [top - sum(layer_thickness[:i+1]) for i in range(nlay)]
            else:
                botm = [top - sum(layer_thickness[:i+1]) for i in range(nlay)]
            basin_floor = float(basin_geom.floor_elev)
            lakebed_thickness = bed_thk
            lake_initial_stage = basin_floor

            conn_layer = None
            for k in range(nlay):
                lay_top = top if k == 0 else botm[k-1]
                lay_bot = botm[k]
                if lay_bot < basin_floor <= lay_top:
                    conn_layer = k
                    break
            if conn_layer is None:
                for k in range(nlay):
                    if basin_floor > botm[k]:
                        conn_layer = k
                        break
            if conn_layer is None:
                conn_layer = 0

            # NOTE: Connection-layer deepening hack removed.
            # UZF+MVR now handles vadose zone infiltration correctly for all
            # water table depths, so artificially thickening the connection
            # layer is no longer needed.

            basin_cells = [(conn_layer, r, c) for (r, c) in basin_cells_2d]

        # Time discretization
        storm_duration_h = float(np.max(storm_data['time_hours'].values))
        total_sim_hours = storm_duration_h + post_days * 24.0
        stress_periods, inflow_per_sp = create_time_varying_stress_periods(
            storm_data,
            total_sim_hours,
            post_storm_step_hours=post_step_h,
            pre_storm_steps=int(perf_cfg.get('pre_storm_steps', _perf['time']['pre_storm_steps'])),
            pre_storm_step_hours=float(perf_cfg.get('pre_storm_step_hours', _perf['time']['pre_storm_step_hours'])),
            pre_storm_nstp=int(perf_cfg.get('pre_storm_nstp', _perf['time']['pre_storm_nstp'])),
            refine=bool(perf_cfg.get('refine', _perf['time']['refine'])),
            nstp_max=int(perf_cfg.get('nstp_max', _perf['time']['nstp_max'])),
        )
        # Total inflow from stress periods (m3)
        try:
            sp_lengths_h = [float(sp[0]) for sp in stress_periods]
            q_sp = np.array(inflow_per_sp, dtype=float)
            total_inflow_sp_m3 = float(np.sum(q_sp[:len(sp_lengths_h)] * np.array(sp_lengths_h) * 3600.0))
        except Exception:
            total_inflow_sp_m3 = None
        # Guard: ensure aligned inflow list matches stress periods
        if len(inflow_per_sp) != len(stress_periods):
            _persist_error_and_summary(RuntimeError(f"Aligned inflow list length {len(inflow_per_sp)} != stress periods {len(stress_periods)}"))
            return {
                "success": False,
                "error": "inflow_per_sp length mismatch",
            }
        # Progress metadata path
        meta_path = Path(MODEL_DIR) / 'run_meta.json'
        try:
            steps_per_period = [int(sp[1]) for sp in stress_periods]
            total_steps = int(np.sum(steps_per_period))
            init_meta = {
                "run_id": run_id,
                "scenario_title": scenario_title,
                "ts1_short": ts1_short,
                "total_periods": len(stress_periods),
                "total_steps": total_steps,
                "completed_periods": 0,
                "completed_steps": 0,
                "current_period": 0,
                "current_timestep": 0,
                "steps_in_current_period": 0,
                "state": "building",
            }
            with open(meta_path, 'w') as fp:
                json.dump(init_meta, fp)
        except Exception:
            pass
        # Build MF6 Simulation and TDIS using the computed stress periods before configuring IMS
        try:
            tdis_data = []
            for sp_length_h, nsteps, mult in stress_periods:
                # Convert hours to days for TDIS perioddata
                tdis_data.append([float(sp_length_h) / 24.0, int(nsteps), float(mult)])
            sim = flopy.mf6.MFSimulation(
                sim_name=MODEL_NAME,
                sim_ws=str(MODEL_DIR),
                exe_name=find_mf6_exe(),
            )
            tdis = flopy.mf6.ModflowTdis(
                sim,
                time_units="DAYS",
                nper=len(stress_periods),
                perioddata=tdis_data,
            )
        except Exception as _e:
            _persist_error_and_summary(_e)
            return {"success": False, "error": f"TDIS/Simulation setup failed: {_e}"}

        # IMS from performance preset; relax within preset if geometry is hard (unless already 'accurate')
        # Determine if geometry/timing likely needs more relaxed solver tolerances.
        try:
            needs_relax = (
                float(basin_geom.max_depth) > 3.0 or
                float(basin_geom.side_slope_hv) < 1.5 or
                abs(float(basin_geom.floor_elev) - float(initial_groundwater_head)) < 0.5
            )
        except Exception:
            # On any parsing error, default to not relaxing beyond the preset
            needs_relax = False
        ims_defaults = _perf['solver']
        if needs_relax and perf_mode != 'accurate':
            print("   🔧 Challenging geometry detected → relaxing IMS within preset")
            ims_defaults = {
                **ims_defaults,
                'ims_outer_dvclose': max(ims_defaults['ims_outer_dvclose'], 2e-3),
                'ims_inner_dvclose': max(ims_defaults['ims_inner_dvclose'], 2e-5),
                'ims_outer_max': max(ims_defaults['ims_outer_max'], 700),
                'ims_inner_max': max(ims_defaults['ims_inner_max'], 700),
                'ims_rclose': max(ims_defaults['ims_rclose'], 0.02),
            }
        ims = flopy.mf6.ModflowIms(
            sim,
            print_option="SUMMARY",
            complexity="COMPLEX",
            outer_dvclose=float(ims_defaults['ims_outer_dvclose']),
            outer_maximum=int(ims_defaults['ims_outer_max']),
            under_relaxation=str(ims_defaults['ims_under_relax']),
            linear_acceleration=str(ims_defaults['ims_linear_accel']),
            reordering_method=str(ims_defaults['ims_reordering']),
            inner_maximum=int(ims_defaults['ims_inner_max']),
            inner_dvclose=float(ims_defaults['ims_inner_dvclose']),
            rcloserecord=[float(ims_defaults['ims_rclose']), "STRICT"],
            backtracking_number=20,
            backtracking_tolerance=2.0,
            backtracking_reduction_factor=0.2,
            backtracking_residual_limit=0.0,
        )
        gwf = flopy.mf6.ModflowGwf(sim, modelname=MODEL_NAME, save_flows=True, newtonoptions="NEWTON UNDER_RELAXATION")
        dis = flopy.mf6.ModflowGwfdis(gwf, nlay=nlay, nrow=nrow, ncol=ncol, delr=delr, delc=delc, top=top, botm=botm)
        ic = flopy.mf6.ModflowGwfic(gwf, strt=initial_groundwater_head)
        xt3d_flag = bool(perf_cfg.get('xt3d', _perf['physics']['xt3d']))
        npf = flopy.mf6.ModflowGwfnpf(
            gwf,
            save_flows=True,
            icelltype=1,
            k=k_horizontal,
            k33=k_vertical,
            xt3doptions=xt3d_flag,
        )
        sto = flopy.mf6.ModflowGwfsto(gwf, save_flows=True, iconvert=1, ss=ss, sy=sy)

        # General Head Boundary (edges) — simplified: apply on all layers with fixed defaults
        def _as_array(v, n):
            return np.array(v) if hasattr(v, '__len__') else np.full(n, v)
        delr_arr = _as_array(delr, ncol)
        delc_arr = _as_array(delc, nrow)
        ghb_list = []
        K_edge = float(k_horizontal)
        # Tuning removed; use fixed defaults
        ghb_mult = 10.0
        head_offset = 0.0
        use_all_layers = True

        # Helper to compute per-layer thickness and valid boundary head
        # (handles both scalar top for manual mode and 2-D array for DEM mode)
        def _layer_top(k, i=None, j=None):
            if k == 0:
                if isinstance(top, np.ndarray) and top.ndim == 2:
                    if i is not None and j is not None:
                        return float(top[i, j])
                    return float(np.max(top))
                return float(top)
            return botm[k - 1]
        def _layer_bot(k):
            return botm[k]

        for i in range(nrow):
            for j in range(ncol):
                if not (i == 0 or i == nrow - 1 or j == 0 or j == ncol - 1):
                    continue
                if j == 0 or j == ncol - 1:
                    width = float(delc_arr[i]); distance = max(0.5 * float(delr_arr[j]), 1e-6)
                else:
                    width = float(delr_arr[j]); distance = max(0.5 * float(delc_arr[i]), 1e-6)

                k_layers = range(nlay) if use_all_layers else [conn_layer]
                for k in k_layers:
                    lay_top = _layer_top(k, i, j)
                    lay_bot = _layer_bot(k)
                    layer_thk = float(lay_top - lay_bot)
                    if layer_thk <= 0:
                        layer_thk = 1.0
                    # Only apply GHB where initial head is above the cell bottom.
                    # This avoids injecting water in layers that would otherwise be dry.
                    ghb_head_min = float(lay_bot) + max(1e-3, 1e-3 * layer_thk)
                    if float(initial_groundwater_head) <= ghb_head_min:
                        continue
                    ghb_head_eff = float(initial_groundwater_head) + float(head_offset)
                    conductance = ghb_mult * (K_edge * width * layer_thk / distance)
                    ghb_list.append([k, i, j, ghb_head_eff, conductance])

        ghb = flopy.mf6.ModflowGwfghb(gwf, stress_period_data=ghb_list, save_flows=True)

        # Output control — avoid writing large .hds/.bud files in lightweight mode
        if lightweight_outputs:
            oc = flopy.mf6.ModflowGwfoc(
                gwf,
                saverecord=[],
                printrecord=[],
            )
        else:
            saverec = [("HEAD", "ALL"), ("BUDGET", "ALL")]
            oc = flopy.mf6.ModflowGwfoc(
                gwf,
                budget_filerecord=f"{MODEL_NAME}.bud",
                head_filerecord=f"{MODEL_NAME}.hds",
                saverecord=saverec,
                printrecord=[("HEAD", "LAST"), ("BUDGET", "LAST")],
            )

        # LAKTAB and LAK
        # Priority: DEM-derived LAKTAB > custom depth-area > trapezoidal
        laktab_rows = None
        if laktab_rows_dem is not None:
            laktab_rows = laktab_rows_dem
        if laktab_rows is None:
            try:
                cda = config.get("custom_depth_area")
                if isinstance(cda, (list, tuple)) and len(cda) >= 2:
                    # cda: [[depth_m, area_m2], ...] relative to floor; monotonic by depth
                    import numpy as _np
                    rows_da = [(float(d), float(a)) for d, a in cda if float(d) >= 0 and float(a) > 0]
                    rows_da.sort(key=lambda x: x[0])
                    if len(rows_da) >= 2:
                        # Compute cumulative volume via trapezoidal integration of area vs depth
                        depths = _np.array([r[0] for r in rows_da], dtype=float)
                        areas = _np.array([r[1] for r in rows_da], dtype=float)
                        vols = _np.zeros_like(depths)
                        for i in range(1, len(depths)):
                            dd = depths[i] - depths[i-1]
                            vols[i] = vols[i-1] + 0.5 * (areas[i] + areas[i-1]) * dd
                        # Convert to (stage, volume, sarea)
                        laktab_rows = [(float(basin_geom.floor_elev + depths[i]), float(vols[i]), float(areas[i])) for i in range(len(depths))]
            except Exception:
                laktab_rows = None
        if laktab_rows is None:
            laktab_rows = generate_tapered_laktab(basin_geom, nrows=41)

        # Compute per-cell layer thickness for LAK connections
        if isinstance(top, np.ndarray) and top.ndim == 2:
            _lak_layer_thk = float(np.max(top)) - botm[conn_layer]
        else:
            _lak_layer_thk = top - botm[conn_layer]

        # Compute lake surface area (DEM: sum of basin cell areas; manual: length×width)
        if use_dem and dem_cfg is not None:
            _lake_sa_m2 = float(dem_cfg.basin_mask.sum()) * dem_cfg.cell_size_x * dem_cfg.cell_size_y
        else:
            _lake_sa_m2 = basin_geom.length_floor * basin_geom.width_floor

        lak_file = create_lak_with_time_series(
            basin_cells,
            storm_data,
            stress_periods,
            str(MODEL_DIR),
            MODEL_NAME,
            basin_floor,
            lakebed_thickness,
            lake_initial_stage,
            laktab_rows=laktab_rows,
            lake_surface_area_m2=_lake_sa_m2,
            table_stage_max_offset=basin_geom.max_depth,
            lakebed_k=(bed_k_mpd/86400.0),
            infiltration_mode=infil_mode,
            side_k=(None if side_k_mpd is None else side_k_mpd/86400.0),
            aligned_inflows_m3s=inflow_per_sp,
            delr=delr,
            delc=delc,
            nrow=nrow,
            ncol=ncol,
            layer_thickness=_lak_layer_thk,
            max_depth=basin_geom.max_depth,
            spill_linear_extension_m=10.0,
            bed_leak_multiplier=1.0,
            top=top,
            botm=botm,
            write_lak_budget=(not lightweight_outputs),
        )

        # UZF package — unsaturated zone flow beneath the basin
        uzf_cfg = config.get("uzf", {}) if isinstance(config.get("uzf"), dict) else {}
        uzf_file = create_uzf_package(
            basin_cells,
            stress_periods,
            str(MODEL_DIR),
            MODEL_NAME,
            vks=bed_k_mpd,
            thts=float(uzf_cfg.get("thts", 0.35)),
            thtr=float(uzf_cfg.get("thtr", 0.05)),
            thti=float(uzf_cfg.get("thti", 0.10)),
            eps=float(uzf_cfg.get("eps", 4.0)),
            write_budget=(not lightweight_outputs),
        )

        # MVR package — routes LAK seepage to UZF cells
        mvr_file = create_mvr_package(
            basin_cells,
            stress_periods,
            str(MODEL_DIR),
            MODEL_NAME,
            delr=delr,
            delc=delc,
            lak_pname="basin_lak",
            uzf_pname="basin_uzf",
        )

        # Persist model metadata for this run
        try:
            import json as _json
            crest_elev = float(basin_geom.floor_elev + basin_geom.max_depth)
            meta = {
                "floor_elev_mAHD": float(basin_geom.floor_elev),
                "crest_elev_mAHD": crest_elev,
                "max_depth_m": float(basin_geom.max_depth),
                "spill_extension_m": 10.0,
                "infiltration_mode": infil_mode,
            }
            with open(Path(MODEL_DIR) / 'model_meta.json', 'w') as _fp:
                _json.dump(meta, _fp, indent=2)
        except Exception:
            pass

        # Write and add LAK, UZF, MVR to name file
        sim.write_simulation()
        gwf_nam_file = Path(MODEL_DIR) / f"{MODEL_NAME}.nam"
        with open(gwf_nam_file, 'r') as f:
            nam_lines = f.readlines()
        add_lines = []
        need_write = False
        has_lak = any('LAK6' in line for line in nam_lines)
        for line in nam_lines:
            if 'OC6' in line and not has_lak:
                add_lines.append(f"  LAK6  {Path(lak_file).name}  basin_lak\n")
                if str(infil_mode).lower() == "full":
                    add_lines.append(f"  UZF6  {Path(uzf_file).name}  basin_uzf\n")
                    add_lines.append(f"  MVR6  {Path(mvr_file).name}\n")
                need_write = True
            add_lines.append(line)
        if need_write:
            with open(gwf_nam_file, 'w') as f:
                f.writelines(add_lines)
    except Exception as _early_e:
        # Persist early error and return cleanly so GUI marks run failed with details
        _persist_error_and_summary(_early_e)
        summary = {
            "success": False,
            "error": str(_early_e),
            "ts1_file": str(ts1_path),
            "scenario": scenario_title,
            "model_name": MODEL_NAME,
        }
        return False, summary, str(MODEL_DIR)

    # Run with live progress by parsing stdout for STRESS PERIOD/TIME STEP
    success = False
    import subprocess, re, time
    # Ensure meta has totals, including steps
    steps_per_period = [int(sp[1]) for sp in stress_periods]
    total_steps = int(np.sum(steps_per_period))
    cum_steps = np.concatenate(([0], np.cumsum(steps_per_period)[:-1]))
    # Initialize meta
    try:
        with open(meta_path, 'r') as fp:
            meta = json.load(fp)
    except Exception:
        meta = {}
    meta.update({
        "run_id": run_id,
        "total_periods": len(stress_periods),
        "total_steps": int(total_steps),
        "completed_periods": 0,
        "completed_steps": 0,
        "current_period": 0,
        "current_timestep": 0,
        "steps_in_current_period": 0,
        "state": "running",
    })
    try:
        with open(meta_path, 'w') as fp:
            json.dump(meta, fp)
    except Exception:
        pass
    # Initialize GUI progress file if requested
    if progress_file:
        try:
            with open(progress_file, 'w') as pf:
                json.dump({
                    "current": 0,
                    "total": int(total_steps),
                    "model_dir": str(MODEL_DIR)
                }, pf)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Locate mf6 executable (with optional deep diagnostics)
    # ------------------------------------------------------------------
    mf6_debug = os.environ.get("BASIM_MF6_DEBUG") == "1"
    diag_lines = []
    def _diag(msg: str):
        if mf6_debug:
            diag_lines.append(msg)
    try:
        exe_path = find_mf6_exe()
        _diag(f"find_mf6_exe() -> {exe_path}")
    except Exception as e:
        # Persist a helpful error for GUI and users, then return
        summary = {
            "success": False,
            "error": f"MODFLOW 6 executable not found: {e}",
            "ts1_file": str(ts1_path),
            "scenario": scenario_title,
            "model_name": MODEL_NAME,
        }
        try:
            from pathlib import Path as _P
            _p = _P(MODEL_DIR)
            (_p / 'last_error.txt').write_text(summary["error"], encoding='utf-8')
            import json as _json
            (_p / 'scenario_summary.json').write_text(_json.dumps(summary, indent=2), encoding='utf-8')
            if mf6_debug:
                (_p / 'mf6_launch_diagnostics.txt').write_text("ERROR locating mf6:\n" + summary["error"], encoding='utf-8')
        except Exception:
            pass
        return False, summary, str(MODEL_DIR)

    if mf6_debug:
        try:
            import hashlib, platform
            from pathlib import Path as _P
            exe_p = _P(exe_path)
            diag_lines.append("--- mf6 launch diagnostics (pre-exec) ---")
            diag_lines.append(f"Timestamp: {datetime.utcnow().isoformat()}Z")
            diag_lines.append(f"Python: {sys.version.split()[0]} frozen={getattr(sys,'frozen',False)} _MEIPASS={getattr(sys,'_MEIPASS',None)}")
            diag_lines.append(f"Platform: {platform.platform()} cwd={os.getcwd()}")
            diag_lines.append(f"MODEL_DIR: {MODEL_DIR}")
            diag_lines.append(f"exe_path exists={exe_p.exists()} size={(exe_p.stat().st_size if exe_p.exists() else 'missing')} bytes")
            if exe_p.exists():
                try:
                    with exe_p.open('rb') as fh:
                        h = hashlib.sha256(fh.read(256*1024))  # hash first 256KB only (speed)
                        diag_lines.append(f"exe_path sha256(first256KB)={h.hexdigest()}")
                except Exception as _he:
                    diag_lines.append(f"sha256 failed: {_he}")
            # Model directory listing (top level)
            try:
                entries = []
                for p in _P(MODEL_DIR).iterdir():
                    try:
                        entries.append(f"{p.name}{'/' if p.is_dir() else ''}")
                    except Exception:
                        continue
                diag_lines.append("MODEL_DIR entries: " + ", ".join(sorted(entries)[:120]))
            except Exception as _le:
                diag_lines.append(f"List MODEL_DIR failed: {_le}")
            # Relevant environment subset
            for k in ["PATH", "PATHEXT", "BASIM_MF6", "BASIM_MF6", "BASIM_MF6_DEBUG"]:
                if k in os.environ:
                    v = os.environ.get(k, '')
                    if len(v) > 400:  # truncate long PATH
                        v = v[:400] + '...'
                    diag_lines.append(f"ENV {k}={v}")
        except Exception as _de:
            diag_lines.append(f"Diagnostics prep failed: {_de}")


    # Basic sanity check: ensure namefile exists before launching
    try:
        from pathlib import Path as _P
        if not (_P(MODEL_DIR) / 'mfsim.nam').exists():
            raise FileNotFoundError('mfsim.nam not found after write_simulation')
    except Exception as _e:
        try:
            (Path(MODEL_DIR) / 'last_error.txt').write_text(str(_e), encoding='utf-8')
        except Exception:
            pass
        summary = {
            "success": False,
            "error": f"Preflight failed: {_e}",
            "ts1_file": str(ts1_path),
            "scenario": scenario_title,
            "model_name": MODEL_NAME,
        }
        try:
            import json as _json
            (_P(MODEL_DIR) / 'scenario_summary.json').write_text(_json.dumps(summary, indent=2), encoding='utf-8')
        except Exception:
            pass
        return False, summary, str(MODEL_DIR)

    from collections import deque
    recent_lines = deque(maxlen=200)
    # Prepare a live stdout log so the GUI can tail it
    _stdout_log_path = Path(MODEL_DIR) / 'mf6_stdout.log'
    try:
        # Truncate any previous file and write a small header
        with open(_stdout_log_path, 'w', encoding='utf-8') as _lf:
            _lf.write(f"MF6 live log for scenario '{scenario_title}' (ts1='{Path(ts1_path).name if ts1_path else ''}')\n")
            _lf.write("--- BEGIN ---\n")
    except Exception:
        pass
    try:
        if mf6_debug:
            diag_lines.append(f"Launching: {exe_path} (cwd={MODEL_DIR})")
        proc = subprocess.Popen([exe_path], cwd=str(MODEL_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        if mf6_debug:
            diag_lines.append(f"Popen started pid={proc.pid}")
    except Exception as _launch_e:
        # Could not launch mf6
        summary = {
            "success": False,
            "error": f"Launch failed: {_launch_e}",
            "ts1_file": str(ts1_path),
            "scenario": scenario_title,
            "model_name": MODEL_NAME,
        }
        try:
            (Path(MODEL_DIR) / 'last_error.txt').write_text(summary["error"], encoding='utf-8')
            import json as _json
            (Path(MODEL_DIR) / 'scenario_summary.json').write_text(_json.dumps(summary, indent=2), encoding='utf-8')
            if mf6_debug:
                (Path(MODEL_DIR) / 'mf6_launch_diagnostics.txt').write_text("\n".join(diag_lines + [f"Launch exception: {_launch_e}"]), encoding='utf-8')
        except Exception:
            pass
        return False, summary, str(MODEL_DIR)

    sp_cur = 0
    ts_cur = 0
    # Robust, case-insensitive patterns: allow any non-digit separator (colon, equals, spaces)
    pat_sp = re.compile(r"stress\s*period[:\s=]*([0-9]+)", re.IGNORECASE)
    pat_ts = re.compile(r"time\s*step[:\s=]*([0-9]+)", re.IGNORECASE)
    pat_both = re.compile(r"Solving[^\d]*stress\s*period[:\s=]*([0-9]+)[^\d]+time\s*step[:\s=]*([0-9]+)", re.IGNORECASE)

    # Read stdout and update progress; if parser fails, fall back to waiting on process
    try:
        while True:
            line = proc.stdout.readline() if proc.stdout else ''
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            # print through for console visibility when running from CLI
            try:
                print(line, end="")
            except Exception:
                pass
            # Append to live stdout log for GUI tailing
            try:
                with open(_stdout_log_path, 'a', encoding='utf-8') as _lf:
                    _lf.write(line)
            except Exception:
                pass
            try:
                recent_lines.append(line)
            except Exception:
                pass
            mb = pat_both.search(line)
            msp = pat_sp.search(line) if not mb else None
            mts = pat_ts.search(line) if not mb else None
            updated = False
            if mb:
                sp_cur = int(mb.group(1)); ts_cur = int(mb.group(2)); updated = True
            elif msp:
                sp_cur = int(msp.group(1))
                ts_cur = 0  # reset until TIME STEP seen
                updated = True
            if mts:
                ts_cur = int(mts.group(1))
                updated = True
            if updated and sp_cur > 0:
                # Compute completed counts
                completed_periods = max(0, sp_cur - 1)
                step_base = int(cum_steps[sp_cur - 1]) if (sp_cur - 1) < len(cum_steps) else total_steps
                steps_in_cur = int(steps_per_period[sp_cur - 1]) if (sp_cur - 1) < len(steps_per_period) else 0
                # Count current timestep as progress but cap to steps in period
                completed_steps = min(total_steps, step_base + min(max(0, ts_cur), steps_in_cur))
                try:
                    with open(meta_path, 'r') as fp:
                        meta_now = json.load(fp)
                except Exception:
                    meta_now = dict(meta)
                meta_now.update({
                    "run_id": run_id,
                    "completed_periods": int(completed_periods),
                    "completed_steps": int(completed_steps),
                    "current_period": int(sp_cur),
                    "current_timestep": int(ts_cur),
                    "steps_in_current_period": int(steps_in_cur),
                    "state": "running",
                })
                try:
                    with open(meta_path, 'w') as fp:
                        json.dump(meta_now, fp)
                except Exception:
                    pass
                # Update external progress file with (current/total) for GUI
                if progress_file:
                    try:
                        with open(progress_file, 'w') as pf:
                            json.dump({
                                "current": int(completed_steps),
                                "total": int(total_steps),
                                "model_dir": str(MODEL_DIR)
                            }, pf)
                    except Exception:
                        pass
    except Exception as _parser_e:
        # Record parser error but do not fail the run; we'll still wait for rc
        try:
            (Path(MODEL_DIR) / 'progress_parser_error.txt').write_text(str(_parser_e), encoding='utf-8')
        except Exception:
            pass

    # Wait for MF6 to finish regardless of parser outcome
    rc = proc.wait()
    success = (rc == 0)
    if not success:
        try:
            tail_txt = ''.join(list(recent_lines))
            (Path(MODEL_DIR) / 'mf6_tail.log').write_text(tail_txt, encoding='utf-8')
            (Path(MODEL_DIR) / 'last_error.txt').write_text(f"mf6 exited with code {rc}\n\nTail:\n{tail_txt}", encoding='utf-8')
            # Also persist a minimal scenario_summary so GUI has context
            import json as _json
            summary = {
                "success": False,
                "error": f"mf6 exited with code {rc}",
                "ts1_file": str(ts1_path),
                "scenario": scenario_title,
                "model_name": MODEL_NAME,
            }
            (Path(MODEL_DIR) / 'scenario_summary.json').write_text(_json.dumps(summary, indent=2), encoding='utf-8')
        except Exception:
            pass
    # After run, mark saving state (GUI will set bar to 100% shortly after)
    try:
        with open(meta_path, 'r') as fp:
            meta = json.load(fp)
    except Exception:
        meta = {"total_periods": len(stress_periods), "total_steps": int(np.sum([sp[1] for sp in stress_periods]))}
    meta.update({
        "run_id": run_id,
        "completed_periods": meta.get("total_periods", len(stress_periods)),
        "completed_steps": meta.get("total_steps", int(np.sum([sp[1] for sp in stress_periods]))),
        "state": "saving",
    })
    try:
        with open(meta_path, 'w') as fp:
            json.dump(meta, fp)
    except Exception:
        pass
    finally:
        if mf6_debug:
            try:
                rc = proc.returncode if 'proc' in locals() else None
                diag_lines.append(f"Process finished returncode={rc}")
                # Append tail of stdout log
                try:
                    if _stdout_log_path.exists():
                        tail = _stdout_log_path.read_text(encoding='utf-8', errors='ignore').splitlines()[-50:]
                        diag_lines.append("--- stdout tail ---")
                        diag_lines.extend(tail)
                except Exception:
                    pass
                (Path(MODEL_DIR) / 'mf6_launch_diagnostics.txt').write_text("\n".join(diag_lines), encoding='utf-8')
            except Exception:
                pass
    # Force GUI progress to full at end
    if progress_file:
        try:
            total_steps = int(meta.get("total_steps", 0))
            with open(progress_file, 'w') as pf:
                json.dump({
                    "current": int(total_steps),
                    "total": int(total_steps),
                    "model_dir": str(MODEL_DIR)
                }, pf)
        except Exception:
            pass

    # If failed once, do a single retry with extra-stable settings
    if not success:
        try:
            print("\n🔁 Retry: enabling more conservative solver and finer end-of-storm steps...\n")
            # Adjust IMS tolerances in-place via new simulation write (reuse inputs)
            # Slightly increase max iterations and relax closures
            try:
                ims = flopy.mf6.ModflowIms(
                    sim,
                    print_option="SUMMARY",
                    complexity="COMPLEX",
                    outer_dvclose=5e-3,
                    outer_maximum=900,
                    under_relaxation="DBD",
                    under_relaxation_theta=0.7,
                    under_relaxation_kappa=0.2,
                    linear_acceleration="BICGSTAB",
                    reordering_method="rcm",
                    inner_maximum=900,
                    inner_dvclose=5e-5,
                    rcloserecord=[0.05, "STRICT"],
                    backtracking_number=25,
                    backtracking_tolerance=2.0,
                    backtracking_reduction_factor=0.2,
                    backtracking_residual_limit=0.0,
                )
            except Exception:
                pass
            sim.write_simulation()
            
            # Re-apply LAK/UZF/MVR packages since write_simulation removes them
            gwf_nam_file = Path(MODEL_DIR) / f"{MODEL_NAME}.nam"
            try:
                with open(gwf_nam_file, 'r') as f:
                    nam_lines = f.readlines()
                add_lines = []
                need_write = False
                has_lak = any('LAK6' in line for line in nam_lines)
                for line in nam_lines:
                    if 'OC6' in line and not has_lak:
                        add_lines.append(f"  LAK6  {Path(lak_file).name}  basin_lak\n")
                        if str(infil_mode).lower() == "full":
                            add_lines.append(f"  UZF6  {Path(uzf_file).name}  basin_uzf\n")
                            add_lines.append(f"  MVR6  {Path(mvr_file).name}\n")
                        need_write = True
                    add_lines.append(line)
                if need_write:
                    with open(gwf_nam_file, 'w') as f:
                        f.writelines(add_lines)
            except Exception:
                pass
            try:
                exe_path = find_mf6_exe()
            except Exception as e:
                success = False
                # If we cannot locate mf6 on retry, bail with same early return
                summary = {
                    "success": False,
                    "error": f"MODFLOW 6 executable not found: {e}",
                    "ts1_file": str(ts1_path),
                    "scenario": scenario_title,
                    "model_name": MODEL_NAME,
                }
                return False, summary, str(MODEL_DIR)
            proc = subprocess.Popen([exe_path], cwd=str(MODEL_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            while True:
                line = proc.stdout.readline() if proc.stdout else b''
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.05)
                    continue
                try:
                    print(line, end="")
                except Exception:
                    pass
            rc = proc.wait()
            success = (rc == 0)
        except Exception:
            success = False

    # Visualize
    try:
        visualize_results(str(MODEL_DIR), MODEL_NAME, nrow, ncol, delr, delc)
    except Exception:
        pass
    # If succeeded, remove any stale error breadcrumbs and legacy artifacts from this folder
    if success:
        try:
            for fname in (
                'last_error.txt',           # stale error marker
                'mf6_tail.log',             # previous tail output
                'water_balance_timeseries.csv',  # legacy, no longer used
                'inflow_timeseries.csv',    # legacy, no longer used
            ):
                p = Path(MODEL_DIR) / fname
                try:
                    if p.exists():
                        p.unlink(missing_ok=True)
                except Exception:
                    # Ignore deletion issues on Windows file locking
                    pass
        except Exception:
            pass
    # Mark final state (done/failed)
    try:
        with open(meta_path, 'r') as fp:
            meta = json.load(fp)
        meta.update({"run_id": run_id, "state": ("done" if success else "failed")})
        with open(meta_path, 'w') as fp:
            json.dump(meta, fp)
    except Exception:
        pass

    # Build summary
    from time import perf_counter as _pc
    # Note: run duration approx from logs isn't tracked; compute from files' mtime difference if possible
    try:
        _t0 = Path(MODEL_DIR) / f"{MODEL_NAME}.nam"
        _t1 = Path(MODEL_DIR) / f"{MODEL_NAME}.lst"
        if not _t1.exists():
            alt = Path(MODEL_DIR) / "mfsim.lst"
            if alt.exists():
                _t1 = alt
        runtime_seconds = float(max(0.0, (_t1.stat().st_mtime - _t0.stat().st_mtime))) if (_t0.exists() and _t1.exists()) else None
    except Exception:
        runtime_seconds = None
    summary = {
        "ts1_file": str(ts1_path),
        "scenario": scenario_title,
        "ts1_short": ts1_short,
        "model_name": MODEL_NAME,
        "performance_mode": str(perf_mode),
        "infiltration_mode": infil_mode,
        "bed_thickness_m": bed_thk,
        "bed_k_mpd": bed_k_mpd,
        "side_k_mpd": side_k_mpd,
        "initial_head_mAHD": float(initial_groundwater_head),
        "bottom_elev_mAHD": (float(bottom_elev) if bottom_elev is not None else None),
        "config_hash": config_hash,
    "success": bool(success),
    **({"runtime_seconds": float(runtime_seconds)} if runtime_seconds is not None else {}),
    }
    if total_inflow_ts1_m3 is not None:
        summary["cumulative_inflow_m3"] = float(total_inflow_ts1_m3)
        summary["cumulative_inflow_m3_ts1"] = float(total_inflow_ts1_m3)
    if total_inflow_sp_m3 is not None:
        summary["cumulative_inflow_m3_stress_periods"] = float(total_inflow_sp_m3)
    if not success:
        try:
            err_file = Path(MODEL_DIR) / 'last_error.txt'
            if err_file.exists():
                summary['error'] = err_file.read_text(encoding='utf-8')[:4000]
        except Exception:
            pass
    # Compute metrics
    try:
        stage_csv = Path(MODEL_DIR) / f"{MODEL_NAME}_lak_stage.csv"
        obs_csv = Path(MODEL_DIR) / f"{MODEL_NAME}_lak_allobs.csv"
        crest_elev = None
        try:
            import json as _json
            meta_path = Path(MODEL_DIR) / 'model_meta.json'
            if meta_path.exists():
                with open(meta_path, 'r') as fp:
                    _meta = _json.load(fp)
                crest_elev = float(_meta.get('crest_elev_mAHD'))
                # also expose geometry for outlet storage mapping
                geom_for_outlet = {
                    "length_floor_m": float(_meta.get('length_floor_m', basin_geom.length_floor)),
                    "width_floor_m": float(_meta.get('width_floor_m', basin_geom.width_floor)),
                    "side_slope_hv": float(_meta.get('side_slope_hv', basin_geom.side_slope_hv)),
                    "max_depth_m": float(_meta.get('max_depth_m', basin_geom.max_depth)),
                }
        except Exception:
            crest_elev = None
            geom_for_outlet = {
                "length_floor_m": basin_geom.length_floor,
                "width_floor_m": basin_geom.width_floor,
                "side_slope_hv": basin_geom.side_slope_hv,
                "max_depth_m": basin_geom.max_depth,
            }
        if stage_csv.exists():
            dfs = pd.read_csv(stage_csv)
            ts_days = dfs.iloc[:,0].values.astype(float)
            stg = dfs.iloc[:,1].values.astype(float)
            peak_idx = int(np.nanargmax(stg))
            peak_stage = float(np.nanmax(stg))
            peak_time_days = float(ts_days[peak_idx])
            # detention time from peak until stage returns to near floor (within 0.01 m)
            floor = basin_floor
            threshold = floor + 0.01
            post = stg[peak_idx:]
            tt = ts_days[peak_idx:]
            last_above_idx = None
            for i in range(len(post)):
                if post[i] > threshold:
                    last_above_idx = i
            if last_above_idx is None:
                detention_hours = 0.0
            else:
                detention_hours = float(tt[last_above_idx] - peak_time_days) * 24.0
            summary.update({
                "peak_stage_m": peak_stage,
                "peak_time_days": peak_time_days,
                "detention_time_hours": detention_hours,
            })
            # Spill detection
            if crest_elev is not None and np.nanmax(stg) > crest_elev + 1e-6:
                summary.update({
                    "spill_detected": True,
                    "spill_max_exceedance_m": float(np.nanmax(stg) - crest_elev),
                    "warning": "Basin spilled; results beyond crest are for stability only."
                })
            else:
                summary.setdefault("spill_detected", False)
        # Get basic metrics from MODFLOW output if available
        if obs_csv.exists():
            try:
                dfw = pd.read_csv(obs_csv)
                if 'LAK_EXT_INFLOW' in dfw.columns and 'time' in dfw.columns:
                    # Calculate cumulative inflow from MODFLOW data
                    t_days = dfw['time'].values.astype(float)
                    # LAK flows are reported per model time unit (days); treat as m3/day here
                    q_m3_per_day = dfw['LAK_EXT_INFLOW'].values.astype(float)
                    # Integrate m3/day over days to get m3
                    try:
                        from scipy.integrate import cumulative_trapezoid
                        cum_inflow_m3 = cumulative_trapezoid(q_m3_per_day, t_days, initial=0.0)
                    except ImportError:
                        dt = np.diff(t_days)
                        qm = 0.5 * (q_m3_per_day[:-1] + q_m3_per_day[1:])
                        cum_inflow_m3 = np.concatenate([[0.0], np.cumsum(qm * dt)])
                    summary["cumulative_inflow_m3_mf6"] = float(cum_inflow_m3[-1])
                    if "cumulative_inflow_m3" not in summary:
                        summary["cumulative_inflow_m3"] = float(cum_inflow_m3[-1])
                    # Get storage if LAKTAB exists
                    laktab = Path(MODEL_DIR) / f"{MODEL_NAME}.laktab"
                    infiltration_rating = None  # will build after storage is computed
                    if laktab.exists() and 'LAK_STAGE' in dfw.columns:
                        stage_m = dfw['LAK_STAGE'].values.astype(float)
                        # Parse LAKTAB
                        stg_tab, vol_tab = [], []
                        try:
                            in_table = False
                            with open(laktab, 'r', encoding='utf-8', errors='ignore') as tf:
                                for line in tf:
                                    s = line.strip()
                                    if not s or s.startswith('#'):
                                        continue
                                    if s.upper().startswith('BEGIN TABLE'):
                                        in_table = True; continue
                                    if s.upper().startswith('END TABLE'):
                                        break
                                    if in_table:
                                        parts = s.split()
                                        if len(parts) >= 2:
                                            try:
                                                stg = float(parts[0]); vol = float(parts[1])
                                                stg_tab.append(stg); vol_tab.append(max(0.0, vol))
                                            except Exception:
                                                pass
                        except Exception:
                            pass
                        if len(stg_tab) >= 2:
                            from numpy import interp
                            storage_m3 = interp(stage_m, np.array(stg_tab, float), np.array(vol_tab, float), 
                                              left=0.0, right=float(vol_tab[-1]))
                            summary["peak_storage_m3"] = float(np.nanmax(storage_m3))
                            # Build stage-dependent infiltration from continuity: Qinf ≈ Qin - dS/dt
                            try:
                                t_days_arr = dfw['time'].values.astype(float)
                                t_sec = t_days_arr * 86400.0
                                q_in_m3s_arr = dfw['LAK_EXT_INFLOW'].values.astype(float) / 86400.0
                                # dS/dt via finite differences in seconds
                                dS = np.diff(storage_m3)
                                dt = np.diff(t_sec)
                                dt[dt == 0.0] = 1e-3
                                dSdt = np.concatenate([[dS[0] / dt[0]], dS / dt])
                                qinf_ts = q_in_m3s_arr - dSdt
                                # Clip to non-negative infiltration (optional; avoids spurious exfiltration)
                                qinf_ts = np.maximum(0.0, qinf_ts)
                                # Create stage→qinf rating by sorting and smoothing
                                order = np.argsort(stage_m)
                                stg_sorted = stage_m[order]
                                qinf_sorted = qinf_ts[order]
                                # Simple moving-average smoothing to reduce noise
                                win = max(3, min(51, (len(qinf_sorted) // 20) * 2 + 1))
                                kernel = np.ones(win, dtype=float) / float(win)
                                qinf_smooth = np.convolve(qinf_sorted, kernel, mode='same')
                                # Build compact grid (downsample to ~200 points max)
                                if len(stg_sorted) > 200:
                                    idx = np.linspace(0, len(stg_sorted) - 1, 200).astype(int)
                                    stg_grid = stg_sorted[idx]
                                    qinf_grid = qinf_smooth[idx]
                                else:
                                    stg_grid = stg_sorted
                                    qinf_grid = qinf_smooth
                                infiltration_rating = {"stage_grid": stg_grid, "qinf_grid": qinf_grid}
                            except Exception:
                                infiltration_rating = None

                    # Outlet post-processing (Option A)
                    try:
                        # Accept either a single outlet dict or a list under 'outlets'
                        outlets_cfg = None
                        if isinstance(config.get("outlets"), list):
                            outlets_cfg = [oc for oc in config.get("outlets") if isinstance(oc, dict) and (oc.get("enabled", True))]
                        out_cfg = config.get("outlet", {}) if isinstance(config.get("outlet", {}), dict) else {}
                        have_single = bool(out_cfg.get("enabled")) if isinstance(out_cfg, dict) else False
                        if outlets_cfg is not None and len(outlets_cfg) > 0:
                            outlets_structs = [create_outlet_from_config(oc) for oc in outlets_cfg]
                        elif have_single and isinstance(out_cfg, dict):
                            outlets_structs = create_outlet_from_config(out_cfg)
                        else:
                            outlets_structs = None
                        if outlets_structs is not None:
                            # Prepare arrays for solver
                            t_days = dfw['time'].values.astype(float)
                            stg_m = (dfw['LAK_STAGE'].values.astype(float)
                                     if 'LAK_STAGE' in dfw.columns else None)
                            if stg_m is None:
                                raise RuntimeError("LAK_STAGE not found in allobs CSV")
                            q_in_m3s = dfw['LAK_EXT_INFLOW'].values.astype(float) / 86400.0
                            # Stage-dependent infiltration rating from base run (continuity), if available
                            q_inf = infiltration_rating if infiltration_rating is not None else None
                            basin_geom_dict = {
                                "length_floor_m": float(geom_for_outlet.get("length_floor_m", basin_geom.length_floor)),
                                "width_floor_m": float(geom_for_outlet.get("width_floor_m", basin_geom.width_floor)),
                                "side_slope_hv": float(geom_for_outlet.get("side_slope_hv", basin_geom.side_slope_hv)),
                                "max_depth_m": float(geom_for_outlet.get("max_depth_m", basin_geom.max_depth)),
                                # Optionally include a custom depth–area if provided via config
                                "custom_depth_area": (config.get("custom_depth_area") if isinstance(config.get("custom_depth_area"), list) else None),
                            }
                            floor = float(basin_geom.floor_elev)
                            res = apply_outlet_to_results(
                                t_days,
                                stg_m,
                                q_in_m3s,
                                q_inf,
                                outlets_structs,
                                basin_geom_dict,
                                floor,
                            )
                            # Persist outlet CSV
                            out_df = pd.DataFrame({
                                'time_days': res['time_days'],
                                'stage_with_outlet_m': res['stage_with_outlet'],
                                'outlet_discharge_m3s': res['outlet_discharge'],
                                'storage_with_outlet_m3': res['storage_with_outlet'],
                                'infiltration_m3s': res.get('infiltration_m3s', np.nan),
                            })
                            # If per-outlet components returned, append columns
                            comps = res.get('outlet_components_m3s', None)
                            try:
                                if comps is not None:
                                    comps = np.asarray(comps, float)
                                    for j in range(comps.shape[1]):
                                        out_df[f'outlet_{j+1}_m3s'] = comps[:, j]
                            except Exception:
                                pass
                            out_df.to_csv(Path(MODEL_DIR) / f"{MODEL_NAME}_with_outlet.csv", index=False)
                            # Augment summary
                            # Peak stage with outlet and detention time
                            try:
                                stg_out = np.asarray(res['stage_with_outlet'], float)
                                t_out = np.asarray(res['time_days'], float)
                                peak_idx_out = int(np.nanargmax(stg_out))
                                peak_stg_out = float(np.nanmax(stg_out))
                                floor_elev = float(basin_floor)
                                thr = floor_elev + 0.01
                                last_above = peak_idx_out
                                for j in range(peak_idx_out, len(stg_out)):
                                    if stg_out[j] > thr:
                                        last_above = j
                                detn_out_hours = float(t_out[last_above] - t_out[peak_idx_out]) * 24.0 if last_above >= peak_idx_out else 0.0
                                summary.update({
                                    "peak_stage_with_outlet_m": peak_stg_out,
                                    "detention_time_with_outlet_hours": detn_out_hours,
                                })
                            except Exception:
                                pass
                            # Peak storage with outlet
                            try:
                                stg_out = np.asarray(res['stage_with_outlet'], float)
                                stor_out = np.asarray(res['storage_with_outlet'], float)
                                if stor_out.size > 0:
                                    summary["peak_storage_with_outlet_m3"] = float(np.nanmax(stor_out))
                            except Exception:
                                pass
                            summary.update({
                                "outlet_enabled": True,
                                "peak_outlet_m3s": float(res.get('peak_outlet_m3s', 0.0)),
                                "total_outlet_m3": float(res.get('total_outlet_m3', 0.0)),
                            })
                        else:
                            # No outlets for this run: ensure summary says so and remove any stale with_outlet.csv
                            try:
                                summary.update({"outlet_enabled": False})
                            except Exception:
                                pass
                            try:
                                stale = Path(MODEL_DIR) / f"{MODEL_NAME}_with_outlet.csv"
                                if stale.exists():
                                    stale.unlink()
                            except Exception:
                                pass
                    except Exception as _out_e:
                        try:
                            (Path(MODEL_DIR) / 'outlet_error.txt').write_text(str(_out_e), encoding='utf-8')
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass

    # Persist summary
    try:
        with open(Path(MODEL_DIR) / 'scenario_summary.json', 'w') as fp:
            json.dump(summary, fp, indent=2)
    except Exception:
        pass

    # Optional cleanup of heavy files after visualization and summary
    if cleanup_heavy:
        try:
            # Remove heavy outputs including listing file (too large for routine use)
            for ext in (".bud", ".hds", ".lst"):
                try:
                    # Prefer removing all matches just in case names vary
                    for p in Path(MODEL_DIR).glob(f"*{ext}"):
                        p.unlink(missing_ok=True)
                except Exception:
                    pass
            # Also remove LAK text budget if present (can be large)
            try:
                (Path(MODEL_DIR) / "basin_budget.txt").unlink(missing_ok=True)
            except Exception:
                pass
        except Exception:
            pass

    return success, summary, str(MODEL_DIR)
