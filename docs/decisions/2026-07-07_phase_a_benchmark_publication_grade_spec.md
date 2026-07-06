# Phase A 设计 spec:benchmark 正式化(publication-grade)

> 日期:2026-07-07 · 状态:已 brainstorm 定稿(5 节全认可),用户授权本阶段自主执行
> 目标:产出 **40 任务 benchmark**(可复现自动打分 + Resource 发布包)+ **MetAgent 在其上的结果**
> 上位文档:`reports/reports_v3/summary/2026-07-04_publishability_assessment_and_roadmap.md`(Phase A)

---

## 0. 四个核心决策(用户逐节认可)

1. **rubric = 本体驱动自动分级 + 双口径**:tier ∈ {exact, parent_child, adjacent, miss};strict = exact+parent_child,lenient = 再加 adjacent。相邻性从 RaMP 库客观算,不靠人拍脑袋。
2. **N=40 硬目标 / 60 stretch**,来源优先级 **A(榨干 Miller,零下载)→ B(Sahoo/Recon 逻辑扩展)→ C(下载新队列,仅按需)**。
3. **统计只做我们自己模型**:bootstrap 任务级区间 + 3-seed range + 分家族。**置换检验/baseline 对比全砍**(留 Phase B)。
4. **全公开发布**:CC-BY-4.0(数据)/ MIT(代码);个别 license 障碍源局部退"受控获取"并在 Datasheet 透明写明。

---

## 1. 总体架构与执行顺序(rubric-first)

```
A1  graded matcher 模块      →  在现有 19 任务上验证复现人工 strict 13/19、lenient 15/19(±有据容差)
A2  扩 N 到 40              →  Miller 榨干 → 不足用 Sahoo/Recon → 仅按需下载
A3  40 任务 3-seed 重跑 + matcher 打分 + 统计
A4  Resource 发布包
```

**数据流**:`bench.jsonl`(40 task,每 task 带 gold pathway KEGG id)→ agent 3-seed 跑出 predicted pathway → matcher 查 RaMP 邻接图给 tier → 双口径聚合 → 统计出区间 → scorecard + release。

**A1 复现硬门**:自动 matcher 在 19 任务上必须复现人工 strict 13/19、lenient 15/19;个别偏离必须写 rationale。这是 matcher 正确性锚。

---

## 2. graded matcher 模块

新模块 `scripts/metagent/pathway_match_rubric.py`,纯确定性、zero-LLM、可单测。

- **输入**:predicted pathway(agent 输出通路名/id)+ gold pathway(task 里 KEGG id / 名)
- **输出**:`MatchResult{tier, evidence, distance}`,tier ∈ {exact, parent_child, adjacent, miss}

**判定(按序短路)**:

| tier | 判定 | 数据源 |
|---|---|---|
| exact | 同一 pathwayRampId / `pathway_duplicates` 成对 / 名规范化相等 | pathway + pathway_duplicates |
| parent_child | 代谢物集合**包含度** ≥ τ_c(小集 ⊂ 大集) | analytehaspathway |
| adjacent | 代谢物集合 **Jaccard** ≥ τ_j **或**共享 ≥ k 个判别性代谢物 | analytehaspathway |
| miss | 以上都不满足 | — |

**RaMP 数据已验证可用**(`/data/weiwentao/llm_agent_metabolomics/ramp.sqlite`):`analytehaspathway`(1.35M)→ 每通路代谢物集合;`pathway_duplicates`(180)→ 跨库 exact;`pathway_similarity`(41k)→ 现成相似度。

**阈值 τ_c / τ_j 标定(防主观质疑)**:用 19 任务 A1 复现约束反标定,选能复现人工判定的最宽松阈值;报告 ±0.05 扰动稳健性(敏感性分析);锁定后全 40 任务统一,不逐任务调。

**predicted pathway 抽取**:先查 agent 输出 schema 有无结构化 pathway 字段;有则直接用,无则加轻量 extractor(通路名规范化 → RaMP id 解析,复用现有 name-resolution)。

**双口径聚合**:strict = exact+parent_child;lenient = 再加 adjacent;miss 永远错;**分母永不剔除任务**(死命令)。

**单测**:每 tier ≥2 正例 +1 反例;propanoate↔BCAA 必落 adjacent(不进 strict、进 lenient);TCA exact;阈值扰动测试。RED→GREEN。

---

## 3. 扩 N 到 40(A→B→C)

- **A. 榨干 Miller ESM1(零下载,先走)**:枚举表内所有可解病种(mean_z>2 有判别 biomarker、非 `X-NNNNN`、非 |z|>50);每新 config 人工核 gold KEGG id + biomarker keywords。预计 +8~15。
- **B. Sahoo/Thiele 235 IEM + Recon2(补足到 40)**:已发表 IEM→通路映射程序化生成;**透明标注** `gold_provenance ∈ {measured_cohort, curated_mapping}`。
- **C. 下载新队列(仅按需)**:某家族覆盖不足且 A/B 补不出时才动。

**家族均衡**:优先补非 TCA/非 BCAA;守 **单一家族 ≤25%**;每任务记 `family / gold_provenance / n_differential / source_pmid`。

**验收**:N≥40,单一家族 ≤25%,每任务可追溯 source + gold_provenance。

---

## 4. 统计模块(仅我们自己模型)

新模块 `scripts/metagent/bench_stats.py`,消费 40×3-seed 的 matcher tier。

每个头条数(总 strict / 总 lenient / 各家族)配:
- **点估计** = 3-seed 均值
- **95% 区间** = 任务级 **BCa bootstrap**(重采样任务,2000 次)
- **seed 稳定性** = 3-seed min/max range(与题目变异**分开报**,不糊成一个数)

**分层**:按 family 出 per-stratum acc + n;n 小家族(Lysine/Carnitine n=1)诚实标注 CI 宽。
**CASP 式坦承**:显式写"描述性基准,非 method-level 显著性主张"。
**置换检验/baseline 对比**:**本阶段不做**(Phase B)。
**输出**:`scorecard.md`(人读)+ `scorecard.csv`(机读)。

---

## 5. 发布包(Resource)

A4 产出可公开目录:

```
metagent_bench_release/
├── metagent_bench.jsonl          # 40 任务(input + gold + gold_provenance + family + source_pmid)
├── DATASHEET.md                  # Datasheet for Datasets(动机/构成/采集/清洗/用途/局限)
├── pathway_match_rubric.py       # 自动分级 matcher
├── bench_stats.py                # 统计
├── build_*.py                    # 各来源 builder(可溯源)
├── scorecard.md / scorecard.csv  # 我们模型成绩单
├── LICENSE-data (CC-BY-4.0) / LICENSE-code (MIT)
└── README.md                     # FAIR 元数据 + 复现步骤
```

**DATASHEET 透明项**:non-circular 设计、`gold_provenance` 两类、已知失败模式(单样本特异/治疗混杂/通路粒度)、license 障碍源。
**验收**:目录自包含、clone 后一条命令复现 scorecard、Datasheet 无 TBD。

---

## 6. 死命令合规检查(全程守)

- 中文对话 / 英文代码;结尾 2 段大白话(进度+下一步,无 sprint/TDD/commit 术语,保留数字)
- MiniMax cost 查 `logs/llm_calls.jsonl`,禁"$0 local"
- **防指标游戏**:不为刷分剔除内源代谢物 / 不擅自把 adjacent 计入 strict;分母永不剔任务
- ReAct 方差控制:3-seed,报 mean+range
- 失败任务全留(单样本特异/治疗混杂),作透明难题
- verifier/concord 修改需对应 warning body(本阶段主要加新代码,预计不触 verifier 核心)
