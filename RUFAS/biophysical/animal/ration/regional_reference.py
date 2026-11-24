"""Read and project an optional regional NRC reference diet."""

import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

from RUFAS.biophysical.animal.data_types.animal_combination import AnimalCombination
from RUFAS.biophysical.animal.ration.ration_optimizer import RationConfig


@dataclass(frozen=True)
class MidwestRecipe:
    path: Path
    shares: tuple[tuple[int, float], ...] = ()
    issue: str | None = None

    @classmethod
    def load(cls, path: Path) -> "MidwestRecipe":
        """Load the explicit lactation percentages from a RuFaS feed JSON."""
        try:
            with path.open(encoding="utf-8-sig") as stream:
                document = json.load(stream)
            rations = document["rations"]
            matches = [ration for ration in rations if ration["animal_combination"] == AnimalCombination.LAC_COW.value]
            if len(matches) != 1:
                return cls(path, issue="Expected exactly one lactating cow recipe.")
            shares = {}
            for item in matches[0]["feeds"]:
                feed_id, share = item["feed_type"], item.get("ration_percentage")
                if (
                    type(feed_id) is not int
                    or feed_id in shares
                    or type(share) not in (int, float)
                    or not isfinite(share)
                    or not 0 <= share <= 100
                ):
                    return cls(path, issue="Recipe needs unique feed IDs and finite percentages in [0, 100].")
                shares[feed_id] = share
            if not any(shares.values()):
                return cls(path, issue="Recipe has no positive percentage.")
            return cls(path, tuple(shares.items()))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as error:
            return cls(path, issue=f"Cannot read Midwest feed recipe: {error}")

    def diagnostics(self) -> dict[str, Any]:
        return {
            "origin": "midwest",
            "recipe_path": self.path.as_posix(),
            "animal_group": AnimalCombination.LAC_COW.value,
            "removed_ingredients": {},
            "retained_original_percent": None,
            "normalized_percentages": {},
            "issue": self.issue,
            "duplicate_of": None,
            "explored": False,
        }

    def project(self, config: RationConfig) -> tuple[dict[int, float], dict[str, Any]]:
        """Keep only menu ingredients and scale their shares to the initial DMI target."""
        diagnostics = self.diagnostics()
        if self.issue is not None:
            return {}, diagnostics

        menu = {feed.rufas_id for feed in config.feeds_used}
        removed = {key: share for key, share in self.shares if share > 0 and key not in menu}
        retained = {key: share for key, share in self.shares if share > 0 and key in menu}
        kept = sum(retained.values())
        diagnostics["removed_ingredients"] = removed
        diagnostics["retained_original_percent"] = 100 * kept / sum(share for _, share in self.shares)
        if not retained:
            diagnostics["issue"] = "No positive recipe ingredients are available in the NRC formulation."
            return {}, diagnostics

        dmi = config.initial_dry_matter_requirement
        diagnostics["normalized_percentages"] = {key: 100 * share / kept for key, share in retained.items()}
        return {key: share * dmi / kept for key, share in retained.items()}, diagnostics
