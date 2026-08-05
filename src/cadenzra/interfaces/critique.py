"""Protocols for the audio critic and the router that interprets it."""

from pathlib import Path
from typing import Protocol

from cadenzra.model.critique import CritiqueBrief, CritiqueVerdict
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.structure import StructurePlan


class AudioCritic(Protocol):
    """A multimodal model listening to the rendered performance."""

    def critique(self, audio: Path, brief: CritiqueBrief) -> CritiqueVerdict: ...


class FeedbackRouter(Protocol):
    """Turns qualitative observations into routable feedback.

    Validator feedback routes by table lookup and needs no intelligence. This
    exists for the critic's output, where "section B sounds cluttered" could
    belong to any of four different layers (docs/05).
    """

    def localize(
        self, verdict: CritiqueVerdict, plan: StructurePlan
    ) -> list[FeedbackItem]: ...
