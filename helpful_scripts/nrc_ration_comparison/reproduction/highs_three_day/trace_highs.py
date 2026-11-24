
import hashlib,json,os,sys
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()))
from helpful_scripts.nrc_ration_comparison.cli_three_day_trace import trace_cli
from helpful_scripts.nrc_ration_comparison.solver_benchmark import linear_matrix,resids
from RUFAS.biophysical.animal.pen import Pen
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import LinearRationOptimizer

path=Path(os.environ["RUFAS_EXPERIMENT_TRACE"])
attempt=Pen._attempt_formulation
solve=LinearRationOptimizer._solve_problem

def capture(pen,*args,**kwargs):
    if pen.animal_combination.value!="lac_cow":
        return attempt(pen,*args,**kwargs)
    cases=[]
    diagnostics_seconds=0.0
    def record(config,problem,variables,solver):
        nonlocal diagnostics_seconds
        start=perf_counter()
        result=solve(config,problem,variables,solver)
        seconds=perf_counter()-start
        start=perf_counter()
        matrix=linear_matrix(problem,variables)
        cases.append({"seconds":seconds,"solver":solver.name,
                      "matrix_sha256":hashlib.sha256(json.dumps(matrix,sort_keys=True).encode()).hexdigest(),
                      "linear_residuals":resids(matrix,[result.quantities[k] for k in variables])
                          if result.quantities is not None else None})
        diagnostics_seconds+=perf_counter()-start
        return result
    with patch.object(LinearRationOptimizer,"_solve_problem",staticmethod(record)):
        solution,config=attempt(pen,*args,**kwargs)
    with path.with_name("phase_details.jsonl").open("a",encoding="utf-8") as stream:
        stream.write(json.dumps({"solver":solution.nutritional_solver,"bound_seconds":solution.bound_seconds,
                      "adapter_seconds":solution.elapsed_seconds,"diagnostics_seconds":diagnostics_seconds,
                      "weight_kg":config.pen_average_body_weight,"initial_dmi":config.initial_dry_matter_requirement,
                      "initial_mp":config.initial_protein_requirement,"cases":cases})+"\n")
    return solution,config

with patch.object(Pen,"_attempt_formulation",capture):
    trace_cli(path)
