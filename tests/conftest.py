"""Shared pytest configuration.

Integration tests need the real LilyPond and FluidSynth binaries; they are
skipped rather than failed when the toolchain is absent, so the unit suite
stays runnable anywhere.
"""

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    missing = [tool for tool in ("lilypond", "fluidsynth") if shutil.which(tool) is None]
    if not missing:
        return
    skip = pytest.mark.skip(reason=f"missing external tool(s): {', '.join(missing)}")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
