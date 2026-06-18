# W22 Structured Claim Verification Design

Date: 2026-06-14
Status: design for PI/Claude review, not implemented

## Scope

W22 investigates whether MetAgent should verify the model's structured `claims[]`
directly instead of re-extracting claims from final prose. D1.6 and D2 were
offline only and used the W18 59-task stored dump.

This document proposes a staged implementation path. It does not change
production code.

## Evidence From Offline Derisking

Inputs:

- W18 clean 59-task dump.
- D1/D1.5/D1.6 W22 offline analysis outputs.
- No ReAct rerun.
- Cost `$0`.

Key outputs:

- `data/metagent/w22_uv_attribution/d1_6_method_aware_metrics.json`
- `data/metagent/w22_uv_attribution/d2_namespace_impact.md`
- `data/metagent/w22_uv_attribution/d2_dropped_rescue.md`
- `data/metagent/w22_uv_attribution/d2_final_opportunity.md`

Main findings:

- D1.6 method-aware routing passed truth validation: `90% / 90%`.
- D2 namespace normalization rescued `4` strict semantic-ID flips after conservative rank/score checking.
- D2 dropped rescue found `31` likely supported rescued claims, but the spotcheck was only `15/20 TRUE = 75%`, so this is a later high-risk stage.
- Projected structured supported honest rate after conservative derisking: `53.95%`.
- Projected supported gain over prose: `+22.25 pp`.
- Projected unlanded burden remains higher than prose:
  - conservative: `+6.73 pp`
  - full-landed projection: `+3.06 pp`

Interpretation:

- The opportunity is real for supported evidence preservation.
- The remaining risk is not method-aware routing; it is dropped-claim grammar rescue and strict namespace/rank/score semantics.

## Architecture

### Current Path

Current verifier adapter returns a prose string:

- `concord/agent/verifier_adapter.py::concord_result_to_b1_narrative`
- `verifier/agent.py:_extract_classify` then extracts/classifies from that string.

For W22, the desired structured path is:

1. Concord result preserves `final_narrative_text` and `final_claims`.
2. Adapter constructs a verifier input payload containing:
   - `narrative_text`
   - `claims`
   - optional provenance fields needed for traceability
3. Existing JSON extraction route consumes the structured `claims`.
4. Method-aware enrichment verifier routes by `evidence_method`.
5. Namespace normalization matches only semantically equivalent IDs.
6. Dropped rescue stays feature-flagged and separate.

### Do Not Touch

The following are B1-core or locked paths and should not be modified for W22:

- `verifier/claim_extractor.py::extract_claims_from_json`
- `verifier/agent.py::_extract_classify`
- `verifier/feedback_hints.py::build_feedback_message`
- `schemas/sub6_report.py::SubsixSourceReport`
- `DEFAULT_MAX_FEEDBACK_ITERS`
- `signal_sub6` dispatcher catch-all rollback state
- `concord/agent/*.py` beyond the already-approved adapter boundary

If implementation appears to require touching any of these, stop and redesign.

## Proposed File Changes

Allowed, staged changes:

- `concord/agent/verifier_adapter.py`
  - Add a new function such as `concord_result_to_b1_structured_payload`.
  - Keep `concord_result_to_b1_narrative` behavior unchanged for backward compatibility.
  - Feature flag the structured path.

- `verifier/helpers/pathway_namespace.py` new
  - Exact semantic ID normalization:
    - KEGG `mapNNNNN` <-> `hsaNNNNN`
    - WikiPathways `WP*`
    - SMPDB `SMP*`
    - Reactome `R-HSA-*`
    - mummichog native IDs
  - No loose fuzzy matching as support.

- `verifier/helpers/method_aware_enrichment.py` new
  - Route by structured `evidence_method`:
    - RaMP -> `ramp_enrichment_result.top_pathways`
    - mummichog -> `mummichog_enrichment_result.pathways/top_pathways`
    - MetaboAnalystR -> `metaboanalystr_enrichment_result.psea.pathways/top_pathways`
    - SSPA/FELLA -> their corresponding carriers
  - Missing carrier -> `UNVERIFIABLE_V0`, not fallback to RaMP.

- `verifier/layers/set_enrichment.py`
  - Minimal integration only after helper tests pass.
  - Preserve existing RaMP behavior when no structured method is available.
  - Use method-aware helper only when claim extracted fields/provenance indicate method.

- `verifier/grammar.py` and classifier mapping
  - Only if a structured-only grammar extension is necessary.
  - Prefer not changing existing grammar first; use `extracted_fields`/raw structured fields where possible.

- Tests under `tests/test_w22_*` and existing layer tests
  - Add targeted tests, not broad snapshot churn.

## Baseline Drift Handling

Changing input from prose re-extraction to structured `claims[]` changes the
claim denominator and therefore W18 absolute numbers.

Implementation must not compare new structured numbers directly to old prose
numbers without marking the contract change.

Recommended handling:

1. Keep W18 stored dump immutable.
2. Recompute a clean W18 structured-verification baseline from the stored dump.
3. Report paired metrics:
   - old prose extraction baseline
   - structured claims baseline
   - structured + method-aware
   - structured + method-aware + namespace normalization
4. Update tests such as `tests/concord/test_d3_zero_llm_extract_invariant.py`
   only to reflect the new adapter contract; do not delete the invariant.
5. Keep a paired task-id denominator for all comparisons.

## Implementation Phases

### Phase 1: Method-aware enrichment, feature flag off by default

Goal:

- Fix the cleanest bug first: claims citing mummichog/MetaboAnalystR must not be verified against RaMP.

Design:

- Add method-aware helper.
- Add namespace helper in exact-ID mode only.
- Do not enable structured adapter by default yet.

Expected risk:

- Low to medium.

### Phase 2: Structured payload adapter, paired baseline mode

Goal:

- Route `final_claims[]` into verifier without changing B1-core extractor.

Design:

- Add new adapter function.
- Feature flag the runner/evaluation path to call it.
- Preserve old prose path.

Expected risk:

- Medium, because denominator changes.

### Phase 3: Namespace normalization in production layer

Goal:

- Accept exact equivalent IDs, not fuzzy names.

Design:

- Add explicit tests for KEGG `map`/`hsa`, Reactome, WP, SMPDB, mummichog.
- Reject same-name/different-rank/score mismatches.

Expected risk:

- Medium.

### Phase 4: Dropped rescue, feature-flagged and last

Goal:

- Recover structured IDs and weak pathway links that current grammar drops.

Design:

- Rescue only typed structured claims.
- Do not rescue prose roundtrip IDs.
- Keep abstract/hedged/directional claims dropped unless a separate hypothesis rule handles them.
- Treat rescued `CONTRADICTED` as high-risk until tests prove semantics.

Expected risk:

- High. D2 spotcheck was only `75%` clean.

## RED Test Checklist

Do not leave failing tests in tree before review. These are the tests to write
when implementation is approved:

- Method-aware routing:
  - mummichog claim reads mummichog carrier, not RaMP.
  - MetaboAnalystR claim reads PSEA carrier, not RaMP.
  - missing method carrier returns `UNVERIFIABLE_V0`.
  - no method/prose claim preserves legacy RaMP behavior.

- Namespace normalization:
  - `KEGG:map00260` equals `KEGG:hsa00260`.
  - `WP:WP2525` equals carrier `pathway_external_id=WP2525`.
  - `SMPDB:SMP00134` equals carrier external ID.
  - `REACT:R-HSA-211859` equals carrier external ID.
  - Reactome must not be parsed as KEGG `hsa`.
  - ID match with rank/score mismatch remains `CONTRADICTED` or `UNSUPPORTED`, not `SUPPORTED`.

- Structured adapter:
  - old `concord_result_to_b1_narrative` remains unchanged.
  - new structured payload includes `claims[]`.
  - zero-LLM JSON extraction invariant still holds.

- Dropped rescue:
  - structured `Cxxxxx` ID is allowed as anchor only in typed structured claim.
  - prose `Cxxxxx` breadcrumb remains dropped.
  - missing-enzyme pathway link downgrades to weak membership only.
  - abstract/hedged/directional claims stay dropped.

- Regression:
  - B1 14-fail floor preserved.
  - W12-W21 gates no regression.
  - `signal_sub6` remains disabled.
  - iter cap remains unchanged.

## Rollback Plan

- Every phase behind a feature flag.
- Default path remains the existing prose verifier until paired baseline passes.
- If method-aware layer regresses, disable the feature flag and keep old RaMP-only behavior.
- If structured adapter changes denominator unexpectedly, keep results as a separate contract and do not merge into main metrics.
- If dropped rescue spotcheck stays below `80%`, leave it disabled.

## Risk Register

| risk | severity | mitigation |
|---|---|---|
| Namespace normalization becomes fuzzy matching | high | exact ID equivalence only; name matching cannot create support without ID/rank/score guard |
| Structured input changes denominator | high | paired baseline and explicit contract label |
| Dropped rescue admits weak claims | high | feature flag last; abstract/hedged stays dropped |
| B1-core extractor pressure | high | do not touch extractor; adapter/helper boundary only |
| CONTRADICTED inflation | medium | rank/score tests and manual spotcheck |
| ReAct variance confounds result | medium | use stored W18 dump for paired offline baseline first |

## Recommendation

Proceed to implementation design review.

If approved, implement only Phase 1 first:

- method-aware enrichment helper
- exact namespace helper
- RED/GREEN tests
- feature flag off by default

Do not implement dropped rescue in the first production patch.

