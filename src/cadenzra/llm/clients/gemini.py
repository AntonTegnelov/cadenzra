"""The Gemini transport. The only module that imports the vendor SDK.

Everything above this speaks musical intent; this speaks HTTP and tool calls.
The separation is what lets a second provider be a sibling file plus a line in
the factory, rather than a change that reaches into the pipeline (docs/06).

LLM calls are non-deterministic, so bounded retries are substance here, unlike
the deterministic subprocess boundaries where retrying is theater (docs/08,
principle 3). A response with no tool call, or one that fails validation, is
retried a fixed number of times and then raises.
"""

import logging
from pathlib import Path
from typing import Any, Final

from google import genai
from google.genai import types

from cadenzra.common.errors import LLMOutputError

_log = logging.getLogger(__name__)

# Forced function calling: the model must answer with a tool call, which is how
# every structured result in the system is obtained (docs/06).
_FORCED: Final = types.FunctionCallingConfigMode.ANY


class GeminiClient:
    """A thin, typed wrapper over one Gemini model."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        attempts: int = 3,
        temperature: float | None = None,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._attempts = max(1, attempts)
        self._temperature = temperature

    def call_tool_with_audio(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tool: dict[str, Any],
        audio: Path,
    ) -> dict[str, Any]:
        """As `call_tool`, with a recording alongside the prompt.

        Audio is inlined rather than uploaded: a compositional proof is short,
        and one request beats a two-step upload that can half-fail.
        """
        return self.call_tool(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tool=tool,
            extra_parts=[
                types.Part.from_bytes(
                    data=audio.read_bytes(), mime_type=_mime_type_of(audio)
                )
            ],
        )

    def call_tool(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tool: dict[str, Any],
        extra_parts: list[types.Part] | None = None,
    ) -> dict[str, Any]:
        """Call the model and return the arguments of its forced tool call.

        Raises `LLMOutputError` if no usable tool call arrives within the
        retry budget.
        """
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=self._temperature,
            tools=[types.Tool(function_declarations=[tool])],  # type: ignore[list-item]
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode=_FORCED)
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                contents: list[types.Part] = [
                    types.Part.from_text(text=user_prompt),
                    *(extra_parts or []),
                ]
                response = self._client.models.generate_content(
                    model=self._model, contents=contents, config=config
                )
                return _arguments_of(response, tool["name"])
            except LLMOutputError as error:
                last_error = error
                _log.warning(
                    "malformed response from %s on attempt %d/%d: %s",
                    self._model,
                    attempt,
                    self._attempts,
                    error,
                )
            except Exception as error:  # transport failure
                last_error = error
                _log.warning(
                    "call to %s failed on attempt %d/%d: %s",
                    self._model,
                    attempt,
                    self._attempts,
                    error,
                )

        raise LLMOutputError(
            f"{self._model} did not return a usable {tool['name']} call in "
            f"{self._attempts} attempts: {last_error}"
        )


_MIME_TYPES: Final[dict[str, str]] = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
}


def _mime_type_of(audio: Path) -> str:
    return _MIME_TYPES.get(audio.suffix.lower(), "audio/wav")


def _arguments_of(response: types.GenerateContentResponse, tool_name: str) -> dict[str, Any]:
    """Pull the forced call's arguments out of a response, or raise."""
    for candidate in response.candidates or []:
        for part in (candidate.content.parts if candidate.content else None) or []:
            call = part.function_call
            if call is not None and call.name == tool_name:
                return dict(call.args or {})

    raise LLMOutputError(
        f"the model answered without calling {tool_name}; "
        f"it said: {(response.text or '')[:300]!r}"
    )
