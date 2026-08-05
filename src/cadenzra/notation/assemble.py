"""Turning validated fragments into a score.

Pure string templating: fragments plus the plan in, one canonical LilyPond file
out. Every convenience the system wants lives here, where no LLM reads or
writes it — that is what keeps the generator surface textbook LilyPond
(docs/03, docs/08 principle 2).

This module owns the **one voice = one track = one channel** invariant. The
analysis validators key on it, and every per-channel performance mechanism —
CC dynamics, per-voice timing, pitch bend — exists only because of it. The M0
empirical check established the recipe: wrap each staff's music in
`\\new Voice = "<voice_id>"` so the track carries the voice's name, and declare
`midiChannelMapping = #'staff` explicitly rather than relying on the default.
"""

from typing import Final

from cadenzra.model.artifacts import AssembledScore, AssembledSection
from cadenzra.model.primitives.ids import SectionId, VoiceId
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.structure import SectionPlan, StructurePlan
from cadenzra.model.voice import VoicePart
from cadenzra.notation.instruments import instrument_name
from cadenzra.notation.scaffold import LILYPOND_VERSION, lily_time_command

_INDENT: Final = "  "


def variable_name(section_id: SectionId, voice_id: VoiceId) -> str:
    """The LilyPond variable holding one (section, voice) fragment.

    LilyPond identifiers are letters only, so ids are transliterated rather
    than interpolated raw.
    """
    return f"music{_letters(section_id)}{_letters(voice_id).capitalize()}"


def _letters(text: str) -> str:
    cleaned = "".join(
        char if char.isalpha() else _spell_digit(char) for char in text
    )
    return cleaned or "X"


def _spell_digit(char: str) -> str:
    names = "Zero One Two Three Four Five Six Seven Eight Nine"
    return names.split()[int(char)] if char.isdigit() else ""


def clef_for(voice: VoiceSpec) -> str:
    """A clef that keeps a voice on the staff without ledger-line thickets."""
    if voice.range_low.cents < Pitch(step="C", octave=3).cents:
        return "bass"
    if voice.range_low.cents < Pitch(step="C", octave=4).cents:
        return '"treble_8"'
    return "treble"


def assemble_section(
    section: SectionPlan,
    parts: dict[VoiceId, VoicePart],
    spec: PieceSpec,
) -> AssembledSection:
    """One section's voices, wrapped in the structure the fragments omit."""
    order = [voice.voice_id for voice in spec.voices if voice.voice_id in parts]
    blocks = []
    for voice_id in order:
        part = parts[voice_id]
        blocks.append(
            f"{variable_name(section.section_id, voice_id)} = \\absolute {{\n"
            f"{_INDENT}{_section_header(section)}\n"
            f"{_indent(part.lily_music)}\n"
            "}"
        )
        if part.lily_lyrics:
            blocks.append(
                f"{_lyrics_name(section.section_id, voice_id)} = {part.lily_lyrics}"
            )

    return AssembledSection(
        section_id=section.section_id,
        lily_source="\n\n".join(blocks),
        voice_order=order,
    )


def _lyrics_name(section_id: SectionId, voice_id: VoiceId) -> str:
    return f"words{_letters(section_id)}{_letters(voice_id).capitalize()}"


def _section_header(section: SectionPlan) -> str:
    """The structural commands a section establishes, which fragments may not."""
    parts = [lily_time_command(section.meter)]
    if section.key:
        parts.append(_key_command(section.key))
    parts.append(f"\\tempo 4 = {section.tempo_bpm}")
    return " ".join(part for part in parts if part)


def _key_command(key: str) -> str:
    """`\\key` from a plan's key string, e.g. "d phrygian" or "Bb major".

    Unrecognized modes fall back to no key signature rather than guessing: an
    accidental-heavy passage engraves correctly either way, and inventing a key
    signature would silently change what the score says.
    """
    words = key.strip().split()
    if not words:
        return ""
    try:
        # `\key` takes a bare pitch name, with no octave mark: `\key d \minor`,
        # never `\key d' \minor`.
        tonic = Pitch.from_scientific(f"{words[0].capitalize()}3").to_lilypond()
    except ValueError:
        return ""
    modes = {
        "major", "minor", "ionian", "dorian", "phrygian",
        "lydian", "mixolydian", "aeolian", "locrian",
    }
    mode = words[1].lower() if len(words) > 1 else "major"
    if mode not in modes:
        return ""
    return f"\\key {tonic} \\{mode}"


def assemble_score(
    plan: StructurePlan,
    sections: dict[SectionId, AssembledSection],
    spec: PieceSpec,
) -> AssembledScore:
    """The canonical LilyPond file — the source everything else derives from."""
    order = [section.section_id for section in plan.sections]
    voices = [voice.voice_id for voice in spec.voices]

    definitions = "\n\n".join(
        sections[section_id].lily_source for section_id in order if section_id in sections
    )

    staves = []
    for voice in spec.voices:
        music = " ".join(
            f"\\{variable_name(section_id, voice.voice_id)}"
            for section_id in order
            if voice.voice_id in sections.get(section_id, _EMPTY).voice_order
        )
        if not music:
            continue
        staves.append(_staff(voice, music, plan, sections, order))

    body = "\n".join(staves)
    staff_group = "ChoirStaff" if all(v.kind == "vocal" for v in spec.voices) else "StaffGroup"

    source = f"""\\version "{LILYPOND_VERSION}"

\\header {{
{_INDENT}title = "{spec.title}"
}}

{definitions}

\\score {{
{_INDENT}\\new {staff_group} <<
{body}
{_INDENT}>>
{_INDENT}\\layout {{}}
{_INDENT}\\midi {{
{_INDENT}{_INDENT}\\context {{
{_INDENT}{_INDENT}{_INDENT}\\Score
{_INDENT}{_INDENT}{_INDENT}midiChannelMapping = #'staff
{_INDENT}{_INDENT}}}
{_INDENT}}}
}}
"""
    return AssembledScore(lily_source=source, section_order=order, voice_order=voices)


def _staff(
    voice: VoiceSpec,
    music: str,
    plan: StructurePlan,
    sections: dict[SectionId, AssembledSection],
    order: list[SectionId],
) -> str:
    """One staff, with its voice named so the MIDI track carries the voice id."""
    lyrics = " ".join(
        f"\\{_lyrics_name(section_id, voice.voice_id)}"
        for section_id in order
        if _has_lyrics(sections, section_id, voice.voice_id, plan)
    )
    pad = _INDENT * 2
    lines = [
        f"{pad}\\new Staff \\with {{",
        f'{pad}{_INDENT}instrumentName = "{voice.voice_id}"',
        f'{pad}{_INDENT}midiInstrument = "{instrument_name(voice.midi_program)}"',
        f"{pad}}} {{",
        f"{pad}{_INDENT}\\clef {clef_for(voice)}",
        f'{pad}{_INDENT}\\new Voice = "{voice.voice_id}" {{ {music} }}',
        f"{pad}}}",
    ]
    if lyrics:
        lines.append(f'{pad}\\new Lyrics \\lyricsto "{voice.voice_id}" {{ {lyrics} }}')
    return "\n".join(lines)


def _has_lyrics(
    sections: dict[SectionId, AssembledSection],
    section_id: SectionId,
    voice_id: VoiceId,
    plan: StructurePlan,
) -> bool:
    del plan
    section = sections.get(section_id)
    return section is not None and voice_id in section.voice_order and (
        f"words{_letters(section_id)}{_letters(voice_id).capitalize()}"
        in section.lily_source
    )


def _indent(text: str) -> str:
    return "\n".join(f"{_INDENT}{line}" if line.strip() else line for line in text.split("\n"))


_EMPTY = AssembledSection(section_id="", lily_source="", voice_order=[])
