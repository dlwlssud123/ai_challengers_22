"""Maximum-coverage shelter selection with PuLP and greedy fallback."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import geopandas as gpd
import numpy as np
import pandas as pd

from src.schemas import OptimizationSummary


LOGGER = logging.getLogger(__name__)


def candidate_coverage_sets(
    candidates: gpd.GeoDataFrame,
    blindspots: gpd.GeoDataFrame,
    *,
    radius_m: float,
    analysis_crs: str = "EPSG:5179",
) -> dict[str, set[str]]:
    """Return candidate-to-cell coverage using projected representative points."""

    if candidates.crs is None or blindspots.crs is None:
        raise ValueError("최적화 거리 계산에는 후보지와 사각지대 CRS가 필요합니다.")
    metric_candidates = candidates.to_crs(analysis_crs)
    metric_blindspots = blindspots.to_crs(analysis_crs)
    blind_points = metric_blindspots.geometry.representative_point()
    cell_ids = metric_blindspots["cell_id"].astype(str)
    coverage: dict[str, set[str]] = {}
    for row in metric_candidates.itertuples():
        distances = blind_points.distance(row.geometry)
        coverage[str(row.candidate_id)] = set(cell_ids.loc[distances <= radius_m])
    return coverage


def remove_existing_overlaps(
    candidates: gpd.GeoDataFrame,
    existing_shelters: gpd.GeoDataFrame | None,
    *,
    minimum_distance_m: float = 100,
    analysis_crs: str = "EPSG:5179",
) -> gpd.GeoDataFrame:
    """Drop candidate points that effectively duplicate an existing shelter."""

    if existing_shelters is None or existing_shelters.empty or candidates.empty:
        return candidates.copy()
    if candidates.crs is None or existing_shelters.crs is None:
        raise ValueError("중복 후보 검사에는 CRS가 필요합니다.")
    metric_candidates = candidates.to_crs(analysis_crs)
    shelter_union = existing_shelters.to_crs(analysis_crs).geometry.union_all()
    keep = metric_candidates.geometry.distance(shelter_union) >= minimum_distance_m
    return candidates.loc[keep.to_numpy()].copy()


def _population_lookup(blindspots: gpd.GeoDataFrame) -> dict[str, float]:
    return {
        str(row.cell_id): max(float(row.estimated_elderly), 0.0)
        for row in blindspots.itertuples()
    }


def _priority_lookup(blindspots: gpd.GeoDataFrame) -> dict[str, float]:
    return {
        str(row.cell_id): float(np.clip(row.priority_score, 0, 100))
        for row in blindspots.itertuples()
    }


def _summary(
    selected_ids: list[str],
    coverage: Mapping[str, set[str]],
    populations: Mapping[str, float],
    costs: Mapping[str, float],
    *,
    solver: str,
    diagnostics: dict[str, object] | None = None,
) -> OptimizationSummary:
    covered = set().union(*(coverage[candidate_id] for candidate_id in selected_ids)) if selected_ids else set()
    return OptimizationSummary(
        selected_candidate_ids=selected_ids,
        newly_covered_elderly=sum(populations[cell_id] for cell_id in covered),
        total_cost=sum(costs[candidate_id] for candidate_id in selected_ids),
        solver=solver,
        covered_cell_ids=sorted(covered),
        diagnostics=diagnostics or {},
    )


def optimize_greedy(
    candidates: gpd.GeoDataFrame,
    blindspots: gpd.GeoDataFrame,
    coverage: Mapping[str, set[str]],
    *,
    budget: float,
    max_facilities: int | None = None,
) -> OptimizationSummary:
    """Budget-aware greedy maximum coverage fallback with unique population counts."""

    costs = {
        str(row.candidate_id): float(row.cost)
        for row in candidates.itertuples()
        if np.isfinite(row.cost) and float(row.cost) > 0
    }
    populations = _population_lookup(blindspots)
    priorities = _priority_lookup(blindspots)
    selected: list[str] = []
    already_covered: set[str] = set()
    remaining_budget = float(budget)
    while True:
        if max_facilities is not None and len(selected) >= max_facilities:
            break
        best_id: str | None = None
        best_tuple = (0.0, 0.0)
        for candidate_id, cells in coverage.items():
            cost = costs.get(candidate_id)
            if candidate_id in selected or cost is None or cost > remaining_budget:
                continue
            new_cells = cells - already_covered
            benefit = sum(populations[cell_id] for cell_id in new_cells)
            tie_break = sum(populations[cell_id] * priorities[cell_id] for cell_id in new_cells) / 10_000
            rank = ((benefit + tie_break) / cost, benefit + tie_break)
            if rank > best_tuple:
                best_tuple = rank
                best_id = candidate_id
        if best_id is None or best_tuple[1] <= 0:
            break
        selected.append(best_id)
        already_covered.update(coverage[best_id])
        remaining_budget -= costs[best_id]
    return _summary(
        selected,
        coverage,
        populations,
        costs,
        solver="greedy-fallback",
        diagnostics={"remaining_budget": remaining_budget},
    )


def optimize_pulp(
    candidates: gpd.GeoDataFrame,
    blindspots: gpd.GeoDataFrame,
    coverage: Mapping[str, set[str]],
    *,
    budget: float,
    max_facilities: int | None = None,
) -> OptimizationSummary:
    """Solve a binary maximum coverage location problem with PuLP/CBC."""

    import pulp

    valid = candidates.copy()
    valid["cost"] = pd.to_numeric(valid["cost"], errors="coerce")
    valid = valid[(valid["cost"] > 0) & (valid["cost"] <= budget)]
    candidate_ids = [str(value) for value in valid["candidate_id"] if coverage.get(str(value))]
    costs = valid.set_index(valid["candidate_id"].astype(str))["cost"].astype(float).to_dict()
    populations = _population_lookup(blindspots)
    priorities = _priority_lookup(blindspots)
    if not candidate_ids or not populations:
        return _summary([], coverage, populations, costs, solver="pulp-cbc")
    problem = pulp.LpProblem("HeatwaveShelterMaximumCoverage", pulp.LpMaximize)
    x = {candidate_id: pulp.LpVariable(f"x_{idx}", cat="Binary") for idx, candidate_id in enumerate(candidate_ids)}
    y = {cell_id: pulp.LpVariable(f"y_{idx}", cat="Binary") for idx, cell_id in enumerate(populations)}
    problem += pulp.lpSum(
        populations[cell_id] * (1.0 + priorities[cell_id] / 100_000.0) * y[cell_id]
        for cell_id in populations
    )
    problem += pulp.lpSum(costs[candidate_id] * x[candidate_id] for candidate_id in candidate_ids) <= budget
    if max_facilities is not None:
        problem += pulp.lpSum(x[candidate_id] for candidate_id in candidate_ids) <= max_facilities
    for cell_id in populations:
        covering = [x[candidate_id] for candidate_id in candidate_ids if cell_id in coverage[candidate_id]]
        if covering:
            problem += y[cell_id] <= pulp.lpSum(covering)
        else:
            problem += y[cell_id] == 0
    status = problem.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=20))
    status_name = pulp.LpStatus.get(status, str(status))
    if status_name not in {"Optimal", "Integer Feasible"}:
        raise RuntimeError(f"PuLP solver status: {status_name}")
    selected = [candidate_id for candidate_id in candidate_ids if pulp.value(x[candidate_id]) > 0.5]
    return _summary(
        selected,
        coverage,
        populations,
        costs,
        solver="pulp-cbc",
        diagnostics={"status": status_name},
    )


def optimize_candidates(
    candidates: gpd.GeoDataFrame,
    blindspots: gpd.GeoDataFrame,
    *,
    budget: float,
    radius_m: float,
    existing_shelters: gpd.GeoDataFrame | None = None,
    prefer_pulp: bool = True,
    max_facilities: int | None = None,
) -> OptimizationSummary:
    """Common interface for PuLP and deterministic greedy fallback."""

    if budget < 0:
        raise ValueError("총예산은 0 이상이어야 합니다.")
    if max_facilities is not None and max_facilities < 0:
        raise ValueError("설치 가능 시설 수는 0 이상이어야 합니다.")
    usable = remove_existing_overlaps(candidates, existing_shelters)
    coverage = candidate_coverage_sets(usable, blindspots, radius_m=radius_m)
    if prefer_pulp:
        try:
            return optimize_pulp(
                usable,
                blindspots,
                coverage,
                budget=budget,
                max_facilities=max_facilities,
            )
        except (ImportError, RuntimeError) as exc:
            LOGGER.warning("PuLP 최적화 실패, greedy fallback 사용: %s", exc)
    return optimize_greedy(
        usable,
        blindspots,
        coverage,
        budget=budget,
        max_facilities=max_facilities,
    )


def selected_candidate_table(
    candidates: gpd.GeoDataFrame,
    blindspots: gpd.GeoDataFrame,
    summary: OptimizationSummary,
    *,
    radius_m: float,
) -> gpd.GeoDataFrame:
    """Attach non-overlapping incremental benefits in selected order."""

    selected = candidates[
        candidates["candidate_id"].astype(str).isin(summary.selected_candidate_ids)
    ].copy()
    order = {candidate_id: idx for idx, candidate_id in enumerate(summary.selected_candidate_ids)}
    if selected.empty:
        selected["incremental_covered_elderly"] = []
        return selected
    selected["_order"] = selected["candidate_id"].astype(str).map(order)
    selected = selected.sort_values("_order")
    coverage = candidate_coverage_sets(selected, blindspots, radius_m=radius_m)
    populations = _population_lookup(blindspots)
    seen: set[str] = set()
    increments: list[float] = []
    for candidate_id in selected["candidate_id"].astype(str):
        new_cells = coverage[candidate_id] - seen
        increments.append(sum(populations[cell_id] for cell_id in new_cells))
        seen.update(coverage[candidate_id])
    selected["incremental_covered_elderly"] = increments
    return selected.drop(columns="_order")

