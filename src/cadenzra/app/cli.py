"""`cadenzra` — the command line.

One command per thing a person actually does: measure a capability against a
real model, or compose a piece. Errors surface as `CadenzraError` with the path
to whatever was produced; anything else escaping is a bug and crashes with a
traceback, on purpose (docs/07).
"""

import argparse
import sys
from pathlib import Path

from cadenzra.app.config import RunConfig
from cadenzra.app.harness import compare, record, run_voice_trials
from cadenzra.common.errors import CadenzraError
from cadenzra.model.primitives.meter import MeterSpec, simple_meter

_METERS: dict[str, MeterSpec] = {
    "4/4": simple_meter(4, 4),
    "5/4": simple_meter(5, 4, [3, 2]),
    "7/8": simple_meter(7, 8, [2, 2, 3]),
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

    args = parser.parse_args(argv)
    try:
        return _run(args)
    except CadenzraError as error:
        print(f"cadenzra: {error}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    if args.command != "harness":
        raise CadenzraError(f"unknown command {args.command!r}")

    config = RunConfig()
    if args.model:
        config = config.model_copy(update={"generation_model": args.model})

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


if __name__ == "__main__":
    raise SystemExit(main())
