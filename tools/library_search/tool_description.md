# library_search

Match a preprocessed MS/MS spectrum against reference libraries and return the
top-K candidate molecules with calibrated similarity scores. Wraps two scorers:
modified cosine (via `matchms`) against GNPS reference spectra, plus an in-house
learned retriever (ms-clip, a CLIP-style spectrum↔molecule model). Scores are
fused into a single normalised value per candidate.

## When to call

- After `spectrum_preprocess` — this tool assumes the `Spectrum` is normalised.
- Ideally after `candidate_prefilter` — pass the returned
  `list[PrefilteredCandidate]` as `candidate_pool`. With a pool the tool scores
  only that narrow set and runs fast. Without a pool the tool falls back to
  scanning the full GNPS v0-usable set, which is slower and noisier. The pool
  does not need to be filtered to `has_reference_spectrum=True` — ms-clip
  scores everything; modified cosine silently skips entries without a GNPS
  reference.
- As the first retrieval step once a spectrum is in hand. `molecule_generate`
  is the right follow-up when this tool returns empty or a top score below 0.5.

## When NOT to call

- Do not call with a raw (non-preprocessed) spectrum — results will be noisy
  and matchms Spectrum construction may fail.
- Do not call repeatedly for the same query hoping for different outputs —
  scoring is deterministic. Widen `candidate_pool`, drop `min_score`, or raise
  `top_k` instead.
- Do not call when the adduct is outside positive-mode LC/DI-ESI vocabulary.
  v0 is positive-mode only; negative-mode queries may be rejected downstream.

## Inputs

| Field | Meaning |
|---|---|
| `spectrum` | Preprocessed `Spectrum`. Required. Intensities must be in `[0, 1]` with the base peak at 1.0 (enforced by the schema). |
| `candidate_pool` | Optional `list[PrefilteredCandidate]` from `candidate_prefilter`. When provided, scoring is restricted to these candidates: ms-clip scores every one; modified cosine scores the subset whose `source_id` resolves in the loaded GNPS pool. When `None`, the tool scans the entire GNPS v0-usable pool. **The `has_reference_spectrum` flag on each pool entry is informational only** — ms-clip scores the candidate regardless of its value. (The contract originally gated library_search on this flag; the gate was removed once the in-house ms-clip retriever landed because ms-clip does not require a reference spectrum.) |
| `top_k` | Max number of candidates to return. Default 10. `0` returns an empty list. |
| `min_score` | Candidates below this fused score are dropped. Default 0.3. Raise to tighten, lower to broaden. |
| `libraries` | Subset of `["inhouse", "gnps"]`. `"gnps"` enables modified cosine (requires reference spectra); `"inhouse"` enables ms-clip. Default is both. |

## Outputs

`LibrarySearchResponse`:

- `candidates`: list of `Candidate`, sorted by `score` descending, deduplicated
  by SMILES. Every `source == "library"`. Every `score` is in `[0, 1]`. The
  list may be empty (not an error) when nothing cleared `min_score`.
- `libraries_searched`: which libraries were actually consulted.
- `n_total_compared`: how many (spectrum, candidate) pairs were scored before
  the `min_score` cut. Useful for telemetry; not a confidence signal.
- `explain`: one templated sentence summarising the run.

### Score semantics

The per-candidate score is `max(modified_cosine, rescaled_ms_clip)`:

- `modified_cosine` is native `[0, 1]`, measured against a specific GNPS
  reference spectrum.
- `rescaled_ms_clip` is the model's global cosine similarity (dot product of
  L2-normalised embeddings, raw range `[-1, 1]`) mapped through
  `calibration.json` to `[0, 1]`.

Max fusion (not weighted sum) is intentional: the two signals have different
availability profiles — a pool candidate without a GNPS reference gets only
ms-clip; a reference without good embedding support gets only modified cosine.
Max prevents a missing signal from deflating a legitimate match.

## Failure modes and errors

- `LibraryUnavailableError` — GNPS dump cannot be loaded (env var unset on the
  fallback path, file missing, JSON malformed). Retry after ensuring
  `METAGENT_GNPS_PATH` is set, or always pass a `candidate_pool`.
- `InHouseModelError` — ms-clip subprocess failed (checkpoint missing, conda
  env missing, timeout, pickle malformed). This is caught internally and
  downgraded: the tool returns modified-cosine-only results and flags it in
  `explain`. It is raised only if the caller explicitly asks for the in-house
  retriever via a separate path (tests).
- Empty `candidates` list is **not** an error — it means nothing cleared
  `min_score`. Follow up with `molecule_generate`.

## In-house model scope

The ms-clip retriever was trained on MassSpecGym (MSG) positive-mode MS/MS
spectra. Adducts supported natively by the model are enumerated in
`ms_clip.common.ions.ION_LST` — roughly `[M+H]+`, `[M+Na]+`, `[M+K]+`,
`[M+NH4]+`, `[M+H-H2O]+`, `[M+H-2H2O]+`, and `[M]+`. Queries with adducts
outside this set are transparently downgraded to modified-cosine-only; the
caller does not need to check.

Negative mode and instruments / sources outside LC/DI-ESI are out of scope for
v0 and may yield unreliable ms-clip scores. The tool does not enforce this at
input time (the orchestrator is expected to restrict to positive mode in v0).

## Operational notes

- GNPS records are cached in-process across calls for the lifetime of the
  Python process; repeated queries do not re-parse the JSON dump.
- ms-clip runs in a separate conda env (`diffms` by default) via `conda run`.
  It materialises a tiny TSV and one JSON per call in a scratch tmpdir — no
  persistent state.
- Typical latency: tens of milliseconds for modified cosine over a 100-entry
  pool; seconds to minutes for ms-clip depending on pool size, GPU availability,
  and conda-env cold start.
