#!/usr/bin/env python3
"""
Preliminary Sizing (Richards' equation) solver for BaSIM.

Solves a 1D vertical Richards equation beneath the basin bed with a
ponded head boundary at the surface (top Dirichlet) and a water-table
boundary at depth D_wt (bottom Dirichlet, h=0). A thin clogging layer at
the bed is represented as an added series resistance on the top face
flux. The resulting infiltration flux is applied to a mass-balance
bucket dV/dt = Qin - I - Qspill, assuming no explicit outlet (the outlet
can be overlaid later in the GUI like the detailed mode).

This replaces the previous Green–Ampt approximation with a more
physically consistent unsaturated/saturated flow model.

Outputs per run directory (same as the GA solver for UI compatibility):
- prelim_timeseries.csv with fields:
  time_hours, stage_m, depth_m, inflow_m3s, infil_m3s, storage_m3,
  spill_m3s, cum_in_m3, cum_infil_m3
- scenario_summary.json with metrics and warnings.
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
class VGSoil:
    Ks_mpd: float      # saturated K (m/day)
    theta_s: float     # saturated water content (-)
    theta_r: float     # residual water content (-)
    alpha_per_m: float # van Genuchten alpha (1/m)
    n: float           # van Genuchten n (-), m = 1 - 1/n
    l: float = 0.5     # Mualem pore-connectivity parameter


@dataclass
class Clogging:
    thickness_m: float  # thickness (m)
    K_mpd: float        # hydraulic conductivity (m/day)


# Volume and area helpers

def _area_top(geo: Geometry, d: float) -> float:
    return (geo.Lf + 2.0 * geo.m * d) * (geo.Wf + 2.0 * geo.m * d)


def _volume(geo: Geometry, d: float) -> float:
    d = max(0.0, d)
    return (geo.Lf * geo.Wf * d) + geo.m * (geo.Lf + geo.Wf) * (d ** 2) + (4.0 / 3.0) * (geo.m ** 2) * (d ** 3)


# van Genuchten relations (pressure head h in meters; h < 0 unsaturated, h >= 0 saturated)

def _vg_Se(h: np.ndarray, soil: VGSoil) -> np.ndarray:
    theta_s, theta_r = soil.theta_s, soil.theta_r
    Se = np.empty_like(h, dtype=float)
    # unsaturated
    m = 1.0 - 1.0 / max(soil.n, 1.001)
    alpha = max(1e-9, soil.alpha_per_m)
    hu = h.copy()
    mask_unsat = hu < 0.0
    # Clamp argument to avoid overflow for very large suctions
    xi = alpha * np.abs(hu[mask_unsat])
    xi = np.clip(xi, 0.0, 100.0)
    x = np.power(1.0 + np.power(xi, soil.n), -m)
    Se_unsat = x
    Se[mask_unsat] = Se_unsat
    # saturated
    Se[~mask_unsat] = 1.0
    return np.clip(Se, 0.0, 1.0)


def _vg_theta(h: np.ndarray, soil: VGSoil) -> np.ndarray:
    Se = _vg_Se(h, soil)
    return soil.theta_r + Se * (soil.theta_s - soil.theta_r)


def _vg_C(h: np.ndarray, soil: VGSoil) -> np.ndarray:
    # Specific moisture capacity C = dtheta/dh
    m = 1.0 - 1.0 / max(soil.n, 1.001)
    n = max(soil.n, 1.001)
    alpha = max(1e-9, soil.alpha_per_m)
    theta_s, theta_r = soil.theta_s, soil.theta_r
    C = np.zeros_like(h, dtype=float)
    mask_unsat = h < 0.0
    if np.any(mask_unsat):
        abs_h = np.abs(h[mask_unsat])
        xi = np.clip(alpha * abs_h, 0.0, 100.0)
        t1 = (alpha ** n) * (n - 1.0) * (abs_h ** (n - 2.0))
        t2 = np.power(1.0 + (xi) ** n, -(m + 1.0))
        dSe_dh = t1 * t2
        C[mask_unsat] = (theta_s - theta_r) * dSe_dh
    return np.clip(C, 1e-10, 1e6)


def _vg_K(h: np.ndarray, soil: VGSoil) -> np.ndarray:
    Ks = max(soil.Ks_mpd, 1e-12) / 86400.0
    l = soil.l
    m = 1.0 - 1.0 / max(soil.n, 1.001)
    Se = _vg_Se(h, soil)
    # Mualem-van Genuchten conductivity function
    term = (1.0 - np.power(1.0 - np.power(Se, 1.0 / m), m)) ** 2
    K = Ks * np.power(Se, l) * term
    # Saturated for h>=0
    K[h >= 0.0] = Ks
    return np.clip(K, 1e-12, Ks)


def _richards_step(h: np.ndarray, dz: float, dt: float, soil: VGSoil, clog: Clogging, h_top: float, h_bot: float) -> tuple[np.ndarray, float]:
    """One explicit time step for head-based Richards equation on a uniform grid.

    Boundary conditions:
    - Top: Dirichlet pressure head h_top (ponded depth). Clogging layer is
      represented as an added series resistance on the top face flux.
    - Bottom: Dirichlet pressure head h_bot (0 at water table).

    Returns updated h array and the instantaneous downward infiltration flux
    at the top face (m/s, positive downward).
    """
    nz = len(h)
    h_new = h.copy()

    # Enforce Dirichlet boundaries on nodes
    h_new[0] = h_top
    h_new[-1] = h_bot

    # Precompute properties
    C = _vg_C(h, soil)
    K = _vg_K(h, soil)

    # Compute interface fluxes q_{i+1/2} = -K_face * (dh/dz - 1). Positive downward.
    q = np.zeros(nz + 1, dtype=float)

    # Top face with clogging resistance
    # Face 0 is between ghost above top node and node 0; we approximate using node 0 and 1
    if nz >= 2:
        # Gradient using nodes 0 and 1 (node 0 is boundary head)
        K_face = (K[0] + K[1]) * 0.5
        # Effective K including series resistance of clogging layer
        Kc = max(clog.K_mpd, 1e-12) / 86400.0 if clog.thickness_m > 1e-9 else None
        if Kc is not None:
            K_eff = dz / (dz / max(K_face, 1e-12) + clog.thickness_m / max(Kc, 1e-12))
        else:
            K_eff = K_face
        dhdz = (h[1] - h_top) / dz
        q[0] = -K_eff * (dhdz - 1.0)
    else:
        q[0] = 0.0

    # Interior faces
    for i in range(1, nz):
        K_face = 0.5 * (K[i - 1] + K[i])
        dhdz = (h[i] - h[i - 1]) / dz
        q[i] = -K_face * (dhdz - 1.0)

    # Bottom face (between node nz-1 and ghost at bottom); use last two nodes
    if nz >= 2:
        K_face = 0.5 * (K[-1] + K[-2])
        dhdz = (h_bot - h[-1]) / dz
        q[-1] = -K_face * (dhdz - 1.0)
    else:
        q[-1] = 0.0

    # Update interior nodes with explicit scheme based on mass conservation:
    # C(h) dh/dt = (q[i] - q[i+1]) / dz
    for i in range(1, nz - 1):
        div_q = (q[i] - q[i + 1]) / dz
        h_new[i] = h[i] + dt * div_q / max(C[i], 1e-10)

    # Re-apply boundary values
    h_new[0] = h_top
    h_new[-1] = h_bot

    infil_flux = max(0.0, q[0])  # downward positive
    return h_new, infil_flux


def _integrate_prelim_richards(
    t_hours: np.ndarray,
    q_in_m3s: np.ndarray,
    geo: Geometry,
    soil: VGSoil,
    clog: Clogging,
    D_wt: float,
    include_side: bool = False,
) -> Tuple[pd.DataFrame, dict]:
    t_sec = np.asarray(t_hours, float) * 3600.0
    qin = np.asarray(q_in_m3s, float)
    assert t_sec.ndim == 1 and qin.ndim == 1 and len(t_sec) == len(qin)

    A_bed = max(1e-6, geo.Lf * geo.Wf)

    # Richards column setup
    zmax = max(0.5, float(D_wt) if D_wt > 0 else 2.0)  # ensure some depth even if WT at surface
    nz = 50
    dz = zmax / nz
    # Initial condition: hydrostatic with h=0 at water table depth
    z = np.linspace(0.0, zmax, nz)
    h = -np.maximum(0.0, z - float(D_wt))  # linear suction above WT, 0 at/below WT

    d = 0.0  # ponded depth in basin
    V_in = 0.0
    V_inf = 0.0
    V_spill = 0.0

    out_rows = []
    hit_wt = D_wt <= 0.0

    for i in range(len(t_sec) - 1):
        t0, t1 = t_sec[i], t_sec[i + 1]
        q0, q1 = qin[i], qin[i + 1]
        dt = max(1e-6, t1 - t0)

        # Substeps for stability
        n_sub = max(1, int(math.ceil(dt / 5.0)))  # ~<=5 s per substep
        dt_sub = dt / n_sub

        I_last = 0.0
        Qin_last = q1
        Qspill_last = 0.0

        for k in range(n_sub):
            t = t0 + (k + 0.5) * dt_sub
            alpha = (t - t0) / dt
            Qin = (1 - alpha) * q0 + alpha * q1

            # Compute infiltration by solving one Richards explicit step
            h_top = max(0.0, d)  # ponded pressure head
            h_bot = 0.0  # at water table
            h, infil_flux = _richards_step(h, dz, dt_sub, soil, clog, h_top, h_bot)

            # Mark if saturation front reached the WT (approximate by any h>=0 below)
            if not hit_wt:
                if np.any(h[z >= min(D_wt, zmax * 0.99)] >= 0.0):
                    hit_wt = True

            # Volumetric infiltration: apply bed area only (side leakage omitted for Richards 1D)
            I = infil_flux * A_bed

            # Mass balance on basin
            A_top = max(1e-6, _area_top(geo, d))
            net = Qin - I
            d_pred = d + (net / A_top) * dt_sub

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

            V_in += Qin * dt_sub
            V_inf += I * dt_sub

            I_last = I
            Qin_last = Qin
            Qspill_last = Qspill

        V_now = _volume(geo, d)
        out_rows.append((t1 / 3600.0, geo.floor_elev + d, d, Qin_last, I_last, V_now, Qspill_last))

    df = pd.DataFrame(out_rows, columns=[
        "time_hours", "stage_m", "depth_m", "inflow_m3s", "infil_m3s", "storage_m3", "spill_m3s"
    ])

    # Integrals
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
        idx = np.where((df["depth_m"].values < 1e-3) & (df["time_hours"].values > df["time_hours"].values.min() + 1e-6))[0]
        if len(idx):
            time_to_empty = float(df["time_hours"].values[int(idx[-1])])
    except Exception:
        time_to_empty = None

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
        "side_leakage_omitted": True,
    }


def _read_ts1_simple(ts1_path: Path) -> Tuple[np.ndarray, np.ndarray]:
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
                tt = float(parts[0]); qq = float(parts[1])
                t.append(tt); q.append(qq)
            except Exception:
                continue
    if not t:
        raise ValueError("TS1 parse produced no data; expected two numeric columns: time_hours flow_m3s")
    return np.array(t, float), np.array(q, float)


def run_preliminary_with_config(ts1_path: Optional[str], config: dict) -> tuple[bool, dict, str]:
    try:
        ts1 = Path(ts1_path) if ts1_path else None
        gcfg = config.get("basin_geometry", {})
        geo = Geometry(
            Lf=float(gcfg.get("length_floor", 50.0)),
            Wf=float(gcfg.get("width_floor", 30.0)),
            m=float(gcfg.get("side_slope_hv", 3.0)),
            Dmax=float(gcfg.get("max_depth", 3.0)),
            floor_elev=float(gcfg.get("floor_elev", 5.0)),
        )

        aqu = config.get("aquifer", {})
        infil = config.get("infiltration", {})

        # Map existing config to van Genuchten defaults
        sy = float(aqu.get("sy", 0.1))
        theta_r = float(infil.get("theta_r", 0.05))
        theta_s = float(infil.get("theta_s", theta_r + max(0.15, min(0.5, sy + 0.2))))
        vg = VGSoil(
            Ks_mpd=float(aqu.get("k_vertical_mpd", 0.0864)),
            theta_s=theta_s,
            theta_r=theta_r,
            alpha_per_m=float(infil.get("vg_alpha_per_m", 2.0)),  # ~1/0.5 m typical for sands
            n=float(infil.get("vg_n", 1.6)),  # 1.2–2.5
            l=float(infil.get("vg_l", 0.5)),
        )
        clog = Clogging(
            thickness_m=float(infil.get("bed_thickness_m", 0.5)),
            K_mpd=float(infil.get("bed_k_mpd", 5.0)),
        )

        # Water table depth below floor
        D_wt = float(geo.floor_elev - float(aqu.get("initial_head", geo.floor_elev - 1.0)))
        D_wt = max(0.0, D_wt)

        # Read hydrograph
        if ts1 is None or not ts1.exists():
            raise FileNotFoundError("TS1 hydrograph file not provided or not found")
        t_hours, q_m3s = _read_ts1_simple(ts1)

        # Integrate
        df, metrics = _integrate_prelim_richards(t_hours, q_m3s, geo, vg, clog, D_wt, include_side=False)

        # Warnings
        warnings = []
        if D_wt < max(1.0, 0.5 * geo.Dmax):
            warnings.append("Shallow water table; detailed analysis recommended.")
        peak_depth = float(np.nanmax(df["depth_m"].values)) if len(df) else 0.0
        if peak_depth > 0.9 * geo.Dmax:
            warnings.append("Peak stage near crest; detailed analysis recommended.")
        try:
            if float(metrics.get("total_spill_m3", 0.0)) > 1e-6:
                warnings.append("Basin spills in preliminary run; ensure outlet or freeboard is adequate.")
        except Exception:
            pass
        if metrics.get("side_leakage_omitted", False):
            warnings.append("Richards 1D model omits sidewall leakage; bed-only infiltration assumed.")

        scen_title = config.get("scenario_title", "Scenario 1").strip() or "Scenario 1"
        base_out = Path(config.get("output_dir") or Path.home() / "Documents" / "BaSIM" / "model_output" / "preliminary")
        scen_dir = base_out / scen_title
        outputs_root = scen_dir / "outputs"
        outputs_root.mkdir(parents=True, exist_ok=True)
        run_name = (ts1.stem if ts1 else "synthetic") + "_prelim"
        run_dir = outputs_root / run_name
        run_dir.mkdir(parents=True, exist_ok=True)

        csv_path = run_dir / "prelim_timeseries.csv"
        df.to_csv(csv_path, index=False)
        summary = {
            "analysis_mode": "preliminary_richards",
            "ts1": str(ts1) if ts1 else None,
            "run_dir": str(run_dir),
            **metrics,
            "warnings": warnings,
        }
        (run_dir / "scenario_summary.json").write_text(json.dumps(summary, indent=2))

        return True, summary, str(run_dir)

    except Exception as e:
        return False, {"error": str(e), "analysis_mode": "preliminary_richards"}, ""
