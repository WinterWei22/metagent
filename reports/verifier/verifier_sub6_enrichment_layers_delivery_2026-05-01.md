# Verifier Sub-6 Enrichment Layers — Delivery Report

- **Date:** 2026-05-01
- **Session ID:** `track_verifier_sub6_enrichment_layers`
- **Branch:** `feature/verifier-enrichment-layers`
- **Predecessors:**
  - `reports/verifier_typed_claim_stage2_confidence_2026-04-28.md` — typed-claim flow this layer set extends
  - `reports/benchmark/sub6_construction_report.md` — Sub-6 task data this layer set consumes
  - `reports/benchmark/sub6_evaluation_guide.md` — verdict / metric conventions used here
- **Status:** ✅ All 8 deliverables shipped, **228 / 228** verifier tests passing, real-data smoke clean across 3 sub6b tasks.

---

## 1. Executive summary

Three new claim types and four new verifier layers extend the existing
A–F cascade so a Sub-6 enrichment narrative can be checked end-to-end:

```
ClaimType.SET_ENRICHMENT       → verifier/layers/set_enrichment.py        (Layer 6a)
ClaimType.DRIVER_METABOLITE    → verifier/layers/driver_metabolite.py     (Layer 6b)
ClaimType.PATHWAY_RELATIONSHIP → verifier/layers/pathway_relationship.py  (Layer 6d)
ClaimType.BIOLOGICAL (Sub-6)   → verifier/layers/biological_sub6.py       (Layer 6c, Q1(b) routing)
```

Dispatch is via a new `verifier.agent.verify_sub6()` entry point that
consumes a parallel `schemas.sub6_report.SubsixSourceReport` (no
`IdentificationReport` references in any new code). The original
`verify()` cascade and Layer A–F implementations are untouched (additive
contract — see §6).

The session also exposed and fixed one real-data bug not visible to
unit tests (RD-001 — pathway-name regex missed disease/condition
pathways like "Alkaptonuria"; details §5).

---

## 2. Deliverables status

| # | Brief deliverable | Files | Status |
|---|---|---|---|
| **D1** | Schema additions (additive only) | `verifier/schemas.py`; `schemas/sub6_report.py` (new) | ✅ |
| **D2** | Layer 6a SET_ENRICHMENT | `verifier/layers/set_enrichment.py` (new) | ✅ |
| **D3** | Layer 6b DRIVER_METABOLITE | `verifier/layers/driver_metabolite.py` (new) | ✅ |
| **D4** | Layer 6d PATHWAY_RELATIONSHIP | `verifier/layers/pathway_relationship.py` (new) | ✅ |
| **D5** | 6c BIOLOGICAL_SIGNIFICANCE routing (Q1(b) — Sub-6 friendly) | `verifier/layers/biological_sub6.py` (new) | ✅ |
| **D6** | Claim extraction & classification updates | `verifier/claim_classifier.py`; `verifier/prompts/{extract,classify_ambiguous}.py` | ✅ |
| **D7** | Agent dispatcher update — Q4(b) independent entry point | `verifier/agent.py` (new `verify_sub6()` + `_verify_per_claim_sub6()`) | ✅ |
| **D8** | Tests (per-layer unit + dispatcher integration) | `tests/test_verifier/test_layer_set_enrichment.py`; `_driver_metabolite.py`; `_pathway_relationship.py`; `_sub6_dispatcher_integration.py` | ✅ |

---

## 3. Schema additions (D1)

`verifier/schemas.py`:

* `ClaimType` — three new values: `SET_ENRICHMENT`, `DRIVER_METABOLITE`, `PATHWAY_RELATIONSHIP`. Existing values unchanged.
* `ClaimSubtype` — six new values: `ENRICHMENT_PATHWAY`, `DRIVER_LIST`, `PATHWAY_UPSTREAM`, `PATHWAY_DOWNSTREAM`, `PATHWAY_CROSS_TALK`, `PATHWAY_SHARED_INTERMEDIATES`.
* New `PathwayMatch` model — structured echo of a `top_pathways[i]` record (id / name / source / rank / fdr / fold_enrichment / matched_compounds / total_pathway_compounds).
* New `EnrichmentContext` model — typed evidence carrier consumed by 6a / 6b / 6d. `extra="forbid"`. Slots:
  - 6a fields: `claimed_pathway`, `claimed_pathway_id`, `matched_top_pathways: list[PathwayMatch]`, `best_match`, `pathway_match_method` (`exact` / `substring_either` / `id` / `none`).
  - 6b fields: `claimed_drivers`, `claimed_drivers_resolved`, `matched_signal_drivers`, `matched_noise_drivers`, `unresolved_drivers`, `off_pool_drivers`, `driver_precision`, `driver_recall`.
  - 6d fields: `pathway_a`, `pathway_b`, `pathway_a_id`, `pathway_b_id`, `relationship_type`, `shared_compound_count`, `shared_compounds: list[str]`, `hierarchy_data_available`.
  - Generic: `tool_evidence: dict[str, Any]`.
* `VerifiedClaim.enrichment_context: EnrichmentContext | None = None` — populated by 6a/6b/6c/6d, None for all other layers.

`schemas/sub6_report.py` (new):

* `SubsixSourceReport` (pydantic BaseModel, `protected_namespaces=()`).
* Fields verbatim from `data/benchmark/sub6/*.jsonl` plus an optional `compound_lookup: dict[str, str] | None` for runner-side preloading of the curated pool.

**Q3 follow-up:** typed `EnrichmentContext` is additive — no other layer or downstream consumer (claim_table, metrics, rewriter, UI) reads the field. 191 / 191 pre-existing verifier tests confirm zero regression.

---

## 4. Per-layer behaviour (D2–D5)

### Layer 6a — SET_ENRICHMENT

| Verdict | Trigger |
|---|---|
| `SUPPORTED` | claimed pathway resolves to one of `top_pathways[:3]` by exact / substring / pathway-ID match |
| `UNSUPPORTED` | match in `top_pathways[3:10]` (weak evidence) |
| `CONTRADICTED` | no match in `top_pathways[:10]` — `correction` set to canonical top-1 pathway name |
| `UNVERIFIABLE_V0` | no pathway phrase / ID lifted from claim text **and** no canonical top-pathway name appears verbatim in claim, **or** `ramp_enrichment_result.top_pathways` empty/missing |

Pathway match methods: `id` (exact RAMP/KEGG/WP id), `exact` (normalised string equal), `substring_either` (claim ⊂ canonical OR canonical ⊂ claim, plus reverse-match for naked names like "Alkaptonuria").

### Layer 6b — DRIVER_METABOLITE

| Verdict | Trigger |
|---|---|
| `CONTRADICTED` | any claimed driver resolves to a compound in `ground_truth_noise_compounds` (false-driver hallucination) |
| `UNSUPPORTED` | claimed driver(s) resolve but land in neither signal nor noise (off-pool) |
| `SUPPORTED` | every resolved claimed driver is in `ground_truth_signal_compounds` |
| `UNVERIFIABLE_V0` | no driver names extractable, **or** every claimed name fails to resolve via the curated pool |

Resolution stack: typed `extracted_fields.candidate_name` → KEGG / HMDB / InChIKey-block regex → **lookup reverse substring match** (preferred; word-bounded, descending key length) → Title-Case / acronym fallback regex (so unresolvable tokens still surface in `unresolved_drivers` for audit).

Lookup load: lazy from `data/benchmark/sub6/curated_hmdb_mammalian.jsonl` on first call (~3.8 ms / 887 keys for 150 records). Cached at module level. `SubsixSourceReport.compound_lookup` short-circuits the load when populated.

### Layer 6d — PATHWAY_RELATIONSHIP

| Relationship | Verdict policy |
|---|---|
| `cross_talk` / `shared_intermediates` | RaMP `analytehaspathway` INTERSECT — count ≥ 2 → SUPPORTED, == 1 → UNSUPPORTED, == 0 → CONTRADICTED |
| `upstream` / `downstream` | always `UNVERIFIABLE_V0` (RaMP-DB v2025-03-06 has no `pathwayhaspathway` or analogue) — `enrichment_context.hierarchy_data_available=False` set explicitly |
| Pathway resolution failed for either A or B | `UNVERIFIABLE_V0` |
| RaMP DB unavailable | `UNVERIFIABLE_V0` |

Pathway-name resolution: regex phrase extraction → `pathway.pathwayName` lookup (NOCASE collation in RaMP) → reverse-match fallback (scan `pathway` table for canonical names appearing verbatim in claim text; word-bounded; normalised-name dedup so KEGG-vs-SMPDB same-name aggregations don't get split into A and B).

### Layer 6c — biological_sub6 (Q1(b) routing)

Decision: do NOT add a new `BIOLOGICAL_SIGNIFICANCE` ClaimType. 6c claims classify as `BIOLOGICAL`, but `verify_sub6` routes them to a Sub-6 friendly `verify_biological_sub6()` instead of the original `layers/biological.py` (which reads `source_report.candidates[*].pathway_context` and would crash on `SubsixSourceReport`).

| Verdict | Trigger |
|---|---|
| `UNVERIFIABLE_V0` | disease keyword detected in claim text (declared limitation: no curated disease-pathway DB in v0) |
| `SUPPORTED` | pathway phrase / ID matches `ground_truth_pathway` or `top_pathways[:10]`, OR resolves directly via RaMP when given an explicit ID |
| `UNSUPPORTED` | pathway named but absent from task context and from RaMP |
| `UNVERIFIABLE_V0` | no concrete pathway phrase / ID lifted from claim |

The disease keyword list (`disease|disorder|deficienc|syndrome|cancer|tumor|...|dysregulated|...`) is conservative; expanding it is the cleanest place to push v0 limits without touching the existing Layer C.

---

## 5. Real-data validation

After 228 / 228 unit tests passed, a real-data smoke (`scripts/spike/sub6_real_data_smoke.py`) ran each layer against the first three sub6b mammalian tasks plus the live RaMP-DB and curated mammalian pool. Initial run exposed one bug; fix verified by a second run.

### 5.1 Smoke configuration

| Layer | Real data source |
|---|---|
| 6a | `data/benchmark/sub6/sub6b_mammalian_tasks.jsonl[0:3]` |
| 6b | `data/benchmark/sub6/curated_hmdb_mammalian.jsonl` (150 records → 887 lookup keys, **3.8 ms** load) |
| 6d | `/data/weiwentao/llm_agent_metabolomics/ramp.sqlite` (~50 k pathways, ~3.7 M `analytehaspathway` rows; **60–215 ms** per shared-compound query) |
| 6c | sub6b tasks + same RaMP-DB |

### 5.2 Verdicts (post-fix)

| Task | 6a (correct/fake claim) | 6b (signal/signal+noise) | 6d (shared/upstream) | 6c (member/disease/unrelated) |
|---|---|---|---|---|
| RAMP_P_000000106 (Tyrosine metabolism) | SUPPORTED rank 1 / CONTRADICTED | SUPPORTED P=1.0 / CONTRADICTED noise=`RYYVLZVUVIJVGH` | **SUPPORTED, 79 shared** / UNVERIFIABLE_V0 | SUPPORTED / UNVERIFIABLE_V0 / UNSUPPORTED |
| RAMP_P_000052705 (Statin pathway) | SUPPORTED rank 1 / CONTRADICTED | SUPPORTED / CONTRADICTED noise=`ZOOGRGPOEVQQDX` | **SUPPORTED, 3 shared** / UNVERIFIABLE_V0 | SUPPORTED / UNVERIFIABLE_V0 / UNSUPPORTED |
| RAMP_P_000053157 (Selenium network) | SUPPORTED rank 2 / CONTRADICTED | SUPPORTED / CONTRADICTED noise=`OBQMLSFOUZUIOB` | UNVERIFIABLE_V0 (top-1 = top-2 same name) / UNVERIFIABLE_V0 | SUPPORTED / UNVERIFIABLE_V0 / UNSUPPORTED |

All verdicts match expectations.

### 5.3 RD-001 — `pathway_relationship` regex missed disease-named pathways

```
Issue ID: RD-001
Severity: MAJOR — task 1 returned UNVERIFIABLE_V0 instead of SUPPORTED
                  on a clearly verifiable cross-pathway claim
Tool: verifier/layers/pathway_relationship.py
Location: _PATHWAY_PHRASE_RE (line ≈ 75)
Description: regex required pathway names to end in metabolism /
             biosynthesis / cycle / etc. RaMP top_pathways[1] / [2] are
             frequently disease or condition names ("Alkaptonuria",
             "Statin inhibition of cholesterol production",
             "Selenium micronutrient network"). These were silently
             dropped, so any claim relating ground-truth pathway A to
             top_pathways[1] returned UNVERIFIABLE_V0 even when the two
             clearly share many compounds. Sub-6 evaluation guide §3
             pitfall 4 explicitly warns about this composition pattern.
Reproduction: scripts/spike/sub6_real_data_smoke.py task 1 (Tyrosine
              metabolism + Alkaptonuria) before fix.
Suggested fix: ADD a reverse-match fallback that scans
               ramp.pathway.pathwayName for canonical names appearing
               verbatim (word-bounded, NOCASE) in claim text. De-duplicate
               by normalised name so KEGG-vs-SMPDB same-name aggregations
               don't get split into A vs B.
Estimated fix time: 1 h (delivered in this session).
Blocks benchmark? Yes — without fix, all cross-pathway claims involving
                  a disease-named pathway are silently downgraded to
                  UNVERIFIABLE_V0.
```

**Fix delivered:** `_reverse_match_pathways` + `_word_bounded_in_text` helpers added to `verifier/layers/pathway_relationship.py`. Triggers only when regex extraction missed at least one pathway. After fix:

* task 1 → SUPPORTED, **shared_compound_count = 79** between Tyrosine metabolism (RAMP_P_000000106) and Alkaptonuria (RAMP_P_000000101).
* task 3 still UNVERIFIABLE_V0 because top-1 and top-2 have the **same canonical name** ("Selenium micronutrient network", aggregated from KEGG + SMPDB) — the new normalised-name dedup correctly refuses to treat the same pathway as both A and B.

---

## 6. Architectural decisions (carried over from session intake Q1–Q4)

| # | Decision | Why |
|---|---|---|
| **Q1(b)** | 6c claims classify as `BIOLOGICAL` but route to `biological_sub6.py` for Sub-6 source reports | Avoids a new ClaimType while honouring "MAY NOT modify existing layers" — original `layers/biological.py` keeps its `IdentificationReport`-only contract, Sub-6 gets a parallel layer with the same ClaimType |
| **Q2** | `SubsixSourceReport` is pydantic BaseModel, not @dataclass | Project consistency with `IdentificationReport`, `MetaboliteInfoResponse`, etc. — also serialises cleanly through claim tables |
| **Q3** | `EnrichmentContext` is typed (`extra="forbid"`), not `dict | None` | Self-documenting for downstream UI / metrics; verified additive (191 / 191 pre-existing tests pass unchanged) |
| **Q4(b)** | New `verify_sub6()` entry, not `verify()` overload | Sub-6 cascade has different stage budget (no Stage 4 rewriter in v0) and different layer surface; mixing branches in one entry point would have made the 7-call budget logic fragile |

---

## 7. Test inventory

```
$ conda run -n metagent-llm python -m pytest tests/test_verifier/ -q
228 passed in 0.66s
```

| File | Passed | Δ vs predecessor |
|---|---:|---:|
| existing 14 layer / cascade / extraction / metrics test files | 191 | 0 (no regression) |
| `test_layer_set_enrichment.py` (new) | 10 | +10 |
| `test_layer_driver_metabolite.py` (new) | 12 | +12 |
| `test_layer_pathway_relationship.py` (new) | 11 | +11 |
| `test_sub6_dispatcher_integration.py` (new) | 4 | +4 |
| **Total** | **228** | **+37** |

Real-data smoke (not in CI): `scripts/spike/sub6_real_data_smoke.py` — environment-dependent (RaMP path) so kept out of the unit test suite. Should be promoted to a `pytest.mark.requires_ramp` integration test once the suite gains a marker policy.

---

## 8. Known limitations / gaps for the next session

1. **Real-data smoke covers 3 sub6b tasks, not 20.** Brief explicitly forbids full evaluation in this session, but corner cases beyond task 3 are unverified. The Sub-6 evaluation runner should re-invoke `verify_sub6()` against all 20 + 14 tasks and stratify verdicts.
2. **Reverse-match disambiguation.** When multiple RaMP pathways' canonical names all appear in a claim, `_reverse_match_pathways` picks by descending name length. Reasonable heuristic, but a claim like "glucose homeostasis and glucose metabolism are linked" would be ambiguous. Not exercised by current test data.
3. **Disease-keyword guard is conservative.** Catches obvious clinical phrasing but a claim like "Tyrosine metabolism plays a role in melanin production in vivo" (no disease word) would route to membership — correct enough for v0, but a future curated-disease lookup would let 6c return real verdicts on these claims.
4. **`compound_lookup` precomputation in benchmark runner.** Field is supported on `SubsixSourceReport` and tests cover the inject path, but the benchmark runner side that actually populates it has not been written (out of scope for this session).
5. **Sub-6 rewriter (Stage 4) intentionally skipped.** `verify_sub6()` sets `claims_v2 = claims_v1` and `rewritten_output = source_llm_output`. The existing rewriter is tuned for spectrum-centric corrections and would emit malformed enrichment narratives. A Sub-6 rewriter prompt is a separate session.
6. **Claim extractor not run on real LLM output.** Stage 1 prompt was updated with enrichment few-shots, but tested only against rule-classified mocks (D8) and synthesised narratives. Real LLM-driven claim extraction will surface phrasing the rule classifier misses → expected to push some claims through the LLM Stage 2 fallback (single batched call).

---

## 9. File manifest

**New (8 files):**

```
schemas/sub6_report.py
verifier/layers/set_enrichment.py
verifier/layers/driver_metabolite.py
verifier/layers/pathway_relationship.py
verifier/layers/biological_sub6.py
tests/test_verifier/test_layer_set_enrichment.py
tests/test_verifier/test_layer_driver_metabolite.py
tests/test_verifier/test_layer_pathway_relationship.py
tests/test_verifier/test_sub6_dispatcher_integration.py
scripts/spike/sub6_real_data_smoke.py
```

**Modified (additive only, 5 files):**

```
verifier/schemas.py                      # +ClaimType / +ClaimSubtype / +PathwayMatch / +EnrichmentContext / +VerifiedClaim.enrichment_context
verifier/agent.py                        # +verify_sub6 / +_verify_per_claim_sub6 / +SubsixSourceReport import
verifier/claim_classifier.py             # +3 enrichment regex / +rule order / +TYPE_LITERALS aliases
verifier/prompts/extract_claims.py       # +5 enrichment few-shot examples
verifier/prompts/classify_ambiguous.py   # +7 enrichment classification examples + type descriptions
```

No file under `verifier/layers/{biological,consistency,factual,grounded,literature,peak_mechanistic}.py` was modified. No file under `schemas/` other than the new `sub6_report.py` was modified.

---

## 10. Reproduction recipe

```bash
cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5
git checkout feature/verifier-enrichment-layers   # branch tip after this session

# Unit + integration suite (network-free, ~0.7 s)
conda run -n metagent-llm python -m pytest tests/test_verifier/ -q

# Real-data smoke (requires RaMP-DB + curated pool; ~1 s total)
METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \
  conda run -n metagent-llm python scripts/spike/sub6_real_data_smoke.py
```

---

## 11. Acceptance sign-off

| Criterion | Status |
|---|---|
| All 4 claim types correctly classified by `verifier.claim_classifier` on sample text | ✅ rule-based hits via `_SET_ENRICHMENT_RE` / `_DRIVER_RE` / `_RELATIONSHIP_RE`, plus LLM fallback few-shots in `classify_ambiguous.py` |
| All 4 layers produce verdicts on real Sub-6 task data | ✅ `test_verify_sub6_routes_all_four_claim_types` uses real `sub6b_mammalian_tasks.jsonl[0]`; smoke covers 3 tasks across 4 layers + real RaMP + real curated pool |
| All existing verifier tests still pass (no regression on Layer A–F) | ✅ 191 / 191 |
| Integration test on Sub-6 narrative produces verdicts for all claim types | ✅ `test_sub6_dispatcher_integration.py` |
| No `IdentificationReport` references in new layers | ✅ verified — every new `verifier/layers/*sub6*.py` and `set_enrichment.py` / `driver_metabolite.py` / `pathway_relationship.py` consume `SubsixSourceReport` only |
| Layer 6d documents whether RaMP has hierarchy data and behaves accordingly | ✅ `EnrichmentContext.hierarchy_data_available=False` set explicitly; upstream / downstream claims always `UNVERIFIABLE_V0`; module docstring + verdict policy reference RaMP v2025-03-06 snapshot |

**Track Verifier-Sub6 — done.** Next session can pick up `compound_lookup` precomputation in the Sub-6 evaluation runner and start scoring real LLM narratives against this layer set.
