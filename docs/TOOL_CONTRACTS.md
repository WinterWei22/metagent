# Tool Contracts

This file is the single source of truth for what each v0 tool does, what it takes in, and what it returns. If you are implementing a tool, your job is to make the code match this document — not the other way around.

If you believe a contract is wrong, **stop and raise it with the maintainer**. Do not change the schema unilaterally.

## v0 scope

- **Ionization mode:** positive only. The schema accepts `"negative"` so v1 does not require a schema bump, but v0 tools MAY raise `NotImplementedError` on negative input. Tests only cover positive.
- **Organism:** human (`organism="hsa"`) only. Same schema-forward-compatibility rule as above.
- **LLM backend:** MiniMax-M2.7 via OpenAI-compatible endpoint. See `docs/LLM_INTEGRATION.md` — tools that invoke an LLM internally must use the shared `common/llm_client.py`, never bypass it.
- **Deployment:** local Python + Docker. No cloud, no web UI.

## Track assignments

| Track | Owner session | Tools | Directory |
|---|---|---|---|
| A1 | Spectrum preprocess | `spectrum_preprocess` | `tools/spectrum_ops/` |
| A2 | Candidate pre-filter | `candidate_prefilter` (NEW) | `tools/candidate_prefilter/` |
| B | Library search | `library_search` | `tools/library_search/` |
| C | Generation | `molecule_generate` | `tools/molecule_gen/` |
| D | Chem/bio context | `fetch_metabolite_info`, `pathway_context` | `tools/metabolite_info/`, `tools/pathway_context/` |
| E | Verifier backbone | `predict_spectrum` | `tools/spectrum_predict/` |
| F | Literature | `literature_search` | `tools/literature/` |

---

## Shared types

These live in `schemas/common.py`. Do not redefine them in a tool's own schema.

- **`Spectrum`** — normalised MS/MS spectrum. Fields: `mz: list[float]`, `intensity: list[float]`, `precursor_mz: float`, `adduct: str`, `ionization_mode: Literal["positive", "negative"]`, `collision_energy: float | None`. Intensity values are normalised to `[0, 1]` with the base peak at `1.0` — this is enforced at construction.
- **`Candidate`** — a proposed molecule. Fields: `smiles: str`, `name: str | None`, `source: Literal["library", "generated", "reference"]`, `score: float` (normalised to `[0, 1]`, higher is better), `source_id: str | None` (HMDB ID, GNPS ID, internal model run ID, etc.), `explain: str` (why this candidate was proposed, one or two sentences).
- **`ToolError`** — structured error base class. Tools raise a subclass (e.g. `InvalidSpectrumError`) rather than returning partial results.
- **`LiteratureRecord`** and **`PathwayEntry`** — see `schemas/common.py`.

## Shared utilities

Live in `common/` (a separate top-level package from `schemas/`).

- **`common/llm_client.py`** — the MiniMax-compatible client. Every tool that calls an LLM imports `from common.llm_client import chat, strip_thinking, extract_json_list`. See `docs/LLM_INTEGRATION.md` for the contract.
- **`common/rdkit_utils.py`** — SMILES validation, canonicalization, formula checks. Used by `molecule_generate` and `predict_spectrum`.

Tools may import from `schemas/` and `common/`. Tools may NOT import from other `tools/*/` packages.

---

## Tool 1: `spectrum_preprocess` (Track A)

**Purpose.** Take a raw spectrum (from mzML, mgf, or a peak list) and return a cleaned, normalised `Spectrum` object ready for downstream tools. Also extract basic features like base peak, number of peaks, and signal quality flag.

**When the LLM should call it.** Always, as the first step. Every downstream tool assumes input has been preprocessed.

**Input (`PreprocessRequest`):**
- `raw_mz: list[float]` — required, non-empty
- `raw_intensity: list[float]` — required, same length as `raw_mz`
- `precursor_mz: float` — required, positive
- `adduct: str` — required (e.g. `"[M+H]+"`)
- `ionization_mode: Literal["positive", "negative"]` — v0 only tests positive
- `collision_energy: float | None`
- `min_relative_intensity: float = 0.01` — peaks below this fraction of base peak are dropped
- `mz_tolerance_ppm: float = 5.0` — for merging near-duplicate peaks

**Output (`PreprocessResponse`):**
- `spectrum: Spectrum` — cleaned spectrum (intensities in [0, 1], base peak = 1.0)
- `n_peaks_in: int`, `n_peaks_out: int` — before/after filter counts
- `base_peak_mz: float`, `base_peak_intensity: float` (in original scale, before normalisation)
- `quality_flag: Literal["good", "sparse", "noisy", "invalid"]`
- `explain: str` — what was filtered and why

**Dependencies.** `matchms`, `numpy`.

**Errors.** Raises `InvalidSpectrumError` if `len(raw_mz) != len(raw_intensity)`, if precursor is non-positive, or if fewer than 3 peaks survive filtering. May raise `NotImplementedError` for `ionization_mode="negative"` in v0.

**Tests must cover.**
- A real spectrum from `tests/fixtures/spectra/` round-trips cleanly.
- Mismatched array lengths raise `InvalidSpectrumError`.
- A spectrum with 2 peaks returns `quality_flag="invalid"` and raises.
- Relative intensity filter actually drops low peaks.
- Output spectrum has base peak intensity exactly 1.0.

---

## Tool 2: `candidate_prefilter` (Track A2) — NEW

**Purpose.** Given a precursor m/z (and optionally a molecular formula), return the pool of plausible candidate structures whose exact mass matches within a ppm tolerance. This is the first narrowing step: it reduces the search space from hundreds of millions of compounds to a manageable shortlist (typically 10 — 10,000) before library search or de novo generation run.

This tool does NOT use the MS/MS spectrum — only the precursor m/z and optional formula. It is fast (<1 second per query against a local SQLite index) and has no LLM component.

**Why it exists.** library_search and molecule_generate both benefit from a pre-narrowed candidate pool. Without pre-filtering, library_search would compare against every spectrum in GNPS (expensive and noisy), and molecule_generate would produce candidates with masses completely inconsistent with the observed precursor.

**When the LLM should call it.** After preprocessing, before library_search or molecule_generate. The typical plan is:
```
preprocess → candidate_prefilter → library_search (against filtered pool)
                                 → molecule_generate (constrained by formula)
```

**Input (`PrefilterRequest`):**
- `precursor_mz: float` — required, positive
- `adduct: str` — required (e.g. `"[M+H]+"`), used to back out the neutral exact mass
- `molecular_formula: str | None` — if known (e.g. from SIRIUS or user input), used as a hard constraint
- `mass_tolerance_ppm: float = 5.0` — ppm tolerance around computed neutral mass
- `pools: list[Literal["gnps", "pubchem_lite", "hmdb"]] = ["gnps", "pubchem_lite"]` — which candidate pools to search
- `max_candidates: int = 5000` — hard cap on returned candidates

**Output (`PrefilterResponse`):**
- `candidates: list[PrefilteredCandidate]` — see below. Sorted by mass error ascending.
- `neutral_mass_computed: float` — the neutral exact mass used for search
- `n_by_pool: dict[str, int]` — how many candidates came from each pool
- `explain: str` — e.g. `"Neutral mass 180.0634 (from [M+H]+ at 181.0707). Formula constraint C6H12O6 applied. Returned 47 candidates from pubchem_lite within 5 ppm."`

**New schema type (`PrefilteredCandidate`, add to schemas/common.py):**
- `smiles: str` — RDKit-valid
- `name: str | None`
- `source_pool: Literal["gnps", "pubchem_lite", "hmdb"]`
- `source_id: str` — CCMSLIB ID, PubChem CID, or HMDB ID
- `molecular_formula: str`
- `exact_mass: float`
- `mass_error_ppm: float` — absolute ppm error vs. query's neutral mass
- `has_reference_spectrum: bool` — True iff this candidate has an MS/MS spectrum available in the GNPS pool. library_search uses this flag to decide which candidates it can actually match spectrally.

**Dependencies.**
- `common.gnps_loader` — for the GNPS pool (load once, build in-memory mass index)
- A **PubChem Lite** local SQLite database (CID + SMILES + MolecularFormula + MonoisotopicMass), built once during setup (see `docker/pubchem_lite_build.Dockerfile`)
- `rdkit` for formula parsing and canonical SMILES

**Errors.** `InvalidAdductError` if the adduct string cannot be parsed. `PubChemLiteNotBuiltError` if the SQLite DB doesn't exist. Empty `candidates` list is NOT an error.

**Tests must cover.**
- Query for glucose's [M+H]+ precursor (181.0707) returns glucose in the top candidates by mass error.
- Formula constraint `C6H12O6` applied as a hard filter (no candidates with different formulas).
- Queries with very specific ppm (0.5 ppm) return far fewer candidates than wide (20 ppm).
- Mass_error_ppm values in the result are all within the requested tolerance.
- Sorting by mass_error_ppm ascending is preserved.
- A nonsense precursor (m/z = 1.0) returns empty candidates from any pool.

**Adduct-to-neutral-mass table.** Implement the common adducts yourself in `tools/candidate_prefilter/adducts.py`. At minimum support: `[M+H]+`, `[M+Na]+`, `[M+K]+`, `[M+NH4]+`, `[M-H]-`, `[M+FA-H]-`. A reference table with exact mass corrections is at https://fiehnlab.ucdavis.edu/staff/kind/metabolomics/ms-adduct-calculator/.

**PubChem Lite setup.** This tool requires a local SQLite DB built from a PubChem subset. The session will need to:
1. Decide on a PubChem subset scope (full PubChem is ~115M compounds, too big for v0; a "bioactive" or "HMDB-plus-DrugBank-plus-ChEBI" subset of ~2-5M is a better fit).
2. Download the chosen subset.
3. Build a SQLite DB with index on MonoisotopicMass.
4. Write the build script so it's reproducible.

Document the setup clearly in `tools/candidate_prefilter/README_PUBCHEM_SETUP.md` so it can be repeated.

---

## Tool 3: `library_search` (Track B)

**Purpose.** Given a preprocessed spectrum and (optionally) a pre-filtered candidate pool, match against GNPS reference spectra for those candidates and return the top-K with modified cosine scores. When no candidate pool is provided, fall back to matching against the full GNPS v0-usable set (slower, noisier).

**When the LLM should call it.** After preprocessing AND (preferably) after `candidate_prefilter`. The candidate pool from prefilter narrows the search; without it, library_search scans all of GNPS.

**Input (`LibrarySearchRequest`):**
- `spectrum: Spectrum` — required, must be preprocessed
- `candidate_pool: list[PrefilteredCandidate] | None = None` — output from `candidate_prefilter`. When provided, only candidates with `has_reference_spectrum=True` are compared.
- `top_k: int = 10`
- `min_score: float = 0.3`
- `libraries: list[Literal["inhouse", "gnps"]] = ["inhouse", "gnps"]`

**Output (`LibrarySearchResponse`):**
- `candidates: list[Candidate]` — sorted descending by score, may be empty
- `libraries_searched: list[str]`
- `n_total_compared: int` — how many library entries were scored
- `explain: str` — e.g. `"Top match has modified cosine 0.87 against GNPS:CCMSLIB..., driven by base peak m/z 163.06."`

**Dependencies.** In-house retrieval model (PyTorch checkpoint — imported via `from tools.library_search.model import InHouseRetriever` internally, NOT exposed across tools), `matchms`, GNPS library dump parsed via `common.gnps_loader` (path configurable via env var `METAGENT_GNPS_PATH`).

**Why GNPS and not MoNA.** The MoNA-export-HMDB.json dump was evaluated and rejected: it contains ~7400 records but they are predominantly GC-EI historical spectra with no precursor m/z or adduct metadata, making them unusable for LC-MS/MS library matching. GNPS's ALL_GNPS_NO_PROPOGATED dump (matchms cleaned version from https://external.gnps2.org/gnpslibrary) is the v0 primary source: it contains ~500k LC-MS/MS spectra with complete precursor / adduct / ion-mode annotations.

**Why not HMDB as a spectrum library.** HMDB is a compound database, not a spectrum library. It is used by `fetch_metabolite_info` for metadata lookup, not by `library_search`.

**GNPS loading contract.** Use `common.gnps_loader.load_v0_usable(path)` to get pre-filtered records (positive ion mode MS/MS, LC/DI-ESI source, has precursor_mz, adduct, ≥3 peaks, SMILES or InChIKey). Do NOT do any GNPS-specific parsing inside `tools/library_search/`. The loader handles ion-mode normalisation, adduct bracket normalisation, peaks_json double-decoding, and rejection of MALDI/GC/EI records. Your job is: given a list of `GnpsRecord` objects, build an index and do modified-cosine matching.

**Errors.** `LibraryUnavailableError` if a requested library cannot be loaded. Empty result is NOT an error.

**Tests must cover.**
- A fixture spectrum derived from a real GNPS record retrieves the same compound in top 3.
- An intentionally nonsensical spectrum returns `candidates=[]`.
- `top_k=1` returns at most one result.
- All returned scores are in `[0, 1]`.
- Integration tests that require the full GNPS dump skip when `METAGENT_GNPS_PATH` is unset.

**Score normalisation rule.** Modified cosine output is already in `[0, 1]`; use as-is. In-house model output must be rescaled to `[0, 1]` using a calibration curve stored at `tools/library_search/calibration.json`. If the file doesn't exist yet, use linear min-max scaling over a batch of 100 library entries on startup, cache, and warn.

---

## Tool 4: `molecule_generate` (Track C)

**Purpose.** De novo generate candidate structures from a spectrum when library search fails. Wraps the in-house generative model.

**When the LLM should call it.** When `library_search` returns empty or low-confidence (top score < 0.5). Also callable directly if the user explicitly requests de novo analysis.

**Input (`GenerateRequest`):**
- `spectrum: Spectrum` — required
- `molecular_formula: str | None` — if known, pass in as a hard constraint
- `candidate_pool: list[PrefilteredCandidate] | None = None` — optional: if provided, the generator should prefer candidates with matching exact mass / formula from this pool over free generation. Implementation detail left to the model wrapper.
- `n_candidates: int = 20`
- `max_molecular_weight: float = 1500.0`

**Output (`GenerateResponse`):**
- `candidates: list[Candidate]` — SMILES guaranteed to pass RDKit parse; invalid ones filtered out
- `n_generated_raw: int`, `n_valid: int` — for diagnostics
- `explain: str`

**Dependencies.** In-house generation model (PyTorch), `rdkit` via `common.rdkit_utils`.

**Errors.** `ModelLoadError` if checkpoint missing. `NoValidCandidatesError` if every generated SMILES fails RDKit parsing.

**Tests must cover.**
- Output SMILES all parse in RDKit.
- Output candidates have `source="generated"` and `score` in `[0, 1]`.
- Molecular-formula constraint, when provided, is respected for >90% of outputs.
- `n_candidates=0` returns empty list without error.

**Important.** Invalid SMILES must be filtered before the Pydantic response is built. The LLM must never see an unparseable string.

---

## Tool 5: `fetch_metabolite_info` (Track D)

**Purpose.** Given a metabolite identifier (HMDB ID, KEGG ID, InChIKey, or SMILES), return a structured metadata bundle: name, synonyms, formula, exact mass, class, tissue localisation, disease associations, linked database IDs.

**When the LLM should call it.** After a candidate is shortlisted, to enrich it for the final report. Also callable by the biological agent when the user asks about a specific metabolite by name.

**Input (`MetaboliteInfoRequest`):**
- `identifier: str` — required
- `id_type: Literal["hmdb", "kegg", "inchikey", "smiles", "name", "auto"] = "auto"`

**Output (`MetaboliteInfoResponse`):**
- `found: bool`
- `primary_name: str | None`
- `synonyms: list[str]`
- `molecular_formula: str | None`
- `exact_mass: float | None`
- `smiles: str | None`, `inchikey: str | None`
- `chemical_class: str | None`
- `tissue_locations: list[str]`
- `disease_associations: list[str]`
- `cross_refs: dict[str, str]` — keys include `"hmdb"`, `"kegg"`, `"chebi"`, `"pubchem_cid"`
- `source: Literal["hmdb", "pubchem", "kegg", "cached"] | None`
- `explain: str`

**Dependencies.** HMDB local dump (preferred, human subset), PubChem PUG-REST (fallback), KEGG REST (for cross-refs only). OPTIONAL metadata supplement: MoNA-export-HMDB.json via `common.mona_loader.iter_mona_records()` — provides high-quality SMILES, InChIKey, molecular formula, and chemical classification for ~7400 HMDB compounds. Useful when the primary HMDB dump is incomplete or unavailable.

**Errors.** Returns `found=False` rather than raising when identifier is valid but not in any source. Raises `IdentifierFormatError` only if the string is malformed.

**Tests must cover.**
- HMDB0000122 (glucose) returns `found=True` with correct formula `C6H12O6`.
- A made-up HMDB ID returns `found=False`.
- `id_type="auto"` correctly detects HMDB vs InChIKey vs SMILES from pattern.
- `cross_refs` round-trips: fetching by KEGG ID returns the same HMDB ID as fetching by that HMDB ID.

**Hallucination hazard.** Under no circumstances return a field invented by the LLM or a generative fallback. If a field is unknown, it is `None` or `[]`. This tool is a trust anchor for the verifier.

---

## Tool 6: `pathway_context` (Track D)

**Purpose.** Given a metabolite (by HMDB ID or KEGG ID) and optionally a sample context (co-observed metabolites), return pathway membership, upstream/downstream neighbours, and a co-occurrence-based biological plausibility score.

**When the LLM should call it.** After candidates are shortlisted, to assess which are biologically plausible in the sample context.

**Input (`PathwayContextRequest`):**
- `metabolite_id: str` — required, HMDB or KEGG ID
- `organism: str = "hsa"` — v0 only tests human
- `co_observed_ids: list[str] = []`
- `neighbour_depth: int = 1`
- `max_pathways: int = 10`

**Output (`PathwayContextResponse`):**
- `pathways: list[PathwayEntry]`
- `upstream_neighbours: list[str]`, `downstream_neighbours: list[str]`
- `cooccurrence_score: float` — in `[0, 1]`
- `plausibility_summary: str` — templated natural-language summary, under 120 words, written by the tool
- `explain: str`

**Dependencies.** RaMP-DB local deployment (SQLite dump). See `docker/ramp_db.Dockerfile`.

**Errors.** `MetaboliteNotInNetworkError` if the ID resolves but has no pathway membership. `RampUnavailableError` if the DB backend is down.

**Tests must cover.**
- A central metabolite (e.g. pyruvate, HMDB0000243) returns multiple pathways.
- `cooccurrence_score` is higher when `co_observed_ids` contains real neighbours than unrelated metabolites.
- `neighbour_depth=0` returns no neighbours.
- An orphan metabolite raises `MetaboliteNotInNetworkError`.

**Design note.** `plausibility_summary` is written by this tool using a template (not an LLM call), so the orchestrator does not pay a second LLM round-trip. Keep factual.

---

## Tool 7: `predict_spectrum` (Track E)

**Purpose.** Given a SMILES and experimental conditions, forward-predict an MS/MS spectrum. Backbone of structural self-verification.

**When the LLM should call it.** During verification, once a shortlist of candidates exists. Called once per candidate.

**Input (`PredictSpectrumRequest`):**
- `smiles: str` — required, must parse in RDKit
- `adduct: str`
- `ionization_mode: Literal["positive", "negative"]` — v0 only tests positive
- `collision_energies: list[float] = [10.0, 20.0, 40.0]`
- `top_n_peaks: int = 50`

**Output (`PredictSpectrumResponse`):**
- `predicted: Spectrum` — union across collision energies, normalised
- `per_energy: dict[float, Spectrum]`
- `model_version: str` — e.g. `"cfm-id-4.0.0"`
- `explain: str`

**Dependencies.** CFM-ID 4.0 via Docker. Dockerfile at `docker/cfm_id.Dockerfile`; tool calls the container via a local REST shim.

**Errors.** `InvalidSmilesError`, `PredictionTimeoutError` (60s default).

**Tests must cover.**
- A known SMILES (glucose) produces a non-empty spectrum with expected characteristic peaks.
- Invalid SMILES raises `InvalidSmilesError`.
- Timeout behaviour is tested (mock subprocess to hang).

**v0 scope.** CFM-ID only. ICEBERG is v1.

---

## Tool 8: `literature_search` (Track F)

**Purpose.** Search PubMed / Europe PMC for literature supporting a candidate. Every returned record must be independently retrievable by PMID — the verifier will spot-check.

**When the LLM should call it.** After shortlisting, to support each top candidate with literature evidence. Also callable for background queries.

**Input (`LiteratureSearchRequest`):**
- `query: str` — required, free-text
- `max_results: int = 5`
- `year_from: int | None = None`
- `sources: list[Literal["pubmed", "europepmc"]] = ["europepmc"]`

**Output (`LiteratureSearchResponse`):**
- `records: list[LiteratureRecord]` — each has `pmid`, `title`, `abstract`, `authors`, `year`, `journal`, `doi`, `url`
- `query_used: str`
- `explain: str`

**Dependencies.** Europe PMC REST (primary, no key needed), NCBI E-utilities (fallback).

**Errors.** `RateLimitError` on 429. Empty list is a valid response.

**Tests must cover.**
- A query with a well-known metabolite returns non-empty results.
- Every PMID is a pure numeric string (no `"PMID:"` prefix).
- Abstract is non-empty or explicitly `""` — never `None`.
- `max_results=0` returns empty list.

**Hallucination hazard.** Never synthesise or paraphrase abstracts. Return verbatim. If the API returns no abstract, return `""`.

---

## Shared test fixtures

`tests/fixtures/` contains (initial minimal set — replace with real GNPS data when available):

- `spectra/` — MS/MS spectra in JSON (simplified format, easy to read without matchms). Real mgf files go here once GNPS download is done.
- `smiles/curated.json` — 10 SMILES covering diverse classes with their InChIKeys.
- `hmdb_ids/expected.json` — 10 HMDB IDs with expected metadata for regression testing.

The maintainer seeds these on day 1 (see `tests/fixtures/README.md`). Tool sessions MUST NOT modify fixtures — propose additions separately.

---

## Change log

```
2026-04-21 — initial v0 contracts (7 tools).
2026-04-21 — v0 scope narrowed: positive ionization only, human organism only.
             Schema unchanged to preserve forward compat.
2026-04-21 — Added common/ package (llm_client, rdkit_utils) as a cross-tool dependency.
             Tools can import from common/ but still cannot import from each other.
2026-04-21 — library_search data sources updated: "hmdb" removed (HMDB is a compound
             DB, not a spectrum library), "mona" added temporarily. MoNA-HMDB dump
             evaluated and found to be GC-EI historical data, not suitable for
             LC-MS/MS.
2026-04-21 — library_search switched from MoNA to GNPS (ALL_GNPS_NO_PROPOGATED,
             matchms cleaned). Dump from https://external.gnps2.org/gnpslibrary,
             located via METAGENT_GNPS_PATH env var. MoNA loader retained as an
             optional metadata supplement for fetch_metabolite_info.
2026-04-21 — Added Tool 2 `candidate_prefilter` (Track A2). Pre-narrows candidate
             pool by mass/formula before library_search or molecule_generate.
             Requires a PubChem Lite local SQLite DB. Tool count now 8, not 7.
             Track count now 6 (A1, A2, B, C, D, E, F; D covers two tools).
             library_search and molecule_generate updated to accept the filtered
             pool as an optional input.
```
