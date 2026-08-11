"""KMA Weather Nuri daily observations used for an extreme-heat demo scenario."""

from __future__ import annotations

import html as html_lib
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from src.data.http import DataSourceError, JsonCache, build_session, redact_secrets
from src.data.kma_surface import DAEGU_STATION_ID, absolute_heat_hazard_score, parse_surface_text


DAILY_OBSERVATION_URL = "https://www.weather.go.kr/w/obs-climate/land/past-obs/obs-by-day.do"


def _plain_text(fragment: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html_lib.unescape(without_tags)).strip()


def parse_daily_max_temperatures(page: str, year: int, month: int) -> list[dict[str, Any]]:
    """Parse Weather Nuri's calendar table into daily maximum temperatures."""

    calendar_match = re.search(
        r'<table[^>]*class="[^"]*table-cal[^"]*"[^>]*>(.*?)</table>',
        page,
        flags=re.I | re.S,
    )
    if calendar_match is None:
        raise DataSourceError("기상청 일별 관측 달력 표를 찾지 못했습니다.")
    calendar = calendar_match.group(1)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", calendar, flags=re.I | re.S)
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:-1]):
        day_cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.I | re.S)
        days = [re.search(r"(\d{1,2})일", _plain_text(cell)) for cell in day_cells]
        if not any(days):
            continue
        value_cells = re.findall(r"<td[^>]*>(.*?)</td>", rows[index + 1], flags=re.I | re.S)
        if len(value_cells) != len(day_cells):
            continue
        for day_match, value_cell in zip(days, value_cells, strict=True):
            if day_match is None:
                continue
            maximum = re.search(r"최고기온\s*:\s*(-?\d+(?:\.\d+)?)", _plain_text(value_cell))
            if maximum:
                day = int(day_match.group(1))
                records.append(
                    {
                        "date": f"{year:04d}-{month:02d}-{day:02d}",
                        "maximum_temperature_c": float(maximum.group(1)),
                    }
                )
    if not records:
        raise DataSourceError("기상청 일별 관측표에서 최고기온을 찾지 못했습니다.")
    return records


def hottest_available_summer_period(now: datetime | None = None) -> tuple[int, list[int]]:
    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    if now.month < 6:
        return now.year - 1, [6, 7, 8]
    return now.year, list(range(6, min(now.month, 8) + 1))


def fetch_hottest_daegu_day(
    *,
    cache: JsonCache,
    timeout: int,
    surface_api_url: str | None = None,
    auth_key: str | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Return the hottest observed Daegu day in the available summer months."""

    year, months = hottest_available_summer_period()
    cache_key = f"kma_daegu_hottest_day_{year}"
    session = build_session()
    try:
        daily_records: list[dict[str, Any]] = []
        for month in months:
            response = session.get(
                DAILY_OBSERVATION_URL,
                params={"stn": DAEGU_STATION_ID, "yy": year, "mm": month, "obs": 1},
                timeout=timeout,
            )
            response.raise_for_status()
            daily_records.extend(parse_daily_max_temperatures(response.text, year, month))
        hottest = max(daily_records, key=lambda row: row["maximum_temperature_c"])
        humidity = 50.0
        humidity_source = "데모 기준값"
        if surface_api_url and auth_key:
            observed_date = hottest["date"].replace("-", "")
            response = session.get(
                surface_api_url,
                params={
                    "tm": f"{observed_date}1500",
                    "stn": DAEGU_STATION_ID,
                    "help": 1,
                    "authKey": auth_key,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            hourly = parse_surface_text(response.text)
            humidity = float(hourly["humidity_percent"])
            humidity_source = "해당일 15시 관측"
        hottest.update(
            {
                "station": "대구 ASOS 143",
                "humidity_percent": humidity,
                "humidity_source": humidity_source,
                "heat_hazard_score": absolute_heat_hazard_score(
                    hottest["maximum_temperature_c"], humidity
                ),
                "period_label": f"{year}년 여름 관측기간",
            }
        )
        cached = cache.save(cache_key, {"hottest_day": hottest}, DAILY_OBSERVATION_URL)
        return hottest, "live", cached.fetched_at
    except (requests.RequestException, DataSourceError) as exc:
        cached = cache.load(cache_key)
        if cached and isinstance(cached.payload.get("hottest_day"), dict):
            return cached.payload["hottest_day"], "cache", cached.fetched_at
        if isinstance(exc, DataSourceError):
            raise
        raise DataSourceError(f"기상청 최고기온 조회 실패: {redact_secrets(str(exc))}") from exc
