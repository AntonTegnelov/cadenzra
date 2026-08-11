"""`StructurePlan` — the formal map every later layer is generated against.

A meter change is modeled as a section boundary. That is a deliberate
simplification: it makes "does every bar match its meter?" decidable per
section with one time signature in scope, at the cost of many short sections
when meter shifts rapidly (docs/03).
"""

from typing import Self

from pydantic import BaseModel, Field, model_validator

from cadenzra.model.primitives.ids import MotifId, SectionId, VoiceId
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.spec import PieceSpec


class DynTarget(BaseModel, frozen=True):
    """One waypoint of a dynamics arc: "by bar 9, reach ff"."""

    bar: int
    level: str


class DynamicsPlan(BaseModel, frozen=True):
    """A piecewise dynamic arc, structured rather than prose.

    It is dual-projected: voice generators realize it as printed dynamics, and
    the interpretation stage realizes it as continuous CC curves. Both come
    from this one plan, which is why it is not free text (docs/03).
    """

    start: str
    targets: list[DynTarget] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_targets_advance(self) -> Self:
        bars = [target.bar for target in self.targets]
        if bars != sorted(bars):
            raise ValueError(f"dynamics targets must be in bar order, got {bars}")
        return self


class GroupRef(BaseModel, frozen=True):
    """A reference to a voice *group* ("concertino", "ripieno") in a plan.

    A wrapper model rather than a bare string so that `active_voices` can hold
    both kinds of reference without the two being indistinguishable (docs/03).
    """

    group: str


type VoiceRef = VoiceId | GroupRef


class MaterialBrief(BaseModel, frozen=True):
    """What `generate_motifs` must produce, and for whom.

    `carrying_voices` is what lets `validate_motifs` range-check a subject
    under every relation before a single section is elaborated — a subject that
    fits the soprano can put the alto's fifth-below answer under its floor
    (docs/05).
    """

    motif_id: MotifId
    role: str
    description: str
    carrying_voices: list[VoiceId] = Field(default_factory=list)


class MaterialEntry(BaseModel, frozen=True):
    """A declared return of named material — what makes strict forms checkable.

    `bar` is a surface coordinate, parsed to an internal offset; `relation`
    names the transform ("exact", "P5 up", "tonal answer") that
    `validate_section` verifies against the compiled music (docs/05).
    """

    motif_id: MotifId
    voice_id: VoiceId
    bar: int
    relation: str


class SectionPlan(BaseModel, frozen=True):
    """One section: one meter, one key, one tempo, one intent."""

    section_id: SectionId
    bars: int
    meter: MeterSpec
    key: str
    tempo_bpm: int
    texture: str
    dynamics: DynamicsPlan
    active_voices: list[VoiceRef] = Field(default_factory=list)
    material: list[MaterialEntry] = Field(default_factory=list)
    intent: str = ""

    @model_validator(mode="after")
    def _check_section(self) -> Self:
        if self.bars < 1:
            raise ValueError(
                f"section {self.section_id!r} must have at least one bar, got {self.bars}"
            )
        if self.tempo_bpm < 1:
            raise ValueError(
                f"section {self.section_id!r} has non-positive tempo {self.tempo_bpm}"
            )
        for entry in self.material:
            if not 1 <= entry.bar <= self.bars:
                raise ValueError(
                    f"section {self.section_id!r} declares a {entry.motif_id!r} entry at "
                    f"bar {entry.bar}, outside its {self.bars} bars"
                )
        return self

    @property
    def voice_ids(self) -> list[VoiceId]:
        """Just the directly-named voices; see `resolved_voice_ids` for groups."""
        return [ref for ref in self.active_voices if isinstance(ref, str)]

    def resolved_voice_ids(self, spec: PieceSpec) -> set[VoiceId]:
        """Every voice active here, with group references expanded.

        The one definition of "who sings in this section" — the pipeline and
        the validators must agree on it, or a plan the validator rejects is one
        the pipeline would have played (and vice versa).
        """
        active = set(self.voice_ids)
        for ref in self.active_voices:
            if isinstance(ref, GroupRef):
                active |= {
                    voice.voice_id for voice in spec.voices if voice.group == ref.group
                }
        return active

    @property
    def group_names(self) -> list[str]:
        return [ref.group for ref in self.active_voices if isinstance(ref, GroupRef)]


class StructurePlan(BaseModel, frozen=True):
    """The whole formal map."""

    sections: list[SectionPlan]
    materials_needed: list[MaterialBrief] = Field(default_factory=list)
    form_summary: str = ""

    @model_validator(mode="after")
    def _check_plan(self) -> Self:
        if not self.sections:
            raise ValueError("a plan needs at least one section")
        ids = [section.section_id for section in self.sections]
        duplicates = {name for name in ids if ids.count(name) > 1}
        if duplicates:
            raise ValueError(f"duplicate section ids: {sorted(duplicates)}")
        return self

    @property
    def sections_by_id(self) -> dict[SectionId, SectionPlan]:
        return {section.section_id: section for section in self.sections}

    def meter_declaring(self, motif_id: MotifId) -> MeterSpec | None:
        """The meter of the first section that declares this motif.

        This is the meter the motif is written in *and* validated against —
        the prompt and the validator must agree on it, or the model is given
        an instruction it can never satisfy (a hook prompted in 7/8 and
        checked in 4/4 burned eight straight rejections, identically across
        model tiers).
        """
        for section in self.sections:
            if any(entry.motif_id == motif_id for entry in section.material):
                return section.meter
        return None

    @property
    def declares_materials(self) -> bool:
        """Whether `generate_motifs` runs at all — the graph's conditional skip."""
        return bool(self.materials_needed)
