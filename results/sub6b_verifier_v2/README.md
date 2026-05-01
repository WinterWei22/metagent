# Verifier-graded results — `sub6b`

Output of `verifier.agent.verify_sub6` applied to the Sub-6 narratives
under track `sub6b`. Mirrors the layout of `results/sub6/` (the
extractor-graded baseline) so the two scorings can be diffed.

## Files

- `sub6b_verdicts.jsonl`         — raw verifier output (one record per task)
- `sub6b_verdicts.csv`           — flat per-task verdict counts
- `sub6b_verdicts_summary.json`  — aggregate verdict counters / rates
- `sub6b_verdicts.md`            — per-task scorecard + claim list + narrative
- `README.md`                            — this file

## Headline numbers

| Metric | Value |
|---|---:|
| n_tasks               | 20 |
| n_error               | 0 |
| total claims          | 772 |
| verifier LLM calls    | 0 |
| supported             | 55 (7.12%) |
| unsupported           | 255 (33.03%) |
| contradicted          | 28 (3.63%) |
| unverifiable_v0       | 434 (56.22%) |
| tasks w/ ≥1 SUPPORTED set_enrichment | 2 / 20 |
| tasks w/ ≥1 CONTRADICTED driver_metabolite | 2 / 20 |

## How to reproduce

```bash
export MINIMAX_API_KEY="$(cat api_key.txt | tr -d '[:space:]')"
python scripts/eval_sub6/grade_with_verifier.py \
    --narratives results/sub6/sub6b_narratives.jsonl \
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \
    --out data/eval/sub6/sub6b_verdicts.jsonl \
    --track sub6b
python scripts/eval_sub6/aggregate_verifier.py \
    --verdicts data/eval/sub6/sub6b_verdicts.jsonl \
    --narratives results/sub6/sub6b_narratives.jsonl \
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \
    --track sub6b \
    --out-dir results/sub6b_verifier_v2
```
