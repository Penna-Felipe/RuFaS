"""Static one-at-a-time price and inclusion sensitivity on an archived NRC formulation."""

import argparse
import csv
import platform
from dataclasses import asdict, replace
from pathlib import Path

import highspy
import pulp

from RUFAS.biophysical.animal.ration.linear_cost_bound import relative_gap
from RUFAS.biophysical.animal.ration.linear_ration_adapter import LinearRationAdapter
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import LinearRationOptimizer

from .adaptive import PRICE_NOTES, scenario_grid
from .cli_isolated_audit import validate_slsqp
from .cli_three_day import write
from .compare import json_safe
from .sensitivity import make_config
from .solver_benchmark import Matrices

SCENARIO = "114502_midwest_plus_soy_market"
MIDWEST = Path("input/data/feed/example_Midwest_feed.json")


def effective_uppers(config, solver):
    ceilings = {}
    for feed in config.feeds_used:
        problem, variables = LinearRationOptimizer._build_problem(config)
        problem.setObjective(-variables[feed.rufas_id])
        assert problem.solve(solver) == pulp.LpStatusOptimal
        ceilings[feed.rufas_id] = min(feed.limit, variables[feed.rufas_id].varValue)
    return ceilings


def cases(feeds, upper):
    yield "base", "base", None, 0, 0, feeds
    for feed in feeds:
        key = feed.rufas_id
        for change in (-20, -10, 10, 20):
            yield f"price_{key}_{change:+}", "price", key, change, 0, [
                replace(f, purchase_cost=f.purchase_cost * (1 + change / 100)) if f.rufas_id == key else f
                for f in feeds
            ]
        yield f"remove_{key}", "remove", key, 0, 100, [f for f in feeds if f.rufas_id != key]
        for cut in (25, 50):
            ceiling = upper[key] * (1 - cut / 100)
            if ceiling >= feed.lower_limit:
                yield f"cap_{key}_{cut}", "cap", key, 0, cut, [
                    replace(f, limit=ceiling) if f.rufas_id == key else f for f in feeds
                ]
    yield "combined_50", "combined", 50, 20, 50, [
        replace(f, limit=upper[50] / 2, purchase_cost=f.purchase_cost * 1.2) if f.rufas_id == 50 else f for f in feeds
    ]


def winner_lp(config, result, solver):
    ref = next(ref for ref in result.references if ref.source == result.selected_reference)
    collector = Matrices()
    regimes = collector.solve_nrc_cases(config, ref.quantities)
    idx = list(regimes).index(result.selected_case)
    problem, columns = collector.problems[idx]
    assert problem.solve(solver) == pulp.LpStatusOptimal
    raw = ref.selection.cases[result.selected_case].quantities
    assert all(abs(var.varValue - raw[key]) < 1e-8 for key, var in columns.items())
    rows = []
    values = []
    for name, row in problem.constraints.items():
        margin = row.value() * row.sense if row.sense else abs(row.value())
        rows.append(
            {
                "constraint": name,
                "sense": row.sense,
                "rhs": -row.constant,
                "shadow_price": row.pi,
                "slack": margin,
                "active": abs(margin) <= 1e-7,
            }
        )
    for key, var in columns.items():
        lower, upper = var.varValue - var.lowBound, var.upBound - var.varValue
        values.append(
            {
                "rufas_id": key,
                "quantity": var.varValue,
                "reduced_cost": var.dj,
                "lower_slack": lower,
                "upper_slack": upper,
                "lower_active": abs(lower) <= 1e-7,
                "upper_active": abs(upper) <= 1e-7,
            }
        )
    return rows, values


def csv_write(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/nrc_price_availability_sensitivity"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    _, inputs, _, metadata = next(s for s in scenario_grid() if s[0] == SCENARIO)
    feeds = inputs["pen_available_feeds"]
    baseline = make_config(inputs)
    solver = pulp.HiGHS(msg=False, threads=1)
    assert solver.available()
    limits = effective_uppers(baseline, solver)
    adapters = {
        f"highs_{n}": LinearRationAdapter(
            "full",
            max_references=n,
            reference_solver=solver,
            bound_solver=solver,
            nutritional_solver=solver,
            midwest_reference_path=MIDWEST,
        )
        for n in (3, 5)
    }
    scenario_details = {}
    summary, composition, dual_rows, dual_variables = [], [], [], []
    menu_ids = [f.rufas_id for f in feeds]
    for name, kind, driver, price, cut, trial in cases(feeds, limits):
        print(name, flush=True)
        trial_inputs = {**inputs, "pen_available_feeds": trial}
        config = make_config(trial_inputs)
        results = {label: adapter._search(config, None) for label, adapter in adapters.items()}
        bound = results["highs_5"].lower_bound
        bound_status = results["highs_5"].bound_details["status"]
        assert all(r.lower_bound == bound and r.bound_details["status"] == bound_status for r in results.values())
        slsqp = validate_slsqp(trial_inputs, {}, 42)
        slsqp_diet = slsqp["final"] if slsqp["converged"] else None
        scenario_details[name] = {
            "slsqp": slsqp,
            "feeds": {f.rufas_id: {"price": f.purchase_cost, "lower": f.lower_limit, "upper": f.limit} for f in trial},
        }
        methods = [
            (
                "slsqp",
                slsqp_diet,
                slsqp["final_cost"] if slsqp_diet else None,
                slsqp["solver_seconds"],
                None,
                slsqp["message"],
                slsqp["converged"],
            )
        ]
        for label, r in results.items():
            methods.append((label, r.quantities, r.fun, r.elapsed_seconds, r.selected_reference, r.message, None))
            scenario_details[name][label] = {
                "status": int(r.status),
                "message": r.message,
                "reference": r.selected_reference,
                "bound": r.bound_details,
                "solver_calls": r.solver_calls,
                "regional": r.regional_reference,
                "references": [asdict(ref) | {"selection": None} for ref in r.references],
                "selected_case": r.selected_case,
                "quantities": r.quantities,
                "validation": (
                    asdict(
                        next(ref.selection for ref in r.references if ref.source == r.selected_reference).validations[
                            r.selected_case
                        ]
                    )
                    if r.success
                    else None
                ),
            }
            if r.success:
                rows, variables = winner_lp(config, r, solver)
                common = {
                    "scenario": name,
                    "method": label,
                    "winner": r.selected_reference,
                    "regime": "/".join(r.selected_case),
                }
                dual_rows.extend(common | row for row in rows)
                dual_variables.extend(common | row for row in variables)
        for method, diet, cost, seconds, source, message, converged in methods:
            state = (
                "nrc_approved"
                if diet is not None
                else "basic_relaxation_infeasible" if bound_status == "Infeasible" else "no_approved_candidate"
            )
            summary.append(
                {
                    "scenario": name,
                    "kind": kind,
                    "driver_rufas_id": driver,
                    "price_change_pct": price,
                    "effective_cap_cut_pct": cut,
                    "method": method,
                    "classification": state,
                    "basic_lp_status": bound_status,
                    "nrc_approved": diet is not None,
                    "legacy_slsqp_converged": converged,
                    "cost_usd_cow_day": cost,
                    "dmi_kg_cow_day": sum(diet.values()) if diet is not None else None,
                    "bound_usd_cow_day": bound,
                    "gap_fraction": relative_gap(cost, bound)[0],
                    "optimization_s": seconds,
                    "winner": source,
                    "message": message,
                }
            )
            composition.extend(
                {
                    "scenario": name,
                    "method": method,
                    "rufas_id": key,
                    "kg_dm_cow_day": diet.get(key, 0) if diet is not None else None,
                    "available": key in {f.rufas_id for f in trial},
                }
                for key in menu_ids
            )
    baselines = {r["method"]: r for r in summary if r["scenario"] == "base"}
    base_diets = {(r["method"], r["rufas_id"]): r["kg_dm_cow_day"] for r in composition if r["scenario"] == "base"}
    for r in summary:
        base = baselines[r["method"]]["cost_usd_cow_day"]
        r["cost_delta_pct_from_method_base"] = (
            (r["cost_usd_cow_day"] / base - 1) * 100 if base and r["cost_usd_cow_day"] is not None else None
        )
    for r in composition:
        base = base_diets[r["method"], r["rufas_id"]]
        r["quantity_delta_kg_from_method_base"] = (
            r["kg_dm_cow_day"] - base if base is not None and r["kg_dm_cow_day"] is not None else None
        )
    for name, data in (
        ("summary", summary),
        ("composition", composition),
        ("lp_constraints", dual_rows),
        ("lp_ingredients", dual_variables),
    ):
        csv_write(args.output / f"{name}.csv", data)
    write(
        args.output / "details.json",
        json_safe(
            {
                "input_scenario": SCENARIO,
                "seed": 42,
                "python": platform.python_version(),
                "pulp": pulp.__version__,
                "highspy": highspy.Highs().version(),
                "ingredient_prices_reference": PRICE_NOTES,
                "original_scenario": metadata,
                "effective_upper_kg_dm": limits,
                "scenarios": scenario_details,
            }
        ),
    )


if __name__ == "__main__":
    main()
