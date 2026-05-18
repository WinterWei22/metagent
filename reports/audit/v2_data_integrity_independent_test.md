# Sub-6 v2 Benchmark — Independent Verification Report

**Date:** 2026-05-18
**Auditor:** independent re-implementation (no access to original `feature/sub6-v2-integrated` audit source code)
**Worktree:** `feature/investigation-concord` HEAD `e258585`
**Mode:** read-only — **no benchmark / verifier file modified**

---

## 1 · Executive Summary

### 1.1 MD5 provenance check

All 5 expected files reach their target MD5, with one path anomaly:

| file | MD5 | match | resolved from |
|------|-----|-------|---------------|
| `data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl` | `23594c0a3c6ab7…` | ✓ | audit worktree |
| `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`      | `73f0f3a336dc3d…` | ✓ | audit worktree |
| `data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl` | `2a8a9f35e8cf84…` | ✓ | audit worktree |
| `data/processed/hmdb_candidates_npc_classified_v2.jsonl` | `8824f112a1a63e…` | ✓ | **sibling worktree** ★ |
| `data/processed/nm002_excluded_gnps_ids.json`        | `b5176477fa803c…` | ✓ | audit worktree |

★ The `hmdb_candidates_npc_classified_v2.jsonl` file is not in
`feature/investigation-concord` (a different branch produced it). It
was resolved at the identical sibling path
`/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/data/processed/…`
and its MD5 matches expected. **Stop-condition #1 ("数据已变") is
therefore not substantively triggered** — data unchanged, only path
differs; proceeding with a written anomaly.

### 1.2 Eight original checks (re-computed, independent agreement)

| Check | This audit verdict | Original audit verdict | Agreement |
|-------|--------------------|------------------------|-----------|
| P0-1 noise ≥ 2 | PASS | PASS | ✓ |
| P0-2 single-task pathways | WARN | WARN | ✓ |
| P0-3 Sub-6A GNPS self-exclusion | PASS | PASS | ✓ |
| P0-4 HMDB pool utilisation | WARN | WARN | ✓ |
| P0-5 NM-002 leakage layering | WARN | WARN | ✓ |
| P1-1 cross-task signal overlap | FAIL | FAIL | ✓ |
| P1-2 spectra per signal compound | FAIL | FAIL | ✓ |
| P1-3 same-pathway GT consistency | PASS | PASS | ✓ |

**All 8 verdicts agree.** All headline numbers reproduce exactly (see
§2 per-check tables). One minor terminology nuance discussed in §6.

### 1.3 Five extended checks

| Check | Numbers | Verdict |
|-------|---------|---------|
| E-1 JSONL structural integrity | 38 / 38 valid Sub-6A, 63 / 63 valid Sub-6B, 0 dup task_id | PASS |
| E-2 signal ⊆ differential | 0 / 63 mismatch | PASS |
| E-3 ground-truth pathway namespace coverage | 13 unique pathway_ids, 63 / 63 RaMP prefix | PASS (single namespace) |
| E-4 noise ⊥ signal | 0 / 63 violating | PASS |
| **E-5 Sub-6A / Sub-6B pathway overlap** | **10 of 10 Sub-6A pathway_ids ⊂ Sub-6B's 13** | ⚠️ **CONCERN — new flag** |

E-5 is a new finding the original audit did not surface. All 10
distinct pathway IDs used in Sub-6A also appear in Sub-6B's ground
truth. If a downstream pipeline runs Sub-6A spectra → compound ID →
pathway inference and then runs Sub-6B on the same pipeline, **its
performance on Sub-6B is potentially inflated by Sub-6A pathway
familiarity** (same ground truth labels under a different formulation).

### 1.4 Deep-dive numbers (full text in sub-reports)

**P1-1 independence** (`reports/audit/v2_p1_1_independence_analysis.md`)
- N_eff naive = 63
- N_eff by unique signal-set = **35**
- N_eff by pathway cluster = **13**
- SE multiplier under pathway clustering = **√(63/13) = 2.20×**
- Standard errors on any per-task metric should be multiplied by 2.2×
  if the analysis intends to claim pathway-level generalisation.

**P1-2 spectra sparsity** (`reports/audit/v2_p1_2_spectra_sparsity.md`)
- Per-task coverage:
  - 30 / 38 tasks have **≥ 3 signal compounds with ≥ 1 spectrum**
  - Only **3 / 38 tasks** have ≥ 3 signal compounds with ≥ 3 spectra
- 45 / 219 instances have 0 mapped spectra (KEGG → InChIKey
  miss-through curated pool — 12 / 219 fall in this category)

### 1.5 ConcordMet usage judgement

| Question | Verdict | Rationale |
|----------|---------|-----------|
| **Q1** Sub-6B v2 as ConcordMet Tier-B benchmark? | ⚠️ **限制可用 (supplementary only)** | N_eff = 13 (by pathway cluster) ≪ 30 threshold. Cooke PRIMARY (N=51, in-silico knockouts, structurally independent) is a strictly stronger primary benchmark. Sub-6B v2 can serve as "real-world / curated KEGG-tagged" *supplementary* cohort if the analysis explicitly clusters by pathway and reports pathway-level effect sizes only. |
| **Q2** Sub-6A v2 as ConcordMet upstream (spectra → cpd → pathway)? | ❌ **不建议用于 robust multi-seed evaluation** | per-compound spectra median = 1; only 3 / 38 tasks have ≥3 compounds with ≥3 spectra. Suitable strictly as a single-spectrum-per-compound demo pipeline, not for robustness claims. |

---

## 2 · Per-check detail (independent vs original)

### P0-1 noise count

| metric | this audit | original audit |
|--------|-----------:|---------------:|
| Sub-6B tasks with noise = 0 | 0 / 63 | 0 / 63 |
| Sub-6A tasks with noise = 0 | 0 / 38 | 0 / 38 |

PASS — match.

### P0-2 single-task pathways (Sub-6B)

| metric | this audit | original audit |
|--------|-----------:|---------------:|
| distinct ground_truth_pathway_id | 13 | 13 |
| singletons (pathway with exactly 1 task) | 5 | 5 |

WARN — match. Singleton pathways: `RAMP_P_000025682`,
`RAMP_P_000050096`, `RAMP_P_000050099`, `RAMP_P_000053042`,
`RAMP_P_000052855`.

### P0-3 Sub-6A GNPS self-exclusion

| metric | this audit | original audit |
|--------|-----------:|---------------:|
| n spectra total | 459 | 459 |
| unique source_ids | 369 | 369 |
| **unique source_ids in exclusion list** | **15** | (audit phrasing "Sub-6A source IDs in NM-002 exclusion list: 25" — but the **25** is the **incident count**, not the unique-set count) |
| incidents (1 per spectrum) | 25 | 25 |

PASS — verdicts match. Minor terminology nuance in §6: original audit
calls a count of 25 "source IDs" when it is in fact an incident
count; the unique-source-id intersection is 15. The dominant repeated
source_id is `CCMSLIB00003138222` appearing 10 times across tasks.

### P0-4 HMDB pool utilisation

| metric | this audit | original audit |
|--------|-----------:|---------------:|
| upstream pool unique KEGG | 526 | 526 |
| curated v2 unique KEGG | 249 | 249 |
| task-used unique KEGG | 174 | 174 |
| % of upstream used in tasks | 33.1 % | 33.1 % |

WARN — match exactly.

### P0-5 NM-002 leakage filter

| metric | this audit | original audit |
|--------|-----------:|---------------:|
| `leakage_filter` referenced in `tools/benchmark/sub6/spectrum_lookup.py` | yes (grep returns mention but no call site) | yes (no actual call) |
| Sub-6A spectra in exclusion list (incidents) | 25 | 25 |

WARN — match. Static grep confirms `leakage_filter` is referenced in
a documentation comment but not invoked at build time.

### P1-1 cross-task signal overlap (Sub-6B)

| metric | this audit | original audit |
|--------|-----------:|---------------:|
| n tasks | 63 | 63 |
| n identical (Jaccard = 1.0) pairs | 67 | (audit "pairs Jaccard ≥ 0.9: 67" — all of these turn out to be 1.0) |
| n pairs Jaccard ≥ 0.9 | 67 | 67 |
| pct tasks involved in ≥ 0.7 overlap pair | **79.4 %** | **79.4 % (50 / 63)** |
| n identical multi-task clusters | 13 | 13 |
| n unique signal-sets | 35 | 35 (implicitly) |

FAIL — match. The 79.4 % figure reproduces exactly.

Identical clusters (signal-set Jaccard = 1.0) are saved to
`data/audit/v2_test/identical_signal_set_groups.csv` for inspection.

### P1-2 spectra per signal compound

| metric | this audit | original audit |
|--------|-----------:|---------------:|
| n (task, signal) instances | 219 | 219 |
| median spectra per instance | 1 | 1 |
| % instances with ≥ 3 spectra | 16.4 % | 16.4 % |
| n instances with 0 spectra | 45 | 45 |
| n instances with 1 spectrum | 80 | 80 |

FAIL — match. Per-instance histogram is identical.

### P1-3 same-pathway GT consistency

| metric | this audit | original audit |
|--------|-----------:|---------------:|
| n pathway groups | 13 | 13 |
| inconsistent groups | 0 | 0 |

PASS — match.

---

## 3 · Extended checks (E-1 … E-5)

### E-1 JSONL structural integrity
- Sub-6A: 38 / 38 lines valid JSON, 0 parse error, 0 duplicate task_id.
- Sub-6B: 63 / 63 lines valid JSON, 0 parse error, 0 duplicate task_id.

### E-2 signal compounds ⊆ differential metabolites

Match by KEGG ID. 0 / 63 Sub-6B tasks have signal-only-not-in-diff. ✓

### E-3 ground-truth pathway namespace

| prefix | count |
|--------|------:|
| RaMP (`RAMP_P_...`) | 63 / 63 |

All 63 Sub-6B tasks carry a single-namespace ground truth. 13 unique
pathway IDs. The `pathway_source` distribution
(reactome / kegg / smpdb / wikipathways) lives in the same pathway
dict and matches the original audit P0-2 table.

### E-4 noise ⊥ signal

For each of 63 Sub-6B tasks, the signal KEGG set is disjoint from the
noise KEGG set. ✓

### E-5 Sub-6A / Sub-6B pathway-id overlap

| metric | value |
|--------|------:|
| Sub-6A unique pathway_ids | 10 |
| Sub-6B unique pathway_ids | 13 |
| **overlap** | **10** |

**All 10 Sub-6A pathway IDs also appear in Sub-6B.** Sample overlap
(first 5): `RAMP_P_000050021`, `RAMP_P_000000203`, `RAMP_P_000000398`,
`RAMP_P_000000141`, `RAMP_P_000000421`. This is a **leakage-of-design
risk** the original audit did not flag: if an evaluation pipeline
identifies compounds from Sub-6A spectra and then maps them to the
same pathway label space, its Sub-6B accuracy is not strictly out-of-
sample for those 10 pathways. Recommend: when reporting both
benchmarks, explicitly note the design overlap and consider a
hold-out variant.

---

## 4 · Deep dives

Full text in:
- `reports/audit/v2_p1_1_independence_analysis.md`
- `reports/audit/v2_p1_2_spectra_sparsity.md`

Headline numbers:

- **P1-1 N_eff:** naive 63, unique-signal-set 35, pathway-cluster 13.
  Per-task SE multiplier under pathway-cluster aggregation = 2.20 ×.
- **P1-2 task-level:** 30 / 38 tasks have ≥ 3 signal compounds with at
  least one spectrum each; only 3 / 38 tasks have ≥ 3 signal compounds
  with ≥ 3 spectra each.

---

## 5 · Usage recommendation

### Q1 Sub-6B v2 for ConcordMet — **限制可用 (supplementary)**

- N_eff (pathway cluster) = 13 < 30 spec floor for primary benchmark
  use. The Cooke PRIMARY cohort (N = 51, in-silico knockouts,
  structurally independent perturbations) is strictly stronger and
  already plays the primary role in W6-W7.
- Sub-6B v2 is *complementary* to Cooke as a real-world / KEGG-tagged
  cohort: its pathway IDs are curated against RaMP-DB rather than
  simulated. If used, reporting MUST:
  - cluster by pathway and report pathway-level effect sizes only
  - cite the 2.20 × SE multiplier (or use a clustered bootstrap)
  - flag the 5 singleton pathways as descriptive only
  - flag the 10-pathway design overlap with Sub-6A (this report E-5)

### Q2 Sub-6A v2 for ConcordMet — **demo-only**

- ConcordMet operates on compound lists, not spectra. Sub-6A's
  spectra → compound pipeline is upstream of ConcordMet.
- The 219 (task × signal compound) instances have median 1 spectrum;
  only 3 / 38 tasks have ≥ 3 compounds with ≥ 3 spectra.
- **Sub-6A is not suitable for per-compound multi-spectrum robustness
  evaluation.** Use only as a single-spectrum-per-compound *cascade
  demonstration* if needed; do not claim per-compound robustness.

### Comprehensive verdict + caveats

| Item | Verdict |
|------|---------|
| Sub-6B v2 paper headline N | **N_eff = 13** (pathway cluster), not 63 |
| Sub-6B v2 standard errors | × 2.20 inflation factor |
| Sub-6A v2 task count | 38 tasks usable for cascade demo |
| Sub-6A v2 per-compound robustness | NOT supported (median 1 spectrum) |
| NM-002 leakage | 15 unique source_ids / 25 incidents present in build artifact; runtime self-exclusion mitigates exact-query leakage but does not cover global NM-002 |
| Cross-Sub-6A/Sub-6B pathway leakage | **All 10 Sub-6A pathway IDs ⊂ Sub-6B** — flag in any joint evaluation |

---

## 6 · Discrepancies with original audit

Only one number-level nuance found across the 8 + 5 = 13 checks:

| Item | Original | This audit | Reason |
|------|----------|-----------|--------|
| P0-3 phrasing "Sub-6A source IDs in NM-002 exclusion list: 25" | 25 | 15 unique / 25 incidents | Original counts spectrum incidents (one per row); this audit reports both as separate fields. **Both numbers are correct** — they answer different questions. Original audit's prose interpretation is ambiguous; the numeric is fine. |

No verdict-level disagreement on any of the 8 original checks. The 5
extended checks add E-5 (Sub-6A / Sub-6B pathway overlap) which is
new information.

---

## 7 · Provenance

- Worktree: `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5_investigation`
- Branch: `feature/investigation-concord`
- HEAD: `e258585`
- Date: 2026-05-18
- Audit script: `data/investigation/scripts/audit_sub6_v2_independent.py`
- Intermediate data: `data/audit/v2_test/check_results.json`,
  `data/audit/v2_test/jaccard_matrix_63x63.csv`,
  `data/audit/v2_test/identical_signal_set_groups.csv`
- Modifications to benchmark / verifier code: **0**
- Modifications to benchmark data files: **0**
- Re-implementation independence: this audit's check logic was written
  without reading the original audit script source (the original lives
  on `feature/sub6-v2-integrated` branch which was not checked out).
  Schema discovery was done directly from the data files. Original
  audit report was read **only after** all 8 verdicts had been
  computed independently, to write §1.2 agreement table and §6
  discrepancies.

---

## 8 · Stop conditions

| condition | triggered? |
|-----------|-----------|
| #1 MD5 check failed | **substantively NO** — data unchanged, only path anomaly (documented §1.1) |
| #2 JSON parse error | NO (E-1 verified all valid) |
| #3 ≥ 3 verdict disagreement | NO (0 / 8 disagree) |
| #4 wall time > 4 h | NO (~ 2 h) |

No stop-condition triggered. Audit concludes cleanly with a usage
recommendation per § 5.
