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
DEFAULT_MAX_FEEDBACK_ITERS = 2

# Inner-retry budget when finalise produces empty / unparseable output.
# Mirrors B1 D4 component 4a.
DEFAULT_INNER_FINALISE_RETRIES = 1

# Per-task wall-time ceiling, mirrors B1 D4 component 4c. Higher than
# B1 (1200 vs 900) because ConcordMet has more potentially-slow tools
# (mummichog + MetaboAnalystR + FELLA all Docker-bound).
DEFAULT_TASK_TIMEOUT_SECONDS = 1200.0

# Defaults for the LLM provider — sub6b v3 baseline. The user-side W7
# OQ-9 noted that only `MINIMAX_API_KEY` is configured locally; if a
# smoke run fails on MiniMax, the caller can swap `chat_with_tools` /
# `llm_model` / `provider` for the GPT-4o fallback path.
DEFAULT_LLM_MODEL = "MiniMax-M2.7"
DEFAULT_LLM_PROVIDER = "minimax"

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
    final_verdict_total: dict[str, int] = field(default_factory=dict)
    task_outcome: str = "normal"  # B1 D4 TaskOutcome enum, str form
    n_feedback_iterations: int = 0
    elapsed_seconds: float = 0.0
    llm_model: str = ""
    metabolite_count: int = 0
    n_distinct_tools_called: int = 0
    tools_called: list[str] = field(default_factory=list)
    tool_calls_trace: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    rollback_reason: str | None = None
    termination_reason: str | None = None


# Verifier injection: a callable that takes the finalised grammar-v2
# JSON narrative + the task row and returns a B1 VerdictReport-equivalent
# dict. D4 wires the real adapter; D3 leaves it Optional.
VerifierFn = Callable[[str, dict[str, Any]], dict[str, Any]]

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
    ) -> ConcordReactResult:
        """Run one sub6b-v3 task end-to-end through the ConcordMet ReAct loop.

        D3 body: ReAct turn loop with the 9 ConcordMet tools, single
        inner finalise retry, task-level wall-time guard. D4 will wrap
        this loop in the verifier feedback path; for now `iterations`
        contains exactly one record (iter_idx=0).
        """
        started = time.time()
        reset_call_cache()
        task_id = str(task.get("task_id") or "unknown")
        trace_id = trace_id or f"concord_w8_d3.{task_id}"

        safe = _strip_task_for_llm(task)
        metabolites = safe["differential_metabolites"]
        messages = build_concord_react_messages(metabolites)

        chat_fn = self.chat_with_tools or _resolve_default_chat_fn()
        deadline = started + self.task_timeout_seconds

        tool_calls_trace: list[dict[str, Any]] = []
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
        elif timed_out or error:
            task_outcome = "empty_system_failure"
            final_narrative_text = ""
            final_claims = []
        else:
            task_outcome = "empty_unknown"
            final_narrative_text = ""
            final_claims = []

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
            task_outcome=task_outcome,
            n_feedback_iterations=0,
            elapsed_seconds=elapsed,
            llm_model=self.llm_model,
            metabolite_count=len(metabolites),
            n_distinct_tools_called=len(distinct_tools),
            tools_called=distinct_tools,
            tool_calls_trace=tool_calls_trace,
            error=error,
            termination_reason=termination_reason,
        )

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
