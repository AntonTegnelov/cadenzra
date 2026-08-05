"""A `GeneratorLLM` that returns canned artifacts, in order."""

from cadenzra.model.contexts import HarmonyContext, MotifContext, VoiceContext
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.motif import MotifLibrary
from cadenzra.model.review import ReviewRequest, ReviewVerdict
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.model.voice import VoicePart


class ScriptedGenerator:
    """Returns scripted artifacts, so loop mechanics can be tested exactly.

    Scripting *failures* matters as much as successes: "fails on attempt 1,
    succeeds on attempt 2" is how the retry path gets covered (docs/09). Each
    layer's script is consumed in order, and the last entry repeats — so a
    single-entry script means "always this".
    """

    def __init__(
        self,
        fragments: list[str] | None = None,
        *,
        style: StylePack | None = None,
        plans: list[StructurePlan] | None = None,
        motifs: list[MotifLibrary] | None = None,
        skeletons: list[HarmonicSkeleton] | None = None,
        verdicts: list[ReviewVerdict] | None = None,
    ) -> None:
        self._fragments = list(fragments or [])
        self._style = style
        self._plans = list(plans or [])
        self._motifs = list(motifs or [])
        self._skeletons = list(skeletons or [])
        self._verdicts = list(verdicts or [])

        self.contexts: list[VoiceContext] = []
        self.motif_contexts: list[MotifContext] = []
        self.harmony_contexts: list[HarmonyContext] = []
        self.reviews: list[ReviewRequest] = []
        self.style_calls = 0
        self.plan_calls = 0

    def derive_style_pack(self, spec: PieceSpec) -> StylePack:
        self.style_calls += 1
        return self._style if self._style is not None else StylePack()

    def plan_structure(
        self,
        spec: PieceSpec,
        style: StylePack,
        feedback: list[FeedbackItem] | None = None,
    ) -> StructurePlan:
        self.plan_calls += 1
        return _pick(self._plans, self.plan_calls - 1, what="plan")

    def generate_motifs(self, ctx: MotifContext) -> MotifLibrary:
        self.motif_contexts.append(ctx)
        return _pick(self._motifs, len(self.motif_contexts) - 1, what="motif library")

    def generate_harmony(self, ctx: HarmonyContext) -> HarmonicSkeleton:
        self.harmony_contexts.append(ctx)
        return _pick(self._skeletons, len(self.harmony_contexts) - 1, what="skeleton")

    def generate_voice(self, ctx: VoiceContext) -> VoicePart:
        self.contexts.append(ctx)
        return VoicePart(
            section_id=ctx.section.section_id,
            voice_id=ctx.voice.voice_id,
            lily_music=_pick(self._fragments, len(self.contexts) - 1, what="fragment"),
        )

    def review(self, request: ReviewRequest) -> ReviewVerdict:
        self.reviews.append(request)
        if not self._verdicts:
            return ReviewVerdict(acceptable=True)
        return _pick(self._verdicts, len(self.reviews) - 1, what="verdict")

    @property
    def calls(self) -> int:
        return len(self.contexts)


def _pick[T](script: list[T], index: int, *, what: str) -> T:
    if not script:
        raise AssertionError(f"the fake generator has no {what} scripted")
    return script[min(index, len(script) - 1)]
