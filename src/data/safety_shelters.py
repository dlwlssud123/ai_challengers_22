"""재난안전데이터공유플랫폼 무더위쉼터 API 연동."""

from __future__ import annotations

from math import ceil
from typing import Any

import geopandas as gpd
import pandas as pd

from src.data.http import DataSourceError, JsonCache, build_session, request_json


DAEGU_BOUNDS = {
    "startLot": 128.30,
    "endLot": 129.00,
    "startLat": 35.50,
    "endLat": 36.20,
}
CACHE_KEY = "safetydata_daegu_heat_shelters"


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = payload.get("body") or []
    if isinstance(body, dict):
        body = body.get("items") or body.get("item") or []
    if not isinstance(body, list):
        raise DataSourceError("무더위쉼터 API 응답의 body 형식이 올바르지 않습니다.")
    return [row for row in body if isinstance(row, dict)]


def _validate(payload: dict[str, Any]) -> None:
    header = payload.get("header") or {}
    if str(header.get("resultCode", "")) != "00":
        message = header.get("resultMsg") or header.get("errorMsg") or "알 수 없는 오류"
        raise DataSourceError(f"무더위쉼터 API 오류: {message}")


def fetch_daegu_shelter_payload(
    *, api_url: str, service_key: str, timeout: int, cache: JsonCache
) -> tuple[dict[str, Any], str, str]:
    """Fetch every page in the Daegu bounding box and keep a last-good cache."""

    session = build_session()
    common = {
        "serviceKey": service_key,
        "returnType": "json",
        "numOfRows": 1000,
        **DAEGU_BOUNDS,
    }
    try:
        first = request_json(session, "GET", api_url, timeout=timeout, params={**common, "pageNo": 1})
        _validate(first)
        total = int(first.get("totalCount") or len(_items(first)))
        rows = _items(first)
        for page in range(2, ceil(total / 1000) + 1):
            payload = request_json(
                session, "GET", api_url, timeout=timeout, params={**common, "pageNo": page}
            )
            _validate(payload)
            rows.extend(_items(payload))
        combined = {"header": first.get("header"), "totalCount": total, "body": rows}
        cached = cache.save(CACHE_KEY, combined, api_url)
        return combined, "live", cached.fetched_at
    except DataSourceError:
        cached = cache.load(CACHE_KEY)
        if cached is None:
            raise
        return cached.payload, "cache", cached.fetched_at


def normalize_safety_shelters(payload: dict[str, Any]) -> gpd.GeoDataFrame:
    """Normalize API rows and exclude nearby provinces caught by the bounding box."""

    raw = pd.DataFrame(_items(payload))
    if raw.empty:
        raise DataSourceError("무더위쉼터 API가 빈 결과를 반환했습니다.")
    road = raw.get("RN_DTL_ADRES", pd.Series("", index=raw.index)).fillna("").astype(str)
    parcel = raw.get("DTL_ADRES", pd.Series("", index=raw.index)).fillna("").astype(str)
    address = road.where(road.str.strip().ne(""), parcel)
    daegu = address.str.contains(r"^(?:대구광역시|대구시)\s", regex=True, na=False)
    raw = raw.loc[daegu].copy()
    address = address.loc[daegu]

    longitude = pd.to_numeric(raw.get("LO"), errors="coerce")
    latitude = pd.to_numeric(raw.get("LA"), errors="coerce")
    valid = longitude.between(128.30, 129.00) & latitude.between(35.50, 36.20)
    raw = raw.loc[valid].copy()
    address = address.loc[valid]
    longitude = longitude.loc[valid]
    latitude = latitude.loc[valid]

    frame = pd.DataFrame(
        {
            "shelter_id": raw.get("RSTR_FCLTY_NO").astype(str),
            "name": raw.get("RSTR_NM", pd.Series("이름 미상", index=raw.index)).fillna("이름 미상"),
            "address": address,
            "latitude": latitude,
            "longitude": longitude,
            "capacity": pd.to_numeric(raw.get("USE_PSBL_NMPR"), errors="coerce").fillna(0),
            "shelter_type": raw.get("FCLTY_TY", pd.Series("미분류", index=raw.index)).fillna("미분류"),
            "weekday_open": True,
            "weekend_open": raw.get(
                "CHCK_MATTER_WKEND_HDAY_OPN_AT", pd.Series("N", index=raw.index)
            ).fillna("N").astype(str).str.upper().eq("Y"),
            "night_open": raw.get(
                "CHCK_MATTER_NIGHT_OPN_AT", pd.Series("N", index=raw.index)
            ).fillna("N").astype(str).str.upper().eq("Y"),
        }
    ).drop_duplicates(subset=["shelter_id"])
    result = gpd.GeoDataFrame(
        frame,
        geometry=gpd.points_from_xy(frame["longitude"], frame["latitude"]),
        crs="EPSG:4326",
    ).reset_index(drop=True)
    result.attrs["quality"] = {
        "input_rows": int(len(_items(payload))),
        "valid_rows": int(len(result)),
        "dropped_outside_daegu_or_invalid": int(len(_items(payload)) - len(result)),
        "source_file": "재난안전데이터공유플랫폼 DSSP-IF-10942",
    }
    return result


def district_name_from_address(address: str) -> str | None:
    """Extract one of Daegu's gu/gun names from a normalized address."""

    parts = str(address).split()
    return parts[1] if len(parts) >= 2 and parts[0] in {"대구광역시", "대구시"} else None
