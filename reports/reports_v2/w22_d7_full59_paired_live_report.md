# W22 D7 Full59 Paired Live Report

Date: 2026-06-15

## Scope

This report summarizes W22 D7: one live MiniMax run over the W18 clean 59-task set,
followed by paired offline verification on the same ReAct dumps.

No ReAct task was run twice for the comparison. The two verifier arms consume the
same live outputs:

- `prose`: final narrative text through the prose verifier path.
- `structured_method_aware`: final `claims[]` through the structured adapter with method-aware enrichment enabled.

## Artifacts

- Live output directory: `data/metagent/w22_full59_paired_live/`
- Full task dumps: `data/metagent/w22_full59_paired_live/path_x_full/`
- Live results JSONL: `data/metagent/w22_full59_paired_live/path_x_results.jsonl`
- Live summary: `data/metagent/w22_full59_paired_live/path_x_summary.json`
- Paired metrics: `data/metagent/w22_full59_paired_live/paired_metrics.json`
- Per-claim paired table: `data/metagent/w22_full59_paired_live/paired_per_claim.csv`
- Per-task paired table: `data/metagent/w22_full59_paired_live/paired_per_task.csv`
- Manual validation candidates: `data/metagent/w22_full59_paired_live/manual_validation_candidates.csv`
- Manual validation review: `data/metagent/w22_full59_paired_live/manual_validation_review.md`
- Analysis script: `scripts/metagent/w22_d7_full59_paired_live.py`
- Master log: `conversation/master/2026-06-15_001622_w22-d7-full59-result.md`

## Live Run

Run configuration:

- Provider: `minimax`
- Model: `MiniMax-M2.7-highspeed`
- Structured verifier flag: enabled
- Task set: 59 W18-clean tasks

Live execution summary:

| metric | value |
|---|---:|
| tasks completed | 59 / 59 |
| crashes | 0 |
| LLM log errors | 0 |
| feedback iter1 tasks | 39 |
| iter2 tasks | 0 |
| rollback total | 8 |
| bridge-in-iters tasks | 51 |
| bridge lost to rollback | 24 |
| max tool calls | 21 |
| p95 tool calls | 18 |
| tasks over 25 tool calls | 0 |
| wall time | 15,227.48 s |

## Actual Cost

Cost is computed from `logs/concord/w22_full59_paired_live.jsonl`.

| token/cost field | value |
|---|---:|
| LLM log rows | 573 |
| prompt tokens | 8,292,424 |
| completion tokens | 748,862 |
| cached tokens | 5,649,172 |
| total tokens | 9,041,286 |
| rate | `$0.30/M prompt + $1.20/M completion` |
| actual cost | `$3.386362` |

## Paired Metrics

Honest denominators include grammar-dropped structured claims.

| arm | source claims | verified | dropped | supported | contradicted | unsupported | UV | supported honest | unlanded honest |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| prose | 410 | 410 | 0 | 150 | 19 | 120 | 121 | 36.59% | 29.51% |
| structured_method_aware | 587 | 451 | 70 | 341 | 13 | 31 | 66 | 58.09% | 23.17% |

Delta:

- Supported gain: `+21.51 pp`
- UV change: `-18.27 pp`
- Unlanded change: `-6.34 pp`
- Mean per-task supported gain: `+19.08 pp`
- Mean per-task unlanded change: `-4.72 pp`
- Tasks with supported gain: 40
- Tasks with supported loss: 17

## Manual Validation

Validation checked 20 rows from `manual_validation_candidates.csv` against the
real carrier rows inside the live full dumps.

| group | true / checked | result |
|---|---:|---|
| pipeline-lost to supported | 19 / 19 | pass |
| new contradicted | 0 / 1 | false positive |
| overall | 19 / 20 | 95% |

The 19 supported rows matched the cited carrier row for pathway identity plus
rank/score. The only new contradicted row was a false positive caused by numeric
notation parsing: `9.533x10^-10` / unicode scientific notation was parsed as
`9.533`, while the carrier row contained `9.533e-10`.

## Interpretation

The D7 paired live run validates the support-recovery signal for structured
claims with method-aware enrichment routing. On the same MiniMax outputs, the
structured arm raises honest supported rate by `+21.51 pp`.

The contradicted bucket is not yet clean enough for hard conclusions. Before
using new `CONTRADICTED` counts as a quality metric, fix numeric notation parsing
for unicode multiplication and superscript exponents, then rerun paired offline
verification.

The 70 structured grammar drops remain an explicit follow-up item. They are
included in the honest denominator here and should be audited before live/eval
enablement is treated as complete.

## Recommended Next Step

1. Patch numeric scientific-notation parsing.
2. Rerun `scripts/metagent/w22_d7_full59_paired_live.py` on the existing dumps.
3. Audit the 70 dropped structured claims.
4. Decide whether to enable the structured method-aware verifier path for the next live/eval run.
