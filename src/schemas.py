"""Pydantic schemas shared by the optimizer and policy-brief adapter."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PolicyBrief(BaseModel):
    """Validated, presentation-ready policy briefing."""

    model_config = ConfigDict(extra="forbid")

    executive_summary: str
    priority_areas: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    expected_spatial_effect: str
    limitations: list[str] = Field(default_factory=list)


class OptimizationSummary(BaseModel):
    """Serializable summary returned by all optimization backends."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    selected_candidate_ids: list[str]
    newly_covered_elderly: float = 0.0
    total_cost: float = 0.0
    solver: str
    covered_cell_ids: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


