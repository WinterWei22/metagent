# Sub-6B Mammalian Construction Report v2

**Generated:** 2026-05-06  
**Branch:** `feature/sub6-v2-expand-pool`  
**Build mode:** Sub-6B mammalian only; Sub-6A skipped with `--skip-spectrum-index`.  
**HMDB candidate pool:** `data/processed/hmdb_candidates_npc_classified_v2.jsonl` (600 rows; 120 per bucket).

## 1. Summary

| metric | v1 | v2 |
|---|---:|---:|
| curated HMDB compounds | 150 | 250 |
| Sub-6B mammalian tasks | 20 | 63 |
| unique pathways covered | 7 | 13 |
| unique pathway buckets covered | 4 | 5 |
| candidate pool rows | 300 | 600 |
| unique KEGG IDs in candidate pool | 245 | 526 |

v2 did not reach the planned 100 tasks, but it is above the fallback acceptance
range. It is accepted as the current realistic ceiling for the 600-compound HMDB
pool. The pool-300 ablation output is preserved as
`data/benchmark/sub6/sub6b_mammalian_tasks_v2_pool300.jsonl` (35 tasks).

## 2. Bucket Distribution

| bucket | v1 tasks | v2 tasks | delta |
|---|---:|---:|---:|
| amino_acid_metabolism | 6 | 20 | +14 |
| central_metabolism | 0 | 10 | +10 |
| lipid_metabolism | 1 | 1 | 0 |
| nucleotide_metabolism | 5 | 2 | -3 |
| other_metabolism | 8 | 30 | +22 |

The expanded pool restored central metabolism task coverage. Lipid and
nucleotide remain thin after task-stage mammalian pathway filtering and top-3
enrichment validation.

## 3. Pathway Distribution

| tasks | pathway_id | bucket | source | pathway |
|---:|---|---|---|---|
| 10 | RAMP_P_000050021 | other_metabolism | reactome | Biological oxidations |
| 10 | RAMP_P_000000203 | other_metabolism | smpdb | Cerivastatin Action Pathway |
| 10 | RAMP_P_000000398 | central_metabolism | kegg | Galactose Metabolism |
| 9 | RAMP_P_000000141 | amino_acid_metabolism | kegg | Tryptophan metabolism |
| 7 | RAMP_P_000000421 | other_metabolism | kegg | Androgen and Estrogen Metabolism |
| 6 | RAMP_P_000000016 | amino_acid_metabolism | kegg | Glycine, serine and threonine metabolism |
| 4 | RAMP_P_000000106 | amino_acid_metabolism | kegg | Tyrosine metabolism |
| 2 | RAMP_P_000053306 | nucleotide_metabolism | wikipathways | Pyrimidine metabolism |
| 1 | RAMP_P_000025682 | other_metabolism | smpdb | Celecoxib Action Pathway |
| 1 | RAMP_P_000050096 | amino_acid_metabolism | reactome | Metabolism of amino acids and derivatives |
| 1 | RAMP_P_000050099 | other_metabolism | reactome | Pyrimidine catabolism |
| 1 | RAMP_P_000053042 | lipid_metabolism | wikipathways | Steroid biosynthesis |
| 1 | RAMP_P_000052855 | other_metabolism | wikipathways | Sulfatase and aromatase pathway |

Top 5 pathways account for 46/63 tasks. Six pathways have only one task, so
per-pathway statistics should not be reported for the tail.

## 4. Quality Gates

| gate | acceptance | result | status |
|---|---:|---:|---|
| ground_truth_pathway in RaMP enrichment top-3 | 100% | 63/63 | PASS |
| no pfocr pathway | 100% | 0/63 pfocr | PASS |
| signal compound count >= 3 per task | 100% | min unique signal = 5 | PASS |
| noise compound count >= 0 per task | 100% | min noise = 2 | PASS |
| duplicate_task_ids == 0 | 100% | 0 | PASS |
| tasks_with_duplicate_signal_ids == 0 | 100% | 0 | PASS |
| min_unique_signal >= 3 across all tasks | 100% | 5 | PASS |

The duplicate-signal bug observed in the pool-300 run is fixed in v2: signal
sampling now deduplicates by KEGG ID first, then InChIKey first-block.

## 5. Curation Stats

| step | count |
|---|---:|
| input HMDB candidates | 600 |
| valid SMILES / deduped first-blocks | 600 |
| with non-pfocr RaMP pathway after re-resolution | 528 |
| pass pathway_min_compounds gate | 524 |
| final curated sample | 250 |

Drop reasons:

| reason | count |
|---|---:|
| no_ramp_pathway | 72 |
| pathway_too_small | 4 |

Curated compound bucket distribution is perfectly balanced at 50 per bucket:
central, lipid, nucleotide, amino acid, and other.

## 6. Provenance

| field | value |
|---|---|
| git commit SHA | `06f0f21397faab244916c67bc0ac112ba06d040c` |
| raw build report | `reports/benchmark/sub6_construction_report_v2_raw.md` |
| raw build wall time | 139.8s |
| curated v2 MD5 | `2a8a9f35e8cf84a9c1e2a452eb00561e` |
| Sub-6B tasks v2 MD5 | `23594c0a3c6ab7a906baad1e0cd622dc` |
| HMDB candidate pool v2 MD5 | `8824f112a1a63e2f91fcc451ce157244` |

Build command:

```bash
PYTHONPATH=. python scripts/build_sub6/build_all.py \
    --hmdb-candidates data/processed/hmdb_candidates_npc_classified_v2.jsonl \
    --target-6b-mammalian 100 \
    --target-curated-hmdb 250 \
    --pathway-min-compounds 3 \
    --tasks-per-pathway-max 10 \
    --tasks-per-bucket-max 20 \
    --output-dir data/benchmark/sub6/ \
    --report-path reports/benchmark/sub6_construction_report_v2_raw.md \
    --skip-spectrum-index \
    --seed 42
```

Note: the raw report's task-stats label still says "Pathways qualifying (>=5
primary members)" in prose, but this build passed `--pathway-min-compounds 3`;
the value reported there is from the v2 run with threshold 3.

## 7. Known Limitations

- Target 100 tasks was not reached; final accepted ceiling is 63 tasks.
- Lipid metabolism has only 1 task and nucleotide metabolism has 2 tasks, so
  those buckets are not suitable for bucket-level statistics.
- Six pathways have only one task and should be treated as pathway-coverage
  examples, not per-pathway performance strata.
- Central metabolism recovered to 10 tasks after pool expansion, but coverage
  is concentrated in Galactose Metabolism.
- Plant subset remains out of scope. The benchmark intentionally does not add a
  plant subset because prior analysis found non-pfocr RaMP coverage insufficient
  for defensible plant ground truth.

## 8. Acceptance Check

| check | status |
|---|---|
| `data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl` exists and has >= 200 rows | PASS |
| `data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl` exists and has >= 50 rows | PASS |
| v1 curated file restored at original path with 150 rows | PASS |
| v1 Sub-6B task file restored at original path with 20 rows | PASS |
| v1 Sub-6A task file restored at original path with 14 rows | PASS |
| pool-300 ablation preserved with 35 tasks | PASS |
| all D4 quality gates pass | PASS |
| Sub-6A spectrum index skipped | PASS |
