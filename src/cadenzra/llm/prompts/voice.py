"""The prompt for `generate_voice`, and the capability gating around it.

Two rules from docs/04 govern this file. **Speak musician**: everything here is
bars, beats, note names, chord symbols and textbook LilyPond. **Show only what
the piece needs**: additive-meter syntax, technique vocabularies and
quarter-tone spellings do not appear unless the spec activates them, because
mentioning a capability is an invitation to use it, and an intuitive surface is
also an unsurprising one.

The fragment-contract rules stay short and mechanical here on purpose. The
enforcement loop carries the real weight — the prompt exists to make that loop
converge fast, not to be the guarantee (docs/04).
"""

from cadenzra.llm.prompts.surface import (
    chord_chart,
    material_text,
    range_text,
    section_text,
    style_text,
)
from cadenzra.model.contexts import VoiceContext
from cadenzra.model.voice import TECHNIQUE_VOCABULARY

_CONTRACT = """\
Write every part under these conventions:
  - Absolute pitch with explicit octave marks (c' is middle C). Never \\relative.
  - Dutch note names, which is what LilyPond reads by default. The rule is \
regular and covers every letter: a flat adds -es and a sharp adds -is — ces \
des ees fes ges aes bes, and cis dis eis fis gis ais bis. Never eb, bb, cb, \
f#, or gbes.
  - An explicit duration on every note (c'8 c'8, not c'8 c').
  - A bar check | at the end of every bar, including the last.
  - Notes, rests, durations, ties, slurs, dynamics, hairpins and markup only. \
No \\time, \\clef, \\key, \\tempo, \\score, \\new or any other structural command \
— the score around your part supplies those.
  - Print the dynamics the section asks for, as ordinary LilyPond (\\p, \\<, \\ff).
  - Before writing any bar's notes, count its durations so they sum to exactly \
one full bar of the meter — the last bar of a phrase deserves the recount most."""

# The contract is piece-invariant, so it rides the system prompt: paying for
# it in the user turn on every one of hundreds of voice calls was the cost
# audit's "a system prompt billed as a user prompt". Only the per-meter
# clauses (`_meter_clauses`) stay in the user turn.
SYSTEM_PROMPT = f"""\
You are a composer writing one vocal or instrumental part at a time, in \
LilyPond notation. You write idiomatic, singable, stylistically committed \
music that fits exactly the bars and harmony you are given.

{_CONTRACT}

Write the music by calling the `write_part` tool. Never reply with prose."""


def build_voice_prompt(ctx: VoiceContext) -> str:
    """The user-turn prompt for one (section, voice) generation.

    Ordered piece-wide → section-wide → voice-specific, invariant text first:
    a cache can only key on a shared prefix, and two voices of one section
    share everything up to the task line.
    """
    blocks = []

    style = style_text(ctx.style, ctx.section.meter)
    if style:
        blocks.append(style)

    blocks.append(section_text(ctx.section))

    meter_clauses = _meter_clauses(ctx)
    if meter_clauses:
        blocks.append(meter_clauses)

    if ctx.skeleton is not None and ctx.skeleton.events:
        blocks.append(
            "Harmony to write against:\n" + chord_chart(ctx.skeleton, ctx.section.meter)
        )

    blocks.append(f"Write the {ctx.voice.voice_id} part for this section.")
    blocks.append(
        f"Range for {ctx.voice.voice_id}: {range_text(ctx.voice)}. "
        "Every note must fall inside it."
    )

    for instruction in ctx.materials:
        blocks.append(material_text(instruction))

    if ctx.previous_tail:
        blocks.append(
            f"The {ctx.voice.voice_id} line ended the previous section like this — "
            f"continue naturally from it:\n  {ctx.previous_tail}"
        )

    if ctx.voice.lyrics:
        blocks.append(
            "This part is sung. The words are written afterwards, to fit the line "
            "you write, so write a singable one: phrases a singer can breathe "
            "between, and note groupings that take one syllable each, with the "
            "occasional held note where a vowel can open out."
        )

    if _uses_techniques(ctx):
        blocks.append(_techniques_block())

    if ctx.is_regeneration:
        blocks.append(_rehearsal_notes(ctx))
    elif ctx.feedback:
        blocks.append(_fresh_start_notes(ctx))

    if ctx.siblings:
        blocks.append(_siblings_block(ctx))

    return "\n\n".join(blocks)


def _siblings_block(ctx: VoiceContext) -> str:
    """The other voices, when the problem is between this line and theirs.

    Shown only on a cross-voice repair. A part told "you move in parallel
    octaves with the viola" and not shown the viola is being asked to fix a
    relationship it cannot see — and it rewrites blind, which is how a repair
    loop trades one parallel for another and stalls.
    """
    lines = "\n".join(
        f"  {voice_id}:\n    " + music.replace("\n", "\n    ")
        for voice_id, music in ctx.siblings.items()
    )
    return (
        "The other voices in this section, which yours has to fit against — "
        "these are fixed, so yours is the line that moves:\n" + lines
    )


def _meter_clauses(ctx: VoiceContext) -> str:
    """The meter reminders this section needs — section-shaped, gated.

    The rest of the fragment contract is invariant and lives in the system
    prompt; these two clauses depend on the section's meter, so they stay in
    the user turn (and only appear where an odd or additive meter needs them).
    """
    meter = ctx.section.meter
    clauses = []
    if meter.grouping is not None:
        grouping = "+".join(str(count) for count in meter.grouping)
        clauses.append(
            f"The meter is {meter.surface_string()}: every bar holds "
            f"{meter.units_per_bar} {_unit_name(meter.unit)}s, felt as {grouping}. "
            "Beam and phrase with that grouping."
        )
    if meter.is_additive:
        clauses.append(
            f"{meter.surface_string_bare()} is an additive meter: a bar is "
            f"{' plus '.join(str(term) for term in meter.terms)}, "
            f"{meter.units_per_bar} {_unit_name(meter.unit)}s in total."
        )
    return "\n".join(clauses)


def _unit_name(denominator: int) -> str:
    return {1: "whole note", 2: "half note", 4: "quarter note", 8: "eighth", 16: "sixteenth"}.get(
        denominator, f"1/{denominator} note"
    )


def _uses_techniques(ctx: VoiceContext) -> bool:
    """Techniques are gated: the vocabulary appears only where a piece already
    calls for one, never as a standing invitation (docs/04)."""
    return bool(ctx.rejected and ctx.rejected.techniques)


def _techniques_block() -> str:
    vocabulary = ", ".join(sorted(TECHNIQUE_VOCABULARY))
    return (
        "If the part uses an extended technique, mark it in the notation and also "
        "declare it in the tool call. Available techniques: " + vocabulary + "."
    )


def _rehearsal_notes(ctx: VoiceContext) -> str:
    """The rejected fragment and why, worded as a rehearsal note.

    The failing fragment is included because minimal repair preserves accepted
    material; regeneration from scratch is the fallback when repair fails
    (docs/04).
    """
    assert ctx.rejected is not None
    notes = "\n".join(f"  - {item.message}" for item in ctx.feedback)
    return (
        "This part was rejected. Here is what you wrote:\n\n"
        f"{ctx.rejected.lily_music}\n\n"
        f"Fix these problems, changing as little else as possible:\n{notes}"
    )


def _fresh_start_notes(ctx: VoiceContext) -> str:
    """Feedback without the text it indicts.

    A model shown its rejected music under "change as little as possible"
    reproduces it nearly verbatim — mistake included. When the loop decides
    the old text has stopped helping, the lesson still reaches the
    regeneration; the copyable text does not (docs/04's regeneration from
    scratch).
    """
    notes = "\n".join(f"  - {item.message}" for item in ctx.feedback)
    return (
        "A previous version of this part was rejected and has been discarded. "
        f"Write the part afresh, avoiding its mistakes:\n{notes}"
    )
