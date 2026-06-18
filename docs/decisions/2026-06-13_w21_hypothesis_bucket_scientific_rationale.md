# W21 — Hypothesis bucket (option 1) 的科学严谨性论证与初衷锚点

Date: 2026-06-13
Status: **PROPOSED**(Claude 推荐方向,待 PI 最终确认评估框架)
Branch: `metagent-v2`
关联: `prompts/track_MetAgent_W21_epsilon_react_prompt_tighten.md`,`docs/decisions/2026-06-12_w19_tool_output_verifier.md`,`docs/decisions/2026-06-12_w20_kegg_kb_audit.md`

> 本文档的目的不是记录"怎么做",而是记录**为什么做、初衷是什么**。
> 写它是因为 PI 担心跨 session 上下文丢失后,我们会忘记 W21 的真实目标,
> 把手段(降 UV 数字)误当成目的,跑偏成指标游戏。
> 未来任何 session 在改 W21 评估框架前,必须先读本文档。

---

## 1. 背景:为什么会走到 op1

verifier 端连续 4 个 sprint 边际递减:
- W17(carrier visibility): UV -14pp
- W18(LLM-judge layer): UV -8pp(含 ±5pp ReAct 方差)
- W19(tool-output verifier): ~0(被噪音吞,INCONCLUSIVE)
- W20(KEGG REST): strict ceiling 2.03pp,< 3pp gate STOP

结论(已落 memory `feedback_verifier_side_marginal_returns`):在 verifier 端加工具/KB 回报触顶,
转 **ReAct 源头**干预。

## 2. 最初目标(PI 原话)

> "能不能从 ReAct 出发,让 ReAct 少输出一些 UV 的内容。"

## 3. 关键转折:为什么不强制 cite

第一版方案是"强制每个 claim 必须 cite 工具证据"。PI 否决,理由:

> "也不能是一定要 cite,这样会损失一些扩展性。"

这个否决是对的,而且戳中我们自己的死命令 `feedback_metagent_must_be_llm_driven`:
如果 ReAct 只能报数据、不能做生物学推断/综合,它就退化成报表生成器,LLM 的价值没了。

## 4. op1 到底是什么(不是临时妥协)

真问题诊断:ReAct 把**两种认识论上本就不同**的东西混在一起输出,verifier 分不清只能全打 UV。

| 句子 | 本质 | 该怎么判 |
|---|---|---|
| "TCA 循环 p 值 = 0.012" | **事实断言**,可被工具输出验证 | 验得到=SUPPORTED,验不到=UNVERIFIABLE(模型可能在编)|
| "TCA 循环功能障碍可能驱动表型" | **科学推断/假设**,从不声称是可验证的事实 | 标注为 HYPOTHESIS,不该算 UV |

**op1 = 让 ReAct 自己把两类分开标(事实挂证据,推断显式标 `Hypothesis:`),
verifier 识别标记把 hypothesis 路由到独立 bucket。**

为什么它**提升**而非损害严谨性:
- 强制模型区分"我测到的"和"我推断的",这是科学写作的诚实底线
- 一个明确标注的假设,比一个伪装成事实的假设**更**严谨
- 科学论文里"we hypothesize / we speculate"是合法表达,把它打成"无法验证的事实"才是分类错误

技术可行性已实测确认(`conversation/master/2026-06-13_003095_w21-d2-0-verifier-handling.md`):
- `Hypothesis:` 标记能扛过 claim_extractor(B1-core),留在 `claim.text`
- 现状下 hypothesis claim 全被打 UV → 不配套就真的白标

## 5. 两条红线(踩了 op1 就从"提升严谨性"变成"损害严谨性")

### 红线 1 — Gaming(换标签游戏)
模型把**本该挂证据的事实**偷懒标成 hypothesis 来逃避 UV。
这是把"查无实据"换个标签,信息没增加,严谨性不升反降。

### 红线 2 — 报告操纵
把 hypothesis 从 UV 率**分母**里偷偷挪走,让主指标数字好看。
paper 审稿人会质疑指标操纵。

## 6. 决策:三分类 + VERIFIED 主指标(防住两条红线)

**核心思想:别再让"UV 率"当唯一的明星指标——争议恰恰出在它身上。
改报完整三分类,核心质量信号转为 VERIFIED 率。**

每个 claim 落三类之一,三类比例都报,**加起来 100%,分母永远是 total,不剔除任何东西**:

| 问题 | 指标 | 方向 |
|---|---|---|
| 有多少话有工具数据撑着? | **VERIFIED 率** | 越高越好(质量主指标)|
| 有多少话伪装成事实却查无实据? | **UNVERIFIABLE 率** | 越低越好(诚信指标)|
| 有多少话是明确的推断? | **HYPOTHESIS 率** | 适中健康,暴涨=gaming 警报 |

### W21 成功标准(防 gaming 焊死)
**不是** "UV↓",而是三元组:
1. VERIFIED 率 ↑(模型真把事实挂上证据 —— 这是赢的核心证据)
2. UNVERIFIABLE 率 ↓
3. HYPOTHESIS 率不暴涨 + 人工抽 10 个 hypothesis claim ≥80% 是真推断(非偷懒标注)

只满足"UV↓"不算成功。如果 UV 降了但 VERIFIED 没涨 → 模型在玩标签游戏 → STOP,回 prompt 加"不准把事实标 hypothesis"约束。

### 被否决的两个替代方案
- **纯把 hypothesis 移出分母**:分子分母一起缩,下降幅度被夸大,审稿人第一个质疑。否。
- **报 uv_raw + uv_adjusted 两个数**:adjusted(剔了 hypothesis 的)本身是有操纵嫌疑的数,报它等于递给读者一个误导性的"更低数字"。不如只报干净的三分类。否。

## 7. 初衷锚点(未来 session 防跑偏的最后一道闸)

1. **目的是输出的科学质量真提升,不是 UV 数字好看。** UV 降只是副产品。
2. **op1 不让任何推断变得更可信** —— 它只是把推断**正确归类**,不是**验证**它。真正让输出可信的是 VERIFIED 涨。
3. **核心指标是 VERIFIED 率,不是 UV 率。** 谁要是回来只盯着 UV 降了多少庆祝,就是忘了初衷。
4. **分母永远是 total,一个 claim 都不许从分母挪走。**
5. **HYPOTHESIS 必须是真推断。** 抽样把关是科学诚信的一部分,不是可选项。

## 8. 当前状态与待确认项

- op1 技术可行性: ✅ 实测确认
- HYPOTHESIS bucket 实现规格: 已定(见 `conversation/claude/2026-06-13_004500_w21-d2-0-approve-option1-antigaming.md`)
- **待 PI 最终拍板**: 评估框架从"UV↓5pp 主导"改为"VERIFIED↑主导 + 三分类"(本文档 §6)。
  Claude 推荐此方向,PI 让先记录初衷再定。
- 未实施任何 production 改动;pilot 未跑。
