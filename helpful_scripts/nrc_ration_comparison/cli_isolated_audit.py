"""Replay the recorded NRC lactating pen formulations without running the simulation."""

import argparse
import json
import random
from dataclasses import asdict
from math import isclose
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.optimize import linprog

from RUFAS.biophysical.animal.animal_module_constants import AnimalModuleConstants as Constants
from RUFAS.biophysical.animal.data_types.animal_combination import AnimalCombination
from RUFAS.biophysical.animal.data_types.nutrition_data_structures import NutritionRequirements
from RUFAS.biophysical.animal.nutrients.nutrition_supply_calculator import NutritionSupplyCalculator
from RUFAS.biophysical.animal.ration.amino_acid import EssentialAminoAcidRequirements
from RUFAS.biophysical.animal.ration.linear_cost_bound import ROWS, relative_gap
from RUFAS.biophysical.animal.ration.linear_ration_adapter import LinearRationAdapter
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import LinearRationOptimizer
from RUFAS.biophysical.animal.ration.linear_reference import OBJECTIVES, build_basic_reference, reference_issue
from RUFAS.biophysical.animal.ration.ration_manager import RationManager
from RUFAS.biophysical.animal.ration.ration_optimizer import RationOptimizer
from RUFAS.data_structures.feed_storage_to_animal_connection import AvailableFeedsBuilder, NutrientStandard
from RUFAS.input_manager import InputManager

from .cli_three_day import BASE, ROOT, read, write
from .compare import DATA, json_safe, read_json
from .sensitivity import ENERGY_FIELDS, make_config, nutrient_errors, protein_offers

MODES = ("full", "adaptive_gap", "single", "slsqp")
TRACE = Path("output/nrc_cli_three_day_diagnostic")
VALIDATE = LinearRationOptimizer.validate_nrc_candidate


def quantities(raw):
    return {int(key): value for key, value in (raw or {}).items()}


def vector(config, diet):
    return np.array([diet.get(feed.rufas_id, 0.0) for feed in config.feeds_used])


def load_feeds(feed_configuration):
    inputs = InputManager()
    original = inputs.pool
    inputs.pool = {**original, "NRC_Comp": inputs._load_data_from_csv(DATA / "feed/NRC_comp.csv")}
    try:
        return {
            feed.rufas_id: feed
            for feed in AvailableFeedsBuilder.setup_available_feeds(feed_configuration, NutrientStandard.NRC)
        }
    finally:
        inputs.pool = original


def inputs_for(row, initial, weight, feeds):
    requirement = row["requirements"].copy()
    requirement["essential_amino_acids"] = EssentialAminoAcidRequirements(**requirement["essential_amino_acids"])
    return {
        "nutrient_standard": NutrientStandard.NRC,
        "pen_average_body_weight": weight,
        "pen_average_enteric_methane": None,
        "pen_average_urine_nitrogen": None,
        "requirements": NutritionRequirements(**requirement),
        "initial_dry_matter_requirement": initial["requirements"]["dry_matter"],
        "initial_protein_requirement": initial["requirements"]["metabolizable_protein"],
        "pen_available_feeds": [feeds[feed_id] for feed_id in row["available_ids"]],
        "animal_combination": AnimalCombination.LAC_COW,
    }


def check_reconstruction(config, row):
    observations = []
    for ref in row.get("references", []):
        for case in ref["cases"]:
            if case["validation"] is not None:
                observations.append((case["lp_quantities"], case["validation"]["unrounded"]["residuals"]))
    if row.get("applied_nrc_check"):
        observations.append((row["applied_quantities"], row["applied_nrc_check"]["unrounded"]["residuals"]))
    differences = {}
    for diet, expected in observations:
        actual = VALIDATE(config, quantities(diet)).unrounded.residuals
        for key, value in expected.items():
            differences[key] = max(differences.get(key, 0), abs(actual[key] - value))
            if not isclose(actual[key], value, abs_tol=1e-9, rel_tol=1e-12):
                raise ValueError(f"Reconstruction disagrees with the recorded residual: {key}.")
    return {"recorded_diets_checked": len(observations), "max_residual_difference_by_constraint": differences}


def validate_slsqp(inputs, previous, seed):
    random.seed(seed)
    start = perf_counter()
    result, config = RationOptimizer().attempt_optimization(**inputs, previous_ration=previous)
    seconds = perf_counter() - start
    diet = {feed.rufas_id: float(amount) for feed, amount in zip(config.feeds_used, result.x, strict=True)}
    validation = VALIDATE(config, diet, repair_rounding=True)
    final = validation.final_quantities
    return {
        "seed": seed,
        "used_previous_ration": bool(previous),
        "status": int(result.status),
        "converged": bool(result.success),
        "message": result.message,
        "iterations": int(result.nit),
        "solver_seconds": seconds,
        "raw": diet,
        "raw_cost": float(result.fun),
        "validation": asdict(validation),
        "validation_status": validation.status.value,
        "final": final,
        "final_cost": RationOptimizer.objective(vector(config, final), config) if final else None,
    }


def factors(config, diet):
    calc = NutritionSupplyCalculator
    dmi = sum(diet.values())
    feeds, discount, _, _ = RationOptimizer._calculate_NE_parameters(vector(config, diet), config)
    concentrate = calc._calculate_percentage_of_concentrates(feeds, dmi)
    return {
        "tdn_original_percent": sum(feed.amount * feed.info.TDN for feed in feeds) / dmi,
        "tdn_intake_discount": discount,
        "concentrate_percent": concentrate,
        "passage_percent_per_hour": calc._calculate_protein_passage_rates(
            feeds, dmi, config.pen_average_body_weight, concentrate
        ),
    }


def protein_attribution(offers):
    tdn, rdp = (offers["microbial_" + key] for key in ("tdn", "rdp"))
    t, r, nt, nr = tdn["predicted"], rdp["predicted"], tdn["nrc"], rdp["nrc"]
    # Symmetric allocation averages the two paths for replacing the branches of min().
    components = {
        "microbial_tdn": 0.32 * (min(t, r) - min(nt, r) + min(t, nr) - min(nt, nr)),
        "microbial_rdp": 0.32 * (min(t, r) - min(t, nr) + min(nt, r) - min(nt, nr)),
        "digestible_rup": offers["digestible_rup"]["signed_error"],
        "endogenous": offers["endogenous"]["signed_error"],
    }
    assert isclose(sum(components.values()), offers["metabolizable_protein"]["signed_error"], abs_tol=1e-8)
    return components


def audit_diet(config, diet, energy, protein, regime):
    errors = nutrient_errors(config, diet, energy, protein)
    offers = errors["offers"]
    energy_minima = {
        "maintenance": config.animal_requirements.maintenance_energy + config.animal_requirements.activity_energy,
        "growth": config.animal_requirements.growth_energy,
        "lactation": config.animal_requirements.lactation_energy + config.animal_requirements.pregnancy_energy,
    }
    stages = {s: offers["energy_" + s]["predicted"] for s in ENERGY_FIELDS}
    lp_protein = protein_offers(diet, protein)
    limiter, other = ("tdn", "rdp") if regime[1] == "tdn" else ("rdp", "tdn")
    case_protein = 0.64 * lp_protein["microbial_" + limiter] + lp_protein["endogenous"] + lp_protein["digestible_rup"]
    fractional_dmi = sum(diet.values())
    original = VALIDATE(config, diet).unrounded
    basic, ids = LinearRationOptimizer._build_problem(config)
    basic_equivalence = {}
    for name, (original_name, ratio) in ROWS.items():
        row = basic.constraints[name]
        signed = row.sense * (row.constant + sum(row.get(v, 0.0) * diet.get(i, 0.0) for i, v in ids.items()))
        basic_equivalence[original_name] = (signed / fractional_dmi if ratio else signed) - original.residuals[
            original_name
        ]
    assert max(map(abs, basic_equivalence.values())) < 1e-8
    return {
        "quantities_kg_dm": diet,
        "dry_matter_kg": fractional_dmi,
        "cost_by_feed_usd": {f.rufas_id: diet.get(f.rufas_id, 0) * f.purchase_cost for f in config.feeds_used},
        "cost_usd": RationOptimizer.objective(vector(config, diet), config),
        **errors,
        "factors": factors(config, diet),
        "protein_error_attribution_g": protein_attribution(offers),
        "lp_residuals_energy_and_protein": {
            **{f"energy_{s}": stages[s] - energy_minima[s] for s in stages},
            "energy_total_case": stages[regime[0]] - config.animal_requirements.total_energy_requirement,
            "energy_total_max": max(stages.values()) - config.animal_requirements.total_energy_requirement,
            "protein_case_lower": case_protein - config.animal_requirements.metabolizable_protein,
            "protein_case_upper": Constants.PROTEIN_UPPER_LIMIT_FACTOR * config.initial_protein_requirement
            - case_protein,
            "active_microbial_limiter": lp_protein["microbial_" + other] - lp_protein["microbial_" + limiter],
        },
        "exact_linear_minus_original_residual": basic_equivalence,
        "original_check": asdict(original),
    }


class MatrixAudit(LinearRationOptimizer):
    """Independently solve the exact PuLP matrix without the CBC command-line result file."""

    def __init__(self):
        self.checks = []

    def _solve_problem(self, config, problem, quantities_by_id, solver):
        original = super()._solve_problem(config, problem, quantities_by_id, solver)
        inverse = list(quantities_by_id)
        variables = list(quantities_by_id.values())
        rows = list(problem.constraints.values())
        assert all(row.sense in (-1, 1) for row in rows)
        result = linprog(
            [problem.objective.get(var, 0) for var in variables],
            A_ub=[[-row.sense * row.get(var, 0) for var in variables] for row in rows],
            b_ub=[row.sense * row.constant for row in rows],
            bounds=[(var.lowBound, var.upBound) for var in variables],
            method="highs",
        )
        diet = dict(zip(inverse, map(float, result.x), strict=True)) if result.success else None
        validation = VALIDATE(config, diet, repair_rounding=True) if diet else None
        cbc_diet = original.quantities
        row_residuals = None
        if cbc_diet:
            row_residuals = {
                name: row.sense
                * (row.constant + sum(row.get(var, 0) * cbc_diet[i] for i, var in quantities_by_id.items()))
                for name, row in problem.constraints.items()
            }
        self.checks.append(
            {
                "status": int(result.status),
                "message": result.message,
                "diet": diet,
                "validation": asdict(validation) if validation else None,
                "validation_status": validation.status.value if validation else None,
                "cost": float(result.fun) if diet else None,
                "cbc_matrix_signed_residuals": row_residuals,
                "cbc_matches_highs_to_eight_significant_digits": (
                    all(float(format(diet[i], ".8g")) == amount for i, amount in cbc_diet.items())
                    if cbc_diet is not None and diet is not None
                    else None
                ),
            }
        )
        return original


def evaluate_reference(config, reference, independent_matrix=False):
    issue = reference_issue(config, reference)
    if issue:
        return {"reference": reference, "issue": issue}
    calculator = MatrixAudit() if independent_matrix else LinearRationOptimizer()
    energy = calculator.calculate_nrc_energy_coefficients(config, reference)
    protein = calculator.calculate_nrc_protein_coefficients(config, reference)
    selection = calculator.solve_and_validate_nrc_cases(config, reference)
    cases = []
    for index, (regime, result) in enumerate(selection.cases.items()):
        row = {"regime": regime, **asdict(result)}
        validation = selection.validations.get(regime)
        if validation:
            row["validation_status"] = validation.status.value
            row["validation"] = asdict(validation)
            row["raw_audit"] = audit_diet(config, result.quantities, energy, protein, regime)
            final = validation.final_quantities
            if final is not None:
                row["final_audit"] = audit_diet(config, final, energy, protein, regime)
        if independent_matrix:
            check = calculator.checks[index]
            row["independent_matrix"] = check
            if validation:
                lp = row["raw_audit"]["lp_residuals_energy_and_protein"]
                matrix = check["cbc_matrix_signed_residuals"]
                for name, expected in {
                    "minimum_total_energy": lp["energy_total_case"],
                    "minimum_metabolizable_protein": lp["protein_case_lower"],
                    "maximum_metabolizable_protein": lp["protein_case_upper"],
                    "active_microbial_limiter": lp["active_microbial_limiter"],
                    **{f"minimum_energy_{key}": lp[f"energy_{key}"] for key in ENERGY_FIELDS},
                }.items():
                    assert isclose(matrix[name], expected, abs_tol=1e-8)
        cases.append(row)
    return {
        "reference": reference,
        "reference_factors": factors(config, reference),
        "reference_basic_and_nrc": asdict(VALIDATE(config, reference).unrounded),
        "energy_coefficients": {i: asdict(c) for i, c in energy.items()},
        "protein_coefficients": {i: asdict(c) for i, c in protein.items()},
        "selected_case": selection.selected_case,
        "selected_cost": selection.selected_cost,
        "cases": cases,
    }


def midwest_reference(config):
    recipe = next(
        r for r in read_json("feed/example_Midwest_feed.json")["rations"] if r["animal_combination"] == "lac_cow"
    )
    weights = {f["feed_type"]: f["ration_percentage"] for f in recipe["feeds"]}
    shares = {feed.rufas_id: weights.get(feed.rufas_id, 0.0) for feed in config.feeds_used}
    return {i: config.initial_dry_matter_requirement * weight / sum(shares.values()) for i, weight in shares.items()}


def replay(base, trace_dir):
    feed_configuration = read(base / "inputs/feed.json")
    feeds = load_feeds(feed_configuration)
    RationManager.set_intake_options(feed_configuration)
    summary = read(base / "summary.json")
    management = read(base / "inputs/full/animal.json")["animal_config"]["management_decisions"]
    milk_mcal_per_kg = (
        0.0929 * management["milk_fat_percent"]
        + 0.0547 / 0.93 * management["milk_protein_percent"]
        + 0.0395 * Constants.MILK_LACTOSE
    )
    weights = {
        row["simulation_day"]: row["requirements"]["avg_BW"]
        for row in summary["full"]["daily"]
        if row["group"] == "LAC_COW"
    }
    report = {}
    memoized = {}
    for mode in MODES:
        source = ROOT / trace_dir / "runs" / mode / "attempts.jsonl"
        rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
        initials = {r["simulation_day"]: r for r in rows if r["attempt"] == 1}
        for row in rows:
            day, attempt = row["simulation_day"], row["attempt"]
            initial = initials[day]
            inputs = inputs_for(row, initial, weights[day], feeds)
            config = make_config(inputs)
            reconstruction = check_reconstruction(config, row)
            previous = quantities(row["previous_ration"])
            key = json.dumps(
                (row["requirements"], initial["requirements"], previous, row["available_ids"], weights[day])
            )
            if key not in memoized:
                starts = {"production_start_seed_42": validate_slsqp(inputs, previous, 42)}
                if day == 2:
                    for seed in (42, 43, 44):
                        starts[f"cold_seed_{seed}"] = validate_slsqp(inputs, {}, seed)
                memoized[key] = starts
            starts = memoized[key]
            strategy = mode if mode != "slsqp" else "full"
            adapter = LinearRationAdapter(strategy=strategy)
            start = perf_counter()
            selection, _ = adapter.attempt_optimization(**inputs, previous_ration=previous)
            elapsed = perf_counter() - start
            payload = {
                "day": day + 150,
                "attempt": attempt,
                "requirements": row["requirements"],
                "weight_kg": weights[day],
                "milk_used_kg_from_NE": config.animal_requirements.lactation_energy / milk_mcal_per_kg,
                "milk_reduction_kg_from_NE": (
                    initial["requirements"]["lactation_energy"] - config.animal_requirements.lactation_energy
                )
                / milk_mcal_per_kg,
                "target_dmi_initial": config.initial_dry_matter_requirement,
                "dmi_limits_kg": [
                    config.animal_requirements.dry_matter * (1 - config.dmi_constraint_fraction),
                    config.initial_dry_matter_requirement * (1 + config.dmi_constraint_fraction),
                ],
                "protein_limits_g": [
                    config.animal_requirements.metabolizable_protein,
                    config.initial_protein_requirement * Constants.PROTEIN_UPPER_LIMIT_FACTOR,
                ],
                "previous_ration": previous,
                "feed_order": row["available_ids"],
                "pulp": {
                    "strategy": strategy,
                    "success": bool(selection.success),
                    "cost": selection.fun,
                    "quantities": selection.quantities,
                    "lower_bound": selection.lower_bound,
                    "gap": selection.gap,
                    "solver_calls": selection.solver_calls,
                    "seconds": elapsed,
                    "references": [
                        {
                            "source": ref.source,
                            "quantities": ref.quantities,
                            "issue": ref.message,
                            "case_counts": (
                                {
                                    status: sum(case.status.value == status for case in ref.selection.cases.values())
                                    for status in ("optimal", "infeasible", "solver_error")
                                }
                                if ref.selection
                                else None
                            ),
                        }
                        for ref in selection.references
                    ],
                    "original_selection_reproduced": (
                        (
                            selection.quantities == quantities(row["selected_quantities"])
                            if row.get("selected_quantities")
                            else not selection.success
                        )
                        if mode != "slsqp"
                        else None
                    ),
                },
                "slsqp": starts,
                "reconstruction": reconstruction,
            }
            if day == 2 and attempt == 1 and mode in ("full", "single"):
                references = {"previous_ration": previous}
                references.update({goal: build_basic_reference(config, goal)[0] for goal in OBJECTIVES})
                references["midwest"] = midwest_reference(config)
                references["slsqp_diagnostic"] = starts["production_start_seed_42"]["raw"]
                payload["reference_audit"] = {
                    name: evaluate_reference(config, reference, independent_matrix=(mode == "full"))
                    for name, reference in references.items()
                }
                payload["reference_gaps"] = {
                    name: relative_gap(result.get("selected_cost"), selection.lower_bound)[0]
                    for name, result in payload["reference_audit"].items()
                }
            report[f"{mode}/{day + 150}/{attempt}"] = payload
    return {
        "feed_library": {
            key: asdict(feed) for key, feed in feeds.items() if any(key in row["feed_order"] for row in report.values())
        },
        "formulations": report,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--trace", type=Path, default=TRACE)
    parser.add_argument("--output", type=Path, default=BASE / "isolated_audit.json")
    args = parser.parse_args()
    write(args.output, json_safe(replay(args.base, args.trace)))
