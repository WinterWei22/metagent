# ConcordMet W13 — A 扩 ID pattern + subject normalization + C iter-2 dynamics 诊断

**Worktree:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2`
**Branch:** `metagent-v2`(W12 完结 HEAD `edb8fe4` 之上)
**Mode:** 6-7 工作日,有人值守,**A + C 并行**
**预算:** ~6d wall + ~$12-15 API(A 路径 X 重跑 1 次 + C 诊断 LLM)

---

## ⚠️ 死命令(全部延续)

- ConcordMet 必须 LLM-driven,不暴露 V3 算法 tool(2026-05-17)
- 不写 paper narrative / Discussion / Methods / Results / footnote / narrative_finalized 等(2026-05-22)
- MiniMax 远程 API,cost 查 `logs/llm_calls.jsonl`,**禁说 "$0 local"**
- 每条 ping 结尾 2 段大白话总结(进展 + 问题,1-3 句各)(2026-05-21+22)

## ⚠️ Verifier 修改政策(2026-05-22 松绑后)

- ✅ **加新代码**(自由):新 enum / 新 layer / 新 helper / 新 regex pattern
- ⚠️ **改现有 verifier 逻辑**:commit body 必须含 `[verifier-modify-warning]` + justification + B1 test 不退步证据 + ping me
- ❌ **改 B1 D5/D6 核心 helper** 默认禁

3 护栏:tag `metagent-v2-base-b1` 不可改 / B1 paper 数据不可覆盖 / B1 test suite 14 fail floor

## ⚠️ W12 教训(强制遵守)

**任何 UV optimization sprint 启动前必做 strict vs fuzzy 重分类**(memory `feedback_uv_sprint_must_reclassify_first`)。本 sprint A 路径 §0 onboarding 阶段强制执行。

---

## §0 Onboarding(30 min)

### Tier 1:W12 close-out + ceiling 教训(必读)

1. **`reports/agent/concord_w12_c7_close_out.md`** — W12 sprint 完整 verdict + ceiling 重校准 + gap-to-ceiling 9.66pp 4 项归因
   *关键 takeaway*:gap 来源 = (1) LLM narrative shift / (2) subject lookup miss / (3) ID pattern miss / (4) side effect(iter-2 deg 升)

2. **`data/concord/w12_d5_5_c7_refine/c7_subclassification.csv`** + summary — W11 C7 226 → 123 strict_id + 103 fuzzy_biology
   *关键 takeaway*:本 sprint A 主线 target = strict_id 子集(123 条)中 W12 未 cover 的 53 条(123 - 70 已 SUPPORTED)

3. **`verifier/layers/factual_sub6.py`**(W12 D3 已 commit)+ `verifier/helpers/fuzzy_match.py`(W12 D4)
   *关键 takeaway*:本 sprint **不动它们,只扩 _ID_PATTERNS regex 列表 + 加 subject normalizer**

### Tier 2:W13.C iter-2 dynamics 上下文

4. **`reports/agent/concord_w10_d4_5_iter2_degradation_analysis.md`**(W10 D4.5 H1/H3 分析)
   *关键 takeaway*:W10 D4 时 iter-2 deg = 17.7%(H3 confirmed:richer feedback → LLM overshoot);W12 D5 升到 22.2%(+4.5pp)

5. **`data/concord/w12_path_x_post_c7/path_x_full63_results.jsonl`** — W13.C 诊断数据源

### Onboarding 完成确认

写到 `reports/agent/concord_sprint_w13_status.md` § "0. Onboarding":

```
Tier 1 W12 close-out:
  - Gap 4 项归因 takeaway: ...
  - W11 C7 真实拆分: 123 strict / 103 fuzzy
  - factual_sub6 W12 转化: 70/123 = 56.9% (53 条 strict 未 cover)

Tier 2 W10 D4.5 iter-2:
  - W10 D4 baseline 17.7% → W12 D5 22.2%(+4.5pp)
  - H3 hypothesis 在 W12 数据上是否仍 confirm 待 W13.C 验证

Confirmation:
  (a) A 主线扩 _ID_PATTERNS + subject normalization(纯 add,无 ⚠ modify)
  (b) C 副线 W12 D5 数据诊断(0.5d analysis,不动 production)
  (c) Target 校准:A 路径 UV 降 ≥ 3pp(基于 53 条 strict 未 cover 的 ~4.8pp 实际 ceiling × 0.6-0.8)
  (d) A + C 并行执行,W13 末汇总
  (e) C8/C9 noise(W13.B candidate)推 W14,fuzzy_biology(W13.D candidate)推 W15+
```

---

## §1 W13 任务目标(一段话)

**主线 A**:扩 `verifier/layers/factual_sub6.py:_ID_PATTERNS`(W12 实测漏识别 KEGG/PubChem/ChEBI 多种 surface form)+ 加 subject name normalizer(Unicode → ASCII,"17β" → "17beta"),消化 W11 C7 strict_id 123 条中 W12 未 cover 的 53 条。**纯 add,0 ⚠ modify**。

**副线 C**:用 W12 D5 path_x 数据诊断 iter-2 degradation 22.2% root cause——是 W10 D4.5 H3(richer feedback overshoot)的延续,还是 W12 D4 新增 dispatcher case 引入的新 root cause?**纯 analysis,0 production change**。

**双线 Hard Gate**:
- A 路径 UV 降幅 ≥ 3pp(校准 target,基于 W11 重分类后的真 ceiling)
- Pathway 准确率不掉 > 3pp(86% → ≥ 83%)
- iter-2 deg 不再升(W12 22.2% 不超)
- B1 test 407/0 / 全 repo 14 fail floor 不退步

W14 主线由 W13 close-out 决定:**A 数字达标 + C 诊断 clear root cause** → W14 走 C8/C9 noise(原 W13.B)/ W14 走 iter-2 fix(C 数据驱动)/ W14 走 C3 signal evidence。

---

## §2 6-7 天 daily breakdown(A + C 并行)

| Day | 主线 A(扩 ID + normalizer)| 副线 C(iter-2 诊断)|
|---|---|---|
| **D1** | Onboarding + RED commit:新 ID pattern + normalizer test(≥ 12 case) | — |
| **D2** | GREEN main:扩 `_ID_PATTERNS` regex + 新 helper `subject_normalizer.py`(纯 add)| — |
| **D3** | — | C 启动:拉 W12 D5 iter-2 degraded task,per-iter quality 分解 |
| **D4** | A Path X 全 63 task 重跑(~2h + $11) | C 报告草稿:H1/H3 在 W12 数据上是否仍 confirm |
| **D5** | A Hard Gate verify + UV 数字 ledger | C 报告 final + W14 候选路径推荐 |
| **D6** | W13 close-out report(A 数字 + C verdict + W14 启动条件) | — |
| **D7** | Buffer | — |

A 路径 commit ~3 个(RED + GREEN + Path X data + close-out)。C 路径 commit ~1-2 个(analysis + report)。**总 ~5-7 commit**。

---

## §3 D1 — A 主线 RED commit(strict TDD per piece)

### 新建 test 文件 `tests/test_factual_sub6_id_patterns_extended.py`

至少 **12 case**(可加,W12 RED 14 case 经验复用):

```python
# 1-4: 扩 KEGG ID surface form
def test_kegg_id_with_colon_namespace_supported():
    """claim_text: 'L-tyrosine has KEGG:C00082' (无 'ID' keyword) → SUPPORTED."""

def test_kegg_id_in_parentheses_supported():
    """claim_text: 'L-tyrosine (C00082)' → SUPPORTED."""

def test_kegg_id_bare_with_kegg_prefix_supported(): ...
def test_kegg_drug_id_dxxxxx_supported(): ...  # D-prefix

# 5-7: PubChem CID
def test_pubchem_cid_with_keyword_supported(): ...
def test_pubchem_cid_short_bare_supported(): ...
def test_pubchem_cid_full_url_extracted_supported(): ...

# 8-10: ChEBI 多 surface form
def test_chebi_id_with_underscore_supported(): ...   # CHEBI_17234
def test_chebi_id_lowercase_supported(): ...          # chebi:17234
def test_chebi_id_full_iri_extracted_supported(): ... # http://...CHEBI_17234

# 11-12: Subject normalization(Unicode → ASCII)
def test_subject_name_greek_letter_match_supported():
    """task: '17β-estradiol', claim: '17beta-estradiol' → SUPPORTED."""

def test_subject_name_whitespace_normalization_supported():
    """task: 'D-glucose', claim: 'D glucose' (extra space) → SUPPORTED."""

# 13 (optional): false positive 防御
def test_random_digit_string_not_matched_as_id():
    """claim_text: 'study found 12345 patients' → 不应 match 任何 ID pattern → UV not SUPPORTED."""
```

预期 RED:**≥ 10/12 fail**(新 pattern 未实现);**0-2 pass**(regression case 如果有)。

RED commit:

```bash
git commit -m "test(verifier): W13.A RED — extended ID patterns + subject normalization (12+ cases)

W12 D5 gap-to-ceiling analysis identified 4 root causes for the
9.66pp gap between actual (-1.5pp) and ceiling (-11.16pp):
  1. LLM narrative shift (out of sprint scope)
  2. Subject lookup miss (e.g. '17β' vs '17beta')        ← this commit
  3. ID pattern miss (e.g. 'KEGG:C00082' no keyword)     ← this commit
  4. Side effect (W13.C separate diagnostic)

This RED commit adds N cases for extended _ID_PATTERNS regex and a new
subject_normalizer helper. Expected: ≥10/12 fail pre-impl, 0-2 pass
(regression baseline).

GREEN follow-up will:
  - Extend verifier/layers/factual_sub6.py:_ID_PATTERNS (✅ add new regex entries)
  - Add verifier/helpers/subject_normalizer.py (✅ pure add new helper)
  - No verifier-modify-warning needed (no existing code logic changed)"
```

### Stop conditions D1

1. Regression case(若有)pre-impl 不通过 → 必停 ping me
2. RED 阶段意外 PASS(implementation 提前存在)→ test 写错重写

---

## §4 D2 — A 主线 GREEN commit(✅ pure add)

### 改动 1:扩 `verifier/layers/factual_sub6.py:_ID_PATTERNS`

**追加新 regex pattern**(不删 / 不改现有 pattern):

```python
_ID_PATTERNS = [
    # Existing W12 patterns (DO NOT MODIFY)
    (r"\b(?:KEGG|kegg)\s*(?:ID|id|:)?\s*([CD]\d{5})\b", "kegg"),
    (r"\bHMDB\s*(?:ID|id|:)?\s*(HMDB\d{7})\b", "hmdb"),
    (r"\bCHEBI\s*(?:ID|id|:)?\s*(\d+)\b", "chebi"),
    (r"\b([A-Z]{14}-[A-Z]{10}-[A-Z])\b", "inchikey"),
    
    # W13.A: KEGG additional surface forms (✅ add)
    (r"\bKEGG:([CD]\d{5})\b", "kegg"),                    # KEGG:C00082 无 keyword
    (r"\(([CD]\d{5})\)", "kegg_paren"),                   # 括号包裹
    
    # W13.A: PubChem CID (✅ add)
    (r"\bPubChem\s*CID:?\s*(\d{4,9})\b", "pubchem"),
    (r"\bCID:\s*(\d{4,9})\b", "pubchem"),
    (r"pubchem\.ncbi\.nlm\.nih\.gov/compound/(\d+)", "pubchem_url"),
    
    # W13.A: ChEBI additional surface forms (✅ add)
    (r"\bCHEBI[_:](\d+)\b", "chebi_underscore"),          # CHEBI_17234 / CHEBI:17234
    (r"\bchebi:?(\d+)\b", "chebi_lowercase"),             # chebi:17234 / chebi17234
    (r"obo/CHEBI_(\d+)", "chebi_iri"),                    # IRI form
]
```

**不要重排现有 pattern 顺序**(W12 测试的 dispatch 顺序 implicit 依赖)。新 pattern 全 append 在末尾。

### 改动 2:新文件 `verifier/helpers/subject_normalizer.py`(✅ pure add)

```python
"""Subject name normalization for factual_sub6 lookup.

Bridges surface form drift between LLM-written claims and task
differential_metabolites names. Examples:
  - '17β-estradiol' → '17beta-estradiol'
  - 'D-glucose'  vs  'D glucose'  (whitespace)
  - 'L-Tyrosine' vs 'l-tyrosine'  (case)

Pure helper, no I/O, no LLM call.
"""

import re
import unicodedata

# Greek letter → Roman name
_GREEK_MAP = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "ε": "epsilon", "ω": "omega",
    # ASCII fallback for upper-case forms
    "Α": "alpha", "Β": "beta", "Γ": "gamma",
}

def normalize_subject_name(name: str) -> str:
    """Lowercase + ASCII Greek + whitespace normalize + strip stereo prefix dash."""
    if not name:
        return ""
    # Unicode NFKD decompose, drop combining marks
    s = unicodedata.normalize("NFKD", name)
    # Greek letter substitution
    for gr, roman in _GREEK_MAP.items():
        s = s.replace(gr, roman)
    # Lower + collapse whitespace
    s = re.sub(r"\s+", "-", s.strip().lower())
    # Remove stereo prefix dashes for matching
    s = re.sub(r"-+", "-", s)
    return s
```

### 改动 3:`factual_sub6.py:_lookup_in_differential` 用 normalizer(可能触发 ⚠ modify)

**关键决策**:`factual_sub6.py` 当前 `_lookup_in_differential` 用 case-insensitive exact match。要让 normalizer 生效,必须改 lookup 函数。

两选项:
- **A1**:lookup 函数加 fallback —— exact match 失败后用 normalizer 重试。**这是 ⚠ modify factual_sub6.py**,但 layer 是 W12 D3 新加的,**算 W12 layer 内 follow-up 不是 B1-core 修改**,policy 上可接受
- **A2**:在 normalizer 文件提供 `match_with_normalization(name1, name2) -> bool` helper,factual_sub6 lookup 调用它。**这也算 ⚠ modify factual_sub6.py**,语义同

两者都需要改 1 行 lookup 函数。**A1 更直接,推荐**。

**所以 W13.A GREEN 实际有一处 ⚠ modify**(factual_sub6.py:_lookup_in_differential 加 fallback)。commit body 含 warning:

```bash
git commit -m "feat(verifier): W13.A GREEN — extended ID patterns + subject normalizer

[verifier-modify-warning]
This commit modifies verifier/layers/factual_sub6.py (W12 D3 territory,
NOT B1-core). Changes:
  1. _ID_PATTERNS: append 8 new regex entries (KEGG no-keyword, PubChem,
     ChEBI multi-form) — ✅ add only, no existing pattern modified
  2. _lookup_in_differential: add normalizer fallback after exact-match
     fail (⚠ modify lookup logic, 4-line addition)
  3. verifier/helpers/subject_normalizer.py: new file (✅ pure add)

Justification per 2026-05-22 modification policy:
  Why modify _lookup_in_differential (not add new layer):
  - normalizer fallback is intrinsic to factual_sub6's lookup semantic
  - parallel layer would duplicate ~80% of factual_sub6 logic
  - 4-line fallback addition = minimal-diff change
  - exact-match path Stage 1 preserved unchanged

B1 verifier-core test suite re-verified:
  - tests/test_verifier/: 407 pass / 0 fail (= D3 baseline)
  - Full repo: 1345 pass / 14 fail (= W10 D4 baseline, no NEW fail)

W13.A 12-case suite: 12/12 PASS
RED reference: <hash>"
```

### Stop conditions D2

1. **RED 12 case 不全转 PASS** → 必修
2. **B1 verifier-core 407/0 退步** → 必停回滚
3. **W12 14-case suite 退步** → 必停回滚(新 normalizer 不该影响 W12 已有 test)
4. **commit body 缺 [verifier-modify-warning]** → 必停回滚
5. **修改了 _ID_PATTERNS 已有条目**(scope violation,仅 append)→ 必停回滚

---

## §5 D3 — W13.C iter-2 诊断(并行启动)

### 任务

从 W12 D5 数据(`data/concord/w12_path_x_post_c7/path_x_full63_results.jsonl`)pull rollback_reason="iter2_degraded" task,逐 task 看 per-iter quality 分解。

诊断脚本 `scripts/concord/w13_c_iter2_diagnostic.py`(新文件,✅ add):

```python
# 对每个 iter2_degraded task:
#   iter 0 / 1 / 2 各自:
#     n_supported / n_unsupported / n_contradicted / n_unverifiable_v0 / n_dropped
#     quality_score = n_contradicted + n_unsupported  (W10 D4.5 公式,不含 UV)
#   计算:
#     δ_quality (q[2] - q[1])
#     δ_supported (s[2] - s[1])
#     主要 quality 上升 source: unsupported / contradicted / 混合
#
# Aggregate(across all iter2_degraded task):
#   H3 vs new root cause attribution
#     若 δ unsupported 主导 → richer feedback overshoot(H3 延续)
#     若 δ contradicted 主导 → W12 dispatcher case 让更多 claim 拿到 verdict,LLM 二轮触错
#     若混合 → 双 root cause
```

输出 `data/concord/w13_c_iter2_diagnostic/per_task.json` + `summary.md`(纯数据,**不写 paper-style 解读**)。

### W13.C Verdict 期望

```
H3 confirmed(richer feedback overshoot)→ W14 候选:调 max_feedback_iters=1 或 quality metric 公式
H3 refuted + dispatcher case 主导 → W14 候选:dispatcher case 加 soft skip 条件
混合 → W14 双轨调查
```

D3-D5 spread,**纯 analysis,0 production change**,不在 ⚠ modify 范畴。

### Stop conditions D3-D5(C 路径)

1. **W12 D5 jsonl per_iter trace 数据缺失**(rollback_reason 字段不全)→ 必停 ping me
2. **诊断脚本数字与 W12 D5 close-out 不一致**(aggregator bug)→ 必停
3. **Verdict 不明确**(11 task 太少,attribution 模糊)→ 不阻塞 W13 close-out,但 W14 prompt 必须含"再 N=63 全样本上验证"step

---

## §6 D4 — A Path X 全 63 task 重跑

### 配置(同 W10 D4 / W12 D5)

```bash
python scripts/concord/w10_d4_path_x_full.py \
    --benchmark data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
    --output data/concord/w13_a_path_x_post_extended_id/path_x_full63_results.jsonl \
    --max-react-turns 8 --max-feedback-iters 2 --k-concurrent 10 \
    --llm minimax-m2.7
```

**新目录** `data/concord/w13_a_path_x_post_extended_id/`(护栏 2,不覆盖 W10 D4 / W12 D5)。

### Budget

- Wall ~1.5-2h
- API soft $10 / hard $13(W12 D5 实测 $11.17)

---

## §7 D5 — Hard Gate verify

```
Gate Pass(必须同时满足):
  ✓ UV 占比降幅 ≥ 3pp(W12 D5 51.45% → W13 ≤ 48.45%)
  ✓ Pathway 准确率不掉 > 3pp(86% → ≥ 83%)
  ✓ iter-2 deg 不再升(W12 D5 22.22% → W13 ≤ 22.22%)
  ✓ B1 test 407/0 不退步
  ✓ 全 repo 1345/14 不退步

Gate Fail → 必停 ping me + 回滚 D2 GREEN commit
```

### Stop conditions D5

1. Wall > 4h / cost > $13 → halt
2. ≥ 10 task LLM API error / verifier crash → halt
3. **UV 降幅 < 3pp** → 必停 ping me(可能 normalizer 没生效 / new pattern 漏覆盖)
4. **Pathway 准确率掉 > 3pp** → 必停回滚
5. **iter-2 deg 比 W12 D5 22.2% 还高** → 必停 ping me(A 路径不该影响 iter-2,如果升说明引入新副作用)

---

## §8 D6 — W13 Close-out Report

`reports/agent/concord_w13_close_out.md`,**纯数据 + 无 paper-style 解读**:

```markdown
# W13 Close-out Report

## 1. A 主线数字(纯实测)
| metric | W12 D5 | W13.A | Δ |
| supported %         | 26.61 | ??.?? | ?.? pp |
| unsupported %       | 20.37 | ??.?? | ?.? pp |
| contradicted %      |  1.57 | ??.?? | ?.? pp |
| unverifiable_v0 %   | 51.45 | ??.?? | ?.? pp |
| pathway 准确率       | 54/63 | ??/63 | ?.? pp |
| iter-2 deg          | 22.22 | ??.?? | ?.? pp |

## 2. A 主线 strict_id ceiling utilization
- W11 C7 strict_id 总数: 123
- W12 已 cover: 70 (56.9%)
- W13.A 新 cover: ?? (??%)
- 剩余 strict 未 cover: ??(归因:LLM 未引用 / 其他类型 surface form 漏)

## 3. C 副线 iter-2 root cause verdict
(填 C diagnostic 结果)

## 4. W14 候选 ranked(数据驱动)
1. [候选 1, ROI, 风险]
2. [候选 2, ...]
3. ...

## 5. Hard Gate 总判
- Gate 1 UV ≥ 3pp: PASS / FAIL
- Gate 2 pathway ≤ 3pp drop: PASS / FAIL
- Gate 3 iter-2 不再升: PASS / FAIL
- Sprint OVERALL: PASS / PARTIAL / FAIL

## 6. Commits ledger
(列 W13 所有 commit hash)
```

---

## §9 Stop Conditions(任 1 触发停下报告)

1. Onboarding §0 confirmation 缺失就动代码
2. RED 12 case 中 regression case pre-impl 不通过
3. GREEN 12 case 不全转 PASS
4. **B1 verifier-core 407/0 退步**(任 1 NEW fail)
5. **全 repo 1345/14 退步**
6. **W12 14-case suite 退步**(A 新 normalizer 不该影响 W12 老 test)
7. **Path X wall > 4h / cost > $13**
8. **UV 降幅 < 3pp / pathway 准确率掉 > 3pp / iter-2 deg 比 W12 D5 高**
9. **commit body 缺 `[verifier-modify-warning]`** when modify factual_sub6 lookup
10. **修改了 W12 _ID_PATTERNS 已有条目**(scope violation,仅 append)
11. **W13.C 诊断数据与 W12 D5 close-out 数字不一致**

任 1 → 写 `reports/agent/concord_sprint_w13_status.md` § BLOCKED,**不要 work around**。

---

## §10 不要做

- ❌ **不动 fuzzy_biology 103 条**(W15+ 范围,需新 verifier shape)
- ❌ **不做 C8/C9 noise**(W14 候选)
- ❌ **不动 quality_score 函数**(W13.C 出诊断后才决定)
- ❌ **不动 max_feedback_iters=2**(W13.C 出诊断后才决定)
- ❌ **不动 system prompt**(W8 D1 锁定)
- ❌ **不暴露 V3 算法 tool**
- ❌ **不写 paper writeup**(死命令)
- ❌ **不 push origin**
- ❌ **不动 B1 D5/D6 已 commit 评测数据**(护栏 2)
- ❌ **不 `git tag -f` / `git tag -d` metagent-v2-base-b1**(护栏 1)
- ❌ **不修改 W12 已 commit 的 _ID_PATTERNS 已有条目**(scope violation)

---

## §11 完成定义

- [ ] Onboarding §0 完成 + confirmation 在 status file
- [ ] A 主线 12 case RED → GREEN
- [ ] A GREEN commit body 含 `[verifier-modify-warning]` + justification + 实测 B1 数字
- [ ] A Path X 全 63 重跑 + 新目录数据落盘
- [ ] A Hard Gate verify(UV ≥ 3pp + pathway ≤ 3pp + iter-2 ≤ 22.2%)
- [ ] C 主线 iter-2 诊断 verdict 明确(H3 confirmed / refuted / 混合)
- [ ] W13 close-out report + W14 候选 ranked
- [ ] 5-7 commit 在 metagent-v2 branch,未 push
- [ ] Ping user 做 W13 sanity + W14 prompt 启动

---

## §12 一句话目标

A 主线:扩 8 个 ID surface form regex + 加 subject normalizer(Greek/whitespace/case),消化 W11 C7 strict_id 123 条中 W12 未 cover 的 53 条,期望 UV 降 ≥ 3pp(校准 target ≤ ceiling × 0.8)。C 副线:用 W12 D5 数据诊断 iter-2 deg 22.2% root cause(H3 延续 vs W12 dispatcher case 新副作用)。**A + C 并行,W13 末汇总决定 W14 主线**。0 strict-TDD slip 标杆延续 W8-W12。

开干。
