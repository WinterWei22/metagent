# Verifier-graded results — `sub6b_v9_phaseC`

Output of `verifier.agent.verify_sub6` applied to the Sub-6 narratives
under track `sub6b_v9_phaseC`. Mirrors the layout of `results/sub6/` (the
extractor-graded baseline) so the two scorings can be diffed.

## Files

- `sub6b_v9_phaseC_verdicts.jsonl`         — raw verifier output (one record per task)
- `sub6b_v9_phaseC_verdicts.csv`           — flat per-task verdict counts
- `sub6b_v9_phaseC_verdicts_summary.json`  — aggregate verdict counters / rates
- `sub6b_v9_phaseC_verdicts.md`            — per-task scorecard + claim list + narrative
- `README.md`                            — this file

## Headline numbers

| Metric | Value |
|---|---:|
| n_tasks               | 20 |
| n_error               | 0 |
| total claims          | 809 |
| verifier LLM calls    | 0 |
| supported             | 169 (20.89%) |
| unsupported           | 163 (20.15%) |
| contradicted          | 63 (7.79%) |
| unverifiable_v0       | 414 (51.17%) |
| tasks w/ ≥1 SUPPORTED set_enrichment | 1 / 20 |
| tasks w/ ≥1 CONTRADICTED driver_metabolite | 1 / 20 |

## How to reproduce

```bash
export MINIMAX_API_KEY="$(cat api_key.txt | tr -d '[:space:]')"
python scripts/eval_sub6/grade_with_verifier.py \
    --narratives results/sub6/sub6b_narratives.jsonl \
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \
    --out data/eval/sub6/sub6b_verdicts.jsonl \
    --track sub6b_v9_phaseC
python scripts/eval_sub6/aggregate_verifier.py \
    --verdicts data/eval/sub6/sub6b_verdicts.jsonl \
    --narratives results/sub6/sub6b_narratives.jsonl \
    --tasks data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \
    --track sub6b_v9_phaseC \
    --out-dir results/sub6b_verifier_v9_phaseC
```
