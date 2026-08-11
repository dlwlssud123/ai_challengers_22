"""Alan LLM 연결 경계를 담당하는 교체 가능한 정책 추천 클라이언트."""

from __future__ import annotations
import json
import os
from typing import Any
import requests
from .mock_data import mock_policy


class AlanClientError(RuntimeError):
    """사용자에게 안전하게 표시할 수 있는 Alan 연결 오류."""


def _read_streamlit_secret(name: str) -> str | None:
    try:
        import streamlit as st
        value = st.secrets.get(name)
        return str(value) if value else None
    except Exception:
        return None


def validate_policy_response(payload: Any, allowed_locations: set[str]) -> dict:
    if not isinstance(payload, dict):
        raise AlanClientError("Alan 응답이 JSON 객체가 아닙니다.")
    required = {"summary", "priority_level", "recommended_policies", "limitations"}
    missing = required - payload.keys()
    if missing:
        raise AlanClientError(f"Alan 응답 필드가 누락되었습니다: {sorted(missing)}")
    if payload["priority_level"] not in {"긴급", "높음", "보통", "낮음"}:
        raise AlanClientError("Alan 응답의 우선순위 값이 허용 범위를 벗어났습니다.")
    policies = payload["recommended_policies"]
    if not isinstance(policies, list) or len(policies) > 3:
        raise AlanClientError("정책 추천은 JSON 배열이며 최대 3개여야 합니다.")
    for policy in policies:
        needed = {"policy_name", "target_location", "reason", "action_plan", "expected_effect"}
        if not isinstance(policy, dict) or needed - policy.keys():
            raise AlanClientError("정책 추천 항목의 필드가 올바르지 않습니다.")
        if policy["target_location"] not in allowed_locations:
            raise AlanClientError("입지 분석에 없는 후보지가 정책 추천에 포함되었습니다.")
        if not isinstance(policy["action_plan"], list):
            raise AlanClientError("action_plan은 JSON 배열이어야 합니다.")
    if not isinstance(payload["limitations"], list):
        raise AlanClientError("limitations는 JSON 배열이어야 합니다.")
    return payload


class AlanPolicyClient:
    def __init__(self, api_key: str | None = None, endpoint: str | None = None, timeout: float = 10.0) -> None:
        self.api_key = api_key or os.getenv("ALAN_API_KEY") or _read_streamlit_secret("ALAN_API_KEY")
        self.endpoint = endpoint or os.getenv("ALAN_API_URL") or _read_streamlit_secret("ALAN_API_URL")
        self.timeout = timeout
        self.last_raw_response: Any = None
        self.last_warning: str | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.endpoint)

    def build_prompt(self, analysis_result: dict) -> str:
        vulnerability, accessibility, optimization = analysis_result["vulnerability"], analysis_result["accessibility"], analysis_result["optimization"]
        facts = {
            "region": analysis_result["region"], "vulnerability_score": vulnerability["vulnerability_score"],
            "vulnerability_grade": vulnerability["vulnerability_grade"], "main_causes": vulnerability["main_causes"],
            "vulnerable_population": vulnerability["vulnerable_population"], "facility_score": accessibility["facility_score"],
            "nearest_shelter_distance_m": accessibility["nearest_shelter_distance_m"], "underserved_population": accessibility["underserved_population"],
            "budget": optimization["budget"], "max_facilities": optimization["max_facilities"],
            "recommended_locations": optimization["recommended_locations"], "before": optimization["before"], "after": optimization["after"],
        }
        schema = {"summary": "지역 상황에 대한 2~3문장 요약", "priority_level": "긴급 | 높음 | 보통 | 낮음", "recommended_policies": [{"policy_name": "정책명", "target_location": "입력으로 제공된 후보지", "reason": "추천 근거", "action_plan": ["실행 방안 1", "실행 방안 2"], "expected_effect": "입력 데이터로 확인 가능한 기대효과"}], "limitations": ["분석 결과를 사용할 때의 한계"]}
        return (
            "당신은 지방정부 폭염 대응 정책 보조자입니다. 아래 입력 사실만 사용해 한국어로 답하세요.\n"
            "규칙:\n1. 입력에 없는 위치, 비용, 통계값을 만들지 마세요.\n2. target_location은 recommended_locations에 포함된 이름만 사용하세요.\n"
            "3. 의료 효과나 온열질환 감소율을 단정하지 마세요.\n4. 기대효과는 접근 가능 인구, 접근거리, 사각지대 변화로 설명하세요.\n"
            "5. 정책은 최대 3개로 제한하고 JSON 외 문장을 출력하지 마세요.\n"
            f"입력 사실:\n{json.dumps(facts, ensure_ascii=False)}\n출력 JSON 스키마:\n{json.dumps(schema, ensure_ascii=False)}"
        )

    def _build_request_payload(self, prompt: str) -> dict:
        # TODO: Alan 공식 API 문서에서 요청 필드가 확인되면 이 메서드만 구현한다.
        raise AlanClientError("Alan 공식 요청 명세가 확인되지 않아 Mock 정책을 사용합니다.")

    def _post_json(self, payload: dict) -> Any:
        if not self.is_configured:
            raise AlanClientError("Alan API 키 또는 공식 엔드포인트가 설정되지 않았습니다.")
        try:
            response = requests.post(self.endpoint, json=payload, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=self.timeout)
            response.raise_for_status()
        except requests.Timeout as exc:
            raise AlanClientError("Alan API 응답 시간이 초과되었습니다.") from exc
        except requests.RequestException as exc:
            raise AlanClientError("Alan API 호출에 실패했습니다.") from exc
        try:
            return response.json()
        except ValueError as exc:
            raise AlanClientError("Alan API 응답을 JSON으로 해석할 수 없습니다.") from exc

    def recommend_policy(self, analysis_result: dict) -> dict:
        allowed = {item["name"] for item in analysis_result["optimization"]["recommended_locations"]}
        try:
            if not self.is_configured:
                raise AlanClientError("Alan API 설정이 없어 Mock 정책을 사용합니다.")
            prompt = self.build_prompt(analysis_result)
            self.last_raw_response = self._post_json(self._build_request_payload(prompt))
            return validate_policy_response(self.last_raw_response, allowed)
        except AlanClientError as exc:
            self.last_warning = str(exc)
            return validate_policy_response(mock_policy(analysis_result), allowed)

