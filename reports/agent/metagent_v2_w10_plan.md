# MetAgent-v2 W10 sprint plan — FINAL

**Generated:** 2026-05-21 (post-merge day +1)
**Sanity-checked:** 2026-05-21 by user (5 open questions resolved — see §5)
**Branch:** `metagent-v2`
**Status doc baseline:** `reports/agent/metagent_v2_merge_status.md`

> Priorities and 7-day shape below are locked. D1 starts on commit of
> this file. Re-issued as `metagent_v2_w10_plan.md` (no "_draft") with
> the agreed sanity-check resolutions applied.

---

## 1 · Inputs

| Source | Items contributed |
|---|---|
| `merge_prep_b1_into_concord.md` §7 | 7.1, 7.2, 7.3, 7.4, 7.5 |
| `phase_b1_merge_prep.md` §8 | 8.1, 8.2, 8.3, 8.4, 8.5 |
| `metagent_v2_merge_status.md` §6.3 | M1 ✓, M2 ✓, M3 ✓ (closed 2026-05-20/21) |

10 open items inherited, sanity-checked into 9 actionable items + 1
doc-only item (P2-D, no code action).

---

## 2 · Priority sort (sanity-checked)

### P0 — paper-critical or quality-floor (must do W10)

| ID | What | Why P0 | Effort | Risk |
|---|---|---|---|---|
| **P0-A** | **Fix mock-signature drift in `tests/eval_sub6/test_prompts.py`, `test_run_sub6{a,b}.py`** (B1 prep §8.2) | 4 of the 18 post-merge baseline failures vanish. Baseline becomes 14 fail (all env-driven), strictly cleaner gate for any W10 ablation. | **0.5 day** | LOW |
| **P0-B** | **Wire `unverifiable=` + `dropped=` into `concord/agent/react_runner.py:_resolve_default_feedback_builder`** (INV prep §7.2) | Addresses W10 Issue #2 (11.1% iter-2 quality degradation per W9 D6). B1 D4 already extended the API; concord still passes only contradicted/unsupported. | **0.5 day** | LOW |
| **P0-C** | **Route ConcordMet verifier through `verifier.claim_extractor.extract_claims_from_json` when LLM output is grammar-v2 JSON** (INV prep §7.3) — **promoted from P1-A per OQ1** | ConcordMet's system prompt mandates grammar-v2 JSON. Skipping one LLM extract call per task verify → ≈ 5% cost reduction (≈ $1 / 63-task run). Enables a cheaper W10 D4-D5 Path X full rerun. Partial credit on W10 Issue #6 (cost ablation). | **1 day** | LOW-MED — behaviour shift if extractor produces a slightly different claim set on edge cases. Prep doc §5.6 flags this as the single biggest behavioural risk inherited from the merge. |

**P0 total: 2 day.**

### P1 — important / paper-relevant (should do W10 if P0 leaves room)

| ID | What | Why P1 | Effort | Risk |
|---|---|---|---|---|
| **P1-A** | **Adapt B1's `aggregate_seed_summary.py` to Path X per-seed jsonls** (INV prep §7.5) — was P1-B | Gives ConcordMet's W9 D5 numbers the same CI95 + sign-test rigour B1 reports (W10 Issue #4 "N_eff ≈ 13 bootstrap CI"). Needs schema adapter (concord `ConcordFeedbackResult` ≠ B1 `IterationRecord`). | **1-1.5 day** | MED — unit drift risk between metric definitions |
| **P1-B** | **Update `reports/agent/phase_b1_followup_debt.md` to mark P0 #1 closed** (B1 prep §8.1) — was P1-C | Cosmetic; commit `ed6243b` closed the `VerifiedClaim.grammar` passthrough debt but the report still lists it open. | **0.1 day** | NONE |

**P1 total: ~1.6 day.**

### P2 — cleanup / cosmetic (defer to W11+ unless idle)

| ID | What | Effort | Notes |
|---|---|---|---|
| **P2-A** | Alias `ConcordTaskOutcome = TaskOutcome` (INV prep §7.1) | 0.1 day | Bundle with P0-B in a single concord/agent/ follow-up commit |
| **P2-B** | Cross-check verifier `task_outcome` vs runner `task_outcome` (INV prep §7.4) | 0.5 day | Diagnostic warning only |
| **P2-C** | Add prose-narrative path to `scripts/eval_sub6/step_r_per_layer.py` (B1 prep §8.3) | 1 day | **Stays P2 per OQ2** — only needed if paper Discussion grows to demand A3 per-layer |
| **P2-D** | Red-line #4 (+3.50 pp, durable FAIL) — Discussion material (B1 prep §8.4) | 0 day | No code action |
| **P2-E** | Remove `/tmp/b1_v2_rerun` + `/tmp/a3_rerun` worktrees (B1 prep §8.5) | 0.1 day | **Per OQ4** — defer to W11 |

**P2 total: ~1.7 day** if all done.

---

## 3 · 7-day W10 shape (locked)

Time split per OQ5: **5 day Track A + 1.5 day Track B + 0.5 day buffer**.

| Day | Track A (technical) | Track B (paper / writeup) | Output |
|---|---|---|---|
| **D1 Wed 2026-05-22** | P0-A (mock fix) + P1-B (followup_debt.md) | — | Baseline 18 → 14 fail; followup_debt.md accurate |
| **D2 Thu 2026-05-23** | P0-B (build_feedback_message wire) + P2-A bundle (ConcordTaskOutcome alias) | — | ConcordMet uses full D4 hint set |
| **D3 Fri 2026-05-24** | P0-C (extract_claims_from_json wire + tests) | — | Cheaper verifier path live; ready for rerun |
| **D4 Sat 2026-05-25** | P1-A part 1 (schema adapter for Path X) — kick off **Path X full rerun overnight** (≈ $22, ~3 h sequential K=10 on cheaper P0-C path) | — | Adapter PR-ready; rerun running |
| **D5 Sun 2026-05-26** | P1-A part 2 (CI95 columns + cross-pipeline comparison report B1 vs ConcordMet on Path X same-LLM) | — | First paper-grade ConcordMet table with CI95 |
| **D6 Mon 2026-05-27** | P2-B (task_outcome cross-check sanity) | Paper outline + methods section integration (grammar-v2 narrative + 5-PA dispatcher) | Sanity-check warning surfaced; ms outline locked |
| **D7 Tue 2026-05-28** | 0.5 day buffer | Paper results section first pass | W10 close-out report |

**Cost budget:** ≈ $22-25 (single Path X rerun on cheaper P0-C path). Under $30/sprint ceiling.
**Out of scope for W10:** P2-C, P2-D (Discussion-only), P2-E (worktree cleanup).

---

## 4 · Dependencies / sequencing

```
P0-A (mock fix)   ── independent ───── D1
                                        │
P1-B (debt doc)   ── independent ───── D1 (parallel to P0-A)
                                        │
P0-B (feedback) ─┐                     │
                 ├──── D2              │
P2-A (alias)   ──┘                     │
                                        │
P0-C (extract_claims) ── after P0-B ── D3 (both touch react_runner.py)
                                        │
P1-A part 1 (adapter) ── independent ── D4
P1-A part 2 (CI95)    ── after P1-A p1, after Path X rerun ── D5
                                        │
P2-B (cross-check) ── after P0-B (uses TaskOutcome from both sides) ── D6
```

**No item blocks more than one other.** P0-A + P1-B run in parallel on D1.

---

## 5 · Sanity-check resolutions (2026-05-21)

| OQ | Question | Decision |
|---|---|---|
| OQ1 | P1-A `extract_claims_from_json` → P0? | **YES** — promoted to P0-C |
| OQ2 | P2-C `step_r` prose-narrative path → P1? | **NO** — stays P2 |
| OQ3 | Path X full rerun budgeted in W10? | **YES** — D4-D5 (≈ $22 on cheaper P0-C path) |
| OQ4 | B1 worktree (`metagent_day1_v5`) cleanup? | **W10 keep** — W11 decide P2-E |
| OQ5 | Track A vs Track B time split? | **5 day Track A + 1.5 day Track B + 0.5 day buffer** |

---

## 6 · References

- Merge commit: `8ce5ad9`
- Source freeze tags: `metagent-v2-base-b1` (`ed6243b`), `metagent-v2-base-investigation` (`3ffe621`)
- Merge status: `reports/agent/metagent_v2_merge_status.md`
- INV-side prep: `reports/agent/merge_prep_b1_into_concord.md`
- B1-side prep: `reports/agent/phase_b1_merge_prep.md`
- W9 framework health v2: `reports/agent/concord_sprint_w9_framework_health.md`
- B1 followup debt: `reports/agent/phase_b1_followup_debt.md`

---

## 7 · P0-C status — closed via regression lock (not new wire) — 2026-05-21

Pre-implementation recon during W10 D3 revealed that
`verifier/agent.py:_extract_classify` (B1 D2 commit `2354011`) already
implements the JSON-first extract routing. The W10 plan v1 description
of P0-C as a "wire" was prep-doc misclassification: §7.3 of
`merge_prep_b1_into_concord.md` missed the existing implementation.

P0-C is hereby closed via regression-lock tests
(`tests/concord/test_d3_zero_llm_extract_invariant.py`, RED commit
`9b0f899`) confirming:

  - zero-LLM extract for grammar-v2 JSON narratives
    (test_grammar_v2_json_narrative_triggers_zero_llm_extract)
  - dropped claim surfacing to `VerifiedIdentification.dropped_claims`
    (test_grammar_v2_json_dropped_claims_surface_to_verdict)
  - backward-compat fallthrough for legacy prose narratives
    (test_non_json_narrative_falls_through_to_llm_extract)

Anchor comment added to `concord/agent/verifier_adapter.py`
(`concord_result_to_b1_narrative` docstring, commit `48a71dd`) so
future readers re-architecting the narrative → verify_sub6 boundary
are pointed at the regression test.

No production code changed by P0-C. Cost-saving claim corrected:
the expected ~5% cost reduction was ALREADY REALIZED in W9 D5 runs
($22) — not a delta the D4 Path X rerun will demonstrate.

Break-verification: confirmed that `extract_calls = 1` (instead of 0)
in the JSON-success branch of `_extract_classify` makes tests #1 and #2
FAIL with the right reason; reverted before the RED commit, git diff
verifier/agent.py is empty.

W10 D3 sprint outcome: 2 commits (RED + GREEN/anchor + this plan update),
0 production behavior change, 3 regression-locked invariants, 0 strict
TDD slip (invariant-lock variant, audit-acceptable because the RED
commit body honestly states "currently passes due to B1 D2 implementation").
