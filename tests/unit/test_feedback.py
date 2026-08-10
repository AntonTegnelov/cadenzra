"""`FeedbackItem.fingerprint()` — a stable identity for a violation.

The double-fugue audit had to match verbatim message strings to learn that nine
violations survived three repair sweeps. The fingerprint pins identity to what
the violation *is* (kind, place, voices), not how it is worded, so convergence
becomes a set computation.
"""

from fractions import Fraction

from cadenzra.model.feedback import FeedbackItem


def _item(**overrides: object) -> FeedbackItem:
    fields: dict[str, object] = {
        "source": "validate_section",
        "level": "section",
        "section_id": "Exposition1",
        "kind": "parallels",
        "voices": ("cello", "viola"),
        "voice_id": "viola",
        "location": Fraction(5, 1),
        "message": "cello and viola move in parallel octaves into bar 6, beat 1",
    }
    fields.update(overrides)
    return FeedbackItem.model_validate(fields)


def test_rewording_does_not_change_the_identity() -> None:
    a = _item()
    b = _item(message="parallel octaves between cello and viola approaching bar 6")

    assert a.fingerprint() == b.fingerprint()


def test_a_different_place_is_a_different_violation() -> None:
    assert _item().fingerprint() != _item(location=Fraction(9, 1)).fingerprint()


def test_a_different_kind_is_a_different_violation() -> None:
    assert _item().fingerprint() != _item(kind="held_tone").fingerprint()


def test_a_different_pair_is_a_different_violation() -> None:
    assert _item().fingerprint() != _item(voices=("cello", "violin2")).fingerprint()


def test_the_routed_voice_does_not_split_the_identity() -> None:
    """The same relationship routed to the other voice is still one fault —
    otherwise the both-free case double-counts every pair."""
    a = _item(voice_id="viola")
    b = _item(voice_id="cello")

    assert a.fingerprint() == b.fingerprint()


def test_a_span_identifies_by_its_start() -> None:
    a = _item(span=(Fraction(5, 1), Fraction(7, 1)), location=None)
    b = _item(span=(Fraction(5, 1), Fraction(8, 1)), location=None)

    assert a.fingerprint() == b.fingerprint(), "a run that grew by a beat is the same fault"


def test_items_without_kind_fall_back_to_source() -> None:
    a = _item(kind=None)
    b = _item(kind=None, source="validate_voice")

    assert a.fingerprint() != b.fingerprint()


def test_a_turns_purpose_follows_its_feedback() -> None:
    """The log's first-vs-repair split cost a day of reconstruction in the
    audit; the generator states it at call time instead."""
    from cadenzra.llm.services.gemini_generator import _purpose_of

    assert _purpose_of(None) == {"purpose": "first"}
    assert _purpose_of([]) == {"purpose": "first"}

    parser_only = [
        FeedbackItem(source="parser", level="voice", message="no lily_music")
    ]
    assert _purpose_of(parser_only) == {"purpose": "retry"}

    real = _item()
    result = _purpose_of([real], rejected=object())
    assert result["purpose"] == "repair"
    assert result["repairs"] == (real.fingerprint(),)
