"""T6–T11: Geometry and parameter edge-case tests for LAK+UZF+MVR.

These tests exercise unusual configurations: missing bottom_elev,
single-cell basins, large basins, full infiltration mode, extreme
UZF parameters, and DEM mode.
"""
import pytest
from conftest import (
    parse_mass_balance,
    parse_peak_stage,
    count_uzf_cells,
    sum_mvr_fractions,
    lak_has_mover,
    nam_has_packages,
)

pytestmark = pytest.mark.slow


def _run(ts1, config):
    from src.main_phase3_step32_time_varying import run_phase3_step32_with_config
    ok, summary, model_dir = run_phase3_step32_with_config(ts1, config)
    return ok, summary, model_dir


# ── T6: No bottom_elev — default layer structure ─────────────────────────
class TestT6NoBotElev:
    """Omit bottom_elev; model should use default 8-layer stack."""

    def test_runs_without_error(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=None,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok, f"Model failed without bottom_elev: {summary.get('error')}"

    def test_output_files_exist(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=None,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        from pathlib import Path
        d = Path(model_dir)
        assert any(d.glob("*.lak")), "LAK file missing"
        assert any(d.glob("*.uzf")), "UZF file missing"
        assert any(d.glob("*.mvr")), "MVR file missing"


# ── T7: Single-cell basin (2m × 2m) ──────────────────────────────────────
class TestT7SingleCell:
    """Tiny basin that should produce exactly 1 UZF cell."""

    def test_model_converges(self, make_config, ts1_short):
        cfg = make_config(
            length=2.0, width=2.0, depth=1.0, slope=0.0,
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok, f"Single-cell model failed: {summary.get('error')}"

    def test_uzf_single_cell(self, make_config, ts1_short):
        cfg = make_config(
            length=2.0, width=2.0, depth=1.0, slope=0.0,
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        n = count_uzf_cells(model_dir)
        # With a 2×2 basin and min cell size ~2 m, expect very few cells
        assert 1 <= n <= 4, f"Expected 1-4 UZF cells, got {n}"

    def test_mvr_fractions_sum_to_one(self, make_config, ts1_short):
        cfg = make_config(
            length=2.0, width=2.0, depth=1.0, slope=0.0,
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        total = sum_mvr_fractions(model_dir)
        assert abs(total - 1.0) < 1e-4, f"MVR fractions sum to {total}, expected 1.0"


# ── T8: Large basin (200m × 100m) ────────────────────────────────────────
class TestT8LargeBasin:
    """Large basin — verify model completes without memory issues."""

    def test_model_completes(self, make_config, ts1_short):
        cfg = make_config(
            length=200.0, width=100.0, depth=3.0, slope=3.0,
            floor_elev=10.0, initial_head=5.0, k_mpd=10.0,
            bottom_elev=-15.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok, f"Large basin model failed: {summary.get('error')}"

    def test_uzf_cell_count_reasonable(self, make_config, ts1_short):
        cfg = make_config(
            length=200.0, width=100.0, depth=3.0, slope=3.0,
            floor_elev=10.0, initial_head=5.0, k_mpd=10.0,
            bottom_elev=-15.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        n = count_uzf_cells(model_dir)
        # 200×100 m basin with ~2-5 m cells → roughly 800-5000 cells
        assert n > 50, f"UZF cell count {n} seems too low for 200×100 basin"


# ── T9: Full infiltration mode (sidewalls) ───────────────────────────────
class TestT9FullMode:
    """Full mode includes HORIZONTAL connections. Should produce more infiltration."""

    def test_model_succeeds(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0, mode="full", bed_k_mpd=5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok, f"Full-mode model failed: {summary.get('error')}"

    def test_horizontal_connections(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0, mode="full", bed_k_mpd=5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        from pathlib import Path
        lak_files = list(Path(model_dir).glob("*.lak"))
        assert lak_files, "No LAK file found"
        text = lak_files[0].read_text(encoding="utf-8")
        assert "HORIZONTAL" in text, "Full mode LAK missing HORIZONTAL connections"


# ── T10: Extreme UZF parameters — θr ≈ θs ────────────────────────────────
class TestT10ExtremeUZF:
    """Near-equal θr and θs boundary. Model should still converge."""

    def test_model_converges(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=3.0, k_mpd=5.0,
            bottom_elev=-10.0, bed_k_mpd=5.0,
            uzf={"thts": 0.35, "thtr": 0.34, "eps": 1.0, "thti": 0.34},
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok, f"Model failed with extreme UZF params: {summary.get('error')}"


# ── T11: DEM mode ────────────────────────────────────────────────────────
class TestT11DEM:
    """DEM-driven grid. UZF/MVR files should be created."""

    def test_dem_mode_creates_uzf_mvr(self, make_config, ts1_short, dem_path):
        if dem_path is None:
            pytest.skip("EXAMPLE.dem not found")
        cfg = make_config(
            source="dem",
            dem_file=dem_path,
            crest_elev=10.0,
            floor_elev=5.0,
            initial_head=3.0,
            k_mpd=5.0,
            bottom_elev=-10.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok, f"DEM mode failed: {summary.get('error')}"
        from pathlib import Path
        d = Path(model_dir)
        assert any(d.glob("*.uzf")), "UZF file not created in DEM mode"
        assert any(d.glob("*.mvr")), "MVR file not created in DEM mode"
