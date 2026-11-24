"""Replay the 552 archived nutritional LPs through the production solver path."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

pytest.importorskip("pulp")
pytest.importorskip("highspy")

from RUFAS.biophysical.animal.ration.linear_ration_adapter import LinearRationAdapter  # noqa: E402
from RUFAS.biophysical.animal.ration.ration_manager import RationManager  # noqa: E402
from helpful_scripts.nrc_ration_comparison.solver_benchmark import (  # noqa: E402
    BASE,
    DEST,
    LinearRationOptimizer,
    json_safe,
    linear_matrix,
    resids,
    scenario_inputs,
)

COST_TOLERANCE = 1e-8


def assert_record(actual, expected):
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            assert_record(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for value, archived in zip(actual, expected, strict=True):
            assert_record(value, archived)
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, abs=1e-8, rel=1e-12)
    else:
        assert actual == expected


@pytest.mark.parametrize(
    ("solver_name", "archive_key", "expected_approved"),
    [
        ("cbc", "cbc", (187, 114, 54, 168)),
        ("highs", "pulp_highs", (264, 113, 110, 223)),
    ],
)
def test_frozen_nutritional_cases(monkeypatch, solver_name, archive_key, expected_approved):
    archive_path = DEST / "results.json"
    audit_path = BASE / "isolated_audit.json"
    for artifact in (archive_path, audit_path, BASE / "inputs/feed.json"):
        if not artifact.is_file():
            pytest.skip(f"Frozen benchmark artifact unavailable: {artifact}")

    # The scenario loader configures class-level intake options for the archived CLI inputs.
    monkeypatch.setattr(RationManager, "intake_options", {}, raising=False)
    archive = json.loads(Path(archive_path).read_text(encoding="utf-8"))["problems"]
    configs = {name: config for name, config, _, _ in scenario_inputs(audit_path, generate_historical_references=False)}
    assert configs.keys() == archive.keys()
    adapter = LinearRationAdapter(nutritional_solver=solver_name)
    counts = {"optimal": 0, "infeasible": 0}
    approvals = [0, 0, 0, 0]
    approved_formulations = 0

    for scenario, config in configs.items():
        frozen = archive[scenario]
        feed_ids = frozen["ordered_feed_ids"]
        assert [feed.rufas_id for feed in config.feeds_used] == feed_ids
        formulation_approved = False
        for source, reference in frozen["core"].items():
            captured = []

            def capture(config, problem, variables, solver):
                assert list(variables) == feed_ids
                assert solver is adapter.nutritional_solver
                captured.append(linear_matrix(problem, variables))
                return LinearRationOptimizer._solve_problem(config, problem, variables, solver)

            monkeypatch.setattr(adapter.optimizer, "_solve_problem", capture)
            diet = {int(key): value for key, value in reference["diet"].items()}
            result = adapter.optimizer.solve_and_validate_nrc_cases(config, diet, adapter.nutritional_solver)
            assert len(result.cases) == 6
            for (regime, case), matrix, row in zip(result.cases.items(), captured, reference["cases"], strict=True):
                context = (scenario, source, regime, solver_name)
                assert list(regime) == row["regime"], context
                digest = hashlib.sha256(json.dumps(matrix, sort_keys=True).encode()).hexdigest()
                assert digest == row["same_matrix_sha256"], context
                expected = row["results"][archive_key]
                assert case.status.value == expected["status"].lower(), context
                counts[case.status.value] += 1
                if case.quantities is None:
                    assert case.status.value == "infeasible" and regime not in result.validations, context
                    continue

                assert set(case.quantities) == set(feed_ids) == set(map(int, expected["quantities_kg_dm"])), context
                assert case.cost == pytest.approx(expected["raw_cost"], abs=COST_TOLERANCE, rel=0), context
                validation = result.validations[regime]
                repair = validation.repair
                final = validation.final_quantities
                stages = (
                    not validation.unrounded.violations,
                    validation.rounded is not None and not validation.rounded.violations,
                    repair is not None and repair.validation is not None and not repair.validation.violations,
                    final is not None,
                )
                assert stages == tuple(
                    expected[key] for key in ("raw_approved", "rounded_approved", "repair_approved", "final_approved")
                ), context
                # The benchmark summary counts rounded approvals only among raw approvals.
                raw, rounded, repaired, final_approved = stages
                summary_stages = (raw, raw and rounded, repaired, final_approved)
                approvals = [count + stage for count, stage in zip(approvals, summary_stages, strict=True)]
                formulation_approved |= final is not None
                residuals = resids(matrix, [case.quantities[feed_id] for feed_id in feed_ids])
                archived_vector = {int(key): value for key, value in expected["quantities_kg_dm"].items()}
                # An alternative optimum can have different row margins and NRC residuals.
                if case.quantities == archived_vector:
                    assert_record(residuals, expected["matrix_residuals"])
                    actual_validation = json.loads(json.dumps(json_safe(asdict(validation))))
                    assert_record(actual_validation, expected["nrc_validation"])
                    if final is not None:
                        assert_record({str(key): value for key, value in final.items()}, expected["final_quantities"])
                else:
                    assert all(
                        margin >= min(-1e-7, expected["matrix_residuals"][name]) - 1e-8
                        for name, margin in residuals.items()
                    ), context
                    assert all(
                        lower - 1e-7 <= case.quantities[key] <= upper + 1e-7
                        for key, (lower, upper) in zip(feed_ids, matrix["bounds"], strict=True)
                    ), context
                if final is not None:
                    final_cost = sum(
                        final[key] * price for key, price in zip(feed_ids, matrix["objective"], strict=True)
                    )
                    assert final_cost == pytest.approx(expected["final_cost"], abs=COST_TOLERANCE, rel=0), context
        approved_formulations += formulation_approved

    assert counts == {"optimal": 466, "infeasible": 86}
    assert tuple(approvals) == expected_approved
    assert approved_formulations == 23
