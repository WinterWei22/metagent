# predict_spectrum

Forward-predict an MS/MS spectrum from a candidate SMILES using CFM-ID 4.0.
This tool is the **verification backbone**: the verifier agent compares the
predicted spectrum against the experimental input to decide whether a
structural candidate is consistent with what was actually observed.

## When to call

- After a shortlist of candidates exists (from `library_search`,
  `molecule_generate`, or both). Call **once per candidate** under review.
- Only when the verifier needs a structural consistency check — e.g. to break
  ties between candidates with similar library scores, or to justify
  accepting a de novo candidate with no library match.
- Always with a **canonical SMILES**. The tool will canonicalise internally
  but rejecting bad SMILES early saves a 60 s round-trip.

## When NOT to call

- Do not call on every candidate from `library_search` — those already carry
  a cosine score. Use this only for candidates that need extra validation.
- Do not call for library matches with cosine ≥ 0.9 and a curated source_id
  (GNPS reference). The reference spectrum is already empirical truth.
- Do not call twice with the same SMILES to "get a better answer". CFM-ID is
  deterministic; the result will not change. Caching belongs in the
  orchestrator, not in this tool.
- Do not call to rank many candidates by score — use `library_search` or
  `molecule_generate` for that. Prediction is slow (seconds per candidate).

## Inputs

| Field | Meaning |
|---|---|
| `smiles` | Candidate structure. Must parse in RDKit. |
| `adduct` | Experimental adduct, e.g. `"[M+H]+"`. Passed through to CFM-ID and used to set the precursor m/z on the returned Spectrum. |
| `ionization_mode` | `"positive"` only in v0. `"negative"` raises `NotImplementedError`. |
| `collision_energies` | Three eV values used as **labels** for the returned `per_energy` dict. CFM-ID 4.0 ships three fixed pre-trained models (≈10 / 20 / 40 eV); any other list length is overridden to the defaults and noted in `explain`. |
| `top_n_peaks` | Cap on peaks per spectrum (both per-energy and union). CFM-ID often emits hundreds; default 50 is plenty for cosine scoring. |

## Outputs

`PredictSpectrumResponse` with:

- `predicted`: a single `Spectrum` — the **union** across the three collision
  energies. Intensities are renormalised so the union base peak = 1.0. Use
  this for single-number cosine comparisons.
- `per_energy`: dict of `{eV: Spectrum}` — the three individual ramps, each
  normalised to its own base peak. Use this when the experimental spectrum
  was recorded at a known collision energy and you want to compare apples
  to apples.
- `model_version`: e.g. `"cfm-id-4.0.0"`. Pinned into every report so the
  verifier can flag a predictor upgrade.
- `explain`: one-to-two-sentence template summary. Non-informational; the
  real structural fit is measured by the verifier.

## Failure modes the LLM should expect

- `InvalidSmilesError` (`PREDICT_INVALID_SMILES`, recoverable): RDKit cannot
  parse the SMILES. Either canonicalise and retry, or drop the candidate.
- `PredictionTimeoutError` (`PREDICT_TIMEOUT`, recoverable): CFM-ID hung for
  over 60 s. Large or floppy molecules are the usual cause. Skip the
  candidate — retries with the same input will not help.
- `CfmUnavailableError` (`PREDICT_CFM_UNAVAILABLE`, not recoverable): the
  container at `METAGENT_CFM_URL` is not running. The tool cannot proceed
  until an operator fixes it; the orchestrator should fall back to
  verification paths that do not need a predicted spectrum.
- `NotImplementedError`: negative ionization mode in v0. Not raised as a
  `ToolError` because the LLM cannot route around it at plan time.

## What this tool does **not** do

- It does not score candidates. Comparing `predicted` to the experimental
  spectrum is the verifier's job.
- It does not cache. Same SMILES → same HTTP call every time.
- It does not retry on failure. One shot, one result, one error.
- It does not launch the CFM-ID container. Assume the shim is already up at
  `METAGENT_CFM_URL`.
