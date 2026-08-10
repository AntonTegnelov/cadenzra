"""Prompts for the lyric layers.

Two calls, and the difference between them is the whole design (docs/10). The
planner works in prose about a story; the writer works against finished music
and writes for every singer in the section at once, which is what makes two
languages at the same time structurally impossible rather than merely
discouraged.

Capability gating applies as everywhere else: an instrumental piece never
reaches this module, and the device vocabulary appears only where a piece has
asked for devices.
"""

from cadenzra.llm.prompts.surface import rehearsal_notes
from cadenzra.model.contexts import LyricsContext
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.lyrics import (
    DEVICE_DEFINITIONS,
    RELATIONSHIP_DEFINITIONS,
    LyricPlan,
)
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import StructurePlan
from cadenzra.model.style import StylePack

LYRIC_PLAN_SYSTEM = """\
You are a lyricist planning the words of a piece before any of them are \
written. You work out what the piece is about, then what each section does \
with that — which part of the story it carries, how the voices relate, and \
what craft it uses.

You are planning, not writing: no actual lyrics here, only the brief each \
section will be written to.

Answer by calling the `plan_lyrics` tool. Never reply with prose."""

LYRICS_SYSTEM = """\
You are a lyricist setting words to music that already exists. The notes are \
finished and will not change: your words fit them, not the other way round.

You write every singing voice in the section together, so their words belong \
to one text — one language, one story, one moment. Whether they sing the same \
words or different ones is the section's own relationship, given to you.

Sing what can be sung: one syllable per note, hyphenating words across notes, \
holding a vowel over several notes where the line asks for it.

Answer by calling the `write_lyrics` tool. Never reply with prose."""


def devices_block(devices: list[str]) -> str:
    """Definitions for the devices in play, and only those.

    Naming a device is an invitation to use it (docs/08, principle 2), so the
    vocabulary is never shown wholesale to a writer — only what was asked for.
    """
    known = [device for device in devices if device in DEVICE_DEFINITIONS]
    if not known:
        return ""
    lines = [f"  - {device}: {DEVICE_DEFINITIONS[device]}" for device in known]
    return "Craft to use here:\n" + "\n".join(lines)


def build_lyric_plan_prompt(
    spec: PieceSpec,
    style: StylePack,
    plan: StructurePlan,
    feedback: list[FeedbackItem] | None = None,
) -> str:
    """Plan the words for the whole piece, section by section."""
    lyrics = spec.lyrics
    language = spec.lyric_language
    singing = [voice.voice_id for voice in spec.singing_voices]

    blocks = [
        f'Plan the words of "{spec.title}".',
        f"Everything is sung in {language}. Every section uses that one language.",
        f"Singing voices: {', '.join(singing)}.",
    ]
    if lyrics is not None and lyrics.brief:
        blocks.append(f"What it is about: {lyrics.brief}")
    else:
        blocks.append(f"What it is about: take it from the music — {spec.style_prompt}")

    if style.idioms:
        blocks.append(
            "The music's character:\n"
            + "\n".join(f"  - {idiom}" for idiom in style.idioms)
        )

    sections = "\n".join(
        f"  {section.section_id}: {section.bars} bars of "
        f"{section.meter.surface_string()}, {section.key}, {section.texture}"
        + (f" — {section.intent}" if section.intent else "")
        for section in plan.sections
        if _sings(section.section_id, plan, spec)
    )
    blocks.append("The sections that are sung:\n" + sections)

    blocks.append(
        "Give the piece one story, then a brief for each sung section: what that "
        "section says, and how the voices relate. A section that brings back an "
        "earlier section's words word for word is a refrain of it."
    )
    blocks.append(
        "Ask for craft only where the material genuinely invites it. A device "
        "forced into a section it does not suit reads worse than a plain lyric, "
        "and most sections need none. Leave devices empty unless you can say "
        "what the section would gain."
    )

    if lyrics is not None and lyrics.rhyme_scheme:
        blocks.append(
            f"The piece asks for a {lyrics.rhyme_scheme} rhyme scheme. Every "
            "section that can carry it should."
        )
    else:
        blocks.append(
            "Ask for a rhyme scheme only where it serves the section — a letter "
            "per line, like AABB or ABAB, x for a line that is free. Leave it out "
            "otherwise; not every lyric rhymes."
        )

    requested = list(lyrics.devices) if lyrics is not None else []
    if requested:
        blocks.append(
            "The piece asks for this craft in particular. Use every one of these "
            "somewhere, in the section where it belongs:\n"
            + "\n".join(f"  - {d}: {DEVICE_DEFINITIONS.get(d, d)}" for d in requested)
        )
    blocks.append(
        "How the voices can relate:\n"
        + "\n".join(
            f"  - {name}: {text}" for name, text in RELATIONSHIP_DEFINITIONS.items()
        )
    )
    notes = rehearsal_notes(feedback or [], what="lyric plan")
    if notes:
        blocks.append(notes)
    return "\n\n".join(blocks)


def build_lyrics_prompt(ctx: LyricsContext) -> str:
    """Write one section's words, for every voice that sings in it."""
    directive = ctx.directive
    blocks = [
        f"Write the words for section {ctx.section.section_id}, in {ctx.language}.",
        f"The piece is about: {ctx.story}",
        f"This section: {directive.story_beat}",
        f"The voices sing in {directive.relationship}"
        f" — {RELATIONSHIP_DEFINITIONS[directive.relationship]}.",
    ]

    if ctx.refrain_source is not None:
        blocks.append(
            "This section is a refrain: it brings back the words of section "
            f"{directive.refrain_of} unchanged. Those words were:\n"
            + _lyrics_text(ctx.refrain_source.voices[0].text if
                           ctx.refrain_source.voices else "")
        )

    blocks.append(
        "The music you are setting, exactly as written — one syllable per note, "
        "and count them:\n"
        + "\n".join(
            f"  {voice_id}:\n    " + _wrapped(ctx.parts[voice_id].lily_music)
            for voice_id in ctx.voice_ids
            if voice_id in ctx.parts
        )
    )
    blocks.append(
        f"The section is {ctx.section.bars} bars of "
        f"{ctx.section.meter.surface_string()}, {ctx.section.key}, "
        f"{ctx.section.tempo_bpm} bpm."
    )

    if ctx.previous:
        recent = ctx.previous[-2:]
        blocks.append(
            "What has been sung so far, so this continues it:\n"
            + "\n".join(
                f"  section {section.section_id}:\n"
                + "\n".join(f"    {voice.text}" for voice in section.voices)
                for section in recent
            )
        )

    if directive.rhyme_scheme:
        scheme = directive.rhyme_scheme
        blocks.append(
            f"Rhyme scheme: {scheme}. One letter per line; lines marked with the "
            f"same letter rhyme at their ends, and x is free. The scheme covers "
            f"one stanza of {len(scheme)} lines and then repeats — write as many "
            "stanzas as the music has room for. Each stanza rhymes within "
            "itself; the next one starts fresh."
        )

    devices = devices_block(directive.devices)
    if devices:
        blocks.append(devices)

    blocks.append(
        "Write the words under these conventions:\n"
        "  - A line is a phrase a singer delivers in one breath — roughly one "
        "or two bars of the music above, not one line per section. Write as "
        "many as the music needs; a long section wants many short lines, never "
        "a few enormous ones.\n"
        "  - Split a word across notes with -- between its syllables: "
        "sha -- dow.\n"
        "  - Hold one syllable across several notes by following it with __ : "
        "light __ __.\n"
        "  - Nothing but the words: no barlines, no \\lyricmode wrapper, no "
        "note names.\n"
        "  - There are as many syllables as there are notes to sing them on."
    )
    if ctx.rejected is not None:
        blocks.append("Your previous attempt:\n" + _rejected_text(ctx))
    notes = rehearsal_notes(ctx.feedback, what="lyrics")
    if notes:
        blocks.append(notes)
    return "\n\n".join(blocks)


def build_device_observation_prompt(lyrics_text: str) -> str:
    """Ask a reader what craft is in these lines — without saying what to find.

    The blinding is the point: a judge told what was intended reports finding
    it whether or not it is there (docs/05, docs/10). The observer sees the
    whole vocabulary and never the directive.
    """
    catalogue = "\n".join(
        f"  - {name}: {text}" for name, text in DEVICE_DEFINITIONS.items()
    )
    return (
        "Read these lyrics and report which of the devices below you actually "
        "find in them, and where.\n\n"
        f"{lyrics_text}\n\n"
        f"The devices to look for:\n{catalogue}\n\n"
        "Report only what is genuinely there. Most lyrics use a few of these; "
        "an empty answer is a fine answer. Do not report a device because it "
        "would be a good idea here."
    )


DEVICE_OBSERVATION_SYSTEM = """\
You are a close reader of poetry and song lyrics. You report what a text \
actually does, not what it might have intended. You would rather report \
nothing than report a device you cannot point at.

Answer by calling the `observe_devices` tool. Never reply with prose."""


def _sings(section_id: str, plan: StructurePlan, spec: PieceSpec) -> bool:
    """Whether any singing voice is active in a section."""
    section = plan.sections_by_id.get(section_id)
    if section is None:
        return False
    singing = {voice.voice_id for voice in spec.singing_voices}
    if not section.active_voices:
        return bool(singing)
    named = {ref for ref in section.active_voices if isinstance(ref, str)}
    if named & singing:
        return True
    groups = {
        voice.group for voice in spec.singing_voices if voice.group is not None
    }
    return any(
        getattr(ref, "group", None) in groups for ref in section.active_voices
    )


def plan_summary(plan: LyricPlan) -> str:
    """The lyric plan as a musician would read it back."""
    lines = [f"Story: {plan.story}", f"Language: {plan.language}"]
    for directive in plan.directives:
        detail: list[str] = [directive.relationship]
        if directive.rhyme_scheme:
            detail.append(directive.rhyme_scheme)
        if directive.devices:
            detail.append(", ".join(directive.devices))
        if directive.refrain_of:
            detail.append(f"refrain of {directive.refrain_of}")
        lines.append(
            f"  {directive.section_id}: {directive.story_beat} "
            f"({'; '.join(detail)})"
        )
    return "\n".join(lines)


def _wrapped(music: str) -> str:
    return music.replace("\n", "\n    ")


def _lyrics_text(text: str) -> str:
    return "\n".join(f"    {line}" for line in text.splitlines())


def _rejected_text(ctx: LyricsContext) -> str:
    assert ctx.rejected is not None
    return "\n".join(
        f"  {voice.voice_id}:\n" + "\n".join(f"    {line.render()}" for line in voice.lines)
        for voice in ctx.rejected.voices
    )
