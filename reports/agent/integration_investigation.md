# ConcordMet Integration Feasibility — Investigation Report

**Branch:** `feature/investigation-concord` (from tag `MetAgent-v1-0514` @ `5bbedcf`)
**Worktree:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5_investigation`
**Started:** 2026-05-15
**Investigator:** Claude (Opus 4.7)
**Mode:** Read-only on existing business code; exploration scripts + report only; no push to origin.

---

## Status Dashboard

| Section | Title | Budget | Status |
|---|---|---|---|
| §0 | 竞品 Repo 实际状态 | 0.5d | **Done(待人工验证 Q-01)** |
| §1 | Codebase Reality Check | 0.5d | **Mostly done(§1.1 pytest 结果待)** |
| §2 | 10 候选工具系统调研 | 2d | Pending (后续 session) |
| §3 | 统一 EnrichmentResult Schema | 0.5d | Pending |
| §4 | Tier A 工具集成计划 | 1d | Pending |
| §5 | Pathway ID Crosswalk 策略 | 0.5d | Pending |
| §6 | Risk Register | 0.5d | Pending |
| §7 | Open Questions | 0.5d (rolling) | Rolling |
| §8 | W1 Gate 1 Toy 数据 (Fig 3 雏形) | 1d | Pending |
| §9 | W3-W4 Sprint Daily Plan | 0.5d | Pending |

**Total budget:** 7 working days wall-time. Each section gates the next where dependencies exist (e.g. §3 depends on §2 hands-on data).

---

## Stop Conditions (任一触发暂停)

1. mummichog 完全装不上(Py3.11+ 不支持)→ 不要 deep debug,报告 + 等用户决定切 R 端
2. FELLA rpy2 spike 显示 K=10 并发完全不可用 + Python 重写预估 > 3 周 → 报告 + 等决定
3. KEGG API rate limit 实测显示 academic 调用已锁 → 影响 §4,立刻 flag
4. Reactome / LIPID MAPS download 失败 → 报告替代源
5. §8 toy run 完全跑不出(所有 method 都失败)→ 影响 Gate 1 判定,立刻报告

---

## §0 — 竞品 Repo 实际状态

_Read-only recon (no clone / no install). 子代理(Explore agent)用 gh CLI + WebFetch 调研 GitHub + 论文摘要,数据 freeze 于 2026-05-15。_

> ⚠️ **可信度警告**:子代理报告中 MS4MS / MSAgent 的 bioRxiv URL 前缀为 `10.64898/...`,但 bioRxiv 标准 DOI 前缀是 `10.1101/...`。这两个链接 **疑似 fetch 模型幻觉**,Investigation §6 / §7 需人工验证(可能项目压根不在 bioRxiv,而在 medRxiv / ChemRxiv / arXiv,或论文识别错误)。MetaboT 和 GeneAgent 的链接通过 GitHub repo 路径交叉验证可信。

### 0.1 MetaboT (Bekbergenova et al., ISMB 2025)
- **Paper / preprint**: arxiv.org/abs/2510.01724
- **Repo**: github.com/HolobiomicsLab/MetaboT
- 状态:**public**
- 装环境难度(读 README 推测,不真装):med — Python 3.11,标准 pip install,需 API key
- README toy 文档化:good — 有 quickstart / CLI 示例 / Streamlit 部署说明
- 输入输出 schema 文档化程度:good — 自然语言 → SPARQL → 结构化结果
- 用什么 LLM:GPT-4o(单次 baseline 8.16% acc,多智能体框架 83.67%)
- 我们能否 head-to-head benchmark? **Y** — 都做 MS 代谢物知识图谱问答;可对标其 50 题基准或共同 benchmark(CANOPUS / CASMI)
- 给 ConcordMet 的借鉴:多智能体架构(入口→验证→监督→KG→查询生成)的分层设计;通过外部知识库(Wikidata / ChEMBL / NPClassifier)做实体解析消除幻觉,这与 ConcordMet 的 reconciliation 思路接近

### 0.2 MS4MS (Guo et al., bioRxiv 2025-12)
- **Paper**:URL 待人工验证(⚠️ 子代理给的 `biorxiv.org/content/10.64898/2025.12.02.691830v2` 疑似幻觉)
- **Repo**:**未公开**(论文仅报告模型部署在 8× NVIDIA 4090,无 code 链接)
- 状态:**paper-only**
- 装环境难度:不可推测(无公开代码)
- README toy / 输入输出 schema:N/A
- 用什么 LLM:**未声明**(仅说 "LLM 驱动多智能体")
- 我们能否 head-to-head benchmark?**部分** — 端到端 LC-MS/MS → 小分子识别 top-1 92.04% 报告,但无法复现
- 给 ConcordMet 的借鉴:4-agent 分工(谱处理 → 分子式预测 → 小分子识别 → 报告);GPU 部署架构

### 0.3 MSAgent (Li et al., bioRxiv 2026-04)
- **Paper**:URL 待人工验证(⚠️ 子代理给的 `biorxiv.org/content/10.64898/2026.04.22.720103v1.full` 疑似幻觉)
- **Repo**:**未公开**
- 状态:**paper-only**
- 装环境难度:不可推测
- README toy / 输入输出 schema:partial — 论文提到 MSToolbox 50+ 域工具支持证据收集与人类可读报告,但工具清单未公开
- 用什么 LLM:**未声明**
- 我们能否 head-to-head benchmark?**Y(若日后开源)** — 论文报告 CASMI MRR > 10% gain / CANOPUS Tanimoto +40%;可对标基准集
- 给 ConcordMet 的借鉴:Evidence grounding 是反幻觉关键;动态工具调用 + 多资源证据融合 + 自校验;"95% 保持或改进排名" 这个 ranking-stability 指标值得采纳

### 0.4 GeneAgent (Wang et al., Nat Methods 2025) — **标杆,非竞品**
- **Paper**:nature.com/articles/s41592-025-02748-6
- **Repo**:github.com/ncbi-nlp/GeneAgent
- 状态:**public**
- 装环境难度:med — Python 3.11, PyTorch 1.13, 需 Azure OpenAI GPT-4 credentials
- README toy 文档化:good — 含示例 / 评估 notebook / 配置说明
- 输入输出 schema 文档化程度:good — gene set → 自校验循环 → 功能注解
- 用什么 LLM:GPT-4(via Azure OpenAI,version 20230613)
- 我们能否 head-to-head benchmark? **N(语义域不同)** — 但 1106 基因集 92% 决策准确率 + P=3.1e-5 的评估范式是直接借鉴对象
- 给 ConcordMet 的借鉴:**核心借鉴**。四步自校验循环(生成 → 验证 → 修改 → 总结)直接映射到 ConcordMet:候选 → DB/文献交叉验证 → 修正 → 报告。**论文级评估范式建议直接 copy**:N=1000+ 样例 + 大规模统计检验 + 可解释性证据链展示

### 0.5 §0 小结

| 项目 | Repo | Head-to-head | 借鉴价值 |
|---|---|---|---|
| MetaboT | public | Y | 多智能体分层 + 实体解析消歧 |
| MS4MS | 未公开 | 部分(仅引用) | 4-agent 分工(架构参考) |
| MSAgent | 未公开 | Y(若日后开源) | Evidence grounding + 95% ranking-stability 指标 |
| GeneAgent | public(NCBI 出品) | N(域不同) | **核心:四步自校验 + 大规模 N=1000+ 评估范式** |

**Open question for §7**:MS4MS / MSAgent 的 bioRxiv DOI 子代理报告疑似幻觉,需人工到 bioRxiv 搜索原始论文(关键词 "MS4MS metabolomics" / "MSAgent mass spectrometry")并修正 §0.2 / §0.3 URL。在 §7 已登记 Q-01。

---

## §1 — Codebase Reality Check

_不靠记忆,实际跑 pytest + tree + grep,产出 3 张表 + "偏差"段。_

### 1.1 Pytest 现状

**Command:** `pytest tests/ -q --ignore=tests/test_ui --ignore=tests/integration`
**Collected:** 607 tests(`--co` 计数)
**Result:** TBD — 后台运行中(pid 2106656,Python 3.13)。

**Known pre-existing skip / ignore(tag MetAgent-v1-0514):**
- `tests/test_ui/test_panel_verifier.py` → 缺 `gradio` 模块(UI 测试,collect 阶段直接报 `ModuleNotFoundError: No module named 'gradio'`,B1 D2 已 ignore)
- `tests/integration/` → 需要 minimax key / 外部服务,常规 CI 跳过
- 收集到的 PytestUnknownMarkWarning:`integration`、`requires_minimax_key` 两个 mark 未注册(pyproject 未在 tag 状态登记)

### 1.2 当前 5 个 Agent Tool 入口

(基于 `tools/agent_tools/*.py` 实际文件,tag `MetAgent-v1-0514` 状态)

| File | 工具语义 | 数据源(实际) | 入口签名 |
|---|---|---|---|
| `tools/agent_tools/lookup_compound_info.py` | 化合物元数据 / cross-ref | `tools.metabolite_info.fetch_metabolite_info`(HMDB + PubChem 后端,具体待 §4 拆解) | `lookup_compound_info(payload: dict) -> dict` |
| `tools/agent_tools/query_kegg_path.py` | KEGG pathway 查询 | **本地 KEGG sqlite**(`sqlite3.connect(_resolve_kegg_db())`,无 REST 调用) | `query_kegg_path(payload: dict) -> dict` |
| `tools/agent_tools/query_pathway_membership.py` | Pathway 成员 + 共现 plausibility | `tools.pathway_context.pathway_context`(RaMP-DB,可能伴 `RampUnavailableError`) | `query_pathway_membership(payload: dict) -> dict` |
| `tools/agent_tools/query_ramp_enrichment.py` | RaMP enrichment (hypergeometric ORA) | `tools.benchmark.sub6.ramp_enrichment.compute_enrichment` — RaMP-DB sqlite | `query_ramp_enrichment(payload: dict) -> dict` |
| `tools/agent_tools/search_literature.py` | 文献检索(摘要 cap 500 字符) | `tools.literature.literature_search` — PubMed / Europe PMC,可抛 `RateLimitError` | `search_literature(payload: dict) -> dict` |

辅助文件(非独立 tool):`dispatcher.py`(LLM tool-call routing)、`schemas.py`(Pydantic input schemas)、`tool_definitions.py`(对 LLM 暴露的 function schema)、`__init__.py`。

### 1.3 当前 10 层 Verifier(Layers A-F + Sub-6 扩展)

(基于 `verifier/layers/*.py`,tag MetAgent-v1-0514)

| File | Layer 语义 | Routing 来源 ClaimType | 数据 |
|---|---|---|---|
| `verifier/layers/grounded.py` | Layer A — grounded(source-report 引用)| `GROUNDED`(main, agent.py:239)+ `CONSISTENCY` fallback(agent.py:261)| source_report |
| `verifier/layers/factual.py` | Layer B — 事实查证(外部 fetcher)| `FACTUAL`(main, agent.py:241)| source_report + `fetcher` |
| `verifier/layers/biological.py` | Layer C — biological(Sub-5 路径)| `BIOLOGICAL`(main, agent.py:243)| source_report |
| `verifier/layers/literature.py` | Layer E — literature 验证 | `LITERATURE`(main, agent.py:245-250)| source_report + `literature_fetcher` |
| `verifier/layers/peak_mechanistic.py` | Layer F — spectrum/peak mechanistic(CFM-ID + SIRIUS cross-validate)| `PEAK_MECHANISTIC`(main, agent.py:251-256;Sub-6,agent.py:486-493)| source_report + `cfmid_fn` |
| `verifier/layers/consistency.py` | Layer D — cross-claim consistency(独立 stage,见 docstring "Layer D runs separately") | — | claim 集合 |
| `verifier/layers/biological_sub6.py` | Sub-6 biological 适配 | `BIOLOGICAL`(verify_sub6, agent.py:479-485)| `SubsixSourceReport` + RaMP db_path/conn |
| `verifier/layers/set_enrichment.py` | Sub-6 set enrichment | `SET_ENRICHMENT`(verify_sub6, agent.py:464)| SubsixSourceReport |
| `verifier/layers/driver_metabolite.py` | Sub-6 driver metabolite | `DRIVER_METABOLITE`(verify_sub6, agent.py:466)| SubsixSourceReport |
| `verifier/layers/pathway_relationship.py` | Sub-6 pathway relationship | `PATHWAY_RELATIONSHIP`(verify_sub6, agent.py:472)| SubsixSourceReport |

合计 **10 个 layer file**;其中 4 个是 Sub-6 专用(biological_sub6 / set_enrichment / driver_metabolite / pathway_relationship),5 个是主线 Layer A/B/C/D/E/F(D=consistency 单独 stage,所以 dispatch 处只见 5 个 elif)。

### 1.4 Dispatcher Routing

**两个 dispatcher 函数**(都在 `verifier/agent.py`,tag MetAgent-v1-0514):

**Main dispatcher `verify()`(line 230-264)** — 处理主线 IdentificationReport claims:

```
for c in claims:
    candidate_ref = resolve_candidate_ref(c, source_report)   # line 236
    if c.claim_type == ClaimType.GROUNDED:           → layer_a.verify_grounded            # 239
    elif c.claim_type == ClaimType.FACTUAL:          → layer_b.verify_factual(fetcher=)   # 241
    elif c.claim_type == ClaimType.BIOLOGICAL:       → layer_c.verify_biological           # 243
    elif c.claim_type == ClaimType.LITERATURE:       → layer_e.verify_literature(literature_fetcher=)  # 245
    elif c.claim_type == ClaimType.PEAK_MECHANISTIC: → layer_f.verify_peak_mechanistic(cfmid_fn=)      # 251
    elif c.claim_type == ClaimType.CONSISTENCY:      → layer_a.verify_grounded (LLM-fallback 兜底)     # 257
    else: raise AssertionError                       # 262 — exhaustive guard
```

**Sub-6 dispatcher `verify_sub6()`(line 373-519)** — 处理 SubsixSourceReport claims:

```
for c in claims:
    if c.claim_type == ClaimType.SET_ENRICHMENT:      → layer_set_enrichment              # 464
    elif c.claim_type == ClaimType.DRIVER_METABOLITE: → layer_driver_metabolite          # 466
    elif c.claim_type == ClaimType.PATHWAY_RELATIONSHIP: → layer_pathway_relationship    # 472
    elif c.claim_type == ClaimType.BIOLOGICAL:        → verify_biological_sub6           # 479
    elif c.claim_type == ClaimType.PEAK_MECHANISTIC:  → layer_f.verify_peak_mechanistic  # 486 (跨用 Layer F)
    else: → UNVERIFIABLE_V0 declared-limitation                                            # 494-518
```

**注意点**:
- Layer D (consistency) 不在 dispatch 链里,docstring 标 "Layer D runs separately"。需要在 §1.5 偏差段记一笔。
- `CONSISTENCY` claim 在 main dispatch 处会被 default-route 到 Layer A grounded(注释解释:Stage 2 不该直接 emit CONSISTENCY,Layer D 才创建;若 LLM fallback 漏出,以 grounded 兜底)。
- 同一个 `Layer F (peak_mechanistic)` 被两条 dispatch 路径共用(main + Sub-6)。
- `tag MetAgent-v1-0514` 早于 D3 commit `01a858b`(classifier 9→4 collapse),所以 claim grammar 还是 v1 9-class。

### 1.5 和我之前理解的偏差

对比 codebase 实际结构 vs Investigation 启动前(从用户文档 + 评审材料推断的)mental model:

1. **"10 层 verifier" 不是单 dispatcher 的 10-way 分支**
   实际是 2 个 dispatcher × 5 个 ClaimType elif 分支 = 10 个 layer file。`verify()` 主线 5 分支(GROUNDED / FACTUAL / BIOLOGICAL / LITERATURE / PEAK_MECHANISTIC,+ CONSISTENCY 兜底到 grounded),`verify_sub6()` 5 分支(SET_ENRICHMENT / DRIVER_METABOLITE / PATHWAY_RELATIONSHIP / BIOLOGICAL / PEAK_MECHANISTIC,+ UNVERIFIABLE_V0 declared-limitation 兜底)。这意味着 ConcordMet 集成 enrichment 工具(§2 / §3)主要落在 **Sub-6 `SET_ENRICHMENT` 分支**,不会扰动主线 5 个 layer。
2. **Layer D (consistency) 不在 dispatch 链里**
   `verifier/layers/consistency.py` 在 `verify()` 调用之外作为 separate stage 跑(docstring "Layer D runs separately")。需要查 `verifier/__init__.py` 或 runner 入口确认 Layer D 何时触发(§2 之前不影响,但写 §3 schema 时若考虑 cross-claim consistency 验证需要回看)。
3. **`Layer F (peak_mechanistic)` 被两条 dispatch 路径共用**
   `layer_f.verify_peak_mechanistic` 同时在 main(L251)和 Sub-6(L486)被调用。改 Layer F 需要双侧测试。
4. **5 个 agent tool 的数据源 mix**
   一个真正"REST 调用"(search_literature → PubMed/Europe PMC,有 RateLimitError);两个本地 sqlite(query_kegg_path / query_ramp_enrichment + query_pathway_membership 走 RaMP);一个聚合元数据后端(lookup_compound_info,具体 backend 待 §4 拆 `tools.metabolite_info`)。**ConcordMet 集成 sspa / mummichog / FELLA 都会落到"新增本地工具"层,不需要新建 REST integration framework**,这降低了 §2 估时。
5. **tag MetAgent-v1-0514 早于 D3 collapse**
   tag freeze 在 9-class claim grammar 状态。B1 D3(commit `01a858b`)做的 9→4 collapse 不在 Investigation worktree 里。**§8 Gate 1 toy 用 9-class extractor 也成立**(toy 不依赖最新 grammar);但 §9 W3-W4 sprint 实施时若 B1 已合并到 main,需对齐到 4-class grammar。

(更多偏差会在 §2 / §3 hands-on 时追加。)

---

## §2 — 10 候选工具系统调研

_后续 session,2 天预算。包含 hands-on 真装真跑 + FELLA rpy2 K=10 并发 spike。_

### 2.0 环境预侦察(本 session,§1 顺带做的)

```
Python: 3.13.11  (miniconda)
✓ rdkit  2025.09.6   (§2.6 跳过 install)
✗ sspa               (待装,§2.1 hands-on)
✗ mummichog          (待装,§2.2 hands-on — ⚠️ Py3.13 兼容性高风险)
✗ rpy2               (待装,§2.4 hands-on — ⚠️ R broken,见下)
✗ metanetx_sdk       (待装,§2.5)
✗ sqlalchemy         (待装,DB ETL 用)
✗ requests_cache     (待装,REST 缓存用)

R: /home/weiwentao/miniconda3/bin/R
   ⚠️ BROKEN: `R --version` 失败,libstdc++ GLIBCXX_3.4.30 not found
   (路径冲突:/lib/x86_64-linux-gnu/libstdc++.so.6 缺新版 GLIBCXX,
    但 miniconda 的 libicuuc.so.75 需要它)
```

**这两个发现直接影响 §2 计划**:
- **mummichog Py3.13 兼容性高风险**:历史 mummichog 只支持 Py3.7-3.9。§2.2 hands-on 大概率直接撞 stop condition #1(完全装不上),需立刻报告 + 等用户决定切 R 端。**但 R 端也坏了**(见下)→ Stop condition 升级:**需要先修 R 环境或考虑 Python 重写 mummichog 算法(也是 fallback path)**。已登记 Q-02。
- **R 环境 broken**:`GLIBCXX_3.4.30 not found` 是典型的 conda libstdc++ 和系统 libstdc++ 版本冲突。这同时影响:
  - §2.3 MetaboAnalystR 4 subprocess(R 跑不起来 → 直接 stop)
  - §2.4 FELLA rpy2 K=10 spike(R 跑不起来 → rpy2 也跑不起来)
  - §2.2 mummichog R-fallback path 也不可用
  - **任何 R-based 工具集成在本机当前状态都无法 hands-on**
  - 已登记 Q-03,提交用户决定:修 R / 切别的服务器 / 直接放弃 R 端工具

### 2.1 py-sspa — Pending (hands-on §2 session)
### 2.2 mummichog v3 (强制 hands-on) — Pending,⚠️ 高风险见 §2.0
### 2.3 MetaboAnalystR 4 (subprocess) — **BLOCKED on R env**,见 Q-03
### 2.4 FELLA (rpy2 并发 spike) — **BLOCKED on R env**,见 Q-03
### 2.5 MetaNetX MNXref 4.5 — Pending
### 2.6 RDKit InChIKey reconciler — rdkit 已装,只需 30-line toy 即可,Pending
### 2.7 Tier B/C 工具速记 — Pending
- PathIntegrate / IMPaLA / PIUMet / NetGSA / fgsea / clusterProfiler / MetExplore / OmicsNet

---

## §3 — 统一 EnrichmentResult Schema

_依赖 §2 实测输出。后续 session。_

最终 schema(Python dataclass)+ 4 个 normalizer 签名 + 已知映射 gap 列表。

---

## §4 — Tier A 工具集成计划

### 4.1 Database Release Pinning — TBD

| 库 | 锁定 release | 验证状态 |
|---|---|---|
| Reactome | TBD | Pending |
| KEGG | TBD(academic rate limit 实测) | Pending |
| LIPID MAPS | TBD | Pending |
| HMDB | 已有 v5.0 | Pending 确认 |
| ChEBI | TBD | Pending |
| PubChem | PUG-REST(rate limit 实测) | Pending |
| MetaNetX | sqlite | Pending |

### 4.2 50-Metabolite × 7 Source 覆盖矩阵 — TBD
### 4.3 W3-W5 集成顺序 — TBD

---

## §5 — Pathway ID Crosswalk 策略

**已拍板**:Internal storage Reactome ID 主键;reporting KEGG ID;crosswalk Reactome ↔ KEGG;Reactome 缺失则 canonical_source=kegg。

### 5.1 Reactome ↔ KEGG 覆盖率 — TBD
### 5.2 Fallback 占比(50 个常见 pathway 抽样)— TBD
### 5.3 Crosswalk Table Schema — TBD

---

## §6 — Risk Register

_整合 R1-R10 + 评审 R8/R9/R10 + Investigation 新发现。_

| Risk | 概率 | Impact | 缓解 | Verification |
|---|---|---|---|---|
| R1: 同方向被抢先 | 高 | 高 | 早 preprint | (无法 verify) |
| R2: LLM 幻觉超出 verifier 兜底 | 中 | 中 | LLM 只协调,工具确定性 | B1 D5 部分缓解 |
| R8: Motivation 不成立 | 中 | 高 | W1 Gate 1 | §8 toy data 验证 |
| R9: Reconciliation 没用 | 中 | 高 | W6 Gate 2 + pivot | W6 才能 verify |
| R10: 竞品无 code | 高 | 中 | 引用 + cannot-reproduce 声明 | §0 验证 |
| TBD R3-R7 + R-NEW-X | | | | |

---

## §7 — Open Questions (Rolling)

_Investigation 期间所有 scope 外但应问的问题归这里。_

### Q-01 — MS4MS / MSAgent bioRxiv URL 真实性校验
- **背景**:§0 子代理回报的 MS4MS 和 MSAgent bioRxiv 链接 DOI 前缀均为 `10.64898/...`,但 bioRxiv 标准前缀是 `10.1101/...`。两者可能是 WebFetch fetch 模型在 abstract page 上幻觉生成的。
- **影响**:不解决会让 §6 risk register R10(竞品无 code)缺少准确引用;§9 W3-W4 Sprint plan 也无法引用对方 benchmark 做 head-to-head。
- **我的建议**:由用户(或下次 session 人工)到 bioRxiv 搜索关键词 "MS4MS metabolomics" / "MSAgent mass spectrometry",定位真实 DOI;若 bioRxiv 无 → 转 ChemRxiv / medRxiv / arXiv 检索。**不能自决**,因为 fetch 重复尝试可能再次幻觉。
- **W 影响**:不阻塞 §2 / §8。最迟在 W2 report 时解决。

### Q-02 — mummichog Python 3.13 兼容性 + R-fallback 双不可用
- **背景**:本机 Python 是 3.13.11,而 mummichog 历史只支持 Py3.7-3.9(setup.py 通常 pin)。同时本机 R 环境 broken(见 Q-03),所以"切 R 端"的 fallback 也不可用。
- **影响**:§2.2 hands-on 很可能完全失败,触发 stop condition #1;§4 集成顺序(W4 mummichog)需要 fallback 决策。
- **我的建议**:三选一,用户拍板:
  (a) 跑一个独立 conda env 装 Py3.9 + mummichog 验证(工程量 1-2h,但可能仍失败)
  (b) 直接放弃 mummichog,改用 sspa 自带的 mummichog-like 实现(若有)或 Python-port `pyMummichog`(实测可用性未知)
  (c) Python 自己重写 mummichog 核心算法(权威老算法,~500 LOC,2-3 天工程)
  我倾向 (a) 先 spike,失败则 (b)。**不能自决**因为依赖 Sprint 时间预算。
- **W 影响**:不阻塞 §1 / §5 / §6 / §7;阻塞 §2.2、§4(W4)、§8(若 §8 toy 想跑 mummichog method)。

### Q-03 — 本机 R 环境 broken(GLIBCXX_3.4.30)
- **背景**:`R --version` 报错 `/lib/x86_64-linux-gnu/libstdc++.so.6: version GLIBCXX_3.4.30 not found`。典型的 miniconda libstdc++ 和系统 libstdc++ 版本错配。
- **影响**:**直接 BLOCK §2.3 / §2.4** — MetaboAnalystR subprocess + FELLA rpy2 都跑不起来,Tier A 工具调研中两个最重的项目无法进行;§4 W5 集成顺序无法 finalize。
- **我的建议**:三选一:
  (a) 修本机 R:`conda install -c conda-forge libstdcxx-ng` 或 `conda update -c conda-forge --all`,然后重试 R(预计 30 分钟;失败可能性高,因为 path 冲突看着复杂)
  (b) 切到另一台服务器跑 §2.3 / §2.4(若用户有备用环境)
  (c) **放弃 R 端工具,纯 Python 路径**:这意味着 ConcordMet **不集成 FELLA / MetaboAnalystR**。需要重新评估 §4 Tier A 列表 + 用户原文档的 4-axis 是否还成立(其中"网络拓扑 axis" 主要靠 FELLA;若去掉需找替代工具如 PIUMet 或 OmicsNet)。
  我倾向 (a) 先 spike;失败转 (c)。**不能自决**,(c) 改变 Sprint 主线。
- **W 影响**:**阻塞 §2.3 / §2.4 / §4(W5)/ §8(若想跑 FELLA-based PA)**。属于 Investigation 最重 blocker。

### Q-04 (placeholder) — TBD

---

## §8 — W1 Gate 1 Toy 数据 (Fig 3 雏形)

_最关键产出。决定 W1 Gate 1 PASS / BORDERLINE / FAIL。1 天预算,后续 session。_

### 8.1 Task 选样 — TBD(5-10 task,from `data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl`)
### 8.2 PA 方法 ≥ 2 — TBD(RaMP ORA + sspa ssGSEA + 可选 mummichog)
### 8.3 ID 方法 ≥ 2 — TBD(HMDB direct + RDKit InChIKey)
### 8.4 跨方法 Jaccard / 跨库 disagreement — TBD
### 8.5 Gate 1 判定 — TBD
### 8.6 Fig 3 雏形(`data/investigation/fig3_toy/jaccard_matrix.png` + CSV)— TBD

```
Mean cross-method Jaccard < 0.4   → Gate 1 PASS
                       0.4 - 0.6  → Gate 1 BORDERLINE
                          > 0.6   → Gate 1 FAIL → W1 pivot
```

---

## §9 — W3-W4 Sprint Daily Plan

_基于 §0-§8 实证产出,后续 session。_

Gantt-style 表 / markdown checklist,带 wall-time 估计 + 依赖关系。

---

## Session Log

### Session 1 — 2026-05-15
**Owner:** Claude (Opus 4.7)
**Time:** ~30 min wall
**Done:**
- ✅ 建 worktree `metagent_day1_v5_investigation` @ tag `MetAgent-v1-0514`,在新分支 `feature/investigation-concord` 上
- ✅ 报告骨架 9 sections + Stop Conditions + Status Dashboard
- ✅ §0 竞品 4 repo recon(子代理并行)
- ✅ §1.2 - §1.5 (codebase tools + verifier layers + dispatcher routing + 5 个偏差)
- ✅ §2.0 环境预侦察(Python 3.13, rdkit ✓,其余 ✗,R broken)
- ✅ §7 登记 Q-01 / Q-02 / Q-03 三个 open question

**Pending(本 session 没收尾的):**
- ⏳ §1.1 pytest 结果(后台 7+ min 还在跑;后续 session 接收完成通知后填)

**Blockers for next session(§2 hands-on)**:
- 🔴 **Q-03 R env broken** — §2.3 / §2.4 完全 BLOCKED,需用户先决定修 R / 换服务器 / 放弃 R 工具
- 🔴 **Q-02 Py3.13 vs mummichog** — §2.2 大概率失败,需用户决定 fallback 路径
- 🟡 **Q-01 MS4MS/MSAgent URL** — 不阻塞 §2,但 W2 report 前需修

**Commits:**
- `7786512 docs(investigation): scaffold integration report + §0 §1 first pass`(+ 后续 commit 见 git log)

**Next session 建议**:
1. 等用户对 Q-02 / Q-03 拍板(否则 §2 卡死)
2. §2.5 MetaNetX + §2.6 RDKit InChIKey reconciler(纯 Python,Q-02/03 不阻塞)
3. §1.1 pytest 结果回填
4. 开始 §3 schema 草案(基于已知工具输出格式)

---

## Appendix — 完成定义

- [ ] 9 个 section 全填
- [ ] `data/investigation/fig3_toy/` 含 Jaccard PNG + CSV
- [ ] `feature/investigation-concord` 上有 N 个 exploration script commit(纯 docs / explore)
- [ ] **不 push origin**
- [ ] Ping 用户做 W2 review
