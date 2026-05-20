"""Sub-6B ReAct + verifier-feedback runner (phase A2 D3, track AGENT).

Closed-loop variant of A1's `run_sub6b_react`:

    iteration 0:  initial ReAct loop → narrative N0
                  → verifier(N0) → verdict V0 (claims annotated by D1)
    iteration 1:  feedback message built from V0's contradicted/unsupported
                  claims (with hints) → continue conversation → narrative N1
                  → verifier(N1) → V1
    iteration 2:  same as 1 against V1 → N2 → V2

After all iterations, the *final* narrative is selected by quality:
    quality(N) = #contradicted + #unsupported + #unverifiable_v0  (lower is better)
    (P0 fix 2026-05-18: UNV added — D4 removed UV from neutral verdicts
    but the quality function never followed suit, so rollback comparisons
    silently treated UV-only iterations as quality=0.)
The *earliest* iteration with the minimum quality wins (Q6: tie ↔ earliest):

    if  q(N2) >  q(N0):  rollback to N0, error="feedback_made_it_worse"
    elif q(N2) >  q(N1):  rollback to N1, error="iter2_degraded"
    else:                 keep N2

(Note on the inequality direction: spec body wrote ``q(N2) < q(N0)`` but
both error labels read "made it worse" / "degraded"; combined with Q6's
``quality = contra + unsup``, lower-is-better, the semantic intent is
``>``. Documented here so the convention is unambiguous.)

A1 file constraints (spec D3): we do NOT modify A1's
``run_sub6b_react.py``. Instead, the iteration-0 ReAct loop is
re-implemented here so it can persist turn-by-turn and continue cleanly
into a feedback iteration without round-tripping the message history.

Verifier integration is via dependency injection: the caller supplies
``verifier_fn(narrative) -> VerdictReport``. This keeps source-report
construction (per-task RaMP / curated-pool plumbing) out of the runner.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, NamedTuple

from common import llm_client
from evaluation.sub6.persist import TaskPersister
from evaluation.sub6.prompts_agent import build_react_messages
from evaluation.sub6.run_sub6b_react import _is_valid_json_payload
from tools.agent_tools import TOOL_DEFINITIONS_OPENAI, dispatch, reset_call_cache
from verifier.schemas import ClaimVerdict, VerifiedClaim

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class VerdictReport(NamedTuple):
    """Slim verifier output the feedback runner consumes.

    ``claims`` must already be annotated by ``verifier.feedback_hints``
    (i.e. ``claim_id`` and ``feedback_hint`` populated). The runner
    pulls only ``CONTRADICTED`` and ``UNSUPPORTED`` claims for the
    feedback message; other verdicts inform the quality score only.

    Phase B1 D4: ``dropped_claims`` and ``task_outcome`` are plumbed
    through so the feedback prompt can name dropped claims back to the
    LLM and so the runner can decide between Mode B refusal-retry and
    normal feedback. Defaults keep pre-D4 callers (and unit-test
    fixtures) working with the old 2-field constructor.
    """
    claims: list[VerifiedClaim]
    verdicts_total: dict[str, int]
    dropped_claims: list = ()
    task_outcome: str = "normal"


VerifierFn = Callable[[str], VerdictReport]
ChatWithToolsFn = Callable[..., dict]


@dataclass
class IterationRecord:
    """One iteration of the feedback loop.

    ``iter_idx == 0`` is the initial ReAct narrative (no feedback prompt
    yet). ``iter_idx >= 1`` is a feedback round: the agent saw the
    previous iteration's verifier hints and produced a revised narrative.
    """
    iter_idx: int
    narrative: str
    verdict_total: dict[str, int]
    quality: int  # n_contradicted + n_unsupported + n_unverifiable_v0 (lower is better; P0 fix 2026-05-18)
    n_contradicted: int
    n_unsupported: int
    n_supported: int
    n_unverifiable_v0: int
    n_tool_calls: int  # tools invoked DURING this iteration
    n_turns: int  # ReAct turns DURING this iteration (incl. finalise pass)
    force_finalised: bool
    feedback_prompt_used: bool
    verifier_failed: bool = False
    """True iff verifier_fn raised during this iteration. When True the
    iteration's ``quality`` is meaningless (computed from an empty
    VerdictReport) and the selection rule treats it as quality=+inf so
    a verifier-failed iteration cannot be picked as the final answer."""


@dataclass
class Sub6BAgentFeedbackResult:
    """Final result of one task's feedback-loop run."""
    task_id: str
    iterations: list[IterationRecord] = field(default_factory=list)
    final_iter_idx: int = 0  # which iteration's narrative is the "final" answer
    final_narrative: str = ""
    final_verdict_total: dict[str, int] = field(default_factory=dict)
    n_feedback_iterations: int = 0  # 0 = no feedback triggered
    elapsed_seconds: float = 0.0
    llm_model: str = ""
    metabolite_count: int = 0
    error: str | None = None
    rollback_reason: str | None = None  # "feedback_made_it_worse" / "iter2_degraded" / None
    termination_reason: str | None = None
    """Why the feedback loop stopped, for D5 audit triage. One of:
      - ``early_exit_no_revisions`` — iter 0 verifier found 0 actionable
        claims; feedback loop never ran. Signals a clean iter 0.
      - ``max_iterations_reached`` — exhausted ``max_feedback_iterations``.
      - ``no_actionable_claims_after_iter`` — feedback loop converged early
        (some iter >= 1 produced 0 actionable claims).
      - ``timeout_in_feedback_loop`` — total_timeout tripped between iters.
      - ``llm_error_in_feedback_iter`` — chat call failed during feedback.
      - ``verifier_error_in_feedback_iter`` — verifier_fn raised during feedback.
    None = single-iteration result with no feedback path taken AND no
    explicit termination marker (e.g. iter-0 LLM error)."""


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_MAX_REACT_TURNS = 5
DEFAULT_MAX_FEEDBACK_ITERS = 2
DEFAULT_TOTAL_TIMEOUT = 1200.0  # Phase B1 D4 — bumped from 900 to align with task-level cap
"""Total wall-time budget per task across all feedback iterations.
A2 D5 bumped this from 240→900: D4 saw 2/5 tasks tripping
total_timeout=600 because a 30-claim verifier round-trip can take
~3 min on its own and we run 3 verifier passes (one per iteration)
plus N LLM turns. 900s gives the loop a fighting chance to complete
all 2 feedback iterations even when MiniMax is slow."""


# ---------------------------------------------------------------------------
# Feedback message construction
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FEEDBACK_PROMPT_PATH = (
    _REPO_ROOT / "prompts" / "agent" / "sub6b_react_feedback_prompt.md"
)


def _load_feedback_template() -> str:
    if not _FEEDBACK_PROMPT_PATH.is_file():
        raise FileNotFoundError(f"feedback template missing at {_FEEDBACK_PROMPT_PATH}")
    text = _FEEDBACK_PROMPT_PATH.read_text(encoding="utf-8")
    # Strip the leading HTML comment block.
    if text.startswith("<!--"):
        end = text.find("-->")
        if end != -1:
            text = text[end + len("-->") :].lstrip()
    return text


def _format_claim_block(claims: list[VerifiedClaim]) -> str:
    """Format contradicted-or-unsupported claims as bullets for the prompt."""
    if not claims:
        return "  (none)"
    lines: list[str] = []
    for c in claims:
        cid = c.claim_id or "?"
        text = (c.claim_text or "").replace("\n", " ").strip()
        # Truncate very long claim text so the feedback prompt does not balloon.
        if len(text) > 280:
            text = text[:277] + "..."
        evidence = (c.evidence or "").replace("\n", " ").strip()
        if len(evidence) > 240:
            evidence = evidence[:237] + "..."
        hint = (c.feedback_hint or "(no hint)").replace("\n", " ").strip()
        lines.append(f"- **[{cid}]** \"{text}\"")
        lines.append(f"    Evidence: {evidence}")
        lines.append(f"    Hint: {hint}")
    return "\n".join(lines)


def _format_dropped_block(dropped_claims: list) -> str:
    """Phase B1 D4: render grammar-dropped claims for the feedback prompt.

    Each ``DroppedClaim`` carries a ``drop_reason`` from
    ``verifier.grammar.validate``; we look up a per-reason hint via
    ``feedback_hints.generate_drop_hint`` so the agent gets actionable
    guidance instead of just a pydantic error blob.
    """
    if not dropped_claims:
        return "  (none)"
    from verifier.feedback_hints import generate_drop_hint
    lines: list[str] = []
    for d in dropped_claims:
        text = (d.claim_text or "(empty)").replace("\n", " ").strip()
        if len(text) > 240:
            text = text[:237] + "..."
        grammar = d.grammar_attempt or "?"
        hint = generate_drop_hint(d).replace("\n", " ").strip()
        lines.append(f"- **[grammar={grammar}]** \"{text}\"")
        lines.append(f"    Drop reason: {d.drop_reason}")
        lines.append(f"    Hint: {hint}")
    return "\n".join(lines)


def build_feedback_message(
    *,
    contradicted: list[VerifiedClaim],
    unsupported: list[VerifiedClaim],
    original_narrative: str,
    unverifiable: list[VerifiedClaim] | None = None,
    dropped: list | None = None,
) -> str:
    """Render the feedback user message from the markdown template.

    Phase B1 D4: wires the four new placeholders the D1 template
    introduced (``{n_unverifiable}``, ``{n_dropped_by_grammar}``,
    ``{unverifiable_block}``, ``{dropped_block}``) plus the renamed
    ``{original_narrative_text}``. ``unverifiable`` and ``dropped``
    default to ``None`` so legacy callers (pre-D4 ablation runs) still
    work — they get empty blocks.
    """
    unverifiable = unverifiable or []
    dropped = dropped or []
    template = _load_feedback_template()
    return template.format(
        n_contradicted=len(contradicted),
        n_unsupported=len(unsupported),
        n_unverifiable=len(unverifiable),
        n_dropped_by_grammar=len(dropped),
        contradicted_block=_format_claim_block(contradicted),
        unsupported_block=_format_claim_block(unsupported),
        unverifiable_block=_format_claim_block(unverifiable),
        dropped_block=_format_dropped_block(dropped),
        original_narrative_text=(original_narrative or "(empty)").strip(),
    )


# ---------------------------------------------------------------------------
# Quality + selection
# ---------------------------------------------------------------------------


def _quality_score(verdict_total: dict[str, int]) -> tuple[int, int, int, int]:
    """Return (quality, n_contradicted, n_unsupported, n_supported).

    Phase B1 P0 fix (2026-05-18):
        quality = n_contradicted + n_unsupported + n_unverifiable_v0.

    Pre-fix the formula was n_contradicted + n_unsupported. That was
    consistent with the pre-D4 ``_NEUTRAL_VERDICTS`` set (which
    included UV), but D4 commit ``39c4272`` removed UV from
    ``_NEUTRAL_VERDICTS`` in ``verifier/feedback_hints.py:58`` and
    started generating feedback hints for UV claims. The quality
    function silently kept the old formula, so:

      (a) the post-iteration exit check ``if q == 0: break`` (line
          ~785) treated UV-only iterations as "nothing more to fix".
      (b) the rollback rule in ``_select_final_iteration`` could
          declare a UV-heavy iter "equal quality" to a low-UV iter,
          eroding the feedback loop's incentive structure.

    UV is now actionable (D4 hint generates a "rewrite or omit"
    instruction); the gate and the rollback should agree.
    """
    n_c = int(verdict_total.get("contradicted", 0))
    n_u = int(verdict_total.get("unsupported", 0))
    n_v = int(verdict_total.get("unverifiable_v0", 0))
    n_s = int(verdict_total.get("supported", 0))
    return n_c + n_u + n_v, n_c, n_u, n_s


def _select_final_iteration(
    iterations: list[IterationRecord],
) -> tuple[int, str | None]:
    """Apply the rollback rule. Returns (chosen_iter_idx, error_marker).

    Rule (mirrors spec D3, with ``>`` not ``<`` per docstring at top of module):
      - q(N2) > q(N0):   rollback to N0,  error="feedback_made_it_worse"
      - q(N2) > q(N1):   rollback to N1,  error="iter2_degraded"
      - else:            keep N2 (or N1 / N0 if loop stopped earlier)

    Verifier-failed iterations (``verifier_failed=True``) are EXCLUDED from
    the comparison: their reported quality is computed from an empty
    VerdictReport and is not a real quality score. D4 surfaced this when
    nucleotide_seed1 iter 2 had quality=0 due to a MiniMax 600 s read
    timeout in the verifier — the runner mistook the empty verdict for a
    perfect narrative and picked it as final. The fixed rule uses the
    last non-failed iteration as the comparison anchor, and skips the
    failed one entirely.

    If all iterations are verifier-failed, returns (0, "all_iters_verifier_failed")
    and the caller should treat this as a hard error.
    """
    if not iterations:
        return 0, None

    valid = [it for it in iterations if not it.verifier_failed]
    if not valid:
        # No iteration had a real verdict. Caller surfaces this as error.
        return iterations[0].iter_idx, "all_iters_verifier_failed"
    if len(valid) == 1:
        return valid[0].iter_idx, None

    last = valid[-1]
    n0 = valid[0]
    if last.quality > n0.quality:
        return n0.iter_idx, "feedback_made_it_worse"
    if len(valid) >= 3:
        n1 = valid[1]
        if last.quality > n1.quality:
            return n1.iter_idx, "iter2_degraded"
    return last.iter_idx, None


# ---------------------------------------------------------------------------
# ReAct turn-loop primitive (used for both initial and feedback iterations)
# ---------------------------------------------------------------------------


def _argument_str(tool_call: dict) -> str:
    fn = tool_call.get("function")
    if isinstance(fn, dict) and "arguments" in fn:
        args = fn["arguments"]
    else:
        args = tool_call.get("arguments")
    if isinstance(args, str):
        return args
    try:
        return json.dumps(args, ensure_ascii=False, default=str)
    except Exception:
        return str(args)


def _echo_assistant(msg: dict) -> dict:
    out: dict[str, Any] = {"role": "assistant"}
    if msg.get("tool_calls"):
        out["content"] = msg.get("content")
        out["tool_calls"] = msg["tool_calls"]
    else:
        out["content"] = msg.get("content") or ""
    return out


def _tool_result_message(envelope: dict, fallback_call_id: str) -> dict:
    return {
        "role": "tool",
        "tool_call_id": envelope.get("tool_call_id") or fallback_call_id,
        "name": envelope["name"],
        "content": json.dumps(
            envelope["result"], ensure_ascii=False, default=str
        ),
    }


def _strip_ground_truth(task: dict) -> dict:
    """Defensive copy used for prompt rendering — nothing leaks into the LLM.

    Mirrors A1's helper of the same name in run_sub6b_react.py. We do
    not import A1's because that file is locked by spec.
    """
    return {
        "task_id": task["task_id"],
        "differential_metabolites": list(task.get("differential_metabolites") or []),
    }


def _react_loop(
    *,
    messages: list[dict],
    chat_with_tools_fn: ChatWithToolsFn,
    finalise_chat_fn: ChatWithToolsFn,
    model: str,
    provider: str,
    temperature: float,
    max_turns: int,
    deadline: float,  # absolute time.perf_counter() value to stop at
    trace_id: str,
    caller: str,
    persister: TaskPersister | None = None,
    iter_idx: int = 0,
) -> tuple[str, list[dict], int, int, bool, str | None, list[dict]]:
    """Run a ReAct turn loop on an existing message history.

    Returns:
      (narrative, tool_calls_log, n_turns, n_tool_calls,
       force_finalised, error, messages_after)

    The loop appends to ``messages`` in place and also returns it.
    ``persister`` is recorded turn-by-turn when not None.
    """
    tool_calls_log: list[dict] = []
    n_turns = 0
    n_tool_calls = 0
    narrative = ""
    err: str | None = None
    timed_out = False

    for turn_idx in range(max_turns):
        if turn_idx > 0 and time.perf_counter() > deadline:
            timed_out = True
            break
        n_turns = turn_idx + 1

        try:
            msg = chat_with_tools_fn(
                messages,
                tools=TOOL_DEFINITIONS_OPENAI,
                tool_choice="auto",
                temperature=temperature,
                model=model,
                provider=provider,
                trace_id=trace_id,
                caller=f"{caller}_turn{n_turns}",
            )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            logger.warning("ReAct turn %d failed for %s: %s", n_turns, trace_id, err)
            break

        echoed = _echo_assistant(msg)
        messages.append(echoed)

        tool_calls = msg.get("tool_calls") or []
        turn_tool_logs: list[dict] = []
        if not tool_calls:
            narrative = (msg.get("content") or "").strip()
            if persister is not None:
                persister.record_turn(
                    iter_idx=iter_idx, turn_idx=n_turns,
                    assistant_message=echoed, tool_calls_log=[],
                )
            break

        for tc in tool_calls:
            n_tool_calls += 1
            envelope = dispatch(tc)
            entry = {
                "iter": iter_idx,
                "turn": n_turns,
                "name": envelope["name"],
                "tool_call_id": envelope.get("tool_call_id"),
                "arguments": _argument_str(tc),
                "result": envelope["result"],
                "cached": envelope["cached"],
            }
            tool_calls_log.append(entry)
            turn_tool_logs.append(entry)
            messages.append(
                _tool_result_message(envelope, fallback_call_id=f"call_local_{n_tool_calls}")
            )

        if persister is not None:
            persister.record_turn(
                iter_idx=iter_idx, turn_idx=n_turns,
                assistant_message=echoed, tool_calls_log=turn_tool_logs,
            )

    # Finalise pass when the loop exited without a narrative.
    force_finalised = False
    inner_retry_used = False
    if not hasattr(_react_loop, "_last_inner_retry"):
        _react_loop._last_inner_retry = False
    needs_finalise = (
        err is None
        and not narrative
        and (n_turns > 0 or timed_out)
    )
    if needs_finalise:
        force_finalised = True
        nudge = (
            "Time to summarise. Based on the tool outputs above, write the "
            "final 200-400 word narrative now. Do NOT call any more tools — "
            "tool_choice is set to 'none' for this turn."
        )
        messages.append({"role": "user", "content": nudge})
        try:
            final_msg = finalise_chat_fn(
                messages,
                tools=TOOL_DEFINITIONS_OPENAI,
                tool_choice="none",
                temperature=temperature,
                model=model,
                provider=provider,
                trace_id=trace_id,
                caller=f"{caller}_finalise",
                response_format={"type": "json_object"},
            )
            narrative = (final_msg.get("content") or "").strip()
            messages.append(_echo_assistant(final_msg))
            # Phase B1 D5 hotfix — Inner retry for Mode A (empty /
            # unparseable finalise). Same shape as
            # ``run_sub6b_react.run_sub6b_react``: budget=1/task, retries
            # only the finalise turn (not the ReAct loop). The feedback
            # runner has its own ``_react_loop`` and was therefore not
            # covered by the D4 inner-retry wire-up; the production D5
            # smoke surfaced 13 EMPTY_SYSTEM_FAILURE on seed 0 because
            # of this gap.
            if not _is_valid_json_payload(narrative):
                inner_retry_used = True
                _react_loop._last_inner_retry = True
                logger.info(
                    "Feedback ReAct finalise empty/unparseable for %s "
                    "— inner retry (budget=1)",
                    trace_id,
                )
                try:
                    final_msg = finalise_chat_fn(
                        messages,
                        tools=TOOL_DEFINITIONS_OPENAI,
                        tool_choice="none",
                        temperature=temperature,
                        model=model,
                        provider=provider,
                        trace_id=trace_id,
                        caller=f"{caller}_finalise_retry",
                        response_format={"type": "json_object"},
                    )
                    narrative = (final_msg.get("content") or "").strip()
                    messages.append(_echo_assistant(final_msg))
                except Exception as exc:
                    logger.warning(
                        "Feedback ReAct finalise inner retry failed for "
                        "%s: %s", trace_id, exc,
                    )
            if timed_out:
                err = "timeout_fallback_used"
            elif not narrative:
                err = "empty_narrative_after_finalise"
        except Exception as exc:
            err = f"finalise_failed: {type(exc).__name__}: {exc}"

    return narrative, tool_calls_log, n_turns, n_tool_calls, force_finalised, err, messages


# ---------------------------------------------------------------------------
# Public entry: run_sub6b_react_feedback
# ---------------------------------------------------------------------------


def run_sub6b_react_feedback(
    task: dict,
    *,
    verifier_fn: VerifierFn,
    chat_with_tools_fn: ChatWithToolsFn | None = None,
    finalise_chat_fn: ChatWithToolsFn | None = None,
    model: str = "MiniMax-M2.7",
    provider: str = "minimax",
    temperature: float = 0.0,
    max_react_turns: int = DEFAULT_MAX_REACT_TURNS,
    max_feedback_iterations: int = DEFAULT_MAX_FEEDBACK_ITERS,
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
    persister: TaskPersister | None = None,
    caller: str = "sub6b_agent_a2",
) -> Sub6BAgentFeedbackResult:
    """Run one Sub-6B task with ReAct + up to N feedback iterations.

    Termination:
      - LLM produces a final narrative AND verifier finds 0 actionable claims
        → loop exits (no feedback needed).
      - max_feedback_iterations reached.
      - total_timeout exceeded across all iterations.
      - Network / verifier error → record error, return what we have.

    The runner does NOT auto-resume from a partial persister state. Spec
    decision: partial detection is for audit triage, not execution.
    """
    chat_with_tools_fn = chat_with_tools_fn or llm_client.chat_with_tools
    finalise_chat_fn = finalise_chat_fn or llm_client.chat_with_tools

    safe = _strip_ground_truth(task)
    metabolites = safe["differential_metabolites"]
    task_id = safe["task_id"]

    reset_call_cache()
    t0 = time.perf_counter()
    deadline = t0 + total_timeout

    iterations: list[IterationRecord] = []
    err: str | None = None

    # ---------- Iteration 0: initial ReAct loop ----------
    messages: list[dict] = build_react_messages(metabolites)
    narrative, tool_log, n_turns, n_calls, force_fin, react_err, messages = _react_loop(
        messages=messages,
        chat_with_tools_fn=chat_with_tools_fn,
        finalise_chat_fn=finalise_chat_fn,
        model=model,
        provider=provider,
        temperature=temperature,
        max_turns=max_react_turns,
        deadline=deadline,
        trace_id=task_id,
        caller=f"{caller}_iter0",
        persister=persister,
        iter_idx=0,
    )
    if react_err and react_err not in {"timeout_fallback_used", "empty_narrative_after_finalise"}:
        # Hard LLM/network failure on iter 0 — bail, no verifier call.
        err = react_err
        result = Sub6BAgentFeedbackResult(
            task_id=task_id, iterations=[], final_iter_idx=0,
            final_narrative=narrative, final_verdict_total={},
            n_feedback_iterations=0,
            elapsed_seconds=time.perf_counter() - t0,
            llm_model=model, metabolite_count=len(metabolites),
            error=err,
        )
        if persister is not None:
            persister.mark_complete(
                final_narrative=narrative, n_iterations=0,
                n_total_tool_calls=n_calls,
                elapsed_seconds=result.elapsed_seconds, error=err,
            )
        return result

    # Verifier on N0
    iter0_verifier_failed = False
    try:
        report_0 = verifier_fn(narrative) if narrative else VerdictReport([], {})
    except Exception as exc:
        err = f"verifier_failed_iter0: {type(exc).__name__}: {exc}"
        report_0 = VerdictReport([], {})
        iter0_verifier_failed = True
        logger.warning("verifier failed on iter 0 for %s: %s", task_id, err)

    q0, n_c0, n_u0, n_s0 = _quality_score(report_0.verdicts_total)
    n_v0 = int(report_0.verdicts_total.get("unverifiable_v0", 0))

    iter0 = IterationRecord(
        iter_idx=0,
        narrative=narrative,
        verdict_total=dict(report_0.verdicts_total),
        quality=q0,
        n_contradicted=n_c0,
        n_unsupported=n_u0,
        n_supported=n_s0,
        n_unverifiable_v0=n_v0,
        n_tool_calls=n_calls,
        n_turns=n_turns,
        force_finalised=force_fin,
        feedback_prompt_used=False,
        verifier_failed=iter0_verifier_failed,
    )
    iterations.append(iter0)
    if persister is not None:
        persister.record_iteration(
            iter_idx=0, narrative=narrative,
            verdict_summary=dict(report_0.verdicts_total),
            n_tool_calls=n_calls, n_turns=n_turns,
            force_finalised=force_fin, feedback_prompt_used=False,
        )

    # ---------- Feedback iterations ----------
    prev_report = report_0
    prev_narrative = narrative
    feedback_iters_done = 0
    termination_reason: str | None = None

    for fb in range(1, max_feedback_iterations + 1):
        # Phase B1 D4: actionable now includes CONTRADICTED, UNSUPPORTED,
        # UNVERIFIABLE_V0 (D4 hint added) AND any grammar-dropped claims
        # from the prev iteration. We also handle Mode B
        # (EMPTY_HONEST_REFUSAL) as a task-level signal that triggers
        # the refusal-specific outer retry.
        actionable = [
            c for c in prev_report.claims
            if c.verdict in (ClaimVerdict.CONTRADICTED, ClaimVerdict.UNSUPPORTED)
        ]
        unverifiable = [
            c for c in prev_report.claims
            if c.verdict == ClaimVerdict.UNVERIFIABLE_V0
        ]
        prev_dropped = list(prev_report.dropped_claims or [])
        is_mode_b = prev_report.task_outcome == "empty_honest_refusal"
        # Outer retry budget for Mode B: only fb iter 1 retries; after
        # one shot we accept the refusal as final.
        if is_mode_b and fb > 1:
            termination_reason = "mode_b_accepted_after_refusal_retry"
            break
        if not (actionable or unverifiable or prev_dropped or is_mode_b):
            termination_reason = (
                "early_exit_no_revisions" if fb == 1
                else "no_actionable_claims_after_iter"
            )
            break

        if time.perf_counter() > deadline:
            err = err or "timeout_in_feedback_loop"
            termination_reason = "timeout_in_feedback_loop"
            break

        contradicted = [c for c in actionable if c.verdict == ClaimVerdict.CONTRADICTED]
        unsupported = [c for c in actionable if c.verdict == ClaimVerdict.UNSUPPORTED]
        feedback_msg = build_feedback_message(
            contradicted=contradicted,
            unsupported=unsupported,
            original_narrative=prev_narrative,
            unverifiable=unverifiable,
            dropped=prev_dropped,
        )
        if is_mode_b:
            from verifier.feedback_hints import generate_refusal_hint
            feedback_msg = generate_refusal_hint() + "\n\n" + feedback_msg
        messages.append({"role": "user", "content": feedback_msg})

        # Constrained ReAct: fewer turns for feedback iteration (LLM should
        # be revising, not re-researching). Half the budget rounded up.
        feedback_max_turns = max(2, (max_react_turns + 1) // 2)
        narrative_n, tool_log_n, n_turns_n, n_calls_n, force_fin_n, react_err_n, messages = _react_loop(
            messages=messages,
            chat_with_tools_fn=chat_with_tools_fn,
            finalise_chat_fn=finalise_chat_fn,
            model=model,
            provider=provider,
            temperature=temperature,
            max_turns=feedback_max_turns,
            deadline=deadline,
            trace_id=f"{task_id}.iter{fb}",
            caller=f"{caller}_iter{fb}",
            persister=persister,
            iter_idx=fb,
        )
        if react_err_n and react_err_n not in {"timeout_fallback_used", "empty_narrative_after_finalise"}:
            err = err or react_err_n
            termination_reason = "llm_error_in_feedback_iter"
            break

        # Verifier on N_fb
        iter_verifier_failed = False
        try:
            report_fb = verifier_fn(narrative_n) if narrative_n else VerdictReport([], {})
        except Exception as exc:
            err = err or f"verifier_failed_iter{fb}: {type(exc).__name__}: {exc}"
            report_fb = VerdictReport([], {})
            termination_reason = "verifier_error_in_feedback_iter"
            iter_verifier_failed = True

        q, n_c, n_u, n_s = _quality_score(report_fb.verdicts_total)
        n_v = int(report_fb.verdicts_total.get("unverifiable_v0", 0))

        iter_rec = IterationRecord(
            iter_idx=fb,
            narrative=narrative_n,
            verdict_total=dict(report_fb.verdicts_total),
            quality=q,
            n_contradicted=n_c,
            n_unsupported=n_u,
            n_supported=n_s,
            n_unverifiable_v0=n_v,
            n_tool_calls=n_calls_n,
            n_turns=n_turns_n,
            force_finalised=force_fin_n,
            feedback_prompt_used=True,
            verifier_failed=iter_verifier_failed,
        )
        iterations.append(iter_rec)
        feedback_iters_done += 1

        if persister is not None:
            persister.record_iteration(
                iter_idx=fb, narrative=narrative_n,
                verdict_summary=dict(report_fb.verdicts_total),
                n_tool_calls=n_calls_n, n_turns=n_turns_n,
                force_finalised=force_fin_n, feedback_prompt_used=True,
            )

        # If THIS iter's verifier failed, do NOT use its empty report to
        # decide actionable / convergence. Bail to selection rule which
        # treats verifier_failed iters as quality=+inf.
        if iter_verifier_failed:
            break

        prev_report = report_fb
        prev_narrative = narrative_n

        # Early exit: no actionable claims left. Don't clobber an
        # already-set termination_reason (e.g. from verifier_error).
        if q == 0:
            termination_reason = termination_reason or "no_actionable_claims_after_iter"
            break

    else:  # for-loop ran to completion without break
        termination_reason = termination_reason or "max_iterations_reached"

    # If feedback loop never ran but iter 0 had 0 actionable claims → mark.
    if feedback_iters_done == 0 and termination_reason is None and len(iterations) == 1:
        if iterations[0].quality == 0:
            termination_reason = "early_exit_no_revisions"

    # ---------- Selection ----------
    final_iter_idx, rollback_reason = _select_final_iteration(iterations)
    if rollback_reason == "all_iters_verifier_failed":
        err = err or "all_iters_verifier_failed"
    final_iter = next(it for it in iterations if it.iter_idx == final_iter_idx)
    elapsed = time.perf_counter() - t0
    n_total_tool_calls = sum(it.n_tool_calls for it in iterations)

    result = Sub6BAgentFeedbackResult(
        task_id=task_id,
        iterations=iterations,
        final_iter_idx=final_iter_idx,
        final_narrative=final_iter.narrative,
        final_verdict_total=final_iter.verdict_total,
        n_feedback_iterations=feedback_iters_done,
        elapsed_seconds=elapsed,
        llm_model=model,
        metabolite_count=len(metabolites),
        error=err,
        rollback_reason=rollback_reason,
        termination_reason=termination_reason,
    )

    if persister is not None:
        persister.mark_complete(
            final_narrative=final_iter.narrative,
            n_iterations=feedback_iters_done,
            n_total_tool_calls=n_total_tool_calls,
            elapsed_seconds=elapsed,
            error=err,
            extra={
                "final_iter_idx": final_iter_idx,
                "rollback_reason": rollback_reason,
                "termination_reason": termination_reason,
                "qualities": [it.quality for it in iterations],
            },
        )

    return result


# ---------------------------------------------------------------------------
# Reuse-narrative entry point (D4 wall-time saver)
# ---------------------------------------------------------------------------


def run_sub6b_feedback_from_narrative(
    task: dict,
    iter0_narrative: str,
    *,
    verifier_fn: VerifierFn,
    chat_with_tools_fn: ChatWithToolsFn | None = None,
    finalise_chat_fn: ChatWithToolsFn | None = None,
    iter0_n_tool_calls: int = 0,
    iter0_n_turns: int = 0,
    iter0_force_finalised: bool = False,
    model: str = "MiniMax-M2.7",
    provider: str = "minimax",
    temperature: float = 0.0,
    max_react_turns: int = DEFAULT_MAX_REACT_TURNS,
    max_feedback_iterations: int = DEFAULT_MAX_FEEDBACK_ITERS,
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
    persister: TaskPersister | None = None,
    caller: str = "sub6b_agent_a2_reuse",
) -> Sub6BAgentFeedbackResult:
    """Run the feedback loop with a pre-computed iteration-0 narrative.

    D4 use case: A2's pilot wants 3 variants (single-call / react-only /
    react+feedback) on the same task. The feedback variant must reuse
    the react-only narrative as its iter 0 — re-running ReAct just to
    re-derive the same N0 wastes ~50 % of wall time and risks LLM-
    nondeterminism drift between the two variants. This entry point
    accepts the prior narrative directly and skips iter 0's ReAct loop.

    Iteration-0 telemetry (n_tool_calls / n_turns / force_finalised) is
    inherited from the caller's prior run via the optional
    ``iter0_*`` kwargs so the IterationRecord still reflects the work
    that produced the narrative.

    Synthetic message history seeded into the LLM context for iteration-1+:

        [system prompt] (build_react_messages)
        [user prompt]   (build_react_messages)
        [assistant]     content=iter0_narrative, no tool_calls

    The LLM in iter 1 sees the conversation as if it had directly
    produced ``iter0_narrative`` without tool calls. It then receives
    the feedback user message and may call tools as in a normal feedback
    iteration.
    """
    chat_with_tools_fn = chat_with_tools_fn or llm_client.chat_with_tools
    finalise_chat_fn = finalise_chat_fn or llm_client.chat_with_tools

    safe = _strip_ground_truth(task)
    metabolites = safe["differential_metabolites"]
    task_id = safe["task_id"]

    reset_call_cache()
    t0 = time.perf_counter()
    deadline = t0 + total_timeout

    # Synthetic message history for iteration-1+.
    messages: list[dict] = build_react_messages(metabolites)
    messages.append(
        {"role": "assistant", "content": iter0_narrative, "tool_calls": None}
    )

    iterations: list[IterationRecord] = []
    err: str | None = None
    termination_reason: str | None = None

    # Verify the supplied narrative.
    iter0_verifier_failed = False
    try:
        report_0 = (
            verifier_fn(iter0_narrative)
            if iter0_narrative
            else VerdictReport([], {})
        )
    except Exception as exc:
        err = f"verifier_failed_iter0: {type(exc).__name__}: {exc}"
        report_0 = VerdictReport([], {})
        iter0_verifier_failed = True
        logger.warning("verifier failed on supplied iter 0 for %s: %s", task_id, err)

    q0, n_c0, n_u0, n_s0 = _quality_score(report_0.verdicts_total)
    n_v0 = int(report_0.verdicts_total.get("unverifiable_v0", 0))

    iter0 = IterationRecord(
        iter_idx=0,
        narrative=iter0_narrative,
        verdict_total=dict(report_0.verdicts_total),
        quality=q0,
        n_contradicted=n_c0,
        n_unsupported=n_u0,
        n_supported=n_s0,
        n_unverifiable_v0=n_v0,
        n_tool_calls=iter0_n_tool_calls,
        n_turns=iter0_n_turns,
        force_finalised=iter0_force_finalised,
        feedback_prompt_used=False,
        verifier_failed=iter0_verifier_failed,
    )
    iterations.append(iter0)
    if persister is not None:
        persister.record_iteration(
            iter_idx=0, narrative=iter0_narrative,
            verdict_summary=dict(report_0.verdicts_total),
            n_tool_calls=iter0_n_tool_calls, n_turns=iter0_n_turns,
            force_finalised=iter0_force_finalised, feedback_prompt_used=False,
        )

    # Run feedback iterations using the same loop body as the full runner.
    prev_report = report_0
    prev_narrative = iter0_narrative
    feedback_iters_done = 0

    for fb in range(1, max_feedback_iterations + 1):
        actionable = [
            c for c in prev_report.claims
            if c.verdict in (ClaimVerdict.CONTRADICTED, ClaimVerdict.UNSUPPORTED)
        ]
        if not actionable:
            termination_reason = (
                "early_exit_no_revisions" if fb == 1
                else "no_actionable_claims_after_iter"
            )
            break

        if time.perf_counter() > deadline:
            err = err or "timeout_in_feedback_loop"
            termination_reason = "timeout_in_feedback_loop"
            break

        contradicted = [c for c in actionable if c.verdict == ClaimVerdict.CONTRADICTED]
        unsupported = [c for c in actionable if c.verdict == ClaimVerdict.UNSUPPORTED]
        # Phase B1 D4 — same outer-retry / dropped / UNV plumbing here.
        unverifiable_b = [
            c for c in prev_report.claims
            if c.verdict == ClaimVerdict.UNVERIFIABLE_V0
        ]
        prev_dropped_b = list(prev_report.dropped_claims or [])
        is_mode_b = prev_report.task_outcome == "empty_honest_refusal"
        feedback_msg = build_feedback_message(
            contradicted=contradicted,
            unsupported=unsupported,
            original_narrative=prev_narrative,
            unverifiable=unverifiable_b,
            dropped=prev_dropped_b,
        )
        if is_mode_b:
            from verifier.feedback_hints import generate_refusal_hint
            feedback_msg = generate_refusal_hint() + "\n\n" + feedback_msg
        messages.append({"role": "user", "content": feedback_msg})

        feedback_max_turns = max(2, (max_react_turns + 1) // 2)
        narrative_n, _tool_log, n_turns_n, n_calls_n, force_fin_n, react_err_n, messages = _react_loop(
            messages=messages,
            chat_with_tools_fn=chat_with_tools_fn,
            finalise_chat_fn=finalise_chat_fn,
            model=model,
            provider=provider,
            temperature=temperature,
            max_turns=feedback_max_turns,
            deadline=deadline,
            trace_id=f"{task_id}.iter{fb}",
            caller=f"{caller}_iter{fb}",
            persister=persister,
            iter_idx=fb,
        )
        if react_err_n and react_err_n not in {"timeout_fallback_used", "empty_narrative_after_finalise"}:
            err = err or react_err_n
            termination_reason = "llm_error_in_feedback_iter"
            break

        iter_verifier_failed = False
        try:
            report_fb = verifier_fn(narrative_n) if narrative_n else VerdictReport([], {})
        except Exception as exc:
            err = err or f"verifier_failed_iter{fb}: {type(exc).__name__}: {exc}"
            report_fb = VerdictReport([], {})
            termination_reason = "verifier_error_in_feedback_iter"
            iter_verifier_failed = True

        q, n_c, n_u, n_s = _quality_score(report_fb.verdicts_total)
        n_v = int(report_fb.verdicts_total.get("unverifiable_v0", 0))

        iter_rec = IterationRecord(
            iter_idx=fb,
            narrative=narrative_n,
            verdict_total=dict(report_fb.verdicts_total),
            quality=q,
            n_contradicted=n_c,
            n_unsupported=n_u,
            n_supported=n_s,
            n_unverifiable_v0=n_v,
            n_tool_calls=n_calls_n,
            n_turns=n_turns_n,
            force_finalised=force_fin_n,
            feedback_prompt_used=True,
            verifier_failed=iter_verifier_failed,
        )
        iterations.append(iter_rec)
        feedback_iters_done += 1

        if persister is not None:
            persister.record_iteration(
                iter_idx=fb, narrative=narrative_n,
                verdict_summary=dict(report_fb.verdicts_total),
                n_tool_calls=n_calls_n, n_turns=n_turns_n,
                force_finalised=force_fin_n, feedback_prompt_used=True,
            )

        if iter_verifier_failed:
            break

        prev_report = report_fb
        prev_narrative = narrative_n

        if q == 0:
            termination_reason = termination_reason or "no_actionable_claims_after_iter"
            break
    else:
        termination_reason = termination_reason or "max_iterations_reached"

    if feedback_iters_done == 0 and termination_reason is None and len(iterations) == 1:
        if iterations[0].quality == 0:
            termination_reason = "early_exit_no_revisions"

    final_iter_idx, rollback_reason = _select_final_iteration(iterations)
    if rollback_reason == "all_iters_verifier_failed":
        err = err or "all_iters_verifier_failed"
    final_iter = next(it for it in iterations if it.iter_idx == final_iter_idx)
    elapsed = time.perf_counter() - t0
    n_total_tool_calls = sum(it.n_tool_calls for it in iterations)

    result = Sub6BAgentFeedbackResult(
        task_id=task_id,
        iterations=iterations,
        final_iter_idx=final_iter_idx,
        final_narrative=final_iter.narrative,
        final_verdict_total=final_iter.verdict_total,
        n_feedback_iterations=feedback_iters_done,
        elapsed_seconds=elapsed,
        llm_model=model,
        metabolite_count=len(metabolites),
        error=err,
        rollback_reason=rollback_reason,
        termination_reason=termination_reason,
    )

    if persister is not None:
        persister.mark_complete(
            final_narrative=final_iter.narrative,
            n_iterations=feedback_iters_done,
            n_total_tool_calls=n_total_tool_calls,
            elapsed_seconds=elapsed,
            error=err,
            extra={
                "final_iter_idx": final_iter_idx,
                "rollback_reason": rollback_reason,
                "termination_reason": termination_reason,
                "qualities": [it.quality for it in iterations],
                "iter0_reused": True,
            },
        )

    return result


# ---------------------------------------------------------------------------
# CLI shim — minimal, mainly for D5 batch driver
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Minimal CLI for one task. Real batch driver lives in scripts/eval_sub6/."""
    import argparse, os
    from collections import Counter
    from evaluation.sub6.io_utils import iter_jsonl
    from evaluation.sub6.run_sub6b import _resolve_api_key

    p = argparse.ArgumentParser()
    p.add_argument("--task-id", required=True)
    p.add_argument("--tasks", required=True, help="Sub-6B v3 jsonl")
    p.add_argument("--out", required=True, help="Output jsonl (single line)")
    p.add_argument("--persist-dir", default="data/eval/sub6/v4_a2/persist")
    p.add_argument("--model", default="MiniMax-M2.7")
    p.add_argument("--provider", default="minimax")
    p.add_argument("--max-react-turns", type=int, default=DEFAULT_MAX_REACT_TURNS)
    p.add_argument("--max-feedback-iters", type=int, default=DEFAULT_MAX_FEEDBACK_ITERS)
    p.add_argument("--total-timeout", type=float, default=DEFAULT_TOTAL_TIMEOUT)
    p.add_argument("--ramp-db", default=os.environ.get(
        "METAGENT_RAMP_PATH",
        "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite",
    ))
    p.add_argument("--curated", default="data/benchmark/sub6/curated_hmdb_mammalian.jsonl")
    args = p.parse_args(argv)

    _resolve_api_key(args.provider, args.model)

    # Locate task
    task = next(
        (t for t in iter_jsonl(args.tasks) if t.get("task_id") == args.task_id),
        None,
    )
    if task is None:
        raise SystemExit(f"task_id {args.task_id} not in {args.tasks}")

    # Build verifier_fn — wraps verify_sub6
    from scripts.eval_sub6.grade_with_verifier import (
        _build_driver_lookup,
        _build_source_report,
    )
    from verifier.agent import verify_sub6

    driver_lookup = _build_driver_lookup(Path(args.curated))
    source_report = _build_source_report(task)

    def verifier_fn(narrative: str) -> VerdictReport:
        v = verify_sub6(
            narrative, source_report,
            trace_id=f"{args.task_id}.a2_feedback",
            ramp_db_path=args.ramp_db,
            driver_lookup=driver_lookup,
        )
        total = Counter(c.verdict.value for c in v.claims_v2)
        return VerdictReport(
            claims=list(v.claims_v2),
            verdicts_total=dict(total),
            dropped_claims=list(getattr(v, "dropped_claims", []) or []),
            task_outcome=getattr(
                getattr(v, "task_outcome", None), "value", "normal"
            ),
        )

    persister = TaskPersister(Path(args.persist_dir), args.task_id)
    result = run_sub6b_react_feedback(
        task,
        verifier_fn=verifier_fn,
        model=args.model,
        provider=args.provider,
        max_react_turns=args.max_react_turns,
        max_feedback_iterations=args.max_feedback_iters,
        total_timeout=args.total_timeout,
        persister=persister,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(asdict(result), ensure_ascii=False, default=str) + "\n")
    print(
        f"task={result.task_id} final_iter={result.final_iter_idx} "
        f"q=[{','.join(str(it.quality) for it in result.iterations)}] "
        f"rollback={result.rollback_reason} error={result.error} "
        f"elapsed={result.elapsed_seconds:.1f}s"
    )
    return 0 if result.error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
