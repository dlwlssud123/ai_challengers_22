import requests
import pytest
from pyproj import Transformer

import src.sgis_client as sgis_client
from src.sgis_client import (
    SGISClient,
    SGISClientError,
    attach_vulnerability_properties,
    convert_geojson_to_wgs84,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, params, timeout))
        if url.endswith("authentication.json"):
            return FakeResponse({
                "errCd": 0,
                "result": {"accessToken": "test-token", "accessTimeout": "9999999999999"},
            })
        return FakeResponse({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"adm_cd": "22000000", "adm_nm": "대구광역시 달서구 송현1동"},
                "geometry": {"type": "Polygon", "coordinates": [[[128.5, 35.8], [128.6, 35.8], [128.5, 35.8]]]},
            }],
        })


def test_authentication_and_boundary_contract():
    SGISClient._token = None
    SGISClient._token_expires_at_ms = 0
    session = FakeSession()
    client = SGISClient("key", "secret", session=session)
    result = client.get_administrative_boundaries("22", 2025, 2)
    assert result["features"][0]["properties"]["adm_cd"] == "22000000"
    assert len(session.calls) == 2
    assert session.calls[1][1]["accessToken"] == "test-token"


def test_coordinate_conversion_from_utm_k_to_wgs84():
    forward = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    x, y = forward.transform(128.6, 35.87)
    geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }]}
    converted = convert_geojson_to_wgs84(geojson)
    longitude, latitude = converted["features"][0]["geometry"]["coordinates"]
    assert longitude == pytest.approx(128.6, abs=1e-5)
    assert latitude == pytest.approx(35.87, abs=1e-5)


def test_vulnerability_join_normalizes_dong_punctuation():
    geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"adm_nm": "대구광역시 서구 비산2.3동"},
        "geometry": {"type": "Polygon", "coordinates": []},
    }]}
    result = attach_vulnerability_properties(geojson)
    properties = result["features"][0]["properties"]
    assert properties["has_analysis"] is True
    assert properties["region"] == "대구광역시 서구 비산2·3동"


def test_connection_error_does_not_expose_credentials():
    class FailingSession:
        def get(self, url, params, timeout):
            raise requests.ConnectionError(f"failed: {params}")

    SGISClient._token = None
    SGISClient._token_expires_at_ms = 0
    client = SGISClient("private-key", "private-secret", session=FailingSession())
    with pytest.raises(SGISClientError) as exc_info:
        client.get_access_token()
    assert "private-key" not in str(exc_info.value)
    assert "private-secret" not in str(exc_info.value)


def test_missing_pyproj_returns_actionable_error(monkeypatch):
    monkeypatch.setattr(sgis_client, "Transformer", None)
    with pytest.raises(SGISClientError, match="pyproj"):
        convert_geojson_to_wgs84({"type": "FeatureCollection", "features": []})
