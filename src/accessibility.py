"""팀원의 시설 접근성 분석을 연결하기 위한 얇은 어댑터."""

from __future__ import annotations
from collections.abc import Callable


class AccessibilityModelUnavailable(RuntimeError):
    pass


def analyze_accessibility(region: str, provider: Callable[[str], dict] | None = None) -> dict:
    if provider is None:
        raise AccessibilityModelUnavailable("시설 접근성 실제 모델이 아직 연결되지 않았습니다.")
    result = provider(region)
    required = {"facility_score", "nearest_shelter_distance_m", "accessible_population", "underserved_population", "coverage_rate", "blind_spot", "existing_facilities"}
    missing = required - result.keys()
    if missing:
        raise ValueError(f"접근성 결과 필드 누락: {sorted(missing)}")
    return result

