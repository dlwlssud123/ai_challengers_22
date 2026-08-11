"""취약도·접근성·입지·정책 추천을 하나의 안정적인 흐름으로 통합한다."""

from __future__ import annotations
from . import accessibility, optimization, vulnerability
from .alan_client import AlanPolicyClient
from .mock_data import mock_accessibility, mock_optimization, mock_vulnerability


def _validate_inputs(region: str, budget: int, max_facilities: int) -> None:
    if not isinstance(region, str) or not region.strip():
        raise ValueError("분석 대상 지역을 선택해 주세요.")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        raise ValueError("예산은 0 이상의 정수여야 합니다.")
    if isinstance(max_facilities, bool) or not isinstance(max_facilities, int) or max_facilities < 0:
        raise ValueError("설치 가능 시설 수는 0 이상의 정수여야 합니다.")


def run_policy_analysis(region: str, budget: int, max_facilities: int, use_mock: bool = False) -> dict:
    """모든 분석과 정책 추천 결과를 단일 표준 딕셔너리로 반환한다."""
    _validate_inputs(region, budget, max_facilities)
    warnings, used_mock = [], use_mock
    try:
        vulnerability_result = mock_vulnerability(region) if use_mock else vulnerability.analyze_vulnerability(region)
    except Exception as exc:
        used_mock = True; warnings.append(f"취약도 분석을 Mock으로 대체했습니다: {exc}"); vulnerability_result = mock_vulnerability(region)
    try:
        accessibility_result = mock_accessibility(region) if use_mock else accessibility.analyze_accessibility(region)
    except Exception as exc:
        used_mock = True; warnings.append(f"시설 접근성 분석을 Mock으로 대체했습니다: {exc}"); accessibility_result = mock_accessibility(region)
    try:
        optimization_result = mock_optimization(region, budget, max_facilities, accessibility_result) if use_mock else optimization.recommend_locations(region, budget, max_facilities, vulnerability_result, accessibility_result)
    except Exception as exc:
        used_mock = True; warnings.append(f"입지 추천을 Mock으로 대체했습니다: {exc}"); optimization_result = mock_optimization(region, budget, max_facilities, accessibility_result)
    partial = {"region": region, "vulnerability": vulnerability_result, "accessibility": accessibility_result, "optimization": optimization_result}
    client = AlanPolicyClient()
    policy_result = client.recommend_policy(partial)
    if client.last_warning:
        warnings.append(client.last_warning)
    return {"status": "success", "analysis_mode": "mock" if used_mock else "real", "region": region, "vulnerability": vulnerability_result, "accessibility": accessibility_result, "optimization": optimization_result, "policy_recommendation": policy_result, "warnings": warnings}

