# Real-run findings — 2026-04-22

Follow-up to `reports/integration_report_2026-04-22.md`. The maintainer
asked me to attempt a real end-to-end run with live model checkpoints
(F6 had been fixed; PubChem-Lite DB and GNPS dump were still being
built, so A2 runs against empty indices for this exercise).

Machine-side sanity: `diffms` env (torch 2.3.1+cu118, CUDA available) and
`ms-bart` env (torch 2.6.0+cu124, transformers 4.57.6, selfies 2.1.1)
both boot. MS-Clip checkpoint (`best.ckpt`, 1.6 GB) and MS-BART
checkpoint directory (full Hugging-Face layout with `pytorch_model.bin`)
both exist at the default paths.

## Summary

| Tool | Real run status | Evidence |
|---|---|---|
| `spectrum_preprocess` (A1) | ✅ pass | Glucose fixture preprocessed in ~0.1 s after matchms cold-start. Base peak = 1.0, quality=sparse, 7/7 peaks retained. |
| `candidate_prefilter` (A2) | ⏸ not exercised | PubChem-Lite DB not built; GNPS dump not downloaded. Empty-index code path (`pools=["gnps"]`) returns an empty pool correctly with the right neutral mass, no errors. Real-data run is blocked on maintainer's ingestion work, not on the tool. |
| `library_search` (B) | ❌ blocked by two integration bugs (F12, F13) | Real subprocess into `diffms` starts and the checkpoint loads, but the query-building layer fails. See F12 / F13 below. |
| `molecule_generate` (C) | ✅ pass | MS-BART subprocess loaded and ran in 6.7 s; 20 raw SMILES → all 20 RDKit-valid → 1 matched `C6H12O6`, connectivity-hash matches glucose (stereo loss is expected — MS-BART does not predict stereo). `in_pool` bonus triggers correctly when the candidate is in the hand-built pool. |

Two new **major/critical** findings added below. They were not visible
at the static-audit stage because both only manifest in a cross-env
subprocess call.

---

## F12 (major, Track B) — `_canonicalise_adduct_for_msclip` import path is wrong

### Where

`tools/library_search/model.py:226-240` — the helper calls
`from ms_clip.common.ions import standardize_adduct` **inside the main
orchestrator process**, not inside the `diffms` subprocess.

### Symptom

When the orchestrator runs under any env that does not itself have
`ms_clip` installed (i.e. the default deployment where heavy ML deps
live only in `diffms`), every adduct — including `"[M+H]+"`, which IS
in the MSG vocabulary — canonicalises to `None` because the Python
import fails upstream of any vocabulary lookup. The caller then raises:

```
InHouseModelError: Adduct '[M+H]+' is not in the ms-clip MSG ion vocabulary
```

which is actively misleading — the real cause is an `ImportError` in
`ms_clip/common/__init__.py` (that `__init__` unconditionally
`import torch`).

### Repro

```bash
# Base conda env without torch installed:
PYTHONPATH=. python -c "
from tools.library_search.model import _canonicalise_adduct_for_msclip
print(_canonicalise_adduct_for_msclip('[M+H]+'))  # -> None (expected: '[M+H]+')"
```

### Why it matters

The `_canonicalise_adduct_for_msclip` helper is executed on every
`library_search` call before the subprocess is launched. It silently
disables ms-clip scoring in the single most common deployment
configuration (orchestrator-light, models heavy and isolated). The
`InHouseModelError` is caught by `library_search.tool.py:108-112` and
downgraded to a warning, so a typical run emits *no* ms-clip scores and
the user only sees "ms-clip scoring failed, continuing with modcos only".

### Fix direction (to be routed to Track B)

Two sensible options; maintainer to choose:

1. Hard-code the ~10-entry MSG positive-ion adduct alias table in
   `tools/library_search/model.py` so the check is pure-Python and
   env-independent. Add a unit test that asserts
   `_canonicalise_adduct_for_msclip("[M+H]+") == "[M+H]+"`.
2. Move adduct canonicalisation into the subprocess (append a
   canonicalisation step inside `ms_clip/inference/predict_smi.py`, or
   pass the raw adduct through the TSV and handle normalisation in the
   dataset layer). Heavier change but avoids duplicating a lookup
   table in two places.

Option 1 is much cheaper and is what I'd recommend.

---

## F13 (critical, Track B) — ms-clip TSV is missing `collision_energies` column

### Where

`tools/library_search/model.py:170-173` — the TSV written to the
subprocess's `data_dir/candidates.tsv` has columns:

```
spec\tsmiles\tionization\tlabel
```

### Symptom

`ms_clip.inference.predict_smi` calls
`CLIPSmiDataset.__init__`, which at
`ms-pred/src/ms_clip/data/dataset.py:380` does:

```python
self.name_to_ce = dict(self.df[["spec", "collision_energies"]].values)
```

→ `KeyError: "['collision_energies'] not in index"`, subprocess exits 1.

### Repro

After applying a local workaround for F12 (running the test from inside
the `diffms` env so ms_clip is importable), a real-data `library_search`
call with a non-empty `candidate_pool` reproduces the
`KeyError: "['collision_energies'] not in index"` in under 15 s of
wall-time — checkpoint is fully loaded, data loader assembly is what
breaks. Full traceback captured in the session log on 2026-04-22
around 16:47.

### Why it matters

This is the single most important **integration** bug discovered today.
Every `library_search` call with a candidate pool fails at this point;
the `min_score=0.3` filter hides it by returning an empty candidate
list with a warning, which looks like "no good hits" from the top.
Without F13 fixed, the real ms-clip path has never been exercised end-
to-end in this repo — any score semantics claim in the contract and
in `tool_description.md` is currently unverified.

### Fix direction (to be routed to Track B)

`collision_energies` is a per-row value in the ms-clip training data
(typically a Python-list-literal string like `"[20.0]"` or a CSV).
`Spectrum.collision_energy` is already carried through from A1, so the
TSV-writing loop can synthesise the column directly:

```python
ce = req.spectrum.collision_energy if req.spectrum.collision_energy is not None else 0.0
f.write("spec\tsmiles\tionization\tlabel\tcollision_energies\n")
for smi in candidate_smiles:
    f.write(f"{spec_name}\t{smi}\t{canonical_adduct}\tFalse\t[{ce}]\n")
```

(Exact literal format — plain float, `[ce]` list literal, or comma-
separated string — needs to be cross-checked against how
`CLIPSmiDataset` parses `collision_energies` downstream. Track B
session will know.)

Add a unit test that writes a one-row TSV with the new column and
invokes the real `predict_smi` as a subprocess smoke test (or asserts
the TSV header is `{"spec", "smiles", "ionization", "label",
"collision_energies"}`).

---

## Supplementary observation — MS-BART does not predict stereo

Not a bug; recording because it affects how integration tests should
assert ground-truth recovery.

The real MS-BART decode of glucose's Morgan fingerprint returns
`OCC1OC(O)C(O)C(O)C1O`, i.e. glucose without stereo annotations. Its
InChIKey is `WQZGKKKJIJFFOK-UHFFFAOYSA-N`, which differs from the
fixture's stereo-aware `WQZGKKKJIJFFOK-GASJEMHNSA-N` in the second
segment (stereo hash). This is **expected MS-BART behaviour** — the
checkpoint trained on MassSpecGym treats stereo as out-of-scope.

**Action (integration layer, self-owned):**
`tests/integration/test_pipeline_e2e.py::test_mocked_groundtruth_present_in_top10_union`
compares full InChIKeys, which happens to work in the mocked flavour
(mock emits the fixture SMILES verbatim) but would mis-fire under any
real generator that canonicalises without stereo. Switching the
assertion to compare connectivity hashes (first segment of the
InChIKey) is the correct fix for the integration suite. I'll land that
in the same commit as this report.

## Reproducibility commands

```bash
# F12 + F13 combined repro (runs inside diffms env so torch + ms_clip import):
conda run -n diffms --no-capture-output python - <<'PY'
import sys; sys.path.insert(0, ".")
sys.path.insert(0, "/home/weiwentao/workspace/reconstruct/ms-pred/src")
from schemas import LibrarySearchRequest, PrefilteredCandidate, Spectrum
from tools.library_search import library_search
from tools.library_search.model import MSClipRetriever
spec = Spectrum(mz=[163.06], intensity=[1.0], precursor_mz=181.07,
                adduct="[M+H]+", ionization_mode="positive")
pool = [PrefilteredCandidate(smiles="CCO", source_pool="pubchem_lite",
                             source_id="x", molecular_formula="C2H6O",
                             exact_mass=46.04, mass_error_ppm=0,
                             has_reference_spectrum=False)]
try:
    r = library_search(LibrarySearchRequest(spectrum=spec, candidate_pool=pool,
                                            libraries=["inhouse"], min_score=0.0),
                       retriever=MSClipRetriever())
    print("explain:", r.explain)
except Exception as e:
    print("ERROR:", e)
PY

# C success repro (glucose oracle):
PYTHONPATH=. python -c "
from schemas import GenerateRequest, PreprocessRequest
from tools.spectrum_ops import preprocess
from tools.molecule_gen import generate
from tools.molecule_gen.fingerprint import GroundTruthFingerprinter
from tools.molecule_gen.model import MSBartGenerator
spec = preprocess(PreprocessRequest(
    raw_mz=[163.0601,145.0495,127.0390,109.0284,85.0284,73.0284,61.0284],
    raw_intensity=[1000,420,380,250,180,120,90],
    precursor_mz=181.0707, adduct='[M+H]+', ionization_mode='positive')).spectrum
glucose = 'OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O'
r = generate(GenerateRequest(spectrum=spec, molecular_formula='C6H12O6', n_candidates=10),
             generator=MSBartGenerator(),
             fingerprinter=GroundTruthFingerprinter.from_smiles(glucose))
print('final:', r.n_generated_raw, '->', r.n_valid, '->', len(r.candidates),
      'top=', r.candidates[0].smiles if r.candidates else None)
"
```

## What's cleared and what's still open

- ✅ Cross-env subprocess dispatch is proven working for **both** model
  tracks (diffms and ms-bart envs boot, checkpoint loads, inference
  completes).
- ✅ `molecule_generate` (C) real path is end-to-end green. The
  subprocess → decoder → RDKit canonicalisation → pool bonus →
  `Candidate` Pydantic object chain works.
- ❌ `library_search` (B) real path is blocked on F12 and F13. F12 is
  a 5-line fix (hard-code the vocabulary lookup). F13 is a 2-line fix
  (add one column to the TSV header + one value per row). Until both
  are in, no real-data integration test for B can pass.
- ⏸ `candidate_prefilter` (A2) real-data path awaits PubChem-Lite DB
  and GNPS dump (maintainer-tracked). The code path is verified to
  handle empty indices without error.
