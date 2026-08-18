"""Shade canopy API and local-file loaders."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from src.config import CACHE_DIR, RAW_DIR, Settings
from src.data.geocoding import SGISAddressGeocoder
from src.data.heat_facilities import load_local_shades
from src.data.http import DataSourceError, JsonCache, build_session, request_json
from src.sgis_client import SGISClient, SGISClientError

STANDARD_SHADE_API_URL = "https://api.data.go.kr/openapi/tn_pubr_public_shade_canopy_api"
SEOGU_SHADE_API_URL = "http://apis.data.go.kr/3430000/shadeInstallationService/getShadeInstallation"
DONGGU_SHADE_API_URL = "http://apis.data.go.kr/3420000/smartShadeOperationService/getSmartShadeOperation"
CACHE_KEY = "data_go_kr_daegu_shades"


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = payload.get("response", {}).get("body", payload.get("body", payload))
    items = body.get("items", []) if isinstance(body, dict) else []
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return [item for item in items if isinstance(item, dict)]


def _first(row: dict[str, Any], names: tuple[str, ...], default: Any = None) -> Any:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        key = name.strip().lower()
        if key in lowered and lowered[key] not in (None, ""):
            return lowered[key]
    return default


def _normalize(rows: list[dict[str, Any]], source: str) -> gpd.GeoDataFrame:
    records: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        city = _first(row, ("시도명", "ctprvnNm", "sido", "SIDO_NM"), "")
        district = _first(row, ("시군구명", "signguNm", "sggNm", "시군구", "구군", "GUGUN_NM"), "")
        latitude = pd.to_numeric(_first(row, ("위도", "latitude", "lat", "LAT")), errors="coerce")
        longitude = pd.to_numeric(_first(row, ("경도", "longitude", "lon", "lng", "LOT", "LON")), errors="coerce")
        name = _first(row, ("설치장소명", "installationLocationName", "설치장소", "설치 장소", "location", "PLC_NM"), "")
        address = _first(row, ("소재지도로명주소", "소재지지번주소", "rdnmadr", "lnmadr", "주소", "address"), "")
        records.append({
            "facility_id": f"SHADE-{source}-{idx:05d}",
            "name": str(name or "그늘막").strip(),
            "address": str(address or "").strip(),
            "district_name": str(district or "").strip(),
            "adm_name": "",
            "facility_type": "그늘막",
            "shelter_type": str(_first(row, ("그늘막유형", "shadeCanopyType", "유형"), "그늘막") or "그늘막").strip(),
            "status": "운영",
            "capacity": 0,
            "longitude": longitude,
            "latitude": latitude,
            "source_file": source,
            "source_city": str(city or "").strip(),
        })
    frame = pd.DataFrame(records)
    if frame.empty:
        return gpd.GeoDataFrame(frame, geometry=[], crs="EPSG:4326")
    keep = (
        frame["source_city"].eq("대구광역시")
        & frame["latitude"].between(35.5, 36.2)
        & frame["longitude"].between(128.2, 129.1)
    )
    frame = frame.loc[keep].drop_duplicates(subset=["name", "latitude", "longitude"]).copy()
    frame["shelter_id"] = frame["facility_id"]
    return gpd.GeoDataFrame(
        frame.drop(columns=["source_city"], errors="ignore"),
        geometry=gpd.points_from_xy(frame["longitude"], frame["latitude"]),
        crs="EPSG:4326",
    ).reset_index(drop=True)


def _fetch_page(api_url: str, service_key: str, timeout: int, *, page_no: int = 1, num_rows: int = 1000) -> dict[str, Any]:
    params = {"serviceKey": service_key, "pageNo": page_no, "numOfRows": num_rows, "type": "json"}
    return request_json(build_session(), "GET", api_url, timeout=timeout, params=params)


def fetch_api_shades(settings: Settings) -> gpd.GeoDataFrame:
    service_key = settings.data_go_kr_service_key or settings.safety_data_service_key
    if not service_key:
        raise DataSourceError("DATA_GO_KR_SERVICE_KEY 또는 SAFETY_DATA_SERVICE_KEY가 없어 그늘막 API를 호출할 수 없습니다.")
    urls = [
        (settings.shade_standard_api_url or STANDARD_SHADE_API_URL, "standard_api"),
        (settings.seogu_shade_api_url or SEOGU_SHADE_API_URL, "seogu_api"),
        (settings.donggu_shade_api_url or DONGGU_SHADE_API_URL, "donggu_api"),
    ]
    layers: list[gpd.GeoDataFrame] = []
    errors: list[str] = []
    raw_payloads: dict[str, Any] = {}
    for url, source in urls:
        try:
            payload = _fetch_page(url, service_key, settings.api_timeout_seconds)
            raw_payloads[source] = payload
            layer = _normalize(_items(payload), source)
            if not layer.empty:
                layers.append(layer)
        except DataSourceError as exc:
            errors.append(f"{source}: {exc}")
    if not layers:
        raise DataSourceError("그늘막 API에서 좌표가 있는 대구 데이터를 얻지 못했습니다. " + " | ".join(errors))
    result = gpd.GeoDataFrame(pd.concat(layers, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    result = result.drop_duplicates(subset=["name", "latitude", "longitude"]).reset_index(drop=True)
    result.attrs["source_mode"] = "api"
    result.attrs["warnings"] = errors
    JsonCache(CACHE_DIR).save(CACHE_KEY, {"payloads": raw_payloads}, "data.go.kr shade APIs")
    return result


def load_shades(settings: Settings | None = None, path: Path | None = None) -> gpd.GeoDataFrame:
    settings = settings or Settings.from_env()
    try:
        return fetch_api_shades(settings)
    except DataSourceError as api_error:
        cache = JsonCache(CACHE_DIR).load(CACHE_KEY)
        if cache is not None:
            layers = [_normalize(_items(payload), source) for source, payload in cache.payload.get("payloads", {}).items()]
            layers = [layer for layer in layers if not layer.empty]
            if layers:
                result = gpd.GeoDataFrame(pd.concat(layers, ignore_index=True), geometry="geometry", crs="EPSG:4326")
                result.attrs["source_mode"] = "cache"
                result.attrs["warnings"] = [str(api_error)]
                return result.drop_duplicates(subset=["name", "latitude", "longitude"]).reset_index(drop=True)
        geocoder = None
        try:
            geocoder = SGISAddressGeocoder(SGISClient(timeout=settings.api_timeout_seconds), JsonCache(CACHE_DIR))
        except SGISClientError:
            geocoder = None
        result = load_local_shades(path, geocoder=geocoder)
        result.attrs["source_mode"] = "local_file"
        result.attrs["warnings"] = [str(api_error)]
        return result
