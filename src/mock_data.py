"""외부 데이터와 모델 없이도 전체 시연을 가능하게 하는 고정 데이터."""

from __future__ import annotations
import os
import pandas as pd
from copy import deepcopy


REGIONS: dict[str, dict] = {
    "대구광역시 달서구 송현1동": {
        "center": {"latitude": 35.8321, "longitude": 128.5518},
        "vulnerability_score": 87.2, "vulnerability_grade": "위험", "vulnerable_population": 1430,
        "main_causes": [
            {"name": "고령인구 비율", "value": 31.2, "contribution": 0.34},
            {"name": "열지수", "value": 39.1, "contribution": 0.28},
            {"name": "녹지 부족", "value": 18.4, "contribution": 0.19},
        ],
        "facility_score": 32.5, "nearest_shelter_distance_m": 820,
        "accessible_population": 720, "underserved_population": 710, "blind_spot_count": 4,
        "existing_facilities": [
            {"name": "송현경로당", "type": "무더위쉼터", "latitude": 35.8332, "longitude": 128.5487, "status": "운영"},
            {"name": "송현1동 행정복지센터", "type": "무더위쉼터", "latitude": 35.8304, "longitude": 128.5539, "status": "운영"},
        ],
        "candidates": [
            {"name": "송현근린공원 입구", "latitude": 35.8288, "longitude": 128.5571, "facility_type": "그늘막", "estimated_cost": 12_000_000, "additional_covered_population": 250, "reason": "보행 동선과 취약인구 밀집지역이 겹치는 후보지"},
            {"name": "월촌역 4번 출구", "latitude": 35.8237, "longitude": 128.5458, "facility_type": "스마트쉼터", "estimated_cost": 28_000_000, "additional_covered_population": 430, "reason": "기존 쉼터와 거리가 먼 대중교통 결절점"},
            {"name": "송현시장 공영주차장", "latitude": 35.8351, "longitude": 128.5562, "facility_type": "쿨링포그", "estimated_cost": 20_000_000, "additional_covered_population": 320, "reason": "고령층 이용이 많은 생활권 중심 후보지"},
        ],
    },
    "대구광역시 서구 비산2·3동": {
        "center": {"latitude": 35.8815, "longitude": 128.5701},
        "vulnerability_score": 78.6, "vulnerability_grade": "주의", "vulnerable_population": 1080,
        "main_causes": [
            {"name": "지표면 온도", "value": 42.3, "contribution": 0.38},
            {"name": "독거노인 비율", "value": 17.8, "contribution": 0.25},
            {"name": "도로율", "value": 29.4, "contribution": 0.16},
        ],
        "facility_score": 45.1, "nearest_shelter_distance_m": 610,
        "accessible_population": 640, "underserved_population": 440, "blind_spot_count": 3,
        "existing_facilities": [
            {"name": "비산2·3동 경로당", "type": "무더위쉼터", "latitude": 35.8830, "longitude": 128.5680, "status": "운영"},
        ],
        "candidates": [
            {"name": "북비산네거리 버스정류장", "latitude": 35.8798, "longitude": 128.5732, "facility_type": "스마트쉼터", "estimated_cost": 28_000_000, "additional_covered_population": 300, "reason": "대중교통 이용량과 열환경 취약성이 높은 후보지"},
            {"name": "비산초등학교 서편", "latitude": 35.8840, "longitude": 128.5741, "facility_type": "그늘막", "estimated_cost": 12_000_000, "additional_covered_population": 180, "reason": "그늘이 부족한 보행축의 설치 가능 후보지"},
        ],
    },
    "대구광역시 북구 산격3동": {
        "center": {"latitude": 35.8936, "longitude": 128.6084},
        "vulnerability_score": 65.4, "vulnerability_grade": "관심", "vulnerable_population": 920,
        "main_causes": [
            {"name": "열대야 일수", "value": 21.0, "contribution": 0.31},
            {"name": "녹지 부족", "value": 15.7, "contribution": 0.24},
            {"name": "고령인구 비율", "value": 22.6, "contribution": 0.18},
        ],
        "facility_score": 58.3, "nearest_shelter_distance_m": 430,
        "accessible_population": 650, "underserved_population": 270, "blind_spot_count": 2,
        "existing_facilities": [
            {"name": "산격3동 행정복지센터", "type": "무더위쉼터", "latitude": 35.8922, "longitude": 128.6110, "status": "운영"},
            {"name": "산격대우아파트 경로당", "type": "무더위쉼터", "latitude": 35.8960, "longitude": 128.6055, "status": "운영"},
        ],
        "candidates": [
            {"name": "산격시장 남문", "latitude": 35.8907, "longitude": 128.6074, "facility_type": "그늘막", "estimated_cost": 12_000_000, "additional_covered_population": 150, "reason": "고령층 통행이 많은 생활권 후보지"},
            {"name": "연암공원 동편", "latitude": 35.8980, "longitude": 128.6120, "facility_type": "쿨링포그", "estimated_cost": 20_000_000, "additional_covered_population": 140, "reason": "기존 시설 서비스권의 외곽 후보지"},
        ],
    },
}


def available_regions() -> list[str]:
    return list(REGIONS)


def region_heatmap_geojson(selected_region: str | None = None) -> dict:
    """시연용 행정동 경계를 반환한다. 실제 경계 GeoJSON으로 교체해야 한다."""
    features = []
    for index, (region, data) in enumerate(REGIONS.items()):
        latitude = data["center"]["latitude"]
        longitude = data["center"]["longitude"]
        # 서로 겹치지 않는 간이 폴리곤이다. 실제 행정동 경계가 아니다.
        longitude_radius = 0.012 if index != 1 else 0.010
        latitude_radius = 0.009 if index != 2 else 0.008
        score = data["vulnerability_score"]
        if region == selected_region:
            fill_color = [249, 115, 22, 235]
            line_color = [255, 255, 255, 255]
        elif score >= 85:
            fill_color = [220, 38, 38, 190]
            line_color = [127, 29, 29, 255]
        elif score >= 70:
            fill_color = [249, 115, 22, 180]
            line_color = [154, 52, 18, 255]
        else:
            fill_color = [250, 204, 21, 165]
            line_color = [161, 98, 7, 255]
        coordinates = [[
            [longitude - longitude_radius, latitude - latitude_radius],
            [longitude + longitude_radius, latitude - latitude_radius],
            [longitude + longitude_radius, latitude + latitude_radius],
            [longitude - longitude_radius, latitude + latitude_radius],
            [longitude - longitude_radius, latitude - latitude_radius],
        ]]
        features.append({
            "type": "Feature",
            "properties": {
                "region": region,
                "vulnerability_score": score,
                "vulnerability_grade": data["vulnerability_grade"],
                "vulnerable_population": data["vulnerable_population"],
                "fill_color": fill_color,
                "line_color": line_color,
            },
            "geometry": {"type": "Polygon", "coordinates": coordinates},
        })
    return {"type": "FeatureCollection", "features": features}


def _region(region: str) -> dict:
    if region in REGIONS:
        return deepcopy(REGIONS[region])
        
    districts = ["수성구", "달서구", "동구", "서구", "남구", "북구", "중구", "달성군", "군위군"]
    for dist in districts:
        if dist in region:
            return deepcopy(REGIONS[dist])
            
    normalized_region = region.replace(" ", "")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(base_dir, "data", "raw", "daegu_dong_population_202607.csv")
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path, encoding="utf-8")
            for row in df.itertuples():
                dong = str(row.adm_name).strip()
                if dong in normalized_region or normalized_region in dong:
                    parent_dist = str(row.district_name).strip()
                    if parent_dist in REGIONS:
                        return deepcopy(REGIONS[parent_dist])
        except Exception:
            pass
            
    return deepcopy(REGIONS["달서구"])


def mock_vulnerability(region: str) -> dict:
    data = _region(region)
    return {"region": region, "vulnerability_score": data["vulnerability_score"], "vulnerability_grade": data["vulnerability_grade"], "main_causes": data["main_causes"], "vulnerable_population": data["vulnerable_population"]}


def mock_accessibility(region: str) -> dict:
    data = _region(region)
    total = data["accessible_population"] + data["underserved_population"]
    return {
        "facility_score": data["facility_score"], "nearest_shelter_distance_m": data["nearest_shelter_distance_m"],
        "accessible_population": data["accessible_population"], "underserved_population": data["underserved_population"],
        "coverage_rate": round(data["accessible_population"] / total * 100, 1), "blind_spot": data["blind_spot_count"] > 0,
        "blind_spot_count": data["blind_spot_count"], "existing_facilities": data["existing_facilities"], "map_center": data["center"],
    }


def mock_optimization(region: str, budget: int, max_facilities: int, accessibility: dict) -> dict:
    data = _region(region)
    candidates = sorted(data["candidates"], key=lambda item: item["additional_covered_population"] / item["estimated_cost"], reverse=True)
    selected, spent = [], 0
    for candidate in candidates:
        if len(selected) >= max_facilities:
            break
        if spent + candidate["estimated_cost"] <= budget:
            selected.append(candidate)
            spent += candidate["estimated_cost"]
    additional = min(accessibility["underserved_population"], sum(item["additional_covered_population"] for item in selected))
    total = accessibility["accessible_population"] + accessibility["underserved_population"]
    after_accessible = accessibility["accessible_population"] + additional
    before_blind = accessibility.get("blind_spot_count", int(accessibility["blind_spot"]))
    return {
        "budget": budget, "max_facilities": max_facilities, "total_estimated_cost": spent, "recommended_locations": selected,
        "before": {"coverage_rate": accessibility["coverage_rate"], "underserved_population": accessibility["underserved_population"], "blind_spot_count": before_blind},
        "after": {"coverage_rate": round(after_accessible / total * 100, 1) if total else 0.0, "underserved_population": max(0, accessibility["underserved_population"] - additional), "blind_spot_count": max(0, before_blind - len(selected))},
    }


def mock_policy(analysis_result: dict) -> dict:
    vulnerability, accessibility, optimization = analysis_result["vulnerability"], analysis_result["accessibility"], analysis_result["optimization"]
    policies = [{
        "policy_name": f"{location['facility_type']} 우선 설치", "target_location": location["name"], "reason": location["reason"],
        "action_plan": ["현장 보행 동선과 설치 가능 여부를 확인합니다.", "시설 운영 주체와 점검 일정을 확정합니다."],
        "expected_effect": f"분석상 최대 {location['additional_covered_population']:,}명의 추가 접근 가능 인구를 확보하는 후보입니다.",
    } for location in optimization["recommended_locations"][:3]]
    score = vulnerability["vulnerability_score"]
    return {
        "summary": f"{analysis_result['region']}의 폭염 취약도는 {score:.1f}점({vulnerability['vulnerability_grade']})이며, 현재 접근 취약인구는 {accessibility['underserved_population']:,}명입니다. 예산 조건에서 {len(policies)}개 후보를 우선 검토할 수 있습니다.",
        "priority_level": "긴급" if score >= 85 else "높음" if score >= 70 else "보통",
        "recommended_policies": policies,
        "limitations": ["현재 결과는 해커톤 시연용 Mock 데이터와 단순 비용 효율 휴리스틱을 사용했습니다.", "실제 집행 전 최신 인구·시설 데이터와 현장 설치 가능 여부를 확인해야 합니다."],
    }
