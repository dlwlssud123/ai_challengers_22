"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"
PROCESSED_DIR = DATA_DIR / "processed"


def _as_int(name: str, default: int) -> int:
    value = _setting(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"환경변수 {name}은 정수여야 합니다: {value!r}") from exc


def _streamlit_secret(name: str) -> str | None:
    try:
        import streamlit as st

        value = st.secrets.get(name)
        return str(value) if value not in (None, "") else None
    except Exception:
        return None


def _setting(name: str, default: str | None = None) -> str | None:
    """Read local environment first and Streamlit Cloud Secrets second."""

    return os.getenv(name) or _streamlit_secret(name) or default


@dataclass(frozen=True)
class ScoreWeights:
    """Auditable default weights for the policy-priority score."""

    temperature: float = 0.70
    humidity: float = 0.30
    elderly_ratio: float = 0.60
    elderly_density: float = 0.40
    heat: float = 0.35
    vulnerability: float = 0.35
    access: float = 0.30


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Secrets are never printed or logged."""

    target_region_name: str = "대구광역시 수성구"
    analysis_year: int = 2024
    default_access_radius_m: int = 500
    default_candidate_grid_m: int = 300
    default_shelter_cost_krw: int = 10_000_000
    api_timeout_seconds: int = 10
    demo_mode: str = "auto"
    sgis_consumer_key: str | None = None
    sgis_consumer_secret: str | None = None
    sgis_adm_cd: str | None = None
    safety_data_shelter_api_url: str | None = None
    safety_data_service_key: str | None = None
    kma_auth_key: str | None = None
    kma_surface_api_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    vworld_api_key: str | None = None
    analysis_crs: str = "EPSG:5179"
    display_crs: str = "EPSG:4326"
    weights: ScoreWeights = field(default_factory=ScoreWeights)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        return cls(
            target_region_name=_setting("TARGET_REGION_NAME", "대구광역시 수성구") or "대구광역시 수성구",
            analysis_year=_as_int("ANALYSIS_YEAR", 2024),
            default_access_radius_m=_as_int("DEFAULT_ACCESS_RADIUS_M", 500),
            default_candidate_grid_m=_as_int("DEFAULT_CANDIDATE_GRID_M", 300),
            default_shelter_cost_krw=_as_int("DEFAULT_SHELTER_COST_KRW", 10_000_000),
            api_timeout_seconds=_as_int("API_TIMEOUT_SECONDS", 10),
            demo_mode=(_setting("DEMO_MODE", "auto") or "auto").strip().lower(),
            sgis_consumer_key=_setting("SGIS_CONSUMER_KEY"),
            sgis_consumer_secret=_setting("SGIS_CONSUMER_SECRET"),
            sgis_adm_cd=_setting("SGIS_ADM_CD"),
            safety_data_shelter_api_url=_setting("SAFETY_DATA_SHELTER_API_URL"),
            safety_data_service_key=_setting("SAFETY_DATA_SERVICE_KEY"),
            kma_auth_key=_setting("KMA_AUTH_KEY"),
            kma_surface_api_url=_setting("KMA_SURFACE_API_URL"),
            openai_api_key=_setting("OPENAI_API_KEY"),
            openai_model=_setting("OPENAI_MODEL"),
            vworld_api_key=_setting("VWORLD_API_KEY"),
        )


def ensure_data_dirs() -> None:
    """Create writable cache/processed directories used at runtime."""

    for path in (RAW_DIR, CACHE_DIR, PROCESSED_DIR):
        path.mkdir(parents=True, exist_ok=True)
