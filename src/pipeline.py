"""End-to-end analysis pipeline shared by scripts and Streamlit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import geopandas as gpd

from src.analysis.accessibility import calculate_accessibility
from src.analysis.blindspots import build_blindspots
from src.analysis.clustering import cluster_areas
from src.analysis.preprocessing import prepare_areas
from src.analysis.risk import calculate_risk_scores, refresh_priority_score
from src.config import Settings
from src.data.loader import DatasetBundle, build_source_dataset


@dataclass
class AnalysisArtifacts:
    areas: gpd.GeoDataFrame
    shelters: gpd.GeoDataFrame
    citywide_shelters: gpd.GeoDataFrame
    candidates: gpd.GeoDataFrame
    blindspots: gpd.GeoDataFrame
    cluster_profiles: list[dict[str, object]]
    metadata: dict[str, object]


def run_analysis(
    settings: Settings,
    *,
    access_radius_m: int | None = None,
    risk_threshold: float = 60.0,
    blindspot_grid_m: int = 300,
) -> AnalysisArtifacts:
    """Build scores, accessibility, clusters, and blind spots from source data."""

    radius = access_radius_m or settings.default_access_radius_m
    source: DatasetBundle = build_source_dataset(settings)
    areas = prepare_areas(source.areas, settings.analysis_crs)
    areas = calculate_risk_scores(areas, settings.weights)
    areas = calculate_accessibility(
        areas, source.shelters, radius_m=radius, analysis_crs=settings.analysis_crs
    )
    areas = refresh_priority_score(areas, settings.weights)
    areas, cluster_profiles = cluster_areas(areas)
    blindspots = build_blindspots(
        areas,
        source.shelters,
        radius_m=radius,
        threshold=risk_threshold,
        grid_size_m=blindspot_grid_m,
        analysis_crs=settings.analysis_crs,
    )
    metadata = dict(source.metadata)
    metadata.update(
        {
            "analysis_timestamp": datetime.now(UTC).isoformat(),
            "access_radius_m": radius,
            "risk_threshold": risk_threshold,
            "blindspot_grid_m": blindspot_grid_m,
            "cluster_profiles": cluster_profiles,
        }
    )
    return AnalysisArtifacts(
        areas=areas,
        shelters=source.shelters,
        citywide_shelters=source.citywide_shelters,
        candidates=source.candidates,
        blindspots=blindspots,
        cluster_profiles=cluster_profiles,
        metadata=metadata,
    )

