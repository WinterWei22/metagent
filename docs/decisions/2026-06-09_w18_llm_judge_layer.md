# W18 LLM-Judge Layer Decision

## Status

Closed at D5 with a 59 / 63 clean aggregate (93.7% task coverage).

W18 beta validates the LLM-as-tool verifier pattern for MetAgent. The final
clean aggregate uses 59 tasks because 4 rerun tasks were left incomplete to
respect the W18 cost cap. Missing tasks are documented in
`data/metagent/w18_path_x_post_llm_judge_full63_d5_clean/missing_4_tasks.md`
and are excluded from claim denominators.

## D1.4 v4 Rubric

v4 tightens the D1 judge-fitness audit with five EDGE rules:

- EDGE-1 external KB scope leak: Reactome / SMPDB / KEGG REACTION / WikiPathways / PubChem / ChEBI / PubMed claims are `judge_uncoverable` unless the relevant lookup output is already in the source report.
- EDGE-2 identifier-as-content miscoding: identifiers presented as molecular formulas, structures, SMILES, or other content are `judge_uncoverable`.
- EDGE-3 interpretive contribution language: claims using `contribute to`, `drive`, `explain`, or `responsible for` beyond carrier-level membership/significance are `judge_uncoverable`.
- EDGE-4 undefined placement/status terms: `unplaced`, `unassigned`, `not classified`, and `outside the scope` are `judge_uncoverable` without a defined carrier field.
- EDGE-5 Mummichog rank/score/p-value claims: direct `MUMM:` rank, p-value, or score claims are `judge_strict` when Mummichog carrier is populated.

## D1.4 Results

- v4 spot-check output: `data/metagent/w18_dual_audit/claim_judge_fitness_spot_check_v4.csv`.
- v4 spot-check agreement: 20 / 20 = 100.0%.
- v4 full inventory: `data/metagent/w18_dual_audit/claim_judge_fitness_inventory_v4.csv`.
- v4 full summary: `data/metagent/w18_dual_audit/claim_judge_fitness_summary_v4.md`.
- `judge_strict`: 277 / 901 = 30.7%.
- `judge_uncoverable`: 624 / 901 = 69.3%.
- Strict ceiling: 13.81 pp of W17 UV.
- Target drop: 8.29 pp.
- Target UV rate: 36.63%.

## v3 vs v4 Delta

| metric | v3 | v4 | delta |
|---|---:|---:|---:|
| `judge_strict` | 296 | 277 | -19 |
| `judge_uncoverable` | 605 | 624 | +19 |
| strict ceiling | 14.76 pp | 13.81 pp | -0.95 pp |
| target drop | 8.85 pp | 8.29 pp | -0.56 pp |

## v4 Distribution

| claim_type | judge_strict | judge_uncoverable |
|---|---:|---:|
| `BIOLOGICAL` | 23 | 142 |
| `CONSISTENCY` | 9 | 41 |
| `DRIVER_METABOLITE` | 1 | 35 |
| `FACTUAL` | 15 | 126 |
| `GROUNDED` | 218 | 171 |
| `OTHER` | 1 | 49 |
| `PATHWAY_RELATIONSHIP` | 7 | 42 |
| `SET_ENRICHMENT` | 3 | 18 |

## D2 Candidate Scope

Conservative D2 candidate scope should prioritize claim patterns represented in v4 strict rows:

- Direct method-attributed numeric/rank claims from populated carriers.
- Direct `MUMM:` rank, p-value, or score claims.
- RaMP / Mummichog / MetaboAnalystR PSEA pathway membership and significance claims with concrete pathway or compound names.
- Simple source-input membership or carrier absence claims where the source report has the relevant list.

Do not include W19 gamma scope in D2:

- Reactome / SMPDB / KEGG REACTION / WikiPathways / PubMed.
- Compound chemistry lookup claims unless the lookup result is already present in the source report.
- Mechanism, contribution, causation, or undefined placement/status claims.

## D1.3 Cost Projection

Projection source: `data/metagent/w18_dual_audit/cost_projection.md`.

Assumptions:

- Path X UV claims: 973 from W17 D4.
- Per-call prompt estimate: 5,000 tokens.
- Per-call completion estimate: 500 tokens.
- MiniMax rates: $0.30 / 1M prompt tokens and $1.20 / 1M completion tokens.
- Per-call cost estimate: `$0.0021`.

| scope | eligible types | expected calls | strict rows covered | projected cost | verdict |
|---|---|---:|---:|---:|---|
| Narrow | `GROUNDED` | 420.1 | 218 / 277 | $0.8822 | PASS |
| Medium | `GROUNDED`, `BIOLOGICAL`, `FACTUAL` | 750.5 | 256 / 277 | $1.5761 | PASS, recommended |
| Wide | `GROUNDED`, `BIOLOGICAL`, `FACTUAL`, `PATHWAY_RELATIONSHIP`, `CONSISTENCY` | 857.4 | 272 / 277 | $1.8006 | PASS, narrow buffer |

Recommended D2 scope:

```python
JUDGE_ELIGIBLE_TYPES = {
    "GROUNDED",
    "BIOLOGICAL",
    "FACTUAL",
}
```

Medium scope is recommended because it covers 256 / 277 = 92.4% of v4 strict rows while staying below the $2 per-Path-X cap with a $0.4239 buffer. Wide only adds 16 strict rows for another ~$0.2245 per Path X, so it is not worth the cap pressure before D4.

Runtime cost cap design: D2 should enforce a hard $2.00 per-run LLM-judge cap. If observed per-call context size exceeds this estimate, remaining eligible claims should stay UV rather than exceeding the cap.

## Cost

- v4 spot-check: $0.0087 from `logs/concord/w18_dual_audit_v4_spot.jsonl`.
- v4 full rerun: $0.3913 from `logs/concord/w18_dual_audit_v4_full.jsonl`.
- cumulative D1 audit attempts: $0.9214 across v1/v2/v3/v4 logs.

## Next Gate

W18 D5 is closed. W19 gamma can build on this layer, but must preserve the
verifier accounting and cost-cap contracts below.

## D3.5 Patch Timeline

| Round | Purpose | Outcome |
|---|---|---|
| D3.5a | Prompt/parser contract repair | Prompt labels changed to runtime verdicts. Parser contract locked. |
| D3.5a | Final-iteration guard | LLM-judge dispatch restricted to final verifier iteration. |
| D3.5a | Path-X run cost cap | Run-level judge cost tracker added. |
| D3.5a | Judge trace | JSONL trace added for task_id / iteration / claim_id / verdict / parser_success / cost. |
| D3.5b | MiniMax response discipline | Reasoning wrappers stripped; prompt strengthened for JSON-only output. |
| D3.5c | Diagnostic | Found all-UV task cause: carrier fields were not visible in prompt excerpts. |
| D3.5d | Carrier-priority excerpts | New judge-specific excerpt builder prioritizes Mummichog / RaMP / MetaboAnalystR / SSPA / FELLA before large metabolite JSON. |
| D3.5e | 5-task smoke | Non-UV judge verdicts restored; approved full-scale rerun. |
| D3.5f | HEDGED accounting bug | `NEEDS_HUMAN_REVIEW` added to claim-table severity mapping. HEDGED counts in total denominator, not UV or SUPPORTED. |
| D3.5f follow-up | Rerun recovery | Retroactive recompute failed because crash-time per-claim state was not persisted; reran enough tasks for 59 / 63 coverage. |

## D4/D5 Clean Metrics

Final clean dataset:

- Results: `data/metagent/w18_path_x_post_llm_judge_full63_d5_clean/path_x_full63_results.jsonl`.
- Metrics: `data/metagent/w18_path_x_post_llm_judge_full63_d5_clean/d5_phase4_metrics_clean.json`.
- Coverage: 59 / 63 tasks = 93.7%.
- Missing: 4 tasks, excluded from all claim denominators.
- HEDGED accounting: 21 HEDGED final-iteration judge verdicts are included in the denominator only.

| Metric | W14 | W17 D4 | W18 D5 clean | Verdict |
|---|---:|---:|---:|---|
| UV rate | 44.25% | 44.92% | 36.45% | PASS |
| UV drop vs W17 | n/a | n/a | 8.47pp | PASS |
| Claim denominator | 2036 | 2166 | 1871 | report |
| Supported claims | 702 | 691 | 698 | report |
| Contradicted claims | n/a | 46 | 44 | report |
| HEDGED claims | n/a | n/a | 21 | report |
| Pathway bridge accuracy | 54 / 63 = 85.7% | 57 / 63 = 90.5% | 52 / 59 = 88.1% | PASS |
| iter-2 degraded | 0 | 0 | 0 | PASS |
| Cumulative W18 LLM cost | n/a | n/a | $24.0561 | PASS |
| Clean final-iteration judge cost | n/a | n/a | $1.0500 | PASS |

## Hard Gates

| Gate | Target | Observed | Verdict |
|---|---|---|---|
| HG-A UV drop | >=4pp PASS; <2pp stop | 8.47pp drop, UV 36.45% | PASS |
| HG-B Pathway accuracy | >=84%; stop <80% | 52 / 59 = 88.1% | PASS |
| HG-C iter-2 degraded | 0 | 0 | PASS |
| HG-D Total W18 cost | <=$25 | $24.0561 | PASS |
| HG-E Judge incremental cost | <=$5 | $1.0500 final-iteration clean judge trace cost | PASS |
| HG-F B1 floor | 14-fail floor preserved | 14 failed, 1503 passed, 14 skipped, 1 xfailed | PASS |
| HG-11 CONTRADICTED sample | TP >=70% | 17 / 20 = 85.0% | PASS |

## HEDGED Bug and Recovery

The D4 full-63 rerun initially produced promising judge trace signals but
30 final iterations crashed during verifier aggregation:

- Cause: `HEDGED` is parsed as `ClaimVerdict.NEEDS_HUMAN_REVIEW`.
- Bug: `verifier/claim_table.py` did not define severity for
  `NEEDS_HUMAN_REVIEW`, causing `_SEVERITY_BY_VERDICT[claim.verdict]` to raise.
- Fix: D3.5f maps `NEEDS_HUMAN_REVIEW` to `minor` severity and locks metrics
  semantics in tests.
- Accounting decision: HEDGED is a separate partial-positive bucket. It is
  included in total claim denominators, but not counted as SUPPORTED or UV.

Recovery path:

- A full retroactive recompute was tested first.
- It failed because failed verifier iterations persisted only raw narrative
  claims and not serialized `claims_v1` / `claims_v2`.
- This exposed a crash-time data preservation gap inherited from the verifier
  result design.
- Enough failed tasks were rerun to reach 26 / 30 recovered tasks, giving
  59 / 63 total clean coverage.

## Carrier Excerpt Repair

D3.5c found that judge prompts contained large `differential_metabolites`
payloads before tool-output carriers. The prompt excerpt often hit the length
limit before Mummichog, RaMP, MetaboAnalystR, SSPA, or FELLA evidence appeared.

D3.5d fixed this with `verifier/helpers/build_judge_excerpt.py`:

- Carrier sections first, around 6000 characters.
- Differential metabolites next, capped around 3000 characters.
- Auxiliary fields last, around 1500 characters.
- Carrier section headers document the intended claim type.
- Scientific notation and ranked pathway evidence are preserved.

This restored non-UV judge verdicts in smoke and full-scale traces.

## Scope Decision

The final W18 eligible type scope remains the D1.3 Medium scope:

```python
JUDGE_ELIGIBLE_TYPES = {
    ClaimType.GROUNDED,
    ClaimType.BIOLOGICAL,
    ClaimType.FACTUAL,
}
```

This scope matched the v4 audit: it covers most strict carrier-backed claims
without admitting W19 gamma external-KB claims.

## Cost Cap Validation

W18 validated the per-Path-X LLM-judge cost pattern:

- Run-level tracker prevents unbounded judge calls.
- Final-iteration guard prevents iter0 + iter1 double judging.
- Clean final-iteration judge trace cost was $1.0500.
- Total W18 LLM cost was $24.0561, below the $25 hard cap.

## W19 Gamma Checklist

- Define which KEGG REST, PubMed, and Reactome surfaces are allowed as tools.
- Keep W18 LLM-judge as a verifier tool; do not convert it into a narrative generator.
- Every new `ClaimVerdict` value must ship with explicit aggregate semantics before any Path-X rerun.
- Reuse the per-Path-X cost cap pattern.
- Reuse the judge trace JSONL format.
- Reuse the carrier-priority excerpt builder pattern for any new KB/tool carriers.
- Add crash-time data preservation: failed verifier passes should persist per-claim intermediate verdicts for forensic recompute.

## Memory Suggestions

Do not edit memory automatically. Suggested updates:

- `feedback_verifier_modification_policy.md`: add a hard rule that every new `ClaimVerdict` must have aggregate/count/severity semantics before full reruns.
- `feedback_metagent_must_be_llm_driven.md`: add W18 as a partial validation case for LLM-judge as a verifier-side tool.
- New `reference_verifier_llm_judge_pattern.md`: document prompt contract tests, parser gates, per-run cost caps, judge trace JSONL, carrier-priority excerpts, HEDGED accounting, and crash-time persistence.
- New `feedback_crash_time_data_preservation.md`: record the W18 finding that verifier crashes must persist per-claim intermediate state.
