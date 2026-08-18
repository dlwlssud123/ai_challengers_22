"""Local heat shelter and shade facility loaders."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import geopandas as gpd
import pandas as pd

from src.config import RAW_DIR
from src.data.shelters import read_tabular


DAEGU_BOUNDS = {
    "lat_min": 35.5,
    "lat_max": 36.2,
    "lon_min": 128.2,
    "lon_max": 129.1,
}


def _valid_daegu_points(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["latitude"].between(DAEGU_BOUNDS["lat_min"], DAEGU_BOUNDS["lat_max"])
        & frame["longitude"].between(DAEGU_BOUNDS["lon_min"], DAEGU_BOUNDS["lon_max"])
    )


def _text(value: Any, default: str = "") -> str:
    if pd.isna(value):
        return default
    return str(value).strip()


def _xlsx_rows(path: Path) -> list[list[Any]]:
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("main:si", ns):
                text = "".join(node.text or "" for node in item.findall(".//main:t", ns))
                shared.append(text)

        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        first_sheet = workbook.find("main:sheets/main:sheet", ns)
        if first_sheet is None:
            return []
        relationship_id = first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(
            rel.attrib["Target"]
            for rel in rels
            if rel.attrib["Id"] == relationship_id
        )
        sheet_path = "xl/" + target.lstrip("/")
        sheet = ElementTree.fromstring(archive.read(sheet_path))

    rows: list[list[Any]] = []
    for row in sheet.findall(".//main:sheetData/main:row", ns):
        values: list[Any] = []
        current_col = 0
        for cell in row.findall("main:c", ns):
            ref = cell.attrib.get("r", "")
            col_letters = "".join(ch for ch in ref if ch.isalpha())
            if col_letters:
                col_index = 0
                for letter in col_letters:
                    col_index = col_index * 26 + ord(letter.upper()) - ord("A") + 1
                while current_col < col_index - 1:
                    values.append(None)
                    current_col += 1
            value_node = cell.find("main:v", ns)
            inline_node = cell.find("main:is/main:t", ns)
            value: Any = None
            if value_node is not None:
                raw = value_node.text or ""
                value = shared[int(raw)] if cell.attrib.get("t") == "s" else raw
            elif inline_node is not None:
                value = inline_node.text or ""
            values.append(value)
            current_col += 1
        rows.append(values)
    return rows


def _read_shelter_excel(path: Path) -> pd.DataFrame:
    try:
        raw = pd.read_excel(path, header=None)
    except ImportError:
        raw = pd.DataFrame(_xlsx_rows(path))
    records = raw.iloc[5:].copy()
    frame = pd.DataFrame(
        {
            "shelter_id": records.iloc[:, 41],
            "name": records.iloc[:, 3],
            "address": records.iloc[:, 7].fillna(records.iloc[:, 8]),
            "district_name": records.iloc[:, 2],
            "adm_name": records.iloc[:, 6],
            "status": records.iloc[:, 4],
            "capacity": records.iloc[:, 12],
            "shelter_type": records.iloc[:, 9].fillna(records.iloc[:, 10]),
            "longitude": records.iloc[:, 36],
            "latitude": records.iloc[:, 37],
        }
    )
    return frame


def load_local_heat_shelters(path: Path | None = None) -> gpd.GeoDataFrame:
    path = path or RAW_DIR / "무더위쉼터현황표.xlsx"
    raw = _read_shelter_excel(path)
    frame = pd.DataFrame(
        {
            "facility_id": raw["shelter_id"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True),
            "name": raw["name"].map(_text),
            "address": raw["address"].map(_text),
            "district_name": raw["district_name"].map(_text),
            "adm_name": raw["adm_name"].map(_text),
            "facility_type": "무더위쉼터",
            "shelter_type": raw["shelter_type"].map(lambda value: _text(value, "미분류")),
            "status": raw["status"].map(lambda value: _text(value, "운영")),
            "capacity": pd.to_numeric(raw["capacity"], errors="coerce").fillna(0).clip(lower=0),
            "longitude": pd.to_numeric(raw["longitude"], errors="coerce"),
            "latitude": pd.to_numeric(raw["latitude"], errors="coerce"),
            "source_file": path.name,
        }
    )
    frame = frame[
        frame["status"].eq("운영")
        & frame["name"].ne("")
        & _valid_daegu_points(frame)
    ].copy()
    missing_id = frame["facility_id"].eq("") | frame["facility_id"].eq("nan")
    frame.loc[missing_id, "facility_id"] = [f"HEAT-{idx + 1:05d}" for idx in range(int(missing_id.sum()))]
    frame["shelter_id"] = frame["facility_id"]
    frame = frame.drop_duplicates(subset=["name", "latitude", "longitude"], keep="first")
    return gpd.GeoDataFrame(
        frame,
        geometry=gpd.points_from_xy(frame["longitude"], frame["latitude"]),
        crs="EPSG:4326",
    ).reset_index(drop=True)


def _empty_shades() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        columns=["facility_id", "name", "address", "district_name", "adm_name", "facility_type", "shelter_type", "status", "capacity", "longitude", "latitude", "source_file", "shelter_id", "geometry"],
        geometry="geometry",
        crs="EPSG:4326",
    )


def _shade_geodataframe(frame: pd.DataFrame) -> gpd.GeoDataFrame:
    frame = frame[frame["name"].ne("") & _valid_daegu_points(frame)].copy()
    frame = frame.drop_duplicates(subset=["name", "latitude", "longitude"], keep="first")
    frame["shelter_id"] = frame["facility_id"]
    return gpd.GeoDataFrame(
        frame,
        geometry=gpd.points_from_xy(frame["longitude"], frame["latitude"]),
        crs="EPSG:4326",
    ).reset_index(drop=True)


def load_standard_shades(path: Path | None = None) -> gpd.GeoDataFrame:
    path = path or RAW_DIR / "전국그늘막쉼터표준데이터.csv"
    raw = read_tabular(path)
    daegu = raw[raw["시도명"].astype(str).str.strip().eq("대구광역시")].copy()
    frame = pd.DataFrame(
        {
            "facility_id": [f"SHADE-{idx + 1:05d}" for idx in range(len(daegu))],
            "name": daegu["설치장소명"].map(_text),
            "address": daegu["소재지도로명주소"].fillna(daegu["소재지지번주소"]).map(_text),
            "district_name": daegu["시군구명"].map(_text),
            "adm_name": "",
            "facility_type": "그늘막",
            "shelter_type": daegu["그늘막유형"].map(lambda value: _text(value, "그늘막")),
            "status": "운영",
            "capacity": 0,
            "longitude": pd.to_numeric(daegu["경도"], errors="coerce"),
            "latitude": pd.to_numeric(daegu["위도"], errors="coerce"),
            "source_file": path.name,
        }
    )
    return _shade_geodataframe(frame)


def load_suseong_shades(path: Path | None = None, geocoder: Any | None = None) -> gpd.GeoDataFrame:
    path = path or RAW_DIR / "대구광역시 수성구_그늘막 설치현황_20250719.csv"
    if not path.exists():
        return _empty_shades()
    raw = read_tabular(path)
    frame = pd.DataFrame(
        {
            "facility_id": "SUSEONG-" + raw["관리번호"].fillna("").astype(str).str.strip(),
            "name": raw["설치장소"].map(_text),
            "address": raw["소재지주소"].map(_text),
            "district_name": "수성구",
            "adm_name": raw["행정동"].map(_text),
            "facility_type": "그늘막",
            "shelter_type": "그늘막",
            "status": "운영",
            "capacity": 0,
            "longitude": pd.NA,
            "latitude": pd.NA,
            "source_file": path.name,
        }
    )
    if geocoder is not None:
        latitudes: list[float | None] = []
        longitudes: list[float | None] = []
        for address in frame["address"]:
            coords = geocoder.geocode(address)
            latitudes.append(coords[0] if coords else None)
            longitudes.append(coords[1] if coords else None)
        frame["latitude"] = latitudes
        frame["longitude"] = longitudes
    frame["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    frame["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")
    return _shade_geodataframe(frame)


def load_local_shades(path: Path | None = None, geocoder: Any | None = None) -> gpd.GeoDataFrame:
    layers = [load_standard_shades(path), load_suseong_shades(geocoder=geocoder)]
    layers = [layer for layer in layers if not layer.empty]
    if not layers:
        return _empty_shades()
    merged = gpd.GeoDataFrame(pd.concat(layers, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    return merged.drop_duplicates(subset=["name", "latitude", "longitude"], keep="first").reset_index(drop=True)
