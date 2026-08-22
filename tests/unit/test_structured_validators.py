"""Contracts for the structured-layer validators.

These are the cheapest checks in the pipeline and the ones that prevent the
most expensive mistakes: a plan that exceeds its meter palette, or a skeleton
that does not fill its section, would otherwise surface as confusing failures
several layers later.
"""

from fractions import Fraction
from pathlib import Path

import pytest

from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.structure import (
    DynamicsPlan,
    DynTarget,
    GroupRef,
    MaterialBrief,
    MaterialEntry,
    SectionPlan,
    StructurePlan,
)
from cadenzra.verification.harmony import validate_harmony
from cadenzra.verification.structure import validate_structure

SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])
FIVE_FOUR = simple_meter(5, 4, [3, 2])
FOUR_FOUR = simple_meter(4, 4)

SOPRANO = VoiceSpec(
    voice_id="soprano",
    kind="vocal",
    group="upper",
    range_low=Pitch(step="C", octave=4),
    range_high=Pitch(step="A", octave=5),
    midi_program=52,
)
BASS = VoiceSpec(
    voice_id="bass",
    kind="vocal",
    group="lower",
    range_low=Pitch(step="E", octave=2),
    range_high=Pitch(step="D", octave=4),
    midi_program=52,
)


def _spec(**overrides: object) -> PieceSpec:
    base = PieceSpec(
        title="T",
        style_prompt="s",
        voices=[SOPRANO, BASS],
        meters_allowed=[SEVEN_EIGHT, FIVE_FOUR],
        target_minutes=2.0,
    )
    return base.model_copy(update=overrides)


def _section(**overrides: object) -> SectionPlan:
    defaults: dict[str, object] = {
        "section_id": "A",
        # 32 bars of 7/8 at 96bpm is 32 * 3.5 quarters / 96 ~= 1.17 minutes.
        "bars": 32,
        "meter": SEVEN_EIGHT,
        "key": "d minor",
        "tempo_bpm": 96,
        "texture": "homophonic",
        "dynamics": DynamicsPlan(start="mf"),
        "active_voices": ["soprano", "bass"],
    }
    return SectionPlan.model_validate(defaults | overrides)


def _plan(*sections: SectionPlan, **overrides: object) -> StructurePlan:
    base = StructurePlan(sections=list(sections) or [_section()])
    return base.model_copy(update=overrides)


def test_a_well_formed_plan_is_accepted() -> None:
    plan = _plan(_section(), _section(section_id="B", meter=FIVE_FOUR, bars=16))

    assert validate_structure(plan, _spec()) == []


def test_a_meter_outside_the_palette_is_rejected() -> None:
    plan = _plan(_section(meter=FOUR_FOUR, bars=28))

    feedback = validate_structure(plan, _spec())

    assert any("meter palette" in item.message for item in feedback)


def test_an_unknown_voice_is_rejected() -> None:
    plan = _plan(_section(active_voices=["soprano", "tenor"]))

    feedback = validate_structure(plan, _spec())

    assert any("tenor" in item.message for item in feedback)


def test_a_known_group_reference_resolves() -> None:
    plan = _plan(
        _section(active_voices=[GroupRef(group="lower")]),
        _section(section_id="B", bars=24),
    )

    assert validate_structure(plan, _spec()) == []


def test_an_unknown_group_reference_is_rejected() -> None:
    plan = _plan(_section(active_voices=[GroupRef(group="concertino")]))

    feedback = validate_structure(plan, _spec())

    assert any("concertino" in item.message for item in feedback)


def test_a_plan_far_from_the_requested_duration_is_rejected() -> None:
    """The LLM proposes, arithmetic disposes (docs/04)."""
    plan = _plan(_section(bars=4))

    feedback = validate_structure(plan, _spec())

    assert any("minutes" in item.message for item in feedback)


def test_a_plan_near_the_requested_duration_is_accepted() -> None:
    plan = _plan(_section(bars=32), _section(section_id="B", bars=24))

    assert validate_structure(plan, _spec()) == []


def test_an_entry_naming_undeclared_material_is_rejected() -> None:
    plan = _plan(
        _section(
            material=[
                MaterialEntry(motif_id="subject", voice_id="soprano", bar=1, relation="exact")
            ]
        )
    )

    feedback = validate_structure(plan, _spec())

    assert any("no material by that name" in item.message for item in feedback)


def test_an_entry_given_to_a_silent_voice_is_rejected() -> None:
    plan = _plan(
        _section(
            active_voices=["soprano"],
            material=[
                MaterialEntry(motif_id="subject", voice_id="bass", bar=1, relation="exact")
            ],
        ),
        materials_needed=[
            MaterialBrief(motif_id="subject", role="fugue subject", description="")
        ],
    )

    feedback = validate_structure(plan, _spec())

    assert any("not singing in that section" in item.message for item in feedback)


def test_an_entry_on_a_member_of_an_active_group_is_accepted() -> None:
    """Group references count: an entry on a voice activated via its group is
    not "silent", or every plan that mixes groups and entries is unplannable."""
    plan = _plan(
        _section(
            active_voices=[GroupRef(group="lower"), "soprano"],
            material=[
                MaterialEntry(motif_id="subject", voice_id="bass", bar=1, relation="exact")
            ],
        ),
        _section(section_id="B", meter=FIVE_FOUR, bars=16),
        materials_needed=[
            MaterialBrief(motif_id="subject", role="fugue subject", description="")
        ],
    )

    assert validate_structure(plan, _spec()) == []


def test_an_entry_on_a_group_name_is_rejected_as_a_group() -> None:
    """An entry must land on one voice. Naming a group is rejected with the
    real reason — 'not singing' would send the regeneration the wrong way."""
    plan = _plan(
        _section(
            active_voices=[GroupRef(group="lower")],
            material=[
                MaterialEntry(motif_id="subject", voice_id="lower", bar=1, relation="exact")
            ],
        ),
        materials_needed=[
            MaterialBrief(motif_id="subject", role="fugue subject", description="")
        ],
    )

    feedback = validate_structure(plan, _spec())

    assert any(
        "group" in item.message and "bass" in item.message for item in feedback
    )
    assert not any("not singing" in item.message for item in feedback)


def test_style_fragments_parse_with_their_meter() -> None:
    from cadenzra.llm.parsers.structured import parse_style_pack

    payload = {
        "idioms": ["Dorian colour"],
        "rhythmic_cells": [],
        "harmony_guidance": "",
        "parallel_fifths_policy": "forbid",
        "dynamics_arc": "",
        "few_shot_fragments": [{"meter": "7/8", "lily": "a'8 a' b' b' c''4. |"}],
    }

    pack = parse_style_pack(payload, _spec())

    (fragment,) = pack.few_shot_fragments
    assert fragment.meter == SEVEN_EIGHT
    assert fragment.lily == "a'8 a' b' b' c''4. |"


def test_a_bare_string_fragment_is_rejected_with_the_shape_named() -> None:
    from cadenzra.common.errors import LLMOutputError
    from cadenzra.llm.parsers.structured import parse_style_pack

    payload = {
        "idioms": [],
        "rhythmic_cells": [],
        "harmony_guidance": "",
        "parallel_fifths_policy": "forbid",
        "dynamics_arc": "",
        "few_shot_fragments": ["c'4 d'4 e'4 f'4 |"],
    }

    with pytest.raises(LLMOutputError, match="meter"):
        parse_style_pack(payload, _spec())


def _cell_spec() -> PieceSpec:
    """One allowed meter, covered by `_COVERING_CELL` — packs under test that
    care about other constraints must not drown in coverage findings."""
    return _spec(meters_allowed=[SEVEN_EIGHT])


def test_broken_exemplars_are_dropped_not_fatal() -> None:
    """Every style retry regenerates the whole pack, so one bad dotted cell
    anywhere re-rolls ten exemplars — a live loop went 2 -> 2 -> 2 -> 1 ->
    4 -> 3 and died at six attempts. An exemplar that does not fill its bar
    simply is not one (the vocabulary-is-the-contract precedent): salvage
    keeps the accepted material and drops the broken, and the validators
    then judge what remains — coverage still rejects a meter left bare."""
    from cadenzra.model.style import RhythmicCell, StyleFragment, StylePack
    from cadenzra.verification.style import salvage_exemplars
    from tests.fakes.renderer import RecordingRenderer, clean, failing_bar_check

    pack = StylePack(
        rhythmic_cells=[
            RhythmicCell(meter=SEVEN_EIGHT, lily="c4. c4 c4", description="bad"),
            RhythmicCell(meter=SEVEN_EIGHT, lily="c8 c c c c4.", description="good"),
        ],
        few_shot_fragments=[
            StyleFragment(meter=SEVEN_EIGHT, lily="a'8 a' b' b' c''4. |")
        ],
    )
    # Exemplars compile in order: bad cell, good cell, fragment.
    renderer = RecordingRenderer([failing_bar_check(line=9), clean(), clean()])

    salvaged = salvage_exemplars(pack, renderer, Path("/tmp/unused"))

    assert [cell.description for cell in salvaged.rhythmic_cells] == ["good"]
    assert len(salvaged.few_shot_fragments) == 1, "the clean fragment survives"


def test_a_meter_with_no_rhythmic_cells_is_rejected() -> None:
    """The prompt asks for two cells per allowed meter and nothing counted
    them: a pack with zero cells for a section's meter silently degraded
    every voice prompt in it — cells are the odd-meter mechanism (docs/04),
    and their absence was the quiet kind of failure."""
    from cadenzra.model.style import RhythmicCell, StylePack
    from cadenzra.verification.style import validate_style_pack
    from tests.fakes.renderer import RecordingRenderer

    partial = StylePack(
        rhythmic_cells=[
            RhythmicCell(meter=SEVEN_EIGHT, lily="c8 c c c c4.", description="d")
        ]
    )
    covered = StylePack(
        rhythmic_cells=[
            RhythmicCell(meter=SEVEN_EIGHT, lily="c8 c c c c4.", description="d"),
            RhythmicCell(meter=FIVE_FOUR, lily="c4 c c c c", description="e"),
        ]
    )

    feedback = validate_style_pack(
        partial, _spec(), RecordingRenderer(), Path("/tmp/unused")
    )

    assert any(
        "5/4" in item.message and "cells" in item.message for item in feedback
    )
    assert (
        validate_style_pack(covered, _spec(), RecordingRenderer(), Path("/tmp/unused"))
        == []
    )


def test_a_pack_demanding_octave_doubling_while_forbidding_parallels_is_incoherent() -> None:
    """The orchestra trap (F3): "doubling of melody in octaves" beside
    parallel_fifths_policy='forbid' produced 72 parallel-octave complaints
    whose minimum edit violated the range floor. A declared relationship
    between two fields of one artifact is arithmetic, not taste."""
    from cadenzra.model.style import RhythmicCell, StylePack
    from cadenzra.verification.style import validate_style_pack
    from tests.fakes.renderer import RecordingRenderer

    incoherent = StylePack(
        idioms=["doubling of melody in octaves"],
        parallel_fifths_policy="forbid",
        rhythmic_cells=[
            RhythmicCell(meter=SEVEN_EIGHT, lily="c8 c c c c4.", description="d")
        ],
    )
    coherent = incoherent.model_copy(update={"parallel_fifths_policy": "allow"})

    feedback = validate_style_pack(
        incoherent, _cell_spec(), RecordingRenderer(), Path("/tmp/unused")
    )

    assert len(feedback) == 1
    assert "doubling of melody in octaves" in feedback[0].message
    assert "allow" in feedback[0].message
    assert (
        validate_style_pack(coherent, _cell_spec(), RecordingRenderer(), Path("/tmp/unused"))
        == []
    )


def test_a_fragment_carrying_structural_commands_is_rejected_by_the_pack_check() -> None:
    """Fragments are exemplars: a \\clef inside one teaches every voice call
    to write a forbidden command. The same denylist scan the voice validator
    runs, applied when the pack is born."""
    from cadenzra.model.style import RhythmicCell, StyleFragment, StylePack
    from cadenzra.verification.style import validate_style_pack
    from tests.fakes.renderer import RecordingRenderer

    pack = StylePack(
        rhythmic_cells=[
            RhythmicCell(meter=SEVEN_EIGHT, lily="c8 c c c c4.", description="d")
        ],
        few_shot_fragments=[
            StyleFragment(meter=SEVEN_EIGHT, lily="\\clef bass c4 d4 e4 f4 |")
        ],
    )

    feedback = validate_style_pack(
        pack, _cell_spec(), RecordingRenderer(), Path("/tmp/unused")
    )

    assert len(feedback) == 1
    assert "\\clef" in feedback[0].message


def test_the_same_motif_entered_twice_at_once_is_rejected_under_forbid() -> None:
    """A motif loop burned 8/8 identical attempts on "S2 (violin1) and S2
    (viola) move in parallel octaves — reshape one of the two": impossible,
    because both are the same line. Identical simultaneous statements are
    parallel by construction whatever the motif looks like, so under a
    forbidding policy the plan owns the fault, at plan time."""
    plan = _plan(
        _section(
            material=[
                MaterialEntry(
                    motif_id="subject", voice_id="soprano", bar=1, relation="exact"
                ),
                MaterialEntry(
                    motif_id="subject", voice_id="bass", bar=1, relation="exact"
                ),
            ]
        ),
        materials_needed=[
            MaterialBrief(motif_id="subject", role="fugue subject", description="")
        ],
    )

    feedback = validate_structure(plan, _spec(), parallel_policy="forbid")

    assert any(
        "parallel" in item.message and "stagger" in item.message
        for item in feedback
    )
    permissive = validate_structure(plan, _spec(), parallel_policy="allow")
    assert not any("stagger" in item.message for item in permissive), (
        "deliberate doubling under a permissive policy is a choice, not a fault"
    )


def test_a_dynamics_target_outside_the_section_is_rejected() -> None:
    """A target at bar 99 of an 8-bar section used to sail through to the
    performance curves; bars are section-local everywhere."""
    with pytest.raises(ValueError, match="bar 99"):
        _section(
            bars=8,
            dynamics=DynamicsPlan(
                start="mf", targets=[DynTarget(bar=99, level="ff")]
            ),
        )


def test_a_brief_carrying_an_unknown_voice_is_rejected() -> None:
    """`carrying_voices` names the ranges the motif prompt shows; an unknown
    id was silently dropped by the prompt builder, so the model wrote for a
    range set that was not the one the validator later checked."""
    plan = _plan(
        _section(
            material=[
                MaterialEntry(
                    motif_id="subject", voice_id="soprano", bar=1, relation="exact"
                )
            ]
        ),
        materials_needed=[
            MaterialBrief(
                motif_id="subject",
                role="fugue subject",
                description="",
                carrying_voices=["soprano", "tenor2"],
            )
        ],
    )

    feedback = validate_structure(plan, _spec())

    assert any(
        "tenor2" in item.message and "carrying_voices" in item.message
        for item in feedback
    )


def test_an_entry_outside_its_section_teaches_local_numbering() -> None:
    """Three consecutive live plans declared an entry at "bar 17" of a
    12-bar section — piece-wide numbering, where bar 17 of the piece is bar
    1 of the section; the third attempt even grew the section chasing the
    feedback. The rejection must teach the convention and read as a
    rehearsal note, not a pydantic traceback."""
    from cadenzra.common.errors import LLMOutputError
    from cadenzra.llm.parsers.structured import parse_structure_plan

    payload = {
        "sections": [
            {
                "section_id": "Exp2",
                "bars": 12,
                "meter": "7/8",
                "key": "d minor",
                "tempo_bpm": 96,
                "texture": "imitative",
                "active_voices": ["soprano"],
                "material": [
                    {
                        "motif_id": "S2",
                        "voice_id": "soprano",
                        "bar": 17,
                        "relation": "exact",
                    }
                ],
            }
        ]
    }

    with pytest.raises(LLMOutputError) as caught:
        parse_structure_plan(payload, _spec())

    message = str(caught.value)
    assert "bar 17" in message and "12 bars" in message
    assert "first bar is bar 1" in message, "the local convention is taught"
    assert "pydantic" not in message and "input_value" not in message, (
        "the model reads a rehearsal note, not a validation dump"
    )


def test_an_unverifiable_relation_is_rejected_at_plan_time() -> None:
    """Catching this here is much cheaper than discovering at section time
    that a declared entry could never have been checked."""
    plan = _plan(
        _section(
            material=[
                MaterialEntry(
                    motif_id="subject", voice_id="soprano", bar=1, relation="sideways"
                )
            ]
        ),
        materials_needed=[
            MaterialBrief(motif_id="subject", role="fugue subject", description="")
        ],
    )

    feedback = validate_structure(plan, _spec())

    assert any("cannot be verified" in item.message for item in feedback)


SHORT = _section(bars=2)
SECTION_LENGTH = Fraction(2 * 7, 8)


def _skeleton(*events: tuple[str, Fraction, Fraction]) -> HarmonicSkeleton:
    return HarmonicSkeleton(
        section_id="A",
        events=[
            HarmonicEvent(chord=chord, offset=offset, duration=duration)
            for chord, offset, duration in events
        ],
    )


def test_a_gapless_skeleton_that_fills_the_section_is_accepted() -> None:
    skeleton = _skeleton(
        ("Dm", Fraction(0), Fraction(7, 8)), ("Bb", Fraction(7, 8), Fraction(7, 8))
    )

    assert validate_harmony(skeleton, SHORT) == []


def test_a_gap_in_the_progression_is_rejected_and_located() -> None:
    skeleton = _skeleton(
        ("Dm", Fraction(0), Fraction(4, 8)), ("Bb", Fraction(7, 8), Fraction(7, 8))
    )

    feedback = validate_harmony(skeleton, SHORT)

    assert any("gapless" in item.message for item in feedback)
    assert any("bar 1, beat 5" in item.message for item in feedback)
    gap = next(item for item in feedback if "gapless" in item.message)
    assert "give the Dm at bar 1, beat 1 a duration of 7 beats (it has 4)" in gap.message, (
        "metal, live: 'the progression must be gapless' flags no chord, and "
        "the amendment prompt says change only flagged chords — the model "
        "kept its grid verbatim six times; the gap must name its own edit"
    )


def test_overlapping_chords_are_rejected() -> None:
    skeleton = _skeleton(
        ("Dm", Fraction(0), Fraction(7, 8)), ("Bb", Fraction(4, 8), Fraction(10, 8))
    )

    feedback = validate_harmony(skeleton, SHORT)

    assert any("overlaps" in item.message for item in feedback)


def test_a_progression_that_does_not_fill_the_section_is_rejected() -> None:
    """Exact `Fraction` arithmetic: a page of 7/8 bars summed in floats would
    not close, and the error would surface three layers later (docs/08)."""
    skeleton = _skeleton(("Dm", Fraction(0), Fraction(7, 8)))

    feedback = validate_harmony(skeleton, SHORT)

    assert any("1 bar" in item.message and "2 bars" in item.message for item in feedback)


def test_a_progression_that_overruns_the_section_is_rejected() -> None:
    skeleton = _skeleton(
        ("Dm", Fraction(0), Fraction(7, 8)),
        ("Bb", Fraction(7, 8), Fraction(7, 8)),
        ("C", Fraction(14, 8), Fraction(7, 8)),
    )

    feedback = validate_harmony(skeleton, SHORT)

    assert any("3 bars" in item.message for item in feedback)


def test_an_empty_progression_is_rejected() -> None:
    feedback = validate_harmony(_skeleton(), SHORT)

    assert len(feedback) == 1
    assert "no chords" in feedback[0].message


def test_an_unreadable_chord_symbol_is_rejected_with_examples() -> None:
    skeleton = _skeleton(
        ("Dm", Fraction(0), Fraction(7, 8)), ("Qx", Fraction(7, 8), Fraction(7, 8))
    )

    feedback = validate_harmony(skeleton, SHORT)

    assert len(feedback) == 1
    assert "Qx" in feedback[0].message
    assert "Esus4" in feedback[0].message
    # The rejection teaches the grammar it enforces, generated from the
    # parser's own table — rich on failure, absent from first prompts
    # (docs/08: lean surface, teaching rejections).
    assert "m7b5" in feedback[0].message
    assert "sus2" in feedback[0].message
    assert "/bass" in feedback[0].message


@pytest.mark.parametrize("meter", [SEVEN_EIGHT, FIVE_FOUR, FOUR_FOUR])
def test_exact_fill_holds_for_every_meter(meter: object) -> None:
    section = _section(meter=meter, bars=3)
    bar = meter.bar_length  # type: ignore[attr-defined]
    skeleton = _skeleton(*[("Dm", bar * index, bar) for index in range(3)])

    assert validate_harmony(skeleton, section) == []


def test_a_motif_that_does_not_fill_its_meter_is_told_the_deficit() -> None:
    """LilyPond's "failed at: X" is where the check landed *within* the bar —
    how much the bar holds, not how much is missing. Reporting X as "off by
    X" told a hook that was an eighth short in 4/4 it was off by 7/8, and
    seven attempts across two model tiers chased the wrong number. The
    rehearsal note must state the deficit."""
    from cadenzra.model.artifacts import BarCheckWarning
    from cadenzra.verification.motifs import _bar_check_reason

    reason = _bar_check_reason(
        [BarCheckWarning(line=9, column=1, message="bar check failed at: 1/8")],
        SEVEN_EIGHT,
    )

    assert reason is not None
    assert "3/4 short" in reason, "7/8 bar holding 1/8 is 3/4 short"
    assert "1/8 over" in reason, "the overfull reading stays visible"


def test_a_barely_overfull_bar_leads_with_the_overfull_reading() -> None:
    """The two readings of "failed at: X" are kept, but the smaller correction
    must lead: a viola part holding 15/16 against 7/8 was twice told "13/16
    short" first, and twice re-sent the same overfull bar. A bar that misses
    by a sixteenth is overwhelmingly one written a sixteenth over."""
    from cadenzra.model.artifacts import BarCheckWarning
    from cadenzra.verification.motifs import _bar_check_reason

    reason = _bar_check_reason(
        [BarCheckWarning(line=9, column=1, message="bar check failed at: 1/16")],
        SEVEN_EIGHT,
    )

    assert reason is not None
    assert reason.index("1/16 over") < reason.index("13/16 short")


def test_no_bar_checks_means_no_paraphrase_to_give() -> None:
    from cadenzra.verification.motifs import _bar_check_reason

    assert _bar_check_reason([], SEVEN_EIGHT) is None
