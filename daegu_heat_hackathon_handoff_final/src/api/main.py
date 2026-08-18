"""FastAPI entry point for the DBSCAN + SHAP snapshot analysis."""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.analysis.cluster_service import (
    ClusterAnalysisError,
    analyze_cluster_snapshot,
    feature_specification,
)
from src.api.schemas import ClusterAnalysisRequest, ClusterAnalysisResponse


def _cors_origins() -> list[str]:
    configured = os.getenv("ALLOWED_ORIGINS", "http://localhost:8501").strip()
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def create_app() -> FastAPI:
    app = FastAPI(
        title="Daegu Heat Adaptation API",
        version="1.0.0",
        description="행정동 전체 스냅샷을 DBSCAN + SHAP으로 분석하고 시설 추천을 반환합니다.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "daegu-heat-api"}

    @app.get("/api/v1/clusters/features", tags=["clusters"])
    def cluster_features() -> dict[str, object]:
        return {
            "analysis_scope": "모든 행정동을 포함한 단일 시점 스냅샷",
            "features": feature_specification(),
        }

    @app.post(
        "/api/v1/clusters",
        response_model=ClusterAnalysisResponse,
        tags=["clusters"],
        summary="행정동 스냅샷 DBSCAN + SHAP 분석",
    )
    def analyze_clusters(request: ClusterAnalysisRequest) -> dict[str, object]:
        try:
            return analyze_cluster_snapshot(
                [record.model_dump(mode="json") for record in request.records]
            )
        except ClusterAnalysisError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app


app = create_app()
