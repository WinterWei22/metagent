# MetAgent Three-Architecture Verdict Summary

This figure collapses the literature ablation and treats the final `v4_a3_d3_with_lit/feedback` output as `MetAgent-feedback`.

| variant | source | total claims | supported % | unsupported % | contradicted % | unverifiable_v0 % |
|---|---|---:|---:|---:|---:|---:|
| MetAgent-single | `data/eval/sub6/v4_a3_d3_no_lit/single` | 2905 | 15.66 | 15.08 | 4.48 | 64.78 |
| MetAgent-ReAct | `data/eval/sub6/v4_a3_d3_no_lit/react` | 3168 | 23.90 | 10.10 | 2.84 | 63.16 |
| MetAgent-feedback | `data/eval/sub6/v4_a3_d3_with_lit/feedback` | 2811 | 30.24 | 5.23 | 1.74 | 62.79 |
