"""Projected-CRS shelter coverage and capacity analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import geopandas as gpd
import numpy as np
import pandas as pd
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


def load_grid_population(
    population_files: Sequence[str | Path],
    *,
    population_metric: str = "to_in_001",
) -> pd.DataFrame:
    """Load SGIS 100m grid population rows keyed by grid code."""

    frames: list[pd.DataFrame] = []
    for path in population_files:
        frame = pd.read_csv(
            path,
            header=None,
            names=["year", "GRID_CD", "metric", "population"],
            encoding="cp949",
        )
        frame = frame.loc[frame["metric"].eq(population_metric), ["GRID_CD", "population"]]
        frame["population"] = pd.to_numeric(frame["population"], errors="coerce").fillna(0)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["GRID_CD", "population"])
    combined = pd.concat(frames, ignore_index=True)
    return combined.groupby("GRID_CD", as_index=False)["population"].sum()


def load_grid_cells(
    grid_shape_files: Sequence[str | Path],
    areas: gpd.GeoDataFrame,
    *,
    analysis_crs: str = "EPSG:5179",
) -> gpd.GeoDataFrame:
    """Load only grid cells overlapping the analysis area's bounding box."""

    if areas.crs is None:
        raise ValueError("격자 추출에는 행정동 CRS가 필요합니다.")
    metric_areas = areas.to_crs(analysis_crs)
    require_projected_crs(metric_areas)
    bounds = tuple(metric_areas.total_bounds)
    frames: list[gpd.GeoDataFrame] = []
    for path in grid_shape_files:
        frame = gpd.read_file(path, bbox=bounds)
        if frame.empty:
            continue
        if frame.crs is None:
            frame = frame.set_crs(analysis_crs)
        frame = frame.to_crs(analysis_crs)
        if "GRID_CD" not in frame.columns:
            raise ValueError(f"격자 SHP에 GRID_CD 컬럼이 없습니다: {path}")
        frames.append(frame[["GRID_CD", "geometry"]])
    if not frames:
        return gpd.GeoDataFrame({"GRID_CD": []}, geometry=[], crs=analysis_crs)
    return pd.concat(frames, ignore_index=True).drop_duplicates("GRID_CD")


def calculate_grid_accessibility_by_dong(
    areas: gpd.GeoDataFrame,
    shelters: gpd.GeoDataFrame,
    *,
    grid_population_files: Sequence[str | Path],
    grid_shape_files: Sequence[str | Path],
    d0_m: float = 300.0,
    walk_limit_m: float = 500.0,
    analysis_crs: str = "EPSG:5179",
) -> gpd.GeoDataFrame:
    """Average grid-center shelter access scores inside each administrative dong."""

    if areas.crs is None or shelters.crs is None:
        raise ValueError("격자 접근성 분석에는 행정동과 쉼터의 CRS가 모두 필요합니다.")
    if "adm_cd" not in areas.columns:
        raise ValueError("행정동 데이터에 adm_cd 컬럼이 필요합니다.")

    metric_areas = areas.to_crs(analysis_crs)
    metric_shelters = shelters.to_crs(analysis_crs)
    require_projected_crs(metric_areas)
    require_projected_crs(metric_shelters)

    grids = load_grid_cells(grid_shape_files, metric_areas, analysis_crs=analysis_crs)
    if grids.empty:
        return _with_empty_grid_accessibility(areas)

    populations = load_grid_population(grid_population_files)
    grids = grids.merge(populations, on="GRID_CD", how="left")
    grids["population"] = pd.to_numeric(grids["population"], errors="coerce").fillna(0)
    grid_points = gpd.GeoDataFrame(
        grids[["GRID_CD", "population"]],
        geometry=grids.geometry.centroid,
        crs=analysis_crs,
    )
    assigned = gpd.sjoin(
        grid_points,
        metric_areas[["adm_cd", "geometry"]],
        how="inner",
        predicate="within",
    ).drop(columns=["index_right"], errors="ignore")
    if assigned.empty:
        return _with_empty_grid_accessibility(areas)

    if metric_shelters.empty:
        assigned["nearest_shelter_distance"] = np.nan
        assigned["grid_accessibility_score"] = 0.0
    else:
        assigned = gpd.sjoin_nearest(
            assigned,
            metric_shelters[["geometry"]],
            how="left",
            distance_col="nearest_shelter_distance",
        ).drop(columns=["index_right"], errors="ignore")
        assigned["grid_accessibility_score"] = np.exp(
            -pd.to_numeric(assigned["nearest_shelter_distance"], errors="coerce") / float(d0_m)
        ).fillna(0.0)

    assigned["beyond_walk_limit"] = (
        pd.to_numeric(assigned["nearest_shelter_distance"], errors="coerce") > float(walk_limit_m)
    )

    def population_weighted_average(group: pd.DataFrame) -> float:
        weights = pd.to_numeric(group["population"], errors="coerce").fillna(0)
        if float(weights.sum()) <= 0:
            return float(group["grid_accessibility_score"].mean())
        return float(np.average(group["grid_accessibility_score"], weights=weights))

    grouped = assigned.groupby("adm_cd", dropna=False)
    summary = grouped.agg(
        grid_cell_count=("GRID_CD", "count"),
        grid_population=("population", "sum"),
        grid_accessibility_index=("grid_accessibility_score", "mean"),
        grid_mean_nearest_shelter_distance=("nearest_shelter_distance", "mean"),
        grid_beyond_walk_limit_ratio=("beyond_walk_limit", "mean"),
    )
    summary["grid_population_weighted_accessibility_index"] = pd.Series(
        {
            adm_cd: population_weighted_average(group)
            for adm_cd, group in grouped
        }
    )
    summary["grid_accessibility_lack_score"] = (
        100.0 * (1.0 - summary["grid_accessibility_index"])
    ).clip(0.0, 100.0)
    summary["grid_population_weighted_accessibility_lack_score"] = (
        100.0 * (1.0 - summary["grid_population_weighted_accessibility_index"])
    ).clip(0.0, 100.0)

    result = areas.copy()
    result = result.merge(summary.reset_index(), on="adm_cd", how="left")
    return _fill_grid_accessibility_defaults(result)


def _with_empty_grid_accessibility(areas: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = areas.copy()
    return _fill_grid_accessibility_defaults(result)


def _fill_grid_accessibility_defaults(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    defaults = {
        "grid_cell_count": 0,
        "grid_population": 0.0,
        "grid_accessibility_index": 0.0,
        "grid_population_weighted_accessibility_index": 0.0,
        "grid_accessibility_lack_score": 100.0,
        "grid_population_weighted_accessibility_lack_score": 100.0,
        "grid_mean_nearest_shelter_distance": np.nan,
        "grid_beyond_walk_limit_ratio": 1.0,
    }
    for column, value in defaults.items():
        if column not in frame.columns:
            frame[column] = value
        else:
            frame[column] = frame[column].fillna(value)
    return frame


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


