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

## D2 — Single-method baseline on Tier-A (2026-05-17)

RaMP top-10 vs Cooke ground-truth pathway name (`concord.analyze.pathway_match.pathway_name_overlap` token-set Jaccard ≥ 0.5):

| Cohort | N | hit | hit_rate | wall_total |
|--------|---:|---:|---------:|-----------:|
| PRIMARY | 51 | 12 | **23.5 %** | 12.1 s |
| SENS_A  | 19 | 7 | **36.8 %** | 1.8 s |
| SENS_B  | 12 | 3 | **25.0 %** | 0.1 s |

All three cohorts fall in the autonomous-mode green band (10-50 %).

**Hotfix**: SENS_B initial run produced hit_rate 0 % because `etl_cooke_tasks(gem="recon2")` left `perturbation_pathway_name` literally as the column header `subsystemN` — the simulatedPA repo *does* ship `data/Recon2.2/r_input/pathway_dict.tsv` (100 entries) but the initial D1.2 ETL only wired up the Human1 dict. Wired the Recon2 dict in `cooke_etl._recon2_perturbation_label` via a lazy global; re-ETL re-runs cleanly with bio names like "Starch and sucrose metabolism".

---

## D3 — 5-axis run on Tier-A (2026-05-17)

K=10 ThreadPoolExecutor concurrency across all (task, method) pairs in a cohort. 410 wrapper calls total (82 tasks × 5 methods).

| Cohort | N | wall | failures by method |
|--------|---:|-----:|---|
| PRIMARY | 51 | 434 s | 0 / 0 / 0 / 0 / 0 |
| SENS_A  | 19 | 196 s | 0 / 0 / 0 / 0 / 0 |
| SENS_B  | 12 | 105 s | 0 / **1** mummichog / 0 / 0 / 0 |

SENS_B mummichog single-task failure (1/12 = 8.3 %) is well below the 30 % systematic-failure stop floor. Cause: one Recon2.2 SENS_B task had only 2 differential compounds with masses below mummichog's filter; logged as a transient cohort-data interaction, not a wrapper regression.

---

## D4 — Gate-2 verdict (2026-05-17)

### PRIMARY (Human1, z=1.0, N=51) — verdict **RED**

```
Metric 1 (paradigm-aware supported %):
  Cond A (Level 1, ORA-only support of GT):  9.8%
  Cond B (Level 4+5, cross-paradigm support): 3.9%
  Delta:                                      -5.9pp
  Metric 1: FAIL

Metric 2 (precision/recall vs Cooke GT, name-fuzzy):
  Cond A (RaMP only)  precision@10:  23.5%  CI95=(13.7%, 37.3%)
  Cond B (consensus)  precision@10:   3.9%  CI95=( 0.0%,  9.8%)
  Delta precision:                  -19.6pp
  Delta recall:                     -19.6pp
  Sign test (per-task delta_precision): p=0.002 (+/-: 0/10)
  Metric 2: FAIL

  PRIMARY verdict: RED
```

### SENS_A (Human1, z=2.0, N=19) — verdict **YELLOW**

```
Metric 1: Cond A 5.3% / Cond B 10.5% / Δ +5.3pp / PASS
Metric 2: Cond A precision 36.8% / Cond B 10.5% / Δ -26.3pp / sign p=0.062 / FAIL
  SENS_A verdict: YELLOW
```

### SENS_B (Recon2.2, z=1.0, N=12) — verdict **YELLOW**

```
Metric 1: Cond A 8.3% / Cond B 16.7% / Δ +8.3pp / PASS
Metric 2: Cond A precision 25.0% / Cond B 16.7% / Δ -8.3pp / sign p=1.000 / FAIL
  SENS_B verdict: YELLOW
```

### Overall: **YELLOW (mixed, contains RED) — 1 RED / 2 YELLOW**

### 5×5 Jaccard buckets (Panel A data, name-overlap)

| Cohort | ora×ora | ora×mz | ora×net | mz×net |
|--------|--------:|-------:|--------:|-------:|
| PRIMARY | 0.061 | 0.004 | 0.000 | 0.000 |
| SENS_A  | 0.057 | 0.006 | 0.000 | 0.000 |
| SENS_B  | 0.090 | 0.003 | 0.000 | 0.000 |

ora×ora (0.06-0.09) is much higher than ora×mz / ora×net / mz×net (≤0.01) — the paradigm-driven cross-method disagreement re-established in W5 D5 holds at the *pathway-name* level on Cooke too.

### Interpretation of the RED PRIMARY verdict

The cross-paradigm consensus path (Level 4+5 only) requires that ≥ 2 paradigms independently rank the same pathway name in their respective top-10. With the across-paradigm Jaccard mean of 0.004 - 0.006, the **intersection of any ORA tool's top-10 with mummichog's top-10 or FELLA's top-10 is nearly empty**. The consensus filter therefore reduces precision rather than improving it — RaMP-only catches the right ground truth pathway ~24 % of the time, but the cross-paradigm filter throws away ~83 % of those hits because mummichog / FELLA don't agree at the *pathway-name* layer.

This is the **same finding** as W5 D5 sanity Check 2: cross-paradigm disagreement at the pathway-id / pathway-name layer is largely paradigm-driven, *not* a sign of disagreement at the biological level (compound-level Jaccard was 0.38 cross-namespace). The strict consensus rule "intersect across paradigms" weaponises that paradigm-driven disagreement against itself.

**Paper narrative (per Fig 3 v3 caption RED branch):** "Cross-paradigm consensus does not yield ground-truth-anchored lift; reconciliation contribution is qualitative (within-paradigm consistency, panel A; compound-level reconciliation, panel B) rather than precision-driven."

W7 has the option to (i) replace the strict consensus rule with a softer score (e.g. paradigm-weighted union, voting), or (ii) report the result as-is and reframe the paper around reconciliation depth rather than ground-truth precision. The W6 spec explicitly says **do not retune for GREEN** — verdict is reported faithfully.

---

## D5 — Fig 3 v3 + closure (2026-05-17)

Artifacts under `data/concord/fig3_v3/`:
- `fig3_v3.png` (387 kB, 300 DPI)
- `fig3_v3.pdf` (32 kB vector)
- `fig3_v3_data.csv` (per-cohort numbers)
- `fig3_v3_caption.md` (140 word caption, RED-narrative branch)

Panel A: 5×5 paradigm-bucket Jaccard heatmap on PRIMARY cohort.
Panel B: W4 v2 charge/tautomer reconciliation bar (carry-forward).
Panel C: Gate-2 precision lift bars (RaMP baseline vs cross-paradigm), grayscale baseline + verdict color for consensus (PRIMARY red, SENS_A/B yellow).

### Wieder email status (W6 D5)

`docs/concord/wieder_outreach.md` exists from W5 H. Per W6 prompt + autonomous mode rule 4, **email is HELD unconditionally** — even if Gate-2 verdict had been GREEN, the spec says "永远不要实发,无条件 hold". Decision: keep `HELD` flag in the doc header; user reviews after W7 launch.

### Background G (per-source canonicalization)

Skipped this run; the W4 v2 number 59.1 % → 5.5 % is the upper-bound estimate cited in Fig 3 v3 Panel B caveat. G will be done in W7 if user keeps the Panel B per-source breakout as a paper figure.

---

## Test coverage at W6 end

- 115 tests at W6 D1 close
- +18 W6 D4/D5 tests (`test_w6_analyze.py`)
- **133 total, 133 PASS** — meets the spec floor of ≥ 130.

---

## Anomalies Logged (autonomous-mode 🟡)

1. **PRIMARY RED Gate-2 verdict** — cross-paradigm consensus *reduces* precision against Cooke ground truth. Sign-test p = 0.002 (significant negative lift on per-task basis). Diagnosed: strict Level-4+ intersection is too restrictive when paradigm-driven pathway-name disagreement is the dominant signal (W5 D5 finding re-confirmed). Paper narrative pivot needed if reviewers expect ground-truth-anchored quantitative lift; the within-paradigm + compound-level reconciliation framing (panels A + B) survives intact.

2. **SENS_A Metric 1 PASS but Metric 2 FAIL** — paradigm support % does shift up under strict consensus (5.3% → 10.5%) but the *precision* hits don't follow. Suggests Metric 1 picks up "support" that doesn't correspond to top-10 rank agreement.

3. **SENS_B mummichog 1/12 task failed** — Recon2.2 SENS_B task with 2 mass-filtered compounds; mummichog had no significant features. Below systematic-failure stop floor (30 %).

4. **OQ-7 → OQ-8 promoted**: mummichog model.json has no KEGG hsa cross-reference; pathway-name-level Jaccard between mummichog and ORA tools = 0.004 (essentially zero). Most paradigm-cross overlap therefore happens only at the compound layer (W5 D5 finding) not the pathway-name layer. The W6 D4 strict-intersection consensus over-penalises this expected structural difference.

---

## Open Questions (rolling)

- **OQ-1 (W5 carry-fwd):** Per-source canonicalization for Fig 3 caveat. Not started; W6 background-G slot still open.
- **OQ-2 (W5 carry-fwd):** Wieder email send decision pinned to Gate-2 verdict (W6 D5).
- **OQ-3 (W5 carry-fwd):** FELLA RWR (pagerank) matrices — defer unless Gate-2 metric needs them.
- **OQ-4 (W5 carry-fwd):** FELLA diffusion per-call wall 94 s — defer; K=10 mitigates.
- **OQ-5 (W5 carry-fwd):** ora.hits namespace heuristic — robust enough for default libs, deferred.
- **OQ-6 (W6 D1 close):** Mummichog peak synthesis + MUMM namespace now wired; ground-truth name-fuzzy-match for `HUMAN1:` / `RECON2:` cohort labels → D4 task.
- **OQ-7 (W6 D1 NEW):** mummichog model.json has `mfn1v10path<NNN>` internal IDs + free-text pathway names but no KEGG hsa cross-reference. Paper Methods should explicitly state the mummichog axis runs in the `MUMM:` namespace and was *not* bridged to KEGG hsa at the pathway-id level. D3 paradigm-consensus accommodates this by paradigm bucketing instead of namespace overlap.
