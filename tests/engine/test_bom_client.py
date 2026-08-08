from __future__ import annotations

from pathlib import Path

from soakhydro.models.common import AEP, Coordinate
from soakhydro.services.bom import BoMIFDClient
from soakhydro.utils.cache import SimpleCache


def test_bom_client_loads_local_dataset(tmp_path):
    sample_path = Path(__file__).resolve().parents[2] / "sample_data" / "bom_ifd.json"
    client = BoMIFDClient(
        cache=SimpleCache(tmp_path / "cache"),
        local_dataset=sample_path,
    )

    results = client.fetch_ifd(
        Coordinate(latitude=-31.95, longitude=115.86),
        durations=(30, 60),
        ae_ps=(AEP.AEP_10, AEP.AEP_5),
        use_cache=False,
    )

    assert {
        (item.aep, item.duration_minutes)
        for item in results
    } == {
        (AEP.AEP_10, 30),
        (AEP.AEP_10, 60),
        (AEP.AEP_5, 30),
        (AEP.AEP_5, 60),
    }
    assert all(item.depth_mm > 0 for item in results)
