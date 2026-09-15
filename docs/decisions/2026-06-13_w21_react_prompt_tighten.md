# W21 React Prompt Tighten Decision

Date: 2026-06-13
Status: **INVALID EXPERIMENT — DETECTION BUG**

## Decision Context

After W19 and W20 showed diminishing returns from verifier-side additions, W21 tested a source-side intervention: change the ReAct prompt so that directly supported facts are separated from biological hypotheses.

The intended evaluation framework was deliberately anti-gaming:

- VERIFIED rate is the primary success metric.
- UNVERIFIABLE rate should decrease.
- HYPOTHESIS rate should remain reasonable and pass manual sampling if present.
- Hypothesis claims stay in the same denominator; no claim is removed from accounting.

## Implementation

Implemented W21 mechanics:

- Added `ClaimVerdict.HYPOTHESIS`.
- Counted hypothesis claims as their own bucket.
- Routed deterministic hypothesis markers in verifier logic.
- Exposed `n_hypothesis` through Concord / Path-X metrics.
- Added prompt discipline text to the ReAct prompt.
- Added W21 paired pilot wrapper with explicit prompt path.
- Added per-task timeout preservation in the W21 pilot wrapper.

Guardrails kept:

- B1-core helpers untouched.
- W17 schema untouched.
- `DEFAULT_MAX_FEEDBACK_ITERS=1` untouched.
- `concord/agent/*.py` untouched by the timeout wrapper change.

## Connectivity Finding

MiniMax M2 and M2.7 both returned normal chat responses and OpenAI-style tool calls. Both may include `<think>` in `content`, but the shared client already strips thinking for `chat` and `chat_with_tools`.

The original 5 minute 1-task smoke failure was a wall-time issue, not a model protocol issue. With a 15 minute timeout the same task completed in about 9 minutes.

## Pilot Result

Source: `data/metagent/w21_pilot_5task_paired/three_class_metrics_pilot.json`

The table below is retained as a run artifact, but it is **not an efficacy verdict**. Real V_b outputs show that `Hypothesis:` markers can appear in narrative text, while the extracted verifier claims contain no marker. The HYPOTHESIS bucket therefore reads 0 because the signal was lost before detection.

| Metric | V_a baseline | V_b labelled | Delta |
|---|---:|---:|---:|
| Valid tasks | 5/5 | 5/5 | 0 |
| VERIFIED rate | 47.76% | 38.06% | -9.70pp |
| UNVERIFIABLE rate | 25.37% | 39.55% | +14.18pp |
| HYPOTHESIS rate | 0.00% | 0.00% | 0.00pp |

The pilot cannot be scored against the W21 gate:

- VERIFIED and UNVERIFIABLE deltas are contaminated by the detector bug.
- HYPOTHESIS did not appear in final bucket metrics because extracted `claim_text` did not preserve the marker.
- The result does not validate or falsify the prompt strategy.

## Extraction-path Finding

Real V_b task dumps show the break in the transport path:

- `Hypothesis:` appears in narrative prose for 2/5 pilot tasks.
- `final_claims` contains no `Hypothesis:` prefix and no `hypothesis` / epistemic-status field in any of the 5 pilot tasks.
- `verifier/agent.py` detects hypotheses after extraction by checking `claim.claim_text`, so the detector has no access to the prose-only marker.

The structured claim schema does have an extensible `ClaimExtractedFields` container, but the current grammar extraction path only threads selected fields such as pathway / term names into it. It does not preserve arbitrary per-claim metadata from the raw claim object. Therefore a repair must either route epistemic status through an already preserved channel, add an explicit non-B1-core transport step, or seek explicit approval for a narrow extractor-adjacent change.

## Decision

Do not proceed to W21 D3 full-59.

Treat the current pilot as **invalid** until the real-output extraction path is fixed and retested. Keep the run data; do not delete or reinterpret it as a prompt failure.

## Follow-up

Recommended W22 checks:

- Validate any detector fix on real ReAct outputs, not synthetic samples.
- Determine whether epistemic status can travel through an existing structured per-claim field.
- If structured transport is impossible without schema churn, compare safer non-B1-core options before changing verifier logic.
- Add prompt-contract tests only after at least one real-output detector check passes.
- Reuse per-task timeout preservation for all future long-running paired pilots.
