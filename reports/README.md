# reports/ 导航

> 全项目一览见 `docs/PROJECT_MAP.md`。本文件只导航 reports/ 目录。
> 2026-06-30 清理：历史过程报告已 `git mv` 到 `reports/archive/`，前台只留当前权威/参考。

## 前台（当前权威 + 参考）

| 目录/文件 | 流程 | 内容 |
|---|---|---|
| `reports_v3/summary/` | Stage 2 | ★ **当前权威总结**（feedback 重构 + v4 复现/cascade，2026-06-29） |
| `reports_v3/*.md` | Stage 2 | v4 详报（复现 / feedback_ab full112 / scorecard / matcher / id pipeline） |
| `reports_v2/*.md` | Stage 2 | 里程碑参考（full344 scorecard / gpt55 对比 / minimax_vs_gpt55） |
| `eval/*.md` | Stage 1 | 结构识别详报（casmi / sub6a rerank / library_search / sirius_cfmid / llm_reranker / layerf）；收口见 `docs/decisions/2026-06-30_stage1_*` |
| `agent/*.md` | 收口 | 阶段 close-out（concord w13/w14 + w17-w21 + merge_status） |
| `verifier/*.md` | Stage 2 | verifier 工程改进（layer6c / kegg_hierarchy / enrichment delivery / llm 对比） |
| `audit/*.md` | 1+2 | 数据完整性/独立性审计 |
| `benchmark/` | infra | 数据集构建审计（sub6 / metagent_bench_v2 卡） |
| `massbank/` `paper/` `unifying_id/` | — | 数据源可行性 / 论文图索引 / ID 命名空间统一 |
| `nm002_leakage_audit_2026-04-29.md` | Stage 1 | 数据泄露审计（GNPS leakage） |
| `project_architecture_tools_verifier_summary_2026-04-27.md` | 1+2 | 架构总参考 |

## archive/（历史过程，已归档，history 保留）

见各子目录；分类与计数见 `docs/PROJECT_MAP.md` §4。**未删除任何文件**，需要时可 `git mv` 取回。
