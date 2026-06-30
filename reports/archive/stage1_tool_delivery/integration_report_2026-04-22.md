# Day-1 Integration Report

**Date:** 2026-04-22
**Author:** Integration session (main_abc)
**Branch:** `integration-day1` — created from `master` (= `46be895`, Track C)
**Scope:** Static + cross-tool audit of the four day-1 tools
(`spectrum_preprocess`, `candidate_prefilter`, `library_search`,
`molecule_generate`) before the orchestrator lands.

This report is the first artifact of the integration session. The audit
report lists findings — it does not fix anything. Where a finding is
routable to a track, it is labeled with that track so the maintainer can
dispatch it.

---

## 0. Merge result

All four tracks live on sibling branches off `master` and change disjoint
files. Merge was executed as three `--no-ff` merges onto
`integration-day1`, preserving per-track authorship:

```
*   007c388 integrate Track B  (library_search)         into integration-day1
|\
| * e06dc12 day 1: library_search (Track B)
* | 8482f4a integrate Track A2 (candidate_prefilter)    into integration-day1
|\ \
| * 85c99aa day 1: candidate_prefilter (Track A2)
* | 4b2a165 integrate Track A1 (spectrum_preprocess)    into integration-day1
|\ \
| * 8431d61 day 1: spectrum_preprocess (Track A1)
|/
* 46be895 day 1: molecule_generate (Track C)
* 3187172 day 1: schemas, contracts, prompts, fixtures
```

Verification:

- Zero conflicts.
- `git diff master..integration-day1 -- schemas/ common/ docs/ prompts/` is
  empty: no shared file was touched by any track.
- `git diff --name-only master..integration-day1` shows only net-new files
  under `tools/{spectrum_ops,candidate_prefilter,library_search}/`, the
  three new `tests/tool_tests/test_<track>.py` files, and `.gitignore`
  (added by Track A1).

The `molecule_gen` track is already on `master` by design (confirmed with
maintainer); no extra merge needed for it.

---

## 1a. Schema conformance

Every tool's main function was driven end-to-end with a valid Pydantic
request; the returned object is a valid Pydantic response in every case.

**Mechanical probe used:** `scripts/audit_tracks.py` (Part 3 deliverable)
exercises each entry point with a canonical glucose-like request and
asserts `isinstance(resp, <ExpectedResponse>)` plus `resp.explain != ""`.
All four tools pass.

### ✅ Positives (no finding required)

- `preprocess(PreprocessRequest) → PreprocessResponse` — OK.
- `prefilter(PrefilterRequest) → PrefilterResponse` — OK (GNPS-only pool
  path exercised; PubChem-Lite path skip-gated on env var).
- `library_search(LibrarySearchRequest) → LibrarySearchResponse` — OK
  (via `MockInHouseRetriever`).
- `generate(GenerateRequest) → GenerateResponse` — OK (via
  `MockGenerator` + `MockFingerprinter`).
- All 8 `*Error` classes across the four tools inherit from
  `schemas.common.ToolError` (grep-verified — see
  `tools/{spectrum_ops,candidate_prefilter,library_search,molecule_gen}/errors.py`).
- Every response's `explain` field is a non-empty, template-rendered
  string. Sample output:
    - A1: `"Preprocessed 7 input peaks → 7 (dropped 0) after relative-intensity filter ≥ 0.01 and 5 ppm merge; base peak at m/z 163.0601; quality=sparse."`
    - A2: `"Neutral mass 180.0634 (from [M+H]+ at 181.0707). Formula constraint C6H12O6 applied. Returned 0 candidates within 5 ppm (0 from gnps)."`
    - B: `"Retrieved 1 candidates from prefiltered pool (libraries [gnps+inhouse], compared 1); top match PUBCHEM:5793 scored 0.910."`
    - C: `"Generated 3 raw SMILES; 2 parsed in RDKit; kept 1 matching formula C8H10N4O2; top score 1.000."`
- No `import openai` / `from common.llm_client import chat` calls in any
  tool module. The only occurrence of `llm_client` under `tools/` is a
  docstring analogy in `tools/candidate_prefilter/gnps_index.py:13`,
  verified by inspection.

### Findings

**F1 (nit, all tracks).** Each tool re-implements its own
`sys.path.insert(0, REPO_ROOT)` block at the top of its test file
(e.g. `tests/tool_tests/test_spectrum_ops.py:18-20`,
`test_molecule_gen.py:16-18`, and identical stanzas in the other two).
Not a correctness issue — it is how the contract says "no shared
conftest" — but creating a `tests/conftest.py` that does this once would
halve test boilerplate. Non-blocking; propose as a post-day-1 cleanup.

---

## 1b. Cross-tool contract conformance

This is the most load-bearing check in the report: each track tested
itself in isolation, so actual cross-tool data flow has never been
exercised before this session. I drove a full
`A1 → (hand-built pool in A2 shape) → B & C` probe against the glucose
fixture; results are documented inline below.

### ✅ Positives

- **A1 → {A2, B, C} via `Spectrum`.** A1 output is accepted unchanged by
  B and C. A2 only reads `precursor_mz` + `adduct` (which `Spectrum`
  carries), so no direct object handoff is needed. All intensity values
  land in `[0, 1]` and base peak is exactly `1.0`; the `Spectrum`
  `model_validator` passes downstream.
- **A2 → B via `list[PrefilteredCandidate]`.** `source_id`, `smiles`,
  `source_pool`, `has_reference_spectrum` round-trip cleanly. A pool
  entry with `source_pool="gnps"` flows through
  `library_search._collect_scoring_targets` and its `source_id`
  resolves in `_build_gnps_id_index` to reach the modified-cosine path.
  Pool entries with other `source_pool` values (e.g. `"pubchem_lite"`)
  still get scored by the ms-clip path — consistent with the B code's
  stated intent (see F3 on the contract divergence).
- **A2 → C via `list[PrefilteredCandidate]`.** The
  `in_pool` soft bonus fires: with glucose in the pool, the generated
  glucose candidate's `explain` contains `"In prefilter pool."` as
  expected (`tools/molecule_gen/tool.py:157-160`).
- **Score range.** Every `Candidate.score` in both B and C outputs is
  empirically in `[0, 1]` (also schema-enforced via `Field(ge=0, le=1)`
  in `schemas/common.py:90`).
- **Source-of-truth imports.** Both B and C import
  `PrefilteredCandidate` from `schemas` (not from
  `tools.candidate_prefilter`) — contract-compliant (no tool-to-tool
  imports).

### Findings

**F2 (major, contract vs code divergence, Track B).** The contract for
`library_search` in `docs/TOOL_CONTRACTS.md` § Tool 3 says:
> "When provided, only candidates with `has_reference_spectrum=True` are
> compared."

The code intentionally does **not** gate on `has_reference_spectrum`.
See `tools/library_search/tool.py:6-16` (module docstring):
> "... the maintainer confirmed the `has_reference_spectrum=True` gate
> in the original contract was dropped once ms-clip landed."

Maintainer ruling (2026-04-22 chat): **code is authoritative**. The
contract text in `docs/TOOL_CONTRACTS.md` § Tool 3 needs to be updated
to reflect that ms-clip scores every pool entry regardless of reference
availability, and modified-cosine scores only the subset whose
`source_id` resolves in the loaded GNPS pool. **Action: route back to
the doc owner (not Track B's code).**

**F3 (minor, environment dependency, Track B).** Under matchms `0.32.x`
(the version currently installed in the base env), `modified_cosine_score`
emits `WARNING:matchms:add_precursor_mz:No precursor_mz found in
metadata.` on every call, even though the code constructs the matchms
`Spectrum` with `metadata={"precursor_mz": float(...)}`
(`tools/library_search/scoring.py:65-75`). The score itself is still
correctly computed; the warning is cosmetic log noise coming from
matchms `add_precursor_mz` being re-run internally on a differently-keyed
metadata lookup. Does not reproduce under matchms `0.24.4` (Track B's
pin). Related to F5 (dependency pin mismatch) — resolving F5 also
resolves F3. **Action: none directly; tracked under F5.**

**F4 (minor, Track A2).** `tools/candidate_prefilter/example.py`'s
docstring claims it prints the error "instead of crashing" when env
vars are unset, but the script calls `prefilter(req)` without a
try/except, so `PubChemLiteNotBuiltError` propagates uncaught. Repro:
```
METAGENT_PUBCHEM_LITE_PATH="" PYTHONPATH=. \
    python tools/candidate_prefilter/example.py
# → Traceback ... PubChemLiteNotBuiltError: METAGENT_PUBCHEM_LITE_PATH is not set...
```
Easy fix: wrap `prefilter(req)` in try/except or gate by env-var
presence. **Action: Track A2 — docstring-code consistency fix.**

---

## 1c. Test coverage audit

Each contract's **Tests must cover** bullets were mapped 1:1 against the
track's test file. All four tracks pass the checklist. Details below.

### A1 `spectrum_preprocess` (5 required cases)

| Contract case | Test function |
|---|---|
| Real spectrum round-trip | `test_glucose_fixture_roundtrip`, `test_caffeine_and_lcarnitine_also_roundtrip` |
| Array-length mismatch raises | `test_mismatched_array_lengths_raise_validation_error` |
| 2-peak spectrum → invalid + raise | `test_literally_two_input_peaks_also_invalid`, `test_two_peaks_after_filter_raises_invalid_spectrum_error` |
| Relative-intensity filter drops low peaks | `test_low_intensity_filter_drops_peaks` |
| Output base peak = 1.0 | `test_response_spectrum_respects_schema_invariants` |

Extras: negative-mode `NotImplementedError`, quality-flag triplet
(`sparse`/`good`/`noisy`), ppm merge positive & negative cases, mz
scrambling tolerated. ✅ **Above contract.**

### A2 `candidate_prefilter` (6 required cases)

| Contract case | Test function |
|---|---|
| glucose [M+H]+ 181.0707 returns glucose in top | `test_glucose_in_top_candidates_for_m_plus_h_at_181_0707` |
| Formula hard filter | `test_formula_hard_constraint_filters_non_matching` |
| 0.5 ppm << 20 ppm candidate count | `test_narrow_ppm_returns_strict_subset_of_wide_ppm` |
| All `mass_error_ppm` ≤ tolerance | `test_all_mass_errors_within_requested_tolerance` |
| Sorted by `mass_error_ppm` asc | `test_candidates_sorted_by_mass_error_ascending` |
| Nonsense precursor → empty list (not error) | `test_empty_candidate_list_does_not_raise` |

Extras: adduct reverse-math for `[M+H]+`, `[M-H]-`, `[M+Na]+`, dimer,
unknown adduct → `InvalidAdductError`; `has_reference_spectrum` cross-
stamping via injected GnpsIndex; `max_candidates` cap; `n_by_pool`
consistency; `hmdb` pool is a documented no-op; `PubChemLiteNotBuiltError`
path. ✅ **Above contract.**

### B `library_search` (5 required cases)

| Contract case | Test function |
|---|---|
| Fixture derived from real GNPS record → top-3 | `test_glucose_fixture_retrieves_glucose_in_top_three` |
| Nonsensical spectrum → empty | `test_nonsensical_spectrum_returns_empty` |
| `top_k=1` → at most 1 | `test_top_k_one_returns_at_most_one` |
| All scores in [0, 1] | `test_all_scores_in_unit_interval` |
| Full-GNPS integration tests skip when env unset | `test_integration_full_gnps_pool_finds_known_compound` (with `@pytest.mark.skipif` on `METAGENT_GNPS_PATH`) |

Extras: `top_k=0` path, schema-enforced descending sort, SMILES
dedup, pool-path vs fallback-path disambiguation, `libraries=["inhouse"]`
vs `libraries=["gnps"]` single-scorer runs. ✅ **Above contract.**

### C `molecule_generate` (4 required cases)

| Contract case | Test function |
|---|---|
| All output SMILES parse in RDKit | `test_all_returned_smiles_parse_in_rdkit` |
| `source=="generated"` and `score ∈ [0, 1]` | `test_source_is_generated`, `test_score_in_unit_interval` |
| Formula constraint respected for >90% of outputs | `test_formula_hard_filter` (actually enforces 100% via hard filter — see F5) |
| `n_candidates=0` returns empty without error | `test_n_candidates_zero_returns_empty` |

Extras: MW filter, invalid-SMILES filtering, sparse-spectrum no-crash,
all-invalid → `NoValidCandidatesError`, descending-score sort, ground-
truth fingerprinter token-string parser, end-to-end fusion-fingerprinter
+ generator wiring test. ✅ **Above contract.**

**F5 (nit, Track C).** Contract says formula constraint respected for
`>90%` of outputs; code does a **hard** filter so the actual rate is
`100%`. Implementation is **stricter** than spec, which is safe but
worth mirroring in the contract to prevent future drift if someone ever
relaxes the filter back to soft. **Action: update
`docs/TOOL_CONTRACTS.md` § Tool 4 bullet to "100% when provided".**

---

## 1d. Dependency audit

Pinned deps per track:

| Track | Package pins |
|---|---|
| A1 `spectrum_ops` | `matchms==0.24.0`, `numpy==1.26.4`, `pydantic==2.8.2` |
| A2 `candidate_prefilter` | `pydantic==2.8.2`, `rdkit==2024.3.5` |
| B `library_search` | `pydantic==2.8.2`, `matchms==0.24.4`, `numpy==1.26.4` |
| C `molecule_gen` | `pydantic==2.8.2`, `rdkit==2024.3.5` |

### Findings

**F6 (major, cross-track pin conflict, Track A1 vs B).** `matchms`
version pin mismatch:
- A1: `matchms==0.24.0`
- B: `matchms==0.24.4`

Both tools land in the same integration environment. Whichever is
installed last wins; the other tool runs against an unpinned version.

**Maintainer ruling (2026-04-22 chat):** follow Track B's pin (`0.24.4`),
because B's Python env is locked to its model-runtime deps and harder to
change. **Action: Track A1 — update
`tools/spectrum_ops/requirements.txt` to `matchms==0.24.4`.** Track A1
code compiles under 0.24.4 trivially — the only matchms calls are
`Spectrum`, `normalize_intensities`, `select_by_relative_intensity`,
whose signatures are unchanged between 0.24.0 and 0.24.4.

**F7 (minor, implicit undeclared dep, Track A2).** `tools/candidate_prefilter/tool.py`
imports `rdkit` lazily inside `_inchikey_for` at call time
(`tool.py:~140`), and both `gnps_index.py` and `pubchem_index.py` lazy-
import rdkit too. `requirements.txt` *does* list `rdkit==2024.3.5`, so
this is a non-bug — flagging only because the lazy-import pattern is
easy to break silently by forgetting to update the requirements file
when new rdkit call sites are added. No action needed now.

**F8 (minor, unpinned implicit dep, Track B).** `library_search/model.py`
uses `pickle` and `subprocess` (stdlib, fine) but relies on the
`diffms` conda env at runtime for ms-clip scoring — this is documented
in the module docstring and `tool_description.md`, but the env-building
instructions are not in-repo. Not a pin issue; flagging as a deployment
follow-up. **Action: operator checklist, not code.**

**F9 (minor, environment drift — this session's env only).** The current
base conda env has:
- `pydantic 2.10.3` (pinned 2.8.2)
- `matchms 0.32.0` (pinned 0.24.x)
- `numpy 2.2.6` (pinned 1.26.4)
- `rdkit 2025.09.6` (pinned 2024.3.5)

All four tools *functionally* run under the drifted versions (verified
via `scripts/audit_tracks.py` — no crashes, results sane), but F3's
matchms warning demonstrates the behavioural creep is real. Operators
should build the integration conda env from the merged
`requirements.txt` union after F6 is resolved; this session's
integration tests declare `@pytest.mark.requires_*` skip markers so
they can still run in a drifted env without lying about success.

---

## 1e. `tool_description.md` audit

The four tool descriptions will be pasted verbatim into the orchestrator's
tool registry. They are graded below on: (i) clear purpose statement,
(ii) when-to-call and when-NOT-to-call guidance, (iii) plain-language I/O
explanation, (iv) documented failure modes.

| Tool | Purpose | When/NOT | I/O fields | Failure modes | Overall |
|---|---|---|---|---|---|
| `spectrum_preprocess` | Clear, 1-line | Both, crisp | Every field | Listed in table | **A** |
| `candidate_prefilter` | Clear, 2-para | Both, with widen-tolerance advice | Every field + supported-adducts list | Explicit table | **A+** |
| `library_search` | Clear, 2-para (modcos + ms-clip named) | Both, with follow-up-with-molecule_generate nudge | Every field + **score semantics section** | Explicit section | **A+** |
| `molecule_generate` | Clear, mentions CSI + MS-BART | Both | Every field + **score formula** | Explicit table | **A+** (most verbose) |

### Findings

**F10 (nit, Tracks A1 & C).** Neither `spectrum_preprocess` nor
`molecule_generate` documents the set of accepted `adduct` strings.
`candidate_prefilter` has an explicit "Supported adducts" section. In
practice the `adduct` field is a free string at A1/C's layer (they just
propagate or reason about formula), so enumeration is not strictly
needed — but since the orchestrator will pipe adducts across all four
tools, a one-line reference pointing to `candidate_prefilter`'s adduct
table would help the LLM keep its vocabulary consistent. **Action:
optional one-liner in A1 and C tool descriptions.**

**F11 (nit, Track B).** `tool_description.md` for `library_search` does
not state that `has_reference_spectrum` is **not** a gate (see F2). Once
F2's doc fix lands, this description should be updated to match. Minor
because the `explain` string does accurately reflect the live behavior
at runtime.

---

## 2. Summary table

| ID | Severity | Track | Category | Finding |
|---|---|---|---|---|
| F1 | nit | all | 1a | Per-test `sys.path` bootstrap duplicated in all four test files |
| F2 | major | B (docs) | 1b | Contract says `has_reference_spectrum` gates modcos; code intentionally does not — code authoritative, doc needs update |
| F3 | minor | B | 1b | matchms `add_precursor_mz` warning on 0.32+ — disappears on 0.24.4 (F6) |
| F4 | minor | A2 | 1b | `example.py` docstring claims error-catching, code doesn't catch |
| F5 | nit | C (docs) | 1c | Contract says `>90%` formula match; code enforces 100% — update doc |
| F6 | major | A1 | 1d | matchms pin conflict A1 `0.24.0` vs B `0.24.4` — update A1 to `0.24.4` |
| F7 | minor | A2 | 1d | Lazy `import rdkit` — declared in reqs, flagged for maintainer awareness |
| F8 | minor | B | 1d | `diffms` conda env not reproducible in-repo — operator follow-up |
| F9 | minor | env | 1d | Current base env pin drift documented; build integration env from union reqs |
| F10 | nit | A1, C | 1e | Tool descriptions don't reference the adduct vocabulary |
| F11 | nit | B | 1e | Tool description silent on ms-clip-not-gated-by-has_reference_spectrum |

**Blocking findings:** none. The pipeline runs end-to-end with mocks
injected at the two model boundaries.

**Routable to individual tracks:**
- Track A1 (one-liner pin bump): F6
- Track A2 (docstring-code consistency): F4
- Track B (tool_description follow-up once contract is updated): F11
- Docs owner (contract text updates): F2 (the contract side), F5

**Must-do next:** none block Part 2 (E2E tests) or Part 3 (smoke script),
so those proceed immediately. Part 2's mocks intentionally bypass the
real ms-clip/MS-BART boundaries, so F2 being undecided in the contract
text doesn't block test authoring — the tests validate observed code
behavior, which is the authoritative source per maintainer ruling.

---

## 3. Appendix — commands used to reproduce findings

```
# Merge and verify disjoint diff
git checkout master && git checkout -b integration-day1
git merge --no-ff track-a1-spectrum-preprocess
git merge --no-ff track-a2-candidate-prefilter
git merge --no-ff track-b-library-search
git diff --stat master..integration-day1 -- schemas/ common/ docs/ prompts/  # expect empty

# Schema-conformance smoke
python scripts/audit_tracks.py

# Cross-tool probe (F2, F3 evidence)
PYTHONPATH=. python -c "
from schemas import PreprocessRequest, LibrarySearchRequest, PrefilteredCandidate
from tools.spectrum_ops import preprocess
from tools.library_search import library_search
from tools.library_search.model import MockInHouseRetriever
# ... see Section 1b for full snippet
"

# F4 repro (A2 example docstring-vs-code)
PYTHONPATH=. python tools/candidate_prefilter/example.py   # → Traceback

# Dependency audit (F6)
diff <(cat tools/spectrum_ops/requirements.txt) \
     <(cat tools/library_search/requirements.txt)
```
