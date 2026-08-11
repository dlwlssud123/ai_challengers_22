"""SGIS 인증과 행정구역 경계 조회를 담당하는 클라이언트."""

from __future__ import annotations

import os
import threading
import time
from copy import deepcopy
from typing import Any

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False

try:
    from pyproj import Transformer
except ImportError:
    Transformer = None

from .mock_data import REGIONS


load_dotenv()

DEFAULT_BASE_URL = "https://sgisapi.mods.go.kr/OpenAPI3"
AUTH_PATH = "/auth/authentication.json"
BOUNDARY_PATH = "/boundary/hadmarea.geojson"


class SGISClientError(RuntimeError):
    """화면에 안전하게 전달할 수 있는 SGIS 연결 오류."""


def _read_streamlit_secret(name: str) -> str | None:
    try:
        import streamlit as st

        value = st.secrets.get(name)
        return str(value) if value else None
    except Exception:
        return None


def _setting(name: str) -> str | None:
    return os.getenv(name) or _read_streamlit_secret(name)


def _normalize_region_name(name: str) -> str:
    return (
        name.replace(" ", "")
        .replace("·", "")
        .replace("ㆍ", "")
        .replace(".", "")
        .replace("・", "")
    )


def _transform_coordinates(value: Any, transformer: Any) -> Any:
    if not isinstance(value, list):
        return value
    if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        x, y = float(value[0]), float(value[1])
        # SGIS 경계는 UTM-K(EPSG:5179)를 사용한다. 이미 경위도면 그대로 둔다.
        if abs(x) <= 180 and abs(y) <= 90:
            return [x, y, *value[2:]]
        longitude, latitude = transformer.transform(x, y)
        return [longitude, latitude, *value[2:]]
    return [_transform_coordinates(item, transformer) for item in value]


def convert_geojson_to_wgs84(feature_collection: dict) -> dict:
    if Transformer is None:
        raise SGISClientError(
            "SGIS 실제 경계를 표시하려면 pyproj가 필요합니다. "
            "현재 Python에서 'python -m pip install -r requirements.txt'를 실행해 주세요."
        )
    result = deepcopy(feature_collection)
    transformer = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    for feature in result.get("features", []):
        geometry = feature.get("geometry") or {}
        if "coordinates" in geometry:
            geometry["coordinates"] = _transform_coordinates(geometry["coordinates"], transformer)
    return result


def attach_vulnerability_properties(feature_collection: dict) -> dict:
    """실제 경계 중 현재 분석값이 있는 지역에 Heat Map 속성을 결합한다."""
    result = deepcopy(feature_collection)
    normalized_regions = {
        _normalize_region_name(region): (region, data) for region, data in REGIONS.items()
    }
    for feature in result.get("features", []):
        properties = feature.setdefault("properties", {})
        api_name = str(properties.get("adm_nm", ""))
        normalized_api_name = _normalize_region_name(api_name)
        match = next(
            (
                (region, data)
                for normalized_name, (region, data) in normalized_regions.items()
                if normalized_api_name.endswith(normalized_name)
                or normalized_name.endswith(normalized_api_name)
            ),
            None,
        )
        if not match:
            properties.update({
                "region": api_name,
                "has_analysis": False,
                "vulnerability_score": None,
                "vulnerability_grade": "분석 데이터 없음",
                "vulnerable_population": None,
                "fill_color": [100, 116, 139, 55],
                "line_color": [148, 163, 184, 115],
            })
            continue
        region, data = match
        score = data["vulnerability_score"]
        fill_color = [220, 38, 38, 195] if score >= 85 else [249, 115, 22, 185] if score >= 70 else [250, 204, 21, 175]
        properties.update({
            "region": region,
            "has_analysis": True,
            "vulnerability_score": score,
            "vulnerability_grade": data["vulnerability_grade"],
            "vulnerable_population": data["vulnerable_population"],
            "fill_color": fill_color,
            "line_color": [255, 255, 255, 210],
        })
    return result


class SGISClient:
    _token: str | None = None
    _token_expires_at_ms: int = 0
    _token_lock = threading.Lock()

    def __init__(
        self,
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
        base_url: str | None = None,
        timeout: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        self.consumer_key = consumer_key or _setting("SGIS_CONSUMER_KEY")
        self.consumer_secret = consumer_secret or _setting("SGIS_CONSUMER_SECRET")
        self.base_url = (base_url or _setting("SGIS_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self.consumer_key and self.consumer_secret)

    def get_access_token(self, force_refresh: bool = False) -> str:
        if not self.is_configured:
            raise SGISClientError("SGIS 인증키가 설정되지 않았습니다.")
        now_ms = int(time.time() * 1000)
        with self._token_lock:
            if not force_refresh and self._token and now_ms < self._token_expires_at_ms - 60_000:
                return self._token
            try:
                # SGIS 인증 엔드포인트는 GET만 허용한다. 요청 URL을 로그에 남기지 않는다.
                response = self.session.get(
                    f"{self.base_url}{AUTH_PATH}",
                    params={
                        "consumer_key": self.consumer_key,
                        "consumer_secret": self.consumer_secret,
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
            except requests.Timeout as exc:
                raise SGISClientError("SGIS 인증 요청 시간이 초과되었습니다.") from None
            except (requests.RequestException, ValueError) as exc:
                raise SGISClientError("SGIS 인증 응답을 처리하지 못했습니다.") from None
            if payload.get("errCd") != 0:
                raise SGISClientError(f"SGIS 인증 실패: {payload.get('errMsg', '알 수 없는 오류')}")
            result = payload.get("result") or {}
            token = result.get("accessToken")
            if not token:
                raise SGISClientError("SGIS 인증 응답에 accessToken이 없습니다.")
            try:
                expires_at_ms = int(result.get("accessTimeout", now_ms + 3_600_000))
            except (TypeError, ValueError):
                expires_at_ms = now_ms + 3_600_000
            type(self)._token = str(token)
            type(self)._token_expires_at_ms = expires_at_ms
            return str(token)

    def get_administrative_boundaries(
        self,
        adm_cd: str,
        year: int,
        low_search: int = 2,
    ) -> dict:
        token = self.get_access_token()
        params = {
            "accessToken": token,
            "year": str(year),
            "adm_cd": str(adm_cd),
            "low_search": str(low_search),
        }
        try:
            response = self.session.get(
                f"{self.base_url}{BOUNDARY_PATH}", params=params, timeout=self.timeout
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise SGISClientError("SGIS 행정동 경계 요청 시간이 초과되었습니다.") from exc
        except (requests.RequestException, ValueError) as exc:
            raise SGISClientError("SGIS 행정동 경계 응답을 처리하지 못했습니다.") from exc
        if payload.get("errCd") not in (None, 0):
            # 토큰 만료 가능성이 있으면 한 번만 새 토큰으로 재시도한다.
            if payload.get("errCd") in (-401, -403):
                params["accessToken"] = self.get_access_token(force_refresh=True)
                try:
                    response = self.session.get(
                        f"{self.base_url}{BOUNDARY_PATH}", params=params, timeout=self.timeout
                    )
                    response.raise_for_status()
                    payload = response.json()
                except (requests.RequestException, ValueError) as exc:
                    raise SGISClientError("SGIS 행정동 경계를 다시 요청하지 못했습니다.") from exc
            if payload.get("errCd") not in (None, 0):
                raise SGISClientError(f"SGIS 경계 조회 실패: {payload.get('errMsg', '알 수 없는 오류')}")
        features = payload.get("features")
        if not isinstance(features, list) or not features:
            raise SGISClientError("SGIS 경계 응답에 행정구역 feature가 없습니다.")
        return convert_geojson_to_wgs84({"type": "FeatureCollection", "features": features})


def load_daegu_heatmap_geojson() -> dict:
    client = SGISClient()
    year = int(_setting("SGIS_BOUNDARY_YEAR") or "2025")
    adm_cd = _setting("SGIS_DAEGU_ADM_CD") or "22"
    boundaries = client.get_administrative_boundaries(adm_cd=adm_cd, year=year, low_search=2)
    return attach_vulnerability_properties(boundaries)
