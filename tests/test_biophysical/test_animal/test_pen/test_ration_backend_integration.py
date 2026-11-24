"""Integration of the opt-in NRC backend with formulation and feed requests."""

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest
from scipy.optimize import OptimizeResult

from RUFAS.biophysical.animal.data_types.animal_combination import AnimalCombination
from RUFAS.biophysical.animal.data_types.animal_types import AnimalType
from RUFAS.biophysical.animal.data_types.nutrition_data_structures import NutritionSupply
from RUFAS.biophysical.animal.herd_manager import HerdManager
from RUFAS.biophysical.animal.nutrients.nutrition_supply_calculator import NutritionSupplyCalculator
from RUFAS.biophysical.animal.pen import Pen
from RUFAS.biophysical.animal.ration.ration_backend_config import RationBackendConfig
from RUFAS.biophysical.animal.ration.ration_manager import RationManager
from RUFAS.data_structures.feed_storage_to_animal_connection import FeedFulfillmentResults, NutrientStandard
from RUFAS.data_validator import DataValidator, ElementsCounter
from RUFAS.simulation_engine import SimulationEngine


@pytest.mark.parametrize("opt_in", [False, True])
def test_existing_schema_accepts_old_and_new_ration_settings(opt_in: bool) -> None:
    path = Path("RUFAS/input/metadata/properties/default.json")
    schema = json.loads(path.read_text(encoding="utf-8"))["animal_properties"]["ration"]
    validator = DataValidator()
    assert validator.validate_properties({"properties": {"ration": schema}}, 8) == (True, "")
    legacy = {
        "user_input": False,
        "formulation_interval": 30,
        "phosphorus_requirement_buffer": 75,
        "maximum_ration_reformulation_attempts": 250,
    }
    extras = (
        {
            "optimizer_backend": "pulp",
            "linear_strategy": "single",
            "linear_gap_target": 0.03,
            "linear_max_references": 3.0,
            "linear_nutritional_solver": "highs",
            "linear_reference_solver": "highs",
            "linear_bound_solver": "highs",
            "linear_midwest_reference_path": "feed_inputs/custom_midwest.json",
        }
        if opt_in
        else {}
    )
    ration = legacy | extras
    assert validator.validate_data_by_type(
        schema,
        ["ration"],
        {"ration": ration},
        True,
        "animal_properties",
        ElementsCounter(),
        True,
        {"number", "string", "bool"},
        path,
    )
    settings = RationBackendConfig.from_mapping(ration)
    if opt_in:
        assert settings == RationBackendConfig(
            "pulp", "single", 0.03, 3, "highs", "highs", "highs", Path("feed_inputs/custom_midwest.json")
        )
    else:
        assert settings == RationBackendConfig()


@pytest.mark.parametrize(
    "extra",
    [
        {"optimizer_backend": "unknown"},
        {"linear_strategy": "unknown"},
        {"linear_nutritional_solver": "unknown"},
        {"linear_nutritional_solver": None},
        {"linear_reference_solver": "unknown"},
        {"linear_reference_solver": None},
        {"linear_bound_solver": "unknown"},
        {"linear_bound_solver": None},
        {"linear_gap_target": 1},
        {"linear_gap_target": float("nan")},
        {"linear_max_references": 1.5},
        {"linear_max_references": False},
    ],
)
def test_settings_validate_options_and_ranges(extra: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="animal.ration"):
        RationBackendConfig.from_mapping(extra)


@pytest.fixture
def feeding(monkeypatch: pytest.MonkeyPatch) -> tuple[HerdManager, Pen, MagicMock, dict[str, Any]]:
    pytest.importorskip("pulp")
    from helpful_scripts.nrc_ration_comparison.compare import build_experiment

    inputs, _, _ = build_experiment()
    monkeypatch.setattr(Pen, "_initialize_beddings", lambda self: None)
    monkeypatch.setattr(NutritionSupplyCalculator, "nutrient_standard", NutrientStandard.NRC, raising=False)
    monkeypatch.setattr(RationManager, "intake_options", {})
    monkeypatch.setattr(RationManager, "maximum_ration_reformulation_attempts", 0, raising=False)
    monkeypatch.setattr(
        RationManager,
        "ration_feeds",
        {AnimalCombination.LAC_COW: [feed.rufas_id for feed in inputs["pen_available_feeds"]]},
        raising=False,
    )

    herd = HerdManager.__new__(HerdManager)
    herd.ration_backend_config = RationBackendConfig.from_mapping(
        {
            "optimizer_backend": "pulp",
            "linear_strategy": "single",
            "linear_gap_target": 0.03,
            "linear_max_references": 2,
        }
    )
    herd.all_pens = []
    herd.initialize_pens([{"id": 7, "animal_combination": "LAC_COW", "number_of_stalls": 10}])
    pen = herd.all_pens[0]
    assert pen.ration_backend_config is herd.ration_backend_config
    pen.om = MagicMock()
    herd.om = MagicMock()
    herd.is_ration_defined_by_user = False
    herd._max_daily_feeds = {}
    herd.advance_purchase_allowance = MagicMock()
    herd.animal_to_pen_id_map = {}
    cow = MagicMock()
    cow.id = 114502
    cow.animal_type = AnimalType.LAC_COW
    cow.nutrient_standard = NutrientStandard.NRC
    cow.body_weight = inputs["pen_average_body_weight"]
    cow.nutrition_requirements = inputs["requirements"]
    cow.nutrition_supply = NutritionSupply.make_empty_nutrition_supply()
    cow.enteric_methane = 0.0
    cow.digestive_system.manure_excretion.urine_nitrogen = 0.0
    cow.milk_production.daily_milk_produced = 30.0
    cow.milk_production.milk_production_reduction = 0.0
    herd.cows = [cow]
    monkeypatch.setattr(
        herd, "allocate_animals_to_pens", lambda day: pen.insert_single_animal_into_animals_in_pen_map(cow)
    )
    return herd, pen, cow, inputs


@pytest.mark.parametrize(
    ("backend", "standard", "group", "user_defined", "reason"),
    [
        ("slsqp", NutrientStandard.NRC, AnimalCombination.LAC_COW, False, "configured_slsqp"),
        ("pulp", NutrientStandard.NASEM, AnimalCombination.LAC_COW, False, "nutrient_standard_not_supported"),
        ("pulp", NutrientStandard.NRC, AnimalCombination.GROWING, False, "animal_group_not_supported"),
        ("pulp", NutrientStandard.NRC, AnimalCombination.LAC_COW, True, "user_defined_ration"),
    ],
)
def test_default_and_unsupported_modes_use_original_optimizer(
    feeding: tuple[HerdManager, Pen, MagicMock, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    standard: NutrientStandard,
    group: AnimalCombination,
    user_defined: bool,
    reason: str,
) -> None:
    _, pen, cow, inputs = feeding
    pen.ration_backend_config = RationBackendConfig(backend)
    pen.animal_combination = group
    pen.animals_in_pen = {cow.id: cow}
    cow.nutrient_standard = standard
    monkeypatch.setattr(RationManager, "user_defined_rations", {group: {23: 100}}, raising=False)
    solution = OptimizeResult(success=True, message="mock result")
    original = Mock(return_value=(solution, None))
    monkeypatch.setattr(pen.ration_optimizer, "attempt_optimization", original)
    result, _ = pen._attempt_formulation(
        user_defined,
        inputs["pen_available_feeds"],
        15,
        {},
        inputs["initial_dry_matter_requirement"],
        inputs["initial_protein_requirement"],
    )
    assert result is solution
    assert result.ration_backend == "slsqp" and result.ration_backend_reason == reason
    original.assert_called_once()
    assert pen._linear_ration_optimizer is None


def test_pulp_applies_validated_diet_across_reallocation_and_ingredient_change(
    feeding: tuple[HerdManager, Pen, MagicMock, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    herd, pen, cow, inputs = feeding
    feeds = list(reversed(inputs["pen_available_feeds"]))
    forbid_slsqp = Mock(side_effect=AssertionError("Unexpected SLSQP call"))
    monkeypatch.setattr(pen.ration_optimizer, "attempt_optimization", forbid_slsqp)
    adapter = pen._get_linear_ration_optimizer()
    attempt = Mock(wraps=adapter.attempt_optimization)
    monkeypatch.setattr(adapter, "attempt_optimization", attempt)

    demand = herd.formulate_rations(feeds, 15, 5, 1)
    first = pen.ration.copy()
    assert attempt.call_args.kwargs["previous_ration"] == {}
    assert demand.requested_feed == {feed_id: amount * 5 for feed_id, amount in first.items()}
    assert cow.nutrition_supply.dry_matter == pytest.approx(sum(first.values()))
    report = pen.om.add_variable.call_args.args[1]
    assert report["backend"] == "pulp" and report["nutritional_validation"] == "approved"
    assert report["reference"] == "minimum_cost" and report["strategy"] == "single"
    assert report["gap_target"] == 0.03 and report["gap_achieved"] is not None
    assert report["simulation_day"] == 1 and report["pen_id"] == 7
    assert report["solver_calls"] > 0 and report["optimization_seconds"] > 0
    assert report["cost_usd_per_animal_day"] == pytest.approx(0.27455306)

    herd.formulate_rations(feeds, 15, 5, 6)
    assert attempt.call_args.kwargs["previous_ration"] == first
    assert pen.om.add_variable.call_args.args[1]["reference"] == "previous_ration"
    # Simulate a previous ration using corn before its removal from this pen.
    pen.ration = {**pen.ration, 44: 0.1}
    previous = pen.ration.copy()
    reduced = [feed for feed in feeds if feed.rufas_id != 44]
    herd.formulate_rations(reduced, 15, 5, 11)
    assert attempt.call_args.kwargs["previous_ration"] == previous
    assert pen.om.add_variable.call_args.args[1]["reference"] == "minimum_cost"
    assert 44 not in pen.ration
    assert herd.collect_daily_feed_request().requested_feed == pen.ration
    forbid_slsqp.assert_not_called()


def test_repopulate_empty_pen_and_reformulate_after_feed_shortage(
    feeding: tuple[HerdManager, Pen, MagicMock, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    herd, pen, cow, inputs = feeding
    feeds = inputs["pen_available_feeds"]
    pen.ration = {23: 1.0}
    monkeypatch.setattr(herd, "allocate_animals_to_pens", lambda day: None)
    assert herd.formulate_rations(feeds, 15, 5, 1).requested_feed == {}
    assert pen.ration == {}
    herd.ANIMAL_GROUPING_SCENARIO = SimpleNamespace(find_animal_combination=lambda _: AnimalCombination.LAC_COW)
    herd._add_animal_to_pen_and_id_map(cow, feeds, SimpleNamespace(mean_air_temperature=15), 2)
    assert pen.ration and herd.animal_to_pen_id_map[cow.id] == pen.id
    assert pen.om.add_variable.call_args.args[1]["reference"] == "minimum_cost"
    before = pen.ration.copy()

    monkeypatch.setattr(
        herd, "allocate_animals_to_pens", lambda day: pen.insert_single_animal_into_animals_in_pen_map(cow)
    )
    monkeypatch.setattr(herd, "execute_daily_routines", Mock(return_value={}))
    monkeypatch.setattr(herd, "report_ration_interval_data", Mock())
    engine = SimulationEngine.__new__(SimulationEngine)
    engine.herd_manager = herd
    engine.available_feeds = feeds
    engine.simulate_feed = True
    engine.feed_manager = MagicMock()
    engine.feed_manager.manage_daily_feed_request.return_value = (False, FeedFulfillmentResults.empty())
    engine.om = MagicMock()
    engine.time = SimpleNamespace(simulation_day=3)
    engine.weather = MagicMock()
    engine.weather.get_current_day_conditions.return_value.mean_air_temperature = 15
    engine.ration_formulation_interval_length = timedelta(days=5)
    adapter = pen._get_linear_ration_optimizer()
    attempt = Mock(wraps=adapter.attempt_optimization)
    monkeypatch.setattr(adapter, "attempt_optimization", attempt)

    engine._execute_daily_animal_operations()
    assert attempt.call_args.kwargs["previous_ration"] == before
    assert pen.om.add_variable.call_args.args[1]["simulation_day"] == 3
    engine.feed_manager.manage_daily_feed_request.assert_called_once()
    request = engine.feed_manager.manage_ration_interval_purchases.call_args.args[0]
    assert request.requested_feed == {feed_id: amount * 5 for feed_id, amount in pen.ration.items()}


def test_pulp_failure_has_no_vector_or_slsqp_fallback_and_retains_legacy_outcome(
    feeding: tuple[HerdManager, Pen, MagicMock, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    herd, pen, _, inputs = feeding
    feeds = inputs["pen_available_feeds"]
    adapter = pen._get_linear_ration_optimizer()
    failed = OptimizeResult(
        success=False,
        x=None,
        status=2,
        message="solver unavailable",
        nrc_validation="no_candidate",
        references=[],
        stop_reason="references_exhausted",
    )
    fail = Mock(return_value=(failed, None))
    monkeypatch.setattr(adapter, "attempt_optimization", fail)
    original = Mock(side_effect=AssertionError("SLSQP must not be used after a PuLP failure"))
    monkeypatch.setattr(pen.ration_optimizer, "attempt_optimization", original)

    with pytest.raises(ValueError, match="No previous ration"):
        herd.formulate_rations(feeds, 15, 5, 1)
    assert pen.om.add_variable.call_args.args[1]["message"] == "solver unavailable"
    assert pen.om.add_variable.call_args.args[1]["backend"] == "pulp"
    pen.ration = {23: 1.0}
    requested = herd.formulate_rations(feeds, 15, 5, 2)
    assert requested.requested_feed == {23: 5.0}
    assert fail.call_count == 2
    original.assert_not_called()


def test_slsqp_default_applies_ration_and_records_legacy_validation(
    feeding: tuple[HerdManager, Pen, MagicMock, dict[str, Any]],
) -> None:
    from helpful_scripts.nrc_ration_comparison.compare import build_experiment

    herd, pen, cow, inputs = feeding
    _, initial, _ = build_experiment()
    pen.ration_backend_config = RationBackendConfig.from_mapping({})
    pen.ration = initial
    requested = herd.formulate_rations(inputs["pen_available_feeds"], 15, 5, 1)
    report = pen.om.add_variable.call_args.args[1]
    assert report["backend"] == "slsqp" and report["backend_reason"] == "configured_slsqp"
    assert report["success"] and report["nutritional_validation"].startswith("legacy_evaluator_")
    assert report["gap_target"] is None and report["gap_achieved"] is None
    assert report["cost_usd_per_animal_day"] == pytest.approx(0.2752838)
    assert cow.nutrition_supply.dry_matter == pytest.approx(sum(pen.ration.values()))
    assert requested.requested_feed == {feed_id: amount * 5 for feed_id, amount in pen.ration.items()}
    assert pen._linear_ration_optimizer is None


def test_pen_applies_adapter_repair_as_the_feed_request(
    feeding: tuple[HerdManager, Pen, MagicMock, dict[str, Any]],
) -> None:
    from helpful_scripts.nrc_ration_comparison.compare import build_experiment

    herd, pen, _, inputs = feeding
    _, initial, _ = build_experiment()
    pen.ration = initial
    requested = herd.formulate_rations(inputs["pen_available_feeds"], 15, 1, 1)
    assert pen.ration[23] == pytest.approx(0.019201, abs=1e-9)
    assert requested.requested_feed == pen.ration
    report = pen.om.add_variable.call_args.args[1]
    assert report["reference"] == "previous_ration" and report["nutritional_validation"] == "approved"
    assert report["cost_usd_per_animal_day"] == pytest.approx(0.29038518)
    assert report["nutritional_solver"] == "PULP_CBC_CMD"
    assert report["reference_solver"] == "PULP_CBC_CMD"
    assert report["bound_solver"] == "PULP_CBC_CMD"


def test_pen_applies_highs_nrc_approved_quantities(
    feeding: tuple[HerdManager, Pen, MagicMock, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("highspy")
    herd, pen, _, inputs = feeding
    pen.ration_backend_config = replace(
        pen.ration_backend_config, nutritional_solver="highs", reference_solver="highs", bound_solver="highs"
    )
    adapter = pen._get_linear_ration_optimizer()
    original_attempt = adapter.attempt_optimization
    results = []

    def capture_attempt(**kwargs: Any) -> Any:
        result = original_attempt(**kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(adapter, "attempt_optimization", capture_attempt)
    requested = herd.formulate_rations(inputs["pen_available_feeds"], 15, 1, 1)
    [(solution, _)] = results
    assert solution.success
    selection = next(ref.selection for ref in solution.references if ref.source == solution.selected_reference)
    approved = selection.validations[solution.selected_case].final_quantities
    assert approved == solution.quantities == pen.ration == requested.requested_feed
    report = pen.om.add_variable.call_args.args[1]
    assert report["nutritional_solver"] == "HiGHS"
    assert report["reference_solver"] == "HiGHS"
    assert report["bound_solver"] == "HiGHS"
    assert report["nutritional_validation"] == "approved"
    assert report["cost_usd_per_animal_day"] == pytest.approx(solution.fun)
    assert report["solver_calls"] == solution.solver_calls


def test_pen_applies_midwest_winner_certified_by_nrc(feeding, monkeypatch):
    pytest.importorskip("highspy")
    from helpful_scripts.nrc_ration_comparison.adaptive import scenario_grid

    herd, pen, cow, _ = feeding
    inputs = next(inputs for name, inputs, _, _ in scenario_grid() if name == "114502_midwest_plus_soy_market")
    cow.body_weight = inputs["pen_average_body_weight"]
    cow.nutrition_requirements = inputs["requirements"]
    feeds = inputs["pen_available_feeds"]
    monkeypatch.setattr(RationManager, "ration_feeds", {AnimalCombination.LAC_COW: [f.rufas_id for f in feeds]})
    pen.ration_backend_config = RationBackendConfig.from_mapping(
        {
            "optimizer_backend": "pulp",
            "linear_strategy": "full",
            "linear_reference_solver": "highs",
            "linear_bound_solver": "highs",
            "linear_nutritional_solver": "highs",
            "linear_midwest_reference_path": "input/data/feed/example_Midwest_feed.json",
            "linear_max_references": 2,
        }
    )
    adapter = pen._get_linear_ration_optimizer()
    original_attempt = adapter.attempt_optimization
    attempts = []

    def capture_attempt(**kwargs):
        result = original_attempt(**kwargs)
        attempts.append(result[0])
        return result

    monkeypatch.setattr(adapter, "attempt_optimization", capture_attempt)
    requested = herd.formulate_rations(feeds, 15, 1, 1)
    [solution] = attempts
    assert solution.selected_reference == "midwest"
    winner = next(ref.selection for ref in solution.references if ref.source == "midwest")
    approved = winner.validations[solution.selected_case].final_quantities
    assert approved == solution.quantities == pen.ration == requested.requested_feed
    report = pen.om.add_variable.call_args.args[1]
    assert report["reference"] == "midwest"
    assert report["nutritional_validation"] == "approved"
    assert report["regional_reference"]["retained_original_percent"] == pytest.approx(71.52)
    assert report["regional_reference"]["removed_ingredients"] == {301: 3.27, 302: 25.21}
    assert report["cost_usd_per_animal_day"] == pytest.approx(solution.fun)
