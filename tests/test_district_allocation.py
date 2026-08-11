from __future__ import annotations

from src.analysis.district_allocation import allocate_facilities_by_priority


def test_allocation_respects_budget_limit_and_priority_order():
    rows = [
        {"region_name": "고위험구", "priority_score": 90, "existing_shelters": 10},
        {"region_name": "중위험구", "priority_score": 60, "existing_shelters": 20},
    ]

    result = allocate_facilities_by_priority(rows, budget=25_000_000, unit_cost=10_000_000, max_facilities=5)

    assert result["new_facilities"].sum() == 2
    assert result["cost"].sum() == 20_000_000
    assert result.iloc[0]["region_name"] == "고위험구"
