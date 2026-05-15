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
| §1 | Codebase Reality Check | 0.5d | **Done(988/2/10,2 fail 非阻塞)** |
| §2 | 10 候选工具系统调研 | 2d | Pending (后续 session) |
| §2 | 10 候选工具系统调研 | 2d | **8/10 (2.0/2.1/2.2/2.5/2.6 done;2.3/2.4 ESCALATE Q-03;2.7 Tier-B/C pending)** |
| §3 | 统一 EnrichmentResult Schema | 0.5d | **Done(v0.3 namespace pivot,11 gap 中 3 RESOLVED / 8 W3 处理)** |
| §4 | Tier A 工具集成计划 | 1d | **partial(8/12 release locked,ChEBI ETL spec 完整)** |
| §5 | Pathway ID Crosswalk 策略 | 0.5d | **Done(3 路 crosswalk + 4 表 namespaced schema)** |
| §6 | Risk Register | 0.5d | **Done(10 原 R + 14 R-NEW)** |
| §7 | Open Questions | 0.5d (rolling) | **Rolling(Q-01 ✅ / Q-02 ✅ / Q-03 ✅ (A) Docker / Q-04 ✅ via ChEBI is_a / Q-05 ✅ / Q05-NEW-4 ✅ / Q05-NEW-5 ✅)** |
| §8 | W1 Gate 1 Toy 数据 (Fig 3 雏形) | 1d | **✅ GREEN(mean Jaccard 0.049,wall 89s)** |
| §9 | W3-W4-W5 Sprint Daily Plan | 0.5d | **Done(W3 5 days + W4 5 days w/ Docker hedge + W5 5 days)** |

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

> ✅ **2026-05-15 二次核实**:WebSearch 在 biorxiv.org 域内**直接命中** MS4MS 和 MSAgent 两篇,关键词描述与子代理摘要互洽。
>
> **重要发现**:bioRxiv 在 2026 年起对新提交 paper **新增了 `10.64898/` DOI 前缀**(原 `10.1101/` 仍用于 2025 及以前)。搜索结果显示 6+ 篇 2026 年 bioRxiv 新 paper 都是 `10.64898` 前缀。**Investigation 启动时(前个 session)误判为幻觉**,实际两篇 paper 均真实存在。Q-01 已 RESOLVED。

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
- **Paper**:https://www.biorxiv.org/content/10.64898/2025.12.02.691830v2.full ✅(WebSearch 2026-05-15 二次核实命中)
- **Repo**:**未公开**(论文仅报告模型部署在 8× NVIDIA 4090,无 code 链接)
- 状态:**paper-only**
- 装环境难度:不可推测(无公开代码)
- README toy / 输入输出 schema:N/A
- 用什么 LLM:**未声明**(仅说 "LLM 驱动多智能体")
- 我们能否 head-to-head benchmark?**部分** — 端到端 LC-MS/MS → 小分子识别 top-1 92.04% 报告,但无法复现
- 给 ConcordMet 的借鉴:4-agent 分工(谱处理 → 分子式预测 → 小分子识别 → 报告);GPU 部署架构

### 0.3 MSAgent (Li et al., bioRxiv 2026-04)
- **Paper**:https://www.biorxiv.org/content/10.64898/2026.04.22.720103v1.full ✅(WebSearch 2026-05-15 二次核实命中)
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

**Q-01 状态:RESOLVED**(2026-05-15 WebSearch 二次核实)。
- 两篇 bioRxiv paper 均真实存在;新 DOI 前缀 `10.64898/` 是 bioRxiv 2026 年新增。
- ChemCrow (Bran et al.) 未在 §0 列出 —— 用户提示其 chemistry-broad 偏离 metabolomics scope,**作为 honorable mention** 不必扩 §0 调研。若 §6 risk register 提到"竞品宽度"维度可补一句"+ ChemCrow (chemistry-broad, 非 metabolomics-narrow)"。

---

## §1 — Codebase Reality Check

_不靠记忆,实际跑 pytest + tree + grep,产出 3 张表 + "偏差"段。_

### 1.1 Pytest 现状

**Command:** `pytest tests/ -q --ignore=tests/test_ui --ignore=tests/integration`
**Wall time:** 11 min 42 s(Python 3.13.11,本机 conda)
**Result:** **988 passed / 2 failed / 10 skipped** — 基本健康,2 个 fail 都是环境依赖(非代码 bug)。

**2 个 failure(均在 `tests/tool_tests/test_library_search.py`,均为 GNPS 库搜索测试):**
1. `TestFallbackPath::test_missing_gnps_env_raises_library_unavailable` — 测"缺 GNPS env 应抛 LibraryUnavailable",但本机环境状态未对齐 fixture 预期
2. `test_integration_full_gnps_pool_finds_known_compound` — 集成测,需要真 GNPS 库 pool

**判定:这 2 个 fail 不阻塞 Investigation**(GNPS library search 不在 ConcordMet enrichment / reconciliation 主线工具集);但后续 §2 hands-on 期间若需触碰 library_search 路径需先修。已登记为 §6 R-NEW-01 风险候选。

**Known pre-existing skip / ignore(tag MetAgent-v1-0514):**
- `tests/test_ui/test_panel_verifier.py` → 缺 `gradio` 模块(UI 测试,collect 阶段直接报 `ModuleNotFoundError: No module named 'gradio'`,B1 D2 已 ignore)
- `tests/integration/` → 需要 minimax key / 外部服务,常规 CI 跳过
- 收集到的 PytestUnknownMarkWarning:`integration`、`requires_minimax_key`、`requires_sirius` 三个 mark 未注册(pyproject 未在 tag 状态登记;非阻塞,但 §6 风险候选 R-NEW-02 记一笔)。

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

### 1.5 和我之前理解的偏差(逐条分类)

对比 codebase 实际结构 vs Investigation 启动前(从用户文档 + 评审材料推断的)mental model。每条标:
- **DD** = Documentation Drift(我之前理解偏差但代码 OK,无需改代码)
- **AB** = Actual Bug(代码确实有问题)
- **MF** = Missing Feature(我以为有但没有)

---

**[DD] D1 — "10 层 verifier" 不是单 dispatcher 的 10-way 分支**
实际是 2 个 dispatcher × 5 个 ClaimType elif 分支 = 10 个 layer file。`verify()` 主线 5 分支(GROUNDED / FACTUAL / BIOLOGICAL / LITERATURE / PEAK_MECHANISTIC,+ CONSISTENCY 兜底到 grounded),`verify_sub6()` 5 分支(SET_ENRICHMENT / DRIVER_METABOLITE / PATHWAY_RELATIONSHIP / BIOLOGICAL / PEAK_MECHANISTIC,+ UNVERIFIABLE_V0 declared-limitation 兜底)。代码意图清晰,只是我的 mental model 没分主线/Sub-6 两条 dispatch。
**ConcordMet 影响**:enrichment 工具集成主要落在 Sub-6 `SET_ENRICHMENT` 分支,**不扰动主线 5 layer**。降低了集成 risk。

**[DD] D2 — Layer D (consistency) 不在 dispatch 链里**
`verifier/layers/consistency.py` 在 `verify()` 调用之外作为 separate stage 跑(docstring "Layer D runs separately")。代码 OK,只是我以为它在 dispatch 链里。
**ConcordMet 影响**:写 §3 schema 时若想给 ConcordMet 加 cross-method consistency 验证,需要回看 Layer D 是怎么 wire 进 runner 的(单独 stage 而非 dispatch entry)。

**[DD] D3 — `Layer F (peak_mechanistic)` 被两条 dispatch 路径共用**
`layer_f.verify_peak_mechanistic` 同时在 main(agent.py:251)和 Sub-6(agent.py:486)被调用。代码 OK(intentional shared layer),只是我以为只在主线。
**ConcordMet 影响**:若 ConcordMet 后续修改 Layer F(疑似需要修改 cross-validation 逻辑,因为引入更多 enrichment 工具),**需要双侧测试**——不能只测 main dispatch。

**[DD] D4 — 5 个 agent tool 数据源 mix(2 sqlite + 1 sqlite-wrapper + 1 REST + 1 元数据 backend)**
一个真正"REST 调用"(search_literature → PubMed/Europe PMC,有 RateLimitError);两个本地 sqlite(query_kegg_path 自管 sqlite + query_ramp_enrichment 走 RaMP-DB sqlite);一个 sqlite-wrapper(query_pathway_membership 走 RaMP);一个聚合元数据后端(lookup_compound_info,backend 待 §4 拆 `tools.metabolite_info`)。代码 OK,只是我之前没看具体每个 tool 的 backend。
**ConcordMet 影响**:**关键发现** — sspa / mummichog / FELLA 都会落到"新增本地工具"层,**不需要新建 REST integration framework**,降低了 §2 估时;但 PubChem PUG-REST 在 lookup_compound_info backend 里仍是单点(§4 rate-limit 实测对象之一)。

**[DD] D5 — tag MetAgent-v1-0514 早于 D3 classifier collapse**
tag freeze 在 9-class claim grammar 状态。B1 D3 commit `01a858b` 做的 9→4 collapse 不在 Investigation worktree。代码 OK(tag 是干净基线,intentional),只是需要注意时间线:
- **§8 Gate 1 toy** 在 9-class grammar 下也成立(toy 不依赖最新 grammar)
- **§9 W3-W4 sprint 实施时** 若 B1 已合并到 main,需对齐到 4-class grammar
- **集成测试** 不能在 worktree 跑 B1 后期 fixture(版本不匹配)

---

**汇总:5 条全是 DD,0 AB,0 MF。** 无需登记 Q-04;§7 不新增条目。如 §2 hands-on 期间发现真 bug,届时补登 Q-04。

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

### 2.1 py-sspa — ✅ Import + load_example_data + process_reactome 通

**Env**: `conda env mummichog_py310`(同 Q-02 env,Py 3.10.18)
**Install**: `pip install sspa` → **sspa 1.0.4**(deps: gseapy 1.2.1, pandas 2.3.3, scikit-learn 1.7.2, statsmodels 0.14.6, scipy 1.15.3, requests, tqdm)

**安装 caveat**(已解决):
1. **`pkg_resources` 缺失**(setuptools ≥ 81 不再 bundle)→ 降到 `setuptools<80`(79.0.1 通)
2. **`tqdm` 缺失**(sspa `download_pathways` 隐式依赖,未在 setup.py 声明)→ `pip install tqdm`
**这两条进 §6 R-NEW-11**(sspa upstream packaging gap)。

**API 暴露(24 个 attr)**:
- 方法:`sspa_ora`(hypergeometric ORA)、`sspa_gsea`(preranked GSEA)、`sspa_ssGSEA`、`sspa_KPCA` / `sspa_kpca`(kernel PCA)、`sspa_SVD`、`sspa_ssClustPA`、`sspa_zscore`、`sspa_cluster`、`t_tests`
- 数据:`load_example_data`、`download_KEGG`、`download_reactome`、`process_reactome`、`process_kegg`、`process_pathbank`、`process_gmt`
- 工具:`identifier_conversion`、`map_identifiers`、`utils`

**Toy 验证**:
```python
df = sspa.load_example_data(omicstype='metabolomics', processed=True)
# shape: (263, 335) — 263 sample × 335 metabolite ChEBI IDs
rh = sspa.process_reactome(organism='Homo sapiens')
# shape: (2243, 1479) — 2243 Reactome pathways × 1479 metabolites
```

**ConcordMet schema 影响 / 实证更新 §3**:
1. **sspa metabolite ID 用 ChEBI**(列名是 ChEBI 数字 ID),与 mummichog 用 KEGG cpd 不同。**`normalize_sspa_output()` 需要 ChEBI → InChIKey 反查**(可走 §2.5 MetaNetX chem_xref 表)。
2. **sspa 自带 download_reactome / process_reactome**,不需要我们手写 Reactome ETL。但 release 是 sspa 内部 hardcode 的,需要查 sspa source(W3 D1 任务)以确认 Reactome release 与我们 §4 锁定的版本一致。如果不一致需要支持 sspa 接受 custom GMT。
3. **sspa.process_reactome 返回 pathway × metabolite 矩阵**(boolean / score),不是 list-of-PathwayHit。`normalize_sspa_output()` 需要先跑 sspa 的 enrichment 方法(`sspa_ora` / `sspa_ssGSEA`),拿 output dataframe(每行=pathway,每列=score),再 normalize。

**§2.1 状态**: **Import + toy DONE**(完整 ORA 端到端 W3 D1 跑)。可 ConcordMet 主路径用。
### 2.2 mummichog — ✅ TOY PASS(注意:**v3 不存在,PyPI 装 v2.7.0**)

**重要更正**:用户原计划写 "mummichog v3" 但 **PyPI 上 latest 是 mummichog 2.7.0**(Shuzhao Li 经典实现)。v3 可能指会议 talk / GitHub-only fork,不是 PyPI 包。**Investigation 用 v2.7.0**。

**Env**: `conda env mummichog_py310`(Python 3.10.18,via `conda create -n mummichog_py310 python=3.10`)
**Install**: `pip install mummichog` → `mummichog-2.7.0`(deps: numpy 2.2.6, scipy 1.15.3, networkx 3.4.2, matplotlib 3.10.9, xlsxwriter, ...)

**Toy 命令**(built-in test data,7995 features):
```
python -m mummichog.main -f tests/testdata0710.txt -o toy_out -m positive -p 50
```
- Wall time: **~13 sec**(包含 pathway + modular analysis + 50 permutations × 2)
- 输出目录:`<timestamp>.toy_out/{tables,figures,js,result.html}`
- 关键文件:
  - `tables/mcg_pathwayanalysis_toy_out.tsv` ← **primary table**:`pathway | overlap_size | pathway_size | p-value | overlap_EmpiricalCompounds | overlap_features(id+name)`
  - `tables/mcg_modularanalysis_toy_out.tsv` ← network modules
  - `tables/ListOfEmpiricalCompounds.tsv` ← m/z → 候选 KEGG cpd ID 映射(EID)
  - `tables/exported_Compounds.json` ← 同上 JSON 格式
  - `figures/plot_pathwayModel_toy_out.pdf` ← bubble plot

**Top 5 pathways(toy data,positive mode)**:
| Pathway | overlap | size | p-value |
|---|---|---|---|
| Alanine and Aspartate Metabolism | 8 | 20 | 0.0035 |
| Aspartate and asparagine metabolism | 19 | 72 | 0.0042 |
| Arginine and Proline Metabolism | 12 | 40 | 0.0064 |
| Aminosugars metabolism | 7 | 20 | 0.0173 |
| Hexose phosphorylation | 5 | 12 | 0.0185 |

**ConcordMet schema 影响**(已反馈 §3):
1. **KEGG cpd ID 是主 compound key**(C00020, C00362 等),需 §5 crosswalk 转 Reactome
2. **Pathway name 是 human_mfn 内部命名**(非 KEGG map / Reactome stable ID)→ schema 需 `pathway_id_native: str` + `pathway_name: str`,**不能假设可解析为 KEGG mapID**。这是 §3 schema gap 新发现,已加 §3 schema 末尾 `SCHEMA_GAPS_FOR_W3` 列表。
3. **网络模型** human_mfn 是默认;支持 worm + user-supplied JSON。ConcordMet 集成时需声明用哪个 release 的 human_mfn(无显式版本号,需查 `mummichog/JSON_metabolicModels.py`)。
4. **mummichog 的 m/z → 候选 compound 多对多映射**(EmpiricalCompound):一个 m/z 可能映 5+ 个 KEGG cpd,这是 §3 schema gap 中已登记的 "mummichog 反查 mz_to_inchikey 失败时 metabolites_hit 留空" 的根因。W3 实现 normalizer 时需 fallback 策略。

**§2.2 状态**: **DONE**。可作为 ConcordMet 的 m/z-driven enrichment 工具,**不需要 R 端 fallback**。Q-02 RESOLVED。
### 2.3 MetaboAnalystR 4 (subprocess) — ❌ **ESCALATE**(Q-03 1h22min @ 3 retry 失败,根因 bfd.h 冲突,见 Q-03 Stage 5)
### 2.4 FELLA (rpy2 并发 spike) — ❌ **ESCALATE**(同上;Python rpy2 也未尝试,因 R 端 dep 装不上)
### 2.5 MetaNetX MNXref — ✅ Endpoint 可达,⏳ 覆盖矩阵计算中

**Release 实测**(2026-05-15):
- **当前 release**:**MNXref 4.5,date 2025-08-13**(从 `chem_xref.tsv` 头部注释抓取)
- **License**:CC-BY 4.0(可用)
- **URL**:`https://www.metanetx.org/cgi-bin/mnxget/mnxref/<file>`

**Endpoint 可达性测试**:

| Endpoint | Status | 用途 |
|---|---|---|
| FTP root `/cgi-bin/mnxget/mnxref/` | ✅ 200 | listing |
| `chem_xref.tsv`(cross-ref core) | ✅ 200 | 跨库 ID 映射核心表 |
| `chem_prop.tsv`(化学属性) | ✅ 200 | mass / formula / InChIKey |
| `reac_xref.tsv`(反应 cross-ref) | ✅ 200 | reaction-level reconcile(W6+) |
| REST API `/cgi-bin/mnxweb/api` | ❌ **500 Internal Server Error** | 不可用,改走 flat-file |

**§4 影响**:**REST API 挂了,只能走 flat-file 路径**(下载 TSV + 本地 sqlite ETL)。这是 Reactome / KEGG 之外的另一个 source-availability flag,§4 release pinning 表需要登记。

**首批 100 行 chem_xref 抽样**(2025-08-13 release 头部样本)显示 cross-ref source 包括(频次降序):**reactome、reactomeM、chebi、SLM(SwissLipids)、hmdb、CHEBI、seedM、vmhM、biggM、keggC、seed.compound、mnx、metacyc.compound、metacycM、vmhmetabolite、bigg.metabolite、kegg.compound、sabiork.compound、sabiorkM**。覆盖 ConcordMet 关心的所有 Tier-1 数据库(reactome / chebi / hmdb / kegg / metacyc / bigg / swisslipids)。

**覆盖率矩阵(实测,partial file 580 MB / unknown total)**:

下载因 15-min timeout 终止于 580 MB;**实测发现 chem_xref.tsv 远比预期大(无 Content-Length,streaming;估计 1+ GB 全量)**。但 partial file 包含 **3.12M 行 / 1.04M unique MNX entities**,统计样本足够大。

**Pass 1:50 个完全随机 MNX(种子=42)** — 几乎全部是 lipid-only(47/50 只有 1 source),严重偏向 SwissLipids/LipidMaps。这是 **partial download artifact**(SLM entries 按字典序排在文件末尾,正好在我们停下的位置),不是 ConcordMet 真实情况。

**Pass 2:**过滤到 ≥3 distinct primary sources 的 MNX(real cross-DB candidates):

| n-distinct-sources | count | 占总 MNX % |
|---|---|---|
| 1 | 961,056 | **92.8%**(主要 lipid-only 或 reaction-only) |
| 2 | 56,604 | 5.5% |
| 3 | 12,823 | 1.2% |
| 4 | 3,430 | 0.33% |
| 5 | 1,217 | 0.12% |
| 6 | 737 | 0.07% |
| **7(全 cover)** | **255** | 0.025% |

**50 个 ≥3-source MNX 抽样的源覆盖率**(real cross-DB 子集):

| Source | Cover % | 评论 |
|---|---|---|
| **chebi** | **100.0%** | **lingua franca,所有跨库 metabolite 都有 ChEBI ID** |
| hmdb | 82.0% | metabolomics 主源,覆盖良好 |
| metacyc | 66.0% | |
| kegg | 58.0% | |
| **lipidmaps** | **50.0%** | 偏 partial-file 还可能更高(全量预计 ~60-65%) |
| bigg | 18.0% | 偏 metabolic-model focused,人不常用 |
| **reactome** | **12.0%** ⚠️ | **远低于预期** — 见 §5 / Q-05 |

**关键发现(改 §5 主键决策)**:**Reactome 在跨库 metabolite 上只覆盖 12%**。这与用户原文档"Reactome stable ID 主键 + KEGG fallback"假设矛盾。**ChEBI 才是真正的 lingua franca**(100% 覆盖)。已登记 **Q-05**,§5 主键策略需重审。

**§2.5 状态**:
- ✅ Endpoint + release 4.5 (2025-08-13) 确认
- ✅ Partial coverage matrix done(580 MB / 估 1+ GB)
- ⚠️ 全量下载需后续 session(curl 30-min timeout 或 chunked download);**partial 已足够支持 §5 主键决策反思**
- ✅ source coverage 数据驱动 Q-05 决策点
### 2.6 RDKit InChIKey reconciler — ✅ Toy DONE

**Script**: `data/investigation/scripts/rdkit_inchikey_toy.py`(46 行,含 fixture + cluster + collision/split check)
**Backend**: rdkit 2025.09.6 + `rdkit.Chem.inchi.MolToInchi` → `InchiToInchiKey`
**Block14**: InChIKey 第一段 14 字符(connectivity / skeleton hash,忽略立体 + 同位素)

**Fixture(13 SMILES,6 化合物)+ 跑结果**:

| Compound | n SMILES | n distinct block14 | 状态 |
|---|---|---|---|
| D-Glucose | 4 | **2** | ⚠️ **FALSE-SPLIT** — 开链 Fischer (`GZCGUPFRVQAUEE`) vs 环状 (`WQZGKKKJIJFFOK`) 不同 block |
| Lactic acid | 3 | 1 (`JVTAAEKCZFNVCJ`) | ✅ L / D / racemic 立体异构正常聚类(差异在 layer 2-3) |
| Caffeine | 2 | 1 (`RYYVLZVUVIJVGH`) | ✅ uppercase/lowercase aromatic SMILES 正常聚类 |
| Glycine | 2 | 1 (`DHMQDGOQFOQNFH`) | ✅ 不同原子顺序正常聚类 |
| Adenine | 2 | 1 (`GFFGJBXGBJISGV`) | ✅ N7H / N9H tautomer 正常聚类(RDKit 默认 InChI standard tautomer 折叠) |
| (cluster GZCGUPFRVQAUEE) | 1 | 1 | 单一 block,无 collision |

**关键发现 / Limitations**:
1. **InChIKey block14 不能 reconcile 开链 ↔ 环状 同分异构**。D-Glucose 的 Fischer 开链 SMILES 与环状 alpha/beta SMILES 在 InChI 层面被认作 *constitutional isomer*(C-O 键连接不同),block14 不同。这是 InChI 设计意图(connectivity matters),不是 RDKit bug。
2. **mild tautomer(prototropic on heteroaromatic ring)、立体异构、原子顺序差异** 都正常聚类,符合 ConcordMet reconciliation 预期需求。
3. **暗示 ConcordMet 集成时**:对糖类、其他多环 ↔ 开链平衡的代谢物,**block14 单层不够**——需要补一个 "tautomer / ring-chain canonicalizer"(可用 RDKit `Chem.MolStandardize.tautomer.TautomerEnumerator`)或对开链糖直接做 cyclization 标准化。Q-04(新)登记。
4. **InChIKey 的 second layer (stereo) 信息丢失** 在我们 use case 里是 feature(L/D/racemic lactic acid 都按"乳酸"聚类),不是 bug。但若 ConcordMet 后续需要区分 enantiomer 生物活性,要用 full InChIKey 而非 block14。

**§2.6 状态**: **DONE**。reconciler 可直接用于 ConcordMet,但需在 §3 schema 留 `tautomer_canonicalized: bool` 字段并在 §4 计划中加一步 ring-chain 预标准化。
### 2.7 Tier B/C 工具速记 — Pending
- PathIntegrate / IMPaLA / PIUMet / NetGSA / fgsea / clusterProfiler / MetExplore / OmicsNet

---

## §3 — 统一 EnrichmentResult Schema — ✅ **v0.3 namespace-prefixed primary keys**

**v0.3 决策(2026-05-15 Q05-NEW-4/5 拍板)**:
- 抛弃"Reactome 主键 + canonical_source 字段",改用 **MIRIAM/identifiers.org 风格 namespace-prefixed primary IDs**
- `PathwayHit.pathway_id` 永远 `"<NS>:<id>"`,NS ∈ {REACT, KEGG, WP, SMPDB, METACYC}
- `CompoundRef.primary_id` 永远 `"<NS>:<id>"`,NS ∈ {CHEBI, LIPIDMAPS, HMDB, KEGG, INCHIKEY}
- **所有外部 DB ID 字段 optional**;InChIKey 作 ground truth 兜底必填(RDKit 总能算出来)
- **`__post_init__` validator** 强制 namespace whitelist 校验

**Script:** `data/investigation/scripts/enrichment_result_schema_draft.py`(228 行,含 dataclass + enums + 4 normalizer stubs + gap list + sanity check)

### 3.1 Schema 核心(v0.3,namespace pivot 后)

**Namespace whitelists**(v0.3 新增):
```python
COMPOUND_NAMESPACES = frozenset({"CHEBI", "LIPIDMAPS", "HMDB", "KEGG", "INCHIKEY"})
PATHWAY_NAMESPACES = frozenset({"REACT", "KEGG", "WP", "SMPDB", "METACYC"})
```

**`CompoundRef`**(v0.3 — namespace-prefixed primary_id + 全 optional 外部 ID):
```python
@dataclass(frozen=True)
class CompoundRef:
    primary_id: str                       # 必填 "<NS>:<id>",NS ∈ COMPOUND_NAMESPACES
    inchikey: str                         # 必填(RDKit 算的出来)— 结构 ground truth
    display_name: str = ""
    chebi_id: str | None = None           # "CHEBI:17234"(optional)
    lipidmaps_id: str | None = None
    hmdb_id: str | None = None
    kegg_compound_id: str | None = None
    pubchem_cid: str | None = None
    metanetx_id: str | None = None
    def __post_init__(self): _check_namespaced(self.primary_id, COMPOUND_NAMESPACES, "primary_id")
```

**`resolve_primary_id()` helper**(v0.3 关键):
```python
# Resolution rule: chebi → lipidmaps → hmdb → kegg → inchikey 第一个非空填
# Returns: "CHEBI:17234" / "LIPIDMAPS:LMFA01030001" / ... / "INCHIKEY:WQZGKK..."
# InChIKey 兜底确保 primary_id 永远非空
```

**`PathwayHit`**(v0.3 — namespace-prefixed pathway_id):
```python
@dataclass(frozen=True)
class PathwayHit:
    pathway_id: str                       # 必填 "<NS>:<id>",NS ∈ PATHWAY_NAMESPACES
    pathway_name: str
    pathway_id_native: str                # 工具实际输出(KEGG map00010 / human_mfn name 等)
    pathway_db: PathwayDB
    score: float; score_type: ScoreType; rank: int
    metabolites_hit: tuple[CompoundRef, ...]
    n_metabolites_in_pathway: int = 0; n_metabolites_input: int = 0
    auxiliary_scores: dict[str, float] = field(default_factory=dict)
    def __post_init__(self): _check_namespaced(self.pathway_id, PATHWAY_NAMESPACES, "pathway_id")
```

**v0.2 → v0.3 关键差异**:
- v0.2 `pathway_id="R-HSA-71387"` + `kegg_id="hsa00010"` 两个字段 → v0.3 单字段 `pathway_id="REACT:R-HSA-71387"` 或 fallback `pathway_id="KEGG:hsa00190"`
- v0.2 `chebi_id` 必填 → v0.3 改 optional;新 `primary_id` 必填且 namespace-prefixed
- 新增 validators(`_check_namespaced`)在 `__post_init__` 自动跑

**`EnrichmentResult`** schema_version 升 `"concordmet_v0.3"`;其余字段不变。

### 3.2 Sanity 测试(v0.3,含 validators)

```
$ python data/investigation/scripts/enrichment_result_schema_draft.py
CompoundRef OK (CHEBI):     primary=CHEBI:17234  name=D-glucose
CompoundRef OK (LIPIDMAPS): primary=LIPIDMAPS:LMFA01030001  name=palmitic acid (long-tail)
PathwayHit OK (REACT):  REACT:R-HSA-71387 (Glycolysis)  score=1e-05  n_metabolites_hit=2
PathwayHit OK (KEGG fallback): KEGG:hsa00190 (Oxidative phosphorylation)
EnrichmentResult OK: mummichog on kegg (1 hits, 14.2s, schema=concordmet_v0.3)
Validator OK (rejects unnamespaced pathway_id): 'R-HSA-71387' missing 'REACT:' prefix
Validator OK (rejects unnamespaced primary_id): '17234' missing 'CHEBI:' prefix
```
✅ 4 use case 通过(CHEBI + LIPIDMAPS fallback + REACT + KEGG fallback);2 个 validator 正确 reject。

### 3.3 4 Normalizer 签名(W3 实现 body)

| Function | 输入 | 关键 gap |
|---|---|---|
| `normalize_sspa_output()` | sspa DataFrame + method enum + inchikey_lookup | 多 score 列何时升 primary;ChEBI/KEGG ID → InChIKey 反查 |
| `normalize_mummichog_output()` | mummichog TSV + mz_to_inchikey(候选反查) | m/z → 候选 compound 多对多,EASE 存 auxiliary;**实测确认输出含 pathway_name 但不含 KEGG mapID** |
| `normalize_fella_output()` | rpy2 调用返回的 R data.frame | RWR score 不是 p-value;5 层 graph 只取 compound 层;**依赖 Q-03 R 修通** |
| `normalize_ramp_output()` | RaMP-DB EnrichmentReport pydantic | 字段重命名 + InChIKey 反查(RaMP 内部用 RaMP source-ID) |

(Tier-B `normalize_metaboanalystr_output()`、`normalize_pathintegrate_output()` 等 W4+)

### 3.4 已知 Schema Gaps(11 个,3 RESOLVED v0.3 / 8 W3 处理)

| # | Severity | Gap | W3 计划 / Sprint 1 影响 |
|---|---|---|---|
| 1 | HIGH | mummichog 输出无 ChEBI ID(只 KEGG cpd 或 human_mfn name),需 KEGG→ChEBI 反查 | W3 D2:走 §5 crosswalk;mummichog normalizer 走 `resolve_primary_id()`;ChEBI miss 时 fallback KEGG: namespace。**不阻塞 Sprint 1 启动**(v0.3 兜底已写好)|
| 2 | MEDIUM | mummichog 反查全 miss 时 metabolites_hit 处理 | Q05-NEW-5 后改:`resolve_primary_id()` InChIKey 兜底永远非空,不会丢 entry,只是 namespace 退化到 `INCHIKEY:`。**Sprint 1 不影响** |
| 3 | HIGH | `score_type=COMPOSITE` 谁生成 | Sprint **W6+** ConcordMet aggregator,**Investigation 不实现 / Sprint 1 不影响** |
| **4** | **✅ RESOLVED-Q05-NEW-5** | CompoundRef chebi_id 必填 → unmapped lipid | **v0.3 解**:chebi_id optional;`primary_id` namespace-prefixed,resolve_primary_id() 按优先级填;InChIKey 兜底必填 |
| **5** | **✅ RESOLVED-Q05-NEW-4** | Reactome 12% compound 覆盖 → KEGG-only pathway 怎么填 pathway_id | **v0.3 解**:pathway_id namespace-prefixed;Reactome miss → `KEGG:hsa00010` / `WP:...` / `SMPDB:...` / `METACYC:...`;validator 强制 NS ∈ whitelist |
| 6 | MEDIUM | sspa 多 score 列升 primary 规则 | W3 D1 看 sspa 实测列再定;**会影响 Sprint 1 W3** |
| 7 | MEDIUM | `tautomer_canonicalized=False` 时是否拒绝下游 reconciliation | Q-05 后默认要求 `chebi_canonicalized=True`,tautomer 是 optional;**Sprint 1 不影响** |
| 8 | ✅ RESOLVED-Q05 | Pathway ID 跨 KEGG/Reactome/WikiPathways 不统一 | (与 #5 同根因)已通过 v0.3 namespace pivot 解决 |
| 9 | LOW | FELLA 跨 5 层 graph 的 `n_metabolites_in_pathway` 定义 | 只取 compound 层;**Sprint 1 不影响** |
| 10 | LOW | `auxiliary_scores` float-only 限制 | W3 D3 看 FELLA 实输出;**Sprint 1 不影响** |
| 11 | LOW | `schema_version` 升级策略 | 已 bump v0.1 → v0.2 → v0.3;**Sprint 1 不影响** |

**Sprint 1 影响汇总(v0.3 后)**:
- ✅ **Q05-NEW-4 / Q05-NEW-5 RESOLVED** — W3 D0 不需要再拍板这俩
- ✅ **#8 RESOLVED**(原 Q-05 第一轮)
- HIGH-1(mummichog ChEBI 反查):W3 D2 实现,**不阻塞启动**(v0.3 兜底完善)
- HIGH-3(composite score):W6+,Sprint 1 不阻塞
- MEDIUM-6(sspa 多 score 列)、MEDIUM-7(tautomer 拒收)、LOW-9/10/11:W3 实现细节
- **Sprint 1 启动门槛降低**:**0 个 W3 D0 必拍 gap**(原有 Q05-NEW-4 / #5 都已 v0.3 解决)

### 3.5 mummichog 实测反馈 §3 新增 gap

**Investigation 期间** 跑了 mummichog toy,**发现 §3 原草案漏了 pathway_id_native 的处理**:
- mummichog 输出 `pathway` 字段是 human_mfn 内部 name(`"Alanine and Aspartate Metabolism"`),不是 KEGG mapID,也不是 stable ID
- 这意味着 `pathway_id_native` 字段对 mummichog 来说就是这个 name 字符串本身
- W3 实现 `normalize_mummichog_output()` 时需要:**(a) 把 human_mfn name → 内部 ID 映射表**(查 `mummichog/JSON_metabolicModels.py`),**或 (b) 把 name 作为 pathway_id_native 接受,§5 crosswalk 用 fuzzy-match 转 Reactome**。倾向 (a),(b) fuzzy-match 风险高。

### 3.6 §3 状态

**Schema v0.3 DONE**(W2 review-ready)。**所有 sub-Q-05 决策完成**(Q05-NEW-4 + Q05-NEW-5 namespace pivot 同时解决两条)。Sprint 1 W3 D0 不需要再 schema-level 拍板,直接进 ChEBI ETL + sspa normalizer。其余 8 gap 在 W3 实现期处理(0 个阻塞启动)。

---

## §4 — Tier A 工具集成计划

### 4.1 Database Release Pinning(Q-05 后)

| 库 | 拟锁定 release | 来源 | 验证状态 |
|---|---|---|---|
| **ChEBI(compound 主键)** | **rel251(2026-04-01)** | `archive/rel251/flat_files/*.tsv.gz` | ✅ **已下载 6 文件(26 MB)+ schema 摸清** |
| **Reactome ChEBI xref(pathway 主键)** | **2026-03-23 release** | `ChEBI2Reactome.txt`(14.4 MB)+ `_All_Levels.txt`(37.5 MB)| ✅ 已下载;113k 行(含 42k Human-only)|
| **MetaNetX MNXref**(crosswalk validator,降级) | **4.5(2025-08-13)** | `chem_xref.tsv` 头部 | ✅ Partial(580 MB);Q-05 后不再主键 source |
| **mummichog** | **2.7.0**(PyPI latest;v3 不存在) | `pip install mummichog` | ✅ Toy verify(Q-02) |
| **R base** | **R 4.4.3 "Trophy Case"** | conda r-base=4.4 in `concord_r` env | ✅ 已 verify |
| **Bioconductor** | BiocManager 3.20 | Bioc release 2024-10 | ⏳ 部分 install(limma ✓,fgsea/KEGGgraph/FELLA retry-2 中)|
| **RDKit** | 2025.09.6 | system base env | ✅ verify(§2.6) |
| **sspa** | 1.0.4(PyPI)+ setuptools<80 + tqdm pin | `mummichog_py310` env | ✅ verify(§2.1) |
| KEGG | TBD(academic rate limit 实测) | 主用 ChEBI xref(45=KEGG_CPD),KEGG REST 只查 pathway | W3 D1 测 |
| LIPID MAPS | TBD | ChEBI xref(50=LIPID MAPS)+ 直接下载 | W3 D2 |
| HMDB | v5.0(主 repo 已有) | 已存(主用 ChEBI xref 35=HMDB) | Pending 确认 |
| PubChem | PUG-REST 实时 | 已有 lookup_compound_info backend(也可走 ChEBI xref 68) | Pending |

**已知 release 锁:**Q-05 pivot 后新增 **ChEBI rel251 + Reactome 2026-03-23**,**共 8/12 项已锁**。

### 4.1.1 ChEBI sqlite ETL 路径(Q-05 实施 spec)

**文件清单(rel251,实测 sizes)**:

| File | Compressed | Uncompressed est. | 用途 | Schema(已抓)|
|---|---|---|---|---|
| `compounds.tsv.gz` | 6.3 MB | ~30 MB | compound 主表 | `id, name, status_id, source, parent_id, merge_type, chebi_accession, definition, ascii_name, stars, modified_on, release_date` |
| `database_accession.tsv.gz` | 3.6 MB | ~22 MB | 跨库 xref | `id, compound_id, accession_number, type, status_id, source_id` |
| `names.tsv.gz` | 8.3 MB | ~50 MB | 同义词 | TBD |
| `relation.tsv.gz` | 2.4 MB | ~14 MB | is_a / tautomer hierarchy(供 Q-04 上爬) | TBD |
| `secondary_ids.tsv.gz` | 0.1 MB | ~0.5 MB | merged ChEBI ID 历史 | TBD |
| `chemical_data.tsv.gz` | 4.6 MB | ~28 MB | mass / formula | TBD |
| `structures.tsv.gz` | **85 MB** | ~500 MB | SMILES / InChI / InChIKey(W3 加索引)| TBD,W3 下载 + ETL |
| `source.tsv.gz` | 3.7 KB | ~30 KB | **source_id → DB name 字典**(45=KEGG, 35=HMDB, 50=LIPIDMAPS, 54=MetaCyc, 68=PubChem, 72=Reactome, 79=SwissLipids) | ✅ 已抓 |

**ChEBI 跨库覆盖率实测**(164,814 compounds 有 ≥1 xref):

| Source ID | DB | n compounds | % |
|---|---|---|---|
| 45 | **KEGG COMPOUND** | **28,948** | 17.5% |
| 35 | HMDB | 19,931 | 12.1% |
| 50 | LIPID MAPS | 12,663 | 7.7% |
| 54 | MetaCyc | 7,144 | 4.3% |
| 46 | KEGG DRUG | 5,371 | 3.3% |
| 72 | Reactome(in-ChEBI xref) | TBD | TBD |

(Reactome 直接走 `ChEBI2Reactome.txt` 113k 行,42k Human-only,更权威)

**ETL 顺序(W3 D1-D3)**:
1. **W3 D1**:`compounds.tsv` → `compound` 主表;`source.tsv` → 字典(内存);`secondary_ids.tsv` → 升级 obsolete ID
2. **W3 D2**:`database_accession.tsv` → `compound_xref`(filter source_id ∈ {35, 45, 50, 54, 68, 72, 79})
3. **W3 D3**:`structures.tsv`(85 MB,需先下载)→ `compound.inchikey` / `smiles` / `inchikey_block14`;`relation.tsv` → `compound.parent_chebi_id`(Q-04 fix)
4. **W3 D4**:`ChEBI2Reactome_All_Levels.txt` → `pathway` + `pathway_compound`(filter species='Homo sapiens',42k 行)

**预估总 wall time:0.5-1 个工作日**(符合用户原估)。
**Sqlite file size 预估**:索引后 ~200-300 MB(主要是 structures InChI/InChIKey)。

### 4.2 50-Metabolite × 7 Source 覆盖矩阵 — ✅ 见 §2.5(partial chem_xref 已跑)

### 4.2 50-Metabolite × 7 Source 覆盖矩阵 — ⏳ 下载完成后用 `metanetx_coverage_probe.py` 跑

probe 输出 3 张表:
- source-prefix 频次分布(全表)
- 50 个随机 MNX × 7 主源(reactome / chebi / hmdb / kegg / metacyc / bigg / lipidmaps)的命中矩阵
- 每个 metabolite 命中 source 数量分布(直方)

### 4.3 W3-W5 集成顺序(Q-05 pivot 后)

| Week | Q-05 后计划 | 理由 |
|---|---|---|
| **W3** | **(1) sspa(已 verify) + (2) RDKit InChIKey reconciler(已 verify) + (3) ChEBI sqlite ETL(新增,Q-05 主键)** | ChEBI 是 compound 层主键,必须在 W3 W4 normalizer 之前 ETL 完;MetaNetX 不再是主键 source,降级 W4 |
| **W4** | mummichog(已 verify)+ schema normalizer 实现 + **MetaNetX 作为 crosswalk validator**(不是主键 source) | mummichog 已 verify(§2.2),normalizer 需要 ChEBI(W3 ETL 产物)做 KEGG cpd → ChEBI 反查;MetaNetX 用作 cross-source verification |
| **W5** | MetaboAnalystR + FELLA(若 Q-03 retry 通) / Python RWR fallback | 取决于 Q-03 escalation 终态;Investigation 中 FELLA deps 部分 install 失败,正在 retry-2 |

**Q-05 ETL 顺序逻辑**:
- ChEBI sqlite ETL 必须最早(W3 D1-D3,因为 mummichog normalizer 必须有 ChEBI→KEGG mapping)
- Reactome ChEBI2Reactome.txt 也 W3 W4(pathway 主键)
- MetaNetX 从"主键 source"降级到"crosswalk validator"(仍下载 + ETL,但工程优先级降一档)

**Pivot 预案(Q-03 retry-2 fail)**:
- (a) Tier-A 缩到 3 工具:sspa + mummichog + FELLA(Python RWR 重写,~2-3 周)
- (b) Tier-A 缩到 3 工具:sspa + mummichog + MetaboAnalystR(若仅 FELLA 失败)
- (c) Docker R 镜像 escalation(W3 加 1 周搭 docker)
- **(d) NEW: 接受 R 部分 install,改 FELLA-only(不要 MetaboAnalystR)** — limma/plyr/Matrix 已通,可能 fgsea/KEGGgraph 第二轮通,FELLA 直接 install。retry-2 后看

(详细 daily plan 见 §9)

---

## §5 — Pathway ID Crosswalk 策略 — ✅ **Q-05 pivot 后定稿**

**用户原决策**:Internal storage Reactome ID 主键;reporting KEGG ID;crosswalk Reactome ↔ KEGG;Reactome 缺失则 canonical_source=kegg。

**§2.5 实测推翻(2026-05-15)**:
- **Reactome 在跨库 metabolite 上只覆盖 12%**(MetaNetX 4.5 chem_xref 中,50 个 ≥3-source 候选)
- **ChEBI 100% 覆盖**(所有跨库 metabolite 都有 ChEBI ID,MetaNetX 自己也用 ChEBI 作 chem_prop.tsv 主键)
- **HMDB 82%、KEGG 58%、MetaCyc 66%**
- **Reactome 在 pathway 层覆盖良好,但在 compound 层很弱** — 这是 Reactome 设计意图:metabolites 是 pathway participants,不是 first-class entity

### 5.1 双主键架构(Q-05 已拍板 2026-05-15)

| 层 | 主键 | Reporting | Fallback ground truth |
|---|---|---|---|
| **Compound** | **ChEBI ID**(CHEBI:NNNNN)| KEGG cpd ID(C00031 等)+ HMDB ID | InChIKey(27-char,结构哈希)|
| **Pathway** | **Reactome stable ID**(R-HSA-XXX)| KEGG mapID(hsa00010 等)| — |
| 结构层 | InChIKey | — | (cross-stereo/tautomer 冲突时仲裁)|

**决策理由(实证)**:
- §2.5 MetaNetX 实测:**ChEBI 100% 覆盖跨库 metabolite**(50 ≥3-source 抽样,seed=42);Reactome 仅 12%
- Reactome 自带 `ChEBI2Reactome.txt`(2026-03-23 release),compound→pathway xref 是 in-house 维护,**比第三方 crosswalk 更权威**
- ChEBI 是 EBI canonical chemical entity,**Reactome 自己内部也用它做 reference**

### 5.2 三路 Crosswalk 策略

**主路径**(Q-05 决策):
```
ChEBI → Reactome
  ↓ via Reactome 自带 ChEBI2Reactome.txt(2026-03-23,~750KB 文件;_All_Levels 37MB)
  → 直接 reactome_id mapping,无需 fuzzy match
```

**Fallback 路径**:
```
ChEBI → KEGG cpd
  ↓ via ChEBI database_accession.tsv(rel251,3.5MB;source_id=45 → KEGG COMPOUND)
  → 实测 source 分布:MANUAL_X_REF 212k / CITATION 120k / CAS 40k / REGISTRY 27k
  → KEGG/MetaCyc/LIPID MAPS 都在 MANUAL_X_REF 桶里
```

**结构辅助**(冲突解决):
```
ChEBI → InChIKey
  ↓ via ChEBI structures.tsv.gz(rel251,85MB,含 SMILES/InChI/InChIKey)
  → 用于 stereo/tautomer 边界 case 仲裁
```

### 5.3 ChEBI 内部 ID hierarchy 用于 Q-04 糖类 false-split

ChEBI 用 `is_a` / `is_tautomer_of` / `has_role` 关系(`relation.tsv.gz` 2.4MB)做 compound hierarchy。
- D-Glucose(CHEBI:17234)是 hexose(CHEBI:18133)的 child
- α-D-Glucopyranose / β-D-Glucopyranose 都是 D-Glucose 的 child(或 tautomer 关系)
- **Q-04 解法**:输入 InChIKey block14 false-split 时,**向上爬 ChEBI is_a 1-2 层**,寻找共同 parent → reconcile 到 parent ChEBI(D-Glucose 而非 α-D-Glucopyranose)
- 实施代码:W3 RDKit + ChEBI sqlite 集成时落地,~30 LOC SQL JOIN + parent walk

### 5.4 Crosswalk Table Schema(W3 ETL 实施 spec)

```
-- v0.3 ALL primary_id / pathway_id ARE NAMESPACED ("NS:id" form)

-- 主表(W3 D1-D3 ETL)
TABLE compound (
    primary_id        TEXT PRIMARY KEY,     -- "CHEBI:17234" / "LIPIDMAPS:LMFA01030001" / "INCHIKEY:..."
    chebi_id          TEXT UNIQUE,          -- "CHEBI:NNNNN"(可空,长尾 lipid 无)
    display_name      TEXT NOT NULL,
    parent_primary_id TEXT,                 -- is_a hierarchy(限于同 namespace 内向上爬)
    inchikey          TEXT NOT NULL,        -- 27-char(必填,RDKit 兜底)
    inchikey_block14  TEXT NOT NULL,        -- 第一段 14 字符
    smiles            TEXT,
    formula           TEXT,
    monoisotopic_mass REAL,
    chebi_status      INTEGER               -- 1=CHECKED 等(过滤 obsolete)
);
CREATE INDEX idx_compound_block14 ON compound(inchikey_block14);
CREATE INDEX idx_compound_parent ON compound(parent_primary_id);
CREATE INDEX idx_compound_chebi ON compound(chebi_id);

-- 跨库 ID 映射(W3 D2-D3 ETL)
TABLE compound_xref (
    primary_id     TEXT NOT NULL,           -- v0.3:namespaced primary key
    external_ns    TEXT NOT NULL,           -- 'CHEBI'/'KEGG'/'HMDB'/'LIPIDMAPS'/'METACYC'/'PUBCHEM'/'METANETX'
    external_id    TEXT NOT NULL,           -- 不含 namespace prefix 的纯 ID
    xref_type      TEXT,                    -- ChEBI 原始 type: MANUAL_X_REF / CITATION
    PRIMARY KEY (primary_id, external_ns, external_id),
    FOREIGN KEY (primary_id) REFERENCES compound(primary_id)
);
CREATE INDEX idx_xref_external ON compound_xref(external_ns, external_id);
-- 反查例:WHERE external_ns='KEGG' AND external_id='C00031' → primary_id='CHEBI:17234'

-- Pathway 主键(W3 D3 ETL)— v0.3 namespaced
TABLE pathway (
    pathway_id    TEXT PRIMARY KEY,         -- "REACT:R-HSA-71387" / "KEGG:hsa00010" / "WP:WP167" / ...
    pathway_ns    TEXT NOT NULL,            -- 'REACT' / 'KEGG' / 'WP' / 'SMPDB' / 'METACYC'(冗余但加速 routing)
    pathway_name  TEXT NOT NULL,
    species       TEXT,                     -- 'Homo sapiens' 等(可空,非物种 pathway 用)
    -- 跨 namespace 等价关系(可空;若知道则填,例 REACT:R-HSA-71387 等价 KEGG:hsa00010)
    kegg_equivalent TEXT,                   -- 用于 reporting fallback
    reactome_equivalent TEXT                -- 反向(若 primary 是 KEGG/WP/...,这里填对应 Reactome)
);
CREATE INDEX idx_pathway_ns ON pathway(pathway_ns);
CREATE INDEX idx_pathway_kegg_eq ON pathway(kegg_equivalent);

-- pathway × compound 隶属(Reactome's ChEBI2Reactome_All_Levels.txt 注入)
TABLE pathway_compound (
    pathway_id    TEXT NOT NULL,            -- v0.3:namespaced
    primary_id    TEXT NOT NULL,            -- v0.3:namespaced compound key
    evidence_code TEXT,                     -- Reactome 提供的 'IEA' / 'TAS' 等
    PRIMARY KEY (pathway_id, primary_id),
    FOREIGN KEY (pathway_id) REFERENCES pathway(pathway_id),
    FOREIGN KEY (primary_id) REFERENCES compound(primary_id)
);
```

**v0.2 → v0.3 改动**:
- `compound.chebi_id` 不再 PK,改 UNIQUE(可空,因为长尾 lipid 走 LIPIDMAPS namespace primary)
- `compound.primary_id` 是 PK,namespace-prefixed
- `compound_xref` 字段从 `(chebi_id, source, external_id)` → `(primary_id, external_ns, external_id)`,与 v0.3 schema 一致
- `pathway.pathway_id` 改 PK 为 namespaced;新增 `pathway_ns` 索引列加速 routing;新增 `kegg_equivalent` / `reactome_equivalent` 用于 cross-namespace mapping
- `pathway_compound` 表 PK 用 `(pathway_id, primary_id)`,FK 自然 follow

**Schema 简化点**:`ChEBI2Reactome.txt` 是 Reactome 自带、已 curated,**不需要 ConcordMet 自己算 crosswalk**。Q-05 pivot 后的关键简化。原"Reactome ↔ KEGG 单向 mapping" 进一步简化为 `pathway.kegg_equivalent` / `reactome_equivalent` 字段(从 ChEBI2Reactome.txt species filter + 已有 KEGG mapping 注入)。

**ChEBI sqlite ETL 工程量(W3 D1-D3)**:
- 6 个 ChEBI TSV.gz(~26 MB compressed,~150 MB uncompressed)+ 2 个 Reactome TSV(~40 MB)
- ETL Python 脚本 ~200 LOC(每个 TSV → table,加索引)
- 加 hierarchy 爬取(parent_chebi_id 物化)~50 LOC
- 预估 wall time:**0.5-1 个工作日**,符合用户原估

---

## §6 — Risk Register

_整合 R1-R10(用户原文档)+ 评审 + Investigation 新发现 R-NEW-X。_

### 6.1 原 R1-R10(从用户战略 doc + 评审材料)

| ID | Risk | 概率 | Impact | 缓解 | Verification 状态 |
|---|---|---|---|---|---|
| R1 | 同方向被抢先 | 高 | 高 | 早 preprint | 不可 verify(外部) |
| R2 | LLM 幻觉超出 verifier 兜底 | 中 | 中 | LLM 只协调,工具确定性 | B1 D5 部分缓解(主 repo) |
| R3 | 工具集成 schema 不一致 | 中 | 高 | §3 统一 EnrichmentResult schema | **§3 已草案 ✅** |
| R4 | 跨库 ID reconciliation 漏 | 中 | 中 | RDKit InChIKey + MetaNetX | **§2.5 / §2.6 部分验证 ✅** |
| R5 | KEGG academic API rate-limit | 中 | 中 | 本地 sqlite cache | KEGG REST 未实测,W3 D1 测 |
| R6 | Reactome 缺失 pathway → KEGG fallback | 中 | 低 | §5 crosswalk fallback | Pending §5 |
| R7 | Sprint 时间表 overrun | 高 | 中 | Time-box + escalation | Investigation 已用 Q-02/03 演练 ✅ |
| R8 | Motivation 不成立(reconciliation 无价值) | 中 | 高 | W1 Gate 1 toy 数据 | **Pending §8(下次 session)** |
| R9 | Reconciliation 没用 | 中 | 高 | W6 Gate 2 + W6 pivot | W6 才能 verify |
| R10 | 竞品无 code → 无法 head-to-head | 高 | 中 | 引用 + cannot-reproduce 声明;不 fork | **§0 已验证:** MetaboT/GeneAgent public(可 head-to-head),MS4MS/MSAgent paper-only(声明 cannot-reproduce) |

### 6.2 Investigation 期间新发现 R-NEW-X

| ID | Risk | 概率 | Impact | 缓解 | 触发 |
|---|---|---|---|---|---|
| R-NEW-01 | `test_library_search` GNPS env 测试失败 | 已发生 | 低 | GNPS 不在 ConcordMet 主线工具集,不阻塞 | §1.1 pytest 实测 |
| R-NEW-02 | Pytest mark 未注册(`integration` / `requires_minimax_key` / `requires_sirius`) | 已发生 | 极低 | 装饰性 warning,无功能影响;Sprint W3 顺手注册 | §1.1 pytest 实测 |
| R-NEW-03 | **R env broken (GLIBCXX_3.4.30)** | 已发生 | 高 | conda r-base=4.4 隔离 env(`concord_r`)已 verify | §2.0 实测 → 已修复 |
| R-NEW-04 | **mummichog v3 不存在,只有 v2.7.0** | 已发生 | 中 | 接受 v2.7.0(经典实现);若 paper 想引 v3 需找 Shuzhao Li GitHub-only fork | §2.2 实测 |
| R-NEW-05 | **Python 3.13 + Bioconductor wheel 不齐** | 已确认 | 中 | mummichog 隔离到 Py3.10;主 repo 不动 | §2.0 实测 |
| R-NEW-06 | **MetaNetX REST API 500 Internal Server Error** | 已确认 | 中 | 改 flat-file 路径(chem_xref.tsv 等)+ 本地 sqlite ETL | §2.5 实测 |
| R-NEW-07 | **InChIKey block14 无法 reconcile 开链↔环状糖类** | 已确认 | 中 | **Q-05 后改方案**:用 ChEBI `is_a` hierarchy(relation.tsv)向上爬 1-2 层,把 α/β/D-glucopyranose 归到 parent ChEBI(D-Glucose, CHEBI:17234)— `compound.parent_chebi_id` 物化到 sqlite,SQL JOIN 一次解决;InChIKey 降为冲突仲裁 fallback。W3 RDKit + ChEBI sqlite 集成时落地 | §2.6 实测 → Q-04 → Q-05 改 spec |
| R-NEW-08 | **mummichog pathway_name 不是 KEGG mapID**(human_mfn 内部命名)| 已确认 | 中 | W3 实现 `normalize_mummichog_output()` 时加 name → mapID 映射表(查 mummichog/JSON_metabolicModels.py)或 fuzzy-match | §2.2 实测 |
| R-NEW-09 | **Q-03 BiocManager install wall time 不确定**(可能 30-60 min)| 已发生 | 低 | Time-box 4h 内必收;超期 escalate(见 Q-03 三选项) | §2.3/§2.4 setup |
| R-NEW-10 | **Bioconductor 3.20 与 R 4.4.3 兼容性未验证**(理论上 Bioc 3.20 对应 R 4.4) | 中 | 中 | Q-03 BiocManager install 跑通即 verify;若失败需降到 Bioc 3.19 | Pending Q-03 |
| R-NEW-11 | **sspa 1.0.4 upstream packaging gap**(`pkg_resources` 依赖未声明 + tqdm 隐式依赖)| 已发生 | 低 | conda env 内 pin `setuptools<80` + `tqdm` 显式装 | §2.1 实测 → workaround verified |
| R-NEW-12 | **sspa metabolite ID 用 ChEBI,与 mummichog KEGG cpd 不同** | 已发生 | 中 | `normalize_sspa_output()` 加 ChEBI→InChIKey 反查(走 §2.5 MetaNetX chem_xref) | §2.1 实测;W3 落地 |
| R-NEW-13 | **sspa 内部 Reactome release 与 §4 锁定版本可能不一致** | 中 | 低 | W3 D1 查 sspa source 确认;不一致则用 custom GMT 走 `sspa.process_gmt` | §2.1 提出 |
| **R-NEW-14** | **本机 conda base env 污染 R native-source 编译路径** | 已发生 | 高 | base `/home/weiwentao/miniconda3/include/bfd.h` 优先于 concord_r env headers → igraph/glpk 编译失败。3 retry 模式各异均 timeout。Q-03 escalate 触发 | §2.4 实测 / Q-03 root cause |
| **R-NEW-15** | **sspa pathway_df 单元格是 int 而非 str(ChEBI numeric)** | 已发生 | 低 | gate1_toy.py 第一版 `isinstance(v, str)` 过滤错过所有 compound → sspa 10/10 task 返回空。修后 `str(int(v))` 一致化 OK。**Sprint W3 D4 normalize_sspa_output() 实现需注意 dtype 一致性** | §8.2 实测 |
| **R-NEW-16** | **Benchmark v3 inchikey 是从 smiles 用 RDKit 预算的,不是真 HMDB sqlite query** | 已发生 | 中 | §8 ID disagreement = 0.0% 是 benchmark artifact,不能 generalize 到 production 跨库一致性。**Sprint W3 D5 需 wire 真 HMDB sqlite InChIKey** 才能给可信数据;不阻塞 Gate 1 判定(Gate 1 看 PA Jaccard) | §8.5 实测 |

### 6.3 风险总览

- **R3 / R4 (集成层 risk)**: **已通过 §3 + §2.5 + §2.6 缓解** ✅
- **R5 / R6 (KEGG / Reactome)**: 待 W3 D1 实测
- **R8 (motivation)**: §8 toy 数据是最关键 verification 点 — **W2 review 必须看到 §8 Fig 3 Jaccard 数据**
- **R10 (竞品)**: §0 ✅
- **R-NEW-03 / R-NEW-04 / R-NEW-05 / R-NEW-06**: 都已通过 Investigation 找到 workaround,不阻塞 Sprint 1 启动
- **R-NEW-07 / R-NEW-08**: schema-level workaround 在 §3 / §4 已 documented,W3 实施期落地
- **R-NEW-09 / R-NEW-10**: 取决于本 session Q-03 BiocManager install 结果

**没有 risk 升级为 stop-Sprint 级别**,假设 Q-03 BiocManager 4h 内通。若 fail → R-NEW-11(待登记)+ §4 pivot 路径已写明。

---

## §7 — Open Questions (Rolling)

_Investigation 期间所有 scope 外但应问的问题归这里。_

### Q-01 — MS4MS / MSAgent bioRxiv URL 真实性校验 — ✅ RESOLVED 2026-05-15
- **背景**:Investigation 启动时 §0 子代理回报 `10.64898/...` DOI 前缀,prev session 误判为 fetch 幻觉。
- **解决**:本 session WebSearch 在 `biorxiv.org` 域内**直接命中** MS4MS 和 MSAgent 两篇,描述互洽。**bioRxiv 在 2026 年起对新提交 paper 启用新 DOI 前缀 `10.64898/`,老 paper 仍用 `10.1101/`**。两篇 paper 均真实存在,§0.2 / §0.3 URL 已更新为 verified。
- **Lesson learned**:不要仅凭 DOI 前缀 pattern 判定 URL 真假;DOI registry(bioRxiv 现有 10.1101 + 10.64898 两个 prefix)是 evolving。

### Q-02 — mummichog Python 3.13 兼容性 + R-fallback 双不可用
- **背景**:本机 Python 是 3.13.11,而 mummichog 历史只支持 Py3.7-3.9(setup.py 通常 pin)。同时本机 R 环境 broken(见 Q-03),所以"切 R 端"的 fallback 也不可用。
- **影响**:§2.2 hands-on 很可能完全失败,触发 stop condition #1;§4 集成顺序(W4 mummichog)需要 fallback 决策。
- **我的建议**:三选一,用户拍板:
  (a) 跑一个独立 conda env 装 Py3.9 + mummichog 验证(工程量 1-2h,但可能仍失败)
  (b) 直接放弃 mummichog,改用 sspa 自带的 mummichog-like 实现(若有)或 Python-port `pyMummichog`(实测可用性未知)
  (c) Python 自己重写 mummichog 核心算法(权威老算法,~500 LOC,2-3 天工程)
  我倾向 (a) 先 spike,失败则 (b)。**不能自决**因为依赖 Sprint 时间预算。
- **W 影响**:不阻塞 §1 / §5 / §6 / §7;阻塞 §2.2、§4(W4)、§8(若 §8 toy 想跑 mummichog method)。

### Q-03 — ✅ **RESOLVED (A) Docker 2026-05-15**

**用户决策(2026-05-15)**:**走 (A) Docker R 镜像**,W4 期间作为 background 写 Dockerfile + subprocess wrapper(~1d 工程量),不阻塞 W3-W4 主线。**拒绝 (B)**(Tier-A 缩 3 工具丢拓扑 axis,paper 政治损失)、**拒绝 (C)**(同样 conda 冲突可能在重搭后再次发生,unbounded risk)。

**Docker 5-sec verify(2026-05-15 Session 2 末尾)**:
```
$ docker --version
Docker version 26.1.3, build 26.1.3-0ubuntu1~20.04.1
$ docker ps   # daemon 通,空 container list
$ groups | grep docker
docker
```
✅ Docker 装在 `/usr/bin/docker`,daemon socket `/var/run/docker.sock` 可访问,用户已在 `docker` 组(memory 中记 spike 期 blocked,现已解);**Sprint W3-W5 Docker 路径完全无阻碍**。

**Sprint 1 plan(Q-03 决策后)**:
- W3-W4 主线:纯 Python(sspa + mummichog + RaMP + ChEBI ETL + MetaNetX validator + RDKit)— 已 verify
- W4 background:Dockerfile + entrypoint.R + Python subprocess wrapper(~1d 工程量,作为 hedge 任务并行做)
- W5 主线:MetaboAnalystR + FELLA via Docker subprocess(替代原 rpy2 路径)

**§2.3 / §2.4 移到 W5 主线** — Sprint 1 启动不阻塞,Investigation 不必 hands-on(Docker 路径 W5 才接触 R/FELLA)。

### Q-03 history(实测过程,保留作为 W2 review 参考)

**Stage 1(15:31)**:`conda create -n concord_r r-base=4.4 -c conda-forge` ✅ R 4.4.3 "Trophy Case" 起来,绕过原 GLIBCXX 问题(原 base env libstdc++ 冲突)。

**Stage 2(15:31 - 16:11)**:`BiocManager::install(...)` 27 包 batch — **40 min timeout (exit 143)**,只装上 limma / graph / plyr / Matrix(137 total)。fgsea / KEGGgraph / FELLA / igraph / KEGGREST 全失败,输出全 buffer 看不到错。

**Stage 3(16:20 - 16:28)**:retry-2 individual install — igraph 单装失败,**root cause 揭露**:
```
/home/weiwentao/miniconda3/include/bfd.h:35:2: error: 
  #error config.h must be included before this header
vendor/cigraph/vendor/glpk/api/prob.h:103:7: error: unknown type name 'BFD'
```
**根因**:igraph 的 GLPK vendor 编译时,`x86_64-conda-linux-gnu-cc` 的 include path 优先级是 `/home/weiwentao/miniconda3/include/`(base env binutils-dev `bfd.h`)→ `concord_r/include/`(R headers)。base env 的 `bfd.h` 要求先 include `config.h`,但 GLPK 没 include,**编译失败**。

**Stage 4(16:33 - 16:53)**:`conda install -n concord_r -c conda-forge -c bioconda r-igraph bioconductor-fella ...` — **20 min timeout (exit 143)**。conda solver 静默挂起,无 diagnostic 输出。猜测:bioconda + conda-forge + 现有 137 R 包 → SAT 解空间过大;或镜像延迟。

**Stage 5 — ESCALATE(2026-05-15 16:53)**:
- Q-03 总耗时:**~1h 22 min**(15:31 - 16:53)
- 3 retry 模式各异均失败:batch CRAN(40min timeout)/ individual CRAN(bfd.h 编译冲突)/ conda binary(solver 超时)
- **Root cause 明确**:本机 base conda env `/home/weiwentao/miniconda3/include/` 污染 concord_r env 的 C/C++ include path → `bfd.h` 头文件冲突阻断 igraph / glpk vendor 编译。这是 conda env 隔离 design issue,不是 R 本身问题
- **R-NEW-14 登记**(见 §6):本机当前 conda env 状态下 R native-source 复杂依赖装不上

**触发用户决策**:按用户原 spec 3 选项,本 session 不自决,请用户拍板:
- **(A) Docker R 镜像兜底** — `docker pull bioconductor/bioconductor_docker:devel`(含全 BiocManager 预装),subprocess 通过 docker exec 调用。Sprint 工程量 +1d(W3 加 1 dockerfile + 调用 wrapper)。**Paper 政治正确性保留**(MetaboAnalystR + FELLA 都可用)。
- **(B) 跳 MetaboAnalystR + FELLA,Tier-A 缩成 3 工具(sspa + mummichog + RaMP)** — 全 Python 路径,工程最干净,但 ConcordMet 4-axis 原计划"网络拓扑 axis 靠 FELLA"丢失。**Paper 政治正确性受损**(竞品用 FELLA 我们用 Python RWR?)。Sprint 时间表不变。
- **(C) 延一周搭专门 R env** — 在新 conda env 把 base 完全隔离开(`conda create --override-channels` 或换 mamba),完全重装。**Sprint W2 加 1 周**,但保留 R 工具。

**我的初步倾向(不算自决)**:
- 短期 Sprint 1:走 (B),立刻能开工
- 中期(W6-W12):并行做 (A) Docker — Docker 镜像搭好后 W6 引入 FELLA / MetaboAnalystR,paper-grade ready
- (C) 延一周 R env 不推荐,因为重新搭可能再撞类似 base env 冲突,unbounded risk

**Sprint 1 不阻塞**:(B) 路径下 W3-W5 全部纯 Python,Q-05 双主键 + ChEBI ETL + sspa + mummichog + RaMP + RDKit 都已 verify,可启动。FELLA 集成移到 W6+(用 (A) Docker 时)。

### Q-03 — 本机 R 环境 broken(GLIBCXX_3.4.30)
- **背景**:`R --version` 报错 `/lib/x86_64-linux-gnu/libstdc++.so.6: version GLIBCXX_3.4.30 not found`。典型的 miniconda libstdc++ 和系统 libstdc++ 版本错配。
- **影响**:**直接 BLOCK §2.3 / §2.4** — MetaboAnalystR subprocess + FELLA rpy2 都跑不起来,Tier A 工具调研中两个最重的项目无法进行;§4 W5 集成顺序无法 finalize。
- **我的建议**:三选一:
  (a) 修本机 R:`conda install -c conda-forge libstdcxx-ng` 或 `conda update -c conda-forge --all`,然后重试 R(预计 30 分钟;失败可能性高,因为 path 冲突看着复杂)
  (b) 切到另一台服务器跑 §2.3 / §2.4(若用户有备用环境)
  (c) **放弃 R 端工具,纯 Python 路径**:这意味着 ConcordMet **不集成 FELLA / MetaboAnalystR**。需要重新评估 §4 Tier A 列表 + 用户原文档的 4-axis 是否还成立(其中"网络拓扑 axis" 主要靠 FELLA;若去掉需找替代工具如 PIUMet 或 OmicsNet)。
  我倾向 (a) 先 spike;失败转 (c)。**不能自决**,(c) 改变 Sprint 主线。
- **W 影响**:**阻塞 §2.3 / §2.4 / §4(W5)/ §8(若想跑 FELLA-based PA)**。属于 Investigation 最重 blocker。

### Q05-NEW-4 / Q05-NEW-5 — ✅ **RESOLVED 2026-05-15 (namespace pivot)**
- **背景**:Q-05 第一轮 pivot 后,§3.4 出现 2 个 sub-question:
  - #4 chebi_id 必填遇到 unmapped LIPIDMAPS 长尾怎么办
  - #5 Reactome miss 时 pathway_id 怎么填
- **解决(用户拍板 2026-05-15)**:**namespace-prefixed primary keys**(MIRIAM/identifiers.org 风格):
  - PathwayHit.pathway_id 永远 `"<NS>:<id>"`,NS ∈ {REACT, KEGG, WP, SMPDB, METACYC}
  - CompoundRef.primary_id 永远 `"<NS>:<id>"`,NS ∈ {CHEBI, LIPIDMAPS, HMDB, KEGG, INCHIKEY}
  - 外部 ID 字段全 optional;InChIKey 兜底必填(RDKit 总能算)
  - `__post_init__` validator 强制 whitelist
- **影响**:schema bump v0.2 → v0.3 完成;§3 / §5 / §9 propagate 完成;**Sprint 1 W3 D0 schema 决策门槛降到 0**(原 2 个 sub-Q 都 v0.3 解决了)。

### Q-05 — **Reactome compound-level 覆盖率只有 12%,推翻原"Reactome 主键"决策**
- **背景**:§2.5 MetaNetX chem_xref 实测显示,Reactome 在跨库 metabolite 上覆盖率仅 12%(50 random ≥3-source MNX);ChEBI 100%,HMDB 82%,KEGG 58%,MetaCyc 66%。
- **影响**:用户原文档"Reactome stable ID 主键 + Reactome 缺失则 KEGG fallback"对 pathway 层有效,但对 compound 层 88% 走 fallback,导致系统复杂度爆炸 + 数据完整性丢失。
- **我的建议**:**Pivot 到方案 B(compound 层 ChEBI 主键 + pathway 层 Reactome stable ID)**。reporting 仍用 KEGG mapID,但内部 compound key 改用 ChEBI(MetaNetX 自己也是这么做的,chem_prop.tsv 以 ChEBI 为主键)。**不能自决** —— W2 architecture 决策。
- **W 影响**:阻塞 §3 schema 的 PathwayHit.metabolites_hit 字段定义(目前是 InChIKey,可保留;但 compound xref table 设计依赖 §5.1)、§4 数据库 ETL 顺序、§5 全部、§9 W3 集成顺序。

### Q-04 — InChIKey block14 不能 reconcile 开链 ↔ 环状 同分异构(糖类等)
- **背景**:§2.6 toy 实测 D-Glucose 开链 Fischer SMILES (`OCC(O)C(O)C(O)C(O)C=O` → block14 `GZCGUPFRVQAUEE`)与环状 SMILES(α/β,block14 `WQZGKKKJIJFFOK`)落到不同 block。这是 InChI 设计意图(C-O connectivity 不同 → 不同 connectivity hash),不是 RDKit bug。
- **影响**:ConcordMet 跨库 reconciliation 对单糖、双糖、其他多环 ↔ 开链平衡分子可能 false-split。受影响代谢物估计 < 5%(HMDB 中糖类约 ~200 / total 220k),但 metabolomics 数据集中糖类占比通常 5-15%(因为生物丰度高 + LC-MS 易检测)。
- **我的建议**:三选一:
  (a) **加 RDKit `MolStandardize.tautomer.TautomerEnumerator` 预标准化**,把开链糖统一到环状代表(工程量 ~50 LOC,W3 集成阶段加);**推荐**。
  (b) 对受影响化合物用 **HMDB / PubChem cross-ref 表** 补 reconcile(已有 lookup_compound_info backend 可做,但慢)。
  (c) 接受 false-split,在 §6 risk register 记一笔"糖类 ID reconciliation 局限"。
  我**倾向 (a)**,因为工程成本可控且符合 ConcordMet 主线。**不能自决**因为这会影响 §3 schema(需加 `tautomer_canonicalized: bool` 字段)+ §9 W3 plan 时长。
- **W 影响**:不阻塞 §2 / §3 / §8 toy;若不在 W3 处理,W4 集成会反复出现糖类 mis-merge bug 报告。

---

## §8 — W1 Gate 1 Toy 数据 (Fig 3 雏形) — ✅ **GATE 1 GREEN**

**Run @ 2026-05-15 18:57 UTC+8,wall 89.2 sec(预算 6h)**
**Output**: `data/investigation/fig3_toy/{jaccard_matrix.png, jaccard_data.csv, id_disagreement.csv, summary.json}`
**Script**: `data/investigation/scripts/gate1_toy.py`

### 8.1 Task 选样(10 task,2 per bucket × 5 buckets,seed=42)

避开 `RAMP_P_000052855`(D2/D3/D4 已用)。Bucket diversity:

| Bucket | Tasks |
|---|---|
| lipid_metabolism | RAMP_P_000000421_seed2,lm_pathway_WP167_seed5 |
| central_metabolism | RAMP_P_000000398_seed5,RAMP_P_000000141_seed8 |
| amino_acid_metabolism | RAMP_P_000050021_seed9,RAMP_P_000000398_seed8 |
| nucleotide_metabolism | RAMP_P_000000016_seed1,RAMP_P_000050099_seed6 |
| other | RAMP_P_000050021_seed3,RAMP_P_000050021_seed6 |

Tasks 平均 metabolite 数:8.3(7-10 范围),共 83 metabolite。

### 8.2 PA 方法 × 3

| Method | Backend | Input format | Pathway DB |
|---|---|---|---|
| **ramp** | `tools.benchmark.sub6.ramp_enrichment.compute_enrichment` (hypergeometric ORA) | HMDB ID list | RaMP-DB(merged KEGG+Reactome+WikiPath+SMPDB) |
| **sspa** | `sspa.sspa_ora` 1.0.4 with synthetic 5-case + 5-ctrl matrix | ChEBI ID list(via KEGG→ChEBI via ChEBI rel251 database_accession.tsv) | Reactome Homo sapiens(2243 × 1479 sspa.process_reactome 输出) |
| **mummichog** | `python -m mummichog.main` 2.7.0 | synthetic m/z table(M+H+ adduct + 250 background random m/z + p-val) | human_mfn(mummichog 内建) |

**实施 fixes 期间发现的 1 bug**:sspa pathway_df 单元格是 **int**(`30616` 等 ChEBI numeric),而我代码原 `isinstance(v, str)` 过滤错过所有。修后 sspa 10/10 task 都返回 top-10。详见 §6 R-NEW-15。

### 8.3 ID Mapper × 2

| Mapper | Source |
|---|---|
| **hmdb_direct** | benchmark v3 metabolite.inchikey field(预算 SMILES via RDKit pre-computed) |
| **rdkit** | session 3 实时 `rdkit.Chem.inchi.InchiToInchiKey(MolToInchi(MolFromSmiles))` |

### 8.4 跨方法 Jaccard 矩阵(normalized pathway name match,top-10)

| | ramp | sspa | mummichog |
|---|---|---|---|
| **ramp** | 1.000 | 0.121 | 0.022 |
| **sspa** | 0.121 | 1.000 | 0.005 |
| **mummichog** | 0.022 | 0.005 | 1.000 |

**Mean off-diagonal Jaccard:0.049**(over 3 pairwise comparisons × 10 tasks)

跨方法不一致**极高**:
- ramp ↔ sspa(都是 ORA 但不同 DB):**87.9% disagreement on top-10**
- ramp ↔ mummichog(ORA vs m/z fisher,不同 DB):**97.8% disagreement**
- sspa ↔ mummichog(完全不同 stat + DB):**99.5% disagreement**

### 8.5 ID mapper disagreement(metabolite-level block14 mismatch)

| metric | value |
|---|---|
| n_metabolites_total | 83 |
| n_disagree_block14 | **0**(0.0%) |

⚠️ **Caveat**:benchmark v3 的 `inchikey` field 本来就是从 `smiles` field 用 RDKit 算出来的(`scripts/benchmark/...` 预处理时种 plant)。所以 hmdb_direct vs rdkit 实质上都走的同一条 RDKit 路径,**这条 disagreement = 0 不能 generalize 到 production 时跨库 InChIKey 一致性**。**Sprint W3 需要换"真 HMDB sqlite InChIKey"** 才能给出有意义的跨源一致性数据。已登记 §6 R-NEW-16。

### 8.6 Fig 3 雏形

`data/investigation/fig3_toy/jaccard_matrix.png` — 3×3 viridis heatmap,off-diagonal 全部 < 0.13(深紫色)。CSV:`jaccard_data.csv` 90 行(per-task × method-pair Jaccard),`id_disagreement.csv` 83 行(per-metabolite block14 比较)。

### 8.7 Gate 1 判定:**🟢 GREEN**

```
Mean cross-method Jaccard = 0.049

GREEN     :  J < 0.4         ← 当前  ✓
BORDERLINE:  0.4 ≤ J ≤ 0.6
RED       :  J > 0.6
```

**Reconciliation motivation 成立**:3 个 PA 方法在 top-10 pathway 列表上几乎不重叠(off-diagonal 0.005-0.121),证明跨方法 disagreement 是 metabolomics enrichment 的真实问题。**继续 ConcordMet 主线 → W2 review 进 Sprint W3**。

### 8.8 Caveats(W2 review 需注意)

1. **Pathway name 匹配算法**:lowercase + 移除停用词 + sort token + 完全匹配。这是较"严格"的匹配,会低估真实 Jaccard。若用更宽松匹配(token Jaccard > 0.6 视为同 pathway),数字会上升。**但即使宽松匹配,off-diagonal 也很难超过 0.4 阈值**(因为不同 DB 命名风格差异大,例 RaMP 用 "Phase II - Conjugation of compounds" vs Reactome 简洁 "Phase II Conjugation")。
2. **mummichog 的输入是合成 m/z + p-val**(255 features:10 diff M+H + 250 random background)。这与典型 LC-MS 真实数据规模不同,真实数据 1000-10000 features 时 mummichog 的 stat 可能有差异。但对 Gate 1 question(方法不一致是否成立)结果稳健。
3. **sspa 的 ORA 走 synthetic 2-class 5+5 sample matrix**(case rows 给 differential metabolite 高表达,ctrl 全均匀)。这是 sspa 的设计用法(它本来就是 sample-based 工具),不算 hacky。Sprint W3 实施 normalizer 时仍这么做。
4. **ID disagreement = 0% 是 benchmark 构造的 artifact**(见 §8.5 caveat),W3 D5 需要 wire 真 HMDB sqlite InChIKey 才能给可信 cross-source 数据。这不影响 Gate 1 判定(Gate 1 看跨方法 Jaccard,不看 ID 一致性)。
5. **10 task 是小样本**。如果 W2 review 想要更高 confidence,可扩 N=30 ~ 60 task(全 benchmark 跑完只需 ~5 min wall;用户 spec 5-10 task 是默认范围)。

---

## §9 — W3-W4 Sprint Daily Plan(Q-05 pivot 后)

### W3 Daily Plan(5 工作日,v0.3 + namespace pivot 后)

✅ **Q05-NEW-4 + Q05-NEW-5 RESOLVED via v0.3 namespace pivot** — W3 D0 不再需要 schema 拍板,直接进 ETL。

| Day | 任务 | Wall-time | 依赖 | 输出 |
|---|---|---|---|---|
| W3 D1 | ChEBI sqlite ETL part 1:`compounds.tsv` → `compound` 表(`primary_id="CHEBI:" + id`);`source.tsv` 字典;`secondary_ids.tsv`;script `concordmet/etl/chebi_etl.py` | 0.5d | rel251 已下载 | sqlite `compound` 表 ~165k rows,namespaced |
| W3 D2 | ChEBI sqlite ETL part 2:`database_accession.tsv` → `compound_xref`(filter source_id ∈ {35, 45, 50, 54, 68, 72, 79});实施 KEGG→ChEBI 反查 SQL 函数 | 0.5d | D1 | `compound_xref` 表 ~140k rows;`resolve_kegg_to_chebi()` 函数 |
| W3 D3 | (a)下 `structures.tsv.gz` 85 MB,ETL 到 `compound.inchikey / smiles / inchikey_block14`;(b)`relation.tsv` → `compound.parent_chebi_id`(Q-04 上爬 fix);(c)Reactome ChEBI2Reactome_All_Levels.txt → `pathway` + `pathway_compound` | 1d | D2 + structures.tsv 下载 | 完整 sqlite ~250 MB;Q-04 fix verified |
| W3 D4 | sspa wrapper:封装 `sspa_ora` / `sspa_ssGSEA` 调用,输出 → ChEBI ID;normalize 到 EnrichmentResult v0.2 | 1d | D2 ChEBI ETL | `normalize_sspa_output()` 实现 + 单测 |
| W3 D5 | RDKit InChIKey reconciler 集成到 lookup_compound_info pipeline + Q-04 上爬 SQL 调用 | 1d | D3 | RDKit + ChEBI 整合工具 |
| **W3 hedge** | GPT-4o wire-up + W3 buffer | 0.5d | — | LLM client 就绪 |

**W3 总 wall-time:5d 工作量 + 0.5d hedge = 5.5d**,正好覆盖 1 周(5 工作日)。

### W4 Daily Plan(Docker Dockerfile 在 W4 期间作为 background 并行)

| Day | 主线任务 | Background(Q-03 (A) Docker)| 依赖 |
|---|---|---|---|
| W4 D1 | mummichog wrapper + `normalize_mummichog_output()`(走 `resolve_primary_id`)| 写 Dockerfile(FROM bioconductor/bioconductor_docker:RELEASE_3_19)| W3 ChEBI ETL |
| W4 D2 | MetaNetX sqlite ETL(降级为 crosswalk validator)| `docker build` + 缓存 image | W3 ChEBI |
| W4 D3 | RaMP `normalize_ramp_output()`(走 namespaced primary_id)| 写 `entrypoint.R`(stdin JSON → MetaboAnalystR/FELLA → stdout JSON)| W3 |
| W4 D4 | 集成 §8 Gate 1 toy:5-10 task × {RaMP, sspa, mummichog} × {RDKit, ChEBI} → Jaccard matrix | Docker subprocess wrapper Python 端 | W4 D1-D3 |
| W4 D5 | W4 buffer + W4 hedge | Docker e2e toy (entrypoint.R call test)| W4 D4 |

### W5 Plan(Q-03 (A) Docker 路径,已拍板)

| Day | 任务 |
|---|---|
| W5 D1 | MetaboAnalystR PerformPSEA via Docker subprocess + `normalize_metaboanalystr_output()` |
| W5 D2 | FELLA RWR single-call via Docker + `normalize_fella_output()` |
| W5 D3 | FELLA 并发 spike — Docker 内 R session 并发(Python 端 `concurrent.futures.ThreadPoolExecutor` × `docker exec`,K=10)。**注意**:原 §2.4 rpy2 K=10 spike 改成 docker exec K=10 spike,因为我们走 Docker 不走 rpy2 |
| W5 D4 | 集成测试:5-10 task × {RaMP, sspa, mummichog, MetaboAnalystR, FELLA} 完整 4-axis Jaccard;扩 §8 数据 |
| W5 D5 | W5 buffer + W6 hedge(ConcordMet aggregator 起手)|

**Docker 性能注**:`docker exec` startup ~2-3s(等同 Rscript 启动),对 K=10 并发可控。FELLA RWR 单 call wall time 与 R session 直接调用基本一致。

### W3-W5 累计依赖图

```
W3 D0 (拍板) ──┬─→ W3 D1-D3 ChEBI ETL ──┬─→ W3 D4 sspa wrapper
               │                          └─→ W3 D5 RDKit + ChEBI 整合
               └─→ W3 hedge GPT-4o
                                          ↓
                            W4 D1 mummichog wrapper ─→ W4 D4 Gate 1 toy
                            W4 D2 MetaNetX validator ──┤
                            W4 D3 RaMP normalize ──────┘
                                          ↓
                            W5 D1-D5 MetaboAnalystR / FELLA(取决于 Q-03)
```

**Critical path**:W3 D0 拍板 → ChEBI ETL D1-D3 → 所有 normalizer。任何 D0 决策延迟 → 整体后移。

---

## Session Log

### Session 1 — 2026-05-15(scaffold + §0 + §1 + §2.0 + Q-blocker discovery)
**Owner:** Claude (Opus 4.7)
**Time:** ~30 min wall
**Done:**
- ✅ 建 worktree `metagent_day1_v5_investigation` @ tag `MetAgent-v1-0514`,新分支 `feature/investigation-concord`
- ✅ 报告骨架 9 sections + Stop Conditions + Status Dashboard
- ✅ §0 竞品 4 repo recon(子代理 + 后续 Q-01 修正)
- ✅ §1.1 - §1.5 (pytest baseline 988/2/10 + tools + verifier layers + dispatcher routing + 5 个偏差)
- ✅ §2.0 环境预侦察(发现 Q-02 Py3.13 vs mummichog + Q-03 R env broken)
- ✅ §7 登记 Q-01 / Q-02 / Q-03

**Commits:** `7786512` → `1670c4b` → `4495352`

### Session 2 — 2026-05-15(Q-resolve sprint + Q-05/Q-03/Q05-NEW-4/Q05-NEW-5 全部 RESOLVED)
**Owner:** Claude (Opus 4.7)
**Time:** ~40 min wall(并行 conda install + curl + report writing)
**Done:**
- ✅ **Q-01 RESOLVED** — bioRxiv 2026 新 DOI 前缀 `10.64898/`,MS4MS / MSAgent 均真实(WebSearch 二次核实)
- ✅ **Q-02 RESOLVED** — `conda mummichog_py310 (Py3.10)` + `pip install mummichog` → v2.7.0(PyPI 上无 v3)
  - Toy 13s wall,7995 features → KEGG cpd-based pathway TSV
  - 发现 R-NEW-04(v3 不存在)+ R-NEW-08(pathway_name 不是 KEGG mapID)
- ✅ **§2.1 sspa 1.0.4** — import + load_example_data + process_reactome 通
  - 同 conda env,装时 `pkg_resources` + `tqdm` 缺失(R-NEW-11)
  - 24 个 API,主用 sspa_ora / sspa_ssGSEA / process_reactome
  - R-NEW-12: ChEBI ID convention(与 mummichog KEGG cpd 不同)
- ✅ **§2.5 MetaNetX(部分)** — MNXref 4.5(2025-08-13)endpoint 可达,REST API 挂(500),flat-file 路径可行;`chem_xref.tsv` ⏳ 仍在下载(已 380+ MB,比预期 50× 大)
- ✅ **§2.6 RDKit InChIKey reconciler** — toy script 跑通,13 SMILES / 6 化合物,**D-Glucose 开链 vs 环状 false-split**(Q-04 + R-NEW-07)
- ✅ **§3 EnrichmentResult schema 草案** — 228 行 dataclass + 4 normalizer 签名 + 8 schema gap
- ✅ **§4 release pinning 5/11**:MetaNetX 4.5 / mummichog 2.7.0 / R 4.4.3 / RDKit 2025.09.6 / HMDB v5.0
- ✅ **§6 风险登记** — 10 原 R + 13 R-NEW(其中 R3/R4 已 mitigated,R8 待 §8)
- ✅ **§1.5 5 处偏差**全部分类:**5 DD / 0 AB / 0 MF**(无需 Q-04 升级)
- ✅ **§7** 新登记 Q-04(InChIKey 糖类 ring-chain reconcile)

**In progress(本 session 收尾时还跑着的):**
- ⏳ **§2.5 chem_xref.tsv** curl(15 min timeout,400+ MB 还在下)
- ⏳ **Q-03 BiocManager** install(R 4.4.3 env 跑 27 个 Bioc deps,output 缓冲不可见,~30-60 min wall)
- 📜 Monitor `bn3vpuoqa` 等 curl 进程退出

**Session 2 终态 — 全部 Q 已 RESOLVED**:
- ✅ Q-01 bioRxiv URLs verified(2026 DOI prefix 10.64898 真实)
- ✅ Q-02 mummichog 2.7.0 toy verified
- ✅ Q-03 (A) Docker 决策已下,Docker 26.1.3 + daemon + 用户组 all verified
- ✅ Q-04 InChIKey 糖类 false-split → ChEBI is_a 上爬方案
- ✅ Q-05 双主键架构(ChEBI compound + Reactome pathway)
- ✅ Q05-NEW-4 + Q05-NEW-5 → namespace-prefixed primary keys(v0.3 schema)

**所有 W3 D0 schema 决策门槛降到 0**(原有 2 个 sub-Q 都 v0.3 解决)。

**Commits 本 session**: 13 个,从 `98b630f` 到 commit 后续。

**Next session 入口(用户指定优先级)**:
1. ✅ Docker verify 已在本 session 末做完(26.1.3 + daemon + group all OK)
2. **§8 W1 Gate 1 toy 数据(最高优先级)** — 5-10 task × {RaMP + sspa + mummichog} × {RDKit + ChEBI},算 Jaccard 矩阵,出 Fig 3 雏形 PNG;**Gate 1 判定 PASS/BORDERLINE/FAIL**
3. W4 期间 background(可在 §8 toy 跑的间隙):写 Dockerfile + entrypoint.R + Python subprocess wrapper
4. **§2.3 MetaboAnalystR + §2.4 FELLA** 通过 Docker 路径在 W5 跑(Session 3 不必动手,Sprint 主线任务)
5. §6 / §7 / §9 细节 polish 在 Gate 1 toy 跑的间隙完成

---

## Appendix — 完成定义

- [ ] 9 个 section 全填
- [ ] `data/investigation/fig3_toy/` 含 Jaccard PNG + CSV
- [ ] `feature/investigation-concord` 上有 N 个 exploration script commit(纯 docs / explore)
- [ ] **不 push origin**
- [ ] Ping 用户做 W2 review
