"""Rendering internal state into the musician's view.

This module is one half of the seam described in docs/03 and docs/08: internals
may be as general as correctness demands, but everything an LLM reads speaks
bar numbers, decimal beats, note names, chord symbols, and textbook LilyPond,
because that is where the model's training-data density — and therefore its
compositional ability — lives.

Nothing else in the system converts between the two registers. A `Fraction`
offset appearing in a prompt, or a bar number appearing in `verification/`
logic, is a review flag.
"""

from fractions import Fraction

from cadenzra.model.contexts import MaterialInstruction
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.primitives.time import bar_beat_of
from cadenzra.model.spec import VoiceSpec
from cadenzra.model.structure import DynamicsPlan, SectionPlan
from cadenzra.model.style import StylePack
from cadenzra.notation.fragments import transposed_first_pitch
from cadenzra.verification.transposition import UnknownRelationError, parse_relation


def beat_text(beat: Fraction) -> str:
    """A beat as a musician writes it: "2", "2.5"."""
    if beat.denominator == 1:
        return str(beat.numerator)
    return f"{float(beat):g}"


def position_text(offset: Fraction, meter: MeterSpec) -> str:
    """An internal offset as "bar 5, beat 2.5"."""
    bar, beat = bar_beat_of(offset, meter)
    return f"bar {bar}, beat {beat_text(beat)}"


def range_text(voice: VoiceSpec) -> str:
    """A voice's range in scientific pitch, with the LilyPond spelling beside
    it — the generator has to write the second form, so it should see it."""
    low, high = voice.range_low, voice.range_high
    return (
        f"{low.to_scientific()} ({low.to_lilypond()}) up to "
        f"{high.to_scientific()} ({high.to_lilypond()})"
    )


def dynamics_text(plan: DynamicsPlan) -> str:
    """A dynamics arc as a sentence."""
    if not plan.targets:
        return f"stay around {plan.start}"
    steps = ", ".join(f"reach {target.level} by bar {target.bar}" for target in plan.targets)
    return f"begin {plan.start}, then {steps}"


def chord_chart(skeleton: HarmonicSkeleton, meter: MeterSpec) -> str:
    """The harmonic skeleton as a bar-by-bar chord chart.

    Grouped by bar, because that is how a musician reads changes — a flat list
    of "offset 7/8: Dm" would be the same information in the register the model
    has seen least.
    """
    by_bar: dict[int, list[str]] = {}
    for event in skeleton.events:
        bar, beat = bar_beat_of(event.offset, meter)
        entry = event.chord if beat == 1 else f"{event.chord} (beat {beat_text(beat)})"
        by_bar.setdefault(bar, []).append(entry)
    return "\n".join(
        f"  bar {bar}: {' | '.join(chords)}" for bar, chords in sorted(by_bar.items())
    )


def rhythmic_cells_text(style: StylePack, meter: MeterSpec) -> str:
    """The vetted cells for a meter, as notation with their groupings.

    Generators build rhythm by selecting, repeating and varying these rather
    than inventing it: free rhythmic invention in 7/8 is where beat-count
    errors concentrate, and varying a correct cell rarely breaks the bar
    (docs/04).
    """
    cells = style.cells_for(meter)
    if not cells:
        return ""
    lines = [f"  {cell.lily}    % {cell.description}" for cell in cells]
    return "\n".join(lines)


def material_text(instruction: MaterialInstruction) -> str:
    """A motif entry as an instruction to a player, with the notes in full.

    Where the entry is transposed, the target starting pitch is computed and
    named outright. Asking a model to work out "a fifth above d'" for itself
    is arithmetic we can do exactly, and every note of the entry is verified
    against that transposition — so the surface should hand over the answer
    rather than the puzzle (docs/08, principle 2).
    """
    entry, motif = instruction.entry, instruction.motif
    lines = [
        f"At bar {entry.bar}, enter with the {motif.role} ({motif.motif_id}).",
        f"The {motif.role} is written as:",
        f"  {motif.lily_music}",
    ]
    if motif.description:
        lines.append(f"  ({motif.description})")

    lines.append(_entry_instruction(instruction))
    lines.append(
        "Reproduce it note for note and rhythm for rhythm — this entry is checked "
        "against the original, and every interval must match."
    )
    return "\n".join(lines)


def _entry_instruction(instruction: MaterialInstruction) -> str:
    """How to place the entry, in the most concrete terms available."""
    entry, motif = instruction.entry, instruction.motif
    try:
        relation = parse_relation(entry.relation)
    except UnknownRelationError:
        return f"Enter it {entry.relation}."

    if relation.kind == "exact":
        return "Enter it at exactly this pitch."
    if relation.kind == "inversion":
        return (
            "Enter it inverted: every interval keeps its size but changes "
            "direction, so a rising third becomes a falling third."
        )
    if relation.kind == "tonal answer":
        return (
            "Enter it as a tonal answer at the fifth: transpose it up a fifth, "
            "adjusting at most one note by a step to stay in the key."
        )

    target = transposed_first_pitch(motif.lily_music, relation.semitones)
    direction = "up" if relation.semitones > 0 else "down"
    if target is None:
        return f"Transpose it {direction} ({entry.relation})."
    return (
        f"Transpose the whole {motif.role} {direction} ({entry.relation}), so it "
        f"begins on {target.to_scientific()} — written {target.to_lilypond()} — "
        "and every following interval is unchanged."
    )


def section_text(section: SectionPlan) -> str:
    """The plan for one section, as a briefing."""
    lines = [
        f"Section {section.section_id}: {section.bars} bars in "
        f"{section.meter.surface_string()}, {section.key}, "
        f"{section.tempo_bpm} bpm.",
        f"Texture: {section.texture}.",
        f"Dynamics: {dynamics_text(section.dynamics)}.",
    ]
    if section.intent:
        lines.append(f"Intent: {section.intent}")
    return "\n".join(lines)


def rehearsal_notes(feedback: list[FeedbackItem], *, what: str) -> str:
    """Validator feedback rendered as a rehearsal note.

    Every regenerating layer needs this, not just voices: a regeneration that
    cannot see why the last attempt was rejected will produce the same mistake
    again, slightly rephrased, until the budget runs out (docs/04).
    """
    if not feedback:
        return ""
    notes = "\n".join(f"  - {item.message}" for item in feedback)
    return (
        f"Your previous {what} was rejected for these reasons. Fix them, changing "
        f"as little else as possible:\n{notes}"
    )


def style_text(style: StylePack, meter: MeterSpec) -> str:
    """The style pack as guidance, showing only what this section can use."""
    lines = []
    if style.idioms:
        lines.append("Style:")
        lines += [f"  - {idiom}" for idiom in style.idioms]
    if style.harmony_guidance:
        lines.append(f"Harmony: {style.harmony_guidance}")
    cells = rhythmic_cells_text(style, meter)
    if cells:
        lines.append(
            f"Rhythmic cells for {meter.surface_string()} — build the rhythm by "
            "selecting, repeating and varying these:"
        )
        lines.append(cells)
    if style.few_shot_fragments:
        lines.append("Fragments in this style:")
        lines += [f"  {fragment}" for fragment in style.few_shot_fragments]
    return "\n".join(lines)
