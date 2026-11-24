"""Conservative cost floor from the primary NRC basic LP."""

from fractions import Fraction
from math import inf, isfinite, nextafter
from numbers import Real

import pulp

from RUFAS.biophysical.animal.ration.linear_ration_optimizer import (
    _INGREDIENT_BOUND_TOLERANCE,
    _NRC_TOLERANCES,
    LinearRationOptimizer,
)
from RUFAS.biophysical.animal.ration.ration_optimizer import RationConfig

ROWS = {
    "minimum_dmi": ("DMI_constraint_lower", False),
    "maximum_dmi": ("DMI_constraint_upper", False),
    "minimum_calcium": ("calcium_constraint", False),
    "minimum_phosphorus": ("phosphorus_constraint", False),
    "minimum_ndf": ("NDF_constraint_lower", True),
    "maximum_ndf": ("NDF_constraint_upper", True),
    "minimum_forage_ndf": ("forage_NDF_constraint", True),
    "maximum_fat": ("fat_constraint", True),
}


def dual_bound(problem: pulp.LpProblem, variables: list[pulp.LpVariable], *, tolerant: bool) -> float:
    """Bound the represented primary LP via a sign-corrected row dual.

    Minimize the remaining linear coefficients on the ingredient box, which
    makes the bound valid even with rounded or nonstationary solver multipliers.
    In tolerant mode use the relaxation implied by the NRC validator.
    """
    if set(problem.constraints) != set(ROWS):
        raise ValueError("Expected only the eight basic LP rows.")
    stationarity = {v: Fraction(problem.objective.get(v, 0)) for v in variables}
    total = Fraction(0)
    for name, row in problem.constraints.items():
        sense = row.sense
        if sense not in (pulp.LpConstraintGE, pulp.LpConstraintLE):
            raise ValueError("Expected an inequality.")
        pi = row.pi
        y = Fraction(pi if isinstance(pi, Real) and isfinite(pi) and sense * pi > 0 else 0)
        original, ratio = ROWS[name]
        tol = Fraction(_NRC_TOLERANCES[original]) if tolerant else Fraction(0)
        rhs = -Fraction(row.constant) - (0 if ratio else sense * tol)
        total += y * rhs
        for v in variables:
            a = Fraction(row.get(v, 0)) + (sense * tol if ratio else 0)
            stationarity[v] -= y * a

    bound_tol = Fraction(_INGREDIENT_BOUND_TOLERANCE) if tolerant else Fraction(0)
    for v, coefficient in stationarity.items():
        if v.lowBound is None or v.upBound is None:
            raise ValueError("Finite ingredient bounds are required.")
        lower = max(Fraction(0), Fraction(v.lowBound) - bound_tol)
        upper = Fraction(v.upBound) + bound_tol
        total += coefficient * (lower if coefficient >= 0 else upper)
    value = float(total)
    return nextafter(value, -inf) if Fraction(value) > total else value


def primary_lower_bound(config: RationConfig, solver: pulp.LpSolver | None = None) -> dict[str, float | str | None]:
    """Bound NRC cost before adding any reference objective or tie-break locks."""
    problem, quantities = LinearRationOptimizer._build_problem(config)
    try:
        status = problem.solve(solver if solver is not None else pulp.PULP_CBC_CMD(msg=False))
    except (pulp.PulpSolverError, OSError) as error:
        return {
            "primary_optimum_cbc": None,
            "strict_lower_bound": None,
            "lower_bound": None,
            "status": "SolverError",
            "message": str(error),
        }
    if status != pulp.LpStatusOptimal or problem.sol_status != pulp.LpSolutionOptimal:
        return {
            "primary_optimum_cbc": None,
            "strict_lower_bound": None,
            "lower_bound": None,
            "status": pulp.LpStatus.get(status, str(status)),
        }
    variables = list(quantities.values())
    # PuLP can add an unset dummy column to an identically zero objective.
    primary = float(sum(coef * v.varValue for v, coef in problem.objective.items() if coef))
    return {
        "status": "Optimal",
        "primary_optimum_cbc": primary,
        "strict_lower_bound": min(primary, dual_bound(problem, variables, tolerant=False)),
        "lower_bound": min(primary, dual_bound(problem, variables, tolerant=True)),
    }


def relative_gap(cost: float | None, lower: float | None) -> tuple[float | None, str]:
    """Possible saving as a fraction of the approved diet cost."""
    if cost is None or lower is None or not (isfinite(cost) and isfinite(lower)):
        return None, "missing_cost_or_bound"
    if cost < lower:
        return None, "incumbent_below_bound"
    if cost == 0 and lower == 0:
        return 0.0, "zero_cost_and_bound"
    if cost <= 0:
        return None, "nonpositive_incumbent"
    if lower == 0:
        return 1.0, "zero_bound"
    return (cost - lower) / cost, "negative_bound" if lower < 0 else "positive_bound"


def meets_target(cost: float, lower: float | None, target: float) -> bool:
    gap, status = relative_gap(cost, lower)
    return status in ("positive_bound", "zero_cost_and_bound") and gap is not None and gap <= target
