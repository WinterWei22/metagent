# Phase B1 D4 — Feedback efficacy on D5 v2 corrected data

**Source:** `data/eval/sub6/b1_d5_v2_full_feedback_lit/` (post A1.6 aggregator correction)

**Stage:** Phase B1 P0 Stage A1.6 Step 3

**Question:** the corrected aggregator showed D4 feedback fired **144/189** times in D5 v2 (not 0/189 as previously reported). Did those iterations actually improve the result?

**Method:** per task with `n_feedback_iterations > 0`, compute iter-0 vs final-iter delta on three metrics:

- **quality** = contradicted + unsupported + unverifiable_v0 (per the P0-fixed `_quality_score`). Positive Δ = improved.

- **supported ratio** = #supported / total_verdicts. Positive Δ = improved.

- **top1 hybrid** = Step Z hybrid extractor (claims-first when any `pathway_enrichment` claim exists, else narrative-first via `evaluation/sub6/metrics.py`). Δ in `{-1, 0, +1}` per task.

---

## Per-seed breakdown

| seed | n_fb_iter>0 | Δ quality | Δ supported | Δ top1 | rollbacks |
|---|---|---|---|---|---|
| seed_0 | 56 | n=56 · ↑45 / =11 / ↓0 · mean Δ=+2.80 | n=56 · ↑46 / =9 / ↓1 · mean Δ=+19.91 pp | n=56 · ↑5 / =50 / ↓1 · mean Δ=+0.07 | 4 |

## Overall (all 3 seeds pooled)

- **n tasks with feedback fired:** 56
- **quality:** n=56 · ↑45 / =11 / ↓0 · mean Δ=+2.80
- **supported ratio:** n=56 · ↑46 / =9 / ↓1 · mean Δ=+19.91 pp
- **top1 hybrid:** n=56 · ↑5 / =50 / ↓1 · mean Δ=+0.07
- **rollback (quality_N0 better → kept N0):** 4

## Interpretation guidance

Decision rules for downstream P0 rerun planning:

- If **mean Δ quality > 0 with N improved > N worse** → D4 has real signal; the P0 fix (adding UV to `_quality_score`) should expand the effective trigger surface and is worth a rerun.

- If **mean Δ quality ≈ 0 and improved ≈ worse** → feedback triggers but doesn't move the needle; investigate hint quality (feedback_hints.py) before any rerun.

- If **mean Δ quality < 0 and rollback_count is high** → rollback is the only thing protecting outcomes; investigate rollback logic in `_select_final_iteration`.

---

## Sample (seed 0, first 5 eligible tasks)

| task | n_fb | qN0→qF | suppN0→suppF | top1 N0→F | term |
|---|---|---|---|---|---|
| `mmalian_RAMP_P_000000016_seed1` | 1 | 1→0 (Δ+1) | 92.3→100.0 (Δ+7.7pp) | 1→1 | no_actionable_claims_after_iter |
| `mmalian_RAMP_P_000000016_seed2` | 2 | 2→0 (Δ+2) | 80.0→100.0 (Δ+20.0pp) | 1→1 | no_actionable_claims_after_iter |
| `mmalian_RAMP_P_000000016_seed4` | 2 | 0→0 (Δ+0) | 100.0→100.0 (Δ+0.0pp) | 1→1 | no_actionable_claims_after_iter |
| `mmalian_RAMP_P_000000016_seed6` | 1 | 2→0 (Δ+2) | 80.0→100.0 (Δ+20.0pp) | 1→1 | no_actionable_claims_after_iter |
| `mmalian_RAMP_P_000000016_seed7` | 2 | 3→1 (Δ+2) | 75.0→90.9 (Δ+15.9pp) | 1→1 | max_iterations_reached |

Full per-task records (all seeds) are written alongside as `d4_efficacy_per_task.json` in the input root.

