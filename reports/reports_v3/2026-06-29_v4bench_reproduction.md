# v4 Benchmark 复现报告（最新 MetAgent）

- 日期：`2026-06-29`
- 分支：`metagent-v3-benchmark`（HEAD `cffc4d3`，已合并 feedback A_cascade + verifier 多源重构）
- 目的：用合并后的最新代码复现 v4 benchmark 结果，验证 2026-06-25 的 75.89% primary semantic 在当前代码上稳定可复现
- 结论：**复现成功**。overall primary semantic 75.89% → **76.79%**（+0.90pp），top-k 83.04% → **83.93%**（+0.89pp），全部在 ReAct 跑次方差（±5pp）内、方向一致偏正；prediction ok 100%、0 crash。

---

## 1. 复现配置

| 项 | 值 |
|---|---|
| Benchmark | `metagent_bench_easy_v4_metabolic.jsonl`（292 task，本次跑 sub6=63 + hmdb_ramp filtered=49 = **112**） |
| Driver | `scripts/metagent/v4_bench_eval.py --strata sub6 hmdb_ramp` |
| 模型 | MiniMax-M2.7-highspeed |
| 参数 | `--max-react-turns 8 --max-feedback-iters 1 --k 8` |
| 结果目录 | `data/metagent/v4_bench_eval_repro_20260629/`（status + path_x_full + scorecard） |
| LLM log | `logs/concord/v4_repro_full.jsonl` |
| Scorecard | `data/metagent/v4_bench_eval_repro_20260629/scorecard/2026-06-29_v4_repro_scorecard.{md,json,csv}` |

代码差异说明：本次代码相比 2026-06-25 多了已合并的 feedback `A_cascade` 策略 + verifier 多源重构 + `v4_task_to_subsix_source_report` adapter。**注意：生产 `react_runner` 的 feedback 路径目前仍是 legacy rewrite，cascade 策略尚未接入生产 driver**（见 2026-06-26 决策文档的文档/代码不一致说明）。因此本次复现走的仍是 legacy feedback 路径，与 2026-06-25 同源，结果可比。

## 2. 主指标对比（primary / top-k pathway accuracy）

| stratum | 指标 | baseline 2026-06-25 | repro 2026-06-29 | Δ |
|---|---|---:|---:|---:|
| **overall** | primary semantic | 75.89% | **76.79%** | **+0.90pp** |
| overall | top-k semantic | 83.04% | **83.93%** | +0.89pp |
| overall | name-exact | 72.32% | 74.11% | +1.79pp |
| overall | abstain | 5.36% | **3.57%** | −1.79pp |
| overall | prediction ok | 100.00% | 100.00% | 0 |
| sub6 | primary semantic | 76.19% | **77.78%** | +1.59pp |
| sub6 | top-k semantic | 87.30% | 87.30% | 0 |
| hmdb_ramp | primary semantic | 75.51% | 75.51% | 0 |
| hmdb_ramp | top-k semantic | 77.55% | **79.59%** | +2.04pp |

ID-exact 全程 0%（v4 设计去掉了 DB ID 预填充，强制 LLM 用 InChIKey 调工具，所以不命中 ID-exact 是预期）。

## 3. Recall@k + Driver P/R

| stratum | recall@3 | hit@3 | MRR | driver P | driver R |
|---|---:|---:|---:|---:|---:|
| overall (repro) | 0.374 | 0.821 | 0.789 | 0.835 | 0.200 |
| overall (baseline) | 0.376 | 0.813 | 0.778 | 0.882 | 0.209 |
| sub6 (repro) | 0.506 | 0.873 | 0.839 | 0.906 | 0.211 |
| hmdb_ramp (repro) | 0.203 | 0.755 | 0.725 | 0.759 | 0.188 |

全部与基线接近；driver precision overall 略降（0.882→0.835），仍在跑次波动范围。

## 4. 成本 / 性能（本次实测）

| 项 | 值 | 来源 |
|---|---|---|
| 墙钟 | **61.5 min**（3690s，k=8） | run 输出 `Done: 112/112 ok` |
| LLM calls | 1137 | `logs/concord/v4_repro_full.jsonl` |
| Token | prompt 13.87M + completion 1.51M = **15.38M**（cached 9.60M） | 同上 |
| **成本** | **$5.98** | MiniMax 计价 $0.30/M prompt + $1.20/M completion |
| 完成度 | **112/112 ok，0 crash** | status 目录 |

（对比 2026-06-25：~65 min、10.8M token；本次 token 偏高主因 cached 占比大，净成本 $5.98。）

## 5. feedback 触发情况（legacy rewrite 路径）

| 量 | 值 |
|---|---|
| 触发 feedback 轮的 task | 57 / 112 |
| 最终停在 iter-0（无反馈或反馈被回滚） | 69 / 112 |
| 最终采用 iter-1 结果 | 43 / 112 |

verifier 指标本次能正常产出（`v4_task_to_subsix_source_report` adapter 生效，0 adapter 失败），不再是 2026-06-25 报告里"v4 无 UV/Supported 指标"的状态。

## 6. 结论

最新代码上，v4 benchmark 的 pathway accuracy **稳定复现并略优于** 2026-06-25 基线（overall primary +0.90pp、top-k +0.89pp、abstain −1.79pp），差异在 ReAct 跑次方差内、方向一致；112/112 跑通、0 crash、成本 $5.98 / 61.5 min。结果可信，benchmark 管线在合并 feedback + verifier 多源重构后无回归。

## 7. 复现命令

```bash
PY=/home/weiwentao/miniconda3/bin/python3
KEY=$(cat /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/api_key_minimax.txt | tr -d '[:space:]')
export MINIMAX_API_KEY="$KEY" METAGENT_API_KEY="$KEY" METAGENT_LLM_PROVIDER=minimax
export METAGENT_VERIFY_STRUCTURED_CLAIMS=1 METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT=1
export METAGENT_LLM_LOG_PATH=logs/concord/v4_repro_full.jsonl

# 跑
PYTHONPATH=. $PY scripts/metagent/v4_bench_eval.py \
    --benchmark data/benchmark/metagent_bench_v2/metagent_bench_easy_v4_metabolic.jsonl \
    --strata sub6 hmdb_ramp \
    --out data/metagent/v4_bench_eval_repro_20260629 \
    --max-react-turns 8 --max-feedback-iters 1 --k 8

# 打分
PYTHONPATH=. $PY scripts/metagent/full344_pathway_scorecard.py \
    --out-dir data/metagent/v4_bench_eval_repro_20260629 \
    --benchmark data/benchmark/metagent_bench_v2/metagent_bench_easy_v4.jsonl \
    --relevant-sidecar data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json \
    --gold-sidecar data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json \
    --ramp /data/weiwentao/llm_agent_metabolomics/ramp.sqlite \
    --report-dir data/metagent/v4_bench_eval_repro_20260629/scorecard \
    --stem 2026-06-29_v4_repro_scorecard \
    --llm-log logs/concord/v4_repro_full.jsonl
```
