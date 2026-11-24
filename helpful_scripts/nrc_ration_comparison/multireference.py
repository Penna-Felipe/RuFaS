"""Test multiple fixed NRC references in the isolated RuFaS example.

    python -m helpful_scripts.nrc_ration_comparison.multireference --output helpful_scripts/nrc_ration_comparison/multireference_results.json

Install RuFaS with .[linear_ration]. Optionally pass --previous-ration with a
JSON object mapping feed IDs to kg DM per cow per day. The example snapshot
itself has no historical ration. The SLSQP result is used only for comparison.
"""

import argparse
import json
from collections.abc import Mapping
from dataclasses import asdict
from math import isfinite
from pathlib import Path
from time import perf_counter
from typing import Any
from unittest.mock import patch

import pulp

from RUFAS.biophysical.animal.ration import ration_optimizer
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import LinearRationOptimizer
from RUFAS.biophysical.animal.ration.ration_optimizer import RationConfig
from RUFAS.biophysical.animal.ration.linear_reference import (
    OBJECTIVES as OBJECTIVES,
    build_basic_reference,
    grid_key as grid_key,
    reference_issue as reference_issue,
)

from .compare import DATA, TimedCBC, TimedLinearOptimizer, build_experiment, json_safe
from .sensitivity import add_diet_metrics, make_config, time_summary


def basic_reference(config: RationConfig, goal: str) -> tuple[dict[int, float], dict[str, Any]]:
    solver = TimedCBC()
    quantities, metrics = build_basic_reference(config, goal, solver)
    return quantities, {**metrics, "cbc_seconds": solver.elapsed}


def external_recipes(config: RationConfig) -> tuple[dict[str, dict[int, float]], list[dict[str, Any]]]:
    recipes = {}
    audit = []
    for path in sorted((DATA / "feed").glob("*.json")):
        content = json.loads(path.read_text(encoding="utf-8"))
        ration = next((r for r in content.get("rations", []) if r["animal_combination"] == "lac_cow"), None)
        feeds = ration["feeds"] if ration else []
        if not feeds or any(feed.get("ration_percentage") is None for feed in feeds):
            audit.append({"file": path.name, "explicit_percentages": False, "included": False})
            continue

        percentages = {feed["feed_type"]: feed["ration_percentage"] for feed in feeds}
        if len(percentages) != len(feeds) or any(not isfinite(p) or p < 0 for p in percentages.values()):
            issue = "Invalid or repeated recipe percentages."
        elif sum(percentages.values()) <= 0:
            issue = "Recipe has no positive inclusion."
        else:
            ration_kg = {
                feed_id: config.initial_dry_matter_requirement * proportion / sum(percentages.values())
                for feed_id, proportion in percentages.items()
                if proportion > 0
            }
            issue = reference_issue(config, ration_kg)
            if issue is None:
                recipes[f"recipe_{path.stem}"] = ration_kg

        audit.append(
            {
                "file": path.name,
                "explicit_percentages": True,
                "percentages": percentages,
                "included": issue is None,
                "reason": issue,
            }
        )
    return recipes, audit


class PhaseTimedOptimizer(TimedLinearOptimizer):
    def __init__(self) -> None:
        super().__init__()
        self.coefficient_seconds = 0.0

    def calculate_nrc_energy_coefficients(self, config: RationConfig, reference_ration: Mapping[int, float]) -> Any:
        start = perf_counter()
        try:
            return super().calculate_nrc_energy_coefficients(config, reference_ration)
        finally:
            self.coefficient_seconds += perf_counter() - start

    def calculate_nrc_protein_coefficients(self, config: RationConfig, reference_ration: Mapping[int, float]) -> Any:
        start = perf_counter()
        try:
            return super().calculate_nrc_protein_coefficients(config, reference_ration)
        finally:
            self.coefficient_seconds += perf_counter() - start


def run_reference(config: RationConfig, reference: dict[int, float]) -> tuple[dict[str, Any], dict[str, float]]:
    optimizer = PhaseTimedOptimizer()
    solver = TimedCBC()
    start = perf_counter()
    selection = optimizer.solve_and_validate_nrc_cases(config, reference, solver)
    total = perf_counter() - start
    validations = selection.validations
    report = {
        "cases": [
            {
                "case": case,
                **asdict(result),
                "validation_status": validations[case].status if case in validations else None,
                "validation": asdict(validations[case]) if case in validations else None,
            }
            for case, result in selection.cases.items()
        ],
        "selected_case": selection.selected_case,
        "selected_cost": selection.selected_cost,
        "message": selection.message,
    }
    return report, {
        "coefficients": optimizer.coefficient_seconds,
        "lp_model_and_bookkeeping": optimizer.model_and_solve - optimizer.coefficient_seconds - solver.elapsed,
        "cbc_all_six_cases": solver.elapsed,
        "validation_repair_selection": total - optimizer.model_and_solve,
        "full": total,
    }


def run_slsqp(
    inputs: dict[str, Any], start_diet: dict[int, float], *, repair_rounding: bool = False
) -> tuple[dict[str, Any], dict[str, float]]:
    minimize = ration_optimizer.minimize
    solver_elapsed = 0.0

    def timed_minimize(*args: Any, **kwargs: Any) -> Any:
        nonlocal solver_elapsed
        start = perf_counter()
        try:
            return minimize(*args, **kwargs)
        finally:
            solver_elapsed = perf_counter() - start

    with patch.object(ration_optimizer, "minimize", timed_minimize):
        start = perf_counter()
        result, config = ration_optimizer.RationOptimizer().attempt_optimization(**inputs, previous_ration=start_diet)
        attempt = perf_counter() - start
    diet = {feed.rufas_id: float(amount) for feed, amount in zip(config.feeds_used, result.x, strict=True)}
    start = perf_counter()
    validation = LinearRationOptimizer.validate_nrc_candidate(config, diet, repair_rounding=repair_rounding)
    validation_elapsed = perf_counter() - start
    final = validation.final_quantities
    return {
        "success": bool(result.success),
        "status": int(result.status),
        "message": str(result.message),
        "iterations": int(result.nit),
        "quantities": diet,
        "raw_cost": float(result.fun),
        "validation_status": validation.status,
        "validation": asdict(validation),
        "final_cost": sum(final[feed.rufas_id] * feed.purchase_cost for feed in config.feeds_used) if final else None,
        "final_dmi": sum(final.values()) if final else None,
    }, {"slsqp_minimize": solver_elapsed, "attempt_with_setup": attempt, "validation": validation_elapsed}


def select_distinct(
    references: dict[str, dict[str, Any]], feed_ids: list[int]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    unique = {}
    best = None
    for name, reference in references.items():
        new = 0
        duplicates = 0
        previous_best = best["diet"]["cost_usd_per_cow_day"] if best else None
        for case in reference["cases"]:
            if json_safe(case["validation_status"]) != "approved":
                continue
            diet = case.get("repaired_diet", case["rounded_diet"])
            key = grid_key(diet["quantities"], feed_ids)
            source = {"reference": name, "case": case["case"]}
            if key in unique:
                duplicates += 1
                unique[key]["sources"].append(source)
                continue
            validation = case["validation"]
            final_check = validation["repair"]["validation"] if "repaired_diet" in case else validation["rounded"]
            entry = {"diet": diet, "validation": final_check, "sources": [source]}
            unique[key] = entry
            new += 1
            if best is None or diet["cost_usd_per_cow_day"] < best["diet"]["cost_usd_per_cow_day"]:
                best = entry

        current_best = best["diet"]["cost_usd_per_cow_day"] if best else None
        reference["contribution"] = {
            "new_approved_diets": new,
            "approved_duplicate_cases": duplicates,
            "best_cost_before": previous_best,
            "best_cost_after": current_best,
        }
    return list(unique.values()), best


def experiment(runs: int, previous_ration: dict[int, float] | None = None) -> dict[str, Any]:
    inputs, midwest, scenario = build_experiment()
    config = make_config(inputs)
    feed_ids = sorted(feed.rufas_id for feed in config.feeds_used)

    start = perf_counter()
    recipes, recipe_audit = external_recipes(config)
    raw_references = {"midwest": midwest}
    generation = {}
    for goal in OBJECTIVES:
        start_goal = perf_counter()
        raw_references[goal], metrics = basic_reference(config, goal)
        generation[goal] = {**metrics, "total_seconds": perf_counter() - start_goal}
    raw_references.update(recipes)
    previous_reason = "No previous pen ration was supplied in the isolated snapshot."
    if previous_ration is not None:
        previous_reason = reference_issue(config, previous_ration)
        if previous_reason is None:
            raw_references["previous_ration"] = previous_ration
    generation_elapsed = perf_counter() - start

    # Build and freeze all independent references before calling SLSQP.
    references = {}
    sources = {}
    known = {}
    for name, quantities in raw_references.items():
        issue = reference_issue(config, quantities)
        if issue is not None:
            raise ValueError(f"{name}: {issue}")
        key = grid_key(quantities, feed_ids)
        if key not in known:
            known[key] = name
            references[name] = quantities
        sources[name] = {"quantities": quantities, "executed_as": known[key]}

    slsqp_runs = [run_slsqp(inputs, midwest) for _ in range(runs)]
    slsqp = slsqp_runs[0][0]
    reports = {}
    for name, reference in references.items():
        measured = [run_reference(config, reference) for _ in range(runs)]
        report = measured[0][0]
        expected = json_safe(report)
        stable = all(json_safe(result) == expected for result, _ in measured)
        add_diet_metrics(config, report, reference, slsqp)
        reference_check = LinearRationOptimizer.validate_nrc_candidate(config, reference)
        reports[name] = {
            **report,
            "reference_nrc_status": reference_check.status,
            "reference_nrc_validation": asdict(reference_check),
            "timings_seconds": time_summary([times for _, times in measured]),
            "repeated_results_match": stable,
        }
    distinct, selected = select_distinct(reports, feed_ids)
    # Sum the phases across distinct references for each repeat before taking
    # medians. Generation is a one-time measurement, reported separately.
    combined_timing = time_summary(
        [
            {
                phase: sum(report["timings_seconds"][phase]["samples"][i] for report in reports.values())
                for phase in reports["midwest"]["timings_seconds"]
            }
            for i in range(runs)
        ]
    )
    return {
        "scenario": scenario,
        "runs": runs,
        "recipe_audit": recipe_audit,
        "previous_ration_skipped_reason": previous_reason,
        "reference_sources": sources,
        "reference_generation": {"total_seconds": generation_elapsed, "by_objective": generation},
        "slsqp": {**slsqp, "timings_seconds": time_summary([timing for _, timing in slsqp_runs])},
        "references": reports,
        "multi_reference_timings_seconds": combined_timing,
        "unique_approved_diets": distinct,
        "selected": selected,
        "selection_message": (
            "No candidate passed NRC validation." if selected is None else "Approved candidate selected."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--previous-ration", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    previous = None
    if args.previous_ration is not None:
        previous = {
            int(key): float(value)
            for key, value in json.loads(args.previous_ration.read_text(encoding="utf-8")).items()
        }
    output = json.dumps(json_safe(experiment(args.runs, previous)), indent=2, allow_nan=False) + "\n"
    if args.output is None:
        print(output, end="")
    else:
        args.output.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
