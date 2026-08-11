from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Point, box

from src.ui.daegu_overview import merge_daegu_boundaries


def test_citywide_boundaries_keep_unanalyzed_regions_selectable():
    boundaries = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"adm_cd": "A", "adm_nm": "대구광역시 수성구 범어1동"},
                "geometry": {"type": "Polygon", "coordinates": []},
            },
            {
                "type": "Feature",
                "properties": {"adm_cd": "B", "adm_nm": "대구광역시 달서구 송현1동"},
                "geometry": {"type": "Polygon", "coordinates": []},
            },
        ],
    }
    areas = gpd.GeoDataFrame(
        [{
            "adm_cd": "A",
            "adm_name": "범어1동",
            "priority_score": 81.2,
            "heat_score": 70.0,
            "vulnerability_score": 80.0,
            "access_score": 90.0,
            "elderly_population": 1234,
            "geometry": box(128.6, 35.8, 128.61, 35.81),
        }],
        crs="EPSG:4326",
    )

    merged = merge_daegu_boundaries(boundaries, areas)
    analyzed, pending = [feature["properties"] for feature in merged["features"]]
    assert analyzed["has_analysis"] is True
    assert analyzed["priority_display"] == "81.2점"
    assert pending["has_analysis"] is False
    assert pending["adm_cd"] == "B"
    assert "분석 데이터 준비 중" in pending["analysis_status"]


def test_citywide_boundaries_use_team_district_results_and_shelter_counts():
    boundaries = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"adm_cd": "B", "adm_nm": "대구광역시 달서구 송현1동"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[128.60, 35.80], [128.61, 35.80], [128.61, 35.81], [128.60, 35.81], [128.60, 35.80]]],
            },
        }],
    }
    areas = gpd.GeoDataFrame(
        [{
            "adm_cd": "A", "adm_name": "범어1동", "priority_score": 81.2,
            "heat_score": 70.0, "vulnerability_score": 80.0, "access_score": 90.0,
            "elderly_population": 1234, "geometry": box(128.6, 35.8, 128.61, 35.81),
        }], crs="EPSG:4326"
    )
    team = [{
        "region_name": "달서구", "vulnerability_score": 54.3, "grade": "주의",
        "cluster": 2, "elderly_ratio": 15.2, "heat_illness_count": 28,
    }]

    citywide_shelters = gpd.GeoDataFrame(
        [{"shelter_id": "S1", "geometry": Point(128.605, 35.805)}], crs="EPSG:4326"
    )

    merged = merge_daegu_boundaries(boundaries, areas, team, citywide_shelters)
    result = merged["features"][0]["properties"]
    assert result["has_district_analysis"] is True
    assert result["priority_display"] == "59.1점"
    assert result["shelter_count"] == 1


def test_missing_citywide_shelter_data_is_not_reported_as_zero():
    boundaries = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"adm_cd": "B", "adm_nm": "대구광역시 달서구 송현1동"},
            "geometry": {"type": "Polygon", "coordinates": []},
        }],
    }
    areas = gpd.GeoDataFrame(
        [{
            "adm_cd": "A", "adm_name": "범어1동", "priority_score": 81.2,
            "heat_score": 70.0, "vulnerability_score": 80.0, "access_score": 90.0,
            "elderly_population": 1234, "geometry": box(128.6, 35.8, 128.61, 35.81),
        }], crs="EPSG:4326"
    )
    team = [{"region_name": "달서구", "vulnerability_score": 54.3, "grade": "주의", "cluster": 2}]

    result = merge_daegu_boundaries(
        boundaries, areas, team, citywide_shelters=None, include_dong_detail=False
    )["features"][0]["properties"]

    assert result["shelter_count"] is None
    assert result["shelter_display"] == "데이터 연결 필요"


def test_shelter_gap_heatmap_changes_by_dong_count():
    boundaries = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"adm_cd": "A", "adm_nm": "대구광역시 달서구 A동"},
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
            },
            {
                "type": "Feature",
                "properties": {"adm_cd": "B", "adm_nm": "대구광역시 달서구 B동"},
                "geometry": {"type": "Polygon", "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]]},
            },
        ],
    }
    areas = gpd.GeoDataFrame(
        [{
            "adm_cd": "X", "adm_name": "기준동", "priority_score": 50,
            "heat_score": 50, "vulnerability_score": 50, "access_score": 50,
            "elderly_population": 100, "geometry": box(0, 0, 1, 1),
        }], crs="EPSG:4326"
    )
    team = [{"region_name": "달서구", "vulnerability_score": 54.3, "grade": "주의", "cluster": 2}]
    shelters = gpd.GeoDataFrame(
        [
            {"shelter_id": "S1", "geometry": Point(0.2, 0.2)},
            {"shelter_id": "S2", "geometry": Point(0.4, 0.4)},
        ], crs="EPSG:4326"
    )

    merged = merge_daegu_boundaries(
        boundaries, areas, team, shelters, include_dong_detail=False, heatmap_metric="shelter_gap"
    )
    first, second = [feature["properties"] for feature in merged["features"]]

    assert first["shelter_count"] == 2
    assert second["shelter_count"] == 0
    assert first["map_score"] < second["map_score"]
    assert first["fill_color"] != second["fill_color"]


def test_dalseo_is_not_misclassified_as_seogu():
    boundaries = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"adm_cd": "B", "adm_nm": "대구광역시 달서구 송현1동"},
            "geometry": {"type": "Polygon", "coordinates": [[[128.60, 35.80], [128.61, 35.80], [128.61, 35.81], [128.60, 35.81], [128.60, 35.80]]]},
        }],
    }
    areas = gpd.GeoDataFrame(
        [{
            "adm_cd": "X", "adm_name": "기준동", "priority_score": 50,
            "heat_score": 50, "vulnerability_score": 50, "access_score": 50,
            "elderly_population": 100, "geometry": box(128.6, 35.8, 128.61, 35.81),
        }], crs="EPSG:4326"
    )
    team = [
        {"region_name": "서구", "vulnerability_score": 31.1, "grade": "보통", "cluster": 0},
        {"region_name": "달서구", "vulnerability_score": 54.3, "grade": "주의", "cluster": 2},
    ]

    result = merge_daegu_boundaries(
        boundaries, areas, team, citywide_shelters=None, include_dong_detail=False
    )["features"][0]["properties"]

    assert result["district_name"] == "달서구"
    assert abs(result["vulnerability_score"] - 79.085) < 1e-2
