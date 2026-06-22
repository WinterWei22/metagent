# Full344 Pathway-Level Scorecard

ID-exact and semantic metrics are reported separately. Semantic is the looser rubric-defined match.

LLM cost from JSONL: $13.099171

## Contamination

{
  "overall": {
    "ratelimit": 88,
    "clean": 256
  },
  "by_stratum": {
    "hmdb_ramp": {
      "ratelimit": 88,
      "clean": 75
    },
    "human1": {
      "clean": 117
    },
    "recon22": {
      "clean": 64
    }
  }
}

## All Denominator

| stratum | tasks | prediction ok | primary ID-exact | primary name-exact | primary semantic | top-k ID-exact | top-k semantic | abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| overall | 344 | 56.40% | 0.00% | 12.50% | 18.02% | 0.00% | 23.84% | 5.52% |
| hmdb_ramp | 163 | 44.79% | 0.00% | 23.31% | 28.83% | 0.00% | 33.74% | 0.00% |
| human1 | 117 | 84.62% | 0.00% | 4.27% | 12.82% | 0.00% | 23.08% | 2.56% |
| recon22 | 64 | 34.38% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 25.00% |

## Clean Denominator

| stratum | tasks | prediction ok | primary ID-exact | primary name-exact | primary semantic | top-k ID-exact | top-k semantic | abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| overall | 256 | 75.78% | 0.00% | 16.80% | 24.22% | 0.00% | 32.03% | 7.42% |
| hmdb_ramp | 75 | 97.33% | 0.00% | 50.67% | 62.67% | 0.00% | 73.33% | 0.00% |
| human1 | 117 | 84.62% | 0.00% | 4.27% | 12.82% | 0.00% | 23.08% | 2.56% |
| recon22 | 64 | 34.38% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 25.00% |

## Recall@k and Driver P/R (Clean Denominator)

| stratum | tasks | recall@3 | hit@3 | MRR | driver P | driver R |
|---|---:|---:|---:|---:|---:|---:|
| overall | 256 | 0.1251 | 0.2344 | 0.2044 | 0.7949 | 0.1893 |
| hmdb_ramp | 75 | 0.3436 | 0.6667 | 0.5844 | 0.7949 | 0.1893 |
| human1 | 117 | 0.0534 | 0.0855 | 0.0727 | N/A | N/A |
| recon22 | 64 | 0.0000 | 0.0000 | 0.0000 | N/A | N/A |

## Validation Candidates

Rows selected for manual semantic/abstain review: 48

