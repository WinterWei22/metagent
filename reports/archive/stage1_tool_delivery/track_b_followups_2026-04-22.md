# Track B — action items from day-1 integration

**For:** the Track B (`library_search`) session
**From:** integration session (`integration-day1` branch)
**Date:** 2026-04-22
**Priority order:** F13 (critical) → F12 (major) → F11 (nit) → F8 (minor, ops).

Parent reports (context):
- `reports/integration_report_2026-04-22.md` — static audit
- `reports/real_run_findings_2026-04-22.md` — live subprocess run

**Acceptance test** (what "done" looks like for this whole ticket): after
F12 and F13 land, the following end-to-end invocation — executed on the
integration-day1 branch with a hand-built `candidate_pool`, a real
MS-Clip checkpoint (`/data/weiwentao/reconstruct/ms-clip/.../best.ckpt`),
and no further orchestrator-env torch install — must return a non-empty
`candidates` list and not emit the `"ms-clip scoring failed"` warning:

```bash
PYTHONPATH=. python - <<'PY'
from schemas import LibrarySearchRequest, PrefilteredCandidate, Spectrum
from tools.library_search import library_search
from tools.library_search.model import MSClipRetriever
spec = Spectrum(mz=[163.06, 145.05, 127.04], intensity=[1.0, 0.4, 0.3],
                precursor_mz=181.07, adduct="[M+H]+", ionization_mode="positive",
                collision_energy=20.0)
pool = [PrefilteredCandidate(
    smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O", name="glucose",
    source_pool="pubchem_lite", source_id="HMDB0000122",
    molecular_formula="C6H12O6", exact_mass=180.0634,
    mass_error_ppm=0.2, has_reference_spectrum=False,
)]
r = library_search(
    LibrarySearchRequest(spectrum=spec, candidate_pool=pool,
                         libraries=["inhouse"], min_score=0.0),
    retriever=MSClipRetriever(),
)
print(r.explain)
assert r.candidates, "expected at least one candidate from ms-clip"
assert "ms-clip scoring failed" not in r.explain
PY
```

The integration suite's real-path test
(`tests/integration/test_pipeline_e2e.py::test_realmodel_groundtruth_top10_union_across_fixtures`)
will also flip from SKIP to PASS once both fixes are in and the
PubChem-Lite / GNPS resources are wired.

---

## F13 — `candidates.tsv` missing `collision_energies` column (critical)

### What's broken

`tools/library_search/model.py:170-173` — `MSClipRetriever.score_candidates`
writes the subprocess's `data_dir/candidates.tsv` with a four-column
header:

```python
f.write("spec\tsmiles\tionization\tlabel\n")
for smi in candidate_smiles:
    f.write(f"{spec_name}\t{smi}\t{canonical_adduct}\tFalse\n")
```

ms-clip's `CLIPSmiDataset.__init__` (at
`/home/weiwentao/workspace/reconstruct/ms-pred/src/ms_clip/data/dataset.py:380`)
then does:

```python
self.name_to_ce = dict(self.df[["spec", "collision_energies"]].values)
```

which raises `KeyError: "['collision_energies'] not in index"` and the
subprocess exits 1. Our `score_candidates` catches the non-zero exit and
downgrades to `InHouseModelError`, which `library_search` further
downgrades to a `"ms-clip scoring failed, continuing with modcos only"`
warning. End result: **the real ms-clip path has never scored a single
candidate in this repo**; every apparently-working test run was
silently falling through to modified-cosine or to the MockInHouseRetriever.

### Repro

Inside the `diffms` env (so `torch` is importable and the
F12 import path doesn't bite first):

```bash
conda run -n diffms --no-capture-output python - <<'PY'
import sys; sys.path[:0] = [".", "/home/weiwentao/workspace/reconstruct/ms-pred/src"]
from schemas import LibrarySearchRequest, PrefilteredCandidate, Spectrum
from tools.library_search import library_search
from tools.library_search.model import MSClipRetriever
spec = Spectrum(mz=[163.06], intensity=[1.0], precursor_mz=181.07,
                adduct="[M+H]+", ionization_mode="positive", collision_energy=20.0)
pool = [PrefilteredCandidate(smiles="CCO", source_pool="pubchem_lite",
        source_id="x", molecular_formula="C2H6O", exact_mass=46.04,
        mass_error_ppm=0, has_reference_spectrum=False)]
r = library_search(LibrarySearchRequest(spectrum=spec, candidate_pool=pool,
                                        libraries=["inhouse"], min_score=0.0),
                   retriever=MSClipRetriever())
print(r.explain)
PY
```

Expect:
```
ms-clip scoring failed, continuing with modcos only: ms-clip subprocess
failed (exit 1): ... KeyError: "['collision_energies'] not in index"
```

### Suggested fix

Synthesise the column from `Spectrum.collision_energy` — which A1 already
carries through unchanged, per `schemas/common.py:63-64`. Patch sketch:

```python
# tools/library_search/model.py, around line 168
ce = req.spectrum.collision_energy if req.spectrum.collision_energy is not None else 0.0
with open(data_dir / labels_file, "w") as f:
    f.write("spec\tsmiles\tionization\tlabel\tcollision_energies\n")
    for smi in candidate_smiles:
        f.write(f"{spec_name}\t{smi}\t{canonical_adduct}\tFalse\t[{ce}]\n")
```

(Note: `score_candidates` currently doesn't receive the full `Spectrum`,
just `query_mz / query_intensity / query_precursor_mz / adduct`. You'll
need to thread `collision_energy` through the same way — either add it
as a kwarg and have `library_search._build_..._target` pass it in, or
pass the whole Spectrum. The Spectrum-pass approach is cleaner and makes
F12's hard-coded vocab less ugly too.)

**Format uncertainty to verify on your side:** I wrote `[{ce}]` as a
list-literal string since that's how MassSpecGym training TSVs carry
`collision_energies`. If `CLIPSmiDataset` parses it differently (plain
float, semicolon-separated list, etc.) adjust accordingly — the
`dataset.py:380` call creates `name_to_ce` by taking the value verbatim,
so check where `name_to_ce` gets consumed to know the expected type.

### Test to add in `tests/tool_tests/test_library_search.py`

A pure TSV-shape unit test that doesn't require the subprocess:

```python
def test_ms_clip_candidates_tsv_header_has_collision_energies(tmp_path, monkeypatch):
    """Regression guard for F13: TSV header must include collision_energies,
    otherwise CLIPSmiDataset.__init__ KeyErrors on the column lookup."""
    # Monkey-patch subprocess.run so we capture the written files without
    # actually launching the conda-run child.
    captured = {}
    def fake_run(cmd, **kw):
        # Find data_dir in cmd arguments, read candidates.tsv there.
        for arg in cmd:
            if arg.startswith("data.data_dir="):
                p = arg.split("=", 1)[1]
                tsv = (Path(p) / "candidates.tsv").read_text()
                captured["tsv"] = tsv
                break
        # Pretend it ran successfully but produced an empty pickle.
        ...
    monkeypatch.setattr(subprocess, "run", fake_run)
    # ... call MSClipRetriever(...).score_candidates(...)
    header = captured["tsv"].splitlines()[0].split("\t")
    assert "collision_energies" in header
```

---

## F12 — `_canonicalise_adduct_for_msclip` imports ms_clip in the wrong process (major)

### What's broken

`tools/library_search/model.py:226-240`:

```python
def _canonicalise_adduct_for_msclip(adduct: str) -> str | None:
    try:
        from ms_clip.common.ions import standardize_adduct
    except Exception as exc:
        logger.debug("ms_clip.common.ions unavailable: %s", exc)
        return None
    try:
        return standardize_adduct(adduct)
    except Exception:
        return None
```

Called from `score_candidates` **in the main orchestrator process**,
before the subprocess is launched. That process runs in whatever env the
orchestrator uses — by the deployment contract, a lightweight env
without torch. `ms_clip.common.__init__` at
`/home/weiwentao/workspace/reconstruct/ms-pred/src/ms_clip/common/__init__.py:2`
unconditionally imports `ms_clip.common.chem`, which in turn
`import torch` — so the whole package fails to import and
`standardize_adduct` never runs. `_canonicalise_adduct_for_msclip`
returns `None` for every input, and the caller at `model.py:141-146`
raises:

```
InHouseModelError: Adduct '[M+H]+' is not in the ms-clip MSG ion vocabulary
```

This is actively misleading — `"[M+H]+"` **is** the first entry in
`ms_clip.common.ions.ion2onehot_pos`. The helper just never reaches the
lookup.

### Repro

Any env without torch (e.g. the base miniconda where the orchestrator
is expected to live):

```bash
/home/weiwentao/miniconda3/bin/python -c "
import sys; sys.path[:0] = ['.', '/home/weiwentao/workspace/reconstruct/ms-pred/src']
from tools.library_search.model import _canonicalise_adduct_for_msclip
print(repr(_canonicalise_adduct_for_msclip('[M+H]+')))  # prints: None
"
```

### Suggested fix

Hard-code the MSG vocabulary lookup in `tools/library_search/model.py`
so the check is pure Python and env-independent. The full table is 10
entries; the code already imports nothing more exotic than `logger`
from stdlib, so this is a purely local change:

```python
# tools/library_search/model.py — replace _canonicalise_adduct_for_msclip
_MSCLIP_ION_REMAP: dict[str, str] = {
    "[M+H]+":       "[M+H]+",
    "[M+Na]+":      "[M+Na]+",
    "[M+K]+":       "[M+K]+",
    "[M-H2O+H]+":   "[M-H2O+H]+",
    "[M+H-H2O]+":   "[M-H2O+H]+",
    "[M+H3N+H]+":   "[M+H3N+H]+",
    "[M+NH4]+":     "[M+H3N+H]+",
    "[M]+":         "[M]+",
    "[M-H4O2+H]+":  "[M-H4O2+H]+",
    "[M+H-2H2O]+":  "[M-H4O2+H]+",
    "[M-2H2O+H]+":  "[M-H4O2+H]+",
    # aliases seen in the wild:
    "M+H":      "[M+H]+",
    "M+Na":     "[M+Na]+",
    "M+H-H2O":  "[M-H2O+H]+",
    "M+NH4":    "[M+H3N+H]+",
}

def _canonicalise_adduct_for_msclip(adduct: str) -> str | None:
    """Return the canonical MSG adduct string, or None if not supported.

    Mirrors ms_clip.common.ions.standardize_adduct but stays env-
    independent so it runs in the orchestrator process without needing
    torch. Kept in sync with that module: if ms-pred adds a new ion,
    mirror it here.
    """
    return _MSCLIP_ION_REMAP.get(adduct.replace(" ", ""))
```

### Cross-check

`supported_adducts()` in `tools/candidate_prefilter/adducts.py` exposes
the A2 side's vocabulary. F12's hard-coded table should be a **subset**
of A2's — A2 supports a wider catalog (negative-mode, dimers, acetate,
formate) that ms-clip's positive-only MSG model doesn't. If a caller
passes an adduct A2 accepts but ms-clip doesn't, `score_candidates`
returning `InHouseModelError` with the old (now-accurate) message
`"Adduct {adduct!r} is not in the ms-clip MSG ion vocabulary"` is the
right behaviour — just make sure the error fires **only** when the
adduct is genuinely out-of-vocab, not when the import failed.

### Test to add

```python
def test_canonicalise_adduct_for_msclip_works_without_torch():
    """Regression guard for F12: the helper must not depend on ms_clip
    being importable — that package often lives only in the diffms env."""
    from tools.library_search.model import _canonicalise_adduct_for_msclip
    assert _canonicalise_adduct_for_msclip("[M+H]+") == "[M+H]+"
    assert _canonicalise_adduct_for_msclip("[M+NH4]+") == "[M+H3N+H]+"
    assert _canonicalise_adduct_for_msclip("M+H") == "[M+H]+"
    assert _canonicalise_adduct_for_msclip("[M+WeirdAdduct]+") is None
```

---

## F11 — `tool_description.md` silent on the ms-clip-not-gated-by-`has_reference_spectrum` behaviour (nit)

### What's broken

`tools/library_search/tool_description.md` under "Inputs" (around the
`candidate_pool` row) says:

> "When provided, scoring is restricted to these candidates: ms-clip
>  scores every one; modified cosine scores the subset whose
>  `source_id` resolves in the loaded GNPS pool."

That's accurate for the code, but contract readers only see
`docs/TOOL_CONTRACTS.md` which still says (`§ Tool 3`, "Input" section):

> "When provided, only candidates with `has_reference_spectrum=True`
>  are compared."

The maintainer ruled on 2026-04-22 that **the code is authoritative** —
the `has_reference_spectrum` gate was intentionally dropped when
ms-clip landed. The contract needs updating, and the tool description
should explicitly say "the `has_reference_spectrum` flag is informational
only — ms-clip scores every candidate regardless of it", so a future
reader of the tool_description doesn't think the gate still applies.

This F11 action is **docs only inside Track B's scope**; the
`docs/TOOL_CONTRACTS.md` update (F2) belongs to the docs owner and is
tracked separately.

### Suggested fix

One sentence in `tool_description.md` under the `candidate_pool` row,
and a parallel sentence in the "When to call" section. For example:

```markdown
| `candidate_pool` | ... ms-clip scores every candidate in the pool
  regardless of its `has_reference_spectrum` flag; modified cosine only
  scores candidates whose `source_id` resolves to a reference spectrum
  in the loaded GNPS pool. ... |
```

No code change.

---

## F8 — `diffms` conda env is not reproducible from the repo (minor, ops)

### What's broken

`tools/library_search/model.py` requires a pre-built `diffms` conda env
(`METAGENT_MSCLIP_ENV`, default `"diffms"`) to exist on the host. There
is no `environment.yml`, Dockerfile, or README section that tells an
operator how to build it — on this machine the env exists (torch
2.3.1+cu118 + ms-pred's deps) but that was built out-of-band.

### Suggested fix

Not urgent for day-1 integration — the env is one-per-machine and the
Track B README can defer to an upstream ms-pred env recipe. But before
handing the repo off to a second deployer, either:

1. Ship `docker/library_search_diffms.Dockerfile` with the recipe, and
   link it from `tool_description.md`'s deployment section.
2. Add a `tools/library_search/DIFFMS_SETUP.md` that replays the
   `conda env create -f …` / `pip install ms-pred` steps.

Mirrors what A2 already did with `README_PUBCHEM_SETUP.md` and what C
mentions for the `ms-bart` env in its tool description.

---

## Not-an-action, for awareness

- **F3 (minor, matchms warning noise)** — `matchms:add_precursor_mz`
  warns "No precursor_mz found in metadata" under matchms 0.32.x. This
  goes away automatically once the integration env is built from the
  union of pinned `requirements.txt` files (matchms 0.24.4 after A1's
  F6 bump). No Track B code change needed.

## Scope reminder

Per the integration session's rules, I (the integration session) did
not modify any file under `tools/library_search/`. The patches above
are **sketches for Track B to apply** — please land them in
`track-b-library-search` (or whichever branch the orchestrator merges
from next), and let the integration session know when F13 and F12 are
in so the real-path e2e test can be re-run.
