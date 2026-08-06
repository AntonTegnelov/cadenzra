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

SYSTEM_PROMPT = """\
You are a composer writing one vocal or instrumental part at a time, in \
LilyPond notation. You write idiomatic, singable, stylistically committed \
music that fits exactly the bars and harmony you are given.

Write the music by calling the `write_part` tool. Never reply with prose."""

_CONTRACT = """\
Write the part under these conventions:
  - Absolute pitch with explicit octave marks (c' is middle C). Never \\relative.
  - Dutch note names, which is what LilyPond reads by default: ees for E flat, \
aes for A flat, fis for F sharp, cis for C sharp. Never eb, bb, f#.
  - An explicit duration on every note (c'8 c'8, not c'8 c').
  - A bar check | at the end of every bar, including the last.
  - Notes, rests, durations, ties, slurs, dynamics, hairpins and markup only. \
No \\time, \\clef, \\key, \\tempo, \\score, \\new or any other structural command \
— the score around your part supplies those.
  - Print the dynamics the section asks for, as ordinary LilyPond (\\p, \\<, \\ff)."""


def build_voice_prompt(ctx: VoiceContext) -> str:
    """The user-turn prompt for one (section, voice) generation."""
    blocks = [
        f"Write the {ctx.voice.voice_id} part for this section.",
        section_text(ctx.section),
        f"Range for {ctx.voice.voice_id}: {range_text(ctx.voice)}. "
        "Every note must fall inside it.",
    ]

    style = style_text(ctx.style, ctx.section.meter)
    if style:
        blocks.append(style)

    if ctx.skeleton is not None and ctx.skeleton.events:
        blocks.append(
            "Harmony to write against:\n" + chord_chart(ctx.skeleton, ctx.section.meter)
        )

    for instruction in ctx.materials:
        blocks.append(material_text(instruction))

    if ctx.previous_tail:
        blocks.append(
            f"The {ctx.voice.voice_id} line ended the previous section like this — "
            f"continue naturally from it:\n  {ctx.previous_tail}"
        )

    blocks.append(_contract_for(ctx))

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

    return "\n\n".join(blocks)


def _contract_for(ctx: VoiceContext) -> str:
    """The fragment contract, plus the meter reminder this section needs."""
    meter = ctx.section.meter
    contract = _CONTRACT
    if meter.grouping is not None:
        grouping = "+".join(str(count) for count in meter.grouping)
        contract += (
            f"\n  - The meter is {meter.surface_string()}: every bar holds "
            f"{meter.units_per_bar} {_unit_name(meter.unit)}s, felt as {grouping}. "
            "Beam and phrase with that grouping."
        )
    if meter.is_additive:
        contract += (
            f"\n  - {meter.surface_string_bare()} is an additive meter: a bar is "
            f"{' plus '.join(str(term) for term in meter.terms)}, "
            f"{meter.units_per_bar} {_unit_name(meter.unit)}s in total."
        )
    return contract


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
