# Sub-6A v2 Construction Audit

**Generated:** 2026-05-06  
**Session:** `track_BENCH_sub6_v2_phase2_e2e`  
**Build mode:** Sub-6A mammalian end-to-end, using Sub-6B v2 construction parameters and expanded HMDB pool.

## 1. Summary

| metric | v1 | v2 |
|---|---:|---:|
| Sub-6A tasks | 14 | 38 |
| total spectra | 128 | 459 |
| spectra/task mean | 9.143 | 12.079 |
| spectra/task min | 5 | 4 |
| spectra/task max | 12 | 23 |
| unique compounds represented in Sub-6A spectra | 43 | 95 |
| HMDB curated compounds covered by spectrum index | 93/150 | 168/250 |
| spectrum index total spectra | 3421 | 5756 |

v2 reaches 38/40 requested Sub-6A tasks with `--min-compounds-with-spectra 3`.
No threshold relaxation was needed.

## 2. Spectrum Source Breakdown

Full spectrum index coverage over the 250 curated HMDB v2 compounds:

| source | n_spectra | n_compounds_covered |
|---|---:|---:|
| GNPS | 5720 | 165 |
| MassBank-non-RIKEN | 36 | 8 |

Spectra actually sampled into the 38 Sub-6A v2 tasks:

| source | n_spectra | n_compounds_used |
|---|---:|---:|
| GNPS | 447 | 94 |
| MassBank-non-RIKEN | 12 | 1 |

MassBank adds little unique compound coverage for this specific v2 task set,
but it is retained because it is non-RIKEN and leakage-compatible.

## 3. Per-Task Spectrum Count Distribution

| spectra per task | n_tasks |
|---:|---:|
| 4 | 1 |
| 5 | 1 |
| 6 | 1 |
| 7 | 3 |
| 8 | 2 |
| 9 | 4 |
| 10 | 4 |
| 12 | 4 |
| 13 | 6 |
| 14 | 1 |
| 15 | 3 |
| 16 | 1 |
| 17 | 2 |
| 18 | 3 |
| 19 | 1 |
| 23 | 1 |

Every retained task has at least 3 unique compounds with spectra. The observed
range is 3 to 10 compounds with spectra per task, with mean 6.868.

## 4. Coverage Gaps

Full index coverage by curated compound bucket:

| bucket | curated compounds | compounds covered | uncovered |
|---|---:|---:|---:|
| central_metabolism | 50 | 40 | 10 |
| lipid_metabolism | 50 | 39 | 11 |
| nucleotide_metabolism | 50 | 32 | 18 |
| amino_acid_metabolism | 50 | 25 | 25 |
| other | 50 | 32 | 18 |

Unique compounds actually used in Sub-6A v2 spectra by curated bucket:

| bucket | compounds used in v2 tasks |
|---|---:|
| central_metabolism | 25 |
| lipid_metabolism | 27 |
| nucleotide_metabolism | 20 |
| amino_acid_metabolism | 8 |
| other | 15 |

Task bucket distribution for Sub-6A v2:

| bucket | n_tasks |
|---|---:|
| other_metabolism | 18 |
| central_metabolism | 10 |
| amino_acid_metabolism | 7 |
| nucleotide_metabolism | 2 |
| lipid_metabolism | 1 |

Spectrum coverage is not the main bottleneck for lipid in v2: lipid has 39/50
curated compounds covered in the full index, but only 1 Sub-6B lipid task exists.
The task-level limitation comes from Sub-6B pathway construction and filtering.

## 5. NM-002 Leakage Handling

`tools/benchmark/sub6/spectrum_lookup.py` excludes RIKEN by default. The default
MassBank contributors are:

```text
Athens_Univ, Eawag, Eawag_Additional_Specs, Washington_State_Univ,
Fac_Eng_Univ_Tokyo, IPB_Halle, Kazusa, Keio_Univ, BS, BGC_Munich,
MPI_for_Chemical_Ecology, MSSJ
```

RIKEN, RIKEN_IMS, RIKEN_NPDepo, and RIKEN_ReSpect are not in the default list.

The v2 sampled spectra have these source-id prefix counts:

| prefix / family | n_spectra |
|---|---:|
| `CCMSLIB...` | 323 |
| `MSBNK-...` | 69 |
| other GNPS IDs such as `MoNA...` and `VF-NPL...` | 67 |

The NM-002 exclusion file is a JSON object whose `excluded_ids` field is a list
of 76,783 GNPS source IDs. This is format-compatible with
`SpectrumPayload.source_id`, but this session does not integrate the downstream
orchestrator exclusion list. Sub-6A evaluation should pass each task's
`differential_spectra[*].source_id` to library search as exclusions to prevent
self-matching.

## 6. Provenance

| field | value |
|---|---|
| git commit SHA | `06f0f21397faab244916c67bc0ac112ba06d040c` |
| branch observed during audit | `feature/sub6-v2-cross-llm` |
| raw build report | `reports/benchmark/sub6a_v2_construction_audit_raw.md` |
| raw build wall time | 188.8s |
| Sub-6A v2 MD5 | `73f0f3a336dc3d0be87571d15cfc6831` |
| Sub-6A v1 MD5 | `8fa791c280d0266468b2086154bcd378` |
| Sub-6B v2 MD5 | `23594c0a3c6ab7a906baad1e0cd622dc` |
| curated HMDB v2 MD5 | `2a8a9f35e8cf84a9c1e2a452eb00561e` |
| raw report MD5 | `baf7df83372aa84f5f5c3d7a8b156442` |

Build command:

```bash
PYTHONPATH=. python scripts/build_sub6/build_all.py \
    --hmdb-candidates data/processed/hmdb_candidates_npc_classified_v2.jsonl \
    --target-6b-mammalian 100 \
    --target-curated-hmdb 250 \
    --pathway-min-compounds 3 \
    --tasks-per-pathway-max 10 \
    --tasks-per-bucket-max 20 \
    --target-6a 40 \
    --spectra-per-compound-min 1 \
    --spectra-per-compound-max 3 \
    --min-compounds-with-spectra 3 \
    --output-dir data/benchmark/sub6/ \
    --report-path reports/benchmark/sub6a_v2_construction_audit_raw.md \
    --seed 42
```

## 7. Known Limitations

- Sub-6A v2 inherits the Sub-6B task imbalance: lipid has 1 task and nucleotide
  has 2 tasks.
- Two of the first 40 Sub-6B v2 tasks were dropped because only 2 compounds had
  spectra; the retained v2 ceiling is 38 tasks.
- GNPS dominates the spectra. MassBank-non-RIKEN contributes 12 sampled spectra
  in v2 and 36 spectra in the full 250-compound index.
- The spectrum index accepts both positive and negative ion modes. In sampled
  v2 tasks, spectra are 364 positive and 95 negative; no ion-mode balancing is
  enforced at task construction time.
- Spectrum peak lists are embedded directly in `differential_spectra`, making
  the JSONL larger but self-contained for benchmark execution.

## 8. Acceptance Check

| check | status |
|---|---|
| `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl` exists and has at least 25 rows | PASS |
| `data/benchmark/sub6/sub6a_e2e_tasks.jsonl` remains v1 with 14 rows | PASS |
| `data/benchmark/sub6/sub6b_mammalian_tasks.jsonl` remains v1 with 20 rows | PASS |
| `data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl` exists with 63 rows | PASS |
| `data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl` exists with 250 rows | PASS |
| every Sub-6A v2 task has at least 3 compounds with spectra | PASS |
| audit report complete | PASS |
