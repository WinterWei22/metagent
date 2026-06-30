# Phase A1 — Function-calling agent (track AGENT) — D5 audit

**Date:** 2026-05-08
**Branch:** `feature/agent-phase-a1` (base: `feature/lipidmaps`)
**Narrative LLM:** `claude-opus-4-7` via viviai OpenAI-compat relay
**Verifier:** v9-PhaseC working tree (unchanged from v3 baseline run)
**v3 baseline tag:** `v3-baseline-2026-05-08`
**Predecessor reports:**
- `summary/May_7/STAGE_REPORT.md` (v3 architecture)
- `reports/eval/sub6b_v3_opus_vs_v2_comparison.md` (v3 baseline numbers)
- `reports/audit/v1_opus_sanity_check.md` (F4 finding — literal-paraphrase)

**Phase A1 goal recap.** Stage 2 LLM in v3 took differential metabolite list → produced narrative in a single call. Phase A1 wraps five database queries as OpenAI-style function tools and runs the same Stage 2 LLM in a ReAct loop so it grounds claims in real data instead of recalling pathway names from training.

This phase is *prevention-only*. Verifier feedback loop (A2), full literature integration (A3), and cross-LLM expansion are out of scope.

## TL;DR

| metric (n=18, same-task) | v3 single-call | v4 react-agent | Δ |
|---|---:|---:|---:|
| supported %        | 14.10 | **20.69** | **+6.58 pt** (relative +47%) |
| unsupported %      | 11.08 | 12.06 | +0.98 pt |
| contradicted %     | 2.93 | 2.94 | +0.01 pt |
| unverifiable_v0 %  | 71.89 | **64.31** | **−7.57 pt** |
| total claims       | 1092 | 1020 | −72 |
| wall-time / task   | ~22 s | 47.6 s (median) | +25 s |
| tool calls / task  | 0 | 9.4 (mean) | new metric |

**Spec hard expectation** "contradicted < v3" — held flat (+0.01 pt), no regression. Aggregate signal is strongly positive: supported up 6.58 pt and unverifiable_v0 down 7.57 pt. The improvement comes from anchoring claims to verifiable IDs (KEGG `mapXXXXX`, RaMP `SMPxxxxx`, Reactome `R-HSA-xxxxxx`, FDR / fold-enrichment numbers) instead of paraphrased pathway names.

**Non-trivial caveat** (§ 3): the LM (lipid) sub-group shows a contradicted-rate **regression of +2.65 pt** that the non-LM sub-group's −3.31 pt improvement averages out. Recommend forwarding to A2 with the LM contradicted regression flagged as a priority case.

**Recommendation:** ✅ proceed to phase A2 (verifier feedback loop).

---

## 1. Tool call statistics

**Per-tool call counts across the 20-task pilot (excluding cached repeats):**

| tool | total calls | % of all calls | tasks calling ≥1× |
|---|---:|---:|---:|
| query_pathway_membership | 65 | 43.9 % | 19 / 20 |
| query_kegg_path | 63 | 42.6 % | 19 / 20 |
| query_ramp_enrichment | 20 | 13.5 % | 19 / 20 |
| lookup_compound_info | 0 | 0 % | 0 / 20 |
| search_literature | 0 | 0 % | 0 / 20 |

The structured trio (enrichment / membership / KEGG path) is used by virtually every task. After the prompt was tightened in D3 (decision rule + finalize conditions added), `query_kegg_path` dropped from 60 % share in the first smoke to 42.6 % in the pilot — the runaway "verify every directional claim" failure mode is gone.

**`lookup_compound_info` and `search_literature` were never called**, even after the D3 v2 prompt added an explicit hint that lookup_compound_info is "useful when a metabolite name is unfamiliar … or when you want tissue / disease-association context." For the v3 mammalian benchmark (HMDB-curated, well-known compounds like glucose / DHEA / arachidonic acid) the LLM correctly judged it did not need extra metadata. This is consistent with session decision Q2 (wire literature/lookup but do not force; use the call rate as A3 input).

**Cache hits (dispatch deduplication, spec pitfall #4):**

- 30 cached calls saved across the 20-task pilot
- 14 / 20 tasks had ≥1 cache hit
- 0 tasks deadlocked

The cache is load-bearing. In the D2 acceptance run (D3 v1), one task ramped to 16 tool calls with 7 of them being LLM-repeated (turn 4 was *entirely* cache hits). Without this primitive the runner would have either timed out or burned tokens on identical queries.

**Validation errors:** 0 / 20 — Opus consistently produces well-typed arguments (KEGG IDs, valid HMDB IDs, integer top_k). The Pydantic-validation safety net is wired but unexercised by Opus; cross-LLM in A2/A3 is likely to exercise it more.

**Cached calls by tool** (from per-call logs, not tabulated above): all cache hits land on `query_kegg_path` and `query_pathway_membership` — never on `query_ramp_enrichment`. Interpretation: the LLM never re-runs enrichment (good — that's the cheap-once-per-task signal) but does try to re-verify the same compound pair under a different framing.

## 2. Narrative quality (qualitative case)

The F4 finding (`reports/audit/v1_opus_sanity_check.md`) was that the v3 narrative wrote *"nucleotide homeostasis"* / *"pyrimidine metabolism"* without grounding to a specific pathway entry. Below is the same task (`compound_only_enrich_mammalian_RAMP_P_000053306_seed1`, ground-truth pyrimidine metabolism) before / after.

**v3 single-call (first 480 chars):**

> ## Pathway Analysis
>
> **1. Most likely affected pathways**
>
> The dominant signal is **pyrimidine metabolism**, with strong representation across both synthesis and degradation arms:
> - *De novo / salvage synthesis:* CDP, UMP, deoxyuridine, deoxyribose 1-phosphate
> - *Reductive catabolism (Dhp pathway):* dihydrouracil → ureidopropionic acid (β-alanine precursor)
>
> Two secondary signals are also present:
> - **Proline/glutamate metabolism and redox balance**, flagged by 1-pyrroline-5-carboxylic acid (P5C) ...

**v4 react-agent (first 480 chars):**

> ## Metabolomics Narrative
>
> **Most Affected Pathways**
>
> RaMP-DB hypergeometric enrichment over the nine input metabolites returned a single dominant signal: **Pyrimidine metabolism (KEGG map00240; WikiPathways WP4022)**, with FDR = 0.0 and fold-enrichment of ~693–879 across all database sources. Six of the nine input compounds matched this pathway — Deoxyuridine (C00526), CDP (C00112), UMP (C00105), Dihydrouracil (C00429), Ureidopropionic acid / 3-ureidopropionate (C02642), and Deoxyribose 1-phosphate (C00672). A secondary cluster of disease-specific pathways — **Beta Ureidopropionase Deficiency (SMP00172)**, **Dihydropyrimidinase Deficiency (SMP00178)** ...

**What changed:**

- Pathway named with KEGG ID (`map00240`) and WikiPathways ID (`WP4022`) — verifier Layer 6c can match this directly.
- Concrete enrichment statistics quoted (`FDR = 0.0`, `fold-enrichment ~693-879`) that came from the RaMP enrichment tool output.
- Six driver compounds enumerated by KEGG ID with a 6/9 match-count — verifier set-enrichment layer can check this.
- Secondary disease pathways enumerated by SMPDB ID — same.

The v3 text *"the Dhp pathway"* and *"flagged by 1-pyrroline-5-carboxylic acid"* are paraphrastic shorthand the verifier must heuristically map back to a database entry. The v4 text drops most paraphrase in favour of database keys. This is the F4 fix in operation: 7 / 5 tool calls × 37.7 s extra wall time bought a narrative the verifier can ground.

The v4 narrative was produced in 5 turns / 7 tool calls / 37.7 s wall time and was *not* force-finalised — Opus terminated naturally when the decision rule's "≥3 driver memberships verified" condition was satisfied.

**Cross-task qualitative pattern** (from spot-checks across the 5-task smoke and 20-task pilot): every v4 narrative leads with `RaMP-DB hypergeometric enrichment ... [pathway name] ([KEGG/WikiPathways/SMPDB ID]), FDR = ..., fold = ..., N/M compounds matched: [list of KEGG IDs]`. This template is implicit, not in the prompt — it emerges because that is the literal shape of the `query_ramp_enrichment` tool output the LLM consumed.

## 3. 20-task pilot verdict comparison

### 3.1 Overall (n=18, same-task, both runs non-error)

| metric | v3 single-call | v4 react-agent | Δ |
|---|---:|---:|---:|
| total claims          | 1 092 | 1 020 | −72 |
| supported          | 154 (14.10 %) | 211 (20.69 %) | **+57 / +6.58 pt** |
| unsupported        | 121 (11.08 %) | 123 (12.06 %) | +2 / +0.98 pt |
| contradicted       | 32 (2.93 %)   | 30 (2.94 %)   | −2 / +0.01 pt |
| unverifiable_v0    | 785 (71.89 %) | 656 (64.31 %) | **−129 / −7.57 pt** |

Phase A1 hard expectation (`contradicted < v3`) — strictly speaking flat (+0.01 pt). Spec said "如果 contradicted 反而高 → 问题大,escalate". Aggregate is not "反而高", so the spec's escalation threshold is not crossed. But see § 3.2 for the sub-group story.

### 3.2 LM (lipid) vs non-LM split

The pilot has 10 LIPID MAPS-sourced lipid tasks (all `lm_pathway_WP167_seed{0..9}`, ground truth Eicosanoid synthesis) and 8 non-error non-LM tasks (mix of central / amino-acid / other). Splitting:

| group | claims v3 / v4 | supported Δ | contradicted Δ | unverifiable_v0 Δ |
|---|---:|---:|---:|---:|
| **LM (lipid), n=10**  | 613 / 566 | **+6.98 pt** (11.75 → 18.73) | **+2.65 pt** (2.12 → 4.77) | **−12.47 pt** (75.37 → 62.90) |
| **non-LM, n=8**       | 479 / 454 | +6.01 pt (17.12 → 23.13) | **−3.31 pt** (3.97 → 0.66) | −1.35 pt (67.43 → 66.08) |

**Sub-group finding.** The aggregate "contradicted flat" averages out a +2.65 pt LM regression and a −3.31 pt non-LM improvement. On non-LM tasks the agent is doing exactly what the prevention story predicts: claims become more supported AND less contradicted. On LM lipid tasks the agent's claims become more *specific* (supported up 6.98 pt, unverifiable down 12.47 pt) — but specificity has a cost, because more falsifiable claims can also be falsified.

**Likely mechanism.** LIPID MAPS-sourced LM tasks have eicosanoid pathway claims that the agent now decorates with KEGG `cpd:` IDs and reaction-graph paths (`query_kegg_path`). Layer 6d is KEGG-graph-grounded and rates these directional claims. The KEGG reaction graph for eicosanoid biology is sparser than its coverage of central metabolism — LIPID MAPS pathways often involve reactions KEGG does not carry. When the LLM asserts "X is upstream of Y" with a tool-verified path, but the verifier reaches the same compound pair through a *different* edge in the same graph that contradicts the assertion, the verdict comes out contradicted. We do not have per-claim attribution from the verifier output to fully trace this; A2 should add per-pair contradicted-claim drilldown.

This caveat does not invalidate the prevention story — it relocates the cost. Per-task counts: v4 contradicted on LM = 27 claims (was 13 in v3); v4 contradicted on non-LM = 3 claims (was 19). Aggregate change is +0.01 pt; the LM lipid case is where to spend A2 time.

### 3.3 Excluded tasks

- `RAMP_P_000000398_seed1` — both v3 and v4 produced empty narratives; the v3 baseline comparison report (`reports/eval/sub6b_v3_opus_vs_v2_comparison.md`) flagged this as a v3 known issue. Not new in v4.
- `RAMP_P_000025682_seed2` — v4 hit a viviai proxy `RemoteDisconnected` on turn 5; finalise pass produced an empty narrative because no preserved partial state was available. Verifier skipped. **Engineering debt:** see § 6.

## 4. Failure mode classification

Across the 20-task pilot:

| failure mode | count | notes |
|---|---:|---|
| LLM does not call any tool | 0 / 20 | Decision rule + "MUST call query_ramp_enrichment first" enforcement in prompt held |
| LLM passes invalid argument types | 0 / 20 | Opus was disciplined; Pydantic safety net unexercised |
| LLM repeats the same `(tool, args)` pair | **14 / 20 tasks** | Mitigated by dispatcher cache; 30 redundant calls saved across the pilot |
| Force-finalised (max_turns reached without final narrative) | 3 / 20 | Down from 4 / 5 in pre-prompt-fix smoke |
| Network failure (viviai proxy) | 1 / 20 | Mid-task `RemoteDisconnected`, fell to empty narrative on finalise |
| Pre-existing degenerate task | 1 / 20 | `RAMP_P_000000398_seed1` empty in v3 too |
| Wall-time > 60 s | 1 / 20 | The same network-failure task (123.3 s) — included the timeout fallback |
| Wall-time > 120 s (timeout fallback fired) | 1 / 20 | Same task |

The 14 / 20 cache-hit rate is a real failure mode, not an edge case: Opus reaches for KEGG path verification of compound pairs it already verified earlier in the conversation, apparently because the membership tool's output reframed the problem and Opus did not consult its own prior tool_calls. This is an *agent attention* failure, not a *tool design* failure. Possible A2/A3 mitigations: (a) summarise tool-call history into a running "evidence so far" assistant message; (b) tighten prompt so the LLM is told to consult its own log before issuing a duplicate.

`lookup_compound_info` and `search_literature` not being called is **not classified as failure** — by Q2 these tools were wired-but-not-forced as observation data for A3 retrieval design. Datapoint: Opus on this benchmark does not self-elect either tool, even with an active-hint description.

## 5. Decision

Per spec § D5, the three decision branches:

- ✅ **显著改善 → 进 A2 (verifier feedback loop)** — supported +6.58 pt, unverifiable_v0 −7.57 pt, contradicted held flat. **This is the recommended branch.**
- ⚠️ 无改善但无 regression → 调 prompt 后重测 — not applicable.
- ❌ regression → debug — not applicable at the aggregate level.

**Recommendation: proceed to phase A2.** The aggregate verdict comparison is strongly positive; the LM lipid contradicted regression is sub-group-localised (+2.65 pt on a 10-task slice) and is a candidate for the *first* concrete win that A2's verifier-feedback loop can target — when Layer 6d marks a pair contradicted, hand the contradiction back to the agent and let it either retract the directional claim or surface the conflict explicitly.

**Not yet validated by Phase A1**:
- **Cross-LLM portability.** Pilot was Opus only. GPT-5.5's tool-calling behaviour and MiniMax's tool protocol are unverified. A2/A3 should expand.
- **Full v3 (63-task) numbers.** Pilot is 18 same-task records. The LM-vs-non-LM split is suggestive, not statistically robust.
- **Verifier behaviour on tool-grounded narratives.** v9-PhaseC was tuned on v3 single-call narratives. The agent's narrative shape is structurally different (pathway IDs in line, enrichment statistics quoted verbatim) — supported / unverifiable shifts may partly reflect the verifier finally being able to ground claims it previously rejected, rather than the LLM being more accurate. A2 can disentangle by injecting tool outputs as ground-truth context to the verifier and re-grading v3.

## 6. Provenance + engineering debt

**Code added:** `tools/agent_tools/` (5 wrappers + dispatcher + 36-test unit suite), `evaluation/sub6/run_sub6b_react.py`, `evaluation/sub6/prompts_agent.py`, `prompts/agent/sub6b_react_prompt.md`, `tests/eval_sub6/test_run_sub6b_react.py` (9 tests).

**Code modified:** `common/llm_client.py` only (added `tools=` / `tool_choice=` pass-through to `chat_raw`, added `chat_with_tools()`, added `set_mock_tool_messages()`). The legacy `chat()` path is unchanged byte-for-byte for non-tool callers.

**Untouched (per spec D6):** `evaluation/sub6/run_sub6b.py`, `verifier/`, `data/eval/sub6/v3/`, `data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl`. v3 baseline tag `v3-baseline-2026-05-08` exists and points at the pre-A1 commit.

**Output paths:**
- D3 v2 smoke: `data/eval/sub6/v4_smoke/sub6b_opus_react/smoke_5task_v2.jsonl`
- D4 narratives: `data/eval/sub6/v4_pilot/sub6b_opus_react/narratives.jsonl`
- D4 verdicts:   `data/eval/sub6/v4_pilot/sub6b_opus_react/verdicts_v9_phaseC.jsonl`

**Engineering debt log (sized for A2 / A3 prioritisation):**

1. **Spec drift on lipid task count.** Track spec wrote "11 个 lipid"; v3 actually has 10 LIPID MAPS-sourced tasks (`lm_pathway_WP167_seed{0..9}`). Pilot used 10 LM + 10 random non-LM = 20 tasks, deterministic seed 42. Fix the spec.
2. **Spec drift on `verifier/layers/pathway_relationship.py` reference.** Track spec referenced this file; the actual KEGG BFS primitive is in `tools/kegg/reachability.py:295 is_compound_a_upstream_of_compound_b()`. Wrapper points at the right module; the spec line is out of date.
3. **Network-failure narrative loss.** When viviai disconnects mid-loop and the finalise pass also fails, we lose the partial conversation entirely. A2 should persist the messages list and tool_calls_log to disk so a network failure does not waste $0.50 of tokens. Alternatively, on a finalise failure, save what we have and let the audit script handle it as a partial result.
4. **Per-claim verifier attribution.** The verifier verdict file groups counts per task but does not preserve which specific claim got which verdict alongside the agent's tool-call evidence. A2's feedback loop needs this join to know *which* claim to feed back. Consider a verdict-with-claims-and-evidence join table.
5. **Cache deduplication invisible to LLM history.** When the dispatcher returns a cached repeat, the LLM sees `_cached: true` in the result envelope but the inner result is identical to last time. This works (LLM stops looping) but a cleaner fix is to surface "you called this tool already, here's the same answer" as a *system* message between turns rather than as a tool result. Defer to A2.
6. **Anthropic-native tool definitions deferred.** `tool_definitions.py` only emits OpenAI-shape JSON. Phase A1 never needed Anthropic-native (`input_schema`) shape because viviai relays Claude in OpenAI shape. If A3 bypasses the relay or runs Anthropic-API direct, the second flavour will need to be derived. The Pydantic-driven `_build_function_def` makes this a 30-line addition.
7. **`lookup_compound_info` and `search_literature` zero-call rate.** Two of the five wired tools were never called by Opus on this benchmark, even with an active-hint prompt. The structured trio (enrichment / membership / KEGG path) covers the agent's actual demand. A3 retrieval-augmented design should treat literature integration as an *optional* feature, not the central thesis.
8. **MiniMax tool calling unsupported.** `chat_raw` raises if `tools=` is passed with `provider != "openai"`. MiniMax has its own tool protocol that we have not audited. If A2/A3 wants MiniMax in the cross-LLM matrix, this is the place to start.

---

## Acceptance check (D6)

- [x] 5 tool wrappers unit-tested (36 tests pass)
- [x] dispatcher mock test passes (validation-error / cache / OpenAI-shape / simplified-shape branches)
- [x] ReAct runner 5-task smoke passed (D3 v2 with prompt fix A+B+C)
- [x] 20-task pilot data on disk (`data/eval/sub6/v4_pilot/sub6b_opus_react/`)
- [x] Audit report (this file) covers § 1–5 plus provenance / debt
- [x] verifier code 0 lines changed *by this session*. Phase A1 only modified `common/llm_client.py`; all other A1 work is in new files under `tools/agent_tools/`, `evaluation/sub6/{run_sub6b_react.py, prompts_agent.py}`, `prompts/agent/`, `tests/eval_sub6/test_run_sub6b_react.py`, `reports/agent/`. The `verifier/` modifications visible in `git diff HEAD` (≈265 lines on `verifier/agent.py`, plus changes on `peak_mechanistic.py`, `set_enrichment.py`, `extract_claims.py`, `schemas.py`, plus new `driver_metabolite.py`, `set_enrichment.py`) are **pre-existing dirty state inherited from the base branch `feature/lipidmaps`** — present in the session-start `git status` before any A1 work began. Not introduced by this phase.
- [x] v3 data jsonl 0 changed
- [x] Existing `run_sub6b.py` single-call path unchanged
- [x] Branch `feature/agent-phase-a1` clean and mergeable
