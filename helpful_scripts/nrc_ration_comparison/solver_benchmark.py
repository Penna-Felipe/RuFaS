"""Benchmark LP solver interfaces on unchanged NRC matrices, outside the simulation."""

import argparse
import hashlib
import json
import platform
import struct
import subprocess
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from statistics import median, quantiles
from tempfile import TemporaryDirectory
from time import perf_counter

import highspy
import numpy as np
import pulp
import scipy
from scipy.optimize import linprog
from scipy.optimize._highspy import _core

from RUFAS.biophysical.animal.animal_module_constants import AnimalModuleConstants
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import (
    LinearRationOptimizer,
    LinearRationResult,
    LinearRationStatus,
    _NRC_TOLERANCES,
)
from RUFAS.biophysical.animal.ration.linear_reference import (
    OBJECTIVES,
    build_basic_reference,
    grid_key,
    reference_issue,
)
from RUFAS.biophysical.animal.ration.ration_manager import RationManager

from .adaptive import scenario_grid
from .cli_isolated_audit import VALIDATE, inputs_for, load_feeds, quantities
from .cli_three_day import BASE, ROOT, read, write
from .compare import json_safe
from .multireference import external_recipes
from .sensitivity import ENERGY_FIELDS, make_config, protein_offers

DEST = Path("output/nrc_solver_benchmark")
CBC = pulp.PULP_CBC_CMD(msg=False)
FLAGS = {
    "cbc": [],
    "cbc_tight": ["primalTolerance 1e-9", "dualTolerance 1e-9"],
    "cbc_format4": ["outputFormat 4"],
}
METHODS = (*FLAGS, "cbc_binary", "pulp_highs", "scipy_highs")
SCIPY_VERSION = ".".join(str(getattr(_core, "HIGHS_VERSION_" + field)) for field in ("MAJOR", "MINOR", "PATCH"))


class Matrices(LinearRationOptimizer):
    """Capture the six models directly from the production builder."""

    def __init__(self):
        self.problems = []

    def _solve_problem(self, config, problem, variables, solver):
        self.problems.append((problem, variables))
        return LinearRationResult(LinearRationStatus.INFEASIBLE)


def linear_matrix(problem, variables):
    columns = tuple(variables.values())
    return {
        "objective": [problem.objective.get(var, 0.0) for var in columns],
        "bounds": [(var.lowBound, var.upBound) for var in columns],
        "rows": {
            name: (row.sense, -row.constant, [row.get(var, 0.0) for var in columns])
            for name, row in problem.constraints.items()
        },
    }


def resids(matrix, values):
    return {name: float(sense * (np.dot(coefs, values) - rhs)) for name, (sense, rhs, coefs) in matrix["rows"].items()}


def compare_mps(variables, variable_names, constraint_names, matrix, path):
    new_variables, exported = pulp.LpProblem.fromMPS(str(path))
    columns = [new_variables[variable_names[var.name]] for var in variables.values()]
    restored_rows = {name: exported.constraints[alias] for name, alias in constraint_names.items()}
    differences = {
        "row_coefficients": max(
            abs(row.get(var, 0.0) - coefficients[i])
            for name, row in restored_rows.items()
            for i, var in enumerate(columns)
            for coefficients in [matrix["rows"][name][2]]
        ),
        "rhs": max(abs(-row.constant - matrix["rows"][name][1]) for name, row in restored_rows.items()),
        "objective": max(
            abs(exported.objective.get(var, 0.0) - matrix["objective"][i]) for i, var in enumerate(columns)
        ),
        "bounds": max(
            abs(a - b)
            for i, var in enumerate(columns)
            for a, b in zip((var.lowBound, var.upBound), matrix["bounds"][i], strict=True)
        ),
    }
    assert all(row.sense == matrix["rows"][name][0] for name, row in restored_rows.items())
    return differences


def cbc_binary(problem, variables, matrix):
    with TemporaryDirectory() as directory:
        folder = Path(directory)
        columns, names, constraints, _ = problem.writeMPS(str(folder / "problem.mps"), rename=1)
        proc = subprocess.run(
            [
                CBC.path,
                "problem.mps",
                "-solve",
                "-printingOptions",
                "all",
                "-solution",
                "result.sol",
                "-saveSolution",
                "result.bin",
            ],
            cwd=folder,
            capture_output=True,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        status, text, _, _, _, solution_status = CBC.readsol_MPS(
            str(folder / "result.sol"), problem, columns, names, constraints
        )
        values = None
        diagnostic = {}
        if status == pulp.LpStatusOptimal and solution_status == pulp.LpSolutionOptimal:
            blob = (folder / "result.bin").read_bytes()
            nrow, ncol, obj = struct.unpack_from("=iid", blob)
            assert nrow == len(constraints) and ncol == len(columns)
            native = struct.unpack_from(f"={ncol}d", blob, 16 + 16 * nrow)
            by_name = dict(zip((var.name for var in columns), native, strict=True))
            values = [by_name[var.name] for var in variables.values()]
            text_values = [text[var.name] for var in variables.values()]
            assert abs(float(np.dot(values, matrix["objective"])) - obj) < 1e-7
            diagnostic = {
                "text_values": text_values,
                "binary_objective": obj,
                "text_diff_max_kg": max(abs(a - b) for a, b in zip(values, text_values, strict=True)),
            }
        return pulp.LpStatus[status], values, diagnostic


def solve(method, problem, variables, matrix, first):
    start = perf_counter()
    extra = {}
    if method == "scipy_highs":
        rows = list(matrix["rows"].values())
        result = linprog(
            matrix["objective"],
            A_ub=[[-sense * c for c in cols] for sense, _, cols in rows],
            b_ub=[-sense * rhs for sense, rhs, _ in rows],
            bounds=matrix["bounds"],
            method="highs",
        )
        values = list(map(float, result.x)) if result.success else None
        status = {0: "Optimal", 2: "Infeasible", 3: "Unbounded"}.get(result.status, f"Status {result.status}")
    elif method == "cbc_binary":
        status, values, extra = cbc_binary(problem, variables, matrix)
    else:
        solver = (
            pulp.HiGHS(msg=False, threads=1)
            if method == "pulp_highs"
            else pulp.PULP_CBC_CMD(msg=False, options=FLAGS[method])
        )
        code = problem.solve(solver)
        status = pulp.LpStatus[code]
        if code == pulp.LpStatusOptimal and problem.sol_status != pulp.LpSolutionOptimal:
            status = pulp.LpSolution[problem.sol_status]
        values = [float(var.varValue) for var in variables.values()] if status == "Optimal" else None
    elapsed = perf_counter() - start
    if method == "cbc_binary" and first:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "problem.mps"
            _, names, constraints, _ = problem.writeMPS(str(path), rename=1)
            extra["mps_export_max_absolute_error"] = compare_mps(variables, names, constraints, matrix, path)
    return status, values, elapsed, extra


def failure_causes(validation, fixed):
    labels = {}
    for name in validation.unrounded.violations:
        original = validation.unrounded.residuals.get(name)
        approx = fixed.get(name)
        tol = _NRC_TOLERANCES.get(name)
        if name in fixed and tol is not None and original is not None:
            if approx >= -tol:
                label = "approximation"
            elif original - approx < -tol:
                label = "numerical_and_approximation"
            else:
                label = "numerical"
        else:
            label = "numerical" if tol is not None or name.startswith("ingredient_") else "invalid_vector"
        labels[name] = label
    return labels


def result_record(config, values, variables, matrix, status, energy, protein):
    if values is None:
        return {"status": status}
    diet = dict(zip(variables, values, strict=True))
    validation = VALIDATE(config, diet, repair_rounding=True)
    final = validation.final_quantities
    linear = resids(matrix, values)
    supplies = {kind: sum(getattr(energy[i], kind) * amount for i, amount in diet.items()) for kind in ENERGY_FIELDS}
    total_mp = protein_offers(diet, protein)["metabolizable_protein"]
    req = config.animal_requirements
    fixed = {
        "NE_total_constraint": max(supplies.values()) - req.total_energy_requirement,
        "NE_maintenance_and_activity_constraint": supplies["maintenance"]
        - req.activity_energy
        - req.maintenance_energy,
        "NE_growth_constraint": supplies["growth"] - req.growth_energy,
        "NE_lactation_constraint": supplies["lactation"] - req.lactation_energy - req.pregnancy_energy,
        "protein_constraint_lower": total_mp - req.metabolizable_protein,
        "protein_constraint_upper": AnimalModuleConstants.PROTEIN_UPPER_LIMIT_FACTOR
        * config.initial_protein_requirement
        - total_mp,
    }
    return {
        "status": status,
        "quantities_kg_dm": diet,
        "raw_cost": float(np.dot(values, matrix["objective"])),
        "matrix_residuals": linear,
        "fixed_nonlinear_residuals": fixed,
        "nrc_validation": asdict(validation),
        "raw_approved": not validation.unrounded.violations,
        "rounded_approved": validation.rounded is not None and not validation.rounded.violations,
        "repair_approved": validation.repair is not None
        and validation.repair.validation is not None
        and not validation.repair.validation.violations,
        "final_approved": final is not None,
        "final_quantities": final,
        "final_cost": sum(final[i] * c for i, c in zip(variables, matrix["objective"], strict=True)) if final else None,
        "raw_failure_causes": failure_causes(validation, fixed),
    }


def benchmark(config, reference, methods, runs):
    collector = Matrices()
    regimes = collector.solve_nrc_cases(config, reference)
    energy = collector.calculate_nrc_energy_coefficients(config, reference)
    protein = collector.calculate_nrc_protein_coefficients(config, reference)
    report = []
    for index, (regime, (problem, variables)) in enumerate(zip(regimes, collector.problems, strict=True)):
        matrix = linear_matrix(problem, variables)
        digest = hashlib.sha256(json.dumps(matrix, sort_keys=True).encode()).hexdigest()
        cases = {method: {"seconds": []} for method in methods}
        for rep in range(runs):
            shift = (rep + index) % len(methods)
            for method in methods[shift:] + methods[:shift]:
                status, values, seconds, extra = solve(method, problem, variables, matrix, rep == 0)
                case = cases[method]
                case["seconds"].append(seconds)
                if rep == 0:
                    case.update(result_record(config, values, variables, matrix, status, energy, protein), **extra)
                    case["repeated_status_and_vector_match"] = True
                elif status != case["status"] or (
                    values is not None and values != list(case.get("quantities_kg_dm", {}).values())
                ):
                    case["repeated_status_and_vector_match"] = False
        for case in cases.values():
            case["median_seconds"] = median(case["seconds"])
        report.append({"regime": regime, "same_matrix_sha256": digest, "matrix": matrix, "results": cases})
    return report


def scenario_inputs(audit, *, generate_historical_references=True):
    rows = read(audit)["formulations"]
    feed_file = read(BASE / "inputs/feed.json")
    feeds = load_feeds(feed_file)
    RationManager.set_intake_options(feed_file)
    for name, source in rows.items():
        mode, day, _ = name.split("/")
        initial = rows[f"{mode}/{day}/1"]
        config = make_config(
            inputs_for({**source, "available_ids": source["feed_order"]}, initial, source["weight_kg"], feeds)
        )
        refs = {
            row["source"]: quantities(row["quantities"])
            for row in source["pulp"]["references"]
            if row["case_counts"] is not None
        }
        yield f"cli/{name}", config, refs, quantities(source["previous_ration"])
    historical = read(Path("helpful_scripts/nrc_ration_comparison/adaptive_results.json"))["scenarios"]
    grid = scenario_grid()
    assert {name for name, *_ in grid} == set(historical)
    for name, inputs, _, _ in grid:
        config = make_config(inputs)
        refs = {}
        seen = set()
        for objective in OBJECTIVES if generate_historical_references else ():
            ref, _ = build_basic_reference(config, objective)
            key = grid_key(ref, [feed.rufas_id for feed in config.feeds_used])
            if reference_issue(config, ref) is None and key not in seen:
                refs[objective] = ref
                seen.add(key)
        yield f"historical/{name}", config, refs, {}


def additional_references(config, base_refs):
    recipes, audit = external_recipes(config)
    from .compare import read_json

    midwest = read_json("feed/example_Midwest_feed.json")
    ration = next(r for r in midwest["rations"] if r["animal_combination"] == "lac_cow")
    shares = {f["feed_type"]: f["ration_percentage"] for f in ration["feeds"]}
    ids = [feed.rufas_id for feed in config.feeds_used]
    retained = {key: share for key, share in shares.items() if key in ids and share > 0}
    if retained:
        recipes["midwest_compatible"] = {
            i: config.initial_dry_matter_requirement * v / sum(retained.values()) for i, v in retained.items()
        }
    seen = {grid_key(ref, ids) for ref in base_refs.values()}
    accepted = {}
    issues = {}
    for name, diet in recipes.items():
        key = grid_key(diet, ids)
        issue = reference_issue(config, diet) or ("Duplicate reference." if key in seen else None)
        if issue:
            issues[name] = issue
        else:
            accepted[name] = diet
            seen.add(key)
    return accepted, {
        "strict_recipe_file_audits": audit,
        "excluded_midwest_percentages": {key: value for key, value in shares.items() if key not in ids},
        "compatible_reference_issues": issues,
    }


def best(reference_rows, method):
    candidates = [
        (r["results"][method]["final_cost"], name, r["regime"], r["results"][method]["final_quantities"])
        for name, data in reference_rows.items()
        for r in data["cases"]
        if r["results"][method].get("final_approved")
    ]
    if not candidates:
        return None
    cost, name, regime, diet = min(candidates, key=lambda x: x[0])
    return {"cost": cost, "reference": name, "regime": regime, "diet": diet}


def totals(problems, methods):
    summary = {}
    cases = [case["results"] for p in problems for ref in p["core"].values() for case in ref["cases"]]
    for method in methods:
        grouped = [c[method] for c in cases]
        medians = [r["median_seconds"] for r in grouped]
        summary[method] = {
            "cases": len(grouped),
            "statuses": dict(Counter(r["status"] for r in grouped)),
            "raw_approved": sum(bool(r.get("raw_approved")) for r in grouped),
            "rounded_approved": sum(bool(r.get("rounded_approved")) for r in grouped),
            "repair_approved": sum(bool(r.get("repair_approved")) for r in grouped),
            "final_approved": sum(bool(r.get("final_approved")) for r in grouped),
            "raw_failure_labels": dict(
                Counter(label for r in grouped for label in r.get("raw_failure_causes", {}).values())
            ),
            "cases_recovered_vs_text_cbc": sum(
                not item["cbc"].get("final_approved") and bool(item[method].get("final_approved")) for item in cases
            ),
            "cases_lost_vs_text_cbc": sum(
                bool(item["cbc"].get("final_approved")) and not item[method].get("final_approved") for item in cases
            ),
            "formulations_approved": sum(p["best"][method] is not None for p in problems),
            "case_median_seconds": median(medians),
            "p90_of_case_medians_seconds": quantiles(medians, n=10)[-1],
            "time_per_repetition_seconds": [
                sum(r["seconds"][i] for r in grouped) for i in range(len(grouped[0]["seconds"]))
            ],
            "deterministic_cases": sum(r["repeated_status_and_vector_match"] for r in grouped),
        }
    return summary


def run(runs, audit, dest):
    assert pulp.HiGHS(msg=False).available(), "Install highspy and expose it through PYTHONPATH."
    problems = {}
    for name, config, reference_rows, previous in scenario_inputs(audit):
        print(f"{len(problems) + 1:02d}/27 {name}", flush=True)
        if not reference_rows:
            raise ValueError(f"Missing core references for {name}.")
        core = {
            key: {"diet": diet, "cases": benchmark(config, diet, METHODS, runs)} for key, diet in reference_rows.items()
        }
        extras, external_audit = additional_references(config, reference_rows)
        external_methods = ("cbc", "pulp_highs")
        external = {
            key: {"diet": diet, "cases": benchmark(config, diet, external_methods, runs)}
            for key, diet in extras.items()
        }
        problems[name] = {
            "ordered_feed_ids": [f.rufas_id for f in config.feeds_used],
            "core": core,
            "external": external,
            "external_audit": external_audit,
            "best": {method: best(core, method) for method in METHODS},
            "best_with_external": {method: best(core | external, method) for method in external_methods},
            "previous_diet_nrc": asdict(VALIDATE(config, previous).unrounded) if previous else None,
        }
        write(dest / "latest.json", {"finished_scenarios": list(problems)})
    summary = {
        label: totals([p for name, p in problems.items() if name.startswith(label)], METHODS)
        for label in ("cli", "historical", "")
    }
    cbc_version = subprocess.run([CBC.path, "-quit"], capture_output=True, text=True, check=True).stdout.splitlines()[1]
    highspy_version = highspy.Highs().version()
    output = {
        "repetitions_per_case": runs,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cbc": cbc_version,
        "pulp": pulp.__version__,
        "scipy": scipy.__version__,
        "scipy_highs_engine": SCIPY_VERSION,
        "highspy": highspy_version,
        "cbc_text_options": FLAGS,
        "pulp_highs_options": {"threads": 1, "msg": False},
        "scipy_highs_options": {"method": "highs"},
        "summary": summary,
        "problems": problems,
    }
    write(dest / "results.json", json_safe(output))


def audit_serialized_matrix(audit, destination):
    """Give the direct HiGHS API the actual coefficient precision of the MPS export."""
    results = read(destination / "results.json")
    report = {}
    quantize = lambda value: float(format(value, ".12e"))
    for name, config, _, _ in scenario_inputs(audit):
        rows = []
        for reference, bundle in results["problems"][name]["core"].items():
            for case in bundle["cases"]:
                original = case["matrix"]
                model = pulp.LpProblem("mps_precision_check")
                variables = {
                    feed.rufas_id: pulp.LpVariable(f"feed_{i}", quantize(lower), quantize(upper))
                    for i, (feed, (lower, upper)) in enumerate(zip(config.feeds_used, original["bounds"], strict=True))
                }
                model += pulp.lpSum(
                    var * quantize(c) for var, c in zip(variables.values(), original["objective"], strict=True)
                )
                for row, (sense, rhs, coefs) in original["rows"].items():
                    lhs = pulp.lpSum(var * quantize(c) for var, c in zip(variables.values(), coefs, strict=True))
                    model += (lhs >= quantize(rhs) if sense == 1 else lhs <= quantize(rhs)), row
                model_matrix = linear_matrix(model, variables)
                status, values, _, _ = solve("pulp_highs", model, variables, model_matrix, False)
                diet = dict(zip(variables, values, strict=True)) if values else None
                check = VALIDATE(config, diet, repair_rounding=True) if diet else None
                old = case["results"]["pulp_highs"]
                rows.append(
                    {
                        "reference": reference,
                        "regime": case["regime"],
                        "status": status,
                        "original_status": old["status"],
                        "diet": diet,
                        "raw_approved": not check.unrounded.violations if check else None,
                        "final_approved": check.final_quantities is not None if check else False,
                        "original_final_approved": bool(old.get("final_approved")),
                        "raw_cost": float(np.dot(values, original["objective"])) if diet else None,
                    }
                )
        report[name] = rows
    write(destination / "mps_precision_control.json", json_safe(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--audit", type=Path, default=BASE / "isolated_audit.json")
    parser.add_argument("--output", type=Path, default=DEST)
    parser.add_argument("--mps-check", action="store_true")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    if args.mps_check:
        audit_serialized_matrix(args.audit, args.output)
    else:
        run(args.runs, args.audit, args.output)
