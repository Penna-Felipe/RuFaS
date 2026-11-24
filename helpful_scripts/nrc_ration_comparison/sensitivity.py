"""Isolated NRC fixed-coefficient sensitivity experiment.

Run from the repository root after installing RuFaS with .[linear_ration].

    python -m helpful_scripts.nrc_ration_comparison.sensitivity --runs 5 --output helpful_scripts/nrc_ration_comparison/sensitivity_results.json

The comparison uses one fixed scenario. Timings exclude error analysis and
report construction. Error percentages are absolute errors divided by the
absolute NRC result, and are null when the NRC result is zero.
"""

import argparse
import json
import platform
from collections.abc import Mapping
from dataclasses import asdict
from math import isclose
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

import numpy as np
import pulp
import scipy

from RUFAS.biophysical.animal.nutrients.nutrition_supply_calculator import NutritionSupplyCalculator
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import (
    LinearRationOptimizer,
    NRCEnergyCoefficients,
    NRCProteinCoefficients,
)
from RUFAS.biophysical.animal.ration.ration_optimizer import RationConfig, RationOptimizer
from RUFAS.data_structures.feed_storage_to_animal_connection import FeedComponentType

from .compare import TimedCBC, TimedLinearOptimizer, build_experiment, compare_once, json_safe

ENERGY_FIELDS = ("maintenance", "growth", "lactation")


def error_metrics(predicted: float, nrc: float, unit: str) -> dict[str, float | str | None]:
    signed = predicted - nrc
    return {
        "unit": unit,
        "predicted": predicted,
        "nrc": nrc,
        "signed_error": signed,
        "absolute_error": abs(signed),
        "relative_error_percent": 100 * abs(signed) / abs(nrc) if nrc != 0 else None,
    }


def protein_offers(
    quantities: Mapping[int, float], coefficients: Mapping[int, NRCProteinCoefficients]
) -> dict[str, float]:
    tdn = sum(amount * coefficients[feed_id].microbial_tdn for feed_id, amount in quantities.items())
    rdp = sum(amount * coefficients[feed_id].microbial_rdp for feed_id, amount in quantities.items())
    rup = sum(amount * coefficients[feed_id].digestible_rup for feed_id, amount in quantities.items())
    endogenous = NRCProteinCoefficients.ENDOGENOUS_PER_KG_DRY_MATTER * sum(quantities.values())
    microbial = NRCProteinCoefficients.MICROBIAL_METABOLIZABLE_FRACTION * min(tdn, rdp)
    return {
        "microbial_tdn": tdn,
        "microbial_rdp": rdp,
        "microbial_metabolizable": microbial,
        "digestible_rup": rup,
        "endogenous": endogenous,
        "metabolizable_protein": rup + endogenous + microbial,
    }


def nutrient_errors(
    config: RationConfig,
    candidate: Mapping[int, float],
    energy: Mapping[int, NRCEnergyCoefficients],
    protein: Mapping[int, NRCProteinCoefficients],
) -> dict[str, Any]:
    vector = np.array([candidate.get(feed.rufas_id, 0.0) for feed in config.feeds_used])
    feeds, discount, de, me = RationOptimizer._calculate_NE_parameters(vector, config)
    calculator = NutritionSupplyCalculator
    energy_nrc = {
        "maintenance": calculator.calculate_actual_maintenance_net_energy(feeds, me),
        "growth": calculator.calculate_actual_growth_net_energy(feeds, me),
        "lactation": calculator.calculate_actual_lactation_net_energy(feeds, me, de),
    }
    errors = {}
    for field in ENERGY_FIELDS:
        predicted = sum(amount * getattr(energy[feed_id], field) for feed_id, amount in candidate.items())
        errors[f"energy_{field}"] = error_metrics(predicted, float(energy_nrc[field]), "Mcal/cow/day")

    predicted_protein = protein_offers(candidate, protein)
    # The original calculator returns only the total. Recompute its component
    # coefficients on the candidate itself (with original discount and passage
    # functions) to expose the native NRC components before summing them.
    fresh = LinearRationOptimizer.calculate_nrc_protein_coefficients(config, candidate)
    protein_nrc = protein_offers(candidate, fresh)
    original_total, _ = RationOptimizer._calculate_protein_constraint_parameters(
        vector, config, use_initial_requirement=False
    )
    if not isclose(protein_nrc["metabolizable_protein"], original_total, rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError("Recomputed protein components disagree with original NRC protein supply.")
    protein_nrc["metabolizable_protein"] = float(original_total)
    for field, predicted in predicted_protein.items():
        errors[field] = error_metrics(predicted, protein_nrc[field], "g/cow/day")

    def limiter(offers: dict[str, float]) -> str:
        if isclose(offers["microbial_tdn"], offers["microbial_rdp"], rel_tol=1e-9, abs_tol=1e-6):
            return "tie"
        return "tdn" if offers["microbial_tdn"] < offers["microbial_rdp"] else "rdp"

    return {
        "offers": errors,
        "predicted_microbial_limiter": limiter(predicted_protein),
        "nrc_microbial_limiter": limiter(protein_nrc),
        "nrc_intake_discount": float(discount),
    }


def forage_weighted_reference(config: RationConfig, original: Mapping[int, float]) -> dict[int, float]:
    """Double forage weights and renormalize to the original dry matter intake."""
    weights = {
        feed.rufas_id: original[feed.rufas_id] * (2 if feed.feed_type is FeedComponentType.FORAGE else 1)
        for feed in config.feeds_used
    }
    scale = sum(original.values()) / sum(weights.values())
    return {feed_id: amount * scale for feed_id, amount in weights.items()}


def make_config(inputs: dict[str, Any]) -> RationConfig:
    return RationConfig(
        inputs["nutrient_standard"],
        inputs["requirements"],
        inputs["pen_available_feeds"],
        inputs["initial_dry_matter_requirement"],
        inputs["initial_protein_requirement"],
        inputs["pen_average_body_weight"],
        inputs["pen_average_enteric_methane"],
        inputs["pen_average_urine_nitrogen"],
        inputs["animal_combination"],
    )


def check_reference_bounds(config: RationConfig, reference: Mapping[int, float]) -> None:
    for feed, lower, upper in zip(config.feeds_used, config.feed_minimum_list, config.feed_maximum_list, strict=True):
        if not lower <= reference[feed.rufas_id] <= upper:
            raise ValueError(f"Reference feed {feed.rufas_id} outside its shared inclusion limits.")


def time_summary(samples: list[dict[str, float]]) -> dict[str, Any]:
    return {
        name: {"median": median(sample[name] for sample in samples), "samples": [sample[name] for sample in samples]}
        for name in samples[0]
    }


def run_alternative(config: RationConfig, reference: dict[int, float]) -> tuple[dict[str, Any], dict[str, float]]:
    optimizer = TimedLinearOptimizer()
    cbc = TimedCBC()
    start = perf_counter()
    selection = optimizer.solve_and_validate_nrc_cases(config, reference, cbc)
    full = perf_counter() - start
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
        "cbc_all_cases_solver_calls": cbc.elapsed,
        "pulp_coefficients_model_and_solve": optimizer.model_and_solve,
        "pulp_validation_and_selection": full - optimizer.model_and_solve,
        "pulp_full": full,
    }


def add_diet_metrics(
    config: RationConfig, report: dict[str, Any], reference: dict[int, float], slsqp: dict[str, Any]
) -> None:
    energy = LinearRationOptimizer.calculate_nrc_energy_coefficients(config, reference)
    protein = LinearRationOptimizer.calculate_nrc_protein_coefficients(config, reference)

    def summarize(quantities: dict[int, float]) -> dict[str, Any]:
        cost = sum(
            quantities.get(feed.rufas_id, 0.0) * price
            for feed, price in zip(config.feeds_used, config.price_list, strict=True)
        )
        return {
            "quantities": quantities,
            "dry_matter_kg_per_cow_day": sum(quantities.values()),
            "cost_usd_per_cow_day": cost,
            **nutrient_errors(config, quantities, energy, protein),
        }

    report["coefficients"] = {
        "energy_mcal_per_kg_dm": {key: asdict(value) for key, value in energy.items()},
        "protein_g_per_kg_dm": {key: asdict(value) for key, value in protein.items()},
        "endogenous_g_per_kg_dm": NRCProteinCoefficients.ENDOGENOUS_PER_KG_DRY_MATTER,
    }
    report["reference"] = summarize(reference)
    report["slsqp_same_reference_coefficients"] = {
        "raw": summarize(slsqp["quantities"]),
        "rounded": summarize(slsqp["validation"]["rounded_quantities"]),
    }
    for case in report["cases"]:
        if case["validation"] is None:
            continue
        validation = case["validation"]
        case["raw_diet"] = summarize(case["quantities"])
        if validation["rounded_quantities"] is not None:
            case["rounded_diet"] = summarize(validation["rounded_quantities"])
        repair = validation["repair"]
        if repair is not None and repair["quantities"] is not None:
            case["repaired_diet"] = summarize(repair["quantities"])
    report["counts"] = {
        key: sum(json_safe(case["status"]) == key for case in report["cases"])
        for key in ("optimal", "infeasible", "solver_error")
    } | {
        key: sum(json_safe(case["validation_status"]) == key for case in report["cases"])
        for key in ("approved", "rejected")
    }


def compare_references(runs: int) -> dict[str, Any]:
    inputs, original, scenario = build_experiment()
    config = make_config(inputs)
    baseline = [compare_once(inputs, original) for _ in range(runs)]
    baseline_result = baseline[0][0]
    slsqp = baseline_result["slsqp"]
    benchmark = time_summary([timing for _, timing in baseline])
    references = (
        ("midwest_original", "Retained Midwest proportions normalized to predicted DMI.", original),
        (
            "forage_weighted",
            "Double forage proportions then normalize to the same DMI.",
            forage_weighted_reference(config, original),
        ),
        ("slsqp_diagnostic", "Raw SLSQP optimum as reference; not an independent comparison.", slsqp["quantities"]),
    )

    results = {}
    for name, description, reference in references:
        check_reference_bounds(config, reference)
        if name == "midwest_original":
            report = baseline_result["pulp"]
            timings = {key: value for key, value in benchmark.items() if not key.startswith("slsqp")}
            repeats = [result["pulp"] for result, _ in baseline]
        else:
            measured = [run_alternative(config, reference) for _ in range(runs)]
            report = measured[0][0]
            timings = time_summary([timing for _, timing in measured])
            repeats = [result for result, _ in measured]
        portable = json_safe(report)
        stable = all(json_safe(candidate_report) == portable for candidate_report in repeats)
        add_diet_metrics(config, report, reference, slsqp)
        results[name] = {
            **report,
            "description": description,
            "timings_seconds": timings,
            "repeated_results_match": stable,
        }

    return {
        "versions": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "pulp": pulp.__version__,
        },
        "scenario": scenario,
        "shared_dmi_constraint_fraction": config.dmi_constraint_fraction,
        "runs": runs,
        "slsqp": {
            **slsqp,
            "dry_matter_kg_per_cow_day": sum(slsqp["quantities"].values()),
            "timings_seconds": {key: value for key, value in benchmark.items() if key.startswith("slsqp")},
            "repeated_results_match": all(json_safe(result["slsqp"]) == json_safe(slsqp) for result, _ in baseline),
        },
        "references": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    payload = json.dumps(json_safe(compare_references(args.runs)), indent=2, allow_nan=False) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
