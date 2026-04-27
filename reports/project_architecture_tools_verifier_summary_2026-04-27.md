# MetAgent 项目架构、工具链与 Verifier 总结报告

日期：2026-04-27
项目路径：`/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5`

## 1. 项目定位

本项目是一个面向 MS/MS 代谢物鉴定的 LLM-agent 系统。它不是让 LLM 直接“猜化合物”，而是先用确定性工具链生成结构化的 `IdentificationReport`，再让 LLM 基于该报告写出自然语言鉴定结论，最后由 verifier 对 LLM 输出中的 claim 逐条核验、标注、必要时改写。

整体设计目标：

- 把谱图处理、候选生成、数据库查询、文献检索等步骤拆成独立工具。
- 用统一 schema 约束工具输入输出，避免 LLM 直接处理松散文本。
- 让 LLM 只负责解释、综合和叙述，不作为唯一事实来源。
- 用 verifier 将 LLM 输出重新拉回可检查的证据链上。

## 2. 总体流程

当前完整流程可以概括为：

```text
raw MS/MS spectrum
→ preprocess
→ candidate_prefilter
→ library_search
→ molecule_generate
→ predict_spectrum
→ metabolite_info / pathway_context / literature_search
→ IdentificationReport
→ naive orchestrator LLM
→ verifier
   → claim extraction
   → claim classification
   → layer-specific verification
   → consistency check
   → rewrite if needed
→ UI 展示
```

真实运行中主要分两个环境：

- `diffms`：跑确定性 pipeline，包含 matchms、RDKit、模型推理等依赖。
- `metagent-llm`：跑 orchestrator、verifier、UI、LLM 调用和轻量工具。

UI live 模式实际执行的是：

```text
Gradio UI
→ ui.data.live_pipeline_runner in diffms
→ orchestrator.naive.identify in metagent-llm
→ verifier.agent.verify in metagent-llm
→ UI panels render
```

## 3. 代码结构

核心目录：

```text
schemas/        项目级数据契约
tools/          确定性工具模块
scripts/        pipeline CLI / 审计脚本 / backfill 脚本
orchestrator/   LLM 编排层
verifier/       LLM 输出核验层
ui/             Gradio UI
tests/          单元测试和集成测试
reports/        各阶段交付报告和实验记录
```

### 3.1 `schemas/`

`schemas/` 是整个系统的接口核心。重要对象包括：

- `Spectrum`：实验谱图，包含 `mz`、`intensity`、`precursor_mz`、`adduct`、`ionization_mode` 等。
- `Candidate`：候选分子基础信息，包含 SMILES、name、score、source 等。
- `CandidateReport`：候选级综合报告，聚合 library score、predicted cosine、metabolite info、pathway context、literature records 等。
- `IdentificationReport`：pipeline 的最终结构化输出，是 orchestrator 和 verifier 的主要输入。

这个设计的关键价值是：LLM 和 verifier 都不直接依赖工具内部实现，只依赖稳定的 report schema。

### 3.2 `tools/`

每个工具模块都遵循类似模式：

```text
tool.py            公开调用入口
schemas.py         请求 / 响应 schema
errors.py          工具级异常
tool_description.md 给 LLM 或开发者看的能力边界说明
```

主要工具包括：

- `spectrum_ops`：谱图预处理。
- `candidate_prefilter`：候选池预筛。
- `library_search`：谱库匹配。
- `molecule_generate`：结构生成 / 候选扩展。
- `spectrum_predict`：预测候选分子的 MS/MS 谱图。
- `metabolite_info`：HMDB / PubChem 等代谢物信息查询。
- `pathway_context`：KEGG / SMPDB / RaMP 等通路上下文。
- `literature`：Europe PMC 文献查询。
- `sirius`：SIRIUS fragmentation tree 注释。
- `classyfire`：ClassyFire 化学分类。

## 4. Pipeline 设计

主入口是 `scripts/run_full_pipeline.py`。

命令示例：

```bash
conda run -n diffms python scripts/run_full_pipeline.py \
  --fixture caffeine_pos \
  --output json \
  --top-k 6 \
  --predict-top-n 2 \
  --literature-top-n 1
```

pipeline 的职责是把 raw fixture 谱图转成 `IdentificationReport`。核心阶段：

1. `preprocess`：清理和标准化谱图。
2. `candidate_prefilter`：根据 precursor mass / adduct / PubChem Lite 等获得候选。
3. `library_search`：用 GNPS 或本地谱库做匹配。
4. `molecule_generate`：补充生成式候选。
5. `predict_spectrum`：对 top candidates 预测谱图并计算 cosine。
6. `metabolite_info`：补充 formula、exact mass、SMILES、InChIKey、cross refs。
7. `pathway_context`：补充 pathway / biological context。
8. `literature_search`：补充候选相关文献。
9. fusion ranking：输出候选排序和各项 evidence score。

当前 pipeline 的一个实际问题是：某些真实运行中 candidate name / metabolite info 会 degraded，例如新跑的 caffeine report 中多个候选 `candidate.name=None`、`metabolite_info.found=False`。这会影响后续 verifier 根据 claim subject 定位 SMILES。

## 5. Orchestrator 设计

`orchestrator/naive.py` 是当前主 orchestrator。

设计特点：

- 输入：`IdentificationReport`
- 输出：自然语言鉴定报告 `llm_output`
- 调用：一次 LLM call
- 不做复杂 tool-use，不做多轮规划，不做自验证

它的定位是“naive baseline”：把结构化 report 转成 prompt，让 LLM 生成可读报告。它的优势是简单、可测试、容易暴露 LLM hallucination 类型；缺点是输出容易出现事实漂移、过度推断、内部矛盾或 claim 粒度不稳定。

CLI 示例：

```bash
conda run -n metagent-llm python -m orchestrator identify \
  --report-json /tmp/report.json \
  --output json \
  --trace-id real_caffeine_20260427_t1t2
```

## 6. Verifier 总体设计

Verifier 位于 `verifier/`，入口是 `verifier.agent.verify()`。

它是一个 4-stage cascade：

```text
Stage 1: claim_extractor
Stage 2: claim_classifier
Stage 3: layer verification
Stage 4: rewriter
```

### 6.1 Stage 1：Claim Extraction

模块：`verifier/claim_extractor.py`

职责：

- 从 LLM 自然语言输出中抽取 atomic factual claims。
- 每条 claim 应该能独立判断。
- 输出 `ExtractedClaim`，包含 `claim_text`、`subject`，以及现在新增的可选 `peak_mz`、`neutral_loss`。

这是 verifier 的上游瓶颈之一。若 extraction 把 claim 切得不合理，后续分类和验证都会受影响。

### 6.2 Stage 2：Claim Classification

模块：`verifier/claim_classifier.py`

职责：

- 给每条 claim 分配 `ClaimType`。
- 优先使用 rule-based regex。
- 规则无法判断时，批量调用 LLM fallback。

当前 claim 类型：

- `GROUNDED`：直接查 `source_report`。
- `FACTUAL`：数据库事实或化学分类事实。
- `BIOLOGICAL`：通路、生物样本、代谢背景。
- `CONSISTENCY`：文内一致性，由 consistency layer 生成。
- `LITERATURE`：PMID / DOI / 文献 claim。
- `PEAK_MECHANISTIC`：峰级机制 claim，接 SIRIUS。

Type 5 规则最新修正：

- 普通 `[M+H]+ precursor m/z` 不再触发 `PEAK_MECHANISTIC`。
- 只有包含 fragment / neutral loss / ring cleavage / bond scission / `[M+H-...]` 等机制语义时才进入 Type 5。

### 6.3 Stage 3：Layer Verification

模块集中在 `verifier/layers/`。

每个 layer 输入：

```python
ClassifiedClaim
IdentificationReport
```

输出：

```python
VerifiedClaim
```

`VerifiedClaim` 包含：

- `claim_text`
- `claim_type`
- `verdict`
- `evidence`
- `source_field`
- `correction`

verdict 类型：

- `SUPPORTED`
- `CONTRADICTED`
- `UNSUPPORTED`
- `UNVERIFIABLE_V0`
- `ERROR`

`UNVERIFIABLE_V0` 是设计上非常重要的保守状态，表示当前工具和数据不足以判断，而不是 claim 一定错误。

### 6.4 Stage 4：Rewrite

模块：`verifier/rewriter.py`

当 v1 claims 中存在 `CONTRADICTED` 或 `UNSUPPORTED` 时，Stage 4 会调用 LLM 改写原始输出，然后重新 extraction / classification / verification，形成 `claims_v2`。

最终 `VerifiedIdentification` 保留：

- 原始 LLM 输出 `source_llm_output`
- 改写输出 `rewritten_output`
- `claims_v1`
- `claims_v2`
- `overall_verdict`
- `verification_warnings`
- `llm_call_count`

最坏情况下 verifier 可能消耗 7 次 LLM call。

## 7. 各 Verifier Layer 逻辑

### 7.1 Grounded Layer

模块：`verifier/layers/grounded.py`

负责检查 source report 中已有字段，例如：

- formula
- precursor m/z
- neutral mass
- evidence score
- cosine score
- candidate rank
- peak count
- adduct

它的优点是无需外部工具调用，直接以 pipeline report 为 source of truth。

### 7.2 Factual Layer

模块：`verifier/layers/factual.py`

原始功能：

- 处理 HMDB / KEGG / PubChem CID / ChEBI / InChIKey 等 ID claim。
- 先 source-first 检查 `source_report.candidates[*].metabolite_info.cross_refs`。
- 如果 source report 没有，再调用 `fetch_metabolite_info` round-trip。

新扩展：

- 支持 ClassyFire 化学分类 claim。

示例：

```text
Caffeine is a purine.
Glucose is a monosaccharide.
L-carnitine belongs to the amino acid class.
```

触发条件：

- claim 没有数据库 ID。
- claim 文本像 chemical taxonomy claim。
- claim 中出现短 vocabulary 中的化学类别词，例如 `purine`、`alkaloid`、`amino acid`、`monosaccharide`、`lipid` 等。

执行逻辑：

```text
claim
→ 判断是否 chemical class claim
→ 从 source_report 根据 subject/name/synonym 找候选
→ 取 SMILES
→ classify_structure(ClassifyStructureRequest(smiles=...))
→ resp.matches_claim(claimed_class)
→ SUPPORTED / CONTRADICTED / UNVERIFIABLE_V0
```

真实工具测试：

```text
Caffeine is a purine
→ ClassyFire confirms: Xanthines (source: cache)
→ SUPPORTED
```

已知限制：

- 如果 source report 中候选没有 name / primary_name / synonym，claim subject 无法定位 SMILES，会返回 `UNVERIFIABLE_V0`。
- ClassyFire 依赖 RDKit 由 SMILES 生成 InChIKey；当前 `metagent-llm` 环境有 RDKit / NumPy ABI warning，虽然测试中仍返回成功，但环境需要清理。

### 7.3 Biological Layer

模块：`verifier/layers/biological.py`

负责 pathway / biological context claim，例如：

- caffeine metabolism
- galactose metabolism
- biological sample prevalence
- disease/pathway membership

它依赖 `source_report.candidates[*].pathway_context`。

当前保守性较强：

- 如果 pathway context 缺失，通常返回 `UNVERIFIABLE_V0`。
- 对宽泛 biological narrative 的验证能力有限。

这是后续优化重点之一。

### 7.4 Literature Layer

模块：`verifier/layers/literature.py`

负责 PMID / DOI / Europe PMC claim。

逻辑：

- 如果 source report 里已有 literature records，先 source-first。
- 否则调用 literature search / Europe PMC round-trip。
- hallucinated PMID / DOI 或 title/journal mismatch 会被标出。

### 7.5 Consistency Layer

模块：`verifier/layers/consistency.py`

负责文内一致性，不验证外部事实。

例如：

- 同一化合物 formula 在不同段落不一致。
- 一处说 caffeine 是 top candidate，另一处说另一个候选分数最高且是最终鉴定。

真实 caffeine run 中出现过 consistency contradiction：

```text
Caffeine is identified as top candidate by evidence score 0.695
but another claim states 1,3,8-trimethyl... score 0.701 is highest.
```

### 7.6 Peak Mechanistic Layer

模块：`verifier/layers/peak_mechanistic.py`

这是最新新增 layer，接入 SIRIUS。

目标 claim：

```text
The peak at m/z 163.06 corresponds to [M+H-H2O]+.
m/z 138.07 is the imidazole ring fragment of caffeine.
Fragment at 175.07 corresponds to lactone ring cleavage.
```

验证逻辑：

```text
claim
→ 提取 peak_mz
→ 检查 experimental_spectrum 中 5 ppm 内是否有该峰
→ 若无峰：CONTRADICTED
→ 若有峰：调用 SIRIUS
→ lookup_fragment(mz, tolerance_ppm=5)
→ 若 SIRIUS tree 无 fragment：UNSUPPORTED
→ 若有 fragment：比较 neutral loss
→ neutral loss 匹配：SUPPORTED
→ neutral loss 不匹配：CONTRADICTED + correction
```

neutral loss 支持常见别名：

```text
H2O == H₂O == water == 18.01
NH3 == ammonia
CO2 == carbon dioxide
...
```

真实工具测试：

```text
The peak at m/z 138.0662 is a fragment ion of caffeine
→ SIRIUS confirms fragment at m/z 138.0662
→ formula C6H7N3O
→ neutral loss C2H3NO
→ SUPPORTED
```

已知限制：

- 当前 fixture 谱图通常只有 5-7 个 peaks，SIRIUS 对稀疏谱图可能无法建树。
- 如果 SIRIUS binary 或 `python-dotenv` 不可用，会返回 `UNVERIFIABLE_V0`，不崩 pipeline。

## 8. UI 设计

UI 位于 `ui/`，使用 Gradio。

入口：

```bash
conda run -n metagent-llm python -m ui.app \
  --host 0.0.0.0 \
  --port 7862 \
  --enable-live
```

当前 UI 分为几类 panel：

- Experimental panel：展示输入谱图和预处理信息。
- Pipeline panel：展示候选、分数、预测谱图 overlay 等。
- LLM panel：展示 orchestrator 输出和 prompt/log 信息。
- Verifier panel：展示 verifier verdict、claims、rewritten output、warnings。

UI live 模式会：

1. 接收 fixture 或用户输入谱图。
2. 调用 pipeline subprocess。
3. 调用 orchestrator LLM。
4. 调用 verifier。
5. 缓存 report 和 verifier sidecar。

重要说明：

- UI 会使用新版 verifier。
- 但 ClassyFire/SIRIUS 是否触发取决于 LLM 输出里是否自然出现对应 claim。
- 如果 LLM 只写普通候选排序和 mass/formula claim，则不会触发 ClassyFire/SIRIUS。

## 9. 测试现状

Verifier 单元测试当前通过：

```text
conda run -n metagent-llm python -m pytest tests/test_verifier/ -q
151 passed in 0.42s
```

真实场景测试已完成：

1. `diffms` 环境跑真实 caffeine pipeline。
2. `metagent-llm` 环境跑真实 orchestrator LLM。
3. 新版 verifier 跑完整 cascade。
4. 额外构造工具触发 claim，验证真实 ClassyFire 和 SIRIUS 均可工作。

真实 orchestrator 输出 verifier 结果：

```text
overall contradicted
claims_v1 47
claims_v2 34
llm_calls 7
warnings []
```

工具触发测试：

```text
Caffeine is a purine
→ factual_roundtrip_claim
→ SUPPORTED
→ ClassyFire confirms: Xanthines

The peak at m/z 138.0662 is a fragment ion of caffeine
→ peak_mechanistic_claim
→ SUPPORTED
→ SIRIUS confirms fragment, formula C6H7N3O
```

全仓库 `pytest` 当前仍未完全可复现，主要阻塞：

- 部分环境缺 `matchms`
- 缺 `requests_mock`
- 曾缺 `dotenv`，本次已在 `metagent-llm` 安装 `python-dotenv`
- RDKit 与 NumPy ABI 不兼容 warning

## 10. 当前主要问题

### 10.1 Claim extraction / classification 仍是关键瓶颈

真实测试已经暴露过误分类：

```text
The precursor m/z 195.0877 [M+H]+ corresponds to a neutral mass...
```

最初被误判成 Type 5，已修复并加回归测试。但这说明 rule-based classifier 需要持续用真实 LLM 输出校准。

### 10.2 Pipeline enrichment 不稳定

新跑的 caffeine report 中：

```text
candidate.name = None
metabolite_info.found = False
```

这会导致 verifier 无法从 claim subject 找到候选 SMILES，从而影响 ClassyFire。

建议优化：

- candidate name fallback
- InChIKey / SMILES canonicalization
- metabolite_info 多 backend fallback
- source_report 中保留更多 candidate provenance

### 10.3 Biological claims 仍大量 UNVERIFIABLE

很多 biological narrative 无法直接映射到 pathway membership。

后续可以考虑：

- 更明确地区分 pathway claim、sample prevalence claim、biological plausibility claim。
- 为 biological layer 增加更多外部 evidence source。
- 对 broad biological statements 使用更合适的 verdict 策略。

### 10.4 SIRIUS 需要更丰富谱图评估

当前 fixture 太稀疏，无法充分测试 fragmentation tree 的真实覆盖率。

建议准备：

- 高峰数 caffeine / glucose / L-carnitine 谱图。
- 带明确 neutral loss 的 benchmark cases。
- 人工标注 fragment assignment ground truth。

### 10.5 环境需要整理

当前项目跨多个 conda env，依赖状态不完全一致。建议输出明确的环境规范：

- `environment.diffms.yml`
- `environment.metagent-llm.yml`
- `requirements-ui.txt`
- `requirements-test.txt`
- pinned NumPy / RDKit 组合

## 11. 下一步优化建议

### 11.1 建立真实输出 regression corpus

保存每次真实运行的：

```text
input spectrum
IdentificationReport
orchestrator llm_output
extracted claims
classified claims
verified claims
rewritten output
human annotations
```

用途：

- 评估 claim extraction。
- 评估 classifier。
- 评估 verifier verdict。
- 捕捉新的 hallucination 类型。

### 11.2 改造 claim classifier

当前 rule-based 有可维护性上限。

建议：

- 保留高精度规则。
- 对 ambiguous claim 使用 constrained schema LLM。
- 输出 `claim_subtype`，例如：
  - `database_id`
  - `formula`
  - `chemical_taxonomy`
  - `peak_fragment`
  - `neutral_loss`
  - `pathway_membership`
  - `literature_citation`

这会让 layer dispatch 更稳定。

### 11.3 增强 verifier trace

建议每条 claim 记录：

- classification rule hit
- extracted fields
- tool called or not
- tool request summary
- tool response summary
- latency
- fallback reason

UI 可以展示“本次触发了哪些 verifier tools”。

### 11.4 强化 source_report

建议把 `IdentificationReport` 从“给 LLM看的摘要”进一步变成“verifier source of truth”：

- 每个 candidate 保留 canonical SMILES / InChIKey。
- 保留 original name、database name、synonyms。
- 保留每个字段来自哪个工具。
- 对 degraded info 记录明确 reason。

### 11.5 改进 UI

建议增加：

- verifier tool trace panel
- claims table 可过滤 Type / verdict
- 展示 rewrite diff
- 展示 ClassyFire/SIRIUS 是否触发
- 展示 UNVERIFIABLE 原因聚合

### 11.6 设计 richer benchmark

目前 3 fixture 不足以评估所有 verifier 能力。

建议新增：

- rich caffeine fragmentation fixture
- glucose / hexose ambiguity fixture
- L-carnitine zwitterion fixture
- known wrong taxonomy claim
- known wrong neutral loss claim
- known hallucinated PMID / DOI claim

## 12. 给下一轮 GPT 的重点问题

可以让 GPT 围绕以下问题构思优化：

1. 如何把 claim extraction / classification 从 regex-heavy 变成更稳健的 typed claim parser？
2. 如何改造 `IdentificationReport`，让 verifier 更容易从 subject 定位候选和证据？
3. 如何定义 biological claim 的可验证边界，减少无意义 `UNVERIFIABLE_V0`？
4. 如何让 UI 清楚展示 verifier 做了什么，而不是只显示最终 verdict？
5. 如何设计一套真实 MS/MS benchmark，覆盖 formula、candidate ranking、taxonomy、fragment、neutral loss、literature、pathway 七类 claim？
6. 如何清理环境，使 pipeline、UI、verifier、全仓库测试可复现？

## 13. 当前结论

项目已经形成清晰的分层架构：

```text
deterministic tools
→ structured report
→ LLM narrative
→ claim-level verifier
→ rewritten / audited output
```

最新版本已经把 ClassyFire 和 SIRIUS 接入 verifier，并通过单元测试和真实工具触发测试验证。当前最值得继续优化的不是单个工具，而是：

- claim 结构化质量
- source_report 的证据完整性
- verifier trace 可解释性
- 真实 benchmark 和环境可复现性

这几个方向会直接决定系统从 demo 走向可靠研究工具的上限。
