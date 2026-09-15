"""W14.B D2 RED — ConcordReactRunner max_feedback_iters default cap (3 cases).

Pins the W14.B contract: `DEFAULT_MAX_FEEDBACK_ITERS` in
`concord/agent/react_runner.py` flips from 2 to 1. Backward compat
preserved: explicit `max_feedback_iters=2` still works.

Justification per W13.C diagnostic (commit 24975d3):
  - H3_CONFIRMED on N=14 iter-2-degraded tasks: 14/14 unsupported
    dominant. Σ Δ unsupported +48, Σ Δ contradicted −4, Σ Δ supported
    −9 across the 14 tasks (iter-1 → iter-2). iter-2 confirmed
    net-destructive on this slice.
  - W13.A already reduced iter-2 deg rate 22.22 % → 15.87 % as side-
    effect of extended ID patterns. Capping iter-2 at the dispatcher
    level closes the remaining overshoot path.

Expected at RED:
  - case 1 (default = 1)              FAIL (DEFAULT_MAX_FEEDBACK_ITERS = 2)
  - case 2 (iter-2 not triggered)     FAIL (default still allows iter 2)
  - case 3 (explicit =2 still works)  PASS (regression baseline; spec
                                       §3 stop-condition #2 acknowledges
                                       this PASS at RED is acceptable)
"""
from __future__ import annotations


def test_react_runner_default_max_feedback_iters_is_one():
    """Case 1 — DEFAULT_MAX_FEEDBACK_ITERS module-level constant equals 1.

    Expected at RED: FAIL (currently 2 at line 50 of react_runner.py).
    """
    from concord.agent.react_runner import DEFAULT_MAX_FEEDBACK_ITERS

    assert DEFAULT_MAX_FEEDBACK_ITERS == 1, (
        f"W14.B requires DEFAULT_MAX_FEEDBACK_ITERS=1 (was 2); "
        f"current value: {DEFAULT_MAX_FEEDBACK_ITERS}"
    )


def test_iter_2_not_triggered_under_default_cap():
    """Case 2 — A ConcordReactRunner constructed without explicit
    max_feedback_iters uses the new default (= 1). The dataclass
    field's default value matches the module-level constant.

    Expected at RED: FAIL.
    """
    from concord.agent.react_runner import ConcordReactRunner

    # Inspect the dataclass field default — no need to spin up an
    # actual runner (which would require chat_with_tools + verifier_fn).
    fields = ConcordReactRunner.__dataclass_fields__
    assert "max_feedback_iters" in fields, (
        "ConcordReactRunner must expose max_feedback_iters as a dataclass field"
    )
    default = fields["max_feedback_iters"].default
    assert default == 1, (
        f"W14.B requires ConcordReactRunner.max_feedback_iters default = 1; "
        f"current value: {default}"
    )


def test_explicit_max_feedback_iters_2_still_supported():
    """Case 3 (regression / backward compat) — explicit
    `max_feedback_iters=2` is still accepted by the constructor and
    passes the `[0, 2]` validation gate. W10 / W13 reproducibility
    relies on this.

    Expected at RED: PASS (backward-compat path already works; W14.B
    only changes the default, not the validation range).
    """
    from concord.agent.react_runner import ConcordReactRunner

    # Construct with a minimal stub for required positional args so the
    # __post_init__ validation runs and accepts the explicit value.
    # chat_with_tools and verifier_fn can be lambdas — we never call them.
    runner = ConcordReactRunner(
        chat_with_tools=lambda *args, **kwargs: {},
        verifier_fn=lambda *args, **kwargs: None,
        max_feedback_iters=2,
    )

    assert runner.max_feedback_iters == 2, (
        f"Explicit max_feedback_iters=2 must survive __post_init__; "
        f"got runner.max_feedback_iters={runner.max_feedback_iters!r}"
    )
