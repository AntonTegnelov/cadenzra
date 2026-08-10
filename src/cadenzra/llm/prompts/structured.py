"""Prompts for the structured layers.

High-level formal planning is the layer LLMs are naturally best at — compact,
abstract, closer to prose than to notation — so these prompts are mostly a
briefing and a request (docs/04). The same two surface rules still apply:
speak musician, and show only what the piece activates.

Form-specific knowledge arrives as *data*. There is no fugue code path and no
concerto code path; the style pack and spec drive the planner, and a form the
system has never seen works the same way (docs/04).
"""

from cadenzra.llm.prompts.surface import (
    chord_chart,
    dynamics_text,
    range_text,
    rehearsal_notes,
    rhythmic_cells_text,
    section_text,
)
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.motif import Motif
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import MaterialBrief, SectionPlan, StructurePlan
from cadenzra.model.style import StylePack

STYLE_SYSTEM = """\
You are a musician translating a style brief into concrete working material \
for a composer: the modes and habits of the style, rhythmic patterns that \
sound like it, and how strictly it treats voice leading.

Answer by calling the `describe_style` tool. Never reply with prose."""

PLAN_SYSTEM = """\
You are a composer laying out the form of a piece before writing any notes. \
You think in sections that relate to each other, with a real arc, and you \
give each section a clear musical purpose.

Answer by calling the `plan_structure` tool. Never reply with prose."""

MOTIF_SYSTEM = """\
You are a composer writing the recurring material a piece will be built from: \
memorable, singable, and distinctive enough to recognize when it returns.

Answer by calling the `write_motifs` tool. Never reply with prose."""

HARMONY_SYSTEM = """\
You are a composer writing the harmonic ground for one section: the chords, \
where they change, and how they carry the section's shape.

Answer by calling the `write_harmony` tool. Never reply with prose."""

REVIEW_SYSTEM = """\
You are an experienced musician reviewing one specific aspect of a work in \
progress. Answer the question you are asked and nothing else. Be concrete: \
name bars, sections and voices.

Answer by calling the `give_verdict` tool. Never reply with prose."""


def build_style_prompt(spec: PieceSpec) -> str:
    """One call that interprets the style brief, once, for the whole run.

    Without this node, "Tool-inspired" would be re-interpreted independently by
    the planner, the harmony generator and every voice generation, with drift
    between them guaranteed (docs/04).
    """
    meters = ", ".join(meter.surface_string() for meter in spec.meters_allowed)
    voices = ", ".join(
        f"{voice.voice_id} ({range_text(voice)})" for voice in spec.voices
    )
    blocks = [
        f'The piece is called "{spec.title}". The brief is:\n\n{spec.style_prompt}',
        f"It is written for: {voices}.",
        f"It may use these meters: {meters}.",
        (
            "Give at least two one-bar rhythmic cells for *each* of those meters. "
            "Write them on the note c with an explicit duration on every note, and "
            "make the cells reflect how the meter is actually felt — for a 7/8 "
            "grouped 2+2+3, the cells should land that way."
        ),
        (
            "The cells matter more than anything else here: the composer will build "
            "rhythm by repeating and varying them rather than inventing it, which is "
            "what keeps odd meters correct."
        ),
    ]
    if spec.key_center:
        blocks.append(f"The tonal centre is {spec.key_center}.")
    return "\n\n".join(blocks)


def build_plan_prompt(
    spec: PieceSpec, style: StylePack, feedback: list[FeedbackItem] | None = None
) -> str:
    """The formal map. Bar counts are the planner's arithmetic to get right."""
    meters = ", ".join(meter.surface_string() for meter in spec.meters_allowed)
    voices = ", ".join(voice.voice_id for voice in spec.voices)
    blocks = [
        f'Plan the form of "{spec.title}", about {spec.target_minutes:g} minutes long.',
        f"Voices: {voices}.",
        f"Meters available: {meters}. A section has one meter throughout; a meter "
        "change means a new section.",
    ]
    if spec.groups:
        blocks.append(
            "Voices are grouped as: "
            + ", ".join(
                f"{group} ({', '.join(v.voice_id for v in spec.voices if v.group == group)})"
                for group in sorted(spec.groups)
            )
            + ". A section may address a group instead of listing its voices."
        )
    if style.idioms:
        blocks.append("Style:\n" + "\n".join(f"  - {idiom}" for idiom in style.idioms))
    if style.dynamics_arc:
        blocks.append(f"Dynamic shape of the whole piece: {style.dynamics_arc}")
    if spec.key_center:
        blocks.append(f"Tonal centre: {spec.key_center}.")

    tempo = spec.tempo_bpm or 100
    blocks.append(
        "Choose bar counts so the sections add up to about the requested duration. "
        f"At {tempo} bpm a bar of 4/4 lasts about "
        f"{60 * 4 / tempo:.1f} seconds, and a bar of 7/8 about "
        f"{60 * 3.5 / tempo:.1f}."
    )
    blocks.append(
        "If — and only if — the form genuinely reuses material (a fugue subject, a "
        "riff, a returning theme), list what is needed under materials_needed and "
        "place each return in the sections that carry it. For a through-composed "
        "piece, leave both empty."
    )
    notes = rehearsal_notes(feedback or [], what="plan")
    if notes:
        blocks.append(notes)
    return "\n\n".join(blocks)


def build_motif_prompt(
    briefs: list[MaterialBrief],
    spec: PieceSpec,
    style: StylePack,
    plan: StructurePlan,
    feedback: list[FeedbackItem] | None = None,
) -> str:
    """Write the material every later entry derives from."""
    first = _carrying_section(briefs, plan)

    def _meter_of(brief: MaterialBrief) -> MeterSpec:
        # The same lookup the validator uses (verification/motifs.py): each
        # motif is checked in its first declaring section's meter, so that is
        # the meter it must be told to write in — one "Write in 7/8" for a
        # batch whose hook enters in 4/4 is an instruction no model can obey.
        return plan.meter_declaring(brief.motif_id) or spec.meters_allowed[0]

    blocks = [
        f"Write the recurring material for this piece: {len(briefs)} "
        + ("theme." if len(briefs) == 1 else "themes."),
        "\n".join(
            f"  - {brief.motif_id} ({brief.role}): {brief.description}"
            + (
                f" Carried by: {', '.join(brief.carrying_voices)}."
                if brief.carrying_voices
                else ""
            )
            + f" Write it in {_meter_of(brief).surface_string()}, every bar "
            "filling that meter exactly."
            for brief in briefs
        ),
        # Without this, a brief carried by three voices comes back as three
        # per-voice variants — `theme_lead`, `theme_keys`, `theme_harmony` —
        # and the one theme the plan asked for does not exist.
        "Write exactly one line of music for each of those, under exactly the "
        "id it is listed with. The voices named as carrying it are the voices "
        "it will later appear in, which tells you the range it has to fit — "
        "not how many versions to write. One id, one line, no variants.",
    ]

    carriers = {
        voice_id for brief in briefs for voice_id in brief.carrying_voices
    } or set(spec.voices_by_id)
    blocks.append(
        "Ranges it must fit — including after transposition, since these lines "
        "return in other voices:\n"
        + "\n".join(
            f"  - {spec.voices_by_id[voice_id].voice_id}: "
            f"{range_text(spec.voices_by_id[voice_id])}"
            for voice_id in sorted(carriers)
            if voice_id in spec.voices_by_id
        )
    )

    relations = sorted(
        {entry.relation for section in plan.sections for entry in section.material}
    )
    if relations:
        blocks.append(
            "These lines return under: " + ", ".join(relations) + ". Keep the range "
            "narrow enough that every one of those still fits its voice."
        )

    blocks.append(f"Key: {first.key}.")
    meters = {_meter_of(brief).surface_string(): _meter_of(brief) for brief in briefs}
    for meter in meters.values():
        cells = rhythmic_cells_text(style, meter)
        if cells:
            blocks.append(
                f"Rhythmic cells of the style in {meter.surface_string()}:\n" + cells
            )
    blocks.append(
        "Keep each one short: one to four bars, at most twelve notes. Every return "
        "of this material has to be written out exactly, and a long line is neither "
        "reproducible nor recognizable when it comes back."
    )
    blocks.append(
        "Absolute pitch with explicit octave marks "
        "(c' is middle C), Dutch note names as LilyPond reads them by default (ees "
        "for E flat, fis for F sharp — never eb or f#), an explicit duration on "
        "every note, a bar check | at the end of every bar, and no structural "
        "commands."
    )
    notes = rehearsal_notes(feedback or [], what="material")
    if notes:
        blocks.append(notes)
    return "\n\n".join(blocks)


def _motif_example(meter: MeterSpec) -> str:
    """One bar of plain notation in this meter, as a worked example.

    Built from the meter rather than hard-coded so it is always a bar that
    actually fills — an example that did not add up would teach the wrong
    lesson more effectively than the instruction teaches the right one.
    """
    pitches = ["d'", "e'", "f'", "g'", "a'", "bes'", "c''", "d''"]
    notes: list[str] = []
    for term in meter.terms:
        for _ in range(term.numerator):
            notes.append(f"{pitches[len(notes) % len(pitches)]}{term.denominator}")
    return " ".join(notes) + " |"


def _carrying_section(briefs: list[MaterialBrief], plan: StructurePlan) -> SectionPlan:
    """The section a motif is first *entered* in, not merely the first section.

    Material is written in the meter it will be sung in. Writing it in the
    opening section's meter instead produced a commission run where the riff
    was two bars of 4/4 and every declared entry was in 7/8: its bars could not
    fit, so no entry could both reproduce the rhythm and fill its bars, and the
    cross-voice check rejected the piece however many times it was rewritten.
    """
    wanted = {brief.motif_id for brief in briefs}
    for section in plan.sections:
        if any(entry.motif_id in wanted for entry in section.material):
            return section
    return plan.sections[0]


def build_harmony_prompt(
    section: SectionPlan,
    style: StylePack,
    motifs: list[Motif],
    previous_tail: HarmonicSkeleton | None,
    previous_section: SectionPlan | None,
    feedback: list[FeedbackItem] | None = None,
) -> str:
    """One section's progression, with the previous section's tail as context.

    Harmony is generated sequentially, unlike voices, because continuity across
    section boundaries is the whole point — the previous tail is the sliding
    window (docs/04).
    """
    blocks = [
        f"Write the chord progression for section {section.section_id}.",
        section_text(section),
    ]
    if style.harmony_guidance:
        blocks.append(f"Harmony in this style: {style.harmony_guidance}")
    if style.dissonance_policy:
        blocks.append(f"Dissonance: {style.dissonance_policy}")

    if previous_tail is not None and previous_tail.events and previous_section is not None:
        blocks.append(
            "The previous section ended on:\n"
            + chord_chart(
                HarmonicSkeleton(
                    section_id=previous_tail.section_id,
                    events=previous_tail.events[-2:],
                ),
                previous_section.meter,
            )
            + "\nBegin somewhere that follows from it."
        )

    for motif in motifs:
        blocks.append(
            f"This section carries the {motif.role} — harmonize so it fits rather "
            f"than fights it:\n  {motif.lily_music}"
        )

    beats = section.meter.units_per_bar
    blocks.append(
        f"Section {section.section_id} is {section.bars} bars of "
        f"{section.meter.surface_string()}, so {beats} beats per bar and "
        f"{section.bars * beats} beats in total. The chord durations must add up to "
        "exactly that, with no gaps and no overlaps."
    )
    blocks.append(f"Dynamics to support: {dynamics_text(section.dynamics)}.")
    notes = rehearsal_notes(feedback or [], what="progression")
    if notes:
        blocks.append(notes)
    return "\n\n".join(blocks)
