# `spectrum_preprocess`

Clean and normalise a raw MS/MS peak list so downstream tools can consume it.
Deterministic, fast (<100 ms per spectrum). No external lookups, no LLM.

## When to call

**Always call this first.** Every other tool in the pipeline
(`candidate_prefilter`, `library_search`, `molecule_generate`,
`predict_spectrum`) assumes its input `Spectrum` has been run through this
tool. Do not pass raw peak lists to any other tool.

## When NOT to call

- Do not call it twice on the same spectrum — the output is already normalised
  and sorted; re-running is a no-op at best and may silently re-scale if peaks
  have drifted.
- Do not call it to "guess" a precursor m/z — `precursor_mz` is a required
  input. If you don't know it, stop and ask the user or the preceding tool.

## Inputs

| Field | Meaning |
|---|---|
| `raw_mz`, `raw_intensity` | Peak arrays, same length, non-empty. Any ordering — the tool sorts. |
| `precursor_mz` | Required, positive. The m/z of the precursor ion as reported by the instrument. |
| `adduct` | Required, e.g. `"[M+H]+"`. Propagated to the output spectrum unchanged. |
| `ionization_mode` | `"positive"` or `"negative"`. Propagated unchanged to the output spectrum. Signal processing itself is polarity-independent; downstream tools (prefilter, library search) handle adduct/polarity semantics. |
| `collision_energy` | Optional, eV. Propagated unchanged. |
| `min_relative_intensity` | Default `0.01`. Peaks below this fraction of the base peak are dropped. Raise it (e.g. `0.05`) to aggressively denoise; lower it (`0.001`) for sparse low-signal spectra. |
| `mz_tolerance_ppm` | Default `5.0`. Peaks within this tolerance are merged into one (intensity-weighted centroid). |

## Outputs

| Field | Meaning |
|---|---|
| `spectrum` | A clean `Spectrum`: m/z sorted ascending, intensities in `[0, 1]` with base peak exactly `1.0`. Safe to pass downstream. |
| `n_peaks_in`, `n_peaks_out` | Counts before and after filtering — the difference tells you how much signal was removed. |
| `base_peak_mz`, `base_peak_intensity` | The base peak in the ORIGINAL (pre-normalisation) scale. Useful when you need to reason about absolute instrument counts. |
| `quality_flag` | `"good"` — ≥ 10 peaks, no single peak dominates; `"sparse"` — 3–9 peaks, passable but thin; `"noisy"` — ≥ 10 peaks but base peak carries > 90% of total intensity (usually indicates an in-source artefact); `"invalid"` — < 3 peaks survived (the tool raises in this case rather than returning). |
| `explain` | One-sentence template summary of what was filtered and the resulting quality. |

## How to interpret outputs

- `quality_flag="good"` → proceed to `candidate_prefilter` and `library_search`
  with default settings.
- `quality_flag="sparse"` → library matching may be unreliable. Consider
  `molecule_generate` even if library_search returns a result, and weight its
  confidence lower.
- `quality_flag="noisy"` → the spectrum may be dominated by an adduct loss or
  artefact. Library_search scores will be misleadingly high for the wrong
  reasons; treat top hits with suspicion and verify with `predict_spectrum`.

## Failure modes

- `InvalidSpectrumError` — raised when fewer than 3 peaks survive filtering,
  when all input intensities are non-positive, or when the input arrays are
  length-mismatched in a way that bypassed schema validation. Non-recoverable;
  the caller should either relax `min_relative_intensity` and retry, or
  abandon the spectrum.
- `pydantic.ValidationError` — raised at request construction time for
  length mismatches, non-positive `precursor_mz`, or `min_relative_intensity`
  outside `[0, 1]`. Fix the caller; do not retry.
