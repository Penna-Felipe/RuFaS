"""Extract daily feeding and optimization metrics from the CLI experiment."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from cli_three_day import BASE, METHODS, ROOT, read, write

PEN_DATA = {
    "ration": "report_ration_per_animal.ration_per_animal_for_{group}_PEN_{pen}",
    "feed": "report_daily_ration_per_pen.ration_daily_feed_totals_for_pen_{pen}_{group}",
    "supply": "report_nutrient_amounts.ration_nutrient_amount_for_{group}_PEN_{pen}",
    "requirements": "report_average_nutrient_requirements.avg_rqmts_for_{group}_PEN_{pen}",
    "legacy_evaluation": "report_average_nutrient_evaluation_results.avg_eval_report_for_{group}_PEN_{pen}",
}
GROUPS = ("CALF", "GROWING", "CLOSE_UP", "LAC_COW")


def indexed(series):
    return {
        info["simulation_day"]: {"value": value, "info": info}
        for value, info in zip(series["values"], series["info_maps"], strict=True)
    }


def series_for(data, suffix):
    return data.get(f"AnimalModuleReporter.{suffix}", {"values": [], "info_maps": []})


def ingredients(amounts):
    return {key: value for key, value in amounts.items() if key.isdecimal()}


def daily_metrics(data, prices):
    milk = indexed(series_for(data, "report_herd_statistics_data.daily_milk_production"))
    days = data.get("RufasTime.day", {}).get("values", [])
    results = []
    for pen, group in enumerate(GROUPS):
        sources = {
            label: indexed(series_for(data, suffix.format(group=group, pen=pen))) for label, suffix in PEN_DATA.items()
        }
        for day, ration in sources["ration"].items():
            feed_per_animal = ingredients(ration["value"])
            feed_for_pen = ingredients(sources["feed"].get(day, {}).get("value", {}))
            row = {
                "simulation_day": day,
                "julian_day": days[day] if day < len(days) else None,
                "pen_id": pen,
                "group": group,
                "animals_at_formulation": ration["info"]["number_animals_in_pen"],
                "kg_dm_per_animal_by_feed": feed_per_animal,
                "kg_dm_pen_by_feed": feed_for_pen,
                "kg_dm_per_animal": ration["value"]["dry_matter_intake_total"],
                "kg_dm_pen": sum(feed_for_pen.values()) if feed_for_pen else None,
                "formulated_usd_per_animal_day": sum(prices[key] * kg for key, kg in feed_per_animal.items()),
                "applied_feed_at_input_prices_usd": (
                    sum(prices[key] * kg for key, kg in feed_for_pen.items()) if feed_for_pen else None
                ),
                "daily_milk_kg": milk.get(day, {}).get("value") if group == "LAC_COW" else None,
            }
            for label in ("supply", "requirements", "legacy_evaluation"):
                item = sources[label].get(day)
                row[label] = item["value"] if item else None
                if label != "legacy_evaluation":
                    row[f"{label}_units"] = item["info"]["units"] if item else None
            results.append(row)
    return sorted(results, key=lambda row: (row["simulation_day"], row["pen_id"]))


def trace_summary(trace_rows, daily):
    result = []
    previous = None
    candidate_statuses = Counter()
    for trace in trace_rows:
        row = {key: value for key, value in trace.items() if key != "references"}
        ration = row["applied_quantities"]
        if ration is not None:
            row["exact_match_to_reported_ration"] = next(
                (
                    ration == daily_row["kg_dm_per_animal_by_feed"]
                    for daily_row in daily
                    if daily_row["simulation_day"] == row["simulation_day"] and daily_row["pen_id"] == row["pen_id"]
                ),
                None,
            )
        row["matches_last_applied_as_previous"] = (
            row["previous_ration"] == previous if previous is not None else row["previous_ration"] == {}
        )
        if ration is not None:
            previous = ration
        if trace.get("backend") == "pulp":
            statuses = Counter()
            for reference in trace["references"]:
                for case in reference["cases"]:
                    statuses[case["validation_status"] or case["lp_status"]] += 1
            row["case_counts"] = dict(statuses)
            row["references"] = [
                (reference["source"], len(reference["cases"]), reference["message"])
                for reference in trace["references"]
            ]
            candidate_statuses.update(statuses)
        result.append(row)
    return {"attempts": result, "case_counts": dict(candidate_statuses)}


def collect(base, diagnostics):
    source = read(base / "inputs/feed.json")
    prices = {str(item["feed_type"]): item["purchased_feed_cost"] for item in source["feeds"]}
    report = {}
    for method in METHODS:
        run = base / "runs" / method
        trace_run = diagnostics / "runs" / method
        original_output = sorted((ROOT / run / "JSONs").glob("*.json"))
        partial = ROOT / trace_run / "partial_variables.json"
        output = original_output[0] if original_output else partial if partial.is_file() else None
        data = read(output) if output else {}
        daily = daily_metrics(data, prices)
        attempts = [
            row for key, element in data.items() if "ration_optimizer_attempt_pen_" in key for row in element["values"]
        ]
        trace_path = ROOT / trace_run / "attempts.jsonl"
        trace_rows = (
            [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
            if (trace_path.is_file())
            else []
        )
        log_path = ROOT / run / "console.log"
        console = log_path.read_text(encoding="utf-8", errors="replace")
        report[method] = {
            "execution": read(run / "run.json"),
            "completed_julian_days": data.get("RufasTime.day", {}).get("values", []),
            "daily": daily,
            "attempts": attempts,
            "calf_direct_path_log_count": console.count("No optimizer used: calves take the direct ration path."),
            "previous_ration_reused_after_failure": "Previous ration used because automated ration" in console,
            "error_titles": sorted(set(re.findall(r"\[ERROR\]\[.*?\] ([^.\r\n]+)", console))),
            "diagnostic_trace": trace_summary(trace_rows, daily),
        }
    write(base / "summary.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--diagnostics", type=Path, default=Path("output/nrc_cli_three_day_diagnostic"))
    args = parser.parse_args()
    collect(args.base, args.diagnostics)
