"""Normalizing a `write_part` tool call into a `VoicePart`.

This is the inward half of the seam: the only place a model's output becomes an
internal value. A malformed call raises `LLMOutputError` and is handled by the
adapter's bounded retry — never scraped with a regex, never coerced to a
default (docs/06).

What this does *not* do is judge the notation. A fragment that parses is only
well-shaped; whether it is well-formed music is the compiler's answer, and
duplicating that here would be the same guard in two places (docs/08,
principle 6).
"""

from typing import Any

from pydantic import ValidationError

from cadenzra.common.errors import LLMOutputError
from cadenzra.model.primitives.ids import SectionId, VoiceId
from cadenzra.model.voice import TechniqueSpan, VoicePart


def parse_voice_part(
    payload: dict[str, Any], *, section_id: SectionId, voice_id: VoiceId
) -> VoicePart:
    """Build a `VoicePart` from a tool call's arguments."""
    music = payload.get("lily_music")
    if not isinstance(music, str) or not music.strip():
        raise LLMOutputError(
            f"the {voice_id} part for section {section_id} came back without any "
            "notation in lily_music"
        )

    lyrics = payload.get("lily_lyrics")
    if lyrics is not None and not isinstance(lyrics, str):
        raise LLMOutputError(
            f"the {voice_id} part for section {section_id} has lyrics that are not text"
        )

    return VoicePart(
        section_id=section_id,
        voice_id=voice_id,
        lily_music=music.strip(),
        lily_lyrics=_normalize_lyrics(lyrics),
        techniques=_parse_techniques(payload.get("techniques"), voice_id=voice_id),
    )


def _normalize_lyrics(lyrics: str | None) -> str | None:
    """Accept lyrics with or without their `\\lyricmode` wrapper, and without
    the barlines a model naturally copies across from the music.

    Two normalizations, both cases of the surface being forgiving while the
    system stays strict underneath (docs/03).

    The barline one is not cosmetic. `|` inside `\\lyricmode` is a bar check
    like any other, and a model mirroring the music's barlines into its lyrics
    writes ones that pass inside a single-section scaffold and then fail once
    sections are concatenated and the lyric context's measure positions shift.
    That produced a run where every part compiled alone and the assembled score
    did not. Lyrics gain nothing from bar checks — note-to-syllable alignment is
    what matters there, and the compiler reports that separately — so they are
    removed rather than enforced.
    """
    if lyrics is None or not lyrics.strip():
        return None
    text = " ".join(lyrics.strip().replace("|", " ").split())
    if text.startswith("\\lyricmode"):
        return text
    return f"\\lyricmode {{ {text.strip('{} ').strip()} }}"


def _parse_techniques(raw: object, *, voice_id: VoiceId) -> list[TechniqueSpan]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise LLMOutputError(f"the {voice_id} part declared techniques that are not a list")

    spans = []
    for item in raw:
        if not isinstance(item, dict):
            raise LLMOutputError(f"the {voice_id} part declared a malformed technique")
        try:
            spans.append(TechniqueSpan.model_validate(item))
        except ValidationError as error:
            raise LLMOutputError(
                f"the {voice_id} part declared a technique the system does not know: "
                f"{item!r}"
            ) from error
    return spans
