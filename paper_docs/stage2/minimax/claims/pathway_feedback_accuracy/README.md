# Pathway Accuracy Before vs After Feedback

Before feedback: `d3_metagent_wo_feedback_no_lit` as `MetAgent-ReAct`
After feedback: `d3_metagent_with_lit` as `MetAgent-feedback`

This follows the three-model paper/audit-aligned architecture framing: `MetAgent-single`, `MetAgent-ReAct`, `MetAgent-feedback`.

| metric | before | after | delta | corrected | lost | kept_correct | kept_incorrect | McNemar exact p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Strict GT top-1 | 40/63 (63.5%) | 40/63 (63.5%) | 0 (+0.0 pp) | 11 | 11 | 29 | 12 | 1 |
| Strict top-3 | 46/63 (73.0%) | 53/63 (84.1%) | 7 (+11.1 pp) | 13 | 6 | 40 | 4 | 0.1671 |
| Semantic GT >= 0.80 | 40/63 (63.5%) | 40/63 (63.5%) | 0 (+0.0 pp) | 11 | 11 | 29 | 12 | 1 |
| Semantic top-3 >= 0.80 | 45/63 (71.4%) | 53/63 (84.1%) | 8 (+12.7 pp) | 14 | 6 | 39 | 4 | 0.1153 |
| Semantic top-10 >= 0.80 | 48/63 (76.2%) | 54/63 (85.7%) | 6 (+9.5 pp) | 12 | 6 | 42 | 3 | 0.2379 |

Mean semantic GT similarity: 0.791 -> 0.795 (delta +0.004).

Generated files:

- `pathway_accuracy_feedback_summary.csv`
- `pathway_accuracy_feedback_transitions.csv`
- `pathway_accuracy_feedback_paired_tasks.csv`
- `pathway_accuracy_before_after_feedback.png/.pdf`
- `pathway_accuracy_transition_counts.png/.pdf`
- `semantic_gt_similarity_delta_after_feedback.png/.pdf`
