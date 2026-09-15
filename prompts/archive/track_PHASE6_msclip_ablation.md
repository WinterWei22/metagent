# Track PHASE 6.1 — MS-CLIP integration with ablation on Sub-6A real-id v2

**Session ID:** `track_PHASE6_msclip_ablation`
**Branch:** `feature/sub6-msclip-ablation`(新建 from `feature/sub6-v2-integrated`)
**Estimated work:** 2-4 hours wall(主要是 LLM-free,3 次 library_search 跑)
**Predecessors:**
- `reports/eval/sub6_v2_comparison_2026-05-06.md`(Sub-6A real-id v2 baseline,67.32% top-1)
- `reports/library_search_phase_a_2026-05-06.md`(Phase A precursor mass window)

---

## Why this matters

当前 Sub-6A real-id v2 的 library_search **只用了 Modified Cosine on GNPS**:

```python
# evaluation/sub6/identification.py:189
libraries: tuple[str, ...] = ("gnps",)   # ← 永不触发 MSClipRetriever
```

我们的私有 MS-CLIP 模型(`tools/library_search/model.py`,通过 `libraries=("inhouse",)` 启用)**从未参与 Sub-6 evaluation**。

本 session 跑一次 ablation 实验(纯 id_accuracy,不跑 LLM narrative/verifier),量化 MS-CLIP 的边际贡献。

---

## Hard scope boundaries

**You MAY:**
- 修 `evaluation/sub6/run_sub6a.py` 加一个 CLI 参数 `--libraries`(透传到 identify_spectrum)
- 修 `scripts/eval_sub6/run_baseline.py` 透传该参数
- 跑 Sub-6A real-id 3 个 ablation 配置(只跑 identification 阶段,**不跑 LLM/verifier**)
- 写报告 `reports/eval/msclip_ablation_v2.md`

**You MAY NOT:**
- 修 `tools/library_search/` 任何代码(MS-CLIP / 评分逻辑保持不变)
- 修 `evaluation/sub6/identification.py` 主体逻辑(只改 default 或加参数透传)
- 跑 LLM narrative 或 verifier(本 session 只看 id_accuracy)
- 覆盖现有 Sub-6A real v2 verdict / narrative 文件
- 修 prompt 模板

**保留原流程**:不删除 `libraries=("gnps",)` 这条路径,只是让它可被 CLI 切换。回归到 default 时行为完全跟 v2 一致。

---

## Background reading

1. `evaluation/sub6/identification.py`(line ~189 是 `libraries` default)
2. `evaluation/sub6/run_sub6a.py`(看 identify_spectrum 调用)
3. `tools/library_search/tool.py`(line ~127 是 MSClipRetriever 启用条件)
4. `tools/library_search/scoring.py`(看 fused_score 怎么合并 cosine + msclip)
5. `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`(38 task)
6. `results/v2/sub6a_real/sub6a_v2_real_verdicts.jsonl`(基线 67.32% id_acc)
7. `logs/v2/sub6a_real.log`(基线跑时的命令格式)

In your first response,确认:
- `libraries=("inhouse",)` 单独启用是否 work(还是必须配 ("gnps", "inhouse"))
- `tools/library_search/scoring.py` 里 fused_score 的具体加权方法(算术平均? max? 学习权重?)
- MS-CLIP 推理需要 GPU 还是 CPU(GPU 占用)
- 跑 38 task × 459 spectrum × 3 config 预计 wall time

不要写代码或跑命令,直到 confirm。

---

## Deliverables

### D1 — CLI 透传(30 分钟,~5 行代码)

修 `evaluation/sub6/run_sub6a.py`:加 `--libraries` CLI 参数(逗号分隔,e.g. `gnps,inhouse`)。透传到 identify_spectrum。

修 `scripts/eval_sub6/run_baseline.py`:接受 `--libraries` 透传。

**关键**:不传 `--libraries` 时回退到 `("gnps",)` default,保证现有 caller 行为不变。

加 unit test:mock library_search,断言 libraries 参数确实透到 identify_spectrum。

### D2 — 跑 3 个 ablation 配置(2-3 hours wall)

**所有配置使用同一 v2 task 集 + 同一 Phase A mass window**(`mass_tolerance_ppm=10.0`),只切 `--libraries`。

#### Config A: `gnps` only(baseline,复现 v2 数字)

```bash
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6a data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
    --output data/eval/sub6/v2_msclip_ablation/gnps_only/ \
    --libraries gnps \
    --strategy library_search \
    --mass-tolerance-ppm 10.0 \
    --skip-narrative \
    > logs/v2_msclip_ablation/gnps_only.log 2>&1
```

期望 id_acc ≈ 67.32%(跟 v2 基线一致,验证回归)。

#### Config B: `inhouse` only(纯 MS-CLIP)

```bash
... --libraries inhouse ...
```

输出 → `data/eval/sub6/v2_msclip_ablation/inhouse_only/`

#### Config C: `gnps,inhouse` fused

```bash
... --libraries gnps,inhouse ...
```

输出 → `data/eval/sub6/v2_msclip_ablation/fused/`

**注意**:如果 `--skip-narrative` flag 不存在,加上(只跑到 identification 完结即停,不调 LLM)。这是本 session 必加的 flag,因为 LLM call 占大部分时间且本 session 不需要 narrative。

如果实在加不上 `--skip-narrative`,跑完 identification 后用 Ctrl-C 停掉,从 identification log 里提取 id_acc 数字。**绝不能跑 LLM,浪费 ~1h × 3 = 3h API 调用**。

### D3 — Aggregate metric(15 分钟)

写脚本 `scripts/eval_sub6/aggregate_msclip_ablation.py`(或在现有 aggregator 里加一个模式),从 3 个 config 的 identification log/output 提取:

| metric | gnps only | inhouse only | fused |
|---|---:|---:|---:|
| n_tasks | 38 | 38 | 38 |
| n_spectra (total) | 459 | 459 | 459 |
| top-1 id_acc (overall %) | 67.32 | ? | ? |
| top-1 id_acc (task mean) | 67.37 | ? | ? |
| **per-bucket id_acc**: amino_acid | ? | ? | ? |
| per-bucket id_acc: central | ? | ? | ? |
| per-bucket id_acc: lipid | ? | ? | ? |
| per-bucket id_acc: nucleotide | ? | ? | ? |
| per-bucket id_acc: other | ? | ? | ? |
| n_compounds gained vs gnps_only | — | ? | ? |
| n_compounds lost vs gnps_only | — | ? | ? |
| wall time per config | ? min | ? min | ? min |

输出 CSV:`data/paper_figures/phase6_msclip_ablation.csv`(供 paper Figure 用)。

### D4 — 报告 `reports/eval/msclip_ablation_v2.md`

#### 1. Summary
3 行 ablation 结论 + paper 影响一句话。

#### 2. Setup
- v2 数据集 task / spectrum 计数
- 3 个 config 命令(完整)
- mass tolerance / top_k / exclusion filter 配置(都跟 v2 baseline 一致)

#### 3. Main result(D3 表格)

#### 4. Per-bucket breakdown
按 5 个 bucket 看 MS-CLIP 改进幅度。可能 amino_acid 涨多,lipid 涨少(或反之)。

#### 5. Per-spectrum win/loss analysis
- 多少 spectrum 在 fused 下从错变对(MS-CLIP 救了)
- 多少 spectrum 在 fused 下从对变错(MS-CLIP 拉低 cosine 把对的踢下去)

#### 6. Cost
- MS-CLIP 推理 wall time + GPU 内存
- fused 比 gnps_only 慢多少倍

#### 7. Paper finding
1-2 段:
- ablation 数字证明 MS-CLIP 边际贡献(几 pt id_acc)
- 跟 prior work(SIRIUS / MIST / pure cosine baselines)对比
- 是否值得作为 paper Figure 的独立 ablation

#### 8. Limitations
- 只测 Sub-6A v2 38 task,GNPS+MassBank-non-RIKEN 谱图分布
- 没测 cross-mode (positive vs negative) 上 MS-CLIP 表现差异
- 没测大型谱图库(只 GNPS,没 NIST 等商业库)

#### 9. Provenance
git commit / file MD5 / wall time / 完整命令

### D5 — Acceptance

```
□ data/eval/sub6/v2_msclip_ablation/{gnps_only,inhouse_only,fused}/ 3 个目录
□ 每个目录有 identification.jsonl(或类似),spectra ≈ 459 行
□ data/paper_figures/phase6_msclip_ablation.csv 主表
□ reports/eval/msclip_ablation_v2.md 完整 9 节
□ Config A 的 id_acc 复现 v2 基线(67.32% ± 0.1pt)— 关键 sanity
□ 现有 results/v2/sub6a_real/* 文件未动
□ 0 LLM narrative 调用(节省成本)
□ 0 verifier 调用(本 session 不验证 narrative)
□ Phase A mass window (10ppm) 在 3 个 config 都相同
```

如果 Config A id_acc 跟 67.32% 偏差 >0.5pt,说明 D1 透传破坏了 default 行为,**escalate**。

---

## Pitfalls

1. **Config A 必须复现 baseline**:这是 sanity check。如果 id_acc 不一致,说明你 D1 改 default 改错了。

2. **MS-CLIP GPU 占用**:可能跟其他 conda env 冲突。先在 D1 之后跑 1 task smoke test 确认 GPU 不 OOM。

3. **`inhouse` only 路径可能踩坑**:看 `tools/library_search/tool.py` 是不是要求 libraries 必须含 "gnps"。如果是,跳 Config B 或改成 dummy gnps + 主信号 inhouse。在第一回合报告这个问题。

4. **不要触动 prompt 模板 / Sub-6B / Sub-6A perfect**:本 session 只动 Sub-6A real-id 的 retrieval 配置。

5. **不要重命名 v2 现有文件**:输出全部去 `v2_msclip_ablation/` 子目录,保持 v2 baseline 文件原位不动。

6. **fused 评分的实现**:看 `tools/library_search/scoring.py`,fused_score 可能是 (cosine + msclip) / 2 或 max。报告里写明实际实现,不要假定。

7. **`--skip-narrative` flag 务必有效**:跑前先在 1 task 上验证它真的跳过 LLM(看 log 没有 chat() 调用)。如果没,本 session 时间预算 wall +3h。

---

## Time budget

- D1: 30 分钟(改 CLI 透传)
- D2: 2-3 hours(3 config × ~30-60 min/config wall)
- D3: 15 分钟
- D4: 30 分钟
- D5: 5 分钟

**Total: 3-4 hours wall**(主要是 library_search 跑全 459 spectrum,GPU + matchms 都吃时间)。

---

## First action checklist

第一回合:
1. 读 7 个 background 文件
2. 报告 `libraries=("inhouse",)` 单独是否 work(看 tool.py logic)
3. 报告 fused_score 实际加权方法(scoring.py)
4. 报告 `--skip-narrative` 是否已在 run_baseline.py 里(若无,要怎么实现)
5. 报告 MS-CLIP 推理在当前 GPU 上的预估耗时(per spectrum)
6. 估算 D2 总 wall(3 个 config 各多久)
7. 任何 clarifying question

不要写代码或跑命令,直到 confirm。
