"""The musician-surface contract.

Principle 2 in docs/08 is a hard requirement, so it gets tests: what an LLM
reads speaks bars, beats, note names and textbook LilyPond, and internal
coordinates never leak outward. The capability-gating rule gets tests too —
mentioning a capability is an invitation to use it, so the surface must stay
silent about what a piece does not need (docs/04).
"""

from fractions import Fraction

import pytest

from cadenzra.common.errors import LLMOutputError
from cadenzra.llm.parsers.voice import parse_voice_part
from cadenzra.llm.prompts.surface import (
    chord_chart,
    dynamics_text,
    position_text,
    range_text,
    rhythmic_cells_text,
)
from cadenzra.llm.prompts.voice import SYSTEM_PROMPT, build_voice_prompt
from cadenzra.llm.schemas.voice import write_part_schema
from cadenzra.model.contexts import MaterialInstruction, VoiceContext
from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
from cadenzra.model.motif import Motif
from cadenzra.model.primitives.meter import MeterSpec, MeterTerm, simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import VoiceSpec
from cadenzra.model.structure import (
    DynamicsPlan,
    DynTarget,
    MaterialEntry,
    SectionPlan,
)
from cadenzra.model.style import RhythmicCell, StylePack
from cadenzra.model.voice import VoicePart

SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])
ADDITIVE = MeterSpec(
    terms=[MeterTerm(numerator=3, denominator=4), MeterTerm(numerator=1, denominator=8)]
)

ALTO = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=5),
    midi_program=52,
)
SOPRANO_SINGING = ALTO.model_copy(update={"voice_id": "soprano", "lyrics": True})

SECTION = SectionPlan(
    section_id="A",
    bars=4,
    meter=SEVEN_EIGHT,
    key="d phrygian",
    tempo_bpm=96,
    texture="imitative",
    dynamics=DynamicsPlan(start="pp", targets=[DynTarget(bar=3, level="ff")]),
    active_voices=["alto"],
    intent="build from stillness",
)

STYLE = StylePack(
    idioms=["Phrygian coloring", "rhythmic unison in heavy passages"],
    rhythmic_cells=[
        RhythmicCell(meter=SEVEN_EIGHT, lily="c8 c c c c c4", description="driving 2+2+3"),
        RhythmicCell(meter=simple_meter(4, 4), lily="c4 c c c", description="plain four"),
    ],
    harmony_guidance="modal, avoid leading tones",
)


def _ctx(**overrides: object) -> VoiceContext:
    base = VoiceContext(section=SECTION, voice=ALTO, style=STYLE)
    return base.model_copy(update=overrides)


def test_offsets_are_rendered_as_bars_and_beats() -> None:
    assert position_text(Fraction(0), SEVEN_EIGHT) == "bar 1, beat 1"
    assert position_text(Fraction(7, 8), SEVEN_EIGHT) == "bar 2, beat 1"
    assert position_text(Fraction(3, 8), simple_meter(4, 4)) == "bar 1, beat 2.5"


def test_a_range_shows_both_spellings_the_generator_needs() -> None:
    text = range_text(ALTO)

    assert "G3" in text
    assert "c''" in text


def test_a_dynamics_arc_reads_as_a_sentence() -> None:
    assert dynamics_text(SECTION.dynamics) == "begin pp, then reach ff by bar 3"
    assert dynamics_text(DynamicsPlan(start="mf")) == "stay around mf"


def test_harmony_is_shown_as_a_bar_by_bar_chord_chart() -> None:
    skeleton = HarmonicSkeleton(
        section_id="A",
        events=[
            HarmonicEvent(offset=Fraction(0), duration=Fraction(7, 8), chord="Dm"),
            HarmonicEvent(offset=Fraction(7, 8), duration=Fraction(4, 8), chord="Esus4"),
            HarmonicEvent(offset=Fraction(11, 8), duration=Fraction(3, 8), chord="Bb"),
        ],
    )

    chart = chord_chart(skeleton, SEVEN_EIGHT)

    assert "bar 1: Dm" in chart
    assert "bar 2: Esus4 | Bb (beat 5)" in chart
    assert "7/8" not in chart
    assert "Fraction" not in chart


def test_only_the_cells_for_this_meter_are_shown() -> None:
    text = rhythmic_cells_text(STYLE, SEVEN_EIGHT)

    assert "driving 2+2+3" in text
    assert "plain four" not in text


def test_the_prompt_speaks_the_musician_register() -> None:
    prompt = build_voice_prompt(_ctx())

    assert "7/8 (2+2+3)" in prompt
    assert "bar" in prompt
    assert "Fraction" not in prompt
    assert "offset" not in prompt
    assert "pc12" not in prompt


def test_the_fragment_contract_lives_in_the_system_prompt() -> None:
    """The conventions never change across a piece, so paying for them in the
    user prompt on every one of hundreds of voice calls was the audit's
    "a system prompt billed as a user prompt". The user turn keeps only the
    per-meter clauses."""
    prompt = build_voice_prompt(_ctx())

    assert "bar check" in SYSTEM_PROMPT
    assert "\\relative" in SYSTEM_PROMPT
    assert "explicit duration" in SYSTEM_PROMPT.lower()
    assert "\\relative" not in prompt
    assert "Write the part under these conventions" not in prompt


def test_the_prompt_reads_piece_wide_then_section_then_voice() -> None:
    """Invariant-first ordering is what gives repeated calls a shared prefix —
    a cache can only key on what comes first."""
    prompt = build_voice_prompt(_ctx())

    style_at = prompt.index("driving 2+2+3")  # piece-wide: rhythmic cells
    section_at = prompt.index("Section A")  # section-wide brief
    task_at = prompt.index("Write the alto part")  # voice-specific

    assert style_at < section_at < task_at


def test_the_prompt_spells_out_an_odd_meters_grouping() -> None:
    prompt = build_voice_prompt(_ctx())

    assert "7 eighths" in prompt
    assert "2+2+3" in prompt


def test_additive_meters_get_their_own_explanation() -> None:
    prompt = build_voice_prompt(
        _ctx(section=SECTION.model_copy(update={"meter": ADDITIVE}))
    )

    assert "additive meter" in prompt
    assert "3/4 plus 1/8" in prompt


def test_a_simple_meter_gets_no_additive_or_grouping_noise() -> None:
    """Capability gating: a 4/4 section must not be told about groupings or
    additive meters it has no use for (docs/04)."""
    prompt = build_voice_prompt(
        _ctx(section=SECTION.model_copy(update={"meter": simple_meter(4, 4)}))
    )

    assert "additive" not in prompt
    assert "felt as" not in prompt


def test_techniques_are_not_mentioned_unless_the_piece_uses_them() -> None:
    """Mentioning a capability is an invitation to use it (docs/04)."""
    prompt = build_voice_prompt(_ctx())

    assert "sul pont." not in prompt
    assert "vocal fry" not in prompt


def test_a_singing_voice_is_told_its_words_come_later() -> None:
    """Words are written afterwards, against the finished music and for every
    singer at once, so the voice call never writes them (docs/10)."""
    instrumental = build_voice_prompt(_ctx())
    singing = build_voice_prompt(_ctx(voice=SOPRANO_SINGING))

    assert "lyricmode" not in instrumental and "sung" not in instrumental
    assert "This part is sung" in singing
    assert "written afterwards" in singing
    assert "lyricmode" not in singing


def test_a_motif_travels_as_notation_with_an_instruction_not_an_id() -> None:
    """The id is bookkeeping for validators; the notes are for the composer
    (docs/03)."""
    instruction = MaterialInstruction(
        motif=Motif(motif_id="subject", role="fugue subject", lily_music="d'4 a'4 f'8 e'8"),
        entry=MaterialEntry(
            motif_id="subject", voice_id="alto", bar=2, relation="P5 up"
        ),
    )

    prompt = build_voice_prompt(_ctx(materials=[instruction]))

    assert "d'4 a'4 f'8 e'8" in prompt
    assert "bar 2" in prompt
    assert "P5 up" in prompt
    assert "fugue subject" in prompt


def test_a_regeneration_prompt_carries_the_rejection_and_the_rehearsal_notes() -> None:
    from cadenzra.model.feedback import FeedbackItem

    rejected = VoicePart(section_id="A", voice_id="alto", lily_music="a'8 a' b'4 |")
    note = FeedbackItem(
        source="validate_voice",
        level="voice",
        section_id="A",
        voice_id="alto",
        message="bar 1 does not fill 7/8 (2+2+3); it is off by 3/8",
    )

    prompt = build_voice_prompt(_ctx(rejected=rejected, feedback=[note]))

    assert "a'8 a' b'4 |" in prompt
    assert "off by 3/8" in prompt
    assert "as little else as possible" in prompt


def test_a_fresh_start_keeps_the_lesson_but_withholds_the_text() -> None:
    """Shown its own rejected music, the model reproduces it nearly verbatim —
    mistake included (orchestra: three ~1400-token identical rewrites). A
    from-scratch regeneration carries the feedback without the copyable text,
    and never asks for minimal change."""
    from cadenzra.model.feedback import FeedbackItem

    note = FeedbackItem(
        source="validate_voice",
        level="voice",
        section_id="A",
        voice_id="alto",
        message="bar 1 does not fill 7/8 (2+2+3); it is off by 3/8",
    )

    prompt = build_voice_prompt(_ctx(rejected=None, feedback=[note]))

    assert "off by 3/8" in prompt, "feedback reaches the regeneration"
    assert "as little else as possible" not in prompt
    assert "discarded" in prompt.lower()


def test_the_schema_shows_only_the_fields_the_piece_needs() -> None:
    plain = write_part_schema(techniques=False)
    extended = write_part_schema(techniques=True)

    assert set(plain["parameters"]["properties"]) == {"lily_music"}
    assert "techniques" in extended["parameters"]["properties"]
    assert "lily_lyrics" not in extended["parameters"]["properties"]


def test_no_internal_type_ever_reaches_a_schema() -> None:
    """A `Fraction` in a tool schema would put the internal register in front
    of the model — the one thing the seam exists to prevent (docs/06)."""
    rendered = str(write_part_schema(techniques=True))

    assert "Fraction" not in rendered
    assert "offset" not in rendered


def test_a_tool_call_parses_into_a_voice_part() -> None:
    part = parse_voice_part(
        {"lily_music": " a'8 a' b' b' c''4. | ", "lily_lyrics": "Sing the mea -- sure"},
        section_id="A",
        voice_id="alto",
    )

    assert part.lily_music == "a'8 a' b' b' c''4. |"
    assert part.lily_lyrics == "\\lyricmode { Sing the mea -- sure }"


def test_lyrics_already_wrapped_are_left_alone() -> None:
    part = parse_voice_part(
        {"lily_music": "a'4 |", "lily_lyrics": "\\lyricmode { one two }"},
        section_id="A",
        voice_id="alto",
    )

    assert part.lily_lyrics == "\\lyricmode { one two }"


@pytest.mark.parametrize("payload", [{}, {"lily_music": ""}, {"lily_music": 7}])
def test_a_response_without_notation_raises_rather_than_defaulting(
    payload: dict[str, object],
) -> None:
    with pytest.raises(LLMOutputError):
        parse_voice_part(payload, section_id="A", voice_id="alto")


def test_an_unknown_technique_raises_rather_than_being_dropped() -> None:
    with pytest.raises(LLMOutputError, match="does not know"):
        parse_voice_part(
            {
                "lily_music": "a'4 |",
                "techniques": [{"technique": "col legno tratto", "from_bar": 1}],
            },
            section_id="A",
            voice_id="alto",
        )


def test_every_regenerating_layer_shows_the_model_why_it_was_rejected() -> None:
    """A regeneration that cannot see the rejection reason repeats the mistake,
    slightly rephrased, until the budget runs out. This was a real bug: the
    motif layer built its prompt without ever reading `MotifContext.feedback`,
    so a subject too high for its answer stayed too high for three attempts."""
    from cadenzra.llm.prompts.structured import (
        build_harmony_prompt,
        build_motif_prompt,
        build_plan_prompt,
    )
    from cadenzra.model.feedback import FeedbackItem
    from cadenzra.model.spec import PieceSpec
    from cadenzra.model.structure import MaterialBrief, StructurePlan

    note = FeedbackItem(
        source="validate_motifs",
        level="motif",
        message="the cello entry at bar 13 would reach A4, above the cello ceiling of G4",
    )
    spec = PieceSpec(
        title="T",
        style_prompt="s",
        voices=[ALTO],
        meters_allowed=[SEVEN_EIGHT],
        target_minutes=1.0,
    )
    plan = StructurePlan(sections=[SECTION])
    briefs = [MaterialBrief(motif_id="subject", role="fugue subject", description="")]

    prompts = [
        build_plan_prompt(spec, STYLE, [note]),
        build_motif_prompt(briefs, spec, STYLE, plan, [note]),
        build_harmony_prompt(SECTION, STYLE, [], None, None, [note]),
    ]

    for prompt in prompts:
        assert "above the cello ceiling of G4" in prompt
        assert "as little else as possible" in prompt


def test_each_motif_is_told_the_meter_it_will_be_checked_in() -> None:
    """The prompt said "Write in 7/8" once for the whole batch while the
    validator checked each motif in its own declaring section's meter — an
    instruction no model could satisfy for a hook declared in 4/4, and
    metal-kpop burned eight straight motif rejections on it, identically
    across model tiers. Each brief now names its own meter, from the same
    lookup the validator uses."""
    from cadenzra.llm.prompts.structured import build_motif_prompt
    from cadenzra.model.spec import PieceSpec
    from cadenzra.model.structure import (
        DynamicsPlan,
        MaterialBrief,
        MaterialEntry,
        SectionPlan,
        StructurePlan,
    )

    seven = SECTION.model_copy(
        update={
            "material": [
                MaterialEntry(motif_id="chug", voice_id="alto", bar=1, relation="exact")
            ]
        }
    )
    four = SectionPlan(
        section_id="B",
        bars=4,
        meter=simple_meter(4, 4),
        key="c major",
        tempo_bpm=120,
        texture="homophonic",
        dynamics=DynamicsPlan(start="mf"),
        active_voices=["alto"],
        material=[
            MaterialEntry(motif_id="hook", voice_id="alto", bar=1, relation="exact")
        ],
    )
    spec = PieceSpec(
        title="T",
        style_prompt="s",
        voices=[ALTO],
        meters_allowed=[SEVEN_EIGHT, simple_meter(4, 4)],
        target_minutes=1.0,
    )
    briefs = [
        MaterialBrief(motif_id="chug", role="riff", description="a chug"),
        MaterialBrief(motif_id="hook", role="theme", description="a hook"),
    ]

    prompt = build_motif_prompt(briefs, spec, STYLE, StructurePlan(sections=[seven, four]))

    chug_line = next(line for line in prompt.splitlines() if "chug (" in line)
    hook_line = next(line for line in prompt.splitlines() if "hook (" in line)
    assert "7/8" in chug_line, "the riff is written and checked in 7/8"
    assert "4/4" in hook_line, "the hook is written and checked in 4/4"


def test_barlines_in_lyrics_are_removed_not_carried_through() -> None:
    """A model mirroring the music's barlines into its lyrics writes bar checks
    that pass inside a single-section scaffold and then fail once sections are
    concatenated — that is a real run where every part compiled alone and the
    assembled score did not. Lyrics gain nothing from bar checks."""
    part = parse_voice_part(
        {
            "lily_music": "a'4 a' a' a' |",
            "lily_lyrics": "Clang crush break the dark | Rise up sound the horn |",
        },
        section_id="A",
        voice_id="bass",
    )

    assert part.lily_lyrics is not None
    assert "|" not in part.lily_lyrics
    assert "Clang crush break the dark Rise up sound the horn" in part.lily_lyrics
    # The music's own bar checks are untouched: they are the meter validator.
    assert part.lily_music.count("|") == 1


def test_the_motif_prompt_asks_for_one_line_per_brief_not_one_per_voice() -> None:
    """A brief carried by three voices came back as three per-voice variants —
    `theme_lead`, `theme_keys`, `theme_harmony` — and the one theme the plan
    asked for did not exist."""
    from cadenzra.llm.prompts.structured import build_motif_prompt
    from cadenzra.model.spec import PieceSpec
    from cadenzra.model.structure import MaterialBrief, StructurePlan

    brief = MaterialBrief(
        motif_id="salt_declamation",
        role="theme",
        description="a declamatory line",
        carrying_voices=["alto"],
    )
    spec = PieceSpec(
        title="T",
        style_prompt="x",
        voices=[ALTO],
        meters_allowed=[SEVEN_EIGHT],
        target_minutes=1.0,
    )
    plan = StructurePlan(sections=[SECTION], materials_needed=[brief])

    prompt = build_motif_prompt([brief], spec, StylePack(), plan)

    assert "One id, one line, no variants." in prompt
    assert "not how many versions to write" in prompt


def test_the_motif_prompt_shows_a_bar_that_actually_fills_its_meter() -> None:
    """The ranges above it are shown as `C3 (c) up to A4 (a')`, and a model
    reading the scientific half writes `b3 4 fis4 8`. A worked example fixes
    what the instruction alone does not — but only if the example is right."""
    from cadenzra.llm.prompts.structured import _motif_example
    from cadenzra.model.primitives.meter import MeterTerm

    assert _motif_example(SEVEN_EIGHT).count("8") == 7
    assert _motif_example(simple_meter(4, 4)) == "d'4 e'4 f'4 g'4 |"

    additive = MeterSpec(
        terms=[MeterTerm(numerator=3, denominator=4), MeterTerm(numerator=1, denominator=8)]
    )
    assert _motif_example(additive) == "d'4 e'4 f'4 g'8 |"


def test_a_bad_style_pack_does_not_end_the_run() -> None:
    """One mistyped meter in one rhythmic cell — "3/3" where the piece allows
    3/4 — ended a twelve-voice run before it had written a note."""
    from pathlib import Path

    from cadenzra.app.config import RetryBudgets
    from cadenzra.app.pipeline import LayerServices, derive_style
    from cadenzra.common.errors import LLMOutputError
    from cadenzra.model.spec import PieceSpec
    from cadenzra.model.state import PipelineState

    calls = {"n": 0}

    class _Flaky:
        def derive_style_pack(self, spec: object) -> StylePack:
            calls["n"] += 1
            if calls["n"] == 1:
                raise LLMOutputError("'3/3' is not one of this piece's meters (4/4)")
            return StylePack(idioms=["second time lucky"])

        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"derive_style should not call {name}")

    spec = PieceSpec(
        title="T",
        style_prompt="x",
        voices=[ALTO],
        meters_allowed=[SEVEN_EIGHT],
        target_minutes=1.0,
    )
    services = LayerServices(
        generator=_Flaky(),  # type: ignore[arg-type]
        renderer=None,  # type: ignore[arg-type]
        workdir=Path("/tmp/unused"),
        budgets=RetryBudgets(),
    )

    state = derive_style(PipelineState(spec=spec), services)

    assert calls["n"] == 2
    assert state.style is not None and state.style.idioms == ["second time lucky"]


def test_a_cross_voice_repair_is_shown_the_lines_it_must_fit_against() -> None:
    """A part told "you move in parallel octaves with the viola" and not shown
    the viola is being asked to fix a relationship it cannot see."""
    plain = build_voice_prompt(_ctx())
    repairing = build_voice_prompt(_ctx(siblings={"viola": "c4 d4 e4 f4 |"}))

    assert "other voices in this section" not in plain
    assert "c4 d4 e4 f4 |" in repairing
    assert "viola" in repairing
    assert "yours is the line that moves" in repairing
