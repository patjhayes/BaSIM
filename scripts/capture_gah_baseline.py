"""Capture deterministic parity fixtures from a pinned GAH-3D checkout."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "gah_baseline"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")


async def _capture_design(request_payload: dict[str, Any]) -> dict[str, Any]:
    from soakhydro.web.api import SimulationRequest, simulate

    response = await simulate(SimulationRequest.model_validate(request_payload), _user={})
    result: dict[str, Any] | None = None
    async for chunk in response.body_iterator:
        event = json.loads(chunk)
        if event["type"] == "error":
            raise RuntimeError(event["message"])
        if event["type"] == "complete":
            result = event["result"]

    if result is None:
        raise RuntimeError("GAH design stream ended without a complete event")
    return result


def _capture_clogging(request_payload: dict[str, Any]) -> dict[str, Any]:
    from soakhydro.web.api import CloggingAnalysisRequest, _run_clogging_analysis

    request = CloggingAnalysisRequest.model_validate(request_payload)
    return _run_clogging_analysis(request).model_dump(mode="json")


def _summary(
    source_commit: str,
    design_result: dict[str, Any],
    clogging_result: dict[str, Any],
) -> dict[str, Any]:
    design_run = design_result["model_runs"][0]
    return {
        "gah_source_commit": source_commit,
        "design": {
            "runoff_rows": len(design_result["runoff_table"]),
            "hydrographs": len(design_result["hydrographs"]),
            "depth_summary": design_run["depth_summary"],
            "drawdown_summary": design_run["drawdown_summary"],
            "warnings": design_result["warnings"],
        },
        "clogging": {
            "years": [
                {
                    "year": item["year"],
                    "k_cl_m_per_day": item["k_cl_m_per_day"],
                    "l_cl_m": item["l_cl_m"],
                    "peak_depth_m": item["peak_depth_m"],
                    "drain_time_hours": item["drain_time_hours"],
                    "spilled": item["spilled"],
                    "depth_summary": item["depth_summary"],
                    "drawdown_summary": item["drawdown_summary"],
                }
                for item in clogging_result["timeline"]
            ]
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gah-source",
        required=True,
        type=Path,
        help="Path to the pinned GAH-3D source checkout.",
    )
    args = parser.parse_args()

    source = args.gah_source.resolve()
    source_package = source / "src"
    if not (source_package / "soakhydro").is_dir():
        parser.error(f"No src/soakhydro package found under {source}")

    sys.path.insert(0, str(source_package))
    source_commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        text=True,
    ).strip()

    previous_cwd = Path.cwd()
    try:
        os.chdir(source)
        design_result = asyncio.run(
            _capture_design(_load_json(FIXTURE_DIR / "design_request.json"))
        )
        clogging_result = _capture_clogging(
            _load_json(FIXTURE_DIR / "clogging_request.json")
        )
    finally:
        os.chdir(previous_cwd)

    _write_json(FIXTURE_DIR / "design_result.json", design_result)
    _write_json(FIXTURE_DIR / "clogging_result.json", clogging_result)
    _write_json(
        FIXTURE_DIR / "baseline_summary.json",
        _summary(source_commit, design_result, clogging_result),
    )
    print(f"Captured GAH-3D baseline fixtures from {source_commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())