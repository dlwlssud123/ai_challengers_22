from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from src.analysis.accessibility import calculate_accessibility, require_projected_crs


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


