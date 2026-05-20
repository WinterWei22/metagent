# Phase B1 D6 Step R — Driver-filtered supported↔correct correlation

**Date:** 2026-05-16
**Branch:** `feature/agent-phase-b1` (HEAD = `0ec15c4`)
**Cost:** ~$0.05 (Layer D mocked; only RaMP-lookup verifiers fired)
**Wall:** ~28 min for 160 NORMAL re-verifies, K=10 parallel
**Source:** `data/eval/sub6/b1_d5_v2_full_feedback_lit/seed_{0,1,2}/<task>/result.json`
**Output:** `data/eval/sub6/b1_d5_v2_full_feedback_lit/step_r_driver_filtered.json`

---

## TL;DR

Filtering supported_ratio to **driver_metabolite claims only** lifts
the supported↔correct correlation from −0.79 pp (full claim set) to
**+5.00 pp** — a **+5.79 pp shift** that confirms `driver_metabolite`
is a less-tautological verifier layer than biological_claim (Layer 6c).

But **+5.0 pp < +10 pp** gate threshold per the brief; red line 4
remains FAIL. The mechanism explanation from Step Q + Step R goes
into the paper: 80 % of supported claims are biological_claim → Layer
6c membership lookups → tautological with the enrichment input. Only
driver_metabolite (12 % of claims) carries genuine top-1 signal, and
the 159 driver_metabolite claims across 160 tasks aren't enough
density to push the per-task correlation to +18 pp.

**Conclusion: accept red line 4 FAIL, write paper §discussion with
mechanism + Step R numbers as evidence.**

---

## §1 Method

For each of the 160 NORMAL runs in D5 v2:

1. Re-verify the saved `final_narrative` (Layer D mocked to skip
   consistency LLM call — does not affect supported counts for the 4
   main claim types).
2. Aggregate per-claim verdicts grouped by `claim_type`:
   - `supp_ratio_all` = total supported / total claims (control)
   - `supp_ratio_driver` = supported driver_metabolite / total driver_metabolite
     (None when the task emitted 0 driver_metabolite claims)
3. Compute `top1_correct` via Step Z hybrid extractor (claims-first
   pathway_enrichment → fallback A3 narrative first-mention).
4. Split tasks into `correct` vs `wrong` (by hybrid top1).
5. For each bucket, mean of `supp_ratio_all` and `supp_ratio_driver`.
6. Δ = correct − wrong.

---

## §2 Results

| Metric | correct (n) | wrong (n) | Δ (pp) |
|---|---:|---:|---:|
| **supp_ratio_all** (control, ≈ §5 reproducible) | **0.9463** (n=100) | **0.9542** (n=60) | **−0.79** |
| **supp_ratio_driver** (filtered) | **0.6844** (n=75) | **0.6344** (n=31) | **+5.00** |

**Exclusions:** 25 correct + 29 wrong tasks emitted **no driver_metabolite
claims at all** and are excluded from the driver-only computation.

**Cross-check:** the −0.79 pp full-supported delta reproduces the §5
finding (−0.98 pp with a slightly different sample) to within sampling
noise. The driver-filtered analysis is on the same data, just
restricted.

---

## §3 Interpretation

The **+5.79 pp shift** when filtering away biological_claim and
set_enrichment is the direct quantitative signature of the tautology
mechanism documented in Step Q + the per-grammar breakdown:

| claim_type | n / 1353 | supported % | "signal density" |
|---|---:|---:|---|
| biological_claim (membership / link) | 1088 (80 %) | 99.0 % | tautological |
| set_enrichment | 104 (8 %) | 99.0 % | tautological |
| **driver_metabolite** | **159 (12 %)** | **62.3 %** | **real signal** |
| consistency_claim | 2 | 0 % | n/a (only contradictions) |

- biological_claim and set_enrichment are RaMP-table lookups against
  output the LLM read from `query_ramp_enrichment` — almost always
  pass tautologically.
- driver_metabolite needs the LLM to commit specific signal_compound
  ids that match the planted ground truth — the only verifier layer
  that requires LLM-side judgement beyond reading the enrichment list.

Restricting to driver_metabolite reveals **+5 pp** of genuine
correctness signal. That this is < +10 pp is itself evidence that:

1. Even driver_metabolite claims are partly tautological (LLM picks
   signal compounds from the input differential set, which the
   ground-truth subset is drawn from).
2. The Sub-6 dataset's "ground truth driver compounds" lookup is
   relatively easy when the LLM has the input list.
3. There aren't enough driver claims per task (mean 1.0 / NORMAL task)
   for the per-task supported_ratio to carry a stable signal.

---

## §4 Gate decision (per user brief)

| Δ | Decision |
|---|---|
| ≥ +18 pp | "Filtered supported recovers red line 4" |
| +10 to +18 pp | "Directional improvement, paper-explainable" |
| **< +10 pp** | **Accept red line 4 FAIL, paper uses mechanism** ← **here** |

**+5.00 pp falls in the third bracket.** Red line 4 stays FAIL. The
mechanism explanation (biological_claim 80 % weight × 99 % pass rate
dilutes any correlation signal) is the paper-ready answer.

---

## §5 What this fixes in the D5 / D6 narrative

Before Step R: the D5 report said "supported↔correct Δ = −0.98 pp,
red line 4 fail, supported is tautological" — true but not actionable.

After Step R: we have a **quantified per-layer attribution**:

- Layer 6c (biological_sub6) is **the dominant tautology source** —
  80 % of claims, 99 % pass rate.
- Layer 6b (driver_metabolite) is **the only layer carrying real
  signal** — +5 pp correlation contribution.
- Layer 6a (set_enrichment) is also tautological (99 % pass) but only
  8 % of claims.

For paper §method: "B1's `supported %` headline number is driven
predominantly by Layer 6c (biological_claim) membership checks, which
re-derive what RaMP enrichment already returned. The
driver_metabolite layer is the only verifier surface that requires
LLM-side commitment beyond reading the enrichment output."

For paper §discussion: "Per-layer breakdown (Step R) shows that
restricting supported_ratio to driver_metabolite claims recovers
+5 pp of supported↔correct correlation, confirming the tautology
mechanism. Future work should re-weight or report per-layer ratios
separately rather than a single aggregate `supported %`."

---

## §6 Files produced

```
data/eval/sub6/b1_d5_v2_full_feedback_lit/
├── claim_distribution_by_grammar.json  (Step Q follow-up — per-type breakdown)
└── step_r_driver_filtered.json         (this analysis — per-task + correlation)
```

Both untracked. No prompt / code changes.

---

## TL;DR (重申)

- driver-filtered correlation Δ = **+5.00 pp** (up from −0.79 pp for
  full-supported)
- < +10 pp gate threshold → **red line 4 accepted as FAIL**
- Mechanism explained: 80 % of supported claims are Layer 6c
  membership lookups (tautological); driver_metabolite is the only
  real signal (12 % of claims, 62 % pass rate)
- Paper § discussion gets concrete per-layer attribution numbers.
- D6 ablation epic includes Step R as the closing analysis.
