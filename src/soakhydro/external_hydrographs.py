"""Validation and normalization for user-supplied basin inflow hydrographs."""

from __future__ import annotations

import csv
import io
import math
import re
from typing import Any

from .models.common import AEP
from .models.results import HydrographResult


_DURATION_PATTERN = re.compile(r"(?<![A-Za-z0-9])0*([1-9][0-9]*)([mMhH])(?![A-Za-z0-9])")
_MAX_ROWS = 100_000


def duration_from_filename(filename: str) -> int:
    """Return the one required duration token in a custom hydrograph filename."""
    matches = list(_DURATION_PATTERN.finditer(filename))
    if len(matches) != 1:
        raise ValueError(
            "Filename must contain exactly one positive duration token such as 0030m or 24h."
        )
    value = int(matches[0].group(1))
    return value * 60 if matches[0].group(2).lower() == "h" else value


def _decode(content: bytes) -> str:
    if not content or b"\0" in content:
        raise ValueError("File must be non-empty text data.")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("File must be UTF-8 encoded text.") from exc


def _normalise(
    filename: str,
    time_values: list[float],
    flow_values: list[float],
    *,
    time_unit: str,
    flow_unit: str,
    source_format: str,
    flow_column: str,
) -> dict[str, Any]:
    if len(time_values) < 2:
        raise ValueError("Hydrograph must contain at least two time-flow records.")
    if len(time_values) > _MAX_ROWS:
        raise ValueError(f"Hydrograph exceeds the {_MAX_ROWS:,}-row limit.")
    if time_unit not in {"minutes", "hours"}:
        raise ValueError("Time unit must be minutes or hours.")
    if flow_unit not in {"m3/s", "L/s"}:
        raise ValueError("Flow unit must be m3/s or L/s.")
    if any(not math.isfinite(value) for value in time_values + flow_values):
        raise ValueError("Hydrograph values must be finite numbers.")

    time_minutes = [value * 60.0 if time_unit == "hours" else value for value in time_values]
    discharge_cms = [value / 1_000.0 if flow_unit == "L/s" else value for value in flow_values]
    if time_minutes[0] != 0.0:
        raise ValueError("Hydrograph time must start at 0.")
    if any(value < 0.0 for value in discharge_cms):
        raise ValueError("Hydrograph flow cannot be negative.")

    intervals = [later - earlier for earlier, later in zip(time_minutes, time_minutes[1:])]
    if any(interval <= 0.0 for interval in intervals):
        raise ValueError("Hydrograph time values must be strictly increasing.")
    timestep_minutes = intervals[0]
    tolerance = max(1e-9, timestep_minutes * 1e-6)
    if any(abs(interval - timestep_minutes) > tolerance for interval in intervals[1:]):
        raise ValueError("Hydrograph time intervals must be evenly spaced.")

    duration_minutes = duration_from_filename(filename)
    volume_m3 = sum(
        flow * timestep_minutes * 60.0 for flow in discharge_cms
    )
    return {
        "filename": filename,
        "duration_minutes": duration_minutes,
        "timestep_minutes": timestep_minutes,
        "time_minutes": time_minutes,
        "discharge_cms": discharge_cms,
        "source_format": source_format,
        "flow_column": flow_column,
        "point_count": len(time_minutes),
        "peak_discharge_cms": max(discharge_cms),
        "volume_m3": volume_m3,
    }


def parse_csv_hydrograph(
    filename: str,
    content: bytes,
    *,
    time_column: str,
    flow_column: str,
    time_unit: str,
    flow_unit: str,
) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(_decode(content)))
    if not reader.fieldnames or time_column not in reader.fieldnames or flow_column not in reader.fieldnames:
        raise ValueError("Select valid time and flow columns from the CSV file.")
    time_values: list[float] = []
    flow_values: list[float] = []
    for row_number, row in enumerate(reader, start=2):
        try:
            time_values.append(float(row[time_column]))
            flow_values.append(float(row[flow_column]))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"CSV row {row_number} has an invalid time or flow value.") from exc
    return _normalise(
        filename,
        time_values,
        flow_values,
        time_unit=time_unit,
        flow_unit=flow_unit,
        source_format="csv",
        flow_column=flow_column,
    )


def _unit_from_time_header(header: str) -> str:
    lower = header.lower()
    if any(unit in lower for unit in ("hour", " hr", "(hr", "(h")):
        return "hours"
    if any(unit in lower for unit in ("min", "(m")):
        return "minutes"
    raise ValueError("TS1 time header must declare minutes or hours.")


def _unit_from_flow_header(header: str) -> str:
    lower = header.lower().replace(" ", "")
    if "l/s" in lower or "lps" in lower:
        return "L/s"
    return "m3/s"


def parse_ts1_hydrograph(
    filename: str,
    content: bytes,
    *,
    flow_column: str | None = None,
) -> dict[str, Any]:
    lines = _decode(content).splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.search(r"\btime\s*\([^)]*\)", line, flags=re.IGNORECASE)
            and ("," in line or "\t" in line)
        ),
        None,
    )
    if header_index is None:
        raise ValueError("TS1 header row not found; expected a 'Time (...)' column.")
    delimiter = "\t" if "\t" in lines[header_index] else ","
    headers = next(csv.reader([lines[header_index]], delimiter=delimiter))
    headers = [header.strip() for header in headers]
    if len(headers) < 2:
        raise ValueError("TS1 file must include time and at least one flow column.")
    candidate_columns = [header for header in headers[1:] if header]
    if flow_column is None:
        if len(candidate_columns) != 1:
            raise ValueError("TS1 file has multiple flow columns; select one flow series.")
        flow_column = candidate_columns[0]
    if flow_column not in candidate_columns:
        if len(candidate_columns) == 1:
            flow_column = candidate_columns[0]
        else:
            raise ValueError("Select a valid TS1 flow column.")
    flow_index = headers.index(flow_column)

    time_values: list[float] = []
    flow_values: list[float] = []
    for row_number, line in enumerate(lines[header_index + 1 :], start=header_index + 2):
        if not line.strip() or line.lstrip().startswith("!"):
            continue
        row = next(csv.reader([line], delimiter=delimiter))
        if len(row) <= flow_index:
            raise ValueError(f"TS1 row {row_number} is missing the selected flow value.")
        try:
            time_values.append(float(row[0].strip()))
            flow_values.append(float(row[flow_index].strip()))
        except ValueError as exc:
            raise ValueError(f"TS1 row {row_number} has an invalid time or flow value.") from exc
    return _normalise(
        filename,
        time_values,
        flow_values,
        time_unit=_unit_from_time_header(headers[0]),
        flow_unit=_unit_from_flow_header(flow_column),
        source_format="ts1",
        flow_column=flow_column,
    )


def parse_external_hydrograph(
    filename: str,
    content: bytes,
    *,
    time_column: str | None = None,
    flow_column: str | None = None,
    time_unit: str | None = None,
    flow_unit: str | None = None,
) -> dict[str, Any]:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "csv":
        if not all((time_column, flow_column, time_unit, flow_unit)):
            raise ValueError("CSV uploads require time column, flow column, time unit, and flow unit.")
        return parse_csv_hydrograph(
            filename,
            content,
            time_column=time_column,
            flow_column=flow_column,
            time_unit=time_unit,
            flow_unit=flow_unit,
        )
    if suffix == "ts1":
        return parse_ts1_hydrograph(filename, content, flow_column=flow_column)
    raise ValueError("Only .csv and .ts1 hydrograph files are supported.")


def hydrograph_result_from_external(
    hydrograph: dict[str, Any],
    event_index: int,
) -> HydrographResult:
    """Construct the routing engine's native hydrograph model from normalized JSON."""
    discharge = [float(value) for value in hydrograph["discharge_cms"]]
    timestep_minutes = float(hydrograph["timestep_minutes"])
    peak_index = discharge.index(max(discharge))
    return HydrographResult(
        aep=AEP.AEP_5,
        duration_minutes=int(hydrograph["duration_minutes"]),
        pattern_rank=event_index + 1,
        discharge_cms=discharge,
        timestep_minutes=timestep_minutes,
        peak_discharge_cms=max(discharge),
        runoff_volume_m3=sum(value * timestep_minutes * 60.0 for value in discharge),
        time_to_peak_minutes=peak_index * timestep_minutes,
    )
