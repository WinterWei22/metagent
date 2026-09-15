# Pathway Prediction Second-Pass Result

Date: 2026-06-18 17:59:40 Asia/Shanghai

## What was requested

Stop tuning `pathway_prediction` inside the same final ReAct JSON. Restore the main ReAct final prompt to baseline and move pathway prediction to an independent second LLM pass after `claims[]` are fixed. Then validate on stored baseline dumps, keep claim-level metrics unchanged, and compute pathway-level metrics for Sub-6 63 + HMDB/RaMP membership 100.

## What was done

- Main ReAct prompt verified unchanged against HEAD:
  - `cmp -s <(git show HEAD:prompts/concord/concord_react_prompt.md) prompts/concord/concord_react_prompt.md`
  - result: `prompt_matches_HEAD`
- Added second-pass pathway selector:
  - `concord/agent/pathway_prediction.py`
  - `generate_pathway_prediction_second_pass(...)`
  - runs after fixed `narrative_text` + `claims[]`; returns only `pathway_prediction`.
- Wired runner serialization:
  - `ConcordReactResult.pathway_prediction`
  - second pass uses the runner's explicit `llm_model` / `llm_provider`.
- Hardened parser tolerance using real MiniMax outputs:
  - unwraps `{"pathway_prediction": {...}}`;
  - accepts string confidence as non-calibrated ordering text;
  - sanitizes out-of-range `supporting_claim_indices`;
  - accepts flat `primary: "name"` + `primary_pathway_id`;
  - accepts string-list alternatives.
- Updated contract doc:
  - `docs/decisions/2026-06-17_stage2_pathway_prediction_contract.md`
  - parser now sanitizes malformed second-pass indices instead of dropping a usable prediction.
- Added offline second-pass script:
  - `scripts/metagent/stage2_pathway_prediction_second_pass.py`

## Tests

- Focused tests:
  - `PYTHONPATH=. /home/weiwentao/miniconda3/bin/pytest tests/concord/test_pathway_prediction_contract.py tests/concord/test_react_runner.py -q`
  - result: `22 passed in 0.19s`
- 14-fail floor:
  - `PYTHONPATH=. /home/weiwentao/miniconda3/bin/pytest -q --tb=line --ignore=tests/test_ui --ignore=tests/integration`
  - result: `14 failed, 1579 passed, 14 skipped, 1 xfailed`
  - floor preserved; failures are existing environment/tool dependency failures (`sspa`, FELLA envelope, PubChem Lite, GNPS path, mummichog wrapper shape).

## Probe

8 stored baseline dumps:

- input: `data/metagent/stage2_pathway_prediction_contract_smoke10/old/path_x_full/`
- output: `data/metagent/stage2_pathway_prediction_second_pass_probe/probe8_predictions.jsonl`
- log: `logs/concord/pathway_prediction_second_pass_probe.jsonl`
- result: 7/8 primary present; 1/8 had no claims, so no second-pass call.
- actual cost from log: `$0.009523`

## Full163 second-pass run

No ReAct rerun. Only second-pass pathway selector was run over stored dumps:

- input dump dir: `data/metagent/w22_easyv3_stratified_paired/path_x_full/`
- output dir: `data/metagent/stage2_pathway_prediction_second_pass_full163/`
- log: `logs/concord/pathway_prediction_second_pass_full163.jsonl`
- report:
  - `reports/reports_v2/2026-06-18_stage2_pathway_prediction_second_pass_full163.md`
  - `reports/reports_v2/2026-06-18_stage2_pathway_prediction_second_pass_full163.csv`
  - `reports/reports_v2/2026-06-18_stage2_pathway_prediction_second_pass_full163.json`
- LLM calls: 159
- prompt tokens: 227,792
- completion tokens: 119,151
- actual cost: `$0.211319`

## Pathway metrics

Claim-level metrics are unchanged by construction because the main ReAct outputs were stored baseline dumps and were not regenerated.

| stratum | tasks | prediction ok | primary ID-exact | primary name-exact | primary semantic | top-k ID-exact | top-k name-exact | top-k semantic | abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| overall | 163 | 159 | 0.00% | 38.65% | 49.69% | 0.00% | 50.31% | 59.51% | 0.61% |
| hmdb_ramp_pathway_membership | 100 | 99 | 0.00% | 30.00% | 41.00% | 0.00% | 40.00% | 51.00% | 1.00% |
| sub6_hmdb_ramp_enrichment | 63 | 60 | 0.00% | 52.38% | 63.49% | 0.00% | 66.67% | 73.02% | 0.00% |

Notes:

- ID-exact is 0 because predictions usually emit KEGG/Wiki/SMPDB IDs while GT uses RaMP IDs (`RAMP_P_*`). This must stay separate from semantic accuracy.
- 4 tasks had no usable primary:
  - `hmdb_ramp_easy_wiki_RAMP_P_000052896_rep1`: no claims in stored dump.
  - `sub6_easy_compound_only_enrich_mammalian_RAMP_P_000050021_seed1`: no claims in stored dump.
  - `sub6_easy_compound_only_enrich_mammalian_lm_pathway_WP167_seed2`: no claims in stored dump.
  - `sub6_easy_compound_only_enrich_mammalian_lm_pathway_WP167_seed4`: no claims in stored dump.
  - plus one ok abstain/no-primary case: `hmdb_ramp_easy_wiki_RAMP_P_000052905_rep1`.

## Semantic validation

Manual validation file:

- `reports/reports_v2/2026-06-18_stage2_pathway_prediction_second_pass_semantic_manual_validation.md`
- `reports/reports_v2/2026-06-18_stage2_pathway_prediction_second_pass_semantic_manual_validation.csv`

Result:

- sample: 20 semantic-hit tasks
- TP: 19/20
- TP rate: 95.0%
- gate: PASS for semantic metric acceptance (`>=80%`)

One FP was documented:

- GT `Biosynthesis of unsaturated fatty acids`
- predicted primary `Fatty acid degradation`
- reason: neighboring fatty-acid biology but not semantically equivalent to biosynthesis.

## Current status

PASS for the requested second-pass pathway prediction experiment.

The same-JSON contract should remain abandoned. The independent second pass preserves claim generation and gives a usable pathway-level scorecard without dropping claims from JSON budget pressure.

## Next step

Await user/PI decision before any broader rerun or production default change.

Possible next decision points:

1. accept second-pass `pathway_prediction` as the Stage2 pathway output contract;
2. add RaMP-ID crosswalk for ID-exact reporting so ID-exact is not structurally zero;
3. tighten semantic rubric for broad pathway-family cases such as fatty acid metabolism vs biosynthesis/degradation;
4. decide whether to re-run only the 4 no-claims stored dumps or leave them as honest missing predictions.
