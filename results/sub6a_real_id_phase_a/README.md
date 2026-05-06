# Sub-6A Baseline LLM Evaluation Results — `library_search`

End-to-end (spectra → identification → narrative) pathway-enrichment results
for 14 tasks under the **library_search** identification strategy.

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
| identification acc (mean)| 72.07% |
| top1 strict rate         | 28.57% |
| top3 acceptance rate     | 28.57% |
| driver precision (mean)  | 0.286 |
| driver recall (mean)     | 0.053 |
| false noise rate (mean)  | 0.143 |
| off-pathway count (mean) | 7.07 |
| narrative chars (mean)   | 2478 |
| total identification time| 111.1 s |
| total LLM time           | 876.4 s |
| total elapsed            | 987.5 s |

## Notes on `library_search`

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
python scripts/eval_sub6/run_baseline.py --sub6a --id-strategy library_search
python scripts/eval_sub6/aggregate_sub6a.py --out-dir results/sub6a_real_id_phase_a
```
