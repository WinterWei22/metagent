# Prompt 改写前的现状审计(Sub-6B narrative + claim extract/classify)

目的:在动手重写 prompt 前,把 narrative 生成、claim 抽取、claim 分类、verifier 路由、feedback hint 五条链路的现状完整摸清楚,定位 63–67% UNV 占比的 prompt 层根因。本文档**只调研,不改文件**。

参考:`reports/agent/diagnosis_unverifiable_and_correlation.md` / `reports/agent/phase_a3_audit.md`(已有诊断)。

---

## 1. Narrative 生成 prompt 现状

### 1.1 入口与文件

| 路径 | 调用入口(文件:行) | 用途 |
|---|---|---|
| `evaluation/sub6/prompts.py` (`SYSTEM_PROMPT` + `USER_PROMPT_TEMPLATE`,L12–29)| `evaluation/sub6/run_sub6b.py:86` `build_messages(metabolites)`;同源被 `evaluation/sub6/run_sub6a.py:222` 复用 | Sub-6A **和** Sub-6B single-call 共用 |
| `prompts/agent/sub6b_react_prompt.md` (SYSTEM + USER 两段,共 67 行)| `evaluation/sub6/prompts_agent.py:60` `build_react_messages()` → `run_sub6b_react.py:174`,`run_sub6b_react_feedback.py:491` | Sub-6B ReAct(phase A1+) |
| `prompts/agent/sub6b_react_feedback_prompt.md`(50 行)| `run_sub6b_react_feedback.py:build_feedback_message()` | A2 D3 feedback 第二轮注入 |

### 1.2 Single-call prompt(`prompts.py`)— 完整 18 行

```
SYSTEM: "You are a metabolomics analyst. Reason carefully about pathway
biology from a list of differentially abundant metabolites. Do not invent
identifiers or list KEGG/InChIKey codes that were not given."

USER:
A metabolomics study identified the following metabolites as significantly
differentially abundant between control and treatment groups:
{metabolite_block}

Please analyze:
1. Which metabolic pathway(s) are most likely affected?
2. Which of the listed metabolites are key drivers in those pathways?
3. What is the biological significance of these pathway changes?
4. Are there upstream/downstream pathway relationships worth noting?

Provide reasoning in 200-400 words.
```

### 1.3 ReAct prompt (`sub6b_react_prompt.md`)关键段

System 部分(节选,完整文件 67 行):
- 列了 5 个工具(`query_ramp_enrichment` / `query_pathway_membership` / `query_kegg_path` / `lookup_compound_info` / `search_literature`)及调用规则。
- Hard rules 5 条:必须先调 enrichment、用真实 ID、不要重复同参调用、最后单一 assistant message 收尾。
- Decision rule:turn 3 应知 top pathway,turn 4 写 narrative,三轮无新证据则停。
- Narrative 格式要求:
  - 200–400 字
  - 必须覆盖 (a) pathway (b) drivers (c) biological significance **(d) upstream/downstream relationships you can verify**
  - 用 tool 返回的 proper name(如 "Cysteine and methionine metabolism (KEGG hsa00270)")
  - directional claim 要用 `query_kegg_path` 路径作背书

### 1.4 现存问题(5 条)

1. **强制四段式 = 强制思辨**。Single-call 的 Q3「biological significance」与 Q4「upstream/downstream」、ReAct 的 narrative 格式 (c)(d) 都**逼 LLM 必须写思辨与方向性内容**,即使工具无法支持也得编。这是 UNV 大量产生的结构性根因。
2. **没有句式/语态负面词表**。整套 prompt 没有任何「不要使用 may/suggest/potentially/likely/downstream」这类硬约束;Hard rules 只规定流程(先 enrichment)、不规定**输出句式可被 verifier 接住**。
3. **没有"可验证"的概念约束**。Prompt 鼓励 "ground every concrete claim in real database evidence",但 ground 的标准模糊:LLM 把"我调用过 enrichment"当作 grounded,即可输出 KEGG 三条 LOX/COX/CYP 分支这种抽象机理叙述(见 §6 样本)。
4. **Sub-6A 与 Sub-6B 共用 prompt,没有区分输入质量**。Sub-6A 输入是 top-1 鉴定结果(可能错),Sub-6B 输入是给定的 differential 列表(干净)。Prompt 用同一段话,Sub-6A 失败时无法在 narrative 层察觉。
5. **输出格式自由 markdown,无 JSON schema**。每段几百词的自由文本要靠下游 Stage 1 LLM 抽 claim,signal-to-noise 完全交给 extractor 来卷,extractor 又被要求"surface what the report says"(见 §2.2)→ 整段链条没有任何一步在做"过滤抽象/思辨"。

---

## 2. Claim Extract prompt 现状

### 2.1 入口

- `verifier/claim_extractor.py:169 extract_claims()`(LLM 路径,1 次 LLM call,JSON list 强制解析,无 retry)
- `verifier/claim_extractor.py:88 extract_claims_rulebased()`(Phase 6.4,Sub-6A real-id 用,按句/bullet 切,**不做原子分解**)
- Prompt 文件:`verifier/prompts/extract_claims.py`(SYSTEM + `_USER_TEMPLATE`)

### 2.2 完整 prompt(LLM 路径)

```
SYSTEM: "You are a precise extractor of factual claims from metabolomics
identification reports."

USER:
Extract every atomic factual claim from the report below. An atomic claim is
one factual statement that can stand on its own without surrounding context.
[examples: D-Gulose has molecular formula C7H14O7 / Caffeine maps to map00232 / mass accuracy <1ppm]
Decompose compound sentences. ...
Parenthetical chemical formulas attached ... yield a separate molecular-formula claim. ...
Pathway-enrichment narratives (Sub-6) follow a recognisable shape; extract these as separate atomic claims: ...
Only return a JSON list, for example: [{"claim_text": "...", "subject": "..."}, ...]
Report:
--- {report} ---
```

注释中**自己写明**:"deliberately does not include 'do not hallucinate' phrasing or instructions to drop uncertain claims. The job is *to surface what the report says*, not to filter it. Filtering happens in the verification layers." 这是 UNV 大量产生的**第二个**根因:**extractor 是"抓全",没有 schema 之外的 drop 逻辑**。

### 2.3 Schema

Pydantic `ExtractedClaim`(`verifier/schemas.py:426`),要求字段:
- `claim_text`(必填)、`subject`(可空)、`normalized_text`、`peak_mz`、`neutral_loss`、`claim_subtype`(`ClaimSubtype` 枚举)、`subject_kind`、`extracted_fields: ClaimExtractedFields`(可携带 formula / mz / pathway_name / pmid 等典型字段)。
- **没有 claim_type 限定枚举字段在 extractor 端**。type 是 Stage 2 决定的。
- 因此 extractor 对"抽象机理句"无任何拒绝信号:它返回的就是一条 `claim_text` 字符串。

---

## 3. Classify prompt + 类型枚举 + 路由表

### 3.1 入口与流程

`verifier/claim_classifier.py:230 classify_claims()`,两段式:
1. **Rule pass**(`_rule_classify`,L307):正则优先级 LITERATURE → PEAK_MECHANISTIC → PATHWAY_RELATIONSHIP → DRIVER_METABOLITE → SET_ENRICHMENT → BIOLOGICAL → GROUNDED → FACTUAL → None。
2. **LLM 兜底**(`_llm_classify`,L379):一次批量 line-delimited 调用;prompt 见 `verifier/prompts/classify_ambiguous.py`(SYSTEM + 8 类定义 + 多个例句)。

### 3.2 ClaimType 枚举(`verifier/schemas.py:46`)

| ClaimType | 值 | verifier 层(spectrum 路径 `verify`) | verifier 层(Sub-6 路径 `verify_sub6`) |
|---|---|---|---|
| GROUNDED | grounded_claim | `layers/grounded.py` (Layer A) | `UNVERIFIABLE_V0`(spectrum-centric,Sub-6 不支持) |
| FACTUAL | factual_roundtrip_claim | `layers/factual.py` (Layer B,fetcher) | `UNVERIFIABLE_V0` |
| BIOLOGICAL | biological_claim | `layers/biological.py` (Layer C) | `layers/biological_sub6.py` |
| CONSISTENCY | consistency_claim | `layers/consistency.py` (Layer D) | 同(Layer D 不读 source_report) |
| LITERATURE | literature_claim | `layers/literature.py` (Layer E) | 不在 sub6 dispatch,落 UNV |
| PEAK_MECHANISTIC | peak_mechanistic_claim | `layers/peak_mechanistic.py` (Layer F) | 同(Phase 6.3 接入) |
| SET_ENRICHMENT | set_enrichment | 无(spectrum 路径下落 GROUNDED 兜底) | `layers/set_enrichment.py` (6a) |
| DRIVER_METABOLITE | driver_metabolite | 无 | `layers/driver_metabolite.py` (6b) |
| PATHWAY_RELATIONSHIP | pathway_relationship | 无 | `layers/pathway_relationship.py` (6d) |

dispatch 代码:`verifier/agent.py:233 _verify_per_claim()` + `agent.py:444 _verify_per_claim_sub6()`。Sub-6 路径下,**所有非 6a/6b/6c/6d/F 的 type 一律直接返回 `UNVERIFIABLE_V0`**(`agent.py:494-518`),这是为什么 Sub-6B narrative 里只要 extractor 抽出 GROUNDED/FACTUAL 形式的 claim,verdict 一定是 UNV。

### 3.3 Classifier prompt 重点(`classify_ambiguous.py:_USER_TEMPLATE`)

8 类的定义文字 + 例句。其中:
- SET_ENRICHMENT 强调 collective subject(metabolites/data/set)与 "dominant/most affected pathway" 谓词。
- BIOLOGICAL 涵盖 pathway membership / disease relevance / 单一化合物角色。Examples 含 "Glutathione is involved in oxidative stress response."、"Polyamines regulate protein synthesis." → **现 prompt 主动收编这种抽象表述为 BIOLOGICAL**,然后 Sub-6 Layer C 在 RaMP/KEGG/HMDB 没匹配就给 unsupported/unverifiable。

注释里"Rules are expected to handle 80%+ of claims"指 rule pass 命中率;LLM 兜底仅处理规则不命中的子集。

---

## 4. Sub-6A vs Sub-6B 路径差异

| 项 | Sub-6A | Sub-6B |
|---|---|---|
| Narrative prompt(single-call) | `prompts.py:build_messages`(同份) | `prompts.py:build_messages`(同份) |
| Narrative prompt(ReAct) | 复用 `sub6b_react_prompt.md`(Phase 6.3 起也用) | `sub6b_react_prompt.md` |
| 输入 metabolite 来源 | top-1 鉴定结果(`run_sub6a.py:192 _ident_to_metabolite`),可能有错 | 任务给定的 differential 列表 |
| IdReport 注入 | **没有专门段**;只把 top-1 当作 metabolite 行注入 metabolite_block | N/A |
| extractor 路径 | Real-id v2 起切到 rule-based(`extract_claims_rulebased`)以保留整句 peak-mechanistic | LLM 抽取(原子分解) |
| Layer F (peak_mechanistic) | 有效(SubsixSourceReport 提供 spectrum adapter,Phase 6.3) | 无 spectrum;落 UNV |
| Layer A (grounded) | Sub-6 路径下直接 UNV(没 IdentificationReport candidates) | 同上 |
| Layer B (factual) | 同上 → UNV | 同上 → UNV |
| Layer E (literature) | Sub-6 dispatch 不分支 → UNV | 同 |

**结论**:Sub-6A 没有真正的 IdReport 注入到 prompt,所谓"Sub-6A 多 IdReport"在 narrative prompt 层并未体现;唯一差别在输入 metabolite 行的来源。Layer A/B/E 对 Sub-6A 和 Sub-6B **都** skip 成 UNV,所以这两类 claim 在 Sub-6 全链路上是死路。

---

## 5. Feedback hint 当前行为

`verifier/feedback_hints.py`:

- **会发 hint 的 verdict**:`CONTRADICTED` / `UNSUPPORTED`(`generate_feedback_hint`,L269)。
- **`_NEUTRAL_VERDICTS`(L57)= SUPPORTED / UNVERIFIABLE_V0 / ERROR / NEEDS_HUMAN_REVIEW** → **UNV 不发 hint**。这就是用户指出的"UNV 在 neutral 里、不进 feedback 循环"。
- Hint 模板按 (verdict, claim_type) 分支,产出一句模板话:
  - CONTRADICTED 分 4 桶:PATHWAY_RELATIONSHIP / DRIVER_METABOLITE / SET_ENRICHMENT+membership / 其他 BIOLOGICAL。
  - UNSUPPORTED 分 4 桶,**BIOLOGICAL 走 literature steer**(env `METAGENT_FEEDBACK_LITERATURE_STEER`,默认开)→ 提示 LLM 调 `search_literature` 救回(Phase A3 D1b)。
- 反馈模板见 `prompts/agent/sub6b_react_feedback_prompt.md`,要求 LLM:retract / rephrase / 加 80 词 Limitations / 不引入新 claim / 不再扩散研究。

**问题**:UNV 不发 hint = 写得越抽象越"安全"(不会被 retract),完美强化"思辨型句子"的产出。

---

## 6. 典型 UNV claim 样本剖析

样本来自 `data/eval/sub6/v4_a3_d3_with_lit/react/compound_only_enrich_mammalian_lm_pathway_WP167_seed0/verdict.json`(59 条 claim,分布:biological/UNV 21,biological/unsupported 10,grounded/UNV 9,factual/UNV 8,biological/supported 7,driver/UNV 2,set/contra 1,consistency/contra 1)。narrative 主体见 `narrative.json`(节选见 §1 之后)。

挑 8 条覆盖典型问题(标签 = 问题类别):

| # | claim | type/verdict | 问题类别 |
|---|---|---|---|
| 1 | "The six lipids are canonical intermediates of the three major enzymatic arms radiating from arachidonic acid" | biological / UNV | **抽象概念**(无端点的"canonical intermediates / arms") |
| 2 | "The three major enzymatic arms include the lipoxygenase branch producing HETEs and leukotrienes" | biological / UNV | **抽象概念 + 教科书叙述**,无 pathway_id 可挂 |
| 3 | "Arachidonic acid is the central upstream node driving the observed elevation or depletion of its downstream eicosanoid products" | driver / UNV | **猜测语态**("driving the observed elevation **or** depletion") |
| 4 | "This perturbation pattern is consistent with inflammatory activation" | biological / UNV | **猜测语态**("consistent with") + 抽象 |
| 5 | "Arachidonic acid has KEGG ID C00219" | factual / UNV | **工具真的够不到**(Sub-6 dispatch 不跑 Layer B → 直接 UNV)|
| 6 | "A two-hop path links arachidonic acid to 15-HETE via an intermediate" | biological / UNV | **方向性链式推理**;原文有 KEGG path,但 extractor 拆分后丢了 C05966 端点 |
| 7 | "6 of the 7 input compounds are confirmed as pathway members of Arachidonic Acid Metabolism" | biological / **unsupported** | extractor 抽出聚合声明,Layer 6c 找不到 6/7 的精确 anchor |
| 8 | "Leukotriene A4 epoxide is the precursor of the classic inflammatory leukotriene cascade" | grounded / UNV | **抽象概念**,且被分类为 GROUNDED → Sub-6 dispatch 直接 UNV |

**根因归属估算(基于该样本 59 条 + diagnosis 报告的整体口径)**:

| 类别 | 占 UNV 的估算比例 | 主要触发位置 |
|---|---|---|
| 猜测语态(may/suggest/consistent with/likely)| ~25–30% | narrative prompt 没禁用 |
| 抽象概念(教科书机理/分支/cascade)| ~25–30% | narrative prompt 鼓励 (c)(d) 段 |
| 方向性链式推理(downstream / drive / upstream of)| ~15–20% | prompt (d) 直接要求 + Sub-6 缺 hierarchy table |
| 工具真的够不到(Sub-6 dispatch skip GROUNDED/FACTUAL/LITERATURE)| ~20–25% | `agent.py:494-518` 一刀切 UNV |
| extractor 切碎导致丢端点 | ~5–10% | `claim_extractor.py:170-230` 原子分解 |

前三类是 **prompt 层可消化** 的;第 4 类需要在 prompt 层让 narrative 不产出这种 GROUNDED/FACTUAL 形态;第 5 类需要 extractor schema 限定。

---

## 7. Prompt 改写候选清单

| 文件 | 改动方向 | 优先级 |
|---|---|---|
| `prompts/agent/sub6b_react_prompt.md` | **改 narrative**:加禁用词表(may/suggest/potentially/likely/可能/可能性/consistent with/canonical/cascade);删除 (c) biological significance 和 (d) upstream/downstream 的强制项,改为"可选,且必须给出工具证据 ID";加输出 schema(JSON list of pathway/driver/relationship 三类显式 claim,每条带 evidence_id 引用工具 turn);单一 collective subject 改写为 "metabolites are enriched in <pathway> (KEGG <id>) (evidence: turn N enrichment)" 句式硬模板 | **P0** |
| `evaluation/sub6/prompts.py` | **改 narrative**:single-call 路径要么淘汰、要么同样加禁用词表 + 输出 schema。Phase A3 之后基本走 ReAct,但 baseline 还在跑 single-call | P1 |
| `prompts/agent/sub6b_react_feedback_prompt.md` | **改 hint 注入端**:把 UNV 也纳入 feedback(配合 §1.4 #5 schema 化,UNV 直接告知 "drop or rephrase to verifiable schema");把第 3 条 Limitations 段去掉(它现在变成 LLM 二次自由发挥的入口)| P0 |
| `verifier/prompts/extract_claims.py` | **改 extract**:加 schema 外 drop 规则——遇到"无具体端点的机理叙述/方向性猜测/抽象 cascade 词"返回空对象或标记 `claim_text=null, dropped_reason=...`;补 Sub-6 narrative 的 negative examples(三条 LOX/COX/CYP 教科书句应被 drop) | **P0** |
| `verifier/prompts/classify_ambiguous.py` | **改 classify**:删除 BIOLOGICAL 收编抽象单化合物角色句的指引(目前 "Polyamines regulate protein synthesis." → biological_claim 是把不可验句子留进 layer);增加一类 `unverifiable_speculation`(或让 classifier 直接输出"drop_recommended")让 dispatcher 提前剪枝 | **P0** |
| `verifier/feedback_hints.py` | **改 hint 行为**:把 UNV 从 `_NEUTRAL_VERDICTS` 移除并加专门模板("the verifier had no tool to check this — rewrite as a verifiable enrichment / membership / KEGG-path statement, or drop");按 claim_type 走不同模板,与 §1 改写后的 schema 句式对齐 | **P0** |
| `verifier/agent.py:494-518`(非 prompt,但与 prompt 改写连带)| Sub-6 dispatch 一刀切 UNV 的 fallback 需要在 prompt schema 落地后审视:理想情况下 prompt 不再产出 GROUNDED/FACTUAL 形态 claim,该兜底变得罕见 | P2 |

**改写主路径建议**:先改 `sub6b_react_prompt.md`(narrative 端硬约束,GeneAgent 思路) → 同步改 `extract_claims.py`(schema 外 drop) → 同步改 `classify_ambiguous.py`(收紧 BIOLOGICAL) → 同步改 `feedback_hints.py`(让 UNV 也能回灌)→ 再观察 `prompts.py` 是否仍需要保留 single-call 路径。
