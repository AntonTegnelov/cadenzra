"""In-memory protocol implementations.

Every pipeline test runs against these, entering through the same factory the
real adapters do — so there is no patching anywhere in the suite (docs/06,
docs/09).
"""

from tests.fakes.generator import ScriptedGenerator
from tests.fakes.renderer import RecordingRenderer

__all__ = ["RecordingRenderer", "ScriptedGenerator"]
