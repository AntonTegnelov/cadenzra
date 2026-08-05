"""An `AudioCritic` and `FeedbackRouter` that never listens to anything."""

from pathlib import Path

from cadenzra.graph.routing import localize_verdict
from cadenzra.model.critique import CritiqueBrief, CritiqueVerdict
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.structure import StructurePlan


class ScriptedCritic:
    """Returns scripted verdicts in order, so every routing path is reachable.

    The last verdict repeats, which is how "complains once, then is satisfied"
    and "complains forever" are both expressible.
    """

    def __init__(self, verdicts: list[CritiqueVerdict] | None = None) -> None:
        self._verdicts = list(verdicts or [CritiqueVerdict(acceptable=True)])
        self.heard: list[Path] = []
        self.briefs: list[CritiqueBrief] = []

    def critique(self, audio: Path, brief: CritiqueBrief) -> CritiqueVerdict:
        self.heard.append(audio)
        self.briefs.append(brief)
        return self._verdicts[min(len(self.heard) - 1, len(self._verdicts) - 1)]

    def localize(
        self, verdict: CritiqueVerdict, plan: StructurePlan
    ) -> list[FeedbackItem]:
        return localize_verdict(verdict, plan)

    @property
    def calls(self) -> int:
        return len(self.heard)
