# Track A1: `spectrum_preprocess`

**Prerequisite:** read `prompts/_preamble.md` first. All its rules apply.

## Your scope

You own exactly one tool: **`spectrum_preprocess`**. Directory: `tools/spectrum_ops/`.

You do NOT own library_search, prefilter, or anything else. Preprocessing is the very first step of the pipeline — every downstream tool consumes a preprocessed `Spectrum`, so your output is a load-bearing foundation.

## The specific task

Given a raw MS/MS peak list (mz array + intensity array) plus precursor info, produce a cleaned, normalized `Spectrum` object:

1. Drop peaks below `min_relative_intensity` × base peak intensity (noise floor).
2. Merge near-duplicate peaks within `mz_tolerance_ppm`.
3. Sort by mz ascending.
4. Normalize intensities so base peak = 1.0 (this is enforced by the Spectrum schema — do it in your code, don't rely on validation to catch it).
5. Assign a `quality_flag`: `"good"` (≥10 peaks, well-distributed), `"sparse"` (3-9 peaks), `"noisy"` (base peak dominates >90% of total intensity), `"invalid"` (<3 peaks after filter).
6. Raise `InvalidSpectrumError` on `<3` peaks after filtering, mismatched arrays, or non-positive precursor.

**Read the full contract:** `docs/TOOL_CONTRACTS.md` → "Tool 1: `spectrum_preprocess`".

## What goes into which file

- `tools/spectrum_ops/tool.py` — the `preprocess(req: PreprocessRequest) -> PreprocessResponse` function
- `tools/spectrum_ops/filters.py` (optional) — if you want to split out the filter logic
- `tools/spectrum_ops/errors.py` — define `InvalidSpectrumError(ToolError)`
- `tools/spectrum_ops/tool_description.md`
- `tools/spectrum_ops/requirements.txt` — `matchms`, `numpy`, `pydantic`
- `tools/spectrum_ops/example.py`
- `tests/tool_tests/test_spectrum_ops.py`

## Test cases you MUST cover

Pull fixtures from `tests/fixtures/spectra/glucose_pos.json`, `caffeine_pos.json`, `lcarnitine_pos.json`. These are synthetic placeholders — treat them as schema-shape correct but not scientifically authoritative.

1. **Round-trip:** load glucose fixture, preprocess with default args, confirm base peak intensity == 1.0, n_peaks_out ≥ 3.
2. **Mismatched arrays** (raw_mz len=5, raw_intensity len=4) raises `InvalidSpectrumError`.
3. **Non-positive precursor** raises `InvalidSpectrumError`.
4. **Two-peak input** (after filter) returns `quality_flag="invalid"` and raises.
5. **Low-intensity filter actually drops peaks:** construct an input with 10 peaks where 7 are below noise floor → output has 3 peaks.
6. **Sort invariance:** feed scrambled mz order → output mz is sorted ascending.
7. **ppm merge:** two peaks at 100.0000 and 100.0004 (4 ppm apart) → merged into one (at default 5 ppm tolerance).

## Dependencies you can use

- `matchms` — for Spectrum primitives and filters (preferred — don't reinvent)
- `numpy` — for array ops
- `pydantic` — for schema construction
- `common.*` — shared utils (you likely don't need any of these)

## Explicit non-goals

- Do NOT load GNPS, HMDB, or any reference data. This tool is pure signal processing.
- Do NOT call an LLM. This is deterministic.
- Do NOT handle negative ion mode specifically — raise `NotImplementedError` in that branch and note it in the test. v0 is positive only.
- Do NOT try to guess precursor_mz from the peak list if missing — the contract says it's required.

## Sanity check before you open the PR

```bash
cd /path/to/metagent
python tools/spectrum_ops/example.py
pytest tests/tool_tests/test_spectrum_ops.py -v
```

Both should pass cleanly. Then you're done.
