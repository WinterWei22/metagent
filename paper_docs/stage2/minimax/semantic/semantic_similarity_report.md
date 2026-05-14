# SapBERT Semantic Pathway Accuracy

Model: `cambridgeltl/SapBERT-from-PubMedBERT-fulltext`. The score is cosine similarity between the first extracted pathway mention and the ground-truth/top-k pathway names after SapBERT encoding.

Thresholded semantic hits are reported at several cutoffs; `@0.80` is the default operating point for quick comparison, not a biologically calibrated boundary.

## D3 Full 63-Task

| dataset | n | strict top1 | sem GT mean | sem GT @0.80 | sem top3 @0.80 | sem top10 @0.80 |
|---|---:|---:|---:|---:|---:|---:|
| d3_llm_single_no_lit | 63 | 30.16% | 0.6241 | 25.40% | 31.75% | 36.51% |
| d3_llm_single_with_lit | 63 | 26.98% | 0.5756 | 17.46% | 28.57% | 44.44% |
| d3_metagent_no_lit | 63 | 65.08% | 0.7871 | 63.49% | 79.37% | 80.95% |
| d3_metagent_with_lit | 63 | 63.49% | 0.7950 | 63.49% | 84.13% | 85.71% |

## D3.5 Rerun CI

Mean +/- CI95 across run1/run2/run3 rates on the 10-task subset.

| dataset | semantic GT @0.80 | semantic top3 @0.80 | semantic GT mean score |
|---|---:|---:|---:|
| d3_5_single_no_lit | 30.00% +/- 24.84% | 30.00% +/- 24.84% | 0.6477 +/- 0.1546 |
| d3_5_single_with_lit | 33.33% +/- 14.34% | 36.67% +/- 28.69% | 0.6393 +/- 0.1804 |
| d3_5_feedback_no_lit | 76.67% +/- 14.34% | 80.00% +/- 24.84% | 0.8803 +/- 0.0682 |
| d3_5_feedback_with_lit | 70.00% +/- 24.84% | 76.67% +/- 14.34% | 0.8477 +/- 0.1850 |
