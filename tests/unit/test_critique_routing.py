"""The M5 gate for routing: what the critic says becomes work someone can do.

The property under test is the cheapest-target-first policy (docs/05).
Misrouting a vague complaint to `plan_structure` would cascade a full
regeneration on the weakest evidence in the system; misrouting it to
`InterpretationParams` costs one deterministic re-render. So when an
observation could belong to several layers, the cheap one must win.
"""

import pytest

from cadenzra.graph.routing import (
    LEVEL_COST,
    cheapest_level,
    classify,
    localize_verdict,
)
from cadenzra.llm.services.gemini_critic import parse_critique_verdict
from cadenzra.model.critique import CritiqueVerdict, Observation
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.structure import DynamicsPlan, SectionPlan, StructurePlan

SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])


def _section(section_id: str) -> SectionPlan:
    return SectionPlan(
        section_id=section_id,
        bars=8,
        meter=SEVEN_EIGHT,
        key="d minor",
        tempo_bpm=96,
        texture="homophonic",
        dynamics=DynamicsPlan(start="mf"),
        active_voices=["soprano", "alto"],
    )


PLAN = StructurePlan(sections=[_section("A"), _section("B")])


def _observed(concern: str, **kwargs: object) -> Observation:
    return Observation.model_validate({"concern": concern, **kwargs})


@pytest.mark.parametrize(
    ("concern", "level"),
    [
        ("the whole thing sounds stiff and mechanical", "interpretation"),
        ("the swell never really arrives", "interpretation"),
        ("it sounds flat, the dynamics do not move", "interpretation"),
        ("the meter does not groove", "interpretation"),
        ("the bass is buried in the mix", "render"),
        ("the lower voices are cluttered here", "voice"),
        ("the middle is mud", "voice"),
        ("the form goes nowhere", "structure"),
    ],
)
def test_a_complaint_lands_on_the_layer_that_owns_it(concern: str, level: str) -> None:
    assert classify(_observed(concern)) == level


def test_an_unlocalizable_complaint_goes_to_the_cheapest_layer() -> None:
    """"It doesn't quite work" is the weakest evidence in the system. Acting on
    it by rewriting the piece would be the most expensive possible response to
    the least information."""
    assert classify(_observed("something about it does not quite work")) == "interpretation"


def test_an_ambiguous_complaint_prefers_the_cheaper_reading() -> None:
    """"Cluttered and stiff" could be texture or interpretation. Trying the
    knob first costs a re-render; trying the notes first costs regeneration."""
    assert classify(_observed("section B is cluttered and stiff")) == "interpretation"


def test_the_cost_order_puts_notes_above_knobs_and_form_above_everything() -> None:
    assert LEVEL_COST["render"] < LEVEL_COST["interpretation"]
    assert LEVEL_COST["interpretation"] < LEVEL_COST["voice"]
    assert LEVEL_COST["voice"] < LEVEL_COST["harmony"]
    assert LEVEL_COST["harmony"] < LEVEL_COST["structure"]


def test_observations_become_routable_feedback() -> None:
    verdict = CritiqueVerdict(
        overall="promising but stiff",
        acceptable=False,
        observations=[
            _observed(
                "the lower voices are cluttered", section_id="B", voice_ids=["alto"]
            )
        ],
    )

    items = localize_verdict(verdict, PLAN)

    assert len(items) == 1
    assert items[0].level == "voice"
    assert items[0].section_id == "B"
    assert items[0].voice_id == "alto"
    assert items[0].source == "critique_audio"


def test_one_observation_about_two_voices_becomes_two_items() -> None:
    """Each item routes to one regeneration target, so a complaint about two
    voices is two pieces of work."""
    verdict = CritiqueVerdict(
        observations=[
            _observed(
                "these lines clash", section_id="A", voice_ids=["alto", "tenor"]
            )
        ]
    )

    items = localize_verdict(verdict, PLAN)

    assert {item.voice_id for item in items} == {"alto", "tenor"}


def test_a_texture_complaint_naming_no_voice_falls_back_to_a_knob() -> None:
    """Voice-level feedback with no voice cannot be acted on as a regeneration
    — there is nothing to regenerate — so it drops to the cheapest layer."""
    verdict = CritiqueVerdict(observations=[_observed("it sounds cluttered")])

    items = localize_verdict(verdict, PLAN)

    assert items[0].level == "interpretation"


def test_a_section_the_plan_does_not_have_is_not_invented() -> None:
    verdict = CritiqueVerdict(
        observations=[_observed("cluttered", section_id="Z", voice_ids=["alto"])]
    )

    assert localize_verdict(verdict, PLAN)[0].section_id is None


def test_structure_feedback_is_about_the_whole_piece() -> None:
    verdict = CritiqueVerdict(
        observations=[_observed("the form goes nowhere", section_id="A")]
    )

    items = localize_verdict(verdict, PLAN)

    assert items[0].level == "structure"
    assert items[0].section_id is None


def test_a_satisfied_critic_produces_no_work() -> None:
    assert localize_verdict(CritiqueVerdict(acceptable=True), PLAN) == []


def test_a_round_is_addressed_at_its_cheapest_target() -> None:
    """Several complaints at once should not trigger the expensive fix while a
    cheap one might resolve the recording."""
    items = [
        FeedbackItem(source="critique_audio", level="structure", message="form"),
        FeedbackItem(source="critique_audio", level="interpretation", message="stiff"),
    ]

    assert cheapest_level(items) == "interpretation"
    assert cheapest_level([]) is None


def test_a_critique_tool_call_parses_into_a_verdict() -> None:
    verdict = parse_critique_verdict(
        {
            "overall": "coherent but stiff",
            "acceptable": False,
            "observations": [
                {
                    "concern": "the swell never arrives",
                    "section_id": "B",
                    "voice_ids": ["soprano"],
                    "severity": 4,
                }
            ],
        }
    )

    assert not verdict.acceptable
    assert verdict.observations[0].section_id == "B"
    assert verdict.observations[0].severity == 4


def test_a_critique_without_observations_is_a_pass() -> None:
    verdict = parse_critique_verdict({"overall": "good", "acceptable": True})

    assert verdict.acceptable
    assert verdict.observations == []


def test_an_observation_with_no_concern_is_dropped_not_guessed_at() -> None:
    verdict = parse_critique_verdict(
        {"acceptable": False, "observations": [{"section_id": "A"}]}
    )

    assert verdict.observations == []
