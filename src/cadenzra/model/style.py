"""`StylePack` — style as data, interpreted exactly once.

This is what keeps the pipeline genre-agnostic: "Tool-inspired" becomes
concrete, checkable material here, so the planner, the harmony generator, and
every voice generation read the same interpretation instead of each inventing
their own (docs/03, docs/04).
"""

from typing import Literal

from pydantic import BaseModel, Field

from cadenzra.model.interpretation import InterpretationParams
from cadenzra.model.primitives.meter import MeterSpec

type ParallelsPolicy = Literal["forbid", "allow", "encourage"]


class RhythmicCell(BaseModel, frozen=True):
    """A vetted one-bar rhythm generators may combine and vary.

    The odd-meter workhorse: free rhythmic invention in 7/8 is where beat-count
    errors are born, and varying a correct cell rarely breaks the bar
    (docs/04). Cells are compile-checked before a pack is accepted.
    """

    meter: MeterSpec
    lily: str
    description: str


class StylePack(BaseModel, frozen=True):
    """The concrete idioms, constraints, and material one style implies."""

    idioms: list[str] = Field(default_factory=list)
    rhythmic_cells: list[RhythmicCell] = Field(default_factory=list)
    harmony_guidance: str = ""
    # Read by validators: the same checker forbids parallels for a chorale and
    # waves them through for a rock texture, driven by this field alone.
    parallel_fifths_policy: ParallelsPolicy = "forbid"
    dissonance_policy: str = ""
    dynamics_arc: str = ""
    interpretation_defaults: InterpretationParams = Field(
        default_factory=InterpretationParams
    )
    few_shot_fragments: list[str] = Field(default_factory=list)

    def cells_for(self, meter: MeterSpec) -> list[RhythmicCell]:
        """The cells a generator may draw on for one section's meter."""
        return [cell for cell in self.rhythmic_cells if cell.meter == meter]
