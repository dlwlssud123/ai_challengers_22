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
    assert result["priority_display"] == "54.3점"
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
