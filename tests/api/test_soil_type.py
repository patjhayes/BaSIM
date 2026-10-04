from __future__ import annotations

from unittest.mock import Mock

from fastapi import HTTPException
import pytest
import requests

from src.api import main


def test_soil_type_returns_decoded_wa_soil_group(monkeypatch) -> None:
    response = Mock()
    response.json.return_value = {
        "type": "FeatureCollection",
        "features": [
            {"properties": {"Decoded WA Soil Group description": "Pale deep sand"}}
        ],
    }
    get = Mock(return_value=response)
    monkeypatch.setattr(main.requests, "get", get)

    result = main.soil_type(-31.95, 115.86)

    assert result == {"soil_type": "Pale deep sand"}
    request_url, = get.call_args.args
    request_params = get.call_args.kwargs["params"]
    assert request_url == main.WA_SOIL_WMS_URL
    assert request_params["REQUEST"] == "GetFeatureInfo"
    assert request_params["INFO_FORMAT"] == "application/geo+json"
    assert get.call_args.kwargs["timeout"] == 10
    response.raise_for_status.assert_called_once()


def test_soil_type_returns_none_when_location_is_unmapped(monkeypatch) -> None:
    response = Mock()
    response.json.return_value = {"type": "FeatureCollection", "features": []}
    monkeypatch.setattr(main.requests, "get", Mock(return_value=response))

    assert main.soil_type(-31.95, 115.86) == {"soil_type": None}


def test_soil_type_reports_upstream_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        main.requests,
        "get",
        Mock(side_effect=requests.Timeout("upstream timeout")),
    )

    with pytest.raises(HTTPException) as error:
        main.soil_type(-31.95, 115.86)

    assert error.value.status_code == 502
