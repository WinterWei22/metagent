# Stage2 Benchmark Final Data Snapshot

**Date:** 2026-05-14  
**Scope:** Final Stage2 data used for Sub-6 evaluation

This note records only the final dataset state that matters for writing. It does not describe earlier prototype or intermediate versions.

## 1. Final Dataset Overview

Stage2 benchmark contains two linked datasets:

1. **Sub-6B mammalian tasks**: compound-list tasks for pathway enrichment and narrative generation.
2. **Sub-6A mammalian end-to-end tasks**: spectrum-to-compound-to-pathway tasks built from the same curated compound pool.

The final benchmark data snapshot is:

| asset | count |
|---|---:|
| upstream HMDB candidates | 600 |
| curated HMDB-Mammalian compounds | 250 |
| Sub-6B mammalian tasks | 63 |
| Sub-6A mammalian tasks | 38 |
| unique Sub-6B pathways | 13 |
| Sub-6B lipid tasks | 11 |
| Sub-6B eicosanoid / WP167 tasks | 10 |
| Sub-6A total spectra | 459 |

## 2. Final Curated Pool

The curated HMDB-Mammalian pool is balanced across five buckets:

| bucket | compounds |
|---|---:|
| amino_acid_metabolism | 50 |
| central_metabolism | 50 |
| lipid_metabolism | 50 |
| nucleotide_metabolism | 50 |
| other_metabolism | 50 |

Key curation properties:

- All 250 compounds have valid HMDB provenance and pathway annotations.
- The pool is derived from a 600-compound upstream candidate set.
- NPClassifier annotations are available for nearly all curated compounds, with a small HMDB fallback remainder.

## 3. Final Sub-6B Task Composition

Sub-6B is the pathway-enrichment benchmark. Final task composition is:

| metric | value |
|---|---:|
| tasks | 63 |
| unique pathways | 13 |
| unique pathway buckets | 5 |
| minimum unique signal compounds per task | 5 |
| duplicate task IDs | 0 |
| duplicate signal IDs | 0 |
| ground-truth pathway in RaMP top-3 | 63/63 |
| pfocr ground-truth pathways | 0/63 |

Bucket distribution:

| bucket | tasks |
|---|---:|
| other_metabolism | 20 |
| amino_acid_metabolism | 20 |
| lipid_metabolism | 11 |
| central_metabolism | 10 |
| nucleotide_metabolism | 2 |

Pathway-level note:

- The lipid bucket is dominated by one LIPID MAPS pathway, `WP167` (`Eicosanoid synthesis`), which accounts for 10 of the 11 lipid tasks.
- The remaining lipid task is the steroid pathway task retained from the RaMP-backed set.
- This means lipid coverage improved at the task level, but not as a broad pathway-diversity expansion.

## 4. Final Sub-6A Task Composition

Sub-6A is the end-to-end spectrum benchmark. Final task composition is:

| metric | value |
|---|---:|
| tasks | 38 |
| total spectra | 459 |
| spectra per task mean | 12.079 |
| spectra per task min | 4 |
| spectra per task max | 23 |
| unique compounds represented | 95 |

Spectrum source breakdown:

| source | n_spectra |
|---|---:|
| GNPS | 323 |
| MassBank-non-RIKEN | 69 |
| MoNA | 58 |
| other sources | 9 |

The final Sub-6A tasks satisfy the construction gate that each task must contain at least 3 compounds with spectra.

## 5. Final Stage2 Quality Gates

| gate | result |
|---|---:|
| Sub-6B ground-truth pathway in RaMP enrichment top-3 | 63/63 |
| Sub-6B no pfocr pathways | 63/63 |
| Sub-6B min unique signal compounds | 5 |
| Sub-6B duplicate task IDs | 0 |
| Sub-6B duplicate signal IDs | 0 |
| Sub-6A tasks with at least 3 compounds with spectra | 38/38 |
| NM-002 exclusion list available for Sub-6A runtime filtering | yes |

## 6. What the Final Data Says

The final Stage2 dataset is large enough to support both pathway-level and end-to-end evaluation, with the following practical properties:

- Sub-6B has sufficient task volume for aggregate narrative/verifier analysis.
- Sub-6A has enough spectra to demonstrate end-to-end identification, but GNPS remains the dominant source.
- Lipid coverage is materially improved relative to the earlier benchmark, but the lipid bucket is still concentrated in one eicosanoid axis.
- The curated pool is balanced, which makes bucket-level comparison feasible at the compound level even when task-level coverage is uneven.

## 7. Files

| file | purpose |
|---|---|
| `data/processed/hmdb_candidates_npc_classified_v2.jsonl` | upstream 600-compound candidate pool |
| `data/benchmark/sub6/curated_hmdb_mammalian_v3.jsonl` | final curated compound pool |
| `data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl` | final Sub-6B task set |
| `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl` | final validated Sub-6A task set |

## 8. Writing Guidance

For paper text, the most useful framing is:

1. Stage2 uses a 600-compound upstream pool and a 250-compound balanced curated pool.
2. Final Sub-6B contains 63 tasks across 13 pathways, with 11 lipid tasks and 10 eicosanoid tasks.
3. Final Sub-6A contains 38 end-to-end tasks and 459 spectra, mostly from GNPS.
4. The data are constructed with strict pathway and leakage gates, so the benchmark is not just larger but cleaner.

