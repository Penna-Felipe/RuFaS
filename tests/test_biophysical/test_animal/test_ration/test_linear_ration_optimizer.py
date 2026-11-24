from collections.abc import Callable
from unittest.mock import MagicMock

import numpy as np
import pytest

from RUFAS.biophysical.animal.data_types.animal_combination import AnimalCombination
from RUFAS.biophysical.animal.data_types.nutrition_data_structures import NutritionRequirements
from RUFAS.biophysical.animal.nutrients.nutrition_supply_calculator import NutritionSupplyCalculator
from RUFAS.biophysical.animal.ration.ration_optimizer import RationConfig, RationOptimizer
from RUFAS.data_structures.feed_storage_to_animal_connection import Feed, FeedComponentType, NutrientStandard

pulp = pytest.importorskip("pulp")

from RUFAS.biophysical.animal.ration.linear_ration_optimizer import (  # noqa: E402
    LinearRationOptimizer,
    LinearRationResult,
    LinearRationStatus,
    NRCEnergyCoefficients,
    NRCProteinCoefficients,
    NRCValidationStatus,
)


@pytest.fixture
def config() -> RationConfig:
    forage = MagicMock(
        spec=Feed,
        rufas_id=20,
        feed_type=FeedComponentType.FORAGE,
        purchase_cost=2,
        lower_limit=0,
        limit=8,
        NDF=50,
        EE=3,
        TDN=60,
        calcium=0.8,
        phosphorus=0.3,
    )
    concentrate = MagicMock(
        spec=Feed,
        rufas_id=3,
        feed_type=FeedComponentType.CONC,
        purchase_cost=1,
        lower_limit=2,
        limit=6,
        NDF=0,
        EE=9,
        TDN=80,
        calcium=0.5,
        phosphorus=0.4,
    )
    requirements = NutritionRequirements.make_empty_nutrition_requirements()
    requirements.dry_matter = 10
    requirements.calcium = 23
    requirements.phosphorus = 15
    requirements.process_based_phosphorus = 20
    result = RationConfig(
        NutrientStandard.NRC,
        requirements,
        [forage, concentrate],
        12,
        100,
        animal_combination=AnimalCombination.LAC_COW,
    )
    result.dmi_constraint_fraction = 0.1
    return result


@pytest.mark.parametrize(
    ("name", "original", "ratio"),
    [
        ("minimum_dmi", RationOptimizer.DMI_constraint_lower, False),
        ("maximum_dmi", RationOptimizer.DMI_constraint_upper, False),
        ("minimum_calcium", RationOptimizer.calcium_constraint, False),
        ("minimum_phosphorus", RationOptimizer.phosphorus_constraint, False),
        ("minimum_ndf", RationOptimizer.NDF_constraint_lower, True),
        ("maximum_ndf", RationOptimizer.NDF_constraint_upper, True),
        ("minimum_forage_ndf", RationOptimizer.forage_NDF_constraint, True),
        ("maximum_fat", RationOptimizer.fat_constraint, True),
    ],
)
@pytest.mark.parametrize("amounts", [(5.0, 4.0), (2.0, 8.0), (9.0, 5.0), (8.0, 0.5), (5.0, 5.0)])
def test_constraint_residual_matches_original(
    config: RationConfig,
    name: str,
    original: Callable[[np.ndarray, RationConfig], float],
    ratio: bool,
    amounts: tuple[float, float],
) -> None:
    problem, quantities = LinearRationOptimizer._build_problem(config)
    for feed, amount in zip(config.feeds_used, amounts):
        quantities[feed.rufas_id].varValue = amount

    constraint = problem.constraints[name]
    residual = constraint.value() * constraint.sense
    expected = original(np.array(amounts), config)
    assert residual == pytest.approx(expected * sum(amounts) if ratio else expected)


def test_solves_least_cost_by_feed_id(config: RationConfig) -> None:
    result = LinearRationOptimizer().solve(config)

    assert result.status is LinearRationStatus.OPTIMAL
    assert result.quantities == pytest.approx({20: 4.5, 3: 4.5})
    assert result.cost == pytest.approx(RationOptimizer.objective(np.array([4.5, 4.5]), config))


def test_honors_ingredient_bounds(config: RationConfig) -> None:
    config.feed_minimum_list[0] = 5.0
    config.feed_maximum_list[1] = 3.5

    result = LinearRationOptimizer().solve(config)

    assert result.status is LinearRationStatus.OPTIMAL
    assert result.quantities == pytest.approx({20: 5.5, 3: 3.5})


def test_reports_infeasibility(config: RationConfig) -> None:
    config.feed_maximum_list = [3.0, 4.0]

    result = LinearRationOptimizer().solve(config)

    assert result.status is LinearRationStatus.INFEASIBLE
    assert result.quantities is None
    assert result.cost is None


def test_reports_solver_exception(config: RationConfig) -> None:
    solver = MagicMock()
    solver.actualSolve.side_effect = pulp.PulpSolverError("solver unavailable")

    result = LinearRationOptimizer().solve(config, solver)

    assert result.status is LinearRationStatus.SOLVER_ERROR
    assert result.quantities is None
    assert result.message == "solver unavailable"


def test_rejects_feasible_solution_without_proof_of_optimality(config: RationConfig) -> None:
    def solve_without_proof(problem: pulp.LpProblem, **kwargs: object) -> int:
        problem.assignStatus(pulp.LpStatusOptimal, pulp.LpSolutionIntegerFeasible)
        return pulp.LpStatusOptimal

    solver = MagicMock()
    solver.actualSolve.side_effect = solve_without_proof

    result = LinearRationOptimizer().solve(config, solver)

    assert result.status is LinearRationStatus.SOLVER_ERROR
    assert result.quantities is None


def test_rejects_duplicate_ids(config: RationConfig) -> None:
    config.feeds_used[1].rufas_id = config.feeds_used[0].rufas_id

    with pytest.raises(ValueError, match="Feed IDs must be unique"):
        LinearRationOptimizer().solve(config)


@pytest.fixture
def energy_config(config: RationConfig) -> RationConfig:
    feeds = [
        MagicMock(
            spec=Feed,
            rufas_id=feed_id,
            feed_type=feed_type,
            is_fat=is_fat,
            EE=ee,
            DE=de,
            TDN=tdn,
            purchase_cost=1.0,
            lower_limit=0.0,
            limit=30.0,
            NDF=ndf,
        )
        for feed_id, feed_type, is_fat, ee, de, tdn, ndf in [
            (20, FeedComponentType.FORAGE, False, 2.0, 3.0, 68.0, 42.0),
            (3, FeedComponentType.CONC, False, 5.0, 3.8, 85.0, 12.0),
            (40, FeedComponentType.MINERAL, False, 0.0, 0.0, 0.0, 0.0),
            (8, FeedComponentType.CONC, True, 98.0, 8.5, 190.0, 0.0),
            (11, FeedComponentType.CONC, False, 3.0, 3.4, 75.0, 16.0),
        ]
    ]
    return RationConfig(
        NutrientStandard.NRC,
        config.animal_requirements,
        feeds,
        24.0,
        1000.0,
        pen_average_body_weight=620.0,
        animal_combination=AnimalCombination.LAC_COW,
    )


@pytest.mark.parametrize(
    "reference",
    [
        {20: 13.2, 3: 9.1, 40: 0.21, 8: 0.42, 11: 1.6},
        {20: 7.3, 3: 4.6, 40: 0.17, 8: 0.31},
    ],
)
def test_reference_energy_matches_original(
    energy_config: RationConfig,
    reference: dict[int, float],
) -> None:
    coefficients = LinearRationOptimizer.calculate_nrc_energy_coefficients(energy_config, reference)
    decision_vector = np.array([reference.get(feed.rufas_id, 0.0) for feed in energy_config.feeds_used])
    feeds, discount, de, me = RationOptimizer._calculate_NE_parameters(decision_vector, energy_config)
    calculator = NutritionSupplyCalculator
    original = {
        "maintenance": calculator.calculate_actual_maintenance_net_energy(feeds, me),
        "growth": calculator.calculate_actual_growth_net_energy(feeds, me),
        "lactation": calculator.calculate_actual_lactation_net_energy(feeds, me, de),
    }
    assert discount < 1.0  # Exercise the diet-dependent discount.
    assert set(coefficients) == {feed.rufas_id for feed in energy_config.feeds_used}
    assert coefficients[40] == NRCEnergyCoefficients(0.0, 0.0, 0.0)
    assert coefficients[8].maintenance == pytest.approx(0.8 * 8.5)
    assert coefficients[8].growth == pytest.approx(0.55 * 8.5)
    assert coefficients[8].lactation == pytest.approx(0.8 * 8.5 * discount)
    assert coefficients[11].lactation > 0.0  # Available even when omitted from the reference.
    for name, expected in original.items():
        approx = sum(getattr(coefficients[feed_id], name) * amount for feed_id, amount in reference.items())
        print(f"{name}: NRC={expected:.12f}, LP={approx:.12f}, absolute deviation={abs(approx - expected):.3e}")
        assert approx == pytest.approx(expected, rel=0, abs=1e-12)

    energy_config.feeds_used.reverse()
    assert LinearRationOptimizer.calculate_nrc_energy_coefficients(energy_config, reference) == coefficients


@pytest.mark.parametrize("weight", [0.0, -1.0, float("nan"), float("inf")])
def test_energy_rejects_invalid_body_weight(energy_config: RationConfig, weight: float) -> None:
    energy_config.pen_average_body_weight = weight
    with pytest.raises(ValueError, match="body weight"):
        LinearRationOptimizer.calculate_nrc_energy_coefficients(energy_config, {20: 10.0})


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ({}, "dry matter intake"),
        ({20: -1.0, 3: 10.0}, "Reference amount"),
        ({20: float("nan")}, "Reference amount"),
        ({20: float("inf")}, "Reference amount"),
        ({20: 1e308, 3: 1e308}, "dry matter intake"),
        ({999: 1.0}, "unknown feed IDs"),
    ],
)
def test_energy_rejects_invalid_reference(
    energy_config: RationConfig, reference: dict[int, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        LinearRationOptimizer.calculate_nrc_energy_coefficients(energy_config, reference)


@pytest.mark.parametrize("field", ["TDN", "DE", "EE"])
def test_energy_rejects_nonfinite_feed_data(energy_config: RationConfig, field: str) -> None:
    setattr(energy_config.feeds_used[0], field, float("nan"))
    with pytest.raises(ValueError, match="must be finite"):
        LinearRationOptimizer.calculate_nrc_energy_coefficients(energy_config, {20: 10.0})


@pytest.fixture
def protein_config(energy_config: RationConfig) -> RationConfig:
    for feed in energy_config.feeds_used:
        feed.CP = 11.0
        feed.N_A = 25.0
        feed.N_B = 55.0
        feed.Kd = 4.5
        feed.dRUP = 78.0
        feed.is_wetforage = feed.rufas_id == 20
        if feed.rufas_id in (8, 40):
            feed.CP = 0.0
    return energy_config


def protein_from_coefficients(
    coefficients: dict[int, NRCProteinCoefficients], ration: dict[int, float]
) -> tuple[float, float, float]:
    tdn = sum(coefficients[feed_id].microbial_tdn * amount for feed_id, amount in ration.items())
    rdp = sum(coefficients[feed_id].microbial_rdp * amount for feed_id, amount in ration.items())
    rup = sum(coefficients[feed_id].digestible_rup * amount for feed_id, amount in ration.items())
    endogenous = NRCProteinCoefficients.ENDOGENOUS_PER_KG_DRY_MATTER * sum(ration.values())
    return NRCProteinCoefficients.MICROBIAL_METABOLIZABLE_FRACTION * min(tdn, rdp) + rup + endogenous, tdn, rdp


def original_protein(config: RationConfig, ration: dict[int, float]) -> float:
    vector = np.array([ration.get(feed.rufas_id, 0.0) for feed in config.feeds_used])
    supply, _ = RationOptimizer._calculate_protein_constraint_parameters(vector, config, use_initial_requirement=False)
    return supply


@pytest.mark.parametrize("limiting_component", ["TDN", "RDP"])
def test_reference_protein_matches_original(protein_config: RationConfig, limiting_component: str) -> None:
    if limiting_component == "TDN":
        for feed in protein_config.feeds_used:
            if feed.CP > 0:
                feed.CP = 35.0
                feed.N_A = 70.0
                feed.N_B = 25.0
    reference = {20: 13.2, 3: 9.1, 40: 0.21, 8: 0.42}
    coefficients = LinearRationOptimizer.calculate_nrc_protein_coefficients(protein_config, reference)
    approx, tdn, rdp = protein_from_coefficients(coefficients, reference)
    original = original_protein(protein_config, reference)
    assert ("TDN" if tdn < rdp else "RDP") == limiting_component
    print(
        f"Reference ({limiting_component} limiting): NRC={original:.12f}, LP={approx:.12f}, "
        f"absolute deviation={abs(approx - original):.3e} g/cow/day"
    )
    assert approx == pytest.approx(original, rel=0, abs=1e-9)
    assert coefficients[11].digestible_rup > 0
    protein_config.feeds_used.reverse()
    assert LinearRationOptimizer.calculate_nrc_protein_coefficients(protein_config, reference) == coefficients


def test_protein_coefficients_are_local_to_reference(protein_config: RationConfig) -> None:
    reference = {20: 13.2, 3: 9.1}
    candidate = {20: 5.0, 3: 17.0, 11: 4.0}
    coefficients = LinearRationOptimizer.calculate_nrc_protein_coefficients(protein_config, reference)
    approx, _, _ = protein_from_coefficients(coefficients, candidate)
    original = original_protein(protein_config, candidate)
    recalculated = LinearRationOptimizer.calculate_nrc_protein_coefficients(protein_config, candidate)
    updated, _, _ = protein_from_coefficients(recalculated, candidate)
    print(
        f"Changed diet: NRC={original:.12f}, fixed reference={approx:.12f}, "
        f"signed deviation={approx - original:.6f} g/cow/day"
    )
    assert abs(approx - original) > 1.0
    assert updated == pytest.approx(original, rel=0, abs=1e-9)
    scaled_candidate = {feed_id: amount * 0.5 for feed_id, amount in candidate.items()}
    scaled, _, _ = protein_from_coefficients(coefficients, scaled_candidate)
    assert scaled == pytest.approx(0.5 * approx)


@pytest.mark.parametrize("field", ["TDN", "NDF", "CP", "N_A", "N_B", "Kd", "dRUP"])
def test_protein_rejects_nonfinite_feed_data(protein_config: RationConfig, field: str) -> None:
    setattr(protein_config.feeds_used[0], field, float("nan"))
    with pytest.raises(ValueError, match="Protein inputs"):
        LinearRationOptimizer.calculate_nrc_protein_coefficients(protein_config, {20: 10.0})


@pytest.fixture
def case_config(config: RationConfig, monkeypatch: pytest.MonkeyPatch) -> RationConfig:
    config.initial_dry_matter_requirement = 10.0
    config.dmi_constraint_fraction = 0.0
    config.initial_protein_requirement = 400.0
    requirements = config.animal_requirements
    requirements.maintenance_energy = 2.0
    requirements.activity_energy = 1.0
    requirements.growth_energy = 2.0
    requirements.lactation_energy = 4.0
    requirements.pregnancy_energy = 1.0

    # At 10 kg intake, the microbial branches cross at 6 kg of forage.
    monkeypatch.setattr(
        LinearRationOptimizer,
        "calculate_nrc_protein_coefficients",
        staticmethod(
            lambda *_: {
                3: NRCProteinCoefficients(40.0, 10.0, 20.0),
                20: NRCProteinCoefficients(10.0, 30.0, 20.0),
            }
        ),
    )
    return config


@pytest.mark.parametrize(
    ("energy_sources", "forage_bounds", "expected_limiters"),
    [
        (("maintenance", "growth", "lactation"), (0.0, 8.0), ("tdn", "rdp")),
        (("maintenance",), (6.5, 8.0), ("tdn",)),
        (("growth",), (0.0, 5.5), ("rdp",)),
        (("lactation",), (6.0, 6.0), ("tdn", "rdp")),
        ((), (0.0, 8.0), ()),
    ],
    ids=["all", "maintenance-tdn", "growth-rdp", "lactation-tie", "total-energy-infeasible"],
)
def test_solve_nrc_cases(
    case_config: RationConfig,
    monkeypatch: pytest.MonkeyPatch,
    energy_sources: tuple[str, ...],
    forage_bounds: tuple[float, float],
    expected_limiters: tuple[str, ...],
    request: pytest.FixtureRequest,
) -> None:
    fields = ("maintenance", "growth", "lactation")
    energy = NRCEnergyCoefficients(*(1.0 if field in energy_sources else 0.9 for field in fields))
    monkeypatch.setattr(
        LinearRationOptimizer,
        "calculate_nrc_energy_coefficients",
        staticmethod(lambda *_: {3: energy, 20: energy}),
    )
    case_config.feed_minimum_list[0], case_config.feed_maximum_list[0] = forage_bounds
    cases = LinearRationOptimizer().solve_nrc_cases(case_config, {3: 5.0, 20: 5.0})

    expected = {(source, limiter) for source in energy_sources for limiter in expected_limiters}
    assert set(cases) == {(source, limiter) for source in fields for limiter in ("tdn", "rdp")}
    print(f"{request.node.name}: {len(expected)} feasible, {len(cases) - len(expected)} infeasible")
    for case, result in cases.items():
        if case not in expected:
            assert result.status is LinearRationStatus.INFEASIBLE
            assert result.quantities is None
            assert result.cost is None
            continue
        assert result.status is LinearRationStatus.OPTIMAL
        forage = max(forage_bounds[0], 6.0 if case[1] == "tdn" else 5.0)
        assert result.quantities == pytest.approx({20: forage, 3: 10.0 - forage})
        assert result.cost == pytest.approx(10.0 + forage)


@pytest.mark.parametrize(
    ("failed_constraint", "energy"),
    [
        ("maintenance_and_activity", NRCEnergyCoefficients(0.25, 1.0, 1.0)),
        ("growth", NRCEnergyCoefficients(1.0, 0.1, 1.0)),
        ("lactation_and_pregnancy", NRCEnergyCoefficients(1.0, 1.0, 0.45)),
        ("minimum_protein", NRCEnergyCoefficients(1.0, 1.0, 1.0)),
        ("maximum_protein", NRCEnergyCoefficients(1.0, 1.0, 1.0)),
    ],
)
def test_nrc_individual_requirements_can_make_every_case_infeasible(
    case_config: RationConfig, monkeypatch: pytest.MonkeyPatch, failed_constraint: str, energy: NRCEnergyCoefficients
) -> None:
    monkeypatch.setattr(
        LinearRationOptimizer,
        "calculate_nrc_energy_coefficients",
        staticmethod(lambda *_: {3: energy, 20: energy}),
    )
    case_config.feed_minimum_list[0] = case_config.feed_maximum_list[0] = 5.0  # RDP-limited, 375.2 g/day.
    if failed_constraint == "minimum_protein":
        case_config.animal_requirements.metabolizable_protein = 376.0
    elif failed_constraint == "maximum_protein":
        case_config.initial_protein_requirement = 249.0  # 373.5 g/day, despite zero current requirement.
    cases = LinearRationOptimizer().solve_nrc_cases(case_config, {3: 5.0, 20: 5.0})
    assert len(cases) == 6
    assert all(result.status is LinearRationStatus.INFEASIBLE for result in cases.values())
    print(f"{failed_constraint}: 0 feasible, 6 infeasible")


def test_solve_nrc_cases_uses_reference_coefficients(protein_config: RationConfig) -> None:
    # Zero energy minima and a generous protein cap isolate the microbial regime.
    protein_config.animal_requirements.calcium = 0.0
    protein_config.animal_requirements.phosphorus = 0.0
    protein_config.animal_requirements.process_based_phosphorus = 0.0
    for feed in protein_config.feeds_used:
        feed.calcium = 0.0
        feed.phosphorus = 0.0
    cases = LinearRationOptimizer().solve_nrc_cases(protein_config, {20: 13.2, 3: 9.1})
    for (_, limiter), result in cases.items():
        expected = LinearRationStatus.OPTIMAL if limiter == "rdp" else LinearRationStatus.INFEASIBLE
        assert result.status is expected
    print("Real reference coefficients: 3 feasible, 3 infeasible")


@pytest.fixture
def validation_config(protein_config: RationConfig) -> RationConfig:
    requirements = protein_config.animal_requirements
    requirements.maintenance_energy = 1.0
    requirements.activity_energy = 1.0
    requirements.growth_energy = 1.0
    requirements.lactation_energy = 1.0
    requirements.pregnancy_energy = 1.0
    requirements.metabolizable_protein = 400.0
    for feed in protein_config.feeds_used:
        feed.calcium = 0.8
        feed.phosphorus = 0.4
    for i, feed in enumerate(protein_config.feeds_used):
        protein_config.price_list[i] = 2.0 if feed.rufas_id == 20 else 1.0
    return protein_config


def test_validates_original_nrc_residuals_in_feed_order(validation_config: RationConfig) -> None:
    candidate = {3: 3.0, 20: 7.0}
    validation = LinearRationOptimizer.validate_nrc_candidate(validation_config, candidate)
    assert validation.status is NRCValidationStatus.APPROVED
    assert validation.rounded is not None
    assert validation.rounded_quantities == {20: 7.0, 3: 3.0, 40: 0.0, 8: 0.0, 11: 0.0}

    original = RationOptimizer()
    original.set_constraints(validation_config)
    vector = np.array([7.0, 3.0, 0.0, 0.0, 0.0])
    expected = {entry["fun"].__name__: entry["fun"](vector, validation_config) for entry in original.cow_constraints}
    assert len(expected) == 14
    assert validation.unrounded.residuals == pytest.approx(expected)
    assert validation.rounded.residuals == pytest.approx(expected)
    print(f"Approved NRC residuals: {expected}")


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("maintenance_energy", 100.0, "NE_maintenance_and_activity_constraint"),
        ("metabolizable_protein", 2000.0, "protein_constraint_lower"),
        ("initial_protein_requirement", 100.0, "protein_constraint_upper"),
    ],
)
def test_rejects_nrc_nutrient_violations(
    validation_config: RationConfig, field: str, value: float, constraint: str
) -> None:
    target = validation_config if field == "initial_protein_requirement" else validation_config.animal_requirements
    setattr(target, field, value)
    validation = LinearRationOptimizer.validate_nrc_candidate(validation_config, {3: 3.0, 20: 7.0})
    assert validation.status is NRCValidationStatus.REJECTED
    assert len(validation.unrounded.residuals) == 14
    assert constraint in validation.unrounded.violations
    assert validation.unrounded.residuals[constraint] < 0
    print(f"Rejected on {constraint}: {validation.unrounded.residuals[constraint]:.9f}")


@pytest.mark.parametrize("invalid", [float("nan"), float("inf")])
def test_rejects_nonfinite_nrc_residues(
    validation_config: RationConfig, monkeypatch: pytest.MonkeyPatch, invalid: float
) -> None:
    def calcium_constraint(*_: object) -> float:
        return invalid

    monkeypatch.setattr(RationOptimizer, "calcium_constraint", staticmethod(calcium_constraint))
    validation = LinearRationOptimizer.validate_nrc_candidate(validation_config, {3: 3.0, 20: 7.0})
    assert validation.status is NRCValidationStatus.REJECTED
    assert len(validation.unrounded.residuals) == 14
    assert validation.unrounded.violations["calcium_constraint"] == "Residual is not finite."


@pytest.mark.parametrize(
    ("candidate", "violation"),
    [
        ({}, "dry_matter_intake"),
        ({20: float("inf"), 3: 3.0}, "ingredient_20"),
        ({20: -0.01, 3: 3.0}, "ingredient_20"),
        ({20: 31.0, 3: 3.0}, "ingredient_20"),
        ({20: 7.0, 3: 3.0, 999: 1.0}, "unknown_ingredients"),
    ],
)
def test_rejects_invalid_candidate_amounts(
    validation_config: RationConfig, candidate: dict[int, float], violation: str
) -> None:
    validation = LinearRationOptimizer.validate_nrc_candidate(validation_config, candidate)
    assert validation.status is NRCValidationStatus.REJECTED
    assert violation in validation.unrounded.violations


def test_checks_rounded_diet_against_original_nrc(validation_config: RationConfig) -> None:
    validation_config.animal_requirements.dry_matter = 9.0000004
    validation_config.dmi_constraint_fraction = 0.0
    validation = LinearRationOptimizer.validate_nrc_candidate(validation_config, {20: 6.0000004, 3: 3.0})
    assert validation.status is NRCValidationStatus.REJECTED
    assert validation.unrounded.violations == {}
    assert validation.rounded_quantities is not None
    assert validation.rounded_quantities[20] == 6.0
    assert validation.rounded is not None
    residual = validation.rounded.residuals["DMI_constraint_lower"]
    assert residual == pytest.approx(-4e-7)
    assert "DMI_constraint_lower" in validation.rounded.violations
    print(f"Rounded DMI lower residual: {residual:.9g} kg/cow/day")


@pytest.mark.parametrize("approve", [True, False])
def test_validates_all_lp_optima_before_selecting(
    validation_config: RationConfig, monkeypatch: pytest.MonkeyPatch, approve: bool
) -> None:
    cases = {
        ("growth", "tdn"): LinearRationResult(LinearRationStatus.OPTIMAL, {20: 3.0, 3: 6.0}, 12.0),
        ("lactation", "rdp"): LinearRationResult(LinearRationStatus.OPTIMAL, {20: 7.0, 3: 3.0}, 17.0),
        ("maintenance", "rdp"): LinearRationResult(LinearRationStatus.OPTIMAL, {20: 6.0, 3: 4.0}, 16.0),
        ("growth", "rdp"): LinearRationResult(LinearRationStatus.INFEASIBLE),
        ("lactation", "tdn"): LinearRationResult(LinearRationStatus.SOLVER_ERROR, message="CBC error"),
        ("maintenance", "tdn"): LinearRationResult(LinearRationStatus.INFEASIBLE),
    }
    monkeypatch.setattr(LinearRationOptimizer, "solve_nrc_cases", lambda *_: cases)
    if not approve:
        validation_config.animal_requirements.metabolizable_protein = 2000.0
    result = LinearRationOptimizer().solve_and_validate_nrc_cases(validation_config, {20: 7.0, 3: 3.0})

    cheapest = ("growth", "tdn")
    assert result.cases == cases
    assert len(result.validations) == 3
    assert result.validations[cheapest].status is NRCValidationStatus.REJECTED
    if approve:
        assert result.validations[("lactation", "rdp")].status is NRCValidationStatus.APPROVED
        assert result.selected_case == ("maintenance", "rdp")
        assert result.selected_cost == 16.0
        assert result.validations[result.selected_case].status is NRCValidationStatus.APPROVED
        print(f"Selection: rejected cheapest LP case, selected {result.selected_case}, cost={result.selected_cost}")
    else:
        assert result.selected_case is None
        assert result.selected_cost is None
        assert "Rejected LP optima: 3. Infeasible LP cases: 2. Solver errors: 1." in result.message
        assert all("protein_constraint_lower" in check.unrounded.violations for check in result.validations.values())
        print(result.message)


def test_solves_and_validates_with_real_cbc_and_nrc(validation_config: RationConfig) -> None:
    reference = {20: 7.0, 3: 3.0}
    bounds = [reference.get(feed.rufas_id, 0.0) for feed in validation_config.feeds_used]
    validation_config.feed_minimum_list = bounds
    validation_config.feed_maximum_list = bounds.copy()
    result = LinearRationOptimizer().solve_and_validate_nrc_cases(validation_config, reference)

    assert len(result.cases) == 6
    assert len(result.validations) == 3
    assert all(check.status is NRCValidationStatus.APPROVED for check in result.validations.values())
    assert result.selected_case in result.validations
    assert result.selected_cost == pytest.approx(17.0)
    print(
        f"CBC plus NRC: {len(result.validations)} approved, selected {result.selected_case}, cost={result.selected_cost}"
    )


@pytest.mark.parametrize(
    ("raw_forage", "minimum_dmi", "maximum_dmi", "trigger", "final_forage", "expected_delta"),
    [
        (7.0000006, 10.0, 10.0000006, "DMI_constraint_upper", 7.0, -2e-6),
        (7.0000004, 10.0000004, 24.0, "DMI_constraint_lower", 7.000001, 2e-6),
    ],
)
def test_repairs_only_rounding_violations(
    validation_config: RationConfig,
    raw_forage: float,
    minimum_dmi: float,
    maximum_dmi: float,
    trigger: str,
    final_forage: float,
    expected_delta: float,
) -> None:
    validation_config.dmi_constraint_fraction = 0.0
    validation_config.animal_requirements.dry_matter = minimum_dmi
    validation_config.initial_dry_matter_requirement = maximum_dmi
    optimizer = LinearRationOptimizer()
    result = optimizer.validate_nrc_candidate(validation_config, {20: raw_forage, 3: 3.0}, repair_rounding=True)

    assert result.unrounded.violations == {}
    assert result.rounded is not None and trigger in result.rounded.violations
    assert result.rounded_quantities is not None and result.rounded_quantities[20] == round(raw_forage, 6)
    assert result.status is NRCValidationStatus.APPROVED
    assert result.repair is not None
    assert result.repair.triggers == (trigger,)
    assert result.repair.attempts == 1
    assert result.repair.cost_delta == pytest.approx(expected_delta, abs=1e-12)
    assert result.repair.validation is not None
    assert len(result.repair.validation.residuals) == 14
    assert result.repair.validation.violations == {}
    assert result.final_quantities is not None
    assert result.final_quantities[20] == final_forage
    checked_again = optimizer.validate_nrc_candidate(validation_config, result.final_quantities, repair_rounding=True)
    assert checked_again.status is NRCValidationStatus.APPROVED
    assert checked_again.final_quantities == result.final_quantities
    assert checked_again.repair is None


def test_repair_tries_another_ingredient_when_calcium_is_active(validation_config: RationConfig) -> None:
    validation_config.dmi_constraint_fraction = 0.0
    validation_config.initial_dry_matter_requirement = 10.0000006
    validation_config.feeds_used[0].calcium = 8.0
    validation_config.animal_requirements.calcium = 24 * 7.0000006 + 4.8 * 3.0
    optimizer = LinearRationOptimizer()

    failed_neighbor = optimizer.validate_nrc_candidate(validation_config, {20: 7.0, 3: 3.0})
    assert failed_neighbor.unrounded.violations.keys() == {"calcium_constraint"}

    repaired = optimizer.validate_nrc_candidate(validation_config, {20: 7.0000006, 3: 3.0}, repair_rounding=True)
    assert repaired.status is NRCValidationStatus.APPROVED
    assert repaired.repair is not None and repaired.repair.attempts > 1
    assert repaired.final_quantities is not None
    assert repaired.final_quantities[20] == 7.000001
    assert repaired.final_quantities[3] == 2.999999
    assert repaired.repair.validation is not None
    assert len(repaired.repair.validation.residuals) == 14


def test_rejects_when_no_single_increment_can_fix_dmi(validation_config: RationConfig) -> None:
    validation_config.dmi_constraint_fraction = 0.0
    validation_config.animal_requirements.dry_matter = 10.0000004
    validation_config.initial_dry_matter_requirement = 10.0000004
    result = LinearRationOptimizer.validate_nrc_candidate(
        validation_config, {20: 7.0000004, 3: 3.0}, repair_rounding=True
    )
    assert result.unrounded.violations == {}
    assert result.rounded is not None and "DMI_constraint_lower" in result.rounded.violations
    assert result.status is NRCValidationStatus.REJECTED
    assert result.repair is not None and 0 < result.repair.attempts <= 32
    assert result.final_quantities is None


def test_repair_cannot_cross_ingredient_bounds(validation_config: RationConfig) -> None:
    validation_config.dmi_constraint_fraction = 0.0
    validation_config.initial_dry_matter_requirement = 10.0000006
    amounts = [7.0000006, 3.0, 0.0, 0.0, 0.0]
    validation_config.feed_minimum_list = amounts
    validation_config.feed_maximum_list = [7.000001, 3.0, 0.0, 0.0, 0.0]
    result = LinearRationOptimizer.validate_nrc_candidate(
        validation_config, {20: amounts[0], 3: amounts[1]}, repair_rounding=True
    )
    assert result.unrounded.violations == {}
    assert result.status is NRCValidationStatus.REJECTED
    assert result.repair is not None and result.repair.attempts == 0


def test_does_not_repair_a_raw_nrc_violation(validation_config: RationConfig) -> None:
    validation_config.dmi_constraint_fraction = 0.0
    validation_config.initial_dry_matter_requirement = 10.0
    result = LinearRationOptimizer.validate_nrc_candidate(
        validation_config, {20: 7.0000006, 3: 3.0}, repair_rounding=True
    )
    assert "DMI_constraint_upper" in result.unrounded.violations
    assert result.status is NRCValidationStatus.REJECTED
    assert result.repair is None
