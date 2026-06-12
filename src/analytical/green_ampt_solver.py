#!/usr/bin/env python3
"""
Preliminary Sizing (Green-Ampt) analytical solver for BaSIM.

Computes basin stage response using a mass-balance ODE with Green–Ampt
infiltration through a clogging layer.

Key assumptions:
- Vertical infiltration through basin bed (optional side-wall contribution)
- Green–Ampt cumulative infiltration with wetting-front depth z_f = F / dtheta
- Effective driving head includes ponded depth and suction head
- Shallow water table reduces driving head and effective depth (conservative)

Outputs:
- prelim_timeseries.csv: time_hours, stage_m, inflow_m3s, infil_m3s,
  cum_in_m3, cum_infil_m3
- scenario_summary.json with peak stage, time to empty, volumes, efficiency,
  and warnings, flagged as analysis_mode="preliminary".
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
import math
import json

import numpy as np
import pandas as pd


@dataclass
class Geometry:
    Lf: float  # floor length (m)
    Wf: float  # floor width (m)
    m: float   # side slope H:V
    Dmax: float  # max depth (m)
    floor_elev: float  # m AHD


@dataclass
class Soil:
    Ksat_mpd: float  # saturated vertical K (m/day)
    dtheta: float    # theta_s - theta_i (use Sy as proxy if unknown)
    psi_f_m: float   # wetting-front suction head (m), typical 0.05–0.3 m


@dataclass
class Clogging:
    thickness_m: float  # thickness (m)
    K_mpd: float        # hydraulic conductivity (m/day)


def _area_top(geo: Geometry, d: float) -> float:
    # Top surface area at depth d (derivative dV/dd)
    return (geo.Lf + 2.0 * geo.m * d) * (geo.Wf + 2.0 * geo.m * d)


def _bed_area(geo: Geometry) -> float:
    return max(0.0, geo.Lf * geo.Wf)


def _side_area(geo: Geometry, d: float) -> float:
    # Approximate wetted side surface area for four walls
    # Two walls of length L, two of length W; sloped height = d*sqrt(1+m^2)
    sl = math.sqrt(1.0 + geo.m * geo.m)
    A_long = 2.0 * (geo.Lf + 2.0 * geo.m * d) * d * sl
    A_wide = 2.0 * (geo.Wf + 2.0 * geo.m * d) * d * sl
    return max(0.0, A_long + A_wide)


def _q_green_ampt(d: float, F: float, soil: Soil, clog: Clogging, D_wt: float) -> float:
        """Compute infiltration capacity (m/s) using Green–Ampt with a clogging layer.

        Regimes:
        - Unsaturated (wetting front above water table): classic GA with suction head
            f = (z_f + psi_f + h) / (z_f / Ksat + Lc / Kc)
        - Saturated/shallow water table (wetting front reached water table or GW at floor):
            suction no longer contributes; infiltration is Darcy-limited by head h across
            the saturated path to the water table + clogging layer:
            f = h / (D_wt / Ksat + Lc / Kc)

        Inputs:
        - d: ponded depth (m)
        - F: cumulative infiltration depth (m) per unit area (m)
        - soil: Ksat (m/day), dtheta, psi_f (m)
        - clog: thickness (m), K (m/day)
        - D_wt: water table depth below floor (m). If <= 0, GW at/above floor.
        """
        Ksat = max(1e-12, soil.Ksat_mpd / 86400.0)
        Kc = max(1e-12, clog.K_mpd / 86400.0) if clog.thickness_m > 1e-9 else 1e12

        dtheta = max(1e-6, soil.dtheta)
        zf = max(1e-9, F / dtheta)  # wetting-front depth
        h = max(0.0, d)

        # If groundwater is at/above the floor (D_wt <= 0) or the wetting front has reached
        # the water table (zf >= D_wt), switch to saturated/Darcy regime with no suction.
        if D_wt is None or D_wt <= 0.0 or zf >= max(1e-9, D_wt):
                denom = (max(1e-12, D_wt) / Ksat) + (clog.thickness_m / Kc if clog.thickness_m > 1e-12 else 0.0)
                denom = max(1e-12, denom)
                q = h / denom  # m/s
        else:
                # Unsaturated Green–Ampt with equivalent resistance of soil + clogging
                z_eff = zf
                num = max(0.0, z_eff + soil.psi_f_m + h)
                denom = (z_eff / Ksat) + (clog.thickness_m / Kc if clog.thickness_m > 1e-12 else 0.0)
                denom = max(1e-12, denom)
                q = num / denom

        # Physical bounds
        q = max(0.0, min(q, max(Ksat, Kc) * 10.0))
        return q


def _integrate_prelim(
    t_hours: np.ndarray,
    q_in_m3s: np.ndarray,
    geo: Geometry,
    soil: Soil,
    clog: Clogging,
    D_wt: float,
    include_side: bool = False,
) -> Tuple[pd.DataFrame, dict]:
    t_sec = np.asarray(t_hours, float) * 3600.0
    qin = np.asarray(q_in_m3s, float)
    assert t_sec.ndim == 1 and qin.ndim == 1 and len(t_sec) == len(qin)

    A_bed = _bed_area(geo)

    # State (bucket): water depth d and cumulative infiltration depth F (m)
    d = 0.0
    F = 1e-9
    V_in = 0.0
    V_inf = 0.0
    V_spill = 0.0

    out_rows = []
    hit_wt = False  # track if/when wetting front reaches GW

    # Time stepping
    for i in range(len(t_sec) - 1):
        t0, t1 = t_sec[i], t_sec[i + 1]
        q0, q1 = qin[i], qin[i + 1]
        dt = max(1e-6, t1 - t0)
        # subdivide for stability if dt is large
        n_sub = max(1, int(math.ceil(dt / 30.0)))  # ~<=30 s per substep
        dt_sub = dt / n_sub

        # track last-substep values for reporting at coarse step end
        I_last = 0.0
        Qin_last = q1
        Qspill_last = 0.0

        for k in range(n_sub):
            t = t0 + (k + 0.5) * dt_sub
            # linear interp inflow within the interval
            alpha = (t - t0) / dt
            Qin = (1 - alpha) * q0 + alpha * q1  # m3/s

            A_top = max(1e-6, _area_top(geo, d))
            A_side = _side_area(geo, d) if include_side else 0.0
            A_inf = A_bed + A_side

            # Infiltration capacity (m/s) and volumetric rate (m3/s)
            q_cap = _q_green_ampt(d, F, soil, clog, D_wt)
            I = q_cap * A_inf

            # Track if wetting front has reached the water table
            try:
                if not hit_wt:
                    zf = max(0.0, F / max(1e-6, soil.dtheta))
                    if D_wt <= 0.0 or zf >= max(1e-6, D_wt):
                        hit_wt = True
            except Exception:
                pass

            # Predict depth change without crest constraint
            net = Qin - I  # Qout = 0 in prelim
            d_pred = d + (net / max(1e-6, A_top)) * dt_sub

            # Handle spill to cap at crest
            Qspill = 0.0
            if d_pred > geo.Dmax + 1e-12:
                d_excess = d_pred - geo.Dmax
                A_cap = max(1e-6, _area_top(geo, geo.Dmax))
                spill_vol = d_excess * A_cap
                V_spill += spill_vol
                Qspill = spill_vol / dt_sub
                d = geo.Dmax
            elif d_pred < 0.0:
                d = 0.0
            else:
                d = d_pred

            # Update cumulative infiltration depth based on bed flux only (vertical GA)
            F += q_cap * dt_sub
            V_in += Qin * dt_sub
            V_inf += I * dt_sub

            # Remember last-substep values for reporting
            I_last = I
            Qin_last = Qin
            Qspill_last = Qspill

        # Storage volume from geometry at the coarse step end
        V_now = (geo.Lf * geo.Wf * d) + geo.m * (geo.Lf + geo.Wf) * (d ** 2) + (4.0 / 3.0) * (geo.m ** 2) * (d ** 3)
        out_rows.append((t1 / 3600.0, geo.floor_elev + d, d, Qin_last, I_last, V_now, Qspill_last))

    df = pd.DataFrame(out_rows, columns=["time_hours", "stage_m", "depth_m", "inflow_m3s", "infil_m3s", "storage_m3", "spill_m3s"])
    # Integrals for convenience
    try:
        from scipy.integrate import cumulative_trapezoid as _ct
        df["cum_in_m3"] = _ct(df["inflow_m3s"].values, df["time_hours"].values * 3600.0, initial=0.0)
        df["cum_infil_m3"] = _ct(df["infil_m3s"].values, df["time_hours"].values * 3600.0, initial=0.0)
    except Exception:
        dt_s = np.diff(df["time_hours"].values) * 3600.0
        df["cum_in_m3"] = np.concatenate([[0.0], np.cumsum(0.5 * (df["inflow_m3s"].values[:-1] + df["inflow_m3s"].values[1:]) * dt_s)])
        df["cum_infil_m3"] = np.concatenate([[0.0], np.cumsum(0.5 * (df["infil_m3s"].values[:-1] + df["infil_m3s"].values[1:]) * dt_s)])

    peak_stage = float(np.nanmax(df["stage_m"].values)) if len(df) else 0.0
    time_to_empty = None
    try:
        # consider basin effectively empty when depth < 1 mm
        idx = np.where((df["depth_m"].values < 1e-3) & (df["time_hours"].values > df["time_hours"].values.min() + 1e-6))[0]
        if len(idx):
            time_to_empty = float(df["time_hours"].values[int(idx[-1])])
    except Exception:
        time_to_empty = None

    # Efficiency and mass balance check
    V_in_tot = float(df["cum_in_m3"].values[-1]) if len(df) else 0.0
    V_inf_tot = float(df["cum_infil_m3"].values[-1]) if len(df) else 0.0
    V_spill_tot = float(np.trapz(df["spill_m3s"].values, df["time_hours"].values * 3600.0)) if len(df) else 0.0
    eff = float(V_inf_tot / V_in_tot) if V_in_tot > 1e-9 else 1.0

    return df, {
        "peak_stage_m": peak_stage,
        "time_to_empty_hours": time_to_empty,
        "total_inflow_m3": V_in_tot,
        "total_infiltration_m3": V_inf_tot,
        "total_spill_m3": V_spill_tot,
        "storage_efficiency": eff,
        "hit_water_table": bool(hit_wt),
    }


def _read_ts1_simple(ts1_path: Path) -> Tuple[np.ndarray, np.ndarray]:
    """Minimal TS1 reader: expects two numeric columns: time_hours, flow_m3s.
    Ignores blank/comment lines (starting with # or //)."""
    t = []
    q = []
    with open(ts1_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("//"):
                continue
            parts = s.replace(",", " ").split()
            if len(parts) < 2:
                continue
            try:
                tt = float(parts[0])
                qq = float(parts[1])
                t.append(tt)
                q.append(qq)
            except Exception:
                continue
    if not t:
        raise ValueError("TS1 parse produced no data; expected two numeric columns: time_hours flow_m3s")
    return np.array(t, float), np.array(q, float)


def run_preliminary_with_config(ts1_path: Optional[str], config: dict) -> tuple[bool, dict, str]:
    """Run the Preliminary Sizing (Green–Ampt) analysis.

    Returns (success, summary_dict, output_dir_str)
    """
    try:
        ts1 = Path(ts1_path) if ts1_path else None
        # Geometry from config (shared with detailed)
        gcfg = config.get("basin_geometry", {})
        geo = Geometry(
            Lf=float(gcfg.get("length_floor", 50.0)),
            Wf=float(gcfg.get("width_floor", 30.0)),
            m=float(gcfg.get("side_slope_hv", 3.0)),
            Dmax=float(gcfg.get("max_depth", 3.0)),
            floor_elev=float(gcfg.get("floor_elev", 5.0)),
        )

        # Soil and clogging from config
        aqu = config.get("aquifer", {})
        infil = config.get("infiltration", {})
        soil = Soil(
            Ksat_mpd=float(aqu.get("k_vertical_mpd", 0.0864)),
            dtheta=float(aqu.get("sy", 0.1)),
            psi_f_m=float(infil.get("psi_f_m", 0.2)),
        )
        clog = Clogging(
            thickness_m=float(infil.get("bed_thickness_m", 0.5)),
            K_mpd=float(infil.get("bed_k_mpd", 5.0)),
        )
        # Water table depth from aquifer initial head vs floor elevation
        D_wt = float(geo.floor_elev - float(aqu.get("initial_head", geo.floor_elev - 1.0)))
        D_wt = max(0.0, D_wt)
        include_side = bool(infil.get("mode", "vertical").lower() == "full")

        # Read hydrograph
        if ts1 is None or not ts1.exists():
            raise FileNotFoundError("TS1 hydrograph file not provided or not found")
        t_hours, q_m3s = _read_ts1_simple(ts1)

        # Integrate
        df, metrics = _integrate_prelim(t_hours, q_m3s, geo, soil, clog, D_wt, include_side)

        # Warnings and recommendations
        warnings = []
        if D_wt < max(1.0, 0.5 * geo.Dmax):
            warnings.append("Shallow water table; detailed analysis recommended.")
        # Compare peak depth (not absolute stage) to crest
        try:
            peak_depth = float(np.nanmax(df["depth_m"].values)) if len(df) else 0.0
        except Exception:
            peak_depth = 0.0
        if peak_depth > 0.9 * geo.Dmax:
            warnings.append("Peak stage near crest; detailed analysis recommended.")
        # Note any spill volume
        try:
            if float(metrics.get("total_spill_m3", 0.0)) > 1e-6:
                warnings.append("Basin spills in preliminary run; ensure outlet or freeboard is adequate.")
        except Exception:
            pass
        if metrics.get("hit_water_table", False):
            warnings.append("Wetting front reached groundwater. Infiltration limited by head to water table (saturated regime).")

        # Output paths
        scen_title = config.get("scenario_title", "Scenario 1").strip() or "Scenario 1"
        base_out = Path(config.get("output_dir") or Path.home() / "Documents" / "BaSIM" / "model_output" / "preliminary")
        scen_dir = base_out / scen_title
        outputs_root = scen_dir / "outputs"
        outputs_root.mkdir(parents=True, exist_ok=True)
        run_name = (ts1.stem if ts1 else "synthetic") + "_prelim"
        run_dir = outputs_root / run_name
        run_dir.mkdir(parents=True, exist_ok=True)

        # Save timeseries and summary
        csv_path = run_dir / "prelim_timeseries.csv"
        df.to_csv(csv_path, index=False)
        summary = {
            "analysis_mode": "preliminary",
            "ts1": str(ts1) if ts1 else None,
            "run_dir": str(run_dir),
            **metrics,
            "warnings": warnings,
        }
        (run_dir / "scenario_summary.json").write_text(json.dumps(summary, indent=2))

        return True, summary, str(run_dir)

    except Exception as e:
        return False, {"error": str(e), "analysis_mode": "preliminary"}, ""
