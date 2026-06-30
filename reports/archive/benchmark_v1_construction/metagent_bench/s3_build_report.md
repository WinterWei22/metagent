# S3 Build Report

- Input source: `/data/weiwentao/llm_agent_metabolomics/data/landscape/S3_ST001142_CCLE_IDH`
- Task output: 1 hard tasks.
- Rule: only IDH1/IDH2 hotspot mutation task is allowed; no broad pan-cancer mutation expansion.
- Guardrail: genotype labels come from DepMap hotspot file, not from 2-hydroxyglutarate abundance.
- Status: complete

## Label Source

- DepMap 22Q2 Public Figshare article 19700056, CC BY 4.0.
- Downloaded files: `sample_info.csv` and `CCLE_mutations_bool_hotspot.csv`; full `CCLE_mutations.csv` was not downloaded because it is >200 MB.

## Signal Summary

- Mutant samples aligned to ST001142: 7
- Wild-type/non-hotspot samples aligned to ST001142: 921
- 2-hydroxyglutarate row: {"hmdb_id": "HMDB00694", "log2FC": 6.098708473227608, "metabolite_name": "2-hydroxyglutarate", "mutant_median": 20466021.0, "mutant_n": 7, "wildtype_median": 298633.0, "wildtype_n": 921}
