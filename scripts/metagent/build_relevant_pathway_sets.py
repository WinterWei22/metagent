#!/usr/bin/env python3
"""Build relevant-pathway-set sidecar for easy_v3 (Decision①)."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from concord.agent.pathway_relevant_set import (
    build_relevant_set_modelorg,
    build_relevant_set_ramp,
)

DEFAULT_BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
DEFAULT_RAMP = Path("/data/weiwentao/llm_agent_metabolomics/ramp.sqlite")
DEFAULT_MEMBERS = ROOT / "data/concord/pathway_members.sqlite"
DEFAULT_OUT = ROOT / "data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json"


def stratum_of(task_id: str) -> str:
    if "human1" in task_id:
        return "human1"
    if "recon2_2" in task_id or "recon2" in task_id:
        return "recon2"
    if "hmdb_ramp" in task_id:
        return "hmdb_ramp"
    if task_id.startswith("sub6"):
        return "sub6"
    return "other"


def build_all(
    benchmark_rows: list[dict],
    ramp_conn: sqlite3.Connection,
    members_conn: sqlite3.Connection,
    *,
    jaccard_threshold: float = 0.3,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in benchmark_rows:
        task_id = row["task_id"]
        gt = row["ground_truth"]["perturbed_pathway"]
        stratum = stratum_of(task_id)
        if stratum in {"sub6", "hmdb_ramp"}:
            names = build_relevant_set_ramp(
                ramp_conn, gt["id"], jaccard_threshold=jaccard_threshold
            )
            source = "ramp"
        elif stratum in {"human1", "recon2"}:
            names = build_relevant_set_modelorg(
                members_conn, gt["name"], stratum, jaccard_threshold=jaccard_threshold
            )
            source = stratum
        else:
            names = set()
            source = "other"
        out[task_id] = {
            "source": source,
            "relevant_names": sorted(names),
            "size": len(names),
        }
    return out


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--ramp", type=Path, default=DEFAULT_RAMP)
    ap.add_argument("--members", type=Path, default=DEFAULT_MEMBERS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--jaccard-threshold", type=float, default=0.3)
    args = ap.parse_args()
    rows = _load_jsonl(args.benchmark)
    ramp_conn = sqlite3.connect(f"file:{args.ramp}?mode=ro", uri=True)
    members_conn = sqlite3.connect(f"file:{args.members}?mode=ro", uri=True)
    out = build_all(rows, ramp_conn, members_conn, jaccard_threshold=args.jaccard_threshold)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(out)} relevant-sets -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
