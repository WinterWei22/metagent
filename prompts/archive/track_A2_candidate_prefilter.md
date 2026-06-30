# Track A2: `candidate_prefilter`

**Prerequisite:** read `prompts/_preamble.md` first.

## Your scope

You own exactly one tool: **`candidate_prefilter`**. Directory: `tools/candidate_prefilter/`.

This is the **NEW** pre-screening tool added in v5. Its job is to narrow the candidate search space BEFORE library_search or molecule_generate run, using precursor mass (and optional molecular formula) as a cheap hard filter. Without this, downstream tools have to scan hundreds of millions of structures — this tool cuts that to a handful-to-thousands.

This tool does NOT use the MS/MS spectrum. Only precursor m/z + adduct + optional formula. It's fast (<1s) and has no LLM component.

## The specific task

```
Given:   precursor_mz (e.g. 181.0707) + adduct (e.g. "[M+H]+") + optional formula
Compute: neutral exact mass (e.g. 180.0634)
Search:  local indices for compounds whose exact mass is within mass_tolerance_ppm
         of the computed neutral mass (AND whose formula matches, if provided)
Return:  sorted list of PrefilteredCandidate objects
```

**Read the full contract:** `docs/TOOL_CONTRACTS.md` → "Tool 2: `candidate_prefilter`".

## This track has TWO subprojects

### Subproject 1: The tool itself (ship this first)

- `tools/candidate_prefilter/tool.py` — main `prefilter(req: PrefilterRequest) -> PrefilterResponse`
- `tools/candidate_prefilter/adducts.py` — adduct-to-neutral-mass conversion. At minimum handle `[M+H]+`, `[M+Na]+`, `[M+K]+`, `[M+NH4]+`, `[M-H]-`, `[M+FA-H]-`. Reference: https://fiehnlab.ucdavis.edu/staff/kind/metabolomics/ms-adduct-calculator/
- `tools/candidate_prefilter/gnps_index.py` — in-memory mass index over GNPS records (built from `common.gnps_loader.load_v0_usable()`). Keeps only (smiles, name, ccmslib_id, formula, exact_mass).
- `tools/candidate_prefilter/pubchem_index.py` — SQLite-backed mass index over PubChem Lite. Query by `exact_mass BETWEEN ? AND ?` with an index on `exact_mass`.
- `tools/candidate_prefilter/errors.py` — `InvalidAdductError`, `PubChemLiteNotBuiltError`

### Subproject 2: PubChem Lite setup (one-time, do this early)

- `tools/candidate_prefilter/build_pubchem_lite.py` — script that downloads a PubChem subset and builds SQLite DB
- `tools/candidate_prefilter/README_PUBCHEM_SETUP.md` — documented setup for other devs

**PubChem subset choice.** Full PubChem is ~115M compounds — too big for v0. Start with one of:
- **Bioactive subset** (~2M compounds in PubChem's "Bioactive and Drug" categorization) — download from https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/
- **HMDB + DrugBank + ChEBI union** (~1M) — makes chemical sense for metabolomics, but requires more plumbing

Discuss the choice with the maintainer at the START before downloading anything — this is a judgment call, not a code decision.

**SQLite schema** (suggested):
```sql
CREATE TABLE pubchem_lite (
    cid INTEGER PRIMARY KEY,
    smiles TEXT NOT NULL,
    canonical_smiles TEXT,
    molecular_formula TEXT NOT NULL,
    exact_mass REAL NOT NULL
);
CREATE INDEX idx_exact_mass ON pubchem_lite(exact_mass);
CREATE INDEX idx_formula ON pubchem_lite(molecular_formula);
```

## Expected output shape

```python
PrefilterResponse(
    candidates=[
        PrefilteredCandidate(
            smiles="OC[C@H]1OC(O)...",
            name="D-Glucose",
            source_pool="pubchem_lite",
            source_id="5793",  # PubChem CID
            molecular_formula="C6H12O6",
            exact_mass=180.0634,
            mass_error_ppm=0.8,
            has_reference_spectrum=False,  # True iff also in GNPS pool
        ),
        # ...
    ],
    neutral_mass_computed=180.0634,
    n_by_pool={"gnps": 3, "pubchem_lite": 42},
    explain="Neutral mass 180.0634 (from [M+H]+ at 181.0707). Returned 45 candidates within 5 ppm.",
)
```

## Test cases you MUST cover

1. **Correct neutral mass back-calculation:** `[M+H]+` at 181.0707 → neutral ~180.0634 (within 0.001 Da).
2. **Glucose is found:** prefilter request with precursor 181.0707 + `[M+H]+` returns D-Glucose (CID 5793) among top candidates.
3. **Formula hard constraint works:** same request with `formula="C6H12O6"` returns ONLY C6H12O6 candidates.
4. **ppm tolerance is respected:** `mass_tolerance_ppm=0.5` returns far fewer than `mass_tolerance_ppm=20`.
5. **Empty candidate list:** a precursor of m/z 1.5 returns zero candidates from all pools (and does not raise).
6. **Sorted ascending by mass_error_ppm:** verify sort order in output.
7. **Invalid adduct** ("banana"): raises `InvalidAdductError`.
8. **has_reference_spectrum flag** is True ONLY for candidates that also appear in the GNPS pool (spot-check with a known-in-GNPS compound).

## Testing without the big data files

You cannot assume the maintainer has the full GNPS dump or a complete PubChem Lite SQLite DB when running your tests. For unit tests:

- Build a **tiny mock SQLite DB** in your test setUp with 20 hand-picked compounds including glucose (CID 5793), caffeine (CID 2519), L-carnitine (CID 10917). Commit this mock DB to `tests/fixtures/pubchem_lite_mini.sqlite`.
- For GNPS index, hand-construct 5 fake `GnpsRecord` objects in memory.

Mark real-dataset tests with `@pytest.mark.integration` and skip if `METAGENT_PUBCHEM_LITE_PATH` isn't set.

## Dependencies you can use

- `rdkit` — for formula parsing, exact mass computation from SMILES
- `sqlite3` (stdlib) — for the PubChem Lite index
- `pydantic` — for schema construction
- `common.gnps_loader` — to load GNPS records for the GNPS sub-pool

## Explicit non-goals

- Do NOT compare spectra. Not your job — library_search does that.
- Do NOT download PubChem at import time. Build-once script is separate from tool runtime.
- Do NOT hit the PubChem REST API at query time. Everything local.
- Do NOT use LLM to guess adducts. Adducts are a small finite table; hard-code it.

## First action

Before writing any code, tell the maintainer your intended PubChem subset choice (bioactive vs. HMDB+DrugBank+ChEBI vs. something else) and why. Wait for confirmation. This is a one-way door — rebuilding the DB is costly.
