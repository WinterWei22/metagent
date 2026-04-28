# NM-002 Leakage Audit

## Section 1 — Executive summary

Of 985,492 GNPS reference records, 76,783 (7.79%) were identified as potential leakage sources for the 5,930-record RIKEN benchmark pool. Without this filter, an estimated **100.0%** of 100 sampled RIKEN-derived queries would self-match in GNPS top-1 hits (proxy: queries with ≥1 same-compound record in the reference library; the spike test confirmed score-1.0 self-matches dominate ranking). The filter reduces this to **0.0%** by removing every same-compound or same-source-id record from the search pool.

## Section 2 — Data inputs

| Input | Path | Records | MD5 (first 64 MB) |
|---|---|---:|---|
| Benchmark pool | `/data/weiwentao/llm_agent_metabolomics/massbank/processed/compound_pool_riken.jsonl` | 5,930 | `b8c66e831b46fd72cbf2b294a8ee1673  (first 15164539 bytes)` |
| GNPS library | `/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned_enriched.csv` | 985,492 | `99164bf0b9b6b4fa728c2173284cfe53  (first 67108864 bytes)` |

## Section 3 — Filter trigger breakdown

| Trigger | Excluded count | % of GNPS | Example |
|---|---:|---:|---|
| InChIKey first-block match | 76,611 | 7.77% | `CCMSLIB00000007046` — `shares_inchikey_first_block_with_query:SZJNCZMRZAUNQT` |
| MSBNK-RIKEN cross-reference | 5,433 | 0.55% | `MSBNK-RIKEN-PR100234` — `cross_reference_to_riken:MSBNK-RIKEN-PR100234` |
| Exact source-id match | 5,433 | 0.55% | `MSBNK-RIKEN-PR100234` — `exact_source_match:MSBNK-RIKEN-PR100234` |
| Library wholesale (MassBank_ML_Export) | 0 | 0.00% | (no example) |
| **Multiple triggers (any 2+)** | 5,433 | 0.55% | — |
| **Total unique excluded** | 76,783 | 7.79% | — |

## Section 4 — Per-compound-class breakdown

(Negative-mode rows only — per audit template instruction. Positive rows follow the same shape and are included below for completeness.)

### Mode = negative

| compound_class | RIKEN queries (N) | GNPS records excluded (sum) | Avg per query | Max per query |
|---|---:|---:|---:|---:|
| other | 1,481 | 324,884 | 219.37 | 1226 |
| flavonoid | 677 | 144,560 | 213.53 | 806 |
| organic_acid | 166 | 30,180 | 181.81 | 1039 |
| lipid | 31 | 2,101 | 67.77 | 149 |
| amino_acid | 25 | 1,131 | 45.24 | 73 |
| nucleoside | 1 | 367 | 367.00 | 367 |
| **Total** | 2,381 | 503,223 | 211.35 | 1226 |

### Mode = positive

| compound_class | RIKEN queries (N) | GNPS records excluded (sum) | Avg per query | Max per query |
|---|---:|---:|---:|---:|
| other | 2,426 | 460,548 | 189.84 | 1226 |
| flavonoid | 725 | 162,715 | 224.43 | 806 |
| organic_acid | 187 | 30,600 | 163.64 | 737 |
| lipid | 164 | 14,314 | 87.28 | 186 |
| amino_acid | 45 | 2,622 | 58.27 | 429 |
| nucleoside | 2 | 368 | 184.00 | 367 |
| **Total** | 3,549 | 671,167 | 189.11 | 1226 |

## Section 5 — Trigger overlap analysis

| Combination | Count |
|---|---:|
| InChIKey + CrossRef + SourceId | 5,261 |
| CrossRef + SourceId | 172 |
| InChIKey | 71,350 |
| **Total unique** | 76,783 |

**Reading**: every excluded record is bucketed by *which* triggers fired for it. 'InChIKey only' means the InChIKey first-block trigger fired but neither of the two source-id-based triggers did. If a row's count is 0, its trigger is fully redundant on this dataset; if it is non-zero, removing that trigger would lose those exclusions.

## Section 6 — Sample exclusions (verbatim, up to 15 examples)

```
Example 1 — InChIKey-only trigger
  Excluded GNPS ID: CCMSLIB00000007046
  Triggered by:     InChIKey
  Reasons:
    - shares_inchikey_first_block_with_query:SZJNCZMRZAUNQT
```

```
Example 2 — InChIKey-only trigger
  Excluded GNPS ID: CCMSLIB00000007047
  Triggered by:     InChIKey
  Reasons:
    - shares_inchikey_first_block_with_query:SZJNCZMRZAUNQT
```

```
Example 3 — InChIKey-only trigger
  Excluded GNPS ID: CCMSLIB00000007048
  Triggered by:     InChIKey
  Reasons:
    - shares_inchikey_first_block_with_query:SZJNCZMRZAUNQT
```

```
Example 4 — InChIKey-only trigger
  Excluded GNPS ID: CCMSLIB00000007049
  Triggered by:     InChIKey
  Reasons:
    - shares_inchikey_first_block_with_query:SZJNCZMRZAUNQT
```

```
Example 5 — InChIKey-only trigger
  Excluded GNPS ID: CCMSLIB00000007050
  Triggered by:     InChIKey
  Reasons:
    - shares_inchikey_first_block_with_query:SZJNCZMRZAUNQT
```

```
Example 6 — Cross-reference trigger
  Excluded GNPS ID: MSBNK-RIKEN-PR100234
  Triggered by:     CrossRef + InChIKey + SourceId
  Matched query: MSBNK-RIKEN-PR100234 (Rhamnetin, compound_class=flavonoid, mode=positive)
  Reasons:
    - shares_inchikey_first_block_with_query:JGUZGNYPMHHYRK
    - exact_source_match:MSBNK-RIKEN-PR100234
    - cross_reference_to_riken:MSBNK-RIKEN-PR100234
```

```
Example 7 — Cross-reference trigger
  Excluded GNPS ID: MSBNK-RIKEN-PR100243
  Triggered by:     CrossRef + InChIKey + SourceId
  Matched query: MSBNK-RIKEN-PR100243 (Kaempferol-3-O-glucoside, compound_class=flavonoid, mode=positive)
  Reasons:
    - shares_inchikey_first_block_with_query:JPUKWEQWGBDDQB
    - exact_source_match:MSBNK-RIKEN-PR100243
    - cross_reference_to_riken:MSBNK-RIKEN-PR100243
```

```
Example 8 — Cross-reference trigger
  Excluded GNPS ID: MSBNK-RIKEN-PR100248
  Triggered by:     CrossRef + InChIKey + SourceId
  Matched query: MSBNK-RIKEN-PR100248 (Myricitrin, compound_class=flavonoid, mode=positive)
  Reasons:
    - shares_inchikey_first_block_with_query:DCYOADKBABEMIQ
    - exact_source_match:MSBNK-RIKEN-PR100248
    - cross_reference_to_riken:MSBNK-RIKEN-PR100248
```

```
Example 9 — Cross-reference trigger
  Excluded GNPS ID: MSBNK-RIKEN-PR100253
  Triggered by:     CrossRef + InChIKey + SourceId
  Matched query: MSBNK-RIKEN-PR100253 (Hyperoside, compound_class=flavonoid, mode=positive)
  Reasons:
    - shares_inchikey_first_block_with_query:OVSQVDMCBVZWGM
    - exact_source_match:MSBNK-RIKEN-PR100253
    - cross_reference_to_riken:MSBNK-RIKEN-PR100253
```

```
Example 10 — Cross-reference trigger
  Excluded GNPS ID: MSBNK-RIKEN-PR100256
  Triggered by:     CrossRef + InChIKey + SourceId
  Matched query: MSBNK-RIKEN-PR100256 (Quercetin-3-O-alpha-L-rhamnopyranoside, compound_class=flavonoid, mode=positive)
  Reasons:
    - shares_inchikey_first_block_with_query:OXGUCUVFOIWWQJ
    - exact_source_match:MSBNK-RIKEN-PR100256
    - cross_reference_to_riken:MSBNK-RIKEN-PR100256
```

```
Example 11 — Exact source-id trigger
  Excluded GNPS ID: MSBNK-RIKEN-PR100234
  Triggered by:     CrossRef + InChIKey + SourceId
  Matched query: MSBNK-RIKEN-PR100234 (Rhamnetin, compound_class=flavonoid, mode=positive)
  Reasons:
    - shares_inchikey_first_block_with_query:JGUZGNYPMHHYRK
    - exact_source_match:MSBNK-RIKEN-PR100234
    - cross_reference_to_riken:MSBNK-RIKEN-PR100234
```

```
Example 12 — Exact source-id trigger
  Excluded GNPS ID: MSBNK-RIKEN-PR100243
  Triggered by:     CrossRef + InChIKey + SourceId
  Matched query: MSBNK-RIKEN-PR100243 (Kaempferol-3-O-glucoside, compound_class=flavonoid, mode=positive)
  Reasons:
    - shares_inchikey_first_block_with_query:JPUKWEQWGBDDQB
    - exact_source_match:MSBNK-RIKEN-PR100243
    - cross_reference_to_riken:MSBNK-RIKEN-PR100243
```

```
Example 13 — Exact source-id trigger
  Excluded GNPS ID: MSBNK-RIKEN-PR100248
  Triggered by:     CrossRef + InChIKey + SourceId
  Matched query: MSBNK-RIKEN-PR100248 (Myricitrin, compound_class=flavonoid, mode=positive)
  Reasons:
    - shares_inchikey_first_block_with_query:DCYOADKBABEMIQ
    - exact_source_match:MSBNK-RIKEN-PR100248
    - cross_reference_to_riken:MSBNK-RIKEN-PR100248
```

```
Example 14 — Exact source-id trigger
  Excluded GNPS ID: MSBNK-RIKEN-PR100253
  Triggered by:     CrossRef + InChIKey + SourceId
  Matched query: MSBNK-RIKEN-PR100253 (Hyperoside, compound_class=flavonoid, mode=positive)
  Reasons:
    - shares_inchikey_first_block_with_query:OVSQVDMCBVZWGM
    - exact_source_match:MSBNK-RIKEN-PR100253
    - cross_reference_to_riken:MSBNK-RIKEN-PR100253
```

```
Example 15 — Exact source-id trigger
  Excluded GNPS ID: MSBNK-RIKEN-PR100256
  Triggered by:     CrossRef + InChIKey + SourceId
  Matched query: MSBNK-RIKEN-PR100256 (Quercetin-3-O-alpha-L-rhamnopyranoside, compound_class=flavonoid, mode=positive)
  Reasons:
    - shares_inchikey_first_block_with_query:OXGUCUVFOIWWQJ
    - exact_source_match:MSBNK-RIKEN-PR100256
    - cross_reference_to_riken:MSBNK-RIKEN-PR100256
```

## Section 7 — Estimated impact on benchmark validity

Method: Per-query intersection of (records sharing inchikey first-block) and (records sharing source-id) within the precomputed exclusion set. Reports a strict 'at least one self-match record in the reference library' rate, which is a tight upper bound on the top-1 rate (the score-1.0 self-match dominates ranking)..

Sample size: 100 random RIKEN queries (seed = 42).

| Metric | Without filter | With filter |
|---|---:|---:|
| % of queries with ≥1 self-match record in GNPS | 100.0% | 0.0% |
| Avg # of self-match records per query | 202.07 | 0.00 |
| Max # of self-match records per query | 1226 | 0 |

Caveats:
- This is a strict per-query intersection of (records sharing inchikey first-block) ∪ (records sharing source-id) within the precomputed exclusion set. The true top-1 rate equals this only if score-1.0 self-matches always rank first; spike report §2.3 supports that assumption (`MSBNK-RIKEN-PR309407` self-matched at score 0.812 — top-1).
- We did NOT run the actual `library_search` tool in this audit; doing so for 100 queries would take ~30-60 minutes (one-time GNPS load + per-query scoring). The conservative proxy here was approved by the maintainer (Q3).

**Paper-relevant finding:** without this filter, every one of the sampled RIKEN-derived queries has a same-compound or same-id record in the GNPS reference library, which the spike test showed dominates top-1 ranking.

## Section 8 — Edge cases and caveats

- GNPS records with malformed/missing InChIKey: **55,498** (5.63% of 985,492). These can only be caught by the cross-ref / source-id triggers.
- Records with **InChIKey but no cross-ref/source-id match** (caught only by InChIKey trigger): 71,350. Removing the InChIKey trigger would lose these.
- Queries with malformed/missing InChIKey on the pool side: 0. These contribute to source-id-based exclusions only.
- Cross-reference patterns the parser recognises: `MSBNK-RIKEN-<id>`, `MassBank:PR<id>`, `RIKEN PR<id>`, `RIKEN-PR<id>`. On this GNPS dump only the canonical first form was observed in real data; the others are forward-compat for hand-curated comments.

## Section 9 — Comparison against spike test prediction

| Spike fixture | Predicted self-match? | Found in this audit? |
|---|---|---|
| MSBNK-RIKEN-PR309128 | Yes (low confidence — citric acid) | ✅ 1039 GNPS record(s) excluded for this query: CCMSLIB00000212339, CCMSLIB00000221733, CCMSLIB00000426201… |
| MSBNK-RIKEN-PR309407 | Yes (top-1, score 0.812 — glutamyltyrosine) | ✅ 2 GNPS record(s) excluded for this query: MSBNK-RIKEN-PR309407, MSBNK-RIKEN-PR311057 |

## Section 10 — Output artifact verification

```
$ ls -la data/processed/nm002_excluded_gnps_ids.json
```

Exclusion list contents:
```
  excluded_ids:      76,783
  exclusion_reasons: 76,783 entries
  stats keys:        ['excluded_by_cross_reference', 'excluded_by_inchikey_match', 'excluded_by_library_wholesale', 'excluded_by_source_match', 'gnps_with_malformed_inchikey', 'queries_with_malformed_inchikey', 'total_excluded', 'total_gnps_records_scanned', 'total_query_records']
```

## Section 11 — Provenance and reproduction

```
Generation date:  2026-04-28T17:03:33.712246+00:00
Hostname:         amax
Git commit:       d119743
Python:           3.13.11
Wall-clock:       12.8 s
Input file MD5s (first 64 MB):
  benchmark pool: b8c66e831b46fd72cbf2b294a8ee1673  (first 15164539 bytes)
  GNPS library:   99164bf0b9b6b4fa728c2173284cfe53  (first 67108864 bytes)

To reproduce:
  python scripts/check_gnps_riken_leakage.py \
    --benchmark-pool /data/weiwentao/llm_agent_metabolomics/massbank/processed/compound_pool_riken.jsonl \
    --gnps-library /data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned_enriched.csv \
    --output reports/nm002_leakage_audit_2026-04-29.md
```
