# Stage2 Pathway Prediction Second-Pass Scorecard

Main ReAct outputs are stored dumps; only the independent second-pass pathway selector was run.

LLM cost from `logs/concord/pathway_prediction_second_pass_full163.jsonl`: $0.211319

| stratum | tasks | prediction ok | primary ID-exact | primary name-exact | primary semantic | top-k ID-exact | top-k name-exact | top-k semantic | abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| overall | 163 | 159 | 0.00% | 38.65% | 49.69% | 0.00% | 50.31% | 59.51% | 0.61% |
| hmdb_ramp_pathway_membership | 100 | 99 | 0.00% | 30.00% | 41.00% | 0.00% | 40.00% | 51.00% | 1.00% |
| sub6_hmdb_ramp_enrichment | 63 | 60 | 0.00% | 52.38% | 63.49% | 0.00% | 66.67% | 73.02% | 0.00% |
