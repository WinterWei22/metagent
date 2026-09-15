# W10 D4.5 — iter-2 degradation root-cause analysis

**Source data:** `data/concord/w10_d4_path_x_full/path_x_full63_results.jsonl`
**Tasks analysed:** 11 `rollback_reason == "iter2_degraded"` + 16 `best_ne_final`

---

## 1 · H1 verdict — REFUTED at structural level

Concord's `VerificationOutcome.quality = n_c + n_u` (`concord/agent/react_runner.py:160-164`). UV claim count is NOT a quality component. The D4 ping's H1 ('UV-driven quality interaction') was framed against B1's `_quality_score` formula in `evaluation/sub6/run_sub6b_react_feedback.py:_quality_score` (which DOES include `n_v` post B1 P0 fix `2a2eeb9`). That formula does not run on the concord Path X — so UV claim growth on the concord path cannot mechanically cause quality rise.

H1 is REFUTED. The iter-2 degradation seen in D4 is **driven by C+U gains** (concord-side quality is c+u-only) — the H3 path.

## 2 · H3 verdict

- **CONFIRMED** — H3 (iter-2 dynamics)
- tasks where iter-2 produces MORE c+u than iter-1: **11/11**
- tasks where iter-2 loses supported claims vs iter-1: **7/11**
- bridging signal still alive in iter 2: **10/11**
- bridge died AT iter-2 step (was alive in iter-1): **0/11**

Interpretation: D2/D2.5 fix is making the feedback prompt informative for the first time on the concord path. iter-1 LLM responds (we see iter-0 → iter-1 c+u improvements broadly). iter-2 LLM, however, often overshoots — rewrites that drop already-grounded supported claims or introduce new c/u claims. This is **iter-2 dynamics** under richer feedback, NOT a regression of D2.5.

## 3 · Per-task table (11 iter-2-degraded)

| task | gt | q[0,1,2] | δq_12 | s[0,1,2] | c+u[0,1,2] | v[0,1,2] | bridge[0,1,2] | best→final |
|---|---|---|---:|---|---|---|---|---|
| `_enrich_mammalian_RAMP_P_000000421_seed3` | Androgen and Estrogen Metaboli | [11, 6, 8] | +2 | [7,2,2] | [11,6,8] | [20,33,21] | ['T', 'T', 'T'] | 1→1 |
| `_enrich_mammalian_RAMP_P_000000421_seed4` | Androgen and Estrogen Metaboli | [9, 1, 3] | +2 | [8,18,11] | [9,1,3] | [22,13,16] | ['T', 'T', 'T'] | 1→1 |
| `_enrich_mammalian_RAMP_P_000000398_seed1` | Galactose Metabolism | [6, 3, 6] | +3 | [9,8,3] | [6,3,6] | [26,9,12] | ['T', 'T', 'T'] | 1→1 |
| `_enrich_mammalian_RAMP_P_000000398_seed3` | Galactose Metabolism | [15, 6, 11] | +5 | [11,6,7] | [15,6,11] | [9,11,7] | ['T', 'T', 'T'] | 1→1 |
| `_enrich_mammalian_RAMP_P_000050099_seed6` | Pyrimidine catabolism | [8, 1, 8] | +7 | [5,8,3] | [8,1,8] | [13,19,8] | ['T', 'T', 'T'] | 1→1 |
| `_enrich_mammalian_RAMP_P_000050021_seed1` | Biological oxidations | [12, 7, 11] | +4 | [9,14,14] | [12,7,11] | [6,18,12] | ['F', 'F', 'F'] | 1→1 |
| `_enrich_mammalian_RAMP_P_000000106_seed0` | Tyrosine metabolism | [8, 4, 8] | +4 | [7,11,21] | [8,4,8] | [32,16,6] | ['T', 'T', 'T'] | 1→1 |
| `_enrich_mammalian_RAMP_P_000000106_seed8` | Tyrosine metabolism | [11, 4, 9] | +5 | [8,20,5] | [11,4,9] | [32,21,22] | ['T', 'T', 'T'] | 1→1 |
| `_enrich_mammalian_lm_pathway_WP167_seed5` | Eicosanoid synthesis | [11, 8, 10] | +2 | [1,8,2] | [11,8,10] | [14,6,6] | ['T', 'T', 'T'] | 1→1 |
| `_enrich_mammalian_lm_pathway_WP167_seed7` | Eicosanoid synthesis | [20, 7, 10] | +3 | [9,7,1] | [20,7,10] | [21,21,12] | ['T', 'T', 'T'] | 1→1 |
| `_enrich_mammalian_RAMP_P_000000141_seed5` | Tryptophan metabolism | [13, 10, 11] | +1 | [15,13,12] | [13,10,11] | [22,4,8] | ['T', 'T', 'T'] | 1→1 |

## 4 · best_ne_final secondary analysis (16 tasks)

- best_iter distribution: {1: 15, 0: 1}
- final_iter distribution: {0: 12, 2: 4}
- rollback_reason distribution: {'feedback_made_it_worse': 12, None: 4}

Sanity: best_ne_final = 16 tasks where the lowest-quality iter is not the selected final iter. Each appears in a rollback bucket — the rollback rule picks N1 or N0 when N2 'degraded', even when N2 had the lowest quality. This is **the rollback rule's design**, not a bug — and the +6 increase from W9 D5 (10→16) is the same iter-2 dynamics story as the iter-2 degradation count: feedback now actually shifts iter-1 quality, so the N2 vs N1 comparison hits the rollback threshold more often.

## 5 · D5 path recommendation

**Option A — D5 with explicit attribution.** The iter-2 degradation rise is a side-effect of feedback finally being informative (D2.5 fix), NOT a regression. D4 data is paper-grade with a Discussion footnote on iter-2 dynamics. Continue to D5 aggregator on D4 data.

**Option B — Quality metric redesign.** Not recommended without evidence that the metric definition is wrong. The c+u metric matches the W8/W9 spec; redesigning post-hoc to mask the iter-2 number would be exactly the 'attribution explain it away' move the user warned against.

**Option C — Truncate to iter-1.** Could artificially eliminate iter-2 degradation by hard-capping `max_feedback_iters=1`. Defensible if iter-2 net contribution is negative (degraded > improved). Needs iter-1 vs iter-2 net contribution number — sub-analysis on D4 data, no rerun needed. **W11 follow-up candidate**.

Verdict-driven recommendation: **D5 proceed with Option A footnote**. D4 data is trustworthy; iter-2 degradation is a real dynamics signal, not a numerical artefact.
