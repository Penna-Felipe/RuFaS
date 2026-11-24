"""Reference rations from the exact linear subset of NRC constraints."""

from collections.abc import Mapping
from math import isfinite

import pulp

from RUFAS.biophysical.animal.ration.linear_ration_optimizer import LinearRationOptimizer, LinearRationStatus
from RUFAS.biophysical.animal.ration.ration_optimizer import RationConfig
from RUFAS.data_structures.feed_storage_to_animal_connection import FeedComponentType

OBJECTIVES = ("minimum_cost", "maximum_forage", "maximum_concentrate", "target_dmi")
# Only used to lock a generation objective between lexicographic solves.
# This does not change the NRC model constraints or its validation tolerances.
OBJECTIVE_LOCK_SLACK = 1e-6


class ReferenceGenerationError(ValueError):
    def __init__(self, goal: str, objective_index: int, status: LinearRationStatus, message: str) -> None:
        super().__init__(f"{goal} reference, objective {objective_index}: {status.value} ({message})")
        self.status = status
        self.solver_calls = objective_index + 1


def build_basic_reference(
    config: RationConfig, goal: str, solver: pulp.LpSolver | None = None
) -> tuple[dict[int, float], dict[str, int | float]]:
    """Optimize only the exact basic constraints and break ties lexicographically."""
    optimizer = LinearRationOptimizer()
    problem, quantities = optimizer._build_problem(config)
    cost = problem.objective
    if goal == "minimum_cost":
        primary = cost
    elif goal in ("maximum_forage", "maximum_concentrate"):
        kind = FeedComponentType.FORAGE if goal == "maximum_forage" else FeedComponentType.CONC
        primary = -pulp.lpSum(quantities[feed.rufas_id] for feed in config.feeds_used if feed.feed_type is kind)
    elif goal == "target_dmi":
        above = pulp.LpVariable("dmi_above_target", lowBound=0)
        below = pulp.LpVariable("dmi_below_target", lowBound=0)
        problem += pulp.lpSum(quantities.values()) - config.initial_dry_matter_requirement == above - below
        primary = above + below
    else:
        raise ValueError(f"Unknown reference objective: {goal}")

    # Lexicographic hierarchy: requested objective, cost, then amounts in
    # ascending feed-ID order. Lock each optimized objective before the next.
    objectives = [primary]
    if goal != "minimum_cost":
        objectives.append(cost)
    objectives.extend(pulp.lpSum([quantities[feed_id]]) for feed_id in sorted(quantities))
    solver = solver if solver is not None else pulp.PULP_CBC_CMD(msg=False)
    optimum = 0.0
    for i, objective in enumerate(objectives):
        problem.setObjective(objective)
        result = optimizer._solve_problem(config, problem, quantities, solver)
        if result.status is not LinearRationStatus.OPTIMAL or result.quantities is None:
            raise ReferenceGenerationError(goal, i, result.status, result.message)
        value = float(pulp.value(objective))
        if i == 0:
            optimum = value
        if i < len(objectives) - 1:
            problem += objective <= value + OBJECTIVE_LOCK_SLACK, f"reference_objective_{i}"

    return result.quantities, {
        "primary_optimum": -optimum if goal.startswith("maximum_") else optimum,
        "lp_calls": len(objectives),
    }


def reference_issue(config: RationConfig, quantities: Mapping[int, float]) -> str | None:
    ids = {feed.rufas_id for feed in config.feeds_used}
    extra = set(quantities) - ids
    if extra:
        return f"Feed IDs outside the scenario: {sorted(extra)}."
    for feed, lower, upper in zip(config.feeds_used, config.feed_minimum_list, config.feed_maximum_list, strict=True):
        amount = quantities.get(feed.rufas_id, 0.0)
        if not isfinite(amount) or not max(lower, 0.0) <= amount <= upper:
            return f"Feed {feed.rufas_id} is outside its inclusion bounds."
    total = sum(quantities.values())
    if not isfinite(total) or total <= 0:
        return "Reference intake must be finite and positive."
    return None


def grid_key(quantities: Mapping[int, float], feed_ids: list[int]) -> tuple[int, ...]:
    """Identify diets by feed ID and the same six-decimal output precision."""
    return tuple(round(quantities.get(feed_id, 0.0) * 1_000_000) for feed_id in feed_ids)
