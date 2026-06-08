# W17 D4 Path X Post Schema Extend

## Aggregate

- Tasks: 63.
- Crashes: 0.
- Valid: 63.
- Wall: 48.9 min.
- LLM calls: 985.
- Prompt tokens: 12,221,562.
- Completion tokens: 2,317,018.
- Cost: $6.4469 using MiniMax rate $0.30/M prompt + $1.20/M completion.

## Metrics

| Metric | W14 baseline | W16 D4 | W17 D4 | Target | Verdict |
|---|---:|---:|---:|---:|---|
| UV claim rate | 44.25% | 47.67% | 44.92% | 43.25-45.25% | PASS |
| UV count / denominator | 901 / 2036 | 880 / 1846 | 973 / 2166 | within +/-1pp | PASS |
| Supported claim rate | 34.48% | 26.38% | 31.90% | report | PASS |
| Pathway bridge accuracy | 54 / 63 = 85.7% | 51 / 63 = 81.0% | 57 / 63 = 90.5% | >=84% | PASS |
| iter-2 trigger count | 0 / 63 | 0 / 63 | 0 / 63 | 0 / 63 | PASS |
| iter-2 degraded rollback | 0 / 63 | 0 / 63 | 0 / 63 | 0 / 63 | PASS |
| Cost | $6.83 | $7.0502 | $6.4469 | <= $15 | PASS |
| Wall | 64.2 min | 47.9 min | 48.9 min | report | PASS |

## Hard Gates

| Gate | Target | Observed | Verdict |
|---|---|---|---|
| HG-5 | UV within +/-1pp of 44.25% | 44.92% | PASS |
| HG-6 | Pathway >=84% | 57 / 63 = 90.5% | PASS |
| HG-7 | iter-2 deg = 0% | 0 iter-2, 0 degraded | PASS |
| HG-8 | Cost <= $15 | $6.4469 | PASS |

## Serialization Round-Trip Check

- File: `data/metagent/w17_path_x_post_schema_extend/path_x_full/compound_only_enrich_mammalian_RAMP_P_000000421_seed5.json`
- `enrichment_carriers` present: True
- Round-trip dict: True
- Carrier keys: metaboanalystr_enrichment_result, mummichog_enrichment_result
