from src.analysis.cluster_service import analyze_cluster_snapshot


def _records() -> list[dict]:
    records = []
    for group in range(3):
        for index in range(12):
            baseline = 10 + group * 25
            records.append(
                {
                    "dong_code": f"{group:02d}{index:08d}",
                    "district_name": "테스트구",
                    "dong_name": f"동{group}-{index}",
                    "features": {
                        "heat_exposure": baseline + index % 3,
                        "elderly_concentration": baseline / 2 + index % 4,
                        "green_deficit": baseline + 5 + index % 2,
                        "access_deficit": baseline + 2 + index % 3,
                        "future_heat_illness_risk": baseline + 1 + index % 4,
                        "response_facility_shortage": baseline + 3 + index % 2,
                    },
                }
            )
    return records


def test_cluster_snapshot_returns_frontend_contract() -> None:
    result = analyze_cluster_snapshot(_records())

    assert result["metadata"]["record_count"] == 36
    assert len(result["assignments"]) == 36
    assert len(result["clusters"]) >= 2
    assert result["assignments"][0]["global_installation_priority"] == 1
    assert len(result["global_feature_importance"]) == 6
