"""What the lyric prompts show, and — as much — what they withhold.

Two rules are load-bearing here (docs/10):
capability gating, so an instrumental piece never sees a word of the device
vocabulary; and blinding, so the reader asked what a lyric does is never told
what it was supposed to do.
"""

from cadenzra.llm.parsers.lyrics import render_lyricmode, tokenize_line
from cadenzra.llm.prompts.lyrics import (
    build_device_observation_prompt,
    build_lyric_plan_prompt,
    build_lyrics_prompt,
)
from cadenzra.model.contexts import LyricsContext
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.lyrics import (
    DEVICE_VOCABULARY,
    SectionLyricDirective,
    SectionLyrics,
    VoiceLyrics,
)
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import LyricsSpec, PieceSpec, VoiceSpec
from cadenzra.model.structure import DynamicsPlan, SectionPlan, StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.model.voice import VoicePart

FOUR_FOUR = simple_meter(4, 4)

SOPRANO = VoiceSpec(
    voice_id="soprano",
    kind="vocal",
    range_low=Pitch.from_scientific("C4"),
    range_high=Pitch.from_scientific("G5"),
    midi_program=52,
    lyrics=True,
)
CELLO = VoiceSpec(
    voice_id="cello",
    kind="instrument",
    range_low=Pitch.from_scientific("C2"),
    range_high=Pitch.from_scientific("C5"),
    midi_program=42,
)
SECTION = SectionPlan(
    section_id="A",
    bars=2,
    meter=FOUR_FOUR,
    key="d minor",
    tempo_bpm=90,
    texture="homophonic",
    dynamics=DynamicsPlan(start="mp"),
    active_voices=["soprano"],
)
PLAN = StructurePlan(sections=[SECTION])


def _spec(voices: list[VoiceSpec], lyrics: LyricsSpec | None = None) -> PieceSpec:
    return PieceSpec(
        title="Test",
        style_prompt="a dark modal piece",
        voices=voices,
        meters_allowed=[FOUR_FOUR],
        target_minutes=1.0,
        lyrics=lyrics,
    )


def _ctx(**overrides: object) -> LyricsContext:
    base = LyricsContext(
        section=SECTION,
        directive=SectionLyricDirective(section_id="A", story_beat="the light fades"),
        language="English",
        story="a slow disappearance",
        voice_ids=["soprano"],
        parts={
            "soprano": VoicePart(
                section_id="A", voice_id="soprano", lily_music="c'4 d'4 e'4 f'4 |"
            )
        },
    )
    return base.model_copy(update=overrides)


def test_the_language_is_stated_in_every_lyric_prompt() -> None:
    """The whole bug: a language nobody was told (docs/10)."""
    planning = build_lyric_plan_prompt(
        _spec([SOPRANO], LyricsSpec(language="Latin")), StylePack(), PLAN
    )
    writing = build_lyrics_prompt(_ctx(language="Latin"))

    assert "Latin" in planning
    assert "Latin" in writing


def test_a_writer_sees_only_the_devices_its_section_asked_for() -> None:
    """Naming a device is an invitation to use it (docs/08, principle 2)."""
    directive = SectionLyricDirective(
        section_id="A", story_beat="x", devices=["chiasmus"]
    )

    prompt = build_lyrics_prompt(_ctx(directive=directive))

    assert "chiasmus" in prompt
    assert "zeugma" not in prompt
    assert "holorime" not in prompt


def test_a_writer_with_no_devices_sees_no_vocabulary_at_all() -> None:
    prompt = build_lyrics_prompt(_ctx())

    assert not any(device in prompt for device in DEVICE_VOCABULARY)


def test_the_writer_is_shown_the_music_it_is_setting() -> None:
    """Words follow notes, so the notes have to be in front of the writer."""
    prompt = build_lyrics_prompt(_ctx())

    assert "c'4 d'4 e'4 f'4 |" in prompt


def test_the_writer_is_shown_what_has_already_been_sung() -> None:
    earlier = SectionLyrics(
        section_id="Z",
        voices=[
            VoiceLyrics(
                voice_id="soprano",
                lines=[tokenize_line("the wa -- ter rose")],
                lily_lyrics=render_lyricmode([tokenize_line("the wa -- ter rose")]),
            )
        ],
    )

    prompt = build_lyrics_prompt(_ctx(previous=[earlier]))

    assert "the water rose" in prompt


def test_a_rejected_attempt_and_its_notes_reach_the_regeneration() -> None:
    """Feedback that does not reach the next prompt produces the same mistake
    rephrased until the budget runs out (docs/05)."""
    rejected = SectionLyrics(
        section_id="A",
        voices=[
            VoiceLyrics(
                voice_id="soprano",
                lines=[tokenize_line("far too ma -- ny syl -- la -- bles here")],
                lily_lyrics="\\lyricmode { x }",
            )
        ],
    )
    note = FeedbackItem(
        source="validate_lyrics",
        level="lyric",
        section_id="A",
        voice_id="soprano",
        message="9 syllables against roughly 4 notes",
    )

    prompt = build_lyrics_prompt(_ctx(rejected=rejected, feedback=[note]))

    assert "syl -- la -- bles" in prompt
    assert "9 syllables against roughly 4 notes" in prompt


def test_the_scheme_reaches_the_writer_when_one_is_asked_for() -> None:
    directive = SectionLyricDirective(
        section_id="A", story_beat="x", rhyme_scheme="AABB"
    )

    assert "AABB" in build_lyrics_prompt(_ctx(directive=directive))
    assert "AABB" not in build_lyrics_prompt(_ctx())


def test_the_device_reader_is_never_told_what_to_look_for() -> None:
    """A judge given the answer key grades against the key. The observer sees
    the whole vocabulary and no directive at all (docs/05, docs/10)."""
    prompt = build_device_observation_prompt("the light falls slow")

    # Every device, so nothing signals which one was wanted.
    for device in DEVICE_VOCABULARY:
        assert device in prompt
    assert "asked for" not in prompt
    assert "intended" not in prompt


def test_the_planner_is_told_which_devices_the_piece_demands() -> None:
    """The planner is not a judge — it is the one being asked to use them."""
    spec = _spec([SOPRANO], LyricsSpec(devices=["ekphrasis"], brief="a lost city"))

    prompt = build_lyric_plan_prompt(spec, StylePack(), PLAN)

    assert "ekphrasis" in prompt
    assert "a lost city" in prompt
