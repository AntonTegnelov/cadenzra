"""The lyric artifacts: what the words are meant to do, and what they became.

Two layers, mirroring the material pattern — a plan-level brief per section
(`SectionLyricDirective`), and the realized text (`SectionLyrics`) written once
the music exists. docs/10 has the reasoning; the shapes here follow it.

Lines are the unit throughout, because lines are what rhyme schemes, refrains
and voice relationships are stated in. A line holds lyricmode tokens exactly as
a writer would type them — `sha -- dow`, `light __` — which is textbook
LilyPond and therefore the surface the model writes best (docs/08, principle 2).
"""

import re
from typing import Final, Literal, Self

from pydantic import BaseModel, Field, model_validator

from cadenzra.model.primitives.ids import SectionId, VoiceId

# A controlled vocabulary so a directive can be checked and an observation can
# be compared against it. Free text would make both impossible.
DEVICE_VOCABULARY: Final[frozenset[str]] = frozenset(
    {
        "objective_correlative",
        "melopoeia",
        "zeugma",
        "anacoluthon",
        "polyptoton",
        "ekphrasis",
        "chiasmus",
        "anaphora",
        "epistrophe",
        "apostrophe",
        "synesthesia",
        "internal_rhyme",
        "mosaic_rhyme",
        "holorime",
        "prosodic_dissonance",
        "refrain",
        "volta",
    }
)

DEVICE_DEFINITIONS: Final[dict[str, str]] = {
    "objective_correlative": (
        "carry the feeling through a concrete object or scene rather than "
        "naming it — the thing stands in for the emotion"
    ),
    "melopoeia": (
        "let the sound of the words do the work: vowel colour and consonant "
        "texture shaped to the music's own sound"
    ),
    "zeugma": "one verb governing two objects that take it differently",
    "anacoluthon": (
        "a sentence that breaks off and restarts in another grammar, as "
        "speech does under pressure"
    ),
    "polyptoton": "the same root returning in different forms — love, loved, loving",
    "ekphrasis": "describing an image or artwork so vividly it stands in the room",
    "chiasmus": "a mirrored structure: A B, then B A",
    "anaphora": "successive lines opening with the same words",
    "epistrophe": "successive lines closing with the same words",
    "apostrophe": "addressing someone or something absent directly",
    "synesthesia": "describing one sense in the terms of another",
    "internal_rhyme": "rhymes inside the line, not only at its end",
    "mosaic_rhyme": "a rhyme where one side is several words — poet / know it",
    "holorime": "two whole lines that sound alike end to end",
    "prosodic_dissonance": (
        "deliberately setting a stressed syllable against a weak beat, for "
        "friction between word and music"
    ),
    "refrain": "words that return unchanged",
    "volta": "a turn — the argument or feeling changes direction here",
}

# Devices a reader can find in the words alone. `prosodic_dissonance` is the
# one that cannot be: it is a relationship between a stressed syllable and a
# weak beat, and the beat is in the music the reader never sees. Asking about
# it from text is not a strict check, it is an unanswerable one (docs/10).
TEXT_OBSERVABLE_DEVICES: Final[frozenset[str]] = DEVICE_VOCABULARY - {
    "prosodic_dissonance"
}

type VoiceRelationship = Literal[
    "unison",
    "duet",
    "canon",
    "call_response",
    "melody_with_harmony",
    "solo",
]

RELATIONSHIP_DEFINITIONS: Final[dict[str, str]] = {
    "unison": "every voice sings the same words at the same time",
    "duet": "two independent texts that answer each other",
    "canon": "the same words entering at staggered times",
    "call_response": "one voice calls, the others answer",
    "melody_with_harmony": (
        "one voice carries the text; the others support it, often on held "
        "vowels or fragments of it"
    ),
    "solo": "one voice sings alone",
}

_SCHEME = re.compile(r"^[A-Zx]+$")


class SectionLyricDirective(BaseModel, frozen=True):
    """What one section's words are for.

    The plan-level brief: written before any lyric exists, so a contradiction
    (a refrain of a section that has not happened, a device nobody knows) is
    caught while it is still cheap to fix.
    """

    section_id: SectionId
    story_beat: str
    devices: list[str] = Field(default_factory=list)
    # A scheme like "AABB" or "ABABx" — one letter per line, `x` for a line
    # that is free. None means no scheme is being enforced here.
    rhyme_scheme: str | None = None
    relationship: VoiceRelationship = "unison"
    refrain_of: SectionId | None = None

    @model_validator(mode="after")
    def _check_directive(self) -> Self:
        unknown = sorted(set(self.devices) - DEVICE_VOCABULARY)
        if unknown:
            raise ValueError(f"unknown lyric device(s): {unknown}")
        if self.rhyme_scheme is not None and not _SCHEME.match(self.rhyme_scheme):
            raise ValueError(
                f"rhyme scheme {self.rhyme_scheme!r} must be capital letters, "
                "with x for a free line — e.g. AABB or ABABx"
            )
        if self.refrain_of == self.section_id:
            raise ValueError(f"section {self.section_id} cannot be a refrain of itself")
        return self


class LyricPlan(BaseModel, frozen=True):
    """The whole piece's words, before any of them are written."""

    language: str
    story: str
    directives: list[SectionLyricDirective] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_plan(self) -> Self:
        seen: list[SectionId] = []
        for directive in self.directives:
            if directive.section_id in seen:
                raise ValueError(f"two directives for section {directive.section_id}")
            if directive.refrain_of is not None and directive.refrain_of not in seen:
                raise ValueError(
                    f"section {directive.section_id} is a refrain of "
                    f"{directive.refrain_of}, which does not come before it"
                )
            seen.append(directive.section_id)
        return self

    @property
    def by_section(self) -> dict[SectionId, SectionLyricDirective]:
        return {directive.section_id: directive for directive in self.directives}


class LyricLine(BaseModel, frozen=True):
    """One line, as lyricmode tokens.

    `["sha", "--", "dow", "falls", "__"]` — stored the way it is written, so
    rendering is a join rather than a reconstruction.
    """

    tokens: list[str]

    @property
    def words(self) -> list[str]:
        """The line as ordinary words, hyphenated syllables rejoined.

        What rhyme checking reads: a rhyme lands on a word, not a syllable.
        """
        words: list[str] = []
        joining = False
        for token in self.tokens:
            if token == "--":
                joining = True
                continue
            if token in ("__", "_"):
                continue
            cleaned = _strip_punctuation(token)
            if not cleaned:
                continue
            if joining and words:
                words[-1] += cleaned
                joining = False
            else:
                words.append(cleaned)
        return words

    @property
    def syllable_count(self) -> int:
        """Syllables as written — every token that is not a joiner or extender.

        This counts the *lyricmode* syllables, which is what a singer reads.
        Whether they line up with the notes is the compiler's answer, not ours
        (docs/10).
        """
        return sum(1 for token in self.tokens if token not in ("--", "__", "_"))

    @property
    def text(self) -> str:
        """The line as prose, for reading and for refrain comparison."""
        return " ".join(self.words)

    def render(self) -> str:
        return " ".join(self.tokens)


class VoiceLyrics(BaseModel, frozen=True):
    """One voice's words for one section, plus the block the score will carry."""

    voice_id: VoiceId
    lines: list[LyricLine] = Field(default_factory=list)
    lily_lyrics: str

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


class SectionLyrics(BaseModel, frozen=True):
    """Every singing voice in one section, written together (docs/10)."""

    section_id: SectionId
    voices: list[VoiceLyrics] = Field(default_factory=list)

    @property
    def by_voice(self) -> dict[VoiceId, VoiceLyrics]:
        return {voice.voice_id: voice for voice in self.voices}


class DeviceObservation(BaseModel, frozen=True):
    """A device a reader noticed, and where.

    Produced blind: the observer is shown the whole vocabulary and never the
    devices that were requested, because a judge given the answer key grades
    against the key (docs/05, docs/10).
    """

    device: str
    lines: list[int] = Field(default_factory=list)
    evidence: str = ""


def _strip_punctuation(token: str) -> str:
    return token.strip(".,;:!?\"'()[]—–-").lower()
