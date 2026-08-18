from __future__ import annotations

from backend.services.dashboard import build_allocation, build_overview
from backend.services.ml_prediction import build_ml_scenario
from backend.services.cluster_analysis import build_cluster_analysis, build_cluster_snapshot


def test_overview_contains_citywide_boundaries_and_shelters():
    payload = build_overview("accessibility")
    assert payload["kpis"]["dong_count"] == 150
    assert len(payload["boundaries"]["features"]) == 150
    assert len(payload["districts"]) == 150
    assert len(payload["shelters"]) > 0


def test_allocation_returns_rows():
    payload = build_allocation({"budget": 50_000_000, "unit_cost": 10_000_000, "max_facilities": 5})
    assert "rows" in payload


def test_overview_accessibility_uses_population_weighted_grid_score():
    payload = build_overview("accessibility")
    first = payload["boundaries"]["features"][0]["properties"]
    assert first["grid_accessibility_index_exp_d_300"] == first["grid_population_weighted_accessibility_index"]
    assert first["grid_accessibility_lack_score"] == first["grid_population_weighted_accessibility_lack_score"]


def test_overview_future_risk_merges_prediction_fields():
    payload = build_overview("future-risk")
    assert payload["kpis"]["future_expected_patients"] > 0
    first = payload["boundaries"]["features"][0]["properties"]
    assert "future_heat_risk_score" in first
    assert "facility_shortage_score" in first


def test_ml_scenario_returns_facility_intervention_estimate():
    overview = build_overview("future-risk")
    district = max(overview["districts"], key=lambda row: row.get("future_expected_patients") or 0)
    payload = build_ml_scenario({
        "sgis_adm_cd": district["sgis_adm_cd"],
        "facility_counts": {"cooling_support": 1, "shade": 1, "cooling_fog": 0, "smart_shelter": 1},
    })
    assert payload["status"] == "success"
    assert payload["total_cost"] == 52_000_000
    assert payload["scenario"]["expected_patients_after"] <= payload["baseline"]["expected_patients"]
    assert payload["model"]["name"] == "GradientBoostingRegressor"


def test_cluster_analysis_returns_dbscan_shap_contract():
    snapshot = build_cluster_snapshot()
    assert len(snapshot) == 150
    assert set(snapshot[0]["features"]) == {
        "heat_exposure",
        "elderly_concentration",
        "green_deficit",
        "access_deficit",
        "future_heat_illness_risk",
        "response_facility_shortage",
    }
    result = build_cluster_analysis()
    assert result["metadata"]["record_count"] == 150
    assert result["metadata"]["dbscan"]["cluster_count"] >= 2
    assert result["global_feature_importance"]
    assert result["clusters"]
    assert result["assignments"]
    assert result["assignments"][0]["main_causes"]
