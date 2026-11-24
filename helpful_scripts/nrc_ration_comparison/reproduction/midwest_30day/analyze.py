import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import median, quantiles

sys.path.insert(0, str(Path.cwd() / "helpful_scripts/nrc_ration_comparison"))
from cli_three_day_summary import daily_metrics
from cli_three_day import read, write

root = Path("output/nrc_midwest_30day")
names = ("slsqp", "highs_midwest_3", "highs_midwest_5")
feed = read(root / "inputs/feed.json")
prices = {str(item["feed_type"]): item["purchased_feed_cost"] for item in feed["feeds"]}


def json_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []


def csv_write(path, rows):
    if not rows:
        return
    columns = list(dict.fromkeys(field for row in rows for field in row))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, columns)
        writer.writeheader()
        writer.writerows(rows)


def diagnostic_causes(trace):
    classes = Counter()
    reasons = Counter()
    for ref in trace.get("references", []):
        for case in ref["cases"]:
            classes[case["validation_status"] or case["lp_status"]] += 1
            val = case["validation"]
            if not val or case["validation_status"] == "approved":
                continue
            for stage in ("unrounded", "rounded"):
                if val.get(stage):
                    reasons.update(f"{stage}:{key}" for key in val[stage]["violations"])
    return dict(classes), dict(reasons)


def summarize():
    summaries = {}
    all_daily, all_attempts, all_groups, tables = [], [], [], []
    for name in names:
        run = root / "runs" / name / "1"
        stamp = read(run / "run.json")
        outputs = list((run / "JSONs").glob("*.json"))
        source = outputs[0] if outputs else run / "partial_variables.json"
        data = read(source) if source.is_file() else {}
        markers = data.get("RufasTime.day", {}).get("values", [])
        compatible = daily_metrics(data, prices)
        days = []
        for day in sorted(set(markers)):
            daily = [row for row in compatible if row["julian_day"] == day]
            if (len(daily) == 4 and all(row["applied_feed_at_input_prices_usd"] is not None for row in daily)
                and any(row["group"] == "LAC_COW" and row["daily_milk_kg"] is not None for row in daily)):
                days.append(day)
        assert days == list(range(150, 150 + len(days))), (name, days)
        completed = stamp["completed"] and stamp["exit_code"] == 0 and days == list(range(150, 180))
        if stamp["completed"]:
            assert completed, (name, days, stamp)

        attempts = [row for key, value in data.items() if "ration_optimizer_attempt_pen_" in key for row in value["values"]]
        attempts.sort(key=lambda x: (x["simulation_day"], x["pen_id"], x["attempt"]))
        raw = json_lines(run / "attempts.jsonl")
        phases = json_lines(run / "phases.jsonl")
        assert len(raw) == len(phases), name
        lactation_index = {(row["simulation_day"], row["pen_id"], row["attempt"]): (row, phase)
                           for row, phase in zip(raw, phases, strict=True)}
        all_lac = [row for row in attempts if row["animal_group"] == "lac_cow"]
        assert len(all_lac) == len(raw), (name, len(all_lac), len(raw))
        for row in attempts:
            key = row["simulation_day"], row["pen_id"], row["attempt"]
            trace, phase = lactation_index.get(key, ({}, {}))
            classes, reasons = diagnostic_causes(trace)
            if row["success"] and row["backend"] == "pulp":
                assert trace["selected_quantities"] == trace["applied_quantities"]
                ref = next(r for r in trace["references"] if r["source"] == trace["selected_reference"])
                case = next(c for c in ref["cases"] if c["regime"] == trace["selected_case"])
                validation = case["validation"]
                approved = (validation["repair"] or {}).get("quantities") or validation["rounded_quantities"]
                assert case["validation_status"] == "approved"
                assert approved == trace["applied_quantities"]
                if row["simulation_day"] + 150 in days:
                    reported = next(d for d in compatible if d["simulation_day"] == row["simulation_day"]
                                    and d["pen_id"] == row["pen_id"])
                    assert approved == reported["kg_dm_per_animal_by_feed"]
            all_attempts.append({
                "scenario": name, "day": row["simulation_day"] + 150, "pen_id": row["pen_id"],
                "group": row["animal_group"], "attempt": row["attempt"], "success": row["success"],
                "backend": row["backend"], "nrc_validation": row["nutritional_validation"],
                "reference_winner": row["reference"], "cost_usd_per_animal": row["cost_usd_per_animal_day"],
                "bound_usd_per_animal": row["lower_bound_usd_per_animal_day"], "gap_fraction": row["gap_achieved"],
                "references_explored": row["references_evaluated"], "solver_calls": row["solver_calls"],
                "optimization_s": row["optimization_seconds"], "generation_s": phase.get("generation_seconds"),
                "bound_s": phase.get("bound_seconds"), "nutritional_lps_s": phase.get("nutritional_lp_seconds"),
                "validation_and_repair_s": phase.get("validation_and_repair_seconds"),
                "stop_reason": row["stop_reason"], "message": row["message"],
                "case_counts": json.dumps(classes), "nrc_failure_reasons": json.dumps(reasons),
                "regional_reference": json.dumps(row.get("regional_reference")),
                "reference_attempts": json.dumps(row.get("reference_attempts")),
            })
        console = (run / "console.log").read_text(encoding="utf-8", errors="replace")
        error_titles = sorted(set(re.findall(r"\[ERROR\]\[.*?\] ([^.\r\n]+)", console)))
        error_lines = [line for line in console.splitlines() if "[ERROR]" in line or "Traceback" in line]
        observed = [row for row in compatible if row["julian_day"] in days]
        cumulative = Counter()
        for day in days:
            group_rows = [r for r in observed if r["julian_day"] == day]
            lac = next(r for r in group_rows if r["group"] == "LAC_COW")
            day_attempts = [a for a in attempts if a["simulation_day"] + 150 == day]
            day_lac = [a for a in day_attempts if a["animal_group"] == "lac_cow"]
            success = next((a for a in reversed(day_lac) if a["success"]), {})
            cost = sum(r["applied_feed_at_input_prices_usd"] for r in group_rows)
            applied = sum(r["kg_dm_pen"] for r in group_rows)
            milk = lac["daily_milk_kg"]
            for k, v in {"cost": cost, "applied": applied, "milk": milk, "lac_cost": lac["applied_feed_at_input_prices_usd"],
                         "optimization": sum(a["optimization_seconds"] for a in day_attempts),
                         "approved": sum(a["success"] for a in day_lac), "attempts": len(day_lac)}.items():
                cumulative[k] += v
            for row in group_rows:
                all_groups.append({"scenario": name, "day": day, "group": row["group"],
                                   "applied_feed_cost_usd": row["applied_feed_at_input_prices_usd"],
                                   "applied_dry_matter_kg": row["kg_dm_pen"], "milk_kg": row["daily_milk_kg"],
                                   "diet_per_cow_by_feed_json": json.dumps(row["kg_dm_per_animal_by_feed"])})
            all_daily.append({
                "scenario": name, "day": day,
                "feed_cost_usd": cost, "cumulative_feed_cost_usd": cumulative["cost"],
                "lactation_feed_cost_usd": lac["applied_feed_at_input_prices_usd"],
                "cumulative_lactation_feed_cost_usd": cumulative["lac_cost"],
                "milk_kg": milk, "cumulative_milk_kg": cumulative["milk"],
                "applied_dm_kg": applied, "cumulative_applied_dm_kg": cumulative["applied"],
                "applied_lactation_dm_kg": lac["kg_dm_pen"],
                "feed_cost_usd_per_kg_milk": cost / milk if milk else None,
                "lactation_feed_cost_usd_per_kg_milk": lac["applied_feed_at_input_prices_usd"] / milk if milk else None,
                "optimization_s": sum(a["optimization_seconds"] for a in day_attempts),
                "optimization_lactation_s": sum(a["optimization_seconds"] for a in day_lac),
                "cumulative_optimization_s": cumulative["optimization"],
                "gap_fraction": success.get("gap_achieved"), "winner": success.get("reference"),
                "solver_calls_all": sum(a["solver_calls"] for a in day_attempts),
                "solver_calls_lactation": sum(a["solver_calls"] for a in day_lac),
                "approved_lactation": sum(a["success"] for a in day_lac),
                "rejected_lactation": sum(not a["success"] for a in day_lac),
                "lactation_attempt_success_fraction": (
                    sum(a["success"] for a in day_lac) / len(day_lac) if day_lac else None
                ),
                "cumulative_lactation_attempt_success_fraction": (
                    cumulative["approved"] / cumulative["attempts"] if cumulative["attempts"] else None
                ),
            })
        winners = Counter(a["reference"] for a in all_lac if a["success"] and a["reference"])
        gaps = [a["gap_achieved"] for a in all_lac if a["success"] and a["gap_achieved"] is not None]
        regional_explored = sum((a.get("regional_reference") or {}).get("explored", False) for a in all_lac)
        case_counts = Counter()
        rejection_causes = Counter()
        for r in raw:
            counts, causes = diagnostic_causes(r)
            case_counts.update(counts)
            if not r["success"]:
                rejection_causes.update(causes)
        record = {
            "scenario": name, "completed": completed, "completed_days": len(days), "first_day": days[0] if days else None,
            "last_day": days[-1] if days else None, "feed_cost_usd": cumulative["cost"],
            "lactation_feed_cost_usd": cumulative["lac_cost"], "milk_kg": cumulative["milk"],
            "applied_dm_kg": cumulative["applied"],
            "applied_lactation_dm_kg": sum(r["kg_dm_pen"] for r in observed if r["group"] == "LAC_COW"),
            "feed_cost_usd_per_kg_milk": cumulative["cost"]/cumulative["milk"] if cumulative["milk"] else None,
            "lactation_feed_cost_usd_per_kg_milk": cumulative["lac_cost"]/cumulative["milk"] if cumulative["milk"] else None,
            "wall_s": stamp["wall_seconds"], "optimization_s": sum(a["optimization_seconds"] for a in attempts),
            "optimization_lactation_s": sum(a["optimization_seconds"] for a in all_lac),
            "approved_all": sum(a["success"] for a in attempts), "rejected_all": sum(not a["success"] for a in attempts),
            "approved_lactation": sum(a["success"] for a in all_lac), "rejected_lactation": sum(not a["success"] for a in all_lac),
            "midwest_explored": regional_explored, "midwest_wins": winners["midwest"],
            "midwest_win_fraction": (winners["midwest"] / sum(a["success"] for a in all_lac)
                                     if name != "slsqp" and any(a["success"] for a in all_lac) else None),
            "gap_min": min(gaps) if gaps else None, "gap_median": median(gaps) if gaps else None,
            "gap_max": max(gaps) if gaps else None, "gap_q1": quantiles(gaps, method="inclusive")[0] if len(gaps)>1 else None,
            "gap_q3": quantiles(gaps, method="inclusive")[2] if len(gaps)>1 else None,
            "gap_at_or_below_5pct": sum(v <= .05 for v in gaps) if gaps else None,
            "solver_calls": sum(a["solver_calls"] for a in attempts),
            "solver_calls_lactation": sum(a["solver_calls"] for a in all_lac),
        }
        for phase in ("generation_seconds", "bound_seconds", "nutritional_lp_seconds", "validation_and_repair_seconds"):
            record[phase] = sum(p.get(phase,0) for p in phases) if name != "slsqp" else None
        summaries[name] = {**record, "winners": dict(winners), "nrc_lp_case_counts": dict(case_counts),
                           "formulation_rejection_causes": dict(rejection_causes), "error_titles": error_titles,
                           "error_lines": error_lines, "completed_julian_days": days,
                           "slsqp_diagnostic_nrc_pass": sum(not t["applied_nrc_check"]["unrounded"]["violations"]
                                                           for t in raw if t.get("applied_nrc_check")) if name=="slsqp" else None}
        tables.append(record)
    write(root/"summary.json", summaries)
    csv_write(root/"summary.csv", tables)
    csv_write(root/"daily_metrics.csv", all_daily)
    csv_write(root/"daily_by_group.csv", all_groups)
    csv_write(root/"attempts.csv", all_attempts)
    common_last = min(d["last_day"] or 149 for d in summaries.values())
    print("common last", common_last)
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    summarize()
