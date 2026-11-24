"""Configuration and eligibility for the opt-in ration formulation backend."""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path, PureWindowsPath

from RUFAS.biophysical.animal.data_types.animal_combination import AnimalCombination
from RUFAS.data_structures.feed_storage_to_animal_connection import NutrientStandard


@dataclass(frozen=True)
class RationBackendConfig:
    backend: str = "slsqp"
    strategy: str = "adaptive_gap"
    gap_target: float = 0.05
    max_references: int = 5
    nutritional_solver: str = "cbc"
    reference_solver: str = "cbc"
    bound_solver: str = "cbc"
    midwest_reference_path: Path | None = None

    @classmethod
    def from_mapping(cls, ration: Mapping[str, object]) -> "RationBackendConfig":
        backend = ration.get("optimizer_backend", "slsqp")
        nutritional_solver = ration.get("linear_nutritional_solver", "cbc")
        reference_solver = ration.get("linear_reference_solver", "cbc")
        bound_solver = ration.get("linear_bound_solver", "cbc")
        recipe_path = ration.get("linear_midwest_reference_path", "")
        strategy = ration.get("linear_strategy", "adaptive_gap")
        gap = ration.get("linear_gap_target", 0.05)
        count = ration.get("linear_max_references", 5)
        if not isinstance(backend, str) or backend not in ("slsqp", "pulp"):
            raise ValueError("animal.ration.optimizer_backend must be slsqp or pulp.")
        if not isinstance(strategy, str) or strategy not in ("single", "full", "adaptive_gap"):
            raise ValueError("animal.ration.linear_strategy must be single, full or adaptive_gap.")
        if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not isfinite(gap) or not 0 <= gap < 1:
            raise ValueError("animal.ration.linear_gap_target must be a finite fraction in [0, 1).")
        if (
            isinstance(count, bool)
            or not isinstance(count, (int, float))
            or not isfinite(count)
            or count < 1
            or int(count) != count
        ):
            raise ValueError("animal.ration.linear_max_references must be a positive integer.")
        if not isinstance(nutritional_solver, str) or nutritional_solver not in ("cbc", "highs"):
            raise ValueError("animal.ration.linear_nutritional_solver must be cbc or highs.")
        if not isinstance(reference_solver, str) or reference_solver not in ("cbc", "highs"):
            raise ValueError("animal.ration.linear_reference_solver must be cbc or highs.")
        if not isinstance(bound_solver, str) or bound_solver not in ("cbc", "highs"):
            raise ValueError("animal.ration.linear_bound_solver must be cbc or highs.")
        if (
            not isinstance(recipe_path, str)
            or Path(recipe_path).is_absolute()
            or PureWindowsPath(recipe_path).anchor
            or (recipe_path and not recipe_path.strip())
        ):
            raise ValueError("animal.ration.linear_midwest_reference_path must be a relative feed JSON path or empty.")
        return cls(
            backend,
            strategy,
            float(gap),
            int(count),
            nutritional_solver,
            reference_solver,
            bound_solver,
            Path(recipe_path) if recipe_path else None,
        )

    def select(
        self, standard: NutrientStandard, group: AnimalCombination, is_ration_defined_by_user: bool
    ) -> tuple[str, str]:
        if self.backend == "slsqp":
            return "slsqp", "configured_slsqp"
        if is_ration_defined_by_user:
            return "slsqp", "user_defined_ration"
        if standard is not NutrientStandard.NRC:
            return "slsqp", "nutrient_standard_not_supported"
        if group is not AnimalCombination.LAC_COW:
            return "slsqp", "animal_group_not_supported"
        return "pulp", "automatic_nrc_lactating_cows"
