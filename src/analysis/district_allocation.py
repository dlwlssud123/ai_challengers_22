"""Transparent district-level facility allocation for the citywide dashboard."""

from __future__ import annotations

from typing import Any

import pandas as pd


def allocate_facilities_by_priority(
    district_rows: list[dict[str, Any]],
    *,
    budget: int,
    unit_cost: int,
    max_facilities: int,
) -> pd.DataFrame:
    """Allocate affordable units round-robin by district priority."""

    columns = ["region_name", "priority_score", "existing_shelters", "new_facilities", "cost"]
    if unit_cost <= 0 or budget <= 0 or max_facilities <= 0 or not district_rows:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(district_rows).copy()
    frame["priority_score"] = pd.to_numeric(frame["priority_score"], errors="coerce").fillna(0)
    frame["existing_shelters"] = pd.to_numeric(
        frame.get("existing_shelters", 0), errors="coerce"
    ).fillna(0).astype(int)
    frame = frame.sort_values(["priority_score", "region_name"], ascending=[False, True])
    affordable = min(int(budget // unit_cost), int(max_facilities))
    allocations = {str(name): 0 for name in frame["region_name"]}
    names = list(allocations)
    for index in range(affordable):
        allocations[names[index % len(names)]] += 1
    frame["new_facilities"] = frame["region_name"].astype(str).map(allocations).astype(int)
    frame = frame[frame["new_facilities"] > 0].copy()
    frame["cost"] = frame["new_facilities"] * int(unit_cost)
    return frame[columns].reset_index(drop=True)
