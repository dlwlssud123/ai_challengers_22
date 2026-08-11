"""Merge the live SGIS Daegu boundaries with available district analysis."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import geopandas as gpd
import numpy as np
from shapely.geometry import shape
from src.analysis.accessibility import calculate_accessibility


def normalize_administrative_name(value: Any) -> str:
    return (
        str(value or "")
        .replace(" ", "")
        .replace("·", "")
        .replace("ㆍ", "")
        .replace(".", "")
        .replace("・", "")
    )


def _score_color(score: float) -> list[int]:
    if score >= 85:
        return [220, 38, 38, 200]
    if score >= 70:
        return [249, 115, 22, 190]
    if score >= 50:
        return [250, 204, 21, 175]
    return [44, 123, 182, 160]


def _analysis_lookup(areas: gpd.GeoDataFrame) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in areas.to_crs("EPSG:4326").itertuples():
        rows[normalize_administrative_name(row.adm_name)] = {
            "adm_cd": str(row.adm_cd),
            "adm_name": str(row.adm_name),
            "priority_score": float(row.priority_score),
            "heat_score": float(row.heat_score),
            "vulnerability_score": float(row.vulnerability_score),
            "access_score": float(row.access_score),
            "elderly_population": int(round(float(row.elderly_population))),
        }
    return rows


def count_shelters_by_boundary(
    boundaries: dict,
    shelters: gpd.GeoDataFrame | None,
) -> dict[str, int] | None:
    """Count point shelters inside each SGIS administrative-dong polygon."""

    if shelters is None or shelters.crs is None:
        return None
    points = shelters.to_crs("EPSG:4326")
    counts: dict[str, int] = {}
    valid_geometry_seen = False
    for feature in boundaries.get("features", []):
        properties = feature.get("properties") or {}
        adm_cd = str(properties.get("adm_cd") or "")
        geometry_data = feature.get("geometry")
        if not adm_cd or not geometry_data:
            continue
        try:
            polygon = shape(geometry_data)
        except (TypeError, ValueError):
            continue
        if polygon.is_empty:
            continue
        valid_geometry_seen = True
        counts[adm_cd] = int(points.geometry.within(polygon).sum())
    return counts if valid_geometry_seen else None


def merge_daegu_boundaries(
    boundaries: dict | None,
    areas: gpd.GeoDataFrame,
    team_vulnerability: list[dict[str, Any]] | None = None,
    citywide_shelters: gpd.GeoDataFrame | None = None,
    live_heat_score: float | None = None,
    include_dong_detail: bool = True,
    heatmap_metric: str = "policy",
) -> dict:
    """Return a selectable citywide layer with dong- or district-level analysis."""

    lookup = _analysis_lookup(areas) if include_dong_detail else {}
    district_lookup = {
        normalize_administrative_name(row.get("region_name")): row
        for row in (team_vulnerability or [])
        if row.get("region_name")
    }
    if boundaries and boundaries.get("features"):
        result = deepcopy(boundaries)
    else:
        result = {
            "type": "FeatureCollection",
            "features": list(areas.to_crs("EPSG:4326").__geo_interface__["features"]),
        }
    dong_shelter_counts = count_shelters_by_boundary(result, citywide_shelters)
    shelter_counts_available = dong_shelter_counts is not None
    dong_shelter_counts = dong_shelter_counts or {}

    # 대구 전역 실시간 쉼터 접근성 지리 연산
    access_lookup = {}
    if result and citywide_shelters is not None and not citywide_shelters.empty:
        try:
            features = result.get("features", [])
            gdf_boundaries = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
            
            # 가상 인구 주입으로 calculate_accessibility 실행 가능화
            gdf_boundaries["elderly_population"] = 1.0
            gdf_boundaries["population"] = 1.0
            
            gdf_access = calculate_accessibility(
                gdf_boundaries,
                citywide_shelters,
                radius_m=500.0, # 기본 대피 반경 500m
                analysis_crs="EPSG:5179"
            )
            for row in gdf_access.itertuples():
                access_lookup[str(row.adm_cd)] = {
                    "coverage_ratio": float(row.coverage_ratio),
                    "nearest_shelter_distance": float(row.nearest_shelter_distance),
                }
        except Exception:
            pass

    for feature in result.get("features", []):
        original = feature.get("properties") or {}
        api_name = str(
            original.get("adm_nm")
            or original.get("region")
            or original.get("adm_name")
            or "행정동명 없음"
        )
        normalized_api_name = normalize_administrative_name(api_name)
        match = next(
            (
                values
                for normalized_name, values in lookup.items()
                if normalized_api_name.endswith(normalized_name)
                or normalized_name.endswith(normalized_api_name)
            ),
            None,
        )
        district_match = next(
            (
                (district_name, values)
                for district_name, values in sorted(
                    district_lookup.items(), key=lambda item: len(item[0]), reverse=True
                )
                if district_name and district_name in normalized_api_name
            ),
            None,
        )
        adm_cd = str(original.get("adm_cd") or (match or {}).get("adm_cd") or "-")
        
        # 접근성 지표 추출
        acc_data = access_lookup.get(adm_cd, {"coverage_ratio": 0.0, "nearest_shelter_distance": float("nan")})
        coverage_pct = acc_data["coverage_ratio"] * 100
        distance_val = acc_data["nearest_shelter_distance"]
        distance_str = f"{distance_val:.0f}m" if not np.isnan(distance_val) else "쉼터 없음"

        if match:
            score = match["priority_score"]
            properties = {
                "region": api_name,
                "adm_name": match["adm_name"],
                "adm_cd": adm_cd,
                "has_analysis": True,
                "analysis_status": "수성구 상세 분석 연결",
                "priority_score": score,
                "priority_display": f"{score:.1f}점",
                "elderly_population": match["elderly_population"],
                "elderly_display": f"{match['elderly_population']:,}명",
                "heat_score": match["heat_score"],
                "vulnerability_score": match["vulnerability_score"],
                "access_score": match["access_score"],
                "fill_color": _score_color(score),
                "line_color": [255, 255, 255, 220],
                "coverage_ratio_display": f"{coverage_pct:.1f}%",
                "nearest_shelter_distance_display": distance_str,
            }
        elif district_match:
            district_name, district = district_match
            vulnerability_score = float(district.get("vulnerability_score") or 0)
            score = (
                0.65 * vulnerability_score + 0.35 * float(live_heat_score)
                if live_heat_score is not None
                else vulnerability_score
            )
            raw_shelter_count = dong_shelter_counts.get(adm_cd)
            shelter_count = int(raw_shelter_count) if raw_shelter_count is not None else None
            properties = {
                "region": api_name,
                "adm_name": api_name,
                "adm_cd": adm_cd,
                "has_analysis": False,
                "has_district_analysis": True,
                "analysis_status": f"{district.get('region_name')} 구·군 단위 팀 분석",
                "district_name": str(district.get("region_name") or "-"),
                "priority_score": score,
                "priority_display": f"{score:.1f}점",
                "district_grade": str(district.get("grade") or "-"),
                "district_cluster": int(district.get("cluster") or 0),
                "elderly_ratio": float(district.get("elderly_ratio") or 0),
                "heat_illness_count": float(district.get("heat_illness_count") or 0),
                "shelter_count": shelter_count,
                "shelter_count_available": shelter_counts_available and shelter_count is not None,
                "shelter_display": f"{shelter_count:,}곳" if shelter_count is not None else "데이터 연결 필요",
                "elderly_population": None,
                "elderly_display": "구·군 결과 참조",
                "heat_score": None,
                "vulnerability_score": vulnerability_score,
                "vulnerability_display": f"{vulnerability_score:.1f}점",
                "live_heat_score": live_heat_score,
                "access_score": None,
                "fill_color": _score_color(score),
                "line_color": [255, 255, 255, 180],
                "coverage_ratio_display": f"{coverage_pct:.1f}%",
                "nearest_shelter_distance_display": distance_str,
            }
        else:
            properties = {
                "region": api_name,
                "adm_name": api_name,
                "adm_cd": adm_cd,
                "has_analysis": False,
                "has_district_analysis": False,
                "analysis_status": "행정경계만 연결 · 분석 데이터 준비 중",
                "priority_score": None,
                "priority_display": "분석 전",
                "elderly_population": None,
                "elderly_display": "데이터 미연결",
                "heat_score": None,
                "vulnerability_score": None,
                "access_score": None,
                "fill_color": [100, 116, 139, 55],
                "line_color": [100, 116, 139, 170],
                "coverage_ratio_display": f"{coverage_pct:.1f}%",
                "nearest_shelter_distance_display": distance_str,
            }
        feature["properties"] = properties

    available_counts = [
        int((feature.get("properties") or {}).get("shelter_count"))
        for feature in result.get("features", [])
        if (feature.get("properties") or {}).get("shelter_count") is not None
    ]
    maximum_count = max(available_counts, default=0)
    minimum_count = min(available_counts, default=0)
    for feature in result.get("features", []):
        properties = feature.get("properties") or {}
        if heatmap_metric == "vulnerability":
            map_score = properties.get("vulnerability_score")
            label = "사회·건강 취약도"
        elif heatmap_metric == "shelter_gap":
            count = properties.get("shelter_count")
            if count is None:
                map_score = None
            elif maximum_count == minimum_count:
                map_score = 0.0
            else:
                map_score = 100.0 * (maximum_count - int(count)) / (maximum_count - minimum_count)
            label = "쉼터 수 부족도"
        else:
            map_score = properties.get("priority_score")
            label = "극한폭염 정책 우선순위"
        properties["map_metric_label"] = label
        properties["map_score"] = float(map_score) if map_score is not None else None
        properties["map_score_display"] = f"{float(map_score):.1f}점" if map_score is not None else "데이터 없음"
        properties["fill_color"] = _score_color(float(map_score)) if map_score is not None else [100, 116, 139, 55]
    return result
