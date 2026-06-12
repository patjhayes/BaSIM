from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from collections import defaultdict
from itertools import accumulate
from typing import Dict, List, Sequence
from urllib.parse import urljoin

import requests

from ..models.common import AEP, Coordinate, TemporalPattern
from ..utils.cache import SimpleCache
from ..utils.paths import get_cache_dir

LOGGER = logging.getLogger(__name__)


class ARRTemporalPatternClient:
    """Client that scrapes ARR Datahub for temporal patterns."""

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
        self._session.headers.update({"User-Agent": "SoakSIM/0.1"})

    def _make_cache_key(
        self, coordinate: Coordinate, durations: Sequence[int], ae_ps: Sequence[AEP]
    ) -> str:
        durations_key = ",".join(map(str, sorted(set(int(d) for d in durations))))
        aep_key = ",".join(f"{a.value}" for a in sorted(ae_ps, key=lambda a: a.value))
        return (
            f"temporal_patterns|{coordinate.latitude:.5f}|{coordinate.longitude:.5f}|"
            f"{durations_key}|{aep_key}"
        )

    def fetch_temporal_patterns(
        self,
        coordinate: Coordinate,
        durations: Sequence[int],
        ae_ps: Sequence[AEP],
        use_cache: bool = True,
    ) -> Dict[tuple, List[TemporalPattern]]:
        key = self._make_cache_key(coordinate, durations, ae_ps)
        if use_cache:
            cached = self.cache.load(key)
            if cached is not None:
                return self._parse_payload(cached)

        payload = self._download_payload(coordinate, durations, ae_ps)
        if use_cache:
            self.cache.save(key, payload)
        return self._parse_payload(payload)

    def _download_payload(
        self,
        coordinate: Coordinate,
        durations: Sequence[int],
        ae_ps: Sequence[AEP],
    ) -> Dict[str, object]:
        html = self._request_result_page(coordinate)
        zip_bytes = self._download_zip_bundle(html)
        return self._extract_patterns(zip_bytes, durations, ae_ps)

    def fetch_climate_factors(
        self,
        coordinate: Coordinate,
        use_cache: bool = True,
    ) -> Dict[str, object]:
        """Fetches and parses the Climate Change Factors [CCF] from the ARR Datahub."""
        key = f"climate_factors_v2|{coordinate.latitude:.5f}|{coordinate.longitude:.5f}"
        if use_cache:
            cached = self.cache.load(key)
            if cached is not None:
                return cached

        html = self._request_result_page(coordinate, climate_change=True)
        
        # Extract text file download link
        match = re.search(r"downloads/[a-zA-Z0-9-]+\.txt", html)
        if not match:
            raise RuntimeError("Unable to locate text file download link in ARR response for CCF.")
        
        txt_url = urljoin(f"{self.base_url}/", match.group(0))
        response = self._session.get(txt_url, timeout=self.timeout_seconds)
        if response.status_code != 200:
            raise RuntimeError("Failed to download ARR Datahub text file.")
            
        lines = response.text.splitlines()
        try:
            start_idx = lines.index("[CCF]")
            end_idx = lines.index("[END_CCF]", start_idx) if "[END_CCF]" in lines[start_idx:] else len(lines)
            ccf_lines = lines[start_idx+1:end_idx]
        except ValueError:
            raise RuntimeError("Could not find [CCF] section in the ARR Datahub text file.")

        # Duration mapping from text columns to minute equivalents
        # <1 hour is mapped to common sub-hour durations: 10, 15, 20, 30, 45, 60
        duration_map = {
            "<1 hour": ["10", "15", "20", "30", "45", "60"],
            "1.5 Hours": ["90"],
            "2 Hours": ["120"],
            "3 Hours": ["180"],
            "4.5 Hours": ["270"],
            "6 Hours": ["360"],
            "9 Hours": ["540"],
            "12 Hours": ["720"],
            "18 Hours": ["1080"],
            ">24 Hours": ["1440", "2880", "4320", "7200"]
        }

        ccf_data = {}
        current_ssp = None
        current_cols = []

        for line in ccf_lines:
            line = line.strip()
            if not line:
                continue
            
            if line.startswith("[SSP"):
                current_ssp = line.replace("[", "").replace("]", "").strip()
                ccf_data[current_ssp] = {}
            elif line.startswith("[END_SSP"):
                current_ssp = None
            elif current_ssp:
                parts = [p.strip() for p in line.split(",")]
                if parts[0] == "":
                    # This is the header row
                    current_cols = parts[1:]
                else:
                    # This is a data row: year, val1, val2...
                    year = parts[0]
                    ccf_data[current_ssp][year] = {}
                    for col_name, val_str in zip(current_cols, parts[1:]):
                        try:
                            val = float(val_str)
                            # Map this col_name to all minutes
                            for minutes in duration_map.get(col_name, []):
                                ccf_data[current_ssp][year][minutes] = val
                        except ValueError:
                            pass
                            
        result = {
            "parsed": ccf_data,
            "raw_txt": response.text
        }
        if use_cache:
            self.cache.save(key, result)
        return result

    def _request_result_page(self, coordinate: Coordinate, climate_change: bool = False) -> str:
        data = {
            "lon_coord": f"{coordinate.longitude:.6f}",
            "lat_coord": f"{coordinate.latitude:.6f}",
            "TemporalPatterns": "on",
            "subButton": "Submit",
        }
        if climate_change:
            data["ClimateChange"] = "on"
            
        url = f"{self.base_url}/"
        response = self._session.post(url, data=data, timeout=self.timeout_seconds)
        if response.status_code != 200:
            raise RuntimeError(
                "ARR Datahub request failed with status "
                f"{response.status_code}: {response.text[:200]}"
            )
        return response.text

    def _download_zip_bundle(self, html: str) -> bytes:
        match = re.search(r"static/temporal_patterns/[^\"]+\.zip", html)
        if not match:
            raise RuntimeError("Unable to locate temporal pattern ZIP link in ARR response")
        zip_url = urljoin(f"{self.base_url}/", match.group(0))
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
                # Find best target AEP from window candidates that user requested
                candidates = self._WINDOW_AEP_CANDIDATES.get(event["aep_window"], [])
                matched = [c for c in candidates if c in target_set]
                if not matched:
                    continue
                closest = min(matched, key=lambda val: abs(val - event["aep_percent"]))
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
    client = ARRTemporalPatternClient(cache=SimpleCache(get_cache_dir() / "tmp"))
    return client._parse_payload(sample_payload)
