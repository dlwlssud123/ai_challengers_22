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
def load_boundaries() -> dict:
    return SGISClient(timeout=30.0).get_administrative_boundaries(
        adm_cd="22", year=2025, low_search=2
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
            map_score = access_index if metric == "accessibility" else priority
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
                    "fill_color": access_color(access_index) if metric == "accessibility" else score_color(priority),
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
    }


def build_overview(metric: str = "vulnerability") -> dict:
    records = load_summary_records()
    shelters = load_shelters()
    shades = load_shades()
    return {
        "metadata": {
            "region": "대구광역시",
            "metric": metric,
            "summary_file": str(SUMMARY_CSV),
            "boundary_source": "SGIS 2025 adm_cd=22 low_search=2",
        },
        "kpis": build_kpis(records, shelters, shades),
        "boundaries": build_geojson(metric, records),
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
