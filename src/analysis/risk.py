"""Explainable heat-hazard and vulnerability scoring."""

from __future__ import annotations

import geopandas as gpd

from src.analysis.preprocessing import safe_minmax
from src.config import ScoreWeights


def calculate_risk_scores(
    areas: gpd.GeoDataFrame, weights: ScoreWeights | None = None
) -> gpd.GeoDataFrame:
    """Calculate policy-priority subscores on a 0–100 scale.

    The score is not a disease probability or medical diagnosis.
    """

    weights = weights or ScoreWeights()
    result = areas.copy()
    norm_temperature = safe_minmax(result["temperature"])
    norm_humidity = safe_minmax(result["humidity"])
    norm_elderly_ratio = safe_minmax(result["elderly_ratio"])
    norm_elderly_density = safe_minmax(result["elderly_density"])
    result["heat_score"] = 100 * (
        weights.temperature * norm_temperature + weights.humidity * norm_humidity
    )
    result["vulnerability_score"] = 100 * (
        weights.elderly_ratio * norm_elderly_ratio
        + weights.elderly_density * norm_elderly_density
    )
    if "access_score" not in result:
        result["access_score"] = 0.0
    result["priority_score"] = (
        weights.heat * result["heat_score"]
        + weights.vulnerability * result["vulnerability_score"]
        + weights.access * result["access_score"]
    ).clip(0, 100)
    return result


def refresh_priority_score(
    areas: gpd.GeoDataFrame, weights: ScoreWeights | None = None
) -> gpd.GeoDataFrame:
    """Recalculate the final score after access analysis updates access_score."""

    weights = weights or ScoreWeights()
    result = areas.copy()
    result["priority_score"] = (
        weights.heat * result["heat_score"]
        + weights.vulnerability * result["vulnerability_score"]
        + weights.access * result["access_score"]
    ).clip(0, 100)
    return result


