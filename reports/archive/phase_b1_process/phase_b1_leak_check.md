# Phase B1 — Leak check + attribution analysis on D5 v3 P0 fix

**Stage:** Phase B1 verification pass (Step 2).
**Question:** the v3 P0 fix N=3 run jumped top-1 from 52.91 % to 83.60 % (+30.69 pp). Is this attributable to the P0 fix (commit `2a2eeb9`, +UV in `_quality_score`), or is something else going on?

**Spoiler — halt-worthy finding (see §3):** the +30 pp gain is **iter-0 origin**, not feedback-loop origin. The P0 fix's marginal contribution is **≈ −4 pp** (slightly negative across seeds). The headline in `phase_b1_d5_v3_p0fix.md` and the commit message of `fdc3250` need correction.

---

## §1 Static GT-leak check (code grep)

The `_quality_score` function (the actual code under test) only reads
`verdict_total` counters and never touches `task['ground_truth_*']`.
But the wider feedback path could in principle echo GT back to the LLM
through verifier `correction` fields. Audit results:

| file | GT references? | analysis |
|---|---|---|
| `verifier/feedback_hints.py` | **0** | Hint generators read only `claim.{claim_type,subtype,extracted_fields,correction,subject}` — never `task['ground_truth_*']`. |
| `verifier/agent.py` | **0** | No GT references at this module's top level. |
| `evaluation/sub6/run_sub6b_react_feedback.py` | 3 (all in `_strip_ground_truth(task)`) | Active leak-defense at lines 588 + 901: returns only `{task_id, differential_metabolites}` before prompt rendering. |
| `evaluation/sub6/run_sub6b_react_feedback.py:_quality_score` | **0** | Only reads `verdict_total` ints. |

So GT is NOT in the prompt. But there is one indirect channel:

**`verifier/layers/biological_sub6.py:789` sets**:

```python
correction = "; ".join(top3_names) if top3_names else None
```

where `top3_names` is the RaMP-DB's **top-3 pathway names for the
compound the LLM mentioned in its claim**. This `correction` field
flows into `_hint_for_contradicted()` (and similar `_hint_for_unsupported`),
which embeds it in the LLM feedback message verbatim:

```python
return (
    f"Pathway '{pathway or 'in claim'}' contradicted by RaMP-DB. "
    f"Use '{correction}' instead, or retract."
)
```

**Status:** this is **not GT leak per se** — `top3_names` is RaMP's
top-3 for the compound, not the benchmark's `ground_truth_pathway`. But
since the benchmark is *designed* so the GT pathway is in RaMP's top-3
(otherwise the task is unsolvable), the two overlap substantially:
**RaMP top-3 contains GT in roughly the same fraction as the eventual
top-3 accept rate, ≈ 80 %.**

This is an architectural property of the verifier-in-the-loop design,
present in **both v2 and v3** (no v3 change to the `correction` field).
It does not explain the v3 vs v2 delta. It is, however, a real concern
for the *absolute* top-1 number — see §4 caveat.

---

## §2 Sample 5 tasks v2-wrong → v3-correct (seed 0)

For each sampled task, GT pathway + iter-0 first `pathway_enrichment`
claim from v2 and v3:

| task | GT | v2 iter 0 first PE | v3 iter 0 first PE | v2 outcome | v3 outcome |
|---|---|---|---|---|---|
| `..._016_seed4` | Glycine, serine and threonine metabolism | Nicotinate and nicotinamide metabolism (wrong) | **Glycine, serine and threonine metabolism (correct)** | wrong | correct |
| `..._398_seed0` | Galactose Metabolism | (EMPTY — 0 claims) | **Galactose Metabolism (correct)** | EMPTY | correct |
| `..._050021_seed0` | Biological oxidations | Phase I - Functionalization of compounds (wrong) | **Biological oxidations (correct)** | wrong | correct |
| `..._421_seed1` | Androgen and Estrogen Metabolism | Estrogen biosynthesis (close-but-wrong) | **Androgen and Estrogen Metabolism (correct)** | wrong | correct |
| `..._106_seed8` | Tyrosine metabolism | (EMPTY — 0 claims) | **Tyrosine metabolism (correct)** | EMPTY | correct |

**Critical observation across all 5 samples:** v3's iter-0 first PE
claim is already correct (or at least exists). The P0 fix only
affects post-iter-0 feedback behaviour. So for these 5 tasks the P0
fix cannot be the cause of the v2→v3 improvement.

---

## §3 Quantitative attribution (all 3 seeds, n=189 task instances)

Decomposing the v3−v2 top-1 delta into "iter 0" component (LLM behavior
on the first call, no feedback) and "feedback" component
(final − iter0, what the feedback loop adds):

| seed | Δ FINAL top-1 (v3−v2) | Δ ITER-0 top-1 (v3−v2) | Feedback gain v3 (final−iter0) | Feedback gain v2 | **P0-fix marginal** |
|---|---:|---:|---:|---:|---:|
| seed 0 | +17 (+27.0 pp) | +19 (+30.2 pp) | +5 | +9 | **−6.3 pp** |
| seed 1 | +27 (+42.9 pp) | +30 (+47.6 pp) | +4 | +8 | **−6.3 pp** |
| seed 2 | +14 (+22.2 pp) | +15 (+23.8 pp) | +9 | +9 | **+0.0 pp** |
| **mean** | **+19 (+30.7 pp)** | **+21 (+33.9 pp)** | **+6** | **+8.7** | **≈ −4 pp** |

### What this says

1. **The v3 top-1 gain originates at iter 0**, before any feedback fires.
   Across all 3 seeds, the iter-0 top-1 jump is +34 pp on average,
   which is more than the full final-top-1 jump (+31 pp). Feedback in
   v3 is actually adding slightly less top-1 than feedback in v2.
2. **The P0 fix's pure marginal contribution to top-1 is ≈ −4 pp**
   (negative). Feedback fires more often in v3 (174 vs 144 tasks),
   reaches iter 2 more often (106 vs 34), but the number of tasks
   where feedback flips top-1 wrong→correct is roughly unchanged
   (5+4+9 = 18 in v3, 9+8+9 = 26 in v2).
3. **The +30 pp must therefore come from something that changed at
   the LLM level between the v2 run (2026-05-15) and the v3 run
   (2026-05-18).** The most likely candidate is a MiniMax M2.7
   server-side model update in that 3-day window. T=0 + K=10 batching
   does have some run-to-run jitter, but the magnitude and consistent
   direction across 3 seeds × 63 tasks rules out plain jitter.

### Confounders ruled out

- **GT leak through code**: no — `_strip_ground_truth` is enforced, hint
  generators don't access GT directly (§1).
- **`correction` field leaking RaMP top-3**: present in both v2 and v3
  identically; can't explain the delta.
- **EMPTY → NORMAL conversion** is a contributor: v3 has 4 fewer
  EMPTY-outcome tasks in seed 0, accounting for ~6 pp of the iter-0
  shift. But the bulk (~24 pp) is from NORMAL-outcome tasks where
  iter-0 first-PE simply changed identity.
- **Prompt/tool changes between runs**: none — I checked git log;
  no commits between `2a2eeb9` (P0 fix, 2026-05-18) and `8924da6` (D6
  reports, 2026-05-16) altered the prompt template or tool definitions.

---

## §4 Implications for `phase_b1_d5_v3_p0fix.md` and `fdc3250`

The N=3 report and the commit message both attribute the +30.69 pp top-1
gain to the P0 fix. **This attribution is wrong.** The correct framing:

1. The P0 fix **does what it was designed to do** — UV now counts in
   `_quality_score`, the feedback gate accepts more tasks, iter 2 reach
   tripled, rollback now fires (4-5 cases/seed). These mechanism-level
   changes are real and reproducible.
2. The P0 fix's **observable top-1 effect is small** (≈ −4 pp marginal,
   noisy across seeds). It is not the headline story.
3. The +30 pp top-1 jump v2→v3 is real and reproducible across seeds,
   but it is **dominated by an LLM-level change** (very likely MiniMax
   server-side, between 2026-05-15 and 2026-05-18). It is not a
   B1-architecture win.
4. Comparison artefacts dated 2026-05-18 ("B1 outperforms A3 by +20 pp")
   are tainted by this confound. To re-anchor the comparison fairly we
   would need to re-run **v2 on 2026-05-18** as a noise-floor control,
   which costs the same as a full N=3 run (~$7, ~2 h).

---

## §5 What is and is not safe to claim

**Safe** (mechanism, not affected by LLM noise):
- The P0 fix correctly expands the feedback funnel (+30 trigger, +72 iter-2 reach).
- Rollback now fires (1 → 14), confirming the gate change is reaching the rollback logic.
- The aggregator-bug retraction of D5 §4 ("D4 dormant") stands: feedback truly fires 144/189 in v2 even before P0 fix.
- Tautology pattern (driver ↓6 pp, membership ↑10 pp) is cross-seed and present in both v2 and v3.

**Unsafe** without a re-run control:
- Any "B1 vs A3" top-1 comparison drawn from the 2026-05-18 v3 numbers (e.g. "B1 +20 pp over A3 63.5 %").
- The v2 → v3 +30.69 pp delta being framed as the P0 fix's effect.
- "P0 fix is the dominant lever for top-1" — false; feedback's top-1 contribution is small (±10 pp at most) and roughly unchanged between v2 and v3.

---

## §6 Recommendation

**Halt the verification pass.** Do not proceed to Step R (red-line #4
driver-filtered correlation on v3) until the user decides on one of:

- **A) Re-run v2 baseline on 2026-05-18 model** to isolate P0-fix-only
  effect. ~2 h wall, ~$7.
- **B) Treat v3 as the "new baseline"** and stop trying to attribute the
  delta. Caveat all v3-vs-v2 comparisons in `phase_b1_d5_v3_p0fix.md`
  with a §"LLM-version confound" note. Cheap.
- **C) Investigate MiniMax model version**: check API headers /
  changelog for a 2026-05-15→18 update. Cheap (15 min) but probably
  unanswerable from outside.
- **D) Bite the bullet and re-run A3 baseline on 2026-05-18 too**, so
  the "B1 vs A3" comparison is on the same model version. More
  expensive (A3 baseline is another full run).

The user's spec for this verification pass said: **"Leak check 暴露问题
→ halt, 把现场写 §3 等我看"**. This finding qualifies. Halting.

---

## §7 Cost so far

- §1 (code grep): ~5 min, $0.
- §2 (sample 5 narratives): ~5 min, $0.
- §3 (attribution decomposition): ~10 min, $0.
- Total: ~20 min, $0.
- No new LLM calls.
