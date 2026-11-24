"""Tests for the installed experimental ration commands."""

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from RUFAS.main import parse_gnu_args

from helpful_scripts.nrc_ration_comparison import ration_cli
from helpful_scripts.nrc_ration_comparison.cli_three_day import ROOT, read, write
from helpful_scripts.nrc_ration_comparison.comparison_report_output import generate
from helpful_scripts.nrc_ration_comparison.terminal_report import show, summarize


def test_default_commands_and_original_entry_point():
    linear = ration_cli.parse_args(False, [])
    compare = ration_cli.parse_args(True, [])
    assert (linear.days, linear.seed, linear.references, linear.strategy) == (3, 42, 5, "full")
    assert not linear.html and not compare.html
    assert linear.midwest and compare.midwest
    assert linear.methods == [ration_cli.Method("highs5", 5)]
    assert compare.methods == [ration_cli.Method("slsqp"), ration_cli.Method("highs5", 5)]
    with (ROOT / "pyproject.toml").open("rb") as stream:
        scripts = tomllib.load(stream)["project"]["scripts"]
    assert scripts["rufas"] == "RUFAS.main:main"
    assert scripts["rufas-linear"].endswith("ration_cli:linear")
    assert scripts["rufas-compare"].endswith("ration_cli:compare")
    assert parse_gnu_args([]).path_to_metadata == "input/task_manager_metadata.json"
    assert parse_gnu_args(["-g", "-p", "own_task_manager.json"]).no_graphics


def test_method_selection():
    args = ration_cli.parse_args(
        True,
        [
            "--methods",
            "highs",
            "--references",
            "3",
            "5",
            "--strategy",
            "adaptive_gap",
            "--gap-target",
            "0.1",
            "--no-midwest",
            "--verbosity",
            "logs",
            "--html",
        ],
    )
    assert args.methods == [ration_cli.Method("highs3", 3), ration_cli.Method("highs5", 5)]
    assert args.strategy == "adaptive_gap" and args.gap_target == 0.1
    assert not args.midwest and args.html and args.verbosity == "logs"


@pytest.mark.parametrize(
    "argv",
    [
        ["--days", "0"],
        ["--seed", "0"],
        ["--seed", "4294967296"],
        ["--gap-target", "nan"],
        ["--references", "0"],
        ["--references", "3", "3"],
        ["--methods", "highs", "highs"],
    ],
)
def test_invalid_arguments(argv):
    with pytest.raises(SystemExit) as exception:
        ration_cli.parse_args(True, argv)
    assert exception.value.code == 2


def test_preparation_and_output_isolation(tmp_path):
    args = ration_cli.parse_args(True, ["--references", "3", "5", "--seed", "73", "--output", str(tmp_path)])
    first = ration_cli.allocate_output(args.output, "compare")
    second = ration_cli.allocate_output(args.output, "compare")
    assert first != second
    preserved = second / "keep.json"
    write(preserved, {"previous": True})
    template = ROOT / "input/metadata/example_animals_only_metadata.json"
    original = template.read_bytes()
    runs, dates = ration_cli.prepare(first, args)
    assert dates == ["2013-05-30", "2013-05-31", "2013-06-01"]
    assert template.read_bytes() == original and read(preserved) == {"previous": True}
    for arm in runs:
        task_path = read(arm.task_manager)["files"]["tasks"]["path"]
        (task,) = read(task_path)["tasks"]
        paths = read(arm.metadata)["files"]
        assert Path(task["metadata_file_path"]) == arm.metadata
        assert task["random_seeds"] == [73]
        assert Path(task["json_output_directory"]) == arm.output / "JSONs"
        assert Path(task["logs_directory"]) == arm.output / "logs"
        assert Path(paths["config"]["path"]) == first / "inputs/config.json"
        assert Path(paths["feed"]["path"]) == first / "inputs/feed.json"
        config = read(paths["config"]["path"])
        assert config["end_date"] == "2013:152" and config["nutrient_standard"] == "NRC"
        ration = read(paths["animal"]["path"])["ration"]
        assert ration["optimizer_backend"] == arm.method.backend and ration["formulation_interval"] == 1
        if arm.method.references is not None:
            assert ration["linear_max_references"] == arm.method.references
            assert ration["linear_midwest_reference_path"] == ration_cli.MIDWEST
            assert [ration[f"linear_{phase}_solver"] for phase in ("reference", "bound", "nutritional")] == [
                "highs"
            ] * 3


def test_custom_metadata_and_date_override(tmp_path):
    metadata = read("input/metadata/example_animals_only_metadata.json")
    animal = read(metadata["files"]["animal"]["path"])
    animal["ration"].update(user_input=False, formulation_interval=2)
    animal_path = tmp_path / "custom_animal.json"
    metadata_path = tmp_path / "custom_metadata.json"
    config_path = tmp_path / "custom_config.json"
    metadata["files"]["animal"]["path"] = str(animal_path)
    write(animal_path, animal)
    write(metadata_path, metadata)
    write(config_path, dict(start_date="2016:366", simulation_type="animals_only", nutrient_standard="NRC"))
    original = metadata_path.read_bytes()
    args = ration_cli.parse_args(
        False,
        [
            "--metadata",
            str(metadata_path),
            "--config",
            str(config_path),
            "--days",
            "2",
            "--no-midwest",
        ],
    )
    runs, dates = ration_cli.prepare(tmp_path / "batch", args)
    assert dates == ["2016-12-31", "2017-01-01"]
    output_meta = read(runs[0].metadata)["files"]
    assert read(output_meta["config"]["path"])["end_date"] == "2017:1"
    assert read(output_meta["feed"]["path"]) == read(metadata["files"]["feed"]["path"])
    ration = read(output_meta["animal"]["path"])["ration"]
    assert ration["formulation_interval"] == 2 and ration["linear_midwest_reference_path"] == ""
    assert metadata_path.read_bytes() == original


def test_simulation_failure_even_with_zero_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(ration_cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    args = ration_cli.parse_args(True, ["--methods", "slsqp"])
    runs, dates = ration_cli.prepare(tmp_path, args)
    with pytest.raises(RuntimeError, match="conclusão"):
        ration_cli.execute(runs[0], args, dates)
    status = read(runs[0].output / "run.json")
    assert status["exit_code"] == 0 and not status["completed"]
    log = runs[0].output / "logs/slsqp_logs_test.json"
    write(log, {ration_cli.FINISHED: {"values": ["Simulation completed"]}})
    with pytest.raises(RuntimeError, match="JSON final"):
        ration_cli.result_file(runs[0].output, 0)
    with pytest.raises(RuntimeError, match="código 2"):
        ration_cli.result_file(runs[0].output, 2)


def test_result_checks_calendar_seed_and_actual_backend():
    dates = ["2013-05-30"]
    method = ration_cli.Method("highs5", 5)
    attempt = dict(
        animal_group="lac_cow",
        backend="pulp",
        reference_solver="HiGHS",
        bound_solver="HiGHS",
        nutritional_solver="HiGHS",
    )
    result = dict(
        daily=[dict(date=dates[0], milk_kg=50, applied_dm_kg=60)],
        complete_calendar=True,
        seed=[42],
        pens=[{}],
        attempts=[attempt],
    )
    ration_cli.check_result(result, method, dates, 42)
    for update, message in [
        (dict(complete_calendar=False), "calendário"),
        (dict(seed=[43]), "semente"),
        (dict(attempts=[dict(attempt, backend="slsqp")]), "backend"),
        (dict(attempts=[dict(attempt, bound_solver="CBC")]), "HiGHS"),
    ]:
        with pytest.raises(RuntimeError, match=message):
            ration_cli.check_result(dict(result, **update), method, dates, 42)


def test_terminal_and_structured_summary(tmp_path, capsys, monkeypatch):
    def sample(method, cost, backend, validation, gap, solver_calls):
        return dict(
            run=method,
            daily=[
                dict(
                    date="2013-05-30", cumulative_applied_usd=cost, cumulative_milk_kg=100, cumulative_applied_dm_kg=80
                )
            ],
            pens=[dict(group="LAC_COW", animals=10, applied_usd=20)],
            composition=[
                dict(group="LAC_COW", ingredient_id="42", applied_kg_dm_pen=60, name="Silage", applied_usd=20)
            ],
            attempts=[
                dict(
                    animal_group="lac_cow",
                    backend=backend,
                    success=True,
                    attempt=1,
                    optimization_seconds=0.25,
                    solver_calls=solver_calls,
                    gap_percent=gap,
                    nutritional_validation=validation,
                    linear_nrc_approved=True if backend == "pulp" else None,
                )
            ],
            nutrition=[],
            purchases=[],
            reuse_log_count=None,
            **dict.fromkeys(
                (
                    "source",
                    "source_sha256",
                    "metadata",
                    "console",
                    "config",
                    "seed",
                    "ration_config",
                    "hashes",
                    "prices",
                    "issues",
                    "trace",
                    "animal",
                )
            ),
        )

    base = sample("slsqp", 25, "slsqp", "legacy_evaluator_failed", None, 1)
    linear = sample("highs5", 30, "pulp", "approved", 24, 20)
    summary = summarize([base, linear], {"slsqp": 10, "highs5": 20})
    assert summary["economics"][0]["lactation_usd_per_animal_day"] == 2
    assert summary["differences"][0]["applied_usd_delta_pct"] == 20
    assert summary["lactation_diet"][0]["kg_dm_per_animal_day"] == 6
    assert summary["lactation_validation"][0]["Rejeitadas"] == 1
    assert summary["lactation_validation"][1]["Aprovadas"] == 1
    assert summary["performance"][0]["gap_median_percent"] is None
    assert summary["performance"][1]["gap_median_percent"] == 24
    show(summary)
    printed = capsys.readouterr().out
    assert "Silage" in printed and "+20,00%" in printed and "avaliador legado" in printed

    def no_plots(*args):
        pytest.fail("CSV-only output must skip plotting")

    monkeypatch.setattr("helpful_scripts.nrc_ration_comparison.comparison_report_output.plots", no_plots)
    report = tmp_path / "report"
    generate([base], report, html=False)
    assert (report / "summary.csv").exists()
    assert not list(report.glob("*.html")) and not list(report.glob("*.png"))
