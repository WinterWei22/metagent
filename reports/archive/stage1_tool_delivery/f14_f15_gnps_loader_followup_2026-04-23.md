# F14 / F15 — GNPS loader does not support CSV / MGF (real-run follow-up)

**For:** the `common/` owner (maintainer) — these affect a cross-tool shared
utility, not any single track
**From:** integration session (`integration-day1` branch)
**Date:** 2026-04-23
**Discovered during:** `/tmp/e2e_real_glucose.py` real-run, 2026-04-23 09:43
**Prior reports:**
- `reports/integration_report_2026-04-22.md`
- `reports/real_run_findings_2026-04-22.md`
- `reports/track_b_followups_2026-04-22.md`

## TL;DR

After F6 / F12 / F13 / F4 landed, a full real A1→A2→B→C run on the glucose
fixture succeeded — **but only with a workaround** (`libraries=["inhouse"]`
on the `library_search` call) that bypasses B's modified-cosine path.
Remove the workaround and B crashes:

```
tools.library_search.errors.LibraryUnavailableError:
  failed to load GNPS from /data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned_enriched.csv:
  Expecting value: line 1 column 1 (char 0)
```

Two underlying defects:

- **F14 (critical)** — `common/gnps_loader.py` assumes the GNPS dump is
  the legacy `ALL_GNPS_NO_PROPOGATED.json`. Track A2 switched the on-disk
  dump to the 2026-04 GNPS2 distribution (a `.csv` of metadata with a
  companion `.mgf` of peaks) and taught its own
  `tools/candidate_prefilter/gnps_index.py` to dispatch on file extension.
  `common/gnps_loader.py` was not updated. B still calls
  `load_v0_usable(path)` which does `json.load(f)` on what is actually a
  CSV header, and blows up immediately.
- **F15 (major)** — `tools/library_search/tool.py:318-324`'s
  `_load_gnps_records(required=False)` raises `LibraryUnavailableError`
  unconditionally when the load fails, ignoring its own `required`
  parameter. The call site at `tool.py:240-244` passes `required=False`
  precisely so an unreadable GNPS path degrades to "no modcos, ms-clip
  only"; today it crashes the whole `library_search` call instead.

F14 is the *cause*. F15 is the reason F14 leaks all the way to the
caller instead of silently degrading to an ms-clip-only result.

## Why the integration session raises both together

They are cheap to fix together and have the same acceptance test
(below). Fixing only F15 would make the crash quieter but still leave
the modcos path inoperative. Fixing only F14 would make the modcos
path work but leave the `required=False` contract broken for any
future GNPS outage. Landing both means a real CSV/MGF dataset fully
exercises both tools.

## F14 — `common/gnps_loader.py` hard-codes JSON input

### Where

`common/gnps_loader.py:268-283` — `iter_records(path)` opens the file
and calls `json.load(f)` with no extension check:

```python
def iter_records(path: str | Path) -> Iterator[GnpsRecord]:
    ...
    with open(path) as f:
        raw_list = json.load(f)
    for raw in raw_list:
        ...
```

`load_v0_usable(path)` (at :286) just wraps `iter_records`.

### Repro

```bash
source tools/candidate_prefilter/env.sh   # points METAGENT_GNPS_PATH at the real CSV
conda run -n diffms --no-capture-output python - <<'PY'
import sys, os
sys.path.insert(0, ".")
from common.gnps_loader import load_v0_usable
try:
    load_v0_usable(os.environ["METAGENT_GNPS_PATH"])
except Exception as e:
    print(f"{type(e).__name__}: {e}")
PY
```

Expect: `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.

### On-disk layout today (2026-04-22 build)

`/data/weiwentao/llm_agent_metabolomics/gnps/`:

| File | Size | Role |
|---|---|---|
| `ALL_GNPS_cleaned_enriched.csv` | 471 MB | metadata only — 985k rows incl. `spectrum_id`, `Adduct`, `Precursor_MZ`, `Smiles`, `InChIKey_smiles`, `Compound_Name`, `Ion_Mode`, `collision_energy`, `classyfire_*`, etc. **No peaks column.** |
| `ALL_GNPS_cleaned.mgf` | 1.9 GB | MGF — per-spectrum block with TITLE/ADDUCT/SMILES/SPECTRUMID/ION_MODE/PEPMASS etc. plus peak list |
| `cleaned_spectra.mgf` | 2.5 GB | MGF — alternate key casing (lowercase `ionmode=positive`); same content shape |

Neither MGF depends on the CSV for B's needs: each MGF `BEGIN IONS` block
already carries SPECTRUM_ID, ADDUCT, SMILES, PRECURSOR_MZ, ION_MODE,
MS_LEVEL, and the peaks. A CSV-only load is unable to supply peaks and
therefore cannot support B's modified-cosine scoring — **CSV is not a
suitable input for the loader in the ms/ms-retrieval role**.

### Suggested fix

Dispatch on extension in `common/gnps_loader.py`. Keep the existing
JSON path unchanged; add an MGF path. CSV is rejected with an
explanatory error that points at the MGF file next to it.

Patch sketch (`common/gnps_loader.py`, around line 268):

```python
def iter_records(path: str | Path) -> Iterator[GnpsRecord]:
    """Yield GnpsRecords from a GNPS dump. Dispatches on extension:

    - .json  — the legacy ALL_GNPS_NO_PROPOGATED.json layout (current impl)
    - .mgf   — per-block metadata + peaks from the 2026-04 GNPS2 distribution
    - .csv   — rejected with a clear message (no peaks column)
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        yield from _iter_records_json(path)
    elif suffix == ".mgf":
        yield from _iter_records_mgf(path)
    elif suffix == ".csv":
        raise ValueError(
            f"{path} is a CSV metadata file with no peak column; it cannot "
            f"support MS/MS retrieval. Point METAGENT_GNPS_PATH at the "
            f"companion .mgf file instead."
        )
    else:
        raise ValueError(f"Unsupported GNPS dump extension: {suffix!r} ({path})")


def _iter_records_json(path: Path) -> Iterator[GnpsRecord]:
    # (existing body, unchanged)
    with open(path) as f:
        raw_list = json.load(f)
    for raw in raw_list:
        try:
            yield parse_record(raw)
        except Exception as e:
            sid = raw.get("spectrum_id", "<unknown>")
            logger.warning("Failed to parse GNPS record %s: %s", sid, e)
            continue


def _iter_records_mgf(path: Path) -> Iterator[GnpsRecord]:
    """Stream an MGF file into GnpsRecords.

    Each BEGIN IONS / END IONS block maps to one record. Header lines
    look like ``KEY=VALUE`` (case-insensitive keys are normalised to
    uppercase); every other non-empty line before END IONS is a
    ``<mz> <intensity>`` peak. Keys we care about: TITLE / SPECTRUMID /
    SPECTRUM_ID (the last one wins), ADDUCT, SMILES, INCHI, INCHIKEY,
    IONMODE / ION_MODE, MSLEVEL / MS_LEVEL, MS_IONISATION (mapped onto
    GnpsRecord.ion_source), PEPMASS / PRECURSOR_MZ, COMPOUND_NAME,
    GNPS_LIBRARY_MEMBERSHIP / LIBRARY_MEMBERSHIP.
    """
    # Parser kept inline; matchms.importing.load_from_mgf also works but
    # adds a heavy dep and we only need header+peaks here.
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
                try:
                    yield _mgf_block_to_record(meta, peaks)
                except Exception as e:
                    logger.warning("Failed to parse MGF block at %s: %s",
                                   meta.get("SPECTRUM_ID", "<unknown>"), e)
                in_block = False
                continue
            if not in_block:
                continue
            if "=" in s and not s[0].isdigit():
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
    """Flatten MGF block metadata dict + peak list to a GnpsRecord.

    Reuses the existing _parse_* / _normalise_adduct / _clean_na helpers
    so the JSON path and MGF path converge on the same validator set.
    """
    spec_id = meta.get("SPECTRUM_ID") or meta.get("SPECTRUMID") or meta.get("TITLE") or ""
    precursor = meta.get("PRECURSOR_MZ") or meta.get("PEPMASS", "").split()[0]
    ms_level = meta.get("MS_LEVEL") or meta.get("MSLEVEL")
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
        precursor_mz=_parse_precursor_mz(precursor),
        ms_level=_parse_ms_level(ms_level),
        peaks=sorted(peaks, key=lambda p: p[0]),
        library_membership=_clean_na(meta.get("GNPS_LIBRARY_MEMBERSHIP")
                                      or meta.get("LIBRARY_MEMBERSHIP")),
        library_quality=_parse_quality(meta.get("LIBRARYQUALITY")),
    )
```

### Follow-up: update `env.sh`

After F14 lands, `tools/candidate_prefilter/env.sh` should point
`METAGENT_GNPS_PATH` at an MGF:

```bash
export METAGENT_GNPS_PATH="${_DATA_ROOT}/gnps/ALL_GNPS_cleaned.mgf"
```

A2's `gnps_index.py` also needs to accept MGF (its current CSV path
skips peak data, which is fine for A2's mass-only indexing — a 10-line
`build_index_from_path` dispatch extension will do). **Worth confirming
with Track A2 before changing env.sh.**

Alternative: keep two env vars, `METAGENT_GNPS_META_PATH` (CSV for A2)
and `METAGENT_GNPS_SPECTRA_PATH` (MGF for B). More flexible but also
more config to keep in sync. Recommend the single-MGF path for
simplicity unless A2 has a reason to prefer CSV.

### Tests to add in `tests/common_tests/test_gnps_loader.py` (new file)

```python
def test_iter_records_dispatches_on_extension_json(tmp_path):
    p = tmp_path / "tiny.json"
    p.write_text('[{"spectrum_id": "X1", "Adduct": "[M+H]+", "Ion_Mode": "Positive", '
                 '"Precursor_MZ": "123.45", "Smiles": "CCO", '
                 '"peaks_json": "[[100,1],[120,0.5],[123,0.1]]"}]')
    recs = list(iter_records(p))
    assert len(recs) == 1 and recs[0].spectrum_id == "X1"
    assert len(recs[0].peaks) == 3

def test_iter_records_dispatches_on_extension_mgf(tmp_path):
    p = tmp_path / "tiny.mgf"
    p.write_text(
        "BEGIN IONS\n"
        "SPECTRUM_ID=X1\nADDUCT=[M+H]+\nION_MODE=positive\n"
        "PRECURSOR_MZ=123.45\nSMILES=CCO\n"
        "100.0 1.0\n120.0 0.5\n123.0 0.1\n"
        "END IONS\n"
    )
    recs = list(iter_records(p))
    assert len(recs) == 1 and recs[0].spectrum_id == "X1"
    assert len(recs[0].peaks) == 3

def test_iter_records_rejects_csv_with_helpful_message(tmp_path):
    p = tmp_path / "tiny.csv"
    p.write_text("scan,spectrum_id\n1,X1\n")
    with pytest.raises(ValueError, match="no peak column"):
        list(iter_records(p))
```

---

## F15 — `_load_gnps_records(required=False)` still raises

### Where

`tools/library_search/tool.py:318-324`:

```python
try:
    from common.gnps_loader import load_v0_usable
    _GNPS_CACHE = load_v0_usable(path)
    return _GNPS_CACHE
except Exception as exc:
    raise LibraryUnavailableError(f"failed to load GNPS from {path}: {exc}") from exc
```

The outer `try/except` catches every loader failure and turns it into
`LibraryUnavailableError`. The `required` parameter is ignored.

### Call sites

- `tool.py:240-244` — Path A (pool provided, `want_gnps=True` and pool
  has at least one GNPS-sourced candidate): calls with
  `required=False`. Expected behaviour: **if GNPS is unavailable, fall
  back to "no reference spectra, ms-clip-only scoring"**, don't crash.
- `tool.py:246-250` — Path B (no pool, scanning full GNPS): calls with
  `required=True`. Expected behaviour: crash is correct.

Today both call sites crash the same way.

### Suggested fix

Honour the flag:

```python
def _load_gnps_records(*, records: list | None, required: bool) -> list | None:
    ...
    try:
        from common.gnps_loader import load_v0_usable
        _GNPS_CACHE = load_v0_usable(path)
        return _GNPS_CACHE
    except Exception as exc:
        if required:
            raise LibraryUnavailableError(
                f"failed to load GNPS from {path}: {exc}"
            ) from exc
        logger.warning(
            "GNPS load failed (%s: %s); continuing without reference peaks. "
            "Library_search will fall back to ms-clip-only scoring for this call.",
            type(exc).__name__, exc,
        )
        return None
```

Then in `_collect_scoring_targets`, already handles `records is None`
via `gnps_by_id = _build_gnps_id_index(records or [])`, so no caller-
side change is needed.

### Test to add in `tests/tool_tests/test_library_search.py`

```python
def test_gnps_load_failure_with_pool_degrades_gracefully(monkeypatch, caplog):
    """Regression guard for F15: when a candidate_pool is provided and
    GNPS is unreadable, library_search must emit an ms-clip-only result,
    not raise."""
    import tools.library_search.tool as lt
    lt.clear_gnps_cache()
    monkeypatch.setenv("METAGENT_GNPS_PATH", "/nonexistent/path/that/does/not/exist.mgf")
    spec = _make_tiny_spectrum()
    pool = [_mk_gnps_candidate("CCMSLIB00000000001", "CCO")]
    retr = MockInHouseRetriever({"CCO": 0.8})
    resp = library_search(
        LibrarySearchRequest(spectrum=spec, candidate_pool=pool,
                             libraries=["inhouse", "gnps"], min_score=0.0),
        retriever=retr,
    )
    assert resp.candidates, "should still score via ms-clip"
    assert "GNPS load failed" in caplog.text
```

---

## Acceptance test (single repro, covers both fixes)

After F14 and F15 land, the following removes the
`libraries=["inhouse"]` workaround from today's real-run script and
must exit 0:

```bash
source tools/candidate_prefilter/env.sh
# After F14: env.sh should point METAGENT_GNPS_PATH at the MGF — if it
# still points at the CSV, update env.sh too (see "Follow-up" above).
conda run -n diffms --no-capture-output python - <<'PY'
import json, sys, time
sys.path.insert(0, ".")
from pathlib import Path
from schemas import (GenerateRequest, LibrarySearchRequest,
                     PrefilterRequest, PreprocessRequest)
from tools.spectrum_ops import preprocess
from tools.candidate_prefilter import prefilter
from tools.library_search import library_search
from tools.library_search.model import MSClipRetriever
from tools.molecule_gen import generate
from tools.molecule_gen.fingerprint import GroundTruthFingerprinter
from tools.molecule_gen.model import MSBartGenerator
from rdkit import Chem

fx = json.loads(Path("tests/fixtures/spectra/glucose_pos.json").read_text())
spec = preprocess(PreprocessRequest(
    raw_mz=[p[0] for p in fx["peaks"]],
    raw_intensity=[p[1] for p in fx["peaks"]],
    precursor_mz=fx["precursor_mz"], adduct=fx["adduct"],
    ionization_mode=fx["ionization_mode"],
    collision_energy=fx["collision_energy"],
)).spectrum
pool = prefilter(PrefilterRequest(precursor_mz=spec.precursor_mz,
    adduct=spec.adduct, molecular_formula="C6H12O6",
    mass_tolerance_ppm=5.0)).candidates
# KEY DIFFERENCE vs today: libraries=["inhouse","gnps"] not ["inhouse"] only.
t0 = time.perf_counter()
b = library_search(
    LibrarySearchRequest(spectrum=spec, candidate_pool=pool[:30], top_k=10,
                         min_score=0.0, libraries=["inhouse", "gnps"]),
    retriever=MSClipRetriever(),
)
print(f"B elapsed={time.perf_counter()-t0:.1f}s n={len(b.candidates)} explain={b.explain}")
assert b.candidates, "modcos + ms-clip should return at least one candidate"
assert "ms-clip scoring failed" not in b.explain
assert "failed to load GNPS" not in b.explain
print("ACCEPTANCE PASSED")
PY
```

Today (pre-fix), this snippet raises `LibraryUnavailableError` before
printing anything.

## Pre-landing checklist for the common/ owner

- [ ] Confirm that pointing `METAGENT_GNPS_PATH` at an MGF is acceptable
      for Track A2 too (A2 reads the same env var; check A2's
      `gnps_index.py::build_index_from_path`).
- [ ] If A2 insists on CSV, split into two env vars (see Alternative in
      F14).
- [ ] Land F14's extension-dispatched `iter_records`, reusing existing
      helpers.
- [ ] Land F15's `required`-aware error handling.
- [ ] Add the three loader tests + one B test above.
- [ ] Update `tools/candidate_prefilter/env.sh` (MGF path) and
      `docs/TOOL_CONTRACTS.md` § Tool 3 "GNPS loading contract" to
      mention MGF support.
- [ ] Run the acceptance snippet and attach elapsed time + top-5
      candidate list to the PR description.

## Scope reminder

Per the integration session's rules, I did not modify `common/`,
`schemas/`, `docs/`, or any `tools/*/` file. The patches above are
sketches for the common/ owner (plus one small follow-up in
`tools/library_search/tool.py` for F15) to apply.
