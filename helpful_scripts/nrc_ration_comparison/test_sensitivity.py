"""Checks for the isolated fixed-coefficient NRC sensitivity experiment."""

from typing import Any

import pytest

pulp = pytest.importorskip("pulp")

from helpful_scripts.nrc_ration_comparison.sensitivity import (  # noqa: E402
    compare_references,
    error_metrics,
    protein_offers,
)
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import NRCProteinCoefficients  # noqa: E402


def test_error_metrics_use_nrc_denominator_and_preserve_units() -> None:
    assert error_metrics(9.0, 10.0, "Mcal/cow/day") == {
        "unit": "Mcal/cow/day",
        "predicted": 9.0,
        "nrc": 10.0,
        "signed_error": -1.0,
        "absolute_error": 1.0,
        "relative_error_percent": 10.0,
    }
    assert error_metrics(2.0, 0.0, "g/cow/day")["relative_error_percent"] is None
    assert error_metrics(-3.0, -2.0, "g/cow/day")["relative_error_percent"] == 50.0


@pytest.mark.parametrize(("tdn", "rdp"), [(50.0, 80.0), (80.0, 50.0), (50.0, 50.0)])
def test_protein_components_take_minimum_after_summing(tdn: float, rdp: float) -> None:
    coefficients = {
        8: NRCProteinCoefficients(tdn, rdp, 9.0),
        3: NRCProteinCoefficients(5.0, 7.0, 6.0),
    }
    offers = protein_offers({3: 1.0, 8: 2.0}, coefficients)
    assert offers["microbial_tdn"] == 2 * tdn + 5.0
    assert offers["microbial_rdp"] == 2 * rdp + 7.0
    assert offers["digestible_rup"] == 24.0
    assert offers["endogenous"] == pytest.approx(14.16)
    microbial = 0.64 * min(2 * tdn + 5.0, 2 * rdp + 7.0)
    assert offers["microbial_metabolizable"] == pytest.approx(microbial)
    assert offers["metabolizable_protein"] == pytest.approx(24.0 + 14.16 + microbial)


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return compare_references(1)


def test_references_reproduce_original_nrc_offers(report: dict[str, Any]) -> None:
    references = report["references"]
    assert set(references) == {"midwest_original", "forage_weighted", "slsqp_diagnostic"}
    original = references["midwest_original"]["reference"]
    alternative = references["forage_weighted"]["reference"]
    assert original["quantities"] != alternative["quantities"]
    assert original["dry_matter_kg_per_cow_day"] == pytest.approx(alternative["dry_matter_kg_per_cow_day"])
    assert alternative["dry_matter_kg_per_cow_day"] == pytest.approx(report["scenario"]["requirements"]["dry_matter"])
    diagnostic = references["slsqp_diagnostic"]
    assert diagnostic["reference"]["quantities"] == report["slsqp"]["quantities"]
    for reference in references.values():
        errors = reference["reference"]["offers"]
        assert len(errors) == 9
        assert max(error["absolute_error"] for error in errors.values()) < 1e-9
        for feed_id, amount in reference["reference"]["quantities"].items():
            feed = report["scenario"]["feeds"][feed_id]
            assert feed["lower"] <= amount <= feed["upper"]
        assert set(reference["coefficients"]["protein_g_per_kg_dm"]) == set(report["scenario"]["feeds"])


def test_cases_keep_shared_prices_and_nrc_validation(report: dict[str, Any]) -> None:
    prices = {feed_id: feed["price"] for feed_id, feed in report["scenario"]["feeds"].items()}
    for reference in report["references"].values():
        cases = reference["cases"]
        assert len(cases) == 6
        counts = reference["counts"]
        assert counts["optimal"] + counts["infeasible"] + counts["solver_error"] == 6
        assert counts["approved"] + counts["rejected"] == counts["optimal"]
        for case in cases:
            if case["validation"] is None:
                continue
            for key in ("raw_diet", "rounded_diet", "repaired_diet"):
                if key not in case:
                    continue
                diet = case[key]
                assert set(diet["quantities"]) == set(prices)
                assert diet["cost_usd_per_cow_day"] == pytest.approx(
                    sum(amount * prices[feed_id] for feed_id, amount in diet["quantities"].items())
                )
                assert diet["offers"]["endogenous"]["absolute_error"] == 0.0
                assert diet["offers"]["energy_maintenance"]["unit"] == "Mcal/cow/day"
                assert diet["offers"]["metabolizable_protein"]["unit"] == "g/cow/day"
        selected = reference["selected_case"]
        if selected is not None:
            case = next(case for case in cases if case["case"] == selected)
            diet = case.get("repaired_diet", case["rounded_diet"])
            check = (
                case["validation"]["repair"]["validation"] if "repaired_diet" in case else case["validation"]["rounded"]
            )
            assert len(check["residuals"]) == 14 and check["violations"] == {}
            assert reference["selected_cost"] == pytest.approx(diet["cost_usd_per_cow_day"])
