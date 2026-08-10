"""The craft review: one blinded question per section, advisory only.

docs/10:62 described this check in the present tense while nothing called it —
a design doc asserting a safeguard that never ran. These pin the contract as
designed: fires once the deterministic checks hold, on attempt 1 only, never
names the theme or the devices or the scheme (a reader told what to find
reports finding it), and never vetoes the final attempt.
"""

from pathlib import Path

from cadenzra.app.compose import ComposeServices, _lyrics_to_convergence
from cadenzra.app.config import RetryBudgets
from cadenzra.llm.parsers.lyrics import render_lyricmode, tokenize_line
from cadenzra.model.artifacts import CompileResult
from cadenzra.model.lyrics import (
    DeviceObservation,
    LyricPlan,
    SectionLyricDirective,
    SectionLyrics,
    VoiceLyrics,
)
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.review import ReviewVerdict
from cadenzra.model.spec import LyricsSpec, PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState, voice_key
from cadenzra.model.structure import DynamicsPlan, SectionPlan, StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.model.voice import VoicePart
from tests.fakes.generator import ScriptedGenerator

FOUR_FOUR = simple_meter(4, 4)

SOPRANO = VoiceSpec(
    voice_id="soprano",
    kind="vocal",
    range_low=Pitch.from_scientific("C4"),
    range_high=Pitch.from_scientific("A5"),
    midi_program=52,
    lyrics=True,
)

SECTION = SectionPlan(
    section_id="A",
    bars=1,
    meter=FOUR_FOUR,
    key="c major",
    tempo_bpm=90,
    texture="homophonic",
    dynamics=DynamicsPlan(start="mf"),
    active_voices=["soprano"],
)

DIRECTIVE = SectionLyricDirective(
    section_id="A",
    story_beat="an opening of quiet wonder",
    devices=["polyptoton"],
    rhyme_scheme=None,
)


def _scripted_lyrics(text: str) -> SectionLyrics:
    lines = [tokenize_line(text)]
    return SectionLyrics(
        section_id="A",
        voices=[
            VoiceLyrics(
                voice_id="soprano", lines=lines, lily_lyrics=render_lyricmode(lines)
            )
        ],
    )


class _CleanRenderer:
    def compile(self, lily_source: str, workdir: Path) -> CompileResult:
        del lily_source, workdir
        return CompileResult(ok=True, raw_output="")


def _state() -> PipelineState:
    spec = PieceSpec(
        title="T",
        style_prompt="s",
        voices=[SOPRANO],
        meters_allowed=[FOUR_FOUR],
        target_minutes=4 / 90,
        lyrics=LyricsSpec(language="English", brief="quiet wonder"),
    )
    return PipelineState(
        spec=spec,
        style=StylePack(),
        structure=StructurePlan(sections=[SECTION]),
        lyric_plan=LyricPlan(
            language="English",
            story="a night walk",
            directives=[DIRECTIVE],
        ),
        voices={
            voice_key("A", "soprano"): VoicePart(
                section_id="A", voice_id="soprano", lily_music="c'4 d'4 e'4 f'4 |"
            )
        },
    )


def _services(generator: ScriptedGenerator, tmp_path: Path) -> ComposeServices:
    return ComposeServices(
        generator=generator,
        renderer=_CleanRenderer(),
        workdir=tmp_path,
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )


def _converge(generator: ScriptedGenerator, tmp_path: Path) -> SectionLyrics:
    return _lyrics_to_convergence(
        _state(),
        _services(generator, tmp_path),
        SECTION,
        DIRECTIVE,
        ["soprano"],
        previous=[],
        refrain_source=None,
    )


def test_an_unacceptable_verdict_buys_one_more_attempt(tmp_path: Path) -> None:
    generator = ScriptedGenerator(
        lyrics={"A": _scripted_lyrics("the walk walks on")},
        observations=[DeviceObservation(device="polyptoton", lines=[1])],
        verdicts=[ReviewVerdict(acceptable=False, reasons=["the second line stumbles"])],
    )

    _converge(generator, tmp_path)

    assert len(generator.lyrics_contexts) == 2, "the verdict bought a second attempt"
    second = generator.lyrics_contexts[1]
    assert any(
        "stumbles" in item.message for item in second.feedback
    ), "the reviewer's reason reaches the regeneration"


def test_the_review_fires_once_and_never_exhausts_the_budget(tmp_path: Path) -> None:
    """Attempt 2 passes the same deterministic checks and is not re-reviewed —
    a judgment call must never starve the decidable checks (docs/10)."""
    generator = ScriptedGenerator(
        lyrics={"A": _scripted_lyrics("the walk walks on")},
        observations=[DeviceObservation(device="polyptoton", lines=[1])],
        verdicts=[ReviewVerdict(acceptable=False, reasons=["flat"])],
    )

    result = _converge(generator, tmp_path)

    assert result.section_id == "A", "the run completed despite the verdict"
    assert len(generator.reviews) == 1, "one blinded question, not a budget"


def test_an_acceptable_verdict_ends_the_section_in_one_attempt(tmp_path: Path) -> None:
    generator = ScriptedGenerator(
        lyrics={"A": _scripted_lyrics("the walk walks on")},
        observations=[DeviceObservation(device="polyptoton", lines=[1])],
        verdicts=[ReviewVerdict(acceptable=True)],
    )

    _converge(generator, tmp_path)

    assert len(generator.lyrics_contexts) == 1


def test_the_review_is_blind_to_the_directive(tmp_path: Path) -> None:
    """A reader told what to find reports finding it (docs/05, proven in the
    audio-critic experiment). The question never names the theme, the devices
    or the scheme."""
    generator = ScriptedGenerator(
        lyrics={"A": _scripted_lyrics("the walk walks on")},
        observations=[DeviceObservation(device="polyptoton", lines=[1])],
        verdicts=[ReviewVerdict(acceptable=True)],
    )

    _converge(generator, tmp_path)

    (request,) = generator.reviews
    asked = f"{request.question} {request.context}".lower()
    assert "polyptoton" not in asked
    assert "wonder" not in asked, "the story beat is withheld"
    assert "night walk" not in asked, "the story is withheld"
    assert "the walk walks on" in request.subject, "the words themselves are shown"
