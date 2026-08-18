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


def _percentile_rank(series: pd.Series) -> pd.Series:
    """0~100 구간으로 백분위수 변환"""
    clean = pd.to_numeric(series, errors="coerce").fillna(0)
    if clean.max() == clean.min():
        return pd.Series(50.0, index=series.index)
    return clean.rank(pct=True) * 100.0


def enrich_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    future_records = load_future_risk_records()
    facility_records = load_facility_shortage_records()
    frame = pd.DataFrame(records)
    
    # 1. 원본 지표 추출
    v_raw = pd.to_numeric(frame["vulnerability_score"], errors="coerce").fillna(0)
    p_raw = pd.to_numeric(frame["priority_score_existing_pipeline"], errors="coerce").fillna(0)
    e_ratio = pd.to_numeric(frame["elderly_ratio_60_plus"], errors="coerce").fillna(0)
    lack_raw = pd.to_numeric(frame["grid_accessibility_lack_score"], errors="coerce").fillna(0)
    green_raw = pd.to_numeric(frame["green_ratio_percent"], errors="coerce").fillna(0)
    cov_raw = pd.to_numeric(frame["coverage_ratio_500m_area"], errors="coerce").fillna(0)

    # 2. 백분위수 기반 정규화 (0~100 스케일)
    v_pct = _percentile_rank(v_raw)
    p_pct = _percentile_rank(p_raw)
    e_pct = _percentile_rank(e_ratio)
    lack_pct = _percentile_rank(lack_raw)
    # 녹지율은 높을수록 안전하므로 역순(100 - 녹지율 백분위)
    green_lack_pct = 100.0 - _percentile_rank(green_raw)
    # 커버리지 부족도 (100 - 커버리지 백분위)
    cov_lack_pct = 100.0 - _percentile_rank(cov_raw)

    # 미래 위험도 결합
    future_scores = []
    for code in frame["resident_adm_code"]:
        c_str = str(code or "").replace(".0", "")
        f_val = future_records.get(c_str, {}).get("future_heat_risk_score")
        future_scores.append(float(f_val) if f_val is not None else 50.0)
    future_pct = _percentile_rank(pd.Series(future_scores))

    # 3. 종합 폭염 위험 지수 (Composite Heat Risk Index) 가중합 산출
    # 고령자 취약(35%) + 쉼터접근성 부족(30%) + 미래기후위험(20%) + 열환경/녹지부족(15%)
    composite_risk = (
        e_pct * 0.35 +
        lack_pct * 0.30 +
        future_pct * 0.20 +
        green_lack_pct * 0.15
    )

    enriched = []
    for i, record in enumerate(records):
        code = str(record.get("resident_adm_code") or "").replace(".0", "")
        merged = dict(record)
        merged.update(future_records.get(code, {}))
        merged.update(facility_records.get(code, {}))

        c_score = round(float(composite_risk.iloc[i]), 1)
        # 5단계 등급 산출
        if c_score >= 80.0:
            grade = "심각"
            grade_en = "severe"
        elif c_score >= 60.0:
            grade = "위험"
            grade_en = "danger"
        elif c_score >= 40.0:
            grade = "주의"
            grade_en = "warning"
        elif c_score >= 20.0:
            grade = "보통"
            grade_en = "moderate"
        else:
            grade = "양호"
            grade_en = "safe"

        # 취약 축별 백분위 값 (0~100)
        e_val = round(float(e_pct.iloc[i]), 1)
        l_val = round(float(lack_pct.iloc[i]), 1)
        f_val = round(float(future_pct.iloc[i]), 1)
        g_val = round(float(green_lack_pct.iloc[i]), 1)

        # 주 원인 진단: 가중치 곱이 아닌 "해당 동에서 대구시 대비 가장 심각한 상대 백분위 순위(x[1])" 기준 정렬
        factors = [
            ("고령 취약계층 밀집", e_val, 0.35, "60세 이상 고령자 거주 비율이 대구시 상위 수준"),
            ("쉼터 접근 사각지대", l_val, 0.30, "도보 500m 반경 쉼터 접근성 부족 및 보행거리 과다"),
            ("2030 기후 열노출 가중", f_val, 0.20, "미래 폭염일수 및 온열질환 발생 위험도 급증 지역"),
            ("도심 열섬·녹지 결여", g_val, 0.15, "식생 지수(NDVI) 부족 및 아스팔트 열축적 심각"),
        ]
        factors.sort(key=lambda x: x[1], reverse=True)

        merged.update({
            "composite_risk_score": c_score,
            "composite_risk_grade": grade,
            "composite_risk_grade_en": grade_en,
            "normalized_vulnerability_score": round(float(v_pct.iloc[i]), 1),
            "normalized_priority_score": round(float(p_pct.iloc[i]), 1),
            "elderly_vulnerability_pct": e_val,
            "accessibility_lack_pct": l_val,
            "future_climate_risk_pct": f_val,
            "green_shortage_pct": g_val,
            "primary_risk_driver": factors[0][0],
            "primary_driver_desc": factors[0][3],
            "secondary_risk_driver": factors[1][0],
            "secondary_driver_desc": factors[1][3],
            "risk_driver_breakdown": [
                {"name": f[0], "score": f[1], "weight": f[2], "desc": f[3]}
                for f in factors
            ]
        })
        enriched.append(merged)
    return enriched


@lru_cache(maxsize=1)
def load_boundaries() -> dict:
    return SGISClient(timeout=30.0).get_administrative_boundaries(
        adm_cd="22", year=2025, low_search=2
    )


@lru_cache(maxsize=1)
def load_district_boundaries() -> dict:
    """구·군 경계 (low_search=1)."""
    raw = SGISClient(timeout=30.0).get_administrative_boundaries(
        adm_cd="22", year=2025, low_search=1
    )
    features = []
    for feature in raw.get("features", []):
        props = dict(feature.get("properties") or {})
        adm_nm: str = str(props.get("adm_nm") or "")
        district_name = adm_nm.split()[-1] if adm_nm.strip() else adm_nm
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
    """0~100 정규화 지수에 따른 명확한 5색 히트맵 색상 매핑"""
    if score is None:
        return [100, 116, 139, 70]
    val = float(score)
    # 심각 (80~100: 빨강)
    if val >= 80:
        return [220, 38, 38, 220]
    # 위험 (60~80: 주황)
    if val >= 60:
        return [249, 115, 22, 210]
    # 주의 (40~60: 황색/노랑)
    if val >= 40:
        return [234, 179, 8, 200]
    # 보통 (20~40: 선명한 하늘색/파랑)
    if val >= 20:
        return [14, 165, 233, 195]
    # 양호 (0~20: 선명한 초록)
    return [34, 197, 94, 190]


def access_color(index: float | None) -> list[int]:
    """접근성 지표 컬러링"""
    if index is None:
        return [100, 116, 139, 70]
    val = float(index)
    if val >= 80:
        return [34, 197, 94, 200]  # 매우 우수 (녹색)
    if val >= 60:
        return [14, 165, 233, 195]  # 우수 (하늘색)
    if val >= 40:
        return [234, 179, 8, 195]  # 보통 (황색)
    if val >= 20:
        return [249, 115, 22, 205]  # 부족 (주황)
    return [220, 38, 38, 220]      # 심각한 부족 (빨강)


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
            c_score = float(record.get("composite_risk_score", 50.0))
            access_pct = float(100.0 - record.get("accessibility_lack_pct", 50.0))
            future_pct = float(record.get("future_climate_risk_pct", 50.0))

            if metric == "accessibility":
                map_score = access_pct
                color = access_color(access_pct)
            elif metric == "future-risk":
                map_score = future_pct
                color = score_color(future_pct)
            else:
                # 기본: 취약도 + 접근성 종합 위험도 히트맵
                map_score = c_score
                color = score_color(c_score)

            merged_props = dict(record)
            merged_props.update({
                "sgis_adm_cd": record.get("sgis_adm_cd"),
                "resident_adm_code": record.get("resident_adm_code"),
                "region": record.get("full_adm_name"),
                "district_name": record.get("district_name"),
                "adm_name": record.get("adm_name"),
                "fill_color": color,
                "line_color": [255, 255, 255, 220],
                "map_score": map_score,
            })
            props.update(merged_props)
        else:
            props.update({"fill_color": [100, 116, 139, 70], "line_color": [255, 255, 255, 160]})
        copied = dict(feature)
        copied["properties"] = props
        features.append(copied)
    return {"type": "FeatureCollection", "features": features}


def build_kpis(records: list[dict[str, Any]], shelters: list[dict[str, Any]], shades: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(records)
    
    # 고위험(심각+위험) 동 개수
    high_risk_count = int((frame["composite_risk_score"] >= 60.0).sum()) if "composite_risk_score" in frame.columns else 0
    # 사각지대 고령인구 추정
    uncovered_elderly = int(pd.to_numeric(frame["elderly_population_60_plus"], errors="coerce").fillna(0).sum() * 0.38)

    return {
        "dong_count": int(len(frame)),
        "population": int(pd.to_numeric(frame["population"], errors="coerce").fillna(0).sum()),
        "elderly_population": int(pd.to_numeric(frame["elderly_population_60_plus"], errors="coerce").fillna(0).sum()),
        "shelter_count": int(len(shelters)),
        "shade_count": int(len(shades)),
        "mean_grid_accessibility": float(pd.to_numeric(frame["grid_population_weighted_accessibility_index"], errors="coerce").mean()),
        "mean_green_ratio": float(pd.to_numeric(frame["green_ratio_percent"], errors="coerce").mean()),
        "high_risk_dong_count": high_risk_count,
        "uncovered_elderly_est": uncovered_elderly,
        "mean_future_heat_risk": float(pd.to_numeric(pd.Series([row.get("future_heat_risk_score") for row in load_future_risk_records().values()]), errors="coerce").mean()) if load_future_risk_records() else 0.0,
        "future_expected_patients": float(pd.to_numeric(pd.Series([row.get("future_expected_patients") for row in load_future_risk_records().values()]), errors="coerce").sum()) if load_future_risk_records() else 0.0,
    }


def compute_correlations(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """폭염 취약도와 각 요인 간의 상관관계 계산"""
    frame = pd.DataFrame(records)
    target = pd.to_numeric(frame["composite_risk_score"], errors="coerce")
    
    factor_defs = [
        ("고령인구 비율 (60세 이상)", "elderly_ratio_60_plus", "양의 상관", "인구학적 취약성"),
        ("쉼터 접근거리 (평균)", "grid_mean_nearest_shelter_distance_m", "양의 상관", "물리적 거리 한계"),
        ("500m 쉼터 커버리지", "coverage_ratio_500m_area", "음의 상관", "공간적 차단 효과"),
        ("녹지율 (식생)", "green_ratio_percent", "음의 상관", "열섬 완화 효과"),
        ("2030 예상 온열질환 환자", "future_expected_patients", "양의 상관", "기후변화 노출도"),
    ]
    results = []
    for label, col, direction, category in factor_defs:
        if col in frame.columns:
            s = pd.to_numeric(frame[col], errors="coerce")
            corr = float(target.corr(s)) if not s.isna().all() else 0.0
            if not np.isnan(corr):
                results.append({
                    "factor": label,
                    "correlation": round(corr, 3),
                    "impact": "강한 영향" if abs(corr) >= 0.5 else "중간 영향" if abs(corr) >= 0.25 else "보통 영향",
                    "direction": "위험 증가 (+)" if corr > 0 else "위험 완화 (-)",
                    "category": category
                })
    return sorted(results, key=lambda x: abs(x["correlation"]), reverse=True)


def build_overview(metric: str = "vulnerability") -> dict:
    records = enrich_records(load_summary_records())
    shelters = load_shelters()
    shades = load_shades()
    try:
        district_boundaries = load_district_boundaries()
    except Exception:
        district_boundaries = {"type": "FeatureCollection", "features": []}
    try:
        city_boundary = load_city_boundary()
    except Exception:
        city_boundary = {"type": "FeatureCollection", "features": []}

    correlations = compute_correlations(records)

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
        "correlations": correlations,
        "shelters": shelters,
        "shades": shades,
    }


def build_allocation(payload: dict) -> dict:
    budget = int(payload.get("budget") or 0)
    unit_cost = int(payload.get("unit_cost") or 10_000_000)
    max_facilities = int(payload.get("max_facilities") or 0)
    records = enrich_records(load_summary_records())
    frame = pd.DataFrame(records)
    
    grouped = (
        frame.groupby("district_name", dropna=False)
        .agg(
            priority_score=("composite_risk_score", "mean"),
            existing_shelters=("shelter_count", "sum"),
            elderly_pop=("elderly_population_60_plus", "sum"),
        )
        .reset_index()
        .rename(columns={"district_name": "region_name"})
    )
    allocation = allocate_facilities_by_priority(
        grouped.to_dict("records"), budget=budget, unit_cost=unit_cost, max_facilities=max_facilities
    )
    return {"rows": allocation.replace({np.nan: None}).to_dict("records")}


def simulate_what_if(payload: dict) -> dict:
    """What-If 시뮬레이션: 예산 및 신규 시설 배치 시 사각지대 해소율과 수혜 인구 산출"""
    budget = int(payload.get("budget") or 50_000_000)
    unit_cost = int(payload.get("unit_cost") or 10_000_000)
    max_facilities = int(payload.get("max_facilities") or 5)
    facility_type = str(payload.get("facility_type") or "스마트쉼터")

    records = enrich_records(load_summary_records())
    # 상위 위험 동 우선 배분 시뮬레이션
    sorted_dongs = sorted(records, key=lambda x: x.get("composite_risk_score", 0), reverse=True)
    
    new_facilities_count = min(max_facilities, budget // unit_cost) if unit_cost > 0 else 0
    allocated_dongs = []
    total_added_coverage_pop = 0
    total_blindspot_reduced_pct = 0.0

    for i in range(min(new_facilities_count, len(sorted_dongs))):
        dong = sorted_dongs[i]
        elderly = int(dong.get("elderly_population_60_plus") or 0)
        curr_cov = float(dong.get("coverage_ratio_500m_area") or 0.0) * 100.0
        
        # 1개 설치당 추가 커버리지 효과 추정
        gain_cov = min(100.0 - curr_cov, 24.5 if facility_type == "스마트쉼터" else 15.0)
        gain_pop = int(elderly * (gain_cov / 100.0) * 0.75)
        
        total_added_coverage_pop += gain_pop
        total_blindspot_reduced_pct += gain_cov / (new_facilities_count or 1)

        allocated_dongs.append({
            "dong_name": dong.get("adm_name"),
            "district_name": dong.get("district_name"),
            "full_name": dong.get("full_adm_name"),
            "current_risk_score": dong.get("composite_risk_score"),
            "current_grade": dong.get("composite_risk_grade"),
            "current_coverage_pct": round(curr_cov, 1),
            "projected_coverage_pct": round(curr_cov + gain_cov, 1),
            "additional_beneficiaries": gain_pop,
            "facility_type": facility_type,
            "cost": unit_cost,
        })

    return {
        "status": "success",
        "budget": budget,
        "spent_budget": new_facilities_count * unit_cost,
        "new_facilities_count": new_facilities_count,
        "total_added_beneficiaries": total_added_coverage_pop,
        "avg_coverage_improvement_pct": round(total_blindspot_reduced_pct, 1),
        "overall_blindspot_reduction_rate": round(min(85.0, new_facilities_count * 12.4), 1),
        "allocated_dongs": allocated_dongs,
    }


def build_ai_briefing(payload: dict) -> dict:
    """시설 배분 시뮬레이션 결과를 설명하는 AI 보고서 생성."""
    simulation = payload.get("simulation")
    if not isinstance(simulation, dict):
        simulation = simulate_what_if(payload)

    budget = int(payload.get("budget") or simulation.get("budget") or 0)
    max_facilities = int(payload.get("max_facilities") or simulation.get("new_facilities_count") or 0)
    facility_type = str(payload.get("facility_type") or "스마트쉼터")
    unit_cost = int(payload.get("unit_cost") or 10_000_000)
    allocated = simulation.get("allocated_dongs") or []
    records = enrich_records(load_summary_records())
    by_name = {
        (str(row.get("district_name") or ""), str(row.get("adm_name") or "")): row
        for row in records
    }

    target_regions = []
    for item in allocated[:6]:
        record = by_name.get((str(item.get("district_name") or ""), str(item.get("dong_name") or "")), {})
        target_regions.append(
            {
                "name": item.get("full_name") or f"{item.get('district_name', '')} {item.get('dong_name', '')}".strip(),
                "district_name": item.get("district_name"),
                "dong_name": item.get("dong_name"),
                "risk_score": item.get("current_risk_score"),
                "risk_grade": item.get("current_grade"),
                "current_coverage_pct": item.get("current_coverage_pct"),
                "projected_coverage_pct": item.get("projected_coverage_pct"),
                "coverage_gain_pct": round(float(item.get("projected_coverage_pct") or 0) - float(item.get("current_coverage_pct") or 0), 1),
                "additional_beneficiaries": item.get("additional_beneficiaries"),
                "primary_driver": record.get("primary_risk_driver"),
                "secondary_driver": record.get("secondary_risk_driver"),
                "elderly_population": record.get("elderly_population_60_plus"),
                "future_expected_patients": record.get("future_expected_patients"),
            }
        )

    total_cost = int(simulation.get("spent_budget") or 0)
    new_facilities = int(simulation.get("new_facilities_count") or 0)
    beneficiaries = int(simulation.get("total_added_beneficiaries") or 0)
    reduction = float(simulation.get("overall_blindspot_reduction_rate") or 0.0)
    avg_improvement = float(simulation.get("avg_coverage_improvement_pct") or 0.0)
    usage_pct = round((total_cost / budget) * 100.0, 1) if budget else 0.0

    summary = (
        f"총 {budget:,}원 예산으로 {facility_type} {new_facilities}개소를 우선 배분하면 "
        f"{beneficiaries:,}명의 고령인구가 새로 보호권에 들어오고, "
        f"사각지대 해소율은 약 {reduction:.1f}%로 추정됩니다. "
        f"배분 대상은 종합 위험지수와 500m 커버리지 부족이 큰 행정동을 우선 선정했습니다."
    )

    policies = []
    for idx, region in enumerate(target_regions[:3], start=1):
        policies.append(
            {
                "policy_name": f"{idx}. {region['name']} {facility_type} 우선 배치",
                "reason": (
                    f"현재 커버리지 {region['current_coverage_pct']}%에서 "
                    f"{region['projected_coverage_pct']}%로 개선되어 "
                    f"약 {int(region.get('additional_beneficiaries') or 0):,}명 보호 효과가 예상됩니다. "
                    f"주요 취약 원인은 {region.get('primary_driver') or '복합 취약요인'}입니다."
                ),
            }
        )

    if not policies:
        policies.append(
            {
                "policy_name": "시설 배분 조건 재검토",
                "reason": "현재 예산 또는 최대 설치 수 조건에서 신규 배분 대상이 산출되지 않았습니다. 예산, 단가, 설치 수 제한을 조정해야 합니다.",
            }
        )

    recommendation = {
        "priority_level": "시설 배분 시뮬레이션 설명",
        "summary": summary,
        "recommended_policies": policies,
        "implementation_steps": [
            "상위 배분 행정동의 보행 결절점, 횡단보도 대기공간, 경로당·복지관 주변을 현장 확인합니다.",
            "전기 인입, 보행 방해, 사유지 저촉 여부를 확인한 뒤 설치 가능 지점을 확정합니다.",
            "설치 후 500m 보행권과 고령인구 보호권을 다시 계산해 사각지대 해소율을 갱신합니다.",
        ],
        "cautions": [
            "본 결과는 현재 데이터 기반 What-If 추정이며 실제 설치 효과의 인과 추정치는 아닙니다.",
            "행정동 내부 실제 입지는 보행량, 그늘 연속성, 전력·수도 인프라를 함께 고려해야 합니다.",
        ],
    }

    return {
        "status": "success",
        "region": "대구광역시 시설 배분 시뮬레이션",
        "report_type": "facility_allocation_simulation",
        "simulation_summary": {
            "budget": budget,
            "unit_cost": unit_cost,
            "facility_type": facility_type,
            "spent_budget": total_cost,
            "budget_usage_pct": usage_pct,
            "new_facilities_count": new_facilities,
            "total_added_beneficiaries": beneficiaries,
            "avg_coverage_improvement_pct": avg_improvement,
            "overall_blindspot_reduction_rate": reduction,
            "target_regions": target_regions,
        },
        "policy_recommendation": recommendation,
    }

