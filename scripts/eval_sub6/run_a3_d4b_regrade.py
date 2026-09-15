"""A3 D4b — Re-grade existing D4 narratives with the post-fix verifier.

Pre-fix verifier (A2 era): ``verifier/layers/pathway_relationship.py``
queried ``pathwaySourceId`` / ``pathwaySource``, both nonexistent
columns. SQL raised, the outer try/except returned None, and every
KEGG-pathway-pair claim fell to ``UNVERIFIABLE_V0``.

Post-fix verifier (A3 D4a): correct column names ``sourceId`` /
``type``. Pathway resolution returns real ``hsa<NNNNN>`` ids and Layer
6d's BFS actually runs, producing SUPPORTED / CONTRADICTED for some
claims that previously fell through.

D4b decision rule (per spec § D4b):
  - |aggregate Δ| > 2 pt on any of supported / contradicted /
    unverifiable_v0 → A2 D5 numbers are based on a buggy verifier
    and must NOT be reused in A3 D2/D3. D2 re-runs feedback variant
    on the post-fix verifier.
  - |aggregate Δ| ≤ 2 pt → reuse D5 narratives in D2.

This script only RE-GRADES — it does not re-generate narratives. Same
narratives, new verifier output. The MiniMax non-determinism in Stage
1 claim extraction is still a drift source (re-grading the same
narrative twice can yield slightly different verdict counts because
extract_claims is LLM-bound), but spec D4b explicitly accepts this
noise and looks for >2 pt aggregate shift as the trigger.

Input:  data/eval/sub6/v4_a2_d4/{single,react,feedback}/{tid}/
        narrative.json (or result.json for feedback)
Output: data/eval/sub6/v4_a3_d4b_postfix/{variant}/{tid}/verdict.json
        + aggregate_delta.json + per_claim_type_delta.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation.sub6.io_utils import iter_jsonl
from evaluation.sub6.parallel_runner import (
    make_progress_logger,
    run_tasks_parallel,
)
from evaluation.sub6.run_sub6b import _resolve_api_key
from scripts.eval_sub6.grade_with_verifier import (
    _build_driver_lookup,
    _build_source_report,
)
from scripts.eval_sub6.run_a2_d4_3way import _persist_json
from verifier.agent import verify_sub6

logger = logging.getLogger(__name__)


def _load_narrative(variant_dir: Path, tid: str, variant: str) -> str:
    """Pull the *final* narrative for one (tid, variant)."""
    task_dir = variant_dir / variant / tid
    if variant in ("single", "react"):
        rec = json.loads((task_dir / "narrative.json").read_text())
        return rec.get("narrative", "")
    if variant == "feedback":
        rec = json.loads((task_dir / "result.json").read_text())
        return rec.get("final_narrative", "")
    raise ValueError(f"unknown variant {variant!r}")


def _verdict_summary(claims) -> dict[str, int]:
    return dict(Counter(c.verdict.value for c in claims))


def _verdict_by_claim_type(claims) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for c in claims:
        ct = c.claim_type.value
        out.setdefault(ct, Counter())[c.verdict.value] += 1
    return {ct: dict(d) for ct, d in out.items()}


def _grade_one(
    *,
    narrative: str,
    task: dict,
    ramp_db_path: str,
    driver_lookup: dict[str, str],
    track: str,
) -> dict:
    if not narrative.strip():
        return {"task_id": task["task_id"], "track": track,
                "verdicts_total": {}, "claims": [],
                "warning": "empty narrative — verifier skipped"}
    try:
        source_report = _build_source_report(task)
        v = verify_sub6(
            narrative, source_report,
            trace_id=f"{task['task_id']}.{track}",
            ramp_db_path=ramp_db_path,
            driver_lookup=driver_lookup,
        )
    except Exception as exc:
        logger.warning("verifier crashed on %s.%s: %s", task["task_id"], track, exc)
        return {"task_id": task["task_id"], "track": track,
                "verdicts_total": {}, "claims": [],
                "error": f"verifier_failed: {type(exc).__name__}: {exc}"}
    return {
        "task_id": task["task_id"],
        "track": track,
        "verdicts_total": _verdict_summary(v.claims_v2),
        "verdicts_by_type": _verdict_by_claim_type(v.claims_v2),
        "claims": [c.model_dump(mode="json") for c in v.claims_v2],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-dir", default="data/eval/sub6/v4_a2_d4")
    parser.add_argument("--out-dir", default="data/eval/sub6/v4_a3_d4b_postfix")
    parser.add_argument("--tasks", default="data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")
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
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOGLEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    in_root = Path(args.in_dir)
    out_root = Path(args.out_dir)
    all_tasks = {t["task_id"]: t for t in iter_jsonl(args.tasks)}
    driver_lookup = _build_driver_lookup(Path(args.curated))

    _resolve_api_key("minimax", "MiniMax-M2.7-highspeed")

    # Build the list of (tid, variant, narrative, task) to grade.
    work: list[dict] = []
    for variant in ("single", "react", "feedback"):
        variant_dir = in_root / variant
        if not variant_dir.is_dir():
            continue
        for task_subdir in sorted(variant_dir.iterdir()):
            if not task_subdir.is_dir():
                continue
            tid = task_subdir.name
            if tid not in all_tasks:
                logger.warning("task %s not in benchmark; skipping", tid)
                continue
            try:
                narrative = _load_narrative(in_root, tid, variant)
            except Exception as exc:
                logger.warning("failed to load narrative for %s/%s: %s", variant, tid, exc)
                continue
            work.append({
                "task_id": f"{variant}::{tid}",
                "narrative": narrative,
                "task": all_tasks[tid],
                "variant": variant,
                "tid": tid,
            })

    print(f"D4b regrade: {len(work)} (variant, task) pairs")

    def task_processor(item: dict) -> dict:
        variant = item["variant"]
        tid = item["tid"]
        v = _grade_one(
            narrative=item["narrative"],
            task=item["task"],
            ramp_db_path=args.ramp_db,
            driver_lookup=driver_lookup,
            track=f"a3_d4b_postfix_{variant}",
        )
        out_path = out_root / variant / tid / "verdict.json"
        _persist_json(out_path, v)
        return v

    progress_cb = make_progress_logger(total=len(work), prefix="regrade")
    outcomes = run_tasks_parallel(
        work, task_processor,
        max_workers=args.workers,
        on_progress=progress_cb,
    )

    # Compute delta vs pre-fix (in_root) verdicts.
    print()
    print("=== Aggregate verdict delta (pre-fix → post-fix) ===")
    delta_per_variant: dict[str, dict] = {}
    for variant in ("single", "react", "feedback"):
        pre_total: Counter = Counter()
        post_total: Counter = Counter()
        pre_by_type: dict[str, Counter] = {}
        post_by_type: dict[str, Counter] = {}
        n_tasks_compared = 0
        for item, outcome in zip(work, outcomes, strict=True):
            if item["variant"] != variant:
                continue
            pre_path = in_root / variant / item["tid"] / "verdict.json"
            if not pre_path.is_file():
                continue
            pre = json.loads(pre_path.read_text())
            post = outcome.result or {}
            if not pre.get("verdicts_total") or not post.get("verdicts_total"):
                continue
            n_tasks_compared += 1
            for k, v in (pre.get("verdicts_total") or {}).items():
                pre_total[k] += v
            for k, v in (post.get("verdicts_total") or {}).items():
                post_total[k] += v
            # Per-claim-type (only post has it via _grade_one; pre depends
            # on whether pre's claims list survived).
            for c in pre.get("claims") or []:
                ct = c.get("claim_type")
                vd = c.get("verdict")
                if ct and vd:
                    pre_by_type.setdefault(ct, Counter())[vd] += 1
            for ct, counts in (post.get("verdicts_by_type") or {}).items():
                d = post_by_type.setdefault(ct, Counter())
                for k, v in counts.items():
                    d[k] += v

        T_pre = sum(pre_total.values()); T_post = sum(post_total.values())
        if T_pre == 0 or T_post == 0:
            continue
        rows = []
        print()
        print(f'--- {variant} (n_tasks_compared={n_tasks_compared}) ---')
        print(f'  total claims: pre={T_pre} post={T_post}  Δ={T_post-T_pre:+d}')
        for k in ("supported", "unsupported", "contradicted", "unverifiable_v0"):
            p_pre = 100 * pre_total.get(k, 0) / T_pre
            p_post = 100 * post_total.get(k, 0) / T_post
            d = p_post - p_pre
            rows.append({"metric": k, "pre_pct": p_pre, "post_pct": p_post, "delta_pt": d})
            marker = "⚠️ >2pt" if abs(d) > 2 else ""
            print(f'  {k:<22} {p_pre:>6.2f}%  →  {p_post:>6.2f}%   Δ={d:+5.2f}pt   {marker}')
        # PATHWAY_RELATIONSHIP claim type specific
        pre_pr = pre_by_type.get("pathway_relationship", Counter())
        post_pr = post_by_type.get("pathway_relationship", Counter())
        print(f'  PATHWAY_RELATIONSHIP claims: pre={dict(pre_pr)}  post={dict(post_pr)}')
        delta_per_variant[variant] = {
            "n_tasks_compared": n_tasks_compared,
            "total_claims_pre": T_pre, "total_claims_post": T_post,
            "rows": rows,
            "pre_pathway_relationship": dict(pre_pr),
            "post_pathway_relationship": dict(post_pr),
        }

    _persist_json(out_root / "aggregate_delta.json", delta_per_variant)

    # Decision
    print()
    print("=== D4b decision ===")
    any_over = False
    for variant, d in delta_per_variant.items():
        max_abs = max(abs(r["delta_pt"]) for r in d["rows"])
        verdict = "REUSE_D5_OK" if max_abs <= 2 else "MUST_RERUN"
        any_over = any_over or (max_abs > 2)
        print(f'  {variant}: max |Δ| = {max_abs:.2f}pt → {verdict}')

    print()
    if any_over:
        print("DECISION: at least one variant > 2pt shift. A2 D5 numbers are")
        print("based on a buggy verifier; D2 must re-run feedback variant.")
    else:
        print("DECISION: all variants ≤ 2pt shift. A2 D5 narratives can be")
        print("reused in D2 (re-grade them with post-fix verifier).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
