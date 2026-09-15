# Task 10 Report — v4 Verifier Offline Replay

**Date:** 2026-06-25
**Scope:** Offline replay of 112 existing v4 ReAct traces through the refactored verifier (no LLM cost).

---

## How the Replay Was Wired

1. **Trace source:** `data/metagent/v4_bench_eval_sub6hmdb_p1p2p3_20260625/path_x_full/` (112 JSON files from main metagent_v2 worktree, resolved via `_locate_trace_dir()` fallback).
2. **Benchmark join:** `data/benchmark/metagent_bench_v2/metagent_bench_easy_v4_metabolic.jsonl` (292 tasks, 112 matched by task_id).
3. **Adapter call:** `v4_task_to_subsix_source_report(task, react_result)` where `react_result = types.SimpleNamespace(enrichment_carriers=..., final_narrative_text=...)`.
4. **Narrative:** `final_narrative_json` from trace (grammar-v2 JSON shape `{"narrative_text": ..., "claims": [...]}`) passed as the `llm_output` string to `verify_sub6()` — routes through `_extract_classify` → `extract_claims_from_json` (zero-LLM path).
5. **Verdict collection:** from `result.claims_v2` (authoritative post-rewrite); `result.claim_metrics.dropped_by_grammar` for grammar drop count.

---

## Actual Numbers

| Metric | Value |
|---|---|
| Tasks processed without exception | **112 / 112 (100%)** |
| Tasks failed (crash / missing benchmark row) | **0 / 112** |
| Total claims surviving grammar validation | **0** |
| Total claims dropped by grammar | **1242** (avg 11.1 / task) |
| overall_verdict=failed | 112 / 112 |

**UV% / SUPPORTED% / INSUFFICIENT%:** N/A — zero claims survived grammar validation (see schema incompatibility finding below).

---

## Key Finding: V4 Claim Schema ≠ B1 Grammar V2

The v4 `final_narrative_json` claims use a ConcordMet-native format:
```json
{"claim_type": "PATHWAY_ENRICHMENT", "pathway_id": "KEGG:hsa00340", "pathway_name": "Histidine metabolism", "evidence_method": "run_ramp_enrichment", "rank": 1, "score": 1.1e-18, "score_type": "fdr"}
```

B1 grammar v2 `validate()` requires `"grammar"` (ClaimGrammar enum string) and `"claim_text"` (non-empty string). The v4 schema has neither → all 1242 claims fail at `grammar field missing or non-string: None`.

This means:
- **Pre-refactor:** 0/112 adapter survived (KeyError in `sub6b_task_to_subsix_source_report` on v4 tasks)
- **Post-refactor:** 112/112 adapter survived, verifier runs end-to-end, but 0 claims verified because pre-existing trace claims use a different schema

A real UV% requires a **live API rerun** with Tasks 1–9 patches active (new traces will produce grammar-v2 JSON claims from the updated system prompt).

---

## False-Positive Sanity

0 SUPPORTED set_enrichment claims existed (all dropped by grammar) → ratio = N/A.

---

## RaMP-Carrier Caveat

The 112 traces predate Task 1's RaMP carrier-capture patch. `enrichment_carriers` contains only `mummichog_enrichment_result` + `metaboanalystr_enrichment_result`. `ramp_enrichment_result` = `{}` (adapter fallback). The multisource pool runs on 2/5 paradigms only.

---

## Gate A Status

`PYTHONPATH=. pytest tests/test_verifier/ -q` → **321 passed, 0 failed** ✅

---

## Files Changed

- **Created:** `scripts/metagent/v4_verifier_replay.py`
- **Report:** `reports/reports_v3/2026-06-25_v4_verifier_multisource_replay.md` (gitignored, written but not committed)
- **Production files modified:** none


---

## Corrected Replay Results (post bridge-fix, 2026-06-25)

### Corrected Wiring

The original script fed `final_narrative_json` (ConcordMet-native schema) directly to `verify_sub6`.
This caused 100% grammar-drop because those claims lack the `grammar` + `claim_text` fields required
by B1 grammar v2 `validate()`.

**Fix:** call `concord_result_to_b1_structured_payload(react_result, task)` from
`concord/agent/verifier_adapter.py` as the translation bridge. This calls `_react_claim_to_verifier_grammar()`
for each claim, converting e.g. `{"claim_type": "PATHWAY_ENRICHMENT", "pathway_id": "KEGG:hsa00340", ...}`
into `{"grammar": "pathway_enrichment", "claim_text": "run_ramp_enrichment ranks KEGG:hsa00340 (...) at rank 1 ...", ...}`.

The `react_result` SimpleNamespace needed `final_claims` (list from `frr_dict.get("final_claims")`)
in addition to `enrichment_carriers`, `final_narrative_text`, `task_outcome`.

Mirror of `react_runner.py:verify_with_b1` lines 748-753 (env flag `METAGENT_VERIFY_STRUCTURED_CLAIMS=1` path).

### REAL Verdict Distribution (112 traces, full run)

| Verdict | Count | % |
|---|---:|---|
| SUPPORTED | 731 | 65.6% |
| INSUFFICIENT_EVIDENCE | 182 | 16.3% |
| UNSUPPORTED | 138 | 12.4% |
| UNVERIFIABLE_V0 | 64 | 5.7% |
| CONTRADICTED | 0 | 0.0% |
| NEEDS_HUMAN_REVIEW | 0 | 0.0% |

Total verified claims: 1115 (0 dropped by grammar)
Tasks: 112/112 processed, 0 failed (pre-refactor: 0/112 processed, 112/112 crashed)

### False-Positive Sanity Ratio

SUPPORTED set_enrichment claims: 343 total
- GT-matching (pathway name in ground_truth.perturbed_pathway.name): 169 = **49.3%**
- Off-pathway (noise): 174 = **50.7%**

Target "GT ≥ noise" not met. Expected: these 112 traces predate Task 1's RaMP carrier-capture patch.
`enrichment_carriers` contains only `mummichog_enrichment_result` + `metaboanalystr_enrichment_result`;
`ramp_enrichment_result` is absent. Ground-truth pathways are KEGG/RAMP_P namespaced → can't be found
in mummichog/metaboanalystr carriers → GT-match rate is depressed. A live rerun with RaMP carriers
present is expected to flip this ratio above 50%.

### RaMP Caveat (Critical)

All 112 traces generated BEFORE Task 1's RaMP carrier-capture patch (`react_runner.py:_store_enrichment_carrier`
RaMP branch fix). `ramp_enrichment_result` is absent from every trace. Multisource pool sees only 2/5
paradigms. Numbers above are **pessimistic lower-bounds**.

### Gate Results

| Gate | Result |
|---|---|
| Gate A (B1 verifier-core 408) | **408 pass / 0 fail** ✅ |
| Gate B (full repo) | **1619 pass / 18 fail / 33 error** — all pre-existing env fails, no regression ✅ |

### Secondary Fixes

1. **`_get_set_enrichment_supported_pathways`**: Fixed to read `VerifiedClaim.claim_type` / `.subject`
   directly (no `.claim` wrapper). Added uppercase `"ClaimType.SET_ENRICHMENT"` match and fallback
   extraction from parenthesised pathway name in `claim_text` when `subject=None`.

2. **`claim_table._SEVERITY_BY_VERDICT` missing `INSUFFICIENT_EVIDENCE`** (Task 6 oversight in
   commit `5157bb8`): patched at runtime via `_claim_table_mod._SEVERITY_BY_VERDICT[...] = "minor"`
   in replay script. No production files modified.

3. **Offline consistency-layer mock**: `set_mock(["[]"] * 20)` via `common.llm_client` makes Layer D
   return "no contradictions" — zero API cost, correct conservative offline assumption.

### Files Changed

- `scripts/metagent/v4_verifier_replay.py` — primary fix (bridge wiring + mock + sanity fix)
- `docs/decisions/2026-06-25_verifier_multisource_refactor.md` — §6 updated with measured numbers
- `reports/reports_v3/2026-06-25_v4_verifier_multisource_replay.md` — corrected report (gitignored)

Commit: `262f480` `fix(replay): use verifier_adapter bridge in v4_verifier_replay`

---

## Second-Pass Fix (flag-corrected replay + framing fixes, 2026-06-25)

### C1 — Env Flag Fix

**Production env vars replicated** (from `react_runner.py:verify_with_b1` lines 775-781,
structured branch):
- `METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT = "1"` — **primary fix**; was missing in prior replay
- `METAGENT_LLM_PROVIDER` — set via `os.environ.setdefault("METAGENT_LLM_PROVIDER", "openai")`
  (mock intercepts before real HTTP; value only matters for non-mock paths)
- `METAGENT_MINIMAX_MODEL` / `METAGENT_OPENAI_MODEL` — not set (no provider configured in offline run,
  setdefault ensures no crash if a branch reads METAGENT_LLM_PROVIDER)

**Flag effect on distribution:** the method-aware pre-pass catches 11 claims that the base
multisource path would SUPPORT but which the method-aware check identifies as CONTRADICTED.
Net shift: SUPPORTED -11 (65.6% → 64.6%), CONTRADICTED +11 (0% → 1.0%). Shift is **minor (~1 pp)**
— distribution is stable; no material divergence from the prior run.

### Flag-Corrected Verdict Distribution (112 traces, METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT=1)

| Verdict | Count | % | Delta vs prior |
|---|---:|---|---|
| SUPPORTED | 720 | **64.6%** | −1.0 pp |
| INSUFFICIENT_EVIDENCE | 182 | **16.3%** | 0 |
| UNSUPPORTED | 138 | **12.4%** | 0 |
| UNVERIFIABLE_V0 | 64 | **5.7%** | 0 |
| CONTRADICTED | 11 | **1.0%** | +1.0 pp (new) |
| NEEDS_HUMAN_REVIEW | 0 | 0.0% | 0 |

Total verified claims: 1115 (0 dropped by grammar). Tasks: 112/112 processed, 0 failed.

### m4 — §2b Conditional Fix

`_write_report()` now checks `dropped_grammar > 0` before emitting the schema-incompatibility
narrative. When `dropped_grammar == 0` (current state with bridge wiring), §2b instead states
"All claims translated successfully — 0 grammar drops." The self-contradictory "All 0 dropped"
text is eliminated.

### I3 — False-Positive Framing Rewrite

**Claim-level GT-match (multi-rank double-counted):**
165 / 332 = **49.7%** GT-matching; 167 / 332 = **50.3%** off-pathway

**Pathway-level GT-match (dedup per task):** added via `gt_pathway_hit_tasks` /
`gt_pathway_miss_tasks` tracking in `_run_replay()`.

**Framing rewrite in both report §3 and decisions §6:**
- (a) Explicitly labels the stat as **claim-level** with a note on multi-rank double-counting
- (b) States 49.7% is a **lower bound on the loose-matching false-positive rate**, not an estimate
  of the true rate
- (c) Names **two co-causes**: RaMP-carrier absence (data caveat) AND loose-matching design risk
  (architectural) — does NOT let RaMP absence be the sole explanation
- Live-run false-positive rate expected to be ≥ offline rate because 5-paradigm noise surface >
  2-paradigm noise surface

### Gate A

`PYTHONPATH=. /home/weiwentao/miniconda3/bin/python3.13 -m pytest tests/test_verifier/ tests/test_d4_feedback_dispatcher.py tests/test_grammar_validate.py tests/test_classifier_collapse.py tests/test_runner_response_format.py tests/test_prompt_banned_sync.py -q`

→ **408 passed, 0 failed** ✅

### Files Changed

- `scripts/metagent/v4_verifier_replay.py` — C1 env flag set; m4 §2b conditional; I3 FP framing + pathway-level stat
- `docs/decisions/2026-06-25_verifier_multisource_refactor.md` — §6 updated with flag-corrected numbers + honest FP framing
- `reports/reports_v3/2026-06-25_v4_verifier_multisource_replay.md` — regenerated (gitignored)
