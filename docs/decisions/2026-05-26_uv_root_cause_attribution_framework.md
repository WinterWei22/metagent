# UV Root-Cause Attribution Framework (W15)

**Date**: 2026-05-26
**Branch**: `metagent-v2`
**Status**: Active — W15 audit sprint in progress
**Author context**: discussion between user and main session 2026-05-26

---

## Context

After W8 → W14 (5 sprints), MetAgent's UV (unverifiable_v0) claim rate dropped from ~58% to 44.25%, with pathway accuracy held at 86%. Each sprint targeted a single W11 9-category bucket (C1-C9) by surface form (namespace / consensus / signal / biology / noise).

**Problem identified 2026-05-26**: The 9-category split only sorts claims **by what they look like**. It does NOT answer the structural root-cause question:

> For a given UV claim — is ReAct (the producer) saying things it shouldn't, or is Verifier missing a tool/data source to check legitimate content?

Without this split, sprint targeting is guesswork. W12 over-estimated its strict ceiling 6-7× because it conflated two sub-populations inside C7 (strict_id vs fuzzy_biology). The same risk applies to every remaining bucket.

Evidence we already had before W15 launch:

| Bucket | Producer fault | Verifier gap | Source |
|---|---|---|---|
| C7 namespace (W12 fixed) | ~50% | ~50% | W12 D5 — factual_sub6 covered 123 strict_id |
| C8/C9 noise (W14 fixed) | 9.5% (14/148) | 90.5% (134/148) | W14 §0 LLM reclassification |
| C1/C2/C3/C4/C5/C6 | ? | ? | **never measured** |

Both measured buckets lean verifier-gap, but C1-C6 (≥60% of current UV) were never split. Continuing to pick sprints by surface bucket without producer/verifier attribution is exactly the trap memory rule `feedback_uv_sprint_must_reclassify_first` was written to prevent.

---

## Options considered

**A. Continue picking sprints by W11 surface bucket** (status quo)
- Pro: zero audit overhead, momentum from W12-W14 patterns
- Con: guessing producer-side vs verifier-side ratio, repeats W12 ceiling-overshoot risk
- Con: cross-method consensus / signal_evidence / intermediate_biology have very different fix paths (prompt vs new layer vs new data source) — wrong sprint type wastes 1-2 weeks

**B. Per-claim 3-way attribution audit** (chosen)
- Pro: each subsequent sprint chooses fix path based on measured majority responsibility
- Pro: cheap (~$1-2 MiniMax, 0.5-1 day, no production code change)
- Pro: produces reusable ranking matrix for W16+
- Con: rubric ambiguity on `both` boundary cases (mitigated by §3 rubric design below)

**C. Just do cross-method consensus (W15 candidate #1) blind**
- Pro: pure-add new layer, low risk, similar to W12 architecture
- Con: if C1 turns out to be 50% producer-side (loose phrasing), a new layer won't catch the producer fraction — under-deliver target like W12 D5

**Chosen: B** — attribution before action. Memory rule `feedback_uv_sprint_must_reclassify_first` already mandates reclassification before any UV sprint. This extends that mandate from "surface bucket split" to "producer/verifier/both split per bucket".

---

## Decision

### Attribution rubric (3-way, mutually exclusive)

**`producer_fault`** — ReAct should NOT have written this claim
- Meta-filler / boilerplate ("Based on the analysis...", "In summary,...")
- Template fragment ("[METABOLITE]", "TBD")
- Self-reference / prompt fragment echo
- Claims with zero tool-output basis (hallucination)

**`verifier_gap`** — Claim is legitimate, verifier cannot check it
- Content derivable from tool output, but no current verifier layer covers it
- Required data source absent (e.g. KEGG REACTION for intermediate claims)
- Claim-type classifier mis-tags it → wrong layer dispatch
- Cross-method consensus statements with no consensus checker

**`both`** — phrased loosely AND no layer would catch even the tight form

### `both` disambiguation rule (added 2026-05-26 after HG-2 60% fail)

Default to a single label. Only assign `both` when **both** conditions hold simultaneously:
1. Phrasing is genuinely loose/improvable (not just slightly informal) — could be tightened to remove a producer concern
2. Even after tightening, no current verifier layer/data source could check the tightened form

If only (1) → `producer_fault`. If only (2) → `verifier_gap`. If neither → re-examine whether this should be UV at all.

### Pipeline

```
1. Load Path X full-63 result (latest UV-state snapshot)
2. Filter verdict == UNVERIFIABLE_V0
3. Per claim → MiniMax classifier with rubric → {label, rationale, evidence_pointer}
4. Cross-tab against W11 9-cat
5. Output: CSV + summary.md (ratio overall, ratio per bucket, W16+ candidates ranked by strict_ceiling × ease)
```

### Quality gates (Hard Gates)

| Gate | Criterion |
|---|---|
| HG-1 | UV pool count matches reported UV rate × total_claim (±2 tolerance) |
| HG-2 | LLM rubric vs human 20-sample agreement ≥ 80% strict |
| HG-3 | 100% claims labeled |
| HG-4 | Cost from `logs/llm_calls.jsonl` actual, not estimated |
| HG-5 | B1 test 14-fail floor preserved |
| HG-6 | `verifier/` and `concord/agent/` zero modification |

---

## Consequences

### Expected
- Every subsequent UV sprint (W16+) starts with a measured producer:verifier:both ratio per bucket
- Sprint type (prompt tweak / new layer / new data source) chosen by majority attribution
- Strict ceiling estimates calibrated against measured attribution, not surface bucket count

### Risks
- **Rubric drift across sprints**: if rubric phrasing changes between audits, results not comparable. Mitigation: pin rubric text in this doc + reuse `scripts/metagent/w15_uv_attribution.py` as template
- **MiniMax classifier non-determinism**: same claim may get different labels across runs. Mitigation: cache raw outputs, spot-check 20 manually
- **`both` over-assignment**: LLM tends conservative, inflates `both`. Mitigation: §3 disambiguation rule above

### Initial findings (W15 v1, n=901, agreement 60% strict / 100% axis-level)
| Label | Count | % |
|---|---|---|
| verifier_gap | 560 | 62.2% |
| both | 175 | 19.4% |
| producer_fault | 166 | 18.4% |

Bucket-level majority:
- C1 cross-method, C2 method-disagree, C4 uncertainty: ≥91% verifier_gap
- C3 signal, C5 intermediate-biology, C6 literature: 59-76% verifier_gap
- **C7 namespace**: 44% producer_fault (unexpected — W12 strict_id was supposed to be cleaned)
- C8 noise: 96% producer_fault (W14 already fixed)
- C9 other: 61% verifier_gap

**Headline**: ~62% verifier-side, ~18% producer-side, ~19% mixed. Main lever for W16+ is verifier capability, not prompt tightening.

C7 anomaly flagged for v2 re-examination: is the 44% producer_fault driven by `both` over-labeling (resolves under v2 rubric), or genuine residual ReAct namespace looseness (W12 factual_sub6 didn't cover)?

---

## Related

**Commits / artifacts** (to be filled after W15 D3 close-out):
- Script: `scripts/metagent/w15_uv_attribution.py`
- Raw output: `data/metagent/w15_uv_attribution/attribution_raw.jsonl` (v1) + `attribution_raw_v2.jsonl` (post-rubric-tighten retry)
- Summary: `data/metagent/w15_uv_attribution/summary.md`

**Prompt**: `prompts/track_MetAgent_W15_uv_attribution_audit.md` (sprint spec)

**Memory rules**:
- `feedback_uv_sprint_must_reclassify_first.md` (extended by this framework)
- `feedback_verifier_modification_policy.md` (this audit is pure-add, no ⚠ modify)
- `feedback_design_decisions_archive.md` (this doc lives by that rule)

**Prior verifier architecture decisions (backfill candidates)**:
- W12 `factual_sub6` layer + `subject_normalizer` helper (FACTUAL/GROUNDED claim handler)
- W14 `grammar.py` `DroppedReason` enum + `noise_pattern.py` helper
- W14 ReAct `DEFAULT_MAX_FEEDBACK_ITERS = 1` cap (iter-2 quality degradation lock)
