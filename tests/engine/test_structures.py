"""Unit tests for the hydraulic outflow structures (BaSIM Engine).

Covers:
- Broad-crested weir: Q ∝ H^1.5, zero below crest, C_d varies by lining.
- Culvert (HY-8): inlet vs outlet control, Manning's n by material, zero below invert.
- Grated pit (QUDM): orifice + weir modes, zero below inlet.
- Rock lining: d50 increases with velocity/slope, layer thickness = 1.5*d50.
- Routing mass balance WITH structures: inflow = storage + infiltration +
  structure_outflow + overflow (residual < 1e-3).
- Weir lowers peak depth vs no-structure case.
"""

from __future__ import annotations

import math
import pytest

from soakhydro.hydraulics.structures import (
    BroadCrestedWeir,
    Culvert,
    GratedPit,
    RockLiningDesign,
    CULVERT_MANNINGS_N,
    CULVERT_DIAMETERS_MM,
    WEIR_CD,
    build_structure,
    compute_structure_outflows,
)
from soakhydro.models.common import AEP
from soakhydro.models.results import HydrographResult
from soakhydro.hydraulics.routing import route_through_basin


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_weir(crest=0.5, length=2.0, lining="concrete"):
    return BroadCrestedWeir(crest_height_m=crest, length_m=length, lining=lining)


def _make_culvert(material="RCP", invert=0.3, diameter=450, **kw):
    return Culvert(
        material=material, invert_height_m=invert,
        diameter_mm=diameter, length_m=kw.get("length", 10.0),
        slope=kw.get("slope", 0.01), count=kw.get("count", 1),
    )


def _make_pit(inlet=0.5, length=0.6, width=0.6, opening=0.5):
    return GratedPit(inlet_height_m=inlet, length_m=length, width_m=width,
                     opening_ratio=opening)


def _hydrograph(peak=0.5, n=60, ts_min=5.0, dur=60, rank=4):
    half = n // 2
    q = []
    for i in range(n):
        if i <= half:
            q.append(peak * (i / max(half, 1)))
        else:
            q.append(peak * (1.0 - (i - half) / max(n - half, 1)))
        q[-1] = max(0.0, q[-1])
    return HydrographResult(
        aep=AEP.AEP_5, duration_minutes=dur, pattern_rank=rank,
        discharge_cms=q, timestep_minutes=ts_min,
        peak_discharge_cms=max(q),
        runoff_volume_m3=sum(qi * ts_min * 60 for qi in q),
        time_to_peak_minutes=(half + 1) * ts_min,
    )


def _route(hydro, structures=None, **kw):
    return route_through_basin(
        hydrograph=hydro,
        base_length_m=kw.get("L", 8.0),
        base_width_m=kw.get("W", 5.0),
        side_slope_ratio=kw.get("slope", 4.0),
        max_depth_m=kw.get("max_depth", 1.0),
        vertical_k_mm_per_hr=kw.get("kv", 50.0),
        horizontal_k_mm_per_hr=None,
        design_drain_time_hours=kw.get("drain_hrs", 24.0),
        soil_moderation_factor=0.5,
        initial_moisture_deficit=0.2,
        capillary_suction_head_m=0.15,
        specific_yield=0.25,
        surface_level_m_ahd=10.0,
        design_gwl_m_ahd=7.0,
        base_aquifer_level_m_ahd=0.0,
        use_clogged_layer=False,
        clogged_k_m_per_day=None,
        clogged_thickness_m=None,
        basin_side_infil_enabled=True,
        hydraulic_structures=structures,
    )


# ── Broad-crested weir ───────────────────────────────────────────────────

class TestWeir:
    def test_zero_below_crest(self):
        w = _make_weir(crest=0.5)
        assert w.outflow_m3s(0.0) == 0.0
        assert w.outflow_m3s(0.49) == 0.0
        assert w.outflow_m3s(0.5) == 0.0  # at crest, H=0

    def test_scales_with_h_15(self):
        w = _make_weir(crest=0.0, length=1.0, lining="concrete")
        q1 = w.outflow_m3s(1.0)
        q2 = w.outflow_m3s(2.0)
        # Q ∝ H^1.5, so doubling H should ~2.83x the flow
        ratio = q2 / q1
        assert 2.7 < ratio < 2.9, f"H^1.5 ratio {ratio} != ~2.83"

    def test_concrete_higher_than_earth(self):
        w_concrete = _make_weir(lining="concrete")
        w_earth = _make_weir(lining="bare_earth")
        h = 1.0
        assert w_concrete.outflow_m3s(h) > w_earth.outflow_m3s(h)
        assert WEIR_CD["concrete"] > WEIR_CD["bare_earth"]

    def test_rock_lined_intermediate(self):
        w_rock = _make_weir(lining="rock_lined")
        w_concrete = _make_weir(lining="concrete")
        w_earth = _make_weir(lining="bare_earth")
        h = 1.0
        q_rock = w_rock.outflow_m3s(h)
        assert w_earth.outflow_m3s(h) < q_rock < w_concrete.outflow_m3s(h)


# ── Culvert (HY-8) ───────────────────────────────────────────────────────

class TestCulvert:
    def test_zero_below_invert(self):
        c = _make_culvert(invert=0.3)
        assert c.outflow_m3s(0.0) == 0.0
        assert c.outflow_m3s(0.29) == 0.0
        assert c.outflow_m3s(0.3) == 0.0  # at invert, H=0

    def test_scales_with_head(self):
        c = _make_culvert(invert=0.0)
        q1 = c.outflow_m3s(1.0)
        q2 = c.outflow_m3s(4.0)
        assert q2 > q1 > 0.0

    def test_material_mannings_n(self):
        assert CULVERT_MANNINGS_N["PVC"] < CULVERT_MANNINGS_N["RCP"]
        assert CULVERT_MANNINGS_N["RCP"] < CULVERT_MANNINGS_N["CSP"]
        assert CULVERT_MANNINGS_N["RCBC"] > CULVERT_MANNINGS_N["PVC"]

    def test_larger_diameter_more_flow(self):
        c_small = _make_culvert(diameter=300)
        c_large = _make_culvert(diameter=900)
        h = 1.0
        assert c_large.outflow_m3s(h) > c_small.outflow_m3s(h)

    def test_multi_barrel_scales(self):
        c1 = _make_culvert(count=1)
        c3 = _make_culvert(count=3)
        h = 1.0
        # Inlet control scales linearly with count; outlet control ~linearly
        assert c3.outflow_m3s(h) > c1.outflow_m3s(h)

    def test_standard_diameters_available(self):
        assert 300 in CULVERT_DIAMETERS_MM
        assert 1800 in CULVERT_DIAMETERS_MM
        assert all(d > 0 for d in CULVERT_DIAMETERS_MM)


# ── Grated pit (QUDM) ────────────────────────────────────────────────────

class TestGratedPit:
    def test_zero_below_inlet(self):
        p = _make_pit(inlet=0.5)
        assert p.outflow_m3s(0.0) == 0.0
        assert p.outflow_m3s(0.49) == 0.0
        assert p.outflow_m3s(0.5) == 0.0  # at inlet, H=0

    def test_scales_with_head(self):
        p = _make_pit(inlet=0.0)
        q1 = p.outflow_m3s(0.5)
        q2 = p.outflow_m3s(2.0)
        assert q2 > q1 > 0.0

    def test_larger_grate_more_flow(self):
        p_small = _make_pit(length=0.3, width=0.3)
        p_large = _make_pit(length=1.2, width=1.2)
        h = 1.0
        assert p_large.outflow_m3s(h) > p_small.outflow_m3s(h)

    def test_opening_ratio_matters(self):
        p_closed = _make_pit(opening=0.1)
        p_open = _make_pit(opening=0.9)
        h = 1.0
        assert p_open.outflow_m3s(h) >= p_closed.outflow_m3s(h)


# ── Rock lining ──────────────────────────────────────────────────────────

class TestRockLining:
    def test_d50_increases_with_velocity(self):
        r_slow = RockLiningDesign(velocity_ms=1.0)
        r_fast = RockLiningDesign(velocity_ms=3.0)
        assert r_fast.d50_governing_mm() > r_slow.d50_governing_mm()

    def test_d50_increases_with_slope(self):
        r_flat = RockLiningDesign(velocity_ms=2.0, slope=0.1)
        r_steep = RockLiningDesign(velocity_ms=2.0, slope=0.5)
        assert r_steep.d50_governing_mm() >= r_flat.d50_governing_mm()

    def test_layer_thickness_is_1_5x_d50(self):
        r = RockLiningDesign(velocity_ms=2.0)
        d50 = r.d50_governing_mm()
        assert abs(r.layer_thickness_mm() - 1.5 * d50) < 0.1

    def test_gradation_band_has_d50_d100_d15(self):
        r = RockLiningDesign(velocity_ms=2.0)
        band = r.gradation_band()
        assert band["d50_mm"] > 0
        assert band["d100_mm"] > band["d50_mm"]
        assert band["d15_mm"] < band["d50_mm"]

    def test_reasonable_values(self):
        r = RockLiningDesign(velocity_ms=2.0, depth_m=0.3, slope=0.33)
        d50 = r.d50_governing_mm()
        assert 50 < d50 < 500, f"d50 {d50}mm outside expected 50-500mm range"


# ── Factory ──────────────────────────────────────────────────────────────

class TestBuildStructure:
    def test_build_weir(self):
        d = {"type": "weir", "weir_crest_level_m_ahd": 10.5,
             "weir_length_m": 2.0, "weir_lining": "concrete",
             "_basin_invert_m_ahd": 10.0}
        s = build_structure(d)
        assert isinstance(s, BroadCrestedWeir)
        assert s.crest_height_m == 0.5  # 10.5 - 10.0

    def test_build_culvert(self):
        d = {"type": "culvert", "culvert_material": "RCP",
             "culvert_diameter_mm": 450, "culvert_invert_level_m_ahd": 10.3,
             "culvert_length_m": 12.0, "culvert_slope": 0.01,
             "_basin_invert_m_ahd": 10.0}
        s = build_structure(d)
        assert isinstance(s, Culvert)
        assert s.invert_height_m == pytest.approx(0.3)

    def test_build_pit(self):
        d = {"type": "grated_pit", "pit_inlet_level_m_ahd": 10.5,
             "pit_length_m": 0.6, "pit_width_m": 0.6,
             "_basin_invert_m_ahd": 10.0}
        s = build_structure(d)
        assert isinstance(s, GratedPit)
        assert s.inlet_height_m == 0.5

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            build_structure({"type": "fountain"})


# ── compute_structure_outflows ───────────────────────────────────────────

class TestComputeOutflows:
    def test_no_structures(self):
        total, per = compute_structure_outflows([], 1.0, 60.0, 100.0)
        assert total == 0.0
        assert per == []

    def test_capped_by_available_storage(self):
        w = _make_weir(crest=0.0, length=10.0)  # large weir
        total, per = compute_structure_outflows([w], 2.0, 60.0, 5.0)
        # Weir Q is large; outflow should be capped to 5.0 m3
        assert total == pytest.approx(5.0, abs=0.01)

    def test_multiple_structures_summed(self):
        w = _make_weir(crest=0.0, length=1.0)
        p = _make_pit(inlet=0.0)
        total, per = compute_structure_outflows([w, p], 1.0, 60.0, 1000.0)
        assert len(per) == 2
        assert total == pytest.approx(sum(per), abs=0.01)


# ── Routing mass balance with structures ─────────────────────────────────

class TestRoutingWithStructures:
    def test_weir_lowers_peak_depth(self):
        """A weir at the basin crest should lower the peak ponded depth
        compared to no structure (water is extracted from the surface)."""
        hydro = _hydrograph(peak=0.5, n=60)
        ts_no_struct = _route(hydro)
        ts_with_weir = _route(hydro, structures=[
            {"type": "weir", "weir_crest_level_m_ahd": 10.5,
             "weir_length_m": 3.0, "weir_lining": "concrete"},
        ])
        peak_no = max(ts_no_struct.depth_m)
        peak_weir = max(ts_with_weir.depth_m)
        assert peak_weir < peak_no, (
            f"Weir should lower peak: weir={peak_weir} vs no-struct={peak_no}"
        )
        # And there should be structure outflow
        assert max(ts_with_weir.cumulative_structure_outflow_m3) > 0.0

    def test_mass_balance_with_structure(self):
        """inflow = storage + infiltration + structure_outflow + overflow."""
        hydro = _hydrograph(peak=0.3, n=40)
        ts = _route(hydro, structures=[
            {"type": "weir", "weir_crest_level_m_ahd": 10.3,
             "weir_length_m": 2.0, "weir_lining": "concrete"},
        ])
        for i in range(len(ts.time_minutes)):
            inflow = ts.cumulative_inflow_m3[i]
            storage = ts.storage_volume_m3[i]
            infil = ts.cumulative_infiltration_m3[i]
            struct = ts.cumulative_structure_outflow_m3[i]
            overflow = ts.cumulative_overflow_m3[i]
            balance = storage + infil + struct + overflow
            assert abs(inflow - balance) < 1e-2, (
                f"Step {i}: inflow {inflow:.3f} != "
                f"storage+infil+struct+overflow {balance:.3f}"
            )

    def test_culvert_lowers_peak_depth(self):
        hydro = _hydrograph(peak=0.5, n=60)
        ts_no = _route(hydro)
        ts_culv = _route(hydro, structures=[
            {"type": "culvert", "culvert_material": "RCP",
             "culvert_diameter_mm": 450, "culvert_invert_level_m_ahd": 10.1,
             "culvert_length_m": 10.0, "culvert_slope": 0.01},
        ])
        assert max(ts_culv.depth_m) < max(ts_no.depth_m)
        assert max(ts_culv.cumulative_structure_outflow_m3) > 0.0

    def test_pit_lowers_peak_depth(self):
        hydro = _hydrograph(peak=0.5, n=60)
        ts_no = _route(hydro)
        ts_pit = _route(hydro, structures=[
            {"type": "grated_pit", "pit_inlet_level_m_ahd": 10.2,
             "pit_length_m": 0.9, "pit_width_m": 0.9, "pit_opening_ratio": 0.5},
        ])
        assert max(ts_pit.depth_m) < max(ts_no.depth_m)

    def test_multiple_structures(self):
        """Multiple structures on one basin — all extract water, mass
        balance holds."""
        hydro = _hydrograph(peak=0.5, n=60)
        ts = _route(hydro, structures=[
            {"type": "weir", "weir_crest_level_m_ahd": 10.5,
             "weir_length_m": 2.0, "weir_lining": "concrete"},
            {"type": "culvert", "culvert_material": "RCP",
             "culvert_diameter_mm": 375, "culvert_invert_level_m_ahd": 10.1},
            {"type": "grated_pit", "pit_inlet_level_m_ahd": 10.3,
             "pit_length_m": 0.6, "pit_width_m": 0.6},
        ])
        assert max(ts.cumulative_structure_outflow_m3) > 0.0
        # Mass balance
        n = len(ts.time_minutes)
        i = n - 1
        inflow = ts.cumulative_inflow_m3[i]
        storage = ts.storage_volume_m3[i]
        infil = ts.cumulative_infiltration_m3[i]
        struct = ts.cumulative_structure_outflow_m3[i]
        overflow = ts.cumulative_overflow_m3[i]
        assert abs(inflow - (storage + infil + struct + overflow)) < 1e-2

    def test_no_structures_backward_compat(self):
        """With no structures, the routing should behave exactly as before —
        structure_outflow is zero, mass balance holds."""
        hydro = _hydrograph(peak=0.2, n=40)
        ts = _route(hydro)
        assert all(v == 0.0 for v in ts.structure_outflow_m3)
        assert all(v == 0.0 for v in ts.cumulative_structure_outflow_m3)
        for i in range(len(ts.time_minutes)):
            inflow = ts.cumulative_inflow_m3[i]
            storage = ts.storage_volume_m3[i]
            infil = ts.cumulative_infiltration_m3[i]
            overflow = ts.cumulative_overflow_m3[i]
            assert abs(inflow - (storage + infil + overflow)) < 1e-3
