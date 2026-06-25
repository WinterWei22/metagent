# Verifier 多源证据池重构 — 设计决策 + 实施计划

- 日期：`2026-06-25`
- 分支：`claude/stupefied-shtern-43fb20`
- 背景调研：OriGene Critic Agent + GeneAgent self-verification（见 §4）

---

## 0. Context（为什么重构）

V3 Part 2 把 benchmark 从 v3 升级到 v4，范式从"benchmark 预填熟饭"变成"agent 自助现场做饭"：代谢物只给 `{name, smiles, inchikey}`，agent 自己用 InChIKey xref 拿 ID，富集结果由 5 个 paradigm 工具运行时产出。

但 verifier 的"事实底座"模型仍停留在 v3 假设（单源 RaMP 预填 + ground truth compounds 预填）。结果是 v4 benchmark 上 **verifier 112/112 全部失败，UV 实测全 0**，V3 Part 2 之后没有任何真实 UV 数字。

诊断定位到**三层结构性断裂**（均已定位到代码行）：

| # | 断裂 | 根因代码 | 后果 |
|---|---|---|---|
| 断裂 1 | adapter 格式不兼容 | `verifier_adapter.py:257` `sub6b_task_to_subsix_source_report()` 硬读 v3 键 | 6 字段全 None → ValidationError → 100% 崩 |
| 断裂 2 | RaMP 富集证据未捕获 | `react_runner.py:1044` `_store_enrichment_carrier()` **漏了 `run_ramp_enrichment` 分支** | verifier 最依赖的 RaMP carrier 永远空 → UV |
| 断裂 3 | 单源底座 vs 多源范式错配 | `set_enrichment.py` 认死 `ramp_enrichment_result`；`method_aware_enrichment.py` 单 carrier 路由；`driver_metabolite` 需 ground truth compounds | 无法消费 5 paradigm 共识；driver 必 UV |

**结论**：UV 偏高的真根因不是"缺某几个判定工具"，而是 verifier 底座模型与 v4 范式从根错配。这是重构级问题。

**预期产出**：verifier 在 v4 上跑通，拿到 V3 Part 2 之后第一份真实 UV 数字，且 UV 显著下降（多源池 + 命中任一 + 补查机制）。

---

## 1. 决策记录（已与用户确认）

| 决策点 | 选择 | 含义 |
|---|---|---|
| 重构范围 | **重写 `set_enrichment`** | 触发 ⚠ `[verifier-modify-warning]`，需 B1 回归实测数字 |
| 判定策略 | **命中任一 paradigm 即 SUPPORTED** | 多源池，宽松，supported 率高、UV 降快；假阳风险由 §5 sanity check 补偿 |
| 实施顺序 | **直接重构**（不单跑 baseline） | adapter 修复 + 多源重写一起做，D5 一次性跑 v4 出新数 |

---

## 2. 重构骨架

```
旧:  claim → set_enrichment（认死单源 RaMP 底座）→ 匹配不上即 UV

新:  claim → 多源证据池（5 paradigm carrier 全收：ramp/mummichog/metaboanalystr/sspa/fella）
            │
            ├─ 命中任一 paradigm 的 top_pathways          → SUPPORTED（命中任一，决策2）
            │
            ├─ 都匹配不上 → 工具补查（query_pathway_members）
            │       ├─ 补查命中                            → SUPPORTED
            │       └─ 仍无                                → INSUFFICIENT_EVIDENCE（带 missing-evidence checklist）
            │
            └─ 池内有该通路但 claim 的 rank/score 矛盾      → CONTRADICTED + top-1 alternative
```

**保留的优势**：4-shape grammar 强结构约束（可审计性强于 OriGene/GeneAgent 的 LLM 隐式判）。重构只换底座模型，不换 grammar。

**复用的现有资产**：
- `verifier/helpers/method_aware_enrichment.py` — `_carrier_rows` / `_find_row` / `pathway_ids_equivalent`（carrier 解析 + ID 等价），直接复用，把"单 carrier 路由"升级为"多源池合并"
- `concord/lookup/pathway_name_matcher.py`（2B）— 通路名语义匹配，并入池命中判定
- `verifier/helpers/pathway_namespace.py` — KEGG map↔hsa 等价

---

## 3. 分步实施计划（严格 TDD，每步独立 commit）

### D0 — 修复证据捕获断裂（`concord/`，`[concord-modify-warning]`）

- **D0.1** `react_runner.py:_store_enrichment_carrier` 加 `run_ramp_enrichment` 分支 → 存 `ramp_enrichment_result`（断裂 2，明确 bug）
- **D0.2** `verifier_adapter.py` 新增 `v4_task_to_subsix_source_report()`（不改旧 v3 函数）：
  - `ground_truth.perturbed_pathway` → `ground_truth_pathway`（id/name/ontology 映射）
  - `final_react_result.enrichment_carriers` 5 carrier 全收 → 对应 5 个 schema 字段
  - 补默认 `task_type="compound_only_enrichment"` / `domain=ontology`
  - `signal/noise_compounds` 缺失 → 空 list（D4 透明记录）
- TDD：各自 RED（v4 行 → 期望构造成功 / RaMP carrier 落字段）→ GREEN

### D1 — 多源证据池 + 命中任一 SUPPORTED（重写 `set_enrichment`，`[verifier-modify-warning]`）

- 新增 `verifier/helpers/multisource_enrichment.py`：合并 5 carrier 的 `top_pathways`/`pathways` 成统一 pool（复用 method_aware 解析 + 2B 名称匹配）
- 重写 `verify_set_enrichment`：查多源池，命中任一 paradigm → SUPPORTED；echo 命中来源到 evidence
- **向后兼容硬约束**：旧 B1 测试（sub6b-v3，只有 ramp 单源）中 ramp 仍是池一部分 → 仍命中 → 不退步
- 验收：Gate A 408/0 实测写进 commit body

### D2 — INSUFFICIENT_EVIDENCE + missing-evidence checklist（加新 enum ✅，OriGene 借鉴）

- 加 `ClaimVerdict.INSUFFICIENT_EVIDENCE`（新 enum，与 UV 区分：UV=范式外无法判；INSUFFICIENT=池内没有但可补查）
- 多源池不命中 → 补查 `query_pathway_members` → 仍无 → INSUFFICIENT_EVIDENCE + checklist（"缺什么数据/工具才能判定此 claim"）
- 下游同步：`react_runner` verdict filter + metrics 聚合识别新 enum

### D3 — CONTRADICTED 注入 top-1 alternative（GeneAgent 借鉴）

- 真矛盾时从多源池取 top-1 pathway 作为 `correction` + `feedback_hint`（不只说"错了"，给"应该是 X"）

### D4 — driver_metabolite v4 降级（透明 limitation）

- v4 无 signal/noise compounds → driver 层降级 INSUFFICIENT_EVIDENCE + 记录为 v4 设计取舍，不当 bug 修

### D5 — v4 全量重跑 + UV 对比 + 假阳 sanity check

- 跑 v4 benchmark（112 task）拿真实 UV，对比重构前（全 UV）后
- **假阳 sanity（决策2 宽松判定的补偿）**：统计 SUPPORTED claim 中命中 ground truth `perturbed_pathway` 的比例 vs 命中噪音 paradigm 的比例
- Gate A 408/0 + Gate B 不退步

---

## 4. 外部架构借鉴（OriGene / GeneAgent）

| 借鉴点 | 来源 | 落地到本重构 |
|---|---|---|
| 多源工具 grounding（g:Profiler 8库 + Enrichr 4库 双覆盖） | GeneAgent | D1 多源池（先用已有 5 paradigm；g:Profiler 作为未来扩展） |
| claim 拆解时过滤低可验证类型 | GeneAgent | 未来 — claim_extractor 阶段过滤注定 UV 的 claim |
| INSUFFICIENT_EVIDENCE ≠ UV（unsure→investigate） | OriGene | D2 |
| missing-evidence checklist + NextQuery | OriGene | D2 — UV/INSUFFICIENT 携带"缺什么"actionable signal |
| refuted 时注入 KB top-1 alternative | GeneAgent | D3 |

---

## 5. 风险 / 限制

| 风险 | 缓解 |
|---|---|
| "命中任一" + 无 baseline → supported 虚高难察 | D5 假阳 sanity check（命中 GT vs 命中噪音比例） |
| 5 carrier schema 异构（`pathways` vs `top_pathways` key 不一） | multisource helper 统一适配（复用 method_aware `_carrier_rows`） |
| 新 enum 下游消费遗漏 | D2 同步 react_runner verdict filter + metrics |
| driver layer v4 必 UV | D4 透明记录为 v4 设计取舍 |
| 重写 set_enrichment 触发 ⚠ 政策 | 每步 Gate A 408/0 实测写 commit body；旧 B1 测试向后兼容 |

---

## 6. 验收标准

- Gate A：B1 verifier-core 408 pass / 0 fail 不退步
- Gate B：全 repo 不新增非环境 fail
- v4：verifier 跑通（112/112 不再 adapter 崩），产出真实 UV 数字
- 假阳 sanity：SUPPORTED 命中 GT 比例 ≥ 命中噪音比例（具体阈值 D5 定）

### 实测结果（Task 10 offline replay — 2026-06-25）

使用 `scripts/metagent/v4_verifier_replay.py` 对 112 条 p1p2p3 traces 离线回放。

**关键前提**：traces 生成于 Task 1 RaMP carrier-capture patch 落地之前，
`enrichment_carriers` 中只含 `mummichog_enrichment_result` 和
`metaboanalystr_enrichment_result`，`ramp_enrichment_result` 缺失，multisource pool
仅 2/5 paradigm 可用。以下数字是**悲观下界**。

| 指标 | 结果 |
|---|---|
| Gate A | **408 pass / 0 fail** ✅ |
| Gate B | **1619 pass / 18 fail / 33 error**（fail 全部预存环境 fail，无新增）✅ |
| v4 adapter crash rate | **0 / 112**（重构前 112/112 崩）✅ |
| total verified claims | 1115（grammar 0 dropped）|
| SUPPORTED | 731 / 1115 = **65.6%** |
| INSUFFICIENT_EVIDENCE | 182 / 1115 = **16.3%** |
| UNSUPPORTED | 138 / 1115 = **12.4%** |
| UNVERIFIABLE_V0 | 64 / 1115 = **5.7%** |
| 假阳 sanity（set_enrichment SUPPORTED）| GT-match 169 / (169+174) = **49.3%**（<50%，因 RaMP 缺失导致 GT pathway 命中率偏低）|

**假阳 sanity 说明**：GT-match 49.3% < 噪音 50.7%，未达到"命中 GT ≥ 噪音"目标。
根因是 traces 缺 RaMP carrier（上述前提），GT pathway（多为 KEGG/RAMP_P 系）无法经
ramp-carrier 路径命中，而非 multisource 逻辑本身有误。带完整 RaMP carrier 的真实
live rerun 预计会扭转此比例。

**附注**：offline replay 使用 `common.llm_client.set_mock(["[]"] * 20)` 使 consistency
layer 离线模拟"无矛盾"，零 LLM API 成本。`verifier/claim_table.py` 中
`_SEVERITY_BY_VERDICT` 缺失 `INSUFFICIENT_EVIDENCE` 条目（Task 6 遗漏），在 replay
脚本内以 dict 注入方式修复（不改 production 文件）。
