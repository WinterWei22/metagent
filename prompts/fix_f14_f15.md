# Claude Code task: land F14 + F15 fixes

You are fixing two bugs in the MetAgent day-1 integration repo. Work
on the `integration-day1` branch. When done, run the acceptance test
and commit. **You have authority to modify `common/gnps_loader.py`,
`tools/library_search/tool.py`, and `tools/candidate_prefilter/env.sh`.
Do not modify anything else under `tools/` or `schemas/`.**

## Context (don't re-derive — take as given)

- Repo root: `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5`
- Current branch: `integration-day1`
- `common/gnps_loader.py::iter_records` unconditionally `json.load(f)`s
  the path, which crashes on the 2026-04 GNPS2 CSV/MGF distribution.
  Fix: dispatch on file extension.
- `tools/library_search/tool.py::_load_gnps_records` raises on load
  failure regardless of its `required` flag. Fix: honour `required=False`.
- A2 already reads `METAGENT_GNPS_PATH` as a CSV for its own mass
  index (`tools/candidate_prefilter/gnps_index.py`). **Do not touch A2.**
  Introduce a new env var `METAGENT_GNPS_SPECTRA_PATH` pointing at the
  MGF for B's use.

## Fixed design decisions (don't second-guess)

1. **Two env vars.** `METAGENT_GNPS_PATH` stays as the CSV path for A2.
   `METAGENT_GNPS_SPECTRA_PATH` is new and points at an MGF for B.
2. `common.gnps_loader.iter_records(path)` dispatches on `Path(path).suffix`:
   `.json` → existing JSON loop (preserve the current behaviour exactly),
   `.mgf`  → new MGF reader below,
   `.csv`  → raise `ValueError` with a message pointing at the MGF.
3. B's `_load_gnps_records` reads `METAGENT_GNPS_SPECTRA_PATH` (new),
   **not** `METAGENT_GNPS_PATH`. If the new var is unset fall back to
   deriving `.mgf` from `METAGENT_GNPS_PATH` if that path ends in `.csv`
   (swap `.csv` → `.mgf` in the same dir); if neither works, treat it as
   "no GNPS available" with the `required`-aware logic below.
4. No destructive ops on git; create normal commits.

## Scope of changes (exhaustive — you may modify only these files)

- `common/gnps_loader.py`
- `tools/library_search/tool.py` (only the `GNPS_PATH_ENV` constant and
  the `_load_gnps_records` function body)
- `tools/candidate_prefilter/env.sh` (add the new export, don't change
  existing ones)
- `tests/tool_tests/test_gnps_loader.py` (new file, if it doesn't exist)
- `tests/tool_tests/test_library_search.py` (append one new test)

## Tasks in order

### 1. Add extension dispatch to `common/gnps_loader.py`

Rename the current `iter_records` body to a new private
`_iter_records_json(path)` (keep its body byte-identical). Write a new
`iter_records(path)` that:

- Converts `path` to `pathlib.Path`.
- If suffix is `.json`: yield from `_iter_records_json(path)`.
- If suffix is `.mgf`: yield from new `_iter_records_mgf(path)`.
- If suffix is `.csv`: raise `ValueError` with message
  `f"{path} is a CSV metadata file with no peak column; it cannot support MS/MS retrieval. Point METAGENT_GNPS_SPECTRA_PATH at the companion .mgf file instead."`
- Any other suffix: raise `ValueError(f"Unsupported GNPS dump extension: {suffix!r}")`.

Write `_iter_records_mgf(path)` and `_mgf_block_to_record(meta, peaks)`
as follows:

```python
def _iter_records_mgf(path: Path) -> Iterator[GnpsRecord]:
    """Stream an MGF file into GnpsRecords.

    Parses BEGIN IONS / END IONS blocks. KEY=VALUE header lines (case-
    insensitive; keys normalised to uppercase) populate metadata. Other
    non-empty lines inside a block are '<mz> <intensity>' peaks.
    """
    with open(path) as f:
        in_block = False
        meta: dict[str, str] = {}
        peaks: list[tuple[float, float]] = []
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s == "BEGIN IONS":
                in_block, meta, peaks = True, {}, []
                continue
            if s == "END IONS":
                if in_block:
                    try:
                        yield _mgf_block_to_record(meta, peaks)
                    except Exception as e:
                        sid = meta.get("SPECTRUM_ID") or meta.get("SPECTRUMID") or "<unknown>"
                        logger.warning("Failed to parse MGF block %s: %s", sid, e)
                in_block = False
                continue
            if not in_block:
                continue
            # KEY=VALUE header vs '<mz> <intensity>' peak
            if "=" in s and not s[0].isdigit() and not s[0] in "+-.":
                k, _, v = s.partition("=")
                meta[k.strip().upper()] = v.strip()
            else:
                parts = s.split()
                if len(parts) >= 2:
                    try:
                        peaks.append((float(parts[0]), float(parts[1])))
                    except ValueError:
                        continue


def _mgf_block_to_record(meta: dict, peaks: list[tuple[float, float]]) -> GnpsRecord:
    """Flatten one MGF block into a GnpsRecord using the shared helpers."""
    spec_id = meta.get("SPECTRUM_ID") or meta.get("SPECTRUMID") or meta.get("TITLE") or ""
    precursor_raw = meta.get("PRECURSOR_MZ")
    if not precursor_raw:
        pep = meta.get("PEPMASS", "").split()
        precursor_raw = pep[0] if pep else None
    ms_level_raw = meta.get("MS_LEVEL") or meta.get("MSLEVEL")
    return GnpsRecord(
        spectrum_id=str(spec_id),
        compound_name=_clean_na(meta.get("COMPOUND_NAME")),
        smiles=_clean_na(meta.get("SMILES")),
        inchi=_clean_na(meta.get("INCHI")),
        inchikey=_clean_na(meta.get("INCHIKEY") or meta.get("INCHIKEY_SMILES")),
        instrument=_clean_na(meta.get("MS_MASS_ANALYZER") or meta.get("INSTRUMENT")),
        ion_source=_clean_na(meta.get("MS_IONISATION") or meta.get("ION_SOURCE")),
        ion_mode=_parse_ion_mode(meta.get("IONMODE") or meta.get("ION_MODE")),
        adduct=_normalise_adduct(meta.get("ADDUCT")),
        precursor_mz=_parse_precursor_mz(precursor_raw),
        ms_level=_parse_ms_level(ms_level_raw),
        peaks=sorted(peaks, key=lambda p: p[0]),
        library_membership=_clean_na(meta.get("GNPS_LIBRARY_MEMBERSHIP") or meta.get("LIBRARY_MEMBERSHIP")),
        library_quality=_parse_quality(meta.get("LIBRARYQUALITY")),
    )
```

### 2. Honour `required=False` in B's `_load_gnps_records`

In `tools/library_search/tool.py`:

- At the top of the module, add a new constant next to `GNPS_PATH_ENV`:
  ```python
  GNPS_SPECTRA_PATH_ENV = "METAGENT_GNPS_SPECTRA_PATH"
  ```
- Change `_load_gnps_records` to (a) look up the spectra path from the
  new env var, falling back to deriving `.mgf` from a `.csv` value of
  `METAGENT_GNPS_PATH` if present, and (b) return `None` instead of
  raising when `required is False`:

```python
def _load_gnps_records(*, records: list | None, required: bool) -> list | None:
    if records is not None:
        return records
    global _GNPS_CACHE
    if _GNPS_CACHE is not None:
        return _GNPS_CACHE

    path = os.environ.get(GNPS_SPECTRA_PATH_ENV)
    if not path:
        meta_path = os.environ.get(GNPS_PATH_ENV)
        if meta_path and meta_path.endswith(".csv"):
            candidate = meta_path[:-4] + ".mgf"
            if os.path.exists(candidate):
                path = candidate
    if not path:
        if required:
            raise LibraryUnavailableError(
                f"{GNPS_SPECTRA_PATH_ENV} is not set; cannot scan GNPS for peaks. "
                "Provide a candidate_pool or set the env var."
            )
        logger.warning(
            "%s unset and cannot derive from %s; continuing without reference peaks.",
            GNPS_SPECTRA_PATH_ENV, GNPS_PATH_ENV,
        )
        return None

    try:
        from common.gnps_loader import load_v0_usable
        _GNPS_CACHE = load_v0_usable(path)
        return _GNPS_CACHE
    except Exception as exc:
        if required:
            raise LibraryUnavailableError(f"failed to load GNPS from {path}: {exc}") from exc
        logger.warning(
            "GNPS load failed (%s: %s); continuing without reference peaks.",
            type(exc).__name__, exc,
        )
        return None
```

### 3. Update `tools/candidate_prefilter/env.sh`

Add, next to the existing `METAGENT_GNPS_PATH` export, a new line:

```bash
# MGF companion dump for library_search (peaks + precursor).
# library_search uses this; candidate_prefilter keeps using the CSV above.
export METAGENT_GNPS_SPECTRA_PATH="${_DATA_ROOT}/gnps/ALL_GNPS_cleaned.mgf"
```

Extend the sanity-check loop at the bottom of the file to include
`METAGENT_GNPS_SPECTRA_PATH` in the `for _var in …` list.

### 4. Add tests

Create `tests/tool_tests/test_gnps_loader.py` with three cases:

- `test_iter_records_dispatches_on_extension_json(tmp_path)` — write a
  minimal 1-record JSON, assert 1 record parsed with 3 peaks.
- `test_iter_records_dispatches_on_extension_mgf(tmp_path)` — write a
  minimal MGF block with SPECTRUM_ID, ADDUCT, ION_MODE, PRECURSOR_MZ,
  SMILES, plus 3 peaks; assert 1 record parsed with 3 peaks and the
  right SPECTRUM_ID.
- `test_iter_records_rejects_csv_with_helpful_message(tmp_path)` — write
  a 2-line CSV; assert `pytest.raises(ValueError, match="no peak column")`.

The first test's JSON body:
```python
'[{"spectrum_id": "X1", "Adduct": "[M+H]+", "Ion_Mode": "Positive", '
'"Precursor_MZ": "123.45", "Smiles": "CCO", '
'"peaks_json": "[[100,1],[120,0.5],[123,0.1]]"}]'
```

The MGF test's body:
```
BEGIN IONS
SPECTRUM_ID=X1
ADDUCT=[M+H]+
ION_MODE=positive
PRECURSOR_MZ=123.45
SMILES=CCO
100.0 1.0
120.0 0.5
123.0 0.1
END IONS
```

Add to `tests/tool_tests/test_library_search.py` one new regression test
named `test_gnps_load_failure_with_pool_degrades_gracefully`:
monkeypatch `METAGENT_GNPS_SPECTRA_PATH` to a non-existent path, call
`library_search` with a 1-entry `source_pool="gnps"` pool and
`libraries=["inhouse", "gnps"]`, pass a `MockInHouseRetriever({"CCO": 0.8})`,
min_score=0.0, and assert `resp.candidates` is non-empty (ms-clip
pass-through), with no raise. Clear the module-level GNPS cache with
`tools.library_search.clear_gnps_cache()` at the start.

### 5. Verification

Run, from the repo root:

```bash
# Unit tests (four tracks + new loader test)
conda run -n diffms --no-capture-output python -m pytest \
    tests/tool_tests/test_spectrum_ops.py \
    tests/tool_tests/test_candidate_prefilter.py \
    tests/tool_tests/test_library_search.py \
    tests/tool_tests/test_molecule_gen.py \
    tests/tool_tests/test_gnps_loader.py -v

# Integration suite
conda run -n diffms --no-capture-output python -m pytest tests/integration/ -v

# Acceptance: full real B path WITHOUT the inhouse-only workaround
source tools/candidate_prefilter/env.sh
conda run -n diffms --no-capture-output python - <<'PY'
import sys, time, json
sys.path.insert(0, ".")
from pathlib import Path
from schemas import (LibrarySearchRequest, PrefilterRequest, PreprocessRequest)
from tools.spectrum_ops import preprocess
from tools.candidate_prefilter import prefilter
from tools.library_search import library_search
from tools.library_search.model import MSClipRetriever

fx = json.loads(Path("tests/fixtures/spectra/glucose_pos.json").read_text())
spec = preprocess(PreprocessRequest(
    raw_mz=[p[0] for p in fx["peaks"]], raw_intensity=[p[1] for p in fx["peaks"]],
    precursor_mz=fx["precursor_mz"], adduct=fx["adduct"],
    ionization_mode=fx["ionization_mode"], collision_energy=fx["collision_energy"],
)).spectrum
pool = prefilter(PrefilterRequest(precursor_mz=spec.precursor_mz,
    adduct=spec.adduct, molecular_formula="C6H12O6", mass_tolerance_ppm=5.0)).candidates
t0 = time.perf_counter()
r = library_search(
    LibrarySearchRequest(spectrum=spec, candidate_pool=pool[:30], top_k=10,
                         min_score=0.0, libraries=["inhouse", "gnps"]),
    retriever=MSClipRetriever(),
)
print(f"elapsed={time.perf_counter()-t0:.1f}s n={len(r.candidates)}")
print(f"explain: {r.explain}")
assert r.candidates, "modcos + ms-clip should return at least one candidate"
assert "ms-clip scoring failed" not in r.explain
assert "failed to load GNPS" not in r.explain
print("ACCEPTANCE PASSED")
PY
```

**Done-when:**
- All three pytest runs are green (existing counts: 86+3 unit, 16+4
  integration; plus your new tests add 3–4 more passing).
- The acceptance snippet prints `ACCEPTANCE PASSED`.
- First A2 call may take ~5 min (GNPS CSV load) — that's fine.

### 6. Commit

One commit, message:

```
fix(common.gnps_loader): F14 extension dispatch + F15 required-aware load

F14: iter_records now dispatches on file extension — .json keeps the
existing behaviour, .mgf uses a new streaming parser that flattens
BEGIN IONS/END IONS blocks via the shared _parse_* / _normalise_adduct
helpers, .csv raises a clear error pointing at the companion .mgf.

F15: _load_gnps_records honours its `required` parameter. When the
new METAGENT_GNPS_SPECTRA_PATH env var is unset (or auto-derived .mgf
isn't on disk) and required=False, it logs a warning and returns None
instead of crashing — library_search degrades to ms-clip-only as the
contract intended.

env.sh grows a METAGENT_GNPS_SPECTRA_PATH export pointing at
ALL_GNPS_cleaned.mgf; METAGENT_GNPS_PATH (CSV, A2-only) is unchanged.

Tests: three new cases in tests/tool_tests/test_gnps_loader.py
exercise the three dispatch paths; one new case in
test_library_search.py asserts library_search degrades gracefully
when GNPS is unreachable.

Acceptance: the full real A1→A2→B pipeline on the glucose fixture
now runs with libraries=["inhouse","gnps"] (no workaround) and
returns a non-empty candidate list.
```

## If something goes wrong

- If the acceptance snippet crashes with `libraries=["inhouse","gnps"]`,
  **do not** re-introduce the `libraries=["inhouse"]` workaround. Debug
  the underlying cause and fix it (or ask).
- If `tests/tool_tests/test_gnps_loader.py` fails due to missing
  `tests/tool_tests/__init__.py`, don't add it — existing track tests
  run without one, so something else is wrong. Investigate.
- If A2's `candidate_prefilter` starts failing because it was reading
  `METAGENT_GNPS_SPECTRA_PATH` somewhere you didn't expect, you went
  beyond scope. Revert the A2-touching change; A2 reads the CSV only.
- **Do not** modify `tools/candidate_prefilter/gnps_index.py`,
  `schemas/`, `docs/`, or any other `tools/*/` directory. If you think
  you need to, stop and escalate.

## Supporting material

Longer context in `reports/f14_f15_gnps_loader_followup_2026-04-23.md`
— read only if you need background; it is not required to do the work.
