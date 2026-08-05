"""A `ScoreRenderer` that records what it was asked to compile."""

from pathlib import Path

from cadenzra.model.artifacts import BarCheckWarning, CompileResult


class RecordingRenderer:
    """Returns a scripted verdict per call and remembers every source.

    Scripted verdicts are keyed by call index, so a test can say "the first
    compile fails a bar check, the second is clean" without any real LilyPond.
    """

    def __init__(self, verdicts: list[CompileResult] | None = None) -> None:
        self._verdicts = list(verdicts or [])
        self.sources: list[str] = []

    def compile(self, lily_source: str, workdir: Path) -> CompileResult:
        self.sources.append(lily_source)
        if not self._verdicts:
            return CompileResult(ok=True)
        index = min(len(self.sources) - 1, len(self._verdicts) - 1)
        return self._verdicts[index]

    @property
    def calls(self) -> int:
        return len(self.sources)


def clean() -> CompileResult:
    return CompileResult(ok=True)


def failing_bar_check(line: int, column: int = 1, remainder: str = "1/8") -> CompileResult:
    return CompileResult(
        ok=True,
        bar_check_warnings=[
            BarCheckWarning(
                line=line, column=column, message=f"bar check failed at: {remainder}"
            )
        ],
    )
