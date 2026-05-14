# CASMI Statistics

Source data: `data/paper_figures/phase6_7c_combined_n378.csv`.

Metrics:
- `acc` = top-1 identification accuracy (`top1_acc_pct` / 100).
- `mrr` = full-set mean reciprocal rank.

Methods:
- MS-CLIP = `msclip_only`
- MS-CLIP + tools weighted = `weighted`
- MS-CLIP + tools + LLM reranking (MetAgent) = `llm_reranker`

Files:
- `casmi2016_2022_acc_mrr_long.csv`: tidy statistics table.
- `casmi2016_2022_acc_mrr_wide.csv`: paper-friendly wide table.
- `casmi2016_2022_significance.csv`: paired Wilcoxon rows for CASMI 2016/2022.
- `casmi_acc_bar.png` / `.svg`: top-1 accuracy grouped bar chart.
- `casmi_mrr_bar.png` / `.svg`: MRR grouped bar chart.

Rerank rank scatter files:
- `casmi_rerank_before_after_gt_ranks.csv`: per-spectrum ground-truth ranks before rerank, after weighted, and after LLM/MetAgent.
- `casmi2016_gt_rank_before_after_scatter.png` / `.svg`: CASMI 2016 before-vs-after LLM rerank scatter.
- `casmi2022_gt_rank_before_after_scatter.png` / `.svg`: CASMI 2022 before-vs-after LLM rerank scatter.

Scatter convention: x-axis is GT rank before rerank under MS-CLIP; y-axis is GT rank after LLM reranking. Smaller rank is better; points above/below the diagonal indicate regression/improvement after accounting for the inverted y-axis. `>20 / NR` means GT was not reachable in top-20.
