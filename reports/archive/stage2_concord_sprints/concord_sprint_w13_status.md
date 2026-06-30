# W13 — extended ID pattern + subject normalization (A) + iter-2 diagnostic (C)

**Worktree:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2`
**Branch:** `metagent-v2` @ `edb8fe4` (W12 close-out)
**Mode:** 6-7 工作日,A + C 并行,有人值守
**Budget:** ~6d wall + ~$12-15 API
**Started:** 2026-05-25

---

## 0 · Onboarding (per W13 spec §0)

### Tier 1 — W12 close-out + ceiling 教训

**Source:** `reports/agent/concord_sprint_w12_status.md` (W12 final status, commit edb8fe4)
**Note:** W13 spec §0 line 35 references `reports/agent/concord_w12_c7_close_out.md` —
actual filename in repo is `concord_sprint_w12_status.md` (same content, named per
W12 spec template).

**Gap 4 项归因 takeaway**(W12 D5 实测 −1.50 pp vs recalibrated ceiling −11.16 pp,
gap 9.66 pp):
1. LLM narrative shift — richer feedback prompt (W10 D2.5 fix) drove behaviour
   change in W12 D5; W11 strict_id surface forms did not all recur
2. Subject lookup miss — many W12 claims have `subject=None` or name variant
   ("17β-estradiol" vs "17beta-estradiol") which fail exact-match
3. ID pattern miss — `_ID_PATTERNS` regex catches "KEGG ID C00082" but misses
   "KEGG:C00082" without keyword, PubChem CID, ChEBI IRI form, etc.
4. Side effect — unsupported +3.66 pp + iter-2 deg +4.48 pp; richer feedback
   shifts verdicts downward into unsupported, not purely upward into supported

**W11 C7 真实拆分(W12 D ceiling re-classification,commit edb8fe4):**
- strict_id      123 / 226 (54.4 %)  ← factual_sub6 amenable
- fuzzy_biology  103 / 226 (45.6 %)  ← needs richer verifier (W15+)
- ceiling        123 / 1102 = 11.16 pp

**Note:** W13 spec §0 references `data/concord/w12_d5_5_c7_refine/c7_subclassification.csv` —
actual path in repo is `data/concord/w12_uv_ceiling/c7_strict_vs_fuzzy.jsonl`
(different filename/format but identical 123 / 103 partition).

**factual_sub6 W12 转化 ledger:**
- 657 FACTUAL/GROUNDED claim routed to factual_sub6 in W12 D5 run
- 70 SUPPORTED → 10.7 % conversion rate
- 587 UV → 89.3 % unconverted (subject miss + ID pattern miss + LLM shift)
- 53 of W11's 123 strict_id 未 cover (123 - 70 = 53) — W13.A target

### Tier 2 — W10 D4.5 iter-2 dynamics context

**Source:** D4.5 commits `d18139d` (diagnostic) + `6ecae00` (H1 verdict).
**Note:** W13 spec §0 line 46 references `reports/agent/concord_w10_d4_5_iter2_degradation_analysis.md` —
actual location is `data/concord/w10_d4_5_degradation_diagnostic/summary.md`
(file resides in `data/concord/` not `reports/agent/` per W10 D4.5 commit `6ecae00`).

**iter-2 degradation trajectory:**
- W10 D4 baseline: 7 / 62 = 11.3 % (pre D2.5 feedback fix)
- W10 D4 post: 11 / 62 = 17.7 % (D2.5 confirmed: richer feedback → LLM overshoot)
- W12 D5: 22.2 % (+4.48 pp vs W10 D4 17.7 %)

H3 hypothesis (richer feedback → iter-2 overshoot): CONFIRMED at W10 D4.5
on 11-task slice (`11/11 c+u gain iter1→iter2`). W12 D5 22.2 % suggests
either H3 amplification or a new W12 D4 dispatcher-case side effect.
W13.C task is to distinguish on the W12 D5 N=63 superset.

### Tier 3 — Current factual_sub6 _ID_PATTERNS surface

```python
# verifier/layers/factual_sub6.py:59
_ID_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("inchikey",       r"\b(?:InChIKey|InChi[Kk]ey|inchikey)\s*[:=]?\s*"
                       r"([A-Z]{14}(?:-[A-Z]{10}-[A-Z])?)\b"),
    ("chebi_id",       r"\b(?:CHEBI|ChEBI)(?:\s+ID)?\s*[:=]?\s*"
                       r"(CHEBI:?\d+|\d+)\b"  IGNORECASE),
    ("hmdb_id",        r"\b(?:HMDB(?:\s+ID)?)\s*[:=]?\s*(HMDB\d+)\b"  IGNORECASE),
    ("kegg_id",        r"\b(?:KEGG(?:\s+ID)?|KEGG\s+compound)\s*[:=]?\s*"
                       r"(C\d{5})\b"  IGNORECASE),
    ("inchikey_short", r"(?<![A-Za-z0-9])([A-Z]{14})(?![A-Za-z0-9])"),
)
```

**Subject lookup current:** `_find_by_subject` does case-insensitive exact-name match
on `differential_metabolites` then `curated_hmdb_mammalian.jsonl`. No Unicode /
whitespace / Greek-letter normalisation.

### Confirmation

- **(a)** A 主线扩 `_ID_PATTERNS` (append new entries) + 新 `verifier/helpers/subject_normalizer.py` (pure-add) + small `_find_by_subject` lookup fallback (⚠ modify factual_sub6.py — W12 D3 territory not B1-core, falls under modify-policy)
- **(b)** C 副线 W12 D5 数据诊断 — pull `iter2_degraded` tasks from `data/concord/w12_path_x_post_c7/path_x_full63_results.jsonl`, per-iter quality decomposition; **0 production change**
- **(c)** Target 校准 per W13 spec §1:**UV 降 ≥ 3 pp**(基于 53 条 strict 未 cover 的 ~4.8 pp 实际 ceiling × 0.6-0.8)+ pathway acc 不掉 > 3 pp + iter-2 deg ≤ W12 D5 22.2 %
- **(d)** A + C 并行执行;W13 末汇总
- **(e)** C8/C9 noise (W13.B candidate) → W14;fuzzy_biology (W13.D candidate) → W15+;不在本 sprint scope

### W12 教训:UV sprint 启动前重分类 — 已完成

- W11 → W12 D 重分类: 123 strict_id / 103 fuzzy_biology(`data/concord/w12_uv_ceiling/c7_strict_vs_fuzzy.jsonl`)
- W13 inherits this partition;target = W12 未 cover 的 53 strict_id 中 W13 能新 cover 的 fraction
- 校准后期望 UV 降 ≥ 3 pp(spec §0 line 68)

---

## 1 · W13 task plan(D1-D7,A + C 并行)

| Day | A 主线 | C 副线 |
|---|---|---|
| **D1** | Onboarding (this doc) + RED commit:12 case extended ID patterns + subject normalizer test | — |
| **D2** | GREEN main:append 8 `_ID_PATTERNS` regex + `verifier/helpers/subject_normalizer.py` + `_find_by_subject` fallback (⚠ modify factual_sub6) | — |
| **D3** | — | C 启动:pull W12 D5 iter2_degraded tasks, per-iter quality decomposition |
| **D4** | A Path X 全 63 task 重跑 (~2h + $11) | C 报告草稿:H1/H3 在 W12 N=63 上是否仍 confirm |
| **D5** | A Hard Gate verify + UV 数字 ledger | C 报告 final + W14 候选 ranked |
| **D6** | W13 close-out report (A 数字 + C verdict + W14 启动条件) | — |
| **D7** | Buffer | — |

Commits ~5-7: A 路径 (RED + GREEN + Path X data + close-out) + C 路径 (analysis + report).

---

## 2 · Hard Gates(W13 sprint 通过判定)

| Gate | Target | Rationale |
|---|---|---|
| 1 — A UV 降幅 | ≥ 3 pp(W12 D5 51.45 % → ≤ 48.45 %) | 53 strict 未 cover × 0.6-0.8 转化 = ~3-4 pp realistic |
| 2 — Pathway accuracy | drop ≤ 3 pp (86 % → ≥ 83 %) | regression guard |
| 3 — iter-2 deg | ≤ W12 D5 22.22 % | A 不该升 iter-2 (no feedback semantic change) |
| 4 — B1 verifier-core | 407 pass / 0 fail | no regression |
| 5 — Full repo | 1345 pass / 14 fail | no NEW fail |

---

## 3 · Stop conditions (per W13 spec §9)

1. Onboarding §0 confirmation 缺失就动代码
2. RED 12 case 中 regression case pre-impl 不通过
3. GREEN 12 case 不全转 PASS
4. B1 verifier-core 407/0 退步
5. 全 repo 1345/14 退步
6. W12 14-case suite 退步 (A normalizer 不该影响 W12 老 test)
7. Path X wall > 4h / cost > $13
8. UV 降幅 < 3 pp / pathway 准确率掉 > 3 pp / iter-2 deg 比 W12 D5 高
9. commit body 缺 `[verifier-modify-warning]` when modify factual_sub6 lookup
10. 修改了 W12 `_ID_PATTERNS` 已有条目 (scope violation, append only)
11. W13.C 诊断数据与 W12 D5 close-out 数字不一致

---

## 4 · 不做(per W13 spec §10)

- ❌ 不动 fuzzy_biology 103 条 (W15+ scope)
- ❌ 不做 C8/C9 noise (W14 candidate)
- ❌ 不动 quality_score function (wait W13.C verdict)
- ❌ 不动 max_feedback_iters=2 (wait W13.C verdict)
- ❌ 不动 system prompt (W8 D1 锁定)
- ❌ 不暴露 V3 算法 tool
- ❌ 不写 paper writeup
- ❌ 不 push origin
- ❌ 不动 B1 D5/D6 评测数据 (护栏 2)
- ❌ 不 `git tag -f` `metagent-v2-base-b1` (护栏 1)
- ❌ 不修改 W12 已 commit 的 `_ID_PATTERNS` 已有条目 (scope violation)
