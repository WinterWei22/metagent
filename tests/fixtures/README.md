# Test fixtures

Shared data used by every tool's unit tests. Tool-implementation sessions **MUST
NOT** modify fixtures — propose additions to the maintainer separately.

## Large data (not in the repo)

Two external datasets feed the integration tests. Neither is required for unit
tests, which use the small derived fixtures below.

**GNPS spectrum library** (primary, for library_search):
```bash
export METAGENT_GNPS_PATH=/path/to/ALL_GNPS_NO_PROPOGATED.json
```
Download from https://external.gnps2.org/gnpslibrary — pick the matchms-cleaned
JSON. ~500k LC-MS/MS records, a few hundred MB on disk, peak memory during
parse around 2-3 GB.

**MoNA-HMDB compound metadata** (optional, for fetch_metabolite_info):
```bash
export METAGENT_MONA_PATH=/path/to/MoNA-export-HMDB.json
```
Download from https://mona.fiehnlab.ucdavis.edu/downloads — ~7400 records.
Despite the name, this dump is mostly GC-EI historical spectra, NOT usable for
library_search. Its compound metadata (SMILES, InChIKey, classification) is
still high-quality and supplements HMDB.

Integration tests guard on these env vars and skip if unset.

## Contents

### `spectra/`

MS/MS spectra in a simple JSON format (easy to read without matchms). Each file
represents one spectrum of a known compound. The placeholder files in the initial
commit are **synthetic minimal spectra** — real GNPS-derived spectra should
replace them before library_search tests can be meaningfully run.

File format:

```json
{
  "compound_name": "glucose",
  "smiles": "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
  "inchikey": "WQZGKKKJIJFFOK-GASJEMHNSA-N",
  "hmdb_id": "HMDB0000122",
  "precursor_mz": 179.0561,
  "adduct": "[M-H]-",
  "ionization_mode": "negative",
  "collision_energy": 20.0,
  "peaks": [[mz1, intensity1], [mz2, intensity2], ...],
  "source": "synthetic_placeholder" | "gnps:CCMSLIB00000...",
  "notes": "..."
}
```

**TODO for maintainer (day 1):** download real MS/MS from GNPS for at least:
- glucose (HMDB0000122) — positive mode `[M+H]+`
- caffeine (HMDB0001847) — positive mode `[M+H]+`
- L-carnitine (HMDB0000062) — positive mode `[M+H]+`

and replace the placeholder JSON files. Filenames must stay the same so tests
don't need to be updated.

### `smiles/curated.json`

10 SMILES covering diverse chemical classes with InChIKey and class label. Used
by `molecule_generate` and `predict_spectrum` tests.

### `hmdb_ids/expected.json`

10 HMDB IDs with expected metadata for `fetch_metabolite_info` regression
testing.

### `kegg_ids/expected.json`

5 KEGG compound IDs with expected pathway memberships for `pathway_context`
testing.

### `llm_responses/`

Recorded MiniMax responses for integration tests. Only populated when tests are
run with `--record-llm`. Normal unit tests use `common.llm_client.set_mock()`.

## Rules

1. Never commit a new fixture without a checksum or provenance note. Every
   file must be traceable — either synthetic (document generation) or
   downloaded from a public source (document URL and date).
2. Fixtures must be small. No single file > 100 KB in v0. Large test data goes
   in `tests/large_fixtures/` which is .gitignored.
3. If a test needs data beyond what's here, the test is over-scoped. Split it.
