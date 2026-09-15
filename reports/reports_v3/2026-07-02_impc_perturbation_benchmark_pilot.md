# Benchmark 试点:扰动锚定 + 非循环硬 gold(IMPC ST001154)—— 概念验证 + 底物否决

> 日期：2026-07-02 · 分支 `metagent-v3-benchmark`
> 目的:验证"用基因 KO 当非循环硬 gold"的 benchmark 设计是否可行(替代当前半合成/循环基准)。
> 源:Metabolomics Workbench **ST001154**(IMPC 小鼠血浆代谢组,220 样,CC BY 4.0,REST API 直取)。
> 脚本:`scripts/metagent/build_impc_pilot_benchmark.py`；产物 `data/benchmark/impc_pilot/`。

---

## TL;DR
- **概念成立**:G6pd2 KO→**ribose ↓**(p=3.9e-4)、Idh1 KO→**α-ketoglutarate ↓**(p=3.4e-4),**方向精准**。非循环 KO gold 确实能在真实数据里 ground 住。
- **但 IMPC 血浆是差底物**:15 个代谢酶 KO 里**只有 2 个**诊断代谢物显著且方向对(**2/15**)。→ **血浆 KO 被否决为主源。**
- **概念不死,底物要换**:最干净的硬 gold 应来自 **IEM 临床数据**(biomarker 定义上就可测)或 **微生物 KO**(酵母/E.coli,直接、无血浆 buffer/菌群混杂),不是哺乳血浆 KO。

---

## 1. 设计(要验证的)
- 输入 = 每个 KO(6 样)vs `Genotype:Null`(40 样)的**真实差异代谢物**(log2FC + Welch t)。
- gold = 被敲基因 → 酶 → 反应/通路。**锚在基因缺陷上,独立于富集本体 → 非循环**(破当前 benchmark 的循环性)。
- 建成 **30 任务**:15 代谢酶 KO(硬 gold)+ 15 非代谢 KO(hard-negative 特异性对照)。

## 2. 概念验证(正面)
去噪 + 定向核对"被敲酶的诊断代谢物"(底物应升/产物应降):

| KO | 酶 | gold 通路 | 诊断代谢物 | log2FC | p | 判定 |
|---|---|---|---|---:|---:|:--:|
| **G6pd2** | glucose-6-P dehydrogenase | Pentose phosphate | ribose | −1.75 | 3.9e-4 | ✅ PASS |
| **Idh1** | isocitrate dehydrogenase 1 | Citrate cycle (TCA) | α-ketoglutarate | −1.00 | 3.4e-4 | ✅ PASS |

**方向完全正确**(IDH1 催化异柠檬酸→αKG,敲了 αKG 降;G6PD 是 PPP 入口,敲了核糖降)。→ **"真实数据 + 非循环 gold"链路成立。**

## 3. 底物否决(负面,试点核心价值)
15 个代谢酶 KO 的可解性:

| 判定 | 数量 | KO |
|---|---:|---|
| ✅ PASS(显著+方向对) | **2** | G6pd2, Idh1 |
| ⚠ WEAK | 1 | Atp6v0d1(lactate p=0.089) |
| ❌ FAIL(测到但不显著/方向反) | 7 | Ahcy(SAH p=0.41)、Pmm2(mannose 持平)、Gnpda1、Pipox、Mmachc、Lmbrd1、Npc2 |
| ❌ NO_METABOLITE(诊断物没测) | 4 | Mvk(甲羟戊酸)、Phyh(植烷酸)、Galc(psychosine)、Dhfr(叶酸) |

**两类失败**:
1. **血浆 buffer 掉局部代谢信号**:单基因 KO 在整只小鼠、测血浆,预期底物/产物变化被系统代偿/稀释(Ahcy/Pmm2/Gnpda1 等)。
2. **untargeted 覆盖缺口**:关键诊断代谢物压根没被测到(Mvk/Phyh/Galc/Dhfr)。

**技术混杂**:naive top-差异被**内标(iSTD)+ 肠道菌代谢物(3-(3-hydroxyphenyl)propionic acid,每个 KO 都出现=cage/批次效应)** 主导 → 必须去内标 + 批次校正才公平。

## 4. 结论
- **设计范式对**(非循环 KO gold 可行且方向精准),**但 IMPC 血浆 KO 不是好底物**:2/15 可解 + 覆盖缺口 + 血浆稀释 + 批次混杂。**不能作主源。**
- **realism↔cleanliness 张力被实测证明**:哺乳血浆真实但信号弱/脏;要干净硬 gold 得换底物。

## 5. 底物再定向(下一步方向)
| 候选底物 | 为什么更干净 | 代价 |
|---|---|---|
| **IEM 临床数据 / IEMbase** | biomarker **定义上就可测**(临床诊断选的就是检得到的)→ "诊断物→缺陷酶"最干净、且人类 | IEMbase 无 API(需爬/求 dump);患者数据可能受控 |
| **微生物 KO(酵母 4678 / E.coli 3807)** | 单细胞、无血浆 buffer/无菌群、酶底物产物直接变 | 非人;读出窄(酵母 20 AA)或需注释(E.coli m/z) |
| ~~哺乳血浆 KO(IMPC)~~ | ~~人类相关~~ | **否决:2/15 可解** |

## 6. 产物 / 复现
- `scripts/metagent/build_impc_pilot_benchmark.py`(MW REST API 取数 + 差异 + 建任务)
- `data/benchmark/impc_pilot/impc_pilot_tasks.jsonl`(30 任务)
- `data/benchmark/impc_pilot/impc_pilot_clean_demo.jsonl`(**2 个去噪+可解性核实的干净 demo**:G6pd2/Idh1)
- `data/benchmark/impc_pilot/impc_pilot_summary.json`
- 可解性方法:对每个 KO 定向核对诊断代谢物(底物↑/产物↓)显著性 + 方向 → "solvability filter"(全量建 benchmark 必用)

## 7. 建议下一步
先探 **IEM 底物**(IEMbase 访问 or 已发表 IEM 队列)——它是"诊断物→缺陷酶"里最干净且人类的一档;或并行探**微生物 KO**(现成 MetaboLights/MassIVE)。**IMPC 血浆不再投入。**
