import logging
import pytest
from src.alan_client import AlanClientError, AlanPolicyClient, validate_policy_response
from src.integration import run_policy_analysis
from src.mock_data import available_regions


REGION = available_regions()[0]


def test_mock_mode_runs_without_api_key(monkeypatch):
    monkeypatch.delenv("ALAN_API_KEY", raising=False)
    monkeypatch.delenv("ALAN_API_URL", raising=False)
    result = run_policy_analysis(REGION, 50_000_000, 2, use_mock=True)
    assert result["status"] == "success" and result["analysis_mode"] == "mock"


def test_module_failure_falls_back_without_stopping(monkeypatch):
    def fail(_region):
        raise RuntimeError("test failure")
    monkeypatch.setattr("src.integration.vulnerability.analyze_vulnerability", fail)
    result = run_policy_analysis(REGION, 50_000_000, 2, use_mock=False)
    assert result["status"] == "success"
    assert any("취약도" in warning for warning in result["warnings"])


@pytest.mark.parametrize("budget,max_facilities", [(-1, 1), (1_000_000, -1), (1.5, 1), (1_000_000, True)])
def test_input_validation(budget, max_facilities):
    with pytest.raises(ValueError):
        run_policy_analysis(REGION, budget, max_facilities, use_mock=True)


def test_policy_json_schema_and_candidate_constraint():
    valid = {"summary": "요약", "priority_level": "높음", "recommended_policies": [{"policy_name": "쉼터 설치", "target_location": "후보 A", "reason": "근거", "action_plan": ["확인"], "expected_effect": "접근성 개선"}], "limitations": ["한계"]}
    assert validate_policy_response(valid, {"후보 A"}) == valid
    valid["recommended_policies"][0]["target_location"] = "입력에 없는 곳"
    with pytest.raises(AlanClientError):
        validate_policy_response(valid, {"후보 A"})


def test_budget_and_facility_limits_are_respected():
    result = run_policy_analysis(REGION, 35_000_000, 1, use_mock=True)
    opt = result["optimization"]
    assert opt["total_estimated_cost"] <= 35_000_000
    assert len(opt["recommended_locations"]) <= 1


def test_api_key_is_not_exposed(caplog):
    secret = "super-secret-api-key"
    client = AlanPolicyClient(api_key=secret, endpoint="https://example.invalid")
    analysis = run_policy_analysis(REGION, 20_000_000, 1, use_mock=True)
    with caplog.at_level(logging.DEBUG):
        client.recommend_policy(analysis)
    assert secret not in caplog.text and secret not in str(client.last_warning)

