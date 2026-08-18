from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.services.dashboard import (
    build_ai_briefing,
    build_allocation,
    build_overview,
    get_summary_csv_path,
)
from backend.services.ml_prediction import build_ml_scenario

app = FastAPI(title="temperAIture API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/overview")
def overview(metric: str = "vulnerability") -> dict:
    return build_overview(metric=metric)


@app.post("/api/allocation")
def allocation(payload: dict) -> dict:
    return build_allocation(payload)


@app.post("/api/ai-briefing")
def ai_briefing(payload: dict) -> dict:
    return build_ai_briefing(payload)


@app.post("/api/ml-scenario")
def ml_scenario(payload: dict) -> dict:
    return build_ml_scenario(payload)


@app.get("/api/download/dong-summary.csv")
def download_dong_summary() -> FileResponse:
    path = get_summary_csv_path()
    return FileResponse(
        path,
        media_type="text/csv; charset=utf-8",
        filename="daegu_all_dong_accessibility_summary.csv",
    )
