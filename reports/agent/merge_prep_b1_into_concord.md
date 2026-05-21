# Merge Preparation Report — `feature/agent-phase-b1` ↔ `feature/investigation-concord`

**Generated:** 2026-05-20
**Investigation worktree HEAD:** `3ffe621` (W9 D6 framework health v2)
**B1 worktree HEAD:** `ed6243b` (B1 P0 followup debt #1)
**Merge-base:** `5bbedcf` (`chore(freeze): MetAgent-v1-0514`)
**Scope:** read-only inventory + conflict analysis + merge strategy.
No code changes were made to produce this report.

---

## 1. TL;DR — Executive Summary

| Question | Answer |
|---|---|
| File-level conflicts | **0** (zero overlapping files across both branches) |
| API/schema breakage on either side | **0** breaking changes detected |
| API/schema additions to absorb | **3** (B1 adds `TaskOutcome`, `DroppedClaim`, `OTHER` ClaimType — all backward-compatible) |
| Recommended merge order | **B1 → investigation-concord** (investigation imports from B1 paths; B1 doesn't import from concord/) |
| Estimated merge wall | **< 5 min** core merge; ~30 min full pytest verification |
| Post-merge optional alignments | **5** (see §7) — none are blockers |

**Bottom line**: the two branches were engineered with **strict
non-overlapping write zones** (B1 stayed in `verifier/` +
`evaluation/sub6/` + `tools/agent_tools/`; investigation-concord
stayed in `concord/` + `evaluation/concord/` + `tests/concord/`).
A vanilla `git merge feature/agent-phase-b1` into
`feature/investigation-concord` should complete with **zero merge
markers**. Logical (API-level) compatibility was preserved through
the W8 architectural rule "do not modify B1 paths; only import."

---

## 2. Branch divergence

```
                    5bbedcf MetAgent-v1-0514 (merge-base)
                   /                              \
   28 commits     /                                \  78 commits
                 v                                  v
       feature/agent-phase-b1               feature/investigation-concord
       (HEAD: ed6243b)                       (HEAD: 3ffe621)
       claim grammar v2                      ConcordMet LLM-agent
       + closed-loop feedback D4             5-PA reconciliation
       + D5/D6 paper-grade eval              + W8/W9 framework
```

### 2.1 Sprint focus

| Branch | Primary scope | Sprints covered |
|---|---|---|
| `feature/agent-phase-b1` | Sub-6B narrative verifier — claim grammar v2, closed-loop feedback (D1-D4), full-eval D5/D6 with paper-grade numbers, P0 fixes / followup-debt cleanup | B1 D1-D6 + P0 cycle |
| `feature/investigation-concord` | ConcordMet LLM-agent pipeline — 5-paradigm pathway-analysis dispatcher, ConcordReactRunner + closed-loop with B1 verifier, full sub6b-v3 framework verification, dispatcher D2 three-axis fix | W3-W9 |

### 2.2 Commit shape

```
B1:  28 commits  (8 feat / 5 fix / 3 test / 12 docs)
INV: 78 commits  (W3-W7 etl/spike + W8/W9 ConcordMet ReAct/verifier wire)
```

---

## 3. File-level inventory

### 3.1 Overlap test

```bash
$ comm -12 <(git diff --name-only 5bbedcf..b1) <(git diff --name-only 5bbedcf..investigation)
# (empty)
```

★ **Zero files modified by both branches.** This is a property of the
W8 architectural rule that landed on investigation-concord at W8 D1
("B1 paths import-only, no edits") and held through W9 D2c.

### 3.2 B1 write zone (`feature/agent-phase-b1`)

| Module | Files touched | Nature |
|---|---|---|
| `verifier/` | 9 (grammar.py + task_outcome.py NEW; agent.py + schemas.py + claim_extractor.py + claim_classifier.py + feedback_hints.py + metrics.py + prompts/classify_ambiguous.py MOD) | claim grammar v2; TaskOutcome enum; DroppedClaim; classifier 9→4 collapse; per-drop-reason feedback hints |
| `evaluation/sub6/` | 5 (`run_sub6a.py` + `run_sub6b.py` + `run_sub6b_react.py` + `run_sub6b_react_feedback.py` + `prompts.py`) | response_format=json_object wire; two-layer retry; UV in feedback gate |
| `scripts/eval_sub6/` | 7 (NEW: `aggregate_seed_summary.py`, `analyze_d4_efficacy.py`, `run_d5_v3_p0fix.py`, `step_r_per_layer.py`, `step_r_v3.py`; MOD: `aggregate_verifier.py`, `grade_with_verifier.py`) | D5/D6 aggregators + Step R driver-filtered correlation |
| `tests/` (root level) | 5 NEW (`test_classifier_collapse.py`, `test_d4_feedback_dispatcher.py`, `test_grammar_validate.py`, `test_prompt_banned_sync.py`, `test_runner_response_format.py`) | B1 D2-D4 unit suite (~31+ cases) |
| `prompts/agent/` | 2 MOD (`sub6b_react_prompt.md`, `sub6b_react_feedback_prompt.md`) | grammar v2 templating, banned-token list, per-drop-reason hint placeholders |
| `data/eval/sub6/` | 31 (paper-grade B1 D5/D6 v2/v3 + p0fix + A3 rerun N=3) | run artefacts, frozen JSON |
| `reports/agent/` | 14 (phase_b1_*) | D4 efficacy, D5 eval, D6 ablation epic, P0 isolation, Step R, leak-check |
| `docs/` | 1 (`claim_grammar_v2.md`) | grammar spec |
| `common/llm_client.py` | 1 MOD | `response_format` passthrough for json_object mode |

### 3.3 Investigation-concord write zone

| Module | Files touched | Nature |
|---|---|---|
| `concord/` | 45 (all new namespace) — agent/ + analyze/ + etl/ + figures/ + lookup/ + normalize/ + reconcile/ + schema/ + validate/ + wrappers/ | 5-paradigm PA wrappers (sspa / ramp / metaboanalystr / mummichog / fella), reconciliation pipeline, schema v0.3.1, ConcordReactRunner + dispatcher |
| `evaluation/concord/` | 6 NEW (path_w.py + path_x.py + path_y.py + path_z.py + smoke_d3.py + smoke_d4.py) | 4-path full-eval runner |
| `tests/concord/` | 32 (all new) | W3-W9 unit + integration coverage |
| `scripts/concord/` | 3 NEW (setup_w8_path_w.sh + w9_d3_round_trip_verify.py + w9_d5_path_x_full.py) | D5 batch driver |
| `data/concord/` | 165 (chebi.sqlite, metanetx.sqlite, pathway_members.sqlite, w8_smoke/, w8_llm_agent/, w9_d3_verify/, w9_llm_agent_full/, etc.) | ETL outputs + run artefacts |
| `prompts/concord/` | 1 NEW (`concord_react_prompt.md`) | ConcordMet ReAct system prompt (independent of B1's sub6b_react_*) |
| `reports/agent/` | 18 (concord_*) | W3-W9 reports including W8 D5 health v1 and W9 D6 health v2 |
| `docs/concord/` | 5 (paper narrative finalised + W3-W7 handoff) | W7 paper draft (sunk; not used after W8 LLM-agent pivot) |
| `conftest.py` + `.gitignore` | 2 small | test-collection guard + Path W symlink rule |

### 3.4 Disjoint write zones — visual

```
B1:   verifier/, evaluation/sub6/, scripts/eval_sub6/, tests/test_*.py,
      prompts/agent/, data/eval/sub6/, reports/agent/phase_b1_*,
      docs/claim_grammar_v2.md, common/llm_client.py
                                              ↕  (zero overlap)
INV:  concord/, evaluation/concord/, tests/concord/, scripts/concord/,
      prompts/concord/, data/concord/, reports/agent/concord_*,
      docs/concord/, conftest.py, .gitignore
```

---

## 4. API / schema integration points

Even though the file sets are disjoint, investigation-concord
**imports** from B1-side modules. Every B1 API touched by
investigation needs a compatibility check.

### 4.1 Imports from investigation-concord into B1 surface

| investigation-concord call site | B1 symbol consumed | B1 change post merge-base | Compat verdict |
|---|---|---|---|
| `concord/agent/verifier_adapter.py` → `verifier.agent.verify_sub6` | `verify_sub6(llm_output, source_report, *, trace_id, ramp_db_path, ramp_conn, driver_lookup)` | **signature unchanged**; body now produces additional `VerifiedIdentification.dropped_claims` + `task_outcome` fields | ✅ compatible (new fields ignored by my reader) |
| `concord/agent/verifier_adapter.py` → `schemas.sub6_report.SubsixSourceReport` | `task_id / task_type / domain / ground_truth_pathway / ground_truth_signal_compounds / ground_truth_noise_compounds / ramp_enrichment_result / differential_metabolites / differential_spectra / compound_lookup` | **schema unchanged** | ✅ |
| `concord/agent/react_runner.py` → `evaluation.sub6.run_sub6b_react_feedback.build_feedback_message` | `(*, contradicted, unsupported, original_narrative)` → B1 adds two new optional kwargs `unverifiable=None, dropped=None` | **call site unaffected**; the new kwargs default to None | ✅ + future enhancement opportunity (§7.2) |
| `concord/agent/react_runner.py` → `verifier.feedback_hints.annotate_claims` | `(claims, *, pass_id)` | **signature unchanged**; body adds drop-reason templates | ✅ |
| `concord/agent/react_runner.py` → `verifier.schemas.ClaimVerdict` enum | `ClaimVerdict.UNVERIFIABLE_V0 / SUPPORTED / UNSUPPORTED / CONTRADICTED / ERROR` | **enum unchanged**; B1 adds new `OTHER` ClaimType (not ClaimVerdict) | ✅ |
| `concord/agent/react_runner.py` → `_default_feedback_builder` reads `verdict.claims_v1[*].verdict` (.value or str fallback) | unchanged | unchanged | ✅ |
| `concord/agent/react_runner.py:verify_with_b1` → `verdict.claim_metrics.supported_claims / unsupported_claims / contradicted_claims / unverifiable_claims` | B1 adds `dropped_by_grammar` field; existing 4 fields unchanged | ✅ |
| `evaluation/concord/path_x.py:_per_task_signals` → `iteration.react_result.task_outcome` (string) | B1 adds verifier-side `TaskOutcome` enum but my runner produces its own string outcome | ✅ disjoint; possible W10 alignment (§7.1) |

### 4.2 New B1 symbols available to investigation post-merge

| Symbol | Source | Use case post-merge |
|---|---|---|
| `verifier.task_outcome.TaskOutcome` | NEW | Can replace local `ConcordTaskOutcome` enum in `verifier_adapter.py` (4 values match byte-for-byte) |
| `verifier.task_outcome.detect_task_outcome(verified, dropped, narrative)` | NEW | Could drive `ConcordReactResult.task_outcome` instead of the runner's hand-coded classification |
| `verifier.schemas.DroppedClaim` | NEW | LLM-agent could read verifier's per-claim drop reasons to surface to next iter's feedback prompt |
| `VerifiedIdentification.dropped_claims` (new field) | NEW | Diagnostic — count of claims rejected at extraction by grammar v2 |
| `VerifiedIdentification.task_outcome` (new field) | NEW | Verifier's view on task outcome; cross-check vs runner's |
| `ClaimMetrics.dropped_by_grammar` (new field) | NEW | Aggregate metric for grammar-v2 drop rate |
| `build_feedback_message(unverifiable=, dropped=)` (new kwargs) | EXTENDED | Richer feedback hint when D4 efficacy data shows current hint is too coarse |
| `verifier.claim_extractor.extract_claims_from_json` | NEW | Bypass LLM-based claim extraction when the source narrative IS valid grammar-v2 JSON (i.e. our case). **Significant LLM-cost saver post-merge** |

### 4.3 Imports from B1 into concord (NONE)

```bash
$ git show feature/agent-phase-b1 -- $(git ls-tree -r --name-only feature/agent-phase-b1 | grep -E '^(verifier|evaluation/sub6|tests/test_|scripts/eval_sub6|prompts/agent|common)') \
    | grep -E "^\+.*from concord|^\+.*import concord"
# (empty)
```

B1 makes zero imports from `concord/*`. The dependency direction is
**investigation-concord depends on B1**, not the reverse.

---

## 5. Conflict analysis

### 5.1 File-level conflicts

**None.** See §3.1.

### 5.2 Schema field name collisions

Both branches add fields to `verifier/schemas.py` (B1) and
`concord/schema/enrichment.py` (investigation). These are different
files. No collision.

Both branches add a `TaskOutcome` concept:
- B1: `verifier.task_outcome.TaskOutcome` (used by verifier internals)
- investigation: `concord.agent.verifier_adapter.ConcordTaskOutcome` (used by runner)

The two enums have identical 4 string values (`normal`,
`empty_honest_refusal`, `empty_system_failure`, `empty_unknown`).
Post-merge, the investigation-side enum can either:
- (a) stay as-is (independent type, no breakage)
- (b) become an alias for B1's enum (`ConcordTaskOutcome = TaskOutcome`)

Recommendation: **option (a) at merge time** (zero risk). Option (b)
is a clean-up that the post-merge team can pick up at leisure.

### 5.3 Test name collisions

```bash
$ comm -12 <(git ls-tree -r feature/agent-phase-b1 -- tests/ | awk '{print $4}' | sort) \
            <(git ls-tree -r feature/investigation-concord -- tests/ | awk '{print $4}' | sort)
# returns only common tests/ infrastructure files (conftest, etc.)
```

B1's tests are at `tests/test_*.py` (root); investigation-concord
tests are at `tests/concord/test_*.py`. **No name collision.**

### 5.4 Prompt file collisions

- B1: `prompts/agent/sub6b_react_prompt.md`, `prompts/agent/sub6b_react_feedback_prompt.md`
- INV: `prompts/concord/concord_react_prompt.md`

Different sub-trees. **No collision.**

### 5.5 Data directory collisions

- B1: `data/eval/sub6/b1_d5_*` + `data/eval/sub6/a3_rerun_*` + `data/eval/sub6/b1_d5_v3_p0fix/`
- INV: `data/concord/*` + `data/eval/sub6/v3/sub6b_opus/` **(SYMLINK to main worktree)**

★ **The Path W symlink** at `data/eval/sub6/v3/sub6b_opus` (created
by `scripts/concord/setup_w8_path_w.sh`) is gitignored via the
existing `.gitignore:27` rule `data/eval/sub6/v*/`. **The symlink is
not in git** — no collision with B1's `data/eval/sub6/b1_*` files
(B1 uses `data/eval/sub6/b1_*` paths which are different siblings
under `data/eval/sub6/`).

### 5.6 Behaviour-level risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| B1's `prompts/agent/sub6b_react_prompt.md` text drift confuses ConcordMet's prompt comparison test if any | LOW | concord uses its own prompt file, no cross-prompt tests in investigation |
| B1's `extract_claims_from_json` is auto-routed when the LLM emits grammar-v2 JSON; if investigation's runner pipeline triggers the JSON path, behavior changes (cheaper, faster, but slightly different claim set than text extraction) | LOW-MED | post-merge regression test on a single ConcordReactRunner smoke task |
| B1's `_failed(dropped_claims=)` is a new kwarg the call site in investigation never passes (we use verify_sub6 which now passes `dropped` internally) | NONE | private helper, unaffected |
| Pytest collection picks up both `tests/test_*.py` (B1) AND `tests/concord/test_*.py` (INV) — could surface env coupling (sspa pkg missing on either side) | KNOWN | already 17 pre-existing fails in INV's pytest baseline; B1 may have similar env-driven xfails. Run merged-tree pytest and compare counts |

---

## 6. Recommended merge strategy

### 6.1 Direction

**Merge `feature/agent-phase-b1` INTO `feature/investigation-concord`.**

Reasons:
1. Dependency flow: investigation imports from B1; B1 doesn't import
   from concord. The recipient should be the importer to keep all
   user-visible types resolved.
2. Investigation-concord HEAD `3ffe621` already references B1
   modules; merging B1 in adds the matching version of those modules
   on top of the import points.
3. Smaller "front" branch — B1 has 28 commits vs INV's 78. The
   merge commit reads cleaner if INV is the recipient.

### 6.2 Procedure (read-only — for the operator who will do the merge)

```bash
# in the investigation worktree:
cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5_investigation
git fetch  # ensure local ref of feature/agent-phase-b1 is current
git status # confirm clean tree (working tree currently clean per HEAD 3ffe621)

# perform the merge — expected: zero conflict markers
git merge --no-ff feature/agent-phase-b1 -m \
  "merge: feature/agent-phase-b1 → feature/investigation-concord
   B1 claim grammar v2 + D4-D6 closed-loop feedback + P0 fixes.
   Investigation-concord W8/W9 ConcordMet LLM-agent + W9 D2 three-axis
   dispatcher fix. Zero file overlap; one merge commit binds the two
   write zones. See reports/agent/merge_prep_b1_into_concord.md."

# post-merge verification — full pytest
PYTHONPATH=. python3 -m pytest -q --tb=line --ignore=tests/test_ui
# expected: > 1306 pass (W9 baseline) + B1 unit tests = ~1330+
# expected: 17 ± a few fail (pre-existing env issues, sspa/Docker/GNPS)
# expected: 0 NEW fail introduced by the merge

# investigation-side regression — verify W9 D2c hot-path
PYTHONPATH=. python3 -m pytest tests/concord/test_envelope_error_surfacing.py \
    tests/concord/test_d2b_mummichog.py \
    tests/concord/test_dispatcher_id_negotiation.py -q

# B1-side regression
PYTHONPATH=. python3 -m pytest tests/test_d4_feedback_dispatcher.py \
    tests/test_classifier_collapse.py \
    tests/test_grammar_validate.py -q
```

### 6.3 Conflict resolution playbook (for the unlikely case markers appear)

Per §3.1 + §5, no conflicts are expected. If `git merge` does report
a conflict, it almost certainly indicates one of:

| Symptom | Almost-certain cause | Resolution |
|---|---|---|
| Conflict on `verifier/agent.py` | Investigation accidentally edited a B1 file post-W9 D6 (would be a strict-TDD-rule violation) | Bisect investigation's W9+ commits; the offending commit needs revert |
| Conflict on `tests/conftest.py` | Both branches added a fixture | Manual merge — should be additive |
| Conflict on `.gitignore` | Both branches added a rule | Manual merge — additive |
| Conflict on `data/concord/chebi.sqlite` (binary) | Should not happen — investigation alone modified | Re-run `python -m concord.etl.chebi_etl --with-isa` post-merge |

---

## 7. Post-merge enhancement opportunities (optional)

These are non-blocking suggestions for the post-merge team. The
merged tree is fully functional without any of them.

### 7.1 Replace `ConcordTaskOutcome` with B1's `TaskOutcome`

`concord/agent/verifier_adapter.py:ConcordTaskOutcome` was defined
in W8 D4 because "B1 D4 TaskOutcome lives on feature/agent-phase-b1
and has not merged". After merge, B1's enum exists at
`verifier.task_outcome.TaskOutcome` with byte-identical 4 values.
A 1-line change replaces the local enum:

```python
# concord/agent/verifier_adapter.py
from verifier.task_outcome import TaskOutcome as ConcordTaskOutcome
```

Drives: type unification across the merged codebase. Optional, no
behaviour change.

### 7.2 Pass `unverifiable` + `dropped` to `build_feedback_message`

B1 D4 extended `build_feedback_message` to accept two new optional
kwargs (`unverifiable=None, dropped=None`). The current
investigation default builder passes only `contradicted` +
`unsupported`. Wiring the two new kwargs gives the LLM richer
revision context on iter ≥ 1.

```python
# concord/agent/react_runner.py:_resolve_default_feedback_builder
return build_feedback_message(
    contradicted=contradicted,
    unsupported=unsupported,
    unverifiable=unverifiable,   # NEW
    dropped=dropped,             # NEW
    original_narrative="",
)
```

Drives: W10 W10 Issue #2 ("quality metric penalises bridging") fix
overlap — richer hints may reduce iter-2 quality degradation rate
(currently 11.1% per W9 D5 §3).

### 7.3 Use `verifier.claim_extractor.extract_claims_from_json` for ConcordMet

B1 D4 added `extract_claims_from_json` for the case where the LLM
output IS valid grammar-v2 JSON. Investigation's ConcordMet system
prompt mandates grammar-v2 JSON output. Current path:
`verify_sub6(llm_output_string)` → LLM-based extractor → claims.
Optimised path post-merge: detect JSON → skip extractor LLM call →
save ~1 LLM call per task verify (≈ ~63 LLM calls saved per W9 D5
re-run ≈ ~5% cost reduction).

Drives: W10 Issue #6 ("cost ablation") partial credit.

### 7.4 Use `VerifiedIdentification.task_outcome` for cross-check

Both verifier and ConcordReactRunner now classify task outcome
(B1 adds `verifier.task_outcome.detect_task_outcome`; runner has
its own classifier). They should agree; post-merge a sanity check
can flag disagreement:

```python
if fb.final_verdict.verdict.task_outcome.value != fb.iterations[fb.final_iter_idx].react_result.task_outcome:
    logger.warning("task_outcome disagreement task=%s runner=%s verifier=%s", ...)
```

Drives: framework consistency audit. No behaviour change at first run.

### 7.5 Adopt B1 D5/D6 paper-grade aggregator for Path X

B1's `scripts/eval_sub6/aggregate_seed_summary.py` is the canonical
B1 D5 aggregator (paper-grade with CI95 and per-seed roll-up).
ConcordMet's W9 D5 `scripts/concord/w9_d5_path_x_full.py` uses a
local `evaluation.concord.path_x.aggregate_path_x()`. Post-merge,
running the B1 aggregator over Path X's per-seed jsonls would give
ConcordMet the same statistical rigour B1 has (CI95 + sign test).

Drives: W10 Issue #4 ("N_eff ≈ 13 bootstrap CI") via B1's existing
implementation.

---

## 8. Cross-branch eval-data inventory (post-merge tree)

After merge, the unified `data/eval/sub6/` will contain both branches'
run artefacts side-by-side:

| Path | Source branch | Purpose |
|---|---|---|
| `data/eval/sub6/v3/sub6b_opus/` (symlink, gitignored) | INV (W8 D1 setup) | Path W baseline (v3 Opus single-iter) |
| `data/eval/sub6/v2/sub6b_opus/` (already on main) | merge-base | v2 Opus baseline |
| `data/eval/sub6/b1_d5_v3_p0fix/` | B1 | B1 D5 v3 P0-fixed paper run (3 seeds, N=63) |
| `data/eval/sub6/b1_d5_v2_full_feedback_lit/` | B1 | B1 D5 v2 feedback-with-lit final |
| `data/eval/sub6/b1_d5_v2_rerun_2026_05_18/` | B1 | B1 D5 v2 rerun for A3 comparison |
| `data/eval/sub6/a3_rerun_2026_05_19/` | B1 | A3 same-LLM controlled rerun N=3 |
| `data/concord/w8_smoke/` | INV (W8) | D3/D4 closed-loop smoke trace (2 task: steroid + WP167 lipid) |
| `data/concord/w8_llm_agent/` | INV (W8 D5) | Path W metrics + Path X 5-task sample + Path Y 63 + Path Z 63 |
| `data/concord/w9_llm_agent_full/` | INV (W9 D5) | Path X full 63-task on D2-fixed dispatcher (3 iter trace each) |
| `data/concord/w9_d3_verify/` | INV (W9 D3) | 5-task × 5-wrapper round-trip table |

★ **Both branches' D5/D6 numbers are addressable side-by-side
post-merge**, enabling a cross-pipeline comparison report (B1
single-LLM-agent vs ConcordMet multi-paradigm-LLM-agent on the
same sub6b-v3 benchmark) without re-running anything.

---

## 9. Headline numbers cross-reference (for the merge announcement)

Both branches converge to **roughly the same headline**: closed-loop
LLM-agent gives a large supported-precision lift on sub6b-v3 vs the
single-iter Opus baseline. Different pipelines being measured, but
the direction agrees.

| Pipeline | Branch | Supported % | Δ vs Opus baseline 17.40 | Note |
|---|---|---:|---:|---|
| Opus single-iter (Path W) | shared baseline | 17.40 | — | from v3 verdict file, both branches read this |
| B1 D5 v3 P0fix (per-task supported_mean across 3 seeds) | B1 | **~96** ★ | n/a (different metric) | per-task supported claims fraction averaged across tasks/seeds — different denominator from Path X / Path W |
| ConcordMet W9 D5 (final iter post-rollback supported %, aggregate over claims) | INV | **26.53** | **+9.13 pp** | aggregate over all claims across 63 tasks; same metric as Path W |

★ The two "supported" numbers are measured on DIFFERENT metrics:
- B1's 96% is a per-task supported-RATIO mean (each task contributes
  its own supported/total ratio; the mean is taken over tasks/seeds).
- ConcordMet's 26.53% is a global supported COUNT across all claims
  in all 63 tasks, divided by global claim count.

Post-merge, **both metrics can be computed on either pipeline** by
applying the other side's aggregator. Recommend this as a W10
follow-up to publish apples-to-apples numbers.

---

## 10. Merge readiness checklist

- [x] File overlap inventory (§3.1): 0 files
- [x] API signature compatibility (§4.1): all imports still resolve
- [x] Schema field-addition compatibility (§4.2): all new fields default-valued
- [x] Test layout disjointness (§5.3): no test-name collisions
- [x] Prompt file disjointness (§5.4): no collisions
- [x] Data directory inspection (§5.5): symlink correctly gitignored
- [x] Cross-branch import audit (§4.3): B1 makes 0 imports from concord
- [x] Cross-branch dependency direction confirmed: INV → B1, not reverse
- [ ] Merge command run (out of scope for this report)
- [ ] Post-merge pytest run (out of scope for this report)
- [ ] Post-merge D1-D6 smoke verification (out of scope for this report)

---

## 11. References

| Document | Purpose |
|---|---|
| `reports/agent/concord_sprint_w8_status.md` | W8 D1-D5 full timeline (investigation side) |
| `reports/agent/concord_w8_framework_health.md` | W8 D5 health report v1 (investigation) |
| `reports/agent/concord_sprint_w9_status.md` | W9 onboarding + confirmation |
| `reports/agent/concord_sprint_w9_d3_verify.md` | W9 D3 5×5 round-trip table |
| `reports/agent/concord_sprint_w9_framework_health.md` | W9 D6 health report v2 (investigation) |
| `reports/agent/phase_b1_d5_v3_p0fix.md` | B1 D5 v3 P0 fix final paper run |
| `reports/agent/phase_b1_d6_ablation_epic.md` | B1 D6 ablation epic narrative |
| `reports/agent/phase_b1_followup_debt.md` | B1 P0 followup debt list |
| `docs/claim_grammar_v2.md` | B1 claim grammar v2 spec |
| `prompts/track_CONCORD_sprint_W8_LLM_agent_pivot.md` | W8 sprint plan (main worktree) |
| `prompts/track_CONCORD_sprint_W9_framework_fix.md` | W9 sprint plan (main worktree) |
| `prompts/track_AGENT_phase_B1_D4.md` | B1 D4 sprint plan (main worktree) |
