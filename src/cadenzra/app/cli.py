"""`cadenzra` — the command line.

One command per thing a person actually does: measure a capability against a
real model, or compose a piece. Errors surface as `CadenzraError` with the path
to whatever was produced; anything else escaping is a bug and crashes with a
traceback, on purpose (docs/07).
"""

import argparse
import sys
from pathlib import Path

from cadenzra.app.compose import build_compose_services, compose, load_resume_state
from cadenzra.app.config import RunConfig
from cadenzra.app.factory import build_generator, build_renderer, open_run_log
from cadenzra.app.harness import (
    compare,
    record,
    run_lyric_trials,
    run_voice_trials,
)
from cadenzra.app.pipeline import (
    LayerServices,
    derive_style,
    generate_harmony,
    generate_motifs,
    plan_structure,
)
from cadenzra.app.specs import SPECS
from cadenzra.common.errors import CadenzraError
from cadenzra.common.runlog import configure_logging
from cadenzra.model.primitives.meter import MeterSpec, MeterTerm, simple_meter
from cadenzra.model.state import PipelineState

_METERS: dict[str, MeterSpec] = {
    "4/4": simple_meter(4, 4),
    "5/4": simple_meter(5, 4, [3, 2]),
    "7/8": simple_meter(7, 8, [2, 2, 3]),
    "11/8": simple_meter(11, 8, [3, 3, 3, 2]),
    "3/4+1/8": MeterSpec(
        terms=[MeterTerm(numerator=3, denominator=4), MeterTerm(numerator=1, denominator=8)],
        grouping=[2, 2, 3],
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cadenzra", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    harness = commands.add_parser(
        "harness", help="measure one capability against the real model"
    )
    harness.add_argument("capability", choices=["voice", "lyrics"])
    harness.add_argument("--meter", choices=sorted(_METERS), default="7/8")
    harness.add_argument("--trials", type=int, default=10)
    harness.add_argument("--bars", type=int, default=8)
    harness.add_argument("--budget", type=int, default=3)
    harness.add_argument("--model", default=None)
    harness.add_argument(
        "--ab",
        action="store_true",
        help="run the rhythmic-cell surface A/B and report both arms",
    )
    harness.add_argument(
        "--scheme", default="AABB", help="rhyme scheme for lyric trials"
    )
    harness.add_argument(
        "--devices",
        default="",
        help="comma-separated lyric devices to demand, for lyric trials",
    )
    harness.add_argument("--workdir", type=Path, default=Path("out/harness"))
    harness.add_argument(
        "--no-record", action="store_true", help="do not write results to docs/"
    )
    _add_log_level(harness)

    layers = commands.add_parser(
        "layers", help="run the structured layers live for one spec"
    )
    layers.add_argument("spec", choices=sorted(SPECS))
    layers.add_argument("--model", default=None)
    layers.add_argument("--workdir", type=Path, default=Path("out/layers"))
    _add_log_level(layers)

    compose_cmd = commands.add_parser("compose", help="compose a piece end to end")
    compose_cmd.add_argument("spec", choices=sorted(SPECS))
    compose_cmd.add_argument("--model", default=None)
    compose_cmd.add_argument("--out", type=Path, default=None)
    compose_cmd.add_argument(
        "--no-critique", action="store_true", help="skip the audio listening pass"
    )
    compose_cmd.add_argument(
        "--resume",
        action="store_true",
        help="pick up from the last run's state.json instead of starting over",
    )
    _add_log_level(compose_cmd)

    replay_cmd = commands.add_parser(
        "replay", help="re-fire one logged LLM turn against the current code"
    )
    replay_cmd.add_argument("spec", choices=sorted(SPECS))
    replay_cmd.add_argument("run", help="run timestamp under out/<spec>/runs/")
    replay_cmd.add_argument("seq", type=int, help="the turn's seq in llm.jsonl")
    replay_cmd.add_argument("--model", default=None)
    _add_log_level(replay_cmd)

    audit_cmd = commands.add_parser(
        "audit",
        help="replay every stored state through the current validators — no API",
    )
    audit_cmd.add_argument("--out", type=Path, default=Path("out"))
    audit_cmd.add_argument("--workdir", type=Path, default=Path("out/audit-work"))
    audit_cmd.add_argument(
        "--json", type=Path, default=None, help="also write the full report as JSON"
    )
    _add_log_level(audit_cmd)

    args = parser.parse_args(argv)
    try:
        return _run(args)
    except CadenzraError as error:
        print(f"cadenzra: {error}", file=sys.stderr)
        return 1


def _add_log_level(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default=None,
        help="threshold for the run's technical log (default: warning)",
    )


def _run(args: argparse.Namespace) -> int:
    configure_logging()
    if args.command == "audit":
        from cadenzra.app.audit import run_audit
        from cadenzra.rendering.lilypond import LilypondAdapter

        print(
            run_audit(
                args.out, LilypondAdapter(), args.workdir, json_path=args.json
            )
        )
        return 0

    config = RunConfig()
    if args.model:
        config = config.model_copy(update={"generation_model": args.model})
    if getattr(args, "log_level", None):
        config = config.model_copy(update={"log_level": args.log_level})

    if args.command == "replay":
        from cadenzra.app.replay import run_replay

        return run_replay(config, SPECS[args.spec], args.spec, args.run, args.seq)
    if args.command == "layers":
        return _run_layers(config, args)
    if args.command == "compose":
        return _run_compose(config, args)
    if args.command != "harness":
        raise CadenzraError(f"unknown command {args.command!r}")

    if args.capability == "lyrics":
        return _run_lyric_harness(config, args)

    meter = _METERS[args.meter]
    variants = [True, False] if args.ab else [True]

    reports = []
    for with_cells in variants:
        report = run_voice_trials(
            config,
            meter,
            trials=args.trials,
            budget=args.budget,
            bars=args.bars,
            with_cells=with_cells,
            workdir=args.workdir / ("cells" if with_cells else "no-cells"),
        )
        reports.append(report)
        print(report.summary())
        if not args.no_record:
            print(f"  recorded to {record(report)}")

    if len(reports) > 1:
        print()
        print(compare(reports))

    return 0 if all(report.pass_rate >= 0.8 for report in reports) else 1


def _run_lyric_harness(config: RunConfig, args: argparse.Namespace) -> int:
    """Measure the words: singable against the notes, and in the stated scheme."""
    devices = [d.strip() for d in args.devices.split(",") if d.strip()]
    report = run_lyric_trials(
        config,
        trials=args.trials,
        budget=args.budget,
        scheme=args.scheme,
        devices=devices,
        workdir=args.workdir / "lyrics",
    )
    print(report.summary())
    if not args.no_record:
        print(f"  recorded to {record(report)}")
    return 0 if report.pass_rate >= 0.8 else 1


def _run_layers(config: RunConfig, args: argparse.Namespace) -> int:
    """Run style, plan, motifs and harmony live, and report what came back."""
    spec = SPECS[args.spec]
    runlog = open_run_log(config, args.workdir / args.spec)
    services = LayerServices(
        generator=build_generator(config, runlog),
        renderer=build_renderer(config, runlog),
        workdir=args.workdir / args.spec,
        budgets=config.budgets,
        runlog=runlog,
    )

    state = PipelineState(spec=spec)
    state = derive_style(state, services)
    state = plan_structure(state, services)
    state = generate_motifs(state, services)
    state = generate_harmony(state, services)

    assert state.style is not None and state.structure is not None
    print()
    print(f"{spec.title}: {state.structure.form_summary}")
    print(
        f"  style: {len(state.style.idioms)} idioms, "
        f"{len(state.style.rhythmic_cells)} rhythmic cells, "
        f"parallels {state.style.parallel_fifths_policy}"
    )
    for section in state.structure.sections:
        skeleton = state.harmony[section.section_id]
        entries = (
            f", {len(section.material)} declared entries" if section.material else ""
        )
        print(
            f"  {section.section_id}: {section.bars} bars of "
            f"{section.meter.surface_string()}, {section.key}, {section.tempo_bpm}bpm, "
            f"{section.texture}, {len(skeleton.events)} chords{entries}"
        )
    if state.motifs is not None:
        for motif in state.motifs.motifs.values():
            print(f"  {motif.motif_id} ({motif.role}): {motif.lily_music}")

    out = args.workdir / args.spec / "state.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    print(f"\n  state written to {out}")
    print(f"  run log      {runlog.dir}")
    return 0


def _run_compose(config: RunConfig, args: argparse.Namespace) -> int:
    """Compose one piece and report where its artifacts landed."""
    spec = SPECS[args.spec]
    out = args.out or config.output_dir / args.spec
    initial = load_resume_state(out, spec) if args.resume else None
    services = build_compose_services(
        config, out, with_critic=not args.no_critique, spec_name=args.spec
    )

    try:
        state = compose(spec, services, initial=initial)
    except CadenzraError as error:
        print(f"cadenzra: {error}", file=sys.stderr)
        print(f"cadenzra: partial artifacts written to {out}", file=sys.stderr)
        assert services.runlog is not None
        print(f"cadenzra: the run log is at {services.runlog.dir}", file=sys.stderr)
        return 1

    artifacts = state.artifacts
    assert artifacts is not None and state.structure is not None
    print()
    print(f"{spec.title} — {len(state.structure.sections)} sections, "
          f"{len(state.voices)} parts")
    if state.feedback:
        print("\n  the critic still had concerns:")
        for item in state.feedback:
            print(f"    [{item.level}] {item.message}")
    print()
    for label, path in (
        ("score", artifacts.lily_path),
        ("pdf", artifacts.pdf_path),
        ("score midi", artifacts.score_midi_path),
        ("performance", artifacts.performance_midi_path),
        ("audio", artifacts.audio_path),
        ("run log", services.runlog.dir if services.runlog else None),
    ):
        print(f"  {label:12} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
