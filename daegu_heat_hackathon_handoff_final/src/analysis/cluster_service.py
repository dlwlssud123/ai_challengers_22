"""Stateless DBSCAN + SHAP service used by the FastAPI layer.

The batch pipeline (``dbscan_shap_batch.py``) remains the source of truth for
the four-source data merge and report artifacts.  This module intentionally
accepts an already prepared, complete administrative-dong snapshot so the web
application can re-run clustering after a What-If simulation without giving a
server-side path or an arbitrary file to the API.

DBSCAN has no native ``predict`` method.  A request therefore always clusters
the *entire supplied snapshot*.  The tree model is only a surrogate used for
SHAP explanations, never a replacement for DBSCAN labels.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.preprocessing import StandardScaler

from .dbscan_shap_batch import (
    FEATURE_CAUSE,
    causes_from_profile,
    cluster_type_from_profile,
    compute_shap,
    make_surrogate,
    recommendations_for,
    select_dbscan,
)


FEATURE_KEYS = (
    "heat_exposure",
    "elderly_concentration",
    "green_deficit",
    "access_deficit",
    "future_heat_illness_risk",
    "response_facility_shortage",
)

FEATURE_LABELS = {
    "heat_exposure": "고온 노출",
    "elderly_concentration": "고령자 집중도",
    "green_deficit": "녹지 부족도",
    "access_deficit": "접근성 결손",
    "future_heat_illness_risk": "미래 온열질환 위험",
    "response_facility_shortage": "대응시설 부족도",
}

MIN_RECORDS = 12
MAX_RECORDS = 500


class ClusterAnalysisError(ValueError):
    """A user-correctable data or model condition for the cluster endpoint."""


def feature_specification() -> list[dict[str, str]]:
    """Expose the only six features accepted by the online clustering API."""
    return [
        {
            "key": key,
            "label": FEATURE_LABELS[key],
            "meaning": {
                "heat_exposure": "기온·폭염일수 등을 사전 산출한 노출 점수",
                "elderly_concentration": "고령 인구 비율 또는 집중도",
                "green_deficit": "녹지율의 역방향 점수",
                "access_deficit": "격자 기반 쉼터 접근성 결손 점수",
                "future_heat_illness_risk": "회귀모델 또는 미래 시나리오 기반 위험 점수",
                "response_facility_shortage": "보호필요도와 시설대응력을 결합한 부족도",
            }[key],
        }
        for key in FEATURE_KEYS
    ]


def _native(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [_native(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): _native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_native(item) for item in value]
    return value


def _require_snapshot(records: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    if not MIN_RECORDS <= len(records) <= MAX_RECORDS:
        raise ClusterAnalysisError(
            f"행정동 스냅샷은 {MIN_RECORDS}~{MAX_RECORDS}건이어야 합니다. 현재 {len(records)}건입니다."
        )
    rows: list[dict[str, Any]] = []
    for position, record in enumerate(records, start=1):
        features = record.get("features")
        if not isinstance(features, Mapping):
            raise ClusterAnalysisError(f"{position}번째 records.features가 객체가 아닙니다.")
        missing = [key for key in FEATURE_KEYS if key not in features]
        unexpected = sorted(set(features) - set(FEATURE_KEYS))
        if missing or unexpected:
            detail = []
            if missing:
                detail.append(f"누락={','.join(missing)}")
            if unexpected:
                detail.append(f"허용하지 않는 키={','.join(unexpected)}")
            raise ClusterAnalysisError(f"{position}번째 Feature 형식 오류: {'; '.join(detail)}")
        try:
            values = {key: float(features[key]) for key in FEATURE_KEYS}
        except (TypeError, ValueError) as exc:
            raise ClusterAnalysisError(f"{position}번째 Feature는 모두 숫자여야 합니다.") from exc
        if not all(np.isfinite(value) for value in values.values()):
            raise ClusterAnalysisError(f"{position}번째 Feature에 NaN 또는 무한대가 있습니다.")
        dong_code = str(record.get("dong_code", "")).strip()
        if not dong_code:
            raise ClusterAnalysisError(f"{position}번째 dong_code가 비어 있습니다.")
        rows.append(
            {
                "dong_code": dong_code,
                "district_name": str(record.get("district_name", "")).strip(),
                "dong_name": str(record.get("dong_name", "")).strip(),
                **values,
            }
        )
    frame = pd.DataFrame(rows)
    duplicated = frame.loc[frame["dong_code"].duplicated(), "dong_code"].tolist()
    if duplicated:
        raise ClusterAnalysisError(f"dong_code는 유일해야 합니다. 중복: {', '.join(duplicated[:10])}")
    if (frame[list(FEATURE_KEYS)].std(ddof=0) == 0).any():
        constant = frame[list(FEATURE_KEYS)].columns[(frame[list(FEATURE_KEYS)].std(ddof=0) == 0)].tolist()
        raise ClusterAnalysisError(f"모든 행에서 같은 값인 Feature가 있습니다: {', '.join(constant)}")
    return frame


def _cluster_name(cluster_type: str, number: int) -> str:
    return f"C{number}_{cluster_type}"


def analyze_cluster_snapshot(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Cluster one complete snapshot and return JSON-native frontend data.

    The expensive part is the exact six-feature SHAP fallback when the optional
    ``shap`` package is unavailable; 150 행정동 기준 해커톤 서버에서 수행할 수
    있도록 request size is intentionally capped.
    """
    frame = _require_snapshot(records)
    feature_frame = frame.loc[:, FEATURE_KEYS].copy()
    scaler = StandardScaler()
    z = scaler.fit_transform(feature_frame)
    z_frame = pd.DataFrame(z, columns=FEATURE_KEYS, index=frame.index)

    try:
        labels, selected, _evaluation, expanded_search = select_dbscan(z)
    except RuntimeError as exc:
        raise ClusterAnalysisError(
            "DBSCAN이 2개 이상의 해석 가능한 군집을 만들지 못했습니다. "
            "입력 Feature 범위·결측 대체·행정동 수를 점검하세요."
        ) from exc

    raw_clusters = sorted(int(cluster) for cluster in set(labels) if cluster != -1)
    if len(raw_clusters) < 2:
        raise ClusterAnalysisError("노이즈를 제외한 DBSCAN 군집이 2개 미만입니다.")
    target_map = {cluster: index for index, cluster in enumerate(raw_clusters)}
    train_mask = labels != -1
    x_train = z[train_mask]
    y_train = np.array([target_map[int(cluster)] for cluster in labels[train_mask]], dtype=int)
    min_class_size = int(pd.Series(y_train).value_counts().min())
    if min_class_size < 2:
        raise ClusterAnalysisError("최소 군집 크기가 2 미만이어서 SHAP 대리모델을 검증할 수 없습니다.")
    cv_folds = min(5, min_class_size)
    model, model_name, model_note = make_surrogate(len(raw_clusters))
    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
    try:
        cv_predictions = cross_val_predict(clone(model), x_train, y_train, cv=cv, method="predict")
        accuracy = float(accuracy_score(y_train, cv_predictions))
        macro_f1 = float(f1_score(y_train, cv_predictions, average="macro", zero_division=0))
        model.fit(x_train, y_train)
        shap_values, shap_info = compute_shap(model, x_train)
    except Exception as exc:
        raise ClusterAnalysisError(
            f"대리모델 또는 SHAP 계산에 실패했습니다: {type(exc).__name__}. "
            "서버 의존성 및 입력 군집 크기를 점검하세요."
        ) from exc

    profiles_z = z_frame.assign(_cluster=labels).groupby("_cluster").mean()
    profiles_raw = feature_frame.assign(_cluster=labels).groupby("_cluster").mean()
    importance_by_cluster: dict[int, pd.Series] = {}
    causes_by_cluster: dict[int, list[str]] = {}
    types_by_cluster: dict[int, str] = {}
    korean_features = [FEATURE_LABELS[key] for key in FEATURE_KEYS]
    for cluster in raw_clusters:
        class_index = target_map[cluster]
        local_values = shap_values[y_train == class_index, :, class_index]
        importance = pd.Series(np.mean(np.abs(local_values), axis=0), index=korean_features)
        z_profile = profiles_z.loc[cluster].rename(index=FEATURE_LABELS)
        importance_by_cluster[cluster] = importance
        types_by_cluster[cluster] = cluster_type_from_profile(z_profile, importance)
        causes_by_cluster[cluster] = causes_from_profile(z_profile, importance)

    shortage = frame.assign(_cluster=labels).groupby("_cluster")["response_facility_shortage"].mean()
    numbered_clusters = sorted(raw_clusters, key=lambda cluster: (-float(shortage.loc[cluster]), cluster))
    display = {
        cluster: _cluster_name(types_by_cluster[cluster], number)
        for number, cluster in enumerate(numbered_clusters, start=1)
    }
    display[-1] = "특이·개별검토형"

    ordered = frame.assign(_cluster=labels).sort_values(
        ["response_facility_shortage", "dong_code"], ascending=[False, True]
    )
    priority = {index: rank for rank, index in enumerate(ordered.index, start=1)}
    local_priority: dict[int, int] = {}
    for cluster in set(labels):
        part = frame.loc[labels == cluster].sort_values(
            ["response_facility_shortage", "dong_code"], ascending=[False, True]
        )
        local_priority.update({index: rank for rank, index in enumerate(part.index, start=1)})

    assignments: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        cluster = int(labels[index])
        if cluster == -1:
            z_values = z_frame.loc[index].rename(index=FEATURE_LABELS)
            top = z_values.abs().sort_values(ascending=False).index[:3].tolist()
            causes = [FEATURE_CAUSE[name] for name in top if z_values[name] > 0]
            causes = list(dict.fromkeys(causes)) or ["현장 정밀진단 필요"]
            facilities = ["현장 정밀진단", "기존시설 유지관리", "폭염 취약계층 모니터링"]
            cluster_type = "특이·개별검토형"
        else:
            causes = causes_by_cluster[cluster]
            facilities = recommendations_for(types_by_cluster[cluster], causes)
            cluster_type = types_by_cluster[cluster]
        assignments.append(
            {
                "dong_code": row["dong_code"],
                "district_name": row["district_name"],
                "dong_name": row["dong_name"],
                "dbscan_cluster": cluster,
                "cluster_name": display[cluster],
                "cluster_type": cluster_type,
                "is_noise": cluster == -1,
                "global_installation_priority": priority[index],
                "cluster_installation_priority": local_priority[index],
                "main_causes": causes[:3],
                "recommended_facilities": facilities[:3],
                "feature_zscores": {
                    key: round(float(z_frame.loc[index, key]), 6) for key in FEATURE_KEYS
                },
            }
        )

    clusters: list[dict[str, Any]] = []
    for cluster in numbered_clusters:
        member_indices = np.flatnonzero(labels == cluster)
        member_assignments = [item for item in assignments if item["dbscan_cluster"] == cluster]
        ranking = sorted(member_assignments, key=lambda item: item["cluster_installation_priority"])[:5]
        clusters.append(
            {
                "dbscan_cluster": cluster,
                "cluster_name": display[cluster],
                "cluster_type": types_by_cluster[cluster],
                "dong_count": int(len(member_indices)),
                "main_causes": causes_by_cluster[cluster][:3],
                "recommended_facilities": recommendations_for(
                    types_by_cluster[cluster], causes_by_cluster[cluster]
                )[:3],
                "feature_raw_means": {
                    key: round(float(profiles_raw.loc[cluster, key]), 6) for key in FEATURE_KEYS
                },
                "feature_zscore_means": {
                    key: round(float(profiles_z.loc[cluster, key]), 6) for key in FEATURE_KEYS
                },
                "top_shap_features": [
                    {
                        "key": next(key for key, label in FEATURE_LABELS.items() if label == feature),
                        "label": feature,
                        "mean_abs_shap": round(float(value), 8),
                    }
                    for feature, value in importance_by_cluster[cluster]
                    .sort_values(ascending=False)
                    .head(3)
                    .items()
                ],
                "priority_dongs": ranking,
            }
        )

    global_importance = pd.Series(
        np.mean(np.abs(shap_values), axis=(0, 2)), index=FEATURE_KEYS
    ).sort_values(ascending=False)
    warning: list[str] = [
        "DBSCAN은 새 행정동 한 건을 예측하지 않습니다. 시설 시뮬레이션 후에는 전체 행정동 스냅샷을 다시 전송해 재군집화하세요.",
        "SHAP은 DBSCAN 군집을 구분하는 대리모델의 설명값이며 인과효과가 아닙니다.",
    ]
    if accuracy < 0.75 or macro_f1 < 0.70:
        warning.append("대리모델 성능이 낮아 SHAP 해석 신뢰도가 낮습니다.")
    if bool(shap_info.get("fallback")):
        warning.append("shap 패키지 대신 정확 열거형 interventional SHAP을 사용했습니다.")

    result = {
        "metadata": {
            "analysis_scope": "요청에 포함된 전체 행정동 스냅샷",
            "record_count": int(len(frame)),
            "feature_keys": list(FEATURE_KEYS),
            "dbscan": {
                "eps": float(selected["eps"]),
                "min_samples": int(selected["min_samples"]),
                "cluster_count_excluding_noise": int(selected["군집수_노이즈제외"]),
                "noise_count": int(selected["노이즈수"]),
                "noise_ratio": float(selected["노이즈비율"]),
                "silhouette_score": float(selected["Silhouette_Score"]),
                "parameter_search_expanded": expanded_search,
            },
            "surrogate_validation": {
                "model": model_name,
                "model_note": model_note,
                "cv_folds": cv_folds,
                "accuracy": accuracy,
                "macro_f1": macro_f1,
                "shap_method": shap_info["method"],
            },
            "warnings": warning,
        },
        "global_feature_importance": [
            {
                "key": key,
                "label": FEATURE_LABELS[key],
                "mean_abs_shap": round(float(value), 8),
            }
            for key, value in global_importance.items()
        ],
        "clusters": clusters,
        "assignments": sorted(assignments, key=lambda item: item["global_installation_priority"]),
    }
    return _native(result)
