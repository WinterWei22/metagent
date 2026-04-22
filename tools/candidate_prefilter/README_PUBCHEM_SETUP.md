# PubChem Lite setup (v0: HMDB-only)

The `candidate_prefilter` tool queries a local SQLite database called
"PubChem Lite". In v0 the database is populated from the public HMDB
metabolites dump (≈220k human metabolites). The SQLite schema is designed
to accept DrugBank, ChEBI, and a PubChem Bioactive subset in v0.1+ without
a migration — only additional rows are needed.

If your v0 query returns zero candidates and you believe the compound is
common, it is most likely not in HMDB (e.g. industrial chemicals, rare
natural products). Re-check the input; if the compound really is novel,
proceed to `molecule_generate`.

## Why HMDB-only for v0

- **Domain fit.** MetAgent's downstream tools (`fetch_metabolite_info`,
  `pathway_context`) are HMDB/KEGG-keyed; an HMDB-backed prefilter pool
  keeps cross-tool IDs consistent and reduces dead-end lookups.
- **Build cost.** One single XML file, one `python -m` invocation, no
  multi-source ID reconciliation. A full build on a modern laptop takes
  ~20 minutes and produces a ~60 MB SQLite DB.
- **Coverage.** For human metabolomics v0 (`organism="hsa"`), HMDB covers
  the endogenous and common dietary / microbial-derived metabolite space
  well. Drug metabolites and industrial chemicals are the known gap and
  motivate v0.1 expansion.

## One-time build

### 1. Install runtime dependencies

From `tools/candidate_prefilter/`:

```bash
pip install -r requirements.txt
```

This pulls `pydantic` and `rdkit`. The build script uses `xml.etree` from
stdlib — no extra XML parser.

### 2. Download HMDB

From [hmdb.ca](https://hmdb.ca/downloads) — pick "All Metabolites" under
"Current Metabolite Data":

```bash
cd /some/workspace
wget https://hmdb.ca/system/downloads/current/hmdb_metabolites.zip
unzip hmdb_metabolites.zip   # => hmdb_metabolites.xml, ~4 GB uncompressed
```

Provenance note: record the download date in your team's ops log. HMDB
releases roll forward silently and the current-url redirects to whatever
the latest release is. Rebuilds are not idempotent across releases.

### 3. Build the SQLite DB

From the repo root:

```bash
python -m tools.candidate_prefilter.build_pubchem_lite \
    --hmdb-xml /some/workspace/hmdb_metabolites.xml \
    --output   /some/workspace/pubchem_lite.sqlite
```

Expected runtime: 15–30 minutes on a laptop. Output looks like:

```
… progress: 5000 seen, 4831 inserted, 169 skipped
… progress: 10000 seen, 9698 inserted, 302 skipped
…
build complete: 216430 inserted, 4182 skipped, DB at /some/workspace/pubchem_lite.sqlite
inserted=216430 skipped=4182 db=/some/workspace/pubchem_lite.sqlite
```

Skipped records are almost entirely HMDB entries without a valid SMILES
(peptides, classes, placeholder entries) or SMILES that RDKit cannot parse.
This is expected and does not indicate a broken build.

The build script recomputes `exact_mass`, `molecular_formula`,
`canonical_smiles`, and `inchikey` with RDKit for every accepted row so
every stored value has a single canonical origin.

### 4. Point the tool at the DB

```bash
export METAGENT_PUBCHEM_LITE_PATH=/some/workspace/pubchem_lite.sqlite
```

Put this in your shell rc or the project's `.envrc` so it's picked up
across sessions. The tool opens the DB read-only, so multiple processes
can share a single file safely.

### 5. (Recommended) also set METAGENT_GNPS_PATH

The `has_reference_spectrum` flag on prefilter output is cross-stamped from
the GNPS pool. Without `METAGENT_GNPS_PATH`, that flag is `False` for
every candidate and `library_search` will have nothing to match against.
See `tests/fixtures/README.md` for the GNPS download.

## SQLite schema

```sql
CREATE TABLE pubchem_lite (
    compound_id       TEXT PRIMARY KEY,   -- HMDB0000122, "CID:5793", DRUGBANK:DB00123, ...
    source            TEXT NOT NULL,      -- "hmdb" | "drugbank" | "chebi" | "pubchem"
    name              TEXT,               -- primary name
    smiles            TEXT NOT NULL,      -- source-supplied SMILES (verbatim)
    canonical_smiles  TEXT,               -- RDKit canonical form
    inchikey          TEXT,               -- RDKit-computed InChIKey
    molecular_formula TEXT NOT NULL,      -- RDKit Hill form
    exact_mass        REAL NOT NULL,      -- RDKit monoisotopic exact mass (Da)
    pubchem_cid       INTEGER,            -- if known, NULL otherwise
    hmdb_id           TEXT                -- if known, NULL otherwise
);
CREATE INDEX idx_exact_mass ON pubchem_lite(exact_mass);
CREATE INDEX idx_formula    ON pubchem_lite(molecular_formula);
CREATE INDEX idx_inchikey   ON pubchem_lite(inchikey);
```

Queries use the `idx_exact_mass` B-tree for the mass-window lookup and
(when supplied) the `idx_formula` index for the formula filter. Typical
cold query returns in <50 ms for a 5 ppm window against ~220k rows.

## Rebuild / extend procedure (v0.1+ roadmap)

- To add DrugBank / ChEBI, extend `build_pubchem_lite.py` with per-source
  loaders that emit the same column set with `source` set appropriately.
  The tool code needs no change — `source_pool="pubchem_lite"` is applied
  uniformly.
- To rebuild from a newer HMDB release, rerun the build command in step 3
  with the new XML. The script truncates the existing DB file first; no
  manual cleanup needed.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `PubChemLiteNotBuiltError: METAGENT_PUBCHEM_LITE_PATH is not set` | Env var missing. Run step 4. |
| `PubChemLiteNotBuiltError: PubChem Lite SQLite DB not found at …` | Path in env var is wrong or file was deleted. |
| Build script reports `skipped` = most of the dump | HMDB dump is corrupt, or RDKit version is very old. Check `rdkit.__version__ >= 2022`. |
| Query returns zero candidates for a common metabolite | `mass_tolerance_ppm` too tight, or wrong `adduct` (check ion mode), or the compound genuinely isn't in the HMDB subset. |
