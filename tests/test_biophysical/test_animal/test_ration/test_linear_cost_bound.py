"""Degenerate and exceptional cases for conservative NRC cost bounds."""

import pytest

pulp = pytest.importorskip("pulp")

from RUFAS.biophysical.animal.ration.linear_cost_bound import (  # noqa: E402
    ROWS,
    dual_bound,
    meets_target,
    primary_lower_bound,
    relative_gap,
)
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import LinearRationOptimizer  # noqa: E402


def basic_problem(cost, demand, *, upper=4):
    problem = pulp.LpProblem("basic_cost", pulp.LpMinimize)
    first = pulp.LpVariable("first", lowBound=0, upBound=upper)
    second = pulp.LpVariable("second", lowBound=0, upBound=upper)
    problem += cost[0] * first + cost[1] * second
    problem += first + second >= demand, "minimum_dmi"
    problem += first + second <= 2 * upper, "maximum_dmi"
    for name in ROWS.keys() - problem.constraints.keys():
        problem += first + second >= 0, name
    return problem, {1: first, 2: second}


@pytest.mark.parametrize("solver_name", ["cbc", "highs"])
@pytest.mark.parametrize(
    ("cost", "demand", "primal"),
    [
        ((1, 1), 3, 3),  # Alternative optima.
        ((0, 0), 3, 0),  # PuLP's dummy column.
        ((1, 2), 5, 6),  # The cheap ingredient's upper bound is active.
        ((1, 2), 9, None),  # Infeasible.
    ],
)
def test_synthetic_cost_bounds(monkeypatch, solver_name, cost, demand, primal):
    if solver_name == "highs":
        pytest.importorskip("highspy")
        solver = pulp.HiGHS(msg=False, threads=1)
    else:
        solver = pulp.PULP_CBC_CMD(msg=False)
    monkeypatch.setattr(LinearRationOptimizer, "_build_problem", staticmethod(lambda _: basic_problem(cost, demand)))
    result = primary_lower_bound(None, solver)
    if primal is None:
        assert result["status"] == "Infeasible" and result["lower_bound"] is None
        assert not meets_target(0, result["lower_bound"], 0.05)
        return
    assert result["status"] == "Optimal"
    assert result["primary_optimum_cbc"] == pytest.approx(primal)
    assert result["strict_lower_bound"] == pytest.approx(primal)
    assert result["lower_bound"] <= primal
    assert result["lower_bound"] == pytest.approx(primal, abs=1e-6)
    assert meets_target(primal, result["lower_bound"], 0.05)
    if primal == 0:
        assert relative_gap(0, result["lower_bound"]) == (0, "zero_cost_and_bound")


@pytest.mark.parametrize("bad_dual", [None, float("nan"), float("inf"), -1.0, "invalid"])
def test_missing_or_invalid_multipliers_give_box_certificate(monkeypatch, bad_dual):
    problem, variables = basic_problem((1, 2), 5)
    solver = pulp.PULP_CBC_CMD(msg=False)
    actual_solve = solver.actualSolve

    def solve(lp, **kwargs):
        status = actual_solve(lp, **kwargs)
        for row in lp.constraints.values():
            row.pi = -row.sense if bad_dual == -1.0 else bad_dual
        return status

    monkeypatch.setattr(solver, "actualSolve", solve)
    monkeypatch.setattr(LinearRationOptimizer, "_build_problem", staticmethod(lambda _: (problem, variables)))
    result = primary_lower_bound(None, solver)
    assert result["primary_optimum_cbc"] == 6
    assert result["lower_bound"] == result["strict_lower_bound"] == 0
    assert not meets_target(6, result["lower_bound"], 0.05)


def test_nonstationary_multiplier_uses_finite_ingredient_box():
    problem, variables = basic_problem((1, 2), 5)
    problem.constraints["minimum_dmi"].pi = 3
    # y*b = 15 and the residual coefficients (-2, -1) attain -12 at the upper bounds.
    assert dual_bound(problem, list(variables.values()), tolerant=False) == 3
