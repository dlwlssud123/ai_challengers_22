"""Shelter CSV/JSON/XLSX discovery, normalization, and validation."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


SHELTER_ALIASES: dict[str, tuple[str, ...]] = {
    "shelter_id": ("shelter_id", "무더위쉼터식별자", "연번", "id"),
    "name": ("name", "무더위쉼터명", "시설명", "쉼터명"),
    "address": ("address", "주소", "소재지", "도로명주소"),
    "latitude": ("latitude", "위도", "lat"),
    "longitude": ("longitude", "경도", "lon", "lng"),
    "capacity": ("capacity", "수용인원", "정원"),
    "shelter_type": ("shelter_type", "유형", "구분", "시설유형"),
    "weekday_open": ("weekday_open", "평일운영여부", "사용여부"),
    "weekend_open": ("weekend_open", "주말운영여부"),
    "night_open": ("night_open", "야간운영여부"),
}


def read_tabular(path: Path) -> pd.DataFrame:
    """Read a supported public-data table with safe Korean encoding fallback."""

    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".json":
        return pd.read_json(path)
    if suffix not in {".csv", ".txt"}:
        raise ValueError(f"지원하지 않는 표 형식입니다: {path.name}")
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(io.StringIO(raw.decode(encoding)))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"CSV 인코딩을 판별할 수 없습니다: {path.name}")


def discover_shelter_file(raw_dir: Path) -> Path:
    """Find a shelter source without relying on one Korean filename."""

    search_dirs = [raw_dir]
    if raw_dir.name.lower() == "raw":
        search_dirs.append(raw_dir.parent)
    preferred = [
        directory / f"shelters{suffix}"
        for directory in search_dirs
        for suffix in (".csv", ".json", ".xlsx")
    ]
    for path in preferred:
        if path.exists():
            return path
    matches = sorted(
        path
        for directory in search_dirs
        if directory.exists()
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".csv", ".json", ".xlsx"}
        and ("shelter" in path.stem.lower() or "쉼터" in path.stem)
    )
    if not matches:
        raise FileNotFoundError("data 또는 data/raw에서 무더위쉼터 파일을 찾지 못했습니다.")
    return matches[0]


def _find_column(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    normalized = {str(col).strip().lower(): str(col) for col in columns}
    for alias in aliases:
        if alias.strip().lower() in normalized:
            return normalized[alias.strip().lower()]
    return None


def _yes_no(value: Any, *, default: bool = False) -> bool:
    if pd.isna(value):
        return default
    return str(value).strip().upper() in {"Y", "YES", "TRUE", "1", "운영", "사용"}


def load_shelters(path: Path) -> gpd.GeoDataFrame:
    """Normalize heterogeneous shelter data to a privacy-safe point layer."""

    raw = read_tabular(path)
    columns = [str(col) for col in raw.columns]
    mapped: dict[str, pd.Series] = {}
    for standard, aliases in SHELTER_ALIASES.items():
        source = _find_column(columns, aliases)
        mapped[standard] = raw[source] if source else pd.Series([pd.NA] * len(raw))
    frame = pd.DataFrame(mapped)
    if frame["shelter_id"].isna().all():
        frame["shelter_id"] = [f"S{i:05d}" for i in range(1, len(frame) + 1)]
    frame["shelter_id"] = frame["shelter_id"].astype(str).str.strip()
    frame["name"] = frame["name"].fillna("이름 미상").astype(str).str.strip()
    frame["address"] = frame["address"].fillna("").astype(str).str.strip()
    frame["capacity"] = pd.to_numeric(frame["capacity"], errors="coerce").fillna(0).clip(lower=0)
    frame["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    frame["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")
    frame["shelter_type"] = frame["shelter_type"].fillna("미분류").astype(str).str.strip()
    frame["weekday_open"] = frame["weekday_open"].map(lambda value: _yes_no(value, default=True))
    frame["weekend_open"] = frame["weekend_open"].map(_yes_no)
    frame["night_open"] = frame["night_open"].map(_yes_no)

    active_col = _find_column(columns, ("사용여부", "운영여부", "active"))
    deleted_col = _find_column(columns, ("삭제여부", "폐쇄여부", "deleted"))
    active = raw[active_col].map(lambda value: _yes_no(value, default=True)) if active_col else True
    deleted = raw[deleted_col].map(_yes_no) if deleted_col else False
    valid_coords = frame["latitude"].between(35.5, 36.1) & frame["longitude"].between(128.3, 129.0)
    keep = valid_coords & active & ~deleted
    dropped = int((~keep).sum())
    frame = frame.loc[keep].copy()
    before_duplicates = len(frame)
    frame = frame.drop_duplicates(subset=["shelter_id"], keep="first")
    frame = frame.drop_duplicates(subset=["name", "latitude", "longitude"], keep="first")
    duplicates = before_duplicates - len(frame)
    result = gpd.GeoDataFrame(
        frame,
        geometry=gpd.points_from_xy(frame["longitude"], frame["latitude"]),
        crs="EPSG:4326",
    ).reset_index(drop=True)
    result.attrs["quality"] = {
        "input_rows": int(len(raw)),
        "valid_rows": int(len(result)),
        "dropped_invalid_or_inactive": dropped,
        "dropped_duplicates": duplicates,
        "source_file": path.name,
    }
    return result

