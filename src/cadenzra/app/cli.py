"""`cadenzra` — the command line.

One command per thing a person actually does: measure a capability against a
real model, or compose a piece. Errors surface as `CadenzraError` with the path
to whatever was produced; anything else escaping is a bug and crashes with a
traceback, on purpose (docs/07).
"""

import argparse
import logging
import sys
from pathlib import Path

from cadenzra.app.compose import build_compose_services, compose
from cadenzra.app.config import RunConfig
from cadenzra.app.factory import build_generator, build_renderer
from cadenzra.app.harness import compare, record, run_voice_trials
from cadenzra.app.pipeline import (
    LayerServices,
    derive_style,
    generate_harmony,
    generate_motifs,
    plan_structure,
)
from cadenzra.app.specs import SPECS
from cadenzra.common.errors import CadenzraError
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
    harness.add_argument("capability", choices=["voice"])
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
    harness.add_argument("--workdir", type=Path, default=Path("out/harness"))
    harness.add_argument(
        "--no-record", action="store_true", help="do not write results to docs/"
    )

    layers = commands.add_parser(
        "layers", help="run the structured layers live for one spec"
    )
    layers.add_argument("spec", choices=sorted(SPECS))
    layers.add_argument("--model", default=None)
    layers.add_argument("--workdir", type=Path, default=Path("out/layers"))

    compose_cmd = commands.add_parser("compose", help="compose a piece end to end")
    compose_cmd.add_argument("spec", choices=sorted(SPECS))
    compose_cmd.add_argument("--model", default=None)
    compose_cmd.add_argument("--out", type=Path, default=None)

    args = parser.parse_args(argv)
    try:
        return _run(args)
    except CadenzraError as error:
        print(f"cadenzra: {error}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    config = RunConfig()
    if args.model:
        config = config.model_copy(update={"generation_model": args.model})

    if args.command == "layers":
        return _run_layers(config, args)
    if args.command == "compose":
        return _run_compose(config, args)
    if args.command != "harness":
        raise CadenzraError(f"unknown command {args.command!r}")

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


def _run_layers(config: RunConfig, args: argparse.Namespace) -> int:
    """Run style, plan, motifs and harmony live, and report what came back."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    spec = SPECS[args.spec]
    services = LayerServices(
        generator=build_generator(config),
        renderer=build_renderer(config),
        workdir=args.workdir / args.spec,
        budgets=config.budgets,
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
    return 0


def _run_compose(config: RunConfig, args: argparse.Namespace) -> int:
    """Compose one piece and report where its artifacts landed."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    spec = SPECS[args.spec]
    out = args.out or config.output_dir / args.spec
    services = build_compose_services(config, out)

    try:
        state = compose(spec, services)
    except CadenzraError as error:
        print(f"cadenzra: {error}", file=sys.stderr)
        print(f"cadenzra: partial artifacts written to {out}", file=sys.stderr)
        return 1

    artifacts = state.artifacts
    assert artifacts is not None and state.structure is not None
    print()
    print(f"{spec.title} — {len(state.structure.sections)} sections, "
          f"{len(state.voices)} parts")
    for label, path in (
        ("score", artifacts.lily_path),
        ("pdf", artifacts.pdf_path),
        ("score midi", artifacts.score_midi_path),
        ("performance", artifacts.performance_midi_path),
        ("audio", artifacts.audio_path),
    ):
        print(f"  {label:12} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
