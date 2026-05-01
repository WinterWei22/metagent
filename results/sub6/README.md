# Sub-6B Baseline LLM Evaluation Results

Naked LLM (no verifier) pathway-enrichment narratives for 20 compound-only tasks.

## Files

- `sub6b_narratives.jsonl` — raw LLM outputs, one JSON record per task
- `sub6b_metrics.jsonl`    — per-task TaskMetrics + provenance, JSON Lines
- `sub6b_metrics.csv`      — same metrics, flat CSV
- `sub6b_summary.json`     — aggregated rates / means across all tasks
- `sub6b_narratives.md`    — human-readable per-task narrative + scorecards
- `README.md`              — this file

## Headline numbers

| Metric | Value |
|---|---:|
| n_tasks                  | 20 |
| errors                   | 0 |
| top1 strict rate         | 30.00% |
| top3 acceptance rate     | 35.00% |
| driver precision (mean)  | 0.750 |
| driver recall (mean)     | 0.432 |
| false noise rate (mean)  | 0.250 |
| off-pathway count (mean) | 5.70 |
| narrative chars (mean)   | 2189 |
| total LLM time           | 779.2 s |
| per-task LLM time (mean) | 39.0 s |

## How metrics are computed

See `evaluation/sub6/metrics.py` (`compute_task_metrics`) and
`reports/benchmark/sub6_evaluation_guide.md` §4. Briefly:

- **top1_pathway_strict**: the LLM's first-mentioned pathway is a fuzzy match
  to `ground_truth_pathway.pathway_name`. Fuzzy = case-insensitive substring,
  or content-token-subset after stripping suffix words ("metabolism",
  "catabolism", "biosynthesis", ...).
- **top3_pathway_acceptance**: the LLM's first-mentioned pathway matches any
  of the top-3 RaMP enrichment pathways.
- **driver_precision / recall**: drivers cited in the narrative
  (sentence-level co-occurrence with markers like "key driver", "drives")
  are resolved to InChIKey first-block via the curated pool, then compared
  to `ground_truth_signal_compounds` (KEGG → InChIKey).
- **false_noise_rate**: fraction of cited drivers that are in
  `ground_truth_noise_compounds`.
- **off_pathway_count**: pathway mentions that don't match any of the top-10
  RaMP candidates — proxy for hallucination.

## Reproduce

```bash
export MINIMAX_API_KEY="$(cat api_key.txt | tr -d '[:space:]')"
python -c "from evaluation.sub6.run_sub6b import run_sub6b_batch; \
  run_sub6b_batch( \
    'data/benchmark/sub6/sub6b_mammalian_tasks.jsonl', \
    'data/eval/sub6/sub6b_narratives.jsonl', \
    caller='sub6b_baseline')"
python scripts/eval_sub6/aggregate_sub6b.py --out-dir results/sub6
```

The runner is idempotent: already-completed `task_id`s in the output JSONL
are skipped. Delete the JSONL to force a full re-run.
