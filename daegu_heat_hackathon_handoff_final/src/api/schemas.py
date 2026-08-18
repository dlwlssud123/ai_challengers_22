"""Request/response contracts for the clustering API."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FeatureVector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heat_exposure: float
    elderly_concentration: float
    green_deficit: float
    access_deficit: float
    future_heat_illness_risk: float
    response_facility_shortage: float

    @field_validator("*")
    @classmethod
    def finite_number(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be a finite number")
        return value


class AdministrativeDongInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dong_code: str = Field(min_length=1, max_length=32)
    district_name: str = Field(min_length=1, max_length=64)
    dong_name: str = Field(min_length=1, max_length=64)
    features: FeatureVector


class ClusterAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[AdministrativeDongInput] = Field(min_length=12, max_length=500)


class ClusterAnalysisResponse(BaseModel):
    """Deliberately open inside sections: chart fields can evolve without API breakage."""

    metadata: dict[str, Any]
    global_feature_importance: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    assignments: list[dict[str, Any]]
