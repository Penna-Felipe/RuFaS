"""Match the production adapter to the archived controlled Midwest experiment."""

import json
from pathlib import Path

import pytest

pytest.importorskip("pulp")
pytest.importorskip("highspy")

from helpful_scripts.nrc_ration_comparison.cli_three_day import BASE  # noqa: E402
from helpful_scripts.nrc_ration_comparison.solver_benchmark import scenario_inputs  # noqa: E402
from RUFAS.biophysical.animal.ration.linear_ration_adapter import LinearRationAdapter  # noqa: E402
from RUFAS.biophysical.animal.ration.ration_manager import RationManager  # noqa: E402


@pytest.mark.parametrize("budget", [2, 3, 5])
def test_midwest_production_matches_27_archived_formulations(monkeypatch, budget):
    archive = Path("output/nrc_independent_references/results.json")
    audit = BASE / "isolated_audit.json"
    if not all(path.is_file() for path in (archive, audit, BASE / "inputs/feed.json")):
        pytest.skip("Archived independent reference inputs or results are unavailable.")
    expected = json.loads(archive.read_text(encoding="utf-8"))["scenarios"]
    monkeypatch.setattr(RationManager, "intake_options", {})
    recipe = Path("input/data/feed/example_Midwest_feed.json")
    solvers = dict(reference_solver="highs", bound_solver="highs", nutritional_solver="highs")
    adapters = {
        "A": LinearRationAdapter("full", max_references=budget, **solvers),
        "B_early" if budget < 5 else "B_late": LinearRationAdapter(
            "full", max_references=budget, midwest_reference_path=recipe, **solvers
        ),
    }
    tested = set()
    for name, config, _, previous in scenario_inputs(audit, generate_historical_references=False):
        tested.add(name)
        for arm, adapter in adapters.items():
            observed = adapter._search(config, previous)
            result = expected[name]["policies"][f"{arm}/{budget}"]["result"]
            assert observed.success == bool(result["best"]), (name, arm)
            assert observed.lower_bound == result["bound"]
            assert observed.gap == pytest.approx(result["gap"], abs=1e-12)
            assert observed.solver_calls == result["calls"]
            reference_names = {"previous": "previous_ration", "Midwest": "midwest"}
            selected = result["best"]
            assert observed.fun == pytest.approx(selected["cost"], abs=1e-10)
            assert observed.quantities == {int(key): value for key, value in selected["quantities"].items()}
            assert observed.selected_reference == reference_names.get(selected["source"], selected["source"])
            assert [ref.source for ref in observed.references if ref.selection is not None] == [
                reference_names.get(source, source) for source in result["refs"]
            ]
            for ref in observed.references:
                if ref.selection is None:
                    continue
                name_in_archive = next(
                    (key for key, value in reference_names.items() if value == ref.source), ref.source
                )
                statuses = {
                    "/".join(regime): (
                        ref.selection.validations[regime].status.value
                        if regime in ref.selection.validations
                        else case.status.value
                    )
                    for regime, case in ref.selection.cases.items()
                }
                assert statuses == result["case_summary"][name_in_archive]["regimes"]
    assert len(tested) == 27 and tested == expected.keys()
