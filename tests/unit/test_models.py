"""Contracts for the artifact models.

The load-bearing one is the JSON round-trip: docs/07 requires the final
`PipelineState` to be written to `out/<run-id>/` as a complete debugging
record, and a state that cannot be read back is not a record. Exact `Fraction`
offsets are the part most likely to degrade.
"""

from fractions import Fraction
from pathlib import Path

import pytest

from cadenzra.model.artifacts import BarCheckWarning, CompileResult, RenderedArtifacts
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
from cadenzra.model.interpretation import ControlChange, InterpretationParams
from cadenzra.model.motif import Motif, MotifLibrary
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState, attempt_key, voice_key
from cadenzra.model.structure import (
    DynamicsPlan,
    DynTarget,
    GroupRef,
    MaterialBrief,
    MaterialEntry,
    SectionPlan,
    StructurePlan,
)
from cadenzra.model.style import RhythmicCell, StylePack
from cadenzra.model.voice import TechniqueSpan, VoicePart

SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])

SOPRANO = VoiceSpec(
    voice_id="soprano",
    kind="vocal",
    range_low=Pitch(step="C", octave=4),
    range_high=Pitch(step="A", octave=5),
    midi_program=52,
    lyrics=True,
)
ALTO = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="D", octave=5),
    midi_program=52,
    lyrics=True,
)

SPEC = PieceSpec(
    title="Test Piece",
    style_prompt="dark, modal, odd meters",
    voices=[SOPRANO, ALTO],
    meters_allowed=[SEVEN_EIGHT],
    target_minutes=2.0,
)


def test_a_voice_range_may_not_be_inverted() -> None:
    with pytest.raises(ValueError, match="above range_high"):
        VoiceSpec(
            voice_id="bass",
            kind="vocal",
            range_low=Pitch(step="C", octave=5),
            range_high=Pitch(step="C", octave=3),
            midi_program=52,
        )


def test_duplicate_voice_ids_are_refused() -> None:
    with pytest.raises(ValueError, match="duplicate voice ids"):
        PieceSpec(
            title="T",
            style_prompt="s",
            voices=[SOPRANO, SOPRANO],
            meters_allowed=[SEVEN_EIGHT],
            target_minutes=1.0,
        )


def test_a_section_may_not_declare_material_outside_its_own_bars() -> None:
    with pytest.raises(ValueError, match="outside its 8 bars"):
        SectionPlan(
            section_id="A",
            bars=8,
            meter=SEVEN_EIGHT,
            key="d minor",
            tempo_bpm=100,
            texture="imitative",
            dynamics=DynamicsPlan(start="p"),
            active_voices=["soprano"],
            material=[
                MaterialEntry(motif_id="subject", voice_id="soprano", bar=9, relation="exact")
            ],
        )


def test_dynamics_targets_must_advance_through_the_section() -> None:
    with pytest.raises(ValueError, match="bar order"):
        DynamicsPlan(
            start="pp", targets=[DynTarget(bar=9, level="ff"), DynTarget(bar=4, level="mf")]
        )


def test_group_references_stay_distinguishable_from_voice_names() -> None:
    section = SectionPlan(
        section_id="A",
        bars=4,
        meter=SEVEN_EIGHT,
        key="d minor",
        tempo_bpm=100,
        texture="antiphonal",
        dynamics=DynamicsPlan(start="mf"),
        active_voices=["soprano", GroupRef(group="ripieno")],
    )

    assert section.voice_ids == ["soprano"]
    assert section.group_names == ["ripieno"]


def test_techniques_outside_the_vocabulary_are_refused() -> None:
    with pytest.raises(ValueError, match="not in the technique vocabulary"):
        TechniqueSpan(technique="col legno tratto", from_bar=1)


def test_a_plan_knows_whether_the_motif_layer_runs() -> None:
    section = SectionPlan(
        section_id="A",
        bars=4,
        meter=SEVEN_EIGHT,
        key="d minor",
        tempo_bpm=100,
        texture="homophonic",
        dynamics=DynamicsPlan(start="mf"),
    )

    assert not StructurePlan(sections=[section]).declares_materials
    assert StructurePlan(
        sections=[section],
        materials_needed=[MaterialBrief(motif_id="subject", role="fugue subject", description="")],
    ).declares_materials


def test_bar_check_warnings_do_not_make_a_compile_clean() -> None:
    warned = CompileResult(
        ok=True,
        bar_check_warnings=[BarCheckWarning(line=12, column=3, message="barcheck failed")],
    )

    assert warned.ok
    assert not warned.clean
    assert CompileResult(ok=True).clean


def test_harmonic_events_reject_impossible_durations() -> None:
    with pytest.raises(ValueError, match="non-positive duration"):
        HarmonicEvent(offset=Fraction(0), duration=Fraction(0), chord="Dm")


def test_a_skeleton_reports_the_chord_sounding_at_an_offset() -> None:
    skeleton = HarmonicSkeleton(
        section_id="A",
        events=[
            HarmonicEvent(offset=Fraction(0), duration=Fraction(7, 8), chord="Dm"),
            HarmonicEvent(offset=Fraction(7, 8), duration=Fraction(7, 8), chord="Esus4"),
        ],
    )

    assert skeleton.chord_at(Fraction(0)) == "Dm"
    assert skeleton.chord_at(Fraction(6, 8)) == "Dm"
    assert skeleton.chord_at(Fraction(7, 8)) == "Esus4"
    assert skeleton.chord_at(Fraction(14, 8)) is None
    assert skeleton.span == Fraction(14, 8)


def test_loop_keys_separate_the_units_that_spend_budget() -> None:
    assert voice_key("A", "soprano") == "A::soprano"
    assert attempt_key("voice", "A", "soprano") == "voice:A:soprano"
    assert attempt_key("harmony", "A", None) == "harmony:A"
    assert attempt_key("structure", None, None) == "structure"


def _full_state() -> PipelineState:
    """A state with every field populated, including the exotic ones."""
    part = VoicePart(
        section_id="A",
        voice_id="soprano",
        lily_music="d''8 d'' d'' e'' e'' f''4 |",
        lily_lyrics="\\lyricmode { one two three four }",
        techniques=[TechniqueSpan(technique="whispered", from_bar=1, to_bar=2)],
    )
    return PipelineState(
        spec=SPEC,
        style=StylePack(
            idioms=["Phrygian coloring"],
            rhythmic_cells=[
                RhythmicCell(meter=SEVEN_EIGHT, lily="c8 c c c c c4", description="2+2+3")
            ],
            parallel_fifths_policy="allow",
            interpretation_defaults=InterpretationParams(
                swing={"A": 0.6},
                voice_offset_ms={"soprano": -12.0},
                technique_mappings={"whispered": ControlChange(controller=11, value=40)},
            ),
        ),
        structure=StructurePlan(
            sections=[
                SectionPlan(
                    section_id="A",
                    bars=8,
                    meter=SEVEN_EIGHT,
                    key="d phrygian",
                    tempo_bpm=96,
                    texture="imitative",
                    dynamics=DynamicsPlan(start="pp", targets=[DynTarget(bar=5, level="ff")]),
                    active_voices=["soprano", GroupRef(group="lower")],
                    material=[
                        MaterialEntry(
                            motif_id="subject", voice_id="soprano", bar=1, relation="exact"
                        )
                    ],
                )
            ],
            materials_needed=[
                MaterialBrief(
                    motif_id="subject",
                    role="fugue subject",
                    description="rising fourth",
                    carrying_voices=["soprano", "alto"],
                )
            ],
            form_summary="single exposition",
        ),
        motifs=MotifLibrary(
            motifs={
                "subject": Motif(motif_id="subject", role="fugue subject", lily_music="d'4 g'4")
            }
        ),
        harmony={
            "A": HarmonicSkeleton(
                section_id="A",
                events=[HarmonicEvent(offset=Fraction(7, 8), duration=Fraction(7, 8), chord="Dm")],
            )
        },
        voices={voice_key("A", "soprano"): part},
        interpretation=InterpretationParams(dynamics_curve_intensity=1.5),
        artifacts=RenderedArtifacts(
            lily_path=Path("out/run/score.ly"),
            pdf_path=Path("out/run/score.pdf"),
            score_midi_path=Path("out/run/score.midi"),
            performance_midi_path=Path("out/run/performance.midi"),
            audio_path=Path("out/run/audio.wav"),
        ),
        feedback=[
            FeedbackItem(
                source="validate_voice",
                level="voice",
                section_id="A",
                voice_id="soprano",
                location=Fraction(3, 8),
                message="bar 1, beat 4 exceeds the soprano ceiling of a''",
                evidence="barcheck failed at: 1/8",
            )
        ],
        attempts={attempt_key("voice", "A", "soprano"): 2},
    )


def test_the_whole_state_survives_the_json_round_trip() -> None:
    state = _full_state()

    restored = PipelineState.model_validate_json(state.model_dump_json())

    assert restored == state


def test_exact_offsets_survive_the_json_round_trip() -> None:
    state = _full_state()

    restored = PipelineState.model_validate_json(state.model_dump_json())

    assert restored.harmony["A"].events[0].offset == Fraction(7, 8)
    assert restored.feedback[0].location == Fraction(3, 8)


def test_a_voice_lookup_that_should_exist_raises_when_it_does_not() -> None:
    state = _full_state()

    assert state.voice_part("A", "soprano").voice_id == "soprano"
    with pytest.raises(KeyError):
        state.voice_part("A", "bass")


def test_feedback_filters_to_the_unit_that_must_regenerate() -> None:
    state = _full_state()

    assert len(state.feedback_for("voice", "A", "soprano")) == 1
    assert state.feedback_for("voice", "A", "alto") == []
    assert state.feedback_for("harmony") == []
