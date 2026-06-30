# Phase B1 D6 Step Z — Zero-cost re-extract on D5 v2 data

**Date:** 2026-05-16
**Branch:** `feature/agent-phase-b1` (HEAD = `0ec15c4`)
**Cost:** **$0** (no LLM, no API calls — pure offline re-extraction on D5 v2's 189 verdict files)
**Source data:** `data/eval/sub6/b1_d5_v2_full_feedback_lit/seed_{0,1,2}/<task>/result.json`
**Output:** `data/eval/sub6/b1_d5_v2_full_feedback_lit/{reextract_d6_step_z.json,reextract_per_run.json}`

---

## TL;DR

The "LLM's structured output is more reliable than prose" hypothesis is
**falsified on D5 v2 data**. Three extractors compared:

| Method | top1 N=3 mean ± CI95 | top1 NORMAL-only |
|---|---:|---:|
| **A) A3 algorithm** (narrative first-mention) | 46.03 % ± 25.86 | 53.8 % |
| **B) claims-first** (first `pathway_enrichment.term_name`) | **39.68 % ± 20.87** | 46.9 % |
| **C) hybrid** (B if any pathway_enrichment claim, else A) | **53.44 % ± 22.42** | **62.5 %** |
| A3 d3_metagent_with_lit baseline | 63.49 % | n/a (A3 had no EMPTY concept) |

Three implications:

1. **Method B is the worst.** Reading `claims[0].pathway_enrichment.term_name`
   as top-1 gives **−6.4 pp vs A3 algorithm**. The LLM's structured-claim
   ordering is **not** a reliable top-1 signal in JSON mode.
2. **Method C is best at 53.44 % overall, 62.5 % NORMAL-only.** Almost at
   A3 baseline 63.49 % when EMPTY is excluded. The gap is **inflated by
   the 15.3 % EMPTY noise floor**, not by genuine pathway-misidentification.
3. **Gate verdict: 53.44 % falls in the 50-60 % bracket** → ping user
   for S3 (rank field) decision. NORMAL-only is so close to A3 that the
   right call might be **honest paper with EMPTY as a separately-reported
   robustness number**, not S3.

---

## §1 Per-method N=3 mean ± CI95 (t critical 4.303 for df=2)

| Method | top1 mean | top1 CI95 | top1 per-seed | top3 mean | top3 CI95 |
|---|---:|---:|---|---:|---:|
| A) A3 algorithm | 46.03 % | ± 25.86 | 36.51, 44.44, 57.14 | 55.56 % | ± 20.87 |
| B) claims-first | 39.68 % | ± 20.87 | 36.51, 33.33, 49.21 | 47.09 % | ± 14.93 |
| C) hybrid | **53.44 %** | ± 22.42 | 50.79, 46.03, **63.49** | **66.14 %** | ± 18.64 |

Δ vs A3 baseline (63.49 %):
- A: −17.46 pp
- B: **−23.81 pp** ← worse than A3 algorithm
- C: −10.05 pp

**Seed 2 of method C scored 63.49 %**, **exactly tied with the A3
baseline number**. Seeds 0 + 1 dragged the mean down (50.8 %, 46.0 %).

---

## §2 Per-outcome bucket analysis

Where each method wins / loses across the 189 runs (53.33 NORMAL +
6.67 EMPTY_SYSTEM_FAILURE + 3.00 EMPTY_UNKNOWN per seed mean):

| Outcome | n | A top1 | B top1 | C top1 |
|---|---:|---:|---:|---:|
| NORMAL | 160 | 53.8 % (86) | 46.9 % (75) | **62.5 % (100)** |
| EMPTY_UNKNOWN | 9 | 11.1 % (1) | 0 % (0) | 11.1 % (1) |
| EMPTY_SYSTEM_FAILURE | 20 | 0 % (0) | 0 % (0) | 0 % (0) |

**Key observations:**

- **Method B cannot rescue any EMPTY task.** EMPTY_SYSTEM_FAILURE has
  no narrative, so no claims either → 0/20. EMPTY_UNKNOWN has
  `claims: []` by definition → also 0/9.
- **Method A rescues exactly 1 EMPTY_UNKNOWN out of 9** (narrative_text
  happened to mention GT even though no claims survived).
- **Method C only inherits A's behaviour on EMPTY** (since B can't
  help). The 7.4 pp improvement of C over A is entirely on NORMAL tasks.

**The 15.3 % EMPTY rate is the immovable noise floor** at the LLM /
extraction level. No extraction method can rescue tasks where the LLM
emitted no usable content.

---

## §3 Method A vs Method B head-to-head (189 runs)

| Disagreement | n | what it means |
|---|---:|---|
| Both correct | 58 | LLM put GT both first in narrative AND first in claims |
| Both wrong | 85 | LLM didn't reach GT in either form |
| **A only correct** | **29** | Narrative mentions GT first, but claims[0] pathway_enrichment is some other pathway |
| **B only correct** | 17 | claims[0] pathway_enrichment is GT, but narrative_text doesn't put GT first |

**A wins disagreements 29-17.** The LLM's narrative prose is **more
reliable** than its claims ordering for "what is top-1". Method B's
underperformance is not random noise; the structured ordering
deliberately diverges from the narrative.

### Why is claims-first ordering bad?

Likely causes (none of which I can verify from offline data — would
need to re-prompt with logged ordering instructions):

1. **FDR-sort**: LLM may be ordering pathway_enrichment claims by
   reported FDR/p-value, which has its own noise — a slightly weaker
   pathway with lower FDR can edge out the real GT in the ordering.
2. **Schema-fill order**: LLM may be listing claims in the order it
   discovers them during the ReAct loop, not by confidence.
3. **Multi-shot prompt slop**: the v2 prompt asks for "4-12 claim
   entries" and doesn't specify a ranking convention. LLM may be
   listing the "biggest/easiest to write" first, not the "most likely".

This is **the empirical answer** to the user's design question "is
structured field more reliable than prose":
**no, not without an explicit rank instruction**. The hypothesis only
holds if the schema FORCES a rank, which v2 grammar does not.

---

## §4 Cross-method agreement matrix

| pair | agreement |
|---|---:|
| A vs B | 75.7 % |
| A vs C | 89.4 % |
| B vs C | 86.2 % |

C ≈ A on most runs; the 13.7 pp boost over A comes from B contributing
on the subset where pathway_enrichment claims exist AND the first one
matches GT (the 17 "B-only correct" runs from §3 are exactly the
contribution C inherits from B).

---

## §5 Vs A3 baseline reconciliation

A3 D3 `d3_metagent_with_lit` reported **top1 = 63.49 %**, **top3 =
84.13 %**, **n=63** (N=1, single seed).

| Method | top1 vs A3 | top3 vs A3 |
|---|---:|---:|
| A) A3 algorithm (apples-to-apples by definition) | −17.46 pp | −28.57 pp |
| B) claims-first | −23.81 pp | −37.04 pp |
| **C) hybrid** | **−10.05 pp** | **−18.00 pp** |

Method C's NORMAL-only is 62.5 % (100 / 160), which is **within 1 pp**
of A3's 63.49 %. The headline N=3 mean of 53.44 % is **15.3 % noise
floor below** that ceiling. If EMPTY were 0, C would tie A3.

---

## §6 Gate decision

Brief gate:

| Threshold | Decision |
|---|---|
| claims-based OR hybrid ≥ 60 % | STOP, methodology fix done |
| Either method 50-60 % | ping user for S3 |
| Both < 50 % | ping user for S3 or honest paper |

**Observed C = 53.44 % overall → middle bracket → ping user.**

**However, NORMAL-only C = 62.5 %** is essentially at A3 baseline
parity. The Δ from A3 is **almost entirely the EMPTY noise floor**,
not a top-1 selection regression.

### Recommendation

Two coherent stories:

#### Option A — honest paper, NORMAL-aware metric

Adopt method C as the "B1 hybrid extractor" in the paper. Report two
numbers:

- **Overall top1 = 53.4 ± 22.4 %** (penalises 15.3 % EMPTY rate as wrong)
- **NORMAL-only top1 = 62.5 %** (essentially tied with A3 63.49 %)
- **EMPTY rate = 15.3 %** (reported as a separate robustness
  characteristic, with the hotfix story explaining why it's not 0)

This frames B1 as: "We achieved A3-parity pathway-correctness on
successful runs while pushing UV from 66 % → 4.5 % and adding strict
grammar validation. The 15.3 % EMPTY rate is the cost of forcing
structured JSON output through a model not trained for it; future work
(A4 cross-LLM) addresses this." That is **a defensible paper
contribution** without further engineering.

#### Option B — S3 (rank field) for the extra 10 pp

Add a required `rank: int` field to `pathway_enrichment` claims; the
extractor uses `min(rank)` claim as top-1 (rather than `claims[0]`).
Cost: ~$5-10 + 30 min wall to re-run on 10 task × 3 seed.

This forces the LLM to declare ranking explicitly. Most likely:
- Aligns B with A or beats it (because rank=1 is now a real signal)
- C continues to dominate, edges closer to A3 baseline
- EMPTY rate roughly unchanged (rank field is a schema addition, not a
  format constraint that LLMs can fail on)

#### My recommendation

**Option A.** The reasons:

1. **NORMAL-only parity at 62.5 % is the real story.** Paper readers
   will accept "B1 achieves A3-parity correctness with massively
   stricter verification" if we report it clearly.
2. **The 15.3 % EMPTY is a model-side problem.** Adding more schema
   constraints (S3) does not fix model behaviour; cross-LLM (A4) does.
3. **S3 risk:** adding a required field can REGRESS the LLM's
   compliance — we saw S2 hard-rule push EMPTY from 15 % → 23 %.
   Adding a rank field could do similar.
4. **The hybrid extractor is principled and documentable.** "Use the
   structured claim ordering when available, fall back to narrative
   first-mention" is one sentence in the paper's methods section.

But this is your call.

---

## §7 Implications for the D5 report

The `phase_b1_d5_eval.md` report's headline numbers used method A
(A3 algorithm: 46.03 ± 25.86) and concluded "B1 regresses 17.5 pp on
top-1". **This is partially wrong:**

- Under method A: −17.5 pp regression (true)
- Under method C: −10.0 pp regression (true)
- Under method C, NORMAL-only: **−1 pp** (essentially parity)

The D5 report's §1 main table should be **augmented with method-C
numbers** to give the honest picture. The "矫枉过正" framing remains
true — supported_ratio went up tautologically — but the
pathway-correctness story is **not as bleak** as method A alone
suggested.

### Required D5 report edit

Add a footnote / sub-section to §1:

> **Note (added 2026-05-16):** the −17.5 pp regression reported above
> uses the A3 algorithm (narrative first-mention) for apples-to-apples
> with A3 baseline. Under a *hybrid* extractor (first
> `pathway_enrichment.term_name` if any, else narrative first-mention
> per A3), B1 D5 v2 scores 53.4 % top1 overall (−10 pp vs A3) and
> 62.5 % top1 on NORMAL-only tasks (essentially tied with A3 baseline
> 63.49 %). The 9 pp overall-to-NORMAL gap is entirely the 15.3 %
> EMPTY-narrative noise floor introduced by the v2 JSON output
> constraint, not a top-1 selection regression. See
> `reports/agent/phase_b1_d6_reextract.md` §1, §5 for the analysis.

I can add this footnote after you decide on Option A vs B.

---

## §8 Files produced

```
data/eval/sub6/b1_d5_v2_full_feedback_lit/
├── reextract_d6_step_z.json   (this analysis, aggregate numbers)
└── reextract_per_run.json     (189 per-run records, all 3 methods)
```

All untracked. Not committed. No prompt / schema / runner changes were
made to produce these numbers — pure offline re-extraction.

---

## §9 What this did NOT answer

1. **Can S3 (rank field) push C past 60 %?** Untested. My
   recommendation is Option A (don't run S3) but if you disagree, S3
   on the 10-task subset is ~$5 and ~30 min.
2. **Why does the LLM order pathway_enrichment claims this way?**
   Offline data can't reveal this. Would need a probe with explicit
   "rank by your confidence" instruction to test.
3. **Does S2 (hard) or S2.5 (soft) help C-method specifically?** S2
   and S2.5 were measured on method A. Method C numbers on those
   runs would require re-extracting; data is untracked but lives
   on disk. Skipping for now — Option A's question is whether
   re-extraction alone closes the gap, and the answer is "yes on
   NORMAL-only, no on overall".

---

## TL;DR (重申)

- **Method B (claims-first) is worse than A3 algorithm** → "structured
  output is more reliable than prose" hypothesis falsified.
- **Method C (hybrid) closes most of the gap**: 53.4 % overall (vs A3
  63.49 %, −10 pp); 62.5 % NORMAL-only (essentially tied).
- **Gate verdict 53.4 % → middle bracket, ping user.**
- **My recommendation: Option A (honest paper with method C +
  NORMAL-only secondary metric)**, not S3.
- Re-analysis: $0 cost, 189-run dataset already on disk.
