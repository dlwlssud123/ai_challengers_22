"""Projected-CRS shelter coverage and capacity analysis."""

from __future__ import annotations

from typing import Iterable

import geopandas as gpd
import numpy as np
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from src.analysis.preprocessing import safe_minmax


def require_projected_crs(frame: gpd.GeoDataFrame) -> None:
    """Reject missing/geographic CRS before any meter-based operation."""

    if frame.crs is None:
        raise ValueError("미터 단위 GIS 연산 전에 원본 CRS가 필요합니다.")
    crs = CRS.from_user_input(frame.crs)
    if not crs.is_projected:
        raise ValueError("EPSG:4326 등 위경도 CRS에서 미터 buffer/distance를 계산할 수 없습니다.")


def geometry_union(geometries: Iterable[BaseGeometry]) -> BaseGeometry:
    series = gpd.GeoSeries(list(geometries))
    return series.union_all()


def build_coverage_union(
    shelters: gpd.GeoDataFrame, radius_m: float, analysis_crs: str = "EPSG:5179"
) -> BaseGeometry:
    """Buffer shelter points only after conversion to a projected CRS."""

    if shelters.crs is None:
        raise ValueError("쉼터 데이터에 CRS가 없습니다.")
    metric = shelters.to_crs(analysis_crs)
    require_projected_crs(metric)
    if metric.empty:
        return gpd.GeoSeries([], crs=analysis_crs).union_all()
    return metric.geometry.buffer(float(radius_m)).union_all()


def calculate_accessibility(
    areas: gpd.GeoDataFrame,
    shelters: gpd.GeoDataFrame,
    *,
    radius_m: float,
    analysis_crs: str = "EPSG:5179",
) -> gpd.GeoDataFrame:
    """Estimate geometric access under uniform within-area elderly distribution."""

    if areas.crs is None or shelters.crs is None:
        raise ValueError("접근성 분석에는 영역과 쉼터의 CRS가 모두 필요합니다.")
    metric_areas = areas.to_crs(analysis_crs)
    metric_shelters = shelters.to_crs(analysis_crs)
    require_projected_crs(metric_areas)
    require_projected_crs(metric_shelters)
    coverage = build_coverage_union(shelters, radius_m, analysis_crs)
    shelter_points = list(metric_shelters.geometry)
    coverage_ratios: list[float] = []
    nearest_distances: list[float] = []
    capacity_values: list[float] = []
    for polygon in metric_areas.geometry:
        area = max(float(polygon.area), 1e-9)
        covered_area = 0.0 if coverage.is_empty else float(polygon.intersection(coverage).area)
        coverage_ratios.append(float(np.clip(covered_area / area, 0.0, 1.0)))
        centroid = polygon.centroid
        nearest_distances.append(
            min((centroid.distance(point) for point in shelter_points), default=float("nan"))
        )
        mask = metric_shelters.geometry.intersects(polygon)
        capacity_values.append(float(metric_shelters.loc[mask, "capacity"].sum()))
    result = areas.copy()
    result["coverage_ratio"] = coverage_ratios
    result["coverage_gap"] = 1.0 - result["coverage_ratio"]
    result["nearest_shelter_distance"] = nearest_distances
    result["estimated_covered_elderly"] = (
        result["elderly_population"] * result["coverage_ratio"]
    )
    result["estimated_uncovered_elderly"] = (
        result["elderly_population"] - result["estimated_covered_elderly"]
    ).clip(lower=0)
    result["shelter_capacity"] = capacity_values
    result["capacity_per_1000_elderly"] = np.where(
        result["elderly_population"] > 0,
        result["shelter_capacity"] / result["elderly_population"] * 1_000,
        0.0,
    )
    distance_score = safe_minmax(result["nearest_shelter_distance"])
    gap_score = safe_minmax(result["coverage_gap"])
    result["access_score"] = (100 * (0.65 * distance_score + 0.35 * gap_score)).clip(0, 100)
    return result


def total_coverage_metrics(areas: gpd.GeoDataFrame) -> dict[str, float]:
    """Aggregate estimated access metrics without calling them actual usage."""

    elderly = float(areas["elderly_population"].sum())
    covered = float(areas["estimated_covered_elderly"].sum())
    covered = min(max(covered, 0.0), elderly)
    return {
        "total_elderly": elderly,
        "estimated_covered_elderly": covered,
        "estimated_uncovered_elderly": max(elderly - covered, 0.0),
        "coverage_rate": covered / elderly if elderly > 0 else 0.0,
    }


