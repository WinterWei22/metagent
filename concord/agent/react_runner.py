"""ConcordMet ReAct + closed-loop verifier runner (W8 D3).

Mirrors the contract of `evaluation/sub6/run_sub6b_react_feedback.py`
but for the ConcordMet 9-tool catalogue. D1 fixed the public surface
(class name, init signature, run_task signature, default constants,
result dataclass shapes); D2 wired the 9 tool handlers; D3 wires the
ReAct loop body so end-to-end smoke on sub6b-v3 tasks can run.

Body wiring status:
  D2:  PA wrappers in `concord/agent/tool_dispatcher.HANDLERS`        ✓
  D3:  ReAct loop body — replaces D1's NotImplementedError below       ✓
       smoke 2 task end-to-end (steroid + WP167 lipid smoking gun)
  D4:  Closed-loop verifier — `verifier_fn` injection so the finalised
       grammar-v2 JSON is fed to `verifier.agent.verify()` via
       `concord.agent.verifier_adapter`. Feedback iteration logic
       lifted from B1's `run_sub6b_react_feedback`.                 (pending)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from concord.agent.system_prompts import build_concord_react_messages
from concord.agent.tool_dispatcher import (
    TOOL_NAMES,
    dispatch,
    get_tool_specs,
    reset_call_cache,
)
from common import llm_client
from concord.agent.pathway_prediction import (
    generate_pathway_prediction_second_pass,
    _ABSTAIN_SECOND_PASS_FAILED,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults (W8 §2 spec)
# ---------------------------------------------------------------------------

# Hard upper bound on intermediate ReAct turns. B1 default is 5; W8
# bumps to 8 because ConcordMet has 9 tools (vs 5 in B1) and an LLM
# may need 1-2 extra turns to call complementary paradigms.
DEFAULT_MAX_REACT_TURNS = 8

# Feedback loop iterations. Sub-6B established 2 is a good ceiling
# (W7+W6 numbers); W8 keeps the same ceiling.
DEFAULT_MAX_FEEDBACK_ITERS = 1  # W14.B (was 2 W8-W13); see commit body for justification

# Inner-retry budget when finalise produces empty / unparseable output.
# Mirrors B1 D4 component 4a.
DEFAULT_INNER_FINALISE_RETRIES = 1

# Per-task wall-time ceiling, mirrors B1 D4 component 4c. Higher than
# B1 (1200 vs 900) because ConcordMet has more potentially-slow tools
# (mummichog + MetaboAnalystR + FELLA all Docker-bound).
DEFAULT_TASK_TIMEOUT_SECONDS = 1200.0

# Defaults for the active LLM provider. MiniMax remains available via explicit
# llm_model / provider overrides.
DEFAULT_LLM_MODEL = "gpt-5.5"
DEFAULT_LLM_PROVIDER = "openai"

# Grammar v2 final-message — the four `claim_type` values the system
# prompt instructs the LLM to emit. Used for structural validation only;
# semantic checks live in the verifier (D4).
GRAMMAR_V2_CLAIM_TYPES = {
    "PATHWAY_ENRICHMENT",
    "PATHWAY_MEMBERSHIP",
    "METABOLITE_PATHWAY_LINK",
    "DRIVER_METABOLITE",
}


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ConcordIterationRecord:
    """One iteration of the ReAct + feedback loop.

    iter_idx == 0 is the initial ReAct run (no verifier feedback prompt
    seen yet). iter_idx >= 1 is a feedback round.
    """

    iter_idx: int
    narrative_json: str  # the final grammar-v2 JSON message verbatim
    verdict_total: dict[str, int] = field(default_factory=dict)
    quality: int = 0  # n_contradicted + n_unsupported (lower is better)
    n_contradicted: int = 0
    n_unsupported: int = 0
    n_supported: int = 0
    n_unverifiable_v0: int = 0
    n_insufficient_evidence: int = 0
    n_tool_calls: int = 0
    n_turns: int = 0
    force_finalised: bool = False
    feedback_prompt_used: bool = False
    verifier_failed: bool = False
    inner_retry_used: bool = False


@dataclass
class ConcordReactResult:
    """Final result of one sub6b task end-to-end through ConcordMet."""

    task_id: str
    iterations: list[ConcordIterationRecord] = field(default_factory=list)
    final_iter_idx: int = 0
    final_narrative_json: str = ""
    final_claims: list[dict[str, Any]] = field(default_factory=list)
    final_narrative_text: str = ""
    pathway_prediction: dict[str, Any] | None = None
    final_verdict_total: dict[str, int] = field(default_factory=dict)
    task_outcome: str = "normal"  # B1 D4 TaskOutcome enum, str form
    n_feedback_iterations: int = 0
    elapsed_seconds: float = 0.0
    llm_model: str = ""
    metabolite_count: int = 0
    n_distinct_tools_called: int = 0
    tools_called: list[str] = field(default_factory=list)
    tool_calls_trace: list[dict[str, Any]] = field(default_factory=list)
    enrichment_carriers: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    rollback_reason: str | None = None
    termination_reason: str | None = None


# Verifier injection: a callable that takes the prose narrative string
# + a B1 SubsixSourceReport (positionally) and returns a B1
# VerifiedIdentification-like object exposing `verdicts_total` (a dict
# of verdict-name → int) and `claims_v1` (list of VerifiedClaim).
# Defaults to `verifier.agent.verify_sub6` (resolved lazily at call
# time so import stays light + tests can inject mocks via constructor).
VerifierFn = Callable[..., Any]


@dataclass
class VerificationOutcome:
    """Envelope returned by `ConcordReactRunner.verify_with_b1`.

    `ok=False` means the verifier did not run successfully — either the
    SubsixSourceReport adapter raised (benchmark corruption) or the B1
    verifier itself raised. In both cases `verdict` is None and `quality`
    is treated as 0 so downstream feedback loops short-circuit
    gracefully rather than crash.
    """

    ok: bool
    verdict: Any  # VerifiedIdentification on success, None on failure
    error: str | None
    n_supported: int = 0
    n_unsupported: int = 0
    n_contradicted: int = 0
    n_unverifiable_v0: int = 0
    n_insufficient_evidence: int = 0

    @property
    def quality(self) -> int:
        """B1 D4 definition: quality = n_contradicted + n_unsupported.
        Lower is better; 0 means no claim needs revision."""
        return self.n_contradicted + self.n_unsupported

# LLM client injection: a callable matching the OpenAI-compatible
# chat-with-tools shape. D3 wires this against `common.llm_client`.
ChatWithToolsFn = Callable[..., dict[str, Any]]


# ---------------------------------------------------------------------------
# Loop helpers (module-private)
# ---------------------------------------------------------------------------


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_object(text: str) -> str | None:
    """Pull a JSON object out of a possibly-noisy LLM message.

    Strategy (cheap → expensive):
      1. Strip MiniMax-style ``</think>`` reasoning.
      2. If the entire trimmed content parses as a dict, return it.
      3. Try the LAST fenced ```json ... ``` block.
      4. Try the largest balanced {...} span.
    Returns the raw JSON string (caller does json.loads), or None.
    """
    if not text:
        return None
    # Strip MiniMax reasoning prelude
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    s = text.strip()
    if not s:
        return None
    # Whole-content direct parse
    try:
        if isinstance(json.loads(s), dict):
            return s
    except json.JSONDecodeError:
        pass
    # Last fenced ```json ... ```
    fences = _JSON_FENCE_RE.findall(s)
    if fences:
        candidate = fences[-1]
        try:
            if isinstance(json.loads(candidate), dict):
                return candidate
        except json.JSONDecodeError:
            pass
    # Largest balanced {...} span
    i, j = s.find("{"), s.rfind("}")
    if 0 <= i < j:
        candidate = s[i : j + 1]
        try:
            if isinstance(json.loads(candidate), dict):
                return candidate
        except json.JSONDecodeError:
            pass
    return None


def _validate_grammar_v2(parsed: dict[str, Any]) -> tuple[bool, str | None]:
    """Light structural check on the final-message JSON.

    Returns (ok, error_reason). Semantic verification is the verifier's
    job (D4); this only checks the LLM emitted the expected SHAPE.
    """
    if not isinstance(parsed, dict):
        return False, "top-level JSON must be an object"
    if "narrative_text" not in parsed:
        return False, "missing 'narrative_text' field"
    if not isinstance(parsed.get("narrative_text"), str):
        return False, "'narrative_text' must be a string"
    claims = parsed.get("claims")
    if not isinstance(claims, list):
        return False, "missing or non-list 'claims' field"
    # Each claim must be a dict with a recognised claim_type. Empty
    # claims list is allowed (LLM may legitimately have nothing concrete
    # to say) but warns at outcome-classification time.
    for i, c in enumerate(claims):
        if not isinstance(c, dict):
            return False, f"claim[{i}] is not an object"
        ct = c.get("claim_type")
        if ct not in GRAMMAR_V2_CLAIM_TYPES:
            return False, (
                f"claim[{i}] claim_type {ct!r} not in "
                f"{sorted(GRAMMAR_V2_CLAIM_TYPES)}"
            )
    return True, None


def _argument_str(tool_call: dict[str, Any]) -> str:
    """Render tool_call arguments as a string for the trace log."""
    fn = tool_call.get("function")
    if isinstance(fn, dict) and "arguments" in fn:
        args = fn["arguments"]
    else:
        args = tool_call.get("arguments")
    if isinstance(args, str):
        return args
    try:
        return json.dumps(args, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return repr(args)


def _echo_assistant(msg: dict[str, Any]) -> dict[str, Any]:
    """Sanitise the LLM's assistant message for re-injection into history."""
    out: dict[str, Any] = {"role": "assistant"}
    if msg.get("tool_calls"):
        out["content"] = msg.get("content")
        out["tool_calls"] = msg["tool_calls"]
    else:
        out["content"] = msg.get("content") or ""
    return out


def _tool_result_message(
    tool_name: str,
    tool_call_id: str,
    payload: dict[str, Any],
    fallback_call_id: str,
) -> dict[str, Any]:
    """Wrap a dispatcher payload as an OpenAI-style `tool` role message."""
    return {
        "role": "tool",
        "tool_call_id": tool_call_id or fallback_call_id,
        "name": tool_name,
        "content": json.dumps(payload, ensure_ascii=False, default=str),
    }


def _strip_task_for_llm(task: dict[str, Any]) -> dict[str, Any]:
    """Defensive copy used for prompt rendering — strips ground-truth.

    The sub6b-v3 task dict carries `ground_truth_pathway`,
    `ground_truth_signal_compounds`, `ground_truth_noise_compounds`, and
    `ramp_enrichment_result` (the build-time RaMP run). We send only
    the differential-metabolite list to the LLM so the LLM cannot
    accidentally regurgitate ground truth.
    """
    return {
        "task_id": task.get("task_id"),
        "differential_metabolites": list(task.get("differential_metabolites") or []),
    }


_RETRY_NUDGE_PROMPT = (
    "Your last message was not a valid grammar-v2 JSON. Re-emit a single "
    "JSON object — fenced in ```json ... ``` is fine — matching this shape:\n"
    "  {\n"
    "    \"narrative_text\": \"<200-400 word prose>\",\n"
    "    \"claims\": [\n"
    "      {\"claim_type\": \"PATHWAY_ENRICHMENT\", \"pathway_id\": \"<NS:id>\", ...},\n"
    "      ...\n"
    "    ]\n"
    "  }\n"
    "Each claim's `claim_type` must be one of: PATHWAY_ENRICHMENT, "
    "PATHWAY_MEMBERSHIP, METABOLITE_PATHWAY_LINK, DRIVER_METABOLITE.\n"
    "Do NOT call any tools. Do NOT add prose outside the JSON object."
)


_FORCE_FINALISE_PROMPT = (
    "You have used your turn budget. Stop calling tools and emit the final "
    "grammar-v2 JSON now, based on the tool outputs you have already "
    "received. Same shape as above: a single fenced JSON object with "
    "`narrative_text` (200-400 words) and `claims` (each with a valid "
    "claim_type)."
)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass
class ConcordReactRunner:
    """Per-session runner for the ConcordMet LLM-agent pipeline.

    Stateless across tasks aside from the per-call dedup cache, which
    is reset at the start of each `run_task` call (mirrors B1
    `run_sub6b_react_feedback.Sub6BAgentFeedbackResult` semantics).
    """

    chat_with_tools: ChatWithToolsFn | None = None
    verifier_fn: VerifierFn | None = None
    llm_model: str = DEFAULT_LLM_MODEL
    llm_provider: str = DEFAULT_LLM_PROVIDER
    max_react_turns: int = DEFAULT_MAX_REACT_TURNS
    max_feedback_iters: int = DEFAULT_MAX_FEEDBACK_ITERS
    inner_finalise_retries: int = DEFAULT_INNER_FINALISE_RETRIES
    task_timeout_seconds: float = DEFAULT_TASK_TIMEOUT_SECONDS
    feedback_strategy: str = "cascade"

    def __post_init__(self) -> None:
        # Validate config the moment a runner is constructed so a
        # garbled call site fails fast rather than mid-loop.
        if self.max_react_turns < 1 or self.max_react_turns > 8:
            raise ValueError(
                f"max_react_turns must be in [1, 8] (W8 ceiling), "
                f"got {self.max_react_turns}"
            )
        if self.max_feedback_iters < 0 or self.max_feedback_iters > 2:
            raise ValueError(
                f"max_feedback_iters must be in [0, 2], "
                f"got {self.max_feedback_iters}"
            )
        if self.inner_finalise_retries < 0 or self.inner_finalise_retries > 1:
            raise ValueError(
                f"inner_finalise_retries must be 0 or 1, "
                f"got {self.inner_finalise_retries}"
            )
        if self.feedback_strategy not in ("cascade", "rewrite"):
            raise ValueError(
                f"feedback_strategy must be 'cascade' or 'rewrite'; "
                f"got {self.feedback_strategy!r}"
            )

        self.tool_specs = get_tool_specs()
        self.tool_names = TOOL_NAMES
        if len(self.tool_specs) != 9:
            raise AssertionError(
                f"ConcordMet tool catalogue must be 9 tools (W8 spec); "
                f"got {len(self.tool_specs)}"
            )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_task(
        self,
        task: dict[str, Any],
        *,
        trace_id: str | None = None,
        feedback_user_msg: str | None = None,
    ) -> ConcordReactResult:
        """Run one sub6b-v3 task end-to-end through the ConcordMet ReAct loop.

        D3 body: ReAct turn loop with the 9 ConcordMet tools, single
        inner finalise retry, task-level wall-time guard.
        D4 extension: optional `feedback_user_msg` is appended as an
        extra user-role message after the initial prompt, so feedback
        iterations (iter ≥ 1 in `run_task_with_feedback`) can seed the
        loop with verifier hints derived from the previous iteration's
        verdict. When None, behaves exactly as D3.
        """
        started = time.time()
        reset_call_cache()
        task_id = str(task.get("task_id") or "unknown")
        trace_id = trace_id or f"concord_w8_d3.{task_id}"

        safe = _strip_task_for_llm(task)
        metabolites = safe["differential_metabolites"]
        messages = build_concord_react_messages(metabolites)
        if feedback_user_msg:
            messages.append({"role": "user", "content": feedback_user_msg})

        chat_fn = self.chat_with_tools or _resolve_default_chat_fn()
        deadline = started + self.task_timeout_seconds

        tool_calls_trace: list[dict[str, Any]] = []
        enrichment_carriers: dict[str, Any] = {}
        n_turns = 0
        n_tool_calls = 0
        force_finalised = False
        inner_retry_used = False
        final_json_text = ""
        final_parsed: dict[str, Any] | None = None
        error: str | None = None
        termination_reason: str | None = None
        timed_out = False

        def _call_llm(*, tool_choice: str, caller: str) -> dict[str, Any]:
            return chat_fn(
                messages,
                tools=self.tool_specs,
                tool_choice=tool_choice,
                temperature=0.0,
                model=self.llm_model,
                provider=self.llm_provider,
                trace_id=trace_id,
                caller=caller,
            )

        while n_turns < self.max_react_turns:
            if time.time() > deadline:
                timed_out = True
                error = "task_timeout"
                termination_reason = "task_timeout"
                break

            n_turns += 1
            try:
                # Once max_react_turns is reached on the final allowed
                # turn, force the LLM into a final-message path by
                # nudging it with the force-finalise prompt and locking
                # tool_choice to "none".
                if n_turns == self.max_react_turns:
                    force_finalised = True
                    messages.append({"role": "user", "content": _FORCE_FINALISE_PROMPT})
                    msg = _call_llm(tool_choice="none", caller=f"concord_d3_finalise")
                else:
                    msg = _call_llm(tool_choice="auto", caller=f"concord_d3_turn{n_turns}")
            except Exception as exc:
                error = f"chat_error: {type(exc).__name__}: {exc}"
                termination_reason = "llm_error"
                logger.warning("ReAct turn %d failed for %s: %s", n_turns, trace_id, error)
                break

            echoed = _echo_assistant(msg)
            messages.append(echoed)
            tool_calls = msg.get("tool_calls") or []

            if tool_calls:
                # B1 ReAct convention: route every tool_call this turn,
                # append `tool` role messages, continue to next LLM turn.
                for tc in tool_calls:
                    n_tool_calls += 1
                    result = dispatch(tc)
                    _store_enrichment_carrier(enrichment_carriers, result.tool_name, result.payload)
                    tool_calls_trace.append({
                        "turn": n_turns,
                        "name": result.tool_name,
                        "tool_call_id": result.tool_call_id,
                        "arguments": _argument_str(tc),
                        "cached": result.from_cache,
                        "payload_summary": _payload_summary(result.payload),
                    })
                    messages.append(_tool_result_message(
                        tool_name=result.tool_name,
                        tool_call_id=result.tool_call_id,
                        payload=result.payload,
                        fallback_call_id=f"call_local_{n_tool_calls}",
                    ))
                continue

            # No tool_calls — the LLM is attempting the final grammar-v2
            # JSON. Try to extract + structurally validate it.
            content = (msg.get("content") or "").strip()
            json_str = _extract_json_object(content)
            parsed = None
            if json_str is not None:
                try:
                    parsed = json.loads(json_str)
                except json.JSONDecodeError:
                    parsed = None

            if parsed is not None:
                ok, why_bad = _validate_grammar_v2(parsed)
                if ok:
                    final_json_text = json_str
                    final_parsed = parsed
                    termination_reason = "normal_finalise" if not force_finalised else "force_finalised"
                    break
            else:
                why_bad = "could not extract a JSON object from the assistant message"

            # Invalid finalise — use the inner-retry budget (B1 D4 4a).
            if not inner_retry_used and self.inner_finalise_retries >= 1:
                inner_retry_used = True
                messages.append({
                    "role": "user",
                    "content": f"{_RETRY_NUDGE_PROMPT}\n\n(Validation said: {why_bad})",
                })
                continue
            error = f"invalid_final_json: {why_bad}"
            termination_reason = "invalid_final_json_after_retry"
            final_json_text = content  # keep raw for debug trace
            break

        elapsed = time.time() - started
        distinct_tools = sorted({t["name"] for t in tool_calls_trace})

        # Outcome classification — B1 D4 TaskOutcome enum semantics
        # (NORMAL / EMPTY_HONEST_REFUSAL / EMPTY_SYSTEM_FAILURE /
        # EMPTY_UNKNOWN). D3 distinguishes:
        #   parse_ok AND claims != []     → NORMAL
        #   parse_ok AND claims == []     → EMPTY_HONEST_REFUSAL
        #   parse_fail / chat_error / timeout → EMPTY_SYSTEM_FAILURE
        #   otherwise                     → EMPTY_UNKNOWN
        if final_parsed is not None:
            n_claims = len(final_parsed.get("claims") or [])
            task_outcome = "normal" if n_claims > 0 else "empty_honest_refusal"
            final_narrative_text = (final_parsed.get("narrative_text") or "").strip()
            final_claims = list(final_parsed.get("claims") or [])
            pathway_prediction = generate_pathway_prediction_second_pass(
                claims=final_claims,
                narrative_text=final_narrative_text,
                chat_fn=llm_client.chat,
                model=self.llm_model,
                provider=self.llm_provider,
                trace_id=f"{trace_id}.pathway_prediction" if trace_id else None,
            )
        elif timed_out or error:
            task_outcome = "empty_system_failure"
            final_narrative_text = ""
            final_claims = []
            pathway_prediction = dict(_ABSTAIN_SECOND_PASS_FAILED)
        else:
            task_outcome = "empty_unknown"
            final_narrative_text = ""
            final_claims = []
            pathway_prediction = dict(_ABSTAIN_SECOND_PASS_FAILED)

        iteration = ConcordIterationRecord(
            iter_idx=0,
            narrative_json=final_json_text,
            n_tool_calls=n_tool_calls,
            n_turns=n_turns,
            force_finalised=force_finalised,
            inner_retry_used=inner_retry_used,
        )

        return ConcordReactResult(
            task_id=task_id,
            iterations=[iteration],
            final_iter_idx=0,
            final_narrative_json=final_json_text,
            final_narrative_text=final_narrative_text,
            final_claims=final_claims,
            pathway_prediction=pathway_prediction,
            task_outcome=task_outcome,
            n_feedback_iterations=0,
            elapsed_seconds=elapsed,
            llm_model=self.llm_model,
            metabolite_count=len(metabolites),
            n_distinct_tools_called=len(distinct_tools),
            tools_called=distinct_tools,
            tool_calls_trace=tool_calls_trace,
            enrichment_carriers=enrichment_carriers,
            error=error,
            termination_reason=termination_reason,
        )

    # ------------------------------------------------------------------
    # B1 verifier feedback loop (D4)
    # ------------------------------------------------------------------

    def run_task_with_feedback(
        self,
        task: dict[str, Any],
        *,
        feedback_msg_builder: Callable[[Any], str] | None = None,
        trace_id: str | None = None,
    ) -> "ConcordFeedbackResult":
        """Run a task through iter 0 → ... → iter N with verifier feedback.

        Loop logic (B1 D4 Q6 quality rollback):
          - iter 0: `run_task(task)` → verify → quality_N0
          - if quality_N0 == 0 or max_feedback_iters == 0:
                return ConcordFeedbackResult(final=N0)
          - iter k (1 ≤ k ≤ max_feedback_iters):
                hint = feedback_msg_builder(verdict_{k-1})
                run_task(task, feedback_user_msg=hint) → verify → quality_Nk
          - Final selection vs N0:
                q(Nfinal) > q(N0) → rollback to N0; reason="feedback_made_it_worse"
                q(Nfinal) > q(N_{final-1}) → rollback to N_{final-1};
                                              reason="iter{N}_degraded"
                else → keep N_final, no rollback

        `feedback_msg_builder(verdict)` builds the user-role hint text
        from a verdict. Inject for tests; runtime default lifts B1's
        `build_feedback_message` from `evaluation.sub6.run_sub6b_react_feedback`
        (lazy-imported so import-time stays light).
        """
        task_id = str(task.get("task_id") or "unknown")
        trace_id = trace_id or f"concord_w8_d4.{task_id}"
        builder = feedback_msg_builder or _resolve_default_feedback_builder()

        iterations: list[tuple[ConcordReactResult, VerificationOutcome]] = []

        # iter 0
        r0 = self.run_task(task, trace_id=f"{trace_id}.iter0")
        iter0_is_final = self.max_feedback_iters == 0
        v0 = self.verify_with_b1(
            r0,
            task,
            trace_id=f"{trace_id}.iter0.verify",
            is_final_iteration=iter0_is_final,
        )
        iterations.append((r0, v0))

        if v0.quality == 0 or self.max_feedback_iters == 0:
            return _assemble_feedback_result(
                task_id=task_id,
                iterations=iterations,
                final_iter_idx=0,
                rollback_reason=None,
            )

        # iter 1..max_feedback_iters
        for k in range(1, self.max_feedback_iters + 1):
            if self.feedback_strategy == "cascade":
                rk, vk = self._run_cascade_iteration(
                    task,
                    prev_outcome=iterations[-1][1],
                    base_result=iterations[0][0],
                    trace_id=trace_id,
                    k=k,
                )
            else:
                # "rewrite" — legacy path: re-run full ReAct with a hint
                prev_verdict = iterations[-1][1].verdict
                try:
                    hint = builder(prev_verdict)
                except Exception as exc:
                    # If the feedback builder itself bombs, treat it as a
                    # halt — we cannot ask the LLM to revise without a hint.
                    logger.warning("feedback builder failed: %s", exc)
                    hint = (
                        "VERIFIER FEEDBACK: previous iteration had unsupported / "
                        "contradicted claims — please re-emit a stricter "
                        "narrative referring to pathways by their literal "
                        "namespace-prefixed names from the tool outputs."
                    )
                rk = self.run_task(
                    task, trace_id=f"{trace_id}.iter{k}", feedback_user_msg=hint,
                )
                vk = self.verify_with_b1(
                    rk,
                    task,
                    trace_id=f"{trace_id}.iter{k}.verify",
                    is_final_iteration=(k == self.max_feedback_iters),
                )
            iterations.append((rk, vk))

        # Final selection: prefer the latest if it monotonically beat both
        # the previous iteration AND iter 0. Otherwise rollback.
        last_idx = len(iterations) - 1
        q_last = iterations[last_idx][1].quality
        q_prev = iterations[last_idx - 1][1].quality
        q0 = iterations[0][1].quality

        if q_last > q0:
            final_iter_idx = 0
            rollback_reason = "feedback_made_it_worse"
        elif q_last > q_prev:
            final_iter_idx = last_idx - 1
            rollback_reason = f"iter{last_idx}_degraded"
        else:
            final_iter_idx = last_idx
            rollback_reason = None

        return _assemble_feedback_result(
            task_id=task_id,
            iterations=iterations,
            final_iter_idx=final_iter_idx,
            rollback_reason=rollback_reason,
        )

    # ------------------------------------------------------------------
    # B1 verifier integration (D4)
    # ------------------------------------------------------------------

    def verify_with_b1(
        self,
        react_result: ConcordReactResult,
        task: dict[str, Any],
        *,
        trace_id: str | None = None,
        is_final_iteration: bool = True,
    ) -> "VerificationOutcome":
        """Run the finalised narrative through B1 `verify_sub6()`.

        Always returns a VerificationOutcome — never raises. Failures
        (adapter / verifier) populate `outcome.error` so a feedback
        loop can decide whether to retry, rollback, or accept.

        `verifier_fn` MUST be injected on the runner (constructor arg)
        — when None, this method raises RuntimeError because D4
        callers explicitly opted into verification and a missing
        verifier is a wiring bug, not a runtime exception.
        """
        if self.verifier_fn is None:
            raise RuntimeError(
                "verifier_fn was not injected on ConcordReactRunner — "
                "call ConcordReactRunner(verifier_fn=verifier.agent.verify_sub6) "
                "or pass a test mock"
            )

        # Short-circuit on empty narrative — calling B1 verify_sub6 with
        # "" wastes 1-7 LLM calls on a known-empty input.
        from concord.agent.verifier_adapter import (
            concord_result_to_b1_narrative,
            concord_result_to_b1_structured_payload,
        )

        use_structured = os.environ.get("METAGENT_VERIFY_STRUCTURED_CLAIMS") == "1"
        narrative = (
            concord_result_to_b1_structured_payload(react_result, task)
            if use_structured
            else concord_result_to_b1_narrative(react_result, task)
        )
        if not narrative:
            return VerificationOutcome(
                ok=True, verdict=None, error=None,
                n_supported=0, n_unsupported=0, n_contradicted=0,
                n_unverifiable_v0=0, n_insufficient_evidence=0,
            )

        # Adapter step — surface adapter failures as outcome.error
        try:
            source_report = self._build_source_report(react_result, task)
        except Exception as exc:
            return VerificationOutcome(
                ok=False, verdict=None,
                error=f"source_report_adapter_failed: {type(exc).__name__}: {exc}",
            )

        tid = trace_id or f"concord_w8_d4.{react_result.task_id}.verify"
        return self._verify_payload(
            narrative,
            source_report,
            react_task_id=react_result.task_id,
            trace_id=tid,
            is_final_iteration=is_final_iteration,
        )

    def _build_source_report(
        self,
        react_result: ConcordReactResult,
        task: dict[str, Any],
    ) -> Any:
        """Build a SubsixSourceReport from a ConcordReactResult + task.

        Dispatches to the v4 adapter when the task has v4 shape, else the
        v3 adapter. Extracted from verify_with_b1 so the cascade path can
        reuse the iter-0 react result's enrichment carriers.

        Raises on adapter failure — callers must catch.
        """
        from concord.agent.verifier_adapter import (
            _is_v4_task,
            sub6b_task_to_subsix_source_report,
            v4_task_to_subsix_source_report,
        )
        if _is_v4_task(task):
            return v4_task_to_subsix_source_report(task, react_result)
        return sub6b_task_to_subsix_source_report({
            **task,
            **react_result.enrichment_carriers,
        })

    def _verify_payload(
        self,
        narrative: str,
        source_report: Any,
        *,
        react_task_id: str,
        trace_id: str,
        is_final_iteration: bool,
    ) -> "VerificationOutcome":
        """Run the B1 verifier on an already-built narrative + source_report.

        This is the shared tail of verify_with_b1 and _run_cascade_iteration:
        env save/restore, verifier_fn call, verdict-count extraction.

        Always returns a VerificationOutcome — never raises.
        """
        use_structured = os.environ.get("METAGENT_VERIFY_STRUCTURED_CLAIMS") == "1"
        # Run B1 verifier — surface its internal failures the same way
        old_method_flag = os.environ.get("METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT")
        old_provider = os.environ.get("METAGENT_LLM_PROVIDER")
        old_minimax_model = os.environ.get("METAGENT_MINIMAX_MODEL")
        old_openai_model = os.environ.get("METAGENT_OPENAI_MODEL")
        if use_structured:
            os.environ["METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT"] = "1"
        os.environ["METAGENT_LLM_PROVIDER"] = self.llm_provider
        if self.llm_provider == "minimax":
            os.environ["METAGENT_MINIMAX_MODEL"] = self.llm_model
        elif self.llm_provider == "openai":
            os.environ["METAGENT_OPENAI_MODEL"] = self.llm_model
        try:
            verdict = self.verifier_fn(
                narrative,
                source_report,
                trace_id=trace_id,
                is_final_iteration=is_final_iteration,
            )
        except Exception as exc:
            return VerificationOutcome(
                ok=False, verdict=None,
                error=f"verifier_raised: {type(exc).__name__}: {exc}",
            )
        finally:
            if use_structured:
                if old_method_flag is None:
                    os.environ.pop("METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT", None)
                else:
                    os.environ["METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT"] = old_method_flag
            if old_provider is None:
                os.environ.pop("METAGENT_LLM_PROVIDER", None)
            else:
                os.environ["METAGENT_LLM_PROVIDER"] = old_provider
            if old_minimax_model is None:
                os.environ.pop("METAGENT_MINIMAX_MODEL", None)
            else:
                os.environ["METAGENT_MINIMAX_MODEL"] = old_minimax_model
            if old_openai_model is None:
                os.environ.pop("METAGENT_OPENAI_MODEL", None)
            else:
                os.environ["METAGENT_OPENAI_MODEL"] = old_openai_model

        # Verdict-count extraction strategy (defensive — B1's
        # VerifiedIdentification has multiple aggregate shapes across
        # the cascade and across mocks):
        #   1. test mocks set `verdicts_total = {"supported": N, ...}`
        #   2. real B1 puts aggregates on `claim_metrics`
        #      (ClaimMetrics) with the fields
        #      supported_claims / unsupported_claims /
        #      contradicted_claims / unverifiable_claims
        #   3. when neither is populated, derive from `claims_v1` (each
        #      claim's `.verdict` is a `ClaimVerdict(str, Enum)`; in
        #      some Py builds `str(enum)` returns
        #      "ClaimVerdict.UNVERIFIABLE_V0" not the value, so read
        #      `.value` defensively)
        counts = {"supported": 0, "unsupported": 0,
                  "contradicted": 0, "unverifiable_v0": 0,
                  "insufficient_evidence": 0}
        vt = getattr(verdict, "verdicts_total", None)
        if isinstance(vt, dict) and vt:
            for k in counts:
                if k in vt:
                    counts[k] = int(vt[k] or 0)
        else:
            cm = getattr(verdict, "claim_metrics", None)
            if cm is not None and (
                getattr(cm, "supported_claims", None) is not None
                or getattr(cm, "total_claims", None) is not None
            ):
                counts["supported"] = int(getattr(cm, "supported_claims", 0) or 0)
                counts["unsupported"] = int(getattr(cm, "unsupported_claims", 0) or 0)
                counts["contradicted"] = int(getattr(cm, "contradicted_claims", 0) or 0)
                counts["unverifiable_v0"] = int(getattr(cm, "unverifiable_claims", 0) or 0)
                counts["insufficient_evidence"] = int(
                    getattr(cm, "insufficient_evidence_claims", 0) or 0
                )
            else:
                claims = list(getattr(verdict, "claims_v1", None) or [])
                for c in claims:
                    vobj = getattr(c, "verdict", None)
                    key = (
                        getattr(vobj, "value", None)
                        or (str(vobj) if vobj is not None else "")
                    ).lower()
                    if key in counts:
                        counts[key] += 1
        return VerificationOutcome(
            ok=True, verdict=verdict, error=None,
            n_supported=counts["supported"],
            n_unsupported=counts["unsupported"],
            n_contradicted=counts["contradicted"],
            n_unverifiable_v0=counts["unverifiable_v0"],
            n_insufficient_evidence=counts["insufficient_evidence"],
        )

    def _weave_llm_call(self, prompt: str) -> str:
        """Single-shot LLM call for the cascade narrative weave.

        Uses this runner's configured provider/model (so the weave matches
        the rest of the run) and NEVER raises — any LLM failure degrades to
        "" so the deterministic cascade claims still flow through. The
        narrative is cosmetic: verify_sub6 verifies the structured `claims`,
        not the prose.
        """
        old_provider = os.environ.get("METAGENT_LLM_PROVIDER")
        old_minimax_model = os.environ.get("METAGENT_MINIMAX_MODEL")
        old_openai_model = os.environ.get("METAGENT_OPENAI_MODEL")
        os.environ["METAGENT_LLM_PROVIDER"] = self.llm_provider
        if self.llm_provider == "minimax":
            os.environ["METAGENT_MINIMAX_MODEL"] = self.llm_model
        elif self.llm_provider == "openai":
            os.environ["METAGENT_OPENAI_MODEL"] = self.llm_model
        try:
            from common.llm_client import chat

            return chat(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=600,
                trace_id="concord.cascade.weave_narrative",
                caller="concord.react_runner._weave_llm_call",
            )
        except Exception as exc:  # noqa: BLE001 — weave is best-effort
            logger.warning("cascade weave LLM call failed, using empty narrative: %s", exc)
            return ""
        finally:
            if old_provider is None:
                os.environ.pop("METAGENT_LLM_PROVIDER", None)
            else:
                os.environ["METAGENT_LLM_PROVIDER"] = old_provider
            if old_minimax_model is None:
                os.environ.pop("METAGENT_MINIMAX_MODEL", None)
            else:
                os.environ["METAGENT_MINIMAX_MODEL"] = old_minimax_model
            if old_openai_model is None:
                os.environ.pop("METAGENT_OPENAI_MODEL", None)
            else:
                os.environ["METAGENT_OPENAI_MODEL"] = old_openai_model

    def _run_cascade_iteration(
        self,
        task: dict[str, Any],
        *,
        prev_outcome: "VerificationOutcome",
        base_result: ConcordReactResult,
        trace_id: str,
        k: int,
    ) -> "tuple[ConcordReactResult, VerificationOutcome]":
        """Run one cascade feedback iteration (no LLM ReAct re-run).

        Deterministically processes iter-0 verified claims by verdict
        (via apply_cascade), weaves a narrative once via LLM (single call,
        not a full ReAct loop), then re-verifies. Returns a synthetic
        ConcordReactResult carrying the corrected payload + a fresh
        VerificationOutcome.
        """
        from concord.agent.feedback_strategies import apply_feedback_strategy

        prev_verdict = prev_outcome.verdict
        prev_claims = list(getattr(prev_verdict, "claims_v2", None) or [])

        # Build source_report reusing iter-0 enrichment carriers.
        try:
            source_report = self._build_source_report(base_result, task)
        except Exception as exc:
            # If the adapter fails, surface gracefully as an error outcome
            # so the quality rollback logic can fall back to iter-0.
            err_outcome = VerificationOutcome(
                ok=False, verdict=None,
                error=f"cascade_source_report_failed: {type(exc).__name__}: {exc}",
            )
            err_result = ConcordReactResult(
                task_id=base_result.task_id,
                enrichment_carriers=getattr(base_result, "enrichment_carriers", {}) or {},
                task_outcome=getattr(base_result, "task_outcome", "normal"),
                n_feedback_iterations=k,
                llm_model=self.llm_model,
                termination_reason="cascade_source_report_error",
            )
            return err_result, err_outcome

        # Run cascade: deterministic claim filter + LLM narrative weave.
        # Route the weave through the runner's own LLM client so it honours
        # this runner's provider/model (the 112-task experiment relied on
        # METAGENT_LLM_PROVIDER=minimax in env; this makes it explicit). The
        # weave produces only the cosmetic narrative_text — verify_sub6 reads
        # the deterministic `claims`, not the prose — so `_weave_llm_call`
        # degrades to "" on any LLM failure rather than crashing the loop.
        fb = apply_feedback_strategy(
            "cascade", prev_claims, source_report, llm_call=self._weave_llm_call,
        )
        payload = fb.payload or ""

        # Extract narrative_text for the trace.
        narr = ""
        if payload:
            try:
                narr = json.loads(payload).get("narrative_text", "")
            except (json.JSONDecodeError, AttributeError):
                narr = ""

        # Re-verify the cascade payload directly (no grammar extraction step —
        # the payload IS already a grammar-v2 JSON string).
        vk = self._verify_payload(
            payload,
            source_report,
            react_task_id=str(task.get("task_id") or "unknown"),
            trace_id=f"{trace_id}.iter{k}.verify",
            is_final_iteration=(k == self.max_feedback_iters),
        )

        # Build a synthetic ConcordReactResult for trace / audit purposes.
        rk = ConcordReactResult(
            task_id=base_result.task_id,
            final_claims=fb.corrected_claims or [],
            final_narrative_text=narr,
            final_narrative_json=payload,
            enrichment_carriers=getattr(base_result, "enrichment_carriers", {}) or {},
            task_outcome=getattr(base_result, "task_outcome", "normal"),
            n_feedback_iterations=k,
            llm_model=self.llm_model,
            termination_reason="cascade_feedback",
        )
        return rk, vk

    # ------------------------------------------------------------------
    # Inspection helpers — useful for tests and D1 sanity probes
    # ------------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """Return a small dict summarising the runner config + registry."""
        return {
            "llm_model": self.llm_model,
            "llm_provider": self.llm_provider,
            "max_react_turns": self.max_react_turns,
            "max_feedback_iters": self.max_feedback_iters,
            "inner_finalise_retries": self.inner_finalise_retries,
            "task_timeout_seconds": self.task_timeout_seconds,
            "n_tools": len(self.tool_specs),
            "tool_names": list(self.tool_names),
            "has_chat_client": self.chat_with_tools is not None,
            "has_verifier": self.verifier_fn is not None,
        }


# ---------------------------------------------------------------------------
# Default LLM client resolver — lazy so import-time stays light + tests
# that inject `chat_with_tools=` never touch the real client.
# ---------------------------------------------------------------------------


def _resolve_default_chat_fn() -> ChatWithToolsFn:
    from common.llm_client import chat_with_tools as _real

    return _real


def _resolve_default_feedback_builder() -> Callable[[Any], str]:
    """Lazy-loaded default: B1's `build_feedback_message` with claim
    annotation via `verifier.feedback_hints`.

    Returns a single-arg fn (verdict → str) so the
    `run_task_with_feedback` interface is the same whether the caller
    injects a mock or accepts the B1 default.
    """
    def _builder(verdict: Any) -> str:
        from evaluation.sub6.run_sub6b_react_feedback import build_feedback_message
        from verifier.feedback_hints import annotate_claims
        from verifier.schemas import ClaimVerdict

        # ``getattr(verdict, ..., None) or []`` is intentional defensive
        # plumbing. ``verdict`` is typed ``Any`` because the runner
        # accepts both the real ``VerifiedIdentification`` (which always
        # has ``claims_v1`` populated) AND a ``SimpleNamespace`` mock used
        # by feedback-builder unit tests (which may omit the attribute or
        # set it to None). The ``or []`` covers the "attribute exists but
        # is None" case that getattr's default-arg form does not.
        claims = list(getattr(verdict, "claims_v1", None) or [])
        # Populate `feedback_hint` per claim using B1's drop-reason +
        # contradicted / unsupported templates. `verify_sub6()` (unlike
        # the spectrum `verify()`) does NOT call annotate_claims
        # internally — we own this step at the feedback boundary.
        annotated = annotate_claims(claims, pass_id="v1")
        # W10 D2.5: all four verdict filters use enum equality. The
        # earlier str(c.verdict).lower() == X.value pattern silently
        # returned empty list on Python 3.11+ because str(Enum) now
        # produces "ClassName.MEMBER" rather than the raw value.
        contradicted = [c for c in annotated if c.verdict == ClaimVerdict.CONTRADICTED]
        unsupported = [c for c in annotated if c.verdict == ClaimVerdict.UNSUPPORTED]
        # W10 D2 P0-B: forward UV claims + grammar-dropped claims so D4's
        # richer feedback template (n_unverifiable / unverifiable_block /
        # n_dropped_by_grammar / dropped_block) surfaces full diagnostics
        # to iter ≥ 1. Both kwargs default to None on the B1 side; passing
        # actual lists keeps the contract symmetric across all 4 categories.
        unverifiable = [c for c in annotated if c.verdict == ClaimVerdict.UNVERIFIABLE_V0]
        dropped = list(getattr(verdict, "dropped_claims", None) or [])
        # Source narrative is not strictly required by B1's template, but
        # passing it gives the LLM context for the re-write. We don't have
        # it cleanly available here without threading; pass empty.
        return build_feedback_message(
            contradicted=contradicted,
            unsupported=unsupported,
            unverifiable=unverifiable,
            dropped=dropped,
            original_narrative="",
        )
    return _builder


@dataclass
class ConcordFeedbackResult:
    """Output of a `run_task_with_feedback` call.

    Carries every iteration's react result + verification outcome so D4
    audit / D5 quad-report can read the trajectory and rollback
    decision. `iterations[final_iter_idx]` is the chosen narrative.
    """

    task_id: str
    iterations: list["FeedbackIterationRecord"]
    final_iter_idx: int
    n_feedback_iterations: int
    rollback_reason: str | None
    final_react_result: ConcordReactResult
    final_verdict: "VerificationOutcome"


@dataclass
class FeedbackIterationRecord:
    """Per-iteration snapshot inside ConcordFeedbackResult.

    `quality` is the B1 D4 definition (n_contradicted + n_unsupported);
    lower is better; 0 means the iteration's claims were fully grounded.
    """

    iter_idx: int
    react_result: ConcordReactResult
    verification: "VerificationOutcome"

    @property
    def quality(self) -> int:
        return self.verification.quality


def _assemble_feedback_result(
    *,
    task_id: str,
    iterations: list[tuple[ConcordReactResult, "VerificationOutcome"]],
    final_iter_idx: int,
    rollback_reason: str | None,
) -> ConcordFeedbackResult:
    """Build a ConcordFeedbackResult from a list of (react_result, outcome) pairs."""
    iter_records = [
        FeedbackIterationRecord(iter_idx=i, react_result=r, verification=v)
        for i, (r, v) in enumerate(iterations)
    ]
    final_r, final_v = iterations[final_iter_idx]
    return ConcordFeedbackResult(
        task_id=task_id,
        iterations=iter_records,
        final_iter_idx=final_iter_idx,
        n_feedback_iterations=len(iter_records) - 1,
        rollback_reason=rollback_reason,
        final_react_result=final_r,
        final_verdict=final_v,
    )


def _payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Trim a dispatcher payload to the keys the trace log needs.

    The full PA result can be 20-50 KB; the smoke trace only needs the
    envelope shape + counts to audit a turn. Result body itself stays in
    the message history for the next LLM turn — this is only the trace
    record kept on the result object.
    """
    keep_keys = {
        "ok", "error", "fallback_suggested", "_tool_name",
        "_n_pathways", "_n_compound_refs", "_n_members",
        "_n_input_refs", "_n_results", "_cached",
    }
    out = {k: v for k, v in payload.items() if k in keep_keys}
    # When ok=True, include a 5-pathway peek of pathway_id + score + rank
    # for at-a-glance smoke inspection. Skip when the result is not a
    # PA-style envelope.
    if payload.get("ok") and isinstance(payload.get("result"), dict):
        pathways = (payload["result"].get("pathways") or [])[:5]
        if pathways:
            out["_pathway_peek"] = [
                {
                    "pathway_id": p.get("pathway_id"),
                    "pathway_name": p.get("pathway_name"),
                    "score": p.get("score"),
                    "rank": p.get("rank"),
                }
                for p in pathways
            ]
    return out


def _store_enrichment_carrier(
    carriers: dict[str, Any],
    tool_name: str,
    payload: dict[str, Any],
) -> None:
    if not payload.get("ok") or not isinstance(payload.get("result"), dict):
        return
    result = payload["result"]
    if tool_name == "run_ramp_enrichment":
        carriers["ramp_enrichment_result"] = result
    elif tool_name == "run_mummichog":
        carriers["mummichog_enrichment_result"] = result
    elif tool_name == "run_metaboanalystr_psea":
        carriers.setdefault("metaboanalystr_enrichment_result", {})["psea"] = result
    elif tool_name == "run_sspa_ora":
        carriers["sspa_enrichment_result"] = result
    elif tool_name == "run_fella_rwr":
        carriers.setdefault("fella_enrichment_result", {})["rwr"] = result
