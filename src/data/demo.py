"""Explicitly labeled demo fallback for missing boundaries/population/weather."""

from __future__ import annotations

import math

import geopandas as gpd
from shapely.geometry import box


DEFAULT_DONG_NAMES = [
    "범어1동", "범어2동", "범어3동", "범어4동", "만촌1동", "만촌2동", "만촌3동",
    "수성1가동", "수성2·3가동", "수성4가동", "황금1동", "황금2동", "중동", "상동",
    "파동", "두산동", "지산1동", "지산2동", "범물1동", "범물2동", "고산1동", "고산2동", "고산3동",
]


def make_demo_areas(
    shelters: gpd.GeoDataFrame, dong_names: list[str] | None = None
) -> gpd.GeoDataFrame:
    """Create deterministic sample zones covering the real shelter extent.

    These are not official administrative boundaries. The function is used only
    when SGIS/raw boundary and population data are unavailable.
    """

    if shelters.empty or shelters.crs is None:
        raise ValueError("데모 영역 생성에는 CRS가 있는 쉼터 좌표가 필요합니다.")
    names = [name for name in (dong_names or DEFAULT_DONG_NAMES) if name]
    if not names:
        names = DEFAULT_DONG_NAMES
    points = shelters.to_crs("EPSG:4326")
    minx, miny, maxx, maxy = points.total_bounds
    pad_x = max((maxx - minx) * 0.04, 0.004)
    pad_y = max((maxy - miny) * 0.04, 0.004)
    minx, maxx = minx - pad_x, maxx + pad_x
    miny, maxy = miny - pad_y, maxy + pad_y
    cols = 5
    rows = math.ceil(len(names) / cols)
    width = (maxx - minx) / cols
    height = (maxy - miny) / rows
    records: list[dict[str, object]] = []
    for idx, name in enumerate(names):
        row, col = divmod(idx, cols)
        # Fill north-to-south so the map reads naturally.
        x0 = minx + col * width
        y1 = maxy - row * height
        geom = box(x0, y1 - height, x0 + width, y1)
        population = 12_000 + (idx * 2_713) % 15_000
        elderly_ratio = 0.17 + ((idx * 7) % 15) / 100
        elderly = round(population * elderly_ratio)
        records.append(
            {
                "adm_cd": f"DEMO{idx + 1:03d}",
                "adm_name": name,
                "population": population,
                "elderly_population": elderly,
                "temperature": 32.0 + ((idx * 11) % 27) / 10,
                "humidity": 50.0 + ((idx * 13) % 31),
                "is_demo": True,
                "geometry": geom,
            }
        )
    result = gpd.GeoDataFrame(records, crs="EPSG:4326")
    metric = result.to_crs("EPSG:5179")
    result["area_km2"] = metric.geometry.area / 1_000_000
    result["elderly_ratio"] = result["elderly_population"] / result["population"]
    result["elderly_density"] = result["elderly_population"] / result["area_km2"]
    return result


