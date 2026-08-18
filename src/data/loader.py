"""Build the best available dataset and expose its provenance."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd

from src.config import CACHE_DIR, DATA_DIR, PROCESSED_DIR, PROJECT_ROOT, RAW_DIR, Settings, ensure_data_dirs
from src.data.candidates import generate_grid_candidates, load_candidate_file
from src.data.demo import DEFAULT_DONG_NAMES, make_demo_areas
from src.data.http import DataSourceError, JsonCache
from src.data.kma_surface import absolute_heat_hazard_score, fetch_latest_daegu_weather
from src.data.safety_shelters import (
    fetch_daegu_shelter_payload,
    normalize_safety_shelters,
)
from src.data.shelters import discover_shelter_file, load_shelters, read_tabular
from src.data.team_vulnerability import load_team_vulnerability


REQUIRED_REAL_AREA_COLUMNS = {
    "adm_cd", "adm_name", "population", "elderly_population", "temperature", "humidity", "geometry"
}


@dataclass
class DatasetBundle:
    areas: gpd.GeoDataFrame
    shelters: gpd.GeoDataFrame
    citywide_shelters: gpd.GeoDataFrame
    candidates: gpd.GeoDataFrame
    metadata: dict[str, Any]


def _administrative_names(path: Path) -> list[str]:
    if not path.exists():
        return DEFAULT_DONG_NAMES
    frame = read_tabular(path)
    if "구분" not in frame:
        return DEFAULT_DONG_NAMES
    names = [str(value).strip() for value in frame["구분"] if str(value).strip() != "수성구청"]
    return names or DEFAULT_DONG_NAMES


def _find_source(preferred_name: str, korean_token: str) -> Path:
    """Prefer normalized raw files, then discover the team's Korean source file."""

    preferred = RAW_DIR / preferred_name
    if preferred.exists():
        return preferred
    matches = sorted(
        path
        for path in DATA_DIR.glob("*.*")
        if path.is_file() and korean_token in path.stem
    )
    return matches[0] if matches else preferred


def read_weather_extremum_context(path: Path) -> dict[str, Any] | None:
    """Read the latest Daegu monthly temperature row from the supplied KMA CSV."""

    if not path.exists():
        return None
    raw = path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return None
    rows = list(csv.reader(io.StringIO(text)))
    header_index = next(
        (idx for idx, row in enumerate(rows) if any("지점번호" in cell for cell in row)), None
    )
    if header_index is None:
        return None
    headers = [cell.strip() for cell in rows[header_index]]
    records = [row for row in rows[header_index + 1 :] if len(row) == len(headers)]
    if not records:
        return None
    latest = dict(zip(headers, records[-1], strict=True))
    return {
        "station": latest.get("지점명", "대구"),
        "period": latest.get("일시"),
        "mean_temperature_c": _float_or_none(latest.get("평균기온(℃)")),
        "mean_high_temperature_c": _float_or_none(latest.get("평균최고기온(℃)")),
        "maximum_temperature_c": _float_or_none(latest.get("최고기온(℃)")),
        "source_file": path.name,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def build_source_dataset(settings: Settings) -> DatasetBundle:
    """Load actual sources where available and use explicit demo fallbacks otherwise."""

    ensure_data_dirs()
    shelters = gpd.GeoDataFrame()
    citywide_shelters = gpd.GeoDataFrame()
    shelter_path = None
    shelter_source_mode = "unavailable"
    shelter_fetched_at = None
    shelter_warning = None

    if settings.safety_data_shelter_api_url and settings.safety_data_service_key:
        try:
            payload, shelter_source_mode, shelter_fetched_at = fetch_daegu_shelter_payload(
                api_url=settings.safety_data_shelter_api_url,
                service_key=settings.safety_data_service_key,
                timeout=settings.api_timeout_seconds,
                cache=JsonCache(CACHE_DIR),
            )
            citywide_shelters = normalize_safety_shelters(payload)
            shelters = citywide_shelters
        except DataSourceError as exc:
            shelter_warning = str(exc)

    if shelters.empty:
        try:
            shelter_path = discover_shelter_file(RAW_DIR)
            fallback_shelters = load_shelters(shelter_path)
            shelters = fallback_shelters
            citywide_shelters = fallback_shelters
            shelter_source_mode = "local_csv"
        except FileNotFoundError:
            if shelter_warning:
                raise DataSourceError(
                    f"무더위쉼터 API/캐시를 사용할 수 없고 로컬 쉼터 파일도 없습니다: {shelter_warning}"
                )
            raise
    area_path = RAW_DIR / "areas.geojson"
    use_real_areas = False
    if area_path.exists() and settings.demo_mode != "true":
        areas = gpd.read_file(area_path)
        missing = REQUIRED_REAL_AREA_COLUMNS - set(areas.columns)
        if missing:
            raise ValueError(f"areas.geojson 필수 컬럼 누락: {', '.join(sorted(missing))}")
        if areas.crs is None:
            raise ValueError("areas.geojson에 CRS가 없습니다. 원본 CRS를 명시해야 합니다.")
        areas = areas.to_crs(settings.display_crs)
        areas["is_demo"] = False
        use_real_areas = True
        if shelter_source_mode in {"live", "cache"}:
            quality = dict(citywide_shelters.attrs.get("quality", {}))
            area_union = areas.to_crs(settings.display_crs).geometry.union_all()
            shelters = citywide_shelters[citywide_shelters.geometry.intersects(area_union)].copy()
            quality["analysis_region_rows"] = int(len(shelters))
            shelters.attrs["quality"] = quality
    else:
        names = _administrative_names(_find_source("administrative_facilities.csv", "행정기관"))
        areas = make_demo_areas(shelters, names)

    live_weather = None
    live_weather_mode = None
    live_weather_fetched_at = None
    weather_warning = None
    if settings.kma_surface_api_url and settings.kma_auth_key:
        try:
            live_weather, live_weather_mode, live_weather_fetched_at = fetch_latest_daegu_weather(
                api_url=settings.kma_surface_api_url,
                auth_key=settings.kma_auth_key,
                timeout=settings.api_timeout_seconds,
                cache=JsonCache(CACHE_DIR),
            )
            areas["live_heat_score"] = absolute_heat_hazard_score(
                live_weather["temperature_c"], live_weather["humidity_percent"]
            )
        except DataSourceError as exc:
            weather_warning = str(exc)

    candidate_path = RAW_DIR / "candidate_sites.csv"
    if candidate_path.exists():
        candidates = load_candidate_file(candidate_path, settings.default_shelter_cost_krw)
        candidate_mode = "실제 제공 후보시설"
    else:
        candidates = generate_grid_candidates(
            areas,
            shelters,
            spacing_m=settings.default_candidate_grid_m,
            default_cost=settings.default_shelter_cost_krw,
        )
        candidate_mode = "공간 후보지역(DEMO): 실제 설치 가능 시설이 아님"

    actual_source_names = [
        "재난안전데이터공유플랫폼 DSSP-IF-10942"
        if shelter_source_mode in {"live", "cache"}
        else shelter_path.name if shelter_path is not None else "무더위쉼터 데이터 없음"
    ]
    if use_real_areas:
        actual_source_names.append(area_path.name)
    optional_sources = (
        ("elderly_facilities.csv", "노인복지시설"),
        ("administrative_facilities.csv", "행정기관"),
        ("weather_extremum.csv", "weather_extremum"),
    )
    for name, token in optional_sources:
        source = _find_source(name, token)
        if source.exists():
            actual_source_names.append(source.name)
    if live_weather:
        weather_context = {
            "station": "대구 ASOS 143",
            "period": live_weather["observed_at_kst"],
            "temperature_c": live_weather["temperature_c"],
            "humidity_percent": live_weather["humidity_percent"],
            "heat_hazard_score": absolute_heat_hazard_score(
                live_weather["temperature_c"], live_weather["humidity_percent"]
            ),
            "variables": "TA/HM",
            "mode": live_weather_mode,
            "fetched_at": live_weather_fetched_at,
            "application": "현재 절대위험 50% + 행정동 기상 스냅샷의 상대위험 50%",
        }
    elif use_real_areas:
        first_area = areas.iloc[0]
        base_date = str(first_area.get("weather_base_date", ""))
        base_time = str(first_area.get("weather_base_time", ""))
        weather_context = {
            "station": "수성구 행정동 중심 KMA 격자",
            "period": f"{base_date} {base_time}".strip() or None,
            "variables": "T1H/REH",
            "mode": str(first_area.get("weather_source", "KMA")),
            "source_file": area_path.name,
        }
    else:
        weather_context = read_weather_extremum_context(_find_source("weather_extremum.csv", "weather_extremum"))
    team_vulnerability = load_team_vulnerability(PROJECT_ROOT)
    team_records = team_vulnerability.where(team_vulnerability.notna(), None).to_dict("records")

    metadata = {
        "region": settings.target_region_name,
        "analysis_year": settings.analysis_year,
        "data_mode": "실제 공공데이터" if use_real_areas else "실제 시설 + DEMO SAMPLE 인구·경계·동별기상",
        "is_demo": not use_real_areas,
        "candidate_mode": candidate_mode,
        "actual_sources": actual_source_names,
        "weather_context": weather_context,
        "weather_warning": weather_warning,
        "shelter_quality": shelters.attrs.get("quality", {}),
        "shelter_source_mode": shelter_source_mode,
        "shelter_fetched_at": shelter_fetched_at,
        "shelter_warning": shelter_warning,
        "citywide_shelter_count": int(len(citywide_shelters)),
        "team_vulnerability": team_records,
        "assumptions": [
            "DEMO SAMPLE 행정동 경계·인구·동별기상" if not use_real_areas else "제공된 실제 행정동 자료",
            "행정동 내부 고령인구 균등분포",
            "EPSG:5179 직선거리 기반 접근권역",
        ],
    }
    return DatasetBundle(
        areas=areas,
        shelters=shelters,
        citywide_shelters=citywide_shelters,
        candidates=candidates,
        metadata=metadata,
    )


def save_bundle(bundle: DatasetBundle, output_dir: Path = PROCESSED_DIR) -> None:
    """Persist processed layers and provenance for repeatable app startup."""

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle.areas.to_file(output_dir / "areas.geojson", driver="GeoJSON")
    bundle.shelters.to_file(output_dir / "shelters.geojson", driver="GeoJSON")
    bundle.candidates.to_file(output_dir / "candidates.geojson", driver="GeoJSON")
    (output_dir / "metadata.json").write_text(
        json.dumps(bundle.metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
