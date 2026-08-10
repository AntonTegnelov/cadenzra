"""The run log records what was actually said, not a summary of it.

The whole value of the flow log is that it is verbatim: a prompt that reads
plausibly in a summary and badly in full is exactly the bug it exists to
surface.
"""

import json
import logging
import threading
from pathlib import Path

from cadenzra.common.runlog import LOGGER_NAME, RunLog, TurnInfo, configure_logging

SYSTEM = "You are a composer."
USER = "Write four bars in 7/8 (2+2+3).\n\nCells: `8 8 8 4.`"


def _flow(log: RunLog) -> list[dict[str, object]]:
    return [json.loads(line) for line in log.flow_path.read_text().splitlines()]


def test_a_turn_is_recorded_verbatim(tmp_path: Path) -> None:
    log = RunLog(tmp_path / "logs")
    log.llm_turn(
        turn=TurnInfo(label="write_part", section_id="B", voice_id="alto"),
        model="gemini-3.6-flash",
        temperature=None,
        attempt=1,
        attempts=3,
        system_prompt=SYSTEM,
        user_prompt=USER,
        tool_name="write_part",
        response={"lily_music": "c'8 d'8 e'8 f'4."},
        thoughts="The 2+2+3 grouping suggests a dotted quarter to close.",
        seconds=2.5,
    )
    log.close()

    (entry,) = _flow(log)
    assert entry["user_prompt"] == USER, "the prompt is stored whole, not trimmed"
    assert entry["system_prompt"] == SYSTEM
    assert entry["section"] == "B" and entry["voice"] == "alto"
    assert entry["response"] == {"lily_music": "c'8 d'8 e'8 f'4."}

    narrative = log.narrative_path.read_text()
    assert "write_part — B / alto" in narrative
    assert "dotted quarter to close" in narrative, "thinking reaches the readable log"
    assert USER in narrative


def test_usage_and_provenance_land_in_the_turn_record(tmp_path: Path) -> None:
    """Token counts are the audit's currency; a turn without them is a guess.

    The cost analysis had to reconstruct every number in it from character
    counts because the client discarded `usage_metadata` — this pins the fields
    that make the next audit a measurement.
    """
    log = RunLog(tmp_path / "logs")
    log.llm_turn(
        turn=TurnInfo(
            label="write_part",
            section_id="B",
            voice_id="alto",
            purpose="repair",
            repairs=("a1b2c3d4",),
        ),
        model="gemini-3.6-flash",
        temperature=None,
        attempt=1,
        attempts=3,
        system_prompt=SYSTEM,
        user_prompt=USER,
        tool_name="write_part",
        response={"lily_music": "c'1"},
        seconds=2.5,
        usage={"input_tokens": 700, "answer_tokens": 90, "thinking_tokens": 510},
        finish_reason="STOP",
        model_version="gemini-3.6-flash-001",
        request_id="req-123",
    )
    log.close()

    (entry,) = _flow(log)
    assert entry["usage"] == {
        "input_tokens": 700,
        "answer_tokens": 90,
        "thinking_tokens": 510,
    }
    assert entry["finish_reason"] == "STOP"
    assert entry["model_version"] == "gemini-3.6-flash-001"
    assert entry["request_id"] == "req-123"
    assert entry["purpose"] == "repair"
    assert entry["repairs"] == ["a1b2c3d4"]


def test_a_turn_without_usage_still_records(tmp_path: Path) -> None:
    """A transport failure has no response to read usage from."""
    log = RunLog(tmp_path / "logs")
    log.llm_turn(
        turn=TurnInfo(label="write_part"),
        model="m",
        temperature=None,
        attempt=1,
        attempts=1,
        system_prompt=SYSTEM,
        user_prompt=USER,
        tool_name="write_part",
        error="boom",
    )
    log.close()

    (entry,) = _flow(log)
    assert entry["usage"] is None
    assert entry["purpose"] == "first", "purpose defaults rather than being absent"


def test_a_wait_is_its_own_event_not_part_of_a_turn(tmp_path: Path) -> None:
    """Backoff sleeps must be legible as waiting, not hidden inside `seconds` —
    a run stalling on quota looked like slow inference in the audit."""
    log = RunLog(tmp_path / "logs")
    log.wait(seconds=40.0, reason="429 RESOURCE_EXHAUSTED")
    log.close()

    (entry,) = _flow(log)
    assert entry["kind"] == "wait"
    assert entry["seconds"] == 40.0
    assert "429" in str(entry["reason"])


def test_validation_items_travel_structured_beside_the_messages(tmp_path: Path) -> None:
    """Cross-sweep survival analysis needed verbatim string matching in the
    audit; a stable identity beside the prose makes it a computation."""
    log = RunLog(tmp_path / "logs")
    items = [
        {
            "id": "deadbeef",
            "kind": "parallels",
            "section": "B",
            "voices": ["cello", "viola"],
            "voice": "viola",
            "bar": 6,
            "message": "cello and viola move in parallel octaves into bar 6",
            "routing": "only-free-voice",
        }
    ]
    log.validation(
        what="the cross-voice checks",
        loop_key="section",
        attempt=1,
        budget=3,
        messages=["cello and viola move in parallel octaves into bar 6"],
        items=items,
    )
    log.close()

    (entry,) = _flow(log)
    assert entry["items"] == items
    assert entry["messages"] == ["cello and viola move in parallel octaves into bar 6"]


def test_a_failed_attempt_is_recorded_too(tmp_path: Path) -> None:
    """The turn that went wrong is the one worth reading."""
    log = RunLog(tmp_path / "logs")
    log.llm_turn(
        turn=TurnInfo(label="write_harmony", section_id="A"),
        model="m",
        temperature=0.7,
        attempt=2,
        attempts=3,
        system_prompt=SYSTEM,
        user_prompt=USER,
        tool_name="write_harmony",
        response=None,
        thoughts=None,
        seconds=1.0,
        error="the model answered without calling write_harmony",
    )
    log.close()

    (entry,) = _flow(log)
    assert entry["error"] == "the model answered without calling write_harmony"
    assert entry["response"] is None
    assert entry["attempt"] == 2
    assert "attempt 2/3" in log.narrative_path.read_text()


def test_compiler_output_survives_to_the_log(tmp_path: Path) -> None:
    """docs/06: compiler stderr is evidence and must reach the log."""
    log = RunLog(tmp_path / "logs")
    log.compile_event(
        workdir="/tmp/work",
        clean=False,
        warnings=2,
        raw_output="score.ly:12:3: warning: barcheck failed at: 3/8",
    )
    log.close()

    (entry,) = _flow(log)
    assert entry["kind"] == "compile"
    assert "barcheck failed at: 3/8" in str(entry["output"])
    assert entry["warnings"] == 2


def test_rejections_leave_the_history_state_drops(tmp_path: Path) -> None:
    """State keeps only current feedback (docs/05); the log keeps the rest."""
    log = RunLog(tmp_path / "logs")
    log.validation(
        what="the alto part for section B",
        loop_key="voice:B:alto",
        attempt=1,
        budget=3,
        messages=["bar 3 has 6 eighths, the meter asks for 7"],
    )
    log.close()

    (entry,) = _flow(log)
    assert entry["kind"] == "validation"
    assert entry["loop_key"] == "voice:B:alto"
    assert entry["messages"] == ["bar 3 has 6 eighths, the meter asks for 7"]
    assert "the meter asks for 7" in log.narrative_path.read_text()


def test_the_technical_log_defaults_to_warning(tmp_path: Path) -> None:
    log = RunLog(tmp_path / "logs")
    logger = logging.getLogger(f"{LOGGER_NAME}.test")
    logger.info("routine progress")
    logger.warning("something is off")
    log.close()

    written = log.technical_path.read_text()
    assert "something is off" in written
    assert "routine progress" not in written


def test_the_technical_log_at_info_traces_everything(tmp_path: Path) -> None:
    log = RunLog(tmp_path / "logs", technical_level="info")
    logging.getLogger(f"{LOGGER_NAME}.test").info("routine progress")
    log.close()

    assert "routine progress" in log.technical_path.read_text()


def test_progress_narration_survives_a_quiet_technical_log(tmp_path: Path) -> None:
    """The console is the human channel; `warning` must not silence it.

    Configuring the level on the logger rather than per handler would have —
    which is why `configure_logging` exists instead of `basicConfig`.
    """
    configure_logging()
    log = RunLog(tmp_path / "logs")  # warning
    console = [h for h in logging.getLogger(LOGGER_NAME).handlers
               if getattr(h, "_cadenzra_console", False)]
    log.close()

    assert console, "a console handler is attached"
    assert console[0].level == logging.INFO
    assert logging.getLogger(LOGGER_NAME).isEnabledFor(logging.INFO)


def test_concurrent_turns_do_not_interleave(tmp_path: Path) -> None:
    """Voices generate in a thread pool; half-written JSON lines would be
    unparseable exactly when a run is at its busiest."""
    log = RunLog(tmp_path / "logs")

    def record(index: int) -> None:
        log.llm_turn(
            turn=TurnInfo(label="write_part", section_id="A", voice_id=f"v{index}"),
            model="m",
            temperature=None,
            attempt=1,
            attempts=1,
            system_prompt=SYSTEM,
            user_prompt=USER * 20,
            tool_name="write_part",
            response={"lily_music": "c'1"},
            thoughts=None,
            seconds=0.1,
        )

    threads = [threading.Thread(target=record, args=(i,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    log.close()

    entries = _flow(log)
    assert len(entries) == 12
    assert sorted(int(str(e["seq"])) for e in entries) == list(range(1, 13))
