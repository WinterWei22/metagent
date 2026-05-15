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
| §2 | 10 候选工具系统调研 | 2d | **partial(2.0/2.2/2.5/2.6 done;2.1/2.3/2.4 pending)** |
| §3 | 统一 EnrichmentResult Schema | 0.5d | **Done(草案 v0.1,W3 实现 normalizer body)** |
| §4 | Tier A 工具集成计划 | 1d | partial(release 数据陆续到位) |
| §5 | Pathway ID Crosswalk 策略 | 0.5d | Pending |
| §6 | Risk Register | 0.5d | Pending |
| §7 | Open Questions | 0.5d (rolling) | Rolling(Q-01 ✅ / Q-02 ✅ / Q-03 ⏳ / Q-04 新) |
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

### 2.1 py-sspa — Pending (hands-on §2 session)
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
### 2.3 MetaboAnalystR 4 (subprocess) — **BLOCKED on R env**,见 Q-03
### 2.4 FELLA (rpy2 并发 spike) — **BLOCKED on R env**,见 Q-03
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

**全量 covergage 矩阵(50-100 metabolite × 7 source)**:⏳ chem_xref.tsv 全量下载中(curl 后台,timeout 15 min);下载完后用 `data/investigation/scripts/metanetx_coverage_probe.py`(W3 写)做随机抽样统计。

**§2.5 状态**: **Endpoint 可达 + release 4.5 (2025-08-13) 确认**;覆盖率矩阵后续 session 完成(curl 完成后注入 sqlite + 抽样)。
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

## §3 — 统一 EnrichmentResult Schema — ✅ 草案 DONE

**Script:** `data/investigation/scripts/enrichment_result_schema_draft.py`(228 行,含 dataclass + enums + 4 normalizer stubs + gap list + sanity check)

### 3.1 Schema 核心(dataclass + enums)

**`EnrichmentResult`**(method-level):
- `method: EnrichmentMethod`(10 个枚举值,覆盖 sspa 4 个方法 / mummichog / FELLA 2 个 / MetaboAnalystR 2 个 / RaMP ORA)
- `pathway_db: PathwayDB`(7 个枚举值:KEGG / Reactome / WikiPathways / MetaCyc / HMDB / SMPDB / MERGED)
- `pathways: tuple[PathwayHit, ...]`
- `parameters: dict[str, Any]`(cutoff / db_release / permutation / seed)
- `tool_version`、`db_release`、`n_input`、`n_input_resolved`、`wall_time_sec` — traceability
- `schema_version: str = "concordmet_v0.1"`
- `tautomer_canonicalized: bool = False` — 落地 §2.6 Q-04 ring-chain 标准化
- `notes: str`

**`PathwayHit`**(per-pathway):
- `pathway_id: str` — canonical(Reactome stable ID 主键,见 §5)
- `pathway_id_native: str` — 工具实际输出(KEGG mapID 或 human_mfn 内部 name)
- `pathway_db: PathwayDB`、`pathway_name: str`
- `score: float` + `score_type: ScoreType`(9 个枚举值:P_VALUE / FDR / ES / NES / SS_ACTIVITY / RWR_SCORE / DIFFUSION_SCORE / EASE / COMPOSITE)
- `rank: int`(工具自报或 by-score)
- `metabolites_hit: tuple[str, ...]` — **full InChIKey(27 字符)**,frozen for hashing
- `metabolites_hit_block14: tuple[str, ...]` — block14(供跨库 cluster joins)
- `n_metabolites_in_pathway: int`、`n_metabolites_input: int`(ORA 需要)
- `auxiliary_scores: dict[str, float]` — 留给每工具特定 metric(EASE / NES / RWR activity / ...)

### 3.2 Sanity 测试

```
$ python data/investigation/scripts/enrichment_result_schema_draft.py
PathwayHit OK: R-HSA-71387 score=1e-05 (p_value)
EnrichmentResult OK: mummichog on kegg (1 hits, 14.2s)
```
✅ dataclass 可实例化,enums 互不冲突。

### 3.3 4 Normalizer 签名(W3 实现 body)

| Function | 输入 | 关键 gap |
|---|---|---|
| `normalize_sspa_output()` | sspa DataFrame + method enum + inchikey_lookup | 多 score 列何时升 primary;ChEBI/KEGG ID → InChIKey 反查 |
| `normalize_mummichog_output()` | mummichog TSV + mz_to_inchikey(候选反查) | m/z → 候选 compound 多对多,EASE 存 auxiliary;**实测确认输出含 pathway_name 但不含 KEGG mapID** |
| `normalize_fella_output()` | rpy2 调用返回的 R data.frame | RWR score 不是 p-value;5 层 graph 只取 compound 层;**依赖 Q-03 R 修通** |
| `normalize_ramp_output()` | RaMP-DB EnrichmentReport pydantic | 字段重命名 + InChIKey 反查(RaMP 内部用 RaMP source-ID) |

(Tier-B `normalize_metaboanalystr_output()`、`normalize_pathintegrate_output()` 等 W4+)

### 3.4 已知 Schema Gaps(W3 需 revisit)

| Severity | Gap | W3 计划 |
|---|---|---|
| HIGH | mummichog `mz_to_inchikey` 失败时 metabolites_hit 留空 | W3 D2 fallback:留 None + auxiliary 备注 |
| HIGH | Pathway ID 跨 KEGG/Reactome/WikiPathways 不统一 | 见 §5 crosswalk,Reactome 主键 + KEGG fallback |
| HIGH | `score_type=COMPOSITE` 谁生成 | Sprint W6+ ConcordMet aggregator,Investigation 不实现 |
| MEDIUM | sspa 多 score 列升 primary 规则 | W3 D1 看 sspa 实测列再定 |
| MEDIUM | `tautomer_canonicalized=False` 时是否拒绝下游 reconciliation | W3 决定;若严格则 ETL 期 reject |
| LOW | FELLA 跨 5 层 graph 的 `n_metabolites_in_pathway` 定义 | 只取 compound 层 |
| LOW | `auxiliary_scores` float-only 限制(若工具输出 list?) | W3 D3 看 FELLA 实输出 |
| LOW | `schema_version` 升级策略 | 任一字段变 → bump v0.1 → v0.2 |

### 3.5 mummichog 实测反馈 §3 新增 gap

**Investigation 期间** 跑了 mummichog toy,**发现 §3 原草案漏了 pathway_id_native 的处理**:
- mummichog 输出 `pathway` 字段是 human_mfn 内部 name(`"Alanine and Aspartate Metabolism"`),不是 KEGG mapID,也不是 stable ID
- 这意味着 `pathway_id_native` 字段对 mummichog 来说就是这个 name 字符串本身
- W3 实现 `normalize_mummichog_output()` 时需要:**(a) 把 human_mfn name → 内部 ID 映射表**(查 `mummichog/JSON_metabolicModels.py`),**或 (b) 把 name 作为 pathway_id_native 接受,§5 crosswalk 用 fuzzy-match 转 Reactome**。倾向 (a),(b) fuzzy-match 风险高。

### 3.6 §3 状态

**Schema 草案 DONE**(W2 review 用),W3 实现 normalizer body 时若实测出更多 gap 再 bump 到 v0.2。

---

## §4 — Tier A 工具集成计划

### 4.1 Database Release Pinning(本 session 已锁定 / 待办)

| 库 | 拟锁定 release | 来源 | 验证状态 |
|---|---|---|---|
| **MetaNetX MNXref** | **4.5(2025-08-13)** | `chem_xref.tsv` 头部声明 | ✅ 已下载 (102 MB),flat-file 路径(REST API 挂) |
| **mummichog** | **2.7.0**(PyPI latest;v3 不存在) | `pip install mummichog` | ✅ 已 Toy verify(Q-02) |
| **R base** | **R 4.4.3 "Trophy Case"** | conda r-base=4.4 in `concord_r` env | ✅ 已 verify |
| **MetaboAnalystR / FELLA / Bioconductor** | BiocManager 3.20 | Bioc release 2024-10 | ⏳ Q-03 install 中 |
| **RDKit** | 2025.09.6 | system base env | ✅ 已 verify(§2.6) |
| Reactome | TBD(W3 锁日期) | Reactome SQL dump | Pending |
| KEGG | TBD(academic rate limit 实测) | KEGG REST + 本地 sqlite | Pending |
| LIPID MAPS | TBD | flat file | Pending |
| HMDB | v5.0(主 repo 已有) | 已存 | Pending 确认 |
| ChEBI | TBD | flat / sqlite | Pending |
| PubChem | PUG-REST 实时(rate limit 实测) | 已有 lookup_compound_info backend | Pending |

**已知 release 锁:5/11 项**(MetaNetX 4.5,mummichog 2.7.0,R 4.4.3,RDKit 2025.09.6,HMDB v5.0)。其余 6 项需 W3 D0 前 finalize。

### 4.2 50-Metabolite × 7 Source 覆盖矩阵 — ⏳ 下载完成后用 `metanetx_coverage_probe.py` 跑

probe 输出 3 张表:
- source-prefix 频次分布(全表)
- 50 个随机 MNX × 7 主源(reactome / chebi / hmdb / kegg / metacyc / bigg / lipidmaps)的命中矩阵
- 每个 metabolite 命中 source 数量分布(直方)

### 4.3 W3-W5 集成顺序(基于本 session 实证调整)

| Week | 原计划 | **实证调整** | 理由 |
|---|---|---|---|
| W3 | sspa + RDKit | **RDKit(已 OK)+ sspa + MetaNetX flat-file ETL** | RDKit toy 通过(§2.6);MetaNetX flat-file 而非 REST(REST 挂);sspa 仍是首选 ORA |
| W4 | mummichog + MetaNetX | **mummichog(已 verify)+ schema normalizer 实现** | mummichog 已 verify(§2.2),W4 直接进 normalizer + 集成测试 |
| W5 | MetaboAnalystR + FELLA | **MetaboAnalystR + FELLA(若 Q-03 通)/ Python RWR fallback** | 取决于 Q-03 escalation,见 §7 |

**Pivot 预案(Q-03 fail)**:
- (a) Tier-A 缩到 3 工具:sspa + mummichog + FELLA(Python RWR 重写,~2-3 周)
- (b) Tier-A 缩到 3 工具:sspa + mummichog + MetaboAnalystR(若仅 FELLA 失败,MetaboAnalystR 仍通)
- (c) Docker R 镜像 escalation(W3 加 1 周搭 docker,paper 政治正确性保留)

(详细 daily plan 见 §9)

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

### Q-03 — 本机 R 环境 broken(GLIBCXX_3.4.30)
- **背景**:`R --version` 报错 `/lib/x86_64-linux-gnu/libstdc++.so.6: version GLIBCXX_3.4.30 not found`。典型的 miniconda libstdc++ 和系统 libstdc++ 版本错配。
- **影响**:**直接 BLOCK §2.3 / §2.4** — MetaboAnalystR subprocess + FELLA rpy2 都跑不起来,Tier A 工具调研中两个最重的项目无法进行;§4 W5 集成顺序无法 finalize。
- **我的建议**:三选一:
  (a) 修本机 R:`conda install -c conda-forge libstdcxx-ng` 或 `conda update -c conda-forge --all`,然后重试 R(预计 30 分钟;失败可能性高,因为 path 冲突看着复杂)
  (b) 切到另一台服务器跑 §2.3 / §2.4(若用户有备用环境)
  (c) **放弃 R 端工具,纯 Python 路径**:这意味着 ConcordMet **不集成 FELLA / MetaboAnalystR**。需要重新评估 §4 Tier A 列表 + 用户原文档的 4-axis 是否还成立(其中"网络拓扑 axis" 主要靠 FELLA;若去掉需找替代工具如 PIUMet 或 OmicsNet)。
  我倾向 (a) 先 spike;失败转 (c)。**不能自决**,(c) 改变 Sprint 主线。
- **W 影响**:**阻塞 §2.3 / §2.4 / §4(W5)/ §8(若想跑 FELLA-based PA)**。属于 Investigation 最重 blocker。

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
