# P1-1 Deep Dive — Sub-6B v2 Task Independence Analysis

**Sibling report to:** `reports/audit/v2_data_integrity_independent_test.md`
**Date:** 2026-05-18

---

## 1 · Headline numbers

| metric | value |
|--------|------:|
| N tasks (naive) | 63 |
| N unique signal-sets (Jaccard = 1.0 clusters collapsed) | **35** |
| N pathway clusters (group by `ground_truth_pathway_id`) | **13** |
| identical multi-task clusters (size ≥ 2) | 13 |
| pairs with Jaccard ≥ 0.9 | 67 |
| pairs with Jaccard ≥ 0.7 | 179 |
| pairs with Jaccard ≥ 0.5 | 209 |
| total pairs | 1953 (= 63 × 62 / 2) |
| pct tasks involved in any Jaccard ≥ 0.7 pair | **79.4 %** (50 / 63) |

---

## 2 · N_eff under different clustering rules

The naive N = 63 assumes independent samples. The data say otherwise.

| clustering rule | N_eff | SE multiplier vs naive |
|-----------------|------:|----------------------:|
| no clustering (naive) | 63 | 1.00 × |
| unique signal-set (Jaccard = 1.0 collapsed) | 35 | √(63 / 35) ≈ 1.34 × |
| **pathway cluster** | **13** | **√(63 / 13) ≈ 2.20 ×** |

Interpretation: any per-task metric reported as μ ± SE on N = 63 has
**under-estimated SE by a factor of 2.2** if the analysis intends to
generalise across pathways. To recover a defensible CI on a pathway-
level claim, multiply naïve SE by 2.20.

---

## 3 · Identical signal-set clusters (Jaccard = 1.0)

The first five clusters of identical signal-set tasks
(`data/audit/v2_test/identical_signal_set_groups.csv` has the full
13-cluster list):

| cluster id | size | sample task ids | signal set size |
|------------|-----:|------------------|---------------:|
| 1 | 7 | `compound_only_enrich_mammalian_RAMP_P_000000421_seed{1..7}` | 6 |
| 2 | 10 | `compound_only_enrich_mammalian_RAMP_P_000000203_seed{0..9}` | 5 |
| … | … | … | … |

(Full table in `data/audit/v2_test/identical_signal_set_groups.csv` —
13 multi-task clusters, total 41 / 63 tasks in identical clusters,
22 / 63 tasks are unique-signal singletons.)

---

## 4 · Recommendation for paper / ConcordMet / B1 usage

### Reporting recommendation

When reporting Sub-6B v2 results, the analysis section must include
**at least one** of:

1. **Pathway-cluster aggregation** — collapse each of the 13 pathway
   groups into a single observation; report N = 13 with the actual
   pathway IDs listed; CI from t-distribution with df = 12.

2. **Cluster-bootstrap CIs** — resample pathway groups (with
   replacement) rather than tasks; this preserves both the cluster
   size variation and the cluster-internal correlation. 95 % CI
   reported under this scheme is typically 2–3× wider than the naïve
   per-task bootstrap.

3. **Explicit SE inflation** — keep N = 63 but multiply SE by 2.20×
   and report the multiplier in the methods section.

Recommendation 1 (pathway-cluster aggregation) is the cleanest.
Recommendation 2 is most flexible if the analysis is regression-based.
Recommendation 3 is acceptable for descriptive tables but should
not appear as the only treatment of independence.

### ConcordMet specific

- Cooke PRIMARY cohort (N = 51, in-silico knockouts) is structurally
  independent: each perturbation is a single distinct pathway
  knockout simulation. There is no pathway clustering inside Cooke
  PRIMARY — N_eff ≈ 51 for the cohort.
- Sub-6B v2 N_eff = 13 is **insufficient** as ConcordMet's primary
  benchmark. Use as supplementary only, with pathway-cluster
  aggregation.
- For B1 (closed-loop verifier evaluation), Sub-6B v2 N = 63 is
  acceptable for per-task statistics (each seed is genuinely a
  different sample for runtime evaluation purposes), but
  pathway-level claims must use N_eff = 13.

### Paper text suggestion

"Sub-6B v2 contains 63 tasks distributed across 13 distinct ground-
truth pathways with substantial seed replication within each
pathway (10 / 13 pathway groups contain ≥ 2 identical signal
compound sets). For pathway-level claims we report effective N = 13;
for per-task runtime evaluation we report N = 63 with cluster-
bootstrap 95 % CIs grouped by pathway."

---

## 5 · Provenance

- Computation: re-implementation in
  `data/investigation/scripts/audit_sub6_v2_independent.py`,
  function `check_p1_1` + `deep_p1_1`
- Data: `data/audit/v2_test/check_results.json` (full numbers),
  `data/audit/v2_test/jaccard_matrix_63x63.csv` (full pairwise
  matrix), `data/audit/v2_test/identical_signal_set_groups.csv`
  (cluster table)
