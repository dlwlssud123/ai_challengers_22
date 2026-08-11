"""기상청 API허브 지상관측 시간자료(kma_sfctm2) 클라이언트."""

from __future__ import annotations

import re
from typing import Any

import requests

from src.data.http import DataSourceError, JsonCache, build_session, redact_secrets


CACHE_KEY = "kma_daegu_surface_latest"
DAEGU_STATION_ID = 143


def absolute_heat_hazard_score(temperature_c: float, humidity_percent: float) -> float:
    """Return a transparent 0–100 demo hazard score from current heat and humidity."""

    temperature = min(max((float(temperature_c) - 25.0) / 12.0, 0.0), 1.0)
    humidity = min(max((float(humidity_percent) - 40.0) / 50.0, 0.0), 1.0)
    return round(100.0 * (0.8 * temperature + 0.2 * humidity), 1)


def parse_surface_text(text: str) -> dict[str, Any]:
    """Parse KMA's whitespace table by using the help header returned with it."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header: list[str] | None = None
    numbered_fields: list[str] = []
    for line in lines:
        if line.startswith("#"):
            descriptor = re.match(r"#\s*\d+\.\s+([A-Z0-9_]+)\s*:", line)
            if descriptor:
                numbered_fields.append(descriptor.group(1))
            fields = line.lstrip("#").split()
            if "TM" in fields and "STN" in fields and "TA" in fields and "HM" in fields:
                header = fields
    if numbered_fields:
        header = numbered_fields
    data_lines = [line for line in lines if not line.startswith("#")]
    if not header or not data_lines:
        raise DataSourceError("기상청 응답에서 관측 필드 또는 자료 행을 찾지 못했습니다.")
    values = data_lines[-1].split()
    if len(values) < len(header):
        raise DataSourceError("기상청 관측자료의 필드 수가 도움말과 일치하지 않습니다.")
    row = dict(zip(header, values, strict=False))
    try:
        return {
            "station_id": int(row["STN"]),
            "observed_at_kst": row["TM"],
            "temperature_c": float(row["TA"]),
            "humidity_percent": float(row["HM"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise DataSourceError("기상청 기온·습도 값을 해석하지 못했습니다.") from exc


def fetch_latest_daegu_weather(
    *, api_url: str, auth_key: str, timeout: int, cache: JsonCache
) -> tuple[dict[str, Any], str, str]:
    """Fetch Daegu ASOS station 143, falling back to a last-good observation."""

    session = build_session()
    try:
        response = session.get(
            api_url,
            params={"stn": DAEGU_STATION_ID, "help": 1, "authKey": auth_key},
            timeout=timeout,
        )
        if response.status_code != 200:
            message = f"HTTP {response.status_code}"
            try:
                body = response.json()
                message = str((body.get("result") or {}).get("message") or message)
            except (ValueError, AttributeError):
                pass
            raise DataSourceError(f"기상청 API 오류: {redact_secrets(message)}")
        observation = parse_surface_text(response.text)
        cached = cache.save(CACHE_KEY, {"observation": observation}, api_url)
        return observation, "live", cached.fetched_at
    except (requests.RequestException, DataSourceError) as exc:
        cached = cache.load(CACHE_KEY)
        if cached is not None and isinstance(cached.payload.get("observation"), dict):
            return cached.payload["observation"], "cache", cached.fetched_at
        if isinstance(exc, DataSourceError):
            raise
        raise DataSourceError(f"기상청 API 요청 실패: {redact_secrets(str(exc))}") from exc
