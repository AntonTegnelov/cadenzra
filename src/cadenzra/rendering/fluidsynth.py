"""The FluidSynth boundary: performance MIDI in, audio out.

The audio this produces is a *compositional proof* — correct notes, rhythms,
balance, and shaping — not a release-ready recording (docs/01). What matters
here is only that the synthesizer faithfully realizes what the performance MIDI
asks for, including its continuous dynamics.
"""

import subprocess
from pathlib import Path
from typing import Final

from cadenzra.common.errors import CadenzraError, SynthesisError
from cadenzra.model.spec import VoiceSpec

DEFAULT_SOUNDFONT: Final = Path("/usr/share/sounds/sf2/FluidR3_GM.sf2")
DEFAULT_SAMPLE_RATE: Final = 44100
DEFAULT_TIMEOUT_S: Final = 300.0


class FluidsynthAdapter:
    """Drives the real synthesizer. Implements `Synthesizer`."""

    def __init__(
        self,
        executable: Path | str = "fluidsynth",
        *,
        soundfont: Path = DEFAULT_SOUNDFONT,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._executable = str(executable)
        self._soundfont = soundfont
        self._sample_rate = sample_rate
        self._timeout_s = timeout_s

    def render(self, midi: Path, voices: list[VoiceSpec], out: Path) -> Path:
        """Render `midi` to a WAV at `out`.

        `voices` is part of the protocol but unread in v1: instrument choice
        travels in the MIDI itself, one program per channel. It stays in the
        signature because per-voice balance and per-voice SoundFonts are the
        obvious next thing to want here, and they are this method's business.
        """
        del voices

        if not midi.exists():
            raise SynthesisError(f"no MIDI to render at {midi}", output="")
        if not self._soundfont.exists():
            raise CadenzraError(f"SoundFont not found at {self._soundfont}")

        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run(
                [
                    self._executable,
                    "-ni",
                    "-F",
                    str(out),
                    "-r",
                    str(self._sample_rate),
                    str(self._soundfont),
                    str(midi),
                ],
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except FileNotFoundError as exc:
            raise CadenzraError(
                f"FluidSynth executable {self._executable!r} not found"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise SynthesisError(
                f"FluidSynth timed out after {self._timeout_s}s rendering {midi}",
                output=_decode(exc.stdout) + _decode(exc.stderr),
            ) from exc

        output = completed.stdout + completed.stderr
        if completed.returncode != 0:
            raise SynthesisError(
                f"FluidSynth exited {completed.returncode} rendering {midi}", output=output
            )
        if not out.exists() or out.stat().st_size == 0:
            raise SynthesisError(
                f"FluidSynth reported success but wrote no audio to {out}", output=output
            )
        return out


def _decode(stream: str | bytes | None) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return stream
