# NPClassifier Full-Pool Classification — Audit Report

**Date:** 2026-04-29
**Branch:** `feature/nm002-leakage-filter`
**Commit:** `2361715` (head before this session's edits, see Provenance)
**API endpoint:** `https://npclassifier.gnps2.org/classify`

---

## 1. Coverage

| Pool                       | Total unique compounds | Classified (status=ok)  | Failed | Coverage |
|----------------------------|-----------------------:|------------------------:|-------:|---------:|
| RIKEN MassBank pool        |                    712 |                     712 |      0 | **100%** |
| HMDB pathway candidates    |                    300 |                     300 |      0 | **100%** |
| Cache reuse (overlap)      |                     19 |                       — |      — |        — |
| Total unique cache entries |                    993 |                     993 |      0 | **100%** |

`status=ok` includes responses where NPClassifier could not assign a natural-product
taxonomy (empty `superclass`/`class`/`pathway` arrays). Per design, those are
recorded as successful cache entries — they represent "API answered cleanly" not
"classification failed".

**Empty-array responses (compound classified but uninformative):**

| Pool   | Empty `superclass` | Empty `pathway` |
|--------|------------------:|----------------:|
| RIKEN  |                50 |              25 |
| HMDB   |                43 |              19 |

These are typically synthetic or non-NP compounds (see §5).

---

## 2. Top NPClassifier `pathway` values

### RIKEN (712 unique compounds)

| Count | Pathway                              |
|------:|--------------------------------------|
|   340 | Shikimates and Phenylpropanoids      |
|   181 | Alkaloids                            |
|    82 | Terpenoids                           |
|    56 | Amino acids and Peptides             |
|    42 | Fatty acids                          |
|    19 | Carbohydrates                        |
|     6 | Polyketides                          |

NPClassifier exposes 7 pathway labels at this level; all 7 are populated.
The dominance of Shikimates/Phenylpropanoids (~48%) reflects RIKEN's
flavonoid- and phenolic-heavy holdings.

### HMDB (300 sampled candidates)

| Count | Pathway                              |
|------:|--------------------------------------|
|    89 | Fatty acids                          |
|    59 | Alkaloids                            |
|    37 | Terpenoids                           |
|    34 | Carbohydrates                        |
|    32 | Shikimates and Phenylpropanoids      |
|    28 | Amino acids and Peptides             |
|     5 | Polyketides                          |

The HMDB stratified sample is more uniform — Fatty acids dominate
(~30%), reflecting the lipid-metabolism stratum. "Alkaloids" here
includes many nucleoside/nucleotide hits since NPClassifier groups
purine/pyrimidine derivatives under that pathway.

---

## 3. Top NPClassifier `class_` values

### RIKEN — Top 20

| Count | Class                                |
|------:|--------------------------------------|
|    67 | Flavones                             |
|    65 | Flavonols                            |
|    30 | Flavanones                           |
|    29 | Cinnamic acids and derivatives       |
|    27 | Isoquinoline alkaloids               |
|    26 | Isoflavones                          |
|    22 | Dipeptides                           |
|    22 | Anthocyanidins                       |
|    21 | Corynanthe type                      |
|    19 | Oleanane triterpenoids               |
|    18 | Chalcones                            |
|    15 | Glucosinolates                       |
|    15 | Carboline alkaloids                  |
|    14 | Other Octadecanoids                  |
|    12 | Terpenoid alkaloids                  |
|    12 | Dammarane and Protostane triterpenoids |
|    11 | Steroidal alkaloids                  |
|    10 | Aspidosperma type                    |
|    10 | Tetrahydroisoquinoline alkaloids     |
|     9 | Simple coumarins                     |

### HMDB — Top 20

| Count | Class                                |
|------:|--------------------------------------|
|    36 | Triacylglycerols                     |
|    23 | Aminoacids                           |
|    15 | Glycerophosphocholines               |
|    13 | Purine nucleos(t)ides                |
|     9 | Fatty acyl CoAs                      |
|     9 | pteridine alkaloids                  |
|     9 | Cholestane steroids                  |
|     8 | Simple phenolic acids                |
|     7 | Pyrimidine nucleos(t)ides            |
|     6 | Dipeptides                           |
|     6 | Pyridine alkaloids                   |
|     6 | Purine alkaloids                     |
|     5 | Simple indole alkaloids              |
|     5 | Pregnane steroids                    |
|     5 | Aminosugars                          |
|     4 | Androstane steroids                  |
|     4 | Cinnamic acids and derivatives       |
|     4 | Phenylethylamines                    |
|     4 | Oxo fatty acids                      |
|     3 | Branched fatty acids                 |

---

## 4. Glycoside breakdown (`isglycoside=true`)

| Pool                 | isglycoside=true | % of classified |
|----------------------|-----------------:|----------------:|
| RIKEN (712)          |              294 |       **41.3%** |
| HMDB (300)           |               15 |        **5.0%** |

The 8× rate gap aligns with RIKEN's natural-product focus
(flavonoid/saponin glycosides) vs. HMDB's central-metabolism enrichment.

---

## 5. Failed compounds & uninformative samples

**Failed:** 0 entries in cache have `status=failed`. Every API call eventually
returned a parseable JSON response.

**Empty-classification samples (RIKEN, first 10 — all three lists empty):**

| InChIKey first-block | Compound                                                       |
|----------------------|----------------------------------------------------------------|
| OGYHCBGORZWBPH       | 1-Isothiocyanato-7-(methylsulfinyl)-heptane                    |
| OZCACMPSTYQSMM       | Carbazochrome sulfonate                                        |
| SUVMJBTUFCVSAD       | 1-Isothiocyanato-4-(methylsulfinyl)-butane                     |
| LDIRGNDMTOGVRB       | 7-Methylsulfenylheptyl isothiocyanate                          |
| YRKLGWOHYXIKSF       | Indole-3-acetyl-L-glutamic acid                                |
| NYSQQJIJJJAWCE       | Pentose-Hexose + C5H9                                          |
| WCVUIHQUPRXYKT       | Licoagroside B (Not validated)                                 |
| AKPIJPQIDBGCGR       | S4:17(P3:15/F1:2)                                              |
| UPRCEYHEHWELCG       | S4:18(P3:16/F1:2)                                              |
| NNYRMMBHXZJRGM       | S4:19(P3:17/F1:2)                                              |

These are mostly **isothiocyanates / glucosinolate breakdown products**, **lipid
shorthand identifiers** (`S4:17(...)` style), and **adducts/conjugates** —
compounds that fall outside NPClassifier's training distribution. These should
be treated as "no NPClassifier signal" downstream, not "classifier broken".

---

## 6. ClassyFire cross-validation hooks

**Status:** the parallel ClassyFire session has not yet populated
`data/cache/classyfire/` in this worktree (0 files). Cross-validation cannot be
executed in this session.

**Hook readiness (when ClassyFire results land):**

- Both classifications are written under `ground_truth` as independent fields:
  - `ground_truth.classyfire` — kingdom/superclass/class/subclass/direct_parent
  - `ground_truth.npclassifier` — superclass[]/class_[]/pathway[]/isglycoside
- Cache key for both is the **InChIKey first-block**, so a join is one Python
  dict lookup per compound.
- Compounds with both classifications can be enumerated by intersecting
  `data/cache/npclassifier/*.json` and `data/cache/classyfire/*.json` filenames.
- Suggested side-by-side comparison columns:
  - `inchikey_first_block, smiles, name, cf.kingdom, cf.superclass, cf.class_,
    npc.superclass, npc.class_, npc.pathway, npc.isglycoside`

When ClassyFire run completes, a follow-up audit can sample 5 compounds from
each NPClassifier pathway and tabulate the corresponding ClassyFire labels.

---

## 7. Provenance

| Field                              | Value                                                                     |
|------------------------------------|---------------------------------------------------------------------------|
| Run timestamp (start → end)        | 2026-04-29 14:23 → 14:53 (Asia/Shanghai, ~30 min wall-clock with retries) |
| Git commit at run start            | `2361715` (`docs(benchmark): NM-002 audit on real GNPS+RIKEN data (D5)`)  |
| Branch                             | `feature/nm002-leakage-filter`                                            |
| Total successful API calls         | 993 (= unique cache entries, 0 failures)                                  |
| Total failed cache entries         | 0                                                                         |
| Cache size on disk                 | 4.0 MB                                                                    |
| Compounds shared by both pools     | 19 (HMDB hits served from RIKEN-warmed cache)                             |
| Request interval                   | 1.0 s between API calls                                                   |
| Retry policy                       | 3 retries on 429/502/503/504 + 1 pool-level 60-s pause-and-retry on SSL EOF |
| Outputs                            | `data/processed/compound_pool_riken_npc_classified.jsonl` (15.3 MB)       |
|                                    | `data/processed/hmdb_candidates_npc_classified.jsonl` (2.6 MB)            |
| Checkpoints                        | `data/processed/.npclassifier_riken_checkpoint.json`                      |
|                                    | `data/processed/.npclassifier_hmdb_checkpoint.json`                       |

### Notes on stability

NPClassifier service was stable enough to deliver a 100% classification rate but
not stable enough to run uninterrupted on an unhardened client:

- Two `SSL: UNEXPECTED_EOF_WHILE_READING` interruptions hit during the RIKEN
  run on different SMILES. The same SMILES re-tried seconds later returned
  HTTP 200 — confirming server-side connection drops, not input-specific issues.
- The client's pool layer was hardened with a single 60-second pause-and-retry
  on `NPClassifierNetworkError`; the scripts now write outputs from cache in a
  `finally`-style block so partial progress is never lost.
- HTTP 500 (NPClassifier's response to invalid SMILES) is treated as a
  permanent compound-level failure with a failure-cache entry; HTTP
  429/502/503/504 are transient and trigger retries.

### Reproduction

```bash
# RIKEN pool (5,930 spectra → 712 unique compounds)
python scripts/npclassifier/classify_riken_pool.py

# HMDB stratified sample (300 across 5 pathway domains)
python scripts/npclassifier/classify_hmdb_candidates.py
```

Both scripts are idempotent: re-running consults the cache and checkpoint, so
only missing entries trigger API calls.
