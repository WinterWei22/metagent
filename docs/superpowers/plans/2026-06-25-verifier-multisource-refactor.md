# Verifier 多源证据池重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 verifier 的"事实底座"从单源 RaMP 改成 5-paradigm 多源证据池,修复 v4 benchmark 上 verifier 100% 崩溃,拿到真实 UV 数字。

**Architecture:** 三层断裂分别修复 —— (1) react_runner 补 RaMP carrier 捕获;(2) adapter 加 v4 格式分支;(3) set_enrichment 重写为多源池命中任一 SUPPORTED + INSUFFICIENT_EVIDENCE 补查 + top-1 alternative。复用 W22 `method_aware_enrichment` 的 carrier 解析与 2B `pathway_name_matcher` 的语义匹配。

**Tech Stack:** Python 3.13, pydantic v2, pytest。远程 MiniMax API(cost 查 `logs/llm_calls.jsonl`)。

## Global Constraints

- 中文对话,英文代码/标识符。模型名 **MetAgent**。
- Verifier 三档政策:加新代码 ✅ / 改现有 verifier 逻辑 ⚠ commit body 含 `[verifier-modify-warning]` + B1 回归实测 / 改 B1-core ❌。
- 改 `concord/` ⚠ commit body 含 `[concord-modify-warning]`。
- **Gate A 不退步**:`PYTHONPATH=. pytest tests/test_verifier/ tests/test_d4_feedback_dispatcher.py tests/test_grammar_validate.py tests/test_classifier_collapse.py tests/test_runner_response_format.py tests/test_prompt_banned_sync.py -q` 期望 **408 pass / 0 fail**(+本次新增用例)。
- 三护栏:`metagent-v2-base-b1` tag immutable / B1 paper 数据 immutable / 14-fail floor 不退。
- 严格 TDD:每 task 先 RED 再 GREEN,独立 commit。
- subagent 用 **sonnet 4.6**(复杂逻辑)或 **haiku 4.5**(机械/单文件)。
- `python3` = conda(3.13);`pytest` 用 `PYTHONPATH=. python3 -m pytest`。
- 设计依据:`docs/decisions/2026-06-25_verifier_multisource_refactor.md`。

---

## File Structure

| 文件 | 责任 | task |
|---|---|---|
| `concord/agent/react_runner.py:1036` `_store_enrichment_carrier` | 补 RaMP carrier 捕获 | T1 |
| `concord/agent/verifier_adapter.py` | 新增 `v4_task_to_subsix_source_report` | T2 |
| `verifier/helpers/multisource_enrichment.py`(新) | 合并 5 carrier → 统一 pool | T3 |
| `verifier/layers/set_enrichment.py` | 重写:多源池命中任一 SUPPORTED | T4 |
| `verifier/schemas.py` `ClaimVerdict` | 加 `INSUFFICIENT_EVIDENCE` enum | T5 |
| `verifier/layers/set_enrichment.py` | 不命中→INSUFFICIENT + checklist | T6 |
| `concord/agent/react_runner.py` verdict filter + metrics | 识别新 enum | T7 |
| `verifier/layers/set_enrichment.py` | CONTRADICTED 注入 top-1 alt | T8 |
| `verifier/layers/driver_metabolite.py` | v4 无 ground truth → 降级 | T9 |
| `scripts/metagent/v4_verifier_rerun.py`(新) | v4 重跑 + UV + 假阳 sanity | T10 |

---

### Task 1 (D0.1): react_runner 补 RaMP carrier 捕获 — `[concord-modify-warning]`

**根因:** `_store_enrichment_carrier`(react_runner.py:1044-1051)只处理 mummichog/metaboanalystr/sspa/fella,**漏了 `run_ramp_enrichment`** → verifier 最依赖的 RaMP carrier 永远空。

**Files:**
- Modify: `concord/agent/react_runner.py:1036-1051`
- Test: `tests/concord/test_ramp_carrier_capture.py`(新)

**Interfaces:**
- Produces: `_store_enrichment_carrier(carriers, "run_ramp_enrichment", payload)` 后 `carriers["ramp_enrichment_result"]` 含 payload["result"]

**建议模型:** haiku 4.5(单分支机械改动)

- [ ] **Step 1: RED — 写失败测试**

```python
# tests/concord/test_ramp_carrier_capture.py
from concord.agent.react_runner import _store_enrichment_carrier

def test_ramp_enrichment_carrier_captured():
    carriers = {}
    payload = {"ok": True, "result": {"top_pathways": [{"pathway_id": "KEGG:hsa00350", "pathway_name": "Tyrosine metabolism"}]}}
    _store_enrichment_carrier(carriers, "run_ramp_enrichment", payload)
    assert "ramp_enrichment_result" in carriers
    assert carriers["ramp_enrichment_result"]["top_pathways"][0]["pathway_id"] == "KEGG:hsa00350"

def test_ramp_carrier_skips_failed_payload():
    carriers = {}
    _store_enrichment_carrier(carriers, "run_ramp_enrichment", {"ok": False})
    assert "ramp_enrichment_result" not in carriers
```

- [ ] **Step 2: 运行确认 FAIL** — `PYTHONPATH=. python3 -m pytest tests/concord/test_ramp_carrier_capture.py -v` 期望 FAIL(carrier 不含 ramp)
- [ ] **Step 3: GREEN** — 在 `_store_enrichment_carrier` 加首分支:

```python
    if tool_name == "run_ramp_enrichment":
        carriers["ramp_enrichment_result"] = result
    elif tool_name == "run_mummichog":
        carriers["mummichog_enrichment_result"] = result
    # ... 其余不变
```

- [ ] **Step 4: 运行确认 PASS** + Gate A 不退步
- [ ] **Step 5: Commit**

```bash
git add concord/agent/react_runner.py tests/concord/test_ramp_carrier_capture.py
git commit -m "fix(carrier): capture run_ramp_enrichment into ramp_enrichment_result

[concord-modify-warning]
根因: _store_enrichment_carrier 漏了 run_ramp_enrichment 分支,导致 verifier
最依赖的 RaMP carrier 永远为空。补单分支。Gate A 408/0 不退步。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2 (D0.2): adapter v4 格式分支 — `[concord-modify-warning]`

**根因:** `sub6b_task_to_subsix_source_report`(verifier_adapter.py:257)硬读 v3 键;v4 task 是 `{input:{differential_metabolites}, ground_truth:{perturbed_pathway, mechanism_evidence}}` → 6 字段全 None → 112/112 崩。

**Files:**
- Modify: `concord/agent/verifier_adapter.py`(新增函数,不改旧函数)
- Modify: `concord/agent/react_runner.py`(verify_with_b1 调 adapter 处加 v4 分流,约 line 757)
- Test: `tests/concord/test_v4_adapter.py`(新)

**Interfaces:**
- Produces: `v4_task_to_subsix_source_report(task: dict, react_result) -> SubsixSourceReport` —— 从 `task["ground_truth"]["perturbed_pathway"]` 取 `{id,name,ontology}` 填 `ground_truth_pathway`;从 `react_result.enrichment_carriers` 收全 5 carrier;`task_type="compound_only_enrichment"`,`domain=ontology`,`ground_truth_signal_compounds=[]`,`ground_truth_noise_compounds=[]`,`differential_metabolites=task["input"]["differential_metabolites"]`
- 检测 v4:`"perturbed_pathway" in task.get("ground_truth", {})` 或顶层缺 `ramp_enrichment_result`

**建议模型:** sonnet 4.6(跨文件 + 格式映射)

- [ ] **Step 1: RED** — 测试 v4 task 行能构造成功 + 5 carrier 落字段

```python
# tests/concord/test_v4_adapter.py
from concord.agent.verifier_adapter import v4_task_to_subsix_source_report

class _FakeReact:
    enrichment_carriers = {
        "ramp_enrichment_result": {"top_pathways": [{"pathway_id": "KEGG:hsa00350", "pathway_name": "Tyrosine metabolism"}]},
        "mummichog_enrichment_result": {"pathways": [{"pathway_id": "MUMM:tyrosine_metabolism"}]},
    }

def _v4_task():
    return {
        "task_id": "t1",
        "input": {"context": "", "differential_metabolites": [{"name": "L-tyrosine", "smiles": "N[C@@H](Cc1ccc(O)cc1)C(=O)O", "inchikey": "OUYCCCASQSFEME-QMMMGPOBSA-N"}]},
        "ground_truth": {"perturbed_pathway": {"id": "hsa00350", "name": "Tyrosine metabolism", "ontology": "KEGG"}, "mechanism_evidence": {}},
    }

def test_v4_adapter_builds_report():
    r = v4_task_to_subsix_source_report(_v4_task(), _FakeReact())
    assert r.task_id == "t1"
    assert r.task_type == "compound_only_enrichment"
    assert r.ground_truth_pathway["pathway_name"] == "Tyrosine metabolism"
    assert r.ramp_enrichment_result["top_pathways"][0]["pathway_id"] == "KEGG:hsa00350"
    assert r.mummichog_enrichment_result is not None
    assert r.differential_metabolites[0]["name"] == "L-tyrosine"

def test_v4_adapter_empty_ground_truth_compounds():
    r = v4_task_to_subsix_source_report(_v4_task(), _FakeReact())
    assert r.ground_truth_signal_compounds == []
    assert r.ground_truth_noise_compounds == []
```

- [ ] **Step 2: 确认 FAIL**(函数不存在)
- [ ] **Step 3: GREEN** — 实现 `v4_task_to_subsix_source_report`;在 `react_runner.verify_with_b1` 调 adapter 处:`if _is_v4_task(task): src = v4_task_to_subsix_source_report(task, react_result) else: src = sub6b_task_to_subsix_source_report(task)`
- [ ] **Step 4: 确认 PASS** + Gate A
- [ ] **Step 5: Commit**(body 含 `[concord-modify-warning]` + Gate A 数字)

---

### Task 3 (D1.1): multisource_enrichment helper

**Files:**
- Create: `verifier/helpers/multisource_enrichment.py`
- Test: `tests/test_multisource_enrichment.py`(新)

**Interfaces:**
- Produces: `build_pathway_pool(source_report) -> list[dict]` —— 把 5 个 carrier(`ramp_enrichment_result.top_pathways` / `mummichog_enrichment_result.pathways` / `metaboanalystr_enrichment_result.psea.pathways` / `sspa_enrichment_result.pathways` / `fella_enrichment_result.rwr.pathways`)的行合并成一个 list,每行附 `_paradigm` 来源标记
- Produces: `match_in_pool(pool, pathway_id, pathway_name) -> dict | None` —— 命中任一行返回该行(含 `_paradigm`),复用 `method_aware_enrichment._find_row` 的 ID 等价 + 复用 `concord.lookup.pathway_name_matcher.PathwayNameMatcher` 的名称语义匹配

**建议模型:** sonnet 4.6(合并逻辑 + 复用多个现有 helper)

- [ ] **Step 1: RED**

```python
# tests/test_multisource_enrichment.py
from verifier.helpers.multisource_enrichment import build_pathway_pool, match_in_pool
from schemas.sub6_report import SubsixSourceReport

def _src(**carriers):
    base = dict(task_id="t", task_type="compound_only_enrichment", domain="KEGG",
                ground_truth_pathway={}, ground_truth_signal_compounds=[],
                ground_truth_noise_compounds=[], ramp_enrichment_result={"top_pathways": []})
    base.update(carriers)
    return SubsixSourceReport(**base)

def test_pool_merges_all_paradigms():
    src = _src(
        ramp_enrichment_result={"top_pathways": [{"pathway_id": "KEGG:hsa00350", "pathway_name": "Tyrosine metabolism"}]},
        mummichog_enrichment_result={"pathways": [{"pathway_id": "MUMM:histidine", "pathway_name": "Histidine metabolism"}]},
    )
    pool = build_pathway_pool(src)
    paradigms = {row["_paradigm"] for row in pool}
    assert "ramp" in paradigms and "mummichog" in paradigms

def test_match_hits_any_paradigm():
    src = _src(mummichog_enrichment_result={"pathways": [{"pathway_id": "MUMM:histidine", "pathway_name": "Histidine metabolism"}]})
    pool = build_pathway_pool(src)
    hit = match_in_pool(pool, None, "Histidine metabolism")
    assert hit is not None and hit["_paradigm"] == "mummichog"

def test_match_returns_none_when_absent():
    src = _src(ramp_enrichment_result={"top_pathways": [{"pathway_id": "KEGG:hsa00350", "pathway_name": "Tyrosine metabolism"}]})
    pool = build_pathway_pool(src)
    assert match_in_pool(pool, None, "Glycolysis") is None
```

- [ ] **Step 2: 确认 FAIL** → **Step 3: GREEN**(复用 `method_aware_enrichment._find_row`、`pathway_namespace.pathway_ids_equivalent`、`PathwayNameMatcher`)→ **Step 4: PASS** + Gate A → **Step 5: Commit**(加新代码 ✅)

---

### Task 4 (D1.2): 重写 verify_set_enrichment 用多源池 — `[verifier-modify-warning]`

**Files:**
- Modify: `verifier/layers/set_enrichment.py`(重写主判定)
- Test: `tests/test_set_enrichment_multisource.py`(新)+ 现有 `tests/test_verifier/test_layer_set_enrichment.py`(10 个,**必须仍过** — 向后兼容:RaMP 是池一部分)

**Interfaces:**
- Consumes: T3 `build_pathway_pool` / `match_in_pool`
- Produces: `verify_set_enrichment(claim, source_report)` —— 命中多源池任一 → SUPPORTED(evidence 注明命中 paradigm);保留旧 verdict 语义(无 pathway/空池 → UV)

**建议模型:** sonnet 4.6(核心重写 + 向后兼容)

- [ ] **Step 1: RED** — 新测试:claim 只命中非 RaMP paradigm 也 SUPPORTED

```python
# tests/test_set_enrichment_multisource.py
from verifier.layers.set_enrichment import verify_set_enrichment
from verifier.schemas import ClaimVerdict, ClaimType, ClaimSubtype, ClassifiedClaim, ClaimExtractedFields
from schemas.sub6_report import SubsixSourceReport

def _claim(name):
    return ClassifiedClaim(claim_text=f"enriched in {name}", claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY, classifier_source="rule",
        extracted_fields=ClaimExtractedFields(pathway_name=name))

def _src(**c):
    base = dict(task_id="t", task_type="compound_only_enrichment", domain="KEGG",
        ground_truth_pathway={}, ground_truth_signal_compounds=[], ground_truth_noise_compounds=[],
        ramp_enrichment_result={"top_pathways": []})
    base.update(c); return SubsixSourceReport(**base)

def test_hit_in_mummichog_only_supported():
    src = _src(mummichog_enrichment_result={"pathways": [{"pathway_id": "MUMM:histidine", "pathway_name": "Histidine metabolism"}]})
    r = verify_set_enrichment(_claim("Histidine metabolism"), src)
    assert r.verdict == ClaimVerdict.SUPPORTED
```

- [ ] **Step 2: 确认 FAIL** → **Step 3: GREEN**(主判定改查多源池;先 ID/名称命中池任一 → SUPPORTED)→ **Step 4: PASS** + **现有 10 个 set_enrichment 测试全过** + Gate A 408/0 → **Step 5: Commit**

```bash
git commit -m "feat(verifier): rewrite set_enrichment to multisource pathway pool

[verifier-modify-warning]
Justification: v4 范式下富集结果由 5 paradigm 运行时产出,单源 RaMP 底座失效。
重写主判定为多源池命中任一 SUPPORTED。RaMP 仍是池一部分 → 旧 B1 测试向后兼容。
B1 回归: Gate A 408/0 不退步; 现有 10 个 set_enrichment 测试全过。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5 (D2.1): 加 ClaimVerdict.INSUFFICIENT_EVIDENCE enum

**Files:**
- Modify: `verifier/schemas.py` `ClaimVerdict`(加 enum 值,加新代码 ✅)
- Test: `tests/test_insufficient_evidence_enum.py`(新)

**Interfaces:**
- Produces: `ClaimVerdict.INSUFFICIENT_EVIDENCE = "insufficient_evidence"`(语义:池内无该通路但可补查,区别于 UV=范式外无法判)

**建议模型:** haiku 4.5(单 enum 值)

- [ ] **Step 1: RED**

```python
# tests/test_insufficient_evidence_enum.py
from verifier.schemas import ClaimVerdict
def test_insufficient_evidence_exists():
    assert ClaimVerdict.INSUFFICIENT_EVIDENCE.value == "insufficient_evidence"
```

- [ ] **Step 2: FAIL** → **Step 3: GREEN**(加一行 enum)→ **Step 4: PASS** + Gate A → **Step 5: Commit**

---

### Task 6 (D2.2): set_enrichment 不命中 → 补查 → INSUFFICIENT + checklist — `[verifier-modify-warning]`

**Files:**
- Modify: `verifier/layers/set_enrichment.py`
- Create: `verifier/helpers/evidence_checklist.py`(missing-evidence checklist builder,加新代码 ✅)
- Test: `tests/test_set_enrichment_insufficient.py`(新)

**Interfaces:**
- Consumes: T5 `ClaimVerdict.INSUFFICIENT_EVIDENCE`
- Produces: 多源池不命中 → 调 `query_pathway_members`(若可用)补查 → 仍无 → `INSUFFICIENT_EVIDENCE`,`feedback_hint` 含 checklist("判定此 claim 缺:pathway_id 对应 member list / 该通路在任一 paradigm 的 top_pathways")
- Produces: `build_missing_evidence_checklist(claim, pool) -> str`

**建议模型:** sonnet 4.6(逻辑 + 区分 UV/INSUFFICIENT)

- [ ] **Step 1: RED**

```python
# tests/test_set_enrichment_insufficient.py
def test_absent_pathway_with_metabolites_is_insufficient():
    # 池非空但不含该通路, claim 有 pathway_name → INSUFFICIENT_EVIDENCE(非 UV)
    src = _src(ramp_enrichment_result={"top_pathways": [{"pathway_id": "KEGG:hsa00010", "pathway_name": "Glycolysis"}]})
    r = verify_set_enrichment(_claim("Tyrosine metabolism"), src)
    assert r.verdict == ClaimVerdict.INSUFFICIENT_EVIDENCE
    assert "缺" in (r.feedback_hint or "") or "missing" in (r.feedback_hint or "").lower()
```

(`_src`/`_claim` 同 T4)

- [ ] **Step 2: FAIL** → **Step 3: GREEN** → **Step 4: PASS** + Gate A + 现有测试不退 → **Step 5: Commit**(`[verifier-modify-warning]` + 数字)

---

### Task 7 (D2.3): 下游识别 INSUFFICIENT_EVIDENCE — `[concord-modify-warning]`

**Files:**
- Modify: `concord/agent/react_runner.py`(verdict filter / UV 计数 / feedback builder 识别新 enum)
- Test: `tests/concord/test_insufficient_downstream.py`(新)

**Interfaces:**
- Consumes: T5 enum
- Produces: react_runner 把 INSUFFICIENT_EVIDENCE 计入独立桶(不混入 supported,也不混入 UV);final_verdict 加 `n_insufficient_evidence` 字段

**建议模型:** sonnet 4.6(下游多处同步)

- [ ] **Step 1-5:** RED(final_verdict 含 n_insufficient_evidence)→ GREEN → Gate A → Commit

---

### Task 8 (D3): CONTRADICTED 注入 top-1 alternative — `[verifier-modify-warning]`

**Files:**
- Modify: `verifier/layers/set_enrichment.py`
- Test: `tests/test_set_enrichment_top1_alt.py`(新)

**Interfaces:**
- Produces: CONTRADICTED 时 `correction` + `feedback_hint` 含多源池 top-1 pathway(GeneAgent 借鉴:不只说"错了",给"应该是 X")

**建议模型:** haiku 4.5(小增强)

- [ ] **Step 1: RED**

```python
def test_contradicted_carries_top1_alternative():
    src = _src(ramp_enrichment_result={"top_pathways": [{"pathway_id": "KEGG:hsa00010", "pathway_name": "Glycolysis", "fdr": 1e-9}]})
    # claim 断言 rank/score 与池矛盾(具体构造见实现) → CONTRADICTED + correction == "Glycolysis"
    ...
```

- [ ] **Step 2-5:** FAIL → GREEN → Gate A → Commit(`[verifier-modify-warning]`)

---

### Task 9 (D4): driver_metabolite v4 降级 — `[verifier-modify-warning]`

**Files:**
- Modify: `verifier/layers/driver_metabolite.py`
- Test: `tests/test_driver_v4_degrade.py`(新)

**Interfaces:**
- Produces: 当 `ground_truth_signal_compounds == [] and ground_truth_noise_compounds == []` → driver claim 返回 `INSUFFICIENT_EVIDENCE` + evidence 注明"v4 无预填 ground truth compounds(设计取舍)",不再静默 UV

**建议模型:** sonnet 4.6(改现有 layer 需谨慎)

- [ ] **Step 1-5:** RED(空 ground truth → INSUFFICIENT)→ GREEN → Gate A + 现有 driver 测试不退 → Commit(`[verifier-modify-warning]` + 数字)

---

### Task 10 (D5): v4 全量重跑 + UV 对比 + 假阳 sanity check

**Files:**
- Create: `scripts/metagent/v4_verifier_rerun.py`(可复用 `scripts/metagent/v4_bench_eval.py` 框架)
- Output: `reports/reports_v3/2026-06-25_v4_verifier_multisource.md`(reports/ gitignored)

**Interfaces:**
- Consumes: T1-T9 全部
- Produces: 112-task v4 跑,产出 UV / supported / insufficient / contradicted 计数 + **假阳 sanity**:SUPPORTED claim 中命中 ground truth `perturbed_pathway` 比例 vs 命中其它(噪音)比例

**建议模型:** sonnet 4.6(脚本 + 分析)。**注意:这步有真实 LLM cost,跑前确认 baseline 跑通 ≤3 task smoke。**

- [ ] **Step 1:** 先 3-task smoke(`--limit 3`)确认 verifier 不再 adapter 崩
- [ ] **Step 2:** 全 112 task 跑,cost 查 `logs/llm_calls.jsonl`
- [ ] **Step 3:** 出 UV 对比表(重构前全 UV → 重构后真实数)+ 假阳 sanity
- [ ] **Step 4:** Gate A 408/0 + Gate B 不退步
- [ ] **Step 5:** Commit 报告 + 更新 `docs/decisions/2026-06-25_verifier_multisource_refactor.md` §6 实测数

---

## Self-Review

- **Spec 覆盖:** 三层断裂 → T1(断裂2 RaMP carrier)/T2(断裂1 adapter)/T3-T4(断裂3 多源池);OriGene 借鉴 → T6(checklist)/T5(INSUFFICIENT);GeneAgent 借鉴 → T8(top-1 alt);driver limitation → T9;真实 UV → T10。✅ 全覆盖。
- **Placeholder:** T8 测试构造细节标"见实现"——CONTRADICTED 的 rank/score 矛盾构造依赖 method_aware 现有逻辑,实现时参照 `method_aware_enrichment._rank_matches`。其余无 placeholder。
- **类型一致:** `build_pathway_pool`/`match_in_pool`(T3)→ T4/T6 消费;`INSUFFICIENT_EVIDENCE`(T5)→ T6/T7/T9 消费;`v4_task_to_subsix_source_report`(T2)签名一致。✅

## Execution Order

T1 → T2(D0 修复,可并行但 T2 依赖 T1 的 carrier)→ T3 → T4(D1)→ T5 → T6 → T7(D2)→ T8(D3)→ T9(D4)→ T10(D5)。
T5 可与 T3/T4 并行(独立 enum)。其余串行(后依赖前)。
