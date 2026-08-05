"""The Cadenzra error hierarchy.

Every error here is raised at a boundary and carries the evidence a human (or
a feedback item) needs to act on it. Anything else that escapes is a bug and
should crash with a traceback, on purpose (docs/08, principle 4).
"""


class CadenzraError(Exception):
    """Base for every error the CLI is willing to catch and report."""


class LilypondCompileError(CadenzraError):
    """The LilyPond compiler failed or timed out.

    Carries the complete compiler output: stderr is evidence for feedback
    items and must survive to the run log (docs/06).
    """

    def __init__(self, message: str, *, output: str) -> None:
        super().__init__(message)
        self.output = output


class SynthesisError(CadenzraError):
    """FluidSynth failed or timed out. Carries the complete tool output."""

    def __init__(self, message: str, *, output: str) -> None:
        super().__init__(message)
        self.output = output


class LLMOutputError(CadenzraError):
    """A model response had no tool call, or one that failed validation.

    Raised in `llm/parsers/` and handled by the adapter's bounded retry —
    never scraped with a regex, never coerced to a default (docs/06).
    """


class BudgetExhaustedError(CadenzraError):
    """A generate/validate loop hit its retry budget.

    The run ends here with partial artifacts written and the accumulated
    feedback preserved. The pipeline never completes by degrading the music
    (docs/02, docs/08 principle 4).
    """

    def __init__(self, message: str, *, loop_key: str, attempts: int) -> None:
        super().__init__(message)
        self.loop_key = loop_key
        self.attempts = attempts
