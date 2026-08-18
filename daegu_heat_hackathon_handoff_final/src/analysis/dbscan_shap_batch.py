#!/usr/bin/env python3
"""Daegu administrative-dong DBSCAN + tree surrogate + SHAP analysis.

The script is intentionally self-contained.  It prefers XGBoost and the SHAP
TreeExplainer when those optional packages are installed.  In restricted
environments it falls back to a RandomForest surrogate and an exact exhaustive
interventional Shapley calculation over the six clustering features.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from itertools import chain
from pathlib import Path
from typing import Any, Iterable

# This module is imported by the API service too.  Use a writable cache in
# minimal containers before importing matplotlib so model requests do not emit
# a warning or fail because /root/.config is read-only.
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.base import clone
from sklearn.cluster import DBSCAN
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    adjusted_rand_score,
    calinski_harabasz_score,
    confusion_matrix,
    davies_bouldin_score,
    f1_score,
    silhouette_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler


SEED = 42
INITIAL_MIN_SAMPLES = [4, 5, 6, 8, 10]
EPS_QUANTILES = [
    0.40,
    0.50,
    0.55,
    0.60,
    0.65,
    0.70,
    0.75,
    0.80,
    0.85,
    0.90,
    0.92,
    0.94,
    0.95,
    0.96,
    0.97,
    0.98,
    0.99,
]

FEATURE_ENGLISH = {
    "고온 노출": "Heat exposure",
    "고령자 집중도": "Age 70+ concentration",
    "녹지 부족도": "Green-space deficit",
    "접근성 결손": "Shelter access deficit",
    "미래 온열질환 위험": "Future heat-illness risk",
    "대응시설 부족도": "Response-facility shortage",
}

FEATURE_CAUSE = {
    "고온 노출": "고온 노출",
    "고령자 집중도": "노인 과밀",
    "녹지 부족도": "녹지 부족·열섬",
    "접근성 결손": "접근성 부족",
    "미래 온열질환 위험": "미래 온열질환 위험",
    "대응시설 부족도": "시설 공급 부족",
}

CAUSE_RECOMMENDATIONS = {
    "접근성 부족": ["실내 무더위쉼터 신설", "기존 쉼터 이전·분산", "보행 접근경로 개선"],
    "녹지 부족·열섬": ["도시숲", "가로수", "그늘막"],
    "노인 과밀": ["경로당 무더위쉼터 연계", "냉방설비 보강", "방문 건강관리"],
    "고온 노출": ["그늘막", "쿨링포그", "야외근로자 휴게시설"],
    "시설 공급 부족": ["무더위쉼터 신설", "수용인원 확대", "운영시간 연장"],
    "미래 온열질환 위험": ["실내 무더위쉼터 신설", "그늘막", "방문 건강관리"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(os.getenv("ANALYSIS_INPUT_DIR", "data/raw")),
        help=(
            "원본 분석 데이터 폴더. 기본값은 data/raw이며, "
            "ANALYSIS_INPUT_DIR 환경변수로도 지정할 수 있습니다."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("ANALYSIS_OUTPUT_DIR", "data/outputs")),
        help=(
            "분석 산출물 폴더. 기본값은 data/outputs이며, "
            "ANALYSIS_OUTPUT_DIR 환경변수로도 지정할 수 있습니다."
        ),
    )
    return parser.parse_args()


def find_input(input_dir: Path, stem: str, suffix: str, required: bool = True) -> Path | None:
    matches = sorted(input_dir.glob(f"{stem}*{suffix}"))
    if len(matches) == 1:
        return matches[0]
    if not matches and not required:
        return None
    if not matches:
        raise FileNotFoundError(f"입력 파일을 찾지 못했습니다: {stem}*{suffix}")
    raise RuntimeError(f"입력 파일 후보가 둘 이상입니다: {[p.name for p in matches]}")


def normalize_name(value: Any) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"[\s\.,·ㆍ]+", "", str(value)).lower()


def normalize_code(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    text = re.sub(r"\.0$", "", text)
    return text.zfill(10) if text.isdigit() else text


def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig")


def json_ready(value: Any) -> Any:
    """Recursively convert NumPy/Pandas scalars into JSON-native values."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [json_ready(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(json_ready(key)): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if pd.isna(value) if not isinstance(value, (str, bytes)) else False:
        return None
    return value


def duplicate_records(df: pd.DataFrame, source: str, key_col: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    dup_mask = df[key_col].duplicated(keep=False) & df[key_col].ne("")
    for key, part in df.loc[dup_mask].groupby(key_col, dropna=False):
        records.append(
            {
                "자료원": source,
                "중복키": key,
                "중복건수": len(part),
                "관련행": " | ".join(
                    part.apply(
                        lambda r: f"{r.get('구·군', r.get('district_name', ''))} {r.get('행정동', r.get('dong_name', ''))}",
                        axis=1,
                    )
                ),
                "처리": "임의 결합 중단",
            }
        )
    return records


def safe_numeric(series: pd.Series) -> tuple[pd.Series, int]:
    converted = pd.to_numeric(series, errors="coerce")
    nonconvertible = int(series.notna().sum() - converted.notna().sum())
    return converted.astype(float), nonconvertible


def range_status(series: pd.Series, lower: float | None, upper: float | None) -> str:
    valid = series.dropna()
    if valid.empty:
        return "값 없음"
    bad_low = int((valid < lower).sum()) if lower is not None else 0
    bad_high = int((valid > upper).sum()) if upper is not None else 0
    if bad_low or bad_high:
        return f"범위 이탈 {bad_low + bad_high}건(하한 {bad_low}, 상한 {bad_high})"
    return "정상"


def make_feature_log_row(
    concept: str,
    preferred: str,
    selected: str,
    source: str,
    substitution: str,
    reason: str,
    original: pd.Series,
    numeric: pd.Series,
    nonconvertible: int,
    median: float | None,
    imputed: int,
    expected: str,
    status: str,
    used: str = "Y",
    exclusion_reason: str = "",
) -> dict[str, Any]:
    return {
        "Feature개념": concept,
        "우선변수": preferred,
        "최종변수": selected,
        "자료원": source,
        "대체변수사용": substitution,
        "선택·대체사유": reason,
        "원자료비결측수": int(original.notna().sum()),
        "수치변환불가건수": nonconvertible,
        "대체전결측수": int(numeric.isna().sum()),
        "중앙값": median,
        "중앙값대체건수": imputed,
        "기대범위": expected,
        "관측최솟값": float(numeric.min()) if numeric.notna().any() else np.nan,
        "관측최댓값": float(numeric.max()) if numeric.notna().any() else np.nan,
        "범위검사": status,
        "군집Feature사용": used,
        "제외사유": exclusion_reason,
    }


def evaluate_labels(
    z: np.ndarray,
    labels: np.ndarray,
    eps: float,
    min_samples: int,
    phase: str,
    eps_source: str,
    reference_labels: np.ndarray | None = None,
) -> dict[str, Any]:
    nonnoise = labels != -1
    clusters = sorted(set(labels[nonnoise].tolist()))
    sizes = [int((labels == c).sum()) for c in clusters]
    n_clusters = len(clusters)
    noise_count = int((~nonnoise).sum())
    noise_ratio = noise_count / len(labels)
    largest_share = max(sizes) / sum(sizes) if sizes else 1.0
    silhouette = np.nan
    ch = np.nan
    db = np.nan
    if n_clusters >= 2 and nonnoise.sum() > n_clusters:
        silhouette = float(silhouette_score(z[nonnoise], labels[nonnoise]))
        ch = float(calinski_harabasz_score(z[nonnoise], labels[nonnoise]))
        db = float(davies_bouldin_score(z[nonnoise], labels[nonnoise]))
    composite = silhouette * (1.0 - noise_ratio) if np.isfinite(silhouette) else np.nan
    preferred = bool(
        2 <= n_clusters <= 8
        and noise_ratio <= 0.30
        and largest_share <= 0.80
        and np.isfinite(silhouette)
    )
    ari = (
        float(adjusted_rand_score(reference_labels, labels))
        if reference_labels is not None
        else np.nan
    )
    return {
        "평가단계": phase,
        "eps후보근거": eps_source,
        "eps": float(eps),
        "min_samples": int(min_samples),
        "군집수_노이즈제외": n_clusters,
        "노이즈수": noise_count,
        "노이즈비율": noise_ratio,
        "Silhouette_Score": silhouette,
        "Calinski_Harabasz_Score": ch,
        "Davies_Bouldin_Score": db,
        "Silhouette_x_비노이즈비율": composite,
        "최대군집점유율_비노이즈기준": largest_share,
        "최소군집크기": min(sizes) if sizes else 0,
        "군집크기": ",".join(map(str, sorted(sizes, reverse=True))),
        "권장조건충족": "Y" if preferred else "N",
        "선정모델": "N",
        "선정·비선정사유": "",
        "기준모델대비_ARI": ari,
    }


def k_distance_candidates(z: np.ndarray, min_samples: int) -> dict[float, list[str]]:
    distances = NearestNeighbors(n_neighbors=min_samples, metric="euclidean").fit(z).kneighbors(z)[0][:, -1]
    distances = np.sort(distances)
    candidates: dict[float, list[str]] = defaultdict(list)
    for q in EPS_QUANTILES:
        value = round(float(np.quantile(distances, q)), 6)
        if value > 0:
            candidates[value].append(f"k-distance q{int(q * 100)}")
    x = np.linspace(0.0, 1.0, len(distances))
    span = float(distances.max() - distances.min())
    if span > 0:
        y = (distances - distances.min()) / span
        knee_idx = int(np.argmax(x - y))
        knee = float(distances[knee_idx])
    else:
        knee = float(distances[-1])
    for factor in [0.80, 0.90, 1.00, 1.10, 1.20]:
        value = round(knee * factor, 6)
        if value > 0:
            candidates[value].append(f"knee×{factor:.2f}")
    return candidates


def select_dbscan(z: np.ndarray) -> tuple[np.ndarray, dict[str, Any], pd.DataFrame, bool]:
    rows: list[dict[str, Any]] = []
    label_cache: dict[tuple[float, int], np.ndarray] = {}
    for min_samples in INITIAL_MIN_SAMPLES:
        candidates = k_distance_candidates(z, min_samples)
        for eps, sources in sorted(candidates.items()):
            labels = DBSCAN(eps=eps, min_samples=min_samples, metric="euclidean").fit_predict(z)
            label_cache[(eps, min_samples)] = labels
            rows.append(
                evaluate_labels(
                    z,
                    labels,
                    eps,
                    min_samples,
                    "초기탐색",
                    "+".join(sources),
                )
            )
    evaluation = pd.DataFrame(rows)
    valid = evaluation[evaluation["권장조건충족"].eq("Y")].copy()
    expanded = False
    if valid.empty:
        expanded = True
        expanded_min_samples = [3, 4, 5, 6, 8, 10, 12]
        expanded_quantiles = np.arange(0.20, 0.996, 0.025)
        extra_rows: list[dict[str, Any]] = []
        for min_samples in expanded_min_samples:
            distances = NearestNeighbors(n_neighbors=min_samples).fit(z).kneighbors(z)[0][:, -1]
            for q in expanded_quantiles:
                eps = round(float(np.quantile(distances, q)), 6)
                if eps <= 0 or (eps, min_samples) in label_cache:
                    continue
                labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(z)
                label_cache[(eps, min_samples)] = labels
                extra_rows.append(
                    evaluate_labels(
                        z,
                        labels,
                        eps,
                        min_samples,
                        "확대탐색",
                        f"확대 k-distance q{q:.3f}",
                    )
                )
        evaluation = pd.concat([evaluation, pd.DataFrame(extra_rows)], ignore_index=True)
        valid = evaluation[evaluation["권장조건충족"].eq("Y")].copy()
    if valid.empty:
        relaxed = evaluation[
            evaluation["군집수_노이즈제외"].between(2, 8)
            & evaluation["Silhouette_Score"].notna()
        ].copy()
        if relaxed.empty:
            raise RuntimeError("2개 이상 군집을 형성하는 DBSCAN 후보가 없습니다.")
        pool = relaxed
        selection_reason = "권장조건 충족 후보 부재: 2~8개 군집 후보 중 복합점수 최상 선택"
    else:
        pool = valid
        selection_reason = (
            "군집수 2~8, 노이즈≤30%, 최대군집점유율≤80% 조건 내 "
            "Silhouette×비노이즈비율 최상"
        )
    order = pool.sort_values(
        [
            "Silhouette_x_비노이즈비율",
            "Silhouette_Score",
            "노이즈비율",
            "최대군집점유율_비노이즈기준",
            "군집수_노이즈제외",
        ],
        ascending=[False, False, True, True, True],
    )
    selected_index = int(order.index[0])
    evaluation.loc[selected_index, "선정모델"] = "Y"
    evaluation.loc[selected_index, "선정·비선정사유"] = selection_reason
    selected = evaluation.loc[selected_index].to_dict()
    eps = float(selected["eps"])
    min_samples = int(selected["min_samples"])
    labels = label_cache[(eps, min_samples)]

    sensitivity_rows: list[dict[str, Any]] = []
    for eps_factor in [0.90, 1.00, 1.10]:
        for ms_delta in [-2, 0, 2]:
            ms = max(2, min_samples + ms_delta)
            sens_eps = round(eps * eps_factor, 6)
            sens_labels = DBSCAN(eps=sens_eps, min_samples=ms).fit_predict(z)
            sensitivity_rows.append(
                evaluate_labels(
                    z,
                    sens_labels,
                    sens_eps,
                    ms,
                    "민감도분석",
                    f"선정eps×{eps_factor:.2f}, min_samples{ms_delta:+d}",
                    reference_labels=labels,
                )
            )
    evaluation = pd.concat([evaluation, pd.DataFrame(sensitivity_rows)], ignore_index=True)
    evaluation["선정·비선정사유"] = evaluation["선정·비선정사유"].fillna("")
    return labels, selected, evaluation, expanded


def make_surrogate(n_classes: int) -> tuple[Any, str, str]:
    try:
        from xgboost import XGBClassifier  # type: ignore

        model = XGBClassifier(
            n_estimators=350,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.90,
            colsample_bytree=0.90,
            objective="multi:softprob" if n_classes > 2 else "binary:logistic",
            eval_metric="mlogloss",
            random_state=SEED,
            n_jobs=1,
        )
        return model, "XGBoostClassifier", "XGBoost 사용"
    except Exception as exc:
        model = RandomForestClassifier(
            n_estimators=400,
            max_depth=None,
            min_samples_leaf=1,
            class_weight="balanced_subsample",
            random_state=SEED,
            n_jobs=-1,
        )
        return model, "RandomForestClassifier", f"XGBoost 사용 불가로 RandomForest 대체: {type(exc).__name__}"


def normalize_shap_array(raw: Any, n: int, p: int, k: int) -> np.ndarray:
    if hasattr(raw, "values"):
        raw = raw.values
    if isinstance(raw, list):
        arr = np.stack([np.asarray(x) for x in raw], axis=2)
    else:
        arr = np.asarray(raw)
    if arr.ndim == 2:
        if k == 2:
            arr = np.stack([-arr, arr], axis=2)
        else:
            arr = arr[:, :, None]
    if arr.ndim != 3:
        raise ValueError(f"예상하지 못한 SHAP 차원: {arr.shape}")
    if arr.shape == (n, p, k):
        return arr
    if arr.shape == (k, n, p):
        return np.transpose(arr, (1, 2, 0))
    if arr.shape == (n, k, p):
        return np.transpose(arr, (0, 2, 1))
    raise ValueError(f"SHAP 배열을 (표본, Feature, 군집)으로 정규화할 수 없습니다: {arr.shape}")


def exact_interventional_shap(
    model: Any, x: np.ndarray, max_background: int = 50
) -> tuple[np.ndarray, np.ndarray, float, int]:
    """Exact Shapley enumeration for six features with an empirical background."""
    n, p = x.shape
    classes = np.asarray(model.classes_)
    k = len(classes)
    if n <= max_background:
        background = x.copy()
    else:
        idx = np.unique(np.linspace(0, n - 1, max_background, dtype=int))
        background = x[idx]
    b = len(background)
    masks = list(range(1 << p))
    factorial = math.factorial
    weights = {
        size: factorial(size) * factorial(p - size - 1) / factorial(p)
        for size in range(p)
    }
    phi = np.zeros((n, p, k), dtype=float)
    baseline = model.predict_proba(background).mean(axis=0)
    for i in range(n):
        batch = np.tile(background, (len(masks), 1))
        for mask in masks:
            start = mask * b
            end = start + b
            for feature_index in range(p):
                if mask & (1 << feature_index):
                    batch[start:end, feature_index] = x[i, feature_index]
        values = model.predict_proba(batch).reshape(len(masks), b, k).mean(axis=1)
        for feature_index in range(p):
            bit = 1 << feature_index
            for mask in masks:
                if mask & bit:
                    continue
                size = int(mask.bit_count())
                phi[i, feature_index, :] += weights[size] * (
                    values[mask | bit, :] - values[mask, :]
                )
    predicted = model.predict_proba(x)
    residual = float(np.max(np.abs(predicted - (baseline[None, :] + phi.sum(axis=1)))))
    return phi, baseline, residual, b


def compute_shap(model: Any, x: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    n, p = x.shape
    k = len(model.classes_)
    try:
        import shap  # type: ignore

        explainer = shap.TreeExplainer(model)
        raw = explainer.shap_values(x)
        values = normalize_shap_array(raw, n, p, k)
        return values, {
            "method": "shap.TreeExplainer",
            "fallback": False,
            "reason": "",
            "array_shape": list(values.shape),
            "additivity_max_abs_error": None,
            "background_size": None,
        }
    except Exception as exc:
        values, _baseline, residual, background_size = exact_interventional_shap(model, x)
        return values, {
            "method": "정확 열거형 interventional SHAP (TreeExplainer 대체)",
            "fallback": True,
            "reason": f"SHAP TreeExplainer 사용 불가: {type(exc).__name__}: {exc}",
            "array_shape": list(values.shape),
            "additivity_max_abs_error": residual,
            "background_size": background_size,
        }


def cluster_type_from_profile(z_mean: pd.Series, importance: pd.Series) -> str:
    negative_count = int((z_mean < 0).sum())
    if (
        z_mean.get("미래 온열질환 위험", 0) < -0.50
        and z_mean.get("대응시설 부족도", 0) < -0.50
        and negative_count >= 4
    ):
        return "상대적양호형"
    specific = [
        "고온 노출",
        "고령자 집중도",
        "녹지 부족도",
        "접근성 결손",
        "대응시설 부족도",
    ]
    if sum(z_mean.get(f, 0) > 0.75 for f in specific) >= 3:
        return "복합취약형"
    scores = {
        feature: float(importance.get(feature, 0)) * max(float(z_mean.get(feature, 0)) + 0.25, 0)
        for feature in specific
    }
    primary = max(scores, key=scores.get)
    return {
        "고온 노출": "고온노출형",
        "고령자 집중도": "노인과밀형",
        "녹지 부족도": "녹지부족·열섬형",
        "접근성 결손": "접근성부족형",
        "대응시설 부족도": "시설공급부족형",
    }[primary]


def causes_from_profile(z_mean: pd.Series, importance: pd.Series) -> list[str]:
    ranked = list(importance.sort_values(ascending=False).index)
    causes: list[str] = []
    for feature in ranked:
        if float(z_mean.get(feature, 0)) <= 0.15:
            continue
        cause = FEATURE_CAUSE[feature]
        if cause not in causes:
            causes.append(cause)
        if len(causes) == 3:
            break
    if not causes:
        causes = ["대구 평균 이하(상대적 양호)"]
    return causes


def recommendations_for(cluster_type: str, causes: list[str]) -> list[str]:
    if cluster_type == "복합취약형":
        return ["실내 무더위쉼터 신설", "그늘막·쿨링포그 설치", "방문 건강관리 연계"]
    if cluster_type == "상대적양호형":
        return ["기존시설 유지관리", "폭염 취약계층 모니터링", "운영시간 탄력조정"]
    type_priority = {
        "접근성부족형": ["실내 무더위쉼터 신설", "기존 쉼터 이전·분산", "보행 접근경로 개선"],
        "녹지부족·열섬형": ["도시숲", "가로수", "그늘막"],
        "노인과밀형": ["경로당 무더위쉼터 연계", "냉방설비 보강", "방문 건강관리"],
        "고온노출형": ["그늘막", "쿨링포그", "야외근로자 휴게시설"],
        "시설공급부족형": ["무더위쉼터 신설", "수용인원 확대", "운영시간 연장"],
    }
    if cluster_type in type_priority:
        return type_priority[cluster_type]
    candidates: list[str] = []
    for cause in causes:
        candidates.extend(CAUSE_RECOMMENDATIONS.get(cause, []))
    return list(dict.fromkeys(candidates))[:3]


def individual_noise_profile(z_row: pd.Series) -> tuple[list[str], list[str], str]:
    top_features = list(z_row.abs().sort_values(ascending=False).head(3).index)
    causes: list[str] = []
    recommendations: list[str] = []
    details: list[str] = []
    for feature in top_features:
        value = float(z_row[feature])
        details.append(f"{feature} z={value:+.2f}")
        if value > 0:
            cause = FEATURE_CAUSE[feature]
            if cause not in causes:
                causes.append(cause)
            recommendations.extend(CAUSE_RECOMMENDATIONS.get(cause, []))
    if not recommendations:
        causes = ["극단값은 있으나 취약 방향이 아님"]
        recommendations = ["현장 정밀진단", "기존시설 유지관리", "폭염 취약계층 모니터링"]
    return causes[:3], list(dict.fromkeys(recommendations))[:3], "; ".join(details)


def configure_plotting() -> None:
    sns.set_theme(style="whitegrid")
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.unicode_minus": False,
            "figure.dpi": 120,
            "savefig.dpi": 220,
        }
    )


def save_pca_plot(z: np.ndarray, labels: np.ndarray, display: dict[int, str], path: Path) -> None:
    pca = PCA(n_components=2, random_state=SEED)
    coords = pca.fit_transform(z)
    fig, ax = plt.subplots(figsize=(10, 7))
    nonnoise_clusters = sorted(c for c in set(labels) if c != -1)
    palette = sns.color_palette("tab10", n_colors=max(len(nonnoise_clusters), 1))
    for color, cluster in zip(palette, nonnoise_clusters):
        mask = labels == cluster
        short = display[cluster].split("_")[0]
        ax.scatter(coords[mask, 0], coords[mask, 1], s=48, alpha=0.78, color=color, label=short)
    noise = labels == -1
    if noise.any():
        ax.scatter(
            coords[noise, 0],
            coords[noise, 1],
            s=75,
            marker="x",
            linewidth=1.7,
            color="black",
            label="Noise / individual review",
        )
    ax.axhline(0, color="#bbbbbb", linewidth=0.7)
    ax.axvline(0, color="#bbbbbb", linewidth=0.7)
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0] * 100:.1f}% variance)")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1] * 100:.1f}% variance)")
    ax.set_title("Daegu DBSCAN clusters in standardized-feature PCA space")
    ax.legend(frameon=True, fontsize=9, loc="best")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def save_map_notice(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.axis("off")
    ax.text(0.5, 0.65, "Administrative-dong cluster map not produced", ha="center", va="center", fontsize=22, weight="bold")
    ax.text(
        0.5,
        0.43,
        "No administrative-boundary geometry was included in the four input files.\n"
        "No artificial points or boundaries were created.\n"
        "Use dbscan_pca_scatter.png and cluster_profile_heatmap.png instead.",
        ha="center",
        va="center",
        fontsize=15,
        linespacing=1.6,
    )
    ax.add_patch(plt.Rectangle((0.08, 0.18), 0.84, 0.64, fill=False, linewidth=2, edgecolor="#555555"))
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def save_profile_heatmap(profile: pd.DataFrame, path: Path) -> None:
    shown = profile.rename(columns=FEATURE_ENGLISH)
    fig, ax = plt.subplots(figsize=(12, max(4.5, 0.75 * len(shown))))
    sns.heatmap(
        shown,
        cmap="RdBu_r",
        center=0,
        annot=True,
        fmt=".2f",
        linewidths=0.5,
        cbar_kws={"label": "Standardized cluster mean (z)"},
        ax=ax,
    )
    ax.set_xlabel("")
    ax.set_ylabel("Cluster")
    ax.set_title("DBSCAN cluster profiles")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def save_shap_summary(
    shap_values: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    path: Path,
) -> None:
    observed = np.vstack([shap_values[i, :, y[i]] for i in range(len(y))])
    global_importance = np.mean(np.abs(shap_values), axis=(0, 2))
    order = np.argsort(global_importance)
    rng = np.random.default_rng(SEED)
    fig, ax = plt.subplots(figsize=(10, 7))
    for y_pos, feature_index in enumerate(order):
        vals = observed[:, feature_index]
        feature_vals = x[:, feature_index]
        lo, hi = np.nanpercentile(feature_vals, [5, 95])
        color_val = np.clip((feature_vals - lo) / (hi - lo + 1e-12), 0, 1)
        jitter = rng.normal(0, 0.085, size=len(vals))
        ax.scatter(
            vals,
            y_pos + jitter,
            c=color_val,
            cmap="coolwarm",
            vmin=0,
            vmax=1,
            s=24,
            alpha=0.72,
            edgecolors="none",
        )
    ax.axvline(0, color="#555555", linewidth=0.9)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([FEATURE_ENGLISH[feature_names[i]] for i in order])
    ax.set_xlabel("SHAP value for the observed DBSCAN cluster class")
    ax.set_title("SHAP summary for the tree surrogate")
    sm = plt.cm.ScalarMappable(cmap="coolwarm", norm=plt.Normalize(0, 1))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, pad=0.02)
    cbar.set_ticks([0, 1])
    cbar.set_ticklabels(["Low feature value", "High feature value"])
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def save_cluster_shap_bars(
    per_cluster: dict[int, pd.Series], display: dict[int, str], path: Path
) -> None:
    clusters = sorted(per_cluster, key=lambda c: int(display[c].split("_")[0][1:]))
    cols = 2
    rows = math.ceil(len(clusters) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(13, 4.4 * rows), squeeze=False)
    for ax, cluster in zip(axes.ravel(), clusters):
        values = per_cluster[cluster].sort_values(ascending=True)
        ax.barh(
            [FEATURE_ENGLISH[f] for f in values.index],
            values.values,
            color="#ef8a62",
            alpha=0.88,
        )
        ax.set_title(display[cluster].split("_")[0])
        ax.set_xlabel("Mean absolute SHAP")
    for ax in axes.ravel()[len(clusters) :]:
        ax.axis("off")
    fig.suptitle("Cluster-specific SHAP importance", y=1.01, fontsize=16)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "(해당 없음)"
    return df.to_markdown(index=False)


def extract_api_text(raw_text: str) -> str:
    stripped = raw_text.strip()
    if not stripped:
        return ""
    try:
        data = json.loads(stripped)
        for key in ["report", "content", "text", "answer", "response", "result"]:
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
        if isinstance(data, dict) and isinstance(data.get("choices"), list) and data["choices"]:
            first = data["choices"][0]
            if isinstance(first, dict):
                message = first.get("message", {})
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"].strip()
                if isinstance(first.get("text"), str):
                    return first["text"].strip()
    except json.JSONDecodeError:
        pass
    sse_parts: list[str] = []
    for line in stripped.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
            for key in ["content", "text", "answer", "response"]:
                if isinstance(obj.get(key), str):
                    sse_parts.append(obj[key])
        except Exception:
            sse_parts.append(payload)
    return "".join(sse_parts).strip() or stripped


def try_alan_api(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    key = os.getenv("ALAN_API_KEY")
    url = os.getenv("ALAN_API_URL")
    if not key or not url:
        missing = [name for name, value in [("ALAN_API_KEY", key), ("ALAN_API_URL", url)] if not value]
        return None, {
            "attempted": False,
            "successful": False,
            "call_count": 0,
            "reason": f"환경변수 미설정: {', '.join(missing)}",
        }
    body = json.dumps(json_ready(payload), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "X-API-Key": key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8", errors="replace")
        report = extract_api_text(raw)
        if not report:
            raise ValueError("응답 본문에서 보고서 텍스트를 찾지 못함")
        return report, {
            "attempted": True,
            "successful": True,
            "call_count": 1,
            "reason": "성공",
        }
    except Exception as exc:
        return None, {
            "attempted": True,
            "successful": False,
            "call_count": 1,
            "reason": f"{type(exc).__name__}: {exc}",
        }


def build_rule_report(
    cluster_summaries: list[dict[str, Any]],
    selected: dict[str, Any],
    validation: dict[str, Any],
    limitations: list[str],
    api_status: dict[str, Any],
    record_count: int,
) -> str:
    lines = [
        "# 대구광역시 행정동 폭염 대응시설 정책 리포트",
        "",
        "> **ALAN API 미호출/미완료**: " + api_status["reason"],
        "> 아래 내용은 분석 산출값만을 사용한 규칙 기반 리포트이며, 임의의 수치나 시설 현황을 보완하지 않았습니다.",
        "",
        "## 1. 요약",
        "",
        f"- 분석 대상은 {record_count}개 행정동이며, 최종 DBSCAN은 eps={float(selected['eps']):.6f}, min_samples={int(selected['min_samples'])}, "
        f"군집 {int(selected['군집수_노이즈제외'])}개, 노이즈 {int(selected['노이즈수'])}개({float(selected['노이즈비율']):.1%})입니다.",
        f"- 대리모델은 {validation['model']}이며 교차검증 Accuracy={validation['accuracy']:.3f}, Macro-F1={validation['macro_f1']:.3f}입니다.",
        "- SHAP 값은 DBSCAN 군집을 구분하는 변수의 기여를 설명하며 인과관계를 뜻하지 않습니다.",
        "",
        "## 2. 군집별 분석",
        "",
    ]
    for item in cluster_summaries:
        lines.extend(
            [
                f"### {item['군집명']} ({item['행정동 수']}개)",
                "",
                f"- 대표 행정동: {item['대표 행정동']}",
                f"- 주요 원인: {', '.join(item['상위 SHAP 원인 3개'])}",
                f"- 대응시설부족도: 평균 {item['대응시설부족도 평균']:.2f}, 최대 {item['대응시설부족도 최댓값']:.2f}",
                f"- 우선 대응 행정동: {', '.join(item['우선 대응 행정동 5개'])}",
                f"- 권장 시설·정책: {', '.join(item['추천시설'])}",
                "",
            ]
        )
    lines.extend(["## 3. 우선사업 대상지", ""])
    priority_rows = []
    for item in cluster_summaries:
        for dong in item["우선 대응 행정동 5개"]:
            priority_rows.append(f"- {item['군집명']}: {dong}")
    lines.extend(priority_rows)
    lines.extend(
        [
            "",
            "## 4. 시설별 실행전략",
            "",
            "1. 1단계(진단·즉시조치): 우선 행정동의 쉼터 접근경로, 냉방 가동, 수용인원, 운영시간을 현장 확인하고 그늘막·쿨링포그 등 단기 조치를 배치합니다.",
            "2. 2단계(분산 확충): 접근성 부족지역은 실내 쉼터를 신설·이전하고, 녹지·열섬지역은 도시숲·가로수·차열포장을 연계합니다.",
            "3. 3단계(서비스 결합): 노인 과밀·복합 취약지역은 경로당 쉼터, 방문 건강관리, 순회 냉방 지원을 시설사업과 함께 운영합니다.",
            "4. 운영단계: 운영시간 연장과 주말 운영 확대는 실제 이용률·수용인원 자료로 재평가하며, 쉼터 단독 대체지역은 다른 종합모형 지역과 직접 비교하지 않습니다.",
            "",
            "## 5. 데이터 한계",
            "",
        ]
    )
    lines.extend([f"- {item}" for item in limitations])
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(output_dir / ".mplconfig"))
    np.random.seed(SEED)
    configure_plotting()

    vulnerability_path = find_input(input_dir, "daegu_heat_vulnerability_v2", ".csv")
    future_path = find_input(input_dir, "daegu_future_heat_illness_risk_index_by_admin_dong_2030", ".xlsx")
    facility_path = find_input(input_dir, "daegu_facility_resilience_by_admin_dong_", ".xlsx")
    shortage_path = find_input(input_dir, "daegu_response_facility_shortage_by_admin_dong_", ".csv", required=False)

    future_raw = pd.read_excel(future_path, sheet_name="행정동별 결과", header=3)
    facility_raw = pd.read_excel(facility_path, sheet_name="행정동별 결과", header=3)
    vulnerability_raw = pd.read_csv(vulnerability_path, encoding="utf-8-sig")
    shortage_raw = (
        pd.read_csv(shortage_path, encoding="utf-8-sig") if shortage_path is not None else None
    )
    for frame in [future_raw, facility_raw, vulnerability_raw] + ([shortage_raw] if shortage_raw is not None else []):
        frame.columns = [str(c).strip() for c in frame.columns]

    future_raw["행정동코드"] = future_raw["행정동코드"].map(normalize_code)
    facility_raw["행정동코드"] = facility_raw["행정동코드"].map(normalize_code)
    if shortage_raw is not None:
        shortage_raw["행정동코드"] = shortage_raw["행정동코드"].map(normalize_code)
    vulnerability_raw["정규화키"] = (
        vulnerability_raw["district_name"].map(normalize_name)
        + "|"
        + vulnerability_raw["dong_name"].map(normalize_name)
    )

    duplicates: list[dict[str, Any]] = []
    duplicates.extend(duplicate_records(future_raw, "미래온열질환위험", "행정동코드"))
    duplicates.extend(duplicate_records(facility_raw, "시설대응력", "행정동코드"))
    if shortage_raw is not None:
        duplicates.extend(duplicate_records(shortage_raw, "대응시설부족도", "행정동코드"))
    duplicates.extend(duplicate_records(vulnerability_raw, "지역취약도", "정규화키"))
    duplicate_columns = ["자료원", "중복키", "중복건수", "관련행", "처리"]
    write_csv(pd.DataFrame(duplicates, columns=duplicate_columns), output_dir / "duplicate_key_errors.csv")
    if duplicates:
        raise RuntimeError("중복키가 발견되어 임의 결합을 중단했습니다. duplicate_key_errors.csv를 확인하세요.")

    future_keep = [
        "구·군",
        "행정동",
        "행정동코드",
        "위험지수",
        "최고 열지수 대체치(℃)",
        "폭염일수",
        "강한폭염일수",
        "열대야일수",
        "대체처리",
        "대체처리 요약",
    ]
    base = future_raw[future_keep].copy().rename(
        columns={"위험지수": "미래온열질환위험", "대체처리 요약": "미래위험대체처리요약"}
    )
    base["정규화키"] = base["구·군"].map(normalize_name) + "|" + base["행정동"].map(normalize_name)

    facility = facility_raw[
        [
            "행정동코드",
            "시설 대응력",
            "시설 부족도",
            "300m 접근률",
            "종합모형",
            "그늘막자료",
            "대체처리·주의",
        ]
    ].copy().rename(
        columns={
            "시설 대응력": "시설대응력",
            "시설 부족도": "시설부족도_시설파일",
            "종합모형": "시설대응력종합모형",
            "그늘막자료": "그늘막자료상태",
            "대체처리·주의": "시설대응력대체처리·주의",
        }
    )
    base = base.merge(facility, on="행정동코드", how="left", validate="one_to_one", indicator="_시설결합")

    if shortage_raw is not None:
        shortage_columns = [
            "행정동코드",
            "미래온열질환위험",
            "지역취약도",
            "보호필요도",
            "시설대응력",
            "대응시설부족도",
        ]
        shortage = shortage_raw[shortage_columns].copy().rename(
            columns={
                "미래온열질환위험": "부족도파일_미래온열질환위험",
                "지역취약도": "부족도파일_지역취약도",
                "시설대응력": "부족도파일_시설대응력",
            }
        )
        base = base.merge(shortage, on="행정동코드", how="left", validate="one_to_one", indicator="_부족도결합")
    else:
        base["_부족도결합"] = "left_only"
        base["부족도파일_미래온열질환위험"] = np.nan
        base["부족도파일_지역취약도"] = np.nan
        base["보호필요도"] = np.nan
        base["부족도파일_시설대응력"] = np.nan
        base["대응시설부족도"] = np.nan

    vulnerability = vulnerability_raw[
        [
            "정규화키",
            "district_name",
            "dong_name",
            "total_population",
            "age70_plus_ratio",
            "green_ratio_percent",
            "A_deficit",
            "heat_vulnerability_score_v2",
        ]
    ].copy().rename(
        columns={
            "district_name": "취약도_원구군",
            "dong_name": "취약도_원행정동",
            "heat_vulnerability_score_v2": "지역취약도",
        }
    )
    base = base.merge(vulnerability, on="정규화키", how="left", validate="one_to_one", indicator="_취약도결합")

    exact_vulnerability = (
        base["구·군"].astype(str).eq(base["취약도_원구군"].astype(str))
        & base["행정동"].astype(str).eq(base["취약도_원행정동"].astype(str))
    )
    vulnerability_method = np.where(
        base["_취약도결합"].eq("both") & exact_vulnerability,
        "구·군+행정동명 정확일치",
        np.where(
            base["_취약도결합"].eq("both"),
            "구·군+행정동명 구분기호 정규화",
            "취약도 미결합",
        ),
    )
    code_method = np.where(
        base["_시설결합"].eq("both") & base["_부족도결합"].eq("both"),
        "행정동코드 일치(미래·시설·부족도)",
        np.where(base["_시설결합"].eq("both"), "행정동코드 부분일치(미래·시설)", "코드 결합 누락"),
    )
    base["결합방법"] = pd.Series(code_method, index=base.index) + "; " + pd.Series(vulnerability_method, index=base.index)
    base["결합성공여부"] = np.where(
        base["_시설결합"].eq("both")
        & (base["_부족도결합"].eq("both") if shortage_raw is not None else True)
        & base["_취약도결합"].eq("both"),
        "Y",
        "N",
    )

    missing_records: list[dict[str, Any]] = []
    for source, indicator in [("시설대응력", "_시설결합"), ("대응시설부족도", "_부족도결합"), ("지역취약도", "_취약도결합")]:
        for _, row in base.loc[base[indicator].ne("both")].iterrows():
            missing_records.append(
                {
                    "기준자료": "미래온열질환위험",
                    "누락자료원": source,
                    "구·군": row["구·군"],
                    "행정동": row["행정동"],
                    "행정동코드": row["행정동코드"],
                    "정규화키": row["정규화키"],
                    "처리": "행 삭제하지 않음; Feature 결측 시 중앙값 대체",
                }
            )
    base_codes = set(base["행정동코드"])
    for source_name, frame in [("시설대응력", facility_raw), ("대응시설부족도", shortage_raw)]:
        if frame is None:
            continue
        for _, row in frame.loc[~frame["행정동코드"].isin(base_codes)].iterrows():
            missing_records.append(
                {
                    "기준자료": source_name,
                    "누락자료원": "미래온열질환위험 기준표에 없음",
                    "구·군": row.get("구·군", ""),
                    "행정동": row.get("행정동", ""),
                    "행정동코드": row["행정동코드"],
                    "정규화키": "",
                    "처리": "기준표에 임의 추가하지 않음",
                }
            )
    missing_columns = ["기준자료", "누락자료원", "구·군", "행정동", "행정동코드", "정규화키", "처리"]
    write_csv(pd.DataFrame(missing_records, columns=missing_columns), output_dir / "merge_missing_dongs.csv")

    numeric_columns = [
        "미래온열질환위험",
        "최고 열지수 대체치(℃)",
        "폭염일수",
        "강한폭염일수",
        "열대야일수",
        "시설대응력",
        "300m 접근률",
        "total_population",
        "age70_plus_ratio",
        "green_ratio_percent",
        "A_deficit",
        "지역취약도",
        "보호필요도",
        "대응시설부족도",
    ]
    conversion_counts: dict[str, int] = {}
    original_numeric: dict[str, pd.Series] = {}
    for column in numeric_columns:
        original_numeric[column] = base[column].copy()
        base[column], conversion_counts[column] = safe_numeric(base[column])

    recomputed_shortage_count = int(base["대응시설부족도"].isna().sum())
    if recomputed_shortage_count:
        protection = base["미래온열질환위험"] * 0.6 + base["지역취약도"] * 0.4
        recalculated = protection * 0.7 + (100 - base["시설대응력"]) * 0.3
        base["보호필요도"] = base["보호필요도"].fillna(protection)
        base["대응시설부족도"] = base["대응시설부족도"].fillna(recalculated)

    feature_specs: list[dict[str, Any]] = []
    heat_candidates = [
        ("최고 열지수 대체치(℃)", "미래위험 엑셀", "최고 열지수 대체치(℃)"),
        ("폭염일수", "미래위험 엑셀", "폭염일수"),
        ("강한폭염일수", "미래위험 엑셀", "강한폭염일수"),
    ]
    heat_selected = next((item for item in heat_candidates if base[item[0]].notna().any()), None)
    if heat_selected is None:
        raise RuntimeError("열 노출 대체변수까지 모두 없습니다.")
    feature_specs.append(
        {
            "concept": "고온 노출",
            "preferred": "최고 열지수 대체치(℃)",
            "selected": heat_selected[0],
            "source": heat_selected[1],
            "series": base[heat_selected[2]],
            "substitution": "N" if heat_selected[0] == "최고 열지수 대체치(℃)" else "Y",
            "reason": "우선순위에 따른 선택",
            "range": (-20.0, 80.0),
            "expected": "-20~80℃ 점검범위",
        }
    )

    if base["age70_plus_ratio"].notna().any():
        elderly_series = base["age70_plus_ratio"]
        elderly_selected = "age70_plus_ratio"
        elderly_source = "지역취약도 CSV"
        elderly_sub = "N"
    else:
        facility_elderly, _ = safe_numeric(facility_raw.set_index("행정동코드").reindex(base["행정동코드"])["고령인구비율"].reset_index(drop=True))
        elderly_series = facility_elderly * 100.0 if facility_elderly.max(skipna=True) <= 1.0 else facility_elderly
        elderly_selected = "고령인구비율(65세 이상)"
        elderly_source = "시설대응력 엑셀"
        elderly_sub = "Y"
    feature_specs.append(
        {
            "concept": "고령자 집중도",
            "preferred": "age70_plus_ratio",
            "selected": elderly_selected,
            "source": elderly_source,
            "series": elderly_series,
            "substitution": elderly_sub,
            "reason": "70세 이상 비율 우선, 없으면 65세 이상 비율",
            "range": (0.0, 100.0),
            "expected": "0~100%",
        }
    )

    green_deficit = 100.0 - base["green_ratio_percent"]
    feature_specs.append(
        {
            "concept": "녹지 부족도",
            "preferred": "100-green_ratio_percent",
            "selected": "100-green_ratio_percent",
            "source": "지역취약도 CSV",
            "series": green_deficit,
            "substitution": "N",
            "reason": "녹지비율의 역방향 지표",
            "range": (0.0, 100.0),
            "expected": "0~100%",
        }
    )

    corr_green_a = float(green_deficit.corr(base["A_deficit"])) if base["A_deficit"].notna().sum() > 2 else np.nan
    if base["A_deficit"].notna().any() and (not np.isfinite(corr_green_a) or abs(corr_green_a) < 0.98):
        access_series = base["A_deficit"]
        access_selected = "A_deficit"
        access_source = "지역취약도 CSV"
        access_sub = "N"
        access_reason = "우선변수 사용"
        access_range = (0.0, 1.0)
        access_expected = "0~1"
    elif base["300m 접근률"].notna().any():
        access_series = 100.0 - base["300m 접근률"]
        access_selected = "100-300m 접근률"
        access_source = "시설대응력 엑셀"
        access_sub = "Y"
        access_reason = f"A_deficit와 녹지부족도의 중복 가중 방지(Pearson r={corr_green_a:.6f}) 및 쉼터 접근성 의미 보존"
        access_range = (0.0, 100.0)
        access_expected = "0~100%"
    else:
        access_series = 100.0 - base["시설대응력"]
        access_selected = "100-시설대응력"
        access_source = "시설대응력 엑셀"
        access_sub = "Y"
        access_reason = "A_deficit 부재/중복 및 300m 접근률 부재"
        access_range = (0.0, 100.0)
        access_expected = "0~100점"
    feature_specs.append(
        {
            "concept": "접근성 결손",
            "preferred": "A_deficit",
            "selected": access_selected,
            "source": access_source,
            "series": access_series,
            "substitution": access_sub,
            "reason": access_reason,
            "range": access_range,
            "expected": access_expected,
        }
    )
    feature_specs.extend(
        [
            {
                "concept": "미래 온열질환 위험",
                "preferred": "미래온열질환위험",
                "selected": "미래온열질환위험",
                "source": "미래위험 엑셀",
                "series": base["미래온열질환위험"],
                "substitution": "N",
                "reason": "원자료 위험지수 사용",
                "range": (0.0, 100.0),
                "expected": "0~100점",
            },
            {
                "concept": "대응시설 부족도",
                "preferred": "대응시설부족도",
                "selected": "대응시설부족도" if recomputed_shortage_count == 0 else "대응시설부족도(일부 재계산)",
                "source": "대응시설부족도 CSV" if shortage_raw is not None else "산식 재계산",
                "series": base["대응시설부족도"],
                "substitution": "N" if recomputed_shortage_count == 0 else "Y",
                "reason": "제공값 사용" if recomputed_shortage_count == 0 else f"결측 {recomputed_shortage_count}건을 지정 산식으로 재계산",
                "range": (0.0, 100.0),
                "expected": "0~100점",
            },
        ]
    )

    feature_names = [spec["concept"] for spec in feature_specs]
    feature_frame = pd.DataFrame(index=base.index)
    feature_log_rows: list[dict[str, Any]] = []
    imputation_notes: list[list[str]] = [[] for _ in range(len(base))]
    for spec in feature_specs:
        raw_series = spec["series"].copy()
        numeric, nonconvertible = safe_numeric(raw_series)
        missing_before = numeric.isna()
        if numeric.notna().sum() == 0:
            raise RuntimeError(f"Feature 전체가 결측입니다: {spec['concept']}")
        median = float(numeric.median())
        filled = numeric.fillna(median)
        feature_frame[spec["concept"]] = filled
        for idx in np.flatnonzero(missing_before.to_numpy()):
            imputation_notes[idx].append(f"{spec['concept']} 중앙값({median:.4g}) 대체")
        lower, upper = spec["range"]
        feature_log_rows.append(
            make_feature_log_row(
                spec["concept"],
                spec["preferred"],
                spec["selected"],
                spec["source"],
                spec["substitution"],
                spec["reason"],
                raw_series,
                numeric,
                nonconvertible,
                median,
                int(missing_before.sum()),
                spec["expected"],
                range_status(numeric, lower, upper),
            )
        )

    excluded_candidates = [
        ("폭염일수", "미래위험 엑셀", "최고 열지수 대체치와 의미 중복; 열 노출 우선순위에서 제외"),
        ("강한폭염일수", "미래위험 엑셀", "최고 열지수 대체치와 의미 중복"),
        ("열대야일수", "미래위험 엑셀", "열 노출 변수 과다 투입 방지"),
        ("지역취약도", "지역취약도 CSV", "고령·녹지 원변수와 복합점수 중복"),
        ("시설대응력", "시설대응력 엑셀", "대응시설부족도 및 접근성 결손과 중복"),
        ("A_deficit", "지역취약도 CSV", access_reason if access_selected != "A_deficit" else "접근성 Feature로 사용"),
        ("total_population", "지역취약도 CSV", "핵심 Feature가 아니며 인구규모의 과대 영향 방지; log1p 미적용"),
    ]
    for column, source, reason in excluded_candidates:
        if column == "A_deficit" and access_selected == "A_deficit":
            continue
        original = base[column] if column in base else pd.Series(np.nan, index=base.index)
        numeric, nonconvertible = safe_numeric(original)
        feature_log_rows.append(
            make_feature_log_row(
                "검토·제외 Feature",
                column,
                column,
                source,
                "해당 없음",
                "",
                original,
                numeric,
                nonconvertible,
                None,
                0,
                "자료 정의에 따름",
                "검토 완료",
                used="N",
                exclusion_reason=reason,
            )
        )
    feature_log = pd.DataFrame(feature_log_rows)
    write_csv(feature_log, output_dir / "feature_substitution_log.csv")

    scaler = StandardScaler()
    z = scaler.fit_transform(feature_frame)
    z_frame = pd.DataFrame(z, columns=feature_names, index=base.index)
    labels, selected, parameter_evaluation, expanded_search = select_dbscan(z)
    write_csv(parameter_evaluation, output_dir / "dbscan_parameter_evaluation.csv")

    raw_clusters = sorted(c for c in set(labels) if c != -1)
    target_map = {cluster: i for i, cluster in enumerate(raw_clusters)}
    train_mask = labels != -1
    x_train = z[train_mask]
    y_train = np.array([target_map[c] for c in labels[train_mask]], dtype=int)
    min_class_size = int(pd.Series(y_train).value_counts().min())
    cv_folds = 5 if min_class_size >= 5 else 3
    if min_class_size < cv_folds:
        cv_folds = min_class_size
    model, model_name, model_note = make_surrogate(len(raw_clusters))
    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=SEED)
    cv_predictions = cross_val_predict(clone(model), x_train, y_train, cv=cv, method="predict", n_jobs=None)
    accuracy = float(accuracy_score(y_train, cv_predictions))
    macro_f1 = float(f1_score(y_train, cv_predictions, average="macro", zero_division=0))
    conf = confusion_matrix(y_train, cv_predictions, labels=list(range(len(raw_clusters))))
    model.fit(x_train, y_train)
    shap_values, shap_info = compute_shap(model, x_train)

    z_profiles_raw = z_frame.assign(_cluster=labels).groupby("_cluster").mean()
    raw_profile_medians = feature_frame.assign(_cluster=labels).groupby("_cluster").median()
    raw_profile_means = feature_frame.assign(_cluster=labels).groupby("_cluster").mean()
    per_cluster_importance: dict[int, pd.Series] = {}
    per_cluster_signed: dict[int, pd.Series] = {}
    cluster_types: dict[int, str] = {}
    cluster_causes: dict[int, list[str]] = {}
    for raw_cluster in raw_clusters:
        class_index = target_map[raw_cluster]
        local_mask = y_train == class_index
        local_values = shap_values[local_mask, :, class_index]
        importance = pd.Series(np.mean(np.abs(local_values), axis=0), index=feature_names)
        signed = pd.Series(np.mean(local_values, axis=0), index=feature_names)
        per_cluster_importance[raw_cluster] = importance
        per_cluster_signed[raw_cluster] = signed
        cluster_types[raw_cluster] = cluster_type_from_profile(z_profiles_raw.loc[raw_cluster], importance)
        cluster_causes[raw_cluster] = causes_from_profile(z_profiles_raw.loc[raw_cluster], importance)

    shortage_means = base.assign(_cluster=labels).groupby("_cluster")["대응시설부족도"].mean()
    numbered_clusters = sorted(raw_clusters, key=lambda c: (-shortage_means.loc[c], c))
    cluster_display = {
        raw_cluster: f"C{rank}_{cluster_types[raw_cluster]}"
        for rank, raw_cluster in enumerate(numbered_clusters, start=1)
    }
    cluster_display[-1] = "특이·개별검토형"

    shap_summary_rows: list[dict[str, Any]] = []
    global_importance = pd.Series(np.mean(np.abs(shap_values), axis=(0, 2)), index=feature_names)
    for rank, (feature, value) in enumerate(global_importance.sort_values(ascending=False).items(), start=1):
        shap_summary_rows.append(
            {
                "DBSCAN원군집": "전체",
                "군집명": "전체",
                "행정동수": int(train_mask.sum()),
                "Feature": feature,
                "원값평균": feature_frame[feature].mean(),
                "원값중앙값": feature_frame[feature].median(),
                "표준화평균": 0.0,
                "표준화중앙값": z_frame[feature].median(),
                "평균절대SHAP": value,
                "평균부호SHAP": np.nan,
                "SHAP순위": rank,
                "SHAP방향": "전체 다중분류 절댓값 요약",
                "상위3원인": "Y" if rank <= 3 else "N",
                "해석주의": "군집 구분 변수이며 인과관계가 아님",
            }
        )
    for raw_cluster in numbered_clusters:
        size = int((labels == raw_cluster).sum())
        importance = per_cluster_importance[raw_cluster]
        signed = per_cluster_signed[raw_cluster]
        for rank, feature in enumerate(importance.sort_values(ascending=False).index, start=1):
            z_mean = float(z_profiles_raw.loc[raw_cluster, feature])
            mean_signed = float(signed[feature])
            if mean_signed > 0 and z_mean > 0:
                direction = "높은 값이 해당 군집 판별에 기여"
            elif mean_signed > 0 and z_mean < 0:
                direction = "낮은 값이 해당 군집 판별에 기여"
            elif mean_signed < 0:
                direction = "해당 군집 판별을 억제하는 방향"
            else:
                direction = "중립"
            shap_summary_rows.append(
                {
                    "DBSCAN원군집": raw_cluster,
                    "군집명": cluster_display[raw_cluster],
                    "행정동수": size,
                    "Feature": feature,
                    "원값평균": raw_profile_means.loc[raw_cluster, feature],
                    "원값중앙값": raw_profile_medians.loc[raw_cluster, feature],
                    "표준화평균": z_mean,
                    "표준화중앙값": z_frame.loc[labels == raw_cluster, feature].median(),
                    "평균절대SHAP": importance[feature],
                    "평균부호SHAP": mean_signed,
                    "SHAP순위": rank,
                    "SHAP방향": direction,
                    "상위3원인": "Y" if rank <= 3 else "N",
                    "해석주의": "군집 구분 변수이며 인과관계가 아님",
                }
            )
    shap_summary_df = pd.DataFrame(shap_summary_rows)
    write_csv(shap_summary_df, output_dir / "daegu_cluster_shap_summary.csv")

    assignments = base[
        [
            "구·군",
            "행정동",
            "행정동코드",
            "결합방법",
            "결합성공여부",
            "미래온열질환위험",
            "지역취약도",
            "시설대응력",
            "대응시설부족도",
            "시설대응력종합모형",
            "그늘막자료상태",
        ]
    ].copy()
    assignments["DBSCAN 원군집"] = labels
    assignments["대리모델 라벨"] = [target_map.get(c, -1) for c in labels]
    assignments["군집명"] = [cluster_display[c] for c in labels]
    assignments["노이즈 여부"] = np.where(labels == -1, "Y", "N")
    for feature in feature_names:
        assignments[feature] = feature_frame[feature]
        assignments[f"{feature}_z"] = z_frame[feature]
    global_order = assignments.sort_values(
        ["대응시설부족도", "행정동코드"], ascending=[False, True]
    ).index
    assignments["전체 설치 우선순위"] = pd.Series(
        range(1, len(assignments) + 1), index=global_order, dtype="int64"
    ).reindex(assignments.index)
    assignments["군집 내 우선순위"] = pd.Series(index=assignments.index, dtype="int64")
    for raw_cluster, part in assignments.groupby("DBSCAN 원군집"):
        local_order = part.sort_values(
            ["대응시설부족도", "행정동코드"], ascending=[False, True]
        ).index
        assignments.loc[local_order, "군집 내 우선순위"] = range(1, len(local_order) + 1)
    assignments["군집 내 우선순위"] = assignments["군집 내 우선순위"].astype("int64")
    assignments["쉼터 단독 대체 여부"] = np.where(assignments["시설대응력종합모형"].astype(str).str.contains("쉼터 단독 대체", na=False), "Y", "N")
    assignments["대체처리·주의사항"] = [
        "; ".join(
            part
            for part in [
                str(base.loc[i, "미래위험대체처리요약"]) if pd.notna(base.loc[i, "미래위험대체처리요약"]) else "",
                str(base.loc[i, "시설대응력대체처리·주의"]) if pd.notna(base.loc[i, "시설대응력대체처리·주의"]) else "",
                " | ".join(imputation_notes[i]),
                "쉼터 단독 대체 적용: 다른 종합모형 지역과 직접 비교 주의" if assignments.loc[i, "쉼터 단독 대체 여부"] == "Y" else "",
            ]
            if part
        )
        for i in range(len(base))
    ]
    write_csv(assignments, output_dir / "daegu_dbscan_cluster_assignments.csv")

    recommendations_rows: list[dict[str, Any]] = []
    for i, row in assignments.iterrows():
        raw_cluster = int(row["DBSCAN 원군집"])
        if raw_cluster == -1:
            causes, facilities, detail = individual_noise_profile(z_frame.loc[i])
            reason = f"특이·개별검토: 절댓값 상위 표준화 Feature {detail}"
        else:
            causes = cluster_causes[raw_cluster]
            facilities = recommendations_for(cluster_types[raw_cluster], causes)
            profile_detail = ", ".join(
                f"{feature} z={z_profiles_raw.loc[raw_cluster, feature]:+.2f}"
                for feature in per_cluster_importance[raw_cluster].sort_values(ascending=False).index[:3]
            )
            reason = (
                f"{cluster_display[raw_cluster]}의 표준화 평균과 군집별 SHAP을 함께 판정: {profile_detail}. "
                "SHAP은 군집 구분 근거이며 인과관계가 아님"
            )
        padded_causes = (causes + [""] * 3)[:3]
        padded_facilities = (facilities + [""] * 3)[:3]
        recommendations_rows.append(
            {
                "구·군": row["구·군"],
                "행정동": row["행정동"],
                "행정동코드": row["행정동코드"],
                "DBSCAN 원군집": raw_cluster,
                "군집명": row["군집명"],
                "노이즈 여부": row["노이즈 여부"],
                "대응시설부족도": row["대응시설부족도"],
                "전체 설치 우선순위": row["전체 설치 우선순위"],
                "군집 내 우선순위": row["군집 내 우선순위"],
                "쉼터 단독 대체 여부": row["쉼터 단독 대체 여부"],
                "군집 주원인 1": padded_causes[0],
                "군집 주원인 2": padded_causes[1],
                "군집 주원인 3": padded_causes[2],
                "추천시설 1": padded_facilities[0],
                "추천시설 2": padded_facilities[1],
                "추천시설 3": padded_facilities[2],
                "추천 근거": reason,
                "결합방법": row["결합방법"],
                "대체처리·주의사항": row["대체처리·주의사항"],
            }
        )
    recommendations_df = pd.DataFrame(recommendations_rows).sort_values("전체 설치 우선순위")
    write_csv(recommendations_df, output_dir / "daegu_facility_recommendations_by_dong.csv")

    cluster_profile_rows: list[dict[str, Any]] = []
    for raw_cluster in numbered_clusters + ([-1] if -1 in set(labels) else []):
        row: dict[str, Any] = {
            "DBSCAN원군집": raw_cluster,
            "군집명": cluster_display[raw_cluster],
            "행정동수": int((labels == raw_cluster).sum()),
        }
        for feature in feature_names:
            row[f"{feature}_평균"] = raw_profile_means.loc[raw_cluster, feature]
            row[f"{feature}_중앙값"] = raw_profile_medians.loc[raw_cluster, feature]
            row[f"{feature}_z평균"] = z_profiles_raw.loc[raw_cluster, feature]
        if raw_cluster == -1:
            row["주원인"] = "행정동별 절댓값 상위 z-Feature 개별 판정"
            row["추천시설"] = "행정동별 개별 추천"
        else:
            row["주원인"] = " | ".join(cluster_causes[raw_cluster])
            row["추천시설"] = " | ".join(recommendations_for(cluster_types[raw_cluster], cluster_causes[raw_cluster]))
        cluster_profile_rows.append(row)
    cluster_profile_df = pd.DataFrame(cluster_profile_rows)
    write_csv(cluster_profile_df, output_dir / "cluster_profiles.csv")

    profile_for_plot = z_profiles_raw.loc[numbered_clusters + ([-1] if -1 in set(labels) else [])].copy()
    profile_for_plot.index = [cluster_display[c].split("_")[0] if c != -1 else "Noise" for c in profile_for_plot.index]
    save_pca_plot(z, labels, cluster_display, output_dir / "dbscan_pca_scatter.png")
    save_map_notice(output_dir / "dbscan_cluster_map.png")
    save_profile_heatmap(profile_for_plot, output_dir / "cluster_profile_heatmap.png")
    save_shap_summary(shap_values, x_train, y_train, feature_names, output_dir / "shap_summary_plot.png")
    save_cluster_shap_bars(per_cluster_importance, cluster_display, output_dir / "cluster_shap_bar_plots.png")

    validation = {
        "model": model_name,
        "model_note": model_note,
        "random_seed": SEED,
        "cv_folds": cv_folds,
        "minimum_cluster_size": min_class_size,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "performance_warning": bool(accuracy < 0.75 or macro_f1 < 0.70),
        "warning_text": "대리모델 성능이 낮아 SHAP 해석 신뢰도가 낮음" if accuracy < 0.75 or macro_f1 < 0.70 else "",
        "confusion_matrix_labels": list(range(len(raw_clusters))),
        "target_label_to_raw_cluster": {str(v): k for k, v in target_map.items()},
        "shap": shap_info,
    }
    (output_dir / "tree_surrogate_validation.json").write_text(
        json.dumps(json_ready(validation), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    confusion_df = pd.DataFrame(
        conf,
        index=[f"실제_{i}" for i in range(len(raw_clusters))],
        columns=[f"예측_{i}" for i in range(len(raw_clusters))],
    ).reset_index(names="실제라벨")
    write_csv(confusion_df, output_dir / "tree_surrogate_confusion_matrix.csv")

    representative_dongs: dict[int, str] = {}
    for raw_cluster in raw_clusters:
        indices = np.flatnonzero(labels == raw_cluster)
        centroid = z[indices].mean(axis=0)
        distances = np.linalg.norm(z[indices] - centroid, axis=1)
        chosen = indices[int(np.argmin(distances))]
        representative_dongs[raw_cluster] = f"{base.loc[chosen, '구·군']} {base.loc[chosen, '행정동']}"
    if -1 in set(labels):
        noise_indices = np.flatnonzero(labels == -1)
        chosen = noise_indices[int(np.argmax(base.loc[noise_indices, "대응시설부족도"].to_numpy()))]
        representative_dongs[-1] = f"{base.loc[chosen, '구·군']} {base.loc[chosen, '행정동']}"

    sensitivity = parameter_evaluation[parameter_evaluation["평가단계"].eq("민감도분석")]
    common_limitations = [
        "행정동 경계파일이 없어 임의 점·경계를 만들지 않았고, 지도 대신 PCA 산점도와 군집 프로파일 히트맵을 작성함.",
        model_note + ".",
        (
            shap_info["reason"]
            + f"; 대신 6개 Feature의 정확 열거형 interventional SHAP을 사용함(배경 {shap_info['background_size']}개, additivity 최대오차 {shap_info['additivity_max_abs_error']:.3e})."
            if shap_info["fallback"]
            else "SHAP TreeExplainer를 사용함."
        ),
        (
            f"A_deficit와 녹지부족도 상관계수 r={corr_green_a:.6f}로 중복 가중 우려가 있어 "
            f"접근성 결손은 {access_selected}로 대체함."
            if access_selected != "A_deficit"
            else f"A_deficit와 녹지부족도 상관계수 r={corr_green_a:.6f}; 중복 기준 미만으로 A_deficit를 접근성 결손에 사용함."
        ),
        f"취약도 이름 구분기호 정규화 결합 {int((pd.Series(vulnerability_method) == '구·군+행정동명 구분기호 정규화').sum())}건; 결합 실패 {int((base['결합성공여부'] == 'N').sum())}건.",
        f"군집 Feature 중앙값 대체 총 {sum(len(notes) for notes in imputation_notes)}건; 인구 Feature는 사용하지 않아 log1p 변환 미적용.",
        (
            f"eps ±10%·min_samples ±2 민감도 9개 조합에서 군집수 {int(sensitivity['군집수_노이즈제외'].min())}~{int(sensitivity['군집수_노이즈제외'].max())}, "
            f"노이즈 {int(sensitivity['노이즈수'].min())}~{int(sensitivity['노이즈수'].max())}개, 기준모델 대비 ARI {sensitivity['기준모델대비_ARI'].min():.3f}~{sensitivity['기준모델대비_ARI'].max():.3f}; "
            "일부 조합은 권장 군집수·균형 조건을 벗어남."
        ),
        "시설대응력의 '쉼터 단독 대체' 지역은 그늘막 포함 70:30 종합모형 지역과 직접 비교할 때 주의해야 함.",
        "SHAP 결과는 DBSCAN 군집을 구분하는 변수이며 인과관계가 아님.",
    ]
    cluster_summaries: list[dict[str, Any]] = []
    summary_order = numbered_clusters + ([-1] if -1 in set(labels) else [])
    for raw_cluster in summary_order:
        mask = labels == raw_cluster
        priority = base.loc[mask, ["구·군", "행정동", "대응시설부족도"]].sort_values("대응시설부족도", ascending=False).head(5)
        if raw_cluster == -1:
            top_causes = ["행정동별 절댓값 상위 표준화 Feature 3개로 개별 판정"]
            recs = ["행정동별 개별 추천(최대 3개)"]
        else:
            top_causes = cluster_causes[raw_cluster]
            recs = recommendations_for(cluster_types[raw_cluster], top_causes)
        feature_stats = []
        for feature in feature_names:
            feature_stats.append(
                {
                    "Feature": feature,
                    "평균": round(float(raw_profile_means.loc[raw_cluster, feature]), 4),
                    "중앙값": round(float(raw_profile_medians.loc[raw_cluster, feature]), 4),
                    "표준화평균": round(float(z_profiles_raw.loc[raw_cluster, feature]), 4),
                }
            )
        cluster_summaries.append(
            {
                "군집명": cluster_display[raw_cluster],
                "행정동 수": int(mask.sum()),
                "대표 행정동": representative_dongs[raw_cluster],
                "주요 Feature 평균과 중앙값": feature_stats,
                "상위 SHAP 원인 3개": top_causes[:3],
                "대응시설부족도 평균": round(float(base.loc[mask, "대응시설부족도"].mean()), 4),
                "대응시설부족도 최댓값": round(float(base.loc[mask, "대응시설부족도"].max()), 4),
                "우선 대응 행정동 5개": [f"{r['구·군']} {r['행정동']}" for _, r in priority.iterrows()],
                "추천시설": recs,
                "자료 대체 및 한계": common_limitations,
            }
        )

    instruction = (
        "당신은 도시 폭염 적응정책 전문가입니다. 제공된 대구광역시 행정동 군집 요약자료를 근거로 "
        "군집별 위험 특성, 우선 대응지역, 권장 시설, 단계별 정책 실행방안, 자료 한계를 포함한 정책 리포트를 작성하세요. "
        "제공되지 않은 수치나 시설 현황을 추정하지 말고, SHAP 결과를 인과관계로 표현하지 마세요. "
        "보고서는 요약, 군집별 분석, 우선사업 대상지, 시설별 실행전략, 데이터 한계 순서로 작성하세요."
    )
    alan_payload = {
        "instruction": instruction,
        "cluster_summary": cluster_summaries,
        "analysis_metadata": {
            "분석행정동수": len(base),
            "결합성공수": int(base["결합성공여부"].eq("Y").sum()),
            "결합실패수": int(base["결합성공여부"].eq("N").sum()),
            "최종DBSCAN": {
                "eps": selected["eps"],
                "min_samples": selected["min_samples"],
                "군집수": selected["군집수_노이즈제외"],
                "노이즈수": selected["노이즈수"],
                "노이즈비율": selected["노이즈비율"],
                "Silhouette": selected["Silhouette_Score"],
                "Calinski_Harabasz": selected["Calinski_Harabasz_Score"],
                "Davies_Bouldin": selected["Davies_Bouldin_Score"],
            },
            "대리모델": validation,
        },
        "generation_options": {"temperature": 0.2, "max_output_tokens": 2000},
    }
    (output_dir / "alan_request_payload.json").write_text(
        json.dumps(json_ready(alan_payload), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    alan_report, api_status = try_alan_api(alan_payload)

    if alan_report is not None:
        report = (
            "# 대구광역시 행정동 폭염 대응시설 정책 리포트\n\n"
            "> ALAN API 호출 성공(1회). 아래 본문은 군집 대표값 JSON만 전달해 생성되었습니다.\n\n"
            + alan_report.strip()
            + "\n\n## 분석 검증 부록\n\n"
            + f"- DBSCAN: eps={float(selected['eps']):.6f}, min_samples={int(selected['min_samples'])}, "
            + f"군집 {int(selected['군집수_노이즈제외'])}개, 노이즈 {int(selected['노이즈수'])}개.\n"
            + f"- 대리모델 {model_name}: Accuracy={accuracy:.3f}, Macro-F1={macro_f1:.3f}.\n"
            + "- SHAP은 군집 구분 변수이며 인과관계가 아닙니다.\n"
            + "- 행정동 경계파일이 없어 지도는 미작성했으며 PCA 산점도와 히트맵으로 대체했습니다.\n"
        )
    else:
        report = build_rule_report(
            cluster_summaries,
            selected,
            validation,
            common_limitations,
            api_status,
            len(base),
        )

    report += (
        "\n## 재현성과 산출물 메모\n\n"
        f"- Random seed: {SEED}\n"
        f"- 파라미터 탐색 확대 여부: {'Y' if expanded_search else 'N'}\n"
        f"- ALAN API 호출 시도: {'Y' if api_status['attempted'] else 'N'}, 성공: {'Y' if api_status['successful'] else 'N'}, 호출 횟수: {api_status['call_count']}\n"
        f"- ALAN 상태 사유: {api_status['reason']}\n"
        f"- 지도: 경계파일 부재로 미작성; dbscan_cluster_map.png는 미작성 사유 안내 이미지임.\n"
    )
    if validation["performance_warning"]:
        report += "- **경고:** 대리모델 성능이 낮아 SHAP 해석의 신뢰도가 낮습니다.\n"
    (output_dir / "daegu_heat_policy_report.md").write_text(report, encoding="utf-8")

    run_summary = {
        "분석행정동수": len(base),
        "결합성공수": int(base["결합성공여부"].eq("Y").sum()),
        "결합실패수": int(base["결합성공여부"].eq("N").sum()),
        "이름정규화결합수": int((pd.Series(vulnerability_method) == "구·군+행정동명 구분기호 정규화").sum()),
        "대체키결합수": 0,
        "eps": float(selected["eps"]),
        "min_samples": int(selected["min_samples"]),
        "군집수": int(selected["군집수_노이즈제외"]),
        "노이즈수": int(selected["노이즈수"]),
        "노이즈비율": float(selected["노이즈비율"]),
        "silhouette": float(selected["Silhouette_Score"]),
        "calinski_harabasz": float(selected["Calinski_Harabasz_Score"]),
        "davies_bouldin": float(selected["Davies_Bouldin_Score"]),
        "대리모델": model_name,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "shap_method": shap_info["method"],
        "alan_api": api_status,
        "군집별핵심원인": {cluster_display[c]: cluster_causes[c] for c in numbered_clusters},
        "군집별추천시설": {
            cluster_display[c]: recommendations_for(cluster_types[c], cluster_causes[c])
            for c in numbered_clusters
        },
    }
    (output_dir / "analysis_run_summary.json").write_text(
        json.dumps(json_ready(run_summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(json_ready(run_summary), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
