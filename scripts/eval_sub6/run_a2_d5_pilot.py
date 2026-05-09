"""A2 D5 — 20-task pilot (single / react / react+feedback) on MiniMax.

Selection: 10 LM lipid (lm_pathway_WP167_seed{0..9}) + 4 D4-overlap
non-LM tasks + 6 fresh random non-LM (seed=42), 20 total. The 4 D4
non-LM overlaps give us a sanity baseline (verdict diff vs v4_a2_d4
within ±1 claim). The lipid seed4 already ran in D4 too, so 5 of 20
tasks are D4 reuses.

Output: data/eval/sub6/v4_a2_d5/{single,react,feedback}/{task_id}/
        + summary.json + hash_check.json + sanity_check.json
        + (audit author writes phase_a2_feedback_audit.md afterwards)

The actual per-task plumbing is reused from
``scripts/eval_sub6/run_a2_d4_3way.py`` — D5 just supplies a different
20-task selection + post-run sanity-check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation.sub6.io_utils import iter_jsonl
from evaluation.sub6.run_sub6b import _resolve_api_key
from scripts.eval_sub6.grade_with_verifier import _build_driver_lookup
from scripts.eval_sub6.run_a2_d4_3way import _process_one_task, _persist_json

logger = logging.getLogger(__name__)


# 4 D4-overlap non-LM tasks — must be in D5 pilot per spec.
D4_NONLM_OVERLAP = [
    "compound_only_enrich_mammalian_RAMP_P_000000016_seed1",   # amino_acid
    "compound_only_enrich_mammalian_RAMP_P_000000398_seed0",   # central
    "compound_only_enrich_mammalian_RAMP_P_000053306_seed1",   # nucleotide (F4)
    "compound_only_enrich_mammalian_RAMP_P_000050021_seed0",   # other
]
# All 10 LM lipid tasks.
LM_TASKS = [
    f"compound_only_enrich_mammalian_lm_pathway_WP167_seed{i}"
    for i in range(10)
]


def select_pilot_tasks(all_tasks: dict[str, dict], *, n_random: int = 6, seed: int = 42) -> list[str]:
    """Build the 20-task pilot selection.

    Layout:
      - 10 LM lipid tasks (all WP167_seed{0..9}) — fixed
      - 4 D4-overlap non-LM tasks — fixed (sanity baseline)
      - n_random additional non-LM tasks, seed=42 deterministic random
        sample from the remaining non-LM pool (excluding LM, excluding
        D4 overlaps)
    """
    selected = list(LM_TASKS) + list(D4_NONLM_OVERLAP)
    pool = [
        tid for tid in all_tasks
        if "lm_pathway" not in tid and tid not in D4_NONLM_OVERLAP
    ]
    rng = random.Random(seed)
    fresh = rng.sample(sorted(pool), n_random)
    return selected + fresh


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sanity_compare(d5_root: Path, d4_root: Path, overlap_ids: list[str]) -> dict:
    """Read d5/{variant}/{tid}/verdict.json and d4 counterpart; diff."""
    rows = []
    for tid in overlap_ids:
        for variant in ("single", "react", "feedback"):
            d5_path = d5_root / variant / tid / "verdict.json"
            d4_path = d4_root / variant / tid / "verdict.json"
            if not d5_path.is_file() or not d4_path.is_file():
                rows.append({
                    "task_id": tid, "variant": variant,
                    "status": "missing",
                    "d5_present": d5_path.is_file(),
                    "d4_present": d4_path.is_file(),
                })
                continue
            d5 = json.loads(d5_path.read_text())
            d4 = json.loads(d4_path.read_text())
            d5_total = d5.get("verdicts_total") or {}
            d4_total = d4.get("verdicts_total") or {}
            keys = set(d5_total) | set(d4_total)
            deltas = {k: d5_total.get(k, 0) - d4_total.get(k, 0) for k in keys}
            n_d5 = sum(d5_total.values())
            n_d4 = sum(d4_total.values())
            max_abs_delta = max((abs(v) for v in deltas.values()), default=0)
            rows.append({
                "task_id": tid, "variant": variant,
                "n_claims_d5": n_d5, "n_claims_d4": n_d4,
                "deltas": deltas,
                "max_abs_delta": max_abs_delta,
                "within_noise": max_abs_delta <= 1,
                "status": "ok",
            })
    n_within = sum(1 for r in rows if r.get("within_noise"))
    n_total = sum(1 for r in rows if r["status"] == "ok")
    n_outliers = n_total - n_within
    return {
        "n_overlap_variants": n_total,
        "n_within_noise_pm1": n_within,
        "n_outliers_gt1": n_outliers,
        "all_within_noise": n_outliers == 0,
        "per_row": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tasks",
        default="data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl",
    )
    parser.add_argument("--out-dir", default="data/eval/sub6/v4_a2_d5")
    parser.add_argument("--d4-out-dir", default="data/eval/sub6/v4_a2_d4")
    parser.add_argument(
        "--curated",
        default="data/benchmark/sub6/curated_hmdb_mammalian.jsonl",
    )
    parser.add_argument(
        "--ramp-db",
        default=os.environ.get(
            "METAGENT_RAMP_PATH",
            "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite",
        ),
    )
    parser.add_argument("--max-react-turns", type=int, default=5)
    parser.add_argument("--max-feedback-iters", type=int, default=2)
    parser.add_argument("--total-timeout", type=float, default=900.0)
    parser.add_argument(
        "--task-id", action="append",
        help="Override pilot selection (repeatable; useful for debugging)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOGLEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    all_tasks = {t["task_id"]: t for t in iter_jsonl(args.tasks)}

    if args.task_id:
        task_ids = list(args.task_id)
    else:
        task_ids = select_pilot_tasks(all_tasks)

    missing = [t for t in task_ids if t not in all_tasks]
    if missing:
        sys.stderr.write(f"ERROR: tasks not in {args.tasks}: {sorted(missing)}\n")
        return 2

    print(f"Pilot composition: {len(task_ids)} tasks")
    n_lm = sum(1 for t in task_ids if "lm_pathway" in t)
    n_d4 = sum(1 for t in task_ids if t in D4_NONLM_OVERLAP)
    print(f"  LM lipid:       {n_lm}")
    print(f"  D4 non-LM:      {n_d4}")
    print(f"  fresh non-LM:   {len(task_ids) - n_lm - n_d4}")

    _resolve_api_key("minimax", "MiniMax-M2.7")

    out_root = Path(args.out_dir)
    driver_lookup = _build_driver_lookup(Path(args.curated))

    summary_rows: list[dict] = []
    hash_pairs: list[dict] = []

    t_pilot = time.perf_counter()
    for idx, tid in enumerate(task_ids, 1):
        task = all_tasks[tid]
        print(f"\n=== [{idx}/{len(task_ids)}] {tid} ===")
        try:
            row = _process_one_task(
                task,
                out_root=out_root,
                ramp_db_path=args.ramp_db,
                driver_lookup=driver_lookup,
                max_react_turns=args.max_react_turns,
                max_feedback_iters=args.max_feedback_iters,
                total_timeout=args.total_timeout,
            )
            summary_rows.append(row["summary"])
            hash_pairs.append(row["hash_pair"])
        except Exception as exc:
            logger.exception("task %s crashed at top level", tid)
            summary_rows.append({"task_id": tid, "fatal": f"{type(exc).__name__}: {exc}"})
            hash_pairs.append({
                "task_id": tid, "react_sha256": None, "feedback_iter0_sha256": None,
                "match": False, "error": f"{type(exc).__name__}: {exc}",
            })

    pilot_elapsed = time.perf_counter() - t_pilot

    # Summary + hash check.
    _persist_json(out_root / "summary.json", summary_rows)
    n_match = sum(1 for p in hash_pairs if p["match"])
    _persist_json(
        out_root / "hash_check.json",
        {
            "all_match": n_match == len(hash_pairs),
            "n_match": n_match,
            "n_total": len(hash_pairs),
            "per_task": hash_pairs,
        },
    )

    # D4 sanity comparison (5 reused tasks × 3 variants = 15 verdict diffs).
    overlap = [t for t in task_ids if t in D4_NONLM_OVERLAP or t == "compound_only_enrich_mammalian_lm_pathway_WP167_seed4"]
    sanity = _sanity_compare(out_root, Path(args.d4_out_dir), overlap)
    _persist_json(out_root / "sanity_check.json", sanity)

    print()
    print(f"=== D5 PILOT SUMMARY ===")
    print(f"tasks processed     : {len(summary_rows)}")
    print(f"hash_check all_match: {n_match == len(hash_pairs)}  ({n_match}/{len(hash_pairs)})")
    print(f"sanity_check (D4↔D5):")
    print(f"  overlap variants  : {sanity['n_overlap_variants']}")
    print(f"  within ±1 noise   : {sanity['n_within_noise_pm1']}")
    print(f"  outliers (>1 diff): {sanity['n_outliers_gt1']}")
    print(f"  all_within_noise  : {sanity['all_within_noise']}")
    print(f"pilot wall          : {pilot_elapsed/60:.1f} min")
    print(f"summary             : {out_root / 'summary.json'}")
    print(f"sanity_check        : {out_root / 'sanity_check.json'}")
    return 0 if (n_match == len(hash_pairs) and sanity["all_within_noise"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
