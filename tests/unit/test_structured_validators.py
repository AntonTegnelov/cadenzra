"""Contracts for the structured-layer validators.

These are the cheapest checks in the pipeline and the ones that prevent the
most expensive mistakes: a plan that exceeds its meter palette, or a skeleton
that does not fill its section, would otherwise surface as confusing failures
several layers later.
"""

from fractions import Fraction

import pytest

from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.structure import (
    DynamicsPlan,
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
