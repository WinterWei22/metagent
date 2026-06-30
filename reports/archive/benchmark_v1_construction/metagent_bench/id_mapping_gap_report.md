# ID Mapping Gap Report

- Dataset: `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/build/metagent_bench.jsonl`
- Mapping status: blocked_without_refmet_ramp_for_canonical_unification

## Local Mapping Resources

- RefMet: not found
- RaMP: not found
- metLinkR: not found
- Huckvale_2023_KEGG_benchmark: present

## Metabolite ID Mentions

- Human1: 2925 mentions across 117 tasks; needs mapping
- Recon2.2: 1600 mentions across 64 tasks; needs mapping
- HMDB: 15 mentions across 1 tasks; canonical-or-source-standard
- KEGG: 14 mentions across 2 tasks; canonical-or-source-standard

## Pathway Ontologies

- Human1: 117 tasks; model-specific; needs crosswalk
- Recon2.2: 64 tasks; model-specific; needs crosswalk
- KEGG: 3 tasks; canonical-or-target

## Required Next Mapping Work

- Add or connect RefMet and RaMP resources before claiming full canonical ID unification.
- Map Human1 and Recon2.2 metabolite IDs to common compound IDs, retaining original model IDs in provenance.
- Map Human1 and Recon2.2 pathway labels to the selected pathway ontology or mark them as model-specific easy tasks.
- Keep S1/S3 KEGG/HMDB hard tasks unchanged until a deterministic crosswalk is available.
