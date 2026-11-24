"""Compare lazy NRC reference selection with a complete search in isolated scenarios.

Run from repository root, with RuFaS and .[linear_ration] installed:
    python -m helpful_scripts.nrc_ration_comparison.adaptive --runs 3 --seed 42 --output helpful_scripts/nrc_ration_comparison/adaptive_results.json

The fixed scenario grid crosses three example animals (milk yields are explicit
assumptions), two NRC ingredient lists, and illustrative and market-proxy price
profiles. Each strategy is timed independently without cached solver results.
"""

import argparse
import json
import platform
import random
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from itertools import product
from math import isfinite
from pathlib import Path
from time import perf_counter
from typing import Any

import pulp
import scipy

from RUFAS.biophysical.animal.animal_module_constants import AnimalModuleConstants
from RUFAS.biophysical.animal.nutrients.nrc_requirements_calculator import NRCRequirementsCalculator
from RUFAS.biophysical.animal.nutrients.nutrition_supply_calculator import NutritionSupplyCalculator
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import (
    _NRC_TOLERANCES,
    LinearRationOptimizer,
)
from RUFAS.biophysical.animal.ration.ration_optimizer import RationConfig
from RUFAS.data_structures.feed_storage_to_animal_connection import AvailableFeedsBuilder
from RUFAS.input_manager import InputManager

from .compare import DATA, build_experiment, json_safe, read_json
from .multireference import OBJECTIVES, basic_reference, grid_key, reference_issue, run_reference, run_slsqp
from .sensitivity import make_config, nutrient_errors, time_summary

ANIMALS = {114502: 30.0, 123802: 24.0, 98648: 40.0}
MENUS = {"midwest_five": (), "midwest_plus_soy": (167,)}
STRATEGIES = {
    "single": ("minimum_cost",),
    "adaptive": (*OBJECTIVES, "midwest"),
    "full": (*OBJECTIVES, "midwest"),
}
SHORT_TON_KG = 907.18474
POUND_KG = 0.45359237
PRICE_SOURCES = {
    "corn_and_hay": "https://esmis.nal.usda.gov/sites/default/release-files/795685/agpr1125.pdf",
    "stored_corn_silage": "https://www.extension.iastate.edu/agdm/crops/pdf/a1-65.pdf",
    "soybean_meal": "https://www.ers.usda.gov/publications/113557",
    "blood_meal": "https://mymarketnews.ams.usda.gov/filerepo/sites/default/files/2837/2025-12-02/1289318/ams_2837_01446.pdf",
}
# USD per kg DM. Grain uses a standard 56 lb bushel and a benchmark DM of
# 84.5%. Hay assumes 90% DM and serves as a proxy for the two other forages.
# Stored corn silage is valued at 11 times grain price per short ton at 35% DM.
MARKET_PRICES = {
    23: 955 / (SHORT_TON_KG * 0.902),
    44: 3.93 / (56 * POUND_KG * 0.845),
    50: (11 * 3.93) / (SHORT_TON_KG * 0.35),
    104: 159 / (SHORT_TON_KG * 0.90),
    110: 168 / (SHORT_TON_KG * 0.90),
    167: 300 / (SHORT_TON_KG * 0.895),
}
PRICE_NOTES = {
    23: "Dec 2 2025 USDA AMS Central U.S. 85% protein blood meal proxy for NRC ID 23, $955/short ton.",
    44: "Oct 2025 USDA NASS U.S. grain corn, $3.93/bu; ignores grinding, delivery and basis.",
    50: "Iowa State stored-silage rule at 11x Oct corn price and 35% DM, proxy for immature silage.",
    104: "Oct 2025 USDA NASS U.S. all baled hay, $159/short ton as proxy for mixed forage silage.",
    110: "Oct 2025 USDA NASS U.S. baled alfalfa, $168/short ton as proxy for legume silage.",
    167: "Dec 2025 USDA ERS 2025/26 forecast, $300/short ton of soybean meal.",
}
_BASIC_NAMES = {
    "DMI_constraint_lower",
    "DMI_constraint_upper",
    "calcium_constraint",
    "phosphorus_constraint",
    "NDF_constraint_lower",
    "NDF_constraint_upper",
    "forage_NDF_constraint",
    "fat_constraint",
}


def discount_audit(config: RationConfig, quantities: Mapping[int, float]) -> dict[str, Any]:
    feeds, intake = LinearRationOptimizer._prepare_nrc_reference(config, quantities)
    total_tdn = sum(feed.amount * feed.info.TDN / 100 for feed in feeds)
    percent = 100 * total_tdn / intake
    weight = config.pen_average_body_weight
    trigger = 0.035 * weight**0.75
    factor = NutritionSupplyCalculator.calculate_nutrient_intake_discount(feeds, weight)
    if percent < 60:
        regime = "tdn_percentage_below_60"
    elif total_tdn < trigger:
        regime = "tdn_intake_below_threshold"
    elif factor == AnimalModuleConstants.MINIMUM_TDN_DISCOUNT:
        regime = "discount_floor"
    else:
        regime = "computed_discount"
    return {
        "dmi": intake,
        "tdn_kg": total_tdn,
        "tdn_percent": percent,
        "tdn_intake_threshold_kg": trigger,
        "factor": factor,
        "regime": regime,
    }


def historical_audit() -> dict[str, Any]:
    inputs, _, _ = build_experiment()
    config = make_config(inputs)
    previous = read_report()
    reference = {int(key): value for key, value in previous["reference_sources"]["minimum_cost"]["quantities"].items()}
    final = {int(key): value for key, value in previous["selected"]["diet"]["quantities"].items()}
    maximum_concentrate = {
        int(key): value for key, value in previous["reference_sources"]["maximum_concentrate"]["quantities"].items()
    }
    energy = LinearRationOptimizer.calculate_nrc_energy_coefficients(config, reference)
    protein = LinearRationOptimizer.calculate_nrc_protein_coefficients(config, reference)
    return {
        "minimum_cost_reference": discount_audit(config, reference),
        "approved_diet": discount_audit(config, final),
        "energy_errors": {
            key: metric
            for key, metric in nutrient_errors(config, final, energy, protein)["offers"].items()
            if key.startswith("energy_")
        },
        "maximum_concentrate_basic_residuals": basic_audit(config, maximum_concentrate),
    }


def read_report() -> dict[str, Any]:
    path = Path(__file__).with_name("multireference_results.json")
    return json.loads(path.read_text(encoding="utf-8"))


def basic_audit(config: RationConfig, reference: dict[int, float]) -> dict[str, Any]:
    check = LinearRationOptimizer.validate_nrc_candidate(config, reference).unrounded
    return {
        "residuals": {key: value for key, value in check.residuals.items() if key in _BASIC_NAMES},
        "violations": {
            key: value
            for key, value in check.violations.items()
            if key in _BASIC_NAMES or key.startswith("ingredient_")
        },
    }


def scenario_grid() -> list[tuple[str, dict[str, Any], dict[int, float], dict[str, Any]]]:
    base_inputs, base_reference, base = build_experiment()
    cows = {cow["id"]: cow for cow in read_json("animal/animal_population.json")["cows"] if cow["id"] in ANIMALS}
    manager = InputManager()
    library = manager._load_data_from_csv(DATA / "feed/NRC_comp.csv")
    full_menu = sorted(set(base_reference) | {167})
    original_pool = manager.pool
    manager.pool = {**original_pool, "NRC_Comp": library}
    try:
        feeds = AvailableFeedsBuilder.setup_available_feeds(
            {
                "feeds": [
                    {"feed_type": key, "purchased_feed_cost": MARKET_PRICES[key], "buffer": 0.15} for key in full_menu
                ],
                "rations": [],
            },
            base_inputs["nutrient_standard"],
        )
    finally:
        manager.pool = original_pool

    cases = []
    for (cow_id, milk), (menu, extra_ids), prices in product(
        ANIMALS.items(), MENUS.items(), ("illustrative", "market")
    ):
        cow = cows[cow_id]
        animal = {
            **base["animal_inputs"],
            **{
                key: cow[key]
                for key in (
                    "body_weight",
                    "mature_body_weight",
                    "days_in_milk",
                    "days_born",
                    "parity",
                    "calving_interval",
                )
            },
            "day_of_pregnancy": cow["days_in_pregnancy"] or None,
            "milk_production": milk,
        }
        requirements = NRCRequirementsCalculator.calculate_requirements(**animal)
        illustrative = {feed_id: value["price"] for feed_id, value in base["feeds"].items()} | {167: 0.35}
        price_list = MARKET_PRICES if prices == "market" else illustrative
        menu_ids = set(base_reference) | set(extra_ids)
        scenario_feeds = [
            replace(feed, purchase_cost=price_list[feed.rufas_id]) for feed in feeds if feed.rufas_id in menu_ids
        ]
        inputs = {
            **base_inputs,
            "requirements": requirements,
            "pen_average_body_weight": animal["body_weight"],
            "initial_dry_matter_requirement": requirements.dry_matter,
            "initial_protein_requirement": requirements.metabolizable_protein,
            "pen_available_feeds": scenario_feeds,
        }
        reference = {
            key: base_reference.get(key, 0) * requirements.dry_matter / sum(base_reference.values())
            for key in sorted(menu_ids)
        }
        metadata = {
            "cow_id": cow_id,
            "milk_kg_per_day_assumed": milk,
            "menu": menu,
            "prices": prices,
            "animal_inputs": animal,
            "requirements": asdict(requirements),
            "feeds": {
                feed.rufas_id: {"usd_per_kg_dm": feed.purchase_cost, "lower": feed.lower_limit, "upper": feed.limit}
                for feed in scenario_feeds
            },
        }
        cases.append((f"{cow_id}_{menu}_{prices}", inputs, reference, metadata))
    return cases


def evaluate_strategy(
    config: RationConfig, midwest: dict[int, float], strategy: str, *, stop_cost: Callable[[float], bool] | None = None
) -> tuple[dict[str, Any], dict[str, float]]:
    start_all = perf_counter()
    feed_ids = sorted(feed.rufas_id for feed in config.feeds_used)
    references = {}
    known = {}
    best = None
    phases = dict.fromkeys(
        ("generation", "coefficients", "lp_model_and_bookkeeping", "cbc_all_six_cases", "validation_repair_selection"),
        0.0,
    )
    for goal in STRATEGIES[strategy]:
        start = perf_counter()
        try:
            reference, generation = (dict(midwest), {}) if goal == "midwest" else basic_reference(config, goal)
        except ValueError as error:
            phases["generation"] += perf_counter() - start
            references[goal] = {"generator_error": str(error)}
            continue

        issue = reference_issue(config, reference)
        key = grid_key(reference, feed_ids) if issue is None else None
        generation_elapsed = perf_counter() - start
        phases["generation"] += generation_elapsed
        info = {"quantities": reference, "generation": generation, "generation_seconds": generation_elapsed}
        if issue is not None:
            references[goal] = {**info, "generator_error": issue}
            continue
        if key in known:
            references[goal] = {**info, "duplicate_of": known[key]}
            continue
        known[key] = goal

        report, timing = run_reference(config, reference)
        for phase in phases.keys() & timing.keys():
            phases[phase] += timing[phase]
        references[goal] = {**info, **report}
        cost = report["selected_cost"]
        if cost is not None and (best is None or cost < best["cost"]):
            best = {"reference": goal, "case": report["selected_case"], "cost": cost}
            if strategy == "adaptive" or (stop_cost is not None and stop_cost(cost)):
                break

    return {"references": references, "selected": best}, {**phases, "full": perf_counter() - start_all}


def annotate(config: RationConfig, result: dict[str, Any]) -> None:
    for ref in result["references"].values():
        if "cases" not in ref:
            continue
        reference = ref["quantities"]
        ref["basic_check"] = basic_audit(config, reference)
        ref["discount"] = discount_audit(config, reference)
        energy = LinearRationOptimizer.calculate_nrc_energy_coefficients(config, reference)
        protein = LinearRationOptimizer.calculate_nrc_protein_coefficients(config, reference)
        for case in ref["cases"]:
            if case["quantities"] is None:
                continue
            validation = case["validation"]
            repair = validation["repair"]
            final = (
                repair["quantities"]
                if repair and repair["quantities"] is not None
                else validation["rounded_quantities"]
            )
            selected = (
                validation["repair"]["validation"]
                if repair and repair["quantities"] is not None
                else validation["rounded"]
            )
            if final is not None and sum(final.values()) > 0 and all(isfinite(x) and x >= 0 for x in final.values()):
                case["rounded_or_repaired"] = {
                    "quantities": final,
                    "dmi": sum(final.values()),
                    "residuals": selected["residuals"],
                    "nutrient_errors": nutrient_errors(config, final, energy, protein),
                    "discount": discount_audit(config, final),
                }
    winner = result["selected"]
    if winner is not None:
        chosen = next(
            case for case in result["references"][winner["reference"]]["cases"] if case["case"] == winner["case"]
        )
        winner["diet"] = chosen["rounded_or_repaired"]


def seeded_slsqp(inputs: dict[str, Any], seed: int) -> tuple[dict[str, Any], dict[str, float]]:
    state = random.getstate()
    random.seed(seed)
    try:
        report, timings = run_slsqp(inputs, {})  # Empty previous ration exercises the original random start.
    finally:
        random.setstate(state)
    report["seed"] = seed
    report["start"] = "original_random_without_previous_ration"
    return report, {**timings, "full": timings["attempt_with_setup"] + timings["validation"]}


def summarize(scenarios: dict[str, Any]) -> dict[str, Any]:
    outcomes = {}
    for strategy in (*STRATEGIES, "slsqp"):
        valid = 0
        times = []
        for scenario in scenarios.values():
            record = scenario["strategies"][strategy] if strategy != "slsqp" else scenario["slsqp"]
            if strategy == "slsqp":
                valid += record["success"] and json_safe(record["validation_status"]) == "approved"
            else:
                valid += record["selected"] is not None
            times.append({"full": record["timings_seconds"]["full"]["median"]})
        outcomes[strategy] = {
            "approved_scenarios": valid,
            "total_scenarios": len(scenarios),
            "across_scenario_median_seconds": time_summary(times)["full"]["median"],
        }

    improved = []
    fallback = []
    for name, scenario in scenarios.items():
        adaptive = scenario["strategies"]["adaptive"]
        first = scenario["strategies"]["single"]["selected"]
        full = scenario["strategies"]["full"]["selected"]
        if first is None:
            fallback.append({"scenario": name, "outcome": adaptive["selected"] and adaptive["selected"]["reference"]})
        if full is not None and adaptive["selected"] is not None and full["cost"] < adaptive["selected"]["cost"] - 1e-9:
            improved.append(
                {
                    "scenario": name,
                    "adaptive_cost": adaptive["selected"]["cost"],
                    "full_cost": full["cost"],
                    "full_reference": full["reference"],
                }
            )
    return {"strategies": outcomes, "adaptive_fallbacks": fallback, "full_cost_improvements": improved}


def experiment(runs: int, seed: int) -> dict[str, Any]:
    records = {}
    for name, inputs, midwest, metadata in scenario_grid():
        config = make_config(inputs)
        strategies = {}
        for strategy in STRATEGIES:
            measured = [evaluate_strategy(config, midwest, strategy) for _ in range(runs)]
            record = measured[0][0]
            repeat_decisions = [[list(row["references"]), row["selected"]] for row, _ in measured]
            record["repeated_selections_match"] = all(row == repeat_decisions[0] for row in repeat_decisions)
            record["timings_seconds"] = time_summary([timing for _, timing in measured])
            annotate(config, record)
            strategies[strategy] = record
        original = [seeded_slsqp(inputs, seed) for _ in range(runs)]
        slsqp = original[0][0]
        slsqp["timings_seconds"] = time_summary([timing for _, timing in original])
        records[name] = {"scenario": metadata, "strategies": strategies, "slsqp": slsqp}

    return {
        "runs": runs,
        "seed": seed,
        "python": platform.python_version(),
        "scipy": scipy.__version__,
        "pulp": pulp.__version__,
        "price_sources": PRICE_SOURCES,
        "market_price_assumptions": PRICE_NOTES,
        "market_usd_per_kg_dm": MARKET_PRICES,
        "nrc_residual_tolerances": _NRC_TOLERANCES,
        "historical_discount_audit": historical_audit(),
        "summary": summarize(records),
        "scenarios": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    payload = json.dumps(json_safe(experiment(args.runs, args.seed)), indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
