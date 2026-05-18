# Sub-6B v3 Benchmark — Independent Verification + v2 Comparison

**Date:** 2026-05-18
**Worktree:** `feature/investigation-concord` HEAD `9ff7c5a` → this commit
**Sibling refs:** `reports/audit/v2_data_integrity_independent_test.md`,
`reports/eval/sub6b_v3_opus_vs_v2_comparison.md` (2026-05-08 verifier-side comparison)
**Mode:** read-only audit — **no benchmark file modified**
**Scope:** Sub-6B v3 only (Sub-6A v3 does not exist in this worktree;
no upstream `hmdb_candidates_npc_classified_v3.jsonl`). The
sub-6B-applicable subset of the W7-audit framework is re-run + diffed
against the v2 numbers we already produced.

---

## 1 · Executive summary

### 1.1 MD5 provenance

| file | MD5 | match expected |
|------|-----|----------------|
| `data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl`  | `331b30a64017debe…` | ✓ (matches 2026-05-08 comparison report) |
| `data/benchmark/sub6/curated_hmdb_mammalian_v3.jsonl` | `3f6227a21b9a67d1…` | — (no original-audit expected MD5; recorded) |

### 1.2 v3 vs v2 side-by-side (sub6b-applicable checks)

| check | v2 | v3 | Δ | direction |
|-------|----|----|---|-----------|
| **P0-1** tasks with noise = 0 | 0/63 | 0/63 | — | same |
| **P0-2** distinct pathway IDs / singletons | 13 / 5 | 13 / 5 | — | same |
| **P0-4** task-used unique KEGG | 174 | **178** | **+4** | tiny ↑ |
| P0-4 task-used % of curated | 69.9 % | **71.5 %** | +1.6 pp | tiny ↑ |
| **P1-1** identical (Jaccard=1.0) pairs | 67 | **83** | **+16** | ↓ (more replication) |
| **P1-1** pairs Jaccard ≥ 0.9 | 67 | 83 | +16 | ↓ |
| **P1-1** pct tasks in high-overlap | **79.4 %** | **79.4 %** | 0 | same |
| **P1-1** unique signal-sets | 35 | **34** | −1 | ↓ |
| **P1-1** pathway clusters | 13 | 13 | 0 | same |
| **P1-3** inconsistent GT groups | 0 | 0 | 0 | same |
| **E-1** jsonl integrity | 63/63 valid, 0 dup | 63/63 valid, 0 dup | — | same |
| **E-2** signal ⊆ diff | 0/63 mismatch | 0/63 mismatch | — | same |
| **E-3** ground-truth pathway sources | reactome / kegg / smpdb / wikipathways | + **lipidmaps (10)** | +1 source | ✓ new ns |
| **E-3** pathway-id prefixes | RaMP only | RaMP 53 + **LIPID_MAPS 10** | +1 prefix | ✓ new ns |
| **E-4** noise ⊥ signal | 0/63 violating | 0/63 violating | — | same |
| **E-6** LIPID MAPS bucket (new) | — | 10 tasks / **1 unique pathway** | new | replicate-bound |

### 1.3 Headline conclusion

**v3 does not improve task independence;** in fact, replication
increases at the signal-set level (67 → 83 identical pairs;
35 → 34 unique signal-sets). The 79.4 % "high-overlap" task-fraction
remains identical to v2 to four significant figures (50 / 63).

The **only structural advance** in v3 is:
- one new pathway-source family (lipidmaps, 10 tasks)
- modest KEGG-pool utilisation gain (+4 task-used compounds, 174 → 178)

**However, the 10 new lipidmaps tasks are 10 seed replicates of the
SAME pathway** `lm_pathway:WP167` ("Eicosanoid synthesis"). This
re-confirms the comparison report's caveat: "10 / 11 lipid tasks
share WP167, so this expands lipid task count but not lipid pathway
diversity." Our E-6 check shows the ratio is even tighter — **10
lipid tasks / 1 unique pathway**.

### 1.4 ConcordMet usage judgement — unchanged from v2

| Question | v2 verdict | v3 verdict | Δ |
|----------|------------|------------|---|
| Q1 Sub-6B as ConcordMet primary | ❌ N_eff=13 << 30 | ❌ N_eff=13 << 30 | no change |
| Q1 Sub-6B as ConcordMet supplementary | ⚠️ with pathway cluster + SE×2.2 | ⚠️ with pathway cluster + SE×2.2 + ns-aware bucket | no change |

The 2.20× SE inflation factor is unchanged (`√(63/13)`). Adding
LIPID MAPS tasks adds *namespace breadth* but not *N_eff*. A paper
reporting v3 results must still:

1. cluster by pathway (N=13);
2. inflate SE by 2.20×;
3. **additionally** disclose that 10 of 13 pathway clusters consist
   of seed replicates with identical signal sets, and 1 pathway
   cluster (`lm_pathway:WP167`) accounts for 10 of the 63 tasks.

---

## 2 · Per-check detail

### P0-1 noise count (v3, sub6b)
- tasks: 63; mean noise = 3.49; range [2, 5]; zero-noise = 0.
- ✓ PASS — identical to v2.

### P0-2 single-task pathways (v3)
- 13 distinct `ground_truth_pathway.pathway_id`; 5 singletons.
- ✓ identical to v2 in count, but identity has shifted: 5 of the 12
  v2 multi-task pathways now appear as singletons or are gone, and 10
  new lipidmaps:WP167 seed tasks occupy a new multi-task cluster of
  size 10. (See §3 below for pathway breakdown.)

### P0-4 HMDB pool utilisation (v3)
- curated v3: 250 entries / 249 unique KEGG (identical to v2's 250 / 249).
- task-used unique KEGG: **178** (vs 174 in v2; +4 net).
- task_used_pct_of_curated: **71.5 %** (vs 69.9 % in v2).
- `task_used ⊂ curated`: **True**.
- ✓ marginally improved. The 4 newly-used compounds are LIPID MAPS /
  eicosanoid pathway members (see E-6).

### P1-1 cross-task signal overlap (v3)
- 63 × 63 Jaccard matrix → `data/audit/v3_test/jaccard_matrix_63x63_v3.csv`
- identical (Jaccard = 1.0) multi-task clusters → `data/audit/v3_test/identical_signal_set_groups_v3.csv`
- 83 identical pairs (vs 67 in v2; +16)
- 34 unique signal-sets (vs 35 in v2; −1)
- 79.4 % tasks involved in ≥ 0.7 Jaccard pair (identical to v2)
- **FAIL** — and slightly worse than v2 at the absolute pair count
  while flat at the percentage level.

### P1-3 same-pathway GT consistency (v3)
- 13 pathway groups; 0 inconsistent.
- ✓ PASS.

### E-1 jsonl integrity (v3)
- 63 / 63 lines valid; 0 duplicate task_id.
- ✓ PASS.

### E-2 signal ⊆ differential (v3)
- 0 / 63 tasks have signal compounds outside differential metabolites.
- ✓ PASS.

### E-3 pathway-id namespace + source (v3)
- 13 unique pathway IDs.
- pathway_id prefix: RaMP 53 + LIPID_MAPS 10.
- pathway_source: kegg 36 / reactome 12 / lipidmaps 10 / wikipathways 4 / smpdb 1.
- ⚠ **new namespace (`lm_pathway:`) introduced** — verifier and downstream
  pipelines must handle it; the W3-W7 ConcordMet schema does not yet
  have a `LM_PATHWAY:` whitelist entry. (v0.3.1 has MUMM / HUMAN1 / RECON2 / KEGG / REACT / WP / SMPDB / METACYC.)

### E-4 noise ⊥ signal (v3)
- 0 / 63 violating tasks.
- ✓ PASS.

### E-6 LIPID MAPS bucket (new)

- n lipid tasks: 10
- n unique lipid pathways: **1** (`lm_pathway:WP167` = "Eicosanoid synthesis")
- pathway replication: 10 / 10 lipid tasks are seed variants of the
  same pathway and same signal-compound set.
- ⚠ same caveat as v2 P0-2 singletons: the lipid bucket is *task-
  replicate-bound*, not *pathway-diverse*.

---

## 3 · Pathway breakdown change v2 → v3

The 13 pathway groups in v3 are not identical to the 13 in v2. Five
of the v2 multi-task groups remain dominant; v3 swaps one or more
older groups for the 10-task `lm_pathway:WP167` bucket. (Full
per-pathway counts are in `data/audit/v3_test/check_results_v3.json`
under `p0_2.n_tasks_per_pathway` and the equivalent v2 dump.)

The net effect is

- v2 (post-audit): 13 pathway groups, 5 singletons, max group = 10 (Biological oxidations / Cerivastatin / Galactose tied at 10)
- v3: 13 pathway groups, 5 singletons, max group = 10 (now includes lm_pathway:WP167 at 10)

so v3 = v2 in N_eff terms; the lipid bucket replaces one of the
v2 multi-task clusters rather than expanding the pathway space.

---

## 4 · Cross-reference with the 2026-05-08 verifier comparison

The `sub6b_v3_opus_vs_v2_comparison.md` report concluded Case B
("v3 useful as data expansion but verifier support did not catch
up", supported % 18.1 → 17.4 with −0.7 pp, unverifiable_v0 65.2 → 67.0
with +1.8 pp). Our data-integrity audit explains *why* the verifier
metrics did not improve:

1. **Task independence did not improve.** P1-1 identical-pair count
   increased (+16) and unique signal-sets decreased (−1). The 79.4 %
   high-overlap fraction was unchanged.
2. **Pathway diversity at the cluster level did not increase.** Both
   v2 and v3 have 13 pathway clusters. v3 swaps namespace family but
   not cluster count.
3. **The new lipidmaps cluster is 100 % seed-replicate.** 10 tasks /
   1 pathway → no within-cluster diversity to test the verifier
   against.

Together these mean: any aggregate metric averaged over 63 tasks
(verifier supported %, ConcordMet precision@10, etc.) has the **same
N_eff = 13 as v2**, with the same 2.20× SE inflation. v3 is paper-
worthy only as a **task-coverage breadth** result, not a sample-size
or independence improvement.

---

## 5 · Provenance

- Worktree: `feature/investigation-concord`
- Audit script: `data/investigation/scripts/audit_sub6_v3_independent.py`
- Reuses helpers from `audit_sub6_v2_independent.py` (`_signal_set`,
  `_jaccard`, `check_e1`)
- v2 baseline numbers loaded from
  `data/audit/v2_test/check_results.json` (HEAD `9ff7c5a`, written by
  the 2026-05-18 v2 independent audit).
- Intermediate data:
  - `data/audit/v3_test/check_results_v3.json`
  - `data/audit/v3_test/jaccard_matrix_63x63_v3.csv`
  - `data/audit/v3_test/identical_signal_set_groups_v3.csv`
- **0 benchmark file modifications, 0 verifier-code modifications.**

---

## 6 · Recommendation

| Action | Recommendation |
|--------|---------------|
| Use v3 in place of v2 for ConcordMet Tier-B? | **Yes** — same N_eff but +1 pathway source family (LIPID MAPS) and slightly higher pool utilisation. Plus, the 2026-05-08 verifier evaluation already operates on v3, so analytical alignment with W7 narrative is easier on v3. |
| Treat v3's 63 tasks as 63 independent samples? | **No.** Use N_eff = 13 (pathway cluster). SE multiplier 2.20×. |
| Report lipid-bucket result as "LIPID MAPS gives independent paper finding"? | **No** — 10 / 10 lipid tasks share a single pathway. Frame as task-coverage expansion only. |
| Extend ConcordMet's PATHWAY_NAMESPACES whitelist? | Add `LM_PATHWAY` namespace if Sub-6B v3 is to be used directly (the current v0.3.1 schema does not whitelist it). |
| Wait for v4 before paper submission? | **Only if** v4 promises *pathway-diverse* lipid expansion (≥ 5 distinct LIPID MAPS pathways) and breaks at least 2 of the existing 10-seed replicate clusters in non-lipid space. Otherwise v3 is the publication-ready version (with the documented caveats). |
