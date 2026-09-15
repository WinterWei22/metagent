# Perturbation benchmark v1.4 (20 tasks, 3 seeds) — MetAgent scorecard

- Tasks: **20** · seeds: 3 · deterministic graded matcher (RaMP registry)
- **Strict accuracy: 61.7%** (95% bootstrap CI 45.0%–78.3%)
- **Lenient accuracy: 71.7%** (95% bootstrap CI 55.0%–86.7%)
- Seed stability (strict, per-seed overall): 50.0%–70.0% ({'run_v13_seed1': 0.5, 'run_v13_seed2': 0.7, 'run_v13_seed3': 0.65})

## Per-family (stratum)

| family | n | strict | lenient |
|---|---:|---:|---:|
| BCAA | 1 | 100.0% | 100.0% |
| Carnitine | 1 | 100.0% | 100.0% |
| Leucine | 2 | 50.0% | 100.0% |
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
| exact | 36 |
| parent_child | 1 |
| adjacent | 6 |
| miss | 17 |

> Strict = exact + parent_child. Lenient adds adjacent. Miss always wrong. Denominator never drops a task. Descriptive benchmark — not a method-level significance claim; CIs are wide at this N.