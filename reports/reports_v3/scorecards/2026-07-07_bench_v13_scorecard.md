# Perturbation benchmark v1.3 (19 tasks, 3 seeds) — MetAgent scorecard

- Tasks: **19** · seeds: 3 · deterministic graded matcher (RaMP registry)
- **Strict accuracy: 61.4%** (95% bootstrap CI 43.9%–79.0%)
- **Lenient accuracy: 70.2%** (95% bootstrap CI 52.6%–86.0%)
- Seed stability (strict, per-seed overall): 52.6%–68.4% ({'run_v13_seed1': 0.5263, 'run_v13_seed2': 0.6842, 'run_v13_seed3': 0.6316})

## Per-family (stratum)

| family | n | strict | lenient |
|---|---:|---:|---:|
| BCAA | 1 | 100.0% | 100.0% |
| Carnitine | 1 | 100.0% | 100.0% |
| Leucine | 1 | 33.3% | 100.0% |
| Lysine | 1 | 0.0% | 0.0% |
| Methionine | 1 | 100.0% | 100.0% |
| Phenylalanine | 1 | 66.7% | 66.7% |
| Propanoate | 3 | 11.1% | 44.4% |
| TCA/oncometabolite | 4 | 83.3% | 83.3% |
| Tyrosine | 1 | 100.0% | 100.0% |
| Urea cycle | 5 | 60.0% | 60.0% |

## Tier distribution (all task-seed judgements)

| tier | count |
|---|---:|
| exact | 34 |
| parent_child | 1 |
| adjacent | 5 |
| miss | 17 |

> Strict = exact + parent_child. Lenient adds adjacent. Miss always wrong. Denominator never drops a task. Descriptive benchmark — not a method-level significance claim; CIs are wide at this N.