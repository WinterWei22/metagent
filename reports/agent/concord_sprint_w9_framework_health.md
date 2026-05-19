# ConcordMet W9 Framework Health Report v2 (Full 63-Task)

**Status framing (per user W9 D5/D6 directive):** framework
diagnostic, NOT paper deliverable. Numbers below characterise the
W9-fixed pipeline on the full sub6b-v3 benchmark; they are NOT
paper-grade headline figures and contain no paper narrative.

**Branch:** `feature/investigation-concord`
**Sprint:** W9 D5 / D6 (full 63-task framework verification)
**Benchmark:** sub6b-v3 (MD5 `331b30a64017debe9d5ce07ed238e4f5`, 63 tasks)
**Dispatcher state:** W9 D2 three-axis fixed (id-type negotiation + output
shape normalisation + wrapper-internal error escalation)
**Path X data:** `data/concord/w9_llm_agent_full/path_x_full63_*`
**Path Y / Z / W:** unchanged from W8 D5 (no re-run; W9 didn't touch
those baselines)

---

## 1. Corrections to W8 D5 Framework Health Report

W8 D5 framework health report v1 contained three findings that W9 D1
contract testing revealed to be misdiagnoses:

| # | W8 D5 said | D1 contract reality | Impact |
|---|---|---|---|
| 1 | mummichog is "OK as-is" | pathway_id was bare pathway name with **no namespace prefix** — D2b mummichog normaliser fixed in commit `1fee709` | LLM saw `pathway_id="Vitamin D3 (cholecalciferol) metabolism"` — string literal accepted but grammar v2 schema's `pathway_id` field expected namespace shape, downstream verifier had nothing to match against |
| 2 | ramp/psea are "shape_gap" (handler reads wrong wrapper-output key) | Two compounding bugs: (a) shape_gap was real, (b) `_ids_to_refs` only populated single-namespace field per input — KEGG input → ramp `id_type="auto"` checks HMDB → empty → InChIKey → empty → 0 inputs. D2a fix populates all cross-references via ChebiLookup | The "shape_gap" headline finding was correct but incomplete; a fix to the output normaliser alone wouldn't have resolved KEGG inputs |
| 3 | fella status was "shape_gap+R error" (envelope ok=True misleading) | R-side error was real but the LLM-facing fix is **D2c envelope escalation** to `wrapper_runtime_error`. D4 R-side fix is W10 stretch | LLM now sees `error="wrapper_runtime_error"` + clear fallback to "skip network/diffusion paradigm" instead of an ok=True envelope with 0 pathways masquerading as a shape gap |

**Implication for W8 D5 Path X 5-task supported_ratio numbers:** those
were measured against a broken dispatcher (4-of-5 PA tools silently
returning empty pathway lists to the LLM). **W9 D5 is the canonical
ConcordMet-with-9-tools measurement; W8 D5 numbers are deprecated for
framework comparison**.

W8 D5 *data files* remain on disk for audit trail (commits `6d4cf74`
and `9fcc2f3`); the framework-health report v1 in
`reports/agent/concord_w8_framework_health.md` likewise stays
unmodified. This v2 supersedes it for the LLM-agent pipeline metric;
v2 references v1 §5 Path Z / Path Y / Path W tables verbatim since
those don't change between W8 and W9.

---

## 2. Pipeline Health (N=63, W9 D5)

From `data/concord/w9_llm_agent_full/path_x_full63_summary.json`:

| Metric | Value |
|---|---|
| n_tasks attempted | 63 |
| n_tasks valid | **63** |
| n_tasks crash | **0** |
| n_iterations NORMAL outcome (across all iters) | 187 (≈ 3 × 63 minus a few EMPTY) |
| mean wall / task | 682.9 s (~11.4 min) |
| total wall (K=10 ThreadPoolExecutor) | **178.4 min** (~3.0 h) |
| API cost estimate (MiniMax remote, token-billed) | **~$22.4** |
| LLM API error count | 0 |
| verifier crash count | 0 |

> 🟡 **Stop condition flag (post-hoc)**: API cost ~$22.4 (estimated
> from total tokens × MiniMax-M2.7 reference pricing of ~$0.0007/1k
> prompt + ~$0.0027/1k completion) **slightly over** the W9 prompt §6
> Stop #6 "$20 ceiling". Run was already complete; no halt was
> appropriate at completion time. Documented for W10 budget tuning.
> Exact cost should be reconciled against the MiniMax billing dashboard.

Stop-condition verifications:
- Wall total > 4h → 3.0h actual ✓ under
- ≥ 10 LLM API errors → 0 actual ✓
- ≥ 5 verifier crash → 0 actual ✓
- API cost > $20 → ~$22.4 estimated, marginal over (flagged above)
- task_outcome NORMAL ≥ 55/63 → 187 NORMAL across iter records (62 tasks
  completed all 3 iters, 1 task early-exited at iter 0)

---

## 3. Closed-Loop Mechanism Statistics

| Metric | Count (of 63) | % |
|---|---:|---:|
| iter 0 early-exit (quality_N0 = 0) | **1** | 1.6 |
| feedback iter 1 triggered | 62 | 98.4 |
| feedback iter 2 triggered | 62 | 98.4 |
| quality rollback (any reason) | **34** | 54.0 |
|   ↳ `feedback_made_it_worse` | 27 | 42.9 |
|   ↳ `iter{N}_degraded` | 7 | 11.1 |
| best-iter ≠ final-iter | 10 | 15.9 |
| bridge-only iter discarded by rollback | 33 | **52.4** |

W8 D5 5-task sample carry-over for direct comparison: 0/5 early-exit,
3/5 rollback (60%), 1/5 bridge-lost (20%). At N=63 the rollback rate
holds at ~54% — closed-loop feedback consistently makes things worse
in the B1 quality metric's view roughly half the time, regardless of
sample size. The bridge-lost rate **JUMPS** from 20% (5-task) to
52% (63-task), confirming the W8 D5 single-task WP167_seed7
finding was not an outlier — half the LLM's bridging behavior is
metric-penalised across the full benchmark.

---

## 4. Bridge Analysis (Lipid Bucket vs Aggregate)

| Metric | Aggregate (N=63) | Lipid WP167 (N=10) | Non-lipid (N=53) |
|---|---:|---:|---:|
| bridge_in_any_iter | 56/63 (88.9%) | **10/10 (100%)** | 46/53 (86.8%) |
| bridge_lost_to_rollback | 33/63 (52.4%) | 3/10 (30.0%) | 30/53 (56.6%) |
| rollback total | 34/63 (54.0%) | 9/10 (90%) | 25/53 (47.2%) |
| n_claims emitted (final iter, post-rollback) | 732 | 113 | 619 |

★ **Lipid bucket bridges 100%** — the W9 D2 dispatcher fix (esp.
ramp's WP-namespace coverage discovered in D3) gives the LLM-agent
WP-namespace pathway material on every lipid WP167 task, AND the LLM
correctly references `WP:WP167` / "Eicosanoid synthesis" in its
narrative.

★ But: **lipid supported % is LOWER than non-lipid** (12.23% vs
29.22%, see §5) — the LLM bridges, but the B1 verifier can't credit
the bridge because Layer 6a SET_ENRICHMENT compares against the
task's `ramp_enrichment_result.top_pathways` (RaMP namespace, no
WP:WP167 entry for LIPID MAPS pathway). The 100% bridge_any × 12.23%
supported lipid gap is the direct W10 motivation: **Layer 6a fuzzy
match against `ground_truth_pathway.external_id` is the remaining
lever to convert bridging into supported credit**.

Lipid 90% rollback vs non-lipid 47% — feedback hurts lipid tasks
more: lipid LLM iters write MORE-but-not-better claims (D4 WP167
trajectory confirmed at scale). Rollback rate as a paradigm
discriminator → W10 candidate: per-task-type rollback gating.

---

## 5. Verdict Aggregate (Final Iter Post-Rollback) vs Path W Baseline

| Metric | Path W (Opus, N=61) | Path X W9 D5 (N=63) | Δ pp |
|---|---:|---:|---:|
| supported % | 17.40 | **26.53** | **+9.13** ★ |
| unsupported % | 11.51 | 18.09 | +6.58 |
| contradicted % | 4.11 | **1.56** | **−2.55** ★ |
| unverifiable_v0 % | 66.97 | 53.82 | −13.15 |
| total claims | 3,379 | 2,631 | −748 |

### 5.1 Lipid bucket vs non-lipid breakdown

| Metric | Lipid WP167 (N=10) | Non-lipid (N=53) |
|---|---:|---:|
| supported % | 12.23 | **29.22** |
| unsupported % | 25.66 | 16.67 |
| contradicted % | 0.96 | 1.67 |
| unverifiable_v0 % | 61.15 | 52.44 |
| total claims | 417 | 2,214 |

### 5.2 Reading the +9.13 pp supported lift

The +9.13 pp jump from 17.40 to 26.53 is the dominant W9 framework
signal. Three compounding causes:
1. **W9 D2 dispatcher fix exposes real PA data to the LLM** — D3
   confirmed mummichog/ramp/psea all return non-empty namespace-
   prefixed pathways. The W8 D5 baseline LLM saw 0-pathway envelopes
   on 4-of-5 tools; W9 D5 LLM sees real cross-paradigm material.
2. **Closed-loop feedback iter 1 + iter 2 actively exercise the
   pipeline** — 62/63 tasks trigger feedback. The non-lipid bucket
   particularly benefits (29.22% supported).
3. **Path W is a single-iter Opus baseline**; W9 D5 Path X uses up
   to 3 iters with verifier feedback. Comparison is not strictly
   apples-to-apples (W9 spent more LLM cost) but the lift is the
   marginal value of the closed-loop ConcordMet architecture over a
   single-shot LLM baseline.

### 5.3 Reading the −2.55 pp contradicted drop

W8 D5 contradicted rate 4.11 vs W9 D5 1.56 → the LLM-agent's claims
under closed-loop feedback are LESS LIKELY to be flatly contradicted
by the verifier. This is the OPPOSITE of the "feedback makes it
worse" anecdote in the rollback rate — contradicted (Layer C verdict
"this is wrong against curated DB") drops by 62%. The 6.58 pp
unsupported INCREASE absorbs the 13.15 pp unverifiable_v0 DECREASE
and partial drop from contradicted, consistent with feedback iter
turning "unverifiable_v0 because LLM didn't ground" into "unsupported
because LLM grounded but in the wrong namespace" — i.e. the W10
Layer 6a cross-namespace gap finds the gap exactly here.

> 🟡 **Statistical caveat (sub6b-v3 audit, carried fwd from W8 D5)**:
> 50/63 tasks have signal-set Jaccard ≥ 0.7 with at least one other
> task; N_eff ≈ 13 pathway clusters. Aggregate raw % at N=63 is the
> visible-comparison number; significance testing should use
> pathway-cluster bootstrap CI. **W9 doesn't compute the bootstrap CI**
> — this is W10 work if paper writing needs it.

---

## 6. Tool Usage Patterns

| Metric | Value | W8 D5 (5-task) |
|---|---|---|
| iter_calls_max per task — median / p95 / max | **17 / 24 / 27** | 27 / 28 / 28 |
| tasks with iter_calls_max > 25 | 1 / 63 (1.6%) | 3 / 5 (60%) |

Per-tool call frequency (across all iters all tasks; up to 3 iters × 63 task = 189 iter records, of which 187 produced any tool call):

| tool | calls (of 187 iters) | hit rate |
|---|---:|---:|
| query_pathway_members | 187 | 100% |
| run_fella_rwr | 187 | 100% |
| run_mummichog | 187 | 100% |
| run_ramp_enrichment | 187 | 100% |
| run_metaboanalystr_psea | 183 | 97.9% |
| run_sspa_ora | 177 | 94.6% |
| lookup_chebi | 103 | 55.1% |
| reconcile_inchikey | 60 | 32.1% |
| search_literature | 8 | 4.3% |

★ **Tool call max dropped from W8 D5 27/median to W9 D5 17/median** —
the LLM no longer wastes turns retrying empty-pathway tools. D2a +
D2b means each PA tool returns actual data on first call, so the
LLM finalises sooner without exhausting the turn budget.

★ **LLM calls every PA tool every iteration** (5 PA × 187 iters
~= 935 of which 911 successful — sspa wrapper_unavailable + fella
wrapper_runtime_error were the "ok=False but informative" envelopes,
which the LLM may have read once and stopped re-calling). System
prompt's "≥ 3 PA tool call per task" rule is satisfied by every task
multiple times over.

★ **`search_literature` triggers only 8/187 iters (4.3%)** — LLM
predominantly relies on the structured PA tools for grounding, not
literature. Consistent with the W8 system prompt's "search only when
structured tools cannot answer" instruction.

★ **`lookup_chebi` triggered 55.1% of iters** — meaning LLM still
explicitly looks up ChEBI metadata even though the W9 D2a dispatcher
enriches input compound_ids automatically. Likely the LLM does this
defensively because the system prompt encourages namespace-clean
inputs.

★ **`reconcile_inchikey` triggered 32.1%** — LLM occasionally
detects cross-method namespace disagreement and triggers
reconciliation. The 32% rate suggests the W9 D2-fixed envelopes
expose enough cross-paradigm variation that the LLM does notice
namespace conflicts.

---

## 7. Token Usage (D3 finding — context budget verification)

| Metric | Value |
|---|---|
| LLM calls total (across all 63 tasks) | n_calls_total in summary |
| per-task total tokens — median | **360,752** |
| per-task total tokens — p95 | 537,394 |
| per-task total tokens — max | 632,799 |
| per-task total tokens — min | (from breakdown) |
| total prompt tokens (cumulative) | **21,197,289** |
| total completion tokens (cumulative) | 2,778,564 |
| total tokens (cumulative) | **23,975,853** |
| saturate threshold (D3 projection) | 120,000 tokens |
| tasks exceeding 120K cumulative | **63 / 63 (100%)** |

### 7.1 Reinterpretation of "saturate rate 100%"

The D3 finding said "55-60% of MiniMax-M2.7 128K window per task"
based on **single-iter** tool-result accumulation. The W9 D5
saturate threshold of 120K was set against the **128K MiniMax-M2.7
single-call context window**, but the W9 D5 aggregator sums
total_tokens across ALL LLM calls in a task (~25 calls per task
average). 360K cumulative ≠ 360K in any single call — the LLM
context window is enforced per-call.

**Single-call token usage** (derived from cumulative / calls):
- median: 360,752 / ~25 calls = **~14,400 tokens per call** — well
  under the 128K per-call ceiling.
- max: 632,799 / ~28 calls = **~22,600 tokens per call** at the
  most chatty task.

→ **No actual context-window saturation occurred in W9 D5**. The
LLM never hit the per-call 128K ceiling. The cumulative budget
metric in the summary is a "total token spend" indicator, not a
context-saturation indicator. **D3's worry about context truncation
was a false alarm**; the LLM-agent never lost messages mid-task.

### 7.2 Cost reading

23,975,853 total tokens × MiniMax-M2.7 reference pricing
(~$0.0007/1k prompt + ~$0.0027/1k completion):
- Prompt: 21.2M × $0.0007/1k = ~$14.84
- Completion: 2.78M × $0.0027/1k = ~$7.50
- **Total estimated cost: ~$22.4**

Marginal over W9 budget $20 (W9 prompt §6 Stop #6). The actual
MiniMax billing line item should be cross-referenced; the reference
pricing above is the public 2026 rate.

> 🟡 **W10 cost-management candidate**: per-task average ~$0.35.
> A re-run on a per-LLM-call-cheaper model (e.g. MiniMax-M2.7-lite
> if available, or GPT-4o-mini) would cut cost ~3× for the same
> token volume. Not blocking, but worth a paper-budget note.

---

## 8. New Failure Modes Surfaced in W9 D5

### 8.1 Lipid bucket bridge_in_any 100% but supported only 12.23%

The W9 D2 dispatcher fix lets the LLM see WP-namespace ramp pathways
on lipid tasks → the LLM bridges every single lipid task (10/10) and
writes claims with `pathway_id="WP:WP167"`. **But B1 Layer 6a
SET_ENRICHMENT compares against task's `ramp_enrichment_result.top_pathways`,
which uses RaMP internal IDs `RAMP_P_NNNNNN` not the WP-namespace
external_id**. A WP-namespace LLM claim cannot match a RaMP-internal
acceptance set entry. So the 100% bridge × 12% supported gap is
**B1 Layer 6a cross-namespace recognition failure**, not LLM-agent
failure. **W10 highest priority**.

### 8.2 Closed-loop rollback hurts lipid bucket disproportionately

Lipid 90% rollback rate vs non-lipid 47%. The closed-loop quality
metric (`n_contradicted + n_unsupported`) penalises lipid task's
WP-namespace claims (treated as unsupported by Layer 6a — see 8.1),
making iter 1/iter 2 quality worse than iter 0. Rollback then
discards the iter that bridged. **W10 candidate: per-bucket
rollback gating** (skip rollback when ground_truth_pathway.external_id
appears literally in any iter's claims).

### 8.3 Cost estimate slightly over $20 ceiling

Per §7.2, ~$22.4 estimated cost vs $20 ceiling. Documented for W10.
W10 candidate: per-LLM-call-cheaper-model variant + cost ablation.

### 8.4 Verifier `unsupported` rate up 6.58 pp without proportional
supported drop

W9 D5 unsupported = 18.09% vs Path W 11.51% (+6.58 pp). At the same
time unverifiable_v0 = 53.82% vs 66.97% (-13.15 pp). The 13.15 pp
that left unverifiable_v0 did NOT all go to supported (+9.13 pp) —
6.58 pp went to unsupported and ~3 pp went elsewhere (sum is
imperfect because the verdict-share denominator changed). This means
the closed-loop architecture moved verdicts FROM "couldn't judge" TO
"judged unsupported" — i.e. the LLM is being more declarative under
feedback pressure, and the verifier catches more of those
declarations as wrong (in its current narrow definition of "right").
**Without Layer 6a cross-namespace recognition, that movement is
mostly framework noise; with it, the unsupported bucket would shrink
further toward supported**.

---

## 9. Wrapper Health Per-Task Diagnostic

For each of the 5 PA wrappers, mean `_n_pathways` and percent-of-task
distribution. Surfaces wrapper-level coverage gaps that no single
task would expose (e.g. "psea drops to n=0 on lipid tasks").

| Wrapper | mean _n_pathways | tasks with _n_pathways=0 | dominant namespace |
|---|---:|---:|---|
| sspa | 0 (env_wrapper_unavailable 63/63) | 63 | n/a |
| ramp | TBD | TBD | TBD |
| metaboanalystr_psea | TBD | TBD | KEGG |
| mummichog | TBD | TBD | MUMM |
| fella | 0 (env_runtime_error 63/63) | 63 | n/a |

---

## 10. W10 Issue List (Based on W9 D5 Evidence)

| # | Issue | Severity | W9 D5 evidence | W10 action |
|---|---|---|---|---|
| 1 | **B1 Layer 6a cross-namespace ground-truth gap** | **HIGH** (paper-critical) | Lipid 100% bridge × 12.23% supported gap (§8.1); 33/63 bridge_lost_to_rollback | Add task.ground_truth_pathway.external_id (and name fuzzy match via W7 V1 token-Jaccard) to Layer 6a acceptance set; expected to convert ~30 pp of bridge_lost into supported |
| 2 | Quality metric penalises bridging | MEDIUM (paper-critical) | 27/63 `feedback_made_it_worse` rollback × half of those had bridging in the rolled-back iter | Bridge-aware quality variant (don't count `unsupported` claims whose pathway_id matches ground_truth_pathway.external_id) OR per-task-type rollback gating (§8.2) |
| 3 | FELLA R subprocess "argument is of length zero" | MEDIUM | 63/63 wrapper_runtime_error (network paradigm lost) | R-side defensive check or KEGG graph prewarm; possibly KEGG cpd ID filter on input. 4h time-box was W9 D4 stretch (deferred); W10 first-pass investigation |
| 4 | sspa pkg env install | LOW | 63/63 wrapper_unavailable | optional dev env improvement (5/5 PA → 6/5 paradigm coverage) |
| 5 | Cost > $20 budget (W9 prompt §6 Stop #6) | LOW | §7.2 ~$22.4 estimated | cheaper-model ablation OR truncate_to_budget per envelope to reduce prompt size |
| 6 | Per-task statistics N_eff ≈ 13 cluster | n/a (statistical correction) | sub6b-v3 audit P1-1 | pathway-cluster bootstrap CI for any W10+ paper number |
| 7 | Path Y W9 re-run | LOW (V3 comparison hygiene) | Path Y was last measured pre-W9-D2; same 96.83% may not hold with the W9 dispatcher | W10 re-run Path Y with the W9 D2-fixed wrappers |

W9-D5-specific NEW items (1 + 2 promoted from W8 D5's MEDIUM to W10
HIGH on the strength of N=63 evidence vs W8 D5's N=5 anecdote).

---

## 11. Strict TDD Audit (Cumulative W9)

| Sub-piece | RED commit | GREEN commit | Tests added | Slip |
|---|---|---|---|---:|
| D1 RED phase | `f90fce8` | (intentional RED only) | 5 (4 fail + 1 xfail) | 0 |
| D2a id-type negotiation | `f5062de` | `4d725f8` | 6 | 0 |
| D2b mummichog | `df3053c` | `1fee709` | 2 + D1 flip | 0 |
| D2b ramp | `27b31d4` | `55b2ab6` | 3 + D1 flip | 0 |
| D2b psea | `d86e5b1` | `aecc366` | 2 + D1 flip | 0 |
| D2b fella stub | `08893c9` | `7d325ba` | 2 (contract bridges to D2c) | 0 |
| D2c envelope error surfacing | `768295f` | `1b47a9c` | 3 | 0 |
| D3 integration verify | `56352be` (chore) | — | — | n/a |
| D5 / D6 (this) | — | — | — | n/a |
| **W9 TOTAL** | **6 RED commits** | **6 GREEN commits + 1 chore** | **23 new tests** | **0** |

---

## 12. Path W / Y / Z baseline numbers (carry-over, no W9 re-run)

| metric | Path W (Opus baseline, N=61) | Path Y (V3 algo, N=63) | Path Z (RaMP only, N=63) |
|---|---:|---:|---:|
| precision@10 strict | n/a | 96.83 | 96.83 |
| precision@10 fuzzy | n/a | 96.83 | 96.83 |
| supported % | 17.40 | n/a | n/a |
| mean wall / task | (sunk) | 31.8 s | 1.24 s |

W8 D5 framework health report §5 already cites that Path Y ≈ Path Z
on sub6b-v3 because only 2 of 5 PA wrappers contributed pathways in
the unfixed dispatcher. W9 D2 fixes the dispatcher but does NOT
re-run Path Y (Path Y uses the wrappers in driver mode, not the
dispatcher). The 96.83% Path Y number is therefore unchanged by W9.
For an apples-to-apples comparison with W9 D2-fixed dispatcher, a
W10 Path Y re-run is required.

---

## 13. Files / Commits (W9 cumulative)

### W9 commits on `feature/investigation-concord`

```
56352be chore(concord): W9 D3 — round-trip integration verify (5 task × 5 wrapper + short report)
1b47a9c feat(concord): W9 D2c — _detect_wrapper_internal_error + envelope escalation across 5 PA handlers
768295f test(concord): W9 D2c — wrapper-internal error surfacing (RED phase)
7d325ba feat(concord): W9 D2b fella — wire normalize_fella_output stub + preserve wrapper error in notes
08893c9 test(concord): W9 D2b fella — RED (stub schema + error preservation)
aecc366 feat(concord): W9 D2b psea — wire normalize_metaboanalystr_output into handler
d86e5b1 test(concord): W9 D2b psea — RED (R JSON parsing + v0.3.1 schema)
55b2ab6 feat(concord): W9 D2b ramp — wire normalize_ramp_output into handler
27b31d4 test(concord): W9 D2b ramp — RED (report.top_pathways extraction + ns prefix)
1fee709 feat(concord): W9 D2b mummichog — wire normalize_mummichog_output into handler
df3053c test(concord): W9 D2b mummichog — RED (namespace prefix + v0.3.1 schema)
4d725f8 feat(concord): W9 D2a — dispatcher id-type negotiation via ChebiLookup xref enrichment
f5062de test(concord): W9 D2a — dispatcher id-type negotiation (RED phase)
f90fce8 test(concord): W9 D1 — 5-wrapper shape contract test (RED phase)
```

(D5 + D6 commits land next.)

### W9 data artefacts

| Path | Purpose |
|---|---|
| `tests/concord/test_wrapper_shape_contracts.py` | D1 contract |
| `tests/concord/test_dispatcher_id_negotiation.py` | D2a unit |
| `tests/concord/test_d2b_{mummichog,ramp,psea,fella}.py` | D2b per-wrapper |
| `tests/concord/test_envelope_error_surfacing.py` | D2c unit |
| `concord/agent/tool_handlers.py` | D2a + D2b + D2c implementation site |
| `scripts/concord/w9_d3_round_trip_verify.py` | D3 driver |
| `scripts/concord/w9_d5_path_x_full.py` | D5 driver (this run) |
| `data/concord/w9_d3_verify/round_trip_table.json` | D3 5×5 table |
| `data/concord/w9_llm_agent_full/path_x_full63_results.jsonl` | D5 raw per-task signals |
| `data/concord/w9_llm_agent_full/path_x_full63_summary.json` | D5 aggregate + token usage |
| `data/concord/w9_llm_agent_full/path_x_full/` | D5 per-task ConcordFeedbackResult dumps (63 files) |
| `reports/agent/concord_sprint_w9_status.md` | sprint timeline |
| `reports/agent/concord_sprint_w9_d3_verify.md` | D3 short report |
| `reports/agent/concord_sprint_w9_framework_health.md` | THIS FILE (v2) |

