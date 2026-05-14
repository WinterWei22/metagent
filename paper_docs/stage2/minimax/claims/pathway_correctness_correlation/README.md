# Claim Counts vs Pathway Correctness

Claim source: `data/eval/sub6/v4_a3_d3_with_lit/feedback`
Correctness source: `paper_docs/stage2/minimax/semantic/figures/fig10_ground_truth_strict_transition_records.csv`

Tasks: 63
Pathway top-1 correct: 40
Pathway top-1 incorrect: 23

Correctness label is `strict_top1_hit_metagent` from the semantic transition table.

## Main Associations

| feature | mean_correct | mean_incorrect | delta | point_biserial_r | p |
|---|---:|---:|---:|---:|---:|
| pathway_supported | 1.475 | 2.130 | -0.655 | -0.282 | 0.02512 |
| pathway_total_claims | 2.950 | 3.652 | -0.702 | -0.193 | 0.1287 |
| supported_fraction | 0.326 | 0.282 | 0.044 | 0.171 | 0.1804 |
| unverifiable_v0 | 26.750 | 30.217 | -3.467 | -0.153 | 0.231 |
| unverifiable_fraction | 0.606 | 0.643 | -0.037 | -0.143 | 0.2626 |
| pathway_actionable_claims | 0.375 | 0.217 | 0.158 | 0.124 | 0.3335 |
| pathway_unsupported | 0.150 | 0.043 | 0.107 | 0.116 | 0.3635 |
| supported | 13.975 | 12.652 | 1.323 | 0.100 | 0.4343 |
| has_supported_pathway_claim | 0.850 | 0.913 | -0.063 | -0.091 | 0.4774 |
| total_claims | 43.700 | 46.217 | -2.517 | -0.087 | 0.4979 |
| pathway_supported_fraction | 0.551 | 0.613 | -0.062 | -0.085 | 0.5074 |
| unsupported | 2.200 | 2.565 | -0.365 | -0.077 | 0.5495 |
| actionable_claims | 2.975 | 3.348 | -0.373 | -0.072 | 0.5753 |
| actionable_fraction | 0.068 | 0.075 | -0.007 | -0.067 | 0.6041 |
| pathway_unverifiable_v0 | 1.100 | 1.304 | -0.204 | -0.064 | 0.6161 |
| pathway_contradicted | 0.225 | 0.174 | 0.051 | 0.052 | 0.688 |
| contradicted | 0.775 | 0.783 | -0.008 | -0.004 | 0.9756 |

Pathway-prefixed features count only `set_enrichment` / `enrichment_pathway` claims.

Interpretation: positive r means larger values are associated with correct pathway identification; negative r means larger values are associated with incorrect identification.

Generated files:

- `claim_counts_vs_pathway_correctness_by_task.csv`
- `claim_count_correlation_stats.csv`
- `claim_counts_by_pathway_correctness_boxplots.png/.pdf`
- `claim_metric_correlations_with_pathway_correctness.png/.pdf`
- `supported_vs_actionable_by_pathway_correctness.png/.pdf`
