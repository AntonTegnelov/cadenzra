"""`GeminiCritic` — the `AudioCritic` implementation, and the router behind it.

The critic listens to a *performance*, not a score: swing, dynamics curves and
timing are all present by the time it hears anything, which is the point of
having a performance domain at all (docs/02).

It also backs `FeedbackRouter`, but not by asking the model again — localization
is rule-based in `graph/routing.py`. Wiring it here keeps the protocol pairing
the docs describe while leaving the routing policy inspectable.
"""

import logging
from pathlib import Path
from typing import Any, Final

from google.genai import types

from cadenzra.common.errors import LLMOutputError
from cadenzra.common.runlog import TurnInfo
from cadenzra.graph.routing import localize_verdict
from cadenzra.llm.clients.gemini import GeminiClient
from cadenzra.model.critique import CritiqueBrief, CritiqueVerdict, Observation
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.structure import StructurePlan

_log = logging.getLogger(__name__)

CRITIQUE_TOOL: Final = "report_listening"

CRITIC_SYSTEM = """\
You are a musician listening to a recording of a new piece and reporting what \
you actually hear. The recording is a synthesized proof of the composition, \
not a performance by people — say nothing about the synthetic timbre, and \
judge the music through it.

Report only what is audible: whether the piece holds together, whether the \
dynamics move, whether the meter grooves, whether any passage is muddy or \
crowded. Do not guess at note-level errors — those are checked elsewhere and \
you will be wrong about them. Do not assume the piece achieves what it set out \
to; describe the recording in front of you.

Answer by calling the `report_listening` tool. Never reply with prose."""


def critique_schema(sections: list[str], voices: list[str]) -> dict[str, Any]:
    return {
        "name": CRITIQUE_TOOL,
        "description": "Report what the recording actually sounds like.",
        "parameters": {
            "type": "object",
            "properties": {
                "overall": {
                    "type": "string",
                    "description": "Two or three sentences on the piece as a whole.",
                },
                "acceptable": {
                    "type": "boolean",
                    "description": (
                        "Whether this holds together as a piece of music. False "
                        "only for real problems you can point at."
                    ),
                },
                "observations": {
                    "type": "array",
                    "description": (
                        "Specific things you heard that could be better. Leave empty "
                        "if there are none."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "concern": {
                                "type": "string",
                                "description": (
                                    "What you heard, in a musician's terms, e.g. "
                                    "'the lower voices are cluttered here' or "
                                    "'the swell never really arrives'."
                                ),
                            },
                            "section_id": {
                                "type": "string",
                                "description": (
                                    "Which section, if you can tell. One of: "
                                    + ", ".join(sections)
                                ),
                            },
                            "voice_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Which voices, if you can tell. From: "
                                    + ", ".join(voices)
                                ),
                            },
                            "severity": {
                                "type": "integer",
                                "description": "1 (trivial) to 5 (serious).",
                            },
                        },
                        "required": ["concern"],
                    },
                },
            },
            "required": ["overall", "acceptable", "observations"],
        },
    }


def build_critique_prompt(brief: CritiqueBrief) -> str:
    """Enough to place an observation, and deliberately nothing more.

    The section list and voice names are here so the critic can say *where*
    something happens. What the piece was trying to be is not, because a critic
    told the intended shape reports hearing it whether or not it is there — see
    the note on `_brief` in `app/compose.py`.
    """
    blocks = [
        "Listen to this recording and report what you actually hear.",
        "It has these sections, in order:\n"
        + "\n".join(f"  - {section}" for section in brief.sections),
        f"The voices are: {', '.join(brief.voices)}.",
    ]
    if brief.intent:
        blocks.append(f"Context: {brief.intent}")
    blocks.append(
        "Describe the piece as you hear it, and name anything that does not "
        "work: passages that sound muddy or crowded, a meter that does not "
        "settle, dynamics that stay level where the music seems to want to "
        "move, a balance problem between voices. Say where — name the section "
        "if you can tell which one it is. If it simply sounds good, say so."
    )
    return "\n\n".join(blocks)


class GeminiCritic:
    """Implements `AudioCritic` and `FeedbackRouter`."""

    def __init__(self, client: GeminiClient, api_key: str, model: str) -> None:
        self._client = client
        self._api_key = api_key
        self._model = model

    def critique(self, audio: Path, brief: CritiqueBrief) -> CritiqueVerdict:
        if not audio.exists():
            raise LLMOutputError(f"no audio to critique at {audio}")

        payload = self._client.call_tool_with_audio(
            system_prompt=CRITIC_SYSTEM,
            user_prompt=build_critique_prompt(brief),
            tool=critique_schema(brief.sections, brief.voices),
            audio=audio,
            turn=TurnInfo(label=CRITIQUE_TOOL),
        )
        return parse_critique_verdict(payload)

    def localize(
        self, verdict: CritiqueVerdict, plan: StructurePlan
    ) -> list[FeedbackItem]:
        return localize_verdict(verdict, plan)


def parse_critique_verdict(payload: dict[str, Any]) -> CritiqueVerdict:
    """Normalize the critic's tool call inward."""
    raw = payload.get("observations")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise LLMOutputError("the critic returned observations that are not a list")

    observations = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("concern"):
            continue
        observations.append(
            Observation(
                concern=str(item["concern"]),
                section_id=_optional_text(item.get("section_id")),
                voice_ids=[str(v) for v in item.get("voice_ids") or []],
                severity=int(item.get("severity") or 3),
            )
        )

    return CritiqueVerdict(
        overall=str(payload.get("overall", "")),
        acceptable=bool(payload.get("acceptable", True)),
        observations=observations,
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def audio_part(audio: Path) -> types.Part:
    """The recording as a model input."""
    return types.Part.from_bytes(data=audio.read_bytes(), mime_type="audio/wav")
