"""Tests for the isolated NRC gap experiment."""

from typing import Any

import pytest

pulp = pytest.importorskip("pulp")

from helpful_scripts.nrc_ration_comparison import gap_experiment as gap  # noqa: E402
from helpful_scripts.nrc_ration_comparison.compare import build_experiment  # noqa: E402
from helpful_scripts.nrc_ration_comparison.sensitivity import make_config  # noqa: E402


def test_degenerate_gaps_do_not_stop_search() -> None:
    assert gap.relative_gap(10, 8)[0] == pytest.approx(0.2)
    assert gap.relative_gap(10, 0) == (1.0, "zero_bound")
    assert gap.relative_gap(10, -5) == (1.5, "negative_bound")
    assert gap.relative_gap(0, 0) == (0.0, "zero_cost_and_bound")
    assert gap.relative_gap(1, 2) == (None, "incumbent_below_bound")
    assert gap.relative_gap(1, None) == (None, "missing_cost_or_bound")
    assert not gap.meets_target(10, 0, 0.1)
    assert not gap.meets_target(1, 2, 0.1)
    assert gap.meets_target(10.0, 9.5, 0.05)


def test_dual_residual_correction_bounds_the_cost_with_imperfect_multiplier() -> None:
    p = pulp.LpProblem("toy")
    x = pulp.LpVariable("x", lowBound=0, upBound=4)
    p += 2 * x
    for name in gap.ROWS:
        p += (x >= 2 if name == "minimum_dmi" else 0 * x >= 0), name
        p.constraints[name].pi = 3 if name == "minimum_dmi" else 0
    assert gap.dual_bound(p, [x], tolerant=False) == 2
    assert gap.dual_bound(p, [x], tolerant=True) <= 2 - 4e-7


def test_ratio_tolerance_relaxes_row_in_proportion_to_intake() -> None:
    p = pulp.LpProblem("toy_ratio")
    x = pulp.LpVariable("x", lowBound=0, upBound=100)
    y = pulp.LpVariable("y", lowBound=0, upBound=100)
    p += x + 2 * y
    for name in gap.ROWS:
        if name == "minimum_dmi":
            p += x + y >= 20, name
            p.constraints[name].pi = 1.5
        elif name == "minimum_ndf":
            p += y - x >= 0, name
            p.constraints[name].pi = 0.5
        else:
            p += 0 * x >= 0, name
            p.constraints[name].pi = 0
    usual = gap.dual_bound(p, [x, y], tolerant=False)
    tolerant = gap.dual_bound(p, [x, y], tolerant=True)
    assert usual == 30.0
    assert tolerant < usual
    # At a 20 kg intake the ratio tolerance allows y-x=-20e-6.
    assert tolerant <= 30.0 - 10e-6


def test_primary_bound_precedes_generator_tiebreaks() -> None:
    inputs, _, _ = build_experiment()
    bound = gap.primary_lower_bound(make_config(inputs))
    assert bound["status"] == "Optimal"
    assert bound["primary_optimum_cbc"] == pytest.approx(0.22854547, abs=1e-7)
    assert bound["lower_bound"] <= bound["strict_lower_bound"] <= bound["primary_optimum_cbc"]
    assert bound["primary_optimum_cbc"] - bound["lower_bound"] < 1e-5


@pytest.mark.parametrize(("goal", "expected"), [(0.10, ["first", "second"]), (0.01, ["first", "second", "third"])])
def test_gap_policy_passes_lazy_stop_to_search(
    monkeypatch: pytest.MonkeyPatch,
    goal: float,
    expected: list[str],
) -> None:
    inputs, diet, _ = build_experiment()
    monkeypatch.setattr(gap, "primary_lower_bound", lambda _: {"lower_bound": 9.0})
    calls = []

    def search(*_: Any, stop_cost: Any) -> tuple[dict[str, Any], dict[str, float]]:
        best = float("inf")
        references = {}
        for label, cost in (("first", 12.0), ("second", 10.0), ("third", 11.0)):
            calls.append(label)
            references[label] = {"cases": [{}] * 6, "generation": {"lp_calls": 2}}
            best = min(best, cost)
            if stop_cost(best):
                break
        return {"references": references, "selected": {"cost": best}}, {}

    monkeypatch.setattr(gap, "evaluate_strategy", search)
    result, timings = gap.run_policy(make_config(inputs), diet, "full", goal)
    assert calls == expected
    assert result["selected"]["cost"] == 10.0
    assert result["solver_calls"]["total"] == 8 * len(expected) + 1
    assert timings["full"] >= timings["lower_bound"]


def test_slsqp_repair_audits_raw_and_rounded_status() -> None:
    inputs, _, _ = build_experiment()
    report, _ = gap.slsqp_with_repair(inputs, 42)
    assert report["raw_approved"] and not report["rounded_approved"]
    assert report["repair_approved"] and report["final_cost"] is not None
