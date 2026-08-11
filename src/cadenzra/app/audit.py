"""`cadenzra audit` — the stored corpus through the current validators, free.

Two instruments, no API calls:

1. **Validator replay**: every stored `state.json` (per-run and the completed
   spec-level ones) is run through every deterministic validator that applies
   to the slices it holds. The completed states are the only material that
   exercises assembly and lyrics across many styles, and a ledger diff after
   any validator change shows what it would now flag — for the price of some
   LilyPond compiles.
2. **Frequency ledger**: every stored run log's `validation` records,
   aggregated by layer and item kind. This is the measured "common vs rare"
   split the surface design principle needs: constraints that fire routinely
   earn a place in the first prompt; rare ones are taught by the rejection
   that catches them (docs/08).

The pipeline's own `load_resume_state` is deliberately not used: it wipes
sections, score and artifacts, which are exactly what the completed states
are here to exercise.
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from cadenzra.app.pipeline import analyzed_motifs
from cadenzra.interfaces.rendering import ScoreRenderer
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.state import PipelineState
from cadenzra.verification.harmony import (
    check_entries_against_grid,
    validate_harmony,
)
from cadenzra.verification.lyrics import validate_section_lyrics
from cadenzra.verification.motifs import validate_motifs
from cadenzra.verification.structure import validate_structure
from cadenzra.verification.style import validate_style_pack
from cadenzra.verification.voice import validate_voice


@dataclass(frozen=True)
class Finding:
    """One validator complaint about one stored state."""

    spec: str
    run: str  # run timestamp, or "spec-level" for completed states
    layer: str
    kind: str
    message: str


def audit_state(
    spec_name: str,
    run_name: str,
    state: PipelineState,
    renderer: ScoreRenderer,
    workdir: Path,
) -> list[Finding]:
    """Every applicable validator over one stored state's slices."""

    def found(layer: str, items: list[FeedbackItem]) -> list[Finding]:
        return [
            Finding(
                spec=spec_name,
                run=run_name,
                layer=layer,
                kind=item.kind or "unspecified",
                message=item.message,
            )
            for item in items
        ]

    findings: list[Finding] = []
    scratch = workdir / spec_name / run_name

    if state.style is not None:
        findings += found(
            "style", validate_style_pack(state.style, state.spec, renderer, scratch / "style")
        )
    if state.structure is not None:
        findings += found(
            "structure", validate_structure(state.structure, state.spec)
        )
    if state.motifs is not None and state.structure is not None:
        # When the style pack was dropped (legacy states), the policy is
        # unknown — default permissive: a discovery tool that guesses
        # "forbid" flags deliberate octave doubling as a fault (minimal's
        # doubled piano pattern, measured).
        policy = state.style.parallel_fifths_policy if state.style else "allow"
        findings += found(
            "motif",
            validate_motifs(
                state.motifs,
                state.structure,
                state.spec,
                renderer,
                scratch / "motifs",
                parallel_policy=policy,
            ),
        )

    if state.structure is not None:
        motif_notes = (
            analyzed_motifs(state, renderer, scratch / "analyzed")
            if state.motifs is not None
            else {}
        )
        dissonance = state.style.dissonance_policy if state.style else ""
        for section in state.structure.sections:
            skeleton = state.harmony.get(section.section_id)
            if skeleton is not None:
                findings += found("harmony", validate_harmony(skeleton, section))
                findings += found(
                    "harmony",
                    check_entries_against_grid(
                        skeleton, section, motif_notes, dissonance
                    ),
                )

        sections_by_id = state.structure.sections_by_id
        for part in state.voices.values():
            part_section = sections_by_id.get(part.section_id)
            voice = state.spec.voices_by_id.get(part.voice_id)
            if part_section is None or voice is None:
                continue
            findings += found(
                "voice",
                validate_voice(
                    part,
                    voice,
                    part_section,
                    renderer,
                    scratch / f"voice-{part.section_id}-{part.voice_id}",
                ),
            )

        if state.lyric_plan is not None:
            directives = {
                directive.section_id: directive
                for directive in state.lyric_plan.directives
            }
            for section_id, lyrics in state.lyrics.items():
                directive = directives.get(section_id)
                sung_section = sections_by_id.get(section_id)
                if directive is None or sung_section is None:
                    continue
                parts = {
                    part.voice_id: part
                    for part in state.voices.values()
                    if part.section_id == section_id
                }
                refrain_source = (
                    state.lyrics.get(directive.refrain_of)
                    if directive.refrain_of
                    else None
                )
                findings += found(
                    "lyric",
                    validate_section_lyrics(
                        lyrics,
                        directive,
                        sung_section,
                        parts,
                        language=state.lyric_plan.language,
                        renderer=renderer,
                        workdir=scratch / f"lyrics-{section_id}",
                        refrain_source=refrain_source,
                    ),
                )
    return findings


def audit_states(
    out_dir: Path, renderer: ScoreRenderer, workdir: Path
) -> list[Finding]:
    """Every stored state under `out_dir` through `audit_state`."""
    findings: list[Finding] = []
    for spec_dir in sorted(path for path in out_dir.iterdir() if path.is_dir()):
        candidates = [(spec_dir / "state.json", "spec-level")]
        runs = spec_dir / "runs"
        if runs.is_dir():
            candidates += [
                (run / "state.json", run.name) for run in sorted(runs.iterdir())
            ]
        for path, run_name in candidates:
            if not path.exists():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            try:
                state = PipelineState.model_validate(raw)
            except ValidationError as first_error:
                # History the audit did not write: 83 of 91 stored states
                # predate StyleFragment and fail only on the style pack. The
                # structure, voices and score slices are the audit's real
                # material, so drop the style pack visibly and keep going;
                # a state unreadable beyond that is reported, never fatal.
                try:
                    state = PipelineState.model_validate(
                        {key: value for key, value in raw.items() if key != "style"}
                    )
                except ValidationError:
                    findings.append(
                        Finding(
                            spec=spec_dir.name,
                            run=run_name,
                            layer="state",
                            kind="unreadable-legacy",
                            message=str(first_error).splitlines()[0],
                        )
                    )
                    continue
                findings.append(
                    Finding(
                        spec=spec_dir.name,
                        run=run_name,
                        layer="state",
                        kind="legacy-style-dropped",
                        message=str(first_error).splitlines()[0],
                    )
                )
            findings += audit_state(
                spec_dir.name, run_name, state, renderer, workdir
            )
    return findings


def frequency_ledger(out_dir: Path) -> Counter[tuple[str, str]]:
    """(layer, item kind) -> occurrences, across every stored run log.

    The measured common-vs-rare split: layers come from the loop key
    ("voice:B:alto" -> "voice"), kinds from the structured items; runs old
    enough to lack structured items count as "unstructured" so their volume
    still shows.
    """
    ledger: Counter[tuple[str, str]] = Counter()
    for log in sorted(out_dir.glob("*/runs/*/llm.jsonl")):
        for line in log.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("kind") != "validation":
                continue
            layer = str(record.get("loop_key", "unknown")).split(":")[0]
            items = record.get("items") or []
            if not items:
                ledger[(layer, "unstructured")] += len(
                    record.get("messages") or []
                )
            for item in items:
                ledger[(layer, item.get("kind") or "unspecified")] += 1
    return ledger


def run_audit(
    out_dir: Path,
    renderer: ScoreRenderer,
    workdir: Path,
    *,
    json_path: Path | None = None,
) -> str:
    """The full audit, as a printable report (and optionally a JSON dump)."""
    ledger = frequency_ledger(out_dir)
    findings = audit_states(out_dir, renderer, workdir)

    lines = ["# Frequency ledger (stored run logs)", ""]
    for (layer, kind), count in ledger.most_common():
        lines.append(f"  {layer:<12} {kind:<24} {count}")
    lines += ["", "# Current validators over stored states", ""]
    by_group = Counter(
        (finding.spec, finding.layer, finding.kind) for finding in findings
    )
    for (spec, layer, kind), count in by_group.most_common():
        lines.append(f"  {spec:<14} {layer:<10} {kind:<24} {count}")
    lines.append("")
    lines.append(
        f"{sum(ledger.values())} logged items across "
        f"{len(ledger)} (layer, kind) groups; "
        f"{len(findings)} findings from current validators."
    )
    report = "\n".join(lines)

    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(
                {
                    "ledger": [
                        {"layer": layer, "kind": kind, "count": count}
                        for (layer, kind), count in ledger.most_common()
                    ],
                    "findings": [vars(finding) for finding in findings],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return report
