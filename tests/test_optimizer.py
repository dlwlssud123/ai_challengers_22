from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Point, box

from src.analysis.optimizer import optimize_candidates, remove_existing_overlaps


def _optimizer_layers():
    candidates = gpd.GeoDataFrame(
        [
            {"candidate_id": "C1", "name": "후보1", "address": "", "facility_type": "공공", "cost": 10.0, "latitude": 0.0, "longitude": 0.0, "geometry": Point(1_000_000, 1_800_000)},
            {"candidate_id": "C2", "name": "후보2", "address": "", "facility_type": "공공", "cost": 10.0, "latitude": 0.0, "longitude": 0.0, "geometry": Point(1_000_100, 1_800_000)},
            {"candidate_id": "C3", "name": "후보3", "address": "", "facility_type": "공공", "cost": 12.0, "latitude": 0.0, "longitude": 0.0, "geometry": Point(1_002_000, 1_800_000)},
        ],
        crs="EPSG:5179",
    )
    blindspots = gpd.GeoDataFrame(
        [
            {"cell_id": "B1", "adm_name": "A동", "estimated_elderly": 100.0, "priority_score": 90.0, "nearest_shelter_distance": 800.0, "geometry": box(999_950, 1_799_950, 1_000_050, 1_800_050)},
            {"cell_id": "B2", "adm_name": "B동", "estimated_elderly": 60.0, "priority_score": 70.0, "nearest_shelter_distance": 900.0, "geometry": box(1_001_950, 1_799_950, 1_002_050, 1_800_050)},
        ],
        crs="EPSG:5179",
    )
    return candidates, blindspots


def test_optimizer_cost_is_within_budget():
    candidates, blindspots = _optimizer_layers()
    result = optimize_candidates(candidates, blindspots, budget=20, radius_m=250, prefer_pulp=True)
    assert result.total_cost <= 20


def test_optimizer_respects_maximum_facility_count():
    candidates, blindspots = _optimizer_layers()
    result = optimize_candidates(
        candidates,
        blindspots,
        budget=100,
        radius_m=250,
        max_facilities=1,
        prefer_pulp=False,
    )
    assert len(result.selected_candidate_ids) <= 1


def test_overlapping_candidates_do_not_double_count_population():
    candidates, blindspots = _optimizer_layers()
    result = optimize_candidates(candidates.iloc[:2], blindspots.iloc[:1], budget=20, radius_m=250, prefer_pulp=False)
    assert result.newly_covered_elderly == 100.0


def test_candidate_identical_to_existing_shelter_is_removed():
    candidates, _ = _optimizer_layers()
    shelters = gpd.GeoDataFrame(
        [{"shelter_id": "S1", "geometry": Point(1_000_000, 1_800_000)}], crs="EPSG:5179"
    )
    filtered = remove_existing_overlaps(candidates, shelters, minimum_distance_m=100)
    assert "C1" not in set(filtered["candidate_id"])
    assert "C3" in set(filtered["candidate_id"])

