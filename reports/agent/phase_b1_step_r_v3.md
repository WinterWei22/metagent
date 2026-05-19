# Phase B1 Step R v3 — Driver-filtered correlation on v3 P0-fix N=3

**Date:** 2026-05-19
**Stage:** Phase B1 verification pass — addressing red-line #4 from `phase_b1_d5_v3_p0fix.md` §5.
**Source:** `data/eval/sub6/b1_d5_v3_p0fix/seed_{0,1,2}/<task>/result.json` (189 task instances total, 182 with non-empty final_narrative).
**Method:** identical to v2 Step R (`reports/agent/phase_b1_d6_step_r.md` §1):
1. Re-verify each NORMAL final_narrative through `verify_sub6` (Layer D consistency mocked → no LLM call).
2. Aggregate per-claim verdicts grouped by `claim_type`.
3. `supp_ratio_driver` per task = supported driver_metabolite claims / total driver_metabolite claims (None if 0 driver claims).
4. Bucket tasks by hybrid extractor top-1 (correct vs wrong).
5. Δ = mean(`supp_ratio_driver` | correct) − mean(`supp_ratio_driver` | wrong).
6. Control: same Δ on `supp_ratio_all` (all claim types).

**Cost:** ~$0 (Layer D mocked; only RaMP-lookup verifiers fire).
**Wall:** ~5 min for 182 re-verifies, single-threaded.
**Output:** `data/eval/sub6/b1_d5_v3_p0fix/step_r_v3_driver_filtered.json`.

---

## §1 Results

| metric | v2 D6 Step R (original) | v3 P0-fix Step R (this report) |
|---|---:|---:|
| n_total (NORMAL tasks) | 160 | 182 |
| n_correct (top-1 hybrid) | varied | 158 |
| n_wrong | varied | 24 |
| `supp_ratio_driver` Δ (correct − wrong) | **+5.00 pp** | **+3.50 pp** |
| `supp_ratio_all` Δ (control) | −0.79 pp | +2.71 pp |
| driver lift vs full | +5.79 pp | +0.79 pp |

---

## §2 Red-line #4 verdict

| threshold | gate | v2 status | v3 status |
|---|---|---|---|
| `supp_ratio_driver` Δ ≥ +18 pp | PASS | FAIL (+5.00) | **FAIL (+3.50)** |
| `supp_ratio_driver` Δ ∈ [+10, +18) | DIRECTIONAL | FAIL | FAIL |
| `supp_ratio_driver` Δ < +10 | FAIL | FAIL | **FAIL** |

**Red line #4 remains FAIL on v3.** The signal is weaker on v3 than v2 (+3.50 vs +5.00 pp). Likely cause: v3 has much higher top-1 accuracy on the new MiniMax model (87 % correct vs 50 % for v2), so the "wrong" bucket is only 24 tasks — noisy and dominated by edge cases. The correlation can't pick up signal when one bucket is sparse.

---

## §3 What this means for B1 attribution

The driver-filtered correlation was a tautology check: if `supp_ratio_driver` correlates with top-1 correctness, supported is meaningful evidence; if not, supported is largely tautological (Layer 6c membership approvals are trivial).

v3 result: Δ +3.50 pp on a +18 threshold. The supported metric **is largely tautological** under v3 — the 96.10 ± 1.21 supported % is dominated by Layer 6c approvals that pass tautologically given the LLM had RaMP top-3 available via feedback hints.

This does NOT invalidate the top-1 hybrid headline (83.60 % on v3 vs 61.29 % on A3 — both measured on the same LLM, same task list). top-1 hybrid is a **direct** metric of pathway prediction correctness — it does not depend on supported %. Step R is about the *supported metric's interpretability*, not about the top-1 finding.

For paper writing:
1. **Lead with top-1 hybrid** (the direct metric) — that's where the +6.96 / +22.31 pp gain lives.
2. **Mention supported % as a process metric** but caveat with Step R's +3.50 pp driver-filtered Δ.
3. **Tautology Discussion section** cites Step R v3 + `phase_b1_d5_v3_p0fix.md` §3 (driver_metabolite −6.5 % vs membership +9.9 % feedback-driven shift).

---

## §4 Comparison with v2 Step R

| dimension | v2 | v3 P0 fix | Δ |
|---|---:|---:|---:|
| top-1 hybrid (cross-seed) | 52.91 % | 83.60 % | +30.69 pp (LLM-version, not P0 fix) |
| `supp_ratio_all` | 94.71 % | 96.10 % | +1.39 pp |
| Δ correct−wrong on driver | +5.00 pp | +3.50 pp | −1.50 pp |
| Δ correct−wrong on full | −0.79 pp | +2.71 pp | +3.50 pp |

"Driver minus full" lift shrank from +5.79 pp (v2) to +0.79 pp (v3). On the new LLM, even driver_metabolite is mostly tautological — the model has gotten better at emitting driver claims that ground (driver supported % is high in both correct and wrong tasks).

---

## §5 Closing on B1 verification

| red line | threshold | v3 actual (today's LLM) | status |
|---|---|---|---|
| 1 UV % | < 10 % | 2.80 ± 0.55 | ✓ |
| 2 dropped_by_grammar % | < 30 % | 1.54 ± 0.10 | ✓ |
| 3 supported not regress > 5 pp | ≥ A3 − 5 pp | 96.10 ± 1.21 | ✓ |
| **4 Step R driver-filtered Δ** | **≥ +18 pp** | **+3.50 pp** | **✗ FAIL** |
| NEW top-1 hybrid ≥ A3 same-LLM | ≥ 61.29 % | 83.60 ± 7.48 | ✓ (+22.31 pp) |
| NEW top-1 method-A ≥ A3 method-A | ≥ 61.29 % | 69.31 ± 8.10 | ✓ (+8.02 pp) |

**5/6 red lines green; #4 is the durable FAIL.** This was true in v2 and is unchanged in v3 — the P0 fix wasn't expected to move the correlation either. The FAIL is informative for the paper's `Discussion` (tautology mechanism), not blocking for the headline (top-1 outperforms A3 same-LLM by +22.31 pp).

---

## §6 Companion artefacts

- `data/eval/sub6/b1_d5_v3_p0fix/step_r_v3_driver_filtered.json` — raw numbers
- `scripts/eval_sub6/step_r_v3.py` — analysis script (reusable; just point `INPUT_ROOT` elsewhere)
- `reports/agent/phase_b1_d6_step_r.md` — v2 Step R for comparison
- `reports/agent/phase_b1_p0_isolation.md` — same-LLM isolation that contextualises the +30 pp LLM-version drift
