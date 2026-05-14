# Track PHASE 6.7-D — MassSpecGym (MSG) OOD validation with specialized MS-CLIP checkpoint

**Session ID:** `track_PHASE6_7D_msg`
**Branch:** `feature/msg-llm-reranker`(off `feature/casmi-llm-reranker`)
**Estimated work:** 2 days wall
**Predecessors:**
- `reports/eval/casmi_llm_reranker_v1_appendixA_mrr.md`(Phase 6.7-A,LLM-as-reranker +11% MRR)
- `ref_paper/MSAgent.pdf`(对照)

---

## Why this matters

Phase 6.7 / 6.7-A 在 CASMI 上验证 LLM-as-reranker +11% MRR(MSAgent 同档),但用的是**默认 MS-CLIP checkpoint** (`v4_spectraverse_20260428` 训练于 SpectraVerse,跟 CASMI 部分重叠)。

MassSpecGym (MSG) 是一个**独立 benchmark**,数据 100% 不在 SpectraVerse 训练集。**Phase 6.7-D 用 MSG-specialized MS-CLIP checkpoint + MSG 数据**,测三件事:

1. **跨 checkpoint generalization**:LLM-as-reranker 跟 MS-CLIP 模型的 prior 是否绑定?换 checkpoint 后还 +11% MRR 吗?
2. **真 OOD**:MSG 候选池是公开 PubChem 子集,无 reference spectra。这是**比 CASMI 更纯的 OOD setting**。
3. **两种候选池对比**:formula-restricted vs mass-window,paper 多一维 ablation。

3 个 benchmark(CASMI 2022 / CASMI 2016 cat2 / MSG) × 3 config(msclip_only / weighted / llm)= 完整 paper §OOD validation matrix。

---

## Hard scope boundaries

**You MAY:**
- 写 `evaluation/sub6/msg_loader.py` 解析 MSG labels.tsv + splits + retrieval json
- 在 `tools/library_search/model.py` 加 `--msclip-checkpoint` CLI / env var(允许 runtime 切 checkpoint)
- 跑 LLM-as-reranker on MSG (msg-trained checkpoint + Opus-4-7)
- 跑 2 个 candidate pool variants(formula-restricted + mass-window)
- 复用 Phase 6.7-A 全部 LLM-as-reranker 基础设施(schema + parser + ranked_indices)
- 写报告 `reports/eval/msg_v1.md`

**You MAY NOT:**
- 修 LLM-as-reranker 算法或 prompt(锁定)
- 修 verifier 任何代码
- 重跑 Phase 6.7 / 6.7-A / 6.7-C CASMI 数据
- 训练新 MS-CLIP checkpoint(用 user 提供的现成 ckpt)

---

## 现有数据状态(user 已确认)

```
MS-CLIP checkpoint (MSG-specialized):
  /home/weiwentao/workspace/reconstruct/ms-pred/results/chemformer_v4_large_ep3unfroze_20260420_235720/version_0/best.ckpt

MSG 数据:
  /home/weiwentao/workspace/ms-pred/data/spec_datasets/msg/
  ├── labels.tsv                                     ← GT 列表
  ├── splits/split_msg.tsv                           ← train/val/test split
  └── retrieval/
      ├── MassSpecGym_retrieval_candidates_formula.json  ← formula-restricted (paper main)
      └── MassSpecGym_retrieval_candidates_mass.json     ← mass-window (richer pool)
```

---

## Background reading

1. `evaluation/sub6/casmi_loader.py`(类比写 msg_loader,follow 同 schema)
2. `tools/library_search/model.py`(看 MS-CLIP checkpoint 怎么加载,加 override)
3. `scripts/eval_sub6/run_casmi.py`(看 CASMI runner 怎么调,msg 仿照)
4. `reports/eval/casmi_llm_reranker_v1_appendixA_mrr.md`(reference setup)
5. User-supplied MSG checkpoint dir(看 hyperparams / config 文件确认是否 chemformer 而非 ms-clip 标准变体)
6. MSG labels.tsv 头几行(看 schema)

In your first response,确认:
- `labels.tsv` schema(预期含 spec_id / smiles / inchikey / formula / ionization)
- `split_msg.tsv` 怎么标 test set(取 test split 跑评估,不用 train/val)
- Test set spec 数量(预期几百到几千)
- 候选 json 结构:formula-restricted 和 mass-window 各每 spec 多少候选?
- MSG-trained checkpoint 的 vocabulary 是否含 negative mode adduct(看 ms-pred config)
- 估算 wall(test set N spec × Opus-4-7 ~15s/call)

不要写代码或跑命令,直到 confirm。

---

## Key design decisions

### D1: MSG checkpoint runtime switch

当前 `tools/library_search/model.py` 的 MSClipRetriever 用环境变量 `METAGENT_MSCLIP_CKPT` 控制 checkpoint path。**不动算法代码**,只在 `run_msg.py` 启动前 set 这个 env var:

```bash
export METAGENT_MSCLIP_CKPT=/home/weiwentao/workspace/reconstruct/ms-pred/results/chemformer_v4_large_ep3unfroze_20260420_235720/version_0/best.ckpt
```

如果 env var 不存在,加(看 `tools/library_search/model.py` 是不是 hardcoded 路径)。

### D2: Test split 限定

只跑 MSG test split,不跑 train / val。从 `split_msg.tsv` 提 test spec_id list 给 loader。

### D3: 两个候选池都跑

`formula` (跟 CASMI 同 protocol)和 `mass` (更宽松)各跑一遍。**这是 paper §OOD ablation 关键**:
- formula 上 +X% MRR (Phase 6.7 paradigm 复现)
- mass 上 +Y% MRR (放宽 candidate 多样性,看 LLM 优势是否放大)

如果 mass > formula → paper claim "LLM rerank 价值随 candidate pool 多样性提升"
如果 mass < formula → 反过来,paper 写 "constrained pool 反而让 LLM 信号更明显"

3 种结果都有 finding。

---

## Deliverables

### D1 — MSG loader(0.5 day)

`evaluation/sub6/msg_loader.py`:

```python
def load_msg_test(
    labels_tsv: Path,
    split_tsv: Path,
    candidates_json: Path,  # formula 或 mass
    spec_dir: Path,         # 如果 spec files 在别处,user 确认路径
) -> list[dict]:
    """
    Returns task list, schema 跟 CASMI 2022 / 2016 兼容
    (differential_spectra + ground_truth_signal_compounds)
    """
```

加 unit test:loader 产出 test split 全部 task,每 task 有 GT InChIKey + 候选。

### D2 — MSG runner(2 hours)

`scripts/eval_sub6/run_msg.py`(类比 `run_casmi.py`):

加 CLI:
- `--msg-candidates {formula,mass}`
- `--msclip-checkpoint <path>`(覆盖 env var)
- 其他 CLI 跟 run_casmi 完全一致

加 unit test:CLI 路由 + checkpoint env var 正确传到 library_search。

### D3 — 3 × 2 = 6 个 config 跑(后台,1 day wall)

```bash
export METAGENT_MSCLIP_CKPT=/home/weiwentao/workspace/reconstruct/ms-pred/results/chemformer_v4_large_ep3unfroze_20260420_235720/version_0/best.ckpt

# Formula-restricted candidate pool
for reranker in none conditional llm; do
    python scripts/eval_sub6/run_msg.py \
        --msg-candidates formula \
        --reranker $reranker \
        ...
        --out-dir data/eval/msg/formula_${reranker}/
done

# Mass-window candidate pool
for reranker in none conditional llm; do
    ... --msg-candidates mass --out-dir data/eval/msg/mass_${reranker}/ ...
done
```

6 个 config × test set 跑。LLM cost 估算:
- 假设 MSG test ~500 spec:500 × 2 (formula+mass) × Opus-4-7 ~15s = ~$10-15

如果 test > 1000 spec,只跑 random subset 500(报告里写明 + 加 seed)。

### D4 — 三 benchmark 联合分析(0.5 day)

复用 `casmi_topk_mrr.py` 改成 `multi_benchmark_topk_mrr.py`:

```csv
benchmark,candidate_pool,reranker,n,top1_acc,top5_acc,mrr,mrr_rel_delta_vs_msclip
casmi_2022,formula,msclip_only,170,13.53%,28.24%,0.2045,—
casmi_2022,formula,llm,170,15.88%,28.24%,0.2271,+11.0%
casmi_2016_cat2,formula,msclip_only,208,?,?,?,—
casmi_2016_cat2,formula,llm,208,?,?,?,?
msg,formula,msclip_only,N,?,?,?,—
msg,formula,llm,N,?,?,?,?
msg,mass,msclip_only,N,?,?,?,—
msg,mass,llm,N,?,?,?,?
```

加 combined Wilcoxon 显著性 csv:

```csv
test,n_paired,p_value,sig_after_bonferroni
casmi_2022 msclip→llm,170,0.087,no
casmi_2016 msclip→llm,208,?,?
msg_formula msclip→llm,N,?,?
msg_mass msclip→llm,N,?,?
combined_all_oOD msclip→llm,?,?,?  ← 关键 row
```

### D5 — 报告 `reports/eval/msg_v1.md`(0.5 day)

8 节,跟 CASMI 报告同结构。重点章节:

#### 1. Headline
MSG 上 LLM Δ vs MS-CLIP-only (formula + mass),跟 CASMI 数字对比。

#### 2. Setup
明确变量:checkpoint (default → msg-trained) + benchmark (CASMI → MSG) + candidate pool (formula → mass)。

#### 3. Main result
2-pool × 3-config 主表。

#### 4. Cross-checkpoint generalization
**关键 paper finding**:LLM rerank Δ 在两个 checkpoint 上是否一致?
- 一致 → "LLM rerank 跟 retriever checkpoint 解耦"(strong finding)
- 不一致 → "LLM rerank 受 retriever 训练分布影响"(也重要 finding)

#### 5. Formula vs Mass pool 对比
LLM Δ 在两种 pool 上的差异。

#### 6. 三 benchmark combined 显著性
n=170 + 208 + N 上 paired Wilcoxon。期望过 Bonferroni。

#### 7. Limitations
- 单 LLM (Opus only)
- MSG-trained checkpoint 训练数据 overlap 风险(MSG 本身就是训练数据吗?check labels.tsv)
- MSG split 协议(train/val/test 分布是否平衡)

#### 8. Provenance + reproducer

### D6 — Acceptance

```
□ data/benchmark/msg/test_tasks_{formula,mass}.jsonl 各 N task
□ data/eval/msg/{formula,mass}_{msclip_only,conditional,llm_reranker}/ 6 套完整
□ phase6_7d_msg_results.csv 主表 + cross-benchmark
□ Combined n (CASMI 2022 + 2016 + MSG) Wilcoxon p 报数
□ 8 节报告
□ 现有 CASMI 数据未动
□ Phase 6.7-A LlmRerankResult schema 不修
```

---

## Pitfalls

1. **MSG-trained checkpoint vocabulary**:checkpoint 名字含 `chemformer_v4_large_ep3unfroze`,可能跟默认 ms-clip 模型架构不同。**第一回合必须 verify** — 如果 checkpoint 不兼容当前 MSClipRetriever 加载逻辑,escalate(可能要改 model.py loader)。

2. **MSG 训练数据 overlap**:checkpoint 在 `chemformer_v4_large_ep3unfroze`,可能在 MSG train split 上训练。**如果在 test split 上评估,split 是干净的;但如果 checkpoint "见过" test split,这是污染**。第一回合 check ms-pred config 文件确认。

3. **候选 json 可能很大**:`MassSpecGym_retrieval_candidates_mass.json` mass-window 候选数量可能 1000s per spec,prompt 给 LLM 时仍要截到 top-5(LLM 输入限制)。

4. **MSG 跟 CASMI 2022 数据可能重叠**:都是公开 benchmark,化合物可能共享。combined Wilcoxon 假设 paired sample,如果有重叠 spec 要按 InChIKey first-block dedupe。**报告 §6 必须报 dedup 数字**。

5. **不要 fine-tune / re-train**:user 给了现成 checkpoint,直接 inference 即可。任何训练操作都 out of scope。

6. **MS-CLIP env var 切换可能要 process restart**:如果当前进程 cache 了 checkpoint,切 env var 不生效。需要新进程跑(`run_msg.py` 启动时读 env)。

---

## Time budget

- Confirm: 30 min
- D1 loader: 0.5 day
- D2 runner: 2 hours
- D3 6 config 跑: ~1 day wall(后台)
- D4 联合分析: 0.5 day
- D5 报告: 0.5 day
- D6: 15 min

**Total: ~2 days wall**(D3 后台跑期间可并行 D4/D5 准备)。

LLM cost: ~$10-15(取决于 MSG test set 大小)。

---

## First action checklist

第一回合:
1. 读 6 个 background 文件
2. 检查 MSG checkpoint 兼容性(架构 + vocabulary)
3. 报告 `labels.tsv` 头 5 行(确认 schema)
4. 报告 `split_msg.tsv` test set 数量
5. 报告候选 json 结构(每 spec 多少候选,formula 跟 mass 差多少)
6. 检查 MSG-trained checkpoint 是否见过 test split(看 ms-pred config)
7. 估算 D3 总 wall + LLM cost
8. 任何 clarifying question

不要写代码或跑命令,直到 confirm。
