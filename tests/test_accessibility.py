from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from src.analysis.accessibility import (
    calculate_accessibility,
    calculate_grid_accessibility_by_dong,
    require_projected_crs,
)


def test_geographic_crs_rejected_for_meter_operation():
    frame = gpd.GeoDataFrame({"geometry": [Point(128.6, 35.8)]}, crs="EPSG:4326")
    with pytest.raises(ValueError, match="위경도 CRS"):
        require_projected_crs(frame)


def test_shelter_coverage_is_in_unit_interval(base_layers):
    areas, _ = base_layers
    assert areas["coverage_ratio"].between(0, 1).all()


def test_adding_candidate_never_reduces_coverage(base_layers):
    areas, shelters = base_layers
    addition = shelters.iloc[[0]].copy()
    addition["shelter_id"] = "S2"
    addition["geometry"] = Point(1_001_500, 1_800_500)
    combined = gpd.GeoDataFrame(
        pd.concat([shelters, addition], ignore_index=True), geometry="geometry", crs=shelters.crs
    )
    after = calculate_accessibility(areas, combined, radius_m=300)
    assert (after["coverage_ratio"] >= areas["coverage_ratio"] - 1e-12).all()





def test_grid_accessibility_averages_cell_center_scores(tmp_path):
    areas = gpd.GeoDataFrame(
        [{"adm_cd": "A", "adm_name": "테스트동", "geometry": box(0, 0, 200, 100)}],
        crs="EPSG:5179",
    )
    grid = gpd.GeoDataFrame(
        [
            {"GRID_CD": "G1", "geometry": box(0, 0, 100, 100)},
            {"GRID_CD": "G2", "geometry": box(100, 0, 200, 100)},
        ],
        crs="EPSG:5179",
    )
    grid_path = tmp_path / "grid.shp"
    grid.to_file(grid_path)
    population_path = tmp_path / "population.csv"
    population_path.write_text(
        "2024,G1,to_in_001,10\n2024,G2,to_in_001,30\n",
        encoding="cp949",
    )
    shelters = gpd.GeoDataFrame(
        [{"shelter_id": "S1", "geometry": Point(50, 50)}],
        crs="EPSG:5179",
    )

    result = calculate_grid_accessibility_by_dong(
        areas,
        shelters,
        grid_population_files=[population_path],
        grid_shape_files=[grid_path],
        d0_m=100.0,
        walk_limit_m=75.0,
    )

    expected_unweighted = (1.0 + np.exp(-1.0)) / 2.0
    expected_weighted = (10.0 * 1.0 + 30.0 * np.exp(-1.0)) / 40.0
    assert result.loc[0, "grid_cell_count"] == 2
    assert result.loc[0, "grid_accessibility_index"] == pytest.approx(expected_unweighted)
    assert result.loc[0, "grid_population_weighted_accessibility_index"] == pytest.approx(expected_weighted)
    assert result.loc[0, "grid_beyond_walk_limit_ratio"] == pytest.approx(0.5)
