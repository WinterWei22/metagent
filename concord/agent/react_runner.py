"""ConcordMet ReAct + closed-loop verifier runner (W8 D1 skeleton).

Mirrors the contract of `evaluation/sub6/run_sub6b_react_feedback.py`
but for the ConcordMet 9-tool catalogue. D1 fixes the public surface
(class name, init signature, run_task signature, default constants,
result dataclass shapes) so D2/D3/D4 fill the body without churning the
interface.

D1 deliberately does NOT execute a real LLM loop. `run_task()` raises
`NotImplementedError("D3 wires the body")` so tests that construct the
runner and probe its registry pass without the LLM client being live.
The intent is to keep import-time + init-time clean and to surface any
import / wiring breakage early.

Body wiring plan:
  D2:  PA wrappers in `concord/agent/tool_dispatcher.HANDLERS`.
  D3:  ReAct loop body — replaces the NotImplementedError below;
       smoke 2 task end-to-end (steroid + WP167 lipid smoking gun).
  D4:  Closed-loop verifier — adds `verifier_fn` injection so the
       finalised grammar-v2 JSON is fed to `verifier.agent.verify()`
       via `concord.agent.verifier_adapter`. Feedback iteration logic
       lifted from B1's `run_sub6b_react_feedback`.
"""
from __future__ import annotations

import logging
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
    final_verdict_total: dict[str, int] = field(default_factory=dict)
    task_outcome: str = "normal"  # B1 D4 TaskOutcome enum, str form
    n_feedback_iterations: int = 0
    elapsed_seconds: float = 0.0
    llm_model: str = ""
    metabolite_count: int = 0
    n_distinct_tools_called: int = 0
    tools_called: list[str] = field(default_factory=list)
    error: str | None = None
    rollback_reason: str | None = None
    termination_reason: str | None = None


# Verifier injection: a callable that takes the finalised grammar-v2
# JSON narrative + the task row and returns a B1 VerdictReport-equivalent
# dict. D4 wires the real adapter; D1 leaves it Optional so the
# signature is fixed.
VerifierFn = Callable[[str, dict[str, Any]], dict[str, Any]]

# LLM client injection: a callable matching the OpenAI-compatible
# chat-with-tools shape. D3 wires this against `common.llm_client`.
ChatWithToolsFn = Callable[..., dict[str, Any]]


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
    llm_model: str = "minimax-m2.7"
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

    def run_task(self, task: dict[str, Any]) -> ConcordReactResult:
        """Run one sub6b-v3 task end-to-end through the ConcordMet loop.

        D1 skeleton: builds the initial messages so the message-shape
        and metabolite-block plumbing are exercised, then raises
        NotImplementedError. D3 replaces the body with the real ReAct
        loop; D4 wires verifier_fn for the feedback layer.
        """
        started = time.time()
        reset_call_cache()
        metabolites = task.get("differential_metabolites") or []
        _ = build_concord_react_messages(metabolites)  # exercise plumbing
        elapsed = time.time() - started
        raise NotImplementedError(
            "ConcordReactRunner.run_task: D1 skeleton only. "
            "D3 wires the ReAct loop body; D4 wires the verifier feedback "
            "loop. (Initial-message build succeeded in "
            f"{elapsed:.3f}s with {len(metabolites)} metabolites and "
            f"{len(self.tool_specs)} registered tools.)"
        )

    # ------------------------------------------------------------------
    # Inspection helpers — useful for tests and D1 sanity probes
    # ------------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """Return a small dict summarising the runner config + registry."""
        return {
            "llm_model": self.llm_model,
            "max_react_turns": self.max_react_turns,
            "max_feedback_iters": self.max_feedback_iters,
            "inner_finalise_retries": self.inner_finalise_retries,
            "task_timeout_seconds": self.task_timeout_seconds,
            "n_tools": len(self.tool_specs),
            "tool_names": list(self.tool_names),
            "has_chat_client": self.chat_with_tools is not None,
            "has_verifier": self.verifier_fn is not None,
        }
