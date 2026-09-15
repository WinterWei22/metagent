# Stage 1 结果分析（一）—— 鉴定性能 + reranking 前后统计

> 日期：2026-06-30 · 分支 `metagent-v3-benchmark`
> 范围：sub6a (real-id)、CASMI 2016 cat2、CASMI 2022 三个评测集的**单谱结构识别准确率**，及 **reranking 前后的配对统计差异**。
> 准确率口径：top-N = predicted SMILES→InChIKey **first-block(14 字符 2D 骨架)** 命中 GT 骨架（非全 InChIKey/非 DB ID）。
> 数据源：`data/eval/casmi/{2016_cat2,2022}_{msclip_only,conditional,llm_reranker[_v2]}/casmi_identifications.jsonl`、`reports/eval/sub6a_real_id_rerank_summary.md`、`reports/eval/library_search_phase_a_2026-05-06.md`。
> 复现：`scripts/eval_sub6/casmi_combined_topk_mrr.py`（top-k/MRR/Wilcoxon）+ 本文附录脚本（McNemar）。

---

## 1. 评测集规模

| 评测集 | 谱数 (n) | 候选池 | ion mode | 性质 |
|---|---:|---|---|---|
| **sub6a (real-id)** | 459（候选-bearing 358） | GNPS 622k → Phase A ±10ppm 后 ~89/谱 | ~60% pos / 40% neg | **in-distribution**（GNPS leakage） |
| **CASMI 2016 cat2** | 208 | per-challenge mass-tolerant CSV | 127 pos / 81 neg | **OOD** |
| **CASMI 2022** | 170 | PubChem formula-restricted | 100% pos | **OOD** |

---

## 2. 鉴定性能（identification accuracy）

### 2.1 CASMI —— top-k + MRR（3 retriever 配置）
来源：`casmi_combined_topk_mrr.py`（reachable MRR = 仅在候选池可达 GT 的子集上）。

| 配置 | 评测集 | n | top-1 | top-3 | top-5 | top-20 | MRR | MRR(reach) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| msclip-only | CASMI 2022 | 170 | 13.53% | 22.94% | 28.24% | 43.53% | 0.2045 | 0.4698 |
| msclip-only | CASMI 2016 | 208 | 28.85% | 47.60% | 55.29% | 75.96% | 0.4059 | 0.5344 |
| msclip-only | **combined** | 378 | **21.96%** | 36.51% | 43.12% | 61.38% | 0.3153 | 0.5138 |
| weighted | CASMI 2022 | 170 | 13.53% | 25.29% | 28.24% | 43.53% | 0.2114 | 0.4856 |
| weighted | CASMI 2016 | 208 | 27.88% | 48.56% | 55.29% | 75.96% | 0.4022 | 0.5295 |
| weighted | **combined** | 378 | **21.43%** | 38.10% | 43.12% | 61.38% | 0.3164 | 0.5155 |
| **LLM reranker** | CASMI 2022 | 170 | 15.88% | 26.47% | 28.24% | 43.53% | 0.2224 | 0.5110 |
| **LLM reranker** | CASMI 2016 | 208 | **37.50%** | 50.96% | 55.29% | 75.96% | 0.4611 | 0.6071 |
| **LLM reranker** | **combined** | 378 | **27.78%** | 39.95% | 43.12% | 61.38% | 0.3538 | 0.5764 |

> top-5/top-20 在三配置间相同：rerank 只在 top-5 head 内重排,不改变 head 成员,故只影响 top-1/top-3 与 MRR。

### 2.2 sub6a —— top-1
来源：`sub6a_real_id_rerank_summary.md` + `library_search_phase_a_2026-05-06.md`。sub6a 无 rank-dump,仅 top-1 可统计。

| 口径 | 分母 | top-1 id_acc |
|---|---:|---:|
| 候选-bearing（Phase A 后有 ≥1 候选） | 358 | **74.58%**（modcos 默认,最强单信号） |
| 全部谱（含 Phase A 0 候选） | 459 | 67.10%（baseline config A） |
| Phase A 子集（library_search_phase_a 口径） | 128 | 72.07%（vs v3 baseline 6.25%，**11.5×**） |

---

## 3. Reranking 前后性能差异（配对统计）

两类检验：**McNemar**（配对二元 top-1 命中,exact binomial on 不一致对 gained/lost）+ **Wilcoxon**（配对 reciprocal-rank,捕捉 rank 改善,Bonferroni α=0.0167）。

### 3.1 CASMI —— top-1 McNemar（配对 by spectrum_id）

| 评测集 | 对比 | n | acc 前 | acc 后 | gained | lost | p (McNemar) | 显著 |
|---|---|---:|---:|---:|---:|---:|---:|:--:|
| CASMI 2016 | msclip → **LLM** | 208 | 28.85% | **37.50%** | 20 | 2 | **1.21e-04** | ✓\*\*\* |
| CASMI 2016 | weighted → **LLM** | 208 | 27.88% | 37.50% | 22 | 2 | **3.59e-05** | ✓\*\*\* |
| CASMI 2016 | msclip → weighted | 208 | 28.85% | 27.88% | 16 | 18 | 0.8642 | ✗ |
| CASMI 2022 | msclip → LLM | 170 | 13.53% | 15.88% | 8 | 4 | 0.3877 | ✗ |
| CASMI 2022 | msclip → weighted | 170 | 13.53% | 13.53% | 8 | 8 | 1.0000 | ✗ |
| **combined** | msclip → **LLM** | 378 | 21.96% | **27.78%** | 28 | 6 | **1.95e-04** | ✓\*\*\* |
| **combined** | weighted → **LLM** | 378 | 21.43% | 27.78% | 30 | 6 | **6.96e-05** | ✓\*\*\* |

### 3.2 CASMI —— reciprocal-rank Wilcoxon（含 rank 改善）
来源：`casmi_combined_topk_mrr.py`，Bonferroni α=0.0167。

| 评测集 | 对比 | n | B>A | A>B | tied | meanΔ RR | Wilcoxon p | 显著 |
|---|---|---:|---:|---:|---:|---:|---:|:--:|
| CASMI 2016 | msclip → LLM | 208 | 26 | 8 | 174 | +0.0552 | **0.0002** | ✓\* |
| CASMI 2016 | weighted → LLM | 208 | 30 | 4 | 174 | +0.0589 | **2.60e-05** | ✓\* |
| CASMI 2022 | msclip → LLM | 170 | 9 | 6 | 155 | +0.0179 | 0.1092 | ✗ |
| **combined** | msclip → LLM | 378 | 35 | 14 | 329 | +0.0384 | **0.0001** | ✓\* |
| **combined** | weighted → LLM | 378 | 38 | 9 | 331 | +0.0374 | **0.0002** | ✓\* |
| combined | msclip → weighted | 378 | 24 | 37 | 317 | +0.0011 | 0.3556 | ✗ |

### 3.3 sub6a —— rerank 前后 top-1 McNemar（全部负向）
来源：`sub6a_real_id_rerank_summary.md` §pre/post 配对表（pre = library_search 默认 top-1，post = reranker 选的 top-1）。

| 配置 | n | pre | post | Δpp | gained | lost | p (McNemar) | 显著 |
|---|---:|---:|---:|---:|---:|---:|---:|:--:|
| 6.2 cfmid (modcos+CFM) | 358 | 74.58% | 72.07% | −2.51 | 16 | 25 | 0.2110 | ✗ |
| 6.2 full (modcos+SIRIUS+CFM) | 358 | 74.58% | 73.46% | −1.12 | 16 | 20 | 0.6177 | ✗ |
| 6.2 sirius (modcos+SIRIUS) | 358 | 74.58% | 73.46% | −1.12 | 6 | 10 | 0.4545 | ✗ |
| 6.3 B (msclip-primary + weighted) | 354 | 74.01% | 68.93% | **−5.08** | 13 | 31 | **0.0096** | ✓\*\* |
| 6.3 C (msclip-primary + LLM) | 358 | 74.02% | 68.99% | **−5.03** | 13 | 31 | **0.0096** | ✓\*\* |

---

## 4. 关键结论

1. **CASMI (OOD)：LLM reranker 是唯一显著正向的 rerank**。combined top-1 21.96%→**27.78%**（+5.82pp，McNemar p=1.95e-4；RR Wilcoxon p=1e-4），由 CASMI 2016 主导（p<1e-3）；CASMI 2022 方向一致但 n 小、效应小、**不显著**（p=0.39）。
2. **weighted reranker ≈ 无效**：weighted vs msclip 在 top-1（p=0.86）与 RR（p=0.36）均不显著；formula/mass-restricted pool 下 modcos=mass_match=SIRIUS gate 近常数，weighted 只剩 CFM-cosine 噪声。
3. **sub6a (in-distribution)：所有 rerank 负向**。modcos-preserving（cfmid/sirius/full）−1～−2.5pp **不显著**（p>0.2）；**切 msclip-primary 则显著变差 −5pp（p<0.01）**——根因 GNPS leakage 让 modcos 实质做 library lookup，74.58% 虚高，任何换主检索/正交信号都只会破坏它。
4. **方向对立**：同一 LLM reranker,OOD（CASMI 2016）显著 +8.65pp、in-distribution（sub6a msclip-primary）显著 −5pp——**rerank 价值只在 leakage-free OOD 才显现**。

---

## 5. 方法 / 统计说明
- **McNemar**：配对二元结局（top-1 命中），对不一致对 (gained b, lost c) 做 exact two-sided binomial test（`scipy.stats.binomtest(min(b,c), b+c, 0.5)`），小样本下比卡方近似稳。
- **Wilcoxon signed-rank**：配对 reciprocal rank（1/rank_of_correct，不可达计 0），`zero_method="wilcox"`，Bonferroni α=0.0167（3 组对比）。
- **配对方式**：CASMI 按 `spectrum_id` 对齐两配置的 `correct_top1`；sub6a 用报告 §pre/post 表的 gained/lost（同一批谱的 pre vs post top-1）。
- **显著性标注**：McNemar p<0.05 记 ✓；Wilcoxon 经 Bonferroni（α=0.0167）。
- 附录脚本：`scripts/eval_sub6/casmi_combined_topk_mrr.py`（top-k/MRR/Wilcoxon）；McNemar 由本文 §3 配对计算（gained/lost → exact binomial）。

> ⚠ sub6a 缺 rank-dump,仅 top-1 可统计；CASMI 有完整 `ranked_candidates` 故可出 top-k/MRR。
> cost 死命令：CASMI LLM reranker 实测 ~$5/配置（远程 Opus-4-7），查 `logs/llm_calls.jsonl`。
