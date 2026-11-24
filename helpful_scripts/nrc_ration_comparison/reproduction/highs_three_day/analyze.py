import json,sys
from collections import Counter,defaultdict
from pathlib import Path
from statistics import median
sys.path.insert(0,str(Path.cwd()))
sys.path.insert(0,str(Path("helpful_scripts/nrc_ration_comparison").resolve()))
from cli_three_day_summary import daily_metrics,trace_summary
from cli_three_day import read,write
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import _NRC_TOLERANCES

root=Path("output/nrc_cli_three_day_highs")
base=Path("output/nrc_cli_three_day")
prior=read(base/"summary.json")
archived=read(Path("output/nrc_solver_benchmark/results.json"))["problems"]
feed=read(root/"inputs/feed.json")
prices={str(it["feed_type"]):it["purchased_feed_cost"] for it in feed["feeds"]}
diag=Path("output/nrc_cli_three_day_diagnostic/runs")
nrc_to_linear={
    "NE_total_constraint":"minimum_total_energy",
    "NE_maintenance_and_activity_constraint":"minimum_energy_maintenance",
    "NE_growth_constraint":"minimum_energy_growth",
    "NE_lactation_constraint":"minimum_energy_lactation",
    "protein_constraint_lower":"minimum_metabolizable_protein",
    "protein_constraint_upper":"maximum_metabolizable_protein",
}

def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

def counts(rows):
    result=Counter()
    for row in rows:
        result["attempts"]+=1
        result["accepted_attempts"]+=int(row["success"])
        if row.get("backend")=="slsqp":
            check=row.get("applied_nrc_check")
            if check:
                result["applied_slsqp_nrc_failures"]+=bool(check["unrounded"]["violations"])
            continue
        for ref in row["references"]:
            for case in ref["cases"]:
                result[case["validation_status"] or case["lp_status"]]+=1
                v=case["validation"]
                if not v: continue
                if v["unrounded"]["violations"]:
                    result["raw_rejected"]+=1
                elif v["rounded"]["violations"]:
                    result["rounding_rejected"]+=1
                repair=v.get("repair")
                if repair:
                    result["repair_searches"]+=1
                    result["repair_trials"]+=repair["attempts"]
                    result["repaired"]+=repair["quantities"] is not None
                labels=set(case.get("raw_causes",{}).values())
                result["raw_with_numerical"]+=int(any("numerical" in label for label in labels))
                result["raw_with_approximation"]+=int(any("approximation" in label for label in labels))
    return dict(result)

def metrics(daily,days):
    group=defaultdict(lambda: {"cost_usd":0,"dm_kg":0,"milk_kg":0,"daily":[]})
    for row in daily:
        if row["julian_day"] not in days: continue
        g=group[row["group"]]
        g["cost_usd"]+=row["applied_feed_at_input_prices_usd"] or 0
        g["dm_kg"]+=row["kg_dm_pen"] or 0
        g["milk_kg"]+=row["daily_milk_kg"] or 0
        g["daily"].append(row)
    return dict(group)

def hydrate_baseline(name,row):
    if name=="slsqp": return
    p=archived[f"cli/{name}/{150+row['simulation_day']}/{row['attempt']}"]
    for ref in row["references"]:
        if not ref["cases"]: continue
        for case,record in zip(ref["cases"],p["core"][ref["source"]]["cases"],strict=True):
            old=record["results"]["cbc"]
            assert case["regime"]==record["regime"]
            assert case["lp_quantities"]==old.get("quantities_kg_dm")
            case["raw_causes"]=old.get("raw_failure_causes",{})

report={}
controlled=[]
for name,val in prior.items():
    rows=lines(diag/name/"attempts.jsonl")
    for row in rows: hydrate_baseline(name,row)
    report["slsqp" if name=="slsqp" else f"cbc_{name}"]={
        **val,"raw_attempts":rows,
        "counts":counts(rows),"group_totals":metrics(val["daily"],val["completed_julian_days"]),
    }

for name in ("single","full","adaptive_gap"):
    run=root/"runs"/name
    execution=read(run/"run.json")
    outputs=list((run/"JSONs").glob("*.json"))
    data=read(outputs[0] if outputs else run/"partial_variables.json")
    days=data["RufasTime.day"]["values"]
    daily=daily_metrics(data,prices)
    rows=lines(run/"attempts.jsonl")
    phases=lines(run/"phase_details.jsonl")
    old=report[f"cbc_{name}"]["raw_attempts"]
    for row,phase in zip(rows,phases,strict=True):
        assert phase["solver"]=="HiGHS"
        row.update({k:v for k,v in phase.items() if k!="cases"})
        nutrition=[case for case in phase["cases"] if case["solver"]=="HiGHS"]
        reference_calls=[case for case in phase["cases"] if case["solver"]=="PULP_CBC_CMD"]
        assert len(reference_calls)==sum(ref["generation_calls"] for ref in row["references"])
        row["phases"]={
            "cbc_bound_seconds":phase["bound_seconds"],
            "cbc_reference_seconds":sum(x["generation_seconds"] for x in row["references"]),
            "nutritional_lp_seconds":sum(x["seconds"] for x in nutrition),
            "nutritional_build_solve_validate_seconds":sum(x["solve_and_validate_seconds"] for x in row["references"]),
            "trace_diagnostics_inside_optimization_seconds":phase["diagnostics_seconds"],
        }
        case_pairs=list(zip((c for ref in row["references"] for c in ref["cases"]),nutrition,strict=True))
        assert all(details["solver"]=="HiGHS" for _,details in case_pairs)
        assert row["solver_calls"]==1+sum(ref["generation_calls"] for ref in row["references"])+len(case_pairs)
        for case,details in case_pairs:
            case.update(details)
            validation=case["validation"]
            if validation is None: continue
            labels={}
            for key in validation["unrounded"]["violations"]:
                row_key=nrc_to_linear.get(key)
                if row_key is None:
                    labels[key]="numerical"
                    continue
                linear=case["linear_residuals"][row_key]
                original=validation["unrounded"]["residuals"][key]
                tolerance=_NRC_TOLERANCES[key]
                labels[key]=("approximation" if linear>=-tolerance else
                             "numerical_and_approximation" if original-linear < -tolerance else "numerical")
            case["raw_causes"]=labels

        this=next((r for r in old if (r["simulation_day"],r["attempt"])==(row["simulation_day"],row["attempt"])),None)
        if this is None: continue
        identical=all(this[k]==row[k] for k in ("requirements","previous_ration","available_ids"))
        hashes=[]
        p=archived[f"cli/{name}/{150+row['simulation_day']}/{row['attempt']}"]
        for ref in row["references"]:
            old_ref=p["core"].get(ref["source"])
            if old_ref is None: continue
            for c,x in zip(ref["cases"],old_ref["cases"]):
                if c["matrix_sha256"]==x["same_matrix_sha256"]:
                    hashes.append({"reference":ref["source"],"regime":c["regime"],"cbc":x["results"]["cbc"],
                                   "highs":c})
        controlled.append({"strategy":name,"julian_day":150+row["simulation_day"],"attempt":row["attempt"],
                           "identical_requirements_previous_ration_and_ids":identical,"same_matrices":hashes,
                           "new_success":row["success"],"old_success":this["success"]})
    for row in rows:
        if not row["success"]: continue
        ref=next(r for r in row["references"] if r["source"]==row["selected_reference"])
        case=next(c for c in ref["cases"] if c["regime"]==row["selected_case"])
        v=case["validation"]
        q=(v["repair"] or {}).get("quantities") or v["rounded_quantities"]
        assert case["validation_status"]=="approved" and q==row["selected_quantities"]==row["applied_quantities"]
    summary=trace_summary(rows,daily)
    assert all(row["exact_match_to_reported_ration"] for row in summary["attempts"] if row["success"])
    report[f"highs_{name}"]={
        "execution":execution,"completed_julian_days":days,"daily":daily,
        "attempts":[row for key,element in data.items() if "ration_optimizer_attempt_pen_" in key
                    for row in element["values"]],
        "diagnostic_trace":summary,"raw_attempts":rows,"counts":counts(rows),"group_totals":metrics(daily,days),
    }
write(root/"comparison.json",{"scenarios":report,"controlled_attempts":controlled})
for name,val in report.items():
    rows=val["raw_attempts"]
    print(name,val["completed_julian_days"],round(val["execution"]["wall_seconds"],3),val["counts"])
    print("groups", {g:[round(v[k],3) for k in ("cost_usd","dm_kg","milk_kg")] for g,v in val["group_totals"].items()})
    print("lactation",[(r["julian_day"],round(r["formulated_usd_per_animal_day"],6),round(r["kg_dm_per_animal"],6),
                       round(r["applied_feed_at_input_prices_usd"],3)) for r in val["daily"] if r["group"]=="LAC_COW"])
    print("attempts",[(150+r["simulation_day"],r["attempt"],r["success"],r.get("selected_reference"),
                      r.get("solver_calls"),r.get("lower_bound"),r.get("gap"),r.get("optimization_seconds"),
                      {k:round(v,5) for k,v in r.get("phases",{}).items()}) for r in rows])
print("controlled",[(r["strategy"],r["julian_day"],r["attempt"],r["identical_requirements_previous_ration_and_ids"],
                    len(r["same_matrices"])) for r in controlled])
for key in ("cbc","highs"):
    cases=[c[key] for r in controlled for c in r["same_matrices"]]
    print("matched",key,len(cases),
          sum(bool(c.get("final_approved")) if key=="cbc" else c["validation_status"]=="approved" for c in cases),
          sum(any("numerical" in v for v in c.get("raw_failure_causes",c.get("raw_causes",{})).values()) for c in cases),
          sum(any("approximation" in v for v in c.get("raw_failure_causes",c.get("raw_causes",{})).values()) for c in cases))
