"""T1–T5: Physics validation tests for LAK+UZF+MVR architecture.

These tests run MODFLOW 6 end-to-end and validate that the new UZF+MVR
routing produces physically correct results across water-table depths
and hydraulic conductivity ranges.
"""
import pytest
from conftest import parse_mass_balance, parse_peak_stage, parse_scenario_summary

pytestmark = pytest.mark.slow


def _run(ts1, config):
    """Run the model and return (success, summary, model_dir)."""
    from src.main_phase3_step32_time_varying import run_phase3_step32_with_config
    ok, summary, model_dir = run_phase3_step32_with_config(ts1, config)
    return ok, summary, model_dir


# ── T1: Deep GW — near-zero ponding (primary validation) ─────────────────
class TestT1DeepGW:
    """floor=50, GW=0, K=50, 50 m clearance.

    With 50 m/day K and 50 m of unsaturated zone, virtually all inflow
    should infiltrate with negligible ponding.
    """

    def test_model_succeeds(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=50.0, initial_head=0.0, k_mpd=50.0,
            bottom_elev=-49.0, depth=3.0, bed_k_mpd=50.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok, f"Model failed: {summary.get('error')}"

    def test_minimal_ponding(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=50.0, initial_head=0.0, k_mpd=50.0,
            bottom_elev=-49.0, depth=3.0, bed_k_mpd=50.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        peak = parse_peak_stage(model_dir)
        if peak is not None:
            assert peak < 50.0 + 0.5, f"Peak stage {peak:.2f} too high for deep GW"

    def test_mass_balance(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=50.0, initial_head=0.0, k_mpd=50.0,
            bottom_elev=-49.0, depth=3.0, bed_k_mpd=50.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        mb = parse_mass_balance(model_dir)
        if mb is not None:
            assert mb < 1.0, f"Mass balance error {mb:.2f}% exceeds 1%"


# ── T2: Shallow GW regression — ponding expected ─────────────────────────
class TestT2ShallowGW:
    """floor=5, GW=4, K=5, 1 m clearance. Moderate K.

    Should produce noticeable ponding since infiltration is limited by
    proximity to water table and moderate K.
    """

    def test_model_succeeds(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0, bed_k_mpd=5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok, f"Model failed: {summary.get('error')}"

    def test_some_ponding(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0, bed_k_mpd=5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        peak = parse_peak_stage(model_dir)
        if peak is not None:
            assert peak > 5.0 + 0.05, f"Expected ponding but peak stage {peak:.3f} near floor"

    def test_mass_balance(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0, bed_k_mpd=5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        mb = parse_mass_balance(model_dir)
        if mb is not None:
            assert mb < 1.0, f"Mass balance error {mb:.2f}% exceeds 1%"


# ── T3: Saturated floor — GW at or above basin floor ─────────────────────
class TestT3SaturatedFloor:
    """floor=5, GW=5.5 (above floor). Everything must pond."""

    def test_model_converges(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=5.5, k_mpd=5.0,
            bottom_elev=-5.0, bed_k_mpd=5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok, f"Model failed with saturated floor: {summary.get('error')}"

    def test_significant_ponding(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=5.5, k_mpd=5.0,
            bottom_elev=-5.0, bed_k_mpd=5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        peak = parse_peak_stage(model_dir)
        if peak is not None:
            assert peak > 5.0, f"Expected ponding but peak stage {peak:.2f} at or below floor"

    def test_mass_balance_relaxed(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=5.5, k_mpd=5.0,
            bottom_elev=-5.0, bed_k_mpd=5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        mb = parse_mass_balance(model_dir)
        if mb is not None:
            assert mb < 5.0, f"Mass balance error {mb:.2f}% exceeds 5% (relaxed for saturated floor)"


# ── T4: Very low K (clay) — maximum ponding ──────────────────────────────
class TestT4Clay:
    """K=0.001 m/day (clay), most water should be retained."""

    def test_model_converges(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=3.0, k_mpd=0.001,
            bottom_elev=-10.0, bed_k_mpd=0.001,
            uzf={"thts": 0.45, "thtr": 0.10, "eps": 3.0, "thti": 0.15},
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok, f"Model failed with clay K: {summary.get('error')}"

    def test_high_ponding(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=3.0, k_mpd=0.001,
            bottom_elev=-10.0, bed_k_mpd=0.001,
            uzf={"thts": 0.45, "thtr": 0.10, "eps": 3.0, "thti": 0.15},
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        peak = parse_peak_stage(model_dir)
        if peak is not None:
            # With clay, expect significant ponding (> 0.5 m above floor)
            assert peak > 5.5, f"Expected high ponding but stage {peak:.2f}"


# ── T5: Very high K (gravel) — minimal ponding ───────────────────────────
class TestT5Gravel:
    """K=100 m/day, deep GW. Should infiltrate almost everything."""

    def test_model_succeeds(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=0.0, k_mpd=100.0,
            bottom_elev=-20.0, bed_k_mpd=100.0,
            uzf={"thts": 0.30, "thtr": 0.03, "eps": 3.5, "thti": 0.05},
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok, f"Model failed: {summary.get('error')}"

    def test_minimal_ponding(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=0.0, k_mpd=100.0,
            bottom_elev=-20.0, bed_k_mpd=100.0,
            uzf={"thts": 0.30, "thtr": 0.03, "eps": 3.5, "thti": 0.05},
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        peak = parse_peak_stage(model_dir)
        if peak is not None:
            assert peak < 5.0 + 0.3, f"Peak stage {peak:.2f} too high for gravel"

    def test_mass_balance(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=0.0, k_mpd=100.0,
            bottom_elev=-20.0, bed_k_mpd=100.0,
            uzf={"thts": 0.30, "thtr": 0.03, "eps": 3.5, "thti": 0.05},
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        mb = parse_mass_balance(model_dir)
        if mb is not None:
            assert mb < 1.0, f"Mass balance error {mb:.2f}% exceeds 1%"
