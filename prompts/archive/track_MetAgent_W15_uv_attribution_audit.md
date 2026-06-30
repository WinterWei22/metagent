# MetAgent W15 — UV Root-Cause Attribution Audit

**Sprint type**: PURE AUDIT (no production code change, no verifier modify, no react modify)
**Duration**: 0.5-1 day (D1 + D2 + D3 close-out)
**Date launched**: 2026-05-26
**Branch**: continue current MetAgent v2 worktree (`affectionate-shockley-b90943`)
**Model name**: **MetAgent** (NOT ConcordMet — ConcordMet is the sibling investigation worktree)

---

## §0 Onboarding — read before any work

### Context inherited from W8 → W14
- Cumulative UV reduction: 52.95% (W10 D4) → **44.25%** (W14 close-out), -8.70pp over 5 sprints
- Pathway accuracy held at 86% throughout
- iter-2 quality degradation: 22.2% → 0% (W14 B `DEFAULT_MAX_FEEDBACK_ITERS = 1`)
- 52 commits / 0 strict-TDD slip
- Tag `metagent-v2-base-b1 @ ed6243b` immutable; B1 paper data immutable; B1 test 14-fail floor preserved

### Why this sprint exists (the problem W15 fixes)

W11 9-category UV classification (C1-C9) only sorts claims **by surface form** (namespace / consensus / signal / biology / noise). It does NOT answer the actual root-cause question:

> For each UV claim — is ReAct saying things it shouldn't (producer fault), or is Verifier missing a tool/data source to check legitimate content (verifier gap)?

**Evidence we already have**:
| Category | Producer fault | Verifier gap | Source |
|---|---|---|---|
| C7 namespace (W12 fixed) | ~50% | ~50% | W12 D5 — factual_sub6 covered 123 strict_id |
| C8/C9 noise (W14 fixed) | **9.5%** (14/148) | **90.5%** (134/148) | W14 §0 LLM reclassification |
| C1+C2 cross-method | ? | ? | **NEVER MEASURED** |
| C3 signal_evidence | ? | ? | **NEVER MEASURED** |
| C5 intermediate_biology | ? | ? | **NEVER MEASURED** |

**Verdict**: 2 measured buckets both lean verifier-gap. But C1/C2/C3/C5 together account for ≥60% of current 44.25% UV. Acting on guesses here is exactly the `feedback_uv_sprint_must_reclassify_first` trap (W12 over-estimated ceiling 6-7×).

### What W15 produces (audit output, not code)

1. CSV: every current UV claim → `{producer_fault, verifier_gap, both}` label + 9-category bucket + free-text rationale
2. Summary: producer:verifier:both ratio **per bucket** + overall
3. Recommendation: ranked W16+ sprint candidates by **strict ceiling × ease** (producer-side fixes are cheap, verifier-side are expensive)
4. Update memory: extend `feedback_uv_sprint_must_reclassify_first` with attribution-audit step

### Death decrees still active
- 中文 conversation, English code
- No paper narrative / Discussion / Methods / Results / footnote prose
- MiniMax = remote API; cost MUST be read from `logs/llm_calls.jsonl`; never claim "$0 local"
- Verifier modification policy (2026-05-22 three tiers): **this sprint is pure-audit, no verifier modify expected**
- V3 deterministic algorithm tool stays unexposed to LLM
- Plain-summary at end of every assistant response (2 paragraphs: progress + next, 1-3 sentences each, no strict-TDD/commit/sprint jargon)

---

## §1 Goals & Non-Goals

### Goals
1. **G1**: Pull current 44.25% UV claim pool from the latest Path X full-63 result (W14 close-out artifact: `data/metagent/w14_path_x_post_noise_cap/path_x_full63_results.jsonl`)
2. **G2**: LLM-based per-claim 3-way classification: `producer_fault` / `verifier_gap` / `both`
3. **G3**: Cross-tabulate against W11 9-category buckets → producer:verifier:both ratio per bucket
4. **G4**: Output ranked W16+ candidate list with **strict ceiling × engineering cost** matrix
5. **G5**: Update memory with attribution-audit-as-prerequisite rule

### Non-Goals (DO NOT do in W15)
- ❌ Do NOT modify `verifier/` (no new layer, no helper change, no dispatcher edit)
- ❌ Do NOT modify `concord/agent/react_runner.py` or `prompts/concord/concord_react_prompt.md`
- ❌ Do NOT run a new Path X (use W14 close-out artifact as-is)
- ❌ Do NOT pick W16 sprint direction in W15 — only produce the ranked candidate list
- ❌ Do NOT write paper-style narrative in the summary

---

## §2 Architecture

### Files to create (all NEW, pure-add)
```
scripts/metagent/w15_uv_attribution.py        # LLM classifier driver
data/metagent/w15_uv_attribution/
  ├─ uv_claim_pool.jsonl                       # extracted from W14 Path X (input)
  ├─ attribution_raw.jsonl                     # LLM raw output per claim
  ├─ attribution.csv                           # final labeled CSV
  └─ summary.md                                # ratio table + W16+ candidates
tests/test_w15_uv_attribution_extractor.py     # ONLY tests the extractor logic
```

### Files NOT touched
- `verifier/**` — frozen
- `concord/agent/**` — frozen
- `prompts/concord/**` — frozen
- Any `data/eval/sub6/b1_*` or `data/eval/sub6/a3_*` — B1 paper data immutable

### Script design (scripts/metagent/w15_uv_attribution.py)
```
1. Load path_x_full63_results.jsonl from W14 close-out
2. Extract every claim with verdict == UNVERIFIABLE_V0
3. Carry over: task_id, claim_text, claim_type, current verifier_layer, W11 9-cat bucket (if tagged)
4. For each claim → MiniMax call with the §3 rubric → JSON {label, rationale, evidence_pointer}
5. Write attribution_raw.jsonl (one line per claim)
6. Aggregate → attribution.csv + summary.md
```

---

## §3 LLM classification rubric

### Three labels (mutually exclusive, must pick one)

**A. `producer_fault`** — ReAct should NOT have written this claim
- Meta-filler / boilerplate ("Based on the analysis...", "In summary,...")
- Template fragment leaking ("[METABOLITE]", "TBD")
- Self-reference ("As I mentioned earlier...")
- Claims with zero tool-output basis (pure hallucination)
- Prompt fragment echo

**B. `verifier_gap`** — Claim is legitimate, verifier cannot check it
- Content is sound / inferable from tool output, but:
  - No verifier layer covers this claim type
  - Required data source absent (e.g. KEGG REACTION for intermediate claims)
  - Claim type classifier mis-tags it → wrong layer dispatch
  - Cross-method consensus statements with no consensus checker
  - Numerical citation correctly from EnrichmentResult but B layer didn't catch

**C. `both`** — partial producer issue AND verifier can't catch
- ReAct phrased loosely (could be tightened) AND verifier has no layer to handle even the tight form
- Mixed claims ("X is in pathway Y and is an intermediate of Z") where half is checkable, half isn't

### Rubric prompt template (give to MiniMax)
```
You are auditing UV (unverifiable_v0) claims from MetAgent.

CLAIM: <text>
CLAIM_TYPE_TAG: <tag>
CURRENT_VERIFIER_LAYER: <layer_or_none>
PATH_X_TASK_CONTEXT: <one-line task summary>

Decide: producer_fault | verifier_gap | both

producer_fault rubric: meta-filler, boilerplate, hallucination with no tool basis,
template echo, self-reference.

verifier_gap rubric: claim content is sound and derivable from upstream tool output,
but no current verifier layer/data source can check it.

both: phrased loosely AND no layer would catch even the tight form.

Output JSON: {"label": "...", "rationale": "...", "evidence_pointer": "..."}
```

### Quality guardrails
- Run on **MiniMax-M2.7** (consistent with W11/W12/W14 §0 audits)
- Sample 20 claims manually → spot-check rubric agreement before scaling
- If <80% agreement → tighten rubric, re-run sample

---

## §4 Deliverables

### D1 (RED + setup, ~0.3d)
- [ ] Pull UV pool from W14 Path X jsonl → write `uv_claim_pool.jsonl` + report count
- [ ] Write extractor test (`tests/test_w15_uv_attribution_extractor.py`) — verify count, schema, no leaked verdict types
- [ ] Run RED — extractor not yet implemented, test fails
- [ ] Implement extractor → GREEN
- [ ] Manual spot-check 20 claims for rubric calibration

### D2 (LLM run + aggregate, ~0.3-0.5d)
- [ ] Run `w15_uv_attribution.py` on full UV pool via MiniMax
- [ ] Verify cost from `logs/llm_calls.jsonl` (NOT estimated — actual)
- [ ] Produce `attribution.csv`
- [ ] Cross-tab against W11 9-cat → write `summary.md`:
  - Table A: producer:verifier:both ratio overall
  - Table B: ratio per C1-C9 bucket
  - Table C: W16+ candidates ranked by (strict_ceiling × ease_score)
- [ ] Commit `[w15-audit]` (no `[verifier-modify-warning]` needed — pure-add)

### D3 (close-out, ~0.2d)
- [ ] Memory update: extend `feedback_uv_sprint_must_reclassify_first.md` with the attribution step (now reclassification = surface bucket + producer/verifier/both split)
- [ ] Ping user with summary + recommended W16 direction
- [ ] Tag-able commit `report(audit): W15 UV attribution`

---

## §5 Hard Gates

| Gate | Pass criteria |
|---|---|
| HG-1 | UV pool count from W14 jsonl matches reported 44.25% × total_claim (±2 tolerance) |
| HG-2 | LLM rubric spot-check ≥80% manual agreement (20-sample) |
| HG-3 | 100% of UV claims labeled (no UNCLASSIFIED leak) |
| HG-4 | Cost from `logs/llm_calls.jsonl` actual reported (no "$0 local" claim) |
| HG-5 | B1 test floor unchanged (run `pytest tests/` — 14 fail or fewer, no NEW fail) |
| HG-6 | No file under `verifier/` or `concord/agent/` modified (`git diff --name-only` audit) |

---

## §6 Daily breakdown

### D1 (Day 1, ~0.3d)
1. Read W14 close-out artifact path, confirm UV count
2. Write extractor + RED test
3. GREEN extractor
4. 20-sample manual spot-check on rubric → tighten if needed
5. Commit `feat(audit): W15 UV extractor`

### D2 (Day 1-2, ~0.3-0.5d)
1. Full MiniMax run (expect ~700-900 claims, ~$1-2)
2. Validate cost from llm_calls.jsonl
3. Aggregate → CSV + summary.md
4. Commit `report(audit): W15 attribution + W16 candidates`

### D3 (Day 2, ~0.2d)
1. Memory update
2. User ping with ranked W16 candidates
3. Await W16 direction

---

## §7 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Rubric ambiguity (claim is both producer-y and verifier-y) | Explicit `both` label; require rationale string |
| MiniMax classifier drift vs W11/W12/W14 LLM runs | Use same model version; spot-check 20 |
| UV pool extraction misses verdict variants (DROPPED vs UV) | Test explicitly filters `verdict == UNVERIFIABLE_V0` only |
| Cost overrun | Set max claim cap = 1000; if pool larger, sample stratified by 9-cat bucket |
| Temptation to start fixing in W15 | NON-GOAL §1 explicit — only audit, defer fixes to W16 |

---

## §8 Banned phrases in this sprint output

- "approximately $0 local" / "free local run" — MiniMax is remote API
- Paper narrative: "Our results show...", "We demonstrate...", "In conclusion,..."
- Strict-TDD/commit/sprint jargon in the user-facing plain summary

---

## §9 Memory updates expected

After D3, update:
- `feedback_uv_sprint_must_reclassify_first.md` — append: "Step 2.5 = attribution audit (producer_fault / verifier_gap / both per claim) BEFORE picking layer-vs-prompt sprint direction"
- New memory? Maybe `project_metagent_w15_attribution_findings.md` if findings are non-obvious

---

## §10 First action on receiving this prompt

1. Acknowledge in Chinese, 2-paragraph plain summary at end
2. Read `data/metagent/w14_path_x_post_noise_cap/path_x_full63_results.jsonl` (or find the actual file if path differs)
3. Confirm UV count matches 44.25%
4. Start D1 extractor + RED test
5. Ping user after D1 GREEN with extractor count + 20-sample spot-check result

---

**Ready. Go.**
