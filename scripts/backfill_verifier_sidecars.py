"""Backfill verifier sidecars for cached UI fixtures.

For each fixture:
  1. Load the IdentificationReport from `/data/.../pipeline_runs/<trace>.json`
     (or `/tmp/o1/<fixture>.json` fallback).
  2. Pull the most-recent orchestrator LLM output for the matching
     trace_id from `logs/llm_calls.jsonl`.
  3. Call `verifier.agent.verify(...)` against (llm_output, report,
     trace_id=<trace_id>_verified).
  4. Persist `VerifiedIdentification.model_dump_json()` to
     `/data/.../verifier_runs/<trace>.verifier.json` (the path the UI
     loader scans).

Idempotent — re-running on a fixture whose sidecar already exists is a
no-op unless `--force` is passed. Skips fixtures whose orchestrator
LLM output cannot be located.

Run from the metagent-llm conda env::

    MINIMAX_API_KEY=... \\
    conda run -n metagent-llm python scripts/backfill_verifier_sidecars.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Fixture inventory — pairs (canonical_fixture_name, trace_id_to_use).
# ---------------------------------------------------------------------------

FIXTURES: list[tuple[str, str]] = [
    ("glucose_pos", "o1-part4-glucose_pos"),
    ("caffeine_pos", "o1-part4-caffeine_pos"),
    ("lcarnitine_pos", "o1-part4-lcarnitine_pos"),
    ("glucose_pos_fusion", "o1-part4-glucose_pos_fusion"),
]


def _load_report(fixture: str, trace_id: str) -> dict | None:
    from ui.data.loaders import _load_json, find_report_path

    path = find_report_path(fixture, trace_id)
    if path is None:
        return None
    try:
        return _load_json(path)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! failed to load {path}: {exc}", file=sys.stderr)
        return None


def _load_llm_output(trace_id: str) -> str | None:
    log_path = _REPO_ROOT / "logs" / "llm_calls.jsonl"
    if not log_path.exists():
        return None
    chosen: dict | None = None
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("trace_id") == trace_id and row.get(
            "caller"
        ) == "orchestrator.naive.identify":
            chosen = row  # take the latest match
    return (chosen or {}).get("response_cleaned")


def _run_one(fixture: str, trace_id: str, *, force: bool) -> str:
    """Returns a one-line status string."""
    from schemas.report import IdentificationReport
    from ui.data.loaders import verifier_sidecar_path
    from verifier.agent import verify

    sidecar = verifier_sidecar_path(trace_id)
    if sidecar.exists() and not force:
        return f"  · {fixture}: sidecar already exists at {sidecar}, skipping (use --force to overwrite)"

    report_dict = _load_report(fixture, trace_id)
    if report_dict is None:
        return f"  ! {fixture}: no IdentificationReport found"

    llm_output = _load_llm_output(trace_id)
    if not llm_output:
        return f"  ! {fixture}: no orchestrator log row for {trace_id}"

    try:
        source_report = IdentificationReport.model_validate(report_dict)
    except Exception as exc:  # noqa: BLE001
        return f"  ! {fixture}: report failed validation: {type(exc).__name__}: {exc}"

    t0 = time.time()
    try:
        verified = verify(
            llm_output, source_report,
            trace_id=f"{trace_id}_verified",
        )
    except Exception as exc:  # noqa: BLE001
        return f"  ! {fixture}: verifier crashed: {type(exc).__name__}: {exc}"
    elapsed = time.time() - t0

    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps(verified.model_dump(mode="json"), ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return (
        f"  ✓ {fixture}: {verified.overall_verdict} "
        f"({len(verified.claims_v1)} v1, {len(verified.claims_v2)} v2, "
        f"{verified.llm_call_count} LLM calls, {elapsed:.0f}s) → {sidecar}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing sidecars.")
    ap.add_argument("--fixtures", nargs="+", default=None,
                    help="Subset of fixture names to backfill.")
    args = ap.parse_args(argv)

    pairs = [
        (f, tid) for (f, tid) in FIXTURES
        if (args.fixtures is None or f in args.fixtures)
    ]
    print(f"Backfilling {len(pairs)} fixture(s).")
    print(f"Sidecar dir: /data/weiwentao/llm_agent_metabolomics/verifier_runs/")
    print()
    for fixture, trace_id in pairs:
        print(_run_one(fixture, trace_id, force=args.force), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
