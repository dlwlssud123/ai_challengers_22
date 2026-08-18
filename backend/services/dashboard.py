from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.alan_client import AlanPolicyClient
from src.analysis.district_allocation import allocate_facilities_by_priority
from src.config import PROCESSED_DIR, Settings
from src.data.loader import build_source_dataset
from src.data.shades import load_shades as load_shade_layer
from src.sgis_client import SGISClient

SUMMARY_CSV = PROCESSED_DIR / "daegu_all_dong_accessibility_summary.csv"
FUTURE_RISK_CSV = PROCESSED_DIR / "daegu_future_heat_illness_risk_2030.csv"
FACILITY_SHORTAGE_CSV = PROCESSED_DIR / "daegu_response_facility_shortage_by_admin_dong_2026-08-18.csv"


def normalize_name(value: Any) -> str:
    return (
        str(value or "")
        .replace(" ", "")
        .replace("·", "")
        .replace("ㆍ", "")
        .replace(".", "")
        .replace("・", "")
    )


def get_summary_csv_path() -> Path:
    if not SUMMARY_CSV.exists():
        raise FileNotFoundError(f"행정동 요약 CSV가 없습니다: {SUMMARY_CSV}")
    return SUMMARY_CSV


@lru_cache(maxsize=1)
def load_summary_records() -> list[dict[str, Any]]:
    frame = pd.read_csv(get_summary_csv_path(), encoding="utf-8-sig")
    frame = frame.replace({np.nan: None})
    return frame.to_dict("records")


@lru_cache(maxsize=1)
def load_future_risk_records() -> dict[str, dict[str, Any]]:
    if not FUTURE_RISK_CSV.exists():
        return {}
    frame = pd.read_csv(FUTURE_RISK_CSV, encoding="utf-8-sig")
    frame = frame.replace({np.nan: None})
    records: dict[str, dict[str, Any]] = {}
    for row in frame.to_dict("records"):
        code = str(row.get("행정동코드") or "").replace(".0", "")
        if not code:
            continue
        records[code] = {
            "future_heat_rank": row.get("발생률순위"),
            "future_heat_incidence_per_10k": row.get("미래 발생률(/1만명)"),
            "future_heat_risk_score": row.get("위험지수"),
            "future_heat_risk_grade": row.get("위험등급"),
            "future_expected_patients": row.get("예상환자수(명)"),
            "future_risk_confidence": row.get("신뢰도"),
            "future_risk_confidence_grade": row.get("신뢰등급"),
            "future_main_driver_1": row.get("주동인1"),
            "future_driver_contribution_1": row.get("기여도1"),
            "future_main_driver_2": row.get("주동인2"),
            "future_driver_contribution_2": row.get("기여도2"),
            "future_max_heat_index_c": row.get("최고 열지수 대체치(℃)"),
            "future_heatwave_days": row.get("폭염일수"),
            "future_strong_heatwave_days": row.get("강한폭염일수"),
            "future_tropical_night_days": row.get("열대야일수"),
            "future_max_heat_streak_days": row.get("최대연속폭염일"),
            "future_cumulative_heat_burden": row.get("누적열부담"),
            "future_climate_unit": row.get("RDA 기후단위"),
            "future_substitution_note": row.get("대체처리 요약"),
        }
    return records


@lru_cache(maxsize=1)
def load_facility_shortage_records() -> dict[str, dict[str, Any]]:
    if not FACILITY_SHORTAGE_CSV.exists():
        return {}
    frame = pd.read_csv(FACILITY_SHORTAGE_CSV, encoding="utf-8-sig")
    frame = frame.replace({np.nan: None})
    records: dict[str, dict[str, Any]] = {}
    for row in frame.to_dict("records"):
        code = str(row.get("행정동코드") or "").replace(".0", "")
        if not code:
            continue
        records[code] = {
            "facility_shortage_rank": row.get("대응시설부족도순위"),
            "future_heat_risk_from_shortage": row.get("미래온열질환위험"),
            "local_vulnerability_from_shortage": row.get("지역취약도"),
            "protection_need_score": row.get("보호필요도"),
            "facility_response_score": row.get("시설대응력"),
            "facility_gap_score": row.get("시설대응력부족분(100-시설대응력)"),
            "facility_shortage_score": row.get("대응시설부족도"),
            "facility_model_note": row.get("시설대응력종합모형"),
            "shade_data_status": row.get("그늘막자료상태"),
            "facility_warning_note": row.get("시설대응력대체처리·주의"),
        }
    return records


def enrich_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    future_records = load_future_risk_records()
    facility_records = load_facility_shortage_records()
    enriched = []
    for record in records:
        code = str(record.get("resident_adm_code") or "").replace(".0", "")
        merged = dict(record)
        merged.update(future_records.get(code, {}))
        merged.update(facility_records.get(code, {}))
        enriched.append(merged)
    return enriched


@lru_cache(maxsize=1)
def load_boundaries() -> dict:
    return SGISClient(timeout=30.0).get_administrative_boundaries(
        adm_cd="22", year=2025, low_search=2
    )


@lru_cache(maxsize=1)
def load_district_boundaries() -> dict:
    """구·군 경계 (low_search=1). DaeguShelterMap에 필요한 district_name/label 좌표를 주입한다."""
    raw = SGISClient(timeout=30.0).get_administrative_boundaries(
        adm_cd="22", year=2025, low_search=1
    )
    features = []
    for feature in raw.get("features", []):
        props = dict(feature.get("properties") or {})
        adm_nm: str = str(props.get("adm_nm") or "")
        # 구·군 이름만 추출 (마지막 토큰)
        district_name = adm_nm.split()[-1] if adm_nm.strip() else adm_nm
        # centroid 계산 (좌표 평균)
        try:
            coords = feature.get("geometry", {}).get("coordinates", [])
            geom_type = feature.get("geometry", {}).get("type", "")
            all_pts: list[list[float]] = []
            if geom_type == "Polygon":
                all_pts = coords[0] if coords else []
            elif geom_type == "MultiPolygon":
                for poly in coords:
                    all_pts.extend(poly[0] if poly else [])
            if all_pts:
                lons = [p[0] for p in all_pts if len(p) >= 2]
                lats = [p[1] for p in all_pts if len(p) >= 2]
                label_lat = sum(lats) / len(lats)
                label_lon = sum(lons) / len(lons)
            else:
                label_lat = label_lon = 0.0
        except Exception:
            label_lat = label_lon = 0.0
        props["district_name"] = district_name
        props["label_latitude"] = label_lat
        props["label_longitude"] = label_lon
        copied = dict(feature)
        copied["properties"] = props
        features.append(copied)
    return {"type": "FeatureCollection", "features": features}


@lru_cache(maxsize=1)
def load_city_boundary() -> dict:
    """대구 전체 외곽 경계 (low_search=0)."""
    return SGISClient(timeout=30.0).get_administrative_boundaries(
        adm_cd="22", year=2025, low_search=0
    )


def _points_to_records(points) -> list[dict[str, Any]]:
    frame = pd.DataFrame(points.drop(columns="geometry", errors="ignore"))
    frame["longitude"] = points.geometry.x
    frame["latitude"] = points.geometry.y
    frame = frame.replace({np.nan: None})
    return frame.to_dict("records")


@lru_cache(maxsize=1)
def load_shelters() -> list[dict[str, Any]]:
    source = build_source_dataset(Settings.from_env())
    shelters = source.citywide_shelters.to_crs("EPSG:4326")
    return _points_to_records(shelters)


@lru_cache(maxsize=1)
def load_shades() -> list[dict[str, Any]]:
    shades = load_shade_layer(Settings.from_env()).to_crs("EPSG:4326")
    return _points_to_records(shades)


def score_color(score: float | None) -> list[int]:
    if score is None:
        return [100, 116, 139, 70]
    if score >= 85:
        return [220, 38, 38, 205]
    if score >= 70:
        return [249, 115, 22, 195]
    if score >= 50:
        return [250, 204, 21, 180]
    return [44, 123, 182, 170]


def access_color(index: float | None) -> list[int]:
    if index is None:
        return [100, 116, 139, 70]
    if index >= 0.55:
        return [34, 197, 94, 185]
    if index >= 0.35:
        return [250, 204, 21, 180]
    if index >= 0.18:
        return [249, 115, 22, 195]
    return [220, 38, 38, 205]


def find_record(records: list[dict[str, Any]], full_name: str) -> dict[str, Any] | None:
    key = normalize_name(full_name)
    for record in records:
        dong_key = normalize_name(f"{record.get('district_name')}{record.get('adm_name')}")
        if dong_key and (dong_key in key or key.endswith(dong_key)):
            return record
    return None


def build_geojson(metric: str, records: list[dict[str, Any]]) -> dict:
    source = load_boundaries()
    future_records = load_future_risk_records()
    facility_records = load_facility_shortage_records()
    features = []
    for feature in source.get("features", []):
        props = dict(feature.get("properties") or {})
        record = find_record(records, props.get("adm_nm", ""))
        if record:
            access_index = record.get("grid_population_weighted_accessibility_index")
            access_lack = record.get("grid_population_weighted_accessibility_lack_score")
            if access_index is None:
                access_index = record.get("grid_accessibility_index_exp_d_300")
            if access_lack is None:
                access_lack = record.get("grid_accessibility_lack_score")
            priority = record.get("priority_score_existing_pipeline")
            code = str(record.get("resident_adm_code") or "").replace(".0", "")
            future = future_records.get(code, {})
            facility = facility_records.get(code, {})
            future_score = future.get("future_heat_risk_score")
            if metric == "accessibility":
                map_score = access_index
            elif metric == "future-risk":
                map_score = future_score
            else:
                map_score = priority
            props.update(
                {
                    "sgis_adm_cd": record.get("sgis_adm_cd"),
                    "resident_adm_code": record.get("resident_adm_code"),
                    "region": record.get("full_adm_name"),
                    "district_name": record.get("district_name"),
                    "adm_name": record.get("adm_name"),
                    "population": record.get("population"),
                    "elderly_population_60_plus": record.get("elderly_population_60_plus"),
                    "elderly_ratio_60_plus": record.get("elderly_ratio_60_plus"),
                    "green_ratio_percent": record.get("green_ratio_percent"),
                    "shelter_count": record.get("shelter_count"),
                    "coverage_ratio_500m_area": record.get("coverage_ratio_500m_area"),
                    "grid_accessibility_index_exp_d_300": access_index,
                    "grid_accessibility_lack_score": access_lack,
                    "grid_unweighted_accessibility_index_exp_d_300": record.get("grid_accessibility_index_exp_d_300"),
                    "grid_unweighted_accessibility_lack_score": record.get("grid_accessibility_lack_score"),
                    "grid_population_weighted_accessibility_index": record.get("grid_population_weighted_accessibility_index"),
                    "grid_population_weighted_accessibility_lack_score": record.get("grid_population_weighted_accessibility_lack_score"),
                    "grid_mean_nearest_shelter_distance_m": record.get("grid_mean_nearest_shelter_distance_m"),
                    "grid_beyond_500m_ratio": record.get("grid_beyond_500m_ratio"),
                    "priority_score": priority,
                    "vulnerability_score": record.get("vulnerability_score"),
                    "heat_score": record.get("heat_score"),
                    **future,
                    **facility,
                    "fill_color": access_color(access_index) if metric == "accessibility" else score_color(future_score) if metric == "future-risk" else score_color(priority),
                    "line_color": [255, 255, 255, 220],
                    "map_score": map_score,
                }
            )
        else:
            props.update({"fill_color": [100, 116, 139, 70], "line_color": [255, 255, 255, 160]})
        copied = dict(feature)
        copied["properties"] = props
        features.append(copied)
    return {"type": "FeatureCollection", "features": features}


def build_kpis(records: list[dict[str, Any]], shelters: list[dict[str, Any]], shades: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(records)
    return {
        "dong_count": int(len(frame)),
        "population": int(pd.to_numeric(frame["population"], errors="coerce").fillna(0).sum()),
        "elderly_population": int(pd.to_numeric(frame["elderly_population_60_plus"], errors="coerce").fillna(0).sum()),
        "shelter_count": int(len(shelters)),
        "shade_count": int(len(shades)),
        "mean_grid_accessibility": float(pd.to_numeric(frame["grid_population_weighted_accessibility_index"], errors="coerce").mean()),
        "mean_green_ratio": float(pd.to_numeric(frame["green_ratio_percent"], errors="coerce").mean()),
        "mean_future_heat_risk": float(pd.to_numeric(pd.Series([row.get("future_heat_risk_score") for row in load_future_risk_records().values()]), errors="coerce").mean()) if load_future_risk_records() else 0.0,
        "future_expected_patients": float(pd.to_numeric(pd.Series([row.get("future_expected_patients") for row in load_future_risk_records().values()]), errors="coerce").sum()) if load_future_risk_records() else 0.0,
    }


def build_overview(metric: str = "vulnerability") -> dict:
    records = enrich_records(load_summary_records())
    shelters = load_shelters()
    shades = load_shades()
    # district_boundaries / city_boundary 로딩 실패 시 빈 FeatureCollection으로 대체
    try:
        district_boundaries = load_district_boundaries()
    except Exception:
        district_boundaries = {"type": "FeatureCollection", "features": []}
    try:
        city_boundary = load_city_boundary()
    except Exception:
        city_boundary = {"type": "FeatureCollection", "features": []}
    return {
        "metadata": {
            "region": "대구광역시",
            "metric": metric,
            "summary_file": str(SUMMARY_CSV),
            "boundary_source": "SGIS 2025 adm_cd=22 low_search=2",
        },
        "kpis": build_kpis(records, shelters, shades),
        "boundaries": build_geojson(metric, records),
        "district_boundaries": district_boundaries,
        "city_boundary": city_boundary,
        "districts": records,
        "shelters": shelters,
        "shades": shades,
    }


def build_allocation(payload: dict) -> dict:
    budget = int(payload.get("budget") or 0)
    unit_cost = int(payload.get("unit_cost") or 10_000_000)
    max_facilities = int(payload.get("max_facilities") or 0)
    frame = pd.DataFrame(load_summary_records())
    grouped = (
        frame.groupby("district_name", dropna=False)
        .agg(
            priority_score=("priority_score_existing_pipeline", "mean"),
            existing_shelters=("shelter_count", "sum"),
        )
        .reset_index()
        .rename(columns={"district_name": "region_name"})
    )
    allocation = allocate_facilities_by_priority(
        grouped.to_dict("records"), budget=budget, unit_cost=unit_cost, max_facilities=max_facilities
    )
    return {"rows": allocation.replace({np.nan: None}).to_dict("records")}


def build_ai_briefing(payload: dict) -> dict:
    adm_cd = str(payload.get("sgis_adm_cd") or "")
    records = load_summary_records()
    record = next((row for row in records if str(row.get("sgis_adm_cd")) == adm_cd), None)
    if not record:
        return {"status": "error", "message": "행정동을 찾을 수 없습니다."}
    region = record.get("full_adm_name") or record.get("adm_name")
    elderly = int(record.get("elderly_population_60_plus") or 0)
    coverage = float(record.get("coverage_ratio_500m_area") or 0.0) * 100.0
    vulnerability = float(record.get("vulnerability_score") or 0.0)
    candidates = [
        {
            "name": f"{region} 행정복지센터 부근 보행축",
            "facility_type": "스마트쉼터",
            "estimated_cost": 28_000_000,
            "additional_covered_population": int(elderly * 0.15),
            "reason": "고령층 생활권 중심 보행축의 대피 지점 보강",
        },
        {
            "name": f"{region} 근린공원 진입부",
            "facility_type": "그늘막",
            "estimated_cost": 12_000_000,
            "additional_covered_population": int(elderly * 0.08),
            "reason": "야외 체류와 이동이 겹치는 지점의 단기 폭염 회피 공간 확보",
        },
    ]
    analysis_result = {
        "region": region,
        "vulnerability": {
            "vulnerability_score": vulnerability,
            "vulnerability_grade": "위험" if vulnerability >= 80 else "주의" if vulnerability >= 50 else "보통",
            "main_causes": [
                {"name": "고령인구 비율", "value": record.get("elderly_ratio_60_plus"), "contribution": 0.35},
                {"name": "인구가중 격자 접근성 부족", "value": record.get("grid_population_weighted_accessibility_lack_score"), "contribution": 0.25},
                {"name": "녹지율", "value": record.get("green_ratio_percent"), "contribution": 0.15},
            ],
            "vulnerable_population": elderly,
        },
        "accessibility": {
            "facility_score": float(record.get("grid_population_weighted_accessibility_index") or record.get("grid_accessibility_index_exp_d_300") or 0.0) * 100.0,
            "nearest_shelter_distance_m": float(record.get("grid_mean_nearest_shelter_distance_m") or 0.0),
            "underserved_population": int(elderly * max(0.0, 1.0 - coverage / 100.0)),
            "coverage_rate": coverage,
            "blind_spot": coverage < 80.0,
            "blind_spot_count": 0,
            "existing_facilities": [],
            "map_center": {"latitude": 35.87, "longitude": 128.60},
        },
        "optimization": {
            "budget": int(payload.get("budget") or 0),
            "max_facilities": int(payload.get("max_facilities") or 0),
            "total_estimated_cost": 40_000_000,
            "recommended_locations": candidates,
            "before": {"coverage_rate": coverage, "underserved_population": int(elderly * max(0.0, 1.0 - coverage / 100.0)), "blind_spot_count": 0},
            "after": {"coverage_rate": min(100.0, coverage + 15.0), "underserved_population": int(elderly * max(0.0, .85 - coverage / 100.0)), "blind_spot_count": 0},
        },
    }
    policy = AlanPolicyClient().recommend_policy(analysis_result)
    return {"status": "success", "region": region, "policy_recommendation": policy}
