"""The run log — what the system said, what the model said back, what broke.

docs/07 promised a complete record of every prompt, response and compiler
output; this is it. Three files, because three different questions get asked of
a run and one format answers none of them well:

- `llm.jsonl` — every LLM turn verbatim, one JSON object per attempt. The
  question it answers is "what exactly did the model see?", so nothing here is
  summarized, truncated or prettified. Failed attempts are recorded too: a
  malformed response is the most interesting turn in the file.
- `narrative.md` — the same flow, readable end to end: prompt, what the model
  was thinking, what came back, what the validators said. The question it
  answers is "is this model any good at composing, and where does it go
  astray?"
- `technical.log` — leveled tracing for the code itself, defaulting to
  `warning` so it stays quiet until something is being debugged.

This module deliberately imports nothing from `cadenzra`. Both `llm/clients/`
and `rendering/` record into it, and a logger that depended on the model layer
would invert the dependency direction docs/07 lays out. Everything arrives as
strings and plain dicts.

Writes open, append and close under a lock. A run that dies on an exhausted
budget is exactly when its log matters most, so nothing is buffered waiting for
a clean shutdown, and the lock is what keeps concurrent voice generation from
interleaving half-lines.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

LOGGER_NAME: Final = "cadenzra"

_LEVELS: Final[dict[str, int]] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

_TECHNICAL_FORMAT: Final = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def level_of(name: str) -> int:
    """A level name from config or the command line, as a logging level."""
    return _LEVELS.get(name.strip().lower(), logging.WARNING)


def run_stamp() -> str:
    """The name of a run directory: sortable, second-resolution, UTC."""
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def configure_logging(*, console_level: int = logging.INFO) -> None:
    """Set up the `cadenzra` logger tree for a command-line run.

    Not `basicConfig`: the run log attaches a file handler that may sit at
    `debug`, and with root-level configuration those records would spill onto
    the terminal as well. The logger runs wide open and each handler decides
    its own threshold, which is what lets a quiet console coexist with a
    verbose file.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        if getattr(handler, "_cadenzra_console", False):
            logger.removeHandler(handler)

    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter("%(message)s"))
    console._cadenzra_console = True  # type: ignore[attr-defined]
    logger.addHandler(console)


@dataclass(frozen=True)
class TurnInfo:
    """Which part of the composition an LLM turn belongs to.

    The client itself has no idea whether it is writing an alto line or a form
    plan. The services do — they hold the context object — so they say, and the
    identity travels as a value rather than through ambient state. That keeps
    it correct under the voice thread pool without any context copying.
    """

    label: str
    section_id: str | None = None
    voice_id: str | None = None
    # Why this turn happened: "first" | "retry" (malformed output) |
    # "repair" (a validator sent it back) | "replay". `repairs` carries the
    # fingerprints of the feedback items a repair is addressing, which is what
    # lets the log answer "what did fixing that violation cost".
    purpose: str = "first"
    repairs: tuple[str, ...] = ()

    def where(self) -> str:
        parts = [p for p in (self.section_id, self.voice_id) if p]
        return " / ".join(parts)


class RunLog:
    """One run's record, written to a directory as it happens."""

    def __init__(self, logs_dir: Path, *, technical_level: str = "warning") -> None:
        self.dir = logs_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.flow_path = self.dir / "llm.jsonl"
        self.narrative_path = self.dir / "narrative.md"
        self.technical_path = self.dir / "technical.log"

        self._lock = threading.Lock()
        self._turns = 0

        handler = logging.FileHandler(self.technical_path, encoding="utf-8")
        handler.setLevel(level_of(technical_level))
        handler.setFormatter(logging.Formatter(_TECHNICAL_FORMAT))
        self._handler = handler
        logger = logging.getLogger(LOGGER_NAME)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

    def close(self) -> None:
        """Detach the file handler. Safe to call twice."""
        logging.getLogger(LOGGER_NAME).removeHandler(self._handler)
        self._handler.close()

    # --- the flow log ---------------------------------------------------

    def llm_turn(
        self,
        *,
        turn: TurnInfo | None,
        model: str,
        temperature: float | None,
        attempt: int,
        attempts: int,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        response: dict[str, Any] | None = None,
        thoughts: str | None = None,
        seconds: float = 0.0,
        error: str | None = None,
        audio: str | None = None,
        usage: dict[str, Any] | None = None,
        finish_reason: str | None = None,
        model_version: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Record one call to a model — successful or not, verbatim."""
        with self._lock:
            self._turns += 1
            seq = self._turns
        label = turn.label if turn else tool_name
        where = turn.where() if turn else ""

        self._append_json(
            self.flow_path,
            {
                "seq": seq,
                "at": _now(),
                "kind": "llm_turn",
                "label": label,
                "section": turn.section_id if turn else None,
                "voice": turn.voice_id if turn else None,
                "purpose": turn.purpose if turn else "first",
                "repairs": list(turn.repairs) if turn else [],
                "attempt": attempt,
                "attempts": attempts,
                "model": model,
                "temperature": temperature,
                "tool": tool_name,
                "audio": audio,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "thoughts": thoughts,
                "response": response,
                "error": error,
                "seconds": round(seconds, 3),
                "usage": usage,
                "finish_reason": finish_reason,
                "model_version": model_version,
                "request_id": request_id,
            },
        )

        heading = f"## {seq}. {label}"
        if where:
            heading += f" — {where}"
        if attempts > 1:
            heading += f" (attempt {attempt}/{attempts})"
        blocks = [heading, "", "### Asked", "", _fence(user_prompt)]
        if thoughts:
            blocks += ["", "### What the model was thinking", "", thoughts.strip()]
        if error is not None:
            blocks += ["", "### Failed", "", _fence(error)]
        elif response is not None:
            blocks += ["", "### Answered", "", _fence(_pretty(response))]
        blocks += ["", f"*{seconds:.1f}s · {model}*", ""]
        self._append_text(self.narrative_path, "\n".join(blocks))

    def compile_event(
        self, *, workdir: str, clean: bool, warnings: int, raw_output: str
    ) -> None:
        """Record a compiler invocation with its output intact.

        docs/06 is firm that compiler stderr is evidence and must survive to
        the log — it is the one diagnosis in the system nobody has to guess at.
        """
        self._append_json(
            self.flow_path,
            {
                "at": _now(),
                "kind": "compile",
                "workdir": workdir,
                "clean": clean,
                "warnings": warnings,
                "output": raw_output,
            },
        )

    def wait(self, *, seconds: float, reason: str) -> None:
        """Record time spent waiting on the outside world (a rate limit).

        Its own event so a run stalling on quota is legible as stalling — folded
        into a turn's `seconds` it reads as slow inference, which is exactly how
        the cost audit misread it.
        """
        self._append_json(
            self.flow_path,
            {"at": _now(), "kind": "wait", "seconds": round(seconds, 3), "reason": reason},
        )
        self._append_text(
            self.narrative_path, f"*Waiting {seconds:.0f}s — {reason}*\n"
        )

    def validation(
        self,
        *,
        what: str,
        loop_key: str,
        attempt: int,
        budget: int,
        messages: list[str],
        items: list[dict[str, Any]] | None = None,
    ) -> None:
        """Record a rejection and what it said.

        State keeps only current feedback — superseded items are dropped when
        their target regenerates (docs/05). This is where the history they left
        behind lives. `items` is the structured mirror of `messages` — plain
        dicts (id, kind, section, voices, voice, bar, message, routing), since
        this module imports nothing from cadenzra — so convergence can be
        computed instead of inferred from prose.
        """
        self._append_json(
            self.flow_path,
            {
                "at": _now(),
                "kind": "validation",
                "what": what,
                "loop_key": loop_key,
                "attempt": attempt,
                "budget": budget,
                "messages": messages,
                "items": items,
            },
        )
        bullets = "\n".join(f"- {message}" for message in messages)
        self._append_text(
            self.narrative_path,
            f"> **Rejected** — {what} (attempt {attempt}/{budget})\n>\n{_quote(bullets)}\n",
        )

    def note(self, heading: str, text: str) -> None:
        """Record something that is neither a turn nor a rejection."""
        self._append_json(
            self.flow_path,
            {"at": _now(), "kind": "note", "heading": heading, "text": text},
        )
        self._append_text(self.narrative_path, f"### {heading}\n\n{text}\n")

    # --- writing --------------------------------------------------------

    def _append_json(self, path: Path, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with self._lock, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _append_text(self, path: Path, text: str) -> None:
        with self._lock, path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _pretty(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _fence(text: str) -> str:
    """Fence a block, with enough backticks to survive LilyPond and JSON."""
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}\n{text.strip()}\n{fence}"


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines())
