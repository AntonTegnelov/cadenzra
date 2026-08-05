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
    """Accept lyrics with or without their `\\lyricmode` wrapper.

    Models supply one or the other depending on the day; the assembler needs
    exactly one form. Normalizing here is what the surface being "forgiving,
    strict underneath" means in practice (docs/03).
    """
    if lyrics is None or not lyrics.strip():
        return None
    text = lyrics.strip()
    if text.startswith("\\lyricmode"):
        return text
    return f"\\lyricmode {{ {text.strip('{} ')} }}"


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
