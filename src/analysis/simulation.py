"""Before/after spatial KPI simulation."""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import pandas as pd

from src.analysis.accessibility import (
    build_coverage_union,
    calculate_accessibility,
    total_coverage_metrics,
)
from src.analysis.optimizer import selected_candidate_table
from src.schemas import OptimizationSummary


@dataclass
class SimulationResult:
    before_metrics: dict[str, float]
    after_metrics: dict[str, float]
    selected_candidates: gpd.GeoDataFrame
    after_areas: gpd.GeoDataFrame
    after_shelters: gpd.GeoDataFrame


def simulate_installation(
    areas: gpd.GeoDataFrame,
    shelters: gpd.GeoDataFrame,
    candidates: gpd.GeoDataFrame,
    blindspots: gpd.GeoDataFrame,
    optimization: OptimizationSummary,
    *,
    radius_m: float,
) -> SimulationResult:
    """Recompute geometric access after installing selected candidates."""

    before = total_coverage_metrics(areas)
    before["blind_spot_count"] = float(len(blindspots))
    before["high_risk_blindspot_elderly"] = float(blindspots["estimated_elderly"].sum())
    selected = selected_candidate_table(
        candidates, blindspots, optimization, radius_m=radius_m
    )
    additions = gpd.GeoDataFrame(
        {
            "shelter_id": selected.get("candidate_id", pd.Series(dtype=str)).astype(str),
            "name": selected.get("name", pd.Series(dtype=str)),
            "address": selected.get("address", pd.Series(dtype=str)),
            "capacity": 0.0,
            "shelter_type": selected.get("facility_type", pd.Series(dtype=str)),
            "latitude": selected.get("latitude", pd.Series(dtype=float)),
            "longitude": selected.get("longitude", pd.Series(dtype=float)),
            "weekday_open": True,
            "weekend_open": False,
            "night_open": False,
        },
        geometry=selected.geometry if not selected.empty else gpd.GeoSeries([], crs=shelters.crs),
        crs=shelters.crs,
    )
    after_shelters = gpd.GeoDataFrame(
        pd.concat([shelters, additions], ignore_index=True), geometry="geometry", crs=shelters.crs
    )
    after_areas = calculate_accessibility(areas, after_shelters, radius_m=radius_m)
    after = total_coverage_metrics(after_areas)
    if blindspots.empty:
        remaining_count = 0
        remaining_population = 0.0
    else:
        metric_blindspots = blindspots.to_crs("EPSG:5179")
        coverage = build_coverage_union(after_shelters, radius_m)
        covered_mask = metric_blindspots.geometry.representative_point().map(coverage.covers)
        remaining = blindspots.loc[~covered_mask.to_numpy()]
        remaining_count = len(remaining)
        remaining_population = float(remaining["estimated_elderly"].sum())
    after["blind_spot_count"] = float(remaining_count)
    after["high_risk_blindspot_elderly"] = remaining_population
    after["blind_spot_reduction"] = before["blind_spot_count"] - after["blind_spot_count"]
    after["newly_covered_elderly"] = max(
        after["estimated_covered_elderly"] - before["estimated_covered_elderly"], 0.0
    )
    return SimulationResult(
        before_metrics=before,
        after_metrics=after,
        selected_candidates=selected,
        after_areas=after_areas,
        after_shelters=after_shelters,
    )


