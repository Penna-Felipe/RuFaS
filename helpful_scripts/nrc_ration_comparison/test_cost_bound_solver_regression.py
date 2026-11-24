"""Compare solver primals and dual certificates for the archived basic LPs."""

import math

import pytest

pulp = pytest.importorskip("pulp")
pytest.importorskip("highspy")

from helpful_scripts.nrc_ration_comparison.cli_three_day import BASE  # noqa: E402
from helpful_scripts.nrc_ration_comparison.reference_solver_pilot import diagnostic_bound  # noqa: E402
from helpful_scripts.nrc_ration_comparison.solver_benchmark import scenario_inputs  # noqa: E402
from RUFAS.biophysical.animal.ration.linear_cost_bound import primary_lower_bound  # noqa: E402
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import LinearRationOptimizer  # noqa: E402
from RUFAS.biophysical.animal.ration.ration_manager import RationManager  # noqa: E402


def test_reference_cost_bound_primals_duals_and_stationarity(monkeypatch) -> None:
    audit = BASE / "isolated_audit.json"
    for artifact in (audit, BASE / "inputs/feed.json"):
        if not artifact.is_file():
            pytest.skip(f"Archived formulation inputs unavailable: {artifact}")
    monkeypatch.setattr(RationManager, "intake_options", {})
    cbc = pulp.PULP_CBC_CMD(msg=False)
    highs = pulp.HiGHS(msg=False, threads=1)
    assert highs.available() and cbc.available()
    count = 0
    for name, config, _, _ in scenario_inputs(audit, generate_historical_references=False):
        count += 1
        diagnostic = diagnostic_bound(config, cbc, highs)
        assert diagnostic["highs"]["primal"] == pytest.approx(diagnostic["cbc"]["primal"], abs=1e-7, rel=0), name
        for key, solver in (("cbc", cbc), ("highs", highs)):
            problem, quantities = LinearRationOptimizer._build_problem(config)
            assert problem.solve(solver) == pulp.LpStatusOptimal
            assert problem.sol_status == pulp.LpSolutionOptimal
            rows = tuple(problem.constraints.values())
            for row in rows:
                assert math.isfinite(row.pi) and row.sense * row.pi >= 0, (name, key, row.name)
                assert abs(row.pi * row.value()) <= 1e-7, (name, key, row.name)
            for feed_id, variable in quantities.items():
                reduced_cost = problem.objective.get(variable, 0) - sum(row.pi * row.get(variable, 0) for row in rows)
                assert math.isfinite(variable.dj)
                assert reduced_cost == pytest.approx(variable.dj, abs=1e-7, rel=0), (name, key, feed_id)
                distance = (
                    variable.value() - variable.lowBound if reduced_cost >= 0 else variable.upBound - variable.value()
                )
                assert abs(reduced_cost * distance) <= 1e-6, (name, key, feed_id)
            result = primary_lower_bound(config, solver)
            reference = diagnostic[key]
            assert result["status"] == "Optimal"
            assert result["strict_lower_bound"] == min(reference["primal"], reference["strict_certificate"])
            assert result["lower_bound"] == min(reference["primal"], reference["tolerant_certificate"])
            assert result["lower_bound"] <= diagnostic["tolerant_primal_highs"] + 1e-12
        assert diagnostic["highs"]["tolerant_certificate"] == pytest.approx(
            diagnostic["tolerant_primal_highs"], abs=1e-12, rel=0
        )
    assert count == 27


def test_highs_dual_signs_for_active_lower_and_upper_rows() -> None:
    problem = pulp.LpProblem("mixed_inequalities", pulp.LpMinimize)
    x, y = (pulp.LpVariable(name, lowBound=0) for name in ("x", "y"))
    problem += x - y
    problem += x >= 2, "lower"
    problem += y <= 3, "upper"
    assert problem.solve(pulp.HiGHS(msg=False, threads=1)) == pulp.LpStatusOptimal
    assert problem.constraints["lower"].pi == pytest.approx(1)
    assert problem.constraints["upper"].pi == pytest.approx(-1)
    assert x.dj == y.dj == 0
