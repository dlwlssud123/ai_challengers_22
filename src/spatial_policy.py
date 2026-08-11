"""Adapt the spatial analysis pipeline to the existing Alan policy contract."""

from __future__ import annotations

from typing import Any

from src.alan_client import AlanPolicyClient
from src.analysis.simulation import SimulationResult
from src.mock_data import mock_policy
from src.pipeline import AnalysisArtifacts


def _grade(score: float) -> str:
    if score >= 85:
        return "위험"
    if score >= 70:
        return "주의"
    return "관심"


def build_policy_payload(
    artifacts: AnalysisArtifacts,
    simulation: SimulationResult,
    selected_area: Any,
    *,
    budget: int,
    max_facilities: int,
) -> dict:
    """Build the legacy policy payload from calculated GIS results."""

    score = float(selected_area["priority_score"])
    cause_values = {
        "기상 위험": float(selected_area["heat_score"]),
        "고령 취약성": float(selected_area["vulnerability_score"]),
        "접근성 부족": float(selected_area["access_score"]),
    }
    cause_total = sum(cause_values.values()) or 1.0
    recommendations = []
    for row in simulation.selected_candidates.itertuples():
        covered = float(row.incremental_covered_elderly)
        recommendations.append(
            {
                "name": str(row.name),
                "latitude": float(row.latitude),
                "longitude": float(row.longitude),
                "facility_type": str(row.facility_type),
                "estimated_cost": int(float(row.cost)),
                "additional_covered_population": int(round(covered)),
                "reason": f"현재 사각지대 중 추정 고령인구 {covered:,.0f}명을 추가 보호하는 공간 후보입니다.",
            }
        )
    before = simulation.before_metrics
    after = simulation.after_metrics
    return {
        "region": f"{artifacts.metadata['region']} {selected_area['adm_name']}",
        "vulnerability": {
            "region": str(selected_area["adm_name"]),
            "vulnerability_score": score,
            "vulnerability_grade": _grade(score),
            "main_causes": [
                {
                    "name": name,
                    "value": value,
                    "contribution": value / cause_total,
                }
                for name, value in cause_values.items()
            ],
            "vulnerable_population": int(round(float(selected_area["elderly_population"]))),
        },
        "accessibility": {
            "facility_score": max(0.0, 100.0 - float(selected_area["access_score"])),
            "nearest_shelter_distance_m": int(round(float(selected_area["nearest_shelter_distance"]))),
            "accessible_population": int(round(float(before["estimated_covered_elderly"]))),
            "underserved_population": int(round(float(before["estimated_uncovered_elderly"]))),
            "coverage_rate": float(before["coverage_rate"]) * 100,
            "blind_spot": bool(before["blind_spot_count"]),
            "existing_facilities": [],
        },
        "optimization": {
            "budget": budget,
            "max_facilities": max_facilities,
            "recommended_locations": recommendations,
            "before": {
                "coverage_rate": float(before["coverage_rate"]) * 100,
                "underserved_population": int(round(float(before["estimated_uncovered_elderly"]))),
                "blind_spot_count": int(before["blind_spot_count"]),
            },
            "after": {
                "coverage_rate": float(after["coverage_rate"]) * 100,
                "underserved_population": int(round(float(after["estimated_uncovered_elderly"]))),
                "blind_spot_count": int(after["blind_spot_count"]),
            },
        },
    }


def recommend_spatial_policy(payload: dict) -> tuple[dict, str | None]:
    """Use Alan when configured and a calculation-bound template otherwise."""

    client = AlanPolicyClient()
    if client.is_configured:
        policy = client.recommend_policy(payload)
        return policy, client.last_warning
    policy = mock_policy(payload)
    policy["limitations"] = [
        "정책 문장은 계산된 GIS 결과를 규칙 기반 템플릿으로 요약했습니다.",
        "공간 후보지역은 토지 소유권, 설치 규제와 현장 보행환경을 확인한 확정 입지가 아닙니다.",
        "접근권역은 실제 도로망이 아닌 직선거리 기반 추정치입니다.",
    ]
    return policy, "Alan API가 설정되지 않아 계산 결과 기반 템플릿을 사용했습니다."
