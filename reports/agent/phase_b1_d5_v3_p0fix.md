# Phase B1 D5 v3 — P0 fix rerun (N=3 final)

> ⚠ **2026-05-19 RETRACTED — see `reports/agent/phase_b1_p0_isolation.md`**
> The "+30.69 pp top-1 attributed to P0 fix" headline is wrong.
> v2 rerun on 2026-05-18/19 model (without P0 fix) reaches the same
> 83.60 ± 3.74 % top-1 hybrid; the entire +30 pp gain came from a
> MiniMax M2.7 server-side change between 2026-05-15 and 2026-05-18,
> NOT from the P0 fix (commit `2a2eeb9`). P0 fix's true marginal on
> top-1 hybrid is **0.00 pp**; it delivers only mechanism telemetry
> (more iter-2 reach, UV % down, supported % up, rollback now firing).
> The honest B1 vs A3 gap on today's LLM is **+6.96 pp** (method A
> apples-to-apples) or **+22.31 pp** (with hybrid extractor) — both
> attributable to the prompt rewrite (D1) and extractor (Step Z), not
> the P0 fix. See `phase_b1_p0_isolation.md` §2-§4 for the full
> attribution decomposition.

**Stage:** Phase B1 P0 Stage A — final N=3 evaluation and gate check.
**Source:** `data/eval/sub6/b1_d5_v3_p0fix/` (3 seeds × 63 tasks = 189 runs).
**Baseline:** `data/eval/sub6/b1_d5_v2_full_feedback_lit/` (N=3 corrected via canonical aggregator, commit `0ba10f7`).
**Code change under test:** commit `2a2eeb9` — `_quality_score` now sums `contradicted + unsupported + unverifiable_v0`. Previously summed only the first two, so UV-only iterations were treated as "nothing to fix" and the feedback loop exited early.
**Config:** identical to D5 v2 (T=0, K=10 workers, max_react_turns=5, max_feedback_iters=2, total_timeout=1200s, MiniMax-M2.7, RaMP + literature tools exposed).
**Wall:** seed 0 = 56 min, seed 1 = 53 min, seed 2 = 33 min (partial resume) → **~2.4 h total**.

---

## §1 Headline numbers — N=3 mean ± CI95

| metric | D5 v2 N=3 corrected | D5 v3 P0 fix N=3 | Δ | gate |
|---|---:|---:|---:|---|
| **feedback iter trigger (sum)** | 144/189 (76 %) | **174/189 (92 %)** | +30 | spec target ~189; +16 pp |
| ↳ iter 1 only | 110 | 68 | −42 | (shifted) |
| ↳ iter 2 reached | **34** | **106** | **+72** | spec ~30; **3× larger reshape** |
| ↳ no feedback (iter 0 already clean) | 45 | 15 | −30 | — |
| **quality_rollback fired** | 1/189 (cold) | **14/189** (active) | +13 | rollback now real |
| supported % (NORMAL) | 94.71 ± 0.98 | **96.10 ± 1.21** | +1.39 pp | within ±5 pp ✓ |
| **UV % (NORMAL)** | 4.53 ± 0.91 | **2.80 ± 0.55** | **−1.73 pp** | ↓ as designed ✓ |
| contradicted % | 0.24 ± 0.11 | 0.58 ± 0.08 | +0.34 pp | tiny absolute, ≪ 5 pp |
| dropped_by_grammar % | 0.23 ± 0.23 | 1.54 ± 0.10 | +1.31 pp | within tolerance, see §2 |
| NORMAL outcome (per seed) | 54 / 49 / 57 = 160/189 | **58 / 62 / 62 = 182/189** | +22 | EMPTY rate halved |
| EMPTY system_failure (per seed) | 7 / 10 / 3 | 5 / 1 / 1 | −13 | matches NORMAL gain |
| EMPTY unknown (per seed) | 2 / 4 / 3 | 0 / 0 / 0 | −9 | gone entirely |
| inner_retry (cross-seed) | 195 | 168 | −27 | similar mechanism load |
| tool_call total | 2 993 | 2 239 | −754 (−25 %) | fewer roundtrips needed |
| wall (mean per task) | 296 s | 375 s | +79 s (+27 %) | feedback loops more often |

### Top-1 (paper-grade metric)

| extractor | D5 v2 N=3 corrected | D5 v3 P0 fix N=3 | Δ |
|---|---:|---:|---:|
| **method C (hybrid, Step Z)** | **52.91 ± 10.52 %** | **83.60 ± 7.48 %** | **+30.69 pp** |
| method A (narrative-first only) | 46.03 ± 11.78 % | 69.31 ± 8.10 % | +23.28 pp |
| method B claims-first pool rate | 26 / 63 / 34 = 46 % avg | 55 / 61 / 58 = 91 % avg | +45 pp |
| method B accuracy (when emitted) | 80.77 / 77.78 / 91.18 = 83 % | 83.64 / 90.16 / 89.66 = 88 % | +5 pp |

### Cross-seed stability of top-1 hybrid

- v3 seed 0: 76.19 % (above A3 baseline 63.5 % ✓)
- v3 seed 1: 88.89 % (above A3 baseline 63.5 % ✓)
- v3 seed 2: 85.71 % (above A3 baseline 63.5 % ✓)

**All three seeds clear the +60 % gate AND clear the A3 63.5 % gate.** The +30.69 pp jump is not a seed-0 fluke.

---

## §2 The new `dropped_by_grammar` signal (N=3 view)

D5 v2 N=3 reported `dropped_by_grammar_mean = 0.23 ± 0.23 %`. D5 v3 reports **1.54 ± 0.10 %**. Same explanation as the seed 0 snapshot: the runner re-extracts the final narrative through the grammar checker, and on v3 the final narrative (now drawn from iter 2 in 106/189 cases) sometimes contains a regenerated sentence that trips a banned-phrase or shape check.

The grammar verifier catches it, so it does not reach `supported`. Not a regression — a side effect of letting the LLM rewrite further. CI95 = 0.10 % is tight; consistent across seeds.

---

## §3 D4 feedback efficacy mechanism: gaming vs real improvement (N=3)

N0 → final claim-type distribution shift (only feedback-fired tasks):

### D5 v2 corrected N=3 (n_eligible = 144)

| grammar | N0 % | final % | Δ % | per-seed Δ |
|---|---:|---:|---:|---:|
| `pathway_membership` (6c) | 52.3 | 64.2 | **+11.9** | +11.6 / +11.7 / +12.7 |
| `pathway_enrichment` (6a) | 13.5 | 8.6 | −5.0 | −5.5 / −5.4 / −4.2 |
| `metabolite_pathway_link` (6c) | 15.2 | 15.3 | +0.1 | +0.8 / +0.4 / −1.0 |
| `driver_metabolite` (6b) | 19.0 | 11.9 | **−7.0** | −6.9 / −6.6 / −7.4 |

### D5 v3 P0 fix N=3 (n_eligible = 174)

| grammar | N0 % | final % | Δ % | per-seed Δ |
|---|---:|---:|---:|---:|
| `pathway_membership` (6c) | 42.1 | 52.0 | **+9.9** | +10.5 / +9.0 / +10.2 |
| `pathway_enrichment` (6a) | 25.0 | 21.4 | −3.7 | −4.0 / −2.6 / −4.5 |
| `metabolite_pathway_link` (6c) | 15.1 | 15.4 | +0.3 | −0.1 / +0.4 / +0.6 |
| `driver_metabolite` (6b) | 17.8 | 11.3 | **−6.5** | −6.4 / −6.8 / −6.3 |

### Interpretation

The shift pattern is **stable cross-seed** (CI on driver Δ ≈ 0.3 pp, on
membership Δ ≈ 0.8 pp), and it is **slightly milder** in v3 than v2
(driver −6.5 vs −7.0; membership +9.9 vs +11.9).

The P0 fix does **not** worsen tautology gaming. If anything it is
marginally better — likely because UV-resolution feedback hints often
tell the LLM to drop a fabricated `pathway_enrichment` claim or rewrite
an unverifiable `driver_metabolite`, both of which leave the
distribution closer to balanced rather than collapsing into pure
membership.

**Key insight:** the LLM trades hard claims (driver) for easy claims
(membership) under feedback pressure in **both** v2 and v3. That is a
prompt/verifier design issue, not a P0-fix issue. Decoupling the
top-1 gain from the gaming requires a separate ablation (out of scope
for this stage).

---

## §4 Red-line judgment (corrected, N=3)

| # | red line | threshold | v3 P0 fix N=3 actual | status |
|---|---|---|---|---|
| 1 | UV < 10 % | < 10 % | **2.80 ± 0.55** | ✓ |
| 2 | dropped_by_grammar < 30 % | < 30 % | **1.54 ± 0.10** | ✓ |
| 3 | supported not regress > 5 pp | ≥ A3 − 5 pp ≈ 88 % | **96.10 ± 1.21** | ✓ |
| 4 | supported↔correct correlation +18 pp | (Step R style) | not re-run; v2 was +5 pp full / +18 pp driver-filtered | deferred — needs separate Step-R re-run on v3 data |
| **NEW** | **top1 hybrid ≥ A3 baseline 63.5 %** | ≥ 63.5 % | **83.60 ± 7.48** | **✓** (+20 pp above gate) |

Four of five red lines green; #4 deferred (it needs the Step R
driver-filtered correlation re-computation on v3 data, which is
~30 min more work but does not block the headline judgment).

---

## §5 Gate check vs user-defined acceptance (Step 5)

| criterion | target | actual | pass? |
|---|---|---|---|
| top-1 ≥ 60 % on all 3 seeds | yes | 76.19 / 88.89 / 85.71 | ✓ |
| iter 2 reached ≥ 25 per seed | ≥ 25 | 36 / 39 / 31 | ✓ |
| any seed top-1 < 50 % (lucky-seed flag) | none | min = 76.19 | ✓ |
| rollback fires (P0 introduced active rollback) | > 0 | 4 / 5 / 5 cross-seed | ✓ stable |

**Verdict: B1 real improvement confirmed.** All three seeds are
substantially above the A3 D3.5 baseline (63.5 %) and above the user's
60 % gate. The +30.69 pp N=3 top-1 jump is not a seed-0 artefact.

---

## §6 Cost & efficiency

- Wall: seed 0 = 56 min, seed 1 = 53 min, seed 2 ≈ 33 min (resume) → **~2.4 h total**.
- LLM provider: **MiniMax M2.7 via remote API** (`https://api.minimaxi.com/v1`).
- LLM cost (measured from `logs/llm_calls.jsonl`, 2 026-05-18 07:00 – 12:30 UTC window):
  - 2 202 LLM calls (excludes RaMP / literature tool calls)
  - 12.6 M prompt tokens (70 % served from cache)
  - 2.86 M completion tokens
  - At MiniMax M2.7 standard pricing ($0.30 / M input, $1.20 / M output): **≈ $7.22**
  - At lower-bound estimate ($0.15 / M in, $0.60 / M out): ≈ $3.61
  - Cheaper than D5 v2 ($16.42 for the same N=3 scope) because v3's longer
    feedback loops reuse the system prompt prefix more (cache hit rate
    70 % vs ~40 % in v2 pilot estimates).
- Tool calls cross-seed: 2 239 (v3) vs 2 993 (v2) — −25 % despite more iter-2 reach. Feedback hints make the LLM more decisive, less reliant on tool roundtrips per iteration.
- Per-task wall: v3 +27 % over v2 (375 vs 296 s mean). The extra time buys +30 pp on top-1, +22 NORMAL outcomes, and active rollback. Worth it.

---

## §7 What this changes for downstream work

1. **`phase_b1_d5_eval.md` headline now legitimately retracted twice.** The original "B1 regressed pathway-correctness" (Step Q corrected to −0.53 pp) AND the original "D4 dormant; prevention > correction" (A1.5–A1.7 corrected to 144/189 fired with +21 pp supported delta) are both resolved by v3 numbers: **top-1 jumps from a tied-with-A3 baseline to +20 pp above it**.

2. **Step R correlation should be re-run on v3 data** (red line #4). Expected outcome: similar +18 pp on driver-filtered correlation, but not verified.

3. **Tautology gaming pattern (driver −7 pp, membership +12 pp) is now confirmed cross-seed across both v2 and v3.** This is the next legitimate research question — but it's an upstream prompt/verifier design issue, not a P0-fix issue.

4. **The 14 rollback cases on v3 are a new behavioural surface.** Worth a brief audit before B2 to confirm the rollback heuristic (lowest quality, earliest wins on tie) is making the right calls. Spot-check artefact: `data/eval/sub6/b1_d5_v3_p0fix/seed_{0,1,2}/<task>/result.json` where `rollback_reason` is non-null.

---

## §8 Companion artefacts

- `reports/agent/phase_b1_d5_v3_efficacy_seed0.md` — Step 3 efficacy report on seed 0 (per-task N0→final delta on 56 fired tasks).
- `data/eval/sub6/b1_d5_v3_p0fix/d5_aggregate.json` — N=3 cross-seed aggregate.
- `data/eval/sub6/b1_d5_v3_p0fix/seed_{0,1,2}/seed_summary.json` — per-seed canonical summaries.
- `data/eval/sub6/b1_d5_v3_p0fix/top1_n3_comparison.json` — N=3 method-A/B/C breakdown for v2 vs v3.

Companion to:
- commit `0ba10f7` — canonical aggregator (A1.6)
- commit `a1fbf2f` — D4 efficacy retraction analysis (A1.7)
- commit `02e7268` — D5 §4 retraction
- commit `2a2eeb9` — `_quality_score` UV fix (P0)

---

## §9 Final red-line status (post-verification, 2026-05-19)

After the verification pass (`phase_b1_leak_check.md` → `phase_b1_p0_isolation.md` → `phase_b1_step_r_v3.md` → A3 rerun N=3), the corrected red-line table on **same-LLM apples-to-apples** comparison:

| # | red line | threshold | v3 P0 fix N=3 actual | status |
|---|---|---|---|---|
| 1 | UV % | < 10 % | 2.80 ± 0.55 | ✓ |
| 2 | dropped_by_grammar % | < 30 % | 1.54 ± 0.10 | ✓ |
| 3 | supported not regress > 5 pp vs A3 | ≥ A3 − 5 pp | 96.10 ± 1.21 | ✓ |
| 4 | Step R driver-filtered Δ | ≥ +18 pp | +3.50 pp | ✗ FAIL (durable; tautology diagnosis line, not a B1-claims line) |
| NEW (top-1 hybrid) | ≥ A3 same-LLM N=3 (66.67 ± 4.75) | CIs disjoint | 83.60 ± 7.48 | **✓ +16.93 pp** significant |
| NEW (top-1 method-A) | ≥ A3 same-LLM N=3 | within CI | 69.31 ± 8.10 | directional +2.64 pp (NOT significant at N=3) |

**5/6 green; #4 is the one durable FAIL.** The NEW method-A row is the most paper-relevant negative finding: at N=3, the **grammar prompt rewrite alone (D1) is within noise**. The full +16.93 pp B1 hybrid gain over A3 comes from the **structured-claims extractor (Step Z)**, not from the prompt rewrite per se.

For paper:
- Lead metric: top-1 hybrid, +16.93 pp over A3 (same LLM, N=3, CIs disjoint).
- Caveat: prompt rewrite alone is in the noise band; the extractor is the work-horse.
- Discussion: Step R FAIL + tautology pattern (driver ↓ ~6 pp, membership ↑ ~10 pp) explains why supported % is a process metric, not a top-1 predictor.
- Do not cite the original "+30 pp" or "+22.31 pp" — see §3 / §4 of `phase_b1_p0_isolation.md`.
