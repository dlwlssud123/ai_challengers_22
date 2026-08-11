"""Build the best available dataset and expose its provenance."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd

from src.config import DATA_DIR, PROCESSED_DIR, RAW_DIR, Settings, ensure_data_dirs
from src.data.candidates import generate_grid_candidates, load_candidate_file
from src.data.demo import DEFAULT_DONG_NAMES, make_demo_areas
from src.data.shelters import discover_shelter_file, load_shelters, read_tabular


REQUIRED_REAL_AREA_COLUMNS = {
    "adm_cd", "adm_name", "population", "elderly_population", "temperature", "humidity", "geometry"
}


@dataclass
class DatasetBundle:
    areas: gpd.GeoDataFrame
    shelters: gpd.GeoDataFrame
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
    shelter_path = discover_shelter_file(RAW_DIR)
    shelters = load_shelters(shelter_path)
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
    else:
        names = _administrative_names(_find_source("administrative_facilities.csv", "행정기관"))
        areas = make_demo_areas(shelters, names)

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

    actual_source_names = [shelter_path.name]
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
    if use_real_areas:
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
    metadata = {
        "region": settings.target_region_name,
        "analysis_year": settings.analysis_year,
        "data_mode": "실제 공공데이터" if use_real_areas else "실제 시설 + DEMO SAMPLE 인구·경계·동별기상",
        "is_demo": not use_real_areas,
        "candidate_mode": candidate_mode,
        "actual_sources": actual_source_names,
        "weather_context": weather_context,
        "shelter_quality": shelters.attrs.get("quality", {}),
        "assumptions": [
            "DEMO SAMPLE 행정동 경계·인구·동별기상" if not use_real_areas else "제공된 실제 행정동 자료",
            "행정동 내부 고령인구 균등분포",
            "EPSG:5179 직선거리 기반 접근권역",
        ],
    }
    return DatasetBundle(areas=areas, shelters=shelters, candidates=candidates, metadata=metadata)


def save_bundle(bundle: DatasetBundle, output_dir: Path = PROCESSED_DIR) -> None:
    """Persist processed layers and provenance for repeatable app startup."""

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle.areas.to_file(output_dir / "areas.geojson", driver="GeoJSON")
    bundle.shelters.to_file(output_dir / "shelters.geojson", driver="GeoJSON")
    bundle.candidates.to_file(output_dir / "candidates.geojson", driver="GeoJSON")
    (output_dir / "metadata.json").write_text(
        json.dumps(bundle.metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
