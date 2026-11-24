"""Checks for the isolated lazy-reference benchmark."""

import random
from typing import Any

import pytest

pytest.importorskip("pulp")

from helpful_scripts.nrc_ration_comparison import adaptive  # noqa: E402
from helpful_scripts.nrc_ration_comparison.compare import build_experiment  # noqa: E402
from helpful_scripts.nrc_ration_comparison.sensitivity import make_config  # noqa: E402
from RUFAS.biophysical.animal.ration.ration_optimizer import RationConfig  # noqa: E402


@pytest.mark.parametrize(
    ("strategy", "first_valid", "expected_calls", "chosen"),
    [
        ("single", False, ["minimum_cost"], None),
        ("adaptive", True, ["minimum_cost"], "minimum_cost"),
        ("adaptive", False, ["minimum_cost", "maximum_forage"], "maximum_forage"),
        ("full", True, ["minimum_cost", "maximum_forage", "maximum_concentrate", "target_dmi"], "maximum_concentrate"),
    ],
)
def test_reference_generation_is_lazy_and_full_search_can_improve_cost(
    monkeypatch: pytest.MonkeyPatch,
    strategy: str,
    first_valid: bool,
    expected_calls: list[str],
    chosen: str | None,
) -> None:
    inputs, midwest, _ = build_experiment()
    config = make_config(inputs)
    calls = []
    references = {name: {**midwest, 23: midwest[23] + i} for i, name in enumerate(adaptive.OBJECTIVES, 1)}

    def generate(_: RationConfig, goal: str) -> tuple[dict[int, float], dict[str, Any]]:
        calls.append(goal)
        return references[goal], {}

    costs = {
        "minimum_cost": 4.0 if first_valid else None,
        "maximum_forage": 3.0,
        "maximum_concentrate": 2.0,
        "target_dmi": None,
    }

    def solve(_: RationConfig, diet: dict[int, float]) -> tuple[dict[str, Any], dict[str, float]]:
        goal = next((goal for goal, reference in references.items() if reference == diet), "midwest")
        return {"selected_cost": costs.get(goal), "selected_case": ("maintenance", "tdn")}, {"coefficients": 0.0}

    monkeypatch.setattr(adaptive, "basic_reference", generate)
    monkeypatch.setattr(adaptive, "run_reference", solve)
    report, timing = adaptive.evaluate_strategy(config, midwest, strategy)
    assert calls == expected_calls
    assert (report["selected"]["reference"] if report["selected"] else None) == chosen
    assert timing["full"] >= timing["generation"] > 0


def test_historical_equal_energy_is_due_to_same_no_discount_branch() -> None:
    report = adaptive.historical_audit()
    for role in ("minimum_cost_reference", "approved_diet"):
        assert report[role]["factor"] == 1
        assert report[role]["tdn_percent"] < 60
        assert report[role]["regime"] == "tdn_percentage_below_60"
    assert max(row["absolute_error"] for row in report["energy_errors"].values()) < 1e-12
    concentration = report["maximum_concentrate_basic_residuals"]
    assert concentration["residuals"]["DMI_constraint_upper"] == pytest.approx(-7.80727106e-7)
    assert "DMI_constraint_upper" in concentration["violations"]


def test_factorial_scenarios_keep_requirements_and_bounds_across_price_profiles() -> None:
    rows = {name: (inputs, diet, metadata) for name, inputs, diet, metadata in adaptive.scenario_grid()}
    assert len(rows) == 12
    for name, (_, reference, market) in rows.items():
        if market["prices"] != "market":
            continue
        _, other_reference, illustrative = rows[name.replace("_market", "_illustrative")]
        assert market["requirements"] == illustrative["requirements"]
        assert reference == other_reference
        assert market["feeds"].keys() == illustrative["feeds"].keys()
        for key, feed in market["feeds"].items():
            assert (feed["lower"], feed["upper"]) == (
                illustrative["feeds"][key]["lower"],
                illustrative["feeds"][key]["upper"],
            )
            assert feed["usd_per_kg_dm"] == adaptive.MARKET_PRICES[key]


def test_slsqp_uses_logged_seed_and_restores_random_state(monkeypatch: pytest.MonkeyPatch) -> None:
    draws = []

    def original(_: dict[str, Any], previous: dict[int, float]) -> tuple[dict[str, Any], dict[str, float]]:
        assert previous == {}
        draws.append(random.random())
        return {}, {"attempt_with_setup": 1.0, "validation": 0.5}

    monkeypatch.setattr(adaptive, "run_slsqp", original)
    state = random.getstate()
    for _ in range(2):
        report, timings = adaptive.seeded_slsqp({}, 42)
        assert report["seed"] == 42
        assert timings["full"] == 1.5
        assert random.getstate() == state
    assert draws[0] == draws[1] == random.Random(42).random()


def test_benchmark_serializes_one_real_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    scenario = adaptive.scenario_grid()[0]
    monkeypatch.setattr(adaptive, "scenario_grid", lambda: [scenario])
    result = adaptive.experiment(1, 42)
    payload = json.dumps(adaptive.json_safe(result), allow_nan=False)
    assert result["summary"]["strategies"]["adaptive"]["approved_scenarios"] == 1
    assert scenario[0] in payload
