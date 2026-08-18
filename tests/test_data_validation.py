from __future__ import annotations

import json

import requests

from src.config import CACHE_DIR, Settings
from src.data.http import DataSourceError, request_json
from src.data.safety_shelters import normalize_safety_shelters
from src.pipeline import run_analysis


def test_cached_api_shelter_data_normalizes_and_drops_sensitive_columns():
    payload = json.loads((CACHE_DIR / "safetydata_daegu_heat_shelters.json").read_text(encoding="utf-8"))
    shelters = normalize_safety_shelters(payload.get("payload", payload))
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
