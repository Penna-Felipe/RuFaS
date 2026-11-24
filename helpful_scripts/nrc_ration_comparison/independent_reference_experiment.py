"""Isolated test of explicit regional NRC recipes projected onto archived menus."""

import argparse
import csv
import json
import platform
from pathlib import Path
from statistics import median
from time import perf_counter

import highspy
import pulp

from RUFAS.biophysical.animal.ration.linear_cost_bound import primary_lower_bound, relative_gap
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import LinearRationOptimizer
from RUFAS.biophysical.animal.ration.linear_reference import (
    OBJECTIVES,
    ReferenceGenerationError,
    build_basic_reference,
    grid_key,
    reference_issue,
)

from .cli_three_day import BASE, write
from .compare import json_safe
from .sensitivity import nutrient_errors
from .solver_benchmark import Matrices, linear_matrix, result_record, scenario_inputs


def inventory():
    directory = Path("input/data/feed")
    with (directory / "NRC_comp.csv").open(encoding="utf-8-sig", newline="") as stream:
        nrc_ids = {int(row["rufas_id"]) for row in csv.DictReader(stream)}
    output = {}
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        groups = {}
        for ration in data.get("rations", []):
            rows = ration["feeds"]
            ids = [x["feed_type"] for x in rows]
            shares = {x["feed_type"]: x.get("ration_percentage") for x in rows}
            groups[ration["animal_combination"]] = {
                "explicit": bool(ids)
                and len(ids) == len(shares)
                and all(isinstance(v, (int, float)) and 0 <= v < float("inf") for v in shares.values())
                and sum(shares.values()) > 0,
                "shares": shares,
                "nrc_missing_ids": sorted(set(ids) - nrc_ids),
            }
        output[path.stem.removeprefix("example_").removesuffix("_feed")] = {
            "file": str(path),
            "master_feed_ids": [x["feed_type"] for x in data.get("feeds", [])],
            "groups": groups,
        }
    return output


def project(config, recipe):
    if not recipe or not recipe["explicit"]:
        return {"issue": "No explicit recipe", "quantities": None}
    ids = {f.rufas_id for f in config.feeds_used} - set(recipe["nrc_missing_ids"])
    positive = {key: v for key, v in recipe["shares"].items() if v > 0}
    retained = {key: v for key, v in positive.items() if key in ids}
    removed = {key: v for key, v in positive.items() if key not in ids}
    share = sum(retained.values())
    total = sum(positive.values())
    diet = {key: v * config.initial_dry_matter_requirement / share for key, v in retained.items()} if share else {}
    issue = reference_issue(config, diet)
    return {
        "issue": issue,
        "quantities": diet if issue is None else None,
        "retention": share / total,
        "removed": removed,
        "original": positive,
        "normalized_percent": {key: 100 * v / share for key, v in retained.items()} if share else {},
        "adapted": bool(removed),
    }


def search(config, previous, recipes, policy, budget, solver, optimizer, *, audit=False):
    started = perf_counter()
    bound = primary_lower_bound(config, solver)
    assert bound["status"] == "Optimal"
    ids = [f.rufas_id for f in config.feeds_used]
    builtin = (["previous"] if previous else []) + list(OBJECTIVES)
    best = None
    refs = {}
    seen = {}
    skips = {}
    calls = 1
    generation_seconds = 0.0
    if policy == "A":
        external = []
    elif policy.startswith("B"):
        external = ["Midwest"]
    else:
        external = sorted(recipes, key=lambda key: (-recipes[key].get("retention", 0), key))
    if policy.endswith("early"):
        prefix = builtin.index("minimum_cost") + 1
        order = builtin[:prefix] + external + builtin[prefix:]
    elif policy.endswith("first"):
        order = external + builtin
    else:
        order = builtin + external
    cases_by_ref = {}
    for name in order:
        if budget is not None and len(refs) >= budget:
            break
        tic = perf_counter()
        try:
            if name == "previous":
                quantities = previous
            elif name in OBJECTIVES:
                quantities, metrics = build_basic_reference(config, name, solver)
                calls += metrics["lp_calls"]
            else:
                quantities = recipes[name]["quantities"]
                if quantities is None:
                    skips[name] = recipes[name]["issue"]
                    continue
        except ReferenceGenerationError as error:
            calls += error.solver_calls
            skips[name] = str(error)
            continue
        finally:
            generation_seconds += perf_counter() - tic
        issue = reference_issue(config, quantities)
        key = grid_key(quantities, ids) if issue is None else None
        if issue or key in seen:
            skips[name] = issue or f"Duplicate of {seen[key]}"
            continue
        seen[key] = name
        refs[name] = quantities
        selection = optimizer.solve_and_validate_nrc_cases(config, quantities, solver)
        calls += len(selection.cases)
        assert len(selection.cases) == 6
        cases_by_ref[name] = {
            "regimes": {
                "/".join(regime): (
                    selection.validations[regime].status.value if regime in selection.validations else case.status.value
                )
                for regime, case in selection.cases.items()
            },
            "cost": selection.selected_cost,
        }
        if selection.selected_case is not None and (best is None or selection.selected_cost < best["cost"]):
            validation = selection.validations[selection.selected_case]
            best = {
                "cost": selection.selected_cost,
                "source": name,
                "case": selection.selected_case,
                "quantities": validation.final_quantities,
            }
    total_seconds = perf_counter() - started
    assert calls >= 1 + len(refs) * 6
    return {
        "best": best,
        "gap": relative_gap(best["cost"] if best else None, bound["lower_bound"])[0],
        "bound": bound["lower_bound"],
        "calls": calls,
        "generation_seconds": generation_seconds,
        "total_seconds": total_seconds,
        "refs": list(refs),
        "skips": skips,
        "case_summary": cases_by_ref,
        **({"vectors": refs} if audit else {}),
    }


def diagnose(config, reference, solver):
    collector = Matrices()
    regimes = collector.solve_nrc_cases(config, reference)
    energy = collector.calculate_nrc_energy_coefficients(config, reference)
    protein = collector.calculate_nrc_protein_coefficients(config, reference)
    optimizer = LinearRationOptimizer()
    cases = {}
    for regime, (problem, variables) in zip(regimes, collector.problems, strict=True):
        matrix = linear_matrix(problem, variables)
        case = optimizer._solve_problem(config, problem, variables, solver)
        amounts = case.quantities
        values = [amounts[key] for key in variables] if amounts is not None else None
        record = result_record(config, values, variables, matrix, case.status.value, energy, protein)
        if amounts is not None:
            record["nutrient_errors"] = nutrient_errors(config, amounts, energy, protein)
        cases["/".join(regime)] = record
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=3, type=int)
    parser.add_argument("--output", default=Path("output/nrc_independent_references"), type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("Use at least one repetition.")
    args.output.mkdir(parents=True, exist_ok=False)
    catalog = inventory()
    write(args.output / "inventory.json", catalog)
    solver = pulp.HiGHS(msg=False, threads=1)
    if not solver.available():
        raise RuntimeError("Install linear_ration_highs.")
    optimizer = LinearRationOptimizer()
    policies = ["A", "B_late", "B_early", "C_late", "C_early", "C_first"]
    cells = [(policy, budget) for budget in (2, 3, 5, None) for policy in policies]
    evaluations = {}
    for index, (name, config, _, previous) in enumerate(
        scenario_inputs(BASE / "isolated_audit.json", generate_historical_references=False)
    ):
        print(f"{index + 1:02d}/27 {name}", flush=True)
        recipes = {k: project(config, v["groups"].get("lac_cow")) for k, v in catalog.items()}
        details = {}
        for rep in range(args.runs):
            offset = (rep + index) % len(cells)
            for policy, budget in cells[offset:] + cells[:offset]:
                key = f"{policy}/{budget or 'all'}"
                result = search(config, previous, recipes, policy, budget, solver, optimizer, audit=True)
                timings = {field: result.pop(field) for field in ("total_seconds", "generation_seconds")}
                if key not in details:
                    details[key] = {"result": result, "timings": []}
                else:
                    assert details[key]["result"] == result, (name, key)
                details[key]["timings"].append(timings)
        unique = {}
        for record in details.values():
            unique.update(record["result"]["vectors"])
            record["median"] = {
                key: median(row[key] for row in record["timings"]) for key in ("total_seconds", "generation_seconds")
            }
        diagnostic = {key: diagnose(config, vector, solver) for key, vector in unique.items()}
        for record in details.values():
            for ref, cases in record["result"]["case_summary"].items():
                for regime, status in cases["regimes"].items():
                    case = diagnostic[ref][regime]
                    assert status == (
                        ("approved" if case["final_approved"] else "rejected")
                        if case["status"] == "optimal"
                        else case["status"]
                    )
        evaluations[name] = {"recipes": recipes, "policies": details, "diagnostic": diagnostic}
    assert len(evaluations) == 27
    write(
        args.output / "results.json",
        json_safe(
            {
                "python": platform.python_version(),
                "pulp": pulp.__version__,
                "highspy": highspy.Highs().version(),
                "repetitions": args.runs,
                "scenarios": evaluations,
            }
        ),
    )


if __name__ == "__main__":
    main()
