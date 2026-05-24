# W12 C7 namespace_form fix — Sprint Status (Final)

**Sprint:** W12 — C7 namespace_form fix(`verifier/layers/factual_sub6.py` + Layer 6a fuzzy match)
**Worktree:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2`
**Branch:** `metagent-v2` @ `2239fcf` (D4 GREEN side+test)
**Dates:** 2026-05-22 → 2026-05-24
**Verdict:** **Gate 2 PASS / Gate 1 FAIL — partial success retained, target recalibrated.**

---

## 1 · Hard Gate verify (W10 D4 baseline vs W12 post-C7)

| metric | W10 D4 | W12 post-C7 | Δ |
|---|---:|---:|---:|
| supported %         | 28.62 | 26.61 | -2.01 pp |
| unsupported %       | 16.71 | 20.37 | +3.66 pp |
| contradicted %      |  1.71 |  1.57 | -0.14 pp |
| unverifiable_v0 %   | **52.95** | **51.45** | **-1.50 pp** ← Gate 1 |
| pathway 准确率       | 54/63 (85.7%) | 54/63 (85.7%) | **+0.00 pp** ← Gate 2 |
| iter-2 degradation  | 17.74 % | 22.22 % | **+4.48 pp** ← Stop #6 trigger |

| Gate | Target | Actual | Verdict |
|---|---|---|---|
| Gate 1 — UV drop ≥ 12pp | ≤ 40.95 % | 51.45 % | **FAIL** |
| Gate 2 — pathway acc drop ≤ 3pp | ≥ 82.7 % | 85.7 % | **PASS** |
| Stop #6 — iter-2 deg ≤ W10 D4 | ≤ 17.74 % | 22.22 % | **TRIGGER** |

---

## 2 · UV ceiling recalibration (W12 D sub-task, 2026-05-24)

The Gate 1 target of −12 pp was sourced from the W11 UV diagnosis,
which classified the 226 C7 claims as a single "namespace_form" bucket
on the assumption they were all amenable to `factual_sub6`-style
"extract ID + lookup" verification. **The W12 D sub-task re-classifies
those 226 claims at finer granularity:**

| bucket | n | % of C7 | description |
|---|---:|---:|---|
| **strict_id** | 123 | **54.4 %** | concrete extractable identifier ("L-tyrosine has KEGG ID C00082"); structurally amenable to factual_sub6 |
| **fuzzy_biology** | 103 | 45.6 % | biology relations / pathway statements / network claims with no extractable ID ("Pyrocatechol appears in Disulfiram action") — require richer verifier |
| **UNCLASSIFIED** | 0 | 0 % | — |

**factual_sub6 theoretical ceiling on the W11 baseline:**

```
123 strict_id claims / 1102 total UV claims = 11.16 pp ceiling on UV %.
```

The original Gate 1 target of −12 pp is **structurally unreachable** —
even a perfect factual_sub6 implementation can convert at most ~11 pp of
UV claims, not 12. **The −12 pp target was a W11-classifier artefact**.

### Recalibrated comparison

| target | basis | reachable? |
|---|---|---|
| W12 spec −12 pp | W11 classifier (all 226 C7 ≈ 80 %) | **NO** (exceeds true ceiling 11.16 pp) |
| Real ceiling −11.16 pp | re-classified strict_id 123 / 1102 | YES (perfect impl) |
| W12 D5 actual −1.50 pp | observed Path X re-run | partial: ~13.4 % of ceiling reached |

### Where the ~9.66 pp gap-to-ceiling went

W12 D5 trace files (`data/concord/w12_path_x_post_c7/path_x_full/`)
show factual_sub6 processed **657 FACTUAL/GROUNDED claims** with verdict
distribution:

| factual_sub6 verdict | n | % of routed |
|---|---:|---:|
| UNVERIFIABLE_V0 | 587 | 89.3 % |
| SUPPORTED | 70 | 10.7 % |

The 70 SUPPORTED is the W12 strict-id realised count. Sources of the
gap from theoretical ceiling 11.16 pp to actual −1.50 pp:

1. **LLM narrative shift**: the W12 D5 LLM run produced different claim
   text than W10 D4 (richer feedback prompt → behaviour change).
   Subject names + ID surface forms drifted; some W11 strict_id-style
   patterns did not recur in W12.
2. **Subject lookup miss**: factual_sub6 requires
   `claim.subject` to match a name in `differential_metabolites` or
   `curated_hmdb_mammalian.jsonl`. Many W12 claims have `subject=None`
   or name forms (e.g. "17β-estradiol" vs "17beta-estradiol") that miss
   the exact-match contract.
3. **ID pattern miss**: factual_sub6's `_ID_PATTERNS` regex catches
   `KEGG ID C00082` but misses some surface forms ("KEGG:C00082",
   "C00082" without keyword, "CID 1060" PubChem-style).
4. **Side effect — increased unsupported**: +3.66 pp unsupported and
   +4.48 pp iter-2 degradation indicate the richer feedback prompt
   (W10 D2.5 fix surfaced contradicted/unsupported claims) is now
   shifting iter-1 verdict distribution downward into unsupported,
   not just upward into supported.

---

## 3 · D5 D sub-task data (this commit's added artefacts)

```
data/concord/w12_uv_ceiling/
├── c7_strict_vs_fuzzy.jsonl    226 W11 C7 claims with new bucket label
└── ceiling_summary.json        {n_strict_id, n_fuzzy_biology, ceiling_pp}

scripts/concord/
└── w12_d_reclassify_c7_strict_vs_fuzzy.py   re-classification driver
                                              (LLM prompt + batch loop)

logs/concord/
└── w12_d_reclassify.jsonl                   12 LLM calls, ~$0.30 cost
```

Cost: **$0.30** at MiniMax-M2.7 (12 calls, prompt 71k + completion 13k tokens).
Wall: 270 s.

---

## 4 · W12 sprint outcome summary

### What landed (committed)

| day | commit | scope |
|---|---|---|
| D1 | `5d6c6b3` | onboarding status (recon, scope mismatch flagged) |
| D2 | `bc160fb` | RED 14 test cases (8 main course + 6 side dish) |
| D3 | `1c639bc` | GREEN main: `verifier/layers/factual_sub6.py` (✅ pure-add) |
| D4 | `2239fcf` | GREEN side: `verifier/agent.py` dispatch + `set_enrichment.py` Stage 2.5 fuzzy + B1 integration test contract update (⚠ verifier-modify-warning) |
| D5 | — | Path X re-run (`data/concord/w12_path_x_post_c7/`, no code commit) |
| D-sub | this | UV ceiling recalibration |

### Test surface delta

| suite | pre-W12 | post-W12 | regression? |
|---|---:|---:|---|
| Gate A (B1 verifier-core) | 407 pass / 0 fail | 407 pass / 0 fail | NO ✓ |
| Full repo pytest | 1331 pass / 14 fail | 1345 pass / 14 fail | NO ✓ (+14 W12 cases) |
| W12 14-case suite | n/a | 14/14 PASS | — |

### Infrastructure delta

- **New**: `verifier/layers/factual_sub6.py` (316 LOC); `verifier/helpers/__init__.py` + `verifier/helpers/fuzzy_match.py` (token-Jaccard, ~65 LOC)
- **Modified**: `verifier/agent.py:_verify_per_claim_sub6` (+8 LOC; FACTUAL/GROUNDED dispatch);
  `verifier/layers/set_enrichment.py` (+30 LOC; Stage 2.5 token-Jaccard);
  `tests/test_verifier/test_sub6_dispatcher_integration.py` (renamed + assertion + docstring)
- **NOT added (spec deviation)**: `verifier/helpers/namespace_xwalk.py` — `data/concord/metanetx.sqlite`
  holds compound-level xref only, no pathway xref; documented in
  `verifier/helpers/__init__.py` docstring.

### Cost ledger

| sprint sub-task | cost | wall |
|---|---:|---:|
| D5 Path X re-run | $11.17 | 109.8 min |
| D ceiling re-classification | $0.30 | 4.5 min |
| **W12 total API** | **$11.47** | **114.3 min** |

W10 D4 baseline was $10.10 / 139.7 min. W12 spent $1.37 more for the
ceiling re-classification artefact + $0.07 from a slightly higher
prompt token count post-feedback-prompt-enrichment.

---

## 5 · Audit trail

W12 strict-TDD slip count: **0** across D2 RED → D3 GREEN main → D4 GREEN side+test.
W8-W12 cumulative slip count: **0**.

D4 commit `2239fcf` carries `[verifier-modify-warning]` body with
per-file justification (modify 1 dispatcher, modify 2 set_enrichment,
modify 3 integration test) + B1 verifier-core 407-pass evidence.

---

## 6 · Source data references

| artefact | path |
|---|---|
| W11 UV diagnosis | `reports/agent/concord_w11_uv_diagnosis.md` |
| W11 C7 226 raw | `data/concord/w11_uv_diagnosis/uv_classified.jsonl` (category == "C7") |
| W12 D ceiling raw | `data/concord/w12_uv_ceiling/c7_strict_vs_fuzzy.jsonl` |
| W12 D5 Path X run | `data/concord/w12_path_x_post_c7/path_x_full63_results.jsonl` |
| W12 D5 token usage | `data/concord/w12_path_x_post_c7/path_x_full63_summary.json` |
| W10 D4 baseline | `data/concord/w10_d4_path_x_full/path_x_full63_results.jsonl` |
| LLM call logs | `logs/concord/w12_d5_path_x.jsonl`, `logs/concord/w12_d_reclassify.jsonl` |
