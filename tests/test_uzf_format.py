"""T12–T13: Config round-trip and file-format validation (fast tests).

These do NOT run MODFLOW — they only call the writer functions and
inspect the generated files.
"""
import json
import pytest
from conftest import (
    count_uzf_cells,
    sum_mvr_fractions,
    lak_has_mover,
    nam_has_packages,
)


def _run(ts1, config):
    from src.main_phase3_step32_time_varying import run_phase3_step32_with_config
    ok, summary, model_dir = run_phase3_step32_with_config(ts1, config)
    return ok, summary, model_dir


# ── T12: Config → GUI → Config round-trip ─────────────────────────────────
class TestT12ConfigRoundTrip:
    """Default config UZF block survives build_config / _apply_config."""

    def test_default_uzf_keys_present(self, make_config):
        cfg = make_config()
        uzf = cfg.get("uzf", {})
        for key in ("thts", "thtr", "eps", "thti"):
            assert key in uzf, f"Missing UZF key: {key}"

    def test_default_uzf_values(self, make_config):
        cfg = make_config()
        uzf = cfg["uzf"]
        assert abs(uzf["thts"] - 0.35) < 1e-6
        assert abs(uzf["thtr"] - 0.05) < 1e-6
        assert abs(uzf["eps"] - 4.0) < 1e-6
        assert abs(uzf["thti"] - 0.10) < 1e-6

    def test_custom_uzf_values_preserved(self, make_config):
        cfg = make_config(uzf={"thts": 0.45, "thtr": 0.10, "eps": 2.5, "thti": 0.12})
        uzf = cfg["uzf"]
        assert abs(uzf["thts"] - 0.45) < 1e-6
        assert abs(uzf["thtr"] - 0.10) < 1e-6
        assert abs(uzf["eps"] - 2.5) < 1e-6
        assert abs(uzf["thti"] - 0.12) < 1e-6

    def test_config_json_serialisable(self, make_config):
        cfg = make_config()
        text = json.dumps(cfg)
        loaded = json.loads(text)
        assert loaded["uzf"] == cfg["uzf"]


# ── T13: File format validation (runs model, inspects output) ────────────
@pytest.mark.slow
class TestT13FileFormat:
    """Verify LAK MOVER keyword, UZF cell count, MVR fractions, NAM entries."""

    def test_lak_has_mover_keyword(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        assert lak_has_mover(model_dir), "LAK file missing MOVER keyword"

    def test_uzf_cell_count_nonzero(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        assert count_uzf_cells(model_dir) > 0, "No UZF cells written"

    def test_mvr_fractions_sum_to_one(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        total = sum_mvr_fractions(model_dir)
        assert abs(total - 1.0) < 1e-4, f"MVR fractions sum={total}"

    def test_nam_has_all_packages(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        checks = nam_has_packages(model_dir)
        assert checks["LAK6"], "NAM missing LAK6"
        assert checks["UZF6"], "NAM missing UZF6"
        assert checks["MVR6"], "NAM missing MVR6"

    def test_mass_balance_acceptable(self, make_config, ts1_short):
        cfg = make_config(
            floor_elev=5.0, initial_head=4.0, k_mpd=5.0,
            bottom_elev=-5.0,
        )
        ok, summary, model_dir = _run(ts1_short, cfg)
        assert ok
        mb = parse_mass_balance_from_summary(summary)
        if mb is not None:
            assert mb < 5.0, f"Mass balance error {mb}% exceeds 5%"


def parse_mass_balance_from_summary(summary):
    """Extract mass balance % from run summary dict."""
    if not summary:
        return None
    for key in ("mass_balance_pct", "mass_balance_error", "mass_bal_pct"):
        val = summary.get(key)
        if val is not None:
            return abs(float(val))
    return None
