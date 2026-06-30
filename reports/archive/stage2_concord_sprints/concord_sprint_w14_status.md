# W14 — noise prompt 收紧 (A) + iter-2 cap (B)

**Worktree:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2`
**Branch:** `metagent-v2` @ `bc3d3e9` (W13 close-out)
**Started:** 2026-05-25
**Mode:** 5-6 工作日,A + B 并行,有人值守

---

## 0 · Onboarding (per W14 spec §0)

### Tier 1 — W13 close-out + iter-2 现状

**`reports/agent/concord_w13_close_out.md`** (commit bc3d3e9):
- UV % 累计降 −5.17 pp (W10 D4 52.95 % → W13.A 47.79 %)
- iter-2 deg rate W12 D5 22.22 % → W13.A **15.87 % (−6.35 pp)** — surprise side-effect of W13.A extended ID patterns
- Hypothesis: extended `_ID_PATTERNS` + subject normaliser → iter-1 more confident → iter-2 fewer overshoot opportunities

**`data/concord/w13_c_iter2_diagnostic/summary.md`** (commit 24975d3):
- H3_CONFIRMED on N=14 iter-2-degraded tasks (W12 D5 superset)
- 14/14 unsupported-dominant (vs 0/14 contradicted-dominant)
- Σ Δ unsupported +48 / Σ Δ contradicted −4 / Σ Δ supported −9 (iter-1 → iter-2)
- iter-2 confirmed net-destructive on this slice → W14.B `max_feedback_iters=1` is justified

### Tier 2 — W14 改动区

**`prompts/concord/concord_react_prompt.md`** (117 lines):
- Current state: NO banned-phrase section. Contains naming-bridge / tool-discipline rules only.
- W14.A target: append a `## BANNED PHRASES — DO NOT WRITE` section listing meta-filler / template / self-reference patterns.

**`concord/agent/react_runner.py`**:
- `DEFAULT_MAX_FEEDBACK_ITERS = 2` at line 50
- `max_feedback_iters: int = DEFAULT_MAX_FEEDBACK_ITERS` at line 354 (dataclass default)
- Validation `0 ≤ max_feedback_iters ≤ 2` at line 366
- Loop: `for k in range(1, max_feedback_iters + 1)` at line 631
- W14.B target: `DEFAULT_MAX_FEEDBACK_ITERS = 1`. Backward compat preserved because explicit `max_feedback_iters=2` still passes the validation gate.

**`verifier/grammar.py`**:
- ⚠ **`DroppedReason` enum does NOT exist** in current codebase. `drop_reason` is a `str | None` field on `ValidationResult` (line 362).
- W14 spec §3 / §4 line 222 assumes the enum exists. Actual implementation must **create the `DroppedReason` enum** (pure-add) and migrate `drop_reason: str | None` callers (would be ⚠ modify — see §0 confirmation deviation note below).
- Alternative path: keep `drop_reason: str`, use the literal `"noise_pattern"` as a magic-string convention. Pure-add to grammar.py, no schema change.

### Tier 3 — W12 教训 + 政策

- W12 教训 `feedback_uv_sprint_must_reclassify_first`: every UV sprint must run strict-vs-fuzzy re-classification on the target W11 bucket before setting Hard Gate target.
- Verifier modification policy (2026-05-22): ✅ pure-add free / ⚠ modify with `[verifier-modify-warning]` body + justification + B1 test no-regression / ❌ B1-core helpers default banned.

### Tier 4 — §0 mandatory re-classification (executed 2026-05-25)

**Script:** `scripts/concord/w14_c8c9_strict_vs_valid.py`
**Output:** `data/concord/w14_uv_reclassify/{c8c9_strict_vs_valid.jsonl,ceiling_summary.json}`
**LLM call log:** `logs/concord/w14_c8c9_reclassify.jsonl`
**Cost:** ~$0.30 at MiniMax-M2.7 (3 batches × 50 claims, 88 s wall)

**Result:**

| bucket | n | % of C8+C9 |
|---|---:|---:|
| **strict_noise** (W14.A can drop) | **14** | **9.5 %** |
| **valid_content** (W11 mis-classification, out of W14 scope) | 134 | 90.5 % |
| UNCLASSIFIED | 0 | 0 % |

### §0 Re-classification verdict — ⚠ critical scope finding

- **strict_noise = 14 claims = 1.27 pp of W11 baseline (1102 UV)**
- **Target (ceiling × 0.6) = 0.76 pp** — significantly smaller than spec implicit assumption that C8+C9 ≈ 15 % UV ceiling
- The 134 valid_content claims are W11 mis-classifications that belong in C1 (cross-method consensus, ~36 found by spot-check) / C3 (signal evidence) / C5 (intermediate biology) / C7 (namespace) buckets. **W14 must NOT touch these** — they should be re-bucketed in a separate W11-classifier-refinement effort (not in W14 scope).

**Implication for W14 sprint shape:**

- **Main course A (noise prompt + grammar subtype)** real impact ceiling is **1.27 pp**, not the ~15 % the spec implicitly suggested. Still worth doing for paper-grade audit hygiene + as foundation for future noise infrastructure.
- **Side dish B (iter-2 cap)** is now the higher-leverage piece: locks the W13.A surprise iter-2 deg −6.35 pp + ~33 % cost reduction. **Primary sprint value will come from B, not A.**
- Hard Gate target for UV drop **must be recalibrated to ≥ 0.76 pp** (not ≥ 3 pp / 5 pp from spec).

### Confirmation matrix (per W14 spec §0 lines 99-106)

| # | Item | Status |
|---|---|---|
| (a) | W14.A main = `concord_react_prompt.md` banned phrases (⚠ modify concord prompt) + `verifier/grammar.py` new noise infrastructure (⚠ modify if migrate to enum, else ✅ add as string convention) | Spec deviation: `DroppedReason` enum does not exist; W14.A will either CREATE it (✅ pure-add new enum) or use string convention "noise_pattern" (no schema change). Default plan = create enum. |
| (b) | W14.B side = `concord/agent/react_runner.py` `DEFAULT_MAX_FEEDBACK_ITERS = 2 → 1` (⚠ modify ConcordMet existing code) | Confirmed |
| (c) | Target recalibrated based on §0 re-classification | **0.76 pp UV drop** (= 14 strict_noise × 0.6 / 1102 total UV) — significantly smaller than spec ~3 pp implicit. **Needs user decision: continue per spec, or rescope W14 to B-only?** |
| (d) | iter-2 cap expected: cost −33 %, iter-2 deg ≤ 15.87 % (W13 baseline preserved) | Confirmed; rerun with `--max-feedback-iters 1` will trigger only 0-1 feedback iters per task |
| (e) | Do not touch `verifier/layers/` (B1-core remains ❌) | Confirmed |
| (f) | No paper writeup | Confirmed |

---

## 1 · W14 task plan (D1-D6,A + B 并行)

| Day | A 主菜 (noise prompt + grammar subtype) | B 副菜 (iter-2 cap) |
|---|---|---|
| **D1** | Onboarding (this doc) + §0 re-classification (done) | — |
| **D2** | RED A:`tests/test_grammar_noise_pattern.py` (≥ 5 case) + `tests/test_concord_react_prompt_banned.py` (≥ 3 case) | RED B:`tests/test_react_runner_iter_cap.py` (≥ 3 case) |
| **D3** | GREEN A:grammar.py noise infrastructure + prompt banned phrases (⚠ modify) | GREEN B:`DEFAULT_MAX_FEEDBACK_ITERS = 1` (⚠ modify ConcordMet code) |
| **D4** | Gate verify (B1 not regressed + W13 26 case not regressed) | same |
| **D5** | Path X 全 63 task 重跑 (`--max-feedback-iters 1`,~1.5 h + $7) | same run |
| **D6** | Close-out report + W15 ranked | — |

Commit count: ~6-8 (onboarding + reclass data + 2 RED + 2 GREEN + Path X data + close-out).

---

## 2 · Hard Gates (recalibrated)

| Gate | Target | Rationale |
|---|---|---|
| 1 — A UV drop ≥ ceiling × 0.6 | **≥ 0.76 pp** | Real ceiling = 14 strict_noise / 1102 UV = 1.27 pp |
| 2 — Pathway accuracy drop ≤ 3 pp | ≥ 82.7 % | regression guard |
| 3 — iter-2 deg ≤ W13.A 15.87 % | ≤ 15.87 % | B cap should preserve or further reduce |
| 4 — API cost ≤ $7 (B cap target) | < W13 $9.90 | B's primary measurable impact |
| 5 — B1 verifier-core 407 / 0 | no fail | no regression |
| 6 — Full repo 1357 / 14 (W13 baseline) + W14 cases | no NEW fail | aggregate floor |

---

## 3 · Open question for user

**OQ1 — Sprint scope decision (blocking before D2)**:

Spec assumed C8+C9 ≈ 15 % UV ceiling. Reality is C8+C9 contains 90.5 %
W11 mis-classifications (valid_content) and only 9.5 % true noise.
W14.A ceiling = 1.27 pp / target = 0.76 pp.

Three plausible paths:

| option | scope | expected outcome | est wall |
|---|---|---|---|
| **A — Continue per spec** | W14.A main + W14.B side, recalibrated target 0.76 pp | UV −0.76 to −1.27 pp + cost −33 % + iter-2 deg locked | 5 d |
| **B — Rescope W14 to B-only** | only iter-2 cap; A defer | UV ±0 + cost −33 % + iter-2 deg locked | 2 d |
| **C — Pivot main: refine W11 C9 → C1/C3/C5** | reclassify the 134 valid_content into existing buckets; A defer to W15 | UV ±0 (just classification) + better W15 scoping | 1 d |

**My recommendation: A (continue per spec)** — even at 0.76 pp ceiling,
the noise infrastructure is paper-grade audit hygiene (we can claim
"LLM produces 0 noise claims post W14") + the B side dish does the
heavy lifting. Cheap to do, low risk.

---

## 4 · Stop conditions

Per W14 spec §9; recalibrated Gate 1 = ≥ 0.76 pp (not ≥ 3 pp).

1. §0 re-classification done ✓ (this commit's data)
2. RED regression case (case 5 real_claim_not_noise) pre-impl fail → ping me
3. B1 verifier-core 407 / 0 regress → halt + revert
4. W13 26 case (W12 14 + W13 12) regress → halt + revert
5. commit body missing warning / justification / placeholder digits → halt
6. Path X wall > 3 h / cost > $10 → halt
7. UV drop < 0.76 pp (recalibrated) → ping me
8. iter-2 deg > 15.87 % → ping me (B cap should preserve or reduce)
9. Pathway accuracy drop > 3 pp → halt + revert

---

## 5 · Do-not list (per W14 spec §10)

- ❌ Touch `verifier/layers/` (main course is at prompt + grammar layer)
- ❌ Modify W12 `factual_sub6.py` or W13 `_ID_PATTERNS` already shipped
- ❌ Pre-do W15 C3 signal_evidence (separate sprint)
- ❌ Modify `max_react_turns` (W14.B only touches `max_feedback_iters`)
- ❌ Paper narrative / push origin / B1 D5/D6 data overwrite

---

## 6 · Pending decisions log (will be filled as user replies)

| # | Question | User decision | Notes |
|---|---|---|---|
| OQ1 | Continue per spec (A) / B-only (B) / Pivot to C9 refinement (C) | **—** | blocking D2 |
