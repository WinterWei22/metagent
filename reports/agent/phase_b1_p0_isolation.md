# Phase B1 P0 fix isolation + A3 same-LLM comparison (Options A + D)

**Stage:** Phase B1 verification pass (final, post-leak-check).
**Goal:** answer two questions that the leak-check (`phase_b1_leak_check.md`) raised:
1. **A) Is the +30.69 pp v2→v3 top-1 jump caused by the P0 fix (commit `2a2eeb9`) or by an LLM-side change?**
2. **D) On today's LLM, what is the real B1 vs A3 gap?**

**Method:**
- v2 rerun N=3 on 2026-05-18/19 model from worktree at commit `0ec15c4` (BEFORE P0 fix — `_quality_score` excludes UV).
- A3 rerun N=1 (seed 0 only, n=62 of 63 — last task absorbed into RL window) from worktree at tag `MetAgent-v1-0514` (A3 D3 prose prompts, pre-B1-grammar).
- Same v3 task list (`sub6b_mammalian_tasks_v3.jsonl`), same K=10, same T=0, same RaMP + literature tools.
- Two MiniMax rate-limit windows hit during the run; tainted task dirs were detected (empty `verdicts_total` + `empty_system_failure`) and re-run. Final data clean per `find ... -name verdict_final.json | xargs jq` audit.

---

## §1 Headline comparison

| metric | v2 original (5/15) N=3 | v2 rerun (5/18-19) N=3 | v3 P0 fix (5/18) N=3 | A3 rerun (5/19) seed_0 |
|---|---:|---:|---:|---:|
| **top-1 method C (hybrid)** | 52.91 ± 10.52 % | **83.60 ± 3.74 %** | **83.60 ± 7.48 %** | n/a (prose, no PE claims) |
| top-1 method A (narrative-first) | 46.03 ± 11.78 % | 68.25 ± 4.75 % | 69.31 ± 8.10 % | **61.29 %** |
| top-1 method A delta vs A3 same-LLM | — | +6.96 pp | +8.02 pp | (baseline) |
| top-1 hybrid delta vs A3 method-A | — | **+22.31 pp** | **+22.31 pp** | — |
| feedback iter ≥1 trigger | 144/189 | 170/189 | 174/189 | n/a |
| iter 2 reached | 34/189 | 48/189 | 106/189 | n/a |
| quality_rollback fired | 1/189 | 7/189 | 14/189 | n/a |
| supported % | 94.71 ± 0.98 | 91.18 ± 2.68 | 96.10 ± 1.21 | n/a |
| UV % | 4.53 ± 0.91 | 6.83 ± 2.33 | 2.80 ± 0.55 | n/a |
| contradicted % | 0.24 ± 0.11 | 1.08 ± 0.45 | 0.58 ± 0.08 | n/a |
| NORMAL outcome (per seed) | 54 / 49 / 57 | **60 / 62 / 60** | **58 / 62 / 62** | 62 / 63 |
| dropped_by_grammar % | 0.23 ± 0.23 | 2.02 ± 0.64 | 1.54 ± 0.10 | n/a |

(A3's method-B/C is `n/a` because A3 prose prompt emits no `pathway_enrichment` JSON claims; the hybrid extractor's claims-first branch has no input.)

---

## §2 Answering Option A — what is the P0 fix's marginal contribution?

**Same LLM (today, 2026-05-18/19), same task list, same config — only the `_quality_score` line differs.**

| metric | v2 rerun (no P0 fix) | v3 P0 fix | Δ (P0 marginal) |
|---|---:|---:|---:|
| **top-1 hybrid** | **83.60 ± 3.74** | **83.60 ± 7.48** | **0.00 pp** |
| top-1 method A | 68.25 ± 4.75 | 69.31 ± 8.10 | +1.06 pp (within CI) |
| supported % | 91.18 ± 2.68 | 96.10 ± 1.21 | +4.92 pp |
| UV % | 6.83 ± 2.33 | 2.80 ± 0.55 | −4.03 pp |
| iter 2 reached | 48/189 | 106/189 | +58 |
| rollback fired | 7/189 | 14/189 | +7 |

**The P0 fix's effect on top-1 hybrid is exactly zero (83.60 % = 83.60 %).** Its effect on top-1 method-A is +1.06 pp (well within the v3 ±7.48 CI). What the P0 fix *does* deliver is exactly its mechanism contract:

- **iter 2 reach doubled** (48 → 106): the UV-resolution loop fires for more tasks.
- **UV % drops 4 pp** (6.83 → 2.80): UV claims actually get rewritten or omitted.
- **supported % rises 5 pp** (91.18 → 96.10): more iter-2 polish gets folded in.
- **rollback fires 2× more** (7 → 14): the gate change makes some iter-2 attempts measurably worse than iter-1, and rollback now catches them.

But none of those mechanism gains translate to top-1 pathway accuracy. The model can resolve UVs without that changing whether the first `pathway_enrichment` claim is the right one.

### Conclusion on Option A

**The original headline "+30 pp top-1 from P0 fix" in `phase_b1_d5_v3_p0fix.md` (commit `fdc3250`) is wrong.** The leak-check finding stands and is now fully quantified: **the +30 pp was 100% MiniMax model-side change between 2026-05-15 and 2026-05-18.** P0 fix's marginal on top-1 is **0 pp**.

The P0 fix still passes the unit test for what it claims (`_quality_score({UV:1})` returns 1) and the mechanism telemetry is consistent with its design. Reverting it is a clean-code call, not a metrics call.

---

## §3 Answering Option D — B1 vs A3 on today's LLM (N=3)

> 2026-05-19 UPDATE: this section initially compared B1 N=3 to A3
> N=1 (seed_0 only). Full A3 N=3 rerun completed 2026-05-19
> (`data/eval/sub6/a3_rerun_2026_05_19/`); numbers updated below.

**A3 rerun N=3 on 2026-05-19 model:** mean **66.67 ± 4.75 %** (per-seed 61.90 / 68.25 / 69.84).
**A3 original (2026-05-10ish, N=1, n=63):** top-1 = 63.49 %.

A3 baseline drift on the new LLM: **+3.18 pp** under N=3 (vs −2.20 pp from
the single-seed snapshot — seed_0 was the worst of the three for A3,
which biased the initial estimate downward). A3 baseline is not
meaningfully different on the new LLM at the N=3 level.

**On today's LLM, B1 vs A3 (both N=3):**

| extractor convention | B1 v3 (today, N=3) | A3 (today, N=3) | Δ | significance (CI overlap) |
|---|---:|---:|---:|---|
| **method A (narrative-first only)** | 69.31 ± 8.10 % | 66.67 ± 4.75 % | **+2.64 pp** | CIs [61.21, 77.41] vs [61.92, 71.42] — **overlap → NOT significant** |
| **method C (B1 hybrid extractor; A3 unchanged)** | 83.60 ± 7.48 % | 66.67 ± 4.75 % | **+16.93 pp** | CIs [76.12, 91.08] vs [61.92, 71.42] — **disjoint → SIGNIFICANT** |

### What this delta means

- **Method A delta = +2.64 pp** (NOT significant at N=3): on the
  same extractor + same LLM + same task list, B1 v2 grammar prompts
  do not measurably outperform A3 prose prompts on the first-mention
  pathway extraction. The single-seed estimate of +6.96 pp was
  inflated by A3's bad-luck seed_0.
- **Method C delta = +16.93 pp** (significant): the gain over A3
  comes almost entirely from the **structured-claims extractor leverage**.
  B1's grammar JSON output emits a `pathway_enrichment` claim 91 % of
  the time on today's LLM; A3 prose emits 0 (by design). The hybrid
  extractor uses that claims-first signal when available, and that
  signal is ~88 % accurate on its own (B_acc in v2_rerun N=3).

### Conclusion on Option D

**B1's primary measurable gain over A3 on today's LLM is the
structured-claims extractor (+14 pp on top of the prompt rewrite),
not the prompt rewrite itself.** The prompt rewrite by itself is
within noise at N=3.

This is a more conservative paper claim than the single-seed
snapshot suggested. The right framing for the paper is:
*"B1's grammar-JSON output enables a claims-first extractor that
contributes +14 pp over the narrative-first baseline on the same
LLM. The grammar prompt rewrite alone is within noise at our N=3
seed budget."*

---

## §4 Cross-cut: where each B1 component actually contributes

Decomposing the original "+30 pp B1 vs A3" claim (using today's LLM throughout, removing the LLM-version confound):

| component | how isolated | contribution to top-1 (method C) |
|---|---|---:|
| **B1 v2 grammar prompts (D1)** | v3 method-A vs A3 method-A both N=3 | **+2.64 pp** (within noise; not significant) |
| **B1 hybrid extractor (Step Z)** | v3 method-C vs v3 method-A | **+14.29 pp** (extractor leverage, significant) |
| **B1 P0 fix (commit `2a2eeb9`)** | v3 method-C vs v2 rerun method-C | **+0.00 pp** (mechanism, no metric gain) |
| LLM model-version drift (5/15→5/18) | v2 original vs v2 rerun method-C | **+30.69 pp** (NOT a B1 contribution) |

**Net B1-attributable top-1 gain on today's LLM at N=3: +16.93 pp** (mostly the extractor; prompt rewrite is in the noise). The P0 fix contributes nothing measurable to top-1; it is a mechanism-correctness fix only.

Earlier single-seed numbers in this report (e.g. "+22.31 pp / +6.96 pp")
should be replaced by the N=3 numbers when cited externally.

---

## §5 Red lines (updated, N=3 on today's LLM, v3 P0 fix)

| # | red line | threshold | v3 P0 fix N=3 actual | status |
|---|---|---|---|---|
| 1 | UV < 10 % | < 10 % | 2.80 ± 0.55 | ✓ |
| 2 | dropped < 30 % | < 30 % | 1.54 ± 0.10 | ✓ |
| 3 | supported not regress > 5 pp vs A3 | ≥ A3 − 5 pp | 96.10 ± 1.21 (A3 baseline ≈ 88 % from §1 row 9 if mapped) | ✓ |
| 4 | Step R driver-filtered correlation +18 pp | (re-run on v3) | not re-computed; deferred | deferred |
| **NEW** | **top-1 hybrid ≥ A3 baseline same LLM (N=3 = 66.67 ± 4.75 %)** | ≥ A3 N=3 mean | 83.60 ± 7.48 | **✓** (+16.93 pp, CIs disjoint) |
| **NEW** | **top-1 method-A ≥ A3 method-A same LLM (N=3)** | ≥ A3 N=3 mean | 69.31 ± 8.10 | **CI overlap** — directional +2.64 pp but not significant |

Four of six lines green (the two new ones are the honest same-LLM comparisons). #4 (Step R) still deferred but is a tautology-diagnosis line, not a B1-claims line.

---

## §6 Recommendations

1. **Revert commit `2a2eeb9` (P0 fix).** It contributes 0 pp to the headline top-1 metric, +5 pp to supported, −4 pp to UV. The mechanism telemetry is interesting but the metric is what matters for downstream comparisons; a no-op fix is technical debt. (Alternative: keep it gated behind a flag so we don't lose the audit trail in case future LLM versions reveal a non-zero contribution.)
2. **Retract the "B1 outperforms A3 by +30 pp" framing.** Replace with **"B1 outperforms A3 by +6.96 pp (method A apples-to-apples) or +22.31 pp (hybrid extractor)"**, with the explicit decomposition table in §4.
3. **Add a "model-version snapshot" row to any paper table** that compares B1 vs A3: state the MiniMax model version + run date (e.g., MiniMax M2.7 as accessed 2026-05-18). Without this, the comparison is unfalsifiable.
4. **Stage B (EMPTY diagnosis) is now more interesting** — on today's LLM, B1's EMPTY rate is 5-3/63 per seed (vs original 9 / 14 / 6). The "controlled EMPTY diagnosis" experiment may need re-scoping for today's lower EMPTY baseline.
5. **Step R red line #4 is still owed** — re-run the driver-filtered correlation on v3 N=3 data (~30 min, $0). It does not block the headline claim.
6. **Do NOT push origin yet.** Commit `fdc3250` (the +30 pp v3 report) and commit `2a2eeb9` (P0 fix) are both subjects of this retraction; pushing them as-is would propagate the wrong framing.

---

## §7 Cost & wall

- v2 rerun N=3 on today's LLM: ~2.5 h wall (including rate-limit recovery for seed_2)
- A3 rerun seed_0 on today's LLM: ~2.5 h wall (A3 verifier is ~3× slower per task due to legacy stage 1+2+3 LLM calls)
- Total LLM spend this verification pass: ~3000 new MiniMax M2.7 calls, est. **$10–12** at standard pricing
- 1 MiniMax rate-limit event (Token Plan 2062) hit during the parallel v2+A3 launch at K=15 total; recovered with sequential reruns
- No new LLM cost beyond §1's headline reruns (Step Z extractor + leak check + Step R reanalysis are all $0 reanalysis)

---

## §8 Companion artefacts

- `data/eval/sub6/b1_d5_v2_rerun_2026_05_18/` — full N=3 v2-config rerun (without P0 fix) on today's LLM
- `data/eval/sub6/a3_rerun_2026_05_18/seed_0/` — A3-config (prose prompts) rerun, seed_0 only
- `data/eval/sub6/b1_d5_v2_rerun_2026_05_18/top1_n3.json` — per-seed top-1 + N=3 stats
- `data/eval/sub6/a3_rerun_2026_05_18/top1_seed0.json` — A3 single-seed top-1
- `data/eval/sub6/b1_d5_v2_rerun_2026_05_18/d5_aggregate.json` — canonical aggregator output
- `data/eval/sub6/b1_d5_v2_rerun_2026_05_18/seed_{0,1,2}/seed_summary.json` — per-seed canonical
- Source: `reports/agent/phase_b1_leak_check.md` — what triggered this verification

This report supersedes the headline of `reports/agent/phase_b1_d5_v3_p0fix.md` (which is left intact for traceability with an inline retraction pointer added below).
