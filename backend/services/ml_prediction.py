from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import KFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from backend.services.dashboard import enrich_records, load_summary_records

FACILITY_TYPES: dict[str, dict[str, Any]] = {
    "cooling_support": {
        "label": "기존 시설 냉방 지원",
        "unit_cost": 2_000_000,
        "response_gain": 1.0,
        "access_lack_delta": -0.15,
        "shade_gain": 0.0,
        "shelter_gain": 0.0,
    },
    "shade": {
        "label": "그늘막",
        "unit_cost": 10_000_000,
        "response_gain": 1.8,
        "access_lack_delta": -0.45,
        "shade_gain": 1.0,
        "shelter_gain": 0.0,
    },
    "cooling_fog": {
        "label": "쿨링포그",
        "unit_cost": 20_000_000,
        "response_gain": 2.8,
        "access_lack_delta": -0.75,
        "shade_gain": 1.2,
        "shelter_gain": 0.0,
    },
    "smart_shelter": {
        "label": "스마트 쉼터",
        "unit_cost": 40_000_000,
        "response_gain": 4.5,
        "access_lack_delta": -1.35,
        "shade_gain": 0.0,
        "shelter_gain": 1.0,
    },
}

FEATURE_COLUMNS = [
    "population",
    "elderly_ratio_60_plus",
    "green_ratio_percent",
    "shelter_count",
    "grid_population_weighted_accessibility_index",
    "grid_population_weighted_accessibility_lack_score",
    "grid_mean_nearest_shelter_distance_m",
    "grid_beyond_500m_ratio",
    "future_max_heat_index_c",
    "future_heatwave_days",
    "future_strong_heatwave_days",
    "future_tropical_night_days",
    "future_max_heat_streak_days",
    "future_cumulative_heat_burden",
    "facility_response_score",
    "facility_gap_score",
    "facility_shortage_score",
    "protection_need_score",
]

TARGET_COLUMN = "future_expected_patients"


def _num(value: Any, default: float = 0.0) -> float:
    converted = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(converted):
        return default
    return float(converted)


def _code(value: Any) -> str:
    return str(value or "").replace(".0", "")


@lru_cache(maxsize=1)
def _training_frame() -> pd.DataFrame:
    frame = pd.DataFrame(enrich_records(load_summary_records()))
    frame["resident_adm_code"] = frame["resident_adm_code"].map(_code)
    frame["sgis_adm_cd"] = frame["sgis_adm_cd"].map(_code)
    for column in FEATURE_COLUMNS + [TARGET_COLUMN, "future_heat_incidence_per_10k", "future_heat_risk_score"]:
        if column not in frame.columns:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["facility_response_score"] = frame["facility_response_score"].fillna(50.0)
    frame["facility_gap_score"] = frame["facility_gap_score"].fillna(50.0)
    frame["facility_shortage_score"] = frame["facility_shortage_score"].fillna(frame["facility_gap_score"])
    frame["protection_need_score"] = frame["protection_need_score"].fillna(frame["priority_score_existing_pipeline"])
    for column in FEATURE_COLUMNS:
        frame[column] = frame[column].fillna(frame[column].median()).fillna(0.0)
    frame[TARGET_COLUMN] = frame[TARGET_COLUMN].fillna(0.0)
    return frame


@lru_cache(maxsize=1)
def _model_bundle() -> dict[str, Any]:
    frame = _training_frame()
    x = frame[FEATURE_COLUMNS]
    y = frame[TARGET_COLUMN]
    model = Pipeline([
        ("scale", StandardScaler()),
        ("regressor", GradientBoostingRegressor(random_state=42, n_estimators=180, max_depth=2, learning_rate=0.045)),
    ])
    model.fit(x, y)
    if len(frame) >= 20 and y.nunique() > 1:
        cv = KFold(n_splits=5, shuffle=True, random_state=42)
        mae = -cross_val_score(model, x, y, cv=cv, scoring="neg_mean_absolute_error").mean()
    else:
        mae = 0.0
    importances = model.named_steps["regressor"].feature_importances_
    importance_rows = sorted(
        [
            {"feature": feature, "importance": float(score)}
            for feature, score in zip(FEATURE_COLUMNS, importances)
        ],
        key=lambda row: row["importance"],
        reverse=True,
    )[:6]
    return {"model": model, "mae": float(mae), "feature_importances": importance_rows}


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, tuple):
        return [_clean(item) for item in value]
    if isinstance(value, np.generic):
        return _clean(value.item())
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    return value


def _facility_counts(payload: dict[str, Any]) -> dict[str, int]:
    raw = payload.get("facility_counts") or payload.get("facilities") or {}
    return {key: max(0, int(raw.get(key) or 0)) for key in FACILITY_TYPES}


def _apply_facility_scenario(row: pd.Series, counts: dict[str, int]) -> pd.Series:
    adjusted = row.copy()
    response_gain = sum(FACILITY_TYPES[key]["response_gain"] * count for key, count in counts.items())
    access_delta = sum(FACILITY_TYPES[key]["access_lack_delta"] * count for key, count in counts.items())
    shade_gain = sum(FACILITY_TYPES[key]["shade_gain"] * count for key, count in counts.items())
    shelter_gain = sum(FACILITY_TYPES[key]["shelter_gain"] * count for key, count in counts.items())

    adjusted["facility_response_score"] = min(100.0, _num(row.get("facility_response_score"), 50.0) + response_gain)
    adjusted["facility_gap_score"] = max(0.0, _num(row.get("facility_gap_score"), 50.0) - response_gain)
    adjusted["facility_shortage_score"] = max(0.0, _num(row.get("facility_shortage_score"), 50.0) - response_gain * 0.72)
    adjusted["grid_population_weighted_accessibility_lack_score"] = max(
        0.0, _num(row.get("grid_population_weighted_accessibility_lack_score"), 0.0) + access_delta
    )
    adjusted["grid_population_weighted_accessibility_index"] = min(
        1.0, _num(row.get("grid_population_weighted_accessibility_index"), 0.0) + max(0.0, -access_delta) / 100.0
    )
    adjusted["grid_beyond_500m_ratio"] = max(0.0, _num(row.get("grid_beyond_500m_ratio"), 0.0) - max(0.0, -access_delta) / 120.0)
    adjusted["shelter_count"] = _num(row.get("shelter_count"), 0.0) + shelter_gain
    adjusted["shade_count_scenario"] = shade_gain
    return adjusted


def _predict(model: Pipeline, row: pd.Series) -> float:
    x = pd.DataFrame([{column: _num(row.get(column), 0.0) for column in FEATURE_COLUMNS}])
    return max(0.0, float(model.predict(x)[0]))


def build_ml_scenario(payload: dict[str, Any]) -> dict[str, Any]:
    frame = _training_frame()
    adm_cd = _code(payload.get("sgis_adm_cd") or payload.get("resident_adm_code"))
    if adm_cd:
        matches = frame[(frame["sgis_adm_cd"] == adm_cd) | (frame["resident_adm_code"] == adm_cd)]
    else:
        matches = frame.sort_values(TARGET_COLUMN, ascending=False).head(1)
    if matches.empty:
        return {"status": "error", "message": "행정동을 찾을 수 없습니다."}

    row = matches.iloc[0]
    counts = _facility_counts(payload)
    total_cost = sum(FACILITY_TYPES[key]["unit_cost"] * count for key, count in counts.items())
    bundle = _model_bundle()
    model = bundle["model"]

    baseline_pred = _predict(model, row)
    baseline_actual = _num(row.get(TARGET_COLUMN), baseline_pred)
    adjusted = _apply_facility_scenario(row, counts)
    adjusted_pred = _predict(model, adjusted)
    aligned_after = baseline_actual * (adjusted_pred / baseline_pred) if baseline_pred > 0 else adjusted_pred

    response_gain = sum(FACILITY_TYPES[key]["response_gain"] * count for key, count in counts.items())
    protection_modifier = 0.65 + min(0.55, _num(row.get("protection_need_score"), 50.0) / 180.0)
    facility_floor_rate = min(0.35, response_gain * 0.006 * protection_modifier)
    policy_after = baseline_actual * (1.0 - facility_floor_rate)

    after_pred = min(baseline_actual, aligned_after, policy_after)
    reduced_patients = max(0.0, baseline_actual - after_pred)
    reduction_rate = reduced_patients / baseline_actual if baseline_actual > 0 else 0.0
    incidence_after = after_pred / max(_num(row.get("population"), 0.0), 1.0) * 10_000.0

    return _clean({
        "status": "success",
        "model": {
            "name": "GradientBoostingRegressor",
            "target": "2030 예상환자수(명)",
            "cv_mae": bundle["mae"],
            "feature_importances": bundle["feature_importances"],
            "note": "기존 2030 예측 결과를 학습한 회귀 기반 시설투입 시나리오 추정입니다. 실제 인과효과 검증 전 단계의 정책 시뮬레이션 값입니다.",
        },
        "facility_unit_costs": {
            key: {"label": spec["label"], "unit_cost": spec["unit_cost"]}
            for key, spec in FACILITY_TYPES.items()
        },
        "facility_counts": counts,
        "total_cost": total_cost,
        "district": {
            "sgis_adm_cd": row.get("sgis_adm_cd"),
            "resident_adm_code": row.get("resident_adm_code"),
            "district_name": row.get("district_name"),
            "adm_name": row.get("adm_name"),
            "full_adm_name": row.get("full_adm_name"),
        },
        "baseline": {
            "expected_patients": baseline_actual,
            "regression_expected_patients": baseline_pred,
            "incidence_per_10k": _num(row.get("future_heat_incidence_per_10k"), 0.0),
            "risk_score": _num(row.get("future_heat_risk_score"), 0.0),
            "risk_grade": row.get("future_heat_risk_grade"),
            "confidence": row.get("future_risk_confidence"),
            "confidence_grade": row.get("future_risk_confidence_grade"),
            "main_driver_1": row.get("future_main_driver_1"),
            "main_driver_2": row.get("future_main_driver_2"),
        },
        "scenario": {
            "expected_patients_after": after_pred,
            "incidence_per_10k_after": incidence_after,
            "reduced_patients": reduced_patients,
            "reduction_rate": reduction_rate,
            "facility_response_score_after": _num(adjusted.get("facility_response_score"), 0.0),
            "facility_gap_score_after": _num(adjusted.get("facility_gap_score"), 0.0),
            "accessibility_lack_after": _num(adjusted.get("grid_population_weighted_accessibility_lack_score"), 0.0),
        },
        "assumptions": [
            "시설별 단가는 냉방지원 200만원, 그늘막 1,000만원, 쿨링포그 2,000만원, 스마트쉼터 4,000만원으로 고정했습니다.",
            "시설 투입 효과는 시설대응력 증가, 시설부족도 감소, 접근성 부족도 완화를 통해 회귀 모델에 반영했습니다.",
            "관측 환자수가 아닌 기존 2030 예측 산출물을 목표값으로 쓰므로, 결과는 정책 우선순위 비교용 시뮬레이션입니다.",
        ],
    })
