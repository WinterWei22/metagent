# MetAgent D3 v4 Claim Distribution

Input: `data/eval/sub6/v4_a3_d3_with_lit/feedback`

Tasks: 63
Claims: 2811

## Verdict Totals

| verdict | n | pct |
|---|---:|---:|
| supported | 850 | 30.2% |
| unsupported | 147 | 5.2% |
| contradicted | 49 | 1.7% |
| unverifiable_v0 | 1765 | 62.8% |

## Claim Type Totals

| claim_type | n | pct | supported | unsupported | contradicted | unverifiable_v0 |
|---|---:|---:|---:|---:|---:|---:|
| biological_claim | 1604 | 57.1% | 712 | 140 | 4 | 748 |
| factual_roundtrip_claim | 502 | 17.9% | 0 | 0 | 0 | 502 |
| grounded_claim | 263 | 9.4% | 0 | 0 | 0 | 263 |
| set_enrichment | 202 | 7.2% | 108 | 7 | 13 | 74 |
| consistency_claim | 106 | 3.8% | 0 | 0 | 30 | 76 |
| pathway_relationship | 64 | 2.3% | 17 | 0 | 0 | 47 |
| driver_metabolite | 39 | 1.4% | 13 | 0 | 2 | 24 |
| literature_claim | 31 | 1.1% | 0 | 0 | 0 | 31 |

Figures:

- `claim_type_by_verdict_counts.png/.pdf`
- `claim_type_by_verdict_percent.png/.pdf`
- `claim_subtype_by_verdict_counts.png/.pdf`
- `per_task_claim_type_boxplot.png/.pdf`
