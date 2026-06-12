"""
Outlet hydraulics (post-processing) for BaSIM.

Implements Option A: Apply outlet structure discharge as a post-process to
MODFLOW LAK results by solving an external water balance.

Conventions
- Stages are absolute elevations (m AHD).
- Time array is in days (consistent with MF6 outputs).
- Flows are in m3/s.

Notes
- Pipe hydraulics implement a pragmatic inlet/outlet control switch using
  standard orifice/weir equations for inlet control and Manning full-flow
  capacity for outlet control (free outfall, no tailwater).
- Broad-crested weir uses Q = Cd * L * h^(1.5) * sqrt(2g) with zero below crest.
- Grated inlet uses the minimum of weir (perimeter-based) and orifice (area-based)
  formulations. Coefficients can be supplied directly or chosen by grate type.

This module avoids external dependencies beyond numpy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List, Callable
import math
import numpy as np

GRAV = 9.80665  # m/s^2


class OutletStructure:
    """Base class for outlet hydraulic structures."""

    def discharge(self, stage: float) -> float:
        """Calculate discharge (m^3/s) for a given absolute stage (m AHD)."""
        raise NotImplementedError


@dataclass
class PipedOutlet(OutletStructure):
    diameter_m: float
    length_m: float
    invert_mAHD: float
    grade: float  # slope m/m (positive downstream)
    mannings_n: float = 0.013
    count: int = 1
    entrance_type: str = "square"  # "square" | "rounded" | "beveled"

    def __post_init__(self):
        self.diameter_m = max(1e-6, float(self.diameter_m))
        self.length_m = max(1e-6, float(self.length_m))
        self.grade = max(1e-6, float(self.grade))
        self.mannings_n = max(1e-6, float(self.mannings_n))
        self.count = max(1, int(self.count))
        self._area = math.pi * (self.diameter_m ** 2) / 4.0
        self._perimeter = math.pi * self.diameter_m
        self._radius_h = self._area / (self._perimeter)  # hydraulic radius when full
        # Entrance coefficients (approximate typical values)
        et = str(self.entrance_type or "").strip().lower()
        if et in ("rounded", "round", "r"):  # rounded edge
            self._Cd_orif = 0.62
            self._Cw_weir = 1.6  # effective broad-weir factor for circular opening
        elif et in ("beveled", "bevel", "b"):
            self._Cd_orif = 0.68
            self._Cw_weir = 1.7
        else:  # square/flush/other
            self._Cd_orif = 0.60
            self._Cw_weir = 1.5

    def _Q_outlet_control_full(self) -> float:
        """Barrel full-flow capacity by Manning (per pipe), m3/s.

        Q = (1/n) * A * R^(2/3) * S^(1/2)
        """
        A = self._area
        R = self._radius_h
        S = max(1e-8, self.grade)
        n = self.mannings_n
        return (1.0 / n) * A * (R ** (2.0 / 3.0)) * (S ** 0.5)

    def _Q_inlet_control(self, head_above_invert: float) -> float:
        """Inlet-control discharge per pipe as min(weir, orifice)."""
        h = max(0.0, head_above_invert)
        if h <= 0.0:
            return 0.0
        # Sharp/rounded entrance weir-like control (span ~ diameter)
        Qw = self._Cw_weir * self.diameter_m * (h ** 1.5) * math.sqrt(2.0 * GRAV)
        # Submerged orifice control
        Qo = self._Cd_orif * self._area * math.sqrt(2.0 * GRAV * h)
        return min(Qw, Qo)

    def discharge(self, stage: float) -> float:
        """Total discharge for all pipes at given stage (m AHD)."""
        # Upstream head above invert
        He = float(stage) - float(self.invert_mAHD)
        if He <= 0.0:
            return 0.0
        q_in = self._Q_inlet_control(He)
        q_out = self._Q_outlet_control_full()
        q_single = min(q_in, q_out)
        return float(self.count) * q_single


@dataclass
class BroadCrestedWeir(OutletStructure):
    crest_mAHD: float
    crest_length_m: float
    Cd: float = 0.577

    def discharge(self, stage: float) -> float:
        h = float(stage) - float(self.crest_mAHD)
        if h <= 0.0:
            return 0.0
        L = max(1e-6, float(self.crest_length_m))
        Cd = max(1e-6, float(self.Cd))
        # Q = Cd * L * h^(3/2) * sqrt(2g)
        return Cd * L * (h ** 1.5) * math.sqrt(2.0 * GRAV)


# Default coefficients for selected grate types (approximate). Users can override via GUI.
GRATE_COEFFICIENTS: Dict[str, Tuple[float, float]] = {
    # name -> (Cw_weir, Cd_orifice)
    "p1-1/8": (1.6, 0.62),
    "p1-7/8": (1.6, 0.62),
    "reticuline": (1.5, 0.60),
    "generic": (1.6, 0.62),
}


@dataclass
class GratedInlet(OutletStructure):
    crest_mAHD: float
    grate_area_m2: float
    perimeter_m: float
    grate_type: str = "generic"
    Cw_weir: Optional[float] = None
    Cd_orifice: Optional[float] = None

    def __post_init__(self):
        self.grate_area_m2 = max(0.0, float(self.grate_area_m2))
        self.perimeter_m = max(0.0, float(self.perimeter_m))
        gt = str(self.grate_type or "generic").strip().lower()
        cw_def, cd_def = GRATE_COEFFICIENTS.get(gt, GRATE_COEFFICIENTS["generic"])
        if self.Cw_weir is None:
            self.Cw_weir = cw_def
        if self.Cd_orifice is None:
            self.Cd_orifice = cd_def

    def discharge(self, stage: float) -> float:
        h = float(stage) - float(self.crest_mAHD)
        if h <= 0.0 or self.grate_area_m2 <= 0.0 or self.perimeter_m <= 0.0:
            return 0.0
        # Weir-like flow across perimeter (shallow heads)
        Qw = float(self.Cw_weir) * float(self.perimeter_m) * (h ** 1.5) * math.sqrt(2.0 * GRAV)
        # Orifice-like flow through openings (submerged heads)
        Qo = float(self.Cd_orifice) * float(self.grate_area_m2) * math.sqrt(2.0 * GRAV * h)
        # QUDM recommends the minimum of the two
        return min(Qw, Qo)


def create_outlet_from_config(cfg: Dict) -> OutletStructure:
    """Factory to build an OutletStructure from config dict."""
    typ = str(cfg.get("type", "")).strip().lower()
    if typ in ("pipe", "piped", "culvert"):
        return PipedOutlet(
            diameter_m=float(cfg.get("diameter_m", 0.0)),
            length_m=float(cfg.get("length_m", 0.0)),
            invert_mAHD=float(cfg.get("invert_mAHD", cfg.get("invert_level_mAHD", 0.0))),
            grade=float(cfg.get("grade", cfg.get("slope", 0.0))),
            mannings_n=float(cfg.get("mannings_n", 0.013)),
            count=int(cfg.get("count", cfg.get("number", 1))),
            entrance_type=str(cfg.get("entrance_type", "square")),
        )
    if typ in ("weir", "broad", "broad-crested weir", "broad_crested_weir"):
        return BroadCrestedWeir(
            crest_mAHD=float(cfg.get("crest_mAHD", cfg.get("crest_level_mAHD", 0.0))),
            crest_length_m=float(cfg.get("crest_length_m", cfg.get("length_m", 0.0))),
            Cd=float(cfg.get("Cd", cfg.get("cd", 0.577))),
        )
    if typ in ("grate", "grated", "grated inlet", "grated_inlet"):
        return GratedInlet(
            crest_mAHD=float(cfg.get("crest_mAHD", cfg.get("crest_level_mAHD", 0.0))),
            grate_area_m2=float(cfg.get("grate_area_m2", cfg.get("area_m2", 0.0))),
            perimeter_m=float(cfg.get("perimeter_m", cfg.get("perimeter", 0.0))),
            grate_type=str(cfg.get("grate_type", "generic")),
            Cw_weir=(None if cfg.get("Cw_weir") is None else float(cfg.get("Cw_weir"))),
            Cd_orifice=(None if cfg.get("Cd_orifice") is None else float(cfg.get("Cd_orifice"))),
        )
    raise ValueError(f"Unsupported outlet type: {cfg.get('type')}")


def _build_depth_area_to_volume(depth_area: List[Tuple[float, float]]):
    """Return (depths, areas, volumes) arrays from a depth–area table.

    Depths must start at 0. Areas must be > 0. Volumes are cumulative trapezoid.
    """
    if not depth_area or len(depth_area) < 2:
        return None
    rows = sorted([(max(0.0, float(d)), max(0.0, float(a))) for d, a in depth_area], key=lambda x: x[0])
    depths = np.array([r[0] for r in rows], float)
    areas = np.array([r[1] for r in rows], float)
    vols = np.zeros_like(depths)
    for i in range(1, len(depths)):
        dd = depths[i] - depths[i - 1]
        vols[i] = vols[i - 1] + 0.5 * (areas[i] + areas[i - 1]) * dd
    return depths, areas, vols


def _geom_stage_to_storage_fn(geom: Dict, floor_elev: float) -> Tuple[Callable[[np.ndarray], np.ndarray], Callable[[np.ndarray], np.ndarray]]:
    """Return two callables: stage->storage and storage->stage using geometry.

    Geometry dict may contain custom_depth_area: [[depth, area], ...]. If not,
    use trapezoidal basin with floor length Lf, width Wf, side slope m (H:V), and
    max_depth D.
    """
    Lf = float(geom.get("length_floor", geom.get("length_floor_m", 0.0)))
    Wf = float(geom.get("width_floor", geom.get("width_floor_m", 0.0)))
    m = float(geom.get("side_slope_hv", geom.get("side_slope", 0.0)))
    Dmax = float(geom.get("max_depth", geom.get("max_depth_m", 0.0)))
    cda = geom.get("custom_depth_area")
    if isinstance(cda, (list, tuple)) and len(cda) >= 2:
        built = _build_depth_area_to_volume(cda)  # [(d, a)] with d from floor
        if built is not None:
            depths, areas, vols = built

            def stg_to_vol(stage: np.ndarray) -> np.ndarray:
                d = np.clip(np.asarray(stage, float) - float(floor_elev), 0.0, float(depths[-1]))
                return np.interp(d, depths, vols, left=0.0, right=float(vols[-1]))

            def vol_to_stg(vol: np.ndarray) -> np.ndarray:
                v = np.clip(np.asarray(vol, float), 0.0, float(vols[-1]))
                d = np.interp(v, vols, depths, left=0.0, right=float(depths[-1]))
                return float(floor_elev) + d

            return stg_to_vol, vol_to_stg

    # Fallback: trapezoidal prism formulas
    Lf = max(0.0, Lf); Wf = max(0.0, Wf); m = max(0.0, m); Dmax = max(0.0, Dmax)

    def stg_to_vol(stage: np.ndarray) -> np.ndarray:
        d = np.clip(np.asarray(stage, float) - float(floor_elev), 0.0, Dmax)
        return (Lf * Wf) * d + m * (Lf + Wf) * (d ** 2) + (4.0 / 3.0) * (m ** 2) * (d ** 3)

    # Invert cubic by monotone interpolation over a fine grid for numerical stability
    d_grid = np.linspace(0.0, max(Dmax, 1e-6), 1001)
    v_grid = (Lf * Wf) * d_grid + m * (Lf + Wf) * (d_grid ** 2) + (4.0 / 3.0) * (m ** 2) * (d_grid ** 3)

    def vol_to_stg(vol: np.ndarray) -> np.ndarray:
        v = np.clip(np.asarray(vol, float), 0.0, float(v_grid[-1]))
        d = np.interp(v, v_grid, d_grid, left=0.0, right=float(d_grid[-1]))
        return float(floor_elev) + d

    return stg_to_vol, vol_to_stg


def apply_outlet_to_results(
    time_days: np.ndarray,
    modflow_stage: np.ndarray,
    modflow_inflow: Optional[np.ndarray],  # m3/s
    modflow_infiltration: Optional[object],  # m3/s array OR callable(stage)->m3/s OR {'stage_grid':..,'qinf_grid':..}
    outlet_structure: OutletStructure | List[OutletStructure],
    basin_geometry: Dict,
    floor_elev: float,
    *,
    max_iter_per_step: int = 12,
    relax: float = 0.6,
) -> Dict[str, np.ndarray | float]:
    """Recalculate basin stage with outlet discharge by mass balance.

    Mass balance per step: S_{i+1} = S_i + (Qin_i - Qinf_i - Qout_i) * dt.
    Qout depends on stage; we use a short Picard iteration with relaxation.

    Returns a dict with arrays: time_days, stage_with_outlet, outlet_discharge, storage_with_outlet.
    Also includes peak_outlet_m3s, total_outlet_m3.
    """
    t = np.asarray(time_days, float)
    stg = np.asarray(modflow_stage, float)
    if t.ndim != 1 or stg.ndim != 1 or len(t) != len(stg):
        raise ValueError("time_days and modflow_stage must be 1D arrays of same length")
    n = len(t)
    # Inflow defaults
    Qin = np.zeros(n, float) if modflow_inflow is None else np.asarray(modflow_inflow, float)
    if len(Qin) != n:
        Qin = np.resize(Qin, n)

    # Build infiltration provider: supports array (per-time), callable(stage)->m3/s, or rating grid dict/tuple
    _qinf_array: Optional[np.ndarray] = None
    _qinf_callable: Optional[Callable[[float], float]] = None
    if modflow_infiltration is None:
        _qinf_callable = lambda _s: 0.0
    elif callable(modflow_infiltration):
        _qinf_callable = lambda s: float(modflow_infiltration(s))
    elif isinstance(modflow_infiltration, dict) and (
        ('stage_grid' in modflow_infiltration and 'qinf_grid' in modflow_infiltration)
        or ('stage' in modflow_infiltration and 'qinf' in modflow_infiltration)
    ):
        stg_key = 'stage_grid' if 'stage_grid' in modflow_infiltration else 'stage'
        q_key = 'qinf_grid' if 'qinf_grid' in modflow_infiltration else 'qinf'
        _stg_grid = np.asarray(modflow_infiltration[stg_key], float)
        _q_grid = np.asarray(modflow_infiltration[q_key], float)
        def _interp_qinf(s: float) -> float:
            return float(np.interp(float(s), _stg_grid, _q_grid, left=float(_q_grid[0]), right=float(_q_grid[-1])))
        _qinf_callable = _interp_qinf
    elif isinstance(modflow_infiltration, (tuple, list)) and len(modflow_infiltration) == 2:
        _stg_grid = np.asarray(modflow_infiltration[0], float)
        _q_grid = np.asarray(modflow_infiltration[1], float)
        def _interp_qinf2(s: float) -> float:
            return float(np.interp(float(s), _stg_grid, _q_grid, left=float(_q_grid[0]), right=float(_q_grid[-1])))
        _qinf_callable = _interp_qinf2
    else:
        # Assume array-like per-time series
        try:
            _qinf_array = np.asarray(modflow_infiltration, float)
            if len(_qinf_array) != n:
                _qinf_array = np.resize(_qinf_array, n)
        except Exception:
            _qinf_callable = lambda _s: 0.0

    # Geometry mappings
    stg2vol, vol2stg = _geom_stage_to_storage_fn(basin_geometry or {}, float(floor_elev))

    # Initial storage from original MF6 stage (baseline)
    S0 = float(stg2vol(stg[0]))
    S = np.zeros(n, float)
    S[0] = S0
    stg_out = np.zeros(n, float)
    stg_out[0] = float(stg[0])
    Qout = np.zeros(n, float)
    # If multiple outlets, also track per-component flows
    outlets: List[OutletStructure]
    if isinstance(outlet_structure, (list, tuple)):
        outlets = list(outlet_structure)  # type: ignore
    else:
        outlets = [outlet_structure]
    comp = np.zeros((n, len(outlets)), float) if len(outlets) > 1 else None
    Qinf_used = np.zeros(n, float)

    # Timestep sizes (seconds). Last dt reused from previous.
    dt_days = np.diff(t)
    if np.any(dt_days <= -1e-12):
        raise ValueError("time_days must be non-decreasing")
    # Replace zeros with tiny to avoid division issues
    dt_sec = np.where(dt_days > 0.0, dt_days * 86400.0, 1e-3)

    for i in range(n - 1):
        dt = float(dt_sec[i])
        # Start with previous stage
        s_prev = float(stg_out[i])
        v_prev = float(S[i])
        # Picard iteration on stage within the step
        s_est = s_prev
        # Estimate total outlet discharge at current stage
        if len(outlets) == 1:
            qout_est = outlets[0].discharge(s_est)
            comp_est = [qout_est]
        else:
            vals = [o.discharge(s_est) for o in outlets]
            qout_est = float(sum(vals))
            comp_est = vals
        # Initial infiltration at current stage estimate
        if _qinf_callable is not None:
            qinf_est = float(_qinf_callable(s_est))
        elif _qinf_array is not None:
            qinf_est = float(_qinf_array[i])
        else:
            qinf_est = 0.0
        for _ in range(max_iter_per_step):
            v_next = v_prev + (float(Qin[i]) - float(qinf_est) - qout_est) * dt
            s_next = float(vol2stg(v_next))
            if len(outlets) == 1:
                qout_next = outlets[0].discharge(s_next)
                comp_next = [qout_next]
            else:
                vlist = [o.discharge(s_next) for o in outlets]
                qout_next = float(sum(vlist))
                comp_next = vlist
            # Update infiltration based on updated stage if stage-dependent model
            if _qinf_callable is not None:
                qinf_next = float(_qinf_callable(s_next))
            elif _qinf_array is not None:
                qinf_next = float(_qinf_array[i])
            else:
                qinf_next = 0.0
            # Relax to improve stability
            qout_new = relax * qout_next + (1.0 - relax) * qout_est
            qinf_new = relax * qinf_next + (1.0 - relax) * qinf_est
            # Convergence check on discharge
            if (
                abs(qout_new - qout_est) <= max(1e-6, 1e-3 * max(1.0, qout_est))
                and abs(qinf_new - qinf_est) <= max(1e-6, 1e-3 * max(1.0, qinf_est))
            ):
                qout_est = qout_new
                qinf_est = qinf_new
                s_est = s_next
                # carry component values forward
                comp_est = comp_next
                break
            qout_est = qout_new
            qinf_est = qinf_new
            s_est = s_next
            # also relax components proportionally if multiple
            if len(outlets) > 1:
                # avoid divide-by-zero; if qout_next ~ 0 use comp_next directly
                if qout_next > 1e-12:
                    scale = qout_new / qout_next
                    comp_est = [c * scale for c in comp_next]
                else:
                    comp_est = comp_next
        # Commit step
        S[i + 1] = v_prev + (float(Qin[i]) - float(qinf_est) - qout_est) * dt
        stg_out[i + 1] = float(vol2stg(S[i + 1]))
        Qout[i] = float(qout_est)
        Qinf_used[i] = float(qinf_est)
        if comp is not None:
            for j, v in enumerate(comp_est):
                comp[i, j] = float(v)
    # For last point's outlet, re-evaluate at last stage
    if len(outlets) == 1:
        Qout[-1] = float(outlets[0].discharge(stg_out[-1]))
        if comp is not None:
            comp[-1, 0] = Qout[-1]
    else:
        last_vals = [o.discharge(stg_out[-1]) for o in outlets]
        Qout[-1] = float(sum(last_vals))
        if comp is not None:
            for j, v in enumerate(last_vals):
                comp[-1, j] = float(v)
    # Last infiltration at last stage
    if _qinf_callable is not None:
        Qinf_used[-1] = float(_qinf_callable(stg_out[-1]))
    elif _qinf_array is not None:
        Qinf_used[-1] = float(_qinf_array[-1])
    else:
        Qinf_used[-1] = 0.0

    # Metrics
    peak_out = float(np.nanmax(Qout)) if len(Qout) else 0.0
    # Integrate outlet volume over the timeline
    if n >= 2:
        # Use seconds grid from t (days)
        t_sec = t * 86400.0
        try:
            from numpy import trapz as _trapz
            vol_out = float(_trapz(Qout, t_sec))
        except Exception:
            vol_out = float(np.sum(Qout[:-1] * np.diff(t_sec)))
    else:
        vol_out = 0.0

    result: Dict[str, np.ndarray | float] = {
        "time_days": t,
        "stage_with_outlet": stg_out,
        "outlet_discharge": Qout,
        "storage_with_outlet": S,
        "infiltration_m3s": Qinf_used,
        "peak_outlet_m3s": peak_out,
        "total_outlet_m3": vol_out,
    }
    if comp is not None:
        result["outlet_components_m3s"] = comp
    return result
