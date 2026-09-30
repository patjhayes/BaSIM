from __future__ import annotations

from pathlib import Path

from soakhydro.models.common import AEP, Coordinate
from soakhydro.services.arr import ARRDataHubClient
from soakhydro.utils.cache import SimpleCache


def test_parse_ifd_table_loads_bundled_sample(tmp_path):
    import json

    sample_path = Path(__file__).resolve().parents[2] / "sample_data" / "arr_ifd.json"
    table = json.loads(sample_path.read_text(encoding="utf-8"))

    results = ARRDataHubClient._parse_ifd_table(
        table,
        durations=(30, 60),
        ae_ps=(AEP.AEP_10, AEP.AEP_5),
    )

    assert {(item.aep, item.duration_minutes) for item in results} == {
        (AEP.AEP_10, 30),
        (AEP.AEP_10, 60),
        (AEP.AEP_5, 30),
        (AEP.AEP_5, 60),
    }
    assert all(item.depth_mm > 0 for item in results)
    assert all(item.intensity_mm_per_hr > 0 for item in results)


def test_parse_ifd_table_ignores_unsupported_aep_columns():
    # The 2026 Data Hub schema includes extra AEP columns (e.g. 39.35%,
    # 18.13%) that are not part of BaSIM's supported AEP set; these must be
    # silently skipped rather than raising.
    table = {
        "index": [30, 60],
        "columns": [63.2, 39.35, 10.0, 18.13],
        "data": [
            [13.1, 16.0, 22.1, 21.0],
            [17.0, 20.0, 28.3, 27.0],
        ],
    }
    results = ARRDataHubClient._parse_ifd_table(
        table, durations=(30, 60), ae_ps=(AEP.AEP_10,)
    )
    assert {(item.aep, item.duration_minutes) for item in results} == {
        (AEP.AEP_10, 30),
        (AEP.AEP_10, 60),
    }


def test_fetch_design_rainfalls_uses_cached_layers(tmp_path, monkeypatch):
    cache = SimpleCache(tmp_path / "cache")
    client = ARRDataHubClient(cache=cache)
    coordinate = Coordinate(latitude=-31.9505, longitude=115.8605)

    layers = {
        "RecIFD": {
            "Default Current (2030) Baseline": {
                "index": [30, 60],
                "columns": [10.0, 5.0],
                "data": [[22.1, 25.3], [28.3, 32.5]],
            }
        }
    }
    cache.save(client._layers_cache_key(coordinate), layers)

    def _fail_download(*args, **kwargs):
        raise AssertionError("Should not hit the network when the layers cache is warm")

    monkeypatch.setattr(client, "_download_layers", _fail_download)

    results = client.fetch_design_rainfalls(
        coordinate, durations=(30, 60), ae_ps=(AEP.AEP_10, AEP.AEP_5)
    )
    assert len(results) == 4
