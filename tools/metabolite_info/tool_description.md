# fetch_metabolite_info

Return a structured metadata bundle for one metabolite, given any of
the common identifiers (HMDB ID, KEGG ID, InChIKey, SMILES, or free-text
name). Every returned field traces back to a real database row — the tool
is a trust anchor for the verifier and will never invent values.

## Call it when

- You have a shortlisted candidate identifier (from `library_search`,
  `molecule_generate`, or `candidate_prefilter`) and want the biological /
  chemical metadata needed to write the report: formula, exact mass,
  chemical class, tissue localisation, disease associations, cross-refs.
- The user asks a direct question about a named metabolite
  ("what is glucose?", "tell me about L-carnitine").
- You need to convert between identifier systems — e.g. resolve a
  KEGG compound ID to an HMDB ID so downstream lookups work.

## Do NOT call it when

- The user gave a raw spectrum only and no candidate has been shortlisted
  yet — there's nothing to look up.
- You are looking for pathway membership or co-occurrence evidence — use
  `pathway_context` for that.
- You are looking for reference MS/MS spectra — use `library_search`.
- You want PMIDs / literature — use `literature_search`.

## Input

| Field        | Type                                                           | Notes                                                                     |
| ------------ | -------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `identifier` | `str` (required, non-empty)                                    | The identifier string. Leading/trailing whitespace is trimmed.            |
| `id_type`    | `'hmdb' \| 'kegg' \| 'inchikey' \| 'smiles' \| 'name' \| 'auto'` | Defaults to `'auto'`. Use `'auto'` unless you are certain of the kind.   |

Legacy 5-digit HMDB IDs (`HMDB00122`) are normalised to the modern 7-digit
form (`HMDB0000122`) internally — either form is accepted.

## Output

| Field                   | Type                  | Meaning                                                         |
| ----------------------- | --------------------- | --------------------------------------------------------------- |
| `found`                 | `bool`                | `True` iff any backend returned a match.                        |
| `primary_name`          | `str \| None`         | Canonical name from the source DB.                              |
| `synonyms`              | `list[str]`           | Alternative names; may be empty.                                |
| `molecular_formula`     | `str \| None`         | Hill notation.                                                  |
| `exact_mass`            | `float \| None`       | Monoisotopic mass in Da.                                        |
| `smiles`                | `str \| None`         | As stored by the source DB; not re-canonicalised.               |
| `inchikey`              | `str \| None`         | Standard 14-10-1 form.                                          |
| `chemical_class`        | `str \| None`         | HMDB taxonomy class label when available.                       |
| `tissue_locations`      | `list[str]`           | Empty when unknown — NEVER invented.                            |
| `disease_associations`  | `list[str]`           | Empty when unknown — NEVER invented.                            |
| `cross_refs`            | `dict[str, str]`      | Keys: `hmdb`, `kegg`, `chebi`, `pubchem_cid`, `chembl`.         |
| `source`                | `'hmdb' \| 'pubchem' \| 'kegg' \| 'cached' \| None` | Which backend answered.            |
| `explain`               | `str`                 | One-line human-readable summary of what happened.               |

When `found=False`, all other fields default to `None` / `[]` / `{}`.

## Failure modes

- **`IdentifierFormatError`** is raised when the identifier string is
  empty, whitespace-only, or `None`. This is the only exception surfaced
  by this tool.
- Every other failure (no DB hit, MoNA unavailable, PubChem offline)
  results in `found=False`, never an exception.

## Source priority

The tool queries sources in this order and stops at the first hit:

1. **Local HMDB SQLite** (preferred). Path configured via
   `METAGENT_HMDB_PATH`. Built once via
   `tools/metabolite_info/build_hmdb_db.py` from the public HMDB XML dump
   at <https://hmdb.ca/downloads>.
2. **MoNA-HMDB supplement** (structural fields only — no tissue/disease).
   Path configured via `METAGENT_MONA_PATH`. Used when the primary HMDB
   DB is missing or incomplete for a given ID. Still reports
   `source="hmdb"` because MoNA-HMDB is a curated subset of HMDB.
3. **PubChem PUG-REST** (network fallback, GATED). Only runs when
   `METAGENT_ALLOW_PUBCHEM=1`. Off by default — tests and air-gapped
   deployments never leak queries.

## Determinism and trust

Calls are deterministic given the same backing databases: there is no
LLM call anywhere in this tool, and no randomness. Any field the source
DB does not carry is returned as `None` or `[]`. If the source DB is
silent on disease associations for caffeine, you will see an empty list
— not a plausibly-worded but fabricated entry.
