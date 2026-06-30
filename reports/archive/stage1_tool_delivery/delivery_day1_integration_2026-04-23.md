# Day-1 integration delivery

**Session:** `main_abc` (integration session)
**Period covered:** 2026-04-22 → 2026-04-23
**Final branch:** `integration-day1` (tip `1ab3cd5` at hand-off)
**Target audience:** anyone picking up day-2 integration, or a track
session reading back the context before making further changes.

This document is a **self-contained hand-off**. Everything you need to
understand, re-run, or continue day-1 integration work should be linked
from here. The four numbered audit reports under `reports/` remain the
authoritative, detailed source; this file is a tour.

---

## 1. Executive summary

**What shipped.** The four day-1 tools (`spectrum_preprocess`,
`candidate_prefilter`, `library_search`, `molecule_generate`) were
merged onto a single branch, contract-audited, integration-tested with
both mocked and real models, and the cross-tool data flow was verified
end-to-end against the glucose fixture.

**Status of the full real pipeline (A1→A2→B→C).** Runnable, with one
workaround. Ground-truth connectivity for glucose is recovered in the
top-10 union of `library_search + molecule_generate`. The workaround is
tracked in `reports/f14_f15_gnps_loader_followup_2026-04-23.md` and
does **not** block the mocked integration suite — that remains green.

**What still needs someone else's hands.** Two routed follow-ups:

- `reports/track_b_followups_2026-04-22.md` — applied by Track B as
  commit `d050ea4`. ✅ done.
- `reports/f14_f15_gnps_loader_followup_2026-04-23.md` — needs the
  `common/` owner. ❌ open.

Tracks D and E landed independently onto `integration-day1` during
this session (`796ad3b`, `2885f17`, `1ab3cd5`). Per maintainer
instruction they were **not** audited or tested by the integration
session.

---

## 2. Branch, tag, and commit state at hand-off

### Branches

```
master                         46be895   day 1: molecule_generate (Track C) — unchanged
integration-day1               1ab3cd5   fix(pathway_context): RaMP v3 + neighbour speedup — latest
track-a1-spectrum-preprocess   a4d027a   audit: F14/F15 GNPS loader follow-up
track-a2-candidate-prefilter   a4d027a   audit: F14/F15 GNPS loader follow-up
track-b-library-search         a4d027a   audit: F14/F15 GNPS loader follow-up
```

`master` has not advanced — day-1 deliberately stopped at "produce the
integration branch", merging back to `master` is a day-2 decision.

The three track branches were fast-forwarded to `a4d027a` (last
integration-session commit). Track D's `1ab3cd5` landed after and
was not propagated back to the track branches — there is no track-d
branch, and D was out-of-scope for this session.

### Tags

```
track-a2-pre-reset → 56d10c4   safety tag for the pre-reset A2 tip
```

Created when `track-a2-candidate-prefilter` was reset from its
independent tip (`56d10c4`, equivalent-content cherry-picks of the A2
commits that had already been rolled into `integration-day1`) to
match `integration-day1`. Content diff between the two was zero at
reset time. Tag is local-only; push it if you want to preserve it
across clones.

### Full commit graph of `master..integration-day1` (chronological)

```
85c99aa  day 1: candidate_prefilter (Track A2)              ← track base
e06dc12  day 1: library_search (Track B)                    ← track base
8431d61  day 1: spectrum_preprocess (Track A1)              ← track base
4b2a165  integrate Track A1 (spectrum_preprocess)           ← integration merge
8482f4a  integrate Track A2 (candidate_prefilter)           ← integration merge
007c388  integrate Track B (library_search)                 ← integration merge
b1e2673  audit: day-1 integration report                    [integration session]
52c6b94  integration: smoke script + e2e pipeline tests     [integration session]
dfe2f58  spectrum_ops: bump matchms to 0.24.4               (F6 fix by A1)
53a4357  fix(candidate_prefilter): example.py docstring     (F4 fix by A2)
380c1ed  audit: real-run findings (F12, F13)                [integration session]
e613a25  audit: Track B followup action items               [integration session]
d050ea4  fix(library_search): F12/F13/F11/F8                (routed fix by B)
e533800  feat(candidate_prefilter): GNPS CSV + PubChemLite  (A2 post-day-1 feature)
796ad3b  feat(track_D): fetch_metabolite_info + pathway_context
1889d2a  chore(candidate_prefilter): add env.sh
2885f17  day 1: predict_spectrum (Track E)
a4d027a  audit: F14/F15 GNPS loader follow-up               [integration session]
1ab3cd5  fix(pathway_context): RaMP v3 + neighbour speedup  (Track D follow-up)
```

Six of those commits ([integration session]) are mine; the rest came
from track sessions or the maintainer.

---

## 3. Artifacts this session delivered

All paths relative to the repo root. Line counts in parentheses.

### Audit reports (`reports/`)

| File | Purpose |
|---|---|
| `integration_report_2026-04-22.md` (407) | Part-1 static audit. 11 findings (F1–F11) with severity + track + repro. Acceptance criteria for "mergeable" status. |
| `real_run_findings_2026-04-22.md` (239) | What the first live-model run surfaced that static audit missed. Introduces F12 (major) and F13 (critical) on Track B's ms-clip adapter. |
| `track_b_followups_2026-04-22.md` (369) | Self-contained action doc for Track B: F11/F12/F13/F8 with patch sketches + tests to add + acceptance snippet. **Landed by B as `d050ea4`.** |
| `f14_f15_gnps_loader_followup_2026-04-23.md` (436) | Self-contained action doc for the `common/` owner: CSV-unaware `gnps_loader` (F14 critical) and `required=False` ignored (F15 major). **Not yet landed.** |

### Integration tests (`tests/integration/`)

| File | Purpose |
|---|---|
| `__init__.py` (0) | Makes the directory a package for clean intra-package imports. |
| `conftest.py` (126) | Loads the 3 JSON fixtures, registers `requires_gnps` / `requires_pubchem_lite` / `requires_inhouse_model` marks, exposes `fixture_spectrum` (parametrised) and `all_fixtures`. |
| `test_pipeline_e2e.py` (462) | 20 tests: 12 mocked (4 × 3 fixtures) + 3 real-pool gated + 1 real-model gated + 4 always-on negatives. Uses InChIKey connectivity hashes (not full keys) so real MS-BART output — which drops stereo — doesn't break assertions. |
| `README.md` (100) | How to run the suite, how to interpret skips vs failures, scope boundaries. |

### Diagnostic tooling (`scripts/`)

| File | Purpose |
|---|---|
| `audit_tracks.py` (100) | 5-second smoke check. Boots every tool with a canonical glucose request (mocks on model boundaries, pools=["gnps"] on prefilter to avoid DB dependency). Exits 0 iff all four run cleanly, non-zero otherwise. |

### Safety tag

| Tag | Points to |
|---|---|
| `track-a2-pre-reset` | `56d10c4` — A2's pre-reset tip, content-equivalent to `integration-day1` at the time |

Nothing under `tools/`, `schemas/`, `common/`, `docs/`, or `prompts/`
was modified by the integration session.

---

## 4. Test matrix and last-run results

### 4.1 Unit tests (per-track, `tests/tool_tests/`)

Run inside the `diffms` conda env (matchms 0.27 — `ModifiedCosine` is
still present; see F9 on env drift). Scope: `test_spectrum_ops.py`,
`test_candidate_prefilter.py`, `test_library_search.py`,
`test_molecule_gen.py`. D and E test files exist under the same
directory but were out of scope.

Last result: **86 passed, 3 skipped.** The 3 skips are `requires_*`
gated tests (real GNPS, real ms-clip, real PubChem-Lite).

```bash
conda run -n diffms --no-capture-output python -m pytest \
    tests/tool_tests/test_spectrum_ops.py \
    tests/tool_tests/test_candidate_prefilter.py \
    tests/tool_tests/test_library_search.py \
    tests/tool_tests/test_molecule_gen.py \
    -v
```

### 4.2 Integration tests (`tests/integration/`)

Last result: **16 passed, 4 skipped.** The 4 skips are
`TestRealPoolPipeline::test_prefilter_returns_at_least_one_candidate[*]`
(requires PubChem-Lite) and
`test_realmodel_groundtruth_top10_union_across_fixtures` (requires
real in-house model + PubChem-Lite).

```bash
conda run -n diffms --no-capture-output python -m pytest tests/integration/ -v
```

Use `--integration` to flip skips-on-missing-env into failures-on-missing-env
(for CI machines that should have every resource wired).

### 4.3 Smoke (`scripts/audit_tracks.py`)

Last result: **exit 0**, four tools boot in a few milliseconds each
(except A1's matchms cold-start ~7 s).

```bash
conda run -n diffms --no-capture-output python scripts/audit_tracks.py
```

### 4.4 Real-backend acceptance tests

| Target | Status | Time | Proof file |
|---|---|---|---|
| Real C (MS-BART subprocess + oracle FP) | ✅ PASSED | 6.7 s | `reports/real_run_findings_2026-04-22.md` §"Supplementary observation" |
| Real B (`MSClipRetriever`, hand-built 1-entry pool) | ✅ PASSED after `d050ea4` | 10.4 s | `reports/track_b_followups_2026-04-22.md` §"Acceptance test" |
| Real A2 (real `pubchem_lite.sqlite` + real GNPS CSV) | ✅ PASSED | 331 s (first load) | session transcript, 2026-04-23 09:49 |
| Full real A1→A2→B→C on glucose | ✅ PASSED, with `libraries=["inhouse"]` workaround | 347 s total | session transcript, 2026-04-23 09:56 |

The last line is the one to re-verify once F14+F15 land — after that
the workaround comes out and the modcos path gets exercised.

---

## 5. Real-model run, per tool

### A1 — `spectrum_preprocess`

Status: ✅ always runnable, no external resources.

```python
from schemas import PreprocessRequest
from tools.spectrum_ops import preprocess
spec = preprocess(PreprocessRequest(
    raw_mz=[163.06, 145.05, ...], raw_intensity=[1000, 420, ...],
    precursor_mz=181.0707, adduct="[M+H]+", ionization_mode="positive",
    collision_energy=20.0,
)).spectrum
```

### A2 — `candidate_prefilter`

Status: ✅ real data path runnable with env vars set.

Required env (via `source tools/candidate_prefilter/env.sh`):
- `METAGENT_PUBCHEM_LITE_PATH=/data/weiwentao/llm_agent_metabolomics/pubchem_lite.sqlite`
- `METAGENT_GNPS_PATH=/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned_enriched.csv`

First call is ~5 min (streams 985k-row GNPS CSV and computes InChIKeys).
Subsequent calls in the same process are sub-millisecond (in-memory
mass-sorted index).

For the glucose fixture query:
- 205 candidates returned (158 GNPS, 47 PubChem-Lite)
- 190 with `has_reference_spectrum=True`
- 73 / 205 connectivity-match glucose (all C6H12O6 hexose isomers
  share the same 2D SMILES after stereo-drop)

### B — `library_search`

Status: ✅ real ms-clip path runnable after `d050ea4` (fixes F12/F13).

Required resources:
- `diffms` conda env (torch 2.3.1+cu118, CUDA on this box)
- ms-clip checkpoint at `/data/weiwentao/reconstruct/ms-clip/results/
  chemformer_v4_large_ep3unfroze_20260420_235720/version_0/best.ckpt`
  (pointed to by `METAGENT_MSCLIP_CKPT` or the default)
- ms-pred repo at `/home/weiwentao/workspace/reconstruct/ms-pred`
  (`METAGENT_MSCLIP_REPO` default)

**Real modcos path (F14/F15) currently blocked.** Work around by
passing `libraries=["inhouse"]`, which skips the GNPS reference
lookup. After F14/F15 land, remove the workaround and re-run the
acceptance test in `reports/f14_f15_gnps_loader_followup_2026-04-23.md`.

Wall time for a 30-candidate pool scored by real ms-clip: ~10 s
(dominated by ckpt load; per-candidate dataloading + inference is
fast).

### C — `molecule_generate`

Status: ✅ real MS-BART path runnable.

Required resources:
- `ms-bart` conda env (torch 2.6.0+cu124, transformers 4.57.6, selfies 2.1.1)
- MS-BART checkpoint dir at `/home/weiwentao/workspace/mol_gen/
  MS-BART/data/MassSpecGym/MS-BART-MassSpecGym/csyanghan/
  MS-BART-MassSpecGym` (pointed to by `METAGENT_MSBART_CKPT` or the
  default)
- Optional: SIRIUS binary if using `SiriusFingerprinter` (not
  available on this box; use `GroundTruthFingerprinter` or
  `CandidateFusionFingerprinter` instead)

Wall time for 20 generations: ~7 s.

Important behavioural note: **MS-BART does not predict stereo**. Its
canonical SMILES are stereo-stripped. Integration tests compare
**InChIKey connectivity hashes** (first `-`-separated segment), not
full InChIKeys — see the `split("-")[0]` pattern in
`tests/integration/test_pipeline_e2e.py`. Do the same in any new
end-to-end assertion.

---

## 6. Open findings

Numbering continues from the static audit's F1–F11.

| ID | Severity | Status | Owner | Summary |
|---|---|---|---|---|
| F1 | nit | open | all tracks | Per-test `sys.path` boilerplate duplicated; merge into a shared conftest |
| F2 | major | partial | docs owner | Contract says `has_reference_spectrum` gates modcos; code disagrees (authoritative). `docs/TOOL_CONTRACTS.md § Tool 3` text still needs updating |
| F3 | minor | blocked by F9 | env | `matchms:add_precursor_mz` warning on matchms 0.32+; disappears on pinned 0.24.4 |
| F4 | minor | **fixed** (`53a4357`) | A2 | `example.py` docstring ↔ code mismatch |
| F5 | nit | open | C / docs | Contract says >90% formula match; code is 100% hard filter |
| F6 | major | **fixed** (`dfe2f58`) | A1 | matchms pin bumped 0.24.0 → 0.24.4 |
| F7 | minor | open | A2 | Lazy `import rdkit` (declared, flagged only for awareness) |
| F8 | minor | **fixed** (`d050ea4`) | B | Documented `diffms` env setup |
| F9 | minor | open | env | Base env pin drift; build integration env from unioned pinned `requirements.txt` |
| F10 | nit | open | A1, C | Tool descriptions don't reference the adduct vocabulary |
| F11 | nit | **fixed** (`d050ea4`) | B | `tool_description.md` now documents that ms-clip is not gated by `has_reference_spectrum` |
| F12 | major | **fixed** (`d050ea4`) | B | `_canonicalise_adduct_for_msclip` imports ms_clip in the wrong process |
| F13 | critical | **fixed** (`d050ea4`) | B | `candidates.tsv` was missing `collision_energies` column |
| F14 | critical | **open** | common/ owner | `common/gnps_loader.py` is JSON-only, chokes on CSV/MGF |
| F15 | major | **open** | common/ owner (or B as secondary) | `_load_gnps_records(required=False)` raises instead of degrading |

**Blocking items (need action before day-2 can add the orchestrator):**
F14 and F15. Everything else can ship as-is.

Optional-but-nice-before-day-2:
- Register the `integration` and `requires_*` pytest marks in a root
  `pytest.ini` / `pyproject.toml` so warnings stop cluttering output.
- Build a `metagent-integration` conda env from the union of pinned
  `requirements.txt` (F9). Avoids the matchms 0.32 vs 0.24.4 drift.

---

## 7. How to re-run / continue

### 7.1 One-shot verification

From the repo root:

```bash
# Unit tests
conda run -n diffms --no-capture-output python -m pytest \
    tests/tool_tests/test_spectrum_ops.py \
    tests/tool_tests/test_candidate_prefilter.py \
    tests/tool_tests/test_library_search.py \
    tests/tool_tests/test_molecule_gen.py -v

# Integration tests
conda run -n diffms --no-capture-output python -m pytest tests/integration/ -v

# Smoke
conda run -n diffms --no-capture-output python scripts/audit_tracks.py
```

Expected: **86+3 unit**, **16+4 integration**, exit 0 smoke.

### 7.2 Full real e2e (the 2026-04-23 run)

```bash
source tools/candidate_prefilter/env.sh
conda run -n diffms --no-capture-output python /tmp/e2e_real_glucose.py
```

The script `/tmp/e2e_real_glucose.py` is ephemeral; the shape of it
lives inside this hand-off document (§ 5). Paste it into
`scripts/e2e_real.py` if you want a permanent home. Today's run is
locked into `libraries=["inhouse"]`; remove that line after F14+F15.

### 7.3 Re-verify B's acceptance test (F12/F13 regression guard)

Paste-and-run snippet is in `reports/track_b_followups_2026-04-22.md`
under "Acceptance test" — 7-line bash block. Expected: non-empty
candidates, no "ms-clip scoring failed" in `explain`.

### 7.4 Re-verify Track B's full real path (after F14+F15)

Paste-and-run snippet is in
`reports/f14_f15_gnps_loader_followup_2026-04-23.md` under
"Acceptance test". Use `libraries=["inhouse", "gnps"]` (no
workaround). Expected: candidates list populated, `n_total_compared`
> 0, no `"failed to load GNPS"` anywhere.

---

## 8. External data and env dependencies (inventory)

### 8.1 Required for real runs

| Resource | Path on this box | Size | Provides |
|---|---|---|---|
| PubChem-Lite SQLite | `/data/weiwentao/llm_agent_metabolomics/pubchem_lite.sqlite` | 324 MB | A2's pubchem_lite pool (HMDB 5.0 ingest) |
| GNPS metadata CSV | `/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned_enriched.csv` | 471 MB (985k rows) | A2's GNPS pool (structures, InChIKey, metadata) |
| GNPS MGF | `/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned.mgf` | 1.9 GB | Peaks for B's modcos — not yet consumed (F14) |
| MS-Clip ckpt | `/data/weiwentao/reconstruct/ms-clip/.../best.ckpt` | 1.6 GB | B's ms-clip scoring |
| MS-BART ckpt dir | `/home/weiwentao/workspace/mol_gen/MS-BART/.../MS-BART-MassSpecGym/` | ~500 MB (`pytorch_model.bin`) | C's MS-BART decoder |

### 8.2 Conda environments (non-reproducible today — see F8, F9)

| Env | Role | Key deps verified |
|---|---|---|
| `diffms` | B's ms-clip subprocess + "orchestrator-side" integration tests | Python 3.9, torch 2.3.1+cu118 (CUDA), matchms 0.27.0, pytest 8.4.2 |
| `ms-bart` | C's MS-BART subprocess | Python 3.?, torch 2.6.0+cu124, transformers 4.57.6, selfies 2.1.1 |
| *(base miniconda3)* | not used for integration runs | Python 3.13, matchms 0.32.0 (F9 drift — breaks B's unit tests) |

The per-track `requirements.txt` files pin `pydantic==2.8.2`,
`numpy==1.26.4`, `matchms==0.24.4`, `rdkit==2024.3.5`. A clean
`metagent-integration` conda env built from the union of those pins
is the right way to run day-2's CI; right now the integration session
runs inside `diffms` and relies on API overlap between 0.24.4 and
0.27.0. This works today; it is not a long-term answer.

### 8.3 Environment variables

See `tools/candidate_prefilter/env.sh` for the canonical set. The
env.sh will need a one-line update once F14 lands (point
`METAGENT_GNPS_PATH` at the `.mgf` instead of the `.csv`); decide
that alongside A2 since A2 currently reads the CSV too.

---

## 9. Hand-off checklist for day-2

A session picking up from here should, in order:

1. **Read this file** plus `integration_report_2026-04-22.md` § 1a–1e.
   Skim the three other reports.
2. **Route F14 and F15** to the `common/` owner (or apply them
   yourself if you have authority). Acceptance snippet is in
   `reports/f14_f15_gnps_loader_followup_2026-04-23.md`.
3. **After F14+F15 land:** re-run the full real A1→A2→B→C with
   `libraries=["inhouse","gnps"]` (no workaround). Expect the top-5
   to mostly still be hexose isomers since GNPS has no stereo
   either; the modcos scores will now actually differ per entry
   instead of being missing.
4. **Decide on the integration conda env** (F9). Either build
   `metagent-integration` from the pinned requirements or document
   that `diffms` is the sanctioned runtime. If the former, bring
   `pytest-registered-marks` along so the four `integration` /
   `requires_*` marks in the tracks' test files stop warning.
5. **Merge to master.** Only after F14+F15 are in. Day-1 deliberately
   did not merge `integration-day1 → master`.
6. **If day-2 brings the orchestrator online:** its first acceptance
   should be the real A1→A2→B→C run wired through the LLM planner,
   using the same glucose fixture and the same truth-connectivity
   check that lives in
   `test_pipeline_e2e.py::test_mocked_groundtruth_present_in_top10_union`.
7. **Do not break the integration tests** without landing a matching
   update in this same branch. The mocked suite is the contract guard;
   if a track change makes it red, that change is wrong.

---

## 10. Known-good invocations (quick reference)

Sources `env.sh` inline so every command is copy-paste safe.

```bash
# Unit tests (four tracks only)
conda run -n diffms --no-capture-output python -m pytest \
    tests/tool_tests/test_{spectrum_ops,candidate_prefilter,library_search,molecule_gen}.py -v

# Integration tests
conda run -n diffms --no-capture-output python -m pytest tests/integration/ -v

# Smoke
conda run -n diffms --no-capture-output python scripts/audit_tracks.py

# Real A2 only (needs env.sh)
( source tools/candidate_prefilter/env.sh && \
  conda run -n diffms --no-capture-output python -c "
import sys; sys.path.insert(0, '.')
from schemas import PrefilterRequest
from tools.candidate_prefilter import prefilter
r = prefilter(PrefilterRequest(precursor_mz=181.0707, adduct='[M+H]+',
                                molecular_formula='C6H12O6', mass_tolerance_ppm=5.0))
print(r.explain)
")

# Real B only (hand-built pool)  — see reports/track_b_followups_2026-04-22.md
# Real C only (oracle FP)        — see reports/real_run_findings_2026-04-22.md
# Full real A1→A2→B→C            — see § 7.2 above
```

---

## Index of linked documents

```
reports/
  delivery_day1_integration_2026-04-23.md       ← you are here
  integration_report_2026-04-22.md              ← Part 1 static audit (F1–F11)
  real_run_findings_2026-04-22.md               ← first live-run results (F12, F13)
  track_b_followups_2026-04-22.md               ← action doc for B (F11/F12/F13/F8)
  f14_f15_gnps_loader_followup_2026-04-23.md    ← action doc for common/ (F14/F15)
tests/integration/
  README.md                                      ← how to run + interpret
  conftest.py  test_pipeline_e2e.py  __init__.py
scripts/
  audit_tracks.py                                ← smoke check
```
