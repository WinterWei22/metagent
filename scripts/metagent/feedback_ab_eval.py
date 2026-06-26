"""4-arm feedback A/B evaluation script (Task 6).

Runs four experimental arms on each trace from the v4_live_full run, using
iter-0 claims as the common starting point for A/B strategies:

  no-feedback  : iter-0 verdict — read directly from trace (0 LLM calls)
  baseline     : iterations[-1].verification — final live-run verdict (0 LLM calls)
  A cascade    : apply_feedback_strategy("cascade") on iter-0 verified claims →
                 verify_sub6(result.payload)  [1 LLM call for narrative weaving]
  B anchored   : apply_feedback_strategy("anchored") → 1 LLM chat call for
                 full rewrite → parse JSON → verify_sub6  [1 LLM call]

Arms A/B reconstruct iter-0 VerifiedClaims by feeding iter-0 react_result
through the v4 adapter (v4_task_to_subsix_source_report +
concord_result_to_b1_structured_payload + verify_sub6).

Usage::

    PYTHONPATH=. python3 scripts/metagent/feedback_ab_eval.py \\
        --limit 2 --out data/metagent/feedback_ab_smoke

Output::

    <out>/results.jsonl          — one line per (task_id, arm) with verdict counts
    <out>/<task_id>_<arm>.json  — full arm result per task (claims + narrative)
    <out>/summary.json           — aggregate counts across all tasks/arms
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import types
from collections import Counter
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Repo root / default paths
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parents[2]

_DEFAULT_TRACE_DIR = _REPO / "data" / "metagent" / "v4_live_full" / "path_x_full"
_DEFAULT_BENCH = (
    _REPO
    / "data"
    / "benchmark"
    / "metagent_bench_v2"
    / "metagent_bench_easy_v4.jsonl"
)
_DEFAULT_OUT = _REPO / "data" / "metagent" / "feedback_ab_smoke"

# Arm names in display order
_ARMS = ["no_feedback", "baseline", "A_cascade", "B_anchored"]


# ---------------------------------------------------------------------------
# Benchmark / trace loading helpers
# ---------------------------------------------------------------------------


def _load_benchmark(bench_path: Path) -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    with open(bench_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            tid = row.get("task_id")
            if tid:
                tasks[tid] = row
    return tasks


def _load_traces(trace_dir: Path, limit: int | None) -> list[dict]:
    files = sorted(trace_dir.glob("*.json"))
    if limit is not None:
        files = files[:limit]
    traces = []
    for fp in files:
        try:
            traces.append(json.loads(fp.read_text()))
        except Exception as exc:
            print(f"[WARN] Failed to load {fp.name}: {exc}", file=sys.stderr)
    return traces


# ---------------------------------------------------------------------------
# Helpers to reconstruct a react_result SimpleNamespace from a trace dict
# ---------------------------------------------------------------------------


def _react_result_ns(rr_dict: dict) -> Any:
    """Build a SimpleNamespace that mirrors ConcordReactResult attrs."""
    return types.SimpleNamespace(
        final_claims=rr_dict.get("final_claims") or [],
        enrichment_carriers=rr_dict.get("enrichment_carriers") or {},
        final_narrative_text=rr_dict.get("final_narrative_text") or "",
        task_outcome=rr_dict.get("task_outcome") or "normal",
    )


# ---------------------------------------------------------------------------
# Verdict counting helper
# ---------------------------------------------------------------------------


def _count_verdicts(claims_v2: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in (claims_v2 or []):
        vstr = str(getattr(v, "verdict", "UNKNOWN"))
        if "." in vstr:
            vstr = vstr.split(".")[-1]
        counts[vstr] = counts.get(vstr, 0) + 1
    return counts


def _narrative_from_result(result: Any) -> str:
    """Extract final narrative text from VerifiedIdentification."""
    return (
        getattr(result, "rewritten_output", None)
        or getattr(result, "source_llm_output", None)
        or ""
    )


# ---------------------------------------------------------------------------
# Arm runners
# ---------------------------------------------------------------------------


def _run_no_feedback(iter0_verification: dict) -> dict:
    """Read arm: iter-0 verification dict from trace (no LLM)."""
    counts = {
        "SUPPORTED": iter0_verification.get("n_supported", 0),
        "UNSUPPORTED": iter0_verification.get("n_unsupported", 0),
        "CONTRADICTED": iter0_verification.get("n_contradicted", 0),
        "UNVERIFIABLE_V0": iter0_verification.get("n_unverifiable_v0", 0),
        "INSUFFICIENT_EVIDENCE": iter0_verification.get("n_insufficient_evidence", 0),
    }
    # Filter zero counts
    counts = {k: v for k, v in counts.items() if v}
    return {
        "arm": "no_feedback",
        "verdict_counts": counts,
        "narrative": None,  # not stored in trace
        "claims": None,
        "error": None,
    }


def _run_baseline(iters: list) -> dict:
    """Read arm: iterations[-1].verification from trace (no LLM)."""
    last_iter = iters[-1] if iters else {}
    ver = last_iter.get("verification", {})
    counts = {
        "SUPPORTED": ver.get("n_supported", 0),
        "UNSUPPORTED": ver.get("n_unsupported", 0),
        "CONTRADICTED": ver.get("n_contradicted", 0),
        "UNVERIFIABLE_V0": ver.get("n_unverifiable_v0", 0),
        "INSUFFICIENT_EVIDENCE": ver.get("n_insufficient_evidence", 0),
    }
    counts = {k: v for k, v in counts.items() if v}
    return {
        "arm": "baseline",
        "verdict_counts": counts,
        "narrative": None,
        "claims": None,
        "error": None,
    }


def _run_cascade(
    task_id: str,
    task: dict,
    iter0_rr_dict: dict,
    verify_sub6_fn,
    v4_task_to_source_fn,
    concord_to_payload_fn,
    apply_feedback_strategy_fn,
) -> dict:
    """Arm A: cascade strategy.

    1. Reconstruct iter-0 VerifiedClaims via verify_sub6 on iter-0 react_result.
    2. apply_feedback_strategy("cascade") → FeedbackResult (kind="cascade", payload=JSON).
    3. verify_sub6(payload) → verdict distribution.
    """
    try:
        react_result = _react_result_ns(iter0_rr_dict)
        payload0 = concord_to_payload_fn(react_result, task)
        source_report = v4_task_to_source_fn(task, react_result)

        # Step 1: iter-0 verify → get verified_claims
        result0 = verify_sub6_fn(
            payload0,
            source_report,
            trace_id=f"ab_eval.{task_id}.iter0",
        )
        verified_claims0 = getattr(result0, "claims_v2", []) or []

        # Step 2: apply cascade strategy → FeedbackResult
        fb_result = apply_feedback_strategy_fn(
            "cascade",
            verified_claims0,
            source_report,
        )
        # fb_result.kind == "cascade", fb_result.payload is a JSON string
        cascade_payload = fb_result.payload

        # Step 3: verify_sub6 on cascade payload
        result_a = verify_sub6_fn(
            cascade_payload,
            source_report,
            trace_id=f"ab_eval.{task_id}.A_cascade",
        )
        claims_a = getattr(result_a, "claims_v2", []) or []
        counts = _count_verdicts(claims_a)
        narrative = _narrative_from_result(result_a)

        return {
            "arm": "A_cascade",
            "verdict_counts": counts,
            "narrative": narrative,
            "claims": [
                {
                    "claim_text": getattr(c, "claim_text", ""),
                    "verdict": str(getattr(c, "verdict", "")).split(".")[-1],
                    "grammar": str(getattr(c, "grammar", "")).split(".")[-1],
                }
                for c in claims_a
            ],
            "error": None,
        }
    except Exception:
        tb = traceback.format_exc()
        print(f"[ERROR] A_cascade {task_id}: {tb}", file=sys.stderr)
        return {
            "arm": "A_cascade",
            "verdict_counts": {},
            "narrative": None,
            "claims": None,
            "error": tb[-500:],
        }


def _run_anchored(
    task_id: str,
    task: dict,
    iter0_rr_dict: dict,
    verify_sub6_fn,
    v4_task_to_source_fn,
    concord_to_payload_fn,
    apply_feedback_strategy_fn,
    chat_fn,
) -> dict:
    """Arm B: anchored rewrite strategy.

    1. Reconstruct iter-0 VerifiedClaims via verify_sub6 on iter-0 react_result.
    2. apply_feedback_strategy("anchored") → FeedbackResult (kind="rewrite", payload=prompt).
    3. 1 LLM chat call with the anchored feedback prompt → rewritten narrative (JSON).
    4. verify_sub6(rewritten_narrative) → verdict distribution.
    """
    try:
        react_result = _react_result_ns(iter0_rr_dict)
        payload0 = concord_to_payload_fn(react_result, task)
        source_report = v4_task_to_source_fn(task, react_result)

        # Step 1: iter-0 verify → get verified_claims
        result0 = verify_sub6_fn(
            payload0,
            source_report,
            trace_id=f"ab_eval.{task_id}.iter0_b",
        )
        verified_claims0 = getattr(result0, "claims_v2", []) or []

        # Step 2: apply anchored strategy → FeedbackResult (prompt string)
        fb_result = apply_feedback_strategy_fn(
            "anchored",
            verified_claims0,
            source_report,
        )
        # fb_result.kind == "rewrite", fb_result.payload is the feedback prompt
        feedback_prompt = fb_result.payload or ""

        # Step 3: Build system message + user message for rewrite call.
        # We ask the LLM to produce a grammar-v2 JSON response: the same
        # format that the production react_runner produces (so verify_sub6
        # takes the zero-LLM extract_claims_from_json path).
        system_msg = (
            "You are a metabolomics pathway-analysis assistant. "
            "Output ONLY valid JSON matching the schema: "
            '{\"narrative_text\": \"<prose>\", \"claims\": [<claim_dicts>]}. '
            "Each claim dict must have: grammar (pathway_enrichment | "
            "pathway_membership | metabolite_pathway_link | driver_metabolite), "
            "claim_text (verbatim sentence). "
            "For pathway_enrichment add term_id, term_name, term_type='pathway'. "
            "For pathway_membership / metabolite_pathway_link / driver_metabolite "
            "add subject, pathway_name. "
            "Do NOT include any text outside the JSON object."
        )
        # Prepend the iter-0 narrative as context so the LLM knows what it wrote
        iter0_narrative = (react_result.final_narrative_text or "").strip()
        user_content = (
            f"Your previous narrative:\n\n{iter0_narrative}\n\n"
            f"Feedback:\n\n{feedback_prompt}\n\n"
            "Now output the revised narrative as JSON (narrative_text + claims)."
        )

        rewritten_raw = chat_fn(
            [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            max_tokens=2000,
            trace_id=f"ab_eval.{task_id}.B_anchored_rewrite",
            caller="feedback_ab_eval.B_anchored",
        )

        # Step 4: verify_sub6 on the rewritten payload
        result_b = verify_sub6_fn(
            rewritten_raw,
            source_report,
            trace_id=f"ab_eval.{task_id}.B_anchored_verify",
        )
        claims_b = getattr(result_b, "claims_v2", []) or []
        counts = _count_verdicts(claims_b)
        narrative = _narrative_from_result(result_b)

        return {
            "arm": "B_anchored",
            "verdict_counts": counts,
            "narrative": narrative,
            "rewrite_raw": rewritten_raw[:1000],  # truncate for storage
            "claims": [
                {
                    "claim_text": getattr(c, "claim_text", ""),
                    "verdict": str(getattr(c, "verdict", "")).split(".")[-1],
                    "grammar": str(getattr(c, "grammar", "")).split(".")[-1],
                }
                for c in claims_b
            ],
            "error": None,
        }
    except Exception:
        tb = traceback.format_exc()
        print(f"[ERROR] B_anchored {task_id}: {tb}", file=sys.stderr)
        return {
            "arm": "B_anchored",
            "verdict_counts": {},
            "narrative": None,
            "claims": None,
            "error": tb[-500:],
        }


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------


def run_eval(
    trace_dir: Path,
    bench_path: Path,
    out_dir: Path,
    limit: int | None,
) -> dict:
    """Run 4-arm evaluation over traces, write per-task JSON + results.jsonl."""
    import verifier.claim_table as _claim_table_mod
    from verifier.schemas import ClaimVerdict as _ClaimVerdict
    from verifier.agent import verify_sub6
    from concord.agent.verifier_adapter import (
        v4_task_to_subsix_source_report,
        concord_result_to_b1_structured_payload,
    )
    from concord.agent.feedback_strategies import apply_feedback_strategy
    from common.llm_client import chat

    # Patch claim_table severity map if needed (mirrors v4_verifier_replay.py)
    if _ClaimVerdict.INSUFFICIENT_EVIDENCE not in _claim_table_mod._SEVERITY_BY_VERDICT:
        _claim_table_mod._SEVERITY_BY_VERDICT[_ClaimVerdict.INSUFFICIENT_EVIDENCE] = "minor"

    # Set env flags to match production verify_with_b1 path
    os.environ["METAGENT_VERIFY_STRUCTURED_CLAIMS"] = "1"
    os.environ["METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT"] = "1"
    # Use MiniMax as LLM provider (do not default to openai)
    os.environ.setdefault("METAGENT_LLM_PROVIDER", "minimax")

    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    summary_path = out_dir / "summary.json"

    tasks = _load_benchmark(bench_path)
    traces = _load_traces(trace_dir, limit)
    print(f"Loaded {len(tasks)} benchmark tasks, {len(traces)} trace files.")

    # Aggregated verdict counts per arm
    agg: dict[str, Counter] = {arm: Counter() for arm in _ARMS}
    n_ok = 0
    n_fail = 0

    with open(results_path, "w") as results_fh:
        for trace in traces:
            task_id = trace.get("task_id", "")
            task = tasks.get(task_id)
            if task is None:
                print(f"[WARN] task_id '{task_id}' not in benchmark — skip", file=sys.stderr)
                n_fail += 1
                continue

            iters = trace.get("iterations", [])
            if not iters:
                print(f"[WARN] {task_id} has no iterations — skip", file=sys.stderr)
                n_fail += 1
                continue

            iter0 = iters[0]
            iter0_rr_dict = iter0.get("react_result", {})
            iter0_ver = iter0.get("verification", {})

            print(f"  Processing {task_id} ({len(iters)} iters)...", flush=True)

            # ----------------------------------------------------------
            # Arm: no_feedback (read from trace iter-0 verification)
            # ----------------------------------------------------------
            arm_no_fb = _run_no_feedback(iter0_ver)

            # ----------------------------------------------------------
            # Arm: baseline (read from trace last iter verification)
            # ----------------------------------------------------------
            arm_baseline = _run_baseline(iters)

            # ----------------------------------------------------------
            # Arm A: cascade (1 LLM call for narrative weave)
            # ----------------------------------------------------------
            arm_a = _run_cascade(
                task_id,
                task,
                iter0_rr_dict,
                verify_sub6,
                v4_task_to_subsix_source_report,
                concord_result_to_b1_structured_payload,
                apply_feedback_strategy,
            )

            # ----------------------------------------------------------
            # Arm B: anchored (1 LLM call for rewrite)
            # ----------------------------------------------------------
            arm_b = _run_anchored(
                task_id,
                task,
                iter0_rr_dict,
                verify_sub6,
                v4_task_to_subsix_source_report,
                concord_result_to_b1_structured_payload,
                apply_feedback_strategy,
                chat,
            )

            # ----------------------------------------------------------
            # Aggregate + write output
            # ----------------------------------------------------------
            task_result = {
                "task_id": task_id,
                "arms": {
                    "no_feedback": arm_no_fb,
                    "baseline": arm_baseline,
                    "A_cascade": arm_a,
                    "B_anchored": arm_b,
                },
            }

            # Per-task JSON
            task_out_path = out_dir / f"{task_id}.json"
            task_out_path.write_text(json.dumps(task_result, indent=2, ensure_ascii=False))

            # results.jsonl line (compact per-arm rows)
            for arm_name, arm_data in [
                ("no_feedback", arm_no_fb),
                ("baseline", arm_baseline),
                ("A_cascade", arm_a),
                ("B_anchored", arm_b),
            ]:
                row = {
                    "task_id": task_id,
                    "arm": arm_name,
                    "verdict_counts": arm_data["verdict_counts"],
                    "error": arm_data.get("error"),
                    "n_supported": arm_data["verdict_counts"].get("SUPPORTED", 0),
                    "n_unsupported": arm_data["verdict_counts"].get("UNSUPPORTED", 0),
                    "n_unverifiable_v0": arm_data["verdict_counts"].get("UNVERIFIABLE_V0", 0),
                    "n_insufficient_evidence": arm_data["verdict_counts"].get("INSUFFICIENT_EVIDENCE", 0),
                    "n_contradicted": arm_data["verdict_counts"].get("CONTRADICTED", 0),
                }
                results_fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                agg[arm_name].update(arm_data["verdict_counts"])

            n_ok += 1
            print(
                f"    no_feedback: {arm_no_fb['verdict_counts']} | "
                f"baseline: {arm_baseline['verdict_counts']} | "
                f"A: {arm_a['verdict_counts']} | "
                f"B: {arm_b['verdict_counts']}"
            )

    # Write summary
    summary = {
        "n_traces": len(traces),
        "n_ok": n_ok,
        "n_fail": n_fail,
        "aggregate_by_arm": {arm: dict(agg[arm]) for arm in _ARMS},
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print(f"\n=== Summary ===")
    print(f"Tasks processed OK : {n_ok}")
    print(f"Tasks failed       : {n_fail}")
    for arm in _ARMS:
        print(f"  {arm}: {dict(agg[arm])}")

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="4-arm feedback A/B evaluation")
    parser.add_argument(
        "--trace-dir",
        type=Path,
        default=_DEFAULT_TRACE_DIR,
        help="Directory of ConcordFeedbackResult trace JSON files",
    )
    parser.add_argument(
        "--bench",
        type=Path,
        default=_DEFAULT_BENCH,
        help="Benchmark JSONL (v4 rows with ground_truth.perturbed_pathway)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only N traces (use 2 for smoke test)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help="Output directory for results.jsonl and per-task JSON",
    )
    args = parser.parse_args()

    print(f"Trace dir : {args.trace_dir}")
    print(f"Benchmark : {args.bench}")
    print(f"Limit     : {args.limit or 'all'}")
    print(f"Output    : {args.out}")
    print()

    run_eval(
        trace_dir=args.trace_dir,
        bench_path=args.bench,
        out_dir=args.out,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
