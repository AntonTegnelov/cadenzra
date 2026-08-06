"""The LilyPond boundary.

LilyPond is not only the output format — it is the pipeline's most trustworthy
validator. Bar arithmetic, syntax, and the score MIDI that every analysis runs
on all come from here, which is why the system never grew its own notation
parser (docs/02).

This module owns the one gnarly parsing job at the boundary: turning compiler
stderr into structured warnings. That parsing lives here, tested against
captured real output, and nowhere else (docs/06).
"""

import re
import subprocess
from pathlib import Path
from typing import Final

from cadenzra.common.errors import CadenzraError, LilypondCompileError
from cadenzra.common.runlog import RunLog
from cadenzra.model.artifacts import BarCheckWarning, CompileResult

SOURCE_STEM: Final = "score"
EXPECTED_VERSION: Final = "2.26"
DEFAULT_TIMEOUT_S: Final = 120.0

# Real 2.26 output, captured:
#   /path/to/score.ly:7:29: warning: bar check failed at: 1/8
_DIAGNOSTIC = re.compile(
    r"^(?P<file>[^\n:]*):(?P<line>\d+):(?P<column>\d+): warning: (?P<message>.*)$",
    re.MULTILINE,
)
_BAR_CHECK = "bar check failed"

_ERROR = re.compile(
    r"^[^\n:]*:\d+:\d+: error: (?P<message>.*)$", re.MULTILINE
)

_VERSION = re.compile(r"GNU LilyPond (?P<version>\d+\.\d+)(?:\.\d+)?")


def parse_warnings(output: str) -> list[BarCheckWarning]:
    """Every located warning in compiler output, in order, deduplicated.

    LilyPond interprets the music once per backend, so a single bad bar is
    reported twice — once for layout, once for MIDI. Deduplication here keeps
    one mistake from becoming two feedback items.
    """
    seen: dict[tuple[str, int, int, str], BarCheckWarning] = {}
    for match in _DIAGNOSTIC.finditer(output):
        warning = BarCheckWarning(
            file=match["file"],
            line=int(match["line"]),
            column=int(match["column"]),
            message=match["message"],
        )
        seen.setdefault(
            (warning.file, warning.line, warning.column, warning.message), warning
        )
    return list(seen.values())


def parse_bar_check_warnings(output: str) -> list[BarCheckWarning]:
    """Just the bar-check failures — the meter validator's raw material."""
    return [w for w in parse_warnings(output) if _BAR_CHECK in w.message]


def first_error(output: str) -> str | None:
    """The compiler's own description of what went wrong.

    Reported verbatim rather than paraphrased. A guessed diagnosis is worse
    than none: telling a generator to "check durations and bar checks" when the
    real fault was an unknown note name sends it looking in the wrong place,
    and it will spend its whole budget there.
    """
    for match in _ERROR.finditer(output):
        return str(match["message"]).strip()
    return None


class LilypondAdapter:
    """Drives the real compiler. Implements `ScoreRenderer`."""

    def __init__(
        self,
        executable: Path | str = "lilypond",
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        expected_version: str = EXPECTED_VERSION,
        runlog: RunLog | None = None,
    ) -> None:
        self._executable = str(executable)
        self._timeout_s = timeout_s
        self._expected_version = expected_version
        self._version_checked = False
        self._runlog = runlog

    def assert_version(self) -> str:
        """Fail at startup on a version drift, not mid-run on a parse miss.

        Error-message formats — which this module parses — and syntax defaults
        drift between releases, so the version is a hard precondition, checked
        once (docs/06).
        """
        try:
            completed = subprocess.run(
                [self._executable, "--version"],
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except FileNotFoundError as exc:
            raise CadenzraError(
                f"LilyPond executable {self._executable!r} not found"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CadenzraError(
                f"LilyPond {self._executable!r} did not respond to --version"
            ) from exc

        match = _VERSION.search(completed.stdout + completed.stderr)
        if match is None:
            raise CadenzraError(
                f"could not read a version from {self._executable!r}: "
                f"{completed.stdout.strip()[:200]!r}"
            )
        found = match["version"]
        if found != self._expected_version:
            raise CadenzraError(
                f"Cadenzra parses LilyPond {self._expected_version} output, but "
                f"{self._executable!r} is {found}. Bumping the version means "
                "regenerating the captured-stderr fixtures (docs/09)."
            )
        self._version_checked = True
        return found

    def compile(self, lily_source: str, workdir: Path) -> CompileResult:
        """Compile source to PDF and score MIDI inside `workdir`.

        Deterministic input, so there are no retries: a failure is either bad
        notation (routes back as feedback) or a broken environment (aborts the
        run), and the exit status tells them apart (docs/06).
        """
        if not self._version_checked:
            self.assert_version()

        workdir.mkdir(parents=True, exist_ok=True)
        source_path = workdir / f"{SOURCE_STEM}.ly"
        source_path.write_text(lily_source, encoding="utf-8")

        try:
            completed = subprocess.run(
                [
                    self._executable,
                    "-dno-point-and-click",
                    "--output",
                    SOURCE_STEM,
                    source_path.name,
                ],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = _decode(exc.stdout) + _decode(exc.stderr)
            self._record(workdir, clean=False, warnings=0, output=timed_out)
            raise LilypondCompileError(
                f"LilyPond timed out after {self._timeout_s}s compiling {source_path}",
                output=timed_out,
            ) from exc

        output = completed.stdout + completed.stderr
        if completed.returncode != 0:
            # A non-zero exit is a syntax or fatal error: no artifacts exist,
            # so there is nothing for a validator to inspect.
            self._record(workdir, clean=False, warnings=0, output=output)
            raise LilypondCompileError(
                f"LilyPond exited {completed.returncode} compiling {source_path}",
                output=output,
            )

        warnings = parse_bar_check_warnings(output)
        self._record(workdir, clean=not warnings, warnings=len(warnings), output=output)
        pdf_path = workdir / f"{SOURCE_STEM}.pdf"
        midi_path = workdir / f"{SOURCE_STEM}.midi"
        return CompileResult(
            ok=True,
            pdf_path=pdf_path if pdf_path.exists() else None,
            midi_path=midi_path if midi_path.exists() else None,
            bar_check_warnings=warnings,
            raw_output=output,
        )

    def _record(
        self, workdir: Path, *, clean: bool, warnings: int, output: str
    ) -> None:
        """Compiler output is evidence and must survive to the log (docs/06)."""
        if self._runlog is not None:
            self._runlog.compile_event(
                workdir=str(workdir), clean=clean, warnings=warnings, raw_output=output
            )


def _decode(stream: str | bytes | None) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return stream
