# Sub-6A Baseline LLM Evaluation Results — `perfect_id`

End-to-end (spectra → identification → narrative) pathway-enrichment results
for 14 tasks under the **perfect_id** identification strategy.

## Files

- `sub6a_narratives.jsonl`     — raw runner output, one JSON record per task
- `sub6a_metrics.jsonl`        — per-task TaskMetrics + identification summary
- `sub6a_metrics.csv`          — same metrics, flat CSV
- `sub6a_summary.json`         — aggregated rates / means
- `sub6a_narratives.md`        — human-readable per-task scorecard + narrative
- `sub6a_identifications.csv` — per-spectrum top-1 audit (one row per spectrum)
- `README.md`                  — this file

## Headline numbers

| Metric | Value |
|---|---:|
| n_tasks                  | 14 |
| errors                   | 0 |
| identification acc (mean)| 100.00% |
| top1 strict rate         | 21.43% |
| top3 acceptance rate     | 21.43% |
| driver precision (mean)  | 0.539 |
| driver recall (mean)     | 0.260 |
| false noise rate (mean)  | 0.389 |
| off-pathway count (mean) | 6.57 |
| narrative chars (mean)   | 2576 |
| total identification time| 0.0 s |
| total LLM time           | 583.2 s |
| total elapsed            | 583.2 s |

## Notes on `perfect_id`

- **`perfect_id`** — bypasses library_search and uses each spectrum's GT
  InChIKey as the prediction. Identification accuracy is trivially 1.0;
  the resulting metric is the **upper-bound baseline** for LLM reasoning
  on Sub-6A inputs (i.e. "what would the LLM achieve if identification
  were perfect").
- **`library_search`** — runs real spectrum identification with per-task
  GNPS exclusion (eval guide §3 pitfall 1). Used to measure end-to-end
  baseline including identification noise.

## Reproduce

```bash
export MINIMAX_API_KEY="$(cat api_key.txt | tr -d '[:space:]')"
python scripts/eval_sub6/run_baseline.py --sub6a --id-strategy perfect_id
python scripts/eval_sub6/aggregate_sub6a.py --out-dir results/sub6a_perfect_id
```
