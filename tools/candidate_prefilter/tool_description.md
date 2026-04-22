# candidate_prefilter

Fast pre-screening of candidate structures by precursor mass (and optional
molecular formula), before library_search or molecule_generate run. Narrows
the search space from hundreds of millions of compounds to a shortlist
(typically tens to low thousands) so downstream tools don't spend effort on
structures whose mass is inconsistent with the observed precursor.

Does not use the MS/MS spectrum. Does not call the LLM. Pure local index
lookup, typically well under one second per call.

## When to call

- Always call after `spectrum_preprocess` and BEFORE `library_search` and
  `molecule_generate`. Pass the returned `candidates` list into those tools'
  `candidate_pool` input.
- Call once per identification. If the result is empty and the query looked
  reasonable (precursor > 50 Da, adduct is standard), the compound is almost
  certainly outside the local pools — widen `mass_tolerance_ppm` to 10 or 20
  before giving up.
- If a SIRIUS / CFM-ID / human-supplied molecular formula is available, pass
  it via `molecular_formula`. It is applied as a hard filter and will drop
  the candidate count by 10x–100x.

## When NOT to call

- Do NOT call to score or rank a known candidate — this tool does not use
  the MS/MS spectrum. For scoring, use `library_search` (retrieval) or
  `predict_spectrum` (verification).
- Do NOT call with a precursor m/z below ~20 Da. The adduct reverse-
  calculation still runs but the neutral mass is chemically implausible.
- Do NOT re-call with a widened tolerance immediately. Review what came back
  at 5 ppm before widening; widening past 20 ppm rarely helps and floods
  downstream tools with noise.

## Inputs

| Field | Meaning |
|---|---|
| `precursor_mz` | Observed m/z of the precursor ion. Required, > 0. |
| `adduct` | Bracketed form, e.g. `"[M+H]+"`, `"[M-H]-"`, `"[M+Na]+"`. See "Supported adducts" below — anything outside the table raises `InvalidAdductError`. |
| `molecular_formula` | Optional Hill-form formula (e.g. `"C6H12O6"`). Applied as a hard exact-string filter. Leave `None` if unknown. |
| `mass_tolerance_ppm` | ppm half-window around the back-calculated neutral mass. Default 5.0. Raise to 10 or 20 only if a 5 ppm query returns nothing and the instrument is known to be less accurate. Hard cap: 100. |
| `pools` | Which pools to query. Default `["gnps", "pubchem_lite"]`. v0 `"pubchem_lite"` pool is HMDB-sourced under the hood; `"hmdb"` pool is a no-op in v0 and returns 0 candidates. |
| `max_candidates` | Hard cap on returned candidates. Default 5000. If your tolerance produces more, the top N by mass-error-ascending are returned. |

## Supported adducts

Positive mode: `[M+H]+`, `[M+Na]+`, `[M+K]+`, `[M+NH4]+`, `[M+H-H2O]+`,
`[M+2H]2+`, `[2M+H]+`, `[2M+Na]+`.

Negative mode: `[M-H]-`, `[M+FA-H]-`, `[M+Cl]-`, `[M+AcO-H]-`, `[2M-H]-`.

Adducts must be passed in the exact bracketed string form shown above.
Unusual adducts outside this table will raise — normalise to one of these
before calling.

## Outputs

`PrefilterResponse` with:

- `candidates`: list of `PrefilteredCandidate`, sorted by `mass_error_ppm`
  ascending. May be empty (not an error). Each candidate has:
    - `smiles` — RDKit-parseable structure.
    - `name` — human-readable when available, may be `None`.
    - `source_pool` — `"gnps"`, `"pubchem_lite"`, or `"hmdb"`.
    - `source_id` — stable id in the source pool: CCMSLIB accession for
      GNPS, HMDB ID for pubchem_lite (in v0), or PubChem CID as
      `"CID:5793"` once v0.1+ adds PubChem.
    - `molecular_formula` — canonical Hill form.
    - `exact_mass` — neutral monoisotopic mass (Daltons).
    - `mass_error_ppm` — absolute ppm deviation from the query's neutral mass.
    - `has_reference_spectrum` — `True` iff this candidate's InChIKey is also
      present in the GNPS pool, regardless of its own `source_pool`. Use this
      flag to decide whether `library_search` can score this candidate.
- `neutral_mass_computed` — the neutral exact mass used for the search.
- `n_by_pool` — dict of how many candidates came from each queried pool
  (pre-cap; the final candidates list may be shorter if `max_candidates` cut it).
- `explain` — one templated factual sentence summarising the run.

### Interpreting the result

- Empty `candidates` with the default 5 ppm: the compound is not in any
  local pool. Retry once with `mass_tolerance_ppm=20`; if still empty, fall
  back to `molecule_generate` with the precursor-derived formula (if
  available) rather than forcing a library match.
- Many candidates with the same molecular formula: mass alone cannot
  distinguish them. This is the expected entry point for `library_search`
  (spectrum matching) and `molecule_generate` (de novo).
- `has_reference_spectrum=False` for every candidate: none of the structural
  matches has a reference MS/MS in GNPS. `library_search` will produce no
  matches; skip it and go directly to `molecule_generate`.

## Failure modes

| Error | When |
|---|---|
| `InvalidAdductError` | `adduct` is not in the supported table above. Recoverable: re-issue with a normalised adduct string. |
| `PubChemLiteNotBuiltError` | `METAGENT_PUBCHEM_LITE_PATH` is unset or points at a missing file, AND `"pubchem_lite"` was in `pools`. NOT recoverable by retry — operator must build the DB (see `README_PUBCHEM_SETUP.md`). To proceed without it, re-issue with `pools=["gnps"]`. |

An empty `candidates` list is **not** an error — it means the query's
neutral mass (± tolerance, ± formula) has no structural match in the local
pools. The caller should decide whether to widen tolerance, drop the formula
constraint, or skip to another tool.

## Deployment notes (for operators, not the LLM)

- GNPS pool is lazily loaded from `METAGENT_GNPS_PATH` on first call. If the
  variable is unset, the pool is empty and `has_reference_spectrum` is
  `False` everywhere — a warning is logged but no error raised. This lets
  v0.1-stage systems ship without the full ~400 MB GNPS dump.
- PubChem Lite SQLite DB is read-only at runtime. Rebuild via
  `python -m tools.candidate_prefilter.build_pubchem_lite --hmdb-xml … --output …`.
  See `README_PUBCHEM_SETUP.md` for the full build procedure.
