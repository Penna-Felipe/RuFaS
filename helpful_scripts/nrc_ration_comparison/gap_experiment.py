"""Audit the NRC cost floor and compare lazy stopping rules in the 12 saved scenarios."""

import argparse
import json
import random
import re
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from RUFAS.biophysical.animal.ration.linear_cost_bound import (
    ROWS as ROWS,
    dual_bound as dual_bound,
    meets_target,
    primary_lower_bound as _primary_lower_bound,
    relative_gap,
)
from RUFAS.biophysical.animal.ration.ration_optimizer import RationConfig

from .adaptive import annotate, evaluate_strategy, scenario_grid
from .compare import TimedCBC, json_safe
from .multireference import run_slsqp
from .sensitivity import make_config, time_summary

TARGETS = (1, 3, 5, 10)


def primary_lower_bound(config: RationConfig) -> dict[str, Any]:
    return _primary_lower_bound(config, TimedCBC())


def cost_gap(cost: float | None, bound: dict[str, Any]) -> dict[str, Any]:
    gap, status = relative_gap(cost, bound["lower_bound"])
    return {"cost": cost, "relative_gap": gap, "gap_status": status}


def solver_counts(refs: dict[str, Any], bound_calls: int) -> dict[str, int]:
    generation = 0
    nutrition = 0
    for ref in refs.values():
        calls = ref.get("generation", {}).get("lp_calls")
        if calls is None:
            failure = re.search(r"objective (\d+):", ref.get("generator_error", ""))
            calls = int(failure[1]) + 1 if failure else 0
        generation += calls
        nutrition += len(ref.get("cases", []))
    return {
        "generation": generation,
        "nutrition": nutrition,
        "bound": bound_calls,
        "total": generation + nutrition + bound_calls,
    }


def run_policy(
    config: RationConfig, midwest: dict[int, float], strategy: str, target: float | None
) -> tuple[dict[str, Any], dict[str, float]]:
    start = perf_counter()
    bound = primary_lower_bound(config) if target is not None else None
    bound_seconds = perf_counter() - start if bound is not None else 0.0
    stop = None
    if target is not None and bound is not None:
        stop = lambda cost: meets_target(cost, bound["lower_bound"], target)
    outcome, timings = evaluate_strategy(config, midwest, strategy, stop_cost=stop)
    refs = outcome["references"]
    selected = outcome["selected"]
    outcome["references_attempted"] = len(refs)
    outcome["references_resolved"] = sum("cases" in ref for ref in refs.values())
    outcome["solver_calls"] = solver_counts(refs, int(bound is not None))
    if stop is not None:
        outcome["stop_reason"] = (
            "target_reached" if selected is not None and stop(selected["cost"]) else "references_exhausted"
        )
    return outcome, {**timings, "lower_bound": bound_seconds, "full": perf_counter() - start}


def slsqp_with_repair(inputs: dict[str, Any], seed: int) -> tuple[dict[str, Any], dict[str, float]]:
    state = random.getstate()
    random.seed(seed)
    try:
        report, timings = run_slsqp(inputs, {}, repair_rounding=True)
    finally:
        random.setstate(state)
    validation = report["validation"]
    report.update(
        {
            "seed": seed,
            "raw_approved": not validation["unrounded"]["violations"],
            "rounded_approved": validation["rounded"] is not None and not validation["rounded"]["violations"],
            "repair_approved": validation["repair"] is not None and validation["repair"]["quantities"] is not None,
            "solver_calls": {"total": 1},
            "references_attempted": 0,
            "references_resolved": 0,
        }
    )
    return report, {**timings, "full": timings["attempt_with_setup"] + timings["validation"]}


def audit_existing(old: dict[str, Any], bound: dict[str, Any]) -> dict[str, Any]:
    records = {}
    for name in ("adaptive", "full"):
        strategy = old["strategies"][name]
        selected = strategy["selected"]
        approved_cases = []
        for reference_name, reference in strategy["references"].items():
            for case in reference.get("cases", []):
                if case["validation_status"] != "approved":
                    continue
                quantities = case["rounded_or_repaired"]["quantities"]
                cost = sum(
                    amount * old["scenario"]["feeds"][feed_id]["usd_per_kg_dm"]
                    for feed_id, amount in quantities.items()
                )
                approved_cases.append({"reference": reference_name, "case": case["case"], **cost_gap(cost, bound)})
        records[name] = {**cost_gap(selected["cost"] if selected else None, bound), "approved_cases": approved_cases}
    raw = old["slsqp"]
    raw_approved = not raw["validation"]["unrounded"]["violations"]
    records["slsqp"] = {
        "raw": cost_gap(raw["raw_cost"] if raw_approved else None, bound),
        "rounded": cost_gap(raw["final_cost"], bound),
        "converged": raw["success"],
    }
    return records


def experiment(runs: int) -> dict[str, Any]:
    previous = json.loads(Path(__file__).with_name("adaptive_results.json").read_text(encoding="utf-8"))
    records = {}
    for name, inputs, reference, metadata in scenario_grid():
        old = previous["scenarios"][name]
        if json.loads(json.dumps(json_safe(metadata))) != old["scenario"]:
            raise ValueError(f"Inputs differ from adaptive_results.json for {name}.")
        config = make_config(inputs)
        bound = primary_lower_bound(config)
        policies = {}
        modes = [(mode, mode, None) for mode in ("single", "adaptive", "full")]
        modes += [(f"gap_{goal}", "full", goal / 100) for goal in TARGETS]
        for label, strategy, target in modes:
            samples = [run_policy(config, reference, strategy, target) for _ in range(runs)]
            result = samples[0][0]
            annotate(config, result)
            selected = result["selected"]
            policies[label] = {
                **result,
                **cost_gap(selected["cost"] if selected else None, bound),
                "timings_seconds": time_summary([timing for _, timing in samples]),
            }
        seed = old["slsqp"]["seed"]
        originals = [slsqp_with_repair(inputs, seed) for _ in range(runs)]
        slsqp = originals[0][0]
        slsqp = {
            **slsqp,
            **cost_gap(slsqp["final_cost"] if slsqp["success"] else None, bound),
            "timings_seconds": time_summary([timing for _, timing in originals]),
        }
        full_cost = policies["full"]["cost"]
        for row in (*policies.values(), slsqp):
            row["usd_above_full"] = (
                row["cost"] - full_cost if full_cost is not None and row["cost"] is not None else None
            )
        records[name] = {
            "lower_bound": bound,
            "existing": audit_existing(old, bound),
            "policies": {**policies, "slsqp": slsqp},
        }

    summary = {}
    for label in next(iter(records.values()))["policies"]:
        rows = [entry["policies"][label] for entry in records.values()]
        differences = [row["usd_above_full"] for row in rows if row["usd_above_full"] is not None]
        summary[label] = {
            "approved": sum(row["cost"] is not None for row in rows),
            "median_full_seconds": median(row["timings_seconds"]["full"]["median"] for row in rows),
            "median_solver_calls": median(row["solver_calls"]["total"] for row in rows),
            "median_references_resolved": median(row["references_resolved"] for row in rows),
            "targets_reached": sum(row.get("stop_reason") == "target_reached" for row in rows),
            "max_usd_above_full": max(differences, default=None),
        }
    return {"runs": runs, "seed": previous["seed"], "summary": summary, "scenarios": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    output = json.dumps(json_safe(experiment(args.runs)), indent=2, allow_nan=False) + "\n"
    if args.output is None:
        print(output, end="")
    else:
        args.output.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
