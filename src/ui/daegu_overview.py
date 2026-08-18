"""Merge the live SGIS Daegu boundaries with available district analysis."""

from __future__ import annotations

from copy import deepcopy
import glob
import os
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape
from src.analysis.accessibility import calculate_accessibility, calculate_grid_accessibility_by_dong


PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

POPULATION_CSV = os.path.join(
    PROJECT_ROOT_DIR,
    "data",
    "raw",
    "daegu_dong_population_202607.csv"
)
GRID_POPULATION_FILES = tuple(sorted(glob.glob(os.path.join(
    PROJECT_ROOT_DIR,
    "data",
    "_census_reqdoc_1787027603696",
    "2024년_인구_*_100M.csv",
))))
GRID_SHAPE_FILES = tuple(sorted(glob.glob(os.path.join(
    PROJECT_ROOT_DIR,
    "data",
    "_grid_border_grid_2025_grid_*",
    "grid_*_100M.shp",
))))


def normalize_administrative_name(value: Any) -> str:
    return (
        str(value or "")
        .replace(" ", "")
        .replace("·", "")
        .replace("ㆍ", "")
        .replace(".", "")
        .replace("・", "")
    )


def _load_population_lookup() -> dict[str, dict]:
    lookup = {}
    if not os.path.exists(POPULATION_CSV):
        return lookup
    try:
        df = pd.read_csv(POPULATION_CSV, encoding="utf-8")
        for row in df.itertuples():
            district = str(row.district_name).strip()
            dong = str(row.adm_name).strip()
            key = normalize_administrative_name(district + dong)
            lookup[key] = {
                "population": int(row.population),
                "elderly_population": int(row.elderly_population_60_plus),
                "elderly_ratio": float(row.elderly_ratio_60_plus) * 100
            }
    except Exception:
        pass
    return lookup


GREENERY_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "raw",
    "daegu_dong_green_ratio.csv"
)


def _load_greenery_lookup() -> dict[str, float]:
    lookup = {}
    if not os.path.exists(GREENERY_CSV):
        return lookup
    try:
        df = pd.read_csv(GREENERY_CSV, encoding="utf-8")
        for row in df.itertuples():
            district = str(row.district_name).strip()
            dong = str(row.adm_name).strip()
            key = normalize_administrative_name(district + dong)
            lookup[key] = float(row.green_ratio_percent)
    except Exception:
        pass
    return lookup


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
    pop_lookup = _load_population_lookup()
    greenery_lookup = _load_greenery_lookup()
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

    # 대구 전역 실시간 쉼터 접근성 지리 연산 복구
    access_lookup = {}
    if result and citywide_shelters is not None and not citywide_shelters.empty:
        try:
            features = result.get("features", [])
            gdf_boundaries = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
            
            # 실제 고령인구와 인구수 주입
            elderly_pops = []
            pops = []
            for feat in features:
                props = feat.get("properties") or {}
                api_n = str(props.get("adm_nm") or props.get("region") or props.get("adm_name") or "")
                norm_n = normalize_administrative_name(api_n)
                pm = None
                for k, v in pop_lookup.items():
                    if k in norm_n or norm_n in k:
                        pm = v
                        break
                elderly_pops.append(float(pm["elderly_population"]) if pm else 0.0)
                pops.append(float(pm["population"]) if pm else 0.0)
                
            gdf_boundaries["elderly_population"] = elderly_pops
            gdf_boundaries["population"] = pops
            
            gdf_access = calculate_accessibility(
                gdf_boundaries,
                citywide_shelters,
                radius_m=500.0,
                analysis_crs="EPSG:5179"
            )
            grid_access_lookup = {}
            if GRID_POPULATION_FILES and GRID_SHAPE_FILES:
                try:
                    gdf_grid_access = calculate_grid_accessibility_by_dong(
                        gdf_boundaries,
                        citywide_shelters,
                        grid_population_files=GRID_POPULATION_FILES,
                        grid_shape_files=GRID_SHAPE_FILES,
                        d0_m=300.0,
                        walk_limit_m=500.0,
                        analysis_crs="EPSG:5179",
                    )
                    for row in gdf_grid_access.itertuples():
                        grid_access_lookup[str(row.adm_cd)] = {
                            "grid_cell_count": int(row.grid_cell_count),
                            "grid_population": float(row.grid_population),
                            "grid_accessibility_index": float(row.grid_accessibility_index),
                            "grid_accessibility_lack_score": float(row.grid_accessibility_lack_score),
                            "grid_population_weighted_accessibility_index": float(
                                row.grid_population_weighted_accessibility_index
                            ),
                            "grid_population_weighted_accessibility_lack_score": float(
                                row.grid_population_weighted_accessibility_lack_score
                            ),
                            "grid_mean_nearest_shelter_distance": float(row.grid_mean_nearest_shelter_distance),
                            "grid_beyond_walk_limit_ratio": float(row.grid_beyond_walk_limit_ratio),
                        }
                except Exception:
                    grid_access_lookup = {}
            for row in gdf_access.itertuples():
                access_lookup[str(row.adm_cd)] = {
                    "coverage_ratio": float(row.coverage_ratio),
                    "nearest_shelter_distance": float(row.nearest_shelter_distance),
                    **grid_access_lookup.get(str(row.adm_cd), {}),
                }
        except Exception:
            pass

    # 1. 대구 150개 동별 고령인구 및 쉼터 공급 능력 사전 집계
    elderly_list = []
    raw_supplies = {}
    raw_supplies_list = []

    for feature in result.get("features", []):
        original = feature.get("properties") or {}
        adm_cd = str(original.get("adm_cd") or "-")
        api_name = str(original.get("adm_nm") or original.get("region") or original.get("adm_name") or "행정동명 없음")
        normalized_api_name = normalize_administrative_name(api_name)
        
        # 쉼터 수
        raw_sc = dong_shelter_counts.get(adm_cd) if shelter_counts_available else None
        shelter_count = int(raw_sc) if raw_sc is not None else 0
        
        # 고령인구 룩업
        pop_match = None
        for key, val in pop_lookup.items():
            if key in normalized_api_name or normalized_api_name in key:
                pop_match = val
                break
        
        elderly_pop = pop_match["elderly_population"] if pop_match else 0
        if elderly_pop <= 0:
            match_check = next((values for k, values in lookup.items() if normalized_api_name.endswith(k) or k.endswith(normalized_api_name)), None)
            if match_check:
                elderly_pop = match_check.get("elderly_population", 0)
                
        elderly_list.append(int(elderly_pop))
        elderly_pop_safe = max(int(elderly_pop), 1)
        raw_supply = (shelter_count / elderly_pop_safe) * 1000.0
        raw_supplies[adm_cd] = raw_supply
        raw_supplies_list.append(raw_supply)
        
    min_supply = min(raw_supplies_list, default=0.0)
    max_supply = max(raw_supplies_list, default=1.0)
    min_elderly = min(elderly_list, default=0)
    max_elderly = max(elderly_list, default=1)

    # 2. 메인 루프 돌며 속성 결합 및 통합 취약도 계산
    for feature in result.get("features", []):
        original = feature.get("properties") or {}
        api_name = str(
            original.get("adm_nm")
            or original.get("region")
            or original.get("adm_name")
            or "행정동명 없음"
        )
        normalized_api_name = normalize_administrative_name(api_name)
        
        # 고령인구 룩업 매치
        pop_match = None
        for key, val in pop_lookup.items():
            if key in normalized_api_name or normalized_api_name in key:
                pop_match = val
                break

        # 녹지율 룩업
        green_ratio = 15.0
        for gk, gv in greenery_lookup.items():
            if gk in normalized_api_name or normalized_api_name in gk:
                green_ratio = gv
                break

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
        
        # 고령인구 1천명당 쉼터 수 접근성 공급 점수 (Min-Max 정규화 0~100점)
        raw_sup = raw_supplies.get(adm_cd, 0.0)
        if max_supply == min_supply:
            supply_score = 100.0 if max_supply > 0.0 else 0.0
        else:
            supply_score = 100.0 * (raw_sup - min_supply) / (max_supply - min_supply)
            
        shelter_accessibility_display = f"{supply_score:.1f}점"

        # 인구 정보 포맷팅
        pop_val = pop_match["population"] if pop_match else None
        elderly_val = pop_match["elderly_population"] if pop_match else 0
        elderly_ratio_val = pop_match["elderly_ratio"] if pop_match else 0.0
        elderly_display_str = f"{elderly_val:,}명 ({elderly_ratio_val:.1f}%)" if pop_match else "데이터 연결 필요"

        # 쉼터 갯수
        raw_sc = dong_shelter_counts.get(adm_cd) if shelter_counts_available else None
        shelter_count = int(raw_sc) if raw_sc is not None else None

        # 1) 폭염 위험 (25%)
        live_heat = float(live_heat_score) if live_heat_score is not None else 50.0
        
        # 2) 60세 이상 인구 취약성 (25%)
        if max_elderly == min_elderly:
            elderly_score = 100.0 if max_elderly > 0 else 0.0
        else:
            elderly_score = 100.0 * (elderly_val - min_elderly) / (max_elderly - min_elderly)
            
        # 3) 녹지 부족 (15%)
        greenery_lack_score = np.clip(100.0 - green_ratio, 0.0, 100.0)
        
        # 4) 고령인구 대비 쉼터 공급 부족 (20%)
        supply_lack_score = 100.0 - supply_score
        
        # 5) 쉼터 공간 접근성 부족 (15%)
        acc_data = access_lookup.get(adm_cd, {"coverage_ratio": 0.0, "nearest_shelter_distance": float("nan")})
        coverage_ratio = acc_data["coverage_ratio"]
        accessibility_lack_score = float(
            acc_data.get("grid_accessibility_lack_score", 100.0 * (1.0 - coverage_ratio))
        )

        # 동별 종합 취약도 연산
        total_vulnerability = (
            0.25 * live_heat +
            0.25 * elderly_score +
            0.15 * greenery_lack_score +
            0.20 * supply_lack_score +
            0.15 * accessibility_lack_score
        )

        distance_val = acc_data["nearest_shelter_distance"]
        distance_str = f"{distance_val:.0f}m" if not np.isnan(distance_val) else "쉼터 없음"
        grid_mean_distance = acc_data.get("grid_mean_nearest_shelter_distance", float("nan"))
        grid_distance_str = f"{grid_mean_distance:.0f}m" if not np.isnan(grid_mean_distance) else "격자 데이터 없음"
        grid_accessibility_display = (
            f"{acc_data['grid_accessibility_index']*100:.1f}%"
            if "grid_accessibility_index" in acc_data else "격자 데이터 없음"
        )

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
                "elderly_population": elderly_val or match["elderly_population"],
                "elderly_display": elderly_display_str if pop_match else f"{match['elderly_population']:,}명",
                "heat_score": match.get("heat_score", live_heat),
                "vulnerability_score": match["vulnerability_score"],
                "vulnerability_display": f"{match['vulnerability_score']:.1f}점",
                "access_score": match.get("access_score", supply_score),
                "fill_color": _score_color(score),
                "line_color": [255, 255, 255, 220],
                "coverage_ratio_display": f"{coverage_ratio*100:.1f}%",
                "nearest_shelter_distance_display": distance_str,
                "shelter_accessibility_score": supply_score,
                "shelter_accessibility_display": shelter_accessibility_display,
                "grid_accessibility_index": acc_data.get("grid_accessibility_index"),
                "grid_accessibility_display": grid_accessibility_display,
                "grid_accessibility_lack_score": accessibility_lack_score,
                "grid_mean_nearest_shelter_distance_display": grid_distance_str,
                "grid_cell_count": acc_data.get("grid_cell_count", 0),
                "grid_beyond_walk_limit_ratio": acc_data.get("grid_beyond_walk_limit_ratio"),
            }
        elif district_match:
            district_name, district = district_match
            properties = {
                "region": api_name,
                "adm_name": api_name,
                "adm_cd": adm_cd,
                "has_analysis": False,
                "has_district_analysis": True,
                "analysis_status": f"{district.get('region_name')} 구·군 단위 팀 분석",
                "district_name": str(district.get("region_name") or "-"),
                "priority_score": total_vulnerability,
                "priority_display": f"{total_vulnerability:.1f}점",
                "district_grade": str(district.get("grade") or "-"),
                "district_cluster": int(district.get("cluster") or 0),
                "elderly_ratio": elderly_ratio_val if elderly_ratio_val > 0.0 else float(district.get("elderly_ratio") or 0),
                "heat_illness_count": float(district.get("heat_illness_count") or 0),
                "shelter_count": shelter_count,
                "shelter_count_available": shelter_counts_available and shelter_count is not None,
                "shelter_display": f"{shelter_count:,}곳" if shelter_count is not None else "데이터 연결 필요",
                "elderly_population": elderly_val,
                "elderly_display": elderly_display_str,
                "heat_score": live_heat,
                "vulnerability_score": total_vulnerability,
                "vulnerability_display": f"{total_vulnerability:.1f}점",
                "live_heat_score": live_heat_score,
                "access_score": supply_score,
                "fill_color": _score_color(total_vulnerability),
                "line_color": [255, 255, 255, 180],
                "coverage_ratio_display": f"{coverage_ratio*100:.1f}%",
                "nearest_shelter_distance_display": distance_str,
                "shelter_accessibility_score": supply_score,
                "shelter_accessibility_display": shelter_accessibility_display,
                "grid_accessibility_index": acc_data.get("grid_accessibility_index"),
                "grid_accessibility_display": grid_accessibility_display,
                "grid_accessibility_lack_score": accessibility_lack_score,
                "grid_mean_nearest_shelter_distance_display": grid_distance_str,
                "grid_cell_count": acc_data.get("grid_cell_count", 0),
                "grid_beyond_walk_limit_ratio": acc_data.get("grid_beyond_walk_limit_ratio"),
            }
        else:
            properties = {
                "region": api_name,
                "adm_name": api_name,
                "adm_cd": adm_cd,
                "has_analysis": False,
                "has_district_analysis": False,
                "analysis_status": "행정경계만 연결 · 분석 데이터 준비 중",
                "priority_score": total_vulnerability,
                "priority_display": f"{total_vulnerability:.1f}점",
                "elderly_population": elderly_val,
                "elderly_display": elderly_display_str,
                "heat_score": live_heat,
                "vulnerability_score": total_vulnerability,
                "vulnerability_display": f"{total_vulnerability:.1f}점",
                "access_score": supply_score,
                "fill_color": [100, 116, 139, 55],
                "line_color": [100, 116, 139, 170],
                "coverage_ratio_display": f"{coverage_ratio*100:.1f}%",
                "nearest_shelter_distance_display": distance_str,
                "shelter_accessibility_score": supply_score,
                "shelter_accessibility_display": shelter_accessibility_display,
                "grid_accessibility_index": acc_data.get("grid_accessibility_index"),
                "grid_accessibility_display": grid_accessibility_display,
                "grid_accessibility_lack_score": accessibility_lack_score,
                "grid_mean_nearest_shelter_distance_display": grid_distance_str,
                "grid_cell_count": acc_data.get("grid_cell_count", 0),
                "grid_beyond_walk_limit_ratio": acc_data.get("grid_beyond_walk_limit_ratio"),
            }
        feature["properties"] = properties

    for feature in result.get("features", []):
        properties = feature.get("properties") or {}
        if heatmap_metric == "shelter_coverage":
            map_score = 0.0
            label = "쉼터 300m 커버 범위"
            properties["fill_color"] = [163, 163, 163, 45]  # 연한 중성 회색 반투명 배경
        else:
            map_score = properties.get("priority_score")
            label = "종합 취약도"
            properties["fill_color"] = _score_color(float(map_score)) if map_score is not None else [100, 116, 139, 55]
            
        properties["map_metric_label"] = label
        properties["map_score"] = float(map_score) if map_score is not None else None
        properties["map_score_display"] = f"{float(map_score):.1f}점" if map_score is not None and heatmap_metric != "shelter_coverage" else "배경"
    return result
