# ConcordMet W12 — C7 namespace_form fix:Layer 6a fuzzy match

**Worktree:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2`
**Branch:** `metagent-v2`(W11 UV 诊断 HEAD `e74af22` 之上)
**Mode:** 5-7 工作日,有人值守
**预算:** ~5d wall + ~$10 API(Path X 重跑 1 次)

---

## ⚠️ 死命令(全部延续)

- ConcordMet 必须 LLM-driven,不暴露 V3 算法 tool(2026-05-17)
- 不写 paper narrative / Discussion / Methods / Results(2026-05-22)
- MiniMax 远程 API,cost 查 `logs/llm_calls.jsonl`,**禁说 "$0 local"**(2026-05-18)
- 每条 ping 结尾必含 2 段大白话总结(进展 + 问题,1-3 句各)(2026-05-21+22)

## ⚠️ Verifier 修改政策(2026-05-22 松绑后)

- ✅ **加新代码**(自由):新 enum / 新 layer / 新 helper
- ⚠️ **改现有 verifier 逻辑**(本 sprint 触发):commit body 必须含 `[verifier-modify-warning]` + justification + B1 test 不退步证据 + ping me
- ❌ **改 B1 D5/D6 核心 helper**(`claim_extractor.extract_claims_from_json` / `feedback_hints.build_feedback_message` / `verifier/agent.py:_extract_classify` 等)默认禁

3 护栏:
1. Tag `metagent-v2-base-b1` @ `ed6243b` 不许 `git tag -f` / `git tag -d`
2. `data/eval/sub6/b1_d5_*/` + `data/eval/sub6/a3_rerun_*/` immutable,**不覆盖**(重跑结果写新目录)
3. B1 test suite 全 repo pytest 14 fail floor 不退步

---

## §0 必读 Onboarding(30 min)

### Tier 1:W11 诊断结果(必读,10 min)

1. **`reports/agent/concord_w11_uv_diagnosis.md`** — UV 9 类分布 + sample
   *关键 takeaway*:C7 namespace_form 占 226/1102 = 20.5%,期望 → supported 18-21pp UV 降幅

2. **`data/concord/w11_uv_diagnosis/uv_category_samples_10each.json`** — C7 sample 10 条原文
   *关键 takeaway*:看 C7 实际什么样,例如 LLM 写 "Eicosanoid synthesis (WP:WP167)" 但 task ground truth 是 `lm_pathway:WP167`,namespace 差一截

### Tier 2:Layer 6a 现状(必读,10 min)

3. **`verifier/layers/set_enrichment.py`** — 整文件
   *Why:* 本 sprint 主战场。**当前 only exact match**,改造目标 = 加 3 段 fallback(fuzzy name → namespace cross-walk → 仍 UV)

4. **`concord/match/pathway_match.py`**(W9 D2 已有)
   *Why:* token-Jaccard ≥ 0.5 fuzzy match logic 复用源,**不重写**

5. **`data/concord/metanetx.sqlite`** schema 看一眼
   *Why:* namespace cross-walk(KEGG ↔ Reactome ↔ WP)数据源,Layer 6a 第三段 fallback 要用

### Tier 3:Verifier 策略 + 数据契约(必读,10 min)

6. **`verifier/schemas.py:SubsixSourceReport`** + **`verifier/schemas.py:ClaimVerdict`**
   *Why:* Layer 6a 输入/输出 schema

7. **`verifier/feedback_hints.py`**(只读 head 80 行)
   *Why:* 改 Layer 6a 不该影响 feedback hint 生成,sanity 一下 hint 模板字段假设

### Onboarding 完成确认

写到 `reports/agent/concord_sprint_w12_status.md` § "0. Onboarding":

```
Tier 1 W11 诊断: [关键 takeaway]
Tier 2 Layer 6a 现状: [当前 match logic 一句话描述]
Tier 3 schema: [Layer 6a input/output 关键字段]

Confirmation:
  (a) C7 是本 sprint 唯一目标(C3/C5/C1/C2 留后续 sprint)
  (b) Layer 6a 改造是 ⚠️ 级,commit body 必须含 warning + justification
  (c) B1 test suite 14 fail floor 不退步是硬 gate
  (d) Path X 重跑配置同 W10 D4(K=10, MiniMax, max_turns=8, max_iter=2)
  (e) Pathway 准确率不掉 > 3pp 是硬 gate(基线 86%)
  (f) UV 降幅 ≥ 5pp 才算 sprint 通过
```

未完成 onboarding 动 verifier code = stop。

---

## §1 W12 任务目标(2026-05-23 update,基于 D1 onboarding recon)

### ⚠️ Sprint scope 校正

D1 onboarding(commit `5d6c6b3`)recon 显示 226 条 C7 namespace_form claim 的 **claim_type 真实分布**:

| claim_type | n | % | verify_sub6 路径 |
|---|---:|---:|---|
| FACTUAL | 125 | 55.3% | **fall-through UV**(agent.py:664-685,无 sub6 layer)|
| GROUNDED | 56 | 24.8% | **fall-through UV** |
| BIOLOGICAL | 37 | 16.4% | biological_sub6.py |
| DRIVER_METABOLITE | 3 | 1.3% | driver_metabolite.py |
| SET_ENRICHMENT | 2 | 0.9% | **set_enrichment.py(原 sprint 目标)** |
| 其他 | 3 | 1.3% | mixed |

**原 sprint title "Layer 6a fuzzy match" 只覆盖 2/226 = 0.9% 的 C7**。真正大头(80.1%,181 条)是 FACTUAL/GROUNDED 类 metabolite-ID claim,**根本走错 dispatcher**——`SubsixSourceReport` 不带 `candidates[*].metabolite_info.cross_refs`(那是 spectrum-centric `IdentificationReport` 的字段),所以 sub6 dispatch 直接 fall-through UV。

### W12 实际做 2 件事(基于 B 决策,2026-05-23 user 确认)

**主菜:新 sub6 layer 处理 FACTUAL/GROUNDED metabolite-ID claim**
- `verifier/layers/factual_sub6.py` (新文件,✅ add)
- 可能合并 GROUNDED 进同一 layer(if grounded sub6 行为 ≈ factual sub6)
- 数据源:**`SubsixSourceReport.differential_metabolites[*]`(已有 kegg_id / hmdb_id / chebi_id)+ `data/benchmark/sub6/curated_hmdb_mammalian.jsonl`(Layer 6b 已用过的 curated 池)**
- **不接外部 RaMP DB lookup**(session 之前 B 选项写"接 RaMP",我否决:工程量翻倍 + ⚠️ modify policy)

**配菜:Layer 6a `set_enrichment.py` fuzzy match**
- 仍做(2 条 SET_ENRICHMENT claim + 未来 C3/C1+C2 sprint 复用 token-Jaccard 基础设施)
- ⚠️ 级 modify(仅改 match cascade 加 fallback stage,不改判定语义)
- commit body 含 `[verifier-modify-warning]` + B1 test 不退步证据

### 期望 gate(校正版)

- **UV 占比降幅 ≥ 12pp**(原 -18 期望,校正为 -12 — 226 条 C7 中可能 5-15% 是 LLM 写错或命名歧义,真到不了 100% 转化)
- **Pathway 准确率不掉 > 3pp**(基线 86%)
- **Gate A B1 verifier-core test 全过**(见 §5 Gate A 定义)

strict TDD per piece + ✅ add 主体 + ⚠️ modify 局部(dispatcher case + Layer 6a fallback)+ Path X 全 63 task 重跑验证。

---

## §2 5 天 daily breakdown(2026-05-23 update)

| Day | 主线 | 预算 |
|---|---|---|
| **D1** | ✓ Onboarding 完成(commit `5d6c6b3`,recon 揭示 scope mismatch + B 决策 lock) | 已完成 |
| **D2** | RED commit:`tests/test_factual_sub6.py`(~8 case 主菜)+ `tests/test_set_enrichment_fuzzy_namespace.py`(~6 case 配菜) | 1d |
| **D3** | GREEN 主菜:`verifier/layers/factual_sub6.py` 新文件 + 单测全过 | 1d |
| **D4** | GREEN 配菜:`verifier/layers/set_enrichment.py` fuzzy fallback(⚠️ modify)+ `verifier/agent.py:_verify_per_claim_sub6` 加 dispatch case(⚠️ modify) | 1d |
| **D5** | Gate A + Gate B verify + Path X 全 63 task 重跑(~2h wall,~$10 cost) | 1d |
| **D6** | Report + ping | 0.5d |

**两个 ⚠️ modify** 都需要 commit body 含 `[verifier-modify-warning]` + justification + B1 test 不退步证据。

---

## §3 D2 — RED commit(两组 unit test,strict TDD per piece)

### 主菜:`tests/test_factual_sub6.py`(新文件,≥ 8 case)

```python
# 1. FACTUAL claim 在 SubsixSourceReport.differential_metabolites 命中(主路径)
def test_factual_kegg_id_match_in_differential_metabolites_supported():
    """claim 说 'L-tyrosine has KEGG ID C00082',task differential_metabolites 含 KEGG:C00082 → SUPPORTED。"""
    # task.differential_metabolites = [{"name": "L-tyrosine", "kegg_id": "C00082", "hmdb_id": "HMDB00158"}, ...]
    # claim: FACTUAL,"L-tyrosine has KEGG ID C00082"
    # expected: SUPPORTED

# 2. FACTUAL claim 在 curated jsonl 命中(fallback)
def test_factual_id_match_in_curated_jsonl_supported():
    """task 没有,但 curated_hmdb_mammalian.jsonl 含 → SUPPORTED。"""

# 3. FACTUAL claim ID 不匹配(CONTRADICTED)
def test_factual_kegg_id_mismatch_contradicted():
    """task 含 L-tyrosine KEGG:C00082,但 claim 说 'L-tyrosine has KEGG ID C99999' → CONTRADICTED。"""

# 4. GROUNDED claim 处理(同 layer 或单独 layer,看实现)
def test_grounded_metabolite_field_lookup_supported():
    """claim 引用 task 字段(如 'differential_metabolites[3].name = X')→ SUPPORTED if path exists。"""

# 5. Namespace 多样性(KEGG / HMDB / ChEBI / InChIKey)
def test_factual_chebi_id_supported(): ...
def test_factual_hmdb_id_supported(): ...
def test_factual_inchikey_supported(): ...

# 6. Empty differential_metabolites + curated 也无 → UV
def test_factual_no_data_uv():
    """task differential_metabolites 空 + curated jsonl 无该 compound → UNVERIFIABLE_V0。"""

# 7. Dispatcher routing test
def test_dispatch_factual_in_sub6_routes_to_factual_sub6():
    """ClaimType.FACTUAL 在 sub6 path 应该走新 layer 而不是 fall-through。"""
```

### 配菜:`tests/test_set_enrichment_fuzzy_namespace.py`(新文件,≥ 6 case)

```python
# (沿用原 prompt §3 设计,精简为 6 case)
def test_exact_match_pathway_id_supported(): ...           # regression
def test_fuzzy_name_token_jaccard_above_threshold_supported(): ...
def test_fuzzy_match_below_threshold_falls_through(): ...
def test_namespace_crosswalk_via_metanetx_supported(): ...  # 走 data/concord/metanetx.sqlite
def test_namespace_crosswalk_no_mapping_uv(): ...          # FP 防御
def test_empty_ramp_enrichment_uv(): ...                   # regression
```

注:tyrosine vs ascorbate FP 防御 case(W6 sanity 教训)合并进 fuzzy_below_threshold case 即可,不单独列。

### D2 RED 阶段执行

```bash
pytest tests/test_factual_sub6.py tests/test_set_enrichment_fuzzy_namespace.py -v
# 预期:主菜 ≥ 6/8 fail(2 regression case 通)+ 配菜 ≥ 4/6 fail(2 regression case 通)
```

RED commit(单 commit,两组 test 一起):

```bash
git commit -m "test(verifier): W12 C7 RED — factual_sub6 + set_enrichment fuzzy (14 cases)

W11 UV diagnosis C7 namespace_form 226 claim recon (commit 5d6c6b3):
80.1% (181 claim) are FACTUAL/GROUNDED metabolite-ID claims that
fall-through verify_sub6 dispatch because SubsixSourceReport has no
candidates[*].metabolite_info.cross_refs field.

Sprint scope (per 2026-05-23 user decision, option B):
  Main course: new verifier/layers/factual_sub6.py + dispatch case
    → handles 181/226 (80.1%) of C7
    → data source: SubsixSourceReport.differential_metabolites +
      data/benchmark/sub6/curated_hmdb_mammalian.jsonl (no external RaMP)
  Side dish: set_enrichment.py fuzzy match cascade
    → handles 2/226 (0.9%) of C7 + future C3/C1+C2 infrastructure

This RED commit adds 8 + 6 = 14 test cases. Main expected fail count:
≥ 6/8 (regression case 1+8 pass). Side expected: ≥ 4/6.

GREEN follow-up will touch verifier/ — see [verifier-modify-warning]
in subsequent commits."
```

### Stop conditions D2

- regression case(主菜 case 1+8 / 配菜 case 1+8)pre-impl 不通过 → 现有 verifier 已退步,**必停 ping me**
- LLM-fail case 在 RED 阶段 actually pass(implementation 不该 already 存在)→ test 写错

### 新建 test 文件

`tests/test_set_enrichment_fuzzy_namespace.py`,**至少 8 case**:

```python
# 1. EXACT MATCH(regression,改造后不能破)
def test_exact_match_pathway_id_supported():
    """完全相同的 pathway_id 应该 supported(改造前后行为不变)。"""
    # claim: WP:WP167  vs  enrichment: WP:WP167
    # expected: SUPPORTED

# 2. FUZZY NAME MATCH(新行为)
def test_fuzzy_name_token_jaccard_above_threshold_supported():
    """token-Jaccard ≥ 0.5 的 pathway name 应该 supported。"""
    # claim: "Eicosanoid synthesis"  vs  enrichment: "WP167 Eicosanoid biosynthesis pathway"
    # token-Jaccard = 2/3 = 0.67 ≥ 0.5 → SUPPORTED

# 3. FUZZY MATCH 边界(0.49 fail / 0.51 pass)
def test_fuzzy_match_below_threshold_falls_through():
    """token-Jaccard < 0.5 应该 fall through 到 namespace cross-walk。"""
    # claim: "Arachidonic acid metabolism"  vs  enrichment: "Eicosanoid synthesis WP167"
    # token-Jaccard = 0 → fall through

# 4. NAMESPACE CROSS-WALK MATCH(新行为)
def test_namespace_crosswalk_via_metanetx_supported():
    """通过 metanetx 跨命名空间能 resolve 到同一 pathway 应该 supported。"""
    # claim: MUMM:arachidonic_acid_metabolism  vs  enrichment: KEGG:hsa00590
    # metanetx 把两者 map 到同一 internal ID → SUPPORTED

# 5. NAMESPACE CROSS-WALK FAIL → UV(regression)
def test_namespace_crosswalk_no_mapping_uv():
    """metanetx 也找不到 mapping 应该返回 UV(不是 unsupported)。"""
    # claim: GARBAGE:nonexistent  vs  enrichment: KEGG:hsa00590
    # → UNVERIFIABLE_V0

# 6. FALSE POSITIVE 防御(W6 sanity 教训:group11 tyrosine vs ascorbate)
def test_fuzzy_match_blocks_tyrosine_ascorbate_false_positive():
    """W6 sanity 暴露的 FP case:tyrosine vs ascorbate 的 stop word 过滤后不能 token-Jaccard 命中。"""
    # claim: "Tyrosine metabolism"  vs  enrichment: "Ascorbate metabolism"
    # 去掉 stop word "metabolism" 后 token-Jaccard = 0 → fall through to cross-walk → UV

# 7. STOP WORD FILTER 验证
def test_stop_word_filter_excludes_generic_tokens():
    """generic tokens(metabolism / pathway / biosynthesis)不算 fuzzy match 命中。"""
    # claim: "Foo metabolism"  vs  enrichment: "Bar metabolism"
    # 去 stop word 后 token-Jaccard = 0 → not supported

# 8. EMPTY ENRICHMENT(regression)
def test_empty_ramp_enrichment_uv():
    """ramp_enrichment_result.top_pathways 为空 → UV(改造前后不变)。"""
    # SubsixSourceReport.ramp_enrichment_result = []
    # → UNVERIFIABLE_V0
```

### RED 阶段执行

```bash
pytest tests/test_set_enrichment_fuzzy_namespace.py -v
# 预期:6/8 fail(case 2/3/4/5/6/7 因为 fuzzy + cross-walk 未实现)
#       2/8 pass(case 1/8 regression case)
```

RED commit:

```bash
git commit -m "test(verifier): W12 C7 RED — Layer 6a fuzzy namespace match (8 cases)

Phase B1 verifier Layer 6a (set_enrichment.py) currently only exact-matches
pathway_id. W11 UV diagnosis showed 226/1102 (20.5%) of UV claims are
'namespace_form' — pathway names that semantically match but namespace
prefix mismatches (e.g. claim 'WP:WP167 Eicosanoid synthesis' vs
ramp_enrichment 'KEGG:hsa00590 Arachidonic acid metabolism').

This RED commit adds 8 test cases for the planned fuzzy+cross-walk
fallback. 6/8 expected fail before impl (cases 2-7); 2/8 pass as
regression baselines (cases 1, 8).

GREEN follow-up will modify verifier/layers/set_enrichment.py — see
[verifier-modify-warning] in that commit body for justification."
```

### Stop conditions D1

- 8 case 中 case 1 或 case 8 不通过(regression 已破)→ 现有 Layer 6a 状态有问题,**必停 ping me**
- 6 case fail 但 reason 不对(不是因为 fuzzy/cross-walk 未实现)→ test 设计错,**重写 test**

---

## §4 D2-D3 — GREEN commit(Layer 6a 改造)

### 实现 spec

`verifier/layers/set_enrichment.py` 现在的 match logic 大致是:

```python
# 伪代码,实际看源
for pathway in ramp_enrichment_result.top_pathways:
    if claim.pathway_id == pathway.pathway_id:
        return SUPPORTED
return UNVERIFIABLE_V0
```

改造为 **3 段 fallback**:

```python
# Stage 1: exact match(不动)
for pathway in ramp_enrichment_result.top_pathways:
    if claim.pathway_id == pathway.pathway_id:
        return SUPPORTED

# Stage 2: fuzzy name match(新)
from concord.match.pathway_match import token_jaccard, STOP_WORDS

for pathway in ramp_enrichment_result.top_pathways:
    score = token_jaccard(
        claim.pathway_name,
        pathway.pathway_name,
        stop_words=STOP_WORDS,
    )
    if score >= 0.5:
        return SUPPORTED  # with trace_summary = f"fuzzy match score={score:.2f}"

# Stage 3: namespace cross-walk via metanetx(新)
from verifier.helpers.namespace_xwalk import resolve_via_metanetx

claim_canonical = resolve_via_metanetx(claim.pathway_id)
for pathway in ramp_enrichment_result.top_pathways:
    enrich_canonical = resolve_via_metanetx(pathway.pathway_id)
    if claim_canonical and enrich_canonical and claim_canonical == enrich_canonical:
        return SUPPORTED  # with trace_summary = f"namespace cross-walk via metanetx"

# Stage 4: 仍找不到 → UV(不动)
return UNVERIFIABLE_V0
```

### 新建 helper(✅ 加新代码,不算 modify)

`verifier/helpers/__init__.py` + `verifier/helpers/namespace_xwalk.py`(新文件):

```python
"""Namespace cross-walk via metanetx.

Resolves pathway_id (e.g. WP:WP167 / KEGG:hsa00590 / MUMM:eicosanoid_*)
to a canonical metanetx internal pathway ID. Returns None if no mapping
found.

Backed by data/concord/metanetx.sqlite (loaded in W9 D2).
"""
import sqlite3
from pathlib import Path
from functools import lru_cache

_METANETX_PATH = Path("data/concord/metanetx.sqlite")

@lru_cache(maxsize=10000)
def resolve_via_metanetx(pathway_id: str) -> str | None:
    """e.g. 'WP:WP167' → 'mnxr_pathway_001234' or None."""
    # query metanetx pathway_xref table
    ...
```

### `concord/match/pathway_match.py` import 检查

复用 W9 D2 已有的 token_jaccard。如果 import 路径在 metagent-v2 branch 上 work,直接用;如果有循环依赖问题,**把 token_jaccard 复制进 `verifier/helpers/fuzzy_match.py`**(算 add 新代码,合规)。

### GREEN commit

**commit body 必须含 `[verifier-modify-warning]` 段**:

```bash
git commit -m "feat(verifier): W12 C7 GREEN — Layer 6a fuzzy name match + namespace cross-walk

[verifier-modify-warning]
This commit modifies verifier/layers/set_enrichment.py (B1 D2 commit
2354011 territory). Justification per 2026-05-22 verifier modification
policy:

  Why modify Layer 6a vs add new layer:
  - Layer 6a is the canonical SET_ENRICHMENT verification path
  - Adding a parallel 'fuzzy enrichment' layer would duplicate ~70% of
    6a's logic (claim parsing, evidence assembly, trace generation)
  - Adding fallback stages within 6a is the minimal-diff change
  - The exact-match Stage 1 is preserved unchanged — no regression risk
    for existing B1 D5/D6 verdict outputs

  B1 test suite re-verified:
  - tests/ full pytest: <count> pass / 14 fail (= W10 D4 baseline, no regression)
  - tests/concord/ subtree: <count> pass / 9 fail (= pre-existing env)
  - tests/test_*.py B1 originals: all pass

  Path X re-run pending (D5).

3 fallback stages added:
  1. exact match (unchanged)
  2. fuzzy name match via concord/match/pathway_match.py (token-Jaccard >= 0.5)
  3. namespace cross-walk via new verifier/helpers/namespace_xwalk.py
     (backed by data/concord/metanetx.sqlite)

RED test reference: <hash> (8/8 pass after GREEN)"
```

### Stop conditions D2-D3

- 8 case test 任 1 仍 fail(GREEN 不完整)→ 必修
- `concord/match/pathway_match.py` import 失败 → 复制 token_jaccard 进 `verifier/helpers/fuzzy_match.py`
- `data/concord/metanetx.sqlite` 不存在 / 损坏 → ping me 决定是否复制 / fallback
- 任 1 现有 verifier test fail(B1 D2-D4 期间的 verifier 测试)→ 必停回滚

---

## §5 D5 — Sanity gate verify + Path X 重跑

### Gate A(必须通过,blocking,B1 verifier-core)

```bash
pytest tests/test_verifier/ \
       tests/test_d4_feedback_dispatcher.py \
       tests/test_grammar_validate.py \
       tests/test_classifier_collapse.py \
       tests/test_runner_response_format.py \
       tests/test_prompt_banned_sync.py \
       -v 2>&1 | tail -20
```

期望:**全过**(B1 D2-D4 期间核心 31+ test)。任 1 fail → **必停回滚到 RED commit 状态**。

### Gate B(监控,允许 ≤14 fail floor)

```bash
pytest tests/ -q --ignore=tests/test_ui --ignore=tests/integration \
       --ignore=tests/benchmark 2>&1 | tail -5
```

期望:**pass count ≥ 1339(W10 D4 baseline 1331 + W11 +N + W12 +14)/ fail ≤ 14**

任 1 NEW fail(非 pre-existing env)→ ping me 判断,**不必自动回滚**(看 fail 是否 verifier-related)。

### Gate C(concord/ subtree)

```bash
pytest tests/concord/ -v 2>&1 | tail -15
```

期望:**~150+ pass / 9 fail(pre-existing env)/ 1 xfail**——不退步即可。

### Path X 全 63 task 重跑

```bash
python scripts/concord/w10_d4_path_x_full.py \
    --benchmark data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
    --output data/concord/w12_path_x_post_c7/path_x_full63_results.jsonl \
    --max-react-turns 8 --max-feedback-iters 2 --k-concurrent 10 \
    --llm minimax-m2.7

# 预算:wall ~1.5-2h,API soft ceiling $10 / hard halt $13
```

**输出新目录** `data/concord/w12_path_x_post_c7/`(护栏 2,不覆盖 W10 D4)。

### Gate 1:B1 test suite 不退步

```bash
pytest tests/ -q --ignore=tests/test_ui --ignore=tests/integration \
       --ignore=tests/benchmark --ignore=tests/eval_sub6/__init__.py \
       2>&1 | tail -20
```

期望:**1331+ pass / 14 fail / 10 skip / 1 xfailed**(D3 sprint W10 baseline + W11 +N + W12 +8 test)

任 1 NEW fail(非 pre-existing env)→ **必停回滚**。

### Gate 2:concord/ subtree 不退步

```bash
pytest tests/concord/ -v 2>&1 | tail -20
```

期望:**~150+ pass / 9 fail(pre-existing env)/ 1 xfail**

### Gate 3:W11 UV 重分类(预跑,不必精确)

跑 W11 分类脚本对 D4 已有数据,看 C7 数字粗略变化(实际 Path X 重跑才是 ground truth)。

```bash
python scripts/concord/w11_classify_uv_claims.py \
    --input data/concord/w10_d4_path_x_full/path_x_full63_results.jsonl \
    --output /tmp/w12_d4_preview_classify.jsonl
# 看 C7 数字是否仍 226 左右(D4 verifier 没改前)
```

这一步只是 sanity,**不算 gate**(D5 Path X 重跑才是真 gate)。

---

## §6 D5 — Hard Gate 判定(双数字)

跑完 Path X 后,**两个数字必须同时通过**才算 W12 sprint PASS:

```
Gate Pass(必须同时满足):
  UV 占比降幅 ≥ 12pp(校正后期望;原 -18 期望降到 -12 因为部分 C7 是 LLM 写错)
  Pathway 准确率不掉 > 3pp(86% → ≥ 83%)

Gate Fail → 必停 ping me + 回滚到 RED commit 状态

数字来源:
  - UV 占比:final iter aggregate 的 unverifiable_v0 / total claims
  - Pathway 准确率:per-task ground truth pathway 是否命中 final 输出 top-10
```

### Stop conditions D5

1. **Wall > 4h**(K=10 应 ~2h)→ 性能 regress
2. **API cost > $13**(soft $10 / hard $13)→ ping me
3. **≥ 10 task LLM API error / verifier crash** → halt
4. **UV 降幅 < 12pp** → 必停 ping me 讨论(可能 fuzzy 阈值 / cross-walk 覆盖不够)
5. **Pathway 准确率掉 > 3pp** → 必停 ping me 回滚
6. **iter-2 quality degradation 比 W10 D4 17.7% 还高** → 引入新 regression,必停

### 配置(同 W10 D4)

```bash
# 走 W9 D5 / W10 D4 同款 driver
python scripts/concord/w10_d4_path_x_full.py \
    --benchmark data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
    --output data/concord/w12_path_x_post_c7/path_x_full63_results.jsonl \
    --max-react-turns 8 \
    --max-feedback-iters 2 \
    --k-concurrent 10 \
    --llm minimax-m2.7

# 预算:wall ~1.5-2h,API ~$10
```

**输出新目录** `data/concord/w12_path_x_post_c7/`(护栏 2,不覆盖 W10 D4)。

### 双数字 hard gate(W12 sprint 通过判定)

```
Gate Pass 条件(必须两个同时):
  UV 占比降幅 ≥ 5pp(期望 -18 to -21pp,从 52% 降到 31-34%)
  Pathway 准确率不掉 > 3pp(86% → ≥ 83%)

Gate Fail → 必停 ping me + 回滚

数字来源:
  - UV 占比:final iter aggregate 的 unverifiable_v0 / total claims
  - Pathway 准确率:per-task ground truth pathway 是否命中 final 输出
```

### Stop conditions D5

1. **Wall > 4h**(K=10 应 ~2h)→ 性能 regress,ping me
2. **API cost > $20** → 超预算
3. **≥ 10 task LLM API error / verifier crash** → halt
4. **UV 降幅 < 5pp** → C7 sprint 失败,必停 ping me 讨论
5. **Pathway 准确率掉 > 3pp** → 必停 ping me 回滚

---

## §7 D6 — Report + ping

`reports/agent/concord_sprint_w12_status.md`,**纯数据 + 短 caption,无 paper-style 解读**:

```markdown
# W12 C7 namespace_form fix — Sprint Report

## 1. Gate Verify
- B1 test suite: <count> pass / 14 fail (baseline, no regression)
- concord/ subtree: <count> pass / 9 fail (pre-existing env)
- Path X full 63 task re-run wall: ?h
- API cost: $? (from logs/llm_calls.jsonl, MiniMax remote API)

## 2. UV Aggregate Comparison

| metric | W10 D4 baseline | W12 post-C7 | Δ |
|---|---|---|---|
| supported %         | 28.62 | ??.?? | +?.?? pp |
| unsupported %       | 16.71 | ??.?? | ?.?? pp |
| contradicted %      |  1.71 | ??.?? | ?.?? pp |
| unverifiable_v0 %   | 52.96 | ??.?? | ?.?? pp |

## 3. Pathway 准确率

| metric | W10 D4 | W12 |
|---|---|---|
| pathway hit / 63 task | 54/63 (86%) | ??/63 (?%) |

Gate verdict:
- UV 降幅 ≥ 5pp: PASS / FAIL
- Pathway 准确率不掉 > 3pp: PASS / FAIL
- Sprint OVERALL: PASS / FAIL

## 4. C7 sub-bucket 转化分析

| original W11 C7 226 claim 现在归类 |
|---|
| supported: ?? |
| unsupported: ?? |
| contradicted: ?? |
| unverifiable_v0(剩余): ?? |
| 其他 category: ?? |

## 5. fuzzy match trace sample
(随机抽 10 条 supported via fuzzy / cross-walk,看 trace_summary 是否 reasonable)

## 6. 不动 conclusion / future work / 不写 paper-style
```

### Ping content template

```
=== W12 C7 namespace_form fix Complete ===

Commits: <RED hash> + <GREEN hash> + <report hash>

Gate Verify:
  B1 test suite:  X pass / 14 fail (no regression) — PASS / FAIL
  concord/:       Y pass / 9 fail — PASS / FAIL
  Path X wall:    ?h
  Path X cost:    $?

UV Δ:
  W10 D4 baseline: 52.96%
  W12 post-C7:    ?? %
  Δ:              -?? pp
  Gate (≥ 5pp drop): PASS / FAIL

Pathway 准确率 Δ:
  W10 D4: 54/63 (86%)
  W12:    ??/63 (?%)
  Δ:      ±?? pp
  Gate (drop ≤ 3pp): PASS / FAIL

Sprint OVERALL: PASS / FAIL

[verifier-modify-warning] commit body verified:
  - Justification present:yes/no
  - B1 test re-verify count cited:yes/no

[2 段大白话总结]
```

---

## §8 Stop Conditions(任 1 触发停下报告)

1. Onboarding §0 confirmation 缺失就动代码
2. RED 阶段 8 case 中 case 1/8(regression)不通过
3. GREEN 阶段 8 case 不全通过
4. **D4 Gate 1 B1 test suite NEW fail**(非 pre-existing env)
5. **D4 Gate 2 concord/ subtree 退步**
6. D5 Path X wall > 4h / cost > $20
7. **D5 Gate UV 降幅 < 5pp**(C7 sprint 失败)
8. **D5 Gate pathway 准确率掉 > 3pp**(回归)
9. 任 1 commit body 缺 `[verifier-modify-warning]` 标签(改 verifier 必含)
10. Strict TDD slip(impl 在 unit test commit 之前 land)

任 1 → 写 `reports/agent/concord_sprint_w12_status.md` § BLOCKED + **回滚到 RED commit 状态**(D2-D3 改动)。

---

## §9 不要做

- ❌ 不顺手做 C3/C5/C1/C2(一次只一个 category)
- ❌ 不改 `claim_extractor.extract_claims_from_json`(B1-core,❌ 级)
- ❌ 不改 `feedback_hints.build_feedback_message`(B1-core)
- ❌ 不改 `verifier/agent.py:_extract_classify`(B1-core)
- ❌ 不改 quality_score 函数(W10 D4.5 H3 数据未驱动)
- ❌ 不动 `data/eval/sub6/b1_d5_*/` 或 `data/eval/sub6/a3_rerun_*/`(护栏 2)
- ❌ 不 `git tag -f` / `git tag -d` `metagent-v2-base-b1`(护栏 1)
- ❌ 不暴露 V3 算法 tool
- ❌ 不写 paper writeup
- ❌ 不 push origin

---

## §10 一句话目标(2026-05-23 update)

W12 实际做 2 件事:**主菜 = 新 sub6 layer(`verifier/layers/factual_sub6.py`)处理 226 条 C7 中 80.1%(181 条)FACTUAL/GROUNDED metabolite-ID claim;配菜 = Layer 6a `set_enrichment.py` fuzzy match + namespace cross-walk(2 条 SET_ENRICHMENT claim + 未来 C3/C1+C2 sprint 复用基础设施)**。strict TDD per piece + ✅ add 为主 + ⚠️ modify 局部(dispatcher case + Layer 6a)+ Path X 全 63 task 重跑验证。**Gate**:UV 降 ≥ 12pp + pathway 准确率不掉 > 3pp + B1 verifier-core test 全过。

D1 onboarding 已完成(commit `5d6c6b3`),从 D2 RED commit 起步。开干。
