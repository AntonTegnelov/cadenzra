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
# The cheapest tier is the fallback on purpose: a run that silently rides a
# stronger model is a run that silently rides a pricier one (a burned monthly
# spending cap found the old gemini-3.6-flash default). Escalating any
# capability is an explicit .env decision, never an accident of a missing one.
DEFAULT_GENERATION_MODEL: Final = "gemini-3.1-flash-lite"
DEFAULT_CRITIC_MODEL: Final = "gemini-3.1-flash-lite"


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

    # The loops that write notation get more room by default: the dev tier
    # runs the weakest model, whose higher correction rate is priced in, and
    # an extra lite-tier attempt costs pennies while a budget_exhausted run
    # costs a resume.
    # The style pack rides this budget too, and it now earns real
    # rejections (compile checks, coverage, coherence) — a live loop went
    # 3 -> 4 -> 1 items and died one attempt from clean at the old 3.
    structure: int = 6
    motifs: int = 8
    # A fugue exposition's grid answers pinned tones in every voice at once;
    # with the constraints charted up front it converges, but 3 -> 4 -> 1
    # complaints at a budget of 3 died one attempt short of done.
    harmony: int = 6
    lyric_plan: int = 3
    lyric: int = 6
    voice: int = 6
    # Cross-voice sweeps shrink monotonically when they are working (73 ->
    # 25 -> 14 -> 7 -> 4 -> 4 -> 2 -> 2 live, killed two sweeps from done)
    # and the convergence guard stops the ones that are not; the budget
    # exists for runaway loops, not to cut converging ones short. It did
    # exactly that at 12: a live sweep descended 61 -> ... -> 11 -> 10,
    # monotone all twelve attempts, guard never fired, budget exhausted.
    section: int = 16
    score: int = 3
    # One listen to find a problem, one to confirm the knob fixed it. This
    # budget bounds the critic invocations themselves — the loop count is
    # `interpretation`, which bounds the cheap re-renders.
    critique: int = 2
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

    # Per-capability model overrides, keyed by tool name (write_part,
    # describe_style, ...). Empty by default: tiering is a knob, not a
    # behavior change — every capability rides `generation_model` until a
    # measurement says otherwise.
    capability_models: dict[str, str] = Field(default_factory=dict)

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
