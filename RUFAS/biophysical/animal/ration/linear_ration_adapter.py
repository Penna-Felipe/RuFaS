"""Opt-in NRC backend with the formulation contract used by the Pen."""

from dataclasses import dataclass
from enum import Enum, IntEnum
from math import isfinite
from time import perf_counter

import numpy as np
import pulp
from scipy.optimize import OptimizeResult

from RUFAS.biophysical.animal.data_types.animal_combination import AnimalCombination
from RUFAS.biophysical.animal.data_types.nutrition_data_structures import NutritionRequirements
from RUFAS.biophysical.animal.ration.linear_cost_bound import meets_target, primary_lower_bound, relative_gap
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import (
    LinearRationOptimizer,
    LinearRationStatus,
    NRCSelectionResult,
)
from RUFAS.biophysical.animal.ration.linear_reference import (
    OBJECTIVES,
    ReferenceGenerationError,
    build_basic_reference,
    grid_key,
    reference_issue,
)
from RUFAS.biophysical.animal.ration.ration_optimizer import RationConfig
from RUFAS.data_structures.feed_storage_to_animal_connection import Feed, NutrientStandard, RUFAS_ID
from RUFAS.output_manager import OutputManager


class LinearSearchStrategy(str, Enum):
    SINGLE = "single"
    FULL = "full"
    ADAPTIVE_GAP = "adaptive_gap"


class LinearAttemptStatus(IntEnum):
    APPROVED = 0
    INFEASIBLE = 1
    SOLVER_ERROR = 2
    NRC_REJECTED = 3
    NO_REFERENCE = 4


@dataclass(frozen=True)
class ReferenceAttempt:
    source: str
    quantities: dict[RUFAS_ID, float] | None
    generation_seconds: float
    generation_calls: int = 0
    status: LinearRationStatus | None = None
    message: str = ""
    selection: NRCSelectionResult | None = None
    solve_and_validate_seconds: float = 0.0


class LinearRationAdapter:
    """Run the linear backend for automatic NRC formulation of lactating cows.

    A compatible previous ration is tried first, followed by the four basic LP
    reference objectives. The budget counts distinct references sent to the six
    NRC LPs. Discarded or duplicated references do not consume the budget.
    """

    def __init__(
        self,
        strategy: LinearSearchStrategy | str = LinearSearchStrategy.ADAPTIVE_GAP,
        gap_target: float = 0.05,
        max_references: int = 5,
        *,
        solver: pulp.LpSolver | None = None,
    ) -> None:
        if not isfinite(gap_target) or not 0 <= gap_target < 1:
            raise ValueError("Gap target must be a finite fraction in [0, 1).")
        if isinstance(max_references, bool) or not isinstance(max_references, int) or max_references < 1:
            raise ValueError("Maximum references must be a positive integer.")
        self.strategy = LinearSearchStrategy(strategy)
        self.gap_target = gap_target
        self.max_references = max_references
        self.solver = solver
        self.optimizer = LinearRationOptimizer()

    def attempt_optimization(
        self,
        nutrient_standard: NutrientStandard,
        pen_average_body_weight: float,
        pen_average_enteric_methane: float | None,
        pen_average_urine_nitrogen: float | None,
        requirements: NutritionRequirements,
        initial_dry_matter_requirement: float,
        initial_protein_requirement: float,
        pen_available_feeds: list[Feed],
        animal_combination: AnimalCombination,
        previous_ration: dict[RUFAS_ID | str, float | str] | None = None,
        user_defined_ration_dictionary: dict[RUFAS_ID, float] | None = None,
        user_defined_ration_tolerance: float | None = None,
    ) -> tuple[OptimizeResult, RationConfig]:
        """Return a Pen-compatible result with final rounded or repaired quantities."""
        if (
            nutrient_standard is not NutrientStandard.NRC
            or animal_combination is not AnimalCombination.LAC_COW
            or user_defined_ration_dictionary is not None
            or user_defined_ration_tolerance is not None
        ):
            raise ValueError("The linear backend supports automatic NRC formulation for lactating cows only.")
        config = RationConfig(
            nutrient_standard,
            requirements,
            list(pen_available_feeds),
            initial_dry_matter_requirement,
            initial_protein_requirement,
            pen_average_body_weight,
            pen_average_enteric_methane,
            pen_average_urine_nitrogen,
            animal_combination,
        )
        return self._search(config, previous_ration), config

    def _search(
        self, config: RationConfig, previous_ration: dict[RUFAS_ID | str, float | str] | None
    ) -> OptimizeResult:
        start = perf_counter()
        bound_start = perf_counter()
        bound = primary_lower_bound(config, self.solver) if config.feeds_used else {}
        bound_seconds = perf_counter() - bound_start if config.feeds_used else 0.0
        lower = bound.get("lower_bound")
        lower = float(lower) if isinstance(lower, (float, int)) else None

        feed_ids = [feed.rufas_id for feed in config.feeds_used]
        sources = ["previous_ration", *OBJECTIVES] if previous_ration else list(OBJECTIVES)
        budget = 1 if self.strategy is LinearSearchStrategy.SINGLE else self.max_references
        attempts: list[ReferenceAttempt] = []
        seen: set[tuple[int, ...]] = set()
        best: dict[RUFAS_ID, float] | None = None
        best_cost: float | None = None
        best_source = None
        best_case = None
        reason = "references_exhausted" if feed_ids else "no_ingredients"

        for source in sources if feed_ids else ():
            generation_start = perf_counter()
            count = 0
            try:
                if source == "previous_ration":
                    reference = self._previous_reference(previous_ration or {}, set(feed_ids))
                else:
                    reference, metrics = build_basic_reference(config, source, self.solver)
                    count = int(metrics["lp_calls"])
            except ReferenceGenerationError as error:
                attempts.append(
                    ReferenceAttempt(
                        source, None, perf_counter() - generation_start, error.solver_calls, error.status, str(error)
                    )
                )
                continue
            except ValueError as error:
                attempts.append(ReferenceAttempt(source, None, perf_counter() - generation_start, message=str(error)))
                continue

            generation_seconds = perf_counter() - generation_start
            issue = reference_issue(config, reference)
            key = grid_key(reference, feed_ids) if issue is None else None
            if issue is not None or key in seen:
                attempts.append(
                    ReferenceAttempt(
                        source, reference, generation_seconds, count, message=issue or "Duplicate reference."
                    )
                )
                continue
            assert key is not None
            seen.add(key)
            solve_start = perf_counter()
            selection = self.optimizer.solve_and_validate_nrc_cases(config, reference, self.solver)
            attempts.append(
                ReferenceAttempt(
                    source,
                    reference,
                    generation_seconds,
                    count,
                    selection=selection,
                    solve_and_validate_seconds=perf_counter() - solve_start,
                )
            )

            if selection.selected_case is not None and selection.selected_cost is not None:
                quantities = selection.validations[selection.selected_case].final_quantities
                if quantities is not None and (best_cost is None or selection.selected_cost < best_cost):
                    best, best_cost = dict(quantities), selection.selected_cost
                    best_source, best_case = source, selection.selected_case

            if (
                self.strategy is LinearSearchStrategy.ADAPTIVE_GAP
                and best_cost is not None
                and meets_target(best_cost, lower, self.gap_target)
            ):
                reason = "gap_target_reached"
                break
            if len(seen) >= budget:
                reason = "reference_limit"
                break

        gap, gap_status = relative_gap(best_cost, lower)
        statuses = {attempt.status for attempt in attempts if attempt.status is not None}
        for attempt in attempts:
            if attempt.selection is not None:
                statuses.update(case.status for case in attempt.selection.cases.values())

        if best is not None:
            status = LinearAttemptStatus.APPROVED
        elif LinearRationStatus.SOLVER_ERROR in statuses or bound.get("status") == "SolverError":
            status = LinearAttemptStatus.SOLVER_ERROR
        elif LinearRationStatus.OPTIMAL in statuses:
            status = LinearAttemptStatus.NRC_REJECTED
        elif LinearRationStatus.INFEASIBLE in statuses:
            status = LinearAttemptStatus.INFEASIBLE
        else:
            status = LinearAttemptStatus.NO_REFERENCE

        messages = {
            LinearAttemptStatus.APPROVED: "Diet approved by NRC.",
            LinearAttemptStatus.SOLVER_ERROR: "Solver error during the linear search.",
            LinearAttemptStatus.NRC_REJECTED: "No linear candidate passed NRC validation.",
            LinearAttemptStatus.INFEASIBLE: "The attempted linear problems were infeasible.",
            LinearAttemptStatus.NO_REFERENCE: "No usable reference was available.",
        }
        return OptimizeResult(
            success=status is LinearAttemptStatus.APPROVED,
            status=int(status),
            message=messages[status],
            x=np.array([best[feed_id] for feed_id in feed_ids], dtype=float) if best is not None else None,
            fun=best_cost,
            quantities=best,
            strategy=self.strategy.value,
            nrc_validation=(
                "approved"
                if best is not None
                else "rejected" if LinearRationStatus.OPTIMAL in statuses else "no_candidate"
            ),
            selected_reference=best_source,
            selected_case=best_case,
            stop_reason=reason,
            gap=gap,
            gap_status=gap_status,
            gap_target=self.gap_target,
            lower_bound=lower,
            bound_details=bound,
            references_resolved=len(seen),
            max_references=budget,
            references=attempts,
            solver_calls=int(bool(bound))
            + sum(
                ref.generation_calls + (len(ref.selection.cases) if ref.selection is not None else 0)
                for ref in attempts
            ),
            bound_seconds=bound_seconds,
            elapsed_seconds=perf_counter() - start,
        )

    @staticmethod
    def _previous_reference(
        ration: dict[RUFAS_ID | str, float | str], available_ids: set[RUFAS_ID]
    ) -> dict[RUFAS_ID, float]:
        reference = {}
        for feed_id, value in ration.items():
            if feed_id in ("status", "objective"):
                continue
            if not isinstance(feed_id, int) or isinstance(value, str) or not isfinite(value) or value < 0:
                raise ValueError("Previous ration must contain finite non-negative quantities keyed by feed ID.")
            if feed_id not in available_ids:
                if value != 0:
                    raise ValueError(f"Previous ration contains unavailable feed {feed_id}.")
                continue
            reference[feed_id] = value
        return reference

    @staticmethod
    def make_ration_from_solution(pen_available_feeds: list[Feed], solution: OptimizeResult) -> dict[RUFAS_ID, float]:
        """Apply the already validated result by ID, even if the feed list was reordered."""
        if not solution.success or solution.quantities is None:
            raise ValueError("No approved linear ration to apply.")
        if {feed.rufas_id for feed in pen_available_feeds} != set(solution.quantities):
            raise ValueError("The approved ration does not match the current ingredients.")
        return {feed.rufas_id: solution.quantities[feed.rufas_id] for feed in pen_available_feeds}

    @staticmethod
    def handle_failed_constraints(
        num_attempts: int,
        solution: OptimizeResult,
        ration_config: RationConfig,
        animal_combination: AnimalCombination,
        pen_id: RUFAS_ID,
        pen_available_feeds: list[Feed],
        average_nutrient_requirements: NutritionRequirements,
        initial_dry_matter_requirement: float,
        initial_protein_requirement: float,
        sim_day: int,
    ) -> list[str]:
        """Expose NRC failure names to the Pen retry logic without requiring solution.x."""
        failed = set()
        for attempt in solution.references:
            if attempt.selection is None:
                continue
            for validation in attempt.selection.validations.values():
                failed.update(validation.unrounded.violations)
                if validation.rounded is not None:
                    failed.update(validation.rounded.violations)
        OutputManager().add_log(
            f"Linear ration attempt for pen {pen_id}",
            f"{solution.message} Stop reason: {solution.stop_reason}. NRC violations: {', '.join(sorted(failed))}.",
            {
                "class": LinearRationAdapter.__name__,
                "function": "handle_failed_constraints",
                "simulation_day": sim_day,
                "attempt": num_attempts,
            },
        )
        return sorted(failed)
