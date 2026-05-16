# Concord Sprint W6 — Status

**Branch:** `feature/investigation-concord` (worktree `metagent_day1_v5_investigation`)
**HEAD at sprint start:** `9686781` (W5 D5 + 3-task pre-W6 recon)
**Sprint window:** 2026-05-16 → 2026-05-22

---

## D1 Cohort Pre-registration (2026-05-17, locked before Gate-2 measurement)

Three cohorts are pre-registered. Cohort assignment is fixed *before* any
Gate-2 metric is computed; metric thresholds and reported numbers are
locked to these cohort definitions to prevent post-hoc fishing.

| Cohort | GEM | z_threshold | min_differential | **N** | Role |
|--------|-----|-----------:|-----------------:|-----:|------|
| **PRIMARY** | Human1 | 1.0 | 2 | **51** | Gate-2 primary verdict |
| **SENS_A**  | Human1 | 2.0 | 3 | **19** | paper-canonical sensitivity |
| **SENS_B**  | Recon2.2 | 1.0 | 2 | **12** | GEM-choice sensitivity |
| Combined (supplementary only) | both | (mixed) | (mixed) | 61 | reported but not main verdict |

Total across the three pre-registered cohorts: **82** (51 + 19 + 12; primary and SENS_A overlap by construction — SENS_A is the strict-threshold subset of the same Human1 columns).

### Why per-cohort, not combined

- Reviewer concern: a "combined Human1 + Recon2.2" mean would entangle GEM-choice variance with threshold-choice variance. Pre-registering three cohorts cleanly separates them.
- Per-cohort verdicts make GEM-choice / threshold-choice robustness an explicit, paper-supplementary readout.
- A 3-cohort consensus verdict (3 GREEN / 3 RED) makes paper credibility strong; a split verdict (e.g. PRIMARY GREEN but SENS_A YELLOW) becomes a *finding* about sensitivity to canonical thresholds, not a contradiction.

### Stop-condition #3 amendment (user decision 2026-05-17)

```
Stop condition #3 amended W6 D1 (2026-05-17):
  original: Cooke ETL output 任务数 < 100 → halt
  amended:  primary cohort (Human1, z=1.0, min=2) < 30 → halt
            sensitivity cohorts can be any N ≥ 5
  reason:   Cooke 数据集天花板 199 perturbations,exometabolome design
            决定 ≥100 N 不可达;统计 power 算 N=49 已足够支持
            per-task delta + sign test paper narrative,不需要假设检验 N
```

Current state: primary 51 ≥ 30 ✓; SENS_A 19 ≥ 5 ✓; SENS_B 12 ≥ 5 ✓ — **proceed**.

---

## D1.1 — B-Cooke-1 / B-Cooke-2 (resolved 2026-05-17 ~00:30)

Full write-up in `docs/concord/cooke_id_resolution.md`. Summary:

- **B-Cooke-1** (metabolite IDs): zscore rows are MAR / BIGG exchange-reaction IDs. 2-hop join via simulatedPA `metab_dict.tsv` + Human-GEM `model/metabolites.tsv` (Human1 path) or MetaNetX `mnx_xref` BIGG bridge (Recon2.2 path) produces ChEBI mapping.
- **B-Cooke-2** (pathway namespace): emit `HUMAN1:<slug>` (Cooke pathway_dict.tsv) and `RECON2:<slug>` (Recon2.2 subsystem column header). KEGG/Reactome fuzzy-match deferred to D4 Gate-2 metric phase.

Both blockers **resolved**; subsequent stop condition was task-count tuning, addressed by the cohort amendment above.

---

## D1.2 — Cooke ETL pipeline (2026-05-17)

`concord/etl/cooke_etl.py`:

- `TierATask` dataclass — task_id, perturbation_pathway_{name,id}, organism, **cohort**, z_threshold, differential_metabolites, differential_raw_ids, z_scores, n_input_raw, n_input_resolved
- `build_id_table(metab_dict, human1_metabolites)` — Human1 2-hop joiner (with CHEBI-strict regex filter for upstream noise like KEGG glycan `G00124` codes in the `metChEBIID` column)
- `build_recon2_id_table(metanetx_sqlite)` — BIGG → MNX → ChEBI dict from W4 MetaNetX sqlite
- `etl_cooke_tasks(..., gem="human1"|"recon2", cohort=..., output_path=...)` — parametric runner; one call per cohort
- `run_all_cohorts()` — top-level driver emitting `tasks_primary.jsonl` / `tasks_sens_a.jsonl` / `tasks_sens_b.jsonl`

Artifacts:

- `data/concord/tier_a_cooke/raw/{Human1,Recon2.2}_zscores.tsv` (gitignored, 28.9 MB)
- `data/concord/tier_a_cooke/aux/{metab_dict_human1,human_gem_metabolites,pathway_dict_human1}.tsv` (gitignored, ~700 kB)
- `data/concord/tier_a_cooke/tasks_{primary,sens_a,sens_b}.jsonl` (51 + 19 + 12 records)

---

## D1.3 — Mummichog wrapper full v0.3 (2026-05-17)

**Schema v0.3 → v0.3.1 (backward-compat bump):**
- `PATHWAY_NAMESPACES` += `{MUMM, HUMAN1, RECON2}`
- `PathwayDB` += `MUMMICHOG_MFN`
- `EnrichmentResult.schema_version` default → `concordmet_v0.3.1`

**`concord/wrappers/mummichog_wrapper.py` additions:**
- `_ADDUCTS_POS` / `_ADDUCTS_NEG` adduct mass tables
- `synthesize_peaks(compound_set, n_background=250, mode, seed)` — port of W4 D5 `gate1_toy.py:run_mummichog` peak-builder; emits M+H + M+Na (positive) or M-H + M+Cl (negative) for each significant CompoundRef + 250 random background features (the upstream gate1_toy default that mummichog needs to fit a null distribution).
- `run_mummichog_for_compound_set(compound_set, ...)` — convenience wrapping `synthesize_peaks` + `run_mummichog`, sharing the `run_*(compound_set, ...)` shape used by the other 4 wrappers.

**`concord/normalize/mummichog_norm.py` rewrite:**
- `_namespace_pathway_id(raw_name)` now emits `MUMM:<slug>` (the W6 prompt spec assumed a KEGG-hsa fallback via mummichog model.json, but the human_mfn model only carries `mfn1v10pathNNN` internal IDs + pathway names — **no hsa cross-reference**, so the fallback as specced does not exist upstream).
- `pathway_db` → `PathwayDB.MUMMICHOG_MFN` (faithful to actual reference DB; previous `PathwayDB.KEGG` over-claimed and inflated cross-tool agreement with PSEA/FELLA in W5 4×4).

**Unit tests (`tests/concord/test_mummichog_w6.py`, 4 cases):**
1. `synthesize_peaks` produces N×|adducts| significant peaks + N_background non-significant peaks (positive mode)
2. negative mode emits M-H / M+Cl adducts (regression for ion mode)
3. `_namespace_pathway_id` produces `MUMM:...` whitelisted
4. W3 hotfix non-regression: pathway with `hits_kegg_ids` → `metabolites_hit` populated (no vacuous validator trip)

**End-to-end smoke** (cooke_human1_group3 "Alanine, aspartate and glutamate metabolism", 21 refs):
- wall 11.8 s
- 10 top pathways, all `MUMM:` namespace, `metabolites_hit` populated 4-8 per pathway
- v0.3.1 schema, no vacuous validator trip

**Regression:** full concord test suite 115/115 PASS (was 111 + 4 new test_mummichog_w6 cases).

---

## Open Questions (rolling)

- **OQ-1 (W5 carry-fwd):** Per-source canonicalization for Fig 3 caveat. Not started; W6 background-G slot still open.
- **OQ-2 (W5 carry-fwd):** Wieder email send decision pinned to Gate-2 verdict (W6 D5).
- **OQ-3 (W5 carry-fwd):** FELLA RWR (pagerank) matrices — defer unless Gate-2 metric needs them.
- **OQ-4 (W5 carry-fwd):** FELLA diffusion per-call wall 94 s — defer; K=10 mitigates.
- **OQ-5 (W5 carry-fwd):** ora.hits namespace heuristic — robust enough for default libs, deferred.
- **OQ-6 (W6 D1 close):** Mummichog peak synthesis + MUMM namespace now wired; ground-truth name-fuzzy-match for `HUMAN1:` / `RECON2:` cohort labels → D4 task.
- **OQ-7 (W6 D1 NEW):** mummichog model.json has `mfn1v10path<NNN>` internal IDs + free-text pathway names but no KEGG hsa cross-reference. Paper Methods should explicitly state the mummichog axis runs in the `MUMM:` namespace and was *not* bridged to KEGG hsa at the pathway-id level. D3 paradigm-consensus accommodates this by paradigm bucketing instead of namespace overlap.
