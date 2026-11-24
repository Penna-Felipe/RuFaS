"""Record formulation inputs and outputs while running the unchanged RuFaS CLI."""

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from RUFAS.biophysical.animal.pen import Pen
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import LinearRationOptimizer
from RUFAS.main import main
from RUFAS.output_manager import OutputManager


def summarize_reference(reference):
    selection = reference.selection
    cases = []
    if selection is not None:
        for regime, result in selection.cases.items():
            validation = selection.validations.get(regime)
            cases.append(
                {
                    "regime": regime,
                    "lp_status": result.status.value,
                    "lp_cost": result.cost,
                    "lp_quantities": result.quantities,
                    "validation_status": validation.status.value if validation else None,
                    "validation": asdict(validation) if validation else None,
                }
            )
    return {
        "source": reference.source,
        "reference_quantities": reference.quantities,
        "generation_calls": reference.generation_calls,
        "generation_seconds": reference.generation_seconds,
        "solve_and_validate_seconds": reference.solve_and_validate_seconds,
        "message": reference.message,
        "cases": cases,
    }


def trace_cli(path):
    attempt = Pen._attempt_formulation
    record = Pen._record_ration_attempt
    dump = OutputManager.dump_all_nondata_pools
    pending = {}

    def capture_inputs(pen, *args, **kwargs):
        ration = dict(pen.ration)
        solution, config = attempt(pen, *args, **kwargs)
        if pen.animal_combination.value == "lac_cow":
            pending[pen.id] = {
                "previous_ration": ration,
                "available_ids": [feed.rufas_id for feed in config.feeds_used],
                "requirements": asdict(config.animal_requirements),
            }
            pending[pen.id]["config"] = config
        return solution, config

    def capture_result(pen, solution, day, number, *args, **kwargs):
        record(pen, solution, day, number, *args, **kwargs)
        if pen.id not in pending:
            return
        inputs = pending.pop(pen.id)
        config = inputs.pop("config")
        if solution.ration_backend == "slsqp":
            applied = dict(pen.ration) if solution.success else None
            row = {
                **inputs,
                "simulation_day": day,
                "pen_id": pen.id,
                "attempt": number,
                "backend": "slsqp",
                "success": bool(solution.success),
                "applied_quantities": applied,
                "applied_nrc_check": (
                    asdict(LinearRationOptimizer.validate_nrc_candidate(config, applied))
                    if applied is not None
                    else None
                ),
            }
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, default=str) + "\n")
            return
        row = {
            **inputs,
            "backend": "pulp",
            "simulation_day": day,
            "pen_id": pen.id,
            "attempt": number,
            "status": int(solution.status),
            "message": solution.message,
            "success": bool(solution.success),
            "selected_reference": solution.selected_reference,
            "selected_case": solution.selected_case,
            "lower_bound": solution.lower_bound,
            "gap": solution.gap,
            "solver_calls": solution.solver_calls,
            "optimization_seconds": solution.ration_optimization_seconds,
            "stop_reason": solution.stop_reason,
            "selected_quantities": solution.quantities,
            "applied_quantities": dict(pen.ration) if solution.success else None,
            "references": [summarize_reference(reference) for reference in solution.references],
        }
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, default=str) + "\n")

    def capture_partial_output(manager, *args, **kwargs):
        variables = manager._get_flat_variables_pool()
        if "RufasTime.day" in variables:
            path.with_name("partial_variables.json").write_text(json.dumps(variables, default=str), encoding="utf-8")
        return dump(manager, *args, **kwargs)

    with (
        patch.object(Pen, "_attempt_formulation", capture_inputs),
        patch.object(Pen, "_record_ration_attempt", capture_result),
        patch.object(OutputManager, "dump_all_nondata_pools", capture_partial_output),
    ):
        main()


if __name__ == "__main__":
    trace_cli(Path(os.environ["RUFAS_EXPERIMENT_TRACE"]))
