"""The narrow-question interface for LLM validators.

An LLM validator is asked one specific question with a structured verdict —
"does this section plan realize the requested arc?" — and only for properties
that are genuinely not decidable: formal coherence, stylistic fit, the
memorability of a subject. Their verdicts route feedback within budget but
never veto a piece that passes every deterministic check on its final attempt
(docs/05).
"""

from pydantic import BaseModel, Field


class ReviewRequest(BaseModel, frozen=True):
    """One narrow question about one artifact."""

    question: str
    subject: str
    context: str = ""


class ReviewVerdict(BaseModel, frozen=True):
    """The answer, structured so it can route."""

    acceptable: bool
    reasons: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
