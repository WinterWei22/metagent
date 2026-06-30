# ConcordMet W14 — A 主线 noise prompt 收紧 + B 副线 iter-2 cap

**Worktree:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2`
**Branch:** `metagent-v2`(W13 完结 HEAD `bc3d3e9` 之上)
**Mode:** 5-6 工作日,有人值守
**预算:** ~5d wall + ~$12-13 API(主菜 Path X 重跑 1 次 + 重分类 LLM)

---

## ⚠️ 死命令(全部延续)

- ConcordMet 必须 LLM-driven,不暴露 V3 算法 tool(2026-05-17)
- 不写 paper narrative / Discussion / Methods / Results / footnote / narrative_finalized 等(2026-05-22)
- MiniMax 远程 API,cost 查 `logs/llm_calls.jsonl`,**禁说 "$0 local"**
- 每条 ping 结尾 2 段大白话总结(进展 + 问题,1-3 句各)
- **UV sprint 启动前必做 strict vs fuzzy 重分类**(W12 教训,memory `feedback_uv_sprint_must_reclassify_first`)— **本 sprint §0 第一件事就做**

## ⚠️ Verifier 修改政策(2026-05-22)

W14 **不动 verifier/ 源码**(主菜改 system prompt,副菜改 ConcordMet react_runner)。无 `[verifier-modify-warning]` 触发,但 ⚠️ modify ConcordMet 既有代码 commit body 仍要含 justification + 不退步证据。

3 护栏(tag immutable / B1 paper 数据 immutable / B1 test 14 fail floor)继续守。

---

## §0 必读 Onboarding(50 min,含强制重分类)

### Tier 1:W13 close-out + iter-2 现状(必读,15 min)

1. **`reports/agent/concord_w13_close_out.md`** — W13 数字 + iter-2 deg 22.22% → 15.87% 副作用
   *关键 takeaway*:UV 累计 -5.17pp(52.96% → 47.79%),iter-2 deg 大降 −6.35pp 是 W13.A 副作用(扩识别让 LLM 第一轮更 confident → 第二轮 overshoot 减少)

2. **`data/concord/w13_c_iter2_diagnostic/summary.md`** — H3_CONFIRMED verdict(14/14 unsupported dominant)
   *关键 takeaway*:iter-2 degraded 主因仍是 richer feedback overshoot,W13.A 副作用降了 6pp 但未消除

3. **`reports/agent/concord_w11_uv_diagnosis.md`** §3 — C8 + C9 sample
   *关键 takeaway*:看 C8(9 条 noise)+ C9(139 条 other)真实长什么样,**这是 §0 重分类的 source data**

### Tier 2:W14 改动区(必读,10 min)

4. **`prompts/concord/concord_react_prompt.md`** — ConcordMet ReAct system prompt(W14.A 主战场)
   *Why:* W14.A 收紧 noise patterns 是改这份 prompt;读现有 banned phrase 列表(若有)+ instruction 风格

5. **`concord/agent/react_runner.py`** — search `max_feedback_iters` 默认值 + 用法
   *Why:* W14.B cap iter-2 是改这里;了解当前 default=2 的传入路径 + 测试 mock 点

6. **`verifier/grammar.py`** — `DroppedReason` enum / dropped subtype(若有)
   *Why:* W14.A 可能把 C8 noise 显式标 dropped_by_grammar subtype="noise_pattern"(精确归类不计入 UV)

### Tier 3:W12 教训 + 政策(必读,5 min)

7. **memory `feedback_uv_sprint_must_reclassify_first`** — 重分类 protocol
8. **memory `feedback_verifier_modification_policy`** — 三档准则

### §0 强制重分类 sub-task(20 min,W12 教训落地)

**任务**:用 LLM 把 W11 C8 9 条 + C9 139 条 = **148 条 claim** 重分类为 2 类:

- **strict_noise**(本 sprint 真能消除):LLM 走神 / 重复段 / 与 task 无关的废话 / 模板套话("以上是分析结果" / "进一步研究需..." / pasted prompt fragment)
- **valid_content**(被 W11 误归 C9,实际有信息):可能是被错分的 C1/C3/C5 内容,本 sprint 不该动

脚本 `scripts/concord/w14_c8c9_strict_vs_valid.py`(新文件,纯 analysis):

```python
# Pull W11 C8 + C9 148 claim 的 claim_text + claim_type + task_id
# 用 MiniMax 一次性 batch 分类(50 条/batch,3 batch,~$0.3)
# 输出:data/concord/w14_uv_reclassify/c8c9_strict_vs_valid.csv
#   columns: original_id, w11_category, w14_label, sample_text
# Aggregate verdict:
#   strict_noise count / valid_content count
#   strict_noise / 1102 total UV = sprint ceiling
```

**预算**:0.3-0.5d wall + ~$0.5 API。

### Onboarding 完成确认

写到 `reports/agent/concord_sprint_w14_status.md` § "0. Onboarding":

```
Tier 1 W13 close-out:
  - UV 累计降 5.17pp(52.96 → 47.79)
  - iter-2 deg W12→W13 大降副作用 22.22 → 15.87

Tier 2 W14 改动区:
  - concord_react_prompt.md banned phrase 现状: [描述]
  - react_runner.py max_feedback_iters default=2 入口: [函数 + 行号]
  - grammar.py DroppedReason enum: [是否存在 / 是否需新增 subtype]

Tier 3 政策: 重分类 protocol + 修改政策 ✓

§0 重分类 verdict(必填!):
  C8 + C9 = 148 条
  strict_noise: ?? 条(本 sprint 可 cover)
  valid_content: ?? 条(本 sprint 不动,可能要分回 C1/C3/C5)
  sprint ceiling: strict_noise / 1102 = ?.?pp
  target: ≤ ceiling × 0.8 = ?.?pp

Confirmation:
  (a) W14.A 主菜:concord_react_prompt.md 加 banned phrases + 可选 grammar.py 加 noise subtype(✅ add for grammar,⚠ modify for prompt)
  (b) W14.B 副菜:react_runner.py max_feedback_iters default 2→1(⚠ modify ConcordMet 既有代码)
  (c) Target 已校准:UV 降幅 ≥ target × 0.6(留 buffer)
  (d) iter-2 cap 期望:cost -33%,iter-2 deg ≤ 15.87%(W13 baseline 不退步)
  (e) 不动 verifier/ 源码(B1-core 仍 ❌ 级)
  (f) 不写 paper writeup
```

未完成重分类 → 不许设 target / 动代码。

---

## §1 W14 任务目标(一段话)

**主菜 A**:扩 `prompts/concord/concord_react_prompt.md` 的 banned phrase 列表 + grammar.py 加 `DroppedReason.NOISE_PATTERN` subtype,让 LLM 在 narrative 阶段就**不产** strict_noise 类 claim(W11 C8 + C9 strict_noise 子集)。**副菜 B**:把 `concord/agent/react_runner.py:max_feedback_iters` 默认值从 2 降到 1,验证 W13 iter-2 deg 6.35pp 副作用是否锁定 + cost 降 ~33%。**双线 Hard Gate**:UV 降幅 ≥ §0 重分类 ceiling × 0.6 / pathway 准确率不掉 > 3pp / iter-2 deg 不超 15.87%(W13 baseline)/ B1 test 407/0 不退步。

---

## §2 5-6 天 daily breakdown

| Day | 主菜 A(noise prompt)| 副菜 B(iter-2 cap)|
|---|---|---|
| **D1** | Onboarding + §0 重分类 + 重分类结果写 status | — |
| **D2** | RED:concord_react_prompt 改动 + grammar.py 新 subtype unit test | RED:react_runner max_feedback_iters cap unit test |
| **D3** | GREEN A:prompt 加 banned phrases + grammar.py 加 NOISE_PATTERN(✅ add)| GREEN B:max_feedback_iters default=1(⚠ modify) |
| **D4** | Gate verify(test + B1 不退步) | 同左 |
| **D5** | Path X 全 63 task 重跑(同 W13.A 配置,~$10-12) | 数据复用 D5 同一 run |
| **D6** | Close-out report + W15 候选 ranked | — |

预期 **6-8 commit**(onboarding + 重分类 + A RED + A GREEN + B RED + B GREEN + Path X + close-out)。

---

## §3 D2 — RED commits(两组,strict TDD per piece)

### A 组:noise prompt + grammar subtype RED

`tests/test_grammar_noise_pattern.py`(新文件,**至少 5 case**):

```python
# 1. NOISE_PATTERN enum value 存在
def test_dropped_reason_noise_pattern_enum_exists():
    """grammar.py DroppedReason 应有 NOISE_PATTERN value。"""
    from verifier.grammar import DroppedReason
    assert hasattr(DroppedReason, 'NOISE_PATTERN')

# 2-4: validator 识别 3 类 strict_noise pattern
def test_validator_marks_meta_filler_as_noise():
    """claim_text: '以上是分析结果' / '总结如下' → dropped, reason=NOISE_PATTERN."""

def test_validator_marks_template_boilerplate_as_noise():
    """claim_text: '进一步研究需要...' / 'future work suggests...' → noise."""

def test_validator_marks_self_reference_as_noise():
    """claim_text: '如上所述' / 'as mentioned above' → noise."""

# 5. regression: 正常 claim 不被误标
def test_validator_does_not_mark_real_claim_as_noise():
    """claim_text: 'L-tyrosine is in KEGG pathway hsa00350' → NOT noise."""
```

**`tests/test_concord_react_prompt_banned.py`**(新文件 OR 加到既有 test_prompt_banned_sync.py,**至少 3 case**):

```python
# 1. concord_react_prompt.md 含新 banned phrase 段
def test_concord_prompt_contains_noise_banned_section():
    """prompt 文件应含 '## BANNED PHRASES (noise patterns)' 段。"""

# 2. banned list 含 W14.A 锁定的关键 pattern
def test_concord_prompt_bans_meta_filler():
    """'以上是分析结果' / '总结如下' / 'as a metabolomics analyst' 在 banned list。"""

# 3. instruction 含 noise 警告
def test_concord_prompt_instructs_against_template_boilerplate():
    """prompt 应明确告知 LLM 不要写 template-style boilerplate。"""
```

### B 组:iter-2 cap RED

`tests/test_react_runner_iter_cap.py`(新文件,**至少 3 case**):

```python
# 1. default 改成 1
def test_react_runner_default_max_feedback_iters_is_one():
    """ConcordReactRunner 默认 max_feedback_iters 应为 1(W14.B cap)。"""

# 2. iter 2 在 default=1 下不触发
def test_iter_2_not_triggered_under_default_cap():
    """在 default config 下,quality_n0>0 → 触发 iter 1,但不该触发 iter 2。"""

# 3. backward compat:显式传 max_feedback_iters=2 仍 work
def test_explicit_max_feedback_iters_2_still_supported():
    """显式传 max_feedback_iters=2 → iter 2 仍可触发(不破坏 W10/W13 复现性)。"""
```

### RED 阶段执行 + commit

```bash
pytest tests/test_grammar_noise_pattern.py \
       tests/test_concord_react_prompt_banned.py \
       tests/test_react_runner_iter_cap.py -v
# 预期 A 组 ≥ 4/5 fail + 3/3 fail / B 组 ≥ 2/3 fail
```

**两个 RED commit 分开**(strict TDD per piece):

```
test(verifier): W14.A RED — grammar NOISE_PATTERN + concord prompt banned (8 cases)
test(concord): W14.B RED — react_runner max_feedback_iters cap (3 cases)
```

### Stop conditions D2

1. Regression case 5(real claim 不被误标)pre-impl 不通过 → 现有 validator bug,**必停 ping me**
2. B 组 case 3(backward compat)pre-impl PASS → 期望 fail 因为 default 还是 2,但 explicit 路径已 work,这不算 spec violation,但要 commit body 说明

---

## §4 D3 — GREEN commits(两组)

### A 组:noise prompt + grammar subtype GREEN

**改动 1**:`verifier/grammar.py` 加 `DroppedReason.NOISE_PATTERN`(✅ add)

```python
class DroppedReason(str, Enum):
    # existing values unchanged
    NOISE_PATTERN = "noise_pattern"   # W14.A: meta-filler / template / self-reference
```

**改动 2**:validator 加 noise pattern 检测(✅ add 新 helper)

```python
# verifier/helpers/noise_pattern.py(新文件)
"""W14.A noise pattern detection.

Identifies meta-filler / template-boilerplate / self-reference claims
that should be DROPPED before reaching layer dispatch (not UV).

Pure function, no I/O.
"""
import re

_NOISE_PATTERNS = [
    r"以上是分析结果",
    r"总结如下",
    r"future work",
    r"进一步研究需要",
    r"as mentioned above",
    r"如上所述",
    r"in summary",
    # ... 完整 list 基于 §0 重分类 sample
]

def is_noise_claim(claim_text: str) -> bool:
    for pat in _NOISE_PATTERNS:
        if re.search(pat, claim_text, re.IGNORECASE):
            return True
    return False
```

`verifier/agent.py` 在 claim extraction 后调用 `is_noise_claim`,标 `DroppedReason.NOISE_PATTERN` 而非走 layer。**这是 ⚠ modify verifier/agent.py**,需 `[verifier-modify-warning]` body。

**改动 3**:`prompts/concord/concord_react_prompt.md` 加 banned phrases 段(⚠ modify concord prompt)

```markdown
## BANNED PHRASES — DO NOT WRITE

Avoid template boilerplate and self-referential filler. The following 
phrases (in any language) are automatically dropped by the verifier 
and waste your output budget:

- 以上是分析结果 / 总结如下 / 如上所述
- "as a metabolomics analyst" / "in this analysis"
- "future work" / "further research" / "进一步研究需要"
- "as mentioned above" / "see above"
- "in summary" / "in conclusion"

Every claim must reference a concrete metabolite, pathway, or tool result.
```

### A 组 commit body

```
feat(verifier): W14.A GREEN main — grammar NOISE_PATTERN subtype + concord prompt banned phrases

[verifier-modify-warning]
This commit modifies TWO files (one verifier source, one concord prompt):
  1. verifier/agent.py — adds noise_pattern check before layer dispatch
     (4-line addition, exact-existing flow preserved)
  2. prompts/concord/concord_react_prompt.md — adds BANNED PHRASES section
     (concord-side prompt, but standalone modify-warning recommended)

Pure adds:
  - verifier/grammar.py: DroppedReason.NOISE_PATTERN enum value
  - verifier/helpers/noise_pattern.py: is_noise_claim() helper

Justification per 2026-05-22 modification policy:
  Why modify verifier/agent.py (modify 1):
  - noise_pattern routing must happen BEFORE layer dispatch (otherwise
    noise claims still route to e.g. factual_sub6 and waste verify cycles)
  - 4-line check before existing dispatch = minimal-diff
  - All other dispatch paths preserved unchanged

  B1 verifier-core test suite re-verified:
  - tests/test_verifier/: <count> pass / 0 fail
  - tests/test_d4_feedback_dispatcher.py: <count> pass
  - tests/test_grammar_validate.py: <count> pass
  - tests/test_classifier_collapse.py: <count> pass

  Full repo pytest: <count> pass / 14 fail (= W13 baseline, no NEW fail)

W14.A 8 case suite: 8/8 PASS
RED reference: <hash>
```

### B 组:iter-2 cap GREEN

`concord/agent/react_runner.py` 找到 `max_feedback_iters` 默认值,从 `2` 改 `1`:

```python
@dataclass
class ConcordReactRunner:
    # existing fields...
    max_feedback_iters: int = 1   # W14.B: was 2, cap iter-2 per W13.C H3_CONFIRMED diagnostic
```

### B 组 commit body

```
feat(concord): W14.B GREEN side — cap max_feedback_iters default 2→1

[concord-modify-warning]
This commit modifies concord/agent/react_runner.py default config.

Justification per W13.C iter-2 diagnostic (commit 24975d3):
  - H3_CONFIRMED on N=14 iter-2-degraded task: 14/14 unsupported dominant
  - W13.A already reduced iter-2 deg 22.22→15.87 pp (副作用)
  - W14.B caps remaining iter-2 overshoot at source: default=1 prevents
    iter 2 from triggering at all under default config
  - Backward compat: explicit max_feedback_iters=2 still works
    (W10/W13 reproducibility preserved)

Expected impact:
  - API cost per task: -33% (3 iter → 2 iter on closed-loop path)
  - iter-2 deg: ≤ 15.87% (W13.A baseline preserved or further reduced)
  - supported %: marginal change (iter-2 contributed some legitimate gains)

Tests added: tests/test_react_runner_iter_cap.py (3 case)
RED reference: <hash>
```

### Stop conditions D3

1. A 组 8 case 不全 PASS → 必修
2. B 组 3 case 不全 PASS → 必修
3. B1 verifier-core 退步 → 必停回滚
4. W13 26 case 退步(W12 14 + W13 12)→ 必停回滚
5. commit body 缺 warning + justification + 实测数字 → 必停
6. Path X 重跑前**两个 GREEN commit 都必须 land**

---

## §5 D4 — Sanity gate verify

**Gate A**(B1 verifier-core,必过)+ **Gate B**(全 repo)+ **Gate C**(concord/)同 W12/W13。

特别留意:
- **Gate C**:concord/ subtree 测试不退步(W14.B react_runner 改动可能误伤)
- 全 repo pass count 应 = W13 1357 + W14 新 case 11 = **1368 pass / 14 fail**

---

## §6 D5 — Path X 全 63 task 重跑

```bash
python scripts/concord/w10_d4_path_x_full.py \
    --benchmark data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
    --output data/concord/w14_path_x_post_noise_cap/path_x_full63_results.jsonl \
    --max-react-turns 8 --max-feedback-iters 1 --k-concurrent 10 \
    --llm minimax-m2.7
```

**注意 `--max-feedback-iters 1`**(显式传 1,verify B 改动生效)。

**新目录** `data/concord/w14_path_x_post_noise_cap/`(护栏 2,不覆盖 W13.A)。

**Budget**:wall **~1.5h**(B cap 后比 W13 2h 更短 ~30%),API soft **$7** / hard **$10**(B cap 后比 W13 $10 更便宜)。

---

## §7 D5 末 — Hard Gate 判定

```
Gate Pass(必须同时满足):
  ✓ UV 占比降幅 ≥ §0 重分类 ceiling × 0.6(W14 spec target)
  ✓ Pathway 准确率不掉 > 3pp(86% → ≥ 83%)
  ✓ iter-2 deg ≤ 15.87%(W13 baseline 不退步)
  ✓ API cost ≤ $10(比 W13 $9.90 降至少 25%,验证 B cap 生效)
  ✓ B1 test 407/0 + 全 repo 14 fail floor

Gate Fail → 必停 ping me + 回滚 GREEN commit
```

### Stop conditions D5

1. Wall > 3h(K=10 应 ~1.5h)→ 性能 regress
2. API cost > $10(B cap 后应 < W13 的 $9.90)→ B cap 没生效
3. ≥ 10 task LLM API error / verifier crash → halt
4. **UV 降幅 < spec target** → 必停 ping me
5. **iter-2 deg > 15.87%** → 必停 ping me(B cap 期望降或持平,如升说明 backward compat 路径错触发)
6. Pathway 准确率掉 > 3pp → 必停回滚

---

## §8 D6 — Close-out + W15 候选 ranked

`reports/agent/concord_w14_close_out.md`,**纯数据 + 短 caption,无 paper-style 解读**:

```markdown
## 1. W14 数字
| metric | W13.A | W14 | Δ |
| supported % | 31.91 | ??.?? | ?.? pp |
| unsupported % | 18.21 | ??.?? | ?.? pp |
| contradicted % | 2.08 | ??.?? | ?.? pp |
| unverifiable_v0 % | 47.79 | ??.?? | -?.? pp |
| pathway 准确率 | 54/63 | ??/63 | ?.? pp |
| iter-2 deg | 15.87% | ??.??% | ?.? pp |
| API cost / Path X | $9.90 | $?.?? | -??% |

## 2. §0 重分类 ceiling utilization
- C8+C9 148 → strict_noise: ?? / valid_content: ??
- ceiling: ?.?pp
- W14 actual: -?.?pp = ?% of ceiling

## 3. W15 候选 ranked
1. C3 signal_evidence(读 task z-score 字段,第一次接新数据通道,~1.5d)
2. C5 intermediate_biology(KEGG 反应图 layer)
3. C1+C2 cross-method(架构改造,让 verifier 看 5 PA 工具输出)
```

---

## §9 Stop Conditions(任 1 触发停下报告)

1. §0 重分类未做 / target 未基于 ceiling × 0.8 校准
2. Regression case 5(real claim 不被误标)pre-impl 不通过
3. B1 verifier-core 退步
4. W13 26 case 退步
5. commit body 缺 warning 或 justification 或 placeholder 数字
6. Path X wall > 3h / cost > $10
7. UV 降幅 < spec target
8. iter-2 deg > 15.87%
9. Pathway 准确率掉 > 3pp

---

## §10 不要做

- ❌ 不动 verifier/layers/(W14 主菜在 prompt + grammar 层)
- ❌ 不动 W12 factual_sub6.py / W13 _ID_PATTERNS(scope violation)
- ❌ 不写 paper writeup
- ❌ 不暴露 V3 算法 tool
- ❌ 不 push origin
- ❌ 不动 B1 D5/D6 已 commit 评测数据
- ❌ 不预先做 W15 C3 signal_evidence(留 W15 sprint)
- ❌ 不动 max_react_turns(W14.B 只动 max_feedback_iters)

---

## §11 完成定义

- [ ] §0 Onboarding + 重分类 + confirmation
- [ ] A 8 case + B 3 case RED → GREEN
- [ ] 两个 GREEN commit body 含 warning + justification + 实测 B1 数字
- [ ] Path X 全 63 重跑 + 新目录数据(--max-feedback-iters 1)
- [ ] Hard Gate verify(UV / pathway / iter-2 / cost / B1 + 全 repo)
- [ ] Close-out report + W15 候选 ranked
- [ ] 6-8 commit 在 metagent-v2 branch,未 push
- [ ] Ping me

---

## §12 一句话目标

**主菜 A**:让 LLM 不再产 strict_noise claim(prompt banned phrases + grammar NOISE_PATTERN subtype),消化 W11 C8+C9 148 条中 §0 重分类后 strict_noise 子集。**副菜 B**:`max_feedback_iters` default 2→1,锁定 W13 iter-2 deg 6pp 副作用 + cost -33%。**Hard Gate**:UV 降 ≥ ceiling × 0.6 + pathway ≤ 3pp drop + iter-2 ≤ 15.87% + cost ≤ $10 + B1 不退步。Strict TDD per piece + ⚠ modify 全标 warning + body 实测数字 non-placeholder。

W8-W13 累计 ~45 commit / 0 strict-TDD slip 标杆延续。开干。
