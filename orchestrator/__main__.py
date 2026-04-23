"""CLI entry for the naive orchestrator.

Two input modes:

    python -m orchestrator identify --fixture glucose_pos
    python -m orchestrator identify --report-json /tmp/report.json

`--fixture` runs the full deterministic pipeline then feeds its report to
the LLM; it requires the pipeline dependencies (rdkit / matchms / torch /
sirius binary / ...), i.e. the `diffms` env.

`--report-json` skips the pipeline and loads a previously-serialised
IdentificationReport; it runs happily in the minimal `metagent-llm` env.

Typical two-step flow when the LLM env is not the pipeline env::

    conda run -n diffms python scripts/run_full_pipeline.py \\
        --fixture glucose_pos --output json > /tmp/report.json
    conda run -n metagent-llm env MINIMAX_API_KEY="$(cat api_key.txt)" \\
        python -m orchestrator identify --report-json /tmp/report.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from orchestrator.naive import identify
from schemas.report import IdentificationReport


_FIXTURES = ("glucose_pos", "caffeine_pos", "lcarnitine_pos")


def _load_report_from_fixture(fixture: str) -> IdentificationReport:
    """Import the pipeline lazily so `--report-json` works in minimal envs."""
    try:
        from scripts.run_full_pipeline import (
            _load_fixture,
            identify as run_pipeline,
        )
    except ImportError as exc:
        raise SystemExit(
            f"--fixture requires the full pipeline dependencies "
            f"(rdkit / matchms / torch / ...). ImportError: {exc}\n\n"
            f"Run the pipeline in the diffms env, then feed the JSON to the "
            f"LLM env via --report-json:\n"
            f"  conda run -n diffms python scripts/run_full_pipeline.py "
            f"--fixture {fixture} --output json > /tmp/report.json\n"
            f"  conda run -n metagent-llm env MINIMAX_API_KEY=\"$(cat api_key.txt)\" "
            f"python -m orchestrator identify --report-json /tmp/report.json"
        )
    req, _meta = _load_fixture(fixture)
    return run_pipeline(req)


def _load_report_from_json(path: str) -> IdentificationReport:
    text = Path(path).read_text(encoding="utf-8")
    return IdentificationReport.model_validate_json(text)


def _print_output(result: Any, mode: str) -> None:
    if mode in ("text", "both"):
        print(result.llm_output)
    if mode == "both":
        print("---")
    if mode in ("json", "both"):
        print(result.model_dump_json(indent=2))


def _cmd_identify(args: argparse.Namespace) -> int:
    if args.fixture and args.report_json:
        print(
            "error: --fixture and --report-json are mutually exclusive",
            file=sys.stderr,
        )
        return 1
    if not args.fixture and not args.report_json:
        print(
            "error: one of --fixture or --report-json is required",
            file=sys.stderr,
        )
        return 1

    if args.report_json:
        report = _load_report_from_json(args.report_json)
    else:
        report = _load_report_from_fixture(args.fixture)

    result = identify(report, trace_id=args.trace_id)
    _print_output(result, args.output)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description=(
            "Naive orchestrator (Track O1): one LLM call per "
            "IdentificationReport. No parsing, no retries, no verifier."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "identify",
        help="Wrap an IdentificationReport with one LLM call and print the output.",
    )
    p.add_argument(
        "--fixture",
        choices=_FIXTURES,
        help="Run the full pipeline on this fixture and feed the report to the LLM.",
    )
    p.add_argument(
        "--report-json",
        type=str,
        metavar="PATH",
        help="Path to a serialised IdentificationReport JSON (skips the pipeline).",
    )
    p.add_argument(
        "--output",
        choices=["text", "json", "both"],
        default="text",
        help="'text' (default): just the LLM output. 'json': full NaiveIdentification. 'both': text then --- then json.",
    )
    p.add_argument(
        "--trace-id",
        type=str,
        default=None,
        help="Override the auto-generated trace_id. Useful for deterministic reruns.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "identify":
        try:
            return _cmd_identify(args)
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 — CLI boundary: surface and exit 1
            print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    # argparse's required=True should prevent this.
    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
