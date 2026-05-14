# MetAgent D3 v4 Internal Feedback Iteration Changes

Input: `data/eval/sub6/v4_a3_d3_with_lit/feedback`

This file compares `result.json` internal iteration 0 against the selected final narrative from the same feedback run, plus final `verdict.json` rescoring. It is not the Phase A3 audit pipeline comparison (`react` -> `fb_nolit` -> `+literature`).

Tasks: 63

## Verdict Totals

| verdict | before_iter0 | final_selected_internal | final_verdict_json | delta_json_minus_before |
|---|---:|---:|---:|---:|
| supported | 781 | 826 | 850 | 69 |
| unsupported | 271 | 119 | 147 | -124 |
| contradicted | 76 | 40 | 49 | -27 |
| unverifiable_v0 | 1977 | 1817 | 1765 | -212 |

## Actionable Claim Quality

Quality is `unsupported + contradicted`; lower is better.

Using selected final iteration's internal verifier total:

- Improved tasks: 47
- Unchanged tasks: 16
- Worsened tasks: 0
- Total before quality: 347
- Total final quality: 159
- Delta quality: -188

Using final `verdict.json` rescoring:

- Improved tasks: 47
- Unchanged tasks: 6
- Worsened tasks: 10
- Total final rescored quality: 196
- Delta rescored quality: -151

## Pathway Identification

Pathway names/IDs are extracted from iter-0 and final selected narratives with regex heuristics; final verifier pathway claims are included in the CSV as a check.

- Tasks with changed extracted pathway identification: 20
- Tasks unchanged: 43

Key files:

- `feedback_verdict_counts_by_task_phase.csv`
- `feedback_change_summary_by_task.csv`
- `pathway_identification_by_task_phase.csv`
- `verdict_totals_before_after.png/.pdf`
- `verdict_delta_totals.png/.pdf`
- `total_claims_before_after.png/.pdf`
- `verdict_composition_percent_before_after.png/.pdf`
- `quality_before_after_scatter.png/.pdf`
- `pathway_identification_changed_counts.png/.pdf`
