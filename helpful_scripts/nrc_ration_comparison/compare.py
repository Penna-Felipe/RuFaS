"""Compare NRC ration formulations in isolation using RuFaS example data.

Run from the repository root with Python 3.12 or 3.13 and install the project
with the optional linear_ration dependencies.

    python -m pip install -e ".[linear_ration]"
    python -m helpful_scripts.nrc_ration_comparison.compare --runs 5 --output helpful_scripts/nrc_ration_comparison/results.json

Without --output the report is written to standard output. The report contains
the input data and source ration percentages, all solver outcomes, validation
residuals before and after rounding, and wall-clock timing samples in seconds.

The modeled cow comes from animal_population.json. Daily milk yield, walking
distance and temperature are explicit scenario assumptions. Other physiological
defaults follow the fresh calculation path without previous nutrition supply.
The Midwest lactating ration is restricted to ingredients with an NRC library
entry. Original prices and inclusion limits are retained. The retained
percentages are normalized to 100% and multiplied by the predicted dry matter
intake. That diet initializes SLSQP and supplies the reference coefficients for
PuLP. Ingredient proportions can vary freely within the same bounds for both.

SLSQP timing records the call to scipy.optimize.minimize and the full original
attempt. CBC timing sums the six actualSolve calls, including file and process
overhead. Full PuLP timing includes coefficient calculation, building and
solving all six models, NRC validation and selection. Input loading and
reference construction take place before timing. All reported medians include
the first run. No simulation or ration retry loop is started.
"""

import argparse
import json
import platform
from dataclasses import asdict
from enum import Enum
from math import isfinite
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any
from unittest.mock import patch

import numpy as np
import pulp
import scipy

from RUFAS.biophysical.animal.animal_module_constants import AnimalModuleConstants as Constants
from RUFAS.biophysical.animal.data_types.animal_combination import AnimalCombination
from RUFAS.biophysical.animal.data_types.animal_types import AnimalType
from RUFAS.biophysical.animal.nutrients.nrc_requirements_calculator import NRCRequirementsCalculator
from RUFAS.biophysical.animal.ration import ration_optimizer
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import LinearRationOptimizer
from RUFAS.data_structures.feed_storage_to_animal_connection import AvailableFeedsBuilder, NRCFeed, NutrientStandard
from RUFAS.input_manager import InputManager

DATA = Path(__file__).resolve().parents[2] / "input" / "data"
COW_ID = 114502
MILK_KG = 30.0
TEMPERATURE_C = 15.0
DISTANCE_M = 500.0


def read_json(relative_path: str) -> Any:
    return json.loads((DATA / relative_path).read_text(encoding="utf-8"))


def build_experiment() -> tuple[dict[str, Any], dict[int, float], dict[str, Any]]:
    feed_config = read_json("feed/example_Midwest_feed.json")
    percentages = {
        feed["feed_type"]: feed["ration_percentage"]
        for ration in feed_config["rations"]
        if ration["animal_combination"] == "lac_cow"
        for feed in ration["feeds"]
    }
    manager = InputManager()
    library = manager._load_data_from_csv(DATA / "feed/NRC_comp.csv")
    compatible_ids = set(percentages) & set(library["rufas_id"])
    filtered_config = {
        **feed_config,
        "feeds": [feed for feed in feed_config["feeds"] if feed["feed_type"] in compatible_ids],
        "rations": [
            {
                **ration,
                "feeds": [feed for feed in ration["feeds"] if feed["feed_type"] in compatible_ids],
            }
            for ration in feed_config["rations"]
            if ration["animal_combination"] == "lac_cow"
        ],
    }
    original_pool = manager.pool
    manager.pool = {**original_pool, "NRC_Comp": library}
    try:
        feeds = AvailableFeedsBuilder.setup_available_feeds(filtered_config, NutrientStandard.NRC)
    finally:
        manager.pool = original_pool
    assert all(isinstance(feed, NRCFeed) for feed in feeds)

    cow = next(cow for cow in read_json("animal/animal_population.json")["cows"] if cow["id"] == COW_ID)
    management = read_json("animal/example_freestall_animal.json")["animal_config"]["management_decisions"]
    animal_inputs = {
        "animal_type": AnimalType(cow["animal_type"]),
        "body_weight": cow["body_weight"],
        "mature_body_weight": cow["mature_body_weight"],
        "day_of_pregnancy": cow["days_in_pregnancy"],
        "body_condition_score_5": Constants.DEFAULT_BODY_CONDITION_SCORE_5,
        "days_in_milk": cow["days_in_milk"],
        "average_daily_gain_heifer": None,
        "parity": cow["parity"],
        "calving_interval": cow["calving_interval"],
        "milk_fat": management["milk_fat_percent"],
        "milk_true_protein": management["milk_protein_percent"],
        "milk_lactose": Constants.MILK_LACTOSE,
        "milk_production": MILK_KG,
        "housing": "barn",
        "distance": DISTANCE_M,
        "previous_temperature": TEMPERATURE_C,
        "net_energy_diet_concentration": Constants.DEFAULT_NET_ENERGY_DIET_CONCENTRATION,
        "days_born": cow["days_born"],
        "TDN_fraction": Constants.DEFAULT_TDN_FRACTION,
        # Initial Nutrients.phosphorus_requirement before any daily process update.
        "process_based_phosphorus_requirement": 0.0,
    }
    requirements = NRCRequirementsCalculator.calculate_requirements(**animal_inputs)
    for feed in feeds:
        if not feed.lower_limit <= 0.0 <= feed.limit:
            raise ValueError("The experiment assumes the example feeds permit zero inclusion.")
    total_percent = sum(percentages[feed.rufas_id] for feed in feeds)
    reference = {feed.rufas_id: requirements.dry_matter * percentages[feed.rufas_id] / total_percent for feed in feeds}
    if any(not feed.lower_limit <= reference[feed.rufas_id] <= feed.limit for feed in feeds):
        raise ValueError("The example reference violates an ingredient bound.")
    solver_inputs = {
        "nutrient_standard": NutrientStandard.NRC,
        "pen_average_body_weight": cow["body_weight"],
        "pen_average_enteric_methane": None,
        "pen_average_urine_nitrogen": None,
        "requirements": requirements,
        "initial_dry_matter_requirement": requirements.dry_matter,
        "initial_protein_requirement": requirements.metabolizable_protein,
        "pen_available_feeds": feeds,
        "animal_combination": AnimalCombination.LAC_COW,
    }
    scenario = {
        "cow_id": COW_ID,
        "animal_inputs": animal_inputs,
        "requirements": asdict(requirements),
        "excluded_feed_ids": sorted(set(percentages) - compatible_ids),
        "feeds": {
            feed.rufas_id: {
                "category": feed.Fd_Category.value,
                "price": feed.purchase_cost,
                "lower": feed.lower_limit,
                "upper": feed.limit,
                "original_reference_pct": percentages[feed.rufas_id],
            }
            for feed in feeds
        },
        "reference": reference,
    }
    return solver_inputs, reference, scenario


class TimedCBC(pulp.PULP_CBC_CMD):
    def __init__(self) -> None:
        super().__init__(msg=False)
        self.elapsed = 0.0

    def actualSolve(self, *args: Any, **kwargs: Any) -> int:
        start = perf_counter()
        try:
            return super().actualSolve(*args, **kwargs)
        finally:
            self.elapsed += perf_counter() - start


class TimedLinearOptimizer(LinearRationOptimizer):
    def solve_nrc_cases(self, *args: Any, **kwargs: Any) -> Any:
        start = perf_counter()
        try:
            return super().solve_nrc_cases(*args, **kwargs)
        finally:
            self.model_and_solve = perf_counter() - start


def compare_once(inputs: dict[str, Any], reference: dict[int, float]) -> tuple[dict[str, Any], dict[str, float]]:
    slsqp_elapsed = 0.0
    minimize = ration_optimizer.minimize

    def timed_minimize(*args: Any, **kwargs: Any) -> Any:
        nonlocal slsqp_elapsed
        start = perf_counter()
        try:
            return minimize(*args, **kwargs)
        finally:
            slsqp_elapsed = perf_counter() - start

    with patch.object(ration_optimizer, "minimize", timed_minimize):
        start = perf_counter()
        slsqp, config = ration_optimizer.RationOptimizer().attempt_optimization(**inputs, previous_ration=reference)
        slsqp_attempt = perf_counter() - start

    linear = TimedLinearOptimizer()
    start = perf_counter()
    slsqp_diet = {feed.rufas_id: float(amount) for feed, amount in zip(config.feeds_used, slsqp.x, strict=True)}
    slsqp_validation = linear.validate_nrc_candidate(config, slsqp_diet)
    slsqp_validation_elapsed = perf_counter() - start

    cbc = TimedCBC()
    start = perf_counter()
    selection = linear.solve_and_validate_nrc_cases(config, reference, cbc)
    linear_total = perf_counter() - start
    rounded = slsqp_validation.rounded_quantities
    rounded_cost = (
        sum(rounded[feed.rufas_id] * feed.purchase_cost for feed in config.feeds_used) if rounded is not None else None
    )
    results = {
        "dmi_constraint_fraction": config.dmi_constraint_fraction,
        "slsqp": {
            "success": bool(slsqp.success),
            "status": int(slsqp.status),
            "message": str(slsqp.message),
            "iterations": int(slsqp.nit),
            "quantities": slsqp_diet,
            "cost": float(slsqp.fun),
            "rounded_cost": rounded_cost,
            "validation_status": slsqp_validation.status,
            "validation": asdict(slsqp_validation),
        },
        "pulp": {
            "cases": [
                {
                    "case": case,
                    **asdict(result),
                    "validation_status": selection.validations[case].status if case in selection.validations else None,
                    "validation": asdict(selection.validations[case]) if case in selection.validations else None,
                }
                for case, result in selection.cases.items()
            ],
            "selected_case": selection.selected_case,
            "selected_cost": selection.selected_cost,
            "message": selection.message,
        },
    }
    timings = {
        "slsqp_minimize": slsqp_elapsed,
        "slsqp_attempt_including_setup": slsqp_attempt,
        "slsqp_validation": slsqp_validation_elapsed,
        "cbc_all_cases_solver_calls": cbc.elapsed,
        "pulp_coefficients_model_and_solve": linear.model_and_solve,
        "pulp_validation_and_selection": linear_total - linear.model_and_solve,
        "pulp_full": linear_total,
    }
    return results, timings


def json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not isfinite(value):
        return str(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    inputs, reference, scenario = build_experiment()
    runs = [compare_once(inputs, reference) for _ in range(args.runs)]
    results = runs[0][0]
    if any(json_safe(result) != json_safe(results) for result, _ in runs[1:]):
        raise RuntimeError("Solver results varied between runs.")
    payload = {
        "versions": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "pulp": pulp.__version__,
        },
        "scenario": scenario,
        "timings_seconds": {
            key: {"median": median(record[key] for _, record in runs), "samples": [record[key] for _, record in runs]}
            for key in runs[0][1]
        },
        "results": results,
    }
    output = json.dumps(json_safe(payload), indent=2, allow_nan=False) + "\n"
    if args.output is None:
        print(output, end="")
    else:
        args.output.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
