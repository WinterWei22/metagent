# Layer F cross-validation — NM-001 mitigation validation

- **Date:** 2026-04-28
- **Branch:** `feature/layer-f-cross-validation` (built from `feature/massbank-data-pipeline` tip `0e1d039`)
- **Predecessors:**
  - `reports/spike/negative_mode_spike_2026-04-28.md` §2.8 (the failure
    mode this report validates the fix for)
  - `reports/acceptance/acceptance_negative_mode_2026-04-28.md` (Tracks
    A/B/C accepted on glucose `[M-H]-`)
- **Conclusion:** ✅ **Layer F now cross-validates SIRIUS against CFM-ID.
  The NM-001 cascade is mitigated**: SIRIUS' wrong-formula prediction
  for citric acid `C4H6N3O6` is detected by the sanity check, downgraded
  to `LOW_CONFIDENCE`, and CFM-ID drives the consensus. The cascading
  false-SUPPORTED on 191.0190 (precursor) verdict from spike §2.8 is
  eliminated.

---

## 1. Summary of changes

| Surface | Change | Files |
|---|---|---|
| Schema | New `ClaimVerdict.NEEDS_HUMAN_REVIEW`; new optional `VerifiedClaim.tool_evidence` field | `verifier/schemas.py` |
| Layer F | Adds CFM-ID arm + 25-cell consensus table + SIRIUS sanity check | `verifier/layers/peak_mechanistic.py` |
| Verifier agent | Plumbs `cfmid_fn` through `verify()` → `_verify_per_claim()`; `_aggregate_verdict()` maps `NEEDS_HUMAN_REVIEW` → `partially_verified` | `verifier/agent.py` |
| Tests | 11 new unit tests + 2 integration tests; all 10 pre-existing tests preserved unchanged | `tests/test_verifier/test_layer_peak_mechanistic.py`, `tests/integration/test_layer_f_cross_validation.py` |
| Spike | New scripted validation comparing pre-fix and post-fix verdicts on the same fixture, using a SIRIUS mock that replays spike §2.4 behaviour | `scripts/spike/test_layer_f_nm001_fix.py` |

No backward-incompatible API changes. The `cfmid_fn` parameter is
optional with default `None` (auto-load), matching the `sirius_fn`
pattern.

---

## 2. Cross-validation logic

The new layer treats SIRIUS and CFM-ID as two **independent voters**
on every peak claim. Each tool produces a `ToolResult` value:

- `MATCHES` — tool's evidence supports the claim
- `MISMATCHES` — tool found relevant evidence but it conflicts (e.g.
  SIRIUS assigned a different neutral loss; CFM-ID's precursor−fragment
  delta does not equal the claimed NL mass)
- `NOT_FOUND` — tool ran but found no evidence at the claimed m/z
- `NO_DATA` — tool unavailable / raised before producing output
- `LOW_CONFIDENCE` — tool ran but produced internally-inconsistent
  output (currently SIRIUS-only: NM-001 sanity-check failure)

The 25-cell consensus table NEVER silently arbitrates when two
queryable tools disagree. Disagreements between `MATCHES` and
`MISMATCHES`/`NOT_FOUND` (in either direction) escalate to
`NEEDS_HUMAN_REVIEW`. Agreement on either polarity produces the
expected `SUPPORTED` / `CONTRADICTED` / `UNSUPPORTED`.

### NM-001 mitigation: SIRIUS sanity check

Before consulting SIRIUS' fragmentation tree, Layer F compares
SIRIUS' top predicted formula against the candidate's molecular
formula (computed from SMILES via RDKit `CalcMolFormula`, or taken
from `prefilter_match.molecular_formula` when available).

If any single element differs by more than **2 atoms** in either
direction, SIRIUS is downgraded to `LOW_CONFIDENCE`. For citric acid
in the spike fixture, SIRIUS predicted `C4H6N3O6` vs the truth
`C6H8O7` — element diff `{C: -2, H: -2, N: +3, O: -1}`. The N
difference of 3 exceeds the threshold and triggers the downgrade.

The threshold of 2 is permissive enough to tolerate small isobaric
drift (e.g. methylation-degree differences) but tight enough to catch
the nitrogen-laden hallucinations seen in the spike.

### CFM-ID arm

For each peak claim:
1. Retrieve the top candidate's SMILES + adduct from the source
   report.
2. Look up `(canonical_smiles, adduct)` in a process-wide cache; on
   miss, call `predict_spectrum`.
3. Match the claim's m/z against `resp.predicted.mz` within 10 ppm
   (wider than SIRIUS' 5 ppm to absorb CFM-ID's known prediction
   noise on negative mode — see NM-007).
4. If a neutral loss is claimed, parse it (with a new monoisotopic-
   mass fallback for arbitrary chemical formulas like `C2H2O5` that
   are not in `COMMON_NEUTRAL_LOSSES`) and verify that the
   `(precursor_mz − fragment_mz)` delta agrees within ±0.02 Da.
5. All exceptions (Docker down, RDKit invalid SMILES, timeout) are
   caught and produce `NO_DATA` so cross-validation degrades
   gracefully to single-tool behaviour.

The cache survives for the lifetime of the process. Many peak claims
on the same spectrum share the same `(SMILES, adduct)` — a single
CFM-ID call (~5–10 s wall) typically serves dozens of claims.

---

## 3. Validation against the spike §2.8 cascade

`scripts/spike/test_layer_f_nm001_fix.py` re-runs the four §2.8
claims with the new layer, using a **SIRIUS mock** that replays the
spike's observed behaviour (predicted_formula `C4H6N3O6`, fragment
annotations as documented in §2.8). CFM-ID is the **live Docker shim**
running on `localhost:8088`.

The SIRIUS mock is necessary because the live SIRIUS CLI in this
environment requires re-authentication (the original spike's session
token has expired since 2026-04-28). The mock is byte-faithful to
spike §2.4's outputs.

### Verdict comparison

| Claim | Pre-fix verdict (spike §2.8) | Post-fix verdict | Consensus label | Status |
|---|---|---|---|---|
| m/z 87.0086 with NL `C2H2O5` | CONTRADICTED (SIRIUS says loss is `HN3`) | **CONTRADICTED** (CFM-ID found peak at 87.00877 but precursor−fragment delta `104.01` Da disagrees with claimed `C2H2O5` mass `105.99` Da) | `cfmid_drives_low_confidence_sirius` | ✅ Same verdict, correct reason |
| m/z 111.0085 with NL `H2O` | CONTRADICTED (SIRIUS says loss is `CH4O4`) | **UNSUPPORTED** (CFM-ID has no peak at 111.0085 within 10 ppm) | `cfmid_drives_low_confidence_sirius` | ✅ More accurate verdict — the LLM's fragment-existence claim is unsupported, but not contradicted by independent evidence |
| m/z 191.0190 (precursor itself) | **SUPPORTED** (SIRIUS confirms — but with wrong formula `C4H6N3O6`) | **UNSUPPORTED** (CFM-ID has no peak at 191.0190 in its 5-peak prediction; SIRIUS unreliable) | `cfmid_drives_low_confidence_sirius` | ✅ **NM-001 fix landed**: false-SUPPORTED eliminated |
| m/z 200.0000 phantom peak with NL `CO2` | CONTRADICTED (peak absent from spectrum) | **CONTRADICTED** (peak absent from spectrum, early return — never reaches SIRIUS / CFM-ID) | n/a (early return) | ✅ Behaviour unchanged |

### The headline result

The 191.0190 row is the load-bearing one. Pre-fix, Layer F trusted
SIRIUS' fragment-tree match at the precursor m/z and returned
SUPPORTED, despite SIRIUS having locked onto the wrong precursor
formula. Post-fix, the sanity check rejects SIRIUS as
`LOW_CONFIDENCE`, the consensus defers to CFM-ID, CFM-ID's prediction
(built on the *correct* candidate SMILES) does not include 191.0190
within 10 ppm, and the verdict becomes UNSUPPORTED.

This matches the brief's design goal: *eliminate downstream trust
in SIRIUS' wrong-formula cascade without requiring SIRIUS to detect
its own errors*.

### Note on the 87.0086 verdict

Pre-fix and post-fix both produce `CONTRADICTED`, but for entirely
different reasons:

- Pre-fix: Layer F asked SIRIUS what the neutral loss was, SIRIUS said
  `HN3` (built on the wrong precursor `C4H6N3O6`), `HN3` ≠ `C2H2O5`
  → CONTRADICTED. The contradiction is correct by accident — SIRIUS'
  hallucinated `HN3` happened not to match the claim.
- Post-fix: SIRIUS is downgraded; CFM-ID independently finds a peak
  at 87.00877 (good evidence the m/z is real) but the
  precursor−fragment delta (`104.01` Da) disagrees with the claimed
  `C2H2O5` mass (`105.99` Da) by ~2 Da, far outside the ±0.02 Da
  tolerance → CONTRADICTED.

Same verdict, but the post-fix reason is independently reproducible
and does not depend on SIRIUS' (wrong) interpretation.

---

## 4. Test coverage

### 4.1 Unit tests (run by default)

```
$ conda run -n metagent-llm pytest tests/test_verifier/test_layer_peak_mechanistic.py -q
.....................                                                    [100%]
21 passed in 0.22s
```

| Group | Count | Notes |
|---|---:|---|
| Pre-existing tests preserved | 10 | All still pass; semantics unchanged when CFM-ID is unavailable (auto-NO_DATA in the unit-test fixture) |
| New cross-validation tests | 11 | Cover: agree-supported, agree-contradicted, tools-disagree (both directions), single-tool fallback (both directions), neither-available, NM-001 sanity catch, sanity passes, tool_evidence populated, backward-compat |
| Total | 21 | |

### 4.2 Verifier suite (run by default)

```
$ conda run -n metagent-llm pytest tests/test_verifier/ -q
........................................................................ [ 37%]
........................................................................ [ 75%]
...............................................                          [100%]
191 passed in 0.70s
```

The cross-cutting metrics, agent cascade, rewriter, and downstream
layers are all unaffected.

### 4.3 Integration tests (skipped by default)

```
tests/integration/test_layer_f_cross_validation.py::TestLayerFCrossValidationReal::test_citric_acid_nm001_mitigation
tests/integration/test_layer_f_cross_validation.py::TestLayerFCrossValidationReal::test_glutamyltyrosine_supported_unchanged
```

Marked `@pytest.mark.requires_cfm_id`. Run with `pytest --integration`
when SIRIUS is logged in and the CFM-ID Docker shim is reachable.

The first asserts SIRIUS' sanity check fails on citric acid (NM-001
in vivo); the second asserts that SIRIUS gets glutamyltyrosine right
and the verdict remains SUPPORTED (control).

---

## 5. What "no silent arbitration" looks like in practice

Before this work, Layer F's behaviour on tools-disagree was
implicitly *trust SIRIUS* (because CFM-ID was never consulted).

After this work, the consensus table is **exhaustive over 25 cells**
and disagreements between two queryable tools always escalate to
`NEEDS_HUMAN_REVIEW`:

| SIRIUS \\ CFM-ID | MATCHES | MISMATCHES | NOT_FOUND | NO_DATA | LOW_CONFIDENCE |
|---|---|---|---|---|---|
| MATCHES | SUPPORTED | NEEDS_HR | NEEDS_HR | SUPPORTED (sirius_only) | SUPPORTED |
| MISMATCHES | NEEDS_HR | CONTRADICTED | CONTRADICTED | CONTRADICTED (sirius_only) | CONTRADICTED |
| NOT_FOUND | NEEDS_HR | CONTRADICTED | UNSUPPORTED | UNSUPPORTED (sirius_only) | NEEDS_HR |
| NO_DATA | SUPPORTED (cfmid_only) | CONTRADICTED (cfmid_only) | UNSUPPORTED (cfmid_only) | UNVERIFIABLE_V0 | NEEDS_HR |
| LOW_CONFIDENCE | SUPPORTED (cfmid drives) | CONTRADICTED (cfmid drives) | UNSUPPORTED (cfmid drives) | NEEDS_HR | NEEDS_HR |

Agreement-on-yes → SUPPORTED; agreement-on-no → CONTRADICTED;
agreement-on-absence → UNSUPPORTED; both sides unreliable →
NEEDS_HUMAN_REVIEW. No cell silently picks a winner between
positively-conflicting tools.

`NEEDS_HUMAN_REVIEW` aggregates to `partially_verified` at the
top-level `VerifiedIdentification.overall_verdict` (matching the
existing handling of `UNSUPPORTED` / `UNVERIFIABLE_V0`). It is *not*
treated as a CONTRADICTED — that distinction matters for downstream
metrics and rewrite triggering.

---

## 6. Implications for downstream work

| Downstream consumer | Impact | Action required |
|---|---|---|
| Sub-3 evaluation | New verdict `NEEDS_HUMAN_REVIEW` should be a first-class bucket (not silently filtered, not counted as CONTRADICTED) | Treat as a separate row in metrics tables; document in evaluation README |
| Rewriter (Stage 4) | `NEEDS_HUMAN_REVIEW` is intentionally NOT in `_ACTIONABLE` — the rewriter cannot meaningfully fix a tools-disagree claim | None; current behaviour is correct |
| Benchmark protocol v3 | Negative-mode subsets that fall into `NEEDS_HUMAN_REVIEW` should be reported separately to make NM-001-style failures visible | Future work |
| `claim_metrics` | New verdict not yet aggregated into `ClaimMetrics` first-class fields | Optional follow-up; per-type dynamic counts already pick it up |

---

## 7. Reproduction recipe

```bash
cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5
git checkout feature/layer-f-cross-validation

# Unit tests (always run)
conda run -n metagent-llm pytest tests/test_verifier/test_layer_peak_mechanistic.py -v

# Full verifier suite
conda run -n metagent-llm pytest tests/test_verifier/ -q

# NM-001 validation script (requires CFM-ID Docker on :8088)
conda run -n metagent-llm python scripts/spike/test_layer_f_nm001_fix.py

# Integration tests (require SIRIUS login + CFM-ID; skipped otherwise)
conda run -n metagent-llm pytest tests/integration/test_layer_f_cross_validation.py -v --integration
```

---

## 8. Time accounting

```
§1 Schema additions                                   :  0.3 h
§2 _parse_formula + _sirius_sanity_check              :  0.7 h
§3 _check_cfmid + monoisotopic-mass fallback + cache  :  1.5 h
§4 _consensus 25-cell table                           :  0.8 h
§5 verify_peak_mechanistic main flow integration      :  0.7 h
§6 agent.py plumbing + _aggregate_verdict patch       :  0.4 h
§7 Unit tests (11 new + autouse cfmid isolation)      :  1.5 h
§8 Integration tests + NM-001 validation script       :  0.7 h
§9 Validation report + spike re-run                   :  0.5 h
                                                Total : ~7.1 h
```

Within the 1–2-day budget. No escalation required.

---

## 9. Open follow-ups (out of scope for this session)

- **NM-002 mitigation** (data leakage in GNPS-RIKEN cross-references)
  remains open. Filed in spike report.
- **Negative-mode benchmark protocol v3** needs to add a
  `needs_human_review_rate` per-mode metric.
- **CFM-ID NL check** could be tightened beyond ±0.02 Da once the
  precision of CFM-ID's precursor mass on negative mode is
  characterised on more fixtures.
- **SIRIUS sanity threshold** (2 atoms) is empirically chosen from
  the citric acid case; should be re-tuned once a wider survey of
  SIRIUS hallucinations is available.

---

## 10. Related documents

| Path | Purpose |
|---|---|
| `reports/spike/negative_mode_spike_2026-04-28.md` | The §2.8 cascade this report mitigates |
| `verifier/layers/peak_mechanistic.py` | Implementation of the cross-validation logic |
| `tests/test_verifier/test_layer_peak_mechanistic.py` | 11 new unit tests + 10 pre-existing tests |
| `tests/integration/test_layer_f_cross_validation.py` | Live-backend integration tests (skipped by default) |
| `scripts/spike/test_layer_f_nm001_fix.py` | Pre-/post-fix verdict comparison script |
| **`reports/spike/layer_f_cross_validation_validation_2026-04-28.md`** (this doc) | Layer F cross-validation acceptance |
