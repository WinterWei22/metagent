# Sub-6B v3 Opus vs v2 Opus Comparison

Date: 2026-05-08  
Track: `sub6b_v3_opus`  
Narrative LLM: `claude-opus-4-7`  
Verifier: working-tree v9-PhaseC, user-accepted dirty state

## 1. Aggregate Verdict Comparison

| metric | v2 sub6b_opus | v3 sub6b_opus | Delta |
|---|---:|---:|---:|
| benchmark tasks | 63 | 63 | 0 |
| narrative rows | 63 | 63 | 0 |
| non-empty narratives | 63 | 61 | -2 |
| verdict task records | 63 | 61 | -2 |
| ok verdict task records | 62 | 60 | -2 |
| error verdict task records | 1 | 1 | 0 |
| total claims | 3,281 | 3,379 | +98 |
| supported % | 18.10 | 17.40 | -0.70 pt |
| unsupported % | 12.56 | 11.51 | -1.04 pt |
| contradicted % | 4.18 | 4.11 | -0.06 pt |
| unverifiable_v0 % | 65.16 | 66.97 | +1.81 pt |
| narrative mean length, all rows | 2,766 | 2,757 | -9 |
| narrative mean length, non-empty rows | 2,766 | 2,848 | +82 |

Interpretation: contradicted rate is effectively unchanged, but unverifiable_v0 does not improve. It rises by 1.81 percentage points. This puts the result in Case B: the LIPID MAPS data integration changed the benchmark composition, but the current narrative plus verifier stack did not convert that into a measurable aggregate verification improvement.

Run caveat: two v3 narratives were empty despite `error=None` from the runner and stayed empty after two fill-in attempts:

- `compound_only_enrich_mammalian_RAMP_P_000000398_seed1`
- `compound_only_enrich_mammalian_RAMP_P_000000141_seed6`

The verifier therefore produced 61 task records. This satisfies the requested lower bound of at least 61 verdict rows, but the two empty narratives should be treated as failed narrative generations in downstream accounting.

The single verifier error was an API connection failure:

- `compound_only_enrich_mammalian_RAMP_P_000053306_seed7`

## 2. Per-Claim-Type Comparison

| claim_type | metric | v2 | v3 | Delta |
|---|---|---:|---:|---:|
| set_enrichment | total | 156 | 159 | +3 |
| set_enrichment | supported | 2 | 2 | 0 |
| set_enrichment | unsupported | 2 | 6 | +4 |
| set_enrichment | contradicted | 32 | 11 | -21 |
| set_enrichment | unverifiable_v0 | 120 | 140 | +20 |
| biological_claim | total | 2,288 | 2,683 | +395 |
| biological_claim | supported | 511 | 499 | -12 |
| biological_claim | unsupported | 402 | 378 | -24 |
| biological_claim | contradicted | 53 | 55 | +2 |
| biological_claim | unverifiable_v0 | 1,322 | 1,751 | +429 |

The largest regression is biological_claim unverifiable count: +429 claims. LIPID MAPS does not reduce Layer 6c unverifiable behavior in aggregate. For set_enrichment, the supported count is unchanged at 2, while unverifiable increases from 120 to 140.

## 3. Lipid Bucket Analysis

v3 contains 11 lipid tasks. Ten of them are seed variants of the same LIPID MAPS/WikiPathways pathway `WP167` (`Eicosanoid synthesis`), so this expands lipid task count but not lipid pathway diversity. The eleventh task is the pre-existing RaMP/WikiPathways steroid task.

| task_id | ground truth | LLM wrote exact ground-truth pathway name? | lipid concepts written | verifier saw WP167/LIPID MAPS context? | at least one supported WP167/eicosanoid-linked claim? |
|---|---|---|---|---|---|
| `compound_only_enrich_mammalian_RAMP_P_000053042_seed9` | Steroid biosynthesis | N | steroid, aromatase | N | N |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed0` | Eicosanoid synthesis | N | eicosanoid, arachidonic, prostaglandin, leukotriene | Y | Y |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed1` | Eicosanoid synthesis | N | eicosanoid, arachidonic, prostaglandin, leukotriene | Y | Y |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed2` | Eicosanoid synthesis | N | eicosanoid, arachidonic, prostaglandin, leukotriene | Y | Y |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed3` | Eicosanoid synthesis | N | eicosanoid, arachidonic, prostaglandin, leukotriene | Y | Y |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed4` | Eicosanoid synthesis | N | eicosanoid, arachidonic, prostaglandin, leukotriene | Y | Y |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed5` | Eicosanoid synthesis | N | eicosanoid, arachidonic, leukotriene | Y | Y |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed6` | Eicosanoid synthesis | N | eicosanoid, arachidonic, leukotriene | Y | Y |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed7` | Eicosanoid synthesis | N | eicosanoid, arachidonic, leukotriene, steroid | Y | Y |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed8` | Eicosanoid synthesis | N | eicosanoid, arachidonic, leukotriene | Y | Y |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed9` | Eicosanoid synthesis | N | eicosanoid, arachidonic, leukotriene | Y | Y |

Main observation: Opus did not literally write `Eicosanoid synthesis` or `LIPID MAPS` in the 10 WP167 narratives. It consistently wrote nearby biological concepts such as arachidonic acid metabolism, eicosanoid biosynthesis/signaling, leukotriene, and prostaglandin. The verifier can sometimes connect these to WP167 through the enriched pathway context, but aggregate set_enrichment support did not increase.

This means the integration is not merely cosmetic: the new lipid tasks are biologically recognized by the LLM. However, the current verifier still mostly rewards KEGG/RaMP-style pathway naming and does not turn the new LIPID MAPS task coverage into a lower unverifiable rate.

## 4. Smoking Gun Example

Task: `compound_only_enrich_mammalian_lm_pathway_WP167_seed3`  
Ground truth: `Eicosanoid synthesis` (`lm_pathway:WP167`, source `lipidmaps`)

The narrative did not use the exact phrase `Eicosanoid synthesis`, but it did state the dominant biology as arachidonic acid metabolism and eicosanoid biosynthesis. The verifier produced supported biological_claim verdicts for claims such as the arachidonic acid/eicosanoid axis and direct mapping of multiple metabolites to that axis, with `pathway_match_method=substring_either` against the task enrichment context.

This is the clearest positive case: LIPID MAPS-created tasks elicit correct eicosanoid biology from Opus, and the verifier can support some of those claims. The limitation is that the same behavior does not move the aggregate unverifiable_v0 rate down, because many free-text mechanistic eicosanoid claims remain outside v0 scope.

## 5. Decision Recommendation

Case B: v3 is useful as a data expansion, but verifier support has not caught up.

Recommended next actions:

1. Keep v3 data for lipid bucket coverage, but do not claim that LIPID MAPS integration improves verifier-level support rates yet.
2. In paper text, describe the lipid gain as task coverage and pathway diversity limitation mitigation, with the explicit caveat that 10/11 lipid tasks share WP167.
3. If the goal is lower unverifiable_v0, extend Layer 6c phrase resolution / verifier pathway synonym support for LIPID MAPS and eicosanoid aliases (`arachidonic acid metabolism`, `eicosanoid biosynthesis`, `eicosanoid signaling`).
4. For a stronger v3 paper result, expand beyond WP167 before rerunning all models; otherwise lipid bucket statistics are still seed-replicate dominated.

## 6. Provenance

Commands:

```bash
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
    --narrative-llm opus47 \
    --output data/eval/sub6/v3/sub6b_opus/ \
    > logs/v3/sub6b_opus_narrative.log 2>&1

METAGENT_LLM_PROVIDER=openai \
METAGENT_OPENAI_MODEL=claude-opus-4-7 \
METAGENT_OPENAI_BASE_URL=https://api.viviai.cc/v1 \
METAGENT_OPENAI_API_KEY=<redacted> \
METAGENT_LLM_LOG_PATH=logs/v3/sub6b_opus_verifier_llm_calls.jsonl \
PYTHONPATH=. python scripts/eval_sub6/grade_with_verifier.py \
    --narratives data/eval/sub6/v3/sub6b_opus/sub6b_narratives.jsonl \
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
    --curated data/benchmark/sub6/curated_hmdb_mammalian_v3.jsonl \
    --out data/eval/sub6/v3/sub6b_opus/verdicts_v9_phaseC.jsonl \
    --track sub6b_v3_opus \
    > logs/v3/sub6b_opus_verifier.log 2>&1

PYTHONPATH=. python scripts/eval_sub6/aggregate_verifier.py \
    --verdicts data/eval/sub6/v3/sub6b_opus/verdicts_v9_phaseC.jsonl \
    --narratives data/eval/sub6/v3/sub6b_opus/sub6b_narratives.jsonl \
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
    --out-dir results/v3/sub6b_opus/ \
    --track sub6b_v3_opus
```

Wall time:

- Narrative first full pass: ~22.6 min; two empty rows persisted after fill-in retries.
- Verifier: ~50.0 min including one recoverable API stall and one final error row.
- Aggregation: <1 min.

Verifier internal LLM check:

- `logs/v3/sub6b_opus_verifier_llm_calls.jsonl`: 181 calls
- model set: `['claude-opus-4-7']`

MD5:

| file | md5 |
|---|---|
| `data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl` | `331b30a64017debe9d5ce07ed238e4f5` |
| `data/eval/sub6/v3/sub6b_opus/sub6b_narratives.jsonl` | `de5212b14fdc61fa98596c56d725eee6` |
| `data/eval/sub6/v3/sub6b_opus/verdicts_v9_phaseC.jsonl` | `5d443cbf4344949a98ac2d276ee90845` |
| `results/v3/sub6b_opus/sub6b_v3_opus_verdicts_summary.json` | `e0b1e750d3251da28623e313181372d5` |
| `logs/v3/sub6b_opus_narrative.log` | `25d4d19cba1e32b404b7ecdb39b30fce` |
| `logs/v3/sub6b_opus_verifier.log` | `6f4f0a8064eba57571b0e3008de9d9a0` |
| `logs/v3/sub6b_opus_verifier_llm_calls.jsonl` | `4a7cc085ef6d1dcbfca8bfe562f60e7c` |

v2 baseline files were unchanged:

| file | md5 |
|---|---|
| `data/eval/sub6/v2/sub6b_opus/sub6b_narratives.jsonl` | `a42b90a2f79b57544828fec521fef840` |
| `data/eval/sub6/v2/sub6b_opus/verdicts_v9_phaseC.jsonl` | `f57108a2a176babd6152ee1b026c6848` |
| `results/v2/sub6b_opus/sub6b_v2_opus_verdicts_summary.json` | `954d5fb2521bb469364a3b215f3ca8a1` |

## 7. Acceptance Check

| check | status | note |
|---|---|---|
| `sub6b_narratives.jsonl` has 63 rows | PASS | 2 rows have empty narrative text |
| `verdicts_v9_phaseC.jsonl` has at least 61 rows | PASS | 61 rows |
| verifier error rows <= 2 | PASS | 1 APIConnectionError row |
| summary JSON exists | PASS | `results/v3/sub6b_opus/sub6b_v3_opus_verdicts_summary.json` |
| report main table filled | PASS | see Section 1 |
| all 11 lipid tasks listed | PASS | see Section 3 |
| verifier internal LLM is `claude-opus-4-7` | PASS | confirmed from LLM call log |
| v2 file MD5 unchanged | PASS | see Section 6 |
| code changes in this evaluation session | PASS | no code files were edited in this session; existing dirty working tree remains |

