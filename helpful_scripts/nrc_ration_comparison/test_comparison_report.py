"""Regression coverage for the standalone comparison report."""

import base64
import csv
import json
import re

import pytest

from helpful_scripts.nrc_ration_comparison.comparison_report import (
    attempt_rows,
    compare_runs,
    date_index,
    extract_run,
    integrity,
    nrc_balance,
)
from helpful_scripts.nrc_ration_comparison.comparison_report_output import generate
from helpful_scripts.nrc_ration_comparison.comparison_report_summary import validation_rows


def series(rows, **extra):
    return {"values": list(rows.values()), "info_maps": [dict(simulation_day=day, **extra) for day in rows]}


def test_dates_use_metadata_across_calendar_years_and_drop_duplicates():
    data = {"RufasTime.day": series({4: 1, 3: 366}), "RufasTime.calendar_year": series({3: 2024, 4: 2025})}
    issues = []
    assert date_index(data, issues) == {3: "2024-12-31", 4: "2025-01-01"}
    assert issues == []
    data["RufasTime.day"]["values"].append(365)
    data["RufasTime.day"]["info_maps"].append({"simulation_day": 3})
    assert date_index(data, issues) == {4: "2025-01-01"}
    assert any("duplicados" in issue for issue in issues)


def test_compare_aligns_by_civil_date_and_excludes_unpaired_cumulative_deltas():
    base = {
        "run": "base",
        "daily": [
            {"date": "2013-01-02", "simulation_day": 0, "applied_usd": 10, "milk_kg": 0, "cumulative_applied_usd": 10},
            {"date": "2013-01-03", "simulation_day": 1, "applied_usd": 20, "cumulative_applied_usd": 30},
        ],
    }
    other = {
        "run": "other",
        "daily": [
            {"date": "2013-01-02", "simulation_day": 8, "applied_usd": 12, "milk_kg": 3, "cumulative_applied_usd": 12},
        ],
    }
    aligned, absent = compare_runs(base, other, "daily")
    assert aligned["applied_usd_delta"] == 2
    assert aligned["applied_usd_delta_pct"] == 20
    assert aligned["milk_kg_delta_pct"] is None
    assert aligned["cumulative_applied_usd_delta"] is None
    assert not absent["comparison_present"]


def test_attempt_instrumentation_and_duplicates():
    base = dict(
        simulation_day=0, pen_id=7, attempt=1, backend="pulp", gap_achieved=0.125, nutritional_validation="approved"
    )
    records = [base, dict(base), dict(base, attempt=2, backend="slsqp", gap_achieved=None)]
    issues = []
    rows = attempt_rows(
        {"Pen.capture_result.ration_optimizer_attempt_pen_7": {"values": records}}, {0: "2013-01-01"}, "test", issues
    )
    assert [row["attempt"] for row in rows] == [2]
    assert rows[0]["linear_nrc_approved"] is None
    assert issues


def test_nrc_limits_are_separate_from_targets_and_legacy_zero():
    req = {
        "DMIest_requirement": 25.874660753542745,
        "Ca_requirement": 70,
        "P_req": 60,
        "P_req_process": 65,
        "MP_requirement": 2800,
    }
    supply = {"dm": 33.637059, "calcium": 0.081, "phosphorus": 0.069, "metabolizable_protein": 2900, "NDF": 15}
    args = (req, supply, {"metabolizable_protein_difference": 0}, "LAC_COW")
    rows = {
        r["constraint"]: r
        for r in nrc_balance(*args, {"attempt": 1, "success": True}, {"nutrient_standard": "NRC"}, {})
    }
    assert len(rows) == 14
    assert rows["DMI_constraint_upper"]["effective_limit"] == pytest.approx(33.63705897960557)
    assert rows["DMI_constraint_upper"]["margin"] < 0
    assert rows["DMI_constraint_upper"]["audit_status"] == "atende"
    assert rows["calcium_constraint"]["offer"] == 81
    assert rows["phosphorus_constraint"]["nutritional_target"] == 65
    assert rows["protein_constraint_lower"]["reporter_evaluation"] == 0
    assert rows["protein_constraint_lower"]["offer_minus_target"] == 100
    retry = nrc_balance(*args, {"attempt": 2, "success": True}, {"nutrient_standard": "NRC"}, {})
    assert all(row["margin"] is None for row in retry)


def test_extraction_aggregation_and_report(tmp_path):
    def write(filename, value):
        path = tmp_path / filename
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    catalog = tmp_path / "catalog.csv"
    catalog.write_text("rufas_id,Name,feed_description,DM,units\n42,Example,Forage,25,kg\n", encoding="utf-8")
    paths = {
        "config": write("config.json", {"start_date": "2013:001", "end_date": "2013:002", "nutrient_standard": "NRC"}),
        "animal": write("animal.json", {"ration": {"optimizer_backend": "slsqp"}}),
        "feed": write("feed.json", {"feeds": [{"feed_type": 42, "purchased_feed_cost": 1.5}]}),
        "user_feeds": catalog,
        "NRC_Comp": catalog,
    }
    metadata = write("metadata.json", {"files": {key: {"path": str(path)} for key, path in paths.items()}})
    ration = {"42": 2, "dry_matter_intake_total": 2}
    totals = {"42": 6, "dry_matter_intake_total": 6}
    prefix = "AnimalModuleReporter."
    data = {
        "RufasTime.day": series({0: 1, 1: 2}),
        "RufasTime.calendar_year": series({0: 2013, 1: 2013}),
        "TaskManager.set_random_seed.random_seed": {"values": [42]},
        prefix
        + "report_ration_per_animal.ration_per_animal_for_LAC_COW_PEN_9": series(
            {0: ration, 1: ration}, number_animals_in_pen=2
        ),
        prefix
        + "report_daily_ration_per_pen.ration_daily_feed_totals_for_pen_9_LAC_COW": series({0: totals, 1: totals}),
        prefix + "report_daily_pen_total.number_of_animals_in_pen_9_LAC_COW": series({0: 3, 1: 3}),
        prefix + "report_herd_statistics_data.daily_milk_production": series({0: 10, 1: 12}),
        prefix
        + "report_milk.milk_data_at_milk_update": {
            "values": [
                {"simulation_day": i, "pen_id": 9, "cow_id": 1, "estimated_daily_milk_produced": kg}
                for i, kg in enumerate((10, 12))
            ]
        },
        "FeedManager.purchase_feed.daily_feed_request_42_cost": series({0: 15}, units="$"),
    }
    data[prefix + "report_nutrient_amounts.ration_nutrient_amount_for_LAC_COW_PEN_9"] = series(
        {0: {"dm": 2}, 1: {"dm": 3}}, units={"dm": "kg/animal"}
    )
    source = write("source.json", data)
    run = extract_run("base", source, metadata)
    assert run["daily"][1]["cumulative_applied_usd"] == 18
    assert run["daily"][1]["cumulative_milk_kg"] == 22
    assert run["pens"][0]["applied_usd_per_animal"] == 3
    assert run["pens"][0]["animals_at_formulation"] == 2
    assert run["pens"][0]["applied_composition_consistent"]
    assert run["composition"][0]["name"] == "Example Forage"
    assert run["composition"][0]["applied_kg_as_fed_pen"] == 24
    assert run["daily"][0]["purchase_usd"] == 15
    assert run["daily"][1]["purchase_usd"] is None
    assert run["daily"][0]["usd_per_kg_milk"] == 0.9
    other = extract_run("<other>", source, metadata)
    assert integrity(run, other)["seed"] == "compatível"
    output = tmp_path / "report"
    generate([run, other], output)
    page = (output / "index.html").read_text(encoding="utf-8")
    detailed = (output / "detailed_report.html").read_text(encoding="utf-8")
    assert "&lt;other&gt;" in page and "&lt;other&gt;" in detailed
    assert 'href="detailed_report.html"' in page
    assert 'href="index.html"' in detailed
    assert page.count("<section ") == 5
    assert set(re.findall(r'href="([^"]+\.csv)"', page)) == {item.name for item in output.glob("*.csv")}
    assert set(re.findall(r'href="([^"]+\.png)"', page)) == {item.name for item in output.glob("*.png")}
    pattern = r"data:image/png;base64,([A-Za-z0-9+/=]+)"
    images = {base64.b64decode(encoded) for encoded in re.findall(pattern, page)}
    detailed_images = {base64.b64decode(encoded) for encoded in re.findall(pattern, detailed)}
    assert len(images) == 5
    assert detailed_images == {item.read_bytes() for item in output.glob("*.png")}
    assert len(detailed_images) == 12
    assert images < detailed_images
    assert "18,00" in page and "22,00" in page
    assert "<td>18</td>" in detailed and "<td>22</td>" in detailed
    payload = json.loads(re.search(r'id="diet-data">(.*?)</script>', page).group(1))
    assert payload["runs"] == ["base", "<other>"]
    assert payload["pens"][0]["label"] == "Lote 9 · Vacas em lactação"
    first, second = payload["pens"][0]["days"]
    assert first["date"] == "2013-01-01" and second["date"] == "2013-01-02"
    assert first["ingredients"][0]["label"] == "42 · Example Forage"
    with (output / "composition.csv").open(encoding="utf-8-sig", newline="") as stream:
        recipe = next(csv.DictReader(stream))
    assert first["ingredients"][0]["values"]["0"] == [
        float(recipe["applied_kg_dm_per_animal"]),
        float(recipe["applied_usd"]) / 3,
    ]
    with (output / "nutrition.csv").open(encoding="utf-8-sig", newline="") as stream:
        nrc = next(row for row in csv.DictReader(stream) if row["constraint"] == "DMI_constraint_lower")
    levels = next(row for row in first["nutrition"] if "Matéria seca · mínimo" in row["label"])
    assert levels["values"]["0"][1] == float(nrc["offer"])
    assert next(row for row in second["nutrition"] if row["label"] == levels["label"])["values"]["0"][1] == 3
    with (output / "daily_herd.csv").open(encoding="utf-8-sig", newline="") as stream:
        assert len(list(csv.DictReader(stream))) == 4
    with pytest.raises(FileExistsError):
        generate([run, other], output)


def test_validation_counts_keep_solver_success_separate():
    def attempt(backend, status, success):
        return dict(animal_group="lac_cow", backend=backend, nutritional_validation=status, success=success)

    rows = validation_rows(
        [
            dict(run="slsqp", attempts=[attempt("slsqp", "legacy_evaluator_failed", True)]),
            dict(
                run="highs3",
                attempts=[
                    attempt("pulp", "approved", True),
                    attempt("pulp", "rejected", False),
                    attempt("pulp", "no_candidate", False),
                ],
            ),
        ]
    )
    assert [row["Aprovadas"] for row in rows] == [0, 1]
    assert [row["Rejeitadas"] for row in rows] == [1, 1]
    assert [row["Sucessos registrados"] for row in rows] == [1, 1]
    assert [row["Falhas registradas"] for row in rows] == [0, 2]
    assert [row["Sem resultado nesse critério"] for row in rows] == [0, 1]
