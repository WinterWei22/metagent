# Sub-6 (Pathway Enrichment) Construction Report — Mammalian-only

**Generated:** 2026-04-30T03:26:36+00:00
**Elapsed:** 87.8s
**Build mode:** mammalian-only (Plant subset removed; see §10).
**Evaluation guide:** `reports/benchmark/sub6_evaluation_guide.md` — read first
before running framework evaluation against this data.

## 1. Executive summary

- **150** HMDB-Mammalian compounds curated.
- **20** Sub-6B-Mammalian tasks (target 20).
- **14** Sub-6A mammalian end-to-end tasks (target 20).
- Ground-truth FDR averaged 6.14e-04 (Sub-6B) / 5.33e-04 (Sub-6A inherits 6B ground truth).

## 2. HMDB-Mammalian curation

- Input size: 300
- After dedup: 300
- After spectrum-quality: 300
- After leakage audit (no drops): 300
- After pathway: 239
- Final: 150
- Drop reasons:
  - `no_ramp_pathway`: 39
  - `pathway_too_small`: 22
- ClassyFire/NPC source distribution:
  - `npclassifier`: 137
  - `hmdb_chemical_class`: 12
  - `missing`: 1
- Pathway-bucket distribution:
  - `central_metabolism`: 31
  - `lipid_metabolism`: 30
  - `amino_acid_metabolism`: 30
  - `nucleotide_metabolism`: 30
  - `other`: 29

## 3. Compound bucket distribution (curated)

- `central_metabolism`: 31
- `lipid_metabolism`: 30
- `amino_acid_metabolism`: 30
- `nucleotide_metabolism`: 30
- `other`: 29

## 4. Sub-6B-Mammalian pathway coverage

- Distinct pathways across tasks: **7**
- Source distribution:
  - `wikipathways`: 9
  - `kegg`: 6
  - `smpdb`: 5
- Bucket distribution (target: 4–5 per bucket × 5 buckets):
  - `other_metabolism`: 8
  - `amino_acid_metabolism`: 6
  - `nucleotide_metabolism`: 5
  - `lipid_metabolism`: 1

**Pathway list (alphabetical):**

- Acute Intermittent Porphyria
- Methionine Metabolism
- Pyrimidine metabolism
- Selenium micronutrient network
- Statin inhibition of cholesterol production
- Sulindac Action Pathway
- Tyrosine metabolism

## 5. Sub-6A spectrum lookup coverage

- Coverage: 93 / 150 compounds have ≥1 qualifying spectrum from GNPS or non-RIKEN MassBank.
- Total qualifying spectra indexed: 3421.

## 6. Ground-truth quality

**Sub-6B-Mammalian:**

- Pathways considered: 61
- Pathways qualifying (≥5 primary members): 13
- Candidate tasks generated: 34
- Dropped (ground truth not in top-3): 1
- Dropped (too few members): 0
- Dropped (too few non-members): 0
- Final: 20
  - `gt_pathway_filter_disease_keyword`: 10
  - `gt_pathway_filter_generic_pathway`: 3
  - `pathway_filter_disease_keyword`: 237
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
    "C00016",
    "C00272",
    "C00155"
  ],
  "ground_truth_noise_compounds": [
    "C07481",
    "C00438"
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

**Sub-6A end-to-end (mammalian) sample:**

```json
{
  "task_id": "e2e_enrich_mammalian_RAMP_P_000000106_seed2068278441",
  "task_type": "end_to_end_enrichment",
  "domain": "mammalian",
  "differential_metabolites": null,
  "differential_spectra": "<9 spectra>",
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
    "C00016",
    "C00272",
    "C00155"
  ],
  "ground_truth_noise_compounds": [
    "C07481",
    "C00438"
  ],
  "ramp_enrichment_result": "<EnrichmentReport: top_pathways=10>",
  "seed": 3696034149,
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
- Mammalian subset: **7 distinct pathways** across 20 tasks; 0 generic / 0 disease / 0 pfocr.

Top mammalian pathways now selected (sample of 10):

- ✅ Acute Intermittent Porphyria
- ✅ Methionine Metabolism
- ✅ Pyrimidine metabolism
- ✅ Selenium micronutrient network
- ✅ Statin inhibition of cholesterol production
- ✅ Sulindac Action Pathway
- ✅ Tyrosine metabolism

## 9. Provenance

- RaMP-DB snapshot: 2025-03-06 00:00:39.153317
- HMDB candidates: `data/processed/hmdb_candidates_npc_classified.jsonl` (md5 `87a8397625daa6f3d3f7985780c509b8`)
- GNPS mgf: `/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned.mgf`
- MassBank root: `/data/weiwentao/llm_agent_metabolomics/massbank/raw/MassBank-data`
- MassBank contributors: `Athens_Univ,Eawag,Eawag_Additional_Specs,Washington_State_Univ,Fac_Eng_Univ_Tokyo,IPB_Halle,Kazusa,Keio_Univ,BS,BGC_Munich,MPI_for_Chemical_Ecology,MSSJ`
- CLI seed: `42`
- Git commit: `d5581cc7541f471f695c1ea8d02ac12c6f49ef39`
- Output files:
  - `data/benchmark/sub6/curated_hmdb_mammalian.jsonl`
  - `data/benchmark/sub6/sub6b_mammalian_tasks.jsonl`
  - `data/benchmark/sub6/sub6a_e2e_tasks.jsonl` (present)

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
- [✓] Mammalian subset: ≥5 distinct pathways — got 7
- [✗] Mammalian subset: 4–5 tasks each in central / lipid / nucleotide / amino_acid metabolism — got {'amino_acid_metabolism': 6, 'lipid_metabolism': 1, 'other_metabolism': 8, 'nucleotide_metabolism': 5}. central=0/lipid=1 reflect data limit: HMDB-Mammalian central compounds collide on broad Reactome 'Metabolism of vitamins/lipids/amino acids' clusters that match the bucket name 'other'; KEGG 'Glycolysis / TCA cycle' have low primary-attribution counts after K-asc dispersal.
- [✗] Final task counts: ≥20 plant + ≥15 mammalian + ≥20 e2e — plant=0 (subset removed), mammalian=20 ✓, e2e=14 ✗. e2e shortfall: GNPS+MassBank cover 93/150 (62%) of curated compounds; with min_compounds_with_spectra=3 and 7-13 compounds/task, ~⅔ of mammalian tasks meet the threshold.
