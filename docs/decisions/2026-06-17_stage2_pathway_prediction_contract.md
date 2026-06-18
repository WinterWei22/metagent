# Stage2 Pathway Prediction Output Contract

Date: 2026-06-17

Project: MetAgent

Decision: adopt an explicit `pathway_prediction` object for Stage2 pathway benchmark tasks, generated in a separate post-finalization LLM pass after the main ReAct `claims[]` JSON is fixed.

## Problem

The current Stage2 structured output has `narrative_text` and `claims[]`, but no single field that means "the model's final pathway identification." Recent analysis had to infer a top pathway from the first `PATHWAY_ENRICHMENT` claim, which is not a reliable or human-readable prediction contract.

This caused three problems:

1. Pathway-level accuracy became ambiguous.
2. Claim-level verification metrics were mixed with final pathway identification metrics.
3. Human review became harder because each task lacked one canonical predicted pathway.

## Decision

Use a second-pass contract: keep the main ReAct final JSON at the baseline `narrative_text` + `claims[]` shape, then ask the LLM once more to select `pathway_prediction` from those already-written claims.

The model must explicitly output:

- one primary predicted pathway;
- zero or more alternative predicted pathways;
- an abstain flag when no defensible pathway can be identified;
- links from prediction entries back to supporting `claims[]` entries.

`pathway_prediction.primary` is the only field that means "the model's final top pathway prediction."

## JSON shape

Main ReAct output remains baseline-only:

```json
{
  "narrative_text": "...",
  "claims": []
}
```

The separate second-pass call returns only this object:

```json
{
  "primary": {
    "pathway_id": "KEGG:hsa00590",
    "pathway_name": "Arachidonic acid metabolism",
    "pathway_source": "KEGG",
    "confidence": 0.86,
    "evidence_methods": [
      "run_ramp_enrichment",
      "run_metaboanalystr_psea",
      "run_mummichog"
    ],
    "supporting_claim_indices": [0, 1, 2],
    "rationale": "Multiple fixed claims converge on arachidonic acid/eicosanoid biology."
  },
  "alternatives": [
    {
      "pathway_id": "WP:WP167",
      "pathway_name": "Eicosanoid synthesis",
      "pathway_source": "WikiPathways",
      "confidence": 0.74,
      "evidence_methods": ["run_ramp_enrichment"],
      "supporting_claim_indices": [3],
      "rationale": "RaMP/WikiPathways evidence supports the eicosanoid pathway family."
    }
  ],
  "abstain": false,
  "abstain_reason": null
}
```

When `abstain` is `true`, `primary` must be `null`, `alternatives` must be an empty list, and `abstain_reason` must explain why no pathway prediction is defensible.

## Field semantics

### `primary`

The model's single final pathway prediction for this task.

Rules:

- Must be selected by the model before verifier post-processing.
- Must not be filled by the verifier or analysis code.
- Must be supported by at least one referenced claim unless `abstain=true`.
- Should prefer the most specific pathway that is consistently supported by evidence.
- Must not be a vague umbrella term such as "metabolism" unless the task evidence truly does not support a more specific pathway.

### `alternatives`

Secondary plausible pathway predictions.

Rules:

- Use alternatives for closely related namespaces, parent/subpathway ambiguity, or genuinely tied evidence.
- Keep the list short: recommended maximum 3.
- Alternatives are not the top prediction.

### `supporting_claim_indices`

Indexes into the already-final main ReAct `claims[]` array.

Rules:

- Each index should point to an existing claim. The parser tolerates malformed
  second-pass outputs by dropping out-of-range indices instead of dropping the
  whole task.
- At least one referenced claim should be a pathway-relevant claim: `PATHWAY_ENRICHMENT`, `PATHWAY_MEMBERSHIP`, `METABOLITE_PATHWAY_LINK`, or `DRIVER_METABOLITE`.
- The prediction object and referenced claims must not contradict each other.

### `confidence`

A model-provided ordering cue from 0 to 1.

Rules:

- Use only to order primary versus alternatives when the pathway evidence is otherwise similar.
- Do not treat it as calibrated probability.
- Do not apply a hard threshold in parser, verifier, or analysis code.
- Low confidence should encourage abstention in the prompt, but malformed or low values must not cause task-level dropping.

## Evaluation metrics

Pathway-level metrics must be computed from the second-pass `pathway_prediction`, not inferred from `claims[]` order.

Report all of the following:

| Metric | Definition |
|---|---|
| `primary_id_exact` | `primary.pathway_id` exactly matches ground-truth ID. |
| `primary_name_exact` | normalized `primary.pathway_name` exactly matches ground-truth pathway name. |
| `primary_semantic_match` | primary pathway name is semantically equivalent, a clear synonym, or a defensible parent/subpathway relation to ground truth. |
| `topk_id_exact` | primary or alternatives contain an exact ground-truth ID match. |
| `topk_name_exact` | primary or alternatives contain an exact normalized name match. |
| `topk_semantic_match` | primary or alternatives contain a semantic match. |
| `verifier_supported_primary` | primary is linked to at least one verifier-supported supporting claim. |
| `verifier_supported_topk` | primary or alternatives have at least one verifier-supported supporting claim. |
| `abstain_rate` | fraction of tasks with `abstain=true`. |

Human1 and Recon2.2 namespace cases must report ID-exact and name/semantic metrics separately. Do not hide namespace mismatch by converting semantic match into ID accuracy.

## Claim-level metrics remain separate

Claim-level metrics are still useful but answer a different question.

Continue reporting:

- source claims;
- verified claims;
- dropped claims;
- supported;
- contradicted;
- unsupported;
- UV;
- supported honest rate;
- UV honest rate;
- unlanded honest rate;
- method-aware hit rate.

Do not use claim-level supported rate as pathway accuracy.

## Verifier integration rule

The verifier may validate whether the supporting claims are supported, but it must not rewrite `pathway_prediction.primary`.

The analysis layer may compute:

- whether primary is supported by its referenced claims;
- whether primary matches ground truth by ID, exact name, or semantic name;
- whether top-k alternatives rescue the task.

## Prompt requirements

The ReAct final-answer prompt should explicitly require:

1. keep the main ReAct final-answer prompt baseline-only: `narrative_text` + four-class `claims[]`;
2. do not mention `pathway_prediction` in the main ReAct prompt;
3. after claims are fixed, run a separate small LLM call that sees `narrative_text` + `claims[]`;
4. the second pass returns only the `pathway_prediction` object;
5. fill `pathway_prediction.primary` unless abstaining;
6. keep `claims[]` and `pathway_prediction` consistent;
7. do not change, reduce, or reorder claims to satisfy `pathway_prediction`;
8. include `supporting_claim_indices` that point to concrete existing claims;
9. use `alternatives` for namespace ambiguity or close biological alternatives;
10. abstain instead of inventing a pathway when inputs are unresolved or evidence is empty.

## Tests required before production use

1. Parser contract test accepts a valid `pathway_prediction`.
2. Parser rejects missing `pathway_prediction`.
3. Parser sanitizes out-of-range `supporting_claim_indices` without rejecting a usable prediction.
4. Parser accepts `abstain=true` only when `primary=null` and `alternatives=[]`.
5. Analysis computes `primary_name_exact` from `pathway_prediction.primary`, not first claim order.
6. Analysis keeps claim-level metrics separate from pathway-level metrics.
7. A real saved task dump with `pathway_prediction` round-trips through runner serialization.

## Implementation boundary

This document is only the contract decision. Implementation should be done in a later patch with tests first.

Expected implementation areas:

- `concord/agent/react_runner.py` final JSON instruction and parsing;
- a small schema/helper for validating `pathway_prediction`;
- tests for parser and analysis behavior;
- reporting scripts that compute pathway metrics from the new field.

Do not change B1-core helpers, W17 schema, or unrelated verifier layers as part of this contract.
