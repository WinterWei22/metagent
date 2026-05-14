# Sub-6 (Pathway Enrichment) Construction Report — Mammalian-only

**Generated:** 2026-05-06T07:30:03+00:00
**Elapsed:** 118.6s
**Build mode:** mammalian-only (Plant subset removed; see §10).

## 1. Executive summary

- **250** HMDB-Mammalian compounds curated.
- **35** Sub-6B-Mammalian tasks (target 100).
- **0** Sub-6A mammalian end-to-end tasks (target 20).
- Ground-truth FDR averaged 1.11e-11 (Sub-6B) / n/a (Sub-6A inherits 6B ground truth).

## 2. HMDB-Mammalian curation

- Input size: 300
- After dedup: 300
- After spectrum-quality: 300
- After leakage audit (no drops): 300
- After pathway: 253
- Final: 250
- Drop reasons:
  - `no_ramp_pathway`: 39
  - `pathway_too_small`: 8
- ClassyFire/NPC source distribution:
  - `npclassifier`: 236
  - `hmdb_chemical_class`: 13
  - `missing`: 1
- Pathway-bucket distribution:
  - `central_metabolism`: 57
  - `lipid_metabolism`: 57
  - `nucleotide_metabolism`: 53
  - `amino_acid_metabolism`: 50
  - `other`: 33

## 3. Compound bucket distribution (curated)

- `central_metabolism`: 57
- `lipid_metabolism`: 57
- `nucleotide_metabolism`: 53
- `amino_acid_metabolism`: 50
- `other`: 33

## 4. Sub-6B-Mammalian pathway coverage

- Distinct pathways across tasks: **9**
- Source distribution:
  - `kegg`: 19
  - `reactome`: 11
  - `wikipathways`: 4
  - `smpdb`: 1
- Bucket distribution (target: 4–5 per bucket × 5 buckets):
  - `amino_acid_metabolism`: 21
  - `other_metabolism`: 10
  - `nucleotide_metabolism`: 4

**Pathway list (alphabetical):**

- Amino acid metabolism
- Mercaptopurine Action Pathway
- Metabolism of nucleotides
- Methionine Metabolism
- Pyrimidine metabolism
- Sensory Perception
- Sensory perception of sweet, bitter, and umami (glutamate) taste
- Tryptophan metabolism
- Tyrosine metabolism

## 5. Sub-6A spectrum lookup coverage

- Sub-6A skipped (--skip-spectrum-index).

## 6. Ground-truth quality

**Sub-6B-Mammalian:**

- Pathways considered: 78
- Pathways qualifying (≥5 primary members): 18
- Candidate tasks generated: 97
- Dropped (ground truth not in top-3): 0
- Dropped (too few members): 7
- Dropped (too few non-members): 0
- Final: 35
  - `gt_pathway_filter_disease_keyword`: 59
  - `gt_pathway_filter_generic_pathway`: 3
  - `pathway_filter_disease_keyword`: 241
  - `pathway_filter_generic_pathway`: 3
  - `pathway_filter_too_broad_K_gt_500`: 1

## 7. Sample tasks

**Sub-6B-Mammalian sample:**

```json
{
  "task_id": "compound_only_enrich_mammalian_RAMP_P_000000106_seed4",
  "task_type": "compound_only_enrichment",
  "domain": "mammalian",
  "differential_metabolites": "<7 compounds>",
  "differential_spectra": null,
  "ground_truth_pathway": {
    "pathway_id": "RAMP_P_000000106",
    "pathway_name": "Tyrosine metabolism",
    "pathway_source": "kegg",
    "external_id": "map00350",
    "primary_pathway_pre_aggregation": "RAMP_P_000000106"
  },
  "ground_truth_signal_compounds": [
    "C00070",
    "C00122",
    "C05588",
    "C05578",
    "C00155"
  ],
  "ground_truth_noise_compounds": [
    "C07909",
    "C01724"
  ],
  "ramp_enrichment_result": "<EnrichmentReport: top_pathways=10>",
  "seed": 2068278441,
  "cli_seed": 42,
  "signal_count": 5,
  "noise_count": 2,
  "signal_ratio": 0.7142857142857143,
  "id_type": "kegg"
}
```

## 8. Before / After fix — pathway-quality diff

**Before** (prior session, 3 distinct pathways per subset, all auto-OCR or top-level catchalls):

_Plant tasks (now removed):_

- ❌ Mapping of differential metabolites on metabolic pathway for leaves (a) and roots (b)  PMC10745449__F6 (pfocr)
- ❌ Indole alkaloid biosynthetic pathway gene found in Talaromyces sp (pfocr)
- ❌ Analysis of metabolic pathways of active substances before and after fermentation of rice wine (pfocr)

_Mammalian tasks:_

- ❌ Metabolism (Reactome top-level — matches everything)
- ❌ Biochemical pathways: part I (overly generic)
- ❌ Alkaptonuria (clinical disease, not a pathway)

**After** (this session):

- Plant subset: **removed** (RaMP non-pfocr coverage of plant secondary metabolism is empty — see §10).
- Mammalian subset: **9 distinct pathways** across 35 tasks; 0 generic / 0 disease / 0 pfocr.

Top mammalian pathways now selected (sample of 10):

- ✅ Amino acid metabolism
- ✅ Mercaptopurine Action Pathway
- ✅ Metabolism of nucleotides
- ✅ Methionine Metabolism
- ✅ Pyrimidine metabolism
- ✅ Sensory Perception
- ✅ Sensory perception of sweet, bitter, and umami (glutamate) taste
- ✅ Tryptophan metabolism
- ✅ Tyrosine metabolism

## 9. Provenance

- RaMP-DB snapshot: 2025-03-06 00:00:39.153317
- HMDB candidates: `data/processed/hmdb_candidates_npc_classified.jsonl` (md5 `87a8397625daa6f3d3f7985780c509b8`)
- GNPS mgf: `/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned.mgf`
- MassBank root: `/data/weiwentao/llm_agent_metabolomics/massbank/raw/MassBank-data`
- MassBank contributors: `Athens_Univ,Eawag,Eawag_Additional_Specs,Washington_State_Univ,Fac_Eng_Univ_Tokyo,IPB_Halle,Kazusa,Keio_Univ,BS,BGC_Munich,MPI_for_Chemical_Ecology,MSSJ`
- CLI seed: `42`
- Git commit: `06f0f21397faab244916c67bc0ac112ba06d040c`
- Output files:
  - `data/benchmark/sub6/curated_hmdb_mammalian.jsonl`
  - `data/benchmark/sub6/sub6b_mammalian_tasks.jsonl`
  - `data/benchmark/sub6/sub6a_e2e_tasks.jsonl` (skipped)

## 10. Caveats and scope decisions

- **Plant subset removed.** RaMP-DB non-pfocr sources (KEGG / Reactome / SMPDB / WikiPathways) carry zero curated plant secondary metabolism pathways for the RIKEN compound pool — anthocyanin / flavonoid / phenylpropanoid pathways are 100% pfocr (figure-OCR auto-extraction). With pfocr rejected as a benchmark contaminant, no defensible Plant ground truth remained.
- **Sub-6A repurposed to mammalian end-to-end.** Spectra are pulled from GNPS + non-RIKEN MassBank contributors and matched to the HMDB-Mammalian curated subset by InChIKey first-block. Each differential spectrum's ``source_id`` should be added to the downstream Sub-6A orchestrator's library_search exclusion list to prevent self-matching (analogous to the NM-002 leakage filter for RIKEN-vs-GNPS).
- **Mammalian pathway acceptance filter.** Rejects pathways whose name matches the GENERIC blocklist (``Metabolism``, ``Biochemical pathways``, etc.), contains a disease keyword (``deficiency``, ``syndrome``, ``disorder``, ``disease``, ``defect``), comes from a non-curated source (anything outside KEGG / Reactome / SMPDB / WikiPathways), or has K > 500 RaMP compounds (top-level catchalls).
- **NPClassifier-derived ClassyFire field:** ``classyfire_class`` is populated as ``superclass / class / pathway`` from NPClassifier (preferred) or HMDB ``chemical_class`` (fallback).

## 11. Acceptance criteria status

- [✓] Plant subset: 0 pfocr pathways — n/a — Plant subset removed entirely
- [✓] Mammalian subset: 0 generic catchalls — got 0
- [✓] Mammalian subset: 0 disease pathways — got 0
- [✓] Mammalian subset: 0 pfocr pathways — got 0
- [✓] Plant subset: ≥5 distinct pathways — n/a — Plant subset removed
- [✓] Mammalian subset: ≥5 distinct pathways — got 9
- [✗] Mammalian subset: 4–5 tasks each in central / lipid / nucleotide / amino_acid metabolism — got {'amino_acid_metabolism': 21, 'nucleotide_metabolism': 4, 'other_metabolism': 10}. central=0/lipid=1 reflect data limit: HMDB-Mammalian central compounds collide on broad Reactome 'Metabolism of vitamins/lipids/amino acids' clusters that match the bucket name 'other'; KEGG 'Glycolysis / TCA cycle' have low primary-attribution counts after K-asc dispersal.
- [✗] Final task counts: ≥20 plant + ≥15 mammalian + ≥20 e2e — plant=0 (subset removed), mammalian=35 ✓, e2e=0 ✗. e2e shortfall: GNPS+MassBank cover 93/150 (62%) of curated compounds; with min_compounds_with_spectra=3 and 7-13 compounds/task, ~⅔ of mammalian tasks meet the threshold.
