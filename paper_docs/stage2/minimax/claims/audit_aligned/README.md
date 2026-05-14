# Phase A3 Audit-Aligned Verdict Summary

This reproduces `reports/agent/phase_a3_audit.md` section 1.2 for D3 full v4, using final `verdict.json` files only.

| variant | source | total claims | supported % | unsupported % | contradicted % | unverifiable_v0 % |
|---|---|---:|---:|---:|---:|---:|
| single | `data/eval/sub6/v4_a3_d3_no_lit/single` | 2905 | 15.66 | 15.08 | 4.48 | 64.78 |
| react | `data/eval/sub6/v4_a3_d3_no_lit/react` | 3168 | 23.90 | 10.10 | 2.84 | 63.16 |
| fb_nolit | `data/eval/sub6/v4_a3_d3_no_lit/feedback` | 2839 | 29.80 | 4.93 | 2.22 | 63.05 |
| +literature | `data/eval/sub6/v4_a3_d3_with_lit/feedback` | 2811 | 30.24 | 5.23 | 1.74 | 62.79 |

Important distinction: this is pipeline-level comparison (`single`, `react`, `fb_nolit`, `+literature`). It is not the same as the internal feedback iteration comparison inside `result.json`.
