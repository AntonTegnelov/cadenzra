"""The single composition point.

The only module that knows which concrete class implements which protocol.
Tests hand the graph fakes through this same door; nothing is ever patched
(docs/06, docs/07).
"""

from pathlib import Path

from cadenzra.app.config import RunConfig
from cadenzra.graph.nodes import Services
from cadenzra.llm.clients.gemini import GeminiClient
from cadenzra.llm.services.gemini_critic import GeminiCritic
from cadenzra.llm.services.gemini_generator import GeminiGenerator
from cadenzra.rendering.fluidsynth import FluidsynthAdapter
from cadenzra.rendering.lilypond import LilypondAdapter


def build_generator(config: RunConfig) -> GeminiGenerator:
    """The `GeneratorLLM` for this run."""
    return GeminiGenerator(
        GeminiClient(
            api_key=config.require_gemini_key(),
            model=config.generation_model,
            attempts=config.llm_attempts,
        )
    )


def build_critic(config: RunConfig) -> GeminiCritic:
    """The `AudioCritic`, which also backs `FeedbackRouter` (docs/06)."""
    key = config.require_gemini_key()
    return GeminiCritic(
        GeminiClient(api_key=key, model=config.critic_model, attempts=config.llm_attempts),
        api_key=key,
        model=config.critic_model,
    )


def build_renderer(config: RunConfig) -> LilypondAdapter:
    return LilypondAdapter(config.lilypond_path)


def build_synthesizer(config: RunConfig) -> FluidsynthAdapter:
    return FluidsynthAdapter(config.fluidsynth_path, soundfont=config.soundfont_path)


def build_services(config: RunConfig, workdir: Path) -> Services:
    """Everything the graph is wired with, for a live run."""
    return Services(
        generator=build_generator(config),
        renderer=build_renderer(config),
        workdir=workdir,
        budgets=config.budgets,
    )
