# Verifier-graded results — `sub6a_perfect_id`

Output of `verifier.agent.verify_sub6` applied to the Sub-6 narratives
under track `sub6a_perfect_id`. Mirrors the layout of `results/sub6/` (the
extractor-graded baseline) so the two scorings can be diffed.

## Files

- `sub6a_perfect_id_verdicts.jsonl`         — raw verifier output (one record per task)
- `sub6a_perfect_id_verdicts.csv`           — flat per-task verdict counts
- `sub6a_perfect_id_verdicts_summary.json`  — aggregate verdict counters / rates
- `sub6a_perfect_id_verdicts.md`            — per-task scorecard + claim list + narrative
- `README.md`                            — this file

## Headline numbers

| Metric | Value |
|---|---:|
| n_tasks               | 14 |
| n_error               | 0 |
| total claims          | 658 |
| verifier LLM calls    | 0 |
| supported             | 62 (9.42%) |
| unsupported           | 200 (30.40%) |
| contradicted          | 18 (2.74%) |
| unverifiable_v0       | 378 (57.45%) |
| tasks w/ ≥1 SUPPORTED set_enrichment | 3 / 14 |
| tasks w/ ≥1 CONTRADICTED driver_metabolite | 3 / 14 |

## How to reproduce

```bash
export MINIMAX_API_KEY="$(cat api_key.txt | tr -d '[:space:]')"
python scripts/eval_sub6/grade_with_verifier.py \
    --narratives results/sub6/sub6b_narratives.jsonl \
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \
    --out data/eval/sub6/sub6b_verdicts.jsonl \
    --track sub6a_perfect_id
python scripts/eval_sub6/aggregate_verifier.py \
    --verdicts data/eval/sub6/sub6b_verdicts.jsonl \
    --narratives results/sub6/sub6b_narratives.jsonl \
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \
    --track sub6a_perfect_id \
    --out-dir results/sub6a_perfect_id_verifier_v6_opus47_aliases
```
