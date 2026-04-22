# molecule_generate

De novo candidate-structure generation from an MS/MS spectrum. Wraps an
in-house two-stage pipeline: CSI:FingerID turns the spectrum into a molecular
fingerprint, then MS-BART decodes the fingerprint into SMILES via SELFIES.

## When to call

- Call after `library_search` returns empty, or returns a top score < 0.5.
- Call when the user explicitly asks for de novo analysis of a spectrum.
- Always call `spectrum_preprocess` first; this tool assumes a normalised
  `Spectrum`.
- If `candidate_prefilter` has produced a `candidate_pool`, pass it in — the
  tool will score generated molecules higher when they match the pool.

## When NOT to call

- Do not call for spectra that already have a high-confidence library match
  (top score ≥ 0.5 in `library_search`). Generation is noisier than retrieval.
- Do not call if the orchestrator only needs metadata for a known candidate;
  use `fetch_metabolite_info` instead.
- Do not call twice in a row with the same inputs to "get more candidates" —
  raise `n_candidates` in the first call instead.

## Inputs

| Field | Meaning |
|---|---|
| `spectrum` | Preprocessed MS/MS spectrum. Required. |
| `molecular_formula` | Optional Hill formula (e.g. `"C8H10N4O2"`). Applied as a **hard filter** after generation: candidates whose RDKit-derived formula does not exactly match are dropped. Leave `None` if unknown. |
| `candidate_pool` | Optional list of `PrefilteredCandidate` from `candidate_prefilter`. Used as a **soft bias** — candidates whose canonical SMILES appears in the pool receive a score bonus (+0.1, clamped to 1.0). Not a filter; structures outside the pool still appear. |
| `n_candidates` | Number of candidates to return. Tuned for 100; values up to 200 are allowed. `0` returns an empty list without invoking the model. |
| `max_molecular_weight` | Upper bound in Da; default 1500. Candidates above this are dropped. |

## Outputs

`GenerateResponse` with:

- `candidates`: list of `Candidate`, sorted by `score` descending. Every SMILES is
  RDKit-valid and canonicalized. Every `source == "generated"`. Every `score`
  is in `[0, 1]`. The list may be empty (not an error) when all generated
  SMILES failed the formula / MW filters.
- `n_generated_raw`: how many SMILES the model emitted before any filtering.
- `n_valid`: how many parsed in RDKit.
- `explain`: one templated sentence summarising the run.

### Score semantics

`score = 0.5 * normalized_log_prob + 0.5 * (1 - formula_mismatch / max_mismatch) + 0.1 * in_prefilter_pool`, clamped to `[0, 1]`. Higher is more plausible.
`normalized_log_prob` is min-max normalized across the returned batch; do not
compare scores across two separate calls of this tool.

## Failure modes

| Error | When |
|---|---|
| `ModelLoadError` | MS-BART checkpoint is missing, `conda run -n ms-bart` fails, inference timed out, or the runner crashed. Not recoverable by retry. |
| `NoValidCandidatesError` | The model emitted ≥1 SMILES but every one failed RDKit parsing. Recoverable: caller can retry with a different `n_candidates` or skip to another tool. |
| `FingerprinterError` | The configured fingerprinter could not produce a fingerprint (SIRIUS binary missing, empty candidate list for `CandidateFusionFingerprinter`, or all candidate SMILES failed RDKit parsing). Not recoverable by retry. |

An empty `candidates` list is **not** an error — it means every generated
molecule was filtered out by the formula or MW constraint, and the caller
should widen those constraints or fall back to another tool.

## Fingerprinter options (for operators)

The tool accepts any `Fingerprinter` via the `fingerprinter=` keyword. Available
implementations in `tools/molecule_gen/fingerprint.py`:

- **`CandidateFusionFingerprinter`** — recommended. Fuses a `list[Candidate]`
  produced by Track B `library_search` into a 4096-bit Morgan fingerprint using
  the same soft-vote protocol MS-BART's fused-FP training uses. No external
  model required. Strategies: `retrieved_only_60` (default), `retrieved_only_80`,
  `topn_60`, `topn_80`. Optional `base_fingerprint` slot for future
  MIST/CSI-adapter integration.
- **`SiriusFingerprinter`** — shells out to SIRIUS for CSI:FingerID. Note that
  CSI output is in a substructure space, not Morgan, so an adapter is required
  before feeding it into the MS-BART checkpoint.
- **`GroundTruthFingerprinter`** — oracle-mode; bypasses spectrum entirely.
  `.from_smiles(smiles)` computes the 4096-bit Morgan FP deterministically;
  `.from_token_string("<fp0042>...")` parses a preset.

## Deployment notes

- MS-BART runs inside the `ms-bart` conda env; the tool shells out via
  `conda run -n ms-bart python -m tools.molecule_gen._runner`.
- Override the checkpoint path with `METAGENT_MSBART_CKPT`. Default points at
  the MassSpecGym/csyanghan MS-BART checkpoint.
- SIRIUS (CSI:FingerID) path uses `docker/molecule_gen.Dockerfile`; point
  `METAGENT_SIRIUS_BIN` at a wrapper script that invokes the container.
