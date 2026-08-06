"""A sung piece, end to end, with the real compiler.

What this pins is the thing that was structurally missing (docs/10): the words
for a section are written **once, for every singing voice**, so they cannot
disagree with each other — and they reach the engraved score through the same
`\\lyricsto` path they always did, without disturbing the channel invariant
every per-voice mechanism rests on.
"""

from fractions import Fraction
from pathlib import Path

import mido
import pytest

from cadenzra.app.compose import ComposeServices, compose
from cadenzra.app.config import RetryBudgets
from cadenzra.common.runlog import RunLog
from cadenzra.llm.parsers.lyrics import render_lyricmode, tokenize_line
from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
from cadenzra.model.lyrics import (
    LyricPlan,
    SectionLyricDirective,
    SectionLyrics,
    VoiceLyrics,
)
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import LyricsSpec, PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState
from cadenzra.model.structure import DynamicsPlan, SectionPlan, StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.rendering.fluidsynth import FluidsynthAdapter
from cadenzra.rendering.lilypond import LilypondAdapter
from cadenzra.verification.midi_analysis import channel_track_invariant_ok
from tests.fakes.generator import ScriptedGenerator

pytestmark = pytest.mark.integration

FOUR_FOUR = simple_meter(4, 4)

SOPRANO = VoiceSpec(
    voice_id="soprano",
    kind="vocal",
    range_low=Pitch(step="C", octave=4),
    range_high=Pitch(step="G", octave=5),
    midi_program=52,
    lyrics=True,
)
ALTO = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=5),
    midi_program=52,
    lyrics=True,
)

SPEC = PieceSpec(
    title="Sung",
    style_prompt="a plain hymn",
    voices=[SOPRANO, ALTO],
    meters_allowed=[FOUR_FOUR],
    target_minutes=0.09,
    tempo_bpm=90,
    lyrics=LyricsSpec(language="English", brief="light on water"),
)

SECTIONS = [
    SectionPlan(
        section_id="A",
        bars=2,
        meter=FOUR_FOUR,
        key="d minor",
        tempo_bpm=90,
        texture="homophonic",
        dynamics=DynamicsPlan(start="mp"),
        active_voices=["soprano", "alto"],
    ),
]
PLAN = StructurePlan(sections=SECTIONS, form_summary="one verse")

FRAGMENTS = {
    ("A", "soprano"): "d''4 d''4 e''4 f''4 |\ne''4 e''4 d''2 |",
    ("A", "alto"): "a'4 a'4 g'4 f'4 |\ng'4 g'4 a'2 |",
}

LYRIC_PLAN = LyricPlan(
    language="English",
    story="light moves across water and is gone",
    directives=[
        SectionLyricDirective(
            section_id="A",
            story_beat="the light arrives on the water",
            relationship="unison",
            rhyme_scheme="AA",
        )
    ],
)


def _voice_lyrics(voice_id: str, text: str) -> VoiceLyrics:
    lines = [tokenize_line(line) for line in text.splitlines()]
    return VoiceLyrics(
        voice_id=voice_id, lines=lines, lily_lyrics=render_lyricmode(lines)
    )


# Eight notes per voice, eight syllables, and the two lines rhyme — so the
# scheme the directive declared actually holds.
WORDS = "the light falls on the sea\nand turns to gold for me"

SECTION_LYRICS = {
    "A": SectionLyrics(
        section_id="A",
        voices=[
            _voice_lyrics("soprano", WORDS),
            _voice_lyrics("alto", WORDS),
        ],
    )
}


def _skeletons() -> list[HarmonicSkeleton]:
    return [
        HarmonicSkeleton(
            section_id="A",
            events=[
                HarmonicEvent(offset=Fraction(0), duration=Fraction(1), chord="Dm"),
                HarmonicEvent(offset=Fraction(1), duration=Fraction(1), chord="Dm"),
            ],
        )
    ]


@pytest.fixture(scope="module")
def sung(tmp_path_factory: pytest.TempPathFactory) -> tuple[PipelineState, Path]:
    out = tmp_path_factory.mktemp("sung")
    runlog = RunLog(out / "runs" / "test")
    generator = ScriptedGenerator(
        by_voice=FRAGMENTS,
        style=StylePack(parallel_fifths_policy="allow"),
        plans=[PLAN],
        skeletons=_skeletons(),
        lyric_plans=[LYRIC_PLAN],
        lyrics=SECTION_LYRICS,
    )
    services = ComposeServices(
        generator=generator,
        renderer=LilypondAdapter(runlog=runlog),
        workdir=out / "work",
        budgets=RetryBudgets(),
        runlog=runlog,
        synthesizer=FluidsynthAdapter(),
        output_dir=out,
    )
    return compose(SPEC, services), out


def test_one_lyric_call_covers_every_singing_voice(
    sung: tuple[PipelineState, Path],
) -> None:
    """The coordination mechanism itself: one writer, one text, so two voices
    cannot end up in two languages (docs/10)."""
    state, _ = sung

    assert set(state.lyrics) == {"A"}
    assert [voice.voice_id for voice in state.lyrics["A"].voices] == [
        "soprano",
        "alto",
    ]


def test_the_words_reach_the_engraved_score(
    sung: tuple[PipelineState, Path],
) -> None:
    state, _ = sung
    assert state.score is not None
    source = state.score.lily_source

    assert '\\lyricsto "soprano"' in source
    assert '\\lyricsto "alto"' in source
    assert "the light falls on the sea" in source.replace(" -- ", "")


def test_the_words_are_carried_by_the_parts_assembly_reads(
    sung: tuple[PipelineState, Path],
) -> None:
    """The lyric layer writes `SectionLyrics`; assembly knows only about
    `VoicePart.lily_lyrics`. The copy across is what keeps assembly unchanged."""
    state, _ = sung

    for voice_id in ("soprano", "alto"):
        part = state.voice_part("A", voice_id)
        assert part.lily_lyrics is not None
        assert "lyricmode" in part.lily_lyrics


def test_lyrics_do_not_disturb_the_channel_invariant(
    sung: tuple[PipelineState, Path],
) -> None:
    """Every `Lyrics` context consumes a channel number, so channels are
    distinct but not contiguous (docs/03). Per-voice analysis depends on the
    invariant surviving that."""
    state, _ = sung
    artifacts = state.artifacts
    assert artifacts is not None

    assert channel_track_invariant_ok(mido.MidiFile(artifacts.score_midi_path))


def test_the_run_writes_the_lyric_plan_into_its_state(
    sung: tuple[PipelineState, Path],
) -> None:
    state, out = sung

    assert state.lyric_plan is not None
    assert state.lyric_plan.language == "English"
    round_tripped = PipelineState.model_validate_json(
        (out / "state.json").read_text()
    )
    assert round_tripped.lyric_plan is not None
    assert round_tripped.lyrics["A"].voices[0].text.startswith("the light")
