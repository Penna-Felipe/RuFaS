"""Compare reference LP solvers while keeping HiGHS nutrition and the CBC cost bound."""

import argparse
import json
import platform
import subprocess
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

import highspy
import pulp

from RUFAS.biophysical.animal.ration.linear_cost_bound import ROWS, dual_bound
from RUFAS.biophysical.animal.ration.linear_ration_adapter import LinearRationAdapter
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import (
    _INGREDIENT_BOUND_TOLERANCE,
    _NRC_TOLERANCES,
    LinearRationOptimizer,
)
from RUFAS.biophysical.animal.ration.linear_reference import OBJECTIVE_LOCK_SLACK, OBJECTIVES, grid_key

from .cli_three_day import BASE, write
from .compare import json_safe
from .solver_benchmark import scenario_inputs

ARMS = ("cbc", "highs")


def expression(coefficients):
    return {variable.name: coefficient for variable, coefficient in coefficients.items() if coefficient}


def timed_search(adapter, config, previous):
    started = perf_counter()
    result = adapter._search(config, previous)
    return result, perf_counter() - started


def generation_audit(adapter, config, previous):
    stages = []
    solver = adapter.reference_solver
    actual_solve = solver.actualSolve

    def capture(problem, **kwargs):
        objective = expression(problem.objective)
        limits = {
            name: {"sense": row.sense, "rhs": -row.constant, "coefficients": expression(row)}
            for name, row in problem.constraints.items()
        }
        status = actual_solve(problem, **kwargs)
        stages.append(
            {
                "objective": objective,
                "optimum": pulp.value(problem.objective),
                "status": pulp.LpStatus[status],
                "constraints": limits,
                "vector": {v.name: v.varValue for v in problem.variables()},
            }
        )
        return status

    solver.actualSolve = capture
    try:
        result, _ = timed_search(adapter, config, previous)
    finally:
        solver.actualSolve = actual_solve
    return result, stages


def candidate_summary(selection):
    if selection is None:
        return None
    cases = []
    for regime, result in selection.cases.items():
        validation = selection.validations.get(regime)
        cases.append(
            {
                "regime": regime,
                "status": result.status.value,
                "raw_cost": result.cost,
                "raw_quantities": result.quantities,
                "validation": asdict(validation) if validation else None,
                "final_quantities": validation.final_quantities if validation else None,
            }
        )
    return {"selected_case": selection.selected_case, "selected_cost": selection.selected_cost, "cases": cases}


def describe(result, stages, config):
    records = []
    used = 0
    ids = [feed.rufas_id for feed in config.feeds_used]
    basic, variables = LinearRationOptimizer._build_problem(config)
    seen_sources = []
    for ref in result.references:
        calls = stages[used : used + ref.generation_calls]
        used += ref.generation_calls
        if calls:
            obj_names = [ref.source]
            if ref.source != "minimum_cost":
                obj_names.append("minimum_cost")
            obj_names.extend(f"feed_{key}" for key in sorted(ids))
            for stage, name in zip(calls, obj_names):
                stage["name"] = name
                stage["native_optimum"] = (
                    -stage["optimum"]
                    if name in ("maximum_forage", "maximum_concentrate") and stage["optimum"] is not None
                    else stage["optimum"]
                )
                vector = stage["vector"]
                stage["max_inequality_violation"] = max(
                    (
                        max(0, -(row["sense"] * residual) if row["sense"] else abs(residual))
                        for row in stage["constraints"].values()
                        if all(vector[key] is not None for key in row["coefficients"])
                        for residual in [
                            sum(coef * vector[key] for key, coef in row["coefficients"].items()) - row["rhs"]
                        ]
                    ),
                    default=0,
                )
            final_vector = calls[-1]["vector"]
            for stage in calls:
                if all(final_vector[key] is not None for key in stage["objective"]):
                    stage["final_value"] = sum(coef * final_vector[key] for key, coef in stage["objective"].items())
        quantities = ref.quantities
        residuals = None
        validation = None
        bounds = None
        key = None
        if quantities is not None:
            key = grid_key(quantities, ids)
            residuals = {
                name: row.sense
                * (
                    sum(
                        coef * quantities.get(feed_id, 0) for feed_id, v in variables.items() if (coef := row.get(v, 0))
                    )
                    + row.constant
                )
                for name, row in basic.constraints.items()
            }
            validation = LinearRationOptimizer.validate_nrc_candidate(config, quantities)
            bounds = {
                feed_id: [quantities.get(feed_id, 0) - v.lowBound, v.upBound - quantities.get(feed_id, 0)]
                for feed_id, v in variables.items()
            }
        if ref.selection is not None:
            seen_sources.append(ref.source)
        records.append(
            {
                "source": ref.source,
                "quantities": quantities,
                "grid_key": key,
                "message": ref.message,
                "generation_calls": ref.generation_calls,
                "basic_linear_residuals": residuals,
                "individual_bound_margins": bounds,
                "basic_residuals_in_nrc_units": (
                    {original: validation.unrounded.residuals.get(original) for original, _ in ROWS.values()}
                    if validation
                    else None
                ),
                "compatible": quantities is not None
                and (ref.selection is not None or ref.message == "Duplicate reference."),
                "lexicographic_stages": calls,
                "selection": candidate_summary(ref.selection),
            }
        )
    assert used == len(stages)
    return {
        "success": bool(result.success),
        "status": int(result.status),
        "cost": result.fun,
        "gap": result.gap,
        "bound": result.bound_details,
        "calls": result.solver_calls,
        "selected_reference": result.selected_reference,
        "selected_case": result.selected_case,
        "quantities": result.quantities,
        "references_sent_to_nutrition": seen_sources,
        "references": records,
    }


def diagnostic_bound(config, cbc, highs):
    output = {}
    for name, solver in zip(ARMS, (cbc, highs), strict=True):
        problem, variables = LinearRationOptimizer._build_problem(config)
        status = problem.solve(solver)
        assert status == pulp.LpStatusOptimal and problem.sol_status == pulp.LpSolutionOptimal
        output[name] = {
            "primal": pulp.value(problem.objective),
            "strict_certificate": dual_bound(problem, list(variables.values()), tolerant=False),
            "tolerant_certificate": dual_bound(problem, list(variables.values()), tolerant=True),
            "rows": {
                key: {"sense": row.sense, "pi": row.pi, "residual": row.sense * row.value()}
                for key, row in problem.constraints.items()
            },
            "reduced_costs": {key: var.dj for key, var in variables.items()},
        }
    # Solve the validator-tolerant basic relaxation explicitly as a second primal check.
    problem, variables = LinearRationOptimizer._build_problem(config)
    for variable in variables.values():
        variable.lowBound = max(0, variable.lowBound - _INGREDIENT_BOUND_TOLERANCE)
        variable.upBound += _INGREDIENT_BOUND_TOLERANCE
    for name, row in problem.constraints.items():
        original, ratio = ROWS[name]
        tol = _NRC_TOLERANCES[original]
        if ratio:
            for variable in variables.values():
                row.expr.addterm(variable, row.sense * tol)
        else:
            row.changeRHS(-row.constant - row.sense * tol)
    status = problem.solve(highs)
    assert status == pulp.LpStatusOptimal and problem.sol_status == pulp.LpSolutionOptimal
    output["tolerant_primal_highs"] = pulp.value(problem.objective)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("output/nrc_reference_solver_pilot"))
    args = parser.parse_args()
    if args.runs < 2:
        parser.error("Use at least two timed repetitions.")
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        parser.error("Use a new or empty output directory.")
    cbc = pulp.PULP_CBC_CMD(msg=False)
    bound_cbc = pulp.PULP_CBC_CMD(msg=False)
    highs = pulp.HiGHS(msg=False, threads=1)
    assert highs.available() and cbc.available()
    adapters = {
        key: LinearRationAdapter(
            "full", max_references=5, reference_solver=solver, bound_solver=bound_cbc, nutritional_solver="highs"
        )
        for key, solver in zip(ARMS, (cbc, highs), strict=True)
    }
    scenarios = {}
    for index, (name, config, _, previous) in enumerate(
        scenario_inputs(BASE / "isolated_audit.json", generate_historical_references=False)
    ):
        print(f"{index + 1:02d}/27 {name}", flush=True)
        results = {}
        for key, adapter in adapters.items():
            result, stages = generation_audit(adapter, config, previous)
            results[key] = describe(result, stages, config)
            assert [ref["source"] for ref in results[key]["references"] if ref["source"] != "previous_ration"] == list(
                OBJECTIVES
            )
            results[key]["timings"] = []
        assert results["cbc"]["bound"] == results["highs"]["bound"]
        for rep in range(args.runs):
            # Alternate first position within each formulation and across formulations.
            order = ARMS if (rep + index) % 2 == 0 else ARMS[::-1]
            for key in order:
                result, elapsed = timed_search(adapters[key], config, previous)
                row = results[key]
                assert (
                    bool(result.success),
                    result.quantities,
                    result.fun,
                    result.gap,
                    result.solver_calls,
                    result.selected_reference,
                    result.selected_case,
                ) == (
                    row["success"],
                    row["quantities"],
                    row["cost"],
                    row["gap"],
                    row["calls"],
                    row["selected_reference"],
                    row["selected_case"],
                ), (
                    name,
                    key,
                    rep,
                )
                assert [(ref.source, ref.quantities, ref.message) for ref in result.references] == [
                    (ref["source"], ref["quantities"], ref["message"]) for ref in row["references"]
                ], (name, key, rep)
                row["timings"].append(
                    {
                        "total_seconds": elapsed,
                        "bound_seconds": result.bound_seconds,
                        "generation_seconds": {ref.source: ref.generation_seconds for ref in result.references},
                        "nutrition_seconds": sum(ref.solve_and_validate_seconds for ref in result.references),
                    }
                )
        scenarios[name] = {"arms": results, "bound_diagnostic": diagnostic_bound(config, cbc, highs)}
        write(args.output / "progress.json", {"finished": list(scenarios)})
    assert len(scenarios) == 27
    write(
        args.output / "results.json",
        json_safe(
            {
                "python": platform.python_version(),
                "pulp": pulp.__version__,
                "highspy": highspy.Highs().version(),
                "cbc": subprocess.check_output([cbc.path, "-quit"], text=True).splitlines()[1].strip(),
                "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "repetitions": args.runs,
                "objective_lock_slack": OBJECTIVE_LOCK_SLACK,
                "scenarios": scenarios,
            }
        ),
    )


if __name__ == "__main__":
    main()
