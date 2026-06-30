# Stage 1（单谱代谢物结构识别 / Per-spectrum Structure Identification）—— 方法 · 数据 · 结果 · 复现

> 整理日期：2026-06-30
> 范围：**Stage 1 = 单谱结构识别**——输入一张 MS/MS 谱 → 输出按证据排名的候选**结构**（SMILES/InChIKey）+ 峰归属 + PMID 文献证据。
> verifier 入口是 `verifier/agent.py::verify()`（spectrum entry，吃 `IdentificationReport` → `VerifiedIdentification`），验证**结构/峰/ID/PMID 级** claim。
> 评测集：**sub6a (real-id)** 与 **CASMI**。
>
> ⚠️ 本文**不涉及 Stage 2**：`verify_sub6()` 入口、4-shape grammar（pathway_membership / metabolite_pathway_link / pathway_enrichment / driver_metabolite）、富集 4 层（6a–6d）、sub6b narrative、Step Z hybrid extractor、D4 narrative feedback、UV/supported 指标——这些全走 `verify_sub6()` = Stage 2 入口（CLAUDE.md line 256），属另一份文档。
>
> 权威来源：`reports/eval/sub6a_real_id_rerank_summary.md`、`reports/eval/library_search_phase_a_2026-05-06.md`、
> `reports/eval/casmi_2016_cat2_v1.md`、`reports/eval/casmi_llm_reranker_v1.md`、`reports/eval/sirius_cfmid_rerank_v2.md`、
> `reports/eval/llm_reranker_v2.md`、`reports/eval/sub6_metagent_final_summary_2026-05-06.md`、
> `reports/project_architecture_tools_verifier_summary_2026-04-27.md`。引用数字均标注来源。

---

## 1. 方法（Method）

### 1.1 识别 pipeline（端到端）

来源：`sub6a_real_id_rerank_summary.md` §2、`library_search_phase_a_2026-05-06.md`

```
input: MS/MS spectrum (precursor m/z + peak 数组)
  │
  ├─[Phase A] precursor-mass window 预筛（±10 ppm）
  │     GNPS 库 622,632 候选 → 平均 ~89 候选（5536× 缩减）
  │
  ├─[library_search] modcos（modified cosine vs GNPS reference）+ 可选 MS-CLIP
  │     按 max(modcos, msclip_rescaled) 排 → top-20 候选
  │
  ├─[optional rerank head]（per-spectrum 正交信号）
  │     • SIRIUS：谱 → top-1 分子式 + fragmentation tree（sanity gate）
  │     • CFM-ID：候选 SMILES → 预测 MS/MS 谱（disk-cached）
  │     • evidence_score = 0.4·modcos + 0.3·predicted_cosine + 0.2·mass_match + 0.1·pathway_presence
  │     • SIRIUS gate：分子式不符 → evidence_score ×0.5
  │     • 可选 LLM reranker（Opus-4-7）：JSON evidence bundle → selected top-1
  │
  └─ ranked candidates（top-1 SMILES/InChIKey）+ 峰证据 [+ 可选 LLM narrative]
        │
        └─[verify()] 抽取 peak-level claims → 分类 → Layer F 逐条验证 → SUPPORTED/CONTRADICTED/UNVERIFIABLE
```

**关键设计决策**：
- **mass tolerance = ±10 ppm**（Phase A 单点最大收益）：5 ppm 对小分子过严、20 ppm 重新引入高置信错误，10 ppm 是 HRMS 标准甜点。
- **library_search 默认 top-1（modcos）是本 benchmark 最强单信号**：sub6a 上 74.58%，所有 rerank 反而降 1–5 pp（见 §3.2，根因 GNPS leakage）。

### 1.2 7-tool 结构管线职责（`docs/TOOL_CONTRACTS.md`）

| tool | 职责 | 关键参数 |
|---|---|---|
| `library_search` | 谱-库匹配生成候选 | `mass_tolerance_ppm=10`, `top_k=20`, GNPS+inhouse |
| `spectrum_predict` / CFM-ID | 候选 SMILES → 预测 MS/MS 谱 | udocker `cfm-id-4.4.7`，disk-cached |
| SIRIUS | 分子式推断 + fragmentation tree | 本地 6.3.4 binary（学术许可，auto-relogin） |
| `molecule_gen` | 生成式 SMILES 候选（library miss 时） | — |
| `metabolite_info` | InChIKey / SMILES / formula | HMDB / PubChem |
| `pathway_context` | 通路关联（evidence_score 0.1 项） | KEGG / RaMP / Reactome |
| `literature` | PMID 文献证据 | PubMed / Europe PMC |

> MS-CLIP（谱-结构相似度）作为可选 primary retriever / fusion 信号，ion vocab 有限（见 §4）。

### 1.3 verify() spectrum 入口 + Layer F（结构识别的 verifier）

入口 `verifier/agent.py::verify(llm_output, source_report: IdentificationReport, …) -> VerifiedIdentification`，4-stage cascade（`project_architecture_tools_verifier_summary_2026-04-27.md` §6）：抽取 atomic claim → 分类 ClaimType → 分层验证 → 可选 rewrite。

**Layer F（peak_mechanistic，`verifier/layers/peak_mechanistic.py`）** 是 Stage 1 结构识别的核心 verifier：
- 触发：claim 同时含 `m/z` 数值 + `fragment`/`loss of` 机制关键词。
- 判定：spectrum ±5 ppm 内是否真有该 m/z 峰。
- 作用：客观量化 LLM 把"工具预测峰"当"实验观测峰"写进 narrative 的 mechanistic hallucination（见 §3.4）。

---

## 2. 数据（Data）

### 2.1 sub6a (real-id) v2

来源：`sub6a_real_id_rerank_summary.md`

| 维度 | 规模 |
|---|---:|
| Tasks | 38 |
| Spectra/task（mean） | 12.1（4–23） |
| **Total spectra** | **459** |
| Phase A 后 ≥1 候选的 spectra | **358（78%）** |
| 0 候选（fail-silent） | ~101（22%） |
| GNPS 候选池（无 mass filter） | 622,632 |
| Phase A（±10 ppm）后平均候选 | ~89（5536× 缩减） |

benchmark 文件：`data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`。

### 2.2 CASMI（OOD 结构识别）

来源：`casmi_2016_cat2_v1.md`

| 维度 | CASMI 2022 | CASMI 2016 cat2 | Combined |
|---|---:|---:|---:|
| Spectra | 170 | 208 | **378** |
| Ion mode | 100% pos | 127 pos / 81 neg | 混合 |
| Candidate pool | PubChem formula-restricted | per-challenge mass-tolerant CSV | 混合 |

### 2.3 Peak evidence 语料（Phase 6.2/6.4 产出）

| 指标 | 规模 |
|---|---:|
| Peak evidence files（per signal-bearing spectrum） | 358 |
| SIRIUS top-1 coverage | 100%（auto-relogin） |
| CFM-ID predicted coverage | 100%（358/358） |
| Layer F dispatched peak claims | 858（rule-based extractor） |

---

## 3. 结果（Results）

### 3.1 ⭐ Phase A mass-filter —— headline，11.5× 准确率 / 170× 提速

来源：`library_search_phase_a_2026-05-06.md` §1/§4/§5

| 指标 | v3 baseline | Phase A | Δ |
|---|---:|---:|---:|
| **id_acc (top-1)** | **6.25%**（8/128） | **72.07%**（92/128） | **+65.82 pp（11.5×）** |
| identification wall time | 5.14 h（18,511 s） | 1.85 min（111 s） | **170× faster** |
| 候选池缩减因子 | — | — | **5536×** |

**诊断**：Phase A 之后，identification 已不是后续 LLM 推理的瓶颈——瓶颈转移到 LLM prompt 设计与 verifier ground-truth 数据库覆盖。

### 3.2 sub6a rerank —— modcos 默认 top-1 最强，所有 rerank 负贡献

来源：`sub6a_real_id_rerank_summary.md` §5、`llm_reranker_v2.md`、`sirius_cfmid_rerank_v2.md`

9 个配置统一结论：**任何正交信号 rerank（MS-CLIP fusion / SIRIUS gate / CFM-ID cosine / LLM reranker）都让 top-1 id_acc 降 1–5 pp**。

| config | 主检索 | reranker | n_spec | pre-rerank | post-rerank | Δ pp |
|---|---|---|---:|---:|---:|---:|
| Phase 6.2 cfmid | modcos | weighted (CFM) | 358 | **74.58%** | 72.07% | −2.51 |
| Phase 6.2 full | modcos | weighted (SIRIUS+CFM) | 358 | 74.58% | 73.46% | −1.12 |
| Phase 6.2 sirius | modcos | weighted (SIRIUS) | 358 | 74.58% | 73.46% | −1.12 |
| Phase 6.3 B | msclip | weighted | 354 | 74.01% | 68.93% | **−5.08** |
| Phase 6.3 C | msclip | **LLM** | 358 | 74.02% | 68.99% | **−5.03** |

**根因 = GNPS leakage**：测试谱来自 RIKEN，但许多 RIKEN 谱被 GNPS 重新收录（InChIKey 一致 / source_id 不同，NM-002 leakage filter 无法完全过滤）→ modcos 实质在做 **library lookup**，74.58% 是**虚高的 in-distribution 数**。spike test 显示：真正 leakage-free OOD 上 modcos 会从 74.6% 跌到 ~6%。**在 in-distribution benchmark 上没有空间给正交信号**。

### 3.3 ⭐ CASMI OOD —— LLM reranker 是唯一正向 rerank 结果

来源：`casmi_2016_cat2_v1.md` §3、`casmi_llm_reranker_v1.md`、`casmi_llm_reranker_v1_appendixA_mrr.md`

| 指标（Δ vs MS-CLIP-only） | CASMI 2022 (n=170) | CASMI 2016 cat2 (n=208) | **Combined (n=378)** |
|---|---:|---:|---:|
| LLM top-1 提升 | +2.35 pp | +8.65 pp | **+5.82 pp** |
| LLM MRR (full) | +0.0226 | +0.0618 | **+0.0442 / +14% rel.** |
| Wilcoxon p (LLM vs msclip) | 0.087 | 3.2×10⁻⁵ | **1.4×10⁻⁵** ✓ Bonferroni-stable |

- combined top-1：msclip-only **21.96%** → LLM **27.78%**。
- **MSAgent 论文 +10% MRR claim 被复现并超越**。
- **为什么 OOD 上 LLM 成功而 weighted 失败**：formula-restricted (2022) / mass-tolerant (2016) pool 下 modcos=mass_match=SIRIUS gate 几乎都成常数，weighted 只剩 0.3·CFM_cosine 噪声；LLM 逐条读原始证据（SMILES 拓扑 / peaks / mass loss）才能在 OOD 提取信号。

> 对照：in-distribution（sub6a，§3.2）rerank 全负；OOD（CASMI）LLM reranker 显著正——**rerank 的价值只在 leakage-free OOD 上才显现**。

### 3.4 Layer F peak-mechanistic —— 量化 LLM 机制幻觉

来源：`sub6a_real_id_rerank_summary.md` §7、`layerf_loop_closed.md`

| verdict | n（/858） | % |
|---|---:|---:|
| SUPPORTED | 0 | 0% |
| **CONTRADICTED** | **699** | **81.5%** |
| UNVERIFIABLE | 159 | 18.5% |

**典型 case**：LLM 把 CFM-ID 预测峰 m/z 109.0648 当成实验观测写进 narrative（"directly match the two most intense experimental peaks … testosterone A-ring enone fragmentation"），Layer F 一查 spectrum ±5 ppm 内根本没这条峰 → CONTRADICTED。**这首次客观数字化了 LLM 多工具推理的幻觉率**，并直接解释 §3.2 里 CFM-cosine 30% 权重为何 mis-calibrated（预测谱本身与实测谱相似度就低，30% 权重只会把正确候选往下拉）。

---

## 4. 已知限制（Limitations）

1. **GNPS leakage（最重要）**：in-distribution 评测里 modcos 74.58% 虚高，rerank 无空间；**未在 leakage-free OOD benchmark 上验证 SIRIUS/CFM 的真实价值**（CASMI 部分缓解，但 sub6a 仍受限）。
2. **MS-CLIP ion-vocab 不全**：25/459 spectra（5.4%）adduct 不在 MS-CLIP 词表（如 `[M+NH3+H]+`、`[M-H2O-H]-`）→ fallback modcos-only。
3. **library 覆盖洞**：~10/37 残留失败 spectra 过不了 Phase A mass filter（如 Sulindac 代谢物在 GNPS 稀疏）→ 需 MassBank/MoNA 扩库或 de-novo `molecule_gen`。
4. **SIRIUS 学术许可 session 过期**：90–120 min token 失效（已用 auto-relogin 缓解，但增加复现复杂度）。
5. **CFM-ID 负离子准确率低**（~20% spike test）；sub6a ~40% 负离子谱图，CFM 贡献集中在正离子。
6. **Layer F per-claim spectrum routing 未实现**：永远查 `differential_spectra[0]`，多 spectrum task 中跨谱 claim 会误判（后续候选）。

---

## 5. 复现方式（Reproduction）

### 5.0 环境

```bash
cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2
./scripts/concord/setup_metagent_v2_env.sh      # symlink chebi/metanetx sqlite
export METAGENT_LLM_PROVIDER=minimax MINIMAX_API_KEY=<key>     # narrative LLM
# LLM reranker / verifier extractor 用 Opus-4-7（OpenAI-compat relay）：
export METAGENT_OPENAI_API_KEY=<key> METAGENT_OPENAI_MODEL=claude-opus-4-7
# rerank 需 SIRIUS：export METAGENT_SIRIUS_USER=... METAGENT_SIRIUS_PASS=...
# CFM-ID udocker 服务监听 http://127.0.0.1:8088
```

### 5.1 sub6a real-id 端到端（Phase A 识别 + verifier）

来源：`sub6_metagent_final_summary_2026-05-06.md` §10.3

```bash
# 1) baseline：Phase A 识别 + narrative
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6a --id-strategy library_search --mass-tolerance-ppm 10 \
    --output-suffix _phase_a --out-dir data/eval/sub6        # ~15 min

# 2) verifier（Opus-4-7，含 Layer F）
PYTHONPATH=. python scripts/eval_sub6/grade_with_verifier.py \
    --narratives data/eval/sub6/sub6a_narratives_phase_a.jsonl \
    --tasks data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
    --out data/eval/sub6/<repro>_verdicts.jsonl --track sub6a_real_id   # ~10 min

# 3) 聚合
PYTHONPATH=. python scripts/eval_sub6/aggregate_verifier.py \
    --verdicts data/eval/sub6/<repro>_verdicts.jsonl \
    --narratives data/eval/sub6/sub6a_narratives_phase_a.jsonl \
    --tasks data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
    --track sub6a_real_id --out-dir results/<repro>
```

### 5.2 CASMI（OOD structure id + rerank 对比）

来源：`casmi_2016_cat2_v1.md` §8

```bash
# MS-CLIP-only baseline
PYTHONPATH=. python scripts/eval_sub6/run_casmi.py \
    --casmi 2016_cat2 --reranker none --primary-retriever msclip \
    --rerank-top-k 5 --dump-ranks --out-dir data/eval/casmi/<repro>_msclip_only   # ~45 min

# LLM rerank（CFM-ID 证据，Opus-4-7）
PYTHONPATH=. python scripts/eval_sub6/run_casmi.py \
    --casmi 2016_cat2 --reranker llm --primary-retriever msclip \
    --rerank-with cfmid --rerank-top-k 5 --narrative-llm opus47 --dump-ranks \
    --out-dir data/eval/casmi/<repro>_llm_reranker        # ~3.5 h, ~$5

# 统计（top-k / MRR / Wilcoxon）
PYTHONPATH=. python scripts/eval_sub6/casmi_combined_topk_mrr.py
```

### 5.3 关键脚本 / 代码位置

| 路径 | 职责 |
|---|---|
| `scripts/eval_sub6/run_baseline.py` | sub6 baseline（`--sub6a`/`--sub6b`/`--both`） |
| `scripts/eval_sub6/run_casmi.py` | CASMI 2022/2016 端到端 runner |
| `scripts/eval_sub6/casmi_combined_topk_mrr.py` / `casmi_topk_mrr.py` | top-k / MRR + Wilcoxon |
| `evaluation/sub6/identification.py` | spectrum 鉴定（library_search / perfect_id） |
| `evaluation/sub6/rerank.py` | SIRIUS+CFM-ID rerank（auto-relogin） |
| `evaluation/sub6/llm_reranker.py` | LLM-as-reranker |
| `verifier/agent.py::verify()` | 4-stage verifier 主入口（spectrum） |
| `verifier/layers/peak_mechanistic.py` | Layer F |

### 5.4 cost 核对（死命令）

MiniMax / Opus 都是远程 API，**禁说 "$0 local"**，实测 cost 查 `logs/llm_calls.jsonl`。

---

## 6. 关键 finding（Stage 1）

1. **rerank 在 in-distribution 上是 negative result**（sub6a）：modcos 默认 top-1（74.58%）已近最优，所有正交 rerank 降 1–5 pp，根因 GNPS leakage。
2. **identification 不是 LLM 推理瓶颈**：Phase A 把 id_acc 拉高 11.5×，但下游 LLM 推理几乎不动——瓶颈在 prompt + verifier KB 覆盖。
3. **LLM-as-reranker 在 OOD 上有效**（CASMI n=378：+5.82 pp top-1 / +14% MRR / p=1.4×10⁻⁵，Bonferroni-stable），复现并超越 MSAgent +10% MRR claim；而 weighted reranker 在同数据上无效。
4. **verifier 量化 LLM 机制幻觉**（Layer F：858 peak claim 中 81.5% CONTRADICTED）——独立 finding，并机制性解释 CFM-cosine 权重 mis-calibration。

---

## 7. 关键文件索引

| 类别 | 文件 |
|---|---|
| Phase A mass-filter | `reports/eval/library_search_phase_a_2026-05-06.md` |
| sub6a rerank 总结 | `reports/eval/sub6a_real_id_rerank_summary.md` |
| SIRIUS+CFM rerank | `reports/eval/sirius_cfmid_rerank_v2.md`、`reports/eval/msclip_ablation_v2.md` |
| LLM reranker | `reports/eval/llm_reranker_v2.md`、`reports/eval/conditional_rerank_v2.md` |
| CASMI OOD | `reports/eval/casmi_2016_cat2_v1.md`、`reports/eval/casmi_llm_reranker_v1.md`、`reports/eval/casmi_ood_v1.md` |
| Layer F 闭环 | `reports/eval/layerf_loop_closed.md` |
| sub6 评测体系 | `reports/eval/sub6_metagent_final_summary_2026-05-06.md` |
| 架构 / verify() | `reports/project_architecture_tools_verifier_summary_2026-04-27.md`、`docs/ARCHITECTURE.md` |
