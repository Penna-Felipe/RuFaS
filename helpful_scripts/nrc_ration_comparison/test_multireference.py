"""Tests for the isolated multi-reference NRC experiment."""

from math import isfinite
from typing import Any

import numpy as np
import pytest

pytest.importorskip("pulp")

from helpful_scripts.nrc_ration_comparison.compare import build_experiment  # noqa: E402
from helpful_scripts.nrc_ration_comparison.multireference import (  # noqa: E402
    OBJECTIVES,
    basic_reference,
    experiment,
    external_recipes,
    grid_key,
    reference_issue,
    select_distinct,
)
from helpful_scripts.nrc_ration_comparison.sensitivity import make_config  # noqa: E402
from RUFAS.biophysical.animal.ration.ration_optimizer import RationOptimizer  # noqa: E402
from RUFAS.biophysical.animal.nutrients.nutrition_supply_calculator import (
    FeedInRation,
    NutritionSupplyCalculator,
)  # noqa: E402
from RUFAS.data_structures.feed_storage_to_animal_connection import FeedComponentType  # noqa: E402


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return experiment(1)


def test_basic_reference_objectives_and_deduplication(report: dict[str, Any]) -> None:
    inputs, _, _ = build_experiment()
    config = make_config(inputs)
    feed_ids = [feed.rufas_id for feed in config.feeds_used]
    references = {name: report["reference_sources"][name]["quantities"] for name in OBJECTIVES}
    assert len({grid_key(diet, feed_ids) for diet in references.values()}) == 3
    assert grid_key(references["target_dmi"], feed_ids) == grid_key(references["minimum_cost"], feed_ids)
    assert report["reference_sources"]["target_dmi"]["executed_as"] == "minimum_cost"

    # Compare to original residuals with separate allowances for CBC solution-file
    # precision. Production validation tolerances remain unchanged.
    for diet in references.values():
        assert reference_issue(config, diet) is None
        vector = np.array([diet[key] for key in feed_ids])
        for function in (
            RationOptimizer.DMI_constraint_lower,
            RationOptimizer.DMI_constraint_upper,
            RationOptimizer.NDF_constraint_lower,
            RationOptimizer.NDF_constraint_upper,
            RationOptimizer.forage_NDF_constraint,
            RationOptimizer.fat_constraint,
        ):
            assert function(vector, config) >= -2e-6
        assert RationOptimizer.calcium_constraint(vector, config) >= -1e-5
        assert RationOptimizer.phosphorus_constraint(vector, config) >= -1e-5

    target, metrics = basic_reference(config, "target_dmi")
    assert target == references["target_dmi"]
    max_p_per_kg = max(
        NutritionSupplyCalculator.calculate_phosphorus_supply([FeedInRation(amount=1.0, info=feed)])
        for feed in config.feeds_used
    )
    required_p = max(config.animal_requirements.phosphorus, config.animal_requirements.process_based_phosphorus)
    minimum_dmi_from_phosphorus = required_p / max_p_per_kg
    target_deviation = minimum_dmi_from_phosphorus - config.initial_dry_matter_requirement
    assert target_deviation > 0
    assert sum(target.values()) == pytest.approx(minimum_dmi_from_phosphorus, rel=0, abs=2e-6)
    assert metrics["primary_optimum"] == pytest.approx(target_deviation, abs=1e-7)

    forage_ids = [feed.rufas_id for feed in config.feeds_used if feed.feed_type is FeedComponentType.FORAGE]
    concentrate_ids = [feed.rufas_id for feed in config.feeds_used if feed.feed_type is FeedComponentType.CONC]
    for goal, ids in (("maximum_forage", forage_ids), ("maximum_concentrate", concentrate_ids)):
        assert (
            sum(references[goal][i] for i in ids)
            >= max(sum(diet[i] for i in ids) for diet in references.values()) - 2e-6
        )


def test_recipe_audit_preserves_scenario_ingredients() -> None:
    inputs, midwest, _ = build_experiment()
    config = make_config(inputs)
    recipes, audit = external_recipes(config)
    assert recipes == {}
    explicit = [row for row in audit if row["explicit_percentages"]]
    assert len(explicit) == 4
    assert all("Feed IDs outside the scenario" in row["reason"] for row in explicit)
    assert reference_issue(config, midwest) is None
    assert reference_issue(config, {**midwest, 301: 1.0}) is not None
    assert reference_issue(config, dict.fromkeys(midwest, 0.0)) is not None


def test_selects_unique_final_diets_and_handles_total_failure() -> None:
    def case(quantities: dict[int, float], cost: float, status: str = "approved") -> dict[str, Any]:
        return {
            "case": ("maintenance", "tdn"),
            "validation_status": status,
            "rounded_diet": {"quantities": quantities, "cost_usd_per_cow_day": cost},
            "validation": {"rounded": {"violations": {}}},
        }

    references = {
        "midwest": {"cases": [case({2: 3.0, 1: 2.0}, 5.0)]},
        "forage": {"cases": [case({1: 2.0, 2: 3.0}, 5.0), case({1: 2.0, 2: 2.0}, 4.0)]},
        "rejected": {"cases": [case({1: 1.0}, 1.0, "rejected")]},
    }
    unique, selected = select_distinct(references, [1, 2])
    assert len(unique) == 2 and len(unique[0]["sources"]) == 2
    assert selected is not None
    assert selected["diet"]["cost_usd_per_cow_day"] == 4.0
    assert references["forage"]["contribution"]["approved_duplicate_cases"] == 1
    assert select_distinct({"rejected": references["rejected"]}, [1, 2]) == ([], None)


def test_shared_scenario_and_all_cases_reported(report: dict[str, Any]) -> None:
    assert report["scenario"]["cow_id"] == 114502
    assert report["previous_ration_skipped_reason"]
    assert set(report["references"]) == {"midwest", "minimum_cost", "maximum_forage", "maximum_concentrate"}
    for ref in report["references"].values():
        assert len(ref["cases"]) == 6
        assert ref["counts"]["optimal"] + ref["counts"]["infeasible"] + ref["counts"]["solver_error"] == 6
        assert all(isfinite(v["median"]) and v["median"] >= 0 for v in ref["timings_seconds"].values())
        assert all(value["absolute_error"] < 1e-9 for value in ref["reference"]["offers"].values())

    selected = report["selected"]
    assert selected is not None
    assert selected["validation"]["violations"] == {}
    assert len(selected["validation"]["residuals"]) == 14
    assert selected["diet"]["cost_usd_per_cow_day"] == min(
        ref["selected_cost"] for ref in report["references"].values() if ref["selected_cost"] is not None
    )
