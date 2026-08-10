"""Protocols for the language-model boundary.

These speak musical intent, not transport — `generate_voice`, never
`complete_prompt`. Prompt construction is an implementation detail of the
adapter, which is what makes swapping providers (or slotting a fine-tuned model
into one method) invisible above the boundary (docs/06).
"""

from typing import Protocol

from cadenzra.model.contexts import (
    HarmonyContext,
    LyricsContext,
    MotifContext,
    PatchContext,
    VoiceContext,
)
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.lyrics import DeviceObservation, LyricPlan, SectionLyrics
from cadenzra.model.motif import MotifLibrary
from cadenzra.model.review import ReviewRequest, ReviewVerdict
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.model.voice import VoicePart


class GeneratorLLM(Protocol):
    """The text/notation generator, one method per generation layer."""

    def derive_style_pack(self, spec: PieceSpec) -> StylePack: ...

    def plan_structure(
        self,
        spec: PieceSpec,
        style: StylePack,
        feedback: list[FeedbackItem] | None = None,
    ) -> StructurePlan: ...

    def plan_lyrics(
        self,
        spec: PieceSpec,
        style: StylePack,
        plan: StructurePlan,
        feedback: list[FeedbackItem] | None = None,
    ) -> LyricPlan: ...

    def generate_motifs(self, ctx: MotifContext) -> MotifLibrary: ...

    def generate_harmony(self, ctx: HarmonyContext) -> HarmonicSkeleton: ...

    def generate_voice(self, ctx: VoiceContext) -> VoicePart: ...

    def patch_voice(self, ctx: PatchContext) -> dict[int, str]: ...

    def generate_lyrics(self, ctx: LyricsContext) -> SectionLyrics: ...

    def observe_lyric_devices(self, lyrics_text: str) -> list[DeviceObservation]: ...

    def review(self, request: ReviewRequest) -> ReviewVerdict: ...
