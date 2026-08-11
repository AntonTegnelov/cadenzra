"""Checking the words: the plan's contracts, and the compiler's alignment.

Three owners, and the boundaries are the design (docs/10):

- The **compiler** decides whether syllables line up with notes. It already
  answers that, and a second implementation in Python would be the same guard
  in two places (docs/08, principle 6).
- **This module** decides everything the plan *declared* — a rhyme scheme, a
  unison relationship, a refrain, a directive that covers its sections. All
  arithmetic, all final.
- An **LLM** decides craft. It is asked elsewhere, and blind.

Nothing here judges whether a lyric is any good. That is the poetics version of
the music-theory engine docs/01 rules out.
"""

from pathlib import Path
from typing import Final

from cadenzra.common.errors import LilypondCompileError
from cadenzra.interfaces.rendering import ScoreRenderer
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.lyrics import (
    TEXT_OBSERVABLE_DEVICES,
    DeviceObservation,
    LyricPlan,
    SectionLyricDirective,
    SectionLyrics,
    VoiceLyrics,
)
from cadenzra.model.primitives.ids import SectionId
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import SectionPlan, StructurePlan
from cadenzra.model.voice import VoicePart
from cadenzra.notation.scaffold import scaffold_fragment
from cadenzra.rendering.lilypond import first_error
from cadenzra.verification.rhyme import is_english, scheme_violations

SOURCE: Final = "validate_lyrics"
PLAN_SOURCE: Final = "validate_lyric_plan"

# LilyPond's complaint when a `\lyricsto` block runs out of notes, or has more
# syllables than there are notes to sing them on.
_ALIGNMENT_WARNING: Final = "cannot find"


def lyric_misalignment(compiler_output: str) -> bool:
    """Whether the compiler said the syllables do not fit the notes.

    Shared with `verification/voice.py` so there is one answer to this
    question, in one place.
    """
    return _ALIGNMENT_WARNING in compiler_output


def validate_lyric_plan(
    plan: LyricPlan, structure: StructurePlan, spec: PieceSpec
) -> list[FeedbackItem]:
    """Check the lyric plan against the form it was written for.

    Cheap checks on a cheap artifact: a directive naming a section that does
    not exist, or a refrain of a section that has not happened, costs nothing
    to catch here and a whole section's lyrics to catch later.
    """
    feedback: list[FeedbackItem] = []
    singing_sections = {
        section.section_id
        for section in structure.sections
        if _singing_voices(section, spec)
    }
    covered = {directive.section_id for directive in plan.directives}

    for missing in sorted(singing_sections - covered):
        feedback.append(
            _plan_item(
                f"section {missing} is sung but the lyric plan says nothing about "
                "it; every sung section needs a brief",
                section_id=missing,
            )
        )
    for extra in sorted(covered - singing_sections):
        feedback.append(
            _plan_item(
                f"the lyric plan briefs section {extra}, where nobody sings",
                section_id=extra,
            )
        )

    for directive in plan.directives:
        if not directive.story_beat.strip():
            feedback.append(
                _plan_item(
                    f"the brief for section {directive.section_id} says nothing "
                    "about what that section is about",
                    section_id=directive.section_id,
                )
            )
        # Device membership is enforced twice upstream — the parser filters
        # unknown names (the vocabulary is the contract) and the directive
        # model raises on them — so no directive here can carry one. A third
        # check that can never fire is theater, and it was removed.

    requested = set(spec.lyrics.devices) if spec.lyrics else set()
    if requested:
        used = {device for d in plan.directives for device in d.devices}
        dropped = sorted(requested - used)
        if dropped:
            feedback.append(
                _plan_item(
                    "the piece asks for "
                    + ", ".join(dropped)
                    + ", and no section uses "
                    + ("them" if len(dropped) > 1 else "it")
                )
            )

    wanted = spec.lyrics.rhyme_scheme if spec.lyrics else None
    if wanted and not any(d.rhyme_scheme for d in plan.directives):
        feedback.append(
            _plan_item(
                f"the piece asks for a {wanted} rhyme scheme and no section carries one"
            )
        )
    return feedback


def validate_section_lyrics(
    lyrics: SectionLyrics,
    directive: SectionLyricDirective,
    section: SectionPlan,
    parts: dict[str, VoicePart],
    *,
    language: str,
    renderer: ScoreRenderer,
    workdir: Path,
    refrain_source: SectionLyrics | None = None,
) -> list[FeedbackItem]:
    """Check one section's words against its music and its brief."""
    feedback: list[FeedbackItem] = []
    feedback += _check_alignment(lyrics, section, parts, renderer, workdir)
    feedback += _check_relationship(lyrics, directive, section)
    feedback += _check_refrain(lyrics, directive, section, refrain_source)
    if directive.rhyme_scheme and is_english(language):
        feedback += _check_scheme(lyrics, directive, section)
    return feedback


def missing_devices(
    directive: SectionLyricDirective, observations: list[DeviceObservation]
) -> list[str]:
    """Which requested devices a blind reader did not find.

    The comparison happens here, on values the observer never saw. Handing it
    the directive and asking "did you find these?" would produce a yes every
    time — the failure docs/05 measured with the audio critic.
    """
    observed = {observation.device for observation in observations}
    return [
        device
        for device in directive.devices
        if device in TEXT_OBSERVABLE_DEVICES and device not in observed
    ]


def _check_alignment(
    lyrics: SectionLyrics,
    section: SectionPlan,
    parts: dict[str, VoicePart],
    renderer: ScoreRenderer,
    workdir: Path,
) -> list[FeedbackItem]:
    """Compile each voice's music with its words and quote what the compiler says."""
    feedback: list[FeedbackItem] = []
    for voice in lyrics.voices:
        part = parts.get(voice.voice_id)
        if part is None:
            continue
        scaffold = scaffold_fragment(
            part.lily_music,
            section.meter,
            lily_lyrics=voice.lily_lyrics,
            tempo_bpm=section.tempo_bpm,
        )
        try:
            result = renderer.compile(
                scaffold.source, workdir / f"lyrics-{voice.voice_id}"
            )
        except LilypondCompileError as error:
            feedback.append(
                _item(
                    section.section_id,
                    voice.voice_id,
                    message=(
                        f"the {voice.voice_id} words do not compile with its music: "
                        + (first_error(error.output) or "the compiler rejected them")
                    ),
                    evidence=error.output,
                )
            )
            continue

        if lyric_misalignment(result.raw_output):
            notes = _note_count(part.lily_music)
            syllables = sum(line.syllable_count for line in voice.lines)
            feedback.append(
                _item(
                    section.section_id,
                    voice.voice_id,
                    message=(
                        f"the {voice.voice_id} words do not line up with its notes: "
                        f"{syllables} syllables against roughly {notes} notes. "
                        "Hyphenate a word across notes with -- , and hold one "
                        "syllable across several with __ ."
                    ),
                    evidence=result.raw_output,
                )
            )
    return feedback


def _check_relationship(
    lyrics: SectionLyrics, directive: SectionLyricDirective, section: SectionPlan
) -> list[FeedbackItem]:
    """The one relationship with a decidable contract: unison.

    Duet, canon and the rest are relationships between texts that only a reader
    can judge; "the same words" is arithmetic.
    """
    if directive.relationship != "unison" or len(lyrics.voices) < 2:
        return []

    first, *rest = lyrics.voices
    expected = [line.text for line in first.lines]
    for voice in rest:
        if [line.text for line in voice.lines] != expected:
            return [
                _item(
                    section.section_id,
                    voice.voice_id,
                    message=(
                        f"section {section.section_id} sings in unison, so "
                        f"{voice.voice_id} needs the same words as "
                        f"{first.voice_id}, and it has different ones"
                    ),
                )
            ]
    return []


def _check_refrain(
    lyrics: SectionLyrics,
    directive: SectionLyricDirective,
    section: SectionPlan,
    refrain_source: SectionLyrics | None,
) -> list[FeedbackItem]:
    if directive.refrain_of is None or refrain_source is None:
        return []

    for voice in lyrics.voices:
        # Against *any* of the source's voices, not just its own line. A chorus
        # where the harmony voice comes back doubling the lead is bringing the
        # words back — more of them, in fact — and checking each voice against
        # only its own part called that a failure.
        if not any(
            _brings_back(voice, original) for original in refrain_source.voices
        ):
            return [
                _item(
                    section.section_id,
                    voice.voice_id,
                    message=(
                        f"section {section.section_id} is a refrain of "
                        f"{directive.refrain_of}, so {voice.voice_id} sings words "
                        "from that section again — its own line there, or another "
                        f'voice\'s. Its line there was: "'
                        + (
                            refrain_source.by_voice[voice.voice_id].text
                            if voice.voice_id in refrain_source.by_voice
                            else refrain_source.voices[0].text
                        )
                        + '". If this section has more music, bring them back in '
                        "full first and then carry on."
                    ),
                )
            ]
    return []


def _brings_back(voice: VoiceLyrics, original: VoiceLyrics) -> bool:
    """Whether a refrain reprises its source.

    The shorter of the two must be a contiguous run of the longer, which is
    symmetric on purpose. A final chorus with extra bars repeats the hook and
    carries on; a short reprise sings as much of it as it has room for and
    stops. Both are what a refrain does, and equality rejected both — measured,
    on three separate pieces, each of which had reprised its words correctly.

    What it still catches is the real failure: a section declared a refrain
    that sings something else.
    """
    words, wanted = _words(voice), _words(original)
    if not wanted or not words:
        return True
    longer, shorter = (words, wanted) if len(words) >= len(wanted) else (wanted, words)
    return any(
        longer[start : start + len(shorter)] == shorter
        for start in range(len(longer) - len(shorter) + 1)
    )


def _words(voice: VoiceLyrics) -> list[str]:
    return [word for line in voice.lines for word in line.words]


def _check_scheme(
    lyrics: SectionLyrics, directive: SectionLyricDirective, section: SectionPlan
) -> list[FeedbackItem]:
    assert directive.rhyme_scheme is not None
    feedback: list[FeedbackItem] = []
    for voice in lyrics.voices:
        endings = [line.words for line in voice.lines]
        for problem in scheme_violations(endings, directive.rhyme_scheme):
            feedback.append(
                _item(
                    section.section_id,
                    voice.voice_id,
                    message=f"in the {voice.voice_id} words, {problem}",
                )
            )
    return feedback


def _note_count(lily_music: str) -> int:
    """Roughly how many notes a fragment has, for a feedback message only.

    A token count, never a parse, and never used to decide anything — the
    compiler owns that verdict. It is here because "23 syllables against about
    18 notes" is actionable and "they do not line up" is not.
    """
    count = 0
    for token in lily_music.replace("|", " ").split():
        head = token.lstrip("<").rstrip(">~([)]")
        if head[:1].isalpha() and head[:1] != "r" and not head.startswith("\\"):
            count += 1
    return count



def _singing_voices(section: SectionPlan, spec: PieceSpec) -> list[str]:
    """Which of a section's active voices sing (see `app/compose.py` for the
    active-voice resolution this mirrors)."""
    singing = {voice.voice_id for voice in spec.singing_voices}
    if not section.active_voices:
        return sorted(singing)

    named: set[str] = set()
    for ref in section.active_voices:
        if isinstance(ref, str):
            named.add(ref)
        else:
            named |= {
                voice.voice_id for voice in spec.voices if voice.group == ref.group
            }
    return sorted(named & singing)


def _item(
    section_id: SectionId,
    voice_id: str,
    *,
    message: str,
    evidence: str | None = None,
) -> FeedbackItem:
    return FeedbackItem(
        source=SOURCE,
        level="lyric",
        section_id=section_id,
        voice_id=voice_id,
        message=message,
        evidence=evidence,
    )


def _plan_item(message: str, *, section_id: SectionId | None = None) -> FeedbackItem:
    return FeedbackItem(
        source=PLAN_SOURCE, level="lyric", section_id=section_id, message=message
    )
