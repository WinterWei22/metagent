# Stage 1 —— 单谱代谢物结构识别（方法 · 数据 · 结果 · 复现）

> 整理日期：2026-06-30 · 分支 `metagent-v3-benchmark`
> 范围：**Stage 1 = 单谱结构识别**——输入一张 MS/MS 谱 → 输出按证据排名的候选**结构**（SMILES/InChIKey）+ 峰归属 + PMID。
> verifier 入口 `verifier/agent.py::verify()`（spectrum entry，吃 `IdentificationReport`），验证结构/峰/ID/PMID 级 claim。
> 评测集：**sub6a (real-id)** 与 **CASMI (OOD)**。
> ⚠️ 不含 Stage 2（`verify_sub6()` / 4-shape grammar / 富集 4 层 / narrative）——见同目录 Stage1+2 文档。
> 详报源：`reports/eval/*`（library_search_phase_a / sub6a_real_id_rerank / casmi_* / sirius_cfmid_rerank / llm_reranker / layerf_loop_closed）。

---

## 1. 方法（Method）

### 1.1 识别 pipeline（端到端）
```
MS/MS 谱 (precursor m/z + peak 数组)
  ├─[Phase A] precursor-mass 窗预筛 ±10 ppm：GNPS 622,632 候选 → 平均 ~89（5536× 缩减）
  ├─[library_search] modcos (modified cosine vs GNPS ref) +可选 MS-CLIP → top-20
  ├─[可选 rerank head]（per-spectrum 正交信号）
  │     SIRIUS 分子式 gate · CFM-ID 预测谱 cosine · 可选 LLM reranker (Opus-4-7)
  │     evidence_score = 0.4·modcos + 0.3·pred_cosine + 0.2·mass_match + 0.1·pathway
  └─ ranked top-1 SMILES/InChIKey + 峰证据
        └─[verify() + Layer F peak_mechanistic] 逐条核 peak claim vs 实测谱 ±5 ppm
```
**关键决策**：
- mass tolerance **±10 ppm**（HRMS 甜点；5ppm 过严、20ppm 引回高置信错误）。
- library_search 默认 top-1（modcos）是本 benchmark 最强单信号；所有 rerank 反降 1–5pp（根因 GNPS leakage，§3.2）。

### 1.2 识别准确率定义（重要）
`correct_top1 = (predicted_smiles → InChIKey **first-block 14 字符**) == (谱自带 inchikey_first_block)`
（`evaluation/sub6/identification.py:557`）——比的是 **2D 连接骨架**，**忽略立体化学/电荷层**；不是精确全 InChIKey,也不是 database ID。这是 MS 鉴定的标准"结构级"口径。

### 1.3 7-tool 结构管线（`docs/TOOL_CONTRACTS.md`）
| tool | 职责 |
|---|---|
| `library_search` | 谱-库匹配生成候选（`mass_tolerance_ppm=10`,`top_k=20`） |
| `spectrum_predict`/CFM-ID | 候选 SMILES → 预测 MS/MS（udocker，disk-cached） |
| SIRIUS | 分子式 + fragmentation tree（本地 6.3.4，auto-relogin） |
| `molecule_gen` | library miss 时生成式 SMILES |
| `metabolite_info` | InChIKey/SMILES/formula（HMDB/PubChem） |
| `pathway_context` | 通路关联（evidence 0.1 项） |
| `literature` | PMID（PubMed/Europe PMC） |

### 1.4 verify() + Layer F
`verify(llm_output, source_report: IdentificationReport) -> VerifiedIdentification`，4-stage：抽 atomic claim → 分类 → 分层验证 → 可选 rewrite。**Layer F (peak_mechanistic)** 触发于「含 m/z 数值 + fragment/loss 关键词」的 claim，判定 spectrum ±5ppm 内是否真有该峰——量化 LLM 把"工具预测峰"当"实验观测峰"的机制幻觉。

---

## 2. 数据（Data）

### 2.1 sub6a (real-id) v2 —— `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`
| 维度 | 规模 |
|---|---:|
| Tasks | 38 |
| Spectra/task (mean) | 12.1（4–23） |
| **Total spectra** | **459** |
| Phase A 后 ≥1 候选 | 358（78%） |
| 0 候选 (fail-silent) | ~101（22%） |
| GNPS 候选池 | 622,632 → Phase A 后 ~89/谱 |

### 2.2 CASMI（OOD 结构识别）
| | CASMI 2022 | 2016 cat2 | Combined |
|---|---:|---:|---:|
| Spectra | 170 | 208 | **378** |
| Ion mode | 100% pos | 127 pos/81 neg | 混合 |
| Pool | PubChem formula-restricted | per-challenge mass-tolerant | 混合 |

### 2.3 Peak evidence 语料
358 peak-evidence files（每张 signal-bearing 谱）· SIRIUS top-1 100% · CFM-ID 100%（358/358）· Layer F dispatched **858** peak claims。

---

## 3. 结果（Results）

### 3.1 ⭐ Phase A mass-filter（headline）
来源 `library_search_phase_a_2026-05-06.md`
| 指标 | v3 baseline | Phase A | Δ |
|---|---:|---:|---:|
| **id_acc (top-1)** | 6.25%（8/128） | **72.07%**（92/128） | **+65.82pp（11.5×）** |
| identification wall | 5.14 h | 1.85 min | **170× faster** |
| 候选池缩减 | — | — | **5536×** |

诊断：Phase A 后 identification 已非瓶颈,瓶颈转移到 LLM prompt 与 verifier KB 覆盖。

### 3.2 sub6a rerank —— modcos 默认最强,所有 rerank 负贡献
| config | 主检索 | reranker | pre | post | Δpp |
|---|---|---|---:|---:|---:|
| 6.2 cfmid | modcos | weighted(CFM) | **74.58%** | 72.07% | −2.51 |
| 6.2 full | modcos | weighted(SIRIUS+CFM) | 74.58% | 73.46% | −1.12 |
| 6.3 B | msclip | weighted | 74.01% | 68.93% | **−5.08** |
| 6.3 C | msclip | **LLM** | 74.02% | 68.99% | **−5.03** |

**根因 = GNPS leakage**：测试谱(RIKEN)许多被 GNPS 重新收录（InChIKey 一致），modcos 实质在做 library lookup，74.58% 是虚高 in-distribution 数；spike test 显示真 OOD 上 modcos 跌到 ~6%。**in-distribution 上没有空间给正交信号**。

### 3.3 ⭐ CASMI OOD —— LLM reranker 唯一正向
| Δ vs MS-CLIP-only | 2022 (n=170) | 2016cat2 (n=208) | **Combined (n=378)** |
|---|---:|---:|---:|
| LLM top-1 | +2.35pp | +8.65pp | **+5.82pp**（21.96%→27.78%） |
| LLM MRR | +0.0226 | +0.0618 | **+0.0442 / +14% rel** |
| Wilcoxon p | 0.087 | 3.2e-5 | **1.4e-5** ✓ Bonferroni-stable |

复现并超越 MSAgent +10% MRR claim。**rerank 价值只在 leakage-free OOD 才显现**（in-dist 全负 / OOD LLM 显著正）。

### 3.4 Layer F —— 量化 LLM 机制幻觉
| verdict | n/858 | % |
|---|---:|---:|
| SUPPORTED | 0 | 0% |
| **CONTRADICTED** | 699 | **81.5%** |
| UNVERIFIABLE | 159 | 18.5% |

典型：LLM 把 CFM-ID 预测峰 m/z 109.0648 当实验观测写进 narrative,Layer F 查 ±5ppm 内无此峰 → CONTRADICTED。**首次客观数字化多工具推理幻觉率**,并解释 §3.2 中 CFM-cosine 30% 权重为何 mis-calibrated。

---

## 4. 已知限制
1. **GNPS leakage（最重要）**：in-dist modcos 74.58% 虚高,rerank 无空间;真值待 leakage-free OOD 验证。
2. MS-CLIP ion-vocab 不全（25/459 谱 adduct 不在词表 → fallback modcos）。
3. library 覆盖洞（~10 谱过不了 Phase A → 需 MassBank/MoNA 扩库或 de-novo）。
4. SIRIUS 学术许可 90–120min 过期（auto-relogin 缓解）。
5. CFM-ID 负离子准确率低（~20% spike）；sub6a ~40% 负离子。
6. Layer F per-claim spectrum routing 未实现（永远查 `differential_spectra[0]`）。

---

## 5. 复现脚本

### 5.0 环境
```bash
cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2
./scripts/concord/setup_metagent_v2_env.sh          # symlink chebi/metanetx sqlite
export METAGENT_LLM_PROVIDER=minimax MINIMAX_API_KEY=<key>          # narrative LLM
export METAGENT_OPENAI_API_KEY=<key> METAGENT_OPENAI_MODEL=claude-opus-4-7   # reranker/verifier extractor
```

### 5.1 sub6a real-id 端到端（Phase A 识别 + verifier）
```bash
# 1) baseline：Phase A 识别 + narrative（~15 min）
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6a --id-strategy library_search --mass-tolerance-ppm 10 \
    --output-suffix _phase_a --out-dir data/eval/sub6
# 2) verifier（Opus-4-7,含 Layer F,~10 min）
PYTHONPATH=. python scripts/eval_sub6/grade_with_verifier.py \
    --narratives data/eval/sub6/sub6a_narratives_phase_a.jsonl \
    --tasks data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
    --out data/eval/sub6/<repro>_verdicts.jsonl --track sub6a_real_id
# 3) 聚合
PYTHONPATH=. python scripts/eval_sub6/aggregate_verifier.py \
    --verdicts data/eval/sub6/<repro>_verdicts.jsonl \
    --narratives data/eval/sub6/sub6a_narratives_phase_a.jsonl \
    --tasks data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
    --track sub6a_real_id --out-dir results/<repro>
```

### 5.2 CASMI（OOD 结构识别 + rerank 对比）
```bash
# MS-CLIP-only baseline（~45 min）
PYTHONPATH=. python scripts/eval_sub6/run_casmi.py \
    --casmi 2016_cat2 --reranker none --primary-retriever msclip \
    --rerank-top-k 5 --dump-ranks --out-dir data/eval/casmi/<repro>_msclip_only
# LLM rerank（CFM-ID 证据,Opus-4-7,~3.5h ~$5）
PYTHONPATH=. python scripts/eval_sub6/run_casmi.py \
    --casmi 2016_cat2 --reranker llm --primary-retriever msclip \
    --rerank-with cfmid --rerank-top-k 5 --narrative-llm opus47 --dump-ranks \
    --out-dir data/eval/casmi/<repro>_llm_reranker
# 统计（top-k/MRR/Wilcoxon）
PYTHONPATH=. python scripts/eval_sub6/casmi_combined_topk_mrr.py
```

### 5.3 关键脚本 / 代码
| 路径 | 职责 |
|---|---|
| `scripts/eval_sub6/run_baseline.py` | sub6 baseline（`--sub6a`/`--sub6b`/`--both`） |
| `scripts/eval_sub6/run_casmi.py` | CASMI 端到端 runner |
| `scripts/eval_sub6/casmi_combined_topk_mrr.py` | top-k/MRR + Wilcoxon |
| `evaluation/sub6/identification.py` | spectrum 鉴定（library_search/perfect_id；`correct_top1` 定义） |
| `evaluation/sub6/rerank.py` · `llm_reranker.py` | SIRIUS+CFM rerank / LLM-as-reranker |
| `verifier/agent.py::verify()` + `verifier/layers/peak_mechanistic.py` | spectrum verifier + Layer F |

> cost 死命令：MiniMax/Opus 均远程 API,禁说 "$0 local",实测查 `logs/llm_calls.jsonl`。
