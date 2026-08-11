"""Per-capability model tiering — knobs only, defaults untouched.

The audit found both roles hardcoded to one model with no tiering seam at all.
These pin the seam's contract: an empty mapping changes nothing, a mapped tool
gets its own client, and a typo in a capability name fails loudly instead of
silently riding the default.
"""

import pytest

from cadenzra.app.config import RunConfig
from cadenzra.app.factory import build_generator
from cadenzra.common.errors import CadenzraError
from cadenzra.llm.clients.gemini import GeminiClient
from cadenzra.llm.services.gemini_generator import GeminiGenerator


def _config(**overrides: object) -> RunConfig:
    return RunConfig.model_validate({"GEMINI_KEY": "k", **overrides})


def test_a_mapped_tool_gets_its_client_and_the_rest_the_default() -> None:
    default = object()
    cheap = object()
    generator = GeminiGenerator(
        default,  # type: ignore[arg-type]
        clients_by_tool={"describe_style": cheap},  # type: ignore[dict-item]
    )

    assert generator._client_for("describe_style") is cheap
    assert generator._client_for("write_part") is default


def test_an_empty_mapping_builds_exactly_one_client() -> None:
    generator = build_generator(_config())

    tools = ("write_part", "describe_style", "write_harmony")
    clients = {id(generator._client_for(tool)) for tool in tools}
    assert len(clients) == 1


def test_two_capabilities_on_one_cheap_model_share_a_client() -> None:
    generator = build_generator(
        _config(
            capability_models={
                "describe_style": "gemini-3.6-flash-lite",
                "observe_devices": "gemini-3.6-flash-lite",
            }
        )
    )

    style = generator._client_for("describe_style")
    observe = generator._client_for("observe_devices")
    part = generator._client_for("write_part")
    assert style is observe, "one client per distinct model, not per capability"
    assert style is not part
    assert isinstance(style, GeminiClient)


def test_a_typo_in_a_capability_name_fails_loudly() -> None:
    with pytest.raises(CadenzraError, match="describe_styel"):
        build_generator(_config(capability_models={"describe_styel": "m"}))


def test_the_default_models_are_the_cheap_tier() -> None:
    """Dev runs gemini-3.1-flash-lite only (standing directive). The code
    default is the fallback when .env says nothing — and a silent fallback
    to a stronger model is a silent fallback to a pricier one, discovered
    as a burned spending cap. Escalation is an explicit .env decision.
    Asserted on the constants, not a built config: RunConfig reads .env,
    which would mask a wrong fallback on any machine that has one."""
    from cadenzra.app.config import DEFAULT_CRITIC_MODEL, DEFAULT_GENERATION_MODEL

    assert DEFAULT_GENERATION_MODEL == "gemini-3.1-flash-lite"
    assert DEFAULT_CRITIC_MODEL == "gemini-3.1-flash-lite"


def test_default_budgets_absorb_the_weak_tier() -> None:
    """Development runs everything on the cheapest model, whose correction
    rate is priced in — the loops that empirically needed more room (motifs,
    voices, lyrics) carry it by default rather than via ad-hoc env knobs."""
    from cadenzra.app.config import RetryBudgets

    budgets = RetryBudgets()

    assert budgets.structure == 6, (
        "the style pack rides this budget and now earns real rejections; a "
        "live loop went 3 -> 4 -> 1 items and died one attempt from clean"
    )
    assert budgets.motifs == 8
    assert budgets.voice == 6
    assert budgets.lyric == 6
    assert budgets.harmony == 6, (
        "a fugue exposition's grid converged 3 -> 4 -> 1 complaints and died "
        "one attempt short of done at the old default of 3"
    )
    assert budgets.section == 16, (
        "cross-voice sweeps converged 73 -> 25 -> 14 -> 7 -> 4 -> 4 -> 2 -> 2 "
        "and were killed by the old budget of 8 two sweeps from done; a later "
        "run descended 61 -> ... -> 11 -> 10 monotone and was killed at 12. "
        "The plateau guard, not the budget, is what stops a sweep that "
        "stopped working"
    )
