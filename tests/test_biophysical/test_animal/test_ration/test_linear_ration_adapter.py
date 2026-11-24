"""Compatibility tests for the isolated linear formulation backend."""

from typing import Any

from collections import Counter

import pytest

pulp = pytest.importorskip("pulp")

from helpful_scripts.nrc_ration_comparison.compare import build_experiment  # noqa: E402
from RUFAS.biophysical.animal.data_types.animal_combination import AnimalCombination  # noqa: E402
from RUFAS.biophysical.animal.ration import linear_ration_adapter as adapter_module  # noqa: E402
from RUFAS.biophysical.animal.ration.linear_ration_adapter import (  # noqa: E402
    LinearAttemptStatus,
    LinearRationAdapter,
    LinearSearchStrategy,
)
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import (  # noqa: E402
    LinearRationOptimizer,
    LinearRationResult,
    LinearRationStatus,
    NRCResiduals,
    NRCSelectionResult,
    NRCValidationResult,
)
from RUFAS.data_structures.feed_storage_to_animal_connection import NutrientStandard  # noqa: E402

CASE = ("maintenance", "tdn")


@pytest.fixture(scope="module")
def scenario() -> tuple[dict[str, Any], dict[int, float]]:
    inputs, midwest, _ = build_experiment()
    return inputs, midwest


@pytest.mark.parametrize(
    ("has_previous", "expected_cost", "expected_source"),
    [(False, 0.27455306, "minimum_cost"), (True, 0.29038518, "previous_ration")],
)
def test_pen_contract_returns_only_final_approved_quantities(
    scenario: tuple[dict[str, Any], dict[int, float]],
    has_previous: bool,
    expected_cost: float,
    expected_source: str,
) -> None:
    inputs, midwest = scenario
    adapter = LinearRationAdapter("single")
    solution, config = adapter.attempt_optimization(**inputs, previous_ration=midwest if has_previous else None)
    assert solution.success and solution.status == LinearAttemptStatus.APPROVED
    assert solution.selected_reference == expected_source
    assert solution.fun == pytest.approx(expected_cost)
    assert solution.references_resolved == 1 and solution.stop_reason == "reference_limit"
    assert solution.lower_bound is not None and solution.gap is not None
    assert dict(zip((feed.rufas_id for feed in config.feeds_used), solution.x, strict=True)) == solution.quantities
    reordered = list(reversed(inputs["pen_available_feeds"]))
    final = adapter.make_ration_from_solution(reordered, solution)
    assert list(final) == [feed.rufas_id for feed in reordered]
    assert final == solution.quantities
    assert LinearRationOptimizer.validate_nrc_candidate(config, final).status.value == "approved"
    report = solution.references[0].selection
    assert report is not None
    if has_previous:
        assert report.validations[report.selected_case].repair is not None
        assert final[23] == pytest.approx(0.019201)


@pytest.fixture
def stub_search(
    scenario: tuple[dict[str, Any], dict[int, float]],
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    _, midwest = scenario
    calls = []

    def make_reference(config: Any, source: str, solver: Any) -> tuple[dict[int, float], dict[str, int]]:
        calls.append(source)
        return {**midwest, 23: 0.1 * len(calls)}, {"lp_calls": 1}

    monkeypatch.setattr(adapter_module, "primary_lower_bound", lambda *_: {"lower_bound": 9.0, "status": "Optimal"})
    monkeypatch.setattr(adapter_module, "build_basic_reference", make_reference)
    return calls


def approved(reference: dict[int, float], cost: float) -> NRCSelectionResult:
    check = NRCResiduals({}, {})
    verification = NRCValidationResult(check, check, reference)
    return NRCSelectionResult(
        {CASE: LinearRationResult(LinearRationStatus.OPTIMAL)}, {CASE: verification}, CASE, cost, ""
    )


@pytest.mark.parametrize(
    ("strategy", "budget", "sources", "winner", "stop"),
    [
        ("adaptive_gap", 5, ["minimum_cost", "maximum_forage"], "maximum_forage", "gap_target_reached"),
        ("adaptive_gap", 1, ["minimum_cost"], "minimum_cost", "reference_limit"),
        (
            "full",
            5,
            ["minimum_cost", "maximum_forage", "maximum_concentrate", "target_dmi"],
            "maximum_concentrate",
            "references_exhausted",
        ),
    ],
)
def test_strategy_budget_and_best_approved_cost(
    scenario: tuple[dict[str, Any], dict[int, float]],
    stub_search: list[str],
    monkeypatch: pytest.MonkeyPatch,
    strategy: str,
    budget: int,
    sources: list[str],
    winner: str,
    stop: str,
) -> None:
    inputs, _ = scenario
    adapter = LinearRationAdapter(LinearSearchStrategy(strategy), max_references=budget)
    costs = dict(zip(adapter_module.OBJECTIVES, [10.0, 9.2, 9.1, 11.0], strict=True))
    monkeypatch.setattr(
        adapter.optimizer,
        "solve_and_validate_nrc_cases",
        lambda config, reference, solver: approved(reference, costs[stub_search[-1]]),
    )
    result, _ = adapter.attempt_optimization(**inputs)
    assert result.success and result.stop_reason == stop
    assert stub_search == sources and result.selected_reference == winner
    assert result.fun == costs[winner]
    assert result.references_resolved == len(sources)


def test_removed_ingredient_falls_back_to_generated_reference(
    scenario: tuple[dict[str, Any], dict[int, float]],
    stub_search: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, previous = scenario
    adapter = LinearRationAdapter("single")
    monkeypatch.setattr(
        adapter.optimizer, "solve_and_validate_nrc_cases", lambda config, reference, solver: approved(reference, 10.0)
    )
    result, _ = adapter.attempt_optimization(**inputs, previous_ration={**previous, 999: 1.0})
    assert result.success
    assert result.references_resolved == 1 and stub_search == ["minimum_cost"]
    assert result.references[0].source == "previous_ration"
    assert "unavailable feed 999" in result.references[0].message
    assert 999 not in result.quantities


@pytest.mark.parametrize(
    ("case_status", "status", "failed_constraints"),
    [
        (LinearRationStatus.INFEASIBLE, LinearAttemptStatus.INFEASIBLE, []),
        (LinearRationStatus.SOLVER_ERROR, LinearAttemptStatus.SOLVER_ERROR, []),
        (LinearRationStatus.OPTIMAL, LinearAttemptStatus.NRC_REJECTED, ["protein_constraint_lower"]),
    ],
)
def test_failures_preserve_pen_retry_diagnostics_without_a_vector(
    scenario: tuple[dict[str, Any], dict[int, float]],
    stub_search: list[str],
    monkeypatch: pytest.MonkeyPatch,
    case_status: LinearRationStatus,
    status: LinearAttemptStatus,
    failed_constraints: list[str],
) -> None:
    inputs, _ = scenario
    adapter = LinearRationAdapter("single")
    rejected = NRCValidationResult(NRCResiduals({}, {"protein_constraint_lower": "Deficit"}))
    selection = NRCSelectionResult(
        {CASE: LinearRationResult(case_status)}, {CASE: rejected} if failed_constraints else {}, None, None, ""
    )
    monkeypatch.setattr(adapter.optimizer, "solve_and_validate_nrc_cases", lambda *_: selection)
    result, config = adapter.attempt_optimization(**inputs)
    assert result.status == status and not result.success and result.x is None
    assert (
        adapter.handle_failed_constraints(
            num_attempts=1,
            solution=result,
            ration_config=config,
            animal_combination=config.animal_combination,
            pen_id=1,
            pen_available_feeds=config.feeds_used,
            average_nutrient_requirements=config.animal_requirements,
            initial_dry_matter_requirement=config.initial_dry_matter_requirement,
            initial_protein_requirement=config.initial_protein_requirement,
            sim_day=0,
        )
        == failed_constraints
    )
    with pytest.raises(ValueError, match="No approved"):
        adapter.make_ration_from_solution(config.feeds_used, result)


@pytest.mark.parametrize(
    "unsupported",
    [
        {"nutrient_standard": NutrientStandard.NASEM},
        {"animal_combination": AnimalCombination.CALF},
        {"user_defined_ration_dictionary": {}},
        {"user_defined_ration_tolerance": 0.0},
    ],
)
def test_rejects_unsupported_modes_before_trying_solver(
    scenario: tuple[dict[str, Any], dict[int, float]],
    unsupported: dict[str, Any],
) -> None:
    inputs, _ = scenario
    with pytest.raises(ValueError, match="automatic NRC formulation for lactating cows only"):
        LinearRationAdapter().attempt_optimization(**(inputs | unsupported))


@pytest.mark.parametrize("solver_name", ["cbc", "highs"])
def test_only_nutritional_cases_use_configured_solver(scenario, monkeypatch, solver_name):
    if solver_name == "highs":
        pytest.importorskip("highspy")
    calls = Counter()

    def record(actual_solve):
        def solve(solver, problem, **kwargs):
            stage = "nutrition" if "minimum_total_energy" in problem.constraints else "basic"
            calls[stage, solver.name] += 1
            return actual_solve(solver, problem, **kwargs)

        return solve

    monkeypatch.setattr(pulp.PULP_CBC_CMD, "actualSolve", record(pulp.PULP_CBC_CMD.actualSolve))
    if solver_name == "highs":
        monkeypatch.setattr(pulp.HiGHS, "actualSolve", record(pulp.HiGHS.actualSolve))
    inputs, _ = scenario
    adapter = LinearRationAdapter("single", nutritional_solver=solver_name)
    solution, _ = adapter.attempt_optimization(**inputs)
    assert solution.success
    assert solution.lower_bound is not None
    (reference,) = solution.references
    assert reference.generation_calls > 0
    assert solution.nutritional_solver == ("HiGHS" if solver_name == "highs" else "PULP_CBC_CMD")
    assert calls == {
        ("basic", "PULP_CBC_CMD"): reference.generation_calls + 1,
        ("nutrition", solution.nutritional_solver): 6,
    }


def test_unavailable_highs_raises_explicitly(monkeypatch):
    monkeypatch.setattr(pulp.HiGHS, "available", lambda self: False)
    with pytest.raises(RuntimeError, match=r"PuLP/HiGHS.*highspy"):
        LinearRationAdapter(nutritional_solver="highs")


def test_unavailable_highs_reference_solver_raises_explicitly(monkeypatch):
    monkeypatch.setattr(pulp.HiGHS, "available", lambda self: False)
    with pytest.raises(RuntimeError, match=r"PuLP/HiGHS.*reference generation.*highspy"):
        LinearRationAdapter(reference_solver="highs")


def test_unavailable_highs_bound_solver_raises_explicitly(monkeypatch):
    monkeypatch.setattr(pulp.HiGHS, "available", lambda self: False)
    with pytest.raises(RuntimeError, match=r"PuLP/HiGHS.*cost lower bound.*highspy"):
        LinearRationAdapter(bound_solver="highs")
