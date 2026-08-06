"""Normalizing lyric tool calls into internal values.

The inward half of the lyric seam. Lines arrive as lyricmode-convention text
and are tokenized here — a token scan, the same allowed class as counting `|`
in a fragment, and emphatically not a parser of anything.

What this does *not* do is judge whether the words fit the notes. That is the
compiler's answer, and duplicating it here would be the same guard in two
places (docs/08, principle 6; docs/10).
"""

from typing import Any

from pydantic import ValidationError

from cadenzra.common.errors import LLMOutputError
from cadenzra.model.lyrics import (
    DEVICE_VOCABULARY,
    DeviceObservation,
    LyricLine,
    LyricPlan,
    SectionLyricDirective,
    SectionLyrics,
    VoiceLyrics,
)
from cadenzra.model.primitives.ids import SectionId, VoiceId
from cadenzra.model.structure import StructurePlan


def parse_lyric_plan(
    payload: dict[str, Any], plan: StructurePlan, *, language: str
) -> LyricPlan:
    """Build a `LyricPlan` from a `plan_lyrics` call."""
    raw_directives = payload.get("directives")
    if not isinstance(raw_directives, list) or not raw_directives:
        raise LLMOutputError("the lyric plan came back without any section directives")

    known = set(plan.sections_by_id)
    directives = []
    for raw in raw_directives:
        if not isinstance(raw, dict):
            raise LLMOutputError("a lyric directive came back malformed")
        section_id = str(raw.get("section_id", "")).strip()
        if section_id not in known:
            raise LLMOutputError(
                f"the lyric plan names section {section_id!r}, which is not in the form"
            )
        try:
            directives.append(
                SectionLyricDirective(
                    section_id=section_id,
                    story_beat=str(raw.get("story_beat", "")).strip(),
                    devices=_devices(raw.get("devices")),
                    rhyme_scheme=_scheme(raw.get("rhyme_scheme")),
                    relationship=str(raw.get("relationship", "unison")).strip(),  # type: ignore[arg-type]
                    refrain_of=_optional_id(raw.get("refrain_of")),
                )
            )
        except ValidationError as error:
            raise LLMOutputError(
                f"the directive for section {section_id} is malformed: {error}"
            ) from error

    try:
        return LyricPlan(
            language=language,
            story=str(payload.get("story", "")).strip(),
            directives=directives,
        )
    except ValidationError as error:
        raise LLMOutputError(f"the lyric plan is malformed: {error}") from error


def parse_section_lyrics(
    payload: dict[str, Any], *, section_id: SectionId, voice_ids: list[VoiceId]
) -> SectionLyrics:
    """Build a `SectionLyrics` from a `write_lyrics` call."""
    raw_voices = payload.get("voices")
    if not isinstance(raw_voices, list) or not raw_voices:
        raise LLMOutputError(
            f"the lyrics for section {section_id} came back without any voices"
        )

    expected = set(voice_ids)
    written: dict[VoiceId, VoiceLyrics] = {}
    for raw in raw_voices:
        if not isinstance(raw, dict):
            raise LLMOutputError(f"a voice's lyrics for section {section_id} are malformed")
        voice_id = str(raw.get("voice_id", "")).strip()
        if voice_id not in expected:
            raise LLMOutputError(
                f"the lyrics name voice {voice_id!r}, which does not sing in "
                f"section {section_id}"
            )
        lines = _lines(raw.get("lines"), voice_id=voice_id, section_id=section_id)
        written[voice_id] = VoiceLyrics(
            voice_id=voice_id, lines=lines, lily_lyrics=render_lyricmode(lines)
        )

    missing = sorted(expected - set(written))
    if missing:
        raise LLMOutputError(
            f"section {section_id} has no words for {', '.join(missing)}; every "
            "singing voice needs them"
        )
    return SectionLyrics(
        section_id=section_id, voices=[written[voice_id] for voice_id in voice_ids]
    )


def parse_device_observations(payload: dict[str, Any]) -> list[DeviceObservation]:
    """What a blind reader reported finding."""
    raw = payload.get("observations")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise LLMOutputError("the device observations came back malformed")

    observations = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        device = str(item.get("device", "")).strip().lower().replace(" ", "_")
        # An observation of something outside the vocabulary is not an error —
        # a reader noticing more than we asked about costs nothing, and the
        # comparison that matters only looks for what was requested.
        observations.append(
            DeviceObservation(
                device=device,
                lines=[int(n) for n in item.get("lines", []) or [] if _is_int(n)],
                evidence=str(item.get("evidence", "")).strip(),
            )
        )
    return observations


def tokenize_line(text: str) -> LyricLine:
    """One line of lyricmode-convention text, as tokens.

    Barlines are removed rather than kept: inside `\\lyricmode` a `|` is a bar
    check, and a writer mirroring the music's barlines into the words produces
    checks that pass in a single-section scaffold and fail once sections are
    concatenated. Lyrics gain nothing from bar checks.
    """
    cleaned = text.replace("|", " ").strip()
    if cleaned.startswith("\\lyricmode"):
        cleaned = cleaned[len("\\lyricmode") :].strip().strip("{}").strip()
    return LyricLine(tokens=cleaned.split())


def render_lyricmode(lines: list[LyricLine]) -> str:
    """The `\\lyricmode` block the score will carry.

    Rendered here rather than asked for, so the block is always well-formed
    whatever the model wrote.
    """
    body = " ".join(line.render() for line in lines if line.tokens)
    return f"\\lyricmode {{ {body} }}"


def _lines(raw: object, *, voice_id: str, section_id: str) -> list[LyricLine]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise LLMOutputError(
            f"the {voice_id} lyrics for section {section_id} have no lines"
        )
    lines = [tokenize_line(str(item)) for item in raw]
    lines = [line for line in lines if line.tokens]
    if not lines:
        raise LLMOutputError(
            f"the {voice_id} lyrics for section {section_id} are empty"
        )
    return lines


def _devices(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [
        name
        for name in (str(item).strip().lower().replace(" ", "_") for item in raw)
        if name in DEVICE_VOCABULARY
    ]


def _scheme(raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(" ", "")
    return text or None


def _optional_id(raw: object) -> SectionId | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _is_int(value: object) -> bool:
    try:
        int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return False
    return True
