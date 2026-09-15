# Stage 2 pathway 已 near-ceiling + pathway critic 负结果（verifier 价值转向 auditability）

> 日期：2026-07-01 · 分支 `metagent-v3-benchmark`
> run：`v4_bench_eval_cascade_fix_20260629`（纯 Stage 2, perfect-id 输入, 112 task）· 全程零 LLM
> 脚本：`scripts/metagent/{diagnose_pathway_ceiling,pathway_oracle_ceiling,simulate_pathway_critic}.py`
> 前置：`reports/reports_v3/stage2_detailed/2026-07-01_pathway_ceiling_adjudication.md`、决策 `docs/decisions/2026-07-01_verifier_feedback_lock_pathway_to_raw.md`

---

## TL;DR
1. **raw LLM 的 pathway 79.5% 已逼近这套（LLM+工具+benchmark）的可达上限。**
2. **pathway critic（把 primary 重锚到最强工具证据）是净负的**（裸规则 −29pp，加 FDR 门仍 −27pp，最好只 +1）。**离线模拟避免了一次 −24pp 回归。**
3. **没有任何测过的 验证/反馈/纠正 机制能提升 pathway**（feedback 拖累 / verifier 判不了 / critic 救不了）。
4. **verifier 在本任务的价值 = auditability，不是 pathway 准确率** → 采纳 D1（pathway 锁 raw + cascade 只清 claim/织叙述）。

---

## 1. 问题溯源（四问归位，见 adjudication 报告）
raw 做错 23/112。诊断：#1 工具上限只 ~3-4；#3 verifier / #4 feedback 只拖累 feedback 不封顶 raw；剩下是 #2 选择 + 测量。用 RaMP `pathway_duplicates` 复核后，"测量·同义"被撤回（RaMP 不背书），headline 诚实保持 **79.5%**。

## 2. Oracle 天花板（若选择完美，上限多少）
| 口径 | 命中 | 准确率 | 含义 |
|---|---:|---:|---|
| raw 现状 | 89/112 | **79.5%** | LLM 实际 primary |
| 完美从 LLM 自己候选选 | 97/112 | **86.6%** | gold 已在其 alternatives，只是没抬成主 |
| 完美从工具输出选（oracle） | 104/112 | **92.9%** | 任何选择策略的**绝对上限** |
| 硬工具死结（gold 任何工具都没给） | 8/112 | **7.1%** | 换工具才行 |
| gold 落在工具 rank-0 | 79/112 | 70.5% | — |

**读法**：选择的 headroom 是真的（79.5→92.9 的 13.4pp 全是"gold 在工具里没被选成 primary"）。**但 oracle 假设选择器知道答案**，现实够不着。

## 3. pathway critic 离线模拟（关键负结果）
critic 候选 = RaMP rank-0（唯一带 FDR 的多库 ORA，最硬的单一证据）。触发则 final=critic，否则 raw。

| 规则 | 准确率 | 救回 | 改坏 | 净 |
|---|---:|---:|---:|---:|
| 基线 raw | **79.5%** | — | — | — |
| R0 总是用 RaMP rank-0 | 53.6% | 10 | 39 | **−29** |
| R1 FDR<1e-10 | 55.4% | 8 | 35 | −27 |
| R2 候选在 LLM alts 里 | 80.4% | 5 | 4 | **+1** |
| R3 FDR<1e-10 且在 alts | 80.4% | 4 | 3 | **+1** |
| R4 FDR<1e-10 或在 alts | 55.4% | 9 | 36 | −27 |
| R5 FDR<1e-5 | 53.6% | 10 | 39 | −29 |

**每条规则净 ≤ +1。** FDR 门无效——FDR 极低（1e-15）不代表对，往往是 "Biological oxidations / Metabolism" 这种又宽又统计显著、但不是具体答案的通路。

## 4. 机制：为什么 critic 死了
**LLM 的选择已经比"工具 rank-0"更好。** 工具把 gold 藏在输出里（oracle 92.9%）却**排不上去**——broad-but-enriched 的错通路 FDR 更低、压在 gold 前面。LLM 大多**正确避开**了这些又宽又显著的错答案；critic 一"相信工具证据"就把 LLM 避开的坑又跳回去（改坏 39）。所以 oracle 的 92.9% 要从工具列表**深处**挑出 gold，而工具排序本身没有这个分辨力，**任何基于工具排序的规则都逼近不了它**。

补充张力：benchmark 里 gold 有时是**宽**通路（Biological oxidations 就是 gold），有时是**具体**通路——LLM 和简单 critic 都无法先验区分该宽还是该窄。这是 benchmark 粒度歧义，不是纯算法问题。

## 5. 结论 → verifier 定位转向
- **pathway 已 near-ceiling**：raw 79.5% ≈ 该 setup 可达上限；feedback/verifier/critic 均无法提升。
- **verifier 价值 = auditability**：不是提 pathway（证明做不到），而是在**守住 raw pathway 上限**的同时把 claim 做得可审计、可信。
- **采纳 D1**（`docs/decisions/2026-07-01_verifier_feedback_lock_pathway_to_raw.md`）：pathway 锁 raw（79.5%，天花板）+ cascade 只清 claim / 织叙述。这是本系统**能稳定拿到的最优产品**：天花板 pathway + 干净可审计 claim。

## 6. 真要再推高 pathway 的三条硬路（都不便宜、不确定，非简单 critic）
1. 换更强富集工具，救那 **7.1% 硬工具死结**（gold 任何工具都没给出）。
2. 解决 benchmark "宽 vs 具体" gold 歧义（评测层，或多粒度 gold）。
3. 做一个真正 **specificity-aware 的选择器**（能在 broad-but-enriched 与 specific-correct 间分辨），比 LLM+工具排序都聪明——研究量级，不是一个规则。

## 7. 方法/复现
- oracle：`pathway_oracle_ceiling.py`；critic 模拟：`simulate_pathway_critic.py`（RaMP rank-0 候选，6 规则）；诊断：`diagnose_pathway_ceiling.py`。
- matcher：`PathwayNameMatcher`（SapBERT cosine ≥0.80 或 token 子集），严格口径未放宽（防指标游戏）。
- 全零 LLM，用现有 run 的 `enrichment_carriers` + iter-0 pathway_prediction + scorecard gold。
