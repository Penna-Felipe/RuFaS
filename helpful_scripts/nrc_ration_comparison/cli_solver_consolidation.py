"""Time the archived three-day NRC scenario with equivalent tracing for every solver configuration."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from statistics import median
from time import perf_counter
from unittest.mock import patch

import highspy
import pulp

from .cli_three_day import BASE, ROOT, read, write

CONFIGURATIONS = {"slsqp": ("slsqp", None)}
CONFIGURATIONS.update(
    {
        f"{method}_{strategy}": (strategy, solvers)
        for method, solvers in (
            ("cbc", ("cbc", "cbc", "cbc")),
            ("highs_nutrition", ("cbc", "cbc", "highs")),
            ("highs_all", ("highs", "highs", "highs")),
        )
        for strategy in ("full", "adaptive_gap")
    }
)
MODULE = "helpful_scripts.nrc_ration_comparison.cli_solver_consolidation"


def trace():
    from RUFAS.biophysical.animal.pen import Pen
    from RUFAS.biophysical.animal.ration.linear_ration_optimizer import LinearRationOptimizer

    from .cli_three_day_trace import trace_cli

    output = Path(os.environ["RUFAS_EXPERIMENT_TRACE"])
    attempt = Pen._attempt_formulation
    solve = LinearRationOptimizer._solve_problem
    validate = LinearRationOptimizer.validate_nrc_candidate
    repair = LinearRationOptimizer._repair_nrc_rounding
    active = None

    def timed(attempted, phase, *args, **kwargs):
        started = perf_counter()
        result = attempted(*args, **kwargs)
        active[phase] += perf_counter() - started
        return result

    def solve_lp(config, problem, quantities, solver):
        if active is not None and "minimum_total_energy" in problem.constraints:
            active["nutritional_calls"] += 1
            active["nutritional_solver_names"].append(solver.name if solver is not None else "PULP_CBC_CMD")
            return timed(solve, "nutritional_lp_seconds", config, problem, quantities, solver)
        return solve(config, problem, quantities, solver)

    def validate_candidate(*args, **kwargs):
        if active is not None:
            return timed(validate, "validation_and_repair_seconds", *args, **kwargs)
        return validate(*args, **kwargs)

    def repair_candidate(*args, **kwargs):
        if active is not None:
            return timed(repair, "repair_seconds", *args, **kwargs)
        return repair(*args, **kwargs)

    def capture_attempt(pen, *args, **kwargs):
        nonlocal active
        if pen.animal_combination.value != "lac_cow":
            return attempt(pen, *args, **kwargs)
        active = Counter()
        active["nutritional_solver_names"] = []
        try:
            solution, config = attempt(pen, *args, **kwargs)
            phases = dict(active)
        finally:
            active = None
        if solution.ration_backend == "pulp":
            phases.update(
                reference_solver=solution.reference_solver,
                bound_solver=solution.bound_solver,
                nutritional_solver=solution.nutritional_solver,
                generation_seconds=sum(ref.generation_seconds for ref in solution.references),
                bound_seconds=solution.bound_seconds,
                bound_details=solution.bound_details,
            )
        phases["optimization_seconds"] = solution.ration_optimization_seconds
        with output.with_name("phases.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(phases) + "\n")
        return solution, config

    with (
        patch.object(Pen, "_attempt_formulation", capture_attempt),
        patch.object(LinearRationOptimizer, "_solve_problem", staticmethod(solve_lp)),
        patch.object(LinearRationOptimizer, "validate_nrc_candidate", staticmethod(validate_candidate)),
        patch.object(LinearRationOptimizer, "_repair_nrc_rounding", staticmethod(repair_candidate)),
    ):
        trace_cli(output)


def prepare(target, name, repetition):
    strategy, solvers = CONFIGURATIONS[name]
    folder = target / "inputs" / name / str(repetition)
    output = target / "runs" / name / str(repetition)
    paths = {
        "animal.json": folder / "animal.json",
        "metadata.json": folder / "metadata.json",
        "task.json": folder / "task.json",
        "task_manager.json": folder / "task_manager.json",
    }
    animal, metadata, task, task_manager = (read(BASE / "inputs" / strategy / f) for f in paths)
    if solvers is not None:
        for phase, solver in zip(("reference", "bound", "nutritional"), solvers, strict=True):
            animal["ration"][f"linear_{phase}_solver"] = solver
        assert animal["ration"]["linear_max_references"] == 5
        assert animal["ration"]["linear_gap_target"] == 0.05
    metadata["files"]["animal"]["path"] = paths["animal.json"].as_posix()
    for section in ("config", "feed"):
        metadata["files"][section]["path"] = (target / "inputs" / f"{section}.json").as_posix()
    task["tasks"][0].update(
        metadata_file_path=paths["metadata.json"].as_posix(),
        filters_directory=(target / "filters").as_posix(),
        json_output_directory=(output / "JSONs").as_posix(),
        csv_output_directory=(output / "CSVs").as_posix(),
    )
    task_manager["files"]["tasks"]["path"] = paths["task.json"].as_posix()
    for path, value in zip(paths.values(), (animal, metadata, task, task_manager), strict=True):
        write(path, value)
    return output, paths["task_manager.json"]


def run(output, task):
    output.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable,
        "-m",
        MODULE,
        "--trace",
        "-g",
        "-v",
        "logs",
        "-p",
        task.as_posix(),
        "-o",
        output.as_posix(),
        "-l",
        (output / "logs").as_posix(),
    ]
    env = {**os.environ, "RUFAS_EXPERIMENT_TRACE": str((output / "attempts.jsonl").resolve())}
    started = perf_counter()
    with (output / "console.log").open("w", encoding="utf-8") as console:
        process = subprocess.run(command, cwd=ROOT, env=env, stdout=console, stderr=subprocess.STDOUT, check=False)
    wall = perf_counter() - started
    completed = any(
        "Simulation completed" in log.read_text(encoding="utf-8", errors="replace") for log in output.rglob("*.log")
    )
    write(output / "run.json", {"wall_seconds": wall, "exit_code": process.returncode, "completed": completed})
    if process.returncode or not completed:
        raise RuntimeError(f"Simulation incomplete. Inspect {output / 'console.log'}")
    return wall


def json_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def collect(output, prices, name):
    # The historical summary is also callable as a standalone script.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from cli_three_day_summary import daily_metrics
    finally:
        sys.path.pop(0)

    outputs = list((output / "JSONs").glob("*.json"))
    assert len(outputs) == 1, outputs
    data = read(outputs[0])
    assert data["RufasTime.day"]["values"] == [150, 151, 152]
    daily = daily_metrics(data, prices)
    trace_rows = json_lines(output / "attempts.jsonl")
    phases = json_lines(output / "phases.jsonl")
    assert len(trace_rows) >= 3
    totals = {}
    cases = Counter()
    for day in daily:
        group = totals.setdefault(day["group"], {"cost": 0.0, "milk": 0.0, "dry_matter": 0.0})
        group["cost"] += day["applied_feed_at_input_prices_usd"]
        group["milk"] += day["daily_milk_kg"] or 0
        group["dry_matter"] += day["kg_dm_pen"]
    records = []
    expected_solvers = CONFIGURATIONS[name][1]
    for row, phase in zip(trace_rows, phases, strict=True):
        selected = row["applied_quantities"]
        if row["success"]:
            actual = next(d for d in daily if d["simulation_day"] == row["simulation_day"] and d["group"] == "LAC_COW")
            assert selected == actual["kg_dm_per_animal_by_feed"]
        if row["backend"] == "slsqp":
            if row["success"]:
                cases["original_nrc_raw_approved"] += not row["applied_nrc_check"]["unrounded"]["violations"]
                cases["original_nrc_raw_rejected"] += bool(row["applied_nrc_check"]["unrounded"]["violations"])
        else:
            names = {"cbc": "PULP_CBC_CMD", "highs": "HiGHS"}
            expected = [names[solver] for solver in expected_solvers]
            assert [phase[f"{step}_solver"] for step in ("reference", "bound", "nutritional")] == expected
            assert all(solver == expected[-1] for solver in phase.pop("nutritional_solver_names"))
            lp_cases = [case for ref in row["references"] for case in ref["cases"]]
            assert phase["nutritional_calls"] == len(lp_cases)
            assert row["solver_calls"] == 1 + len(lp_cases) + sum(ref["generation_calls"] for ref in row["references"])
            for case in lp_cases:
                cases[case["validation_status"] or case["lp_status"]] += 1
                val = case["validation"]
                if not val:
                    continue
                cases["raw_rejected"] += bool(val["unrounded"]["violations"])
                cases["repaired"] += bool(val.get("repair") and val["repair"]["quantities"] is not None)
            if row["success"]:
                ref = next(ref for ref in row["references"] if ref["source"] == row["selected_reference"])
                case = next(case for case in ref["cases"] if case["regime"] == row["selected_case"])
                val = case["validation"]
                approved = (val.get("repair") or {}).get("quantities") or val["rounded_quantities"]
                assert case["validation_status"] == "approved"
                assert approved == selected == row["selected_quantities"]
        records.append(
            {key: value for key, value in row.items() if key not in ("references", "optimization_seconds")}
            | {"references": [ref["source"] for ref in row.get("references", []) if ref["cases"]]}
        )
    timing = {"wall_seconds": read(output / "run.json")["wall_seconds"]}
    for key in (
        "optimization_seconds",
        "generation_seconds",
        "bound_seconds",
        "nutritional_lp_seconds",
        "validation_and_repair_seconds",
        "repair_seconds",
    ):
        timing[key] = (
            sum(phase.get(key, 0) for phase in phases) if expected_solvers or key == "optimization_seconds" else None
        )
    return {
        "days": [150, 151, 152],
        "group_totals": totals,
        "daily": daily,
        "attempts": records,
        "case_counts": dict(cases),
        "timings": timing,
        "attempt_phases": phases,
    }


def benchmark(target, runs, summarize_only):
    if not summarize_only:
        target.mkdir(parents=True, exist_ok=True)
        if any(target.iterdir()):
            raise ValueError("Use a new or empty output directory.")
        (target / "inputs").mkdir()
        for name in ("config.json", "feed.json", "preflight.json"):
            shutil.copyfile(BASE / "inputs" / name, target / "inputs" / name)
        shutil.copytree(BASE / "filters", target / "filters")
        metadata = read(BASE / "inputs/full/metadata.json")
        write(
            target / "manifest.json",
            {
                "runs": runs,
                "python": platform.python_version(),
                "pulp": pulp.__version__,
                "highspy": highspy.Highs().version(),
                "cbc": subprocess.check_output([pulp.PULP_CBC_CMD().path, "-quit"], text=True).splitlines()[1].strip(),
                "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "diff_sha256": hashlib.sha256(subprocess.check_output(["git", "diff", "HEAD"])).hexdigest(),
                "archived_inputs_sha256": {
                    k: hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
                    for k, item in metadata["files"].items()
                },
            },
        )
    feed = read(target / "inputs/feed.json")
    prices = {str(item["feed_type"]): item["purchased_feed_cost"] for item in feed["feeds"]}
    results = {name: [] for name in CONFIGURATIONS}
    names = list(CONFIGURATIONS)
    for repetition in range(1, runs + 1):
        offset = (repetition - 1) * 3 % len(names)
        for name in names[offset:] + names[:offset]:
            if summarize_only:
                output = target / "runs" / name / str(repetition)
            else:
                output, task = prepare(target, name, repetition)
                print(f"{repetition}/{runs} {name} started", flush=True)
                wall = run(output, task)
                print(f"{repetition}/{runs} {name} completed in {wall:.2f} s", flush=True)
            result = collect(output, prices, name)
            results[name].append(result)
            write(target / "progress.json", {key: len(rows) for key, rows in results.items()})
    summary = {}
    for name, rows in results.items():
        comparable = ("days", "group_totals", "attempts", "case_counts")
        first = rows[0]
        for row in rows[1:]:
            assert all(first[key] == row[key] for key in comparable), f"Outcome varied across repetitions: {name}"
        summary[name] = {
            **{key: first[key] for key in (*comparable, "daily")},
            "timings": [row["timings"] for row in rows],
            "attempt_phases_by_repetition": [row["attempt_phases"] for row in rows],
            "median_timings": {
                key: median(row["timings"][key] for row in rows) if value is not None else None
                for key, value in first["timings"].items()
            },
        }
    write(target / "comparison.json", summary)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--trace":
        del sys.argv[1]
        trace()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/nrc_solver_consolidation"))
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--summarize-only", action="store_true")
    args = parser.parse_args()
    benchmark(args.output, args.runs, args.summarize_only)


if __name__ == "__main__":
    main()
