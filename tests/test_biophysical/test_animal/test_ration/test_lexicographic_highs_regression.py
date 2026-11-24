"""Exact archived model for the sixth-stage target DMI regression."""

import json
from fractions import Fraction
from pathlib import Path

import pytest

pulp = pytest.importorskip("pulp")
pytest.importorskip("highspy")


def test_target_dmi_sixth_stage_is_infeasible_with_the_frozen_locks() -> None:
    fixture = Path(__file__).with_name("lexicographic_stage_six.json")
    model = json.loads(fixture.read_text(encoding="utf-8"))
    problem = pulp.LpProblem("target_dmi_sixth_stage", pulp.LpMinimize)
    variables = {key: pulp.LpVariable(key, *bounds) for key, bounds in model["bounds"].items()}
    problem += pulp.lpSum(coef * variables[key] for key, coef in model["objective"].items())
    for name, row in model["rows"].items():
        expression = pulp.lpSum(coef * variables[key] for key, coef in row["coefficients"].items())
        problem += pulp.LpConstraint(expression, sense=row["sense"], rhs=row["rhs"], name=name)

    assert model["objective_stage"] == 6
    assert problem.solve(pulp.HiGHS(msg=False, threads=1)) == pulp.LpStatusInfeasible

    # The first lock bounds each nonnegative auxiliary by their bounded sum.
    first_lock = model["rows"]["reference_objective_0"]
    assert first_lock["sense"] == pulp.LpConstraintLE
    assert first_lock["coefficients"] == {"dmi_above_target": 1, "dmi_below_target": 1}
    assert all(model["bounds"][key][0] == 0 for key in first_lock["coefficients"])
    combined = dict.fromkeys(variables, Fraction(0))
    rhs = Fraction(0)
    # These weights come from a diagnostic LP that minimizes row relaxations.
    # Check them exactly so the infeasibility claim is independent of solver tolerances.
    for name, dual in model["infeasibility_certificate"].items():
        row = model["rows"][name]
        weight = Fraction(dual)
        assert row["sense"] == 0 or weight * row["sense"] >= 0
        rhs += weight * Fraction(row["rhs"])
        for key, coefficient in row["coefficients"].items():
            combined[key] += weight * Fraction(coefficient)

    maximum_on_box = Fraction(0)
    for key, coef in combined.items():
        lower, upper = model["bounds"][key]
        if upper is None:
            assert key in first_lock["coefficients"]
            upper = first_lock["rhs"]
        maximum_on_box += coef * Fraction(upper if coef >= 0 else lower)
    # Every feasible vector would have combined lhs >= rhs, including exact floating-point inputs.
    assert rhs - maximum_on_box > Fraction(2, 10**9)

    previous = model["preceding_vector"]
    phosphorus = model["rows"]["minimum_phosphorus"]
    shortfall = phosphorus["rhs"] - sum(coef * previous[key] for key, coef in phosphorus["coefficients"].items())
    assert shortfall == pytest.approx(4.637129080720115e-8, abs=1e-13)
