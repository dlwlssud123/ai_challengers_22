from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from src.analysis.preprocessing import prepare_areas, safe_minmax
from src.analysis.risk import calculate_risk_scores


def test_safe_minmax_constant_is_finite_zero():
    normalized = safe_minmax(pd.Series([7.0, 7.0, 7.0]))
    assert normalized.tolist() == [0.0, 0.0, 0.0]
    assert np.isfinite(normalized).all()


def test_risk_scores_always_between_zero_and_one_hundred(base_layers):
    areas, _ = base_layers
    for column in ["heat_score", "vulnerability_score", "access_score", "priority_score"]:
        assert areas[column].between(0, 100).all()


def test_missing_values_do_not_break_scoring():
    raw = gpd.GeoDataFrame(
        [
            {
                "adm_cd": "X",
                "adm_name": "결측동",
                "population": None,
                "elderly_population": None,
                "temperature": None,
                "humidity": None,
                "geometry": box(1_000_000, 1_800_000, 1_001_000, 1_801_000),
            }
        ],
        crs="EPSG:5179",
    )
    scored = calculate_risk_scores(prepare_areas(raw))
    assert scored["priority_score"].notna().all()
    assert scored["priority_score"].between(0, 100).all()


def test_live_heat_score_contributes_absolute_hazard():
    raw = gpd.GeoDataFrame(
        [
            {
                "adm_cd": "A",
                "adm_name": "관측동",
                "population": 1000,
                "elderly_population": 200,
                "temperature": 30.0,
                "humidity": 60.0,
                "live_heat_score": 80.0,
                "geometry": box(1_000_000, 1_800_000, 1_001_000, 1_801_000),
            }
        ],
        crs="EPSG:5179",
    )

    scored = calculate_risk_scores(prepare_areas(raw))

    assert scored.iloc[0]["heat_score"] == 40.0

