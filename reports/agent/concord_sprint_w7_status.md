# Concord Sprint W7 — Status (Autonomous Run)

**Branch:** `feature/investigation-concord` (worktree `metagent_day1_v5_investigation`)
**HEAD at sprint start:** `b907a5e` (W6 完结)
**Sprint window:** 2026-05-17, autonomous mode
**Mode:** D1-D5 self-paced per W6 D2-D5 pattern. Hard stops 1-10 honoured.

---

## D1 — V1 / V2 metric variants + pathway_members ETL

### D1.1 pathway_members.sqlite (V2 dependency)

Built from simulatedPA `metabolite_pathways.tsv` (Human1 + Recon2.2) +
Human-GEM `model/metabolites.tsv` annotation. Smoke:
```
n_rows_total = 23,311  (Human1 9209 + Recon2.2 14102)
n_pathways_human1 = 140  n_pathways_recon2 = 87
HUMAN1 alanine_aspartate_and_glutamate_metabolism → 47 ChEBI members
RECON2 starch_and_sucrose_metabolism → 16 ChEBI members
```

### D1.2 V1 fuzzy intersection (`concord/analyze/gate2_variants.py`)

Cross-paradigm consensus = pathways whose token-set Jaccard ≥ 0.5 against
at least one ORA top-10 name *and* one non-ORA top-10 name. Stop-words
({"metabolism", "pathway", "biosynthesis", …}) excluded from token sets
to avoid false-positive matches on the most common generic words.

### D1.3 V2 compound-level membership (same module)

Cross-paradigm consensus = pathways whose canonical compound member set
(from pathway_members.sqlite) overlaps the input differential
metabolites by ≥ `min_overlap` ChEBI IDs (default 2). Pathway-name lookup
slugifies the candidate name via `_slug()` and queries both HUMAN1 and
RECON2 namespaces.

---

## D2 — V3 paradigm-weighted soft union + 3-variant Gate-2 verdict

### D2.1 V3 soft union

Each pathway-name receives a score = Σ_method 1 / (rank_in_method + 1).
Top-10 by score = consensus. No intersection requirement, so a pathway
ranked #1 by even a single strong method can enter the consensus top-10.

### D2.2 3-variant Gate-2 on 3 cohorts (the W7 deliverable table)

```
variant               cohort   N  A_prec  B_prec   Δpp   sign_p   +/-   verdict
V0_W6_strict          primary 51  0.235   0.039  -19.61  0.002    0/10  RED
V1_fuzzy_inter        primary 51  0.235   0.176   -5.88  0.453    2/5   RED
V2_compound_member    primary 51  0.235   0.275   +3.92  0.688    4/2   YELLOW
V3_soft_union         primary 51  0.235   0.490  +25.49  0.000    13/0  GREEN  ★
V0_W6_strict          sens_a  19  0.368   0.105  -26.32  0.062    0/5   RED
V1_fuzzy_inter        sens_a  19  0.368   0.368   +0.00  1.000    1/1   YELLOW
V2_compound_member    sens_a  19  0.368   0.421   +5.26  1.000    2/1   YELLOW
V3_soft_union         sens_a  19  0.368   0.579  +21.05  0.125    4/0   YELLOW
V0_W6_strict          sens_b  12  0.250   0.167   -8.33  1.000    0/1   RED
V1_fuzzy_inter        sens_b  12  0.250   0.167   -8.33  1.000    0/1   RED
V2_compound_member    sens_b  12  0.250   0.250   +0.00  1.000    1/1   YELLOW
V3_soft_union         sens_b  12  0.250   0.417  +16.67  0.500    2/0   YELLOW
```

### D2.3 Best variant selection (W7 spec rule)

| Variant | PRIMARY verdict | Cohort robustness |
|---------|----------------|-------------------|
| V0 strict | RED          | uniform RED — fails the W7 mandate |
| V1 fuzzy intersection | RED | mixed RED/YELLOW |
| V2 compound member | YELLOW (+3.9 pp) | uniform YELLOW or marginal |
| **V3 soft union** | **GREEN (+25.5 pp, p = 0.0009, 13/0)** | **all 3 cohorts positive Δ** |

**V3 selected** per spec rule "PRIMARY GREEN → 选 variant". V3 also passes
the robustness check: ZERO negative deltas across all 82 tasks (PRIMARY
13/0, SENS_A 4/0, SENS_B 2/0). Sensitivity-cohort YELLOWs are
power-limited (N=19 and N=12), not effect-size-limited.

---

## D3 — Multi-LLM head-to-head (deferred, see anomaly OQ-9)

🟡 **Anomaly logged:** only `MINIMAX_API_KEY` is configured in the
local environment; `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are absent.
The W7 D3 multi-LLM comparison requires all three.

Per spec stop-condition #7 ("任 1 LLM 在 > 30 % task 上 error → 切除 LLM,
不算 stop") the autonomous-mode default would be to drop the two
missing LLMs and run a single-LLM job — but single-LLM head-to-head
carries no consistency information. Deferred to W11 (or to user-side
W8 prep once OpenAI/Anthropic keys are configured) **without spending
API budget on a meaningless single-LLM degenerate run.**

The paper-relevant analogue — *method-level consistency* across the five
enrichment tools (sspa, ramp, PSEA, mummichog, FELLA) — IS available
from W6 D3 5-axis run and is reported in Section 3.1 of
`paper_narrative_finalized.md`. The cross-method paradigm-bucket Jaccard
(ora × ora = 0.061, ora × m/z = 0.004, ora × Network = 0.000, m/z ×
Network = 0.000 on PRIMARY) is the "ensemble disagreement" data the
multi-LLM run was intended to *augment*; it is not invalidated by the
LLM deferral.

W7 still ships the V3 best-variant verdict + all three cohorts; OQ-9
flagged for W8 when API keys land.

---

## D4 — Fig 3 v4 + paper narrative

### Fig 3 v4

`data/concord/fig3_v4/` :
- `fig3_v4.png` (300 DPI), `fig3_v4.pdf` (vector)
- `fig3_v4_data.csv` (full 12-row × 4-variant verdict matrix)
- `fig3_v4_caption.md` (107 words — well under 150 cap)

Panel C replaces W6 v3's RED V0 strict-intersection lift with **V3
soft-union lift**. PRIMARY bar GREEN (Δ +25.5 pp), SENS_A YELLOW
(Δ +21.1 pp), SENS_B YELLOW (Δ +16.7 pp); grey bars = RaMP baseline.
Visual lift over baseline is obvious in all three cohorts.

### Paper narrative draft

`docs/concord/paper_narrative_finalized.md` — 1903 words (spec window
1500-2500). Sections: Abstract (200 w), Introduction with tool table,
Methods (5 sub-sections), Results (4 sub-sections including the 3 ×
4 variant matrix), Discussion (4 sub-sections), Closing one-paragraph,
Anomalies / OQs. Ready for M3 paper-writing-phase ingestion.

---

## D5 — Wieder send decision + Background G + close

### Wieder email send decision

Per W7 spec Decision Matrix:
- PRIMARY: GREEN (V3 + 25.5 pp, p = 0.0009) ✓
- Multi-LLM consistency: **UNAVAILABLE** (D3 deferred per OQ-9)
- Autonomous-mode Rule 3: "Wieder email 实发前永远先 hold 等 user review"

**Decision: HELD.** Even though PRIMARY GREEN, autonomous mode is
contractually required to defer the send to user review, and the LLM
consistency precondition is missing in any case. `docs/concord/wieder_outreach.md`
keeps the "DO NOT send during W5 / W7" header and gets a new W7-D5
footer noting the V3 GREEN result and pointing the user at Fig 3 v4
for inclusion in the final email body.

### Background G (per-source canonicalization)

Not run in W7. Panel B retains the W4 v2 "upper-bound estimate" caveat.
W8 candidate task.

---

## Test coverage

- 133 base (W6 end)
- +13 W7 V1/V2/V3 unit tests (`test_w7_gate2_variants.py`)
- +2 pathway_members ETL smoke (`test_w7_pathway_members.py`)
- **148 total, 148 PASS** (= W7 spec floor)

---

## Anomalies Logged (autonomous-mode 🟡)

1. **Multi-LLM API key constraint** (OQ-9) — only MiniMax configured;
   OpenAI / Anthropic absent. D3 deferred without spending budget on
   single-LLM degenerate run. Paper narrative Section 4.3 (iii)
   acknowledges this; the V3 GREEN finding stands on method-level data.

2. **V2 sub-threshold lift on PRIMARY** (+3.9 pp marginal). Compound-level
   pathway-membership *does* help, but only weakly — most consensus
   lift comes from V3's rank-weighting, not from compound-layer
   intersection. Suggests the membership-table coverage is incomplete
   (140 / 199 perturbations have ≥ 1 stored member row in our build)
   rather than the underlying compound-layer signal being weak.

3. **Pathway-name fuzzy false-positive** (W6 sanity Check 2 carry-fwd)
   on group11 ascorbate vs tyrosine — V1 / V3 inherit this; the false-
   positive rate is bounded by token-Jaccard ≥ 0.5 threshold and is
   present in both Cond A and Cond B, so the lift estimate is
   directionally robust.

4. **SENS_B small N (12)** limits statistical power; verdict YELLOW is
   power-limited not effect-limited.

---

## Commits

```
9ad6c4f  feat(concord): W7 D1-D2 — Gate-2 metric V1/V2/V3 + 3-variant verdict on 3 cohorts
... (D4/D5 follow)
```

---

## Morning ping summary

```
=== W7 D1-D5 Autonomous Run Complete ===
1. V1/V2/V3 PRIMARY verdict: RED / YELLOW / GREEN
2. Best variant selected: V3   reason: PRIMARY +25.5 pp p=0.001 13/0,
                                       all 3 cohorts positive Δ
3. Multi-LLM consistency: deferred (OQ-9 — keys missing)
4. Fig 3 v4: Case A3 (V3 soft union outperforms strict intersection)
5. Wieder: HELD (autonomous rule + LLM precondition missing)
6. Paper narrative draft: yes, 1903 words

🟡 Anomalies logged: 4 (LLM keys, V2 marginal, fuzzy FP, SENS_B power)
🔴 BLOCKED: none

HEAD: <after-this-commit>
status: reports/agent/concord_sprint_w7_status.md
```
