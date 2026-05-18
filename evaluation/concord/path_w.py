"""W8 D5 Path W — recompute v3 Opus baseline aggregate metrics.

Reads the symlinked v3 Opus verdict JSONL (frozen 2026-05-08; pointed
to the main worktree via `scripts/concord/setup_w8_path_w.sh`) and
derives the four-verdict-ratio + counts the W8 quad-report compares
the LLM-agent's Path X against.

This module owns NO LLM call and NO PA wrapper call — it is a pure
aggregation over an existing JSONL. The recompute exists so the W8
status / quad-report can quote the same numbers v3 report §1 quotes,
without re-running the 22-minute Opus narrative pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


_DEFAULT_VERDICTS_PATH = Path("data/eval/sub6/v3/sub6b_opus/verdicts_v9_phaseC.jsonl")

_VERDICT_KEYS = ("supported", "unsupported", "contradicted", "unverifiable_v0")


def aggregate_v3_opus_metrics(
    verdicts_jsonl: Path | str = _DEFAULT_VERDICTS_PATH,
) -> dict[str, Any]:
    """Read v3 Opus verdicts JSONL, return aggregate counts + percent.

    Output shape::

        {
            "n_task_records": int,
            "n_error_rows": int,        # rows with non-None `error`
            "counts": {
                "supported": int, "unsupported": int,
                "contradicted": int, "unverifiable_v0": int,
                "total_claims": int,
            },
            "pct": {
                "supported": float, ...
            },
            "source_jsonl": str,
        }

    Percents are over `total_claims` (sum across non-error rows), NOT
    over n_task_records — matches v3 report §1 convention.
    """
    path = Path(verdicts_jsonl)
    if not path.exists():
        raise FileNotFoundError(f"verdict JSONL not found at {path}")

    counts = dict.fromkeys(_VERDICT_KEYS, 0)
    n_task_records = 0
    n_error_rows = 0
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            n_task_records += 1
            if row.get("error") is not None:
                n_error_rows += 1
                continue
            vt = row.get("verdicts_total") or {}
            for k in _VERDICT_KEYS:
                counts[k] += int(vt.get(k, 0) or 0)

    total_claims = sum(counts.values())
    counts["total_claims"] = total_claims
    if total_claims > 0:
        pct = {k: 100.0 * counts[k] / total_claims for k in _VERDICT_KEYS}
    else:
        pct = {k: 0.0 for k in _VERDICT_KEYS}

    return {
        "n_task_records": n_task_records,
        "n_error_rows": n_error_rows,
        "counts": counts,
        "pct": pct,
        "source_jsonl": str(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verdicts", type=Path, default=_DEFAULT_VERDICTS_PATH)
    parser.add_argument("--out", type=Path,
                         default=Path("data/concord/w8_llm_agent/path_w_v3_opus_metrics.json"))
    args = parser.parse_args()

    metrics = aggregate_v3_opus_metrics(args.verdicts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(metrics, indent=2))
    print(f"Path W aggregate from {metrics['source_jsonl']}")
    print(f"  n_task_records: {metrics['n_task_records']}")
    print(f"  n_error_rows:   {metrics['n_error_rows']}")
    print(f"  total_claims:   {metrics['counts']['total_claims']}")
    for k in _VERDICT_KEYS:
        print(f"  {k:<18s}: {metrics['counts'][k]:5d}  ({metrics['pct'][k]:5.2f}%)")
    print(f"saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
