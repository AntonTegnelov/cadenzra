"""The complaint cap: a repair prompt carries what a repair can act on.

The double-fugue handed one voice 45 complaints in a single prompt. A voice
asked to fix 45 relationships fixes none of them well; the cap keeps the most
structural complaints (entries before held tones before parallels) and says
plainly that more are waiting.
"""

from cadenzra.app.compose import _prioritized
from cadenzra.model.feedback import FeedbackItem


def _item(kind: str, index: int) -> FeedbackItem:
    return FeedbackItem(
        source="validate_section",
        level="section",
        section_id="A",
        voice_id="alto",
        kind=kind,
        message=f"{kind} complaint {index}",
    )


def test_a_short_list_passes_through_untouched() -> None:
    items = [_item("parallels", index) for index in range(3)]

    assert _prioritized(items) == items


def test_a_long_list_is_capped_with_a_note_about_the_rest() -> None:
    items = [_item("parallels", index) for index in range(20)]

    capped = _prioritized(items)

    real = [item for item in capped if item.source != "router"]
    notes = [item for item in capped if item.source == "router"]
    assert len(real) < 20
    assert len(notes) == 1
    assert "12 more" in notes[0].message
    assert "re-checked" in notes[0].message


def test_entries_outrank_held_tones_outrank_parallels() -> None:
    """Priority is the ordering contract; the constant's value is not pinned."""
    items = (
        [_item("parallels", index) for index in range(10)]
        + [_item("held_tone", index) for index in range(4)]
        + [_item("entry", 0)]
    )

    capped = _prioritized(items)

    real = [item for item in capped if item.source != "router"]
    kinds = [item.kind for item in real]
    assert kinds[0] == "entry", "the most structural complaint survives first"
    assert kinds.index("held_tone") < kinds.index("parallels")


def test_order_within_a_class_is_stable() -> None:
    items = [_item("held_tone", index) for index in range(10)]

    real = [item for item in _prioritized(items) if item.source != "router"]

    numbers = [int(item.message.split()[-1]) for item in real]
    assert numbers == sorted(numbers)
