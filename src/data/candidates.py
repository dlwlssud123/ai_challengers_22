"""Candidate-facility adapters, optional geocoding, and spatial grid fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from src.data.http import JsonCache, build_session, request_json
from src.data.shelters import read_tabular


VWORLD_ADDRESS_URL = "https://api.vworld.kr/req/address"


def _clean_address(value: Any) -> str:
    text = re.sub(r"\([^)]*\)", "", str(value or ""))
    text = text.replace("대구광역시", "").replace("수성구", "")
    return re.sub(r"\s+", "", text).strip()


def load_public_facilities(paths: list[Path]) -> pd.DataFrame:
    """Normalize supplied welfare/administrative facility address lists."""

    records: list[pd.DataFrame] = []
    for path in paths:
        if not path.exists():
            continue
        raw = read_tabular(path)
        if "시설명" in raw.columns:
            name = raw["시설명"]
            address = raw.get("소재지", "")
            facility_type = raw.get("구분", "노인복지시설")
        elif "구분" in raw.columns and "주소" in raw.columns:
            name = raw["구분"]
            address = raw["주소"]
            facility_type = pd.Series(["행정기관"] * len(raw))
        else:
            continue
        records.append(
            pd.DataFrame(
                {
                    "name": name.astype(str).str.strip(),
                    "address": pd.Series(address).astype(str).str.strip(),
                    "facility_type": pd.Series(facility_type).astype(str).str.strip(),
                    "source_file": path.name,
                }
            )
        )
    if not records:
        return pd.DataFrame(columns=["name", "address", "facility_type", "source_file"])
    return pd.concat(records, ignore_index=True).drop_duplicates(subset=["name", "address"])


def attach_known_coordinates(
    facilities: pd.DataFrame, shelters: gpd.GeoDataFrame
) -> pd.DataFrame:
    """Reuse coordinates only for exact normalized address/name matches."""

    result = facilities.copy()
    result["address_key"] = result["address"].map(_clean_address)
    shelter_lookup = shelters[["name", "address", "latitude", "longitude"]].copy()
    shelter_lookup["address_key"] = shelter_lookup["address"].map(_clean_address)
    address_coords = (
        shelter_lookup.drop_duplicates("address_key")
        .set_index("address_key")[["latitude", "longitude"]]
        .to_dict("index")
    )
    name_coords = (
        shelter_lookup.drop_duplicates("name")
        .set_index("name")[["latitude", "longitude"]]
        .to_dict("index")
    )
    latitudes: list[float | None] = []
    longitudes: list[float | None] = []
    for row in result.itertuples():
        coords = address_coords.get(row.address_key) or name_coords.get(row.name)
        latitudes.append(float(coords["latitude"]) if coords else None)
        longitudes.append(float(coords["longitude"]) if coords else None)
    result["latitude"] = latitudes
    result["longitude"] = longitudes
    return result.drop(columns=["address_key"])


@dataclass
class VWorldGeocoder:
    """Optional key-based road-address geocoder for candidate facilities."""

    api_key: str
    timeout: int
    cache: JsonCache

    def __post_init__(self) -> None:
        self.session = build_session()

    def geocode(self, address: str) -> tuple[float, float] | None:
        cache_key = f"vworld_{_clean_address(address)}"
        cached = self.cache.load(cache_key)
        if cached:
            point = cached.payload.get("response", {}).get("result", {}).get("point", {})
        else:
            payload = request_json(
                self.session,
                "GET",
                VWORLD_ADDRESS_URL,
                timeout=self.timeout,
                params={
                    "service": "address",
                    "request": "getcoord",
                    "version": "2.0",
                    "crs": "EPSG:4326",
                    "address": address,
                    "refine": "true",
                    "simple": "false",
                    "format": "json",
                    "type": "road",
                    "key": self.api_key,
                },
            )
            self.cache.save(cache_key, payload, VWORLD_ADDRESS_URL)
            point = payload.get("response", {}).get("result", {}).get("point", {})
        try:
            return float(point["y"]), float(point["x"])
        except (KeyError, TypeError, ValueError):
            return None


def load_candidate_file(path: Path, default_cost: int) -> gpd.GeoDataFrame:
    """Load a user-provided candidate_sites table using the standard schema."""

    frame = read_tabular(path).copy()
    aliases = {
        "candidate_id": ("candidate_id", "후보지식별자", "연번"),
        "name": ("name", "시설명", "후보지명"),
        "address": ("address", "주소", "소재지"),
        "latitude": ("latitude", "위도"),
        "longitude": ("longitude", "경도"),
        "facility_type": ("facility_type", "시설유형", "구분"),
        "cost": ("cost", "비용", "설치비용"),
    }
    rename: dict[str, str] = {}
    for standard, options in aliases.items():
        source = next((column for column in options if column in frame.columns), None)
        if source:
            rename[source] = standard
    frame = frame.rename(columns=rename)
    required = {"name", "latitude", "longitude"}
    if not required.issubset(frame.columns):
        missing = ", ".join(sorted(required - set(frame.columns)))
        raise ValueError(f"candidate_sites 필수 컬럼이 없습니다: {missing}")
    frame["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    frame["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")
    frame = frame[
        frame["latitude"].between(35.5, 36.1)
        & frame["longitude"].between(128.3, 129.0)
    ].copy()
    if "candidate_id" not in frame:
        frame["candidate_id"] = [f"C{i:05d}" for i in range(1, len(frame) + 1)]
    if "facility_type" not in frame:
        frame["facility_type"] = "공공시설 후보"
    if "address" not in frame:
        frame["address"] = ""
    frame["cost"] = pd.to_numeric(frame.get("cost"), errors="coerce").fillna(default_cost)
    return gpd.GeoDataFrame(
        frame[
            [
                "candidate_id", "name", "address", "facility_type", "cost",
                "latitude", "longitude",
            ]
        ],
        geometry=gpd.points_from_xy(frame["longitude"], frame["latitude"]),
        crs="EPSG:4326",
    )


def generate_grid_candidates(
    areas: gpd.GeoDataFrame,
    shelters: gpd.GeoDataFrame,
    *,
    spacing_m: int,
    default_cost: int,
    minimum_existing_distance_m: int = 100,
) -> gpd.GeoDataFrame:
    """Generate spatial candidate regions, explicitly not verified facilities."""

    if areas.crs is None or shelters.crs is None:
        raise ValueError("후보지 생성 전 영역과 쉼터 CRS가 필요합니다.")
    metric_areas = areas.to_crs("EPSG:5179")
    metric_shelters = shelters.to_crs("EPSG:5179")
    region = metric_areas.geometry.union_all()
    minx, miny, maxx, maxy = region.bounds
    shelter_union = metric_shelters.geometry.union_all()
    rows: list[dict[str, object]] = []
    index = 1
    for x in np.arange(minx + spacing_m / 2, maxx, spacing_m):
        for y in np.arange(miny + spacing_m / 2, maxy, spacing_m):
            point = Point(float(x), float(y))
            if not region.covers(point):
                continue
            if not shelter_union.is_empty and point.distance(shelter_union) < minimum_existing_distance_m:
                continue
            rows.append(
                {
                    "candidate_id": f"GRID{index:05d}",
                    "name": f"공간 후보지역 {index}",
                    "address": "",
                    "facility_type": "공간 후보지역(DEMO)",
                    "cost": float(default_cost),
                    "geometry": point,
                }
            )
            index += 1
    metric = gpd.GeoDataFrame(rows, crs="EPSG:5179")
    if metric.empty:
        return gpd.GeoDataFrame(
            columns=[
                "candidate_id", "name", "address", "facility_type", "cost",
                "latitude", "longitude", "geometry",
            ],
            geometry="geometry",
            crs="EPSG:4326",
        )
    result = metric.to_crs("EPSG:4326")
    result["latitude"] = result.geometry.y
    result["longitude"] = result.geometry.x
    return result


