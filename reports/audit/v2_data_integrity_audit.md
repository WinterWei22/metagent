# Sub-6 v2 Data Integrity Audit

Generated: 2026-05-07

## 1. Executive Summary

| Metric | Value |
|---|---:|
| Total checks | 8 |
| PASS | 3 |
| WARN | 3 |
| FAIL | 2 |

Critical issues for paper investment:

- **FAIL P1-1:** Sub-6B task independence is weak. 50/63 tasks (79.4%) have at least one other task with signal-set Jaccard >= 0.7; 41/63 are in identical signal-set groups. Do not treat all 63 tasks as independent samples without clustering/downweighting by pathway/signal set.
- **FAIL P1-2:** Sub-6A spectrum depth is below the v3.1 target. Only 36/219 signal-compound task instances (16.4%) have >=3 spectra; 80 have exactly 1 and 45 have 0. Task-level construction still has >=3 compounds with spectra, but per-compound spectral robustness is limited.
- **WARN P0-5:** NM-002 leakage handling is runtime-only for Sub-6A. Build artifacts still contain 25 query spectra whose source_id appears in the NM-002 exclusion list. Runtime self-exclusion is active, but there is no build-time/global NM-002 filtering.

| Check | Judgment | Key evidence |
|---|---|---|
| P0-1 noise >=2 | PASS | Sub-6B min noise 2; Sub-6A min noise 2; zero-noise tasks 0/101 |
| P0-2 single-task pathways | WARN | 5 singletons among 13 pathways; top 5 = 46/63 tasks |
| P0-3 GNPS task self-exclusion | PASS | 459 runtime identifications inspected; runtime task exclusion set covers all 459 task source IDs; RIKEN-derived spectra 0 |
| P0-4 pool utilization | WARN | task/upstream KEGG utilization 33.1% (174/526) |
| P0-5 NM-002 build leakage filter | WARN | `spectrum_lookup.py` delegates leakage handling to downstream runtime; 25 Sub-6A source IDs overlap NM-002 exclusion list |
| P1-1 cross-task signal overlap | FAIL | 50/63 tasks have another task with Jaccard >=0.7; max Jaccard 1.0 |
| P1-2 spectra per signal compound | FAIL | >=3 spectra for 36/219 instances (16.4%) |
| P1-3 same-pathway ground truth consistency | PASS | 8 multi-task pathways checked; inconsistent groups 0 |

## 2. Per-Check Detail

### P0-1: Noise Compounds

Method: read `ground_truth_noise_compounds`, `ground_truth_signal_compounds`, `noise_count`, and `signal_count` from `data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl` and `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`. Also inspected `tools/benchmark/sub6/task_constructor.py`; the constructor default is `noise_count_range=(2, 5)`.

| Metric | Sub-6B v2 | Sub-6A v2 |
|---|---:|---:|
| tasks | 63 | 38 |
| min noise_count | 2 | 2 |
| max noise_count | 5 | 5 |
| mean noise_count | 3.492 | 3.500 |
| tasks with noise=0 | 0 | 0 |
| tasks with noise>=2 | 63 | 38 |
| min signal_count | 5 | 5 |
| max signal_count | 8 | 8 |

Judgment: **PASS**. The v2 data meet the v3.1 noise >=2 requirement even though the construction report phrased the gate as allowing noise >=0.

Impact: no evidence that noise=0 contaminates the current v2 benchmark.

### P0-2: Single-Task Pathways

Method: count `ground_truth_pathway.external_id` over Sub-6B v2 tasks and list all pathway sources/names/task counts.

| pathway_id | external_id | source | name | n_tasks | class |
|---|---|---|---|---:|---|
| RAMP_P_000050021 | R-HSA-211859 | reactome | Biological oxidations | 10 | metabolic/biological pathway |
| RAMP_P_000000203 | SMP00111 | smpdb | Cerivastatin Action Pathway | 10 | drug/action pathway |
| RAMP_P_000000398 | map00052 | kegg | Galactose Metabolism | 10 | metabolic/biological pathway |
| RAMP_P_000000141 | map00380 | kegg | Tryptophan metabolism | 9 | metabolic/biological pathway |
| RAMP_P_000000421 | map00150 | kegg | Androgen and Estrogen Metabolism | 7 | metabolic/biological pathway |
| RAMP_P_000000016 | map00260 | kegg | Glycine, serine and threonine metabolism | 6 | metabolic/biological pathway |
| RAMP_P_000000106 | map00350 | kegg | Tyrosine metabolism | 4 | metabolic/biological pathway |
| RAMP_P_000053306 | WP4022 | wikipathways | Pyrimidine metabolism | 2 | metabolic/biological pathway |
| RAMP_P_000025682 | SMP00096 | smpdb | Celecoxib Action Pathway | 1 | drug/action pathway |
| RAMP_P_000050096 | R-HSA-71291 | reactome | Metabolism of amino acids and derivatives | 1 | broad metabolism |
| RAMP_P_000050099 | R-HSA-73621 | reactome | Pyrimidine catabolism | 1 | metabolic/biological pathway |
| RAMP_P_000053042 | WP496 | wikipathways | Steroid biosynthesis | 1 | metabolic/biological pathway |
| RAMP_P_000052855 | WP5368 | wikipathways | Sulfatase and aromatase pathway | 1 | metabolic/biological pathway |

Judgment: **WARN**. Actual singleton pathways = 5, not 6 for the inspected file. There are no disease-only singleton pathways, but singleton/top-heavy pathways include drug/action and broad Reactome entries.

Impact: per-pathway statistics are not defensible for singleton pathways; report the singleton pathway list explicitly as a limitation.

### P0-3: Sub-6A GNPS Exclusion Runtime Check

Method: inspect every `differential_spectra.source_id` in Sub-6A v2, compare against `data/processed/nm002_excluded_gnps_ids.json`, inspect `logs/v2/sub6a_real.log`, inspect runtime code paths in `evaluation/sub6/run_sub6a.py`, `evaluation/sub6/identification.py`, and `tools/library_search/tool.py`, and inspect `data/eval/sub6/v2/sub6a_real/sub6a_narratives.jsonl` identification metadata.

| Metric | Value |
|---|---:|
| total Sub-6A spectra | 459 |
| GNPS `source_db` spectra | 447 |
| MassBank `source_db` spectra | 12 |
| CCMSLIB-prefix spectra | 323 |
| MSBNK-prefix spectra | 69 |
| RIKEN-derived spectra | 0 |
| unique source IDs | 369 |
| Sub-6A source IDs in NM-002 exclusion list | 25 |
| runtime identifications inspected | 459 |
| runtime exclusion set size min/max/sum | 4 / 23 / 459 |
| runtime records with `excluded_source_ids_hit` | 0 |
| predicted source IDs that are task query source IDs | 45 |
| predicted source IDs in NM-002 exclusion list | 17 |
| log contains explicit exclusion text | False |

Runtime code evidence: `run_sub6a.py` computes `task_exclusion_set(task)`, `identification.py` passes `exclusion_source_ids` into `LibrarySearchRequest`, and `tools/library_search/tool.py` filters targets whose `spectrum_id` is in `excluded_source_ids` before candidate scoring. The zero `excluded_source_ids_hit` count is consistent with pre-filtering before results are returned, not proof that exclusion was absent.

Judgment: **PASS** for exact task self-exclusion at runtime. Observability gap: the log does not print the per-task exclusion set, so future runs should log the exclusion count/source IDs hash.

Impact: the reported Sub-6A real top-1 accuracy is not explained by direct self-matching to the same query spectrum. However, global NM-002/cross-task leakage is only partially covered; see P0-5.

### P0-4: HMDB Pool Utilization

Method: compare unique KEGG IDs in `hmdb_candidates_npc_classified_v2.jsonl`, `curated_hmdb_mammalian_v2.jsonl`, and all Sub-6B v2 signal/noise/differential metabolites.

| Metric | Value | Percent |
|---|---:|---:|
| upstream pool unique KEGG | 526 | 100.0% |
| curated v2 unique KEGG | 249 | 47.3% of upstream |
| task-used unique KEGG | 174 | 33.1% of upstream |
| curated -> task utilization | 174 / 249 | 69.9% |
| task KEGG not in curated | 0 | 0.0% |

Judgment: **WARN** by the specified threshold: task/upstream utilization is 33.1%, below the PASS threshold of 40% but above the FAIL threshold of 20%.

Impact: the 600 pool was materially used, but task construction remains the bottleneck; expansion did not translate linearly into independent tasks.

### P0-5: NM-002 Leakage Filter Layering

Method: inspect `tools/benchmark/sub6/spectrum_lookup.py` for build-time leakage filtering, inspect runtime Sub-6A identification path, and compare Sub-6A `source_id` values to NM-002 excluded IDs. The spectrum lookup file mentions `tools.benchmark.leakage_filter` in documentation but does not actually call it for build-time filtering.

| Metric | Value |
|---|---:|
| build-time NM-002 filtering in spectrum lookup | False |
| Sub-6A task source IDs overlapping NM-002 exclusion list | 25 |
| runtime self-exclusion code active | True |
| predicted source IDs that are task query source IDs | 45 |
| predicted source IDs in NM-002 exclusion list | 17 |

Judgment: **WARN**. Exact task self-exclusion is active at runtime, but the build output is not globally NM-002-filtered. Some query and predicted source IDs overlap the NM-002 exclusion list.

Impact: do not describe Sub-6A v2 as build-time leakage-free. The current evidence supports removal of exact self-query matches, not removal of all NM-002/global library overlap.

### P1-1: Cross-Task Signal Compound Overlap

Method: compute sorted signal-compound sets per Sub-6B task from `ground_truth_signal_compounds`, count identical sets, and compute all pairwise Jaccard similarities.

| Metric | Value |
|---|---:|
| tasks total | 63 |
| duplicate signal-set groups | 13 |
| tasks in duplicate signal-set groups | 41 |
| task pairs Jaccard >=0.9 | 67 |
| task pairs Jaccard >=0.7 | 179 |
| task pairs Jaccard >=0.5 | 209 |
| tasks with another task Jaccard >=0.7 | 50 (79.4%) |
| max Jaccard excluding self | 1.0 |
| signal compounds appearing in >=3 tasks | 43 |

Example max-overlap pair: `compound_only_enrich_mammalian_RAMP_P_000000421_seed1` vs `compound_only_enrich_mammalian_RAMP_P_000000421_seed4` has Jaccard 1.0 with signal set `C00280, C00468, C00535, C00951, C01227, C03917`.

Judgment: **FAIL**. The failure threshold is >30% of tasks having another task with Jaccard >=0.7; observed is 79.4%.

Impact: Sub-6B v2 should be analyzed as correlated pathway/signal-set replicates, not 63 independent samples.

### P1-2: Sub-6A Spectra per Signal Compound

Method: for each Sub-6A task, map spectra to signal compounds via `compound_kegg_id` / `compound_inchikey` / first-block fallback and count spectra per `task_id, signal_compound` instance.

| Metric | Value |
|---|---:|
| signal-compound task instances | 219 |
| mean spectra per signal-compound instance | 1.388 |
| instances with >=3 spectra | 36 (16.4%) |
| instances with exactly 1 spectrum | 80 |
| instances with 0 spectra | 45 |
| spectra count histogram | 0: 45, 1: 80, 2: 58, 3: 36 |

Judgment: **FAIL**. PASS requires >=80% of compounds with >=3 spectra; observed is 16.4%.

Impact: Sub-6A task-level spectral coverage is usable, but per-compound spectral variability is sparse and should be framed as a limitation.

### P1-3: Same-Pathway Ground Truth Consistency

Method: group Sub-6B v2 tasks by `ground_truth_pathway.pathway_id`; compare the full `ground_truth_pathway` dict across tasks within each multi-task group.

| Metric | Value |
|---|---:|
| total pathways | 13 |
| multi-task pathways | 8 |
| inconsistent multi-task pathway groups | 0 |

Judgment: **PASS**. No pathway-name/source/external-id drift was found inside same-pathway task groups.

Impact: verifier grouping by pathway is stable for Sub-6B v2.

## 3. Cross-Cutting Findings

1. The main v2 quality issue is not missing noise or duplicate task IDs; those gates pass. The remaining statistical risk is correlation: task expansion produced many seed variants over the same pathway/signal compounds. This matters more for paper claims than raw task count.
2. The 600-compound pool helped but did not linearly convert into independent Sub-6B tasks. Only 174/526 upstream KEGG IDs appear in tasks, while 50/63 tasks have high signal-set overlap with another task. The bottleneck is task construction/pathway structure, not simply upstream pool size.
3. Sub-6A leakage control has layered behavior: runtime exact self-exclusion is active, RIKEN-derived spectra are absent, but build artifacts still contain NM-002-listed GNPS source IDs. This is acceptable only if the methods section is precise: runtime query-source exclusion, not global build-time filtering.
4. Sub-6A has broader task count than v1 but limited per-compound spectral depth. It supports end-to-end cascade examples, not strong claims about robustness across multiple spectra per compound.
5. Pathway distribution is top-heavy. Five pathways account for 46/63 Sub-6B tasks, and five pathways are singletons. Any per-pathway analysis should use only sufficiently replicated pathways or explicitly mark singletons as descriptive only.

## 4. Recommended Actions

| Priority | Action | Cost | Paper impact | Recommendation |
|---|---|---|---|---|
| P0 | Update paper/report wording for independence: analyze by pathway or signal-set cluster; avoid treating 63 Sub-6B tasks as iid. | Low: reporting/statistics change, no rebuild required | High: prevents inflated confidence intervals and overclaiming | yes |
| P0 | Add an independence sensitivity table: task-level metric plus pathway-clustered or unique-signal-set metric. | Medium: evaluation aggregation only | High: directly addresses P1-1 FAIL | yes |
| P0 | Clarify NM-002 language: current system performs runtime task source exclusion; it does not globally filter all NM-002-listed spectra at build time. | Low: methods/report edit | High: avoids leakage overclaim | yes |
| P1 | Add explicit logging of `exclusion_source_ids` count/hash in Sub-6A real runs. | Low code change, one future rerun if needed | Medium: improves auditability of P0-3 | yes, before final camera-ready numbers |
| P1 | Consider a stricter Sub-6A v3 build option requiring >=3 spectra per signal compound, or label current v2 as sparse-spectrum E2E. | Medium/high: likely fewer tasks or needs more spectra sources | Medium: robustness claim depends on it | wait_for_paper_v1 unless robustness is central |
| P1 | For singleton pathways, either merge/report them as tail examples or exclude from per-pathway statistics. | Low | Medium: cleans interpretation | yes |
| P2 | Improve task constructor diversity constraints to avoid repeated identical/high-overlap signal sets. | Medium code + rebuild | Medium/high for future v3 independence | yes for next data version, not required to publish v2 if limitations are clear |
| P2 | If global NM-002 leakage exclusion is required, add build-time filtering in `spectrum_lookup.py` or enforce global exclusions inside library search. | Medium code + rerun | Medium/high only if claiming global leakage-free ID accuracy | wait unless reviewer/paper claim requires it |

## 5. Provenance

- Git branch: `feature/sub6-v2-integrated`
- Git commit: `584253fa33318a5f38b71a4db0b627d43105ec31`
- Audit wall time for aggregation script: 0.228 s
- Audited files and MD5:
  - `data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl`: `23594c0a3c6ab7a906baad1e0cd622dc`
  - `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`: `73f0f3a336dc3d0be87571d15cfc6831`
  - `data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl`: `2a8a9f35e8cf84a9c1e2a452eb00561e`
  - `data/processed/hmdb_candidates_npc_classified_v2.jsonl`: `8824f112a1a63e2f91fcc451ce157244`
  - `data/processed/nm002_excluded_gnps_ids.json`: `b5176477fa803c3c2a3c13eeae1f7638`
  - `reports/benchmark/sub6_construction_report_v2.md`: `1d5b5ebcf071077a6f9045536543c476`
  - `reports/benchmark/sub6a_v2_construction_audit.md`: `919aca7123a09cab2c1e9bb82ed88f25`
  - `reports/benchmark/curation/hmdb_pool_expansion_audit.md`: `053a4acf06826ea19bc9368780eb57f5`
  - `reports/eval/sub6_v2_comparison_2026-05-06.md`: `e7a29a564e01660e4d841f69e05a0110`
- Audit commands: local read-only Python/json/log inspection; no benchmark/verifier/narrative rerun.
- Intermediate file: `/tmp/v2_data_integrity_audit_stats.json`.
- Code/data modification policy: 0 code changes; 0 `data/` file modifications; only this report file was written.
- Acceptance check: 8 checks executed; every check has numeric evidence and explicit PASS/WARN/FAIL.
