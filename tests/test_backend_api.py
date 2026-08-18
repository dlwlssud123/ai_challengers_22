from __future__ import annotations

from backend.services.dashboard import build_allocation, build_overview


def test_overview_contains_citywide_boundaries_and_shelters():
    payload = build_overview("accessibility")
    assert payload["kpis"]["dong_count"] == 150
    assert len(payload["boundaries"]["features"]) == 150
    assert len(payload["districts"]) == 150
    assert len(payload["shelters"]) > 0


def test_allocation_returns_rows():
    payload = build_allocation({"budget": 50_000_000, "unit_cost": 10_000_000, "max_facilities": 5})
    assert "rows" in payload
