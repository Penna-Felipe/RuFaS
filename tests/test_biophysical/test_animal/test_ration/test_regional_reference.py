"""Projection, validation and selection of an explicitly configured Midwest recipe."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("pulp")

from RUFAS.biophysical.animal.ration import linear_ration_adapter as adapter_module  # noqa: E402
from RUFAS.biophysical.animal.ration.linear_ration_adapter import LinearRationAdapter  # noqa: E402
from RUFAS.biophysical.animal.ration.ration_backend_config import RationBackendConfig  # noqa: E402
from RUFAS.biophysical.animal.ration.regional_reference import MidwestRecipe  # noqa: E402

original_energy = adapter_module.LinearRationOptimizer.calculate_nrc_energy_coefficients


def recipe_file(path, shares, group="lac_cow"):
    feeds = [{"feed_type": key, "ration_percentage": value} for key, value in shares.items()]
    path.write_text(json.dumps({"rations": [{"animal_combination": group, "feeds": feeds}]}), encoding="utf-8")
    return path


def config(*ids):
    return SimpleNamespace(
        feeds_used=[SimpleNamespace(rufas_id=key) for key in ids],
        feed_minimum_list=[0] * len(ids),
        feed_maximum_list=[100] * len(ids),
        initial_dry_matter_requirement=25.0,
    )


@pytest.mark.parametrize(
    ("menu", "expected", "retention", "removed"),
    [
        ((1, 2), {1: 10, 2: 15}, 100, {}),
        ((1,), {1: 25}, 40, {2: 60}),
        ((3,), {}, 0, {1: 40, 2: 60}),
    ],
)
def test_normalizes_available_ingredients(tmp_path, menu, expected, retention, removed):
    recipe = MidwestRecipe.load(recipe_file(tmp_path / "custom.json", {1: 40, 2: 60}))
    quantities, audit = recipe.project(config(*menu))
    assert quantities == expected
    assert audit["retained_original_percent"] == retention
    assert audit["removed_ingredients"] == removed
    assert audit["issue"] is None if expected else "No positive recipe ingredients" in audit["issue"]
    assert sum(audit["normalized_percentages"].values()) == (100 if expected else 0)
    assert audit["origin"] == "midwest"
    assert audit["animal_group"] == "lac_cow"


@pytest.mark.parametrize("value", [None, -5, "30", True, float("nan"), 101, 0])
def test_invalid_or_missing_percentages(tmp_path, value):
    path = recipe_file(tmp_path / "invalid.json", {1: value})
    if value is None:
        doc = json.loads(path.read_text(encoding="utf-8"))
        del doc["rations"][0]["feeds"][0]["ration_percentage"]
        path.write_text(json.dumps(doc), encoding="utf-8")
    recipe = MidwestRecipe.load(path)
    quantities, audit = recipe.project(config(1))
    assert quantities == {} and audit["issue"]


def test_recipe_demands_lactation_group(tmp_path):
    path = recipe_file(tmp_path / "rearing.json", {1: 100}, "growing")
    assert "lactating cow" in MidwestRecipe.load(path).issue


@pytest.mark.parametrize("invalid", [None, "/root/feed.json", r"C:\feed.json", " "])
def test_configuration_rejects_invalid_paths(invalid):
    assert RationBackendConfig.from_mapping({}).midwest_reference_path is None
    assert RationBackendConfig.from_mapping(
        {"linear_midwest_reference_path": "feeds/ration.json"}
    ).midwest_reference_path == Path("feeds/ration.json")
    with pytest.raises(ValueError, match="linear_midwest_reference_path"):
        RationBackendConfig.from_mapping({"linear_midwest_reference_path": invalid})


@pytest.fixture
def stub_solver(monkeypatch):
    monkeypatch.setattr(adapter_module, "primary_lower_bound", lambda *_: {"lower_bound": 1.0})
    values = (10, 11, 12, 13)
    sources = dict(zip(adapter_module.OBJECTIVES, values, strict=True))
    monkeypatch.setattr(
        adapter_module,
        "build_basic_reference",
        lambda cfg, name, _: ({cfg.feeds_used[0].rufas_id: sources[name]}, {"lp_calls": 1}),
    )
    monkeypatch.setattr(adapter_module.LinearRationOptimizer, "calculate_nrc_energy_coefficients", lambda *_: {})
    monkeypatch.setattr(adapter_module.LinearRationOptimizer, "calculate_nrc_protein_coefficients", lambda *_: {})
    monkeypatch.setattr(
        adapter_module.LinearRationOptimizer,
        "solve_and_validate_nrc_cases",
        lambda *args: SimpleNamespace(cases={}, selected_case=None, selected_cost=None),
    )


@pytest.mark.parametrize(
    ("strategy", "budget", "previous", "expected"),
    [
        ("single", 5, None, ["minimum_cost"]),
        ("full", 2, None, ["minimum_cost", "midwest"]),
        ("full", 2, {1: 8}, ["previous_ration", "minimum_cost"]),
        ("adaptive_gap", 3, {1: 8}, ["previous_ration", "minimum_cost", "midwest"]),
        ("full", 5, None, ["minimum_cost", "maximum_forage", "maximum_concentrate", "target_dmi", "midwest"]),
        ("full", 5, {1: 8}, ["previous_ration", "minimum_cost", "maximum_forage", "maximum_concentrate", "target_dmi"]),
    ],
)
def test_budget_order(tmp_path, stub_solver, strategy, budget, previous, expected):
    path = recipe_file(tmp_path / "midwest.json", {1: 100})
    adapter = LinearRationAdapter(strategy, max_references=budget, midwest_reference_path=path)
    result = adapter._search(config(1), previous)
    assert [r.source for r in result.references if r.selection is not None] == expected
    assert result.references_resolved == len(expected)
    assert result.regional_reference["explored"] == ("midwest" in expected)
    if "midwest" not in expected:
        assert "not reached" in result.regional_reference["issue"]


def test_disabled_and_duplicate_midwest(tmp_path, stub_solver):
    disabled = LinearRationAdapter("full", max_references=3)._search(config(1), None)
    assert disabled.regional_reference is None
    assert [r.source for r in disabled.references] == list(adapter_module.OBJECTIVES[:3])
    path = recipe_file(tmp_path / "midwest.json", {1: 100})
    enabled = LinearRationAdapter("full", max_references=3, midwest_reference_path=path)._search(config(1), {1: 25})
    assert enabled.regional_reference["duplicate_of"] == "previous_ration"
    assert not enabled.regional_reference["explored"]
    assert enabled.references_resolved == 3
    assert [r.source for r in enabled.references if r.selection is not None] == [
        "previous_ration",
        "minimum_cost",
        "maximum_forage",
    ]


def test_unavailable_nrc_composition_is_discarded(tmp_path, stub_solver):
    path = recipe_file(tmp_path / "midwest.json", {1: 100})
    adapter = LinearRationAdapter("full", max_references=2, midwest_reference_path=path)
    # Exercise the actual coefficient calculator on an ingredient with missing composition.
    from helpful_scripts.nrc_ration_comparison.compare import build_experiment
    from helpful_scripts.nrc_ration_comparison.sensitivity import make_config
    from dataclasses import replace

    inputs, _, _ = build_experiment()
    real = make_config(inputs)
    real.feeds_used = [replace(f, TDN=float("nan")) for f in real.feeds_used]
    path = recipe_file(path, {real.feeds_used[0].rufas_id: 100})
    adapter.midwest_recipe = MidwestRecipe.load(path)
    real.feed_minimum_list = [0] * len(real.feeds_used)
    real.feed_maximum_list = [100] * len(real.feeds_used)
    # Install the real preparation and energy calculator again after the search stubs.
    adapter.optimizer.calculate_nrc_energy_coefficients = original_energy
    result = adapter._search(real, None)
    assert "Invalid NRC reference coefficients" in result.regional_reference["issue"]
    assert result.references_resolved == 2
