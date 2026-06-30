# S6 Build Report

- Input source: `/data/weiwentao/llm_agent_metabolomics/data/landscape/S6_sspa`
- Task output: 0 tasks.
- Reason: ssPA provides COVID example matrices and pathway-analysis utilities, but the landed source does not define a source-level perturbed pathway gold label for COVID vs healthy.
- Guardrail: no pathway task generated from enrichment output or inferred disease biology.

## Example Data Profile

- Su_covid_metabolomics_processed.csv: rows=263, metabolite_columns=333, groups={'Healthy Donor': 133, 'COVID19': 130}, WHO_status={'0': 133, '3-4': 57, '5-7': 28, '1-2': 45}
- Su_metab_data_raw.csv: rows=266, metabolite_columns=1050, groups={'Healthy Donor': 133, 'COVID19': 133}, WHO_status={'0': 133, '3-4': 59, '5-7': 29, '1-2': 45}

## Usable Role

- Keep S6 as pathway database/tool baseline material, not as a task source, unless a future source-level gold pathway rule is explicitly approved.
