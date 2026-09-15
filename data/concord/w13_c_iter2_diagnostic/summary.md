# W13.C — iter-2 degradation root-cause on W12 D5 N=63 superset

**Source data:** `data/concord/w12_path_x_post_c7/path_x_full63_results.jsonl`
**Tasks analysed:** 14 `rollback_reason == "iter2_degraded"`
**Cross-check vs W12 D5 close-out aggregate:** match ✓

---

## 1 · Verdict

**H3_CONFIRMED** — unsupported gains dominate in 14/14 tasks (>= 60 %). H3 (richer feedback → LLM unsupported overshoot) extends from W10 D4.5 to W12 D5 N=63.

- H3 (unsupported dominant) tasks:    **14/14**
- H4 (contradicted dominant) tasks:   **0/14**
- Tied / mixed:                       0/14
- Other (neither positive):           0/14

Aggregate iter-1 → iter-2 deltas (sum across all degraded tasks):

- Σ Δ unsupported: **+48** claims
- Σ Δ contradicted: **-4** claims
- Σ Δ supported: **-9** claims
- Tasks losing supported in iter-2: 8/14

---

## 2 · Per-task table

| task_id (tail) | q[0,1,2] | Δq_12 | Δs_12 | Δu_12 | Δc_12 | Δv_12 |
|---|---|---:|---:|---:|---:|---:|
| `mmalian_RAMP_P_000000421_seed1` | [10, 5, 10] | +5 | -4 | +5 | +0 | -2 |
| `mmalian_RAMP_P_000025682_seed2` | [20, 8, 13] | +5 | -5 | +5 | +0 | +1 |
| `mmalian_RAMP_P_000000398_seed4` | [11, 4, 5] | +1 | -4 | +2 | -1 | -4 |
| `mmalian_RAMP_P_000000398_seed7` | [19, 7, 9] | +2 | -10 | +3 | -1 | +6 |
| `mmalian_RAMP_P_000000398_seed3` | [15, 4, 7] | +3 | -4 | +3 | +0 | -10 |
| `mmalian_RAMP_P_000000398_seed6` | [7, 4, 7] | +3 | -4 | +4 | -1 | -1 |
| `mmalian_RAMP_P_000050021_seed9` | [15, 7, 9] | +2 | -1 | +2 | +0 | -3 |
| `mmalian_RAMP_P_000050096_seed6` | [12, 5, 10] | +5 | +6 | +5 | +0 | -3 |
| `mmalian_RAMP_P_000000106_seed3` | [17, 4, 13] | +9 | +5 | +9 | +0 | -23 |
| `mmalian_lm_pathway_WP167_seed3` | [2, 0, 1] | +1 | +5 | +1 | +0 | -2 |
| `mmalian_lm_pathway_WP167_seed5` | [17, 11, 13] | +2 | +4 | +2 | +0 | +8 |
| `mmalian_lm_pathway_WP167_seed7` | [15, 9, 12] | +3 | +5 | +4 | -1 | -13 |
| `mmalian_lm_pathway_WP167_seed4` | [7, 2, 3] | +1 | +0 | +1 | +0 | +7 |
| `mmalian_RAMP_P_000000141_seed6` | [7, 4, 6] | +2 | -2 | +2 | +0 | -7 |

---

## 3 · W14 candidate paths (data-driven)

- **W14-α (recommended)**: cap `max_feedback_iters=1`. iter-2 rewrite consistently degrades quality on iter-1's responsive narrative; removing iter-2 eliminates the regression source.
- **W14-β (alternative)**: redesign quality_score to count supported gains positively (currently c+u only). May offset iter-2 unsupported overshoot.

