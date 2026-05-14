# HMDB Pool Expansion Audit

**Generated:** 2026-05-06T07:57:39+00:00
**Wall time:** 762.1s

## 1. Summary

| metric | original (300) | v2 (600+) |
|---|---:|---:|
| total candidates | 300 | 600 |
| amino_acid_metabolism bucket | 60 | 120 |
| central_metabolism bucket | 60 | 120 |
| lipid_metabolism bucket | 60 | 120 |
| nucleotide_metabolism bucket | 60 | 120 |
| other bucket | 60 | 120 |
| unique KEGG IDs | 245 | 526 |
| NPClassifier cache hits | 300 | 320 |
| NPClassifier API calls (new) | 0 | 280 |
| API call failures | n/a | 0 |

## 2. Selection Logic

HMDB query and RaMP join are reused from `scripts/npclassifier/classify_hmdb_candidates.py`:

```sql
SELECT m.hmdb_id, m.primary_name, m.molecular_formula, m.exact_mass,
       m.smiles, m.inchikey, m.chemical_class, m.kegg_id,
       m.chebi_id, m.pubchem_cid,
       COUNT(DISTINCT p.pathwayRampId) AS pathway_count,
       GROUP_CONCAT(DISTINCT p.pathwayName) AS pathway_names
FROM metabolites m
JOIN ramp.source s
  ON s.sourceId = 'kegg:' || m.kegg_id
 AND s.geneOrCompound = 'compound'
JOIN ramp.analytehaspathway ahp ON ahp.rampId = s.rampId
JOIN ramp.pathway p ON p.pathwayRampId = ahp.pathwayRampId
WHERE m.kegg_id IS NOT NULL AND m.kegg_id != ''
  AND m.smiles IS NOT NULL AND m.smiles != ''
  AND m.inchikey IS NOT NULL AND m.inchikey != ''
  AND m.exact_mass BETWEEN 50 AND 1000
GROUP BY m.hmdb_id
```

Pathway-domain assignment is the existing first-match keyword rule over RaMP pathway names:

```python
joined = ' | '.join(pathway_names).lower()
for domain, keywords in DOMAIN_KEYWORDS.items():
    if any(keyword.lower() in joined for keyword in keywords):
        return domain
return 'other'
```

Domain keywords:

```json
{
  "amino_acid_metabolism": [
    "amino acid",
    "alanine",
    "arginine",
    "aspartate",
    "cysteine",
    "glutamate",
    "glutamine",
    "glycine",
    "histidine",
    "isoleucine",
    "leucine",
    "lysine",
    "methionine",
    "phenylalanine",
    "proline",
    "serine",
    "threonine",
    "tryptophan",
    "tyrosine",
    "valine"
  ],
  "central_metabolism": [
    "tca",
    "citric acid",
    "glycolysis",
    "gluconeogenesis",
    "pentose phosphate",
    "pyruvate",
    "citrate cycle"
  ],
  "lipid_metabolism": [
    "lipid",
    "fatty acid",
    "beta-oxidation",
    "\u03b2-oxidation",
    "phospholipid",
    "sphingolipid",
    "glycerolipid",
    "bile acid",
    "steroid"
  ],
  "nucleotide_metabolism": [
    "purine",
    "pyrimidine",
    "nucleotide",
    "nucleoside",
    "riboflavin",
    "folate"
  ]
}
```

Selection pins all original 300 rows, then adds candidates round-robin across the five buckets to target 120 per bucket. New rows prefer KEGG IDs not already present in v1; duplicate KEGG rows are only used if a bucket cannot otherwise fill.

## 3. Per-Bucket Sample

### amino_acid_metabolism

- alpha-Ketoisovaleric acid (`C00141`) — Fatty acids
- 3-Methoxytyramine (`C05587`) — Alkaloids
- (S)-3-Hydroxyisobutyric acid (`C06001`) — Fatty acids
- Argininosuccinic acid (`C03406`) — Amino acids and Peptides
- Pipecolic acid (`C00408`) — Amino acids and Peptides

### central_metabolism

- Adenosine monophosphate (`C00020`) — Carbohydrates
- Adenosine (`C00212`) — Carbohydrates
- Cyclic AMP (`C00575`) — Carbohydrates
- Cortisol (`C00735`) — Terpenoids
- Cholesterol (`C00187`) — Terpenoids

### lipid_metabolism

- Cortexolone (`C05488`) — Terpenoids
- Deoxycorticosterone (`C03205`) — Terpenoids
- Tetrahydrobiopterin (`C00272`) — Alkaloids
- Androsterone (`C00523`) — Terpenoids
- 7-Dehydrocholesterol (`C01164`) — Terpenoids

### nucleotide_metabolism

- 2-Ketobutyric acid (`C00109`) — Fatty acids
- Deoxyuridine (`C00526`) — Carbohydrates
- Deoxycytidine (`C00881`) — Carbohydrates
- Ureidopropionic acid (`C02642`) — Amino acids and Peptides
- Dihydrobiopterin (`C02953`) — Alkaloids

### other

- 4-Pyridoxic acid (`C00847`) — Alkaloids
- Cysteinylglycine (`C01419`) — Amino acids and Peptides
- Phenol (`C15584`) — Shikimates and Phenylpropanoids
- Pyroglutamic acid (`C01879`) — Amino acids and Peptides
- 2-Methoxyestradiol (`C05302`) — Terpenoids

## 4. Coverage Gaps

- `amino_acid_metabolism`: 120/120 selected; HMDB candidate capacity 341 (filled).
- `central_metabolism`: 120/120 selected; HMDB candidate capacity 419 (filled).
- `lipid_metabolism`: 120/120 selected; HMDB candidate capacity 711 (filled).
- `nucleotide_metabolism`: 120/120 selected; HMDB candidate capacity 161 (filled).
- `other`: 120/120 selected; HMDB candidate capacity 1475 (filled).

## 5. NPClassifier API Stats

- Cache files before: 993
- Cache files after: 1273
- Cache files added: 280
- Cache hits/checkpoint skips: 320
- API calls: 280
- Failed compounds: 0

## 6. Provenance

- Git commit SHA: `06f0f21397faab244916c67bc0ac112ba06d040c`
- Output file: `data/processed/hmdb_candidates_npc_classified_v2.jsonl`
- File MD5: `8824f112a1a63e2f91fcc451ce157244`
- Wall time: 762.1s
- Command: `scripts/expand_hmdb_pool.py --request-interval 1.0`

## 7. Handoff to Phase 1

Phase 1 should rerun `scripts/build_sub6/build_all.py` with:

```bash
PYTHONPATH=. python scripts/build_sub6/build_all.py \
    --hmdb-candidates data/processed/hmdb_candidates_npc_classified_v2.jsonl \
    --target-6b-mammalian 100 \
    --target-curated-hmdb 250 \
    --pathway-min-compounds 3 \
    --tasks-per-pathway-max 10 \
    --tasks-per-bucket-max 20 \
    --output-dir data/benchmark/sub6/ \
    --report-path reports/benchmark/sub6_construction_report_v2_raw.md \
    --skip-spectrum-index \
    --seed 42
```

Expected Sub-6B task count by linear extrapolation is roughly `35 * 600 / 250 = 84`, but the real value depends on unique KEGG coverage after RaMP top-3 validation. Central/lipid task recovery is expected to improve if the added pool survives task-stage mammalian pathway filtering.

## Acceptance Snapshot

- Original file preserved: True
- v2 row count >= 500: True
- v2 contains all original KEGG IDs: True
- v2 contains all original InChIKey first-blocks: True
- Every bucket >= 50: True
- Records missing npclassifier: 0
