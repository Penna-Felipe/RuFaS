import json
from pathlib import Path
from statistics import median
from time import perf_counter
from RUFAS.biophysical.animal.ration.linear_ration_adapter import LinearRationAdapter
from helpful_scripts.nrc_ration_comparison.solver_benchmark import scenario_inputs
from helpful_scripts.nrc_ration_comparison.cli_three_day import BASE

output=Path("output/nrc_reference_solver_budgets")
output.mkdir(exist_ok=False)
scenarios=list(scenario_inputs(BASE/"isolated_audit.json",generate_historical_references=False))
adapters={(k,b):LinearRationAdapter("full",max_references=b,reference_solver=k,nutritional_solver="highs")
          for b in (1,2,3,5) for k in ("cbc","highs")}
results={}
for name,config,_,previous in scenarios:
    print(name,flush=True)
    results[name]={}
    for (key,budget),adapter in adapters.items():
        start=perf_counter()
        res=adapter._search(config,previous)
        results[name].setdefault(key,{})[str(budget)]={
            "success":bool(res.success),"status":int(res.status),"cost":res.fun,"gap":res.gap,
            "bound":res.lower_bound,"winner":res.selected_reference,"stop_reason":res.stop_reason,
            "calls":res.solver_calls,"seconds":perf_counter()-start,
            "evaluated":[r.source for r in res.references if r.selection is not None],
            "generation_failures":[[r.source,r.message] for r in res.references if r.quantities is None],
        }
    for budget in (1,2,3,5):
        assert results[name]["cbc"][str(budget)]["bound"]==results[name]["highs"][str(budget)]["bound"]
assert len(results)==27
(output/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
for b in (1,2,3,5):
    rows=[[x[k][str(b)] for x in results.values()] for k in ("cbc","highs")]
    print(b,[(sum(x["success"] for x in a),sum(x["gap"] is not None and x["gap"]<=.05 for x in a),
              sum(x["calls"] for x in a),round(median(x["seconds"] for x in a),4)) for a in rows],
          sum(a["success"] and not z["success"] for a,z in zip(*rows)),
          sum(z["success"] and not a["success"] for a,z in zip(*rows)))
print("problem",results["historical/123802_midwest_five_market"])
