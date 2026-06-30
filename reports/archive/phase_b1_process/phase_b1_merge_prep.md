# Phase B1 — pre-merge handoff (feature/agent-phase-b1 → feature/investigation-concord)

**Date:** 2026-05-20
**Source branch:** `feature/agent-phase-b1` (HEAD = `ed6243b`)
**Target branch:** `feature/investigation-concord` (HEAD = `3ffe621`)
**Merge base:** `5bbedcf` (tag `MetAgent-v1-0514`, 2026-05-14)
**Scope:** report only — no code changes in this artefact. Quantifies what each branch did since divergence, predicts conflict surface, and lists the follow-ups the merge unlocks.

---

## 1 · Executive summary

| | feature/agent-phase-b1 | feature/investigation-concord |
|---|---|---|
| Commits since merge-base | 28 (16 pre-session + 12 this session) | 30 (W3 → W9 sprints) |
| Files changed (vs merge-base) | 75 | 277 |
| Insertions | ~16 k (+15.8 k this session) | ~150 k |
| Touch surface | `verifier/`, `evaluation/sub6/`, `scripts/eval_sub6/`, `tests/`, `reports/agent/`, `data/eval/sub6/`, `docs/claim_grammar_v2.md` | new `concord/` top-level + `scripts/concord/`, `evaluation/concord/`, `tests/concord/`, `data/concord/`, `data/audit/`, `reports/concord/`, `reports/audit/`, `docs/concord/`, `conftest.py`, `.gitignore` |
| Code-file overlap with the other branch | **0** | **0** |
| Reports overlap | **0** | **0** |

**The two branches operate in fully disjoint directories.** No file is modified by both branches (`comm -12` of changed-file lists returns empty). The only file both branches even touch is `.gitignore` — and `feature/agent-phase-b1` made **zero changes** to it post-merge-base, so the investigation-branch additions to `.gitignore` apply cleanly. The merge is expected to be a near-fast-forward — most files just appear from one side, no `<<<<<<<` markers anywhere.

---

## 2 · feature/agent-phase-b1 — what landed since merge-base

### 2.1 Pre-session (commits `5bbedcf..808a42e`)

| Commit | Subject | Surface |
|---|---|---|
| `59ba540` | feat(llm_client): add response_format passthrough for json_object mode | `common/llm_client.py` |
| `a0d7feb` | feat(verifier): add Phase B1 claim grammar v2 schema and design doc | `verifier/grammar.py`, `docs/claim_grammar_v2.md` |
| `5a915c0` | feat(prompts): Phase B1 D1 — narrative prompts emit grammar-v2 JSON | `evaluation/sub6/prompts.py` |
| `90774d4` | feat(runner): wire response_format=json_object for sub6 runners (B1 D2) | `evaluation/sub6/run_sub6{a,b,b_react,b_react_feedback}.py` |
| `2354011` | feat(verifier): grammar-based extractor + dropped_by_grammar metric (B1 D2) | `verifier/claim_extractor.py`, `verifier/schemas.py` |
| `f9fe9a5` | test(verifier): grammar.validate unit tests + runner wire-up tests (B1 D2) | `tests/test_grammar_validate.py`, `tests/test_runner_response_format.py` |
| `9f5c9ae` | fix(grammar): context-aware skip for tool-roundtrip regex when token grounded in structured field (B1 D2 hotfix) | `verifier/grammar.py` |
| `3cdca61` | fix(prompts): make claim_text explicitly required on every claim entry (B1 D2 followup) | `evaluation/sub6/prompts.py` |
| `01a858b` | feat(classifier): collapse 9-class v1 → 4-class grammar v2 routing (B1 D3) | `verifier/claim_classifier.py`, `tests/test_classifier_collapse.py` |
| `717fe22` | feat(verifier): TaskOutcome enum + dispatcher v2-legacy deprecation (B1 D4 C1+C2) | `verifier/schemas.py`, `verifier/task_outcome.py`, `verifier/agent.py` |
| `39c4272` | feat(feedback): per-drop-reason hint templates + UNV removed from neutral set (B1 D4 C3) | `verifier/feedback_hints.py` |
| `7127023` | feat(runner): two-layer retry (inner finalise + outer feedback) + task-level timeout (B1 D4 C4) | `evaluation/sub6/run_sub6b_react_feedback.py` |
| `f42aacb` | test(verifier): D4 unit suite — 31 cases (B1 D4 C5) | `tests/test_d4_feedback_dispatcher.py` |
| `0ec15c4` | fix(runner): wire inner retry into feedback runner _react_loop (B1 D5 hotfix) | `evaluation/sub6/run_sub6b_react_feedback.py` |
| `8924da6` | feat(reports): D5 v2 final + D6 step analyses (B1 paper-grade) | `reports/agent/phase_b1_d5_eval.md` + step Q/R/Z reports |
| `808a42e` | docs(reports): D6 ablation epic narrative + followup debt | `reports/agent/phase_b1_d6_ablation_epic.md`, `reports/agent/phase_b1_followup_debt.md` |

### 2.2 This session (12 commits `808a42e..ed6243b`)

Chronological:

| Commit | Subject | What it does | Why |
|---|---|---|---|
| `0ba10f7` | **feat(aggregator): canonical seed_summary aggregator (B1 P0 A1.6)** | New `scripts/eval_sub6/aggregate_seed_summary.py` (~470 LOC) with audit + write modes; re-emits seed_summary + d5_aggregate JSONs from per-task result.json | The original aggregator was a lost ad-hoc script; audit (commit body) revealed 3 silent bugs |
| `a1fbf2f` | docs(reports): D4 efficacy analysis on D5 v2 corrected data (B1 A1.7) | New `scripts/eval_sub6/analyze_d4_efficacy.py` + report | Shows D4 feedback iter actually improved supported +21.92 pp on 144 fired tasks; the "D4 dormant" framing was a pure aggregator artefact |
| `02e7268` | docs(reports): retract D5 §4 D4-dormant claim, link efficacy analysis | edits `phase_b1_d5_eval.md` § 4 with retraction banner | preserve traceability of the original claim |
| `2a2eeb9` | **fix(runner): include UV in feedback quality gate (B1 P0 silent bug)** | `evaluation/sub6/run_sub6b_react_feedback.py:_quality_score` now sums `contradicted + unsupported + unverifiable_v0` (was `c + u` only) | D4 removed UV from `_NEUTRAL_VERDICTS` but the quality function never followed suit |
| `fdc3250` | docs(reports): D5 v3 P0 fix N=3 final + retraction of D5 §4 "B1 矫枉过正" claim (B1 A path complete) | `scripts/eval_sub6/run_d5_v3_p0fix.py` + report; runs 3 seeds × 63 tasks on the P0-fixed code | establish the v3 baseline |
| `eb691dd` | docs(reports): leak check halts P0-fix attribution claim (B1 verification §3) | `reports/agent/phase_b1_leak_check.md` | quantitative attribution found that the v2→v3 +30 pp jump originates at iter 0 (before any feedback fires), implicating MiniMax model drift between 2026-05-15 and 2026-05-18, NOT the P0 fix |
| `b050d04` | docs(reports): P0 fix isolation + A3 same-LLM rerun retract +30pp attribution | v2 worktree at `0ec15c4` + A3 worktree at `MetAgent-v1-0514` rerun on today's LLM → `reports/agent/phase_b1_p0_isolation.md` | P0 fix isolated marginal on top-1 = **0.00 pp** |
| `830d86b` | docs(reports): Step R driver-filtered correlation on v3 N=3 (B1 red line #4 final) | `scripts/eval_sub6/step_r_v3.py` + report | red line #4 FAIL on v3 (+3.50 pp), same as v2 (+5.00 pp) |
| `acbeb66` | docs(reports): A3 rerun N=3 same-LLM (B1 vs A3 controlled comparison final) | A3 seeds 1+2 on today's LLM → mean 66.67 ± 4.75 % top-1 | corrects the single-seed snapshot which used the worst A3 seed |
| `b524f6b` | docs(reports): D5 v3 §9 final red-line status (post-A3 N=3 + Step R) | appends § 9 to `phase_b1_d5_v3_p0fix.md` | 5/6 red lines green; #4 durable FAIL |
| `9e212fd` | docs(reports): per-layer supported breakdown + Step R extension on 6a/6c (B1 Stage C) | `scripts/eval_sub6/step_r_per_layer.py` + report | per-layer: 6c 99.9 % / Δ −0.07, 6a 96.6 % / Δ +17.97, 6b 72.3 % / Δ +3.50 |
| `ed6243b` | **fix(verifier): grammar field passthrough to VerifiedClaim (B1 P0 followup debt #1)** | `verifier/schemas.py:704` adds `grammar` field; `verifier/agent.py:372` new helper `_stamp_grammar_from_classified`; `tests/test_d4_feedback_dispatcher.py:558` regression test | closes followup_debt P0 #1 — `VerifiedClaim.grammar` was always `None` because the field didn't exist on the model |

### 2.3 Code files touched this session

```
M  evaluation/sub6/run_sub6b_react_feedback.py    (P0 _quality_score fix)
M  tests/test_d4_feedback_dispatcher.py            (regression tests for P0 + grammar passthrough)
M  verifier/agent.py                               (_stamp_grammar_from_classified helper + 2 call sites)
M  verifier/schemas.py                             (VerifiedClaim.grammar field)
A  scripts/eval_sub6/aggregate_seed_summary.py    (canonical aggregator, ~470 LOC)
A  scripts/eval_sub6/analyze_d4_efficacy.py       (per-task N0→final delta)
A  scripts/eval_sub6/run_d5_v3_p0fix.py           (N=3 wrapper around the runner)
A  scripts/eval_sub6/step_r_v3.py                 (driver-filtered correlation reanalysis)
A  scripts/eval_sub6/step_r_per_layer.py          (per-layer extension)
```

Plus 8 new `reports/agent/phase_b1_*.md` + 1 modified (`phase_b1_d5_eval.md`).

Plus 31 small data JSONs under `data/eval/sub6/{b1_d5_v2_full_feedback_lit,b1_d5_v2_rerun_2026_05_18,b1_d5_v3_p0fix,a3_rerun_2026_05_19}/` (seed_summary, d5_aggregate, per_layer, step_r, efficacy, audit_raw, top1_n3 — all aggregator outputs, no raw task results committed because they are gitignored / too large).

### 2.4 Headline numerical findings

| metric | v3 P0 fix N=3 (2026-05-18, MiniMax M2.7) | A3 N=3 same-LLM (2026-05-19) | Δ |
|---|---:|---:|---:|
| top-1 method A (narrative-first) | 69.31 ± 8.10 % | 66.67 ± 4.75 % | +2.64 pp (CI overlap → not significant) |
| top-1 method C (hybrid extractor) | 83.60 ± 7.48 % | 66.67 ± 4.75 % | **+16.93 pp** (CI disjoint → significant) |
| supported % | 96.10 ± 1.21 % | n/a (different verifier path) | — |
| UV % | 2.80 ± 0.55 % | n/a | — |

**P0 fix marginal on top-1 = 0.00 pp** (v2 rerun without P0 fix on today's LLM also reaches 83.60 ± 3.74 % method C). Net B1 attributable gain over A3: **prompt rewrite alone ≈ +2.64 pp (not significant); + structured-claims extractor lift ≈ +14.29 pp; total +16.93 pp**.

5/6 red lines GREEN; red line #4 (driver-filtered correlation Δ ≥ +18 pp) durable FAIL at +3.50 pp — informative for paper Discussion (tautology), not a B1-claims blocker.

---

## 3 · feature/investigation-concord — what landed since merge-base

(Summary; the canonical write-ups are `reports/agent/concord_session_handoff_report.md` and `reports/agent/concord_sprint_w9_framework_health.md` on that branch.)

### 3.1 New top-level: `concord/` (~ 7 k LOC core, 148+ tests as of W7; expanded W8-W9)

- `concord/schema/{enrichment,peak}.py` — v0.3.1 `EnrichmentResult` + `PathwayHit` + `CompoundRef` + namespace whitelists
- `concord/etl/{chebi,metanetx,cooke,pathway_members}_etl.py` — sqlite ETLs for ChEBI rel251, MetaNetX, Cooke 2025 SAMBA Tier-A, pathway-members
- `concord/lookup/chebi.py` — thread-safe `ChebiLookup`
- `concord/reconcile/{id_resolve,inchikey,charge_state}.py` — cross-source ID + charge-state reconciliation
- `concord/validate/metanetx_validator.py`
- `concord/wrappers/{sspa,mummichog,ramp,metaboanalystr,fella}_wrapper.py` — 5 PA tool wrappers
- `concord/wrappers/_docker_r_session.py` — persistent R docker session manager
- `concord/normalize/{sspa,mummichog,ramp,metaboanalystr,fella}_norm.py` — wrapper-output → v0.3.1 schema adapters
- `concord/analyze/{pathway_match,paradigm_consensus,gate2_variants}.py` — consensus metric V0-V3
- `concord/figures/fig3_{preliminary,v2_refined}.py` + `figures/_reconcile_cross_source.py`
- `concord/agent/{react_runner,system_prompts,tool_dispatcher,tool_handlers,verifier_adapter}.py` — W8/W9: LLM ReAct runner driving the 9-function-tool dispatcher

### 3.2 Tests + scripts + data

- `tests/concord/test_*.py` — 148+ unit tests; W9 added 5 wrapper shape contract tests + per-wrapper D2b RED/GREEN pairs + envelope-error surfacing
- `scripts/concord/{setup_w8_path_w.sh, w9_d3_round_trip_verify.py, w9_d5_path_x_full.py}`
- `evaluation/concord/{path_w,path_x,path_y,path_z}.py` + smoke runners
- `data/concord/`, `data/audit/`, `data/investigation/` artefact roots (large sqlites are gitignored; small CSV/JSON committed)

### 3.3 W8-W9 LLM-agent integration

W8 wired ConcordMet's 5 PA wrappers into an LLM-function-tool dispatcher (9 tools total); W9 fixed 3-axis dispatcher bugs (id-type negotiation, output shape normalisation, envelope error escalation) and ran a full 63-task LLM-agent benchmark (Path X). W9 framework-health report's headline: pipeline is now valid on all 63 tasks (0 crash, 0 LLM error, 0 verifier crash), cost ≈ $22.4 — slightly over $20 ceiling but flagged not halted.

### 3.4 Imports from soon-to-be-merged feature/agent-phase-b1

`concord/agent/` already imports 4 symbols that live on (and were touched by) `feature/agent-phase-b1`:

| concord file | symbol imported | B1 file (post-merge) | B1 status |
|---|---|---|---|
| `system_prompts.py:20` | `render_metabolite_block` | `evaluation/sub6/prompts.py:110` | exists ✓ (rewritten in B1 D1; behaviour shift is grammar-v2 prompts, not API shift — still takes `list[dict]`, still returns `str`) |
| `react_runner.py:831` | `build_feedback_message` | `evaluation/sub6/run_sub6b_react_feedback.py:223` | exists ✓ (signature: `(contradicted, unsupported, original_narrative, unverifiable=None, dropped=None)`; D4 added 2 new kwargs, defaults preserve A2 callers) |
| `react_runner.py:832` | `annotate_claims` | `verifier/feedback_hints.py:470` | exists ✓ |
| `react_runner.py:833` | `ClaimVerdict` | `verifier/schemas.py:170` | exists ✓ |

All 4 imports resolve cleanly post-merge.

### 3.5 Anticipated-merge note inside concord

`concord/agent/verifier_adapter.py:18` explicitly states:

> *"`verifier.schemas.TaskOutcome` is **not yet merged into the `feature/investigation-concord` branch** (B1 D4 lives on `feature/agent-phase-b1`). Rather than wait, we own a `ConcordTaskOutcome` enum here with the same 4 string values; once B1 D4 lands, the enum can be re-exported or aliased without touching callers."*

The two enums have identical values (`NORMAL` / `EMPTY_HONEST_REFUSAL` / `EMPTY_SYSTEM_FAILURE` / `EMPTY_UNKNOWN`). Post-merge, `ConcordTaskOutcome` can be aliased to `verifier.schemas.TaskOutcome` in a single follow-up commit. **Not required for the merge itself.**

---

## 4 · Conflict surface analysis

### 4.1 File-level conflicts (predicted)

| file | a3-phase-b1 changes vs MB | investigation-concord changes vs MB | merge behaviour |
|---|---|---|---|
| `.gitignore` | none | adds 17 lines for investigation data + concord sqlites | clean — investigation-side strictly additive |
| every other file | disjoint sets | disjoint sets | clean — no overlap |

### 4.2 Semantic conflicts (predicted)

| risk | analysis |
|---|---|
| Import-resolution drift between `concord/agent/*` and B1's `evaluation/sub6/prompts.py` / `verifier/feedback_hints.py` | Verified §3.4: all 4 imports resolve. `render_metabolite_block` and `build_feedback_message` were modified by B1 D1 / D4 but kept signature-compatible (B1 added optional kwargs with defaults). |
| `ConcordTaskOutcome` vs `verifier.schemas.TaskOutcome` enum collision | No collision — they live in different modules. Post-merge cleanup is optional alias, not required. |
| Schema-additive change to `VerifiedClaim.grammar` (Stage D, commit `ed6243b`) | Field defaults to `None`. Concord's `verifier_adapter.py` does not read `VerifiedClaim.grammar` (greps clean), so the new field is invisible to concord. Safe. |
| New helper `_stamp_grammar_from_classified` (commit `ed6243b`) | Module-private (`_` prefix). Not imported anywhere outside `verifier/agent.py`. No external callers. |
| Renamed/removed functions | None on B1 side this session — all changes are additive or local-fix. |

### 4.3 Test-suite interaction post-merge

- B1 added: `tests/test_grammar_validate.py`, `tests/test_runner_response_format.py`, `tests/test_classifier_collapse.py`, `tests/test_d4_feedback_dispatcher.py`, `tests/test_prompt_banned_sync.py` (all in `tests/` flat).
- Investigation added: `conftest.py` (puts repo root on `sys.path` so `import concord` works) + `tests/concord/test_*.py` (≥ 148 tests, namespaced under `tests/concord/`).
- No file collision. B1's test files do not need `concord` on path; concord's `conftest.py` is additive at root.
- B1 test sweep on its branch (excluding pre-existing GNPS/sub6 mock-signature failures): **1065 passed, 5 failed, 9 skipped**. The 5 failures predate B1's session and are unrelated to anything concord touches.
- Concord-side test count per W9 framework health: ≥ 148 + W8/W9 additions. Concord's tests don't import from `verifier/` modules that B1 modified beyond what §3.4 covers, so a combined sweep should still pass on both halves.

### 4.4 Data / artefact paths

| dir | branch | size | merge impact |
|---|---|---|---|
| `data/eval/sub6/b1_d5_*/` | B1 only | ~120 MB raw (gitignored where appropriate) + ~700 kB committed JSONs | additive |
| `data/eval/sub6/a3_rerun_2026_05_19/` | B1 only | ~30 MB raw + small JSONs | additive |
| `data/concord/`, `data/audit/`, `data/investigation/` | investigation only | ~32 MB committed + ~620 MB gitignored sqlites | additive |
| `reports/agent/phase_b1_*.md` | B1 only | 12 files | additive |
| `reports/agent/concord_*.md`, `reports/audit/*.md` | investigation only | 14+ files | additive |
| `scripts/eval_sub6/` | both ADD files but no shared filename | — | additive |

---

## 5 · Recommended merge procedure

1. **From `feature/investigation-concord` worktree**, run:
   ```
   git fetch
   git merge --no-ff feature/agent-phase-b1
   ```
   Expected: clean fast-forward-ish merge, no conflicts. If `.gitignore` produces a merge marker (unlikely — B1 made no changes), accept investigation-side (since B1's .gitignore == merge-base .gitignore).

2. **Sanity-check the import boundary**:
   ```
   python -c "from concord.agent.verifier_adapter import ConcordTaskOutcome; from verifier.schemas import TaskOutcome; assert {o.value for o in ConcordTaskOutcome} == {o.value for o in TaskOutcome}; print('enum parity ok')"
   python -c "from concord.agent.react_runner import ConcordReactRunner; print('concord react_runner imports clean')"
   ```

3. **Run full test sweep** on the merged tree:
   ```
   PYTHONPATH=. pytest tests/ -q --ignore=tests/integration --ignore=tests/test_ui
   ```
   Expected: B1's prior 1065 passed + concord's full suite. The 5 pre-existing B1 failures (mock signature + GNPS env) carry through unchanged — they are not caused by either branch's session work.

4. **Optional same-commit follow-ups** (if you want a clean post-merge commit):
   - In `concord/agent/verifier_adapter.py`: replace `ConcordTaskOutcome` with `from verifier.schemas import TaskOutcome as ConcordTaskOutcome` (1-line aliasing; comment can be deleted since B1 D4 has now merged).
   - Update `reports/agent/phase_b1_followup_debt.md` to mark P0 #1 (grammar passthrough) as resolved by Stage D commit `ed6243b`.
   - Decide whether to remove the two B1-detached worktrees `/tmp/b1_v2_rerun` and `/tmp/a3_rerun` (`git worktree remove /tmp/b1_v2_rerun /tmp/a3_rerun`) — these were created during the P0 isolation experiments and are no longer needed.

5. **Do not push to origin** until either (a) a user-level decision is made, or (b) the reviewer signs off on the combined surface.

---

## 6 · What the merge unlocks downstream

| capability | depends on | notes |
|---|---|---|
| Concord's `verifier_adapter.py` can drop its `ConcordTaskOutcome` shim and alias `TaskOutcome` directly | B1 D4 `verifier/schemas.py:TaskOutcome` + `verifier/task_outcome.py` | enum values already identical; aliasing is cosmetic |
| Concord LLM-agent results can be aggregated through B1's canonical aggregator | `scripts/eval_sub6/aggregate_seed_summary.py` | the aggregator reads per-task `result.json` files with the runner's `IterationRecord` schema. Concord's `ConcordFeedbackResult` has a different shape, so this is a tooling lead, not a drop-in. |
| Per-grammar metric breakdowns are now possible on any B1- or concord-derived NORMAL run | Stage D commit `ed6243b` (`VerifiedClaim.grammar` field populated) | any new run after this merge will have `VerifiedClaim.grammar` set; existing JSONs are unaffected (no migration needed because the field is optional). |
| Step R-style driver-filtered + per-layer analysis is now reusable on concord outputs | `scripts/eval_sub6/step_r_per_layer.py` | the script reads result.json directly; concord-side equivalent would need a thin adapter or could call `verify_sub6` on the saved final_narrative the same way step_r_v3 does. |
| The "B1 vs A3 same-LLM, +16.93 pp hybrid extractor" headline is paper-quotable | `phase_b1_p0_isolation.md` + `phase_b1_step_r_per_layer.md` | both reports flag the LLM-version confound prominently; any paper draft should cite the date + model-version snapshot used. |

---

## 7 · Cost & wall (B1 session this run)

- **Total session wall:** ~12 h (mostly dominated by 3 × 63 × N=3 sequential runs at K=10 + 2 × Step R reanalyses)
- **MiniMax API cost:** ~ $25-30 estimated
  - v3 P0 fix N=3: ~$7
  - v2 rerun N=3 (without P0 fix): ~$7
  - A3 rerun N=3: ~$11
  - Step R + per-layer + leak-check reanalyses: $0 (Layer D mocked, RaMP only)
- **Rate-limit events:** 1 (during K=15 parallel; resolved via sequential rerun chain)

---

## 8 · Open items not addressed by this merge

These are not blocking the merge; included for handoff completeness.

1. **`reports/agent/phase_b1_followup_debt.md`** still lists P0 #1 (grammar passthrough) as open. Stage D commit `ed6243b` closes it. Suggest updating the entry post-merge.
2. **Test mock signature drift** (`tests/eval_sub6/test_prompts.py`, `tests/eval_sub6/test_run_sub6{a,b}.py`) — 4 tests fail because mocks don't accept B1 D1's `response_format` kwarg. Pre-existing on the B1 branch since D1 (May 14). Concord-side conftest does not fix them. Suggest a separate cleanup commit on the merged branch.
3. **A3 per-layer breakdown** was attempted and aborted (verify_sub6 hangs on prose narratives). If a future paper section wants A3-side per-layer numbers, the analysis script (`scripts/eval_sub6/step_r_per_layer.py`) would need a prose-narrative path — current implementation assumes v2-grammar JSON output.
4. **Red line #4** (driver-filtered Δ ≥ +18 pp): durable FAIL at +3.50 pp on v3 N=3. Captured as Discussion material in `phase_b1_step_r_v3.md` + `phase_b1_step_r_per_layer.md`.
5. **The two detached worktrees** `/tmp/b1_v2_rerun` and `/tmp/a3_rerun` should be removed after the merge if not needed for re-runs. Use `git worktree remove`.

---

## 9 · Companion artefacts

For the merger to load context quickly:

- `reports/agent/phase_b1_d5_v3_p0fix.md` — main v3 N=3 report (with §1 retraction banner pointing to §6 below and §9 final red-line status)
- `reports/agent/phase_b1_leak_check.md` — quantitative attribution finding that triggered Option A/D verification
- `reports/agent/phase_b1_p0_isolation.md` — N=3 same-LLM B1-vs-A3 comparison, current paper-grade
- `reports/agent/phase_b1_step_r_v3.md` — red-line #4 final on v3
- `reports/agent/phase_b1_step_r_per_layer.md` — per-layer breakdown (Stage C)
- `reports/agent/phase_b1_aggregator_audit.md` — original audit that found the 3 silent bugs
- `reports/agent/phase_b1_d4_efficacy.md` — D4 mechanism efficacy
- `reports/agent/phase_b1_d5_v3_efficacy_seed0.md` — single-seed efficacy detail

Investigation-side context (read in conjunction):

- `reports/agent/concord_session_handoff_report.md` (W3-W7)
- `reports/agent/concord_sprint_w9_framework_health.md` (W8-W9, framework-status, not paper-status)
