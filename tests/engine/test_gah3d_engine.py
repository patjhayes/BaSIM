"""Unit tests for the GAH-3D basin engine (phase 7 v1.2.0 mechanics).

Covers:
- Green-Ampt flux >= Ks invariant.
- Recharge mass conservation (phase 4 identity: F = deficit_filled +
  cum_recharge, exact by construction of the overflow-reservoir +
  back-calculation throttle).
- No mound "burst": the single-step mound rise stays bounded (the back-calc
  throttle damps recharge to the lateral-drainage rate when the mound
  reaches the basin invert).
- theta_deficit wiring (front speed scales inversely with the deficit).
- mound_rise_alpha defaults to 0.0 (peak-preserving, mound capped at D_gw).
- The bundled __main__ verification scenario runs without NaNs.
"""

from __future__ import annotations

import math

import numpy as np

from soakhydro.hydraulics.gah_3d_engine import GAH3D_Basin


def _make_basin(theta_deficit=None, D_gw=3.0, Ks=5e-5, Sy=0.25, **kw):
    return GAH3D_Basin(
        Ks=Ks,
        psi=0.1,
        Sy=Sy,
        b=10.0,
        L=20.0,
        W=10.0,
        D_gw=D_gw,
        theta_deficit=theta_deficit,
        **kw,
    )


def test_green_ampt_flux_is_at_least_ks():
    """The Green-Ampt potential flux f_GA must be >= Ks (capillary drive adds
    to gravity). The collision-smoothing blend only ever reduces toward Ks, so
    the realised f_actual must also be >= Ks asymptotically."""
    basin = _make_basin(theta_deficit=0.2)
    # Early time: deep front, large capillary pull -> f >> Ks
    f = basin.predict_potential_infil(dt=60.0, current_ponding_depth=0.5)
    assert f >= basin.Ks - 1e-15


def test_recharge_mass_is_conserved():
    """Phase 4 subsurface mass identity: F = deficit_filled + cum_recharge.

    The engine tracks cumulative infiltration F (per footprint area), the
    vadose deficit filled (min(F, D_gw*dtheta)), and cumulative recharge.
    Their identity holds by construction (the overflow-reservoir + back-calc
    throttle is mass-conserving). Verified per-step and cumulatively.
    """
    basin = _make_basin(theta_deficit=0.2, D_gw=0.5)
    dt = 60.0
    for _ in range(80):
        # Use step with available_water_depth so the engine handles the cap.
        # Constant 0.3 m ponding -> available depth = 0.3 m per step.
        f_base = basin.step(dt=dt, current_ponding_depth=0.3, available_water_depth=0.3)
        # Per-step subsurface identity: F = deficit_filled + cum_recharge.
        col_cap = basin.D_gw * basin.theta_deficit
        deficit = min(basin.F, col_cap)
        resid = basin.F - (deficit + basin.cum_recharge)
        assert abs(resid) < 1e-9, (
            f"per-step mass imbalance: F={basin.F:.6e} "
            f"deficit={deficit:.6e} recharge={basin.cum_recharge:.6e} resid={resid:.6e}"
        )
    # Cumulative check after the full run.
    col_cap = basin.D_gw * basin.theta_deficit
    deficit = min(basin.F, col_cap)
    resid = basin.F - (deficit + basin.cum_recharge)
    assert abs(resid) < 1e-6, (
        f"cumulative mass imbalance: F={basin.F:.6e} "
        f"deficit+recharge={deficit + basin.cum_recharge:.6e} resid={resid:.6e}"
    )


def test_no_mound_burst():
    """The mound must rise gradually, not spike in a single timestep.

    The former kinematic lag-queue clustered all buffered recharge into one
    step when the wetting front reached the water table, spiking the mound by
    metres in a single timestep. Under the overflow-reservoir model the
    single-step rise must stay a small fraction of the depth to groundwater.
    """
    basin = _make_basin(theta_deficit=0.2, D_gw=3.0)
    dt = 60.0
    Hm_prev = 0.0
    max_rise = 0.0
    for _ in range(int(12 * 3600 / dt)):
        basin.step(dt=dt, current_ponding_depth=0.5)
        rise = basin.H_m - Hm_prev
        max_rise = max(max_rise, rise)
        Hm_prev = basin.H_m
    # A 3 m column over 12 h of ponding must not jump more than ~10% in one
    # minute-long step (the old burst was a full 3 m in one step).
    assert max_rise < 0.30, f"mound burst: single-step rise {max_rise:.3f} m"
    assert basin.H_m <= basin.D_gw + 1e-9, "mound exceeded ground surface"
    assert not math.isnan(basin.H_m), "mound is NaN"


def test_theta_deficit_changes_front_speed():
    """A larger moisture deficit (Δθ) means the same flux advances the front
    more slowly (Z_f = F/Δθ). With everything else equal, tripling Δθ should
    roughly cut the front advance to one-third for the first step."""
    basin_lo = _make_basin(theta_deficit=0.1)
    basin_hi = _make_basin(theta_deficit=0.3)
    dt = 60.0
    # Use step with a small available_water_depth that caps f to a known value
    # (avail_depth/dt), so both basins get the same realised flux. The engine's
    # GA potential is huge at F=0, so the available-water cap binds.
    avail_depth = 1e-5 * dt  # -> f_cap = 1e-5 m/s
    basin_lo.step(dt=dt, current_ponding_depth=0.3, available_water_depth=avail_depth)
    basin_hi.step(dt=dt, current_ponding_depth=0.3, available_water_depth=avail_depth)
    # Z_f advances by f*dt/Δθ, so the low-deficit front advances ~3x further.
    assert basin_lo.Z_f > basin_hi.Z_f
    ratio = basin_lo.Z_f / max(basin_hi.Z_f, 1e-12)
    assert 2.5 < ratio < 3.5


def test_verification_scenario_runs_without_nans():
    """The bundled __main__ verification scenario must run stably."""
    basin = _make_basin(theta_deficit=0.25, D_gw=3.0)
    dt = 60
    for _ in range(int(12 * 3600 / dt)):
        basin.step(dt, 0.5)
    assert math.isfinite(basin.Z_f)
    assert math.isfinite(basin.H_m)
    assert 0.0 <= basin.H_m <= basin.D_gw + 1e-9


def test_mound_rise_alpha_default_is_zero():
    """The default mound_rise_alpha is 0.0 (peak-preserving hard cap), matching
    the phase 4 shipped configuration. With alpha=0 the mound is pinned at the
    basin bottom (D_gw) once it reaches it; it never exceeds D_gw."""
    basin = _make_basin(D_gw=3.0)
    assert basin.mound_rise_alpha == 0.0
    # Run constant ponding long enough for the mound to reach the cap.
    dt = 60.0
    for _ in range(int(12 * 3600 / dt)):
        basin.step(dt=dt, current_ponding_depth=0.5)
    assert basin.H_m <= basin.D_gw + 1e-9, "mound exceeded D_gw with alpha=0"
    assert basin.H_m > 0.0, "mound never rose"
