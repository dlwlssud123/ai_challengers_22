from __future__ import annotations

import geopandas as gpd
import requests

from src.config import PROCESSED_DIR, Settings
from src.data.http import DataSourceError, request_json
from src.pipeline import run_analysis


def test_processed_shelter_data_is_runtime_ready():
    shelters = gpd.read_file(PROCESSED_DIR / "shelters.geojson")
    assert len(shelters) > 0
    assert shelters.crs.to_epsg() == 4326
    assert "담당자" not in shelters.columns
    assert shelters.geometry.notna().all()


def test_real_snapshot_and_api_shelters_build_one_pipeline():
    artifacts = run_analysis(Settings(demo_mode="auto"), access_radius_m=500)
    assert artifacts.metadata["is_demo"] is False
    assert len(artifacts.areas) == 23
    assert len(artifacts.shelters) > 0
    assert artifacts.areas["adm_cd"].is_unique


def test_http_errors_redact_credentials():
    class FailedSession:
        def request(self, *args, **kwargs):
            raise requests.ConnectionError(
                "https://example.test/api?consumer_secret=do-not-log&authKey=also-secret"
            )

    try:
        request_json(FailedSession(), "GET", "https://example.test/api", timeout=1)
    except DataSourceError as exc:
        message = str(exc)
    else:
        raise AssertionError("DataSourceError was not raised")
    assert "do-not-log" not in message
    assert "also-secret" not in message
    assert message.count("[REDACTED]") == 2
