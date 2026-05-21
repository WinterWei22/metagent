# Phase B1 — Follow-up debt

**Date:** 2026-05-16 (end of B1 D6 wrap-up)
**Branch:** `feature/agent-phase-b1` (HEAD = `0ec15c4`)
**Purpose:** record known issues, partial implementations, and
defer-to-later concerns that B1 D5/D6 surfaced. Each item links to
the report or commit that discovered it.

Use this file as the starting point for Phase B2 / B3 / A4 scoping.

---

## P0 — should fix before next phase

### 1. `grammar` field passthrough is broken in production — **[RESOLVED 2026-05-20, commit `ed6243b`]**

> Closed by Stage D commit `ed6243b` ("fix(verifier): grammar field
> passthrough to VerifiedClaim"). The fix added the `grammar` field on
> `VerifiedClaim` (`verifier/schemas.py:704`) and a private helper
> `_stamp_grammar_from_classified` (`verifier/agent.py:372`) wired into
> the dispatcher; regression test landed in
> `tests/test_d4_feedback_dispatcher.py:558`.

**Where:** all 189 D5 v2 runs.
**Discovered in:** `phase_b1_d5_eval.md` per-grammar breakdown step
(2026-05-16). Re-verifying a NORMAL task's `VerifiedClaim` instances
showed `grammar = None` for every claim, even though the source
`ExtractedClaim.grammar` field was added in D3 commit `01a858b` and
passed through `ClassifiedClaim → VerifiedClaim` per design.

**Symptom:** `VerifiedClaim.grammar` is None even when the upstream
extractor (`extract_claims_from_json` in `verifier/claim_extractor.py`)
explicitly set `ExtractedClaim.grammar = ClaimGrammar(grammar_str)`.

**Likely root cause:** either
- `claim_classifier.classify_claims` is not copying `extracted.grammar`
  onto `ClassifiedClaim` (line 297 in classifier creates ClassifiedClaim
  with `grammar=c.grammar` per D3 commit, but maybe the field isn't
  surviving the pydantic build), OR
- Sub-6 dispatcher's per-layer verifier (e.g.
  `verify_biological_sub6` in `verifier/layers/biological_sub6.py`)
  is constructing `VerifiedClaim` from scratch without copying
  `classified.grammar`.

**Impact:** the deprecation-warning helper
`_maybe_warn_v1_legacy_in_v2_path` (D4 C2, agent.py) reads
`c.grammar` to decide whether to warn. Since grammar is None for
everything, the helper has been silently no-op for the entire D5 run
— **0 deprecation warnings is mis-reported as "v2 routing is clean"
when actually the helper can't observe v2-ness at all.**

**Fix scope:** trace the grammar field through ClassifiedClaim
construction in classify_claims, then through each Sub-6 layer's
VerifiedClaim construction. Likely one or two missing `grammar=c.grammar`
kwargs in the layer files. Add a regression test that asserts
`VerifiedClaim.grammar is not None` after `verify_sub6` on a v2-JSON
narrative.

**Priority:** P0 — it's a silent observability bug that hides D3/D4
correctness regressions. Could land in B2 first commit.

**Status:** **CLOSED** by commit `ed6243b` (Stage D, 2026-05-20). All
post-merge `verify_sub6` runs now carry `VerifiedClaim.grammar` through
classifier → dispatcher → metric aggregator. Deprecation-warning
telemetry is honest again.

---

### 2. D5 report §1's original "−17.5 pp regression" is partially wrong

**Where:** `phase_b1_d5_eval.md` §1 / §3 / §6 (now updated 2026-05-16
with Step Q / R corrections, but the original framing was misleading
for ~24 h).

**Discovered in:** `phase_b1_d6_step_q.md` apples-to-apples
re-analysis.

**Symptom:** D5 §1 reported "B1 D5 v2 top1 = 46.03 ± 25.86, A3 =
63.49, Δ = −17.5 pp regression". After Step Q correction the real
number under NORMAL-UNION apples-to-apples is **Δ = −0.53 pp** (no
regression).

**Fix:** report has been updated with Step Q section + revised §3
verdict table. Anyone reading the file should now see the Step Q
correction inline. **The phrase "B1 regressed pathway-correctness"
should be carefully scoped in any paper / talk derived from this
report** — it's true only under the A3-strict extractor on the full
denominator including EMPTY tasks.

**Priority:** documentation hygiene; no code action.

---

## P1 — should consider before D5-style rerun

### 3. Aggregator `aggregate_verifier.py` doesn't read `task_outcome` if absent

**Where:** `scripts/eval_sub6/aggregate_verifier.py:103` defaults
missing `task_outcome` to `"normal"`. Legacy v1 verdict files don't
have this field. **Good**: replay safe.

**But:** any old verdict-file with non-NORMAL outcome would silently
be counted as normal, polluting the NORMAL-only ratios. This is fine
for B1 forward-only verdicts but worth a note when re-aggregating
A3-era data.

**Priority:** P1 — only relevant if someone re-aggregates pre-B1 data.

### 4. v1 legacy classifier LLM call is preserved for ablation but never used in D5/D6

**Where:** `verifier/claim_classifier.py:_legacy_classify` and the
LLM prompt in `verifier/prompts/classify_ambiguous.py`.

D3 brief said "keep legacy LLM classifier for D5/D6 ablation". D5 +
D6 ran 7 experiments and none used the legacy path. The code is dead
weight on the v2 path (the v2 router short-circuits before reaching
it).

**Fix scope:** decide whether to (a) delete `_legacy_classify` +
`classify_ambiguous` prompt + tests, (b) gate it behind an explicit
ablation flag, or (c) leave dormant. (a) is cleaner; (b) preserves
optionality at the cost of branch noise.

**Priority:** P1 — clean-up before paper code release.

### 5. v2 grammar's `pathway_membership` and `metabolite_pathway_link` both route to `BIOLOGICAL`

**Where:** `_V2_GRAMMAR_TO_LEGACY_ROUTE` in
`verifier/claim_classifier.py`. Both grammar shapes collapse to one
`ClaimType.BIOLOGICAL`. Per-grammar breakdown in
`claim_distribution_by_grammar.json` therefore can't distinguish them
from the verdict side.

**Symptom:** the per-grammar breakdown table in D5 §1 lumps them as
"biological_claim (membership + link)". Paper might want to report
them separately (e.g. to show that `metabolite_pathway_link` with
strict enzyme requirement is harder to pass than bare membership).

**Fix scope:** either (a) add a sub-route on Layer 6c that distinguishes
membership vs link by checking `enzyme_or_reaction` field presence on
the source ExtractedClaim, OR (b) just bypass the issue by reading
`ExtractedClaim.grammar` (which has the right value) in the metric
aggregator. (b) is cleaner once issue #1 (grammar passthrough bug) is
fixed.

**Priority:** P1 — paper writing might want this.

---

## P2 — observed but acceptable as-is

### 6. RaMP eager-init noise on worker spawn

**Where:** `tools/agent_tools/query_ramp_enrichment.py` (or similar
RaMP entry point).
**Symptom:** every ThreadPoolExecutor worker prints
`query_ramp_enrichment: EnrichmentError: RaMP DB path not provided
and $RAMP_DB_PATH unset / invalid` at import time, before the
per-task `ramp_db_path=RAMP` kwarg is honored. Cosmetic; actual
queries succeed.

**Priority:** P2 — lazy-init the RaMP module so the warning doesn't
fire until first actual query.

### 7. MiniMax 15 % JSON-mode EMPTY rate

**Where:** MiniMax M2.7 + `response_format={"type":"json_object"}` +
tool_choice="none" finalise turns.

**Symptom:** ~15 % of finalise turns return empty `content` even
after one inner retry. Documented in D5 §2 and §6 noise-floor
analysis.

**Priority:** P2 — this is a model-side characteristic, not a B1 code
bug. Phase A4 should test if Opus 4.7 / GPT 5.5 close this gap.

### 8. `consistency_claim` is 0.1 % of claims and only ever contradicted

**Where:** Layer D in `verifier/layers/consistency.py`.
**Symptom:** in 1353 D5 v2 NORMAL claims, only 2 were consistency_claim, both contradicted. Layer D is effectively dead under v2 grammar.

**Priority:** P2 — Layer D was useful in v1 free-text mode for cross-claim consistency. Under v2 grammar, schema validation catches most cross-claim issues at extract time. Consider gating Layer D behind an env var or deleting after a final v1-compat check.

---

## P3 — paper-time discussion items, no code

### 9. Per-layer `supported %` is more honest than aggregate

**Source:** Step R + per-grammar breakdown.
**Suggestion:** any future paper or report should NOT report a single
`supported %` headline. Instead report per-layer rates:

| layer | claims | supported % |
|---|---:|---:|
| 6c biological | 1088 (80 %) | 99 % |
| 6a set_enrichment | 104 (8 %) | 99 % |
| 6b driver_metabolite | 159 (12 %) | 62 % |

The aggregate 94 % is a weighted average dominated by tautological
Layer 6c.

### 10. `top1_pathway_strict` over EMPTY tasks is meaningless

**Source:** Step Q.
**Suggestion:** any future top-1 metric should explicitly bucket EMPTY-task runs separately rather than count them as wrong. Step Q's NORMAL-UNION metric is the right denominator. The "overall" metric (counting EMPTY as wrong) buries the model-side robustness story.

### 11. v3 benchmark's `large` task bucket (n_metab ≥ 20) is empty

**Source:** pilot 10-task selection.
**Symptom:** v3 max n_metab = 13. The original pilot brief asked for
2 tasks with n_metab ≥ 20 — substituted with 2 highest-available
(n=12).

**Priority:** P3 — v4 benchmark should include n_metab > 20 tasks if
the paper wants to claim coverage across input-size ranges.

---

## What got fixed during B1

These were debts before but resolved within B1:

- **D2** — `dropped_by_grammar` metric (added)
- **D2 hotfix** — context-aware regex skip for `\bC\d{5}\b` etc. when grounded in structured field (fixed Anomaly #2)
- **D2 followup** — `claim_text` made explicitly required in prompt (fixed Anomaly #8 latent KeyError)
- **D3** — 9-class classifier collapse to 4-class grammar v2 routing
- **D4** — TaskOutcome enum + deprecation warnings + feedback hint per-drop_reason + inner/outer retry
- **D5 hotfix** — `_react_loop` inner retry coverage (cut EMPTY 24 % → 15 %)
- **D6 Step Q** — clean apples-to-apples baseline interpretation
- **Stage D (2026-05-20, commit `ed6243b`)** — P0 #1 grammar passthrough fix + regression test (see top of file)

---

## Summary

B1 closes with **1 P0 item open + 1 P0 closed** (grammar passthrough
silent bug **CLOSED by commit `ed6243b`**; documentation framing of
"regression" still open), 3 P1 (aggregator missing data, dead legacy
classifier, per-grammar sub-routing), 3 P2 (RaMP warning, MiniMax noise,
dead Layer D), and 3 P3 (paper-time discussion items).

The metagent-v2 W10 sprint (started 2026-05-21) opens on the remaining
debt: see `reports/agent/metagent_v2_w10_plan.md` for prioritisation.
