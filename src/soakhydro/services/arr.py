from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from collections import defaultdict
from itertools import accumulate
from typing import Dict, List, Optional, Sequence, Tuple

import requests

from ..models.common import AEP, Coordinate, DesignRainfall, TemporalPattern
from ..utils.cache import SimpleCache
from ..utils.paths import get_cache_dir

LOGGER = logging.getLogger(__name__)

# Bumped whenever the cached payload shape changes, so stale HTML-era caches
# on disk are never reused.
_CACHE_SCHEMA_VERSION = "v2"

DEFAULT_IFD_BASELINE = "Default Current (2030) Baseline"

_SSP_LABELS = {
    "SSP1": "SSP1-2.6",
    "SSP2": "SSP2-4.5",
    "SSP3": "SSP3-7.0",
    "SSP5": "SSP5-8.5",
}

_CC_TABLE_LABEL_RE = re.compile(r"\((\d{4}) Baseline - SSP(\d)\)")


class ARRDataHubClient:
    """Client for the ARR Data Hub JSON API (data.arr-software.org).

    A single GET request returns the design rainfall (Default IFD) depths,
    the temporal pattern bundle location, and the climate-change-adjusted
    IFD tables for a coordinate, replacing the previous BOM IFD HTML scrape
    and the ARR HTML result-page scrape.
    """

    # Maps ARR AEP-window labels to candidate AEP values (ordered by priority)
    _WINDOW_AEP_CANDIDATES = {
        "frequent": [63.2, 50.0, 20.0, 10.0],
        "infrequent": [20.0, 10.0, 5.0],
        "intermediate": [10.0, 5.0, 2.0],
        "rare": [2.0, 1.0, 5.0],
        "very rare": [1.0, 2.0],
    }

    def __init__(
        self,
        cache: SimpleCache | None = None,
        base_url: str = "https://data.arr-software.org",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.cache = cache or SimpleCache(get_cache_dir() / "arr")
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "BaSIM/4.0"})

    # ── Shared layers payload (IFD + temporal pattern URL + CC-adjusted IFD) ──

    def _layers_cache_key(self, coordinate: Coordinate) -> str:
        return (
            f"{_CACHE_SCHEMA_VERSION}|layers|{coordinate.latitude:.5f}|"
            f"{coordinate.longitude:.5f}"
        )

    def _fetch_layers(self, coordinate: Coordinate, use_cache: bool = True) -> Dict[str, object]:
        key = self._layers_cache_key(coordinate)
        if use_cache:
            cached = self.cache.load(key)
            if cached is not None:
                return cached
        layers = self._download_layers(coordinate)
        if use_cache:
            self.cache.save(key, layers)
        return layers

    def _download_layers(self, coordinate: Coordinate) -> Dict[str, object]:
        params = {
            "lon_coord": f"{coordinate.longitude:.6f}",
            "lat_coord": f"{coordinate.latitude:.6f}",
            "type": "json",
            "TemporalPatterns": "1",
            "BoMIFD": "1",
            "CCAdjIFDDatasets": "1",
        }
        response = self._session.get(
            f"{self.base_url}/", params=params, timeout=self.timeout_seconds
        )
        if response.status_code != 200:
            raise RuntimeError(
                "ARR Data Hub request failed with status "
                f"{response.status_code}: {response.text[:200]}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError("ARR Data Hub returned a non-JSON response") from exc
        layers = body.get("layers")
        if not isinstance(layers, dict):
            raise RuntimeError("ARR Data Hub response is missing the 'layers' object")
        return layers

    # ── Design rainfall (Default IFD depths) ─────────────────────────────

    def fetch_design_rainfalls(
        self,
        coordinate: Coordinate,
        durations: Sequence[int],
        ae_ps: Sequence[AEP],
        use_cache: bool = True,
        baseline: str = DEFAULT_IFD_BASELINE,
    ) -> List[DesignRainfall]:
        layers = self._fetch_layers(coordinate, use_cache=use_cache)
        rec_ifd = layers.get("RecIFD")
        if not isinstance(rec_ifd, dict) or baseline not in rec_ifd:
            raise RuntimeError(
                f"ARR Data Hub response is missing the Default IFD baseline '{baseline}'"
            )
        return self._parse_ifd_table(rec_ifd[baseline], durations, ae_ps)

    # ── Climate-change-adjusted IFD depths ────────────────────────────────

    def fetch_climate_adjusted_ifds(
        self,
        coordinate: Coordinate,
        durations: Sequence[int],
        ae_ps: Sequence[AEP],
        use_cache: bool = True,
    ) -> Dict[Tuple[str, int], List[DesignRainfall]]:
        layers = self._fetch_layers(coordinate, use_cache=use_cache)
        cc_tables = layers.get("CCAdjIFDDatasets")
        if not isinstance(cc_tables, dict):
            raise RuntimeError("ARR Data Hub response is missing the CCAdjIFDDatasets layer")
        result: Dict[Tuple[str, int], List[DesignRainfall]] = {}
        for label, table in cc_tables.items():
            parsed_label = self._parse_cc_table_label(label)
            if parsed_label is None:
                continue
            ssp, epoch = parsed_label
            result[(ssp, epoch)] = self._parse_ifd_table(table, durations, ae_ps)
        return result

    @staticmethod
    def _parse_cc_table_label(label: str) -> Optional[Tuple[str, int]]:
        match = _CC_TABLE_LABEL_RE.search(label)
        if not match:
            return None
        epoch = int(match.group(1))
        ssp = _SSP_LABELS.get(f"SSP{match.group(2)}")
        if ssp is None:
            return None
        return ssp, epoch

    @staticmethod
    def _parse_ifd_table(
        table: object,
        durations: Sequence[int],
        ae_ps: Sequence[AEP],
    ) -> List[DesignRainfall]:
        """Parse a Data Hub {index, columns, data} IFD matrix.

        ``index`` holds durations in minutes, ``columns`` holds AEP percent
        values, and ``data`` is a duration x AEP depth matrix (mm).
        """
        if not isinstance(table, dict):
            raise RuntimeError("Malformed ARR Data Hub IFD table")
        index = table.get("index")
        columns = table.get("columns")
        data = table.get("data")
        if not isinstance(index, list) or not isinstance(columns, list) or not isinstance(data, list):
            raise RuntimeError("Malformed ARR Data Hub IFD table")

        duration_filter = {int(d) for d in durations}
        aep_filter = {float(a.value) for a in ae_ps}

        results: List[DesignRainfall] = []
        for row_idx, duration_raw in enumerate(index):
            try:
                duration_minutes = int(round(float(duration_raw)))
            except (TypeError, ValueError):
                continue
            if duration_filter and duration_minutes not in duration_filter:
                continue
            if row_idx >= len(data) or not isinstance(data[row_idx], list):
                continue
            row = data[row_idx]
            for col_idx, aep_raw in enumerate(columns):
                try:
                    aep_percent = float(aep_raw)
                except (TypeError, ValueError):
                    continue
                if aep_filter and aep_percent not in aep_filter:
                    continue
                try:
                    aep_enum = AEP.from_percent(aep_percent)
                except ValueError:
                    continue
                if col_idx >= len(row):
                    continue
                try:
                    depth_mm = float(row[col_idx])
                except (TypeError, ValueError):
                    continue
                duration_hr = duration_minutes / 60.0
                intensity = round(depth_mm / duration_hr, 2) if duration_hr > 0 else 0.0
                results.append(
                    DesignRainfall(
                        duration_minutes=duration_minutes,
                        aep=aep_enum,
                        depth_mm=depth_mm,
                        intensity_mm_per_hr=intensity,
                    )
                )
        return results

    # ── Temporal patterns ──────────────────────────────────────────────

    def _make_pattern_cache_key(
        self, coordinate: Coordinate, durations: Sequence[int], ae_ps: Sequence[AEP]
    ) -> str:
        durations_key = ",".join(map(str, sorted(set(int(d) for d in durations))))
        aep_key = ",".join(f"{a.value}" for a in sorted(ae_ps, key=lambda a: a.value))
        return (
            f"{_CACHE_SCHEMA_VERSION}|temporal_patterns|{coordinate.latitude:.5f}|"
            f"{coordinate.longitude:.5f}|{durations_key}|{aep_key}"
        )

    def fetch_temporal_patterns(
        self,
        coordinate: Coordinate,
        durations: Sequence[int],
        ae_ps: Sequence[AEP],
        use_cache: bool = True,
    ) -> Dict[tuple, List[TemporalPattern]]:
        key = self._make_pattern_cache_key(coordinate, durations, ae_ps)
        if use_cache:
            cached = self.cache.load(key)
            if cached is not None:
                return self._parse_payload(cached)

        payload = self._download_pattern_payload(coordinate, durations, ae_ps, use_cache=use_cache)
        if use_cache:
            self.cache.save(key, payload)
        return self._parse_payload(payload)

    def _download_pattern_payload(
        self,
        coordinate: Coordinate,
        durations: Sequence[int],
        ae_ps: Sequence[AEP],
        use_cache: bool = True,
    ) -> Dict[str, object]:
        layers = self._fetch_layers(coordinate, use_cache=use_cache)
        point_tp = layers.get("PointTP")
        if not isinstance(point_tp, dict) or not point_tp.get("url"):
            raise RuntimeError("ARR Data Hub response is missing the PointTP temporal pattern layer")
        zip_bytes = self._download_zip(str(point_tp["url"]))
        return self._extract_patterns(zip_bytes, durations, ae_ps)

    def _download_zip(self, zip_url: str) -> bytes:
        response = self._session.get(zip_url, timeout=self.timeout_seconds)
        if response.status_code != 200:
            raise RuntimeError(
                "ARR temporal pattern ZIP download failed with status "
                f"{response.status_code}: {response.text[:200]}"
            )
        return response.content

    def _extract_patterns(
        self,
        zip_bytes: bytes,
        durations: Sequence[int],
        ae_ps: Sequence[AEP],
    ) -> Dict[str, object]:
        durations_filter = {int(d) for d in durations}
        target_values = sorted({a.value for a in ae_ps})
        patterns: List[Dict[str, object]] = []

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            stats_name = self._find_member(archive, suffix="_AllStats.csv")
            increments_name = self._find_member(archive, suffix="_Increments.csv")
            stats_by_event = self._load_stats(archive.open(stats_name))
            events = self._load_events(
                archive.open(increments_name), durations_filter, stats_by_event
            )

        buckets: Dict[tuple[float, int], List[Dict[str, object]]] = defaultdict(list)
        target_set = set(target_values)
        for event in events:
            if not target_values:
                continue
            if event["aep_percent"] is not None:
                closest = min(target_values, key=lambda val: abs(val - event["aep_percent"]))
                diff = abs(event["aep_percent"] - closest)
            else:
                # Find best target AEP from window candidates that user requested
                candidates = self._WINDOW_AEP_CANDIDATES.get(event["aep_window"], [])
                matched = [c for c in candidates if c in target_set]
                if not matched:
                    continue
                closest = matched[0]
                diff = 0.0
            if closest not in target_set:
                continue
            event["target_aep"] = closest
            event["difference"] = diff
            buckets[(closest, event["duration"])].append(event)

        for (target_aep, duration), events_for_combo in buckets.items():
            events_for_combo.sort(
                key=lambda item: (item["difference"], item["aep_percent"] or float("inf"))
            )
            for rank, event in enumerate(events_for_combo[:10], start=1):
                metadata = dict(event["metadata"])
                metadata.update(
                    {
                        "assigned_aep_percent": target_aep,
                        "difference_from_target": event["difference"],
                    }
                )
                patterns.append(
                    {
                        "aep": target_aep,
                        "duration": duration,
                        "rank": rank,
                        "cumulative": event["cumulative"],
                        "metadata": metadata,
                    }
                )

        return {"patterns": patterns}

    def _find_member(self, archive: zipfile.ZipFile, suffix: str) -> str:
        for name in archive.namelist():
            if name.endswith(suffix):
                return name
        raise RuntimeError(
            f"Temporal pattern bundle missing required file matching {suffix}"
        )

    def _load_stats(self, file_obj: io.BufferedIOBase) -> Dict[str, Dict[str, object]]:
        stats: Dict[str, Dict[str, object]] = {}
        reader = csv.DictReader(io.TextIOWrapper(file_obj, "utf-8"))
        for row in reader:
            event_id = row.get("Event ID", "").strip()
            if not event_id:
                continue
            aep_raw = (row.get("AEP (source) (%)") or "").strip()
            try:
                aep_percent = float(aep_raw)
            except ValueError:
                aep_percent = None
            stats[event_id] = {
                "aep_percent": aep_percent,
                "region": (row.get("Region") or "").strip(),
                "burst_start": (row.get("Burst Start Date") or "").strip(),
                "burst_end": (row.get("Burst End Date") or "").strip(),
            }
        return stats

    def _load_events(
        self,
        file_obj: io.BufferedIOBase,
        durations_filter: set[int],
        stats_by_event: Dict[str, Dict[str, object]],
    ) -> List[Dict[str, object]]:
        reader = csv.reader(io.TextIOWrapper(file_obj, "utf-8"))
        next(reader, None)
        events: List[Dict[str, object]] = []
        for row in reader:
            if len(row) < 6:
                continue
            event_id = row[0].strip()
            try:
                duration = int(float(row[1].strip()))
            except ValueError:
                continue
            if durations_filter and duration not in durations_filter:
                continue
            try:
                timestep = float(row[2].strip())
            except ValueError:
                timestep = None
            aep_window = row[4].strip().lower()
            increments = [float(value) for value in row[5:] if value.strip()]
            if not increments:
                continue
            total = sum(increments)
            if total <= 0:
                continue
            cumulative = [value for value in accumulate((inc / total) for inc in increments)]
            cumulative[-1] = 1.0
            stat = stats_by_event.get(event_id, {})
            events.append(
                {
                    "event_id": event_id,
                    "duration": duration,
                    "timestep": timestep,
                    "aep_window": aep_window,
                    "aep_percent": stat.get("aep_percent"),
                    "cumulative": cumulative,
                    "metadata": {
                        "event_id": event_id,
                        "region": stat.get("region"),
                        "aep_window": aep_window,
                        "source_aep_percent": stat.get("aep_percent"),
                        "burst_start": stat.get("burst_start"),
                        "burst_end": stat.get("burst_end"),
                        "timestep_minutes": timestep,
                    },
                }
            )
        return events

    def _parse_payload(
        self, payload: Dict[str, object]
    ) -> Dict[tuple, List[TemporalPattern]]:
        patterns_data = payload.get("patterns")
        if patterns_data is None and "temporal_patterns" in payload:
            patterns_data = []
            records = payload.get("temporal_patterns", [])
            if not isinstance(records, list):
                raise ValueError("Invalid ARR payload: expected list under 'temporal_patterns'")
            for item in records:
                try:
                    duration = int(item["duration_minutes"])
                    aep_percent = float(item["aep_percent"])
                    fractions = [float(value) for value in item["cumulative_fractions"]]
                except (KeyError, TypeError, ValueError) as exc:
                    LOGGER.warning("Skipping malformed ARR legacy temporal pattern: %s", exc)
                    continue
                patterns_data.append(
                    {
                        "aep": aep_percent,
                        "duration": duration,
                        "rank": int(item.get("pattern_rank", item.get("rank", 1))),
                        "cumulative": fractions,
                        "metadata": {
                            "source": payload.get("source", "arr-datahub"),
                            "pattern_variant": item.get("pattern_variant", "standard"),
                        },
                    }
                )
        if not patterns_data:
            return {}
        grouped: Dict[tuple, List[TemporalPattern]] = {}
        for entry in patterns_data:
            try:
                aep_value = float(entry["aep"])
                duration = int(entry["duration"])
                rank = int(entry["rank"])
                cumulative = [float(value) for value in entry["cumulative"]]
                metadata = entry.get("metadata", {})
                aep_enum = AEP.from_percent(aep_value)
            except (KeyError, TypeError, ValueError) as exc:
                LOGGER.warning("Skipping malformed ARR temporal pattern entry: %s", exc)
                continue
            pattern = TemporalPattern(
                duration_minutes=duration,
                pattern_rank=rank,
                cumulative_fractions=cumulative,
                metadata=metadata,
            )
            try:
                pattern.validate()
            except ValueError as exc:
                LOGGER.warning("Discarding invalid temporal pattern: %s", exc)
                continue
            grouped.setdefault((aep_enum, duration), []).append(pattern)

        for patterns in grouped.values():
            patterns.sort(key=lambda p: p.pattern_rank)
        return grouped


def fetch_sample_temporal_patterns(sample_payload: Dict[str, object]) -> Dict[tuple, List[TemporalPattern]]:
    client = ARRDataHubClient(cache=SimpleCache(get_cache_dir() / "tmp"))
    return client._parse_payload(sample_payload)
