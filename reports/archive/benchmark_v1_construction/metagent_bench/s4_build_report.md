# S4 Build Report

- Input source: `/data/weiwentao/llm_agent_metabolomics/data/landscape/S4_cooke_2025`
- Rule: one easy task per simulated Human1 or Recon2.2 pathway column with state `able_to_run` or `unable_to_run_ORA`.
- Metabolite mapping: z-score source IDs mapped through model-specific `metab_dict.tsv`; top 25 absolute z-score mapped metabolites retained.
- Minimum mapped metabolites per task: 8
- Tasks generated: 181

## Counters

- unmapped_zscore_id: 113709
- Human1:tasks: 117
- Human1:included_state:unable_to_run_ORA: 66
- Recon2.2:tasks: 64
- Human1:included_state:able_to_run: 51
- Recon2.2:included_state:able_to_run: 34
- Recon2.2:included_state:unable_to_run_ORA: 30
- excluded_state:blocked: 14
- excluded_state:removed_but_ran: 4
