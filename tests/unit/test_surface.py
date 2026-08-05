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
from cadenzra.llm.prompts.voice import build_voice_prompt
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


def test_the_prompt_states_the_fragment_contract() -> None:
    prompt = build_voice_prompt(_ctx())

    assert "bar check" in prompt
    assert "\\relative" in prompt
    assert "explicit duration" in prompt.lower()


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


def test_lyrics_are_asked_for_only_from_a_singing_voice() -> None:
    assert "lyricmode" not in build_voice_prompt(_ctx())
    assert "lyricmode" in build_voice_prompt(_ctx(voice=SOPRANO_SINGING))


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


def test_the_schema_shows_only_the_fields_the_piece_needs() -> None:
    plain = write_part_schema(lyrics=False, techniques=False)
    singing = write_part_schema(lyrics=True, techniques=False)

    assert set(plain["parameters"]["properties"]) == {"lily_music"}
    assert "lily_lyrics" in singing["parameters"]["properties"]
    assert "lily_lyrics" in singing["parameters"]["required"]


def test_no_internal_type_ever_reaches_a_schema() -> None:
    """A `Fraction` in a tool schema would put the internal register in front
    of the model — the one thing the seam exists to prevent (docs/06)."""
    rendered = str(write_part_schema(lyrics=True, techniques=True))

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
