# Full344 Pathway-Level Scorecard

ID-exact and semantic metrics are reported separately. Semantic is the looser rubric-defined match.

LLM cost from JSONL: $0.000000

## Contamination

{
  "overall": {
    "clean": 81
  },
  "by_stratum": {
    "hmdb_ramp": {
      "clean": 18
    },
    "sub6": {
      "clean": 63
    }
  }
}

## All Denominator

| stratum | tasks | prediction ok | primary ID-exact | primary name-exact | primary semantic | top-k ID-exact | top-k semantic | abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| overall | 81 | 96.30% | 0.00% | 67.90% | 69.14% | 0.00% | 86.42% | 0.00% |
| hmdb_ramp | 18 | 94.44% | 0.00% | 77.78% | 83.33% | 0.00% | 88.89% | 0.00% |
| sub6 | 63 | 96.83% | 0.00% | 65.08% | 65.08% | 0.00% | 85.71% | 0.00% |

## Clean Denominator

| stratum | tasks | prediction ok | primary ID-exact | primary name-exact | primary semantic | top-k ID-exact | top-k semantic | abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| overall | 81 | 96.30% | 0.00% | 67.90% | 69.14% | 0.00% | 86.42% | 0.00% |
| hmdb_ramp | 18 | 94.44% | 0.00% | 77.78% | 83.33% | 0.00% | 88.89% | 0.00% |
| sub6 | 63 | 96.83% | 0.00% | 65.08% | 65.08% | 0.00% | 85.71% | 0.00% |

## Recall@k and Driver P/R (Clean Denominator)

| stratum | tasks | recall@3 | hit@3 | MRR | driver P | driver R |
|---|---:|---:|---:|---:|---:|---:|
| overall | 81 | 0.4384 | 0.8765 | 0.7860 | 0.9108 | 0.2230 |
| hmdb_ramp | 18 | 0.3161 | 0.8889 | 0.8333 | 0.8519 | 0.1987 |
| sub6 | 63 | 0.4734 | 0.8730 | 0.7725 | 0.9308 | 0.2313 |

## Validation Candidates

Rows selected for manual semantic/abstain review: 15

