"""Least-cost NRC ration model for the linear subset of the original constraints."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import ClassVar

import numpy as np
import numpy.typing as npt
import pulp

from RUFAS.biophysical.animal.animal_module_constants import AnimalModuleConstants
from RUFAS.biophysical.animal.data_types.animal_combination import AnimalCombination
from RUFAS.biophysical.animal.nutrients.nutrition_supply_calculator import FeedInRation, NutritionSupplyCalculator
from RUFAS.biophysical.animal.ration.ration_optimizer import RationConfig, RationOptimizer
from RUFAS.data_structures.feed_storage_to_animal_connection import FeedComponentType, NutrientStandard, RUFAS_ID


from RUFAS.general_constants import GeneralConstants


class LinearRationStatus(Enum):
    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"
    SOLVER_ERROR = "solver_error"


@dataclass(frozen=True)
class LinearRationResult:
    status: LinearRationStatus
    quantities: dict[RUFAS_ID, float] | None = None
    cost: float | None = None
    message: str = ""


@dataclass(frozen=True)
class NRCEnergyCoefficients:
    """Net energy per ingredient, in Mcal per kg of dry matter."""

    maintenance: float
    growth: float
    lactation: float


@dataclass(frozen=True)
class NRCProteinCoefficients:
    """Protein contributions in g per kg of ingredient dry matter."""

    microbial_tdn: float
    microbial_rdp: float
    digestible_rup: float

    MICROBIAL_METABOLIZABLE_FRACTION: ClassVar[float] = 0.64
    ENDOGENOUS_PER_KG_DRY_MATTER: ClassVar[float] = 0.4 * 11.8


NRCCase = tuple[str, str]

# Absolute tolerances in the units of each original residual.
_NRC_TOLERANCES = {
    "DMI_constraint_lower": 1e-7,  # kg dry matter / cow / day
    "DMI_constraint_upper": 1e-7,
    "calcium_constraint": 1e-5,  # g / cow / day
    "phosphorus_constraint": 1e-5,
    "protein_constraint_lower": 1e-5,
    "protein_constraint_upper": 1e-5,
    "NDF_constraint_lower": 1e-6,  # percentage points
    "NDF_constraint_upper": 1e-6,
    "forage_NDF_constraint": 1e-6,
    "fat_constraint": 1e-6,
    "NE_total_constraint": 1e-6,  # Mcal / cow / day
    "NE_maintenance_and_activity_constraint": 1e-6,
    "NE_growth_constraint": 1e-6,
    "NE_lactation_constraint": 1e-6,
}
_INGREDIENT_BOUND_TOLERANCE = 1e-7  # kg dry matter / cow / day
_ROUNDING_SCALE = 1_000_000
_MAX_ROUNDING_REPAIR_ATTEMPTS = 32


class NRCValidationStatus(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class NRCResiduals:
    residuals: dict[str, float]
    violations: dict[str, str]


@dataclass(frozen=True)
class NRCRoundingRepair:
    """Outcome of the bounded search around the rounded ration."""

    triggers: tuple[str, ...]
    attempts: int
    quantities: dict[RUFAS_ID, float] | None = None
    validation: NRCResiduals | None = None
    cost_delta: float | None = None


@dataclass(frozen=True)
class NRCValidationResult:
    unrounded: NRCResiduals
    rounded: NRCResiduals | None = None
    rounded_quantities: dict[RUFAS_ID, float] | None = None

    repair: NRCRoundingRepair | None = None

    @property
    def final_quantities(self) -> dict[RUFAS_ID, float] | None:
        if self.repair is not None and self.repair.quantities is not None:
            return self.repair.quantities
        if self.status is NRCValidationStatus.APPROVED:
            return self.rounded_quantities
        return None

    @property
    def status(self) -> NRCValidationStatus:
        if self.rounded is not None and not self.unrounded.violations:
            if not self.rounded.violations or (self.repair is not None and self.repair.quantities is not None):
                return NRCValidationStatus.APPROVED
        return NRCValidationStatus.REJECTED


@dataclass(frozen=True)
class NRCSelectionResult:
    cases: dict[NRCCase, LinearRationResult]
    validations: dict[NRCCase, NRCValidationResult]
    selected_case: NRCCase | None
    selected_cost: float | None
    message: str


class LinearRationOptimizer:
    """Solve the linear constraints for lactating NRC cows using kg of dry matter per cow per day."""

    @staticmethod
    def calculate_nrc_energy_coefficients(
        config: RationConfig, reference_ration: Mapping[RUFAS_ID, float]
    ) -> dict[RUFAS_ID, NRCEnergyCoefficients]:
        """Calculate NRC net energy coefficients in Mcal per kg of ingredient dry matter.

        Reference amounts are kg of dry matter per cow per day. Missing feed IDs
        have zero inclusion. The intake discount is calculated once from the
        entire reference ration and is held fixed for all ingredients. Multiplying
        these coefficients by candidate amounts and summing gives linear offers
        in Mcal per cow per day. The offers reproduce NRC at the reference ration
        up to floating-point error and approximate NRC away from it.
        """
        reference_feeds, _ = LinearRationOptimizer._prepare_nrc_reference(config, reference_ration)
        for feed in reference_feeds:
            info = feed.info
            if not all(isfinite(value) for value in (info.TDN, info.DE, info.EE)):
                raise ValueError(f"TDN, DE and EE for feed {info.rufas_id} must be finite.")

        calculator = NutritionSupplyCalculator
        discount = calculator.calculate_nutrient_intake_discount(reference_feeds, config.pen_average_body_weight)
        digestible_energy = {feed.info.rufas_id: feed.info.DE * discount for feed in reference_feeds}
        metabolizable_energy = calculator.calculate_actual_metabolizable_energy(reference_feeds, digestible_energy)
        if not (
            isfinite(discount)
            and all(isfinite(value) for value in digestible_energy.values())
            and all(isfinite(value) for value in metabolizable_energy.values())
        ):
            raise ValueError("Reference energy factors must be finite.")

        coefficients = {}
        for reference_feed in reference_feeds:
            feed = reference_feed.info
            feed_id = feed.rufas_id
            unit_feed = [FeedInRation(amount=1.0, info=feed)]
            maintenance = calculator.calculate_actual_maintenance_net_energy(unit_feed, metabolizable_energy)
            growth = calculator.calculate_actual_growth_net_energy(unit_feed, metabolizable_energy)
            lactation = calculator.calculate_actual_lactation_net_energy(
                unit_feed, metabolizable_energy, digestible_energy
            )
            if not all(isfinite(value) for value in (maintenance, growth, lactation)):
                raise ValueError(f"Net energy coefficients for feed {feed_id} must be finite.")
            coefficients[feed_id] = NRCEnergyCoefficients(maintenance, growth, lactation)
        return coefficients

    @staticmethod
    def calculate_nrc_protein_coefficients(
        config: RationConfig, reference_ration: Mapping[RUFAS_ID, float]
    ) -> dict[RUFAS_ID, NRCProteinCoefficients]:
        """Calculate fixed NRC protein coefficients by feed ID.

        Reference amounts are kg of dry matter per cow per day. Omitted feeds
        have zero inclusion. The intake discount and passage rates are computed
        from the complete reference, then held fixed for any candidate.

        Per kg of ingredient dry matter, the microbe estimates are 0.13 times
        discounted TDN mass and 0.85 times RDP mass, converted to grams. Digestible
        RUP is RUP mass times its digestibility, also converted to grams.
        For a candidate, multiply each coefficient by its ingredient amount and
        sum each component across the diet. Protein supply (g/cow/day) is
        0.64 times the minimum of the two microbial totals, plus digestible RUP
        and 4.72 g per kg of candidate dry matter intake.
        """
        feeds, intake = LinearRationOptimizer._prepare_nrc_reference(config, reference_ration)
        for feed in feeds:
            info = feed.info
            if not all(
                isfinite(value) for value in (info.TDN, info.NDF, info.CP, info.N_A, info.N_B, info.Kd, info.dRUP)
            ):
                raise ValueError(f"Protein inputs for feed {info.rufas_id} must be finite.")

        calculator = NutritionSupplyCalculator
        weight = config.pen_average_body_weight
        discount = calculator.calculate_nutrient_intake_discount(feeds, weight)
        concentrate_percentage = calculator._calculate_percentage_of_concentrates(feeds, intake)
        passage = calculator._calculate_protein_passage_rates(feeds, intake, weight, concentrate_percentage)
        if not all(isfinite(value) for value in (discount, concentrate_percentage, *passage.values())):
            raise ValueError("Reference protein factors must be finite.")

        rdp = calculator._calculate_rumen_degradable_protein_percentages(feeds, passage)
        rup = calculator._calculate_rumen_undegradable_protein_percentages(feeds, rdp)
        fraction = GeneralConstants.PERCENTAGE_TO_FRACTION
        grams_per_kg = GeneralConstants.KG_TO_GRAMS
        coefficients = {}
        for feed in feeds:
            feed_id = feed.info.rufas_id
            microbial_tdn = feed.info.TDN * discount * fraction * 0.13 * grams_per_kg
            microbial_rdp = rdp[feed_id] * fraction * 0.85 * grams_per_kg
            digestible_rup = rup[feed_id] * fraction * feed.info.dRUP * fraction * grams_per_kg
            if not all(isfinite(value) for value in (microbial_tdn, microbial_rdp, digestible_rup)):
                raise ValueError(f"Protein coefficients for feed {feed_id} must be finite.")
            coefficients[feed_id] = NRCProteinCoefficients(microbial_tdn, microbial_rdp, digestible_rup)
        return coefficients

    @staticmethod
    def _prepare_nrc_reference(
        config: RationConfig, reference_ration: Mapping[RUFAS_ID, float]
    ) -> tuple[list[FeedInRation], float]:
        if config.nutrient_standard is not NutrientStandard.NRC:
            raise ValueError("Reference coefficients require the NRC nutrient standard.")

        weight = config.pen_average_body_weight
        if not isfinite(weight) or weight <= 0:
            raise ValueError("Mean body weight must be finite and positive.")

        feeds_by_id = {feed.rufas_id: feed for feed in config.feeds_used}
        if len(feeds_by_id) != len(config.feeds_used):
            raise ValueError("Feed IDs must be unique.")
        if reference_ration.keys() - feeds_by_id.keys():
            raise ValueError("The reference ration contains unknown feed IDs.")

        feeds = []
        for feed_id in sorted(feeds_by_id):
            amount = reference_ration.get(feed_id, 0.0)
            if not isfinite(amount) or amount < 0:
                raise ValueError(f"Reference amount for feed {feed_id} must be finite and non-negative.")
            feeds.append(FeedInRation(amount=amount, info=feeds_by_id[feed_id]))

        intake = sum(feed.amount for feed in feeds)
        if not isfinite(intake) or intake <= 0:
            raise ValueError("Reference dry matter intake must be finite and positive.")
        return feeds, intake

    def solve_nrc_cases(
        self,
        config: RationConfig,
        reference_ration: Mapping[RUFAS_ID, float],
        solver: pulp.LpSolver | None = None,
    ) -> dict[NRCCase, LinearRationResult]:
        """Solve each (total energy source, microbial protein limiter) case.

        NRC coefficients are calculated once from the reference, in Mcal or g
        per kg of dry matter. All offers and requirements are per cow per day.
        Each OPTIMAL result is a candidate of the fixed-coefficient LP only.
        Evaluating nutritional adequacy requires recalculating NRC on the candidate.
        """
        energy = self.calculate_nrc_energy_coefficients(config, reference_ration)
        protein = self.calculate_nrc_protein_coefficients(config, reference_ration)
        requirements = config.animal_requirements
        energy_minimums = {
            "maintenance": requirements.maintenance_energy + requirements.activity_energy,
            "growth": requirements.growth_energy,
            "lactation": requirements.lactation_energy + requirements.pregnancy_energy,
        }
        protein_maximum = config.initial_protein_requirement * AnimalModuleConstants.PROTEIN_UPPER_LIMIT_FACTOR

        results = {}
        for total_energy_source in energy_minimums:
            for protein_limiter, other_limiter in (("tdn", "rdp"), ("rdp", "tdn")):
                problem, quantities = self._build_problem(config)
                for source, minimum in energy_minimums.items():
                    supply = pulp.lpSum(
                        amount * getattr(energy[feed_id], source) for feed_id, amount in quantities.items()
                    )
                    problem += supply >= minimum, f"minimum_energy_{source}"
                    if source == total_energy_source:
                        problem += supply >= requirements.total_energy_requirement, "minimum_total_energy"

                microbial = {
                    "tdn": pulp.lpSum(
                        amount * protein[feed_id].microbial_tdn for feed_id, amount in quantities.items()
                    ),
                    "rdp": pulp.lpSum(
                        amount * protein[feed_id].microbial_rdp for feed_id, amount in quantities.items()
                    ),
                }
                problem += microbial[protein_limiter] <= microbial[other_limiter], "active_microbial_limiter"
                protein_supply = NRCProteinCoefficients.MICROBIAL_METABOLIZABLE_FRACTION * microbial[
                    protein_limiter
                ] + pulp.lpSum(
                    amount * (protein[feed_id].digestible_rup + NRCProteinCoefficients.ENDOGENOUS_PER_KG_DRY_MATTER)
                    for feed_id, amount in quantities.items()
                )
                problem += protein_supply >= requirements.metabolizable_protein, "minimum_metabolizable_protein"
                problem += protein_supply <= protein_maximum, "maximum_metabolizable_protein"
                results[total_energy_source, protein_limiter] = self._solve_problem(config, problem, quantities, solver)
        return results

    @staticmethod
    def validate_nrc_candidate(
        config: RationConfig, candidate: Mapping[RUFAS_ID, float], *, repair_rounding: bool = False
    ) -> NRCValidationResult:
        """Evaluate all original NRC inequalities before and after six-decimal rounding.

        Candidate amounts are kg dry matter per cow per day. Omitted ingredients
        have zero inclusion. A valid diet must pass both evaluations. The NRC
        functions are evaluated directly, with no call to SLSQP. With repair
        enabled, only raw-valid candidates rejected after rounding are eligible.
        """
        if (
            config.nutrient_standard is not NutrientStandard.NRC
            or config.animal_combination is not AnimalCombination.LAC_COW
        ):
            raise ValueError("Candidate validation requires NRC and lactating cows.")
        if not isfinite(config.pen_average_body_weight) or config.pen_average_body_weight <= 0:
            raise ValueError("Mean body weight must be finite and positive.")

        feed_ids = [feed.rufas_id for feed in config.feeds_used]
        if len(set(feed_ids)) != len(feed_ids):
            raise ValueError("Feed IDs must be unique.")
        bounds = list(zip(config.feed_minimum_list, config.feed_maximum_list, strict=True))
        if len(bounds) != len(feed_ids):
            raise ValueError("Ingredient bounds must match the feed list.")
        if any(not (isfinite(lower) and isfinite(upper) and lower <= upper) for lower, upper in bounds):
            raise ValueError("Ingredient bounds must be finite and ordered.")

        vector = np.array([candidate.get(feed_id, 0.0) for feed_id in feed_ids], dtype=float)
        violations = {
            f"ingredient_{feed_id}": "Quantity must be finite and non-negative."
            for feed_id, amount in zip(feed_ids, vector)
            if not isfinite(amount) or amount < 0
        }
        unknown_ids = candidate.keys() - set(feed_ids)
        if unknown_ids:
            violations["unknown_ingredients"] = f"Unexpected ingredient IDs: {sorted(unknown_ids)}."
        if violations:
            return NRCValidationResult(NRCResiduals({}, violations))

        original = RationOptimizer()
        original.set_constraints(config)
        functions = [constraint["fun"] for constraint in original.cow_constraints]

        # Round NumPy scalars in the same way as make_ration_from_solution.
        rounded = np.array([round(amount, 6) for amount in vector], dtype=float)
        unrounded_report = LinearRationOptimizer._evaluate_nrc_residuals(config, feed_ids, bounds, functions, vector)
        rounded_report = LinearRationOptimizer._evaluate_nrc_residuals(config, feed_ids, bounds, functions, rounded)
        repair = None
        if repair_rounding and not unrounded_report.violations and rounded_report.violations:
            repair = LinearRationOptimizer._repair_nrc_rounding(
                config, feed_ids, bounds, functions, vector, rounded, tuple(rounded_report.violations)
            )
        return NRCValidationResult(unrounded_report, rounded_report, dict(zip(feed_ids, rounded.tolist())), repair)

    @staticmethod
    def _repair_nrc_rounding(
        config: RationConfig,
        feed_ids: list[RUFAS_ID],
        bounds: list[tuple[float, float]],
        functions: list[Callable[[npt.NDArray[np.float64], RationConfig], float]],
        raw: npt.NDArray[np.float64],
        rounded: npt.NDArray[np.float64],
        triggers: tuple[str, ...],
    ) -> NRCRoundingRepair:
        """Try at most 32 one-increment neighbors, in order of distance from the raw diet."""
        ticks = [round(float(amount) * _ROUNDING_SCALE) for amount in rounded]
        neighbors = []
        for index, (tick, (lower, upper)) in enumerate(zip(ticks, bounds, strict=True)):
            for step in (-1, 1):
                amount = (tick + step) / _ROUNDING_SCALE
                if max(0.0, lower) <= amount <= upper:
                    distance_delta = abs(amount - raw[index]) - abs(rounded[index] - raw[index])
                    cost_delta = step * config.price_list[index] / _ROUNDING_SCALE
                    neighbors.append((distance_delta, cost_delta, feed_ids[index], index, amount))

        # A single change cannot repair a bound violation on a different ingredient.
        outside_bounds = {
            i
            for i, (amount, (lower, upper)) in enumerate(zip(rounded, bounds, strict=True))
            if not max(0.0, lower) <= amount <= upper
        }
        attempts = 0
        for _, cost_delta, _, index, amount in sorted(neighbors):
            if attempts >= _MAX_ROUNDING_REPAIR_ATTEMPTS:
                break
            if outside_bounds - {index}:
                continue
            candidate = rounded.copy()
            candidate[index] = amount
            attempts += 1
            validation = LinearRationOptimizer._evaluate_nrc_residuals(config, feed_ids, bounds, functions, candidate)
            if not validation.violations:
                return NRCRoundingRepair(
                    triggers, attempts, dict(zip(feed_ids, candidate.tolist())), validation, cost_delta
                )

        return NRCRoundingRepair(triggers, attempts)

    @staticmethod
    def _evaluate_nrc_residuals(
        config: RationConfig,
        feed_ids: list[RUFAS_ID],
        bounds: list[tuple[float, float]],
        functions: list[Callable[[npt.NDArray[np.float64], RationConfig], float]],
        vector: npt.NDArray[np.float64],
    ) -> NRCResiduals:
        residuals = {}
        violations = {}
        for feed_id, (lower, upper), amount in zip(feed_ids, bounds, vector):
            if not isfinite(amount):
                violations[f"ingredient_{feed_id}"] = "Rounded quantity is not finite."
            elif amount < lower - _INGREDIENT_BOUND_TOLERANCE or amount > upper + _INGREDIENT_BOUND_TOLERANCE:
                violations[f"ingredient_{feed_id}"] = f"{amount:g} kg outside [{lower:g}, {upper:g}] kg."

        intake = sum(vector.tolist())
        if not isfinite(intake) or intake <= 0:
            violations["dry_matter_intake"] = "Dry matter intake must be finite and positive."
            return NRCResiduals(residuals, violations)

        for function in functions:
            name = function.__name__
            try:
                residual = float(function(vector, config))
            except (ArithmeticError, ValueError) as error:
                residuals[name] = float("nan")
                violations[name] = f"Residual evaluation failed: {error}"
                continue
            residuals[name] = residual
            tolerance = _NRC_TOLERANCES[name]
            if not isfinite(residual):
                violations[name] = "Residual is not finite."
            elif residual < -tolerance:
                violations[name] = f"Residual {residual:.9g} is below {-tolerance:g}."
        return NRCResiduals(residuals, violations)

    def solve_and_validate_nrc_cases(
        self,
        config: RationConfig,
        reference_ration: Mapping[RUFAS_ID, float],
        solver: pulp.LpSolver | None = None,
    ) -> NRCSelectionResult:
        """Evaluate each LP optimum and rank approved diets by their final cost."""
        cases = self.solve_nrc_cases(config, reference_ration, solver)
        validations = {}
        selected_case = None
        selected_cost = None
        for case, result in cases.items():
            if result.status is not LinearRationStatus.OPTIMAL:
                continue
            if result.quantities is None:
                validation = NRCValidationResult(NRCResiduals({}, {"quantities": "LP optimum has no quantities."}))
            else:
                validation = self.validate_nrc_candidate(config, result.quantities, repair_rounding=True)
            validations[case] = validation
            final_quantities = validation.final_quantities
            if final_quantities is not None:
                cost = sum(
                    final_quantities[feed.rufas_id] * price for feed, price in zip(config.feeds_used, config.price_list)
                )
                if selected_cost is None or cost < selected_cost:
                    selected_case, selected_cost = case, cost

        message = ""
        if selected_case is None:
            message = (
                f"No candidate passed NRC validation. Rejected LP optima: {len(validations)}. "
                f"Infeasible LP cases: {sum(r.status is LinearRationStatus.INFEASIBLE for r in cases.values())}. "
                f"Solver errors: {sum(r.status is LinearRationStatus.SOLVER_ERROR for r in cases.values())}."
            )
        return NRCSelectionResult(cases, validations, selected_case, selected_cost, message)

    def solve(self, config: RationConfig, solver: pulp.LpSolver | None = None) -> LinearRationResult:
        """Return quantities by feed ID only when the solver proves optimality."""
        problem, quantities = self._build_problem(config)
        return self._solve_problem(config, problem, quantities, solver)

    @staticmethod
    def _solve_problem(
        config: RationConfig,
        problem: pulp.LpProblem,
        quantities: dict[RUFAS_ID, pulp.LpVariable],
        solver: pulp.LpSolver | None,
    ) -> LinearRationResult:
        try:
            status = problem.solve(solver if solver is not None else pulp.PULP_CBC_CMD(msg=False))
        except (pulp.PulpSolverError, OSError) as error:
            return LinearRationResult(LinearRationStatus.SOLVER_ERROR, message=str(error))

        if status == pulp.LpStatusInfeasible:
            return LinearRationResult(LinearRationStatus.INFEASIBLE, message="Infeasible")
        if status != pulp.LpStatusOptimal or problem.sol_status != pulp.LpSolutionOptimal:
            message = (
                f"{pulp.LpStatus.get(status, status)} / {pulp.LpSolution.get(problem.sol_status, problem.sol_status)}"
            )
            return LinearRationResult(LinearRationStatus.SOLVER_ERROR, message=message)

        solution = {}
        for feed_id, variable in quantities.items():
            amount = variable.varValue
            if amount is None or not isfinite(amount):
                return LinearRationResult(
                    LinearRationStatus.SOLVER_ERROR, message=f"Missing or invalid quantity for feed {feed_id}"
                )
            solution[feed_id] = amount

        cost = sum(solution[feed.rufas_id] * price for feed, price in zip(config.feeds_used, config.price_list))
        return LinearRationResult(LinearRationStatus.OPTIMAL, quantities=solution, cost=cost)

    @staticmethod
    def _build_problem(config: RationConfig) -> tuple[pulp.LpProblem, dict[RUFAS_ID, pulp.LpVariable]]:
        if (
            config.nutrient_standard is not NutrientStandard.NRC
            or config.animal_combination is not AnimalCombination.LAC_COW
        ):
            raise ValueError("The linear ration model requires NRC and lactating cows.")

        requirements = config.animal_requirements
        minimum_dmi = requirements.dry_matter * (1 - config.dmi_constraint_fraction)
        if not isfinite(minimum_dmi) or minimum_dmi <= 0:
            raise ValueError("The minimum dry matter intake must be finite and positive.")

        feed_ids = [feed.rufas_id for feed in config.feeds_used]
        if len(set(feed_ids)) != len(feed_ids):
            raise ValueError("Feed IDs must be unique.")

        quantities = {
            feed_id: pulp.LpVariable(f"feed_{index}", lowBound=lower, upBound=upper)
            for index, (feed_id, lower, upper) in enumerate(
                zip(feed_ids, config.feed_minimum_list, config.feed_maximum_list)
            )
        }
        problem = pulp.LpProblem("linear_ration_nrc", pulp.LpMinimize)
        problem += pulp.lpSum(quantities[feed_id] * price for feed_id, price in zip(feed_ids, config.price_list))

        dmi = pulp.lpSum(quantities.values())
        problem += dmi >= minimum_dmi, "minimum_dmi"
        problem += dmi <= config.initial_dry_matter_requirement * (1 + config.dmi_constraint_fraction), "maximum_dmi"

        unit_feeds = [FeedInRation(amount=1.0, info=feed) for feed in config.feeds_used]
        calcium = pulp.lpSum(
            quantities[feed_id] * NutritionSupplyCalculator.calculate_calcium_supply([feed])
            for feed_id, feed in zip(feed_ids, unit_feeds)
        )
        phosphorus = pulp.lpSum(
            quantities[feed_id] * NutritionSupplyCalculator.calculate_phosphorus_supply([feed])
            for feed_id, feed in zip(feed_ids, unit_feeds)
        )
        problem += calcium >= requirements.calcium, "minimum_calcium"
        minimum_phosphorus = max(requirements.phosphorus, requirements.process_based_phosphorus)
        problem += phosphorus >= minimum_phosphorus, "minimum_phosphorus"

        # Keep percentages in percentage points, as in the original constraint residuals.
        ndf = pulp.lpSum(quantities[feed_id] * percentage for feed_id, percentage in zip(feed_ids, config.NDF_list))
        forage_ndf = pulp.lpSum(
            quantities[feed.rufas_id] * feed.NDF
            for feed in config.feeds_used
            if feed.feed_type == FeedComponentType.FORAGE
        )
        fat = pulp.lpSum(quantities[feed_id] * percentage for feed_id, percentage in zip(feed_ids, config.EE_list))
        problem += ndf >= AnimalModuleConstants.MINIMUM_RATION_NDF * dmi, "minimum_ndf"
        problem += ndf <= AnimalModuleConstants.MAXIMUM_RATION_NDF * dmi, "maximum_ndf"
        problem += forage_ndf >= AnimalModuleConstants.MINIMUM_RATION_FORAGE_NDF * dmi, "minimum_forage_ndf"
        problem += fat <= AnimalModuleConstants.MAXIMUM_RATION_FAT * dmi, "maximum_fat"
        return problem, quantities
