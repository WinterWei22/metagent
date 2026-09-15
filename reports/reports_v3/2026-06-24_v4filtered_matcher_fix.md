# Full344 Pathway-Level Scorecard

ID-exact and semantic metrics are reported separately. Semantic is the looser rubric-defined match.

LLM cost from JSONL: $0.000000

## Contamination

{
  "overall": {
    "clean": 342
  },
  "by_stratum": {
    "hmdb_ramp": {
      "clean": 99
    },
    "human1": {
      "clean": 116
    },
    "recon22": {
      "clean": 64
    },
    "sub6": {
      "clean": 63
    }
  }
}

## All Denominator

| stratum | tasks | prediction ok | primary ID-exact | primary name-exact | primary semantic | top-k ID-exact | top-k semantic | abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| overall | 342 | 97.08% | 0.00% | 27.19% | 33.92% | 0.00% | 45.61% | 0.00% |
| hmdb_ramp | 99 | 95.96% | 0.00% | 38.38% | 47.47% | 0.00% | 57.58% | 0.00% |
| human1 | 116 | 97.41% | 0.00% | 7.76% | 15.52% | 0.00% | 24.14% | 0.00% |
| recon22 | 64 | 96.88% | 0.00% | 12.50% | 17.19% | 0.00% | 31.25% | 0.00% |
| sub6 | 63 | 98.41% | 0.00% | 60.32% | 63.49% | 0.00% | 80.95% | 0.00% |

## Clean Denominator

| stratum | tasks | prediction ok | primary ID-exact | primary name-exact | primary semantic | top-k ID-exact | top-k semantic | abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| overall | 342 | 97.08% | 0.00% | 27.19% | 33.92% | 0.00% | 45.61% | 0.00% |
| hmdb_ramp | 99 | 95.96% | 0.00% | 38.38% | 47.47% | 0.00% | 57.58% | 0.00% |
| human1 | 116 | 97.41% | 0.00% | 7.76% | 15.52% | 0.00% | 24.14% | 0.00% |
| recon22 | 64 | 96.88% | 0.00% | 12.50% | 17.19% | 0.00% | 31.25% | 0.00% |
| sub6 | 63 | 98.41% | 0.00% | 60.32% | 63.49% | 0.00% | 80.95% | 0.00% |

## Recall@k and Driver P/R (Clean Denominator)

| stratum | tasks | recall@3 | hit@3 | MRR | driver P | driver R |
|---|---:|---:|---:|---:|---:|---:|
| overall | 342 | 0.1985 | 0.4035 | 0.3499 | 0.8070 | 0.2319 |
| hmdb_ramp | 99 | 0.1548 | 0.5354 | 0.4848 | 0.7323 | 0.2354 |
| human1 | 116 | 0.0977 | 0.1724 | 0.1351 | N/A | N/A |
| recon22 | 64 | 0.1953 | 0.2031 | 0.1615 | N/A | N/A |
| sub6 | 63 | 0.4557 | 0.8254 | 0.7249 | 0.9465 | 0.2254 |

## Validation Candidates

Rows selected for manual semantic/abstain review: 45

