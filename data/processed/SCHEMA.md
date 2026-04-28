# Compound Pool JSONL Schema

Output format of `scripts/build_compound_pool.py`. Round-trips through
`tools.benchmark.massbank_filter.CompoundPool.{save,load}`.

One JSON object per line. Field-by-field:

```jsonc
{
  // ─── Spectrum (validates via schemas.common.Spectrum) ─────────────────
  "spectrum": {
    "mz":              [float, …],   // sorted ascending, length == intensity
    "intensity":       [float, …],   // [0, 1] floats; max == 1.0
    "precursor_mz":    float,        // > 0
    "adduct":          string,       // canonical bracketed form, e.g. "[M+H]+"
    "ionization_mode": "positive" | "negative",
    "collision_energy": float | null  // eV; null when CE is unknown / ramp / N/A
  },

  // ─── Ground truth (free-form dict; not Pydantic-validated) ────────────
  "ground_truth": {
    "smiles":              string,        // canonical SMILES from CH$SMILES
    "inchi":               string | null, // CH$IUPAC (full InChI string)
    "inchikey":            string,        // 14-10-1 hash (recovered from SMILES if missing)
    "molecular_formula":   string | null, // CH$FORMULA
    "exact_mass":          float | null,  // Da; computed via RDKit if missing
    "compound_names":      [string, …],   // every CH$NAME entry, in source order
    "primary_compound_name": string | null, // == compound_names[0] for convenience
    "pubchem_cid":         int | null,    // parsed from CH$LINK PUBCHEM
    "compound_class":      string | null  // present iff classify=True; one of:
                                          // amino_acid | nucleoside | organic_acid |
                                          // flavonoid | lipid | alkaloid | other | null
  },

  // ─── Metadata (free-form dict; for traceability + downstream sub-pools) ─
  "metadata": {
    "accession":       string,        // e.g. "MSBNK-RIKEN-PR301141"
    "record_title":    string,        // verbatim RECORD_TITLE
    "contributor":     string,        // from filename: "RIKEN", "EAWAG", …
    "instrument":      string | null, // verbatim AC$INSTRUMENT
    "instrument_type": string | null, // verbatim AC$INSTRUMENT_TYPE
    "ms_level":        string | null, // "MS2", "MS", …
    "source_file":     string | null  // absolute path during build (snapshot)
  },

  // ─── Soft warnings collected during normalisation ────────────────────
  "normalization_warnings": [string, …]   // empty list if clean
}
```

## Invariants

- `len(spectrum.mz) == len(spectrum.intensity)` and ≥ 1.
- `max(spectrum.intensity) == 1.0`; min ≥ 0.001 (noise floor applied).
- `spectrum.precursor_mz > 0`.
- `ground_truth.smiles` is non-empty and parseable by RDKit (filter drops
  records where this fails, so loaded pools should never contain garbage).
- `ground_truth.inchikey` is always populated when classification ran
  (recovered from SMILES via RDKit if MassBank didn't supply one).

## Loading in downstream code

```python
from tools.benchmark.massbank_filter import CompoundPool

pool = CompoundPool.load("data/processed/compound_pool_riken.jsonl")

# Stage-1 sub-pool selection examples:
amino_acids = pool.by_class("amino_acid")
neg_mode    = pool.by_mode("negative")
print(pool.stats())
# →  {"total": 4523, "by_mode": {"positive": 3289, "negative": 1234},
#     "by_class": {"amino_acid": 687, ...}, ... }
```

## Versioning

The schema is versioned implicitly by the contents of
`tools.benchmark.massbank_filter._record_to_jsonable` /
`_record_from_jsonable`. Any breaking change requires bumping a
``schema_version`` field — not yet present because there is no v2 yet.
