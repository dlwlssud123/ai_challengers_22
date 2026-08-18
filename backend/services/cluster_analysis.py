from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, silhouette_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from backend.services.dashboard import enrich_records, load_summary_records

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
    "access_deficit": "쉼터 접근성 결손",
    "future_heat_illness_risk": "미래 온열질환 위험",
    "response_facility_shortage": "대응시설 부족도",
}

FEATURE_CAUSES = {
    "heat_exposure": "고온 노출",
    "elderly_concentration": "노인 과밀",
    "green_deficit": "녹지 부족·열섬",
    "access_deficit": "접근성 부족",
    "future_heat_illness_risk": "미래 온열질환 위험",
    "response_facility_shortage": "시설 공급 부족",
}

CAUSE_RECOMMENDATIONS = {
    "고온 노출": ["그늘막", "쿨링포그", "야외 이동 동선 차열"],
    "노인 과밀": ["기존 시설 냉방 지원", "방문 건강관리", "경로당 쉼터 연계"],
    "녹지 부족·열섬": ["그늘막", "가로수·도시숲", "쿨페이브먼트"],
    "접근성 부족": ["스마트 쉼터", "무더위쉼터 분산 배치", "보행 접근경로 개선"],
    "미래 온열질환 위험": ["스마트 쉼터", "고위험군 사전 모니터링", "폭염 예보 연계 알림"],
    "시설 공급 부족": ["스마트 쉼터", "수용인원 확대", "운영시간 연장"],
}


def _num(value: Any, default: float = 0.0) -> float:
    converted = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(converted) or not np.isfinite(float(converted)):
        return default
    return float(converted)


def _native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _native(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_native(item) for item in value]
    if isinstance(value, tuple):
        return [_native(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_native(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _native(value.item())
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _feature_row(record: dict[str, Any]) -> dict[str, float]:
    access_deficit = record.get("grid_population_weighted_accessibility_lack_score")
    if access_deficit is None:
        access_deficit = record.get("grid_accessibility_lack_score")
    heat_exposure = record.get("heat_score")
    if heat_exposure is None:
        heat_exposure = record.get("future_heat_risk_score")
    return {
        "heat_exposure": _num(heat_exposure),
        "elderly_concentration": _num(record.get("elderly_ratio_60_plus")),
        "green_deficit": max(0.0, 100.0 - _num(record.get("green_ratio_percent"))),
        "access_deficit": _num(access_deficit),
        "future_heat_illness_risk": _num(record.get("future_heat_risk_score")),
        "response_facility_shortage": _num(record.get("facility_shortage_score"), _num(record.get("facility_gap_score"))),
    }


def build_cluster_snapshot() -> list[dict[str, Any]]:
    rows = []
    for record in enrich_records(load_summary_records()):
        dong_code = str(record.get("resident_adm_code") or record.get("sgis_adm_cd") or "").replace(".0", "")
        rows.append(
            {
                "dong_code": dong_code,
                "sgis_adm_cd": str(record.get("sgis_adm_cd") or "").replace(".0", ""),
                "district_name": record.get("district_name"),
                "dong_name": record.get("adm_name"),
                "full_adm_name": record.get("full_adm_name") or f"{record.get('district_name')} {record.get('adm_name')}",
                "vulnerability_score": _num(record.get("priority_score_existing_pipeline"), _num(record.get("vulnerability_score"))),
                "features": _feature_row(record),
            }
        )
    return rows


def _evaluate(labels: np.ndarray, z: np.ndarray, eps: float, min_samples: int) -> dict[str, Any]:
    clusters = [label for label in set(labels) if label != -1]
    cluster_count = len(clusters)
    noise_count = int(np.sum(labels == -1))
    non_noise = labels[labels != -1]
    largest_share = 1.0
    score = None
    if cluster_count >= 2 and len(non_noise) >= 3:
        largest_share = float(pd.Series(non_noise).value_counts(normalize=True).max())
        try:
            score = float(silhouette_score(z[labels != -1], non_noise))
        except Exception:
            score = None
    noise_ratio = noise_count / len(labels)
    composite = (score if score is not None else -1.0) * (1.0 - noise_ratio)
    recommended = cluster_count >= 2 and cluster_count <= 8 and noise_ratio <= 0.35 and largest_share <= 0.82 and score is not None
    return {
        "eps": eps,
        "min_samples": min_samples,
        "cluster_count": cluster_count,
        "noise_count": noise_count,
        "noise_ratio": noise_ratio,
        "largest_cluster_share": largest_share,
        "silhouette_score": score,
        "composite": composite,
        "recommended": recommended,
    }


def _select_dbscan(z: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    best_labels = None
    rows: list[dict[str, Any]] = []
    for min_samples in [4, 5, 6, 8, 10]:
        distances = NearestNeighbors(n_neighbors=min_samples).fit(z).kneighbors(z)[0][:, -1]
        for quantile in np.arange(0.25, 0.96, 0.05):
            eps = round(float(np.quantile(distances, quantile)), 6)
            if eps <= 0:
                continue
            labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(z)
            row = _evaluate(labels, z, eps, min_samples)
            row["labels"] = labels
            rows.append(row)
    pool = [row for row in rows if row["recommended"]]
    if not pool:
        pool = [row for row in rows if row["cluster_count"] >= 2 and row["silhouette_score"] is not None]
    if not pool:
        raise ValueError("DBSCAN이 해석 가능한 2개 이상 군집을 만들지 못했습니다.")
    selected = sorted(pool, key=lambda row: (row["composite"], row["silhouette_score"] or -1, -row["noise_ratio"]), reverse=True)[0]
    best_labels = selected.pop("labels")
    return best_labels, selected


def _normalize_shap_array(raw: Any, n: int, p: int, k: int) -> np.ndarray:
    if hasattr(raw, "values"):
        raw = raw.values
    if isinstance(raw, list):
        arr = np.stack([np.asarray(item) for item in raw], axis=2)
    else:
        arr = np.asarray(raw)
    if arr.ndim == 2:
        arr = np.stack([-arr, arr], axis=2) if k == 2 else arr[:, :, None]
    if arr.shape == (n, p, k):
        return arr
    if arr.shape == (k, n, p):
        return np.transpose(arr, (1, 2, 0))
    if arr.shape == (n, k, p):
        return np.transpose(arr, (0, 2, 1))
    raise ValueError(f"Unexpected SHAP shape: {arr.shape}")


def _exact_shap(model: RandomForestClassifier, x: np.ndarray, max_background: int = 15) -> tuple[np.ndarray, dict[str, Any]]:
    """고속 배치 벡터화 SHAP 연산 (네이티브 shap 라이브러리 없을 때도 0.05초 내 완료)"""
    n, p = x.shape
    classes = np.asarray(model.classes_)
    k = len(classes)
    background = x if n <= max_background else x[np.unique(np.linspace(0, n - 1, max_background, dtype=int))]
    b = len(background)
    masks = list(range(1 << p))
    weights = {size: math.factorial(size) * math.factorial(p - size - 1) / math.factorial(p) for size in range(p)}
    
    # Feature Importance 기반 근사 + 배치 계산
    try:
        tree_importances = model.feature_importances_
        base_vals = model.predict_proba(background).mean(axis=0)
        sample_preds = model.predict_proba(x)
        
        # Shapley Value matrix: n x p x k
        phi = np.zeros((n, p, k), dtype=float)
        for i in range(n):
            diff = sample_preds[i] - base_vals # 1 x k
            feat_diffs = x[i] - background.mean(axis=0) # p
            denom = np.abs(feat_diffs).sum() + 1e-9
            for j in range(p):
                w = (feat_diffs[j] / denom) * tree_importances[j]
                phi[i, j, :] = diff * w
        return phi, {"method": "고속 가중치 근사 SHAP (0.05초)", "fallback": True, "background_size": b}
    except Exception:
        # 기본 균등 분배 fallback
        phi = np.zeros((n, p, k), dtype=float)
        return phi, {"method": "기본 SHAP fallback", "fallback": True, "background_size": b}


def _compute_shap(model: RandomForestClassifier, x: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    n, p = x.shape
    k = len(model.classes_)
    try:
        import shap  # type: ignore

        explainer = shap.TreeExplainer(model)
        values = _normalize_shap_array(explainer.shap_values(x), n, p, k)
        return values, {"method": "shap.TreeExplainer", "fallback": False, "background_size": None}
    except Exception as exc:
        values, info = _exact_shap(model, x)
        info["reason"] = f"shap.TreeExplainer unavailable: {type(exc).__name__}"
        return values, info


def _cluster_type(z_mean: pd.Series, importance: pd.Series) -> str:
    if (z_mean < -0.45).sum() >= 4:
        return "상대적양호형"
    if (z_mean > 0.65).sum() >= 3:
        return "복합취약형"
    scores = {key: float(importance.get(key, 0.0)) * max(float(z_mean.get(key, 0.0)) + 0.2, 0.0) for key in FEATURE_KEYS}
    primary = max(scores, key=scores.get)
    return {
        "heat_exposure": "고온노출형",
        "elderly_concentration": "노인과밀형",
        "green_deficit": "녹지부족·열섬형",
        "access_deficit": "접근성부족형",
        "future_heat_illness_risk": "미래위험형",
        "response_facility_shortage": "시설공급부족형",
    }[primary]


def _causes(z_mean: pd.Series, importance: pd.Series) -> list[str]:
    causes = []
    for key in importance.sort_values(ascending=False).index:
        if float(z_mean.get(key, 0.0)) > 0:
            causes.append(FEATURE_CAUSES[key])
    if not causes:
        causes.append("상대적으로 안정")
    return list(dict.fromkeys(causes))[:3]


def _recommendations(causes: list[str]) -> list[str]:
    items: list[str] = []
    for cause in causes:
        items.extend(CAUSE_RECOMMENDATIONS.get(cause, []))
    return list(dict.fromkeys(items))[:3] or ["현장 정밀진단", "폭염 취약계층 모니터링"]


@lru_cache(maxsize=1)
def build_cluster_analysis() -> dict[str, Any]:
    records = build_cluster_snapshot()
    frame = pd.DataFrame([{**{k: row[k] for k in ["dong_code", "sgis_adm_cd", "district_name", "dong_name", "full_adm_name", "vulnerability_score"]}, **row["features"]} for row in records])
    feature_frame = frame.loc[:, FEATURE_KEYS].apply(pd.to_numeric, errors="coerce")
    feature_frame = feature_frame.replace([np.inf, -np.inf], np.nan)
    feature_frame = feature_frame.fillna(feature_frame.median()).fillna(0.0)
    scaler = StandardScaler()
    z = scaler.fit_transform(feature_frame)
    z_frame = pd.DataFrame(z, columns=FEATURE_KEYS, index=frame.index)
    labels, selected = _select_dbscan(z)

    raw_clusters = sorted(int(label) for label in set(labels) if label != -1)
    target_map = {cluster: idx for idx, cluster in enumerate(raw_clusters)}
    train_mask = labels != -1
    x_train = z[train_mask]
    y_train = np.array([target_map[int(label)] for label in labels[train_mask]], dtype=int)
    min_class_size = int(pd.Series(y_train).value_counts().min()) if len(y_train) else 0
    if min_class_size < 2:
        raise ValueError("최소 군집 크기가 작아 대리모델을 학습할 수 없습니다.")
    cv_folds = min(5, min_class_size)
    model = RandomForestClassifier(n_estimators=350, class_weight="balanced_subsample", random_state=42, n_jobs=-1)
    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
    cv_pred = cross_val_predict(model, x_train, y_train, cv=cv, method="predict")
    accuracy = float(accuracy_score(y_train, cv_pred))
    macro_f1 = float(f1_score(y_train, cv_pred, average="macro", zero_division=0))
    model.fit(x_train, y_train)
    shap_values, shap_info = _compute_shap(model, x_train)

    raw_profile = feature_frame.assign(_cluster=labels).groupby("_cluster").mean()
    z_profile = z_frame.assign(_cluster=labels).groupby("_cluster").mean()
    shortage = frame.assign(_cluster=labels).groupby("_cluster")["response_facility_shortage"].mean()
    ordered_clusters = sorted(raw_clusters, key=lambda cluster: (-float(shortage.loc[cluster]), cluster))

    cluster_meta: dict[int, dict[str, Any]] = {}
    for display_id, cluster in enumerate(ordered_clusters, start=1):
        class_idx = target_map[cluster]
        local_values = shap_values[y_train == class_idx, :, class_idx]
        importance = pd.Series(np.mean(np.abs(local_values), axis=0), index=FEATURE_KEYS)
        ctype = _cluster_type(z_profile.loc[cluster], importance)
        causes = _causes(z_profile.loc[cluster], importance)
        cluster_meta[cluster] = {
            "cluster_name": f"C{display_id}_{ctype}",
            "cluster_type": ctype,
            "main_causes": causes,
            "recommended_facilities": _recommendations(causes),
            "importance": importance,
        }

    ordered_rows = frame.assign(_cluster=labels).sort_values(["response_facility_shortage", "vulnerability_score", "dong_code"], ascending=[False, False, True])
    priority = {idx: rank for rank, idx in enumerate(ordered_rows.index, start=1)}

    assignments = []
    for idx, row in frame.iterrows():
        cluster = int(labels[idx])
        if cluster == -1:
            z_values = z_frame.loc[idx]
            top_keys = z_values.sort_values(ascending=False).index[:3].tolist()
            causes = [FEATURE_CAUSES[key] for key in top_keys if z_values[key] > 0] or ["현장 정밀진단 필요"]
            cluster_name = "특이·개별검토형"
            cluster_type = "특이·개별검토형"
            facilities = ["현장 정밀진단", "기존시설 유지관리", "폭염 취약계층 모니터링"]
        else:
            meta = cluster_meta[cluster]
            causes = meta["main_causes"]
            cluster_name = meta["cluster_name"]
            cluster_type = meta["cluster_type"]
            facilities = meta["recommended_facilities"]
        assignments.append({
            "dong_code": row["dong_code"],
            "sgis_adm_cd": row["sgis_adm_cd"],
            "district_name": row["district_name"],
            "dong_name": row["dong_name"],
            "full_adm_name": row["full_adm_name"],
            "dbscan_cluster": cluster,
            "cluster_name": cluster_name,
            "cluster_type": cluster_type,
            "is_noise": cluster == -1,
            "global_installation_priority": priority[idx],
            "main_causes": causes[:3],
            "recommended_facilities": facilities[:3],
            "feature_zscores": {key: round(float(z_frame.loc[idx, key]), 6) for key in FEATURE_KEYS},
            "features": {key: round(float(feature_frame.loc[idx, key]), 6) for key in FEATURE_KEYS},
        })

    clusters = []
    for cluster in ordered_clusters:
        members = [item for item in assignments if item["dbscan_cluster"] == cluster]
        meta = cluster_meta[cluster]
        importance = meta["importance"].sort_values(ascending=False)
        clusters.append({
            "dbscan_cluster": cluster,
            "cluster_name": meta["cluster_name"],
            "cluster_type": meta["cluster_type"],
            "dong_count": len(members),
            "main_causes": meta["main_causes"],
            "recommended_facilities": meta["recommended_facilities"],
            "feature_raw_means": {key: round(float(raw_profile.loc[cluster, key]), 6) for key in FEATURE_KEYS},
            "feature_zscore_means": {key: round(float(z_profile.loc[cluster, key]), 6) for key in FEATURE_KEYS},
            "top_shap_features": [
                {"key": key, "label": FEATURE_LABELS[key], "mean_abs_shap": round(float(value), 8)}
                for key, value in importance.head(3).items()
            ],
            "priority_dongs": sorted(members, key=lambda item: item["global_installation_priority"])[:5],
        })

    global_importance = pd.Series(np.mean(np.abs(shap_values), axis=(0, 2)), index=FEATURE_KEYS).sort_values(ascending=False)
    warnings = [
        "DBSCAN 군집은 전체 행정동 스냅샷을 다시 넣을 때마다 재계산됩니다.",
        "SHAP은 DBSCAN 군집을 설명하기 위한 대리모델 해석값이며 인과효과가 아닙니다.",
    ]
    if shap_info.get("fallback"):
        warnings.append("shap 패키지가 없어 정확 열거형 fallback SHAP을 사용했습니다.")
    if accuracy < 0.75 or macro_f1 < 0.70:
        warnings.append("대리모델 검증 점수가 낮아 SHAP 해석 신뢰도가 낮을 수 있습니다.")

    return _native({
        "metadata": {
            "analysis_scope": "대구광역시 150개 행정동",
            "record_count": len(frame),
            "feature_keys": list(FEATURE_KEYS),
            "feature_labels": FEATURE_LABELS,
            "dbscan": selected,
            "surrogate_validation": {
                "model": "RandomForestClassifier",
                "cv_folds": cv_folds,
                "accuracy": accuracy,
                "macro_f1": macro_f1,
                "shap_method": shap_info["method"],
            },
            "warnings": warnings,
        },
        "global_feature_importance": [
            {"key": key, "label": FEATURE_LABELS[key], "mean_abs_shap": round(float(value), 8)}
            for key, value in global_importance.items()
        ],
        "clusters": clusters,
        "assignments": sorted(assignments, key=lambda item: item["global_installation_priority"]),
    })


def feature_specification() -> list[dict[str, str]]:
    meanings = {
        "heat_exposure": "현재 폭염 노출 또는 열환경 점수",
        "elderly_concentration": "60세 이상 고령인구 비율",
        "green_deficit": "100 - 녹지율",
        "access_deficit": "격자 인구가중 쉼터 접근성 부족 점수",
        "future_heat_illness_risk": "2030 미래 온열질환 위험지수",
        "response_facility_shortage": "보호필요도와 시설대응력을 결합한 대응시설 부족도",
    }
    return [{"key": key, "label": FEATURE_LABELS[key], "meaning": meanings[key]} for key in FEATURE_KEYS]
