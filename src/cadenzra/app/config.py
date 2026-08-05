"""`RunConfig` — everything a run needs that is not the music itself.

One settings object carries model ids per role, retry budgets per loop, tool
paths, and the seed, so that a run is reproducible and nothing below `app/`
reads the environment (docs/06).
"""

from pathlib import Path
from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from cadenzra.rendering.fluidsynth import DEFAULT_SOUNDFONT

# Gemini backs every LLM role in v1. The protocol layer is what keeps that a
# wiring choice rather than an architectural one: adding another provider is a
# client plus a service plus one line in the factory (docs/06).
DEFAULT_GENERATION_MODEL: Final = "gemini-3.6-flash"
DEFAULT_CRITIC_MODEL: Final = "gemini-3.6-flash"


class RetryBudgets(BaseSettings):
    """How many times each loop may regenerate before the run fails loudly.

    The audio-critique loop is stricter because it is the most expensive and
    least precise; interpretation adjustments get their own budget because they
    are cheap — a re-render, not a regeneration (docs/02).
    """

    structure: int = 3
    motifs: int = 3
    harmony: int = 3
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

    # Bounded retries for transport and malformed output — LLM calls are
    # non-deterministic and warrant them, unlike deterministic subprocesses.
    llm_attempts: int = 3
    seed: int = 0

    def require_gemini_key(self) -> str:
        """The API key, or a clear message about where to put one."""
        if not self.gemini_key:
            raise ValueError(
                "no Gemini API key configured; set GEMINI_KEY in the environment "
                "or in .env at the repository root"
            )
        return self.gemini_key
