# Phase B1 — Aggregator audit (D5 v2 seed summaries)

**Generated:** Phase B1 P0 Stage A1.5

**Source:** `data/eval/sub6/b1_d5_v2_full_feedback_lit`

**Purpose:** verify every field in each `seed_summary.json` by re-deriving from per-task `result.json` + `verdict_final.json`. The aggregator script that wrote these summaries is not in the committed repo (`git log -S "seed_summary"` returns 0 hits), so any mismatch below is a silent bug in a lost ad-hoc script — downstream reports (`phase_b1_d5_eval.md` §1 / §4) inherit those bugs verbatim.

---

## seed_0

- total fields checked: **22**
- mismatched: **13**

### Mismatches

| field | on_disk | truth | delta | %off |
|---|---|---|---|---|
| `n_feedback_iter_above_zero` | `0` | `50` | `50` | `100.00` |
| `deprecation_warnings` | `0` | `N/A (runner counter, not aggregator-derived)` | `—` | `—` |
| `metrics_normal_only.unsupported_mean` | `MISSING` | `0.00322671` | `—` | `—` |
| `feedback_iter_distribution.0` | `63` | `13` | `-50` | `384.62` |
| `feedback_iter_distribution.1` | `0` | `40` | `40` | `100.00` |
| `feedback_iter_distribution.2` | `0` | `10` | `10` | `100.00` |
| `wall_seconds.max` | `738.1` | `MISSING` | `—` | `—` |
| `wall_seconds.mean` | `293.495` | `293.492` | `-0.00318791` | `0.00` |
| `wall_seconds.median` | `263.5` | `263.499` | `-0.000956101` | `0.00` |
| `wall_seconds.min` | `30.6` | `MISSING` | `—` | `—` |
| `wall_seconds.n` | `MISSING` | `63` | `—` | `—` |
| `wall_seconds.p95` | `MISSING` | `546.731` | `—` | `—` |
| `wall_seconds.total` | `MISSING` | `18490` | `—` | `—` |

### Derived fields not in on-disk summary

| field | truth |
|---|---|
| `termination_reason_distribution` | `{'no_actionable_claims_after_iter': 48, 'max_iterations_reached': 2, 'early_exit_no_revisions': 12, 'none': 1}` |
| `quality_rollback_count` | `0` |
| `inner_retry_count` | `64` |
| `tool_call_total` | `957` |

## seed_1

- total fields checked: **22**
- mismatched: **13**

### Mismatches

| field | on_disk | truth | delta | %off |
|---|---|---|---|---|
| `n_feedback_iter_above_zero` | `None` | `43` | `—` | `—` |
| `deprecation_warnings` | `0` | `N/A (runner counter, not aggregator-derived)` | `—` | `—` |
| `metrics_normal_only.unsupported_mean` | `MISSING` | `0.00616368` | `—` | `—` |
| `feedback_iter_distribution.0` | `63` | `20` | `-43` | `215.00` |
| `feedback_iter_distribution.1` | `0` | `33` | `33` | `100.00` |
| `feedback_iter_distribution.2` | `0` | `10` | `10` | `100.00` |
| `wall_seconds.max` | `1200` | `MISSING` | `—` | `—` |
| `wall_seconds.mean` | `347.592` | `347.594` | `0.00152238` | `0.00` |
| `wall_seconds.median` | `286.3` | `286.31` | `0.010163` | `0.00` |
| `wall_seconds.min` | `51.3` | `MISSING` | `—` | `—` |
| `wall_seconds.n` | `MISSING` | `63` | `—` | `—` |
| `wall_seconds.p95` | `MISSING` | `751.626` | `—` | `—` |
| `wall_seconds.total` | `MISSING` | `21898.4` | `—` | `—` |

### Derived fields not in on-disk summary

| field | truth |
|---|---|
| `termination_reason_distribution` | `{'early_exit_no_revisions': 20, 'no_actionable_claims_after_iter': 40, 'max_iterations_reached': 3}` |
| `quality_rollback_count` | `0` |
| `inner_retry_count` | `66` |
| `tool_call_total` | `1002` |

## seed_2

- total fields checked: **22**
- mismatched: **13**

### Mismatches

| field | on_disk | truth | delta | %off |
|---|---|---|---|---|
| `n_feedback_iter_above_zero` | `None` | `51` | `—` | `—` |
| `deprecation_warnings` | `0` | `N/A (runner counter, not aggregator-derived)` | `—` | `—` |
| `metrics_normal_only.unsupported_mean` | `MISSING` | `0.00591757` | `—` | `—` |
| `feedback_iter_distribution.0` | `63` | `12` | `-51` | `425.00` |
| `feedback_iter_distribution.1` | `0` | `37` | `37` | `100.00` |
| `feedback_iter_distribution.2` | `0` | `14` | `14` | `100.00` |
| `wall_seconds.max` | `503.9` | `MISSING` | `—` | `—` |
| `wall_seconds.mean` | `241.629` | `241.626` | `-0.00239231` | `0.00` |
| `wall_seconds.median` | `232` | `232.033` | `0.0326783` | `0.01` |
| `wall_seconds.min` | `50.3` | `MISSING` | `—` | `—` |
| `wall_seconds.n` | `MISSING` | `63` | `—` | `—` |
| `wall_seconds.p95` | `MISSING` | `401.081` | `—` | `—` |
| `wall_seconds.total` | `MISSING` | `15222.4` | `—` | `—` |

### Derived fields not in on-disk summary

| field | truth |
|---|---|
| `termination_reason_distribution` | `{'early_exit_no_revisions': 12, 'no_actionable_claims_after_iter': 46, 'max_iterations_reached': 5}` |
| `quality_rollback_count` | `1` |
| `inner_retry_count` | `65` |
| `tool_call_total` | `1034` |

---

## Summary across seeds

**Total mismatched (field, seed) pairs:** 39

| field | seeds affected |
|---|---|
| `deprecation_warnings` | seed_0, seed_1, seed_2 |
| `feedback_iter_distribution.0` | seed_0, seed_1, seed_2 |
| `feedback_iter_distribution.1` | seed_0, seed_1, seed_2 |
| `feedback_iter_distribution.2` | seed_0, seed_1, seed_2 |
| `metrics_normal_only.unsupported_mean` | seed_0, seed_1, seed_2 |
| `n_feedback_iter_above_zero` | seed_0, seed_1, seed_2 |
| `wall_seconds.max` | seed_0, seed_1, seed_2 |
| `wall_seconds.mean` | seed_0, seed_1, seed_2 |
| `wall_seconds.median` | seed_0, seed_1, seed_2 |
| `wall_seconds.min` | seed_0, seed_1, seed_2 |
| `wall_seconds.n` | seed_0, seed_1, seed_2 |
| `wall_seconds.p95` | seed_0, seed_1, seed_2 |
| `wall_seconds.total` | seed_0, seed_1, seed_2 |

## Headline narrative impact

**Feedback-trigger metric is wrong.** The on-disk summary reports `n_feedback_iter_above_zero = 0` across seeds. The truth derived from `result.json:n_feedback_iterations` shows actual non-zero triggers per seed:

- seed_0: reported `0` / truth `50`
- seed_1: reported `None` / truth `43`
- seed_2: reported `None` / truth `51`

This directly invalidates `phase_b1_d5_eval.md` §4 claim that '0/189 feedback iter triggered'.

