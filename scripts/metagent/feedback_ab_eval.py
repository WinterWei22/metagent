"""5-arm feedback A/B evaluation script (Task 6 + Task 7).

Runs five experimental arms on each trace from the w14 run, using a shared
iter-0 live re-verify result as the common starting point for A/B strategies:

  no_feedback      : iter-0 verdict — read directly from trace (0 LLM calls)
  baseline         : iterations[-1].verification — final live-run verdict (0 LLM calls)
  iter0_reverify   : live re-verify of iter-0 payload with NO feedback (1 LLM call)
  A_cascade        : apply_feedback_strategy("cascade") on iter0_reverify claims →
                     verify_sub6(cascade_payload)  [1 LLM call for narrative weaving]
  B_anchored       : apply_feedback_strategy("anchored") → 1 LLM chat call for
                     full rewrite → parse JSON → verify_sub6  [1 LLM call]

Task 7 adds:
- iter0_reverify arm: fair common starting point (live re-verify, no feedback)
- Shared iter-0 re-verify: computed ONCE per task, reused by iter0_reverify + A + B
- pathway_accuracy: top-1 semantic match against GT perturbed_pathway.name
- claim_dist: verdict distribution per arm
- paired_delta: per arm Δ vs iter0_reverify (supported/unsupported/UV)

Usage::

    PYTHONPATH=. python3 scripts/metagent/feedback_ab_eval.py \\
        --traces-dir data/concord/w14_path_x_post_noise_cap/path_x_full \\
        --benchmark data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \\
        --output data/metagent/feedback_ab_eval/task7_smoke.json \\
        --limit 2

Output::

    <output>/ (directory)
        results.jsonl          — one line per (task_id, arm) with verdict counts + pathway
        <task_id>.json         — full arm result per task (claims + narrative + pathway)
        summary.json           — aggregate counts + paired delta across all tasks/arms
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

_DEFAULT_TRACE_DIR = _REPO / "data" / "concord" / "w14_path_x_post_noise_cap" / "path_x_full"
_DEFAULT_BENCH = (
    _REPO
    / "data"
    / "benchmark"
    / "sub6"
    / "sub6b_mammalian_tasks_v3.jsonl"
)
_DEFAULT_OUT = _REPO / "data" / "metagent" / "feedback_ab_eval"

# Arm names in display order (5 arms for Task 7)
_ARMS = ["no_feedback", "baseline", "iter0_reverify", "A_cascade", "B_anchored"]

# ---------------------------------------------------------------------------
# Default task selection (Task 7 — 23 tasks covering up/down/flat × strata)
#
# Selected from w14 traces with n_feedback_iterations > 0 (62/63 tasks).
# Bucketed by delta_supported (last_iter - first_iter):
#   down  (10): delta < 0  — 7 hmdb_ramp + 3 sub6b
#   up    (10): delta > 0  — 7 hmdb_ramp + 3 sub6b
#   flat   (3): delta == 0 — 3 hmdb_ramp  (only 4 flat tasks exist)
# Both strata (hmdb_ramp / sub6b) represented.
# ---------------------------------------------------------------------------
DEFAULT_EVAL_TASK_IDS: list[str] = [
    # --- down bucket (delta < 0) ---
    "compound_only_enrich_mammalian_RAMP_P_000000141_seed6",   # delta=-24 hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000000398_seed4",   # delta=-18 hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000000016_seed4",   # delta=-16 hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000000141_seed3",   # delta=-15 hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000000016_seed2",   # delta=-14 hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000000398_seed2",   # delta=-14 hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000000398_seed6",   # delta=-13 hmdb_ramp
    "compound_only_enrich_mammalian_lm_pathway_WP167_seed8",   # delta=-8  sub6b
    "compound_only_enrich_mammalian_lm_pathway_WP167_seed2",   # delta=-6  sub6b
    "compound_only_enrich_mammalian_lm_pathway_WP167_seed1",   # delta=-3  sub6b
    # --- up bucket (delta > 0) ---
    "compound_only_enrich_mammalian_RAMP_P_000000141_seed5",   # delta=+19 hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000053306_seed1",   # delta=+12 hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000000016_seed7",   # delta=+11 hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000000421_seed5",   # delta=+7  hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000000141_seed8",   # delta=+6  hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000052855_seed0",   # delta=+5  hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000000016_seed1",   # delta=+5  hmdb_ramp
    "compound_only_enrich_mammalian_lm_pathway_WP167_seed7",   # delta=+12 sub6b
    "compound_only_enrich_mammalian_lm_pathway_WP167_seed5",   # delta=+8  sub6b
    "compound_only_enrich_mammalian_lm_pathway_WP167_seed3",   # delta=+4  sub6b
    # --- flat bucket (delta == 0) ---
    "compound_only_enrich_mammalian_RAMP_P_000050021_seed2",   # delta=0   hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000000398_seed8",   # delta=0   hmdb_ramp
    "compound_only_enrich_mammalian_RAMP_P_000000421_seed3",   # delta=0   hmdb_ramp
]


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


def _load_traces(trace_dir: Path, limit: int | None, task_ids: list[str] | None = None) -> list[dict]:
    """Load trace files; if task_ids given, only load matching files."""
    if task_ids is not None:
        files = sorted(
            fp for tid in task_ids
            for fp in [trace_dir / f"{tid}.json"] if fp.exists()
        )
    else:
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
# Ground-truth pathway extraction (supports sub6b-v3 format)
# ---------------------------------------------------------------------------


def _get_gt_pathway(task: dict) -> tuple[str, str]:
    """Return (pathway_id, pathway_name) from a task row.

    Supports both sub6b-v3 format (top-level ground_truth_pathway) and
    v4 format (ground_truth.perturbed_pathway).
    """
    # sub6b-v3 format
    gtp = task.get("ground_truth_pathway")
    if isinstance(gtp, dict) and gtp.get("pathway_name"):
        return str(gtp.get("pathway_id") or ""), str(gtp.get("pathway_name") or "")
    # v4 format
    gt = task.get("ground_truth", {})
    pp = gt.get("perturbed_pathway", {})
    if isinstance(pp, dict) and pp.get("name"):
        return str(pp.get("id") or ""), str(pp.get("name") or "")
    return "", ""


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


def _claims_to_list(claims_v2: list) -> list[dict]:
    return [
        {
            "claim_text": getattr(c, "claim_text", ""),
            "verdict": str(getattr(c, "verdict", "")).split(".")[-1],
            "grammar": str(getattr(c, "grammar", "")).split(".")[-1],
        }
        for c in (claims_v2 or [])
    ]


# ---------------------------------------------------------------------------
# Pathway accuracy evaluation
# ---------------------------------------------------------------------------


def _extract_pathway_name_from_claim(c) -> str:
    """Extract pathway name from a claim object (dict or VerifiedClaim)."""
    if isinstance(c, dict):
        return c.get("pathway_name") or c.get("term_name") or ""
    # VerifiedClaim: check extracted_fields.pathway_name first
    ef = getattr(c, "extracted_fields", None)
    ef_pname = getattr(ef, "pathway_name", None) if ef is not None else None
    return (
        ef_pname
        or getattr(c, "pathway_name", None)
        or getattr(c, "term_name", None)
        or ""
    )


def _is_preferred_verdict(c) -> bool:
    """True iff claim has a verdict that is reliable for primary_name selection.

    SUPPORTED and INSUFFICIENT_EVIDENCE are the only verdicts whose pathway
    names are trustworthy: CONTRADICTED claims carry the verifier correction
    in pathway_name (not the actual pathway), UNSUPPORTED claims reference
    pathways the verifier could not confirm, and UV/ERROR are out-of-scope.
    """
    from verifier.schemas import ClaimVerdict
    verdict = getattr(c, "verdict", None)
    if verdict is None:
        # dict claims (from _claims_to_list) store verdict as string
        if isinstance(c, dict):
            verdict_str = c.get("verdict", "")
            # Normalise "ClaimVerdict.SUPPORTED" -> "SUPPORTED" -> "supported"
            if "." in verdict_str:
                verdict_str = verdict_str.split(".")[-1]
            verdict_str = verdict_str.lower()
            return verdict_str in ("supported", "insufficient_evidence")
        return False
    # Enum or string
    verdict_val = verdict.value if hasattr(verdict, "value") else str(verdict).lower()
    if "." in verdict_val:
        verdict_val = verdict_val.split(".")[-1].lower()
    return verdict_val in ("supported", "insufficient_evidence")


def _eval_pathway_accuracy(
    narrative: str | None,
    claims: list | None,
    gt_pathway_name: str,
    pathway_semantic_match_fn,
) -> dict[str, Any]:
    """Compute pathway accuracy for one arm.

    Extracts pathway names from claims (term_name / pathway_name fields),
    then uses the canonical pathway_semantic_match function.

    primary_name is taken from the FIRST SUPPORTED or INSUFFICIENT_EVIDENCE
    claim that has a non-empty pathway name. This prevents CONTRADICTED claims
    (whose pathway_name field may contain the verifier correction text, not a
    real pathway name) from biasing the top-1 accuracy metric. Falls back to
    scanning all claims only when no preferred-verdict claim has a pathway name.

    topk scans ALL claims regardless of verdict so that any pathway named in
    the result (even a corrected or unsupported one) contributes to topk recall.

    Returns dict with keys: primary_name, top1_hit, topk_hit, abstain.
    """
    if not gt_pathway_name:
        return {"primary_name": None, "top1_hit": None, "topk_hit": None, "abstain": False}

    claims_list = list(claims or [])

    # Collect ALL predicted pathway names (for topk).
    all_predicted_names: list[str] = []
    for c in claims_list:
        pname = _extract_pathway_name_from_claim(c)
        if pname:
            all_predicted_names.append(str(pname))

    if not all_predicted_names:
        return {"primary_name": None, "top1_hit": False, "topk_hit": False, "abstain": True}

    # Collect preferred-verdict names (for primary_name / top1).
    preferred_names: list[str] = [
        str(_extract_pathway_name_from_claim(c))
        for c in claims_list
        if _is_preferred_verdict(c) and _extract_pathway_name_from_claim(c)
    ]

    # Use preferred names for primary if available; otherwise fall back to all.
    primary_pool = preferred_names if preferred_names else all_predicted_names

    primary_name = primary_pool[0]
    top1_hit = pathway_semantic_match_fn(gt_pathway_name, primary_name)
    topk_hit = any(pathway_semantic_match_fn(gt_pathway_name, p) for p in all_predicted_names)

    return {
        "primary_name": primary_name,
        "top1_hit": top1_hit,
        "topk_hit": topk_hit,
        "abstain": False,
    }


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
    counts = {k: v for k, v in counts.items() if v}
    return {
        "arm": "no_feedback",
        "verdict_counts": counts,
        "narrative": None,
        "claims": None,
        "pathway_accuracy": None,  # no live claims available
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
        "pathway_accuracy": None,  # no live claims available
        "error": None,
    }


def _run_iter0_reverify(
    task_id: str,
    task: dict,
    iter0_rr_dict: dict,
    verify_sub6_fn,
    sub6b_task_to_source_fn,
    concord_to_payload_fn,
    pathway_semantic_match_fn,
    gt_pathway_name: str,
) -> tuple[dict, Any, list]:
    """Arm iter0_reverify: live re-verify of iter-0 payload with NO feedback.

    Returns (arm_result_dict, result0_object, verified_claims0) so that
    A/B arms can reuse result0 and verified_claims0 without an extra LLM call.
    This shared computation cuts ~30% LLM cost vs recomputing in each arm.
    """
    try:
        react_result = _react_result_ns(iter0_rr_dict)
        payload0 = concord_to_payload_fn(react_result, task)
        source_report = sub6b_task_to_source_fn(task)

        result0 = verify_sub6_fn(
            payload0,
            source_report,
            trace_id=f"ab_eval.{task_id}.iter0_reverify",
        )
        verified_claims0 = getattr(result0, "claims_v2", []) or []
        counts = _count_verdicts(verified_claims0)
        narrative = _narrative_from_result(result0)
        claims_list = _claims_to_list(verified_claims0)
        pathway_acc = _eval_pathway_accuracy(
            narrative, verified_claims0, gt_pathway_name, pathway_semantic_match_fn
        )

        arm = {
            "arm": "iter0_reverify",
            "verdict_counts": counts,
            "narrative": narrative,
            "claims": claims_list,
            "pathway_accuracy": pathway_acc,
            "error": None,
        }
        return arm, result0, verified_claims0
    except Exception:
        tb = traceback.format_exc()
        print(f"[ERROR] iter0_reverify {task_id}: {tb}", file=sys.stderr)
        arm = {
            "arm": "iter0_reverify",
            "verdict_counts": {},
            "narrative": None,
            "claims": None,
            "pathway_accuracy": None,
            "error": tb[-500:],
        }
        return arm, None, []


def _run_cascade(
    task_id: str,
    task: dict,
    iter0_rr_dict: dict,
    result0: Any,
    verified_claims0: list,
    verify_sub6_fn,
    sub6b_task_to_source_fn,
    concord_to_payload_fn,
    apply_feedback_strategy_fn,
    pathway_semantic_match_fn,
    gt_pathway_name: str,
) -> dict:
    """Arm A: cascade strategy.

    Reuses result0 + verified_claims0 from iter0_reverify (shared computation).
    apply_feedback_strategy("cascade") → FeedbackResult → verify_sub6.
    """
    try:
        source_report = sub6b_task_to_source_fn(task)

        # Fall back to recomputing if iter0_reverify failed
        if result0 is None or not verified_claims0:
            react_result = _react_result_ns(iter0_rr_dict)
            payload0 = concord_to_payload_fn(react_result, task)
            result0_local = verify_sub6_fn(
                payload0,
                source_report,
                trace_id=f"ab_eval.{task_id}.iter0_for_cascade",
            )
            verified_claims0_local = getattr(result0_local, "claims_v2", []) or []
        else:
            verified_claims0_local = verified_claims0

        # Apply cascade strategy → FeedbackResult
        fb_result = apply_feedback_strategy_fn(
            "cascade",
            verified_claims0_local,
            source_report,
        )
        cascade_payload = fb_result.payload

        # Verify cascade payload
        result_a = verify_sub6_fn(
            cascade_payload,
            source_report,
            trace_id=f"ab_eval.{task_id}.A_cascade",
        )
        claims_a = getattr(result_a, "claims_v2", []) or []
        counts = _count_verdicts(claims_a)
        narrative = _narrative_from_result(result_a)
        claims_list = _claims_to_list(claims_a)
        pathway_acc = _eval_pathway_accuracy(
            narrative, claims_a, gt_pathway_name, pathway_semantic_match_fn
        )

        return {
            "arm": "A_cascade",
            "verdict_counts": counts,
            "narrative": narrative,
            "claims": claims_list,
            "pathway_accuracy": pathway_acc,
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
            "pathway_accuracy": None,
            "error": tb[-500:],
        }


def _run_anchored(
    task_id: str,
    task: dict,
    iter0_rr_dict: dict,
    result0: Any,
    verified_claims0: list,
    verify_sub6_fn,
    sub6b_task_to_source_fn,
    concord_to_payload_fn,
    apply_feedback_strategy_fn,
    chat_fn,
    pathway_semantic_match_fn,
    gt_pathway_name: str,
) -> dict:
    """Arm B: anchored rewrite strategy.

    Reuses result0 + verified_claims0 from iter0_reverify (shared computation).
    apply_feedback_strategy("anchored") → feedback prompt → LLM rewrite → verify_sub6.
    """
    try:
        source_report = sub6b_task_to_source_fn(task)
        react_result = _react_result_ns(iter0_rr_dict)

        # Fall back to recomputing if iter0_reverify failed
        if result0 is None or not verified_claims0:
            payload0 = concord_to_payload_fn(react_result, task)
            result0_local = verify_sub6_fn(
                payload0,
                source_report,
                trace_id=f"ab_eval.{task_id}.iter0_for_anchored",
            )
            verified_claims0_local = getattr(result0_local, "claims_v2", []) or []
        else:
            verified_claims0_local = verified_claims0

        # Apply anchored strategy → FeedbackResult (prompt string)
        fb_result = apply_feedback_strategy_fn(
            "anchored",
            verified_claims0_local,
            source_report,
        )
        feedback_prompt = fb_result.payload or ""

        # Build system + user messages for rewrite call
        system_msg = (
            "You are a metabolomics pathway-analysis assistant. "
            "Output ONLY valid JSON matching the schema: "
            '{"narrative_text": "<prose>", "claims": [<claim_dicts>]}. '
            "Each claim dict must have: grammar (pathway_enrichment | "
            "pathway_membership | metabolite_pathway_link | driver_metabolite), "
            "claim_text (verbatim sentence). "
            "For pathway_enrichment add term_id, term_name, term_type='pathway'. "
            "For pathway_membership / metabolite_pathway_link / driver_metabolite "
            "add subject, pathway_name. "
            "Do NOT include any text outside the JSON object."
        )
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

        # Verify the rewritten payload
        result_b = verify_sub6_fn(
            rewritten_raw,
            source_report,
            trace_id=f"ab_eval.{task_id}.B_anchored_verify",
        )
        claims_b = getattr(result_b, "claims_v2", []) or []
        counts = _count_verdicts(claims_b)
        narrative = _narrative_from_result(result_b)
        claims_list = _claims_to_list(claims_b)
        pathway_acc = _eval_pathway_accuracy(
            narrative, claims_b, gt_pathway_name, pathway_semantic_match_fn
        )

        return {
            "arm": "B_anchored",
            "verdict_counts": counts,
            "narrative": narrative,
            "rewrite_raw": rewritten_raw[:1000],
            "claims": claims_list,
            "pathway_accuracy": pathway_acc,
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
            "pathway_accuracy": None,
            "error": tb[-500:],
        }


# ---------------------------------------------------------------------------
# Paired delta computation
# ---------------------------------------------------------------------------


def _compute_paired_delta(arm_data: dict, ref_data: dict, label: str) -> dict[str, Any]:
    """Compute delta for arm vs reference (iter0_reverify) arm."""
    ref_counts = ref_data.get("verdict_counts", {})
    arm_counts = arm_data.get("verdict_counts", {})

    def _get(d: dict, k: str) -> int:
        return d.get(k, 0)

    ref_sup = _get(ref_counts, "SUPPORTED")
    ref_uv = _get(ref_counts, "UNVERIFIABLE_V0") + _get(ref_counts, "INSUFFICIENT_EVIDENCE")
    ref_unsup = _get(ref_counts, "UNSUPPORTED")

    arm_sup = _get(arm_counts, "SUPPORTED")
    arm_uv = _get(arm_counts, "UNVERIFIABLE_V0") + _get(arm_counts, "INSUFFICIENT_EVIDENCE")
    arm_unsup = _get(arm_counts, "UNSUPPORTED")

    # Pathway accuracy delta
    ref_top1 = (ref_data.get("pathway_accuracy") or {}).get("top1_hit")
    arm_top1 = (arm_data.get("pathway_accuracy") or {}).get("top1_hit")
    top1_delta: int | None = None
    if ref_top1 is not None and arm_top1 is not None:
        top1_delta = (1 if arm_top1 else 0) - (1 if ref_top1 else 0)

    return {
        "arm": label,
        "delta_supported": arm_sup - ref_sup,
        "delta_uv": arm_uv - ref_uv,
        "delta_unsupported": arm_unsup - ref_unsup,
        "delta_pathway_top1": top1_delta,
    }


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------


def run_eval(
    trace_dir: Path,
    bench_path: Path,
    out_dir: Path,
    limit: int | None,
    task_ids: list[str] | None = None,
) -> dict:
    """Run 5-arm evaluation over traces, write per-task JSON + results.jsonl."""
    import verifier.claim_table as _claim_table_mod
    from verifier.schemas import ClaimVerdict as _ClaimVerdict
    from verifier.agent import verify_sub6
    from concord.agent.verifier_adapter import (
        sub6b_task_to_subsix_source_report,
        concord_result_to_b1_structured_payload,
    )
    from concord.agent.feedback_strategies import apply_feedback_strategy
    from concord.agent.pathway_prediction import pathway_semantic_match
    from common.llm_client import chat

    # Patch claim_table severity map if needed (mirrors v4_verifier_replay.py)
    if _ClaimVerdict.INSUFFICIENT_EVIDENCE not in _claim_table_mod._SEVERITY_BY_VERDICT:
        _claim_table_mod._SEVERITY_BY_VERDICT[_ClaimVerdict.INSUFFICIENT_EVIDENCE] = "minor"

    # Set env flags to match production verify_with_b1 path
    os.environ["METAGENT_VERIFY_STRUCTURED_CLAIMS"] = "1"
    os.environ["METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT"] = "1"
    os.environ.setdefault("METAGENT_LLM_PROVIDER", "minimax")

    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    summary_path = out_dir / "summary.json"

    tasks = _load_benchmark(bench_path)
    traces = _load_traces(trace_dir, limit, task_ids=task_ids)
    print(f"Loaded {len(tasks)} benchmark tasks, {len(traces)} trace files.")

    # Aggregated verdict counts per arm
    agg: dict[str, Counter] = {arm: Counter() for arm in _ARMS}
    # Pathway accuracy counts per arm
    pathway_hits: dict[str, dict[str, int]] = {
        arm: {"top1_hit": 0, "topk_hit": 0, "total": 0, "abstain": 0}
        for arm in _ARMS
    }
    # Paired delta accumulators vs iter0_reverify
    paired_deltas: dict[str, list[dict]] = {arm: [] for arm in _ARMS}
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

            gt_pathway_id, gt_pathway_name = _get_gt_pathway(task)
            print(f"  Processing {task_id} (GT: {gt_pathway_name[:50]})...", flush=True)

            # ----------------------------------------------------------
            # Arm: no_feedback (read from trace iter-0 verification)
            # ----------------------------------------------------------
            arm_no_fb = _run_no_feedback(iter0_ver)

            # ----------------------------------------------------------
            # Arm: baseline (read from trace last iter verification)
            # ----------------------------------------------------------
            arm_baseline = _run_baseline(iters)

            # ----------------------------------------------------------
            # Arm: iter0_reverify — live re-verify, SHARED with A and B.
            # Computed ONCE per task; result0 + verified_claims0 are
            # passed to _run_cascade and _run_anchored to avoid redundant
            # LLM calls (saves ~2 verify calls per task ≈ 30% cost cut).
            # ----------------------------------------------------------
            arm_iter0_rv, result0, verified_claims0 = _run_iter0_reverify(
                task_id,
                task,
                iter0_rr_dict,
                verify_sub6,
                sub6b_task_to_subsix_source_report,
                concord_result_to_b1_structured_payload,
                pathway_semantic_match,
                gt_pathway_name,
            )

            # ----------------------------------------------------------
            # Arm A: cascade (reuses result0 + verified_claims0)
            # ----------------------------------------------------------
            arm_a = _run_cascade(
                task_id,
                task,
                iter0_rr_dict,
                result0,
                verified_claims0,
                verify_sub6,
                sub6b_task_to_subsix_source_report,
                concord_result_to_b1_structured_payload,
                apply_feedback_strategy,
                pathway_semantic_match,
                gt_pathway_name,
            )

            # ----------------------------------------------------------
            # Arm B: anchored (reuses result0 + verified_claims0)
            # ----------------------------------------------------------
            arm_b = _run_anchored(
                task_id,
                task,
                iter0_rr_dict,
                result0,
                verified_claims0,
                verify_sub6,
                sub6b_task_to_subsix_source_report,
                concord_result_to_b1_structured_payload,
                apply_feedback_strategy,
                chat,
                pathway_semantic_match,
                gt_pathway_name,
            )

            # ----------------------------------------------------------
            # Aggregate + paired delta
            # ----------------------------------------------------------
            arm_map = {
                "no_feedback": arm_no_fb,
                "baseline": arm_baseline,
                "iter0_reverify": arm_iter0_rv,
                "A_cascade": arm_a,
                "B_anchored": arm_b,
            }

            for arm_name in _ARMS:
                arm_data = arm_map[arm_name]
                agg[arm_name].update(arm_data["verdict_counts"])
                # Pathway accuracy
                pa = arm_data.get("pathway_accuracy")
                if pa is not None:
                    pathway_hits[arm_name]["total"] += 1
                    if pa.get("abstain"):
                        pathway_hits[arm_name]["abstain"] += 1
                    if pa.get("top1_hit"):
                        pathway_hits[arm_name]["top1_hit"] += 1
                    if pa.get("topk_hit"):
                        pathway_hits[arm_name]["topk_hit"] += 1
                # Paired delta vs iter0_reverify
                delta = _compute_paired_delta(arm_data, arm_iter0_rv, arm_name)
                paired_deltas[arm_name].append(delta)

            # Per-task JSON
            task_result = {
                "task_id": task_id,
                "gt_pathway_name": gt_pathway_name,
                "arms": {arm_name: arm_map[arm_name] for arm_name in _ARMS},
                "paired_deltas_vs_iter0_reverify": {
                    arm_name: paired_deltas[arm_name][-1]
                    for arm_name in _ARMS
                },
            }
            task_out_path = out_dir / f"{task_id}.json"
            task_out_path.write_text(json.dumps(task_result, indent=2, ensure_ascii=False))

            # results.jsonl line (compact per-arm rows)
            for arm_name in _ARMS:
                arm_data = arm_map[arm_name]
                pa = arm_data.get("pathway_accuracy") or {}
                row = {
                    "task_id": task_id,
                    "arm": arm_name,
                    "verdict_counts": arm_data["verdict_counts"],
                    "error": arm_data.get("error"),
                    "n_supported": arm_data["verdict_counts"].get("SUPPORTED", 0),
                    "n_unsupported": arm_data["verdict_counts"].get("UNSUPPORTED", 0),
                    "n_unverifiable_v0": arm_data["verdict_counts"].get("UNVERIFIABLE_V0", 0),
                    "n_insufficient_evidence": arm_data["verdict_counts"].get(
                        "INSUFFICIENT_EVIDENCE", 0
                    ),
                    "n_contradicted": arm_data["verdict_counts"].get("CONTRADICTED", 0),
                    "pathway_top1_hit": pa.get("top1_hit"),
                    "pathway_topk_hit": pa.get("topk_hit"),
                    "pathway_abstain": pa.get("abstain"),
                    "pathway_primary_name": pa.get("primary_name"),
                }
                results_fh.write(json.dumps(row, ensure_ascii=False) + "\n")

            n_ok += 1
            print(
                f"    no_fb:{arm_no_fb['verdict_counts']} | "
                f"base:{arm_baseline['verdict_counts']} | "
                f"rv0:{arm_iter0_rv['verdict_counts']} | "
                f"A:{arm_a['verdict_counts']} | "
                f"B:{arm_b['verdict_counts']}"
            )

    # ---------------------------------------------------------------------------
    # Compute aggregate summary with pathway accuracy rates and paired deltas
    # ---------------------------------------------------------------------------

    def _avg_delta(arm_name: str, key: str) -> float | None:
        vals = [d[key] for d in paired_deltas[arm_name] if d.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    pathway_accuracy_summary: dict[str, Any] = {}
    for arm_name in _ARMS:
        ph = pathway_hits[arm_name]
        total = ph["total"]
        pathway_accuracy_summary[arm_name] = {
            "total_with_eval": total,
            "top1_hit": ph["top1_hit"],
            "topk_hit": ph["topk_hit"],
            "abstain": ph["abstain"],
            "top1_hit_rate": round(ph["top1_hit"] / total, 4) if total else None,
            "topk_hit_rate": round(ph["topk_hit"] / total, 4) if total else None,
        }

    paired_delta_summary: dict[str, Any] = {}
    for arm_name in _ARMS:
        paired_delta_summary[arm_name] = {
            "avg_delta_supported": _avg_delta(arm_name, "delta_supported"),
            "avg_delta_uv": _avg_delta(arm_name, "delta_uv"),
            "avg_delta_unsupported": _avg_delta(arm_name, "delta_unsupported"),
            "avg_delta_pathway_top1": _avg_delta(arm_name, "delta_pathway_top1"),
        }

    summary = {
        "n_traces": len(traces),
        "n_ok": n_ok,
        "n_fail": n_fail,
        "arms": _ARMS,
        "aggregate_by_arm": {arm: dict(agg[arm]) for arm in _ARMS},
        "pathway_accuracy_by_arm": pathway_accuracy_summary,
        "paired_delta_vs_iter0_reverify": paired_delta_summary,
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print(f"\n=== Summary ===")
    print(f"Tasks processed OK : {n_ok}")
    print(f"Tasks failed       : {n_fail}")
    print(f"\nVerdict aggregate by arm:")
    for arm in _ARMS:
        print(f"  {arm}: {dict(agg[arm])}")
    print(f"\nPathway accuracy (top1 hit rate):")
    for arm in _ARMS:
        pa = pathway_accuracy_summary[arm]
        print(
            f"  {arm}: {pa['top1_hit_rate']} "
            f"({pa['top1_hit']}/{pa['total_with_eval']})"
        )
    print(f"\nPaired delta vs iter0_reverify (avg):")
    for arm in _ARMS:
        d = paired_delta_summary[arm]
        print(
            f"  {arm}: Δsup={d['avg_delta_supported']}  "
            f"Δuv={d['avg_delta_uv']}  "
            f"Δpathway_top1={d['avg_delta_pathway_top1']}"
        )

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="5-arm feedback A/B evaluation (Task 7)")
    parser.add_argument(
        "--traces-dir",
        "--trace-dir",
        dest="traces_dir",
        type=Path,
        default=_DEFAULT_TRACE_DIR,
        help="Directory of ConcordFeedbackResult trace JSON files",
    )
    parser.add_argument(
        "--benchmark",
        "--bench",
        dest="benchmark",
        type=Path,
        default=_DEFAULT_BENCH,
        help="Benchmark JSONL (sub6b-v3 rows with ground_truth_pathway)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only N traces (use 2 for smoke test)",
    )
    parser.add_argument(
        "--output",
        "--out",
        dest="output",
        type=Path,
        default=_DEFAULT_OUT,
        help="Output directory (or .json path; parent dir used if .json suffix)",
    )
    parser.add_argument(
        "--all-tasks",
        action="store_true",
        default=False,
        help="Run all traces in traces-dir, not just DEFAULT_EVAL_TASK_IDS",
    )
    args = parser.parse_args()

    # If --output is a .json path, use its parent directory
    out_dir = args.output
    if str(out_dir).endswith(".json"):
        out_dir = out_dir.parent

    task_ids = None if args.all_tasks else DEFAULT_EVAL_TASK_IDS
    # skip-if-done: drop tasks whose per-task output JSON already exists, so an
    # interrupted run resumes without re-spending LLM cost on completed tasks.
    if task_ids is not None:
        before = len(task_ids)
        task_ids = [t for t in task_ids if not (out_dir / f"{t}.json").exists()]
        print(f"skip-done  : {before - len(task_ids)} already done, {len(task_ids)} remaining")

    print(f"Trace dir  : {args.traces_dir}")
    print(f"Benchmark  : {args.benchmark}")
    print(f"Limit      : {args.limit or 'all'}")
    print(f"Output dir : {out_dir}")
    print(f"Task IDs   : {'all' if task_ids is None else f'{len(task_ids)} selected'}")
    print()

    run_eval(
        trace_dir=args.traces_dir,
        bench_path=args.benchmark,
        out_dir=out_dir,
        limit=args.limit,
        task_ids=task_ids,
    )


if __name__ == "__main__":
    main()
