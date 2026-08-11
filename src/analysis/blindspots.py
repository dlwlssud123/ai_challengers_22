"""Projected grid generation and high-priority access-gap detection."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import Point, box

from src.analysis.accessibility import build_coverage_union, require_projected_crs


BLINDSPOT_COLUMNS = [
    "cell_id", "adm_cd", "adm_name", "estimated_elderly", "priority_score",
    "nearest_shelter_distance", "geometry",
]


def build_blindspots(
    areas: gpd.GeoDataFrame,
    shelters: gpd.GeoDataFrame,
    *,
    radius_m: float,
    threshold: float,
    grid_size_m: int = 300,
    analysis_crs: str = "EPSG:5179",
) -> gpd.GeoDataFrame:
    """Find grid cells whose centroid is high-priority and outside coverage."""

    if areas.crs is None or shelters.crs is None:
        raise ValueError("사각지대 분석에는 영역과 쉼터 CRS가 필요합니다.")
    metric_areas = areas.to_crs(analysis_crs).reset_index(drop=True)
    metric_shelters = shelters.to_crs(analysis_crs)
    require_projected_crs(metric_areas)
    require_projected_crs(metric_shelters)
    region = metric_areas.geometry.union_all()
    coverage = build_coverage_union(shelters, radius_m, analysis_crs)
    shelter_union = metric_shelters.geometry.union_all()
    minx, miny, maxx, maxy = region.bounds
    grid_records: list[dict[str, object]] = []
    cell_number = 1
    for x in np.arange(minx, maxx, grid_size_m):
        for y in np.arange(miny, maxy, grid_size_m):
            raw_cell = box(float(x), float(y), float(x + grid_size_m), float(y + grid_size_m))
            cell = raw_cell.intersection(region)
            if cell.is_empty or cell.area < grid_size_m * grid_size_m * 0.05:
                continue
            grid_records.append({"cell_id": f"B{cell_number:05d}", "geometry": cell})
            cell_number += 1
    if not grid_records:
        return gpd.GeoDataFrame(columns=BLINDSPOT_COLUMNS, geometry="geometry", crs="EPSG:4326")
    cells = gpd.GeoDataFrame(grid_records, crs=analysis_crs)
    centers = cells.geometry.representative_point()
    if not coverage.is_empty:
        cells = cells.loc[~centers.covered_by(coverage)].copy()
        centers = cells.geometry.representative_point()
    if cells.empty:
        return gpd.GeoDataFrame(columns=BLINDSPOT_COLUMNS, geometry="geometry", crs="EPSG:4326")

    area_fields = metric_areas[
        ["adm_cd", "adm_name", "elderly_population", "priority_score", "geometry"]
    ].copy()
    area_fields["administrative_area_m2"] = area_fields.geometry.area.clip(lower=1e-9)
    fragments = gpd.overlay(cells, area_fields, how="intersection", keep_geom_type=False)
    if fragments.empty:
        return gpd.GeoDataFrame(columns=BLINDSPOT_COLUMNS, geometry="geometry", crs="EPSG:4326")
    fragments["fragment_area_m2"] = fragments.geometry.area
    fragments["fragment_elderly"] = (
        fragments["elderly_population"]
        * fragments["fragment_area_m2"]
        / fragments["administrative_area_m2"]
    )
    dominant_indices = fragments.groupby("cell_id")["fragment_area_m2"].idxmax()
    dominant = fragments.loc[
        dominant_indices, ["cell_id", "adm_cd", "adm_name", "priority_score"]
    ].set_index("cell_id")
    estimated = fragments.groupby("cell_id")["fragment_elderly"].sum()
    result = cells.set_index("cell_id").join(dominant).join(
        estimated.rename("estimated_elderly")
    )
    result = result[result["priority_score"] >= threshold].copy()
    if result.empty:
        return gpd.GeoDataFrame(columns=BLINDSPOT_COLUMNS, geometry="geometry", crs="EPSG:4326")
    result_centers = result.geometry.representative_point()
    result["nearest_shelter_distance"] = (
        result_centers.distance(shelter_union) if not shelter_union.is_empty else np.nan
    )
    result = result.reset_index()
    return gpd.GeoDataFrame(result[BLINDSPOT_COLUMNS], crs=analysis_crs).to_crs("EPSG:4326")

