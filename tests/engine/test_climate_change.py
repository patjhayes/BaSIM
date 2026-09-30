from __future__ import annotations

from soakhydro.climate_change import apply_climate_change_factors
from soakhydro.models.common import AEP, Coordinate, DesignRainfall


class _FakeArrClient:
    """Stub returning a fixed live CC-adjusted-IFD response for the given SSP/epoch pairs."""

    def __init__(self, adjusted_by_key):
        self._adjusted_by_key = adjusted_by_key
        self.calls = 0

    def fetch_climate_adjusted_ifds(self, coordinate, durations, ae_ps, use_cache=True):
        self.calls += 1
        return self._adjusted_by_key


def _baseline() -> list[DesignRainfall]:
    return [
        DesignRainfall(duration_minutes=60, aep=AEP.AEP_10, depth_mm=28.3, intensity_mm_per_hr=28.3),
    ]


def test_apply_climate_change_factors_uses_live_data_when_available():
    baseline = _baseline()
    adjusted_by_key = {
        ("SSP2-4.5", 2030): [
            DesignRainfall(duration_minutes=60, aep=AEP.AEP_10, depth_mm=29.0, intensity_mm_per_hr=29.0)
        ],
        ("SSP2-4.5", 2050): [
            DesignRainfall(duration_minutes=60, aep=AEP.AEP_10, depth_mm=31.0, intensity_mm_per_hr=31.0)
        ],
    }
    client = _FakeArrClient(adjusted_by_key)
    coordinate = Coordinate(latitude=-31.9505, longitude=115.8605)

    result = apply_climate_change_factors(
        baseline, "SSP2-4.5", 2040, arr_client=client, coordinate=coordinate
    )

    assert client.calls == 1
    # 2040 is halfway between 2030 (29.0) and 2050 (31.0) -> 30.0
    assert result[0].depth_mm == 30.0


def test_apply_climate_change_factors_falls_back_when_live_fetch_raises():
    baseline = _baseline()

    class _RaisingClient:
        def fetch_climate_adjusted_ifds(self, *args, **kwargs):
            raise RuntimeError("network unavailable")

    coordinate = Coordinate(latitude=-31.9505, longitude=115.8605)
    result = apply_climate_change_factors(
        baseline, "SSP2-4.5", 2050, arr_client=_RaisingClient(), coordinate=coordinate
    )

    # Falls back to the bundled national CCF snapshot rather than raising.
    assert result[0].depth_mm > baseline[0].depth_mm


def test_apply_climate_change_factors_historical_is_noop():
    baseline = _baseline()
    result = apply_climate_change_factors(baseline, "Historical", None)
    assert result is baseline
