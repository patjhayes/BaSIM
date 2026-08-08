from __future__ import annotations

import logging
import json
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import requests

from ..models.common import AEP, Coordinate, DesignRainfall
from ..utils.cache import SimpleCache
from ..utils.paths import get_cache_dir

LOGGER = logging.getLogger(__name__)

# ── Duration label → minutes lookup ──────────────────────────────────────
_DURATION_LABEL_TO_MINUTES: Dict[str, int] = {}
for _m in [1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 45]:
    _DURATION_LABEL_TO_MINUTES[f"{_m} min"] = _m
for _h_val, _h_min in [
    (1, 60), (1.5, 90), (2, 120), (3, 180), (4.5, 270),
    (6, 360), (9, 540), (12, 720), (18, 1080), (24, 1440),
    (30, 1800), (36, 2160), (48, 2880), (72, 4320),
    (96, 5760), (120, 7200), (144, 8640), (168, 10080),
]:
    label = f"{_h_val:g} hour" if _h_val != int(_h_val) else f"{int(_h_val)} hour"
    _DURATION_LABEL_TO_MINUTES[label] = _h_min

# ── AEP header → percent lookup ─────────────────────────────────────────
_AEP_HEADER_TO_PERCENT: Dict[str, float] = {
    "63.2%": 63.2, "50%": 50.0, "50%#": 50.0,
    "20%": 20.0, "20%*": 20.0,
    "10%": 10.0, "5%": 5.0, "2%": 2.0, "1%": 1.0,
}


class BoMIFDClient:
    """Client for Bureau of Meteorology revised IFD datasets.

    Scrapes the BOM Design Rainfall Data System (2016) HTML page to
    extract IFD depth and intensity tables.
    """

    _BOM_IFD_URL = "http://www.bom.gov.au/water/designRainfalls/revised-ifd/"

    def __init__(
        self,
        cache: SimpleCache | None = None,
        base_url: str = "http://www.bom.gov.au/water/designRainfalls/revised-ifd/",
        timeout_seconds: float = 30.0,
        local_dataset: str | Path | None = None,
        local_dataset_env: str = "SOAKSIM_BOM_IFD_JSON",
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.cache = cache or SimpleCache(get_cache_dir() / "bom")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        env_path = os.environ.get(local_dataset_env)
        chosen_path = Path(local_dataset).expanduser() if local_dataset else None
        if not chosen_path and env_path:
            chosen_path = Path(env_path).expanduser()
        self._local_dataset = chosen_path
        self._local_payload: Dict[str, object] | None = None

    def _cache_key(
        self, coordinate: Coordinate, durations: Sequence[int], ae_ps: Sequence[AEP]
    ) -> str:
        durations_key = ",".join(map(str, sorted(durations)))
        ae_ps_key = ",".join(f"{a.value}" for a in sorted(ae_ps, key=lambda a: a.value))
        return f"ifd|{coordinate.latitude:.5f}|{coordinate.longitude:.5f}|{durations_key}|{ae_ps_key}"

    def fetch_ifd(
        self,
        coordinate: Coordinate,
        durations: Sequence[int],
        ae_ps: Sequence[AEP],
        use_cache: bool = True,
    ) -> List[DesignRainfall]:
        key = self._cache_key(coordinate, durations, ae_ps)
        if use_cache:
            cached = self.cache.load(key)
            if cached is not None:
                return self._parse_response(cached)
        if self._local_dataset is not None:
            payload = self._load_from_local_dataset(durations, ae_ps)
        else:
            payload = self._download(coordinate, durations, ae_ps)
        if use_cache:
            self.cache.save(key, payload)
        return self._parse_response(payload)

    def _load_from_local_dataset(
        self, durations: Sequence[int], ae_ps: Sequence[AEP]
    ) -> Dict[str, object]:
        if self._local_dataset is None:
            raise RuntimeError("Local BoM dataset path not configured")
        if not self._local_dataset.exists():
            raise FileNotFoundError(
                f"Configured BoM dataset path does not exist: {self._local_dataset}"
            )
        if self._local_payload is None:
            LOGGER.info("Loading BoM IFD data from %s", self._local_dataset)
            with self._local_dataset.open("r", encoding="utf-8") as handle:
                self._local_payload = json.load(handle)
        records = self._local_payload.get("ifd", [])  # type: ignore[assignment]
        if not isinstance(records, list):
            raise ValueError("Local BoM dataset must contain an 'ifd' list")
        duration_filter = {int(d) for d in durations}
        aep_filter = {float(a.value) for a in ae_ps}
        filtered = [
            item
            for item in records
            if int(float(item.get("duration_minutes", 0))) in duration_filter
            and float(item.get("aep_percent", 0.0)) in aep_filter
        ]
        if not filtered:
            LOGGER.warning(
                "No matching design rainfalls found in local dataset for requested durations/AEPs"
            )
        return {"ifd": filtered}

    def _download(
        self,
        coordinate: Coordinate,
        durations: Sequence[int],
        ae_ps: Sequence[AEP],
    ) -> Dict[str, object]:
        """Fetch IFD data by scraping the BOM Design Rainfall HTML page."""
        params = {
            "coordinate_type": "dd",
            "latitude": str(coordinate.latitude),
            "longitude": str(coordinate.longitude),
            "user_label": "",
            "design": "ifds",
            "sdmin": "true",
            "sdhr": "true",
            "sdday": "true",
            "nsd[]": "",
            "nsdunit[]": "m",
            "values": "depths",
            "update": "",
        }
        LOGGER.info(
            "Fetching BOM IFD data for (%.5f, %.5f)",
            coordinate.latitude,
            coordinate.longitude,
        )
        response = self._session.get(
            self.base_url, params=params, timeout=self.timeout_seconds
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"BoM IFD request failed with status {response.status_code}"
            )
        html = response.text
        return self._parse_html_tables(html)

    # ── HTML table parser ────────────────────────────────────────────────

    @staticmethod
    def _parse_html_tables(html: str) -> Dict[str, object]:
        """Extract IFD depth and intensity data from the BOM HTML page.

        The page contains (at least) two relevant ``<table>`` elements:
        1. Depths (mm) — durations in rows, AEPs in columns
        2. Intensities (mm/hr) — same layout

        We parse both and merge them into an ``{"ifd": [...]}`` payload
        compatible with ``_parse_response``.
        """
        tables = re.findall(r"<table[^>]*>(.*?)</table>", html, re.DOTALL)

        depth_table: List[List[str]] | None = None
        intensity_table: List[List[str]] | None = None

        for table_html in tables:
            rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
            if len(rows_html) < 3:
                continue
            rows: List[List[str]] = []
            for rh in rows_html:
                cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rh, re.DOTALL)
                clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
                rows.append(clean)

            # Identify the table by its header row
            header_row = None
            for r in rows:
                if "Duration" in r and any("%" in c for c in r):
                    header_row = r
                    break
            if header_row is None:
                continue

            # Check if first data row values look like depths (>1) or
            # intensities (could be >100 for short durations).
            # Depths table: "1 min" row has values ~1-10
            # Intensity table: "1 min" row has values ~100-400
            data_start = rows.index(header_row) + 1
            if data_start >= len(rows):
                continue
            first_data = rows[data_start]
            if len(first_data) < 2:
                continue
            try:
                first_val = float(first_data[1])
            except ValueError:
                continue

            if depth_table is None and first_val < 50:
                depth_table = rows
            elif intensity_table is None and first_val >= 50:
                intensity_table = rows

        if depth_table is None:
            raise RuntimeError(
                "Could not locate the IFD depth table in the BOM response"
            )

        # Parse depth table
        records = BoMIFDClient._extract_records_from_rows(
            depth_table, value_key="depth_mm"
        )

        # Parse intensity table and merge if available
        if intensity_table is not None:
            intensity_records = BoMIFDClient._extract_records_from_rows(
                intensity_table, value_key="intensity_mm_per_hr"
            )
            # Build lookup for fast merge
            int_lookup: Dict[tuple, float] = {}
            for rec in intensity_records:
                int_lookup[
                    (rec["aep_percent"], rec["duration_minutes"])
                ] = rec["intensity_mm_per_hr"]

            for rec in records:
                key = (rec["aep_percent"], rec["duration_minutes"])
                if key in int_lookup:
                    rec["intensity_mm_per_hr"] = int_lookup[key]
                else:
                    # Compute from depth
                    dur_hr = rec["duration_minutes"] / 60.0
                    rec["intensity_mm_per_hr"] = round(
                        rec["depth_mm"] / dur_hr, 1
                    ) if dur_hr > 0 else 0.0
        else:
            # Compute intensities from depths
            for rec in records:
                dur_hr = rec["duration_minutes"] / 60.0
                rec["intensity_mm_per_hr"] = round(
                    rec["depth_mm"] / dur_hr, 1
                ) if dur_hr > 0 else 0.0

        return {"ifd": records}

    @staticmethod
    def _extract_records_from_rows(
        rows: List[List[str]], value_key: str
    ) -> List[Dict[str, object]]:
        """Parse a duration × AEP table into a flat list of records."""
        # Find header row
        header_row: List[str] | None = None
        header_idx = 0
        for i, r in enumerate(rows):
            if "Duration" in r and any("%" in c for c in r):
                header_row = r
                header_idx = i
                break
        if header_row is None:
            return []

        # Map column indices to AEP percentages
        col_aeps: List[tuple[int, float]] = []
        for j, cell in enumerate(header_row):
            aep_pct = _AEP_HEADER_TO_PERCENT.get(cell)
            if aep_pct is not None:
                col_aeps.append((j, aep_pct))

        records: List[Dict[str, object]] = []
        for row in rows[header_idx + 1:]:
            if not row:
                continue
            label = row[0].strip()
            dur_min = _DURATION_LABEL_TO_MINUTES.get(label)
            if dur_min is None:
                continue  # skip winter factor rows etc
            for col_idx, aep_pct in col_aeps:
                if col_idx >= len(row):
                    continue
                val_str = row[col_idx].strip()
                if val_str in ("-", ""):
                    continue
                try:
                    value = float(val_str)
                except ValueError:
                    continue
                rec: Dict[str, object] = {
                    "aep_percent": aep_pct,
                    "duration_minutes": dur_min,
                    value_key: value,
                }
                records.append(rec)
        return records

    def _parse_response(self, payload: Dict[str, object]) -> List[DesignRainfall]:
        records = payload.get("ifd", [])
        if not isinstance(records, list):
            raise ValueError("Unexpected BoM IFD payload format")
        results: List[DesignRainfall] = []
        for item in records:
            duration = float(item["duration_minutes"])
            aep = AEP.from_percent(float(item["aep_percent"]))
            depth_mm = float(item.get("depth_mm", item.get("depth", 0.0)))
            intensity = float(item.get("intensity_mm_per_hr", item.get("intensity", 0.0)))
            results.append(
                DesignRainfall(
                    duration_minutes=int(duration),
                    aep=aep,
                    depth_mm=depth_mm,
                    intensity_mm_per_hr=intensity,
                )
            )
        return results
