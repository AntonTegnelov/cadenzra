"""`GeminiGenerator` — the `GeneratorLLM` implementation for v1.

It owns the round trip for each capability: build the surface prompt, force the
tool call, parse the result inward. Adding a capability means four artifacts,
always all four — prompt builder, schema, parser, protocol method (docs/06).
"""

from typing import Any

from cadenzra.common.runlog import TurnInfo
from cadenzra.llm.clients.gemini import GeminiClient
from cadenzra.llm.parsers.lyrics import (
    parse_device_observations,
    parse_lyric_plan,
    parse_section_lyrics,
)
from cadenzra.llm.parsers.patch import parse_bar_patch
from cadenzra.llm.parsers.structured import (
    parse_harmonic_skeleton,
    parse_motif_library,
    parse_review_verdict,
    parse_structure_plan,
    parse_style_pack,
)
from cadenzra.llm.parsers.voice import parse_voice_part
from cadenzra.llm.prompts.lyrics import (
    DEVICE_OBSERVATION_SYSTEM,
    LYRIC_PLAN_SYSTEM,
    LYRICS_SYSTEM,
    build_device_observation_prompt,
    build_lyric_plan_prompt,
    build_lyrics_prompt,
)
from cadenzra.llm.prompts.patch import PATCH_SYSTEM, build_patch_prompt
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
from cadenzra.llm.schemas.lyrics import (
    OBSERVE_DEVICES_TOOL,
    PLAN_LYRICS_TOOL,
    WRITE_LYRICS_TOOL,
    observe_devices_schema,
    plan_lyrics_schema,
    write_lyrics_schema,
)
from cadenzra.llm.schemas.patch import REWRITE_BARS_TOOL, rewrite_bars_schema
from cadenzra.llm.schemas.structured import (
    DERIVE_STYLE_TOOL,
    PLAN_STRUCTURE_TOOL,
    REVIEW_TOOL,
    WRITE_HARMONY_TOOL,
    WRITE_MOTIFS_TOOL,
    describe_style_schema,
    plan_structure_schema,
    review_schema,
    write_harmony_schema,
    write_motifs_schema,
)
from cadenzra.llm.schemas.voice import WRITE_PART_TOOL, write_part_schema
from cadenzra.model.contexts import (
    HarmonyContext,
    LyricsContext,
    MotifContext,
    PatchContext,
    VoiceContext,
)
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.lyrics import (
    RELATIONSHIP_DEFINITIONS,
    DeviceObservation,
    LyricPlan,
    SectionLyrics,
)
from cadenzra.model.motif import MotifLibrary
from cadenzra.model.review import ReviewRequest, ReviewVerdict
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.model.voice import VoicePart


def _purpose_of(
    feedback: list[FeedbackItem] | None, rejected: object | None = None
) -> dict[str, Any]:
    """Why this turn is happening, as `TurnInfo` kwargs for the run log.

    "first" — nothing came back yet; "retry" — the previous answer would not
    parse (source "parser"); "repair" — a validator rejected real music, and
    the fingerprints say which violations this turn is paying to fix.
    """
    items = feedback or []
    if not items and rejected is None:
        return {"purpose": "first"}
    if items and all(item.source == "parser" for item in items):
        return {"purpose": "retry"}
    return {
        "purpose": "repair",
        "repairs": tuple(
            item.fingerprint() for item in items if item.source != "parser"
        ),
    }


class GeminiGenerator:
    """Implements `GeneratorLLM` against a Gemini model.

    `clients_by_tool` lets individual capabilities ride a different model — a
    cheaper one for classification-shaped work, a stronger one where the
    correction rate justifies it. Unmapped tools use the default client.
    """

    def __init__(
        self,
        client: GeminiClient,
        *,
        clients_by_tool: dict[str, GeminiClient] | None = None,
    ) -> None:
        self._client = client
        self._clients_by_tool = clients_by_tool or {}

    def _client_for(self, tool: str) -> GeminiClient:
        return self._clients_by_tool.get(tool, self._client)

    def derive_style_pack(
        self, spec: PieceSpec, feedback: list[FeedbackItem] | None = None
    ) -> StylePack:
        payload = self._client_for(DERIVE_STYLE_TOOL).call_tool(
            system_prompt=STYLE_SYSTEM,
            user_prompt=build_style_prompt(spec, feedback),
            tool=describe_style_schema(
                [meter.surface_string() for meter in spec.meters_allowed]
            ),
            turn=TurnInfo(label=DERIVE_STYLE_TOOL, **_purpose_of(feedback)),
        )
        return parse_style_pack(payload, spec)

    def plan_structure(
        self,
        spec: PieceSpec,
        style: StylePack,
        feedback: list[FeedbackItem] | None = None,
    ) -> StructurePlan:
        payload = self._client_for(PLAN_STRUCTURE_TOOL).call_tool(
            system_prompt=PLAN_SYSTEM,
            user_prompt=build_plan_prompt(spec, style, feedback),
            tool=plan_structure_schema(
                [meter.surface_string() for meter in spec.meters_allowed],
                [voice.voice_id for voice in spec.voices],
                sorted(spec.groups),
            ),
            turn=TurnInfo(label=PLAN_STRUCTURE_TOOL, **_purpose_of(feedback)),
        )
        return parse_structure_plan(payload, spec)

    def plan_lyrics(
        self,
        spec: PieceSpec,
        style: StylePack,
        plan: StructurePlan,
        feedback: list[FeedbackItem] | None = None,
    ) -> LyricPlan:
        payload = self._client_for(PLAN_LYRICS_TOOL).call_tool(
            system_prompt=LYRIC_PLAN_SYSTEM,
            user_prompt=build_lyric_plan_prompt(spec, style, plan, feedback),
            tool=plan_lyrics_schema(
                [section.section_id for section in plan.sections],
                sorted(RELATIONSHIP_DEFINITIONS),
            ),
            turn=TurnInfo(label=PLAN_LYRICS_TOOL, **_purpose_of(feedback)),
        )
        return parse_lyric_plan(payload, plan, language=spec.lyric_language)

    def generate_motifs(self, ctx: MotifContext) -> MotifLibrary:
        payload = self._client_for(WRITE_MOTIFS_TOOL).call_tool(
            system_prompt=MOTIF_SYSTEM,
            user_prompt=build_motif_prompt(
                ctx.briefs, ctx.spec, ctx.style, ctx.plan, ctx.feedback
            ),
            tool=write_motifs_schema(),
            turn=TurnInfo(label=WRITE_MOTIFS_TOOL, **_purpose_of(ctx.feedback)),
        )
        return parse_motif_library(payload)

    def generate_harmony(self, ctx: HarmonyContext) -> HarmonicSkeleton:
        payload = self._client_for(WRITE_HARMONY_TOOL).call_tool(
            system_prompt=HARMONY_SYSTEM,
            user_prompt=build_harmony_prompt(
                ctx.section,
                ctx.style,
                ctx.motifs,
                ctx.previous_skeleton,
                ctx.previous_section,
                ctx.feedback,
                pinned=ctx.pinned,
            ),
            tool=write_harmony_schema(ctx.section.bars),
            turn=TurnInfo(
                label=WRITE_HARMONY_TOOL,
                section_id=ctx.section.section_id,
                **_purpose_of(ctx.feedback),
            ),
        )
        return parse_harmonic_skeleton(payload, ctx.section)

    def generate_voice(self, ctx: VoiceContext) -> VoicePart:
        payload = self._client_for(WRITE_PART_TOOL).call_tool(
            system_prompt=VOICE_SYSTEM,
            user_prompt=build_voice_prompt(ctx),
            tool=write_part_schema(
                techniques=bool(ctx.rejected and ctx.rejected.techniques),
            ),
            turn=TurnInfo(
                label=WRITE_PART_TOOL,
                section_id=ctx.section.section_id,
                voice_id=ctx.voice.voice_id,
                **_purpose_of(ctx.feedback, ctx.rejected),
            ),
        )
        return parse_voice_part(
            payload,
            section_id=ctx.section.section_id,
            voice_id=ctx.voice.voice_id,
        )

    def patch_voice(self, ctx: PatchContext) -> dict[int, str]:
        payload = self._client_for(REWRITE_BARS_TOOL).call_tool(
            system_prompt=PATCH_SYSTEM,
            user_prompt=build_patch_prompt(ctx),
            tool=rewrite_bars_schema(list(ctx.editable_bars)),
            turn=TurnInfo(
                label=REWRITE_BARS_TOOL,
                section_id=ctx.section.section_id,
                voice_id=ctx.voice.voice_id,
                **_purpose_of(ctx.feedback, ctx.part),
            ),
        )
        return parse_bar_patch(
            payload,
            list(ctx.editable_bars),
            meter=ctx.section.meter,
        )

    def generate_lyrics(self, ctx: LyricsContext) -> SectionLyrics:
        payload = self._client_for(WRITE_LYRICS_TOOL).call_tool(
            system_prompt=LYRICS_SYSTEM,
            user_prompt=build_lyrics_prompt(ctx),
            tool=write_lyrics_schema(ctx.voice_ids),
            turn=TurnInfo(
                label=WRITE_LYRICS_TOOL,
                section_id=ctx.section.section_id,
                **_purpose_of(ctx.feedback, ctx.rejected),
            ),
        )
        return parse_section_lyrics(
            payload, section_id=ctx.section.section_id, voice_ids=ctx.voice_ids
        )

    def observe_lyric_devices(self, lyrics_text: str) -> list[DeviceObservation]:
        """Read the lyrics blind and report what is in them (docs/10)."""
        payload = self._client_for(OBSERVE_DEVICES_TOOL).call_tool(
            system_prompt=DEVICE_OBSERVATION_SYSTEM,
            user_prompt=build_device_observation_prompt(lyrics_text),
            tool=observe_devices_schema(),
            turn=TurnInfo(label=OBSERVE_DEVICES_TOOL),
        )
        return parse_device_observations(payload)

    def review(self, request: ReviewRequest) -> ReviewVerdict:
        payload = self._client_for(REVIEW_TOOL).call_tool(
            system_prompt=REVIEW_SYSTEM,
            user_prompt="\n\n".join(
                block
                for block in (request.context, request.subject, request.question)
                if block
            ),
            tool=review_schema(),
            turn=TurnInfo(label=REVIEW_TOOL),
        )
        return parse_review_verdict(payload)
