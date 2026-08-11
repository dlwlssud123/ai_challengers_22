from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

from src.analysis.accessibility import calculate_accessibility
from src.analysis.preprocessing import prepare_areas
from src.analysis.risk import calculate_risk_scores, refresh_priority_score


@pytest.fixture
def base_layers():
    areas = gpd.GeoDataFrame(
        [
            {
                "adm_cd": "A",
                "adm_name": "A동",
                "population": 1_000,
                "elderly_population": 250,
                "temperature": 34.0,
                "humidity": 70.0,
                "geometry": box(1_000_000, 1_800_000, 1_001_000, 1_801_000),
            },
            {
                "adm_cd": "B",
                "adm_name": "B동",
                "population": 1_200,
                "elderly_population": 180,
                "temperature": 32.0,
                "humidity": 55.0,
                "geometry": box(1_001_000, 1_800_000, 1_002_000, 1_801_000),
            },
        ],
        crs="EPSG:5179",
    )
    shelters = gpd.GeoDataFrame(
        [
            {
                "shelter_id": "S1",
                "name": "기존쉼터",
                "address": "",
                "capacity": 50,
                "shelter_type": "복지관",
                "latitude": 0.0,
                "longitude": 0.0,
                "weekday_open": True,
                "weekend_open": False,
                "night_open": False,
                "geometry": Point(1_000_500, 1_800_500),
            }
        ],
        crs="EPSG:5179",
    )
    prepared = prepare_areas(areas)
    scored = calculate_risk_scores(prepared)
    accessible = calculate_accessibility(scored, shelters, radius_m=300)
    accessible = refresh_priority_score(accessible)
    return accessible, shelters


