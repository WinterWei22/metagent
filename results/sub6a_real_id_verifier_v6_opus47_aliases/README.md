# Verifier-graded results — `sub6a_real_id`

Output of `verifier.agent.verify_sub6` applied to the Sub-6 narratives
under track `sub6a_real_id`. Mirrors the layout of `results/sub6/` (the
extractor-graded baseline) so the two scorings can be diffed.

## Files

- `sub6a_real_id_verdicts.jsonl`         — raw verifier output (one record per task)
- `sub6a_real_id_verdicts.csv`           — flat per-task verdict counts
- `sub6a_real_id_verdicts_summary.json`  — aggregate verdict counters / rates
- `sub6a_real_id_verdicts.md`            — per-task scorecard + claim list + narrative
- `README.md`                            — this file

## Headline numbers

| Metric | Value |
|---|---:|
| n_tasks               | 14 |
| n_error               | 0 |
| total claims          | 611 |
| verifier LLM calls    | 0 |
| supported             | 39 (6.38%) |
| unsupported           | 213 (34.86%) |
| contradicted          | 14 (2.29%) |
| unverifiable_v0       | 345 (56.46%) |
| tasks w/ ≥1 SUPPORTED set_enrichment | 0 / 14 |
| tasks w/ ≥1 CONTRADICTED driver_metabolite | 0 / 14 |

## How to reproduce

```bash
export MINIMAX_API_KEY="$(cat api_key.txt | tr -d '[:space:]')"
python scripts/eval_sub6/grade_with_verifier.py \
    --narratives results/sub6/sub6b_narratives.jsonl \
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \
    --out data/eval/sub6/sub6b_verdicts.jsonl \
    --track sub6a_real_id
python scripts/eval_sub6/aggregate_verifier.py \
    --verdicts data/eval/sub6/sub6b_verdicts.jsonl \
    --narratives results/sub6/sub6b_narratives.jsonl \
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \
    --track sub6a_real_id \
    --out-dir results/sub6a_real_id_verifier_v6_opus47_aliases
```
