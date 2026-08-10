"""`RunConfig` — everything a run needs that is not the music itself.

One settings object carries model ids per role, retry budgets per loop, tool
paths, and the seed, so that a run is reproducible and nothing below `app/`
reads the environment (docs/06).
"""

from pathlib import Path
from typing import Final

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from cadenzra.rendering.fluidsynth import DEFAULT_SOUNDFONT

# Gemini backs every LLM role in v1. The protocol layer is what keeps that a
# wiring choice rather than an architectural one: adding another provider is a
# client plus a service plus one line in the factory (docs/06).
DEFAULT_GENERATION_MODEL: Final = "gemini-3.6-flash"
DEFAULT_CRITIC_MODEL: Final = "gemini-3.6-flash"


class ModelPrice(BaseModel, frozen=True):
    """Per-million-token rates for one model, for the run summary's dollars.

    `thinking_per_mtok` defaults to the output rate, which is how Gemini bills
    reasoning. The table ships empty: an unpriced model yields `dollars: null`
    in the summary rather than an invented figure.
    """

    input_per_mtok: float
    output_per_mtok: float
    thinking_per_mtok: float | None = None

    def dollars(self, *, input_tokens: int, answer_tokens: int, thinking_tokens: int) -> float:
        thinking_rate = (
            self.thinking_per_mtok
            if self.thinking_per_mtok is not None
            else self.output_per_mtok
        )
        return (
            input_tokens * self.input_per_mtok
            + answer_tokens * self.output_per_mtok
            + thinking_tokens * thinking_rate
        ) / 1_000_000


class RetryBudgets(BaseSettings):
    """How many times each loop may regenerate before the run fails loudly.

    The audio-critique loop is stricter because it is the most expensive and
    least precise; interpretation adjustments get their own budget because they
    are cheap — a re-render, not a regeneration (docs/02).
    """

    structure: int = 3
    motifs: int = 3
    harmony: int = 3
    lyric_plan: int = 3
    lyric: int = 3
    voice: int = 3
    section: int = 3
    score: int = 3
    critique: int = 1
    interpretation: int = 2

    def for_level(self, level: str) -> int:
        return int(getattr(self, level, 3))


class RunConfig(BaseSettings):
    """Settings for one composition run, from environment and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # The key name matches what is already in the repo's .env.
    gemini_key: str = Field(default="", alias="GEMINI_KEY")

    generation_model: str = DEFAULT_GENERATION_MODEL
    critic_model: str = DEFAULT_CRITIC_MODEL

    lilypond_path: Path = Path("lilypond")
    fluidsynth_path: Path = Path("fluidsynth")
    soundfont_path: Path = DEFAULT_SOUNDFONT

    output_dir: Path = Path("out")
    budgets: RetryBudgets = Field(default_factory=RetryBudgets)

    # Per-model price table for the run summary. Empty by default — dollars
    # are computed only for models actually priced here.
    prices: dict[str, ModelPrice] = Field(default_factory=dict)

    # Bounded retries for transport and malformed output — LLM calls are
    # non-deterministic and warrant them, unlike deterministic subprocesses.
    llm_attempts: int = 3
    seed: int = 0

    # The technical log's threshold, not the console's: progress narration
    # stays visible at any setting. `info` traces everything the code does.
    log_level: str = Field(default="warning", alias="LOG_LEVEL")
    # Thought summaries are what make the narrative log worth reading — they
    # are the difference between seeing a wrong answer and seeing why.
    log_thoughts: bool = True

    def require_gemini_key(self) -> str:
        """The API key, or a clear message about where to put one."""
        if not self.gemini_key:
            raise ValueError(
                "no Gemini API key configured; set GEMINI_KEY in the environment "
                "or in .env at the repository root"
            )
        return self.gemini_key
