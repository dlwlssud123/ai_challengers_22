"""Spatial analysis pipeline to compute green area ratio by administrative dongs."""

from __future__ import annotations
import geopandas as gpd
import pandas as pd


def compute_dong_green_ratio(
    dong_boundary_path: str,
    park_polygon_path: str,
    analysis_crs: str = "EPSG:5179"
) -> gpd.GeoDataFrame:
    """
    행정동 경계와 공원 폴리곤 데이터를 결합하여 동별 녹지 면적 및 녹지 비율(%)을 계산합니다.

    Args:
        dong_boundary_path: 행정동 경계 GeoJSON/SHP 파일 경로
        park_polygon_path: 도시공원 폴리곤 GeoJSON/SHP 파일 경로
        analysis_crs: 면적 계산에 사용할 평면투영좌표계 (기본값: EPSG:5179 - 미터 단위)

    Returns:
        동별 녹지 비율(green_ratio_pct)이 포함된 GeoDataFrame
    """
    # 1. 지리 데이터 로드
    dongs = gpd.read_file(dong_boundary_path)
    parks = gpd.read_file(park_polygon_path)

    # 2. 정확한 면적 계산(미터 단위)을 위해 평면투영좌표계(CRS)로 통일
    if dongs.crs is None or parks.crs is None:
        raise ValueError("데이터의 원본 CRS 정보가 없습니다. 지리좌표계(EPSG:4326) 설정 여부를 확인하세요.")
        
    dongs_projected = dongs.to_crs(analysis_crs)
    parks_projected = parks.to_crs(analysis_crs)

    # 3. 행정동 자체의 전체 면적(㎡) 계산 및 저장
    dongs_projected["dong_area_m2"] = dongs_projected.geometry.area

    # 4. Spatial Overlay (Intersection)를 사용해 행정동 경계 내로 잘려 들어온 공원 폴리곤 조각 생성
    # 이 연산은 공원이 여러 동에 걸쳐 있을 때 정확히 동 경계선으로 공원 면적을 분할해 줍니다.
    parks_in_dongs = gpd.overlay(dongs_projected, parks_projected, how="intersection")

    # 5. 각 조각들의 면적 계산
    parks_in_dongs["intersected_park_area_m2"] = parks_in_dongs.geometry.area

    # 6. 행정동 코드(adm_cd) 기준으로 그룹화하여 동별 공원 면적 합산
    # 'adm_cd'는 통계청 행정동 코드 고유값
    park_area_by_dong = (
        parks_in_dongs.groupby("adm_cd")["intersected_park_area_m2"]
        .sum()
        .reset_index()
    )

    # 7. 원본 행정동 데이터와 조인
    result = dongs_projected.merge(park_area_by_dong, on="adm_cd", how="left")
    
    # 공원이 전혀 없는 행정동은 NaN을 0으로 대체
    result["intersected_park_area_m2"] = result["intersected_park_area_m2"].fillna(0.0)

    # 8. 녹지 비율(%) 계산
    result["green_ratio_pct"] = (
        result["intersected_park_area_m2"] / result["dong_area_m2"] * 100
    ).round(2)

    # 9. 시각화(Folium/Mapbox 등)와 연동하기 위해 최종 반환 시 위경도 좌표계(EPSG:4326)로 환원
    return result.to_crs("EPSG:4326")
