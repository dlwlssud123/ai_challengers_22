"""Address geocoding helpers backed by SGIS."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pyproj import Transformer

from src.data.http import JsonCache
from src.sgis_client import SGISClient, SGISClientError


def clean_geocode_key(value: Any) -> str:
    text = re.sub(r"\([^)]*\)", "", str(value or ""))
    return re.sub(r"\s+", "", text).strip()


@dataclass
class SGISAddressGeocoder:
    """Geocode Korean addresses with SGIS and cache each resolved point."""

    client: SGISClient
    cache: JsonCache

    def __post_init__(self) -> None:
        self.transformer = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

    def geocode(self, address: str) -> tuple[float, float] | None:
        normalized = str(address or "").strip()
        if not normalized:
            return None
        cache_key = f"sgis_geocode_{clean_geocode_key(normalized)}"
        cached = self.cache.load(cache_key)
        if cached:
            point = cached.payload.get("point") or {}
            try:
                return float(point["latitude"]), float(point["longitude"])
            except (KeyError, TypeError, ValueError):
                return None
        token = self.client.get_access_token()
        try:
            response = self.client.session.get(
                f"{self.client.base_url}/addr/geocode.json",
                params={"accessToken": token, "address": normalized, "pagenum": 0, "resultcount": 5},
                timeout=self.client.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise SGISClientError("SGIS 주소 지오코딩 요청을 처리하지 못했습니다.") from exc
        if payload.get("errCd") not in (None, 0):
            raise SGISClientError(f"SGIS 주소 지오코딩 실패: {payload.get('errMsg', '알 수 없는 오류')}")
        rows = (payload.get("result") or {}).get("resultdata") or []
        if not rows:
            self.cache.save(cache_key, {"address": normalized, "point": None}, "SGIS addr/geocode")
            return None
        row = rows[0]
        try:
            x = float(row.get("x") or row.get("x_coor"))
            y = float(row.get("y") or row.get("y_coor"))
        except (TypeError, ValueError):
            self.cache.save(cache_key, {"address": normalized, "point": None, "raw": row}, "SGIS addr/geocode")
            return None
        lon, lat = self.transformer.transform(x, y)
        self.cache.save(
            cache_key,
            {"address": normalized, "point": {"latitude": lat, "longitude": lon}, "raw": row},
            "SGIS addr/geocode",
        )
        return lat, lon
