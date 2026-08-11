"""Exploratory KMeans policy-type clustering for administrative areas."""

from __future__ import annotations

import os
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler


os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")


CLUSTER_FEATURES = [
    "elderly_ratio",
    "elderly_density",
    "nearest_shelter_distance",
    "coverage_gap",
    "capacity_per_1000_elderly",
    "temperature",
    "humidity",
]


def _profile_dimension(z_centroid: pd.Series) -> tuple[str, float]:
    age = float(z_centroid[["elderly_ratio", "elderly_density"]].mean())
    access = float(
        np.mean(
            [
                z_centroid["nearest_shelter_distance"],
                z_centroid["coverage_gap"],
                -z_centroid["capacity_per_1000_elderly"],
            ]
        )
    )
    heat = float(z_centroid[["temperature", "humidity"]].mean())
    dimensions = {"고령 취약형": age, "접근성 취약형": access, "폭염 노출형": heat}
    return max(dimensions.items(), key=lambda item: item[1])


def cluster_areas(
    areas: gpd.GeoDataFrame, *, max_clusters: int = 3, random_state: int = 42
) -> tuple[gpd.GeoDataFrame, list[dict[str, Any]]]:
    """Cluster policy response types; this does not replace priority scoring."""

    missing = set(CLUSTER_FEATURES) - set(areas.columns)
    if missing:
        raise ValueError(f"군집분석 필수 컬럼 누락: {', '.join(sorted(missing))}")
    result = areas.copy()
    feature_frame = result[CLUSTER_FEATURES].apply(pd.to_numeric, errors="coerce")
    feature_frame = feature_frame.replace([np.inf, -np.inf], np.nan)
    feature_frame = feature_frame.fillna(feature_frame.median()).fillna(0.0)
    n_samples = len(feature_frame)
    if n_samples < 3:
        result["cluster"] = 0
        result["cluster_name"] = "탐색적 단일 유형"
        return result, [
            {
                "cluster_id": 0,
                "cluster_name": "탐색적 단일 유형",
                "area_count": n_samples,
                "silhouette_score": None,
                "centroid": feature_frame.mean().round(3).to_dict(),
            }
        ]
    n_clusters = min(max_clusters, n_samples - 1)
    scaled = StandardScaler().fit_transform(feature_frame)
    model = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
    labels = model.fit_predict(scaled)
    result["cluster"] = labels
    silhouette = float(silhouette_score(scaled, labels)) if len(set(labels)) > 1 else None
    z_frame = pd.DataFrame(scaled, columns=CLUSTER_FEATURES, index=result.index)
    profiles: list[dict[str, Any]] = []
    used_names: dict[str, int] = {}
    names_by_cluster: dict[int, str] = {}
    for cluster_id in sorted(set(labels)):
        mask = result["cluster"] == cluster_id
        z_centroid = z_frame.loc[mask].mean()
        base_name, dominant_score = _profile_dimension(z_centroid)
        used_names[base_name] = used_names.get(base_name, 0) + 1
        name = base_name if used_names[base_name] == 1 else f"{base_name} {used_names[base_name]}"
        names_by_cluster[int(cluster_id)] = name
        profiles.append(
            {
                "cluster_id": int(cluster_id),
                "cluster_name": name,
                "area_count": int(mask.sum()),
                "dominant_z_score": round(dominant_score, 3),
                "silhouette_score": round(silhouette, 3) if silhouette is not None else None,
                "centroid": feature_frame.loc[mask].mean().round(3).to_dict(),
                "interpretation": "탐색적 정책 대응 유형이며 위험확률 예측이 아닙니다.",
            }
        )
    result["cluster_name"] = result["cluster"].map(names_by_cluster)
    return result, profiles

