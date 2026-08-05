"""`GeminiGenerator` — the `GeneratorLLM` implementation for v1.

It owns the round trip for each capability: build the surface prompt, force the
tool call, parse the result inward. Adding a capability means four artifacts,
always all four — prompt builder, schema, parser, protocol method (docs/06).
"""

from cadenzra.llm.clients.gemini import GeminiClient
from cadenzra.llm.parsers.structured import (
    parse_harmonic_skeleton,
    parse_motif_library,
    parse_review_verdict,
    parse_structure_plan,
    parse_style_pack,
)
from cadenzra.llm.parsers.voice import parse_voice_part
from cadenzra.llm.prompts.structured import (
    HARMONY_SYSTEM,
    MOTIF_SYSTEM,
    PLAN_SYSTEM,
    REVIEW_SYSTEM,
    STYLE_SYSTEM,
    build_harmony_prompt,
    build_motif_prompt,
    build_plan_prompt,
    build_style_prompt,
)
from cadenzra.llm.prompts.voice import SYSTEM_PROMPT as VOICE_SYSTEM
from cadenzra.llm.prompts.voice import build_voice_prompt
from cadenzra.llm.schemas.structured import (
    describe_style_schema,
    plan_structure_schema,
    review_schema,
    write_harmony_schema,
    write_motifs_schema,
)
from cadenzra.llm.schemas.voice import write_part_schema
from cadenzra.model.contexts import HarmonyContext, MotifContext, VoiceContext
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.motif import MotifLibrary
from cadenzra.model.review import ReviewRequest, ReviewVerdict
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.model.voice import VoicePart


class GeminiGenerator:
    """Implements `GeneratorLLM` against a Gemini model."""

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

    def derive_style_pack(self, spec: PieceSpec) -> StylePack:
        payload = self._client.call_tool(
            system_prompt=STYLE_SYSTEM,
            user_prompt=build_style_prompt(spec),
            tool=describe_style_schema(
                [meter.surface_string() for meter in spec.meters_allowed]
            ),
        )
        return parse_style_pack(payload, spec)

    def plan_structure(
        self,
        spec: PieceSpec,
        style: StylePack,
        feedback: list[FeedbackItem] | None = None,
    ) -> StructurePlan:
        payload = self._client.call_tool(
            system_prompt=PLAN_SYSTEM,
            user_prompt=build_plan_prompt(spec, style, feedback),
            tool=plan_structure_schema(
                [meter.surface_string() for meter in spec.meters_allowed],
                [voice.voice_id for voice in spec.voices],
                sorted(spec.groups),
            ),
        )
        return parse_structure_plan(payload, spec)

    def generate_motifs(self, ctx: MotifContext) -> MotifLibrary:
        payload = self._client.call_tool(
            system_prompt=MOTIF_SYSTEM,
            user_prompt=build_motif_prompt(
                ctx.briefs, ctx.spec, ctx.style, ctx.plan, ctx.feedback
            ),
            tool=write_motifs_schema(),
        )
        return parse_motif_library(payload)

    def generate_harmony(self, ctx: HarmonyContext) -> HarmonicSkeleton:
        payload = self._client.call_tool(
            system_prompt=HARMONY_SYSTEM,
            user_prompt=build_harmony_prompt(
                ctx.section,
                ctx.style,
                ctx.motifs,
                ctx.previous_skeleton,
                ctx.previous_section,
                ctx.feedback,
            ),
            tool=write_harmony_schema(ctx.section.bars),
        )
        return parse_harmonic_skeleton(payload, ctx.section)

    def generate_voice(self, ctx: VoiceContext) -> VoicePart:
        payload = self._client.call_tool(
            system_prompt=VOICE_SYSTEM,
            user_prompt=build_voice_prompt(ctx),
            tool=write_part_schema(
                lyrics=ctx.voice.lyrics,
                techniques=bool(ctx.rejected and ctx.rejected.techniques),
            ),
        )
        return parse_voice_part(
            payload,
            section_id=ctx.section.section_id,
            voice_id=ctx.voice.voice_id,
        )

    def review(self, request: ReviewRequest) -> ReviewVerdict:
        payload = self._client.call_tool(
            system_prompt=REVIEW_SYSTEM,
            user_prompt="\n\n".join(
                block
                for block in (request.context, request.subject, request.question)
                if block
            ),
            tool=review_schema(),
        )
        return parse_review_verdict(payload)
