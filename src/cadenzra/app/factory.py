"""The single composition point.

The only module that knows which concrete class implements which protocol.
Tests hand the graph fakes through this same door; nothing is ever patched
(docs/06, docs/07).
"""

from pathlib import Path

from cadenzra.app.config import RunConfig
from cadenzra.common.runlog import RunLog, run_stamp
from cadenzra.graph.nodes import Services
from cadenzra.llm.clients.gemini import GeminiClient
from cadenzra.llm.services.gemini_critic import GeminiCritic
from cadenzra.llm.services.gemini_generator import GeminiGenerator
from cadenzra.rendering.fluidsynth import FluidsynthAdapter
from cadenzra.rendering.lilypond import LilypondAdapter


def build_generator(config: RunConfig, runlog: RunLog | None = None) -> GeminiGenerator:
    """The `GeneratorLLM` for this run."""
    return GeminiGenerator(
        GeminiClient(
            api_key=config.require_gemini_key(),
            model=config.generation_model,
            attempts=config.llm_attempts,
            runlog=runlog,
            include_thoughts=config.log_thoughts and runlog is not None,
        )
    )


def build_critic(config: RunConfig, runlog: RunLog | None = None) -> GeminiCritic:
    """The `AudioCritic`, which also backs `FeedbackRouter` (docs/06)."""
    key = config.require_gemini_key()
    return GeminiCritic(
        GeminiClient(
            api_key=key,
            model=config.critic_model,
            attempts=config.llm_attempts,
            runlog=runlog,
            include_thoughts=config.log_thoughts and runlog is not None,
        ),
        api_key=key,
        model=config.critic_model,
    )


def build_client_for_tool(
    config: RunConfig, tool: str, runlog: RunLog | None = None
) -> GeminiClient:
    """The client one capability's calls go through.

    Today every tool rides the generation model; this is the seam where the
    per-capability model knobs attach, and what replay uses so a replayed turn
    is wired exactly like a live one.
    """
    del tool  # every capability rides the generation model, for now
    return GeminiClient(
        api_key=config.require_gemini_key(),
        model=config.generation_model,
        attempts=config.llm_attempts,
        runlog=runlog,
        include_thoughts=config.log_thoughts and runlog is not None,
    )


def build_renderer(config: RunConfig, runlog: RunLog | None = None) -> LilypondAdapter:
    return LilypondAdapter(config.lilypond_path, runlog=runlog)


def build_synthesizer(config: RunConfig) -> FluidsynthAdapter:
    return FluidsynthAdapter(config.fluidsynth_path, soundfont=config.soundfont_path)


def build_services(
    config: RunConfig, workdir: Path, runlog: RunLog | None = None
) -> Services:
    """Everything the graph is wired with, for a live run."""
    return Services(
        generator=build_generator(config, runlog),
        renderer=build_renderer(config, runlog),
        workdir=workdir,
        budgets=config.budgets,
    )


def open_run_log(config: RunConfig, output_dir: Path) -> RunLog:
    """A fresh log directory for this run, under the piece's output.

    Runs are kept rather than overwritten: the interesting comparison is almost
    always between two runs of the same piece, and the artifacts a run produces
    already live one level up.
    """
    return RunLog(
        output_dir / "runs" / run_stamp(), technical_level=config.log_level
    )
