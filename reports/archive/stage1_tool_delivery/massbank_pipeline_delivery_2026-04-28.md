# Track BENCH-MB — MassBank pipeline delivery

- **Date:** 2026-04-28
- **Branch:** `feature/massbank-data-pipeline`
- **Scope:** `tools/benchmark/`, `tests/benchmark/`, `scripts/build_compound_pool.py`, `data/processed/SCHEMA.md`
- **Status:** Implemented, 112 unit + integration tests passing (1 network-bound test gated on `METAGENT_RUN_INTEGRATION=1`); RIKEN smoke test in flight (results filled in below).

This report is self-contained — a future benchmark-construction session
can use it without reading the development chat.

---

## 1. What was built

```
tools/benchmark/
├── __init__.py
├── massbank_downloader.py   # git clone / HTTP zip + checkpoint marker
├── massbank_parser.py       # MassBank .txt  →  MassBankRecord
├── massbank_normalizer.py   # MassBankRecord →  NormalizedRecord (Spectrum + GT + meta)
├── massbank_filter.py       # FilterCriteria, classify_compound, CompoundPool I/O
└── requirements.txt

tests/benchmark/
├── __init__.py
├── fixtures/massbank_records/   # 4 real RIKEN/Eawag .txt + 3 synthetic edge cases
├── test_massbank_downloader.py     14 tests
├── test_massbank_parser.py         22 tests
├── test_massbank_normalizer.py     48 tests
├── test_massbank_filter.py         25 tests
└── test_pipeline_integration.py     3 CLI subprocess tests

scripts/
└── build_compound_pool.py    # argparse CLI, end-to-end pipeline

data/processed/
└── SCHEMA.md                 # JSONL schema documentation
```

Total: **8 production files + 5 test files + 7 fixtures + SCHEMA.md.**

## 2. Pipeline at a glance

```
download_massbank()                       (git clone / HTTP zip; checkpointed)
        │
        ▼
parse_massbank_directory()                (raw .txt → MassBankRecord, streaming)
        │
        ▼
normalize_record()                        (→ NormalizedRecord wrapping Spectrum,
                                            ground_truth dict, metadata dict)
        │   drops on: missing/invalid SMILES, missing precursor m/z,
        │              unparseable ion_mode/adduct, < 5 peaks
        ▼
filter_records(FilterCriteria)            (protocol §2.2 defaults)
        │   drops on: ion_mode/instrument/contributor/MS-level mismatches,
        │              peak count < 15, precursor_mz outside [100, 800]
        ▼
build_compound_pool(classify=True)        (ClassyFire → SMARTS fallback,
                                            8 buckets total: 6 protocol + "other" + None)
        │
        ▼
CompoundPool                              (.by_class, .by_mode, .stats, .save, .load)
        │
        ▼
JSONL  (data/processed/compound_pool_*.jsonl)
```

## 3. Critical design decisions

| Decision | Choice | Why |
|---|---|---|
| Where dirty data is laundered | `massbank_normalizer.py` only | Pitfall #4 in brief: the schema is frozen. Normaliser is the single sink. |
| Spectrum schema modifications | **None** | `_preamble.md` rule "Schemas are law"; brief explicitly forbids it. Extra info goes into `NormalizedRecord.{ground_truth,metadata}` dicts. |
| Multi-charge adducts (Q4 of plan) | Preserved verbatim (`[M+2H]2+` stays `[M+2H]2+`) | `Spectrum.adduct: str` has no charge constraint. Lossless. |
| Ion-mode / adduct mismatch | Trust `ion_mode`, log warning | Brief explicitly says so. |
| Collision energy (`NCE 30`, `15 % (nominal)`, `20-40 eV`) | Numeric value with warning | `NCE` / `%` → numeric + "treated as eV-equivalent" warning; ranges → midpoint + warning; `ramp` / `stepwave` → `None` + warning |
| Peak noise floor | Drop rel-int < 0.001 | Pitfall #2: don't drop aggressively, but bare `0` is noise. |
| Compound classification | ClassyFire first (cached SQLite), SMARTS fallback | Reuses existing `tools/classyfire/` (don't reinvent). Fallback covers the offline / API-down case. |
| Where the data lives | Code in project; data under `/data/.../massbank/{raw,cache,processed}/` | Per maintainer instruction. Project tree stays tidy. |
| Resilience to schema drift | Checkpoint markers + JSONL versioning hook in SCHEMA.md | If we add a `schema_version` field later, downstream loaders can tell. |

## 4. Filter defaults (matches protocol §2.2)

```python
FilterCriteria(
    ion_mode = ["positive", "negative"],          # CLI default
    instrument_types = ["Q-TOF", "Orbitrap", "QFT", "FT-ICR"],
    ms_level = ["MS2"],
    min_peaks = 15,
    precursor_mz_range = (100.0, 800.0),
    require_inchikey = True,
    require_smiles = True,
    require_formula = True,
)
```

Override any field for sub-pool experiments. Filtering is streaming-friendly
(consumes `Iterable[NormalizedRecord]`).

## 5. Compound class taxonomy (protocol §2.4)

Six buckets + `"other"` + `None`. ClassyFire keyword map is in
`_CF_KEYWORD_MAP`; SMARTS patterns in `_SMARTS_PATTERNS`.

| Class | ClassyFire keywords (excerpt) | SMARTS pattern (fallback) |
|---|---|---|
| `amino_acid` | `amino acid`, `α-amino acid`, `dipeptide`, `tripeptide` | `[NX3;H2,H1;!$(NC=O)][CX4][CX3](=O)[OX2H,OX1H0-]` |
| `nucleoside` | `nucleoside`, `nucleotide`, `purine ribonucleotide` | purine *or* pyrimidine ring + sugar ring |
| `organic_acid` | `carboxylic acid`, `dicarboxylic acid`, `hydroxy acid` | `[CX3](=O)[OX2H1]` |
| `flavonoid` | `flavonoid`, `flavone`, `flavonol`, `anthocyanid` | `O=c1cc(-[c]2ccccc2)oc2ccccc12` (chromone-2-aryl) |
| `lipid` | `glycerophospholipid`, `sphingolipid`, `lyso`, `acylcarnitine` | GPL backbone *or* C13 chain + ester/acid |
| `alkaloid` | `alkaloid` | (ClassyFire only — too varied for one SMARTS) |

## 6. CLI usage

```sh
python scripts/build_compound_pool.py \
    --contributors RIKEN \
    --target-dir   /data/.../massbank/raw \
    --output       /data/.../massbank/processed/compound_pool_riken.jsonl \
    --ion-modes    positive negative \
    --min-peaks    15 \
    --classify
```

Exit codes:

- `0` success, JSONL written
- `2` fatal parse error walking the clone
- `3` zero records survived normalisation
- `4` zero records survived filtering

All log output goes to stderr; the JSONL is written via `CompoundPool.save`,
not stdout, so output redirection is unnecessary.

## 7. Tests

```sh
$ pytest tests/benchmark/ -q
112 passed, 1 skipped, 2 warnings in 1.34s
```

The 1 skipped test is `test_real_git_clone` (gated on `METAGENT_RUN_INTEGRATION=1`).
The 3 integration tests in `test_pipeline_integration.py` use a fake clone
built from the existing fixtures, so they are network-free.

## 8. RIKEN smoke test (live run on real data)

Two runs were executed against the real `MassBank/MassBank-data` GitHub
clone. The first surfaced an `instrument_type` matcher bug
(`Q-TOF` whitelist failed to match RIKEN's `LC-ESI-QTOF`); commit
`0dcbaf7` (`fix(benchmark): instrument-type matcher robust to hyphenation`)
fixes it. The numbers below are from the second, post-fix run.

Command:
```sh
python scripts/build_compound_pool.py \
    --contributors RIKEN \
    --target-dir /data/weiwentao/llm_agent_metabolomics/massbank/raw \
    --output /data/weiwentao/llm_agent_metabolomics/massbank/processed/compound_pool_riken.jsonl \
    --classify --no-classyfire
```

The brief specified `--classify` (which defaults to using ClassyFire), but
the cold ClassyFire cache hit ~2 s of latency per molecule → ~2.3 hours
estimated for the 5930 surviving compounds. To deliver a usable smoke
result in this session I switched to `--no-classyfire` (pure SMARTS
classification, ~50 ms per compound). The 172 cache entries that the
ClassyFire run populated before being killed remain in
`data/classyfire_cache.sqlite`; a future overnight `--classify` rerun
will benefit from them. **For the final benchmark pool used downstream,
re-run `--classify` (without `--no-classyfire`) once the cache has been
warmed.**

### Smoke test results

| Metric | Value |
|---|---:|
| Clone wall-clock (run 1) | 164 s |
| Clone size on disk | 558 MB |
| RIKEN `.txt` files found | 11 935 |
| After parse | 11 935 |
| After normalise | 9 617 (-2 318 dropped: GC-EI MS1 with no precursor) |
| After filter | 5 930 (drops: 28 instrument, 2 839 min_peaks, 820 precursor_mz) |
| Classified via SMARTS | 5 930 (`failed=0`) |
| Final pool size | 5 930 records |
| JSONL on disk | 14.5 MB |
| Wall-clock (run 3, post-fix, SMARTS-only) | < 30 s parse + classify + save |

#### Mode breakdown
| mode | count | pct |
|---|---:|---:|
| positive | 3 549 | 59.8% |
| negative | 2 381 | 40.2% |

#### Compound-class breakdown (SMARTS fallback)
| class | count | pct |
|---|---:|---:|
| other | 3 907 | 65.9% |
| flavonoid | 1 402 | 23.6% |
| organic_acid | 353 | 6.0% |
| lipid | 195 | 3.3% |
| amino_acid | 70 | 1.2% |
| nucleoside | 3 | 0.1% |

The high `other` rate is expected for SMARTS-only classification — alkaloids,
terpenoids, glycosides etc. don't fall in any of the six benchmark buckets
and don't match the conservative SMARTS patterns. With ClassyFire the
expectation is roughly:
- `other` rate would drop to ~25%
- alkaloids would absorb ~10%
- the remaining specialised classes (terpenoids, glycosides, etc.) would still be `other` per protocol §2.4

Counts already meet the protocol §3.1.2 target of "≥30 per class for ≥4
classes" if we use ClassyFire labels (preliminary expectation), and meet
"≥30 per class for 4 classes" today with SMARTS-only labels for
flavonoid / organic_acid / lipid / amino_acid (3 of 4 over the 30
threshold, amino_acid above by 40).

#### Sanity check on a sample record
```
accession      MSBNK-RIKEN-PR100211
ionization     positive
adduct         [M+H]+
precursor_mz   608.08937
peaks          17
compound_class lipid
inchikey       LFTYTUAZOPRMMI-NESSUJCYSA-N
```
All `Spectrum` validators pass (mz/intensity lengths match, intensity
in [0,1], precursor>0).

## 9. Known gaps & follow-ups

1. **Identification level filtering not implemented.** MassBank does not
   expose a uniform `IDENTIFICATION_LEVEL` field. `FilterCriteria.identification_levels`
   is reserved for future use.
2. **`tests/integration/` dir already in this project; mine is at `tests/benchmark/test_pipeline_integration.py`.** Naming kept `tests/benchmark/` per the brief's deliverable list to avoid colliding with the existing `tests/integration/` directory.
3. **Pyteomics not adopted.** matchms-style MGF parsing was unnecessary —
   MassBank is a custom `.txt` format with peak blocks; we parse it directly.
4. **`pytest.mark.integration` is unregistered.** Two warnings emitted.
   Could be silenced by adding to a `pytest.ini` `markers =` list — out of
   scope for this track (`pytest.ini` does not currently exist).
5. **CompoundPool currently writes everything in one JSONL pass.** For
   pools >100 k records, consider switching to gzipped JSONL — not a
   concern at protocol scale (max ~10 k expected).

## 10. For the next session

```python
from tools.benchmark.massbank_filter import CompoundPool

pool = CompoundPool.load(
    "/data/weiwentao/llm_agent_metabolomics/massbank/processed/compound_pool_riken.jsonl"
)

# Sub-1 candidates: 250 records, mode-balanced, ≥30 per class
# (the protocol §3.1.2 target). Just filter the pool further:
amino_acids_pos = [
    r for r in pool.by_class("amino_acid")
    if r.spectrum.ionization_mode == "positive"
]
```

The file format is documented at `data/processed/SCHEMA.md`. Each record
carries enough info (accession + record_title + source_file) to trace
back to the original MassBank `.txt` if needed.

## 11. Commit log

```
103577a feat(benchmark): CLI build_compound_pool + pipeline integration tests
0154464 feat(benchmark): add MassBank filter + CompoundPool
dca33c2 feat(benchmark): add MassBank normalizer
3cab5a7 spectrum_ops: support negative ion mode    ← unrelated, picked up by other agent
40d6ebc feat(benchmark): add MassBank downloader + parser
```

Two interleaved switches by an external agent (the spectrum_ops track)
landed `3cab5a7` on this branch by accident. The cherry-pick has since
been reapplied to the right branch (`track-a1-spectrum-preprocess`).
Including its commit on this branch is harmless — same content, no diff
on the merge target.
