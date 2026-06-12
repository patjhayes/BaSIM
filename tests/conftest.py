"""Shared fixtures for BaSIM UZF+MVR integration tests."""
import json
import os
import re
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------
def pytest_configure(config):
    config.addinivalue_line("markers", "slow: runs MODFLOW 6 (may take 10-60s)")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def project_root():
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def ts1_short(project_root):
    """A short-duration TS1 file for fast tests."""
    p = project_root / "model_input" / "ts1_files" / "test_ aep6EY_du1hour.out.ts1"
    if p.exists():
        return str(p)
    # Fallback: any TS1 file in ts1_files
    d = project_root / "model_input" / "ts1_files"
    if d.exists():
        for f in sorted(d.glob("*.ts1")):
            return str(f)
    pytest.skip("No TS1 file available")


@pytest.fixture(scope="session")
def ts1_1pct(project_root):
    """1% AEP 1-hour burst TS1 for deep-GW validation."""
    p = project_root / "External" / "OUTPUT" / "cat1_Catchments_1%AEP_1hourBurst.ts1"
    if p.exists():
        return str(p)
    # Fall back to any TS1
    return None


@pytest.fixture(scope="session")
def dem_path(project_root):
    """Path to EXAMPLE.dem if available."""
    p = project_root / "Elevation Data" / "EXAMPLE.dem"
    if p.exists():
        return str(p)
    return None


# ---------------------------------------------------------------------------
# Config Factory
# ---------------------------------------------------------------------------
@pytest.fixture
def make_config(tmp_path):
    """Factory fixture returning a config dict builder.

    Usage:
        cfg = make_config(floor_elev=50, initial_head=0, k_mpd=50)
    """
    def _build(
        *,
        floor_elev=5.0,
        length=50.0,
        width=30.0,
        depth=3.0,
        slope=3.0,
        k_mpd=5.0,
        kh_mpd=None,
        ss=1e-5,
        sy=0.10,
        initial_head=4.0,
        bottom_elev=-5.0,
        bed_thickness=0.5,
        bed_k_mpd=None,
        side_k_mpd=None,
        mode="vertical",
        post_storm_days=0.5,
        post_storm_step_hours=1.0,
        uzf=None,
        source="manual",
        dem_file=None,
        crest_elev=None,
    ):
        if bed_k_mpd is None:
            bed_k_mpd = k_mpd
        if kh_mpd is None:
            kh_mpd = k_mpd
        if side_k_mpd is None:
            side_k_mpd = 0.0 if mode == "vertical" else bed_k_mpd

        bg = {
            "source": source,
            "length_floor": length,
            "width_floor": width,
            "max_depth": depth,
            "side_slope_hv": slope,
            "floor_elev": floor_elev,
        }
        if source == "dem" and dem_file:
            bg["dem_file"] = dem_file
            bg["crest_elev"] = crest_elev or (floor_elev + depth)
            bg["min_cell_size_m"] = 5.0

        aq = {
            "k_horizontal_mpd": kh_mpd,
            "k_vertical_mpd": k_mpd,
            "ss": ss,
            "sy": sy,
            "initial_head": initial_head,
        }
        if bottom_elev is not None:
            aq["bottom_elev"] = bottom_elev

        cfg = {
            "scenario_title": "Test",
            "model_tag": "test",
            "analysis_mode": "detailed",
            "basin_geometry": bg,
            "aquifer": aq,
            "infiltration": {
                "mode": mode,
                "bed_thickness_m": bed_thickness,
                "bed_k_mpd": bed_k_mpd,
                "side_k_mpd": side_k_mpd,
                "side_k_separate": False,
            },
            "perf": {"mode": "fast", "min_cells_wide": 3},
            "post_storm_days": post_storm_days,
            "post_storm_step_hours": post_storm_step_hours,
            "lightweight_outputs": True,
            "cleanup_heavy": False,
            "output_dir": str(tmp_path / "output"),
        }
        if uzf is not None:
            cfg["uzf"] = uzf

        return cfg

    return _build


# ---------------------------------------------------------------------------
# Parsing Helpers (available as module-level functions)
# ---------------------------------------------------------------------------
def parse_mass_balance(model_dir: str | Path) -> float | None:
    """Extract worst percent discrepancy from mfsim.lst."""
    lst = Path(model_dir) / "mfsim.lst"
    if not lst.exists():
        return None
    text = lst.read_text(encoding="utf-8", errors="replace")
    vals = re.findall(r"PERCENT\s+DISCREPANCY\s*=\s*([-\d.eE+]+)", text, re.IGNORECASE)
    if not vals:
        return None
    return max(abs(float(v)) for v in vals)


def parse_peak_stage(model_dir: str | Path) -> float | None:
    """Read peak stage from the LAK stage CSV."""
    import csv
    model_dir = Path(model_dir)
    # Find *_lak_stage.csv
    for f in model_dir.glob("*_lak_stage.csv"):
        with open(f, newline="") as fh:
            reader = csv.DictReader(fh)
            stages = []
            for row in reader:
                for k, v in row.items():
                    if "stage" in k.lower():
                        try:
                            stages.append(float(v))
                        except (ValueError, TypeError):
                            pass
            if stages:
                return max(stages)
    return None


def parse_scenario_summary(model_dir: str | Path) -> dict | None:
    """Load scenario_summary.json from the output directory."""
    p = Path(model_dir) / "scenario_summary.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def count_uzf_cells(model_dir: str | Path) -> int:
    """Count PACKAGEDATA rows in the .uzf file."""
    model_dir = Path(model_dir)
    for f in model_dir.glob("*.uzf"):
        text = f.read_text(encoding="utf-8")
        in_pkg = False
        count = 0
        for line in text.splitlines():
            stripped = line.strip().upper()
            if stripped.startswith("BEGIN PACKAGEDATA"):
                in_pkg = True
                continue
            if stripped.startswith("END PACKAGEDATA"):
                break
            if in_pkg and stripped and not stripped.startswith("#"):
                count += 1
        return count
    return 0


def sum_mvr_fractions(model_dir: str | Path) -> float:
    """Sum FACTOR values from the first PERIOD block in the .mvr file."""
    model_dir = Path(model_dir)
    for f in model_dir.glob("*.mvr"):
        text = f.read_text(encoding="utf-8")
        in_period = False
        total = 0.0
        for line in text.splitlines():
            stripped = line.strip().upper()
            if stripped.startswith("BEGIN PERIOD"):
                in_period = True
                continue
            if stripped.startswith("END PERIOD"):
                break
            if in_period and stripped and not stripped.startswith("#"):
                parts = line.split()
                # Last token is the fraction value
                try:
                    total += float(parts[-1])
                except (ValueError, IndexError):
                    pass
        return total
    return 0.0


def lak_has_mover(model_dir: str | Path) -> bool:
    """Check if the .lak file has MOVER in its OPTIONS block."""
    model_dir = Path(model_dir)
    for f in model_dir.glob("*.lak"):
        text = f.read_text(encoding="utf-8")
        in_opts = False
        for line in text.splitlines():
            stripped = line.strip().upper()
            if stripped.startswith("BEGIN OPTIONS"):
                in_opts = True
                continue
            if stripped.startswith("END OPTIONS"):
                break
            if in_opts and "MOVER" in stripped:
                return True
    return False


def nam_has_packages(model_dir: str | Path) -> dict:
    """Check which packages appear in the .nam file."""
    model_dir = Path(model_dir)
    result = {"LAK6": False, "UZF6": False, "MVR6": False}
    for f in model_dir.glob("*.nam"):
        text = f.read_text(encoding="utf-8")
        for line in text.splitlines():
            for pkg in result:
                if pkg in line.upper():
                    result[pkg] = True
    return result
