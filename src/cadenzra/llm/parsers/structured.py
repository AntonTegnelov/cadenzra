"""Normalizing the structured layers' tool calls inward.

This is where the surface's bar/beat coordinates become internal `Fraction`
offsets, and where a meter string like "7/8 (2+2+3)" becomes a `MeterSpec`. The
surface is allowed to be forgiving — a model may write "7/8" for a meter the
piece defines with a grouping — because parsing normalizes and the deterministic
validators re-derive everything decidable from the notation itself (docs/03).

What is *not* forgiving: anything missing or unrecognizable raises
`LLMOutputError` rather than being defaulted (docs/06).
"""

from fractions import Fraction
from typing import Any

from pydantic import ValidationError

from cadenzra.common.errors import LLMOutputError
from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
from cadenzra.model.interpretation import InterpretationParams
from cadenzra.model.motif import Motif, MotifLibrary
from cadenzra.model.primitives.ids import SectionId
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.primitives.time import offset_of, to_fraction
from cadenzra.model.review import ReviewVerdict
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import (
    DynamicsPlan,
    DynTarget,
    GroupRef,
    MaterialBrief,
    MaterialEntry,
    SectionPlan,
    StructurePlan,
    VoiceRef,
)
from cadenzra.model.style import RhythmicCell, StyleFragment, StylePack


def parse_style_pack(payload: dict[str, Any], spec: PieceSpec) -> StylePack:
    """Build a `StylePack` from a `describe_style` call."""
    cells = []
    for raw in _list_of(payload, "rhythmic_cells"):
        meter = _match_meter(_text(raw, "meter", where="a rhythmic cell"), spec)
        cells.append(
            RhythmicCell(
                meter=meter,
                lily=_text(raw, "lily", where="a rhythmic cell"),
                description=str(raw.get("description", "")),
            )
        )

    policy = str(payload.get("parallel_fifths_policy", "forbid"))
    if policy not in ("forbid", "allow", "encourage"):
        raise LLMOutputError(
            f"the style pack asked for a parallels policy of {policy!r}; it must be "
            "forbid, allow or encourage"
        )

    return StylePack(
        idioms=[str(item) for item in _list_of(payload, "idioms", required=False)],
        rhythmic_cells=cells,
        harmony_guidance=str(payload.get("harmony_guidance", "")),
        parallel_fifths_policy=policy,  # type: ignore[arg-type]
        dissonance_policy=str(payload.get("dissonance_policy", "")),
        dynamics_arc=str(payload.get("dynamics_arc", "")),
        interpretation_defaults=InterpretationParams(),
        few_shot_fragments=[
            _parse_fragment(raw, spec)
            for raw in _list_of(payload, "few_shot_fragments", required=False)
        ],
    )


def _parse_fragment(raw: Any, spec: PieceSpec) -> StyleFragment:
    if not isinstance(raw, dict):
        raise LLMOutputError(
            f"a style fragment came back as {type(raw).__name__}; each fragment "
            "is an object with a meter and its lily text"
        )
    return StyleFragment(
        meter=_match_meter(_text(raw, "meter", where="a style fragment"), spec),
        lily=_text(raw, "lily", where="a style fragment"),
    )


def parse_structure_plan(payload: dict[str, Any], spec: PieceSpec) -> StructurePlan:
    """Build a `StructurePlan` from a `plan_structure` call."""
    sections = [
        _parse_section(raw, spec) for raw in _list_of(payload, "sections")
    ]
    briefs = [
        MaterialBrief(
            motif_id=_text(raw, "motif_id", where="a material brief"),
            role=_text(raw, "role", where="a material brief"),
            description=str(raw.get("description", "")),
            carrying_voices=[str(v) for v in raw.get("carrying_voices", []) or []],
        )
        for raw in _list_of(payload, "materials_needed", required=False)
    ]

    try:
        return StructurePlan(
            sections=sections,
            materials_needed=briefs,
            form_summary=str(payload.get("form_summary", "")),
        )
    except ValidationError as error:
        raise LLMOutputError(f"the plan is malformed: {_reasons(error)}") from error


def _parse_section(raw: dict[str, Any], spec: PieceSpec) -> SectionPlan:
    section_id = _text(raw, "section_id", where="a section")
    active: list[VoiceRef] = []
    known_voices = set(spec.voices_by_id)
    for name in raw.get("active_voices", []) or []:
        text = str(name)
        active.append(text if text in known_voices else GroupRef(group=text))

    targets = [
        DynTarget(bar=int(item["bar"]), level=str(item["level"]))
        for item in raw.get("dynamics_targets", []) or []
        if "bar" in item and "level" in item
    ]

    try:
        return SectionPlan(
            section_id=section_id,
            bars=int(raw["bars"]),
            meter=_match_meter(_text(raw, "meter", where=f"section {section_id}"), spec),
            key=str(raw.get("key", "")),
            tempo_bpm=int(raw.get("tempo_bpm") or spec.tempo_bpm or 100),
            texture=str(raw.get("texture", "")),
            dynamics=DynamicsPlan(
                start=str(raw.get("dynamics_start", "mf")),
                targets=sorted(targets, key=lambda target: target.bar),
            ),
            active_voices=active,
            material=[_parse_entry(item, section_id) for item in raw.get("material", []) or []],
            intent=str(raw.get("intent", "")),
        )
    except ValidationError as error:
        # The model reads this. `str(error)` is a pydantic dump — input_value
        # reprs, doc links — burying the one sentence our validator wrote.
        raise LLMOutputError(
            f"section {section_id!r} is malformed: {_reasons(error)}"
        ) from error
    except (KeyError, TypeError, ValueError) as error:
        raise LLMOutputError(f"section {section_id!r} is malformed: {error}") from error


def _reasons(error: ValidationError) -> str:
    """A ValidationError's messages alone, stripped of pydantic's framing."""
    return "; ".join(
        str(item["msg"]).removeprefix("Value error, ") for item in error.errors()
    )


def _parse_entry(raw: dict[str, Any], section_id: SectionId) -> MaterialEntry:
    try:
        return MaterialEntry(
            motif_id=str(raw["motif_id"]),
            voice_id=str(raw["voice_id"]),
            bar=int(raw["bar"]),
            relation=str(raw["relation"]),
        )
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise LLMOutputError(
            f"a material entry in section {section_id!r} is malformed: {error}"
        ) from error


def parse_motif_library(payload: dict[str, Any]) -> MotifLibrary:
    """Build a `MotifLibrary` from a `write_motifs` call."""
    motifs = {}
    for raw in _list_of(payload, "motifs"):
        motif_id = _text(raw, "motif_id", where="a motif")
        motifs[motif_id] = Motif(
            motif_id=motif_id,
            role=_text(raw, "role", where=f"motif {motif_id}"),
            lily_music=_text(raw, "lily_music", where=f"motif {motif_id}").strip(),
            description=str(raw.get("description", "")),
        )
    return MotifLibrary(motifs=motifs)


def parse_harmonic_skeleton(
    payload: dict[str, Any], section: SectionPlan
) -> HarmonicSkeleton:
    """Build a `HarmonicSkeleton`, converting bar/beat to internal offsets.

    This is the surface-to-internal conversion the whole seam exists for: the
    model wrote "bar 4, beat 2.5, for 1.5 beats", and everything downstream
    sees exact `Fraction` offsets (docs/03).
    """
    events = []
    unit = section.meter.unit_length
    for raw in _list_of(payload, "events"):
        try:
            bar = int(raw["bar"])
            beat = to_fraction(raw.get("beat", 1))
            beats = to_fraction(raw["duration_beats"])
        except (KeyError, TypeError, ValueError) as error:
            raise LLMOutputError(
                f"a chord in section {section.section_id!r} is malformed: {raw!r}"
            ) from error

        chord = _text(raw, "chord", where=f"section {section.section_id}")
        try:
            offset = offset_of(bar, beat, section.meter)
        except ValueError as error:
            raise LLMOutputError(
                f"the chord {chord!r} in section {section.section_id!r} is placed at "
                f"bar {bar}, beat {beat}, which is not a position: {error}"
            ) from error

        duration = beats * unit
        if duration <= 0:
            raise LLMOutputError(
                f"the chord {chord!r} in section {section.section_id!r} lasts "
                f"{beats} beats"
            )
        events.append(HarmonicEvent(offset=offset, duration=duration, chord=chord))

    events.sort(key=lambda event: event.offset)
    return HarmonicSkeleton(section_id=section.section_id, events=events)


def parse_review_verdict(payload: dict[str, Any]) -> ReviewVerdict:
    if "acceptable" not in payload:
        raise LLMOutputError("the review came back without a verdict")
    return ReviewVerdict(
        acceptable=bool(payload["acceptable"]),
        reasons=[str(item) for item in payload.get("reasons", []) or []],
        suggestions=[str(item) for item in payload.get("suggestions", []) or []],
    )


def _match_meter(text: str, spec: PieceSpec) -> MeterSpec:
    """Match a meter string against the piece's palette.

    Forgiving on purpose: "7/8" matches the palette's "7/8 (2+2+3)", because
    the grouping is the piece's decision and the model is only naming which
    allowed meter it means.
    """
    wanted = text.strip()
    for meter in spec.meters_allowed:
        if wanted in (meter.surface_string(), meter.surface_string_bare()):
            return meter
    palette = ", ".join(meter.surface_string() for meter in spec.meters_allowed)
    raise LLMOutputError(
        f"{text!r} is not one of this piece's meters ({palette})"
    )


def _list_of(payload: dict[str, Any], key: str, *, required: bool = True) -> list[Any]:
    value = payload.get(key)
    if value is None:
        if required:
            raise LLMOutputError(f"the response has no {key}")
        return []
    if not isinstance(value, list):
        raise LLMOutputError(f"{key} came back as {type(value).__name__}, not a list")
    return value


def _text(raw: dict[str, Any], key: str, *, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LLMOutputError(f"{where} is missing its {key}")
    return value.strip()


def bars_to_offset(bar: int, beat: float, meter: MeterSpec) -> Fraction:
    """Exposed for tests: the surface-to-internal position conversion."""
    return offset_of(bar, to_fraction(beat), meter)
