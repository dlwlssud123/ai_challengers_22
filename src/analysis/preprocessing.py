"""Schema-safe preprocessing for administrative area inputs."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd


AREA_REQUIRED = {
    "adm_cd", "adm_name", "population", "elderly_population", "temperature", "humidity", "geometry"
}


def safe_minmax(
    values: pd.Series, *, lower_quantile: float = 0.02, upper_quantile: float = 0.98
) -> pd.Series:
    """Return a NaN/constant/outlier-safe 0–1 min-max normalization."""

    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if numeric.notna().sum() == 0:
        return pd.Series(0.0, index=values.index, dtype=float)
    filled = numeric.fillna(float(numeric.median()))
    if len(filled) >= 5:
        low = float(filled.quantile(lower_quantile))
        high = float(filled.quantile(upper_quantile))
        clipped = filled.clip(lower=low, upper=high)
    else:
        clipped = filled
    minimum = float(clipped.min())
    maximum = float(clipped.max())
    if not np.isfinite(minimum) or not np.isfinite(maximum) or maximum <= minimum:
        return pd.Series(0.0, index=values.index, dtype=float)
    return ((clipped - minimum) / (maximum - minimum)).clip(0.0, 1.0)


def prepare_areas(areas: gpd.GeoDataFrame, analysis_crs: str = "EPSG:5179") -> gpd.GeoDataFrame:
    """Validate area inputs and calculate demographic density fields."""

    missing = AREA_REQUIRED - set(areas.columns)
    if missing:
        raise ValueError(f"행정동 데이터 필수 컬럼 누락: {', '.join(sorted(missing))}")
    if areas.crs is None:
        raise ValueError("행정동 geometry에 원본 CRS가 없습니다.")
    result = areas.copy()
    for column in ("population", "elderly_population", "temperature", "humidity"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["population"] = result["population"].fillna(0).clip(lower=0)
    result["elderly_population"] = result["elderly_population"].fillna(0).clip(lower=0)
    result["elderly_population"] = np.minimum(
        result["elderly_population"], result["population"]
    )
    temperature_median = (
        result["temperature"].median() if result["temperature"].notna().any() else 0.0
    )
    humidity_median = result["humidity"].median() if result["humidity"].notna().any() else 0.0
    result["temperature"] = result["temperature"].fillna(
        0.0 if pd.isna(temperature_median) else temperature_median
    )
    result["humidity"] = result["humidity"].fillna(
        0.0 if pd.isna(humidity_median) else humidity_median
    ).clip(0, 100)
    metric = result.to_crs(analysis_crs)
    result["area_km2"] = (metric.geometry.area / 1_000_000).clip(lower=1e-9)
    result["elderly_ratio"] = np.where(
        result["population"] > 0,
        result["elderly_population"] / result["population"],
        0.0,
    )
    result["elderly_density"] = result["elderly_population"] / result["area_km2"]
    return result

