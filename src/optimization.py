"""팀원의 입지 최적화 모델을 연결하기 위한 얇은 어댑터."""

from __future__ import annotations
from collections.abc import Callable


class OptimizationModelUnavailable(RuntimeError):
    pass


def recommend_locations(region: str, budget: int, max_facilities: int, vulnerability: dict, accessibility: dict, provider: Callable[..., dict] | None = None) -> dict:
    if provider is None:
        raise OptimizationModelUnavailable("입지 최적화 실제 모델이 아직 연결되지 않았습니다.")
    result = provider(region=region, budget=budget, max_facilities=max_facilities, vulnerability=vulnerability, accessibility=accessibility)
    required = {"budget", "max_facilities", "recommended_locations", "before", "after"}
    missing = required - result.keys()
    if missing:
        raise ValueError(f"입지 추천 결과 필드 누락: {sorted(missing)}")
    return result

