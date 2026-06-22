#!/usr/bin/env python3
"""Build gold-driver sidecar for easy_v3 (Decision②); sub6/hmdb_ramp only."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from concord.agent.driver_gold import build_gold_drivers_ramp

DEFAULT_BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
DEFAULT_RAMP = Path("/data/weiwentao/llm_agent_metabolomics/ramp.sqlite")
DEFAULT_OUT = ROOT / "data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json"

_NA = {"human1", "recon2"}


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


def is_na_stratum(stratum: str) -> bool:
    return stratum in _NA


def build_all(benchmark_rows: list[dict], ramp_conn: sqlite3.Connection) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {}
    for row in benchmark_rows:
        task_id = row["task_id"]
        stratum = stratum_of(task_id)
        if is_na_stratum(stratum) or stratum == "other":
            out[task_id] = None
            continue
        gt = row["ground_truth"]["perturbed_pathway"]
        input_ids = [m["id"] for m in row["input"]["differential_metabolites"]]
        gold = build_gold_drivers_ramp(ramp_conn, input_ids, gt["id"])
        out[task_id] = {"gold_ramp_ids": sorted(gold)}
    return out


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--ramp", type=Path, default=DEFAULT_RAMP)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    rows = _load_jsonl(args.benchmark)
    ramp_conn = sqlite3.connect(f"file:{args.ramp}?mode=ro", uri=True)
    out = build_all(rows, ramp_conn)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n_gold = sum(1 for v in out.values() if v is not None)
    print(f"wrote {len(out)} rows ({n_gold} with gold drivers) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
