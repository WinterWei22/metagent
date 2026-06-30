# S1 Rule Sensitivity Report

This is a decision-support analysis only. It does not modify `build/tasks_s1.jsonl`.

## Summary

- D1_v1_current: candidates=2, gold_source=unique_gene_kegg_or_unique_kegg_supported_by_ev3_clr, min_metabolites=5, max_ev4_rank=2
- D1_candidate_gene_kegg_min3: candidates=4, gold_source=unique_gene_kegg_or_unique_kegg_supported_by_ev3_clr, min_metabolites=3, max_ev4_rank=2
- D1_candidate_paper_clr_min5: candidates=9, gold_source=unique_significant_ev3_clr_pathway, min_metabolites=5, max_ev4_rank=2
- D1_candidate_paper_clr_min3: candidates=23, gold_source=unique_significant_ev3_clr_pathway, min_metabolites=3, max_ev4_rank=2
- D1_candidate_paper_clr_rank3_min3: candidates=23, gold_source=unique_significant_ev3_clr_pathway, min_metabolites=3, max_ev4_rank=3
- D1_highrisk_top_paper_clr_min5: candidates=216, gold_source=top_significant_ev3_clr_pathway, min_metabolites=5, max_ev4_rank=2
- D1_highrisk_top_paper_clr_min3: candidates=357, gold_source=top_significant_ev3_clr_pathway, min_metabolites=3, max_ev4_rank=2

## Interpretation

- `D1_v1_current` is the current strict rule used for official S1 tasks.
- `unique_significant_ev3_clr_pathway` variants rely on Fuhrer EV3 pathway-by-CLR output as the gold source and therefore require manual approval before task generation.
- `top_significant_ev3_clr_pathway` variants are explicitly high-risk: they choose a top pathway even when multiple significant CLR pathways exist.
- Candidate rows are written to `build/s1_candidate_review.tsv` for manual audit.
