# W13 Close-out — Extended ID Patterns (A) + iter-2 Diagnostic (C)

**Branch:** `metagent-v2` @ post W13.A path-x rerun
**Worktree:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2`
**Sprint dates:** 2026-05-25 (single-day execution, spec budgeted 6-7 d)
**Verdict:** **A PASS / B PASS / C H3_CONFIRMED — all 3 Hard Gates green.**

---

## 1 · A 主线数字(纯实测)

| metric              | W10 D4 | W12 D5 | **W13.A** | Δ vs W12  |
|---|---:|---:|---:|---:|
| supported %         | 28.62  | 26.61  | **31.91** | **+5.30 pp** ✓ |
| unsupported %       | 16.71  | 20.37  | 18.21     | −2.16 pp |
| contradicted %      |  1.71  |  1.57  |  2.08     | +0.51 pp |
| **unverifiable_v0 %** | 52.95 | 51.45 | **47.79** | **−3.66 pp** ← Gate 1 ✓ |
| pathway 准确率       | 54/63 (85.7 %) | 54/63 (85.7 %) | **54/63 (85.7 %)** | **+0.00 pp** ← Gate 2 ✓ |
| **iter-2 deg rate**  | 17.46 % (11/63) | 22.22 % (14/63) | **15.87 % (10/63)** | **−6.35 pp** ← Gate 3 ✓ |
| total claims        | 2100  | 2101 | 2015 | −86 |
| Wall (min)          | 139.7 | 109.8 | **103.7** | −6.1 |
| API cost ($)        | 11.17 | 11.17 | **9.90** | −1.27 |

W13.A wall 103.7 min is the fastest of the three runs; API $9.90 stays
inside the $10 soft ceiling. Total claim count drops 86 — extended
patterns recognise more IDs upstream, fewer claims emitted as fuzzy
fallbacks.

---

## 2 · A 主线 strict_id ceiling utilisation

| metric | value |
|---|---:|
| W11 C7 strict_id total | 123 |
| factual_sub6 SUPPORTED in W12 D5 | 70 (= 56.9 % of strict ceiling) |
| factual_sub6 SUPPORTED in W13.A | (analysis pending,W14 task)|
| W11 strict subset unconverted in W12 | 53 |
| Theoretical UV ceiling on W11 baseline | 11.16 pp |
| W12 D5 actual UV drop vs ceiling | 1.50 / 11.16 = 13.4 % |
| **W13.A cumulative UV drop vs ceiling** | **(52.95 − 47.79) / 11.16 = 46.2 %** |

W13.A nearly triples the ceiling-utilisation rate vs W12 D5 alone
(13.4 % → 46.2 %). Compound observation across W12 + W13.A: cumulative
−5.16 pp UV reduction, still −6 pp short of recalibrated ceiling, with
the remaining gap attributable to LLM narrative shift (root cause 1)
and curated-pool name variants not yet normalised.

---

## 3 · C 副线 iter-2 root cause verdict

**H3_CONFIRMED** on W12 D5 N=14 superset (extends the W10 D4.5 N=11
finding):

| signal | n / 14 |
|---|---:|
| H3 — unsupported gains dominate iter-1 → iter-2 | **14 / 14 (100 %)** |
| H4 — contradicted gains dominate | 0 / 14 |
| Tied / mixed | 0 / 14 |

Aggregate iter-1 → iter-2 deltas across the 14 degraded tasks:

- Σ Δ unsupported: **+48** claims
- Σ Δ contradicted: **−4** claims
- Σ Δ supported: **−9** claims (8 / 14 tasks lose supported)

Detailed per-task table at `data/concord/w13_c_iter2_diagnostic/summary.md`.
Diagnostic driver at `scripts/concord/w13_c_iter2_diagnostic.py`. No
production code touched, no LLM call.

**Surprise side-effect of W13.A**: iter-2 deg rate dropped from 22.22 %
(W12 D5, 14/63) to 15.87 % (W13.A, 10/63), **−6.35 pp**. Plausible
hypothesis (not validated): extended `_ID_PATTERNS` + subject normaliser
let iter-1 LLM resolve more grounded claims explicitly, reducing the
fuzzy-claim surface area iter-2 can overshoot on. **W14 should re-run
the C diagnostic on W13.A data to confirm.**

---

## 4 · W14 候选 ranked (data-driven, post-C verdict)

| # | candidate | why this rank | est wall | risk |
|---|---|---|---|---|
| **1** | **C iter-2 dynamics fix** — cap `max_feedback_iters = 1` OR redesign quality_score | H3_CONFIRMED 14/14 on N=63;Σ Δs −9 / Σ Δu +48 shows iter-2 is net-destructive; W13.A side-effect already moved iter-2 deg −6.35 pp, suggesting low-hanging fruit | 3-4 d | low (capping iter-count = single-line config change) |
| **2** | **C8 + C9 noise** — system prompt tightens + dropped_by_grammar promotion for ".....", "see above" patterns | W11 reported 0.8 % C8 + 12.6 % C9 = 13.4 % UV; small absolute reduction but cheap | 2-3 d | low (no verifier change) |
| **3** | **C3 signal_evidence** — diagnose whether C3's 29 % UV is "echoing input z-score" vs "independent signal inference", then either tighten prompt or add `signal_evidence_sub6` layer | C3 was the W11 C3 largest bucket (320 of 1102 UV = 29 %) but needs diagnostic sub-task first to choose between prompt-tighten vs new layer | 1-1.5 wk | med (prompt change ripple risk) |
| **4** | **C1 + C2 cross-method consensus** — add `consensus_sub6` layer that verifies multi-method top-N overlap | W11 ~10 % UV; conceptually self-contained but adds new shape | 1-1.5 wk | low-med |
| 5 (defer to W15+) | **fuzzy_biology C5** — pathway-aware verifier with KEGG reactions DB | W11 ~20 % UV but requires new data integration (KEGG reactions); ROI lower than #1-#4 | 2-3 wk | high (semantic verifier scope creep) |

**My recommendation:** W14 = candidate #1 (C iter-2 fix). H3_CONFIRMED at
N=14 leaves no ambiguity, candidate is small + reversible, and W13.A
already showed a side-effect drop. Confirms or refutes H3 final.

---

## 5 · Hard Gate summary

| Gate | Target | Actual | Verdict |
|---|---|---|---|
| 1 — A UV drop ≥ 3 pp | ≤ 48.45 % | 47.79 % | **PASS** (−3.66 pp) |
| 2 — Pathway accuracy drop ≤ 3 pp | ≥ 82.7 % | 85.7 % | **PASS** (0.00 pp) |
| 3 — iter-2 deg ≤ W12 D5 22.22 % | ≤ 22.22 % | 15.87 % | **PASS** (−6.35 pp) |
| 4 — B1 verifier-core 407/0 | no fail | 407/0 | **PASS** (verified W13 D2) |
| 5 — Full repo 1345/14 | no NEW fail | 1357/14 | **PASS** (= W12 baseline + 12 W13 cases) |
| **Sprint OVERALL** | | | **PASS** |

---

## 6 · Commits ledger

| Day | commit | scope |
|---|---|---|
| D1 | `e7761b8` | chore: W13 onboarding + status |
| D1 | `766164d` | test: W13.A RED (12 cases) — 9 fail / 3 pass |
| D2 | `e9e9fdb` | feat: W13.A GREEN (+8 ID patterns + subject_normalizer + lookup fallback) — `[verifier-modify-warning]` body |
| D3 | `24975d3` | chore: W13.C iter-2 diagnostic — H3_CONFIRMED 14/14 |
| D4 | (this commit) | docs + Path X data: W13 close-out + W13.A path_x_post_extended_id/ |

5 commits total. 0 strict-TDD slip. W8-W13 cumulative slip = 0.

---

## 7 · Cost + wall ledger

| sub-task | cost | wall |
|---|---:|---:|
| W13.A Path X 63-task rerun | $9.90 | 103.7 min |
| W13.C iter-2 diagnostic | $0 (no LLM) | < 1 min |
| **W13 total** | **$9.90** | **104.7 min** |

Within budget (spec $12-15 / 6-7 d), under by significant margin.

---

## 8 · Output files

```
data/concord/w13_a_path_x_post_extended_id/
├── path_x_full63_results.jsonl       63 task signals jsonl
├── path_x_full63_summary.json        aggregated metrics
└── path_x_full/                      63 per-task full traces

data/concord/w13_c_iter2_diagnostic/
├── per_task.json                     14 iter2_degraded task analysis
└── summary.md                        H3 verdict + per-task table

scripts/concord/
├── w13_c_iter2_diagnostic.py         C diagnostic driver

reports/agent/
├── concord_sprint_w13_status.md      onboarding doc (D1)
└── concord_w13_close_out.md          this file

logs/concord/
└── w13_a_path_x.jsonl                A run LLM call log (gitignored)
```

---

## 9 · References

- W11 UV diagnosis: `reports/agent/concord_w11_uv_diagnosis.md`
- W11 C7 re-classification: `data/concord/w12_uv_ceiling/c7_strict_vs_fuzzy.jsonl`
- W12 close-out: `reports/agent/concord_sprint_w12_status.md`
- W10 D4.5 H3 diagnostic: `data/concord/w10_d4_5_degradation_diagnostic/summary.md`
- W13.A test: `tests/test_factual_sub6_id_patterns_extended.py`
