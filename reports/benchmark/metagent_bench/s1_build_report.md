# S1 Build Report

- Input source: `/data/weiwentao/llm_agent_metabolomics/data/landscape/S1_fuhrer_sauer_2017`
- Rule: D1_v1, gold pathway from public KEGG eco gene-pathway mapping; multi-pathway genes are kept only when Fuhrer EV3 CLR has exactly one significant pathway matching the gene's allowed KEGG memberships.
- Differential metabolite filter: KEGG C ID, EV3 AUC >= 0.7, abs(Z-score) >= 3.0, EV4 rank <= 2, EV4 AUC >= 0.7.
- Structured high-confidence genes/tasks: 2
- Lower-bound check (>=80): fail

## Exclusions

- ambiguous_or_missing_gold_pathway:0: 1202
- ambiguous_or_missing_gold_pathway:2: 34
- ambiguous_or_missing_gold_pathway:3: 12
- ambiguous_or_missing_gold_pathway:4: 8
- ambiguous_or_missing_gold_pathway:5: 3
- too_few_high_conf_metabolites:0: 3
- too_few_high_conf_metabolites:1: 3
- ambiguous_or_missing_gold_pathway:8: 2
- too_few_high_conf_metabolites:4: 1
- too_few_high_conf_metabolites:2: 1
- too_few_high_conf_metabolites:3: 1
- ambiguous_or_missing_gold_pathway:13: 1

## Gate Result

S1 did not reach 80 high-confidence hard tasks under the conservative D1_v1 thresholds. The script did not relax thresholds to inflate count.
