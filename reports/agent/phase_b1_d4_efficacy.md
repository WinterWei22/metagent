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
| seed_0 | 50 | n=50 · ↑45 / =4 / ↓1 · mean Δ=+2.02 | n=50 · ↑45 / =3 / ↓2 · mean Δ=+21.86 pp | n=50 · ↑9 / =38 / ↓3 · mean Δ=+0.12 | 0 |
| seed_1 | 43 | n=43 · ↑40 / =3 / ↓0 · mean Δ=+2.95 | n=43 · ↑41 / =2 / ↓0 · mean Δ=+25.93 pp | n=43 · ↑8 / =34 / ↓1 · mean Δ=+0.16 | 0 |
| seed_2 | 51 | n=51 · ↑41 / =9 / ↓1 · mean Δ=+1.92 | n=51 · ↑41 / =9 / ↓1 · mean Δ=+18.58 pp | n=51 · ↑9 / =42 / ↓0 · mean Δ=+0.18 | 1 |

## Overall (all 3 seeds pooled)

- **n tasks with feedback fired:** 144
- **quality:** n=144 · ↑126 / =16 / ↓2 · mean Δ=+2.26
- **supported ratio:** n=144 · ↑127 / =14 / ↓3 · mean Δ=+21.92 pp
- **top1 hybrid:** n=144 · ↑26 / =114 / ↓4 · mean Δ=+0.15
- **rollback (quality_N0 better → kept N0):** 1

## Interpretation guidance

Decision rules for downstream P0 rerun planning:

- If **mean Δ quality > 0 with N improved > N worse** → D4 has real signal; the P0 fix (adding UV to `_quality_score`) should expand the effective trigger surface and is worth a rerun.

- If **mean Δ quality ≈ 0 and improved ≈ worse** → feedback triggers but doesn't move the needle; investigate hint quality (feedback_hints.py) before any rerun.

- If **mean Δ quality < 0 and rollback_count is high** → rollback is the only thing protecting outcomes; investigate rollback logic in `_select_final_iteration`.

---

## Sample (seed 0, first 5 eligible tasks)

| task | n_fb | qN0→qF | suppN0→suppF | top1 N0→F | term |
|---|---|---|---|---|---|
| `mmalian_RAMP_P_000000016_seed1` | 1 | 3→0 (Δ+3) | 70.0→100.0 (Δ+30.0pp) | 0→1 | no_actionable_claims_after_iter |
| `mmalian_RAMP_P_000000016_seed2` | 2 | 2→1 (Δ+1) | 80.0→91.7 (Δ+11.7pp) | 0→1 | max_iterations_reached |
| `mmalian_RAMP_P_000000016_seed4` | 1 | 6→2 (Δ+4) | 33.3→71.4 (Δ+38.1pp) | 0→0 | no_actionable_claims_after_iter |
| `mmalian_RAMP_P_000000016_seed6` | 1 | 4→1 (Δ+3) | 66.7→87.5 (Δ+20.8pp) | 0→0 | no_actionable_claims_after_iter |
| `mmalian_RAMP_P_000000016_seed7` | 1 | 2→1 (Δ+1) | 83.3→91.7 (Δ+8.3pp) | 0→0 | no_actionable_claims_after_iter |

Full per-task records (all seeds) are written alongside as `d4_efficacy_per_task.json` in the input root.

