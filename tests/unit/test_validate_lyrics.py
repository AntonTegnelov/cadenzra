"""What the lyric validators decide — and what they refuse to.

The boundary is the design (docs/10): declared contracts are checked here,
alignment belongs to the compiler, and craft belongs to a reader. A test that
asserted "these words are good" would be asserting the thing this module is
built not to do.
"""

from pathlib import Path

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
from cadenzra.model.spec import LyricsSpec, PieceSpec, VoiceSpec
from cadenzra.model.structure import DynamicsPlan, SectionPlan, StructurePlan
from cadenzra.model.voice import VoicePart
from cadenzra.verification.lyrics import (
    missing_devices,
    validate_lyric_plan,
    validate_section_lyrics,
)

FOUR_FOUR = simple_meter(4, 4)


def _voice(voice_id: str, *, sings: bool = True) -> VoiceSpec:
    return VoiceSpec(
        voice_id=voice_id,
        kind="vocal" if sings else "instrument",
        range_low=Pitch.from_scientific("C3"),
        range_high=Pitch.from_scientific("C6"),
        midi_program=52,
        lyrics=sings,
    )


def _spec(**kwargs: object) -> PieceSpec:
    return PieceSpec(
        title="Test",
        style_prompt="anything",
        voices=[_voice("soprano"), _voice("alto")],
        meters_allowed=[FOUR_FOUR],
        target_minutes=1.0,
        **kwargs,  # type: ignore[arg-type]
    )


def _section(section_id: str = "A") -> SectionPlan:
    return SectionPlan(
        section_id=section_id,
        bars=2,
        meter=FOUR_FOUR,
        key="d minor",
        tempo_bpm=90,
        texture="homophonic",
        dynamics=DynamicsPlan(start="mp"),
        active_voices=["soprano", "alto"],
    )


def _structure(*section_ids: str) -> StructurePlan:
    return StructurePlan(sections=[_section(s) for s in section_ids])


def _lyrics(section_id: str, **by_voice: list[str]) -> SectionLyrics:
    voices = []
    for voice_id, lines in by_voice.items():
        parsed = [tokenize_line(line) for line in lines]
        voices.append(
            VoiceLyrics(
                voice_id=voice_id, lines=parsed, lily_lyrics=render_lyricmode(parsed)
            )
        )
    return SectionLyrics(section_id=section_id, voices=voices)


class _CleanRenderer:
    """A renderer that compiles anything. Alignment is exercised against the
    real compiler in the integration tests; here the subject is the checks that
    are ours."""

    def compile(self, lily_source: str, workdir: Path) -> CompileResult:
        del lily_source, workdir
        return CompileResult(ok=True, raw_output="")


def _validate(
    lyrics: SectionLyrics,
    directive: SectionLyricDirective,
    *,
    language: str = "English",
    refrain_source: SectionLyrics | None = None,
    tmp_path: Path | None = None,
) -> list[str]:
    parts = {
        voice.voice_id: VoicePart(
            section_id=lyrics.section_id,
            voice_id=voice.voice_id,
            lily_music="c'4 d'4 e'4 f'4 |",
        )
        for voice in lyrics.voices
    }
    feedback = validate_section_lyrics(
        lyrics,
        directive,
        _section(lyrics.section_id),
        parts,
        language=language,
        renderer=_CleanRenderer(),
        workdir=tmp_path or Path("/tmp/unused"),
        refrain_source=refrain_source,
    )
    assert all(item.level == "lyric" for item in feedback)
    return [item.message for item in feedback]


# --- the plan ---------------------------------------------------------


def test_a_sung_section_with_no_brief_is_caught() -> None:
    plan = LyricPlan(
        language="English",
        story="a story",
        directives=[
            SectionLyricDirective(section_id="A", story_beat="opening")
        ],
    )

    feedback = validate_lyric_plan(plan, _structure("A", "B"), _spec())

    assert len(feedback) == 1
    assert "section B is sung" in feedback[0].message


def test_a_brief_for_a_section_nobody_sings_in_is_caught() -> None:
    spec = PieceSpec(
        title="Test",
        style_prompt="anything",
        voices=[_voice("soprano"), _voice("cello", sings=False)],
        meters_allowed=[FOUR_FOUR],
        target_minutes=1.0,
    )
    instrumental = SectionPlan(
        section_id="B",
        bars=2,
        meter=FOUR_FOUR,
        key="d minor",
        tempo_bpm=90,
        texture="solo",
        dynamics=DynamicsPlan(start="mp"),
        active_voices=["cello"],
    )
    plan = LyricPlan(
        language="English",
        story="a story",
        directives=[
            SectionLyricDirective(section_id="A", story_beat="opening"),
            SectionLyricDirective(section_id="B", story_beat="nobody sings this"),
        ],
    )

    feedback = validate_lyric_plan(
        plan, StructurePlan(sections=[_section("A"), instrumental]), spec
    )

    assert any("where nobody sings" in item.message for item in feedback)


def test_a_device_the_piece_asked_for_and_no_section_uses_is_caught() -> None:
    spec = _spec(lyrics=LyricsSpec(devices=["chiasmus", "ekphrasis"]))
    plan = LyricPlan(
        language="English",
        story="a story",
        directives=[
            SectionLyricDirective(
                section_id="A", story_beat="opening", devices=["chiasmus"]
            )
        ],
    )

    feedback = validate_lyric_plan(plan, _structure("A"), spec)

    assert any("ekphrasis" in item.message for item in feedback)


def test_a_plan_that_covers_its_sections_passes() -> None:
    plan = LyricPlan(
        language="English",
        story="a story",
        directives=[
            SectionLyricDirective(section_id="A", story_beat="opening"),
            SectionLyricDirective(section_id="B", story_beat="closing"),
        ],
    )

    assert validate_lyric_plan(plan, _structure("A", "B"), _spec()) == []


# --- the words --------------------------------------------------------


def test_unison_voices_must_sing_the_same_words() -> None:
    """The one relationship with a decidable contract."""
    lyrics = _lyrics(
        "A",
        soprano=["the light falls slow"],
        alto=["a diff -- erent line"],
    )

    problems = _validate(lyrics, SectionLyricDirective(
        section_id="A", story_beat="x", relationship="unison"
    ))

    assert len(problems) == 1
    assert "unison" in problems[0] and "alto" in problems[0]


def test_a_duet_may_sing_different_words() -> None:
    """Duet, canon and the rest are judged by a reader, not here."""
    lyrics = _lyrics(
        "A", soprano=["the light falls slow"], alto=["and I am still here"]
    )

    assert _validate(lyrics, SectionLyricDirective(
        section_id="A", story_beat="x", relationship="duet"
    )) == []


def test_a_refrain_must_bring_the_words_back() -> None:
    source = _lyrics("A", soprano=["the light falls slow"])
    changed = _lyrics("C", soprano=["the light falls fast"])

    problems = _validate(
        changed,
        SectionLyricDirective(
            section_id="C", story_beat="return", refrain_of="A", relationship="solo"
        ),
        refrain_source=source,
    )

    assert len(problems) == 1
    assert "refrain of A" in problems[0]
    assert "the light falls slow" in problems[0]


def test_a_refrain_may_reprise_and_then_carry_on() -> None:
    """A final chorus with more music than the first repeats the hook and
    extends it, which is what a final chorus is for. Demanding exact equality
    rejected one that had reprised every word correctly."""
    source = _lyrics("A", soprano=["the light falls slow"])
    extended = _lyrics(
        "C", soprano=["the light falls slow", "and will not come again"]
    )

    assert _validate(
        extended,
        SectionLyricDirective(
            section_id="C", story_beat="return", refrain_of="A", relationship="solo"
        ),
        refrain_source=source,
    ) == []


def test_a_refrain_may_redistribute_its_words_between_voices() -> None:
    """A chorus where the harmony voice comes back doubling the lead is
    bringing the words back — more of them — and checking each voice against
    only its own earlier line called that a failure."""
    source = _lyrics(
        "A", soprano=["the light falls slow"], alto=["and I am still"]
    )
    doubled = _lyrics(
        "C", soprano=["the light falls slow"], alto=["the light falls slow"]
    )

    assert _validate(
        doubled,
        SectionLyricDirective(
            section_id="C", story_beat="return", refrain_of="A", relationship="unison"
        ),
        refrain_source=source,
    ) == []


def test_a_refrain_that_returns_unchanged_passes() -> None:
    source = _lyrics("A", soprano=["the light falls slow"])
    same = _lyrics("C", soprano=["The light falls slow"])  # casing is not a change

    assert _validate(
        same,
        SectionLyricDirective(
            section_id="C", story_beat="return", refrain_of="A", relationship="solo"
        ),
        refrain_source=source,
    ) == []


def test_a_declared_scheme_is_enforced() -> None:
    lyrics = _lyrics(
        "A",
        soprano=["it falls at night", "and turns to light", "out on the sea", "far from me"],
    )
    broken = _lyrics(
        "A",
        soprano=["it falls at night", "and turns to stone", "out on the sea", "far from me"],
    )
    directive = SectionLyricDirective(
        section_id="A", story_beat="x", rhyme_scheme="AABB", relationship="solo"
    )

    assert _validate(lyrics, directive) == []
    problems = _validate(broken, directive)
    assert len(problems) == 1
    assert "night" in problems[0] and "stone" in problems[0]


def test_a_scheme_is_not_enforced_outside_english() -> None:
    """CMUdict cannot speak for Latin, so the deterministic check stands down
    and the reader takes over (docs/10)."""
    lyrics = _lyrics("A", soprano=["dona nobis pacem", "lux aeterna luceat"])
    directive = SectionLyricDirective(
        section_id="A", story_beat="x", rhyme_scheme="AA", relationship="solo"
    )

    assert _validate(lyrics, directive, language="Latin") == []


def test_no_scheme_means_nothing_to_enforce() -> None:
    """Not every lyric rhymes, and unrequested rhyme is not a contract."""
    lyrics = _lyrics("A", soprano=["the light", "the sea", "the stone"])

    assert _validate(lyrics, SectionLyricDirective(
        section_id="A", story_beat="x", relationship="solo"
    )) == []


# --- blind device observation ----------------------------------------


def test_a_device_nobody_noticed_is_reported() -> None:
    directive = SectionLyricDirective(
        section_id="A", story_beat="x", devices=["chiasmus", "ekphrasis"]
    )
    observed = [DeviceObservation(device="chiasmus", evidence="mirrored line")]

    assert missing_devices(directive, observed) == ["ekphrasis"]


def test_devices_a_reader_found_unprompted_count() -> None:
    directive = SectionLyricDirective(
        section_id="A", story_beat="x", devices=["chiasmus"]
    )
    observed = [
        DeviceObservation(device="chiasmus", evidence="mirrored"),
        DeviceObservation(device="anaphora", evidence="repeated opening"),
    ]

    assert missing_devices(directive, observed) == []
