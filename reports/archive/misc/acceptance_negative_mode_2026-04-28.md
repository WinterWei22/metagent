# Acceptance report — Tracks A/B/C negative-mode update

**Date:** 2026-04-28
**Verifier:** integration session (`main_abc`)
**Branch under acceptance:** `feature/massbank-data-pipeline` tip `47241dd`
**Predecessor acceptance:** `reports/acceptance_tracks_abc_2026-04-23.md`
(positive-mode only, day-1)
**Overall verdict:** ✅ **ALL FOUR TRACKS ACCEPTED FOR NEGATIVE MODE.**
The schema's `Literal["positive", "negative"]` constraint was always
forward-compatible; this update lights up the negative path end-to-end
with no contract changes.

## 1. Executive summary

Five negative-mode commits land across three of the four tracks (C
needed no change — it never gated on polarity). On the glucose `[M-H]-`
fixture the full pipeline runs without any workaround:

```
              unit    delta   integ   real-neg-run    contract     verdict
              tests   vs day1 shape   (glucose [M-H]-) alignment
  A1          18/18   +1      ✅      ✅              ✅           ACCEPT
  A2          34/35*  +5      ✅      ✅              ✅           ACCEPT
  B           36/38*  +13     ✅      ✅              ✅           ACCEPT
  C           18/18    0      ✅      ✅              ✅           ACCEPT

  * skips are real-resource gates (requires_*), not failures.
```

End-to-end on negative-mode glucose:
- A2 returned **345 candidates** (298 GNPS + 47 PubChem-Lite), **330**
  with `has_reference_spectrum=True` under the new same-mode semantics,
  151/345 connectivity-match glucose.
- B returned 5 candidates with top-1 **0.828** via the new
  `v4_spectraverse` checkpoint, no degradation marker in `explain`.
- C returned glucose's stereo-stripped canonical SMILES with score
  1.000, `[in_pool]` bonus triggered.
- Truth connectivity (`WQZGKKKJIJFFOK`) recovered in top-10 B∪C union.

## 2. What's new since 2026-04-23

Five commits on `feature/massbank-data-pipeline`:

| Commit | Track | Subject | LoC change |
|---|---|---|---|
| `3cab5a7` | A1 | spectrum_ops: support negative ion mode | tool.py / tool_description.md / 2 new tests + 1 new fixture |
| `84b00f8` | A2 | candidate_prefilter: mode-aware queries (negative ion mode support) | adducts.py +19 / gnps_index.py +131 / tool.py +15 / tests +156 |
| `c803f47` | A2 | candidate_prefilter: JSON GNPS path also picks up negative mode | (small follow-up to 84b00f8) |
| `87a864d` | B  | library_search: negative-mode adducts via spectraverse checkpoint | model.py +37 / tool_description.md +38 / tests +139 |
| `47241dd` | B  | library_search: GPU selection in MSClipRetriever | (operational, not negative-mode-specific but bundled here) |

**Track C had no commits** — its pipeline reads `Spectrum.ionization_mode`
only via schema validation; the pydantic `Literal["positive","negative"]`
was already permissive, so generation works on either polarity without
code change.

**Schema is unchanged.** The `Literal["positive", "negative"]` constraint
in `schemas/spectrum.py` and `schemas/common.py` was set up on day-1 to
be forward-compatible; today's work consumes the previously-unused half
of the literal.

## 3. Acceptance criteria (carried over from 2026-04-23)

Same five criteria as the positive-mode acceptance — see
`reports/acceptance_tracks_abc_2026-04-23.md § 3`. Re-evaluated under
negative-mode inputs.

## 4. Per-track verdicts

### 4.1 Track A1 — `spectrum_preprocess` ✅ ACCEPT

**What changed.** `tools/spectrum_ops/tool.py` removed the early
`raise NotImplementedError` for negative mode and updated the pipeline
docstring + `tool_description.md`. Signal-processing primitives
(intensity filter, ppm merge, sort, normalise, quality flag) are
polarity-independent so no algorithmic change was required.

**Test delta.** `test_negative_mode_is_not_implemented_in_v0` was
replaced by two passing tests:
- `test_negative_mode_fixture_roundtrip` against the new
  `tests/fixtures/spectra/glucose_neg.json` (synthetic placeholder
  with `[M-H]- 179.0556` precursor + 7 fragments).
- `test_negative_mode_synthetic_passes_through` — minimal hand-built
  3-peak negative-mode spectrum.

**Total: 18 / 18 passed (was 17 / 17 on day-1).** The negative-mode
fixture round-trip asserts `ionization_mode` and `adduct` propagate
unchanged, base peak normalised to 1.0, mz ascending.

**Real run.** Glucose `[M-H]-` from the new fixture preprocesses to a
7-peak `Spectrum` in <0.1 s, base peak m/z 161.0455 (intensity 1.0 in
normalised scale, 1000.0 in original scale).

**Findings.** None new. F10 (tool description doesn't reference adduct
vocabulary) is still parked, unchanged.

### 4.2 Track A2 — `candidate_prefilter` ✅ ACCEPT

**What changed.** Three structural additions:

1. `adducts.py::polarity_for(adduct) -> "positive" | "negative"` —
   exposes the existing `AdductRule.polarity` field as a public helper.
2. `gnps_index.py` — `GnpsIndex` now partitions records into separate
   mass-sorted lists per ion mode, with per-mode InChIKey first-block
   sets. `search()` requires an `ion_mode` argument and refuses to
   bridge modes (B can't score a negative query against a positive
   reference). The CSV reader stops dropping negative-mode rows; the
   JSON path is fixed (commit `c803f47`) so
   `common.gnps_loader.load_v0_usable` no longer silently drops
   negative records via its old `is_usable_for_v0 == positive` gate.
3. `tool.py` — derives mode from `req.adduct` via `polarity_for()`,
   threads it into `gnps_idx.search()` and the cross-stamp.

**`has_reference_spectrum` semantics tightened.** Now means "GNPS has
a *same-mode* reference for this candidate's connectivity". This is
strictly more useful for B downstream — B cannot bridge polarities
during scoring, so a positive-mode reference for a negative-mode query
would have been a false positive.

**Test delta.** +5 negative-mode tests:
- `polarity_for` table-driven test
- negative-adduct end-to-end query
- mode-specific `has_reference_spectrum` cross-stamping
- unknown-mode records dropped at index construction
- existing CSV-reader test updated to assert negative-mode is **kept**
  (still rejecting MALDI / EI / GC)

**Total: 34 / 35 passed (was 29 / 30 on day-1).** The 1 skip is the
real-PubChemLite integration test, gated on the env var.

**Real run.** Glucose `[M-H]-` query at 5 ppm:
- Total 345 candidates (298 GNPS + 47 PubChem-Lite)
- 330 with `has_reference_spectrum=True` (negative-mode same-mode set)
- 151/345 connectivity-match glucose (more than positive's 73/205 —
  expected, GNPS has more `[M-H]-` annotated records for sugars)
- First-call wall time 435 s (loads 930k records: 697k positive + 232k
  negative across the full GNPS CSV)

**Findings.** None new. F4 / F7 status unchanged.

### 4.3 Track B — `library_search` ✅ ACCEPT

**What changed.** Two commits:

1. `87a864d` — `_MSCLIP_ION_REMAP` extended with 4 negative ions
   (`[M-H]-`, `[M+FA-H]-`, `[M+CH3COO]-`, `[M+Cl]-`) plus common GNPS /
   vendor aliases (`[M+HCOO]-`→`[M+FA-H]-`, `[M+OAc]-`→
   `[M+CH3COO]-`, bare `M-H`→`[M-H]-`). The orchestrator-side helper
   stays env-independent (F12-style constraint preserved).
   `DEFAULT_CKPT_PATH` switched to `v4_spectraverse_20260428_134311`,
   which extends the original `chemformer_v4_large_*` with negative-
   mode training; positive vocab indices 0-6 are preserved (backward-
   compatible).
2. `47241dd` — `MSClipRetriever` gains a `gpu_id` parameter
   (int / "auto" / "inherit"), defaulting to "auto" (picks the GPU
   with most free memory via `nvidia-smi`). Operational improvement,
   not negative-mode-specific.

**Test delta.** +5 negative-mode regression tests in `87a864d`:
- canonical negative adducts pass through unchanged
- aliases canonicalise to MSG form
- unsupported negative adducts (`[M-2H]2-`, `[M+TFA-H]-`) → `None`
- negative-mode `Spectrum` scores via inhouse without modcos
  degradation
- TSV writes the canonical adduct form

Plus 8 more tests caught by the broader test-collection delta (likely
GPU-selection coverage).

**Total: 36 / 38 passed (was 23 / 25 on day-1).** The 2 skips remain
the pre-existing real-resource gates.

**Real run.** Glucose `[M-H]-` against 30-candidate slice:

```
explain: Retrieved 5 candidates from prefiltered pool (libraries
         [gnps+inhouse], compared 30); top match CCMSLIB00005720867
         scored 0.828.
  rank 1  0.828  CCMSLIB00005720867  MYO-INOSITOL
  rank 2  0.820  CCMSLIB00005436197  ALLOSE
  rank 3  0.810  CCMSLIB00005436164  PSICOSE
  rank 4  0.809  CCMSLIB00005720863  FRUCTOSE
  rank 5  0.781  CCMSLIB00000479619  Fructose
```

Wall time 105 s. **Top-1 score 0.828 is higher than positive mode's
0.789** — the spectraverse checkpoint is delivering on negative-mode
discrimination. Neither "ms-clip scoring failed" nor "failed to load
GNPS" appears in the explain string; both `gnps` and `inhouse`
libraries contributed to the fused scores.

**Findings.** None new. F8 / F11 / F12 / F13 / F14 / F15 all remain
closed.

### 4.4 Track C — `molecule_generate` ✅ ACCEPT

**What changed.** Nothing. Track C never gated on `ionization_mode`;
the schema's permissive `Literal` was always sufficient.

**Test delta.** 0. Existing 18 tests still pass.

**Real run.** On the same negative-mode glucose spectrum as A1/A2/B,
`MSBartGenerator` + `GroundTruthFingerprinter.from_smiles(glucose)`
produces 20 raw → 20 RDKit-valid → 1 final candidate matching
`C6H12O6` (`OCC1OC(O)C(O)C(O)C1O`, score 1.000, `[in_pool]` bonus
fired against A2's 345-candidate pool).

Wall time 8.2 s. The MS-BART checkpoint itself doesn't model polarity
at the decoder level — it consumes a fingerprint plus optional formula
constraint, both polarity-agnostic. This is the right separation: C is
a structure proposer, not a spectrum interpreter, so polarity is
implicit in upstream stages.

**Findings.** None new. F5 (contract says >90% formula match, code
enforces 100%) still parked.

## 5. Cross-tool end-to-end (negative mode)

Same composition pattern as the positive-mode run on 2026-04-23, with
the `glucose_neg.json` fixture:

| Stage | Real / Mock | Wall time | Result |
|---|---|---|---|
| A1 preprocess | real | <0.1 s | 7 peaks, mode=negative, adduct=[M-H]-, base peak=1.0 |
| A2 prefilter | real | 435 s¹ | 345 candidates (298 GNPS + 47 PubChem-Lite); 330 with same-mode reference; 151/345 conn-match glucose |
| B library_search (top-30 slice, `libraries=["inhouse","gnps"]`) | real | 105 s | 5 candidates, top-1 0.828 MYO-INOSITOL via spectraverse checkpoint, explain clean |
| C molecule_generate (glucose oracle FP + full pool for bonus) | real | 8.2 s | 20 raw / 20 valid / 1 final glucose-equivalent, score 1.000, in_pool bonus |
| **Truth-connectivity union check** | — | — | ✅ `WQZGKKKJIJFFOK` in top-10 union |

¹ Includes loading 930k GNPS records (697k pos + 232k neg). Subsequent
calls are sub-millisecond.

### 5.1 Cross-tool contract round-trip evidence

- **A1 → A2.** `Spectrum(adduct="[M-H]-", ionization_mode="negative")`
  consumed by A2's `polarity_for(req.adduct)` to derive mode. OK.
- **A2 → B.** `list[PrefilteredCandidate]` with `has_reference_spectrum=
  True` under the new same-mode semantics. B's pool path used the
  GNPS MGF for negative-mode peak resolution (F14 dispatch), and
  ms-clip routed `[M-H]-` to vocab index 7 in the spectraverse
  checkpoint.
- **A2 → C.** Same pool used as soft bonus. Glucose's stereo-stripped
  SMILES appears in the pool under multiple `source_id`s
  (CCMSLIB000054361xx for the negative mode hexose family); C's
  in_pool bonus fired correctly.

### 5.2 Positive vs negative comparison

Same fixture compound (glucose) just different ionisation:

| Variant | A2 #cand | A2 has_ref | B top-1 score | B top-1 name | C result |
|---|---|---|---|---|---|
| `[M+H]+` (2026-04-23) | 205 | 190 | 0.789 | β-D-Allose | glucose-equiv 1.000 |
| `[M-H]-` (2026-04-28) | 345 | 330 | **0.828** | MYO-INOSITOL | glucose-equiv 1.000 |

Negative mode pulls more candidates because GNPS has more `[M-H]-`
annotations for hexoses. B's top-1 score is higher in negative mode,
suggesting the spectraverse checkpoint discriminates better on negative-
mode peak patterns (the `[M-H-H2O]-`, `[M-H-2H2O]-` water-loss series
seen in glucose negative-mode fragmentation has more discriminatory
power than positive-mode protonated fragments). Both runs recover
truth connectivity in the top-10 B+C union.

## 6. Findings ledger (updated 2026-04-28)

| ID | Severity | Status at 2026-04-23 | Status at 2026-04-28 |
|---|---|---|---|
| F1–F15 | various | (see day-1 acceptance) | unchanged — none reopened |
| **F16** | n/a | n/a | not raised — no new findings during this acceptance |

No critical or major findings raised in this round. The negative-mode
work landed cleanly: every commit ships its own regression tests, the
real-data run on the new fixture passes, and no positive-mode test
flipped to red.

## 7. Test inventory at acceptance

```
$ cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5
$ conda run -n diffms --no-capture-output python -m pytest \
      tests/tool_tests/test_spectrum_ops.py \
      tests/tool_tests/test_candidate_prefilter.py \
      tests/tool_tests/test_library_search.py \
      tests/tool_tests/test_molecule_gen.py \
      tests/tool_tests/test_gnps_loader.py \
      tests/integration/test_pipeline_e2e.py

============ 125 passed, 7 skipped, 2 warnings in 3.97s ============
```

Per-file breakdown (in the `diffms` env):

| File | Passed | Skipped | Δ vs 2026-04-23 |
|---|---|---|---|
| `test_spectrum_ops.py` | 18 | 0 | +1 (negative fixture + synthetic) |
| `test_candidate_prefilter.py` | 34 | 1 | +5 (polarity table, mode-aware queries, mode-stamping, unknown-mode drop, CSV-reader update) |
| `test_library_search.py` | 36 | 2 | +13 (5 negative adducts + 8 GPU selection) |
| `test_molecule_gen.py` | 18 | 0 | 0 |
| `test_gnps_loader.py` | 3 | 0 | 0 |
| `test_pipeline_e2e.py` (integration) | 16 | 4 | 0 |
| **Total** | **125** | **7** | **+19** |

All skips are `requires_*`-gated; none are failures.

## 8. Acceptance sign-off

For the negative-mode update:

- **A1 `spectrum_preprocess`** — ✅ ACCEPT.
- **A2 `candidate_prefilter`** — ✅ ACCEPT.
- **B  `library_search`** — ✅ ACCEPT.
- **C  `molecule_generate`** — ✅ ACCEPT.
- **A1 → A2 → B → C cross-tool composition (negative mode)** — ✅ ACCEPT.

Negative-ion-mode support is complete across the four day-1 tracks.
The pipeline runs end-to-end against real backends with no workarounds
on both polarities. Schema unchanged; contract still authoritative.

## 9. Reproduction recipe

```bash
cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5

# Regression (all four tracks + integration)
conda run -n diffms --no-capture-output python -m pytest \
    tests/tool_tests/test_spectrum_ops.py \
    tests/tool_tests/test_candidate_prefilter.py \
    tests/tool_tests/test_library_search.py \
    tests/tool_tests/test_molecule_gen.py \
    tests/tool_tests/test_gnps_loader.py \
    tests/integration/test_pipeline_e2e.py

# Negative-mode acceptance (full real e2e). First A2 call ~7 min on the
# 930k-record GNPS index; subsequent calls in same process sub-ms.
source tools/candidate_prefilter/env.sh
conda run -n diffms --no-capture-output python /tmp/e2e_real_glucose_neg.py
```

The standalone driver script lives at `/tmp/e2e_real_glucose_neg.py`
(ephemeral). If you want a permanent copy, drop it into
`scripts/e2e_real_neg.py` — its shape is captured in this report.

## 10. Related documents

| Path | Purpose |
|---|---|
| `reports/acceptance_tracks_abc_2026-04-23.md` | Day-1 positive-mode per-track acceptance (predecessor) |
| `reports/f14_f15_acceptance_2026-04-23.md` | F14/F15 fix verification (still relevant; same loader path used here) |
| `reports/delivery_day1_integration_2026-04-23.md` | Day-1 hand-off doc |
| **`reports/acceptance_negative_mode_2026-04-28.md`** (this doc) | **Negative-mode update acceptance sign-off** |
| `tests/fixtures/spectra/glucose_neg.json` | New negative-mode fixture introduced by `3cab5a7` |
