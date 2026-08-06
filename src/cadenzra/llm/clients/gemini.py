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
import time
from pathlib import Path
from typing import Any, Final

from google import genai
from google.genai import types

from cadenzra.common.errors import LLMOutputError
from cadenzra.common.runlog import RunLog, TurnInfo

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
        runlog: RunLog | None = None,
        include_thoughts: bool = False,
        backoff_s: float = 20.0,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._attempts = max(1, attempts)
        self._temperature = temperature
        self._runlog = runlog
        self._include_thoughts = include_thoughts
        self._backoff_s = backoff_s

    def call_tool_with_audio(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tool: dict[str, Any],
        audio: Path,
        turn: TurnInfo | None = None,
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
            turn=turn,
            audio=str(audio),
        )

    def call_tool(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tool: dict[str, Any],
        extra_parts: list[types.Part] | None = None,
        turn: TurnInfo | None = None,
        audio: str | None = None,
    ) -> dict[str, Any]:
        """Call the model and return the arguments of its forced tool call.

        Raises `LLMOutputError` if no usable tool call arrives within the
        retry budget.

        `turn` says which part of the composition this call serves. The client
        cannot know that on its own, and the run log is far less useful without
        it — "the alto in section B, second attempt" is the unit a reader is
        actually looking for.
        """
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=self._temperature,
            tools=[types.Tool(function_declarations=[tool])],  # type: ignore[list-item]
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode=_FORCED)
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=(
                types.ThinkingConfig(include_thoughts=True)
                if self._include_thoughts
                else None
            ),
        )

        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            started = time.monotonic()
            thoughts: str | None = None
            try:
                contents: list[types.Part] = [
                    types.Part.from_text(text=user_prompt),
                    *(extra_parts or []),
                ]
                response = self._client.models.generate_content(
                    model=self._model, contents=contents, config=config
                )
                arguments, thoughts = _extract(response, tool["name"])
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
                # A rate limit is not a bad answer, it is "not yet". Retrying
                # three times in a second spends the whole budget before the
                # window has moved, which is how a ten-minute piece dies
                # halfway through on a quota that would have cleared.
                if attempt < self._attempts and _is_rate_limited(error):
                    delay = self._backoff_s * (2 ** (attempt - 1))
                    _log.warning("rate limited; waiting %.0fs", delay)
                    time.sleep(delay)
            else:
                self._record(
                    turn=turn,
                    tool=tool,
                    attempt=attempt,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response=arguments,
                    thoughts=thoughts,
                    seconds=time.monotonic() - started,
                    audio=audio,
                )
                return arguments

            # A rejected attempt is the most informative turn in the log: it
            # shows what the model was told at the moment it went wrong.
            self._record(
                turn=turn,
                tool=tool,
                attempt=attempt,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=None,
                thoughts=thoughts,
                seconds=time.monotonic() - started,
                error=str(last_error),
                audio=audio,
            )

        raise LLMOutputError(
            f"{self._model} did not return a usable {tool['name']} call in "
            f"{self._attempts} attempts: {last_error}"
        )

    def _record(
        self,
        *,
        turn: TurnInfo | None,
        tool: dict[str, Any],
        attempt: int,
        system_prompt: str,
        user_prompt: str,
        response: dict[str, Any] | None,
        thoughts: str | None,
        seconds: float,
        error: str | None = None,
        audio: str | None = None,
    ) -> None:
        if self._runlog is None:
            return
        self._runlog.llm_turn(
            turn=turn,
            model=self._model,
            temperature=self._temperature,
            attempt=attempt,
            attempts=self._attempts,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tool_name=str(tool.get("name", "")),
            response=response,
            thoughts=thoughts,
            seconds=seconds,
            error=error,
            audio=audio,
        )


_MIME_TYPES: Final[dict[str, str]] = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
}


_RATE_LIMITED: Final = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")


def _is_rate_limited(error: Exception) -> bool:
    """Whether waiting is likely to help.

    Matched on the message rather than an exception type: the SDK raises its
    own error classes and the status is what is stable across versions.
    """
    text = str(error)
    return any(marker in text for marker in _RATE_LIMITED)


def _mime_type_of(audio: Path) -> str:
    return _MIME_TYPES.get(audio.suffix.lower(), "audio/wav")


def _extract(
    response: types.GenerateContentResponse, tool_name: str
) -> tuple[dict[str, Any], str | None]:
    """Pull the forced call's arguments and any thought summary, or raise.

    Thoughts arrive as ordinary text parts flagged `thought`; a walk that only
    looked for the function call would discard the reasoning that makes the
    narrative log worth reading.
    """
    arguments: dict[str, Any] | None = None
    thoughts: list[str] = []
    for candidate in response.candidates or []:
        for part in (candidate.content.parts if candidate.content else None) or []:
            if part.thought and part.text:
                thoughts.append(part.text)
            call = part.function_call
            if arguments is None and call is not None and call.name == tool_name:
                arguments = dict(call.args or {})

    if arguments is None:
        raise LLMOutputError(
            f"the model answered without calling {tool_name}; "
            f"it said: {(response.text or '')[:300]!r}"
        )
    return arguments, "\n\n".join(thoughts) if thoughts else None
