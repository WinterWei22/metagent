# Part 1 — Benchmark Recall@k + Driver P/R Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-ground-truth pathway hit metric with (1A) `recall@k / hit@k / MRR` against a deterministically-built *relevant pathway set*, and add (1B) driver-metabolite `precision/recall` against a deterministically-built *gold driver set*.

**Architecture:** Two offline build scripts read the heavy reference DBs once and emit small committed sidecar JSON annotations keyed by `task_id`. Pure metric functions live in `concord/agent/pathway_prediction.py`. The scorecard script loads the sidecars and computes the new columns. Eval-time never touches the 1.9 GB `ramp.sqlite` — only the sidecars.

**Tech Stack:** Python 3.11, sqlite3 (stdlib), pytest. No new third-party deps.

## Global Constraints

- 对话用中文，代码/标识符用英文。
- 严格 TDD：每个 piece 先写失败测试 → 跑红 → 最小实现 → 跑绿 → commit。
- 不碰 B1 冻结资产：`metagent-v2-base-b1` tag、`data/eval/sub6/b1_d5_*`、`data/eval/sub6/a3_rerun_*` immutable；不改 `verifier/` 核心 helper。本计划只新增 `concord/agent/` 模块 + `scripts/metagent/` 脚本 + 改 `scripts/metagent/full344_pathway_scorecard.py`，**不动 verifier/**。
- 保留旧 exact/semantic 指标列做对照，**只新增不删除**。
- Driver P/R 仅对 `sub6` + `hmdb_ramp` 两层计算；`human1` + `recon2_2` 显式标 `null`（N/A）。
- Relevant-set 对**全部四层**计算（RaMP 两层走 `ramp.sqlite`，human1/recon2 走 `pathway_members.sqlite`）。
- 相关集合定义（决策①已锁）：GT 通路 + RaMP `pathway_duplicates` + member-overlap Jaccard ≥ θ 邻居（θ 默认 0.3，CLI 可调）。
- 提交信息英文，结尾不加 Co-Authored-By（沿用本仓历史风格，无此约定则省略）。

---

## Data Facts (verified 2026-06-22)

- `ramp.sqlite` 路径：`/data/weiwentao/llm_agent_metabolomics/ramp.sqlite`（gitignored，1.9 GB，构建期只读，不进 eval 路径）。
  - `analytehaspathway(rampId, pathwayRampId, pathwaySource)` — 成员关系。
  - `pathway(pathwayRampId, sourceId, type, pathwayCategory, pathwayName)`。
  - `pathway_duplicates(pathwayRampId1, pathwayRampId2)` — 跨源等价。
  - `source(sourceId, rampId, IDtype, geneOrCompound, ...)`；KEGG 化合物 `sourceId='kegg:C00048'`, `geneOrCompound='compound'`。
- `data/concord/pathway_members.sqlite` → `pathway_member(pathway_namespace, pathway_label_slug, pathway_name, member_chebi_id, member_mam_id, source)`；`source ∈ {human1, recon2}`。
- 基准 `data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl`（344 行）。每行 `ground_truth.perturbed_pathway = {id, name, ontology}`，`ontology ∈ {RaMP:wikipathways, RaMP:kegg, Human1, Recon2.2}`；`input.differential_metabolites=[{id,id_type,name}]`（sub6/hmdb_ramp 的 id_type=KEGG）。
- 层判定（task_id 前缀）：含 `human1`→human1；含 `recon2_2`→recon2；含 `hmdb_ramp`→hmdb_ramp；前缀 `sub6`→sub6。
- 复用 `concord/agent/pathway_prediction.py::norm_name(value)` 做名称归一。
- 现有评分脚本：`scripts/metagent/full344_pathway_scorecard.py`，dump 在 `data/metagent/full344_fullpipeline_eval/path_x_full/<task_id>.json`，预测形态见 `tests/test_full344_pathway_scorecard.py::_prediction`（`{"primary":{"pathway_id","pathway_name","supporting_claim_indices"},"alternatives":[...],"abstain":bool}`）。

---

## File Structure

- Create `concord/agent/pathway_relevant_set.py` — 相关集合构建（RaMP + model-org），纯函数 + sqlite 读。
- Create `concord/agent/driver_gold.py` — 驱动金标准构建 + 预测驱动 id 解析（RaMP 两层）。
- Modify `concord/agent/pathway_prediction.py` — 追加 `pathway_recall_metrics()` + `driver_pr_metrics()` 纯指标函数。
- Create `scripts/metagent/build_relevant_pathway_sets.py` — 离线写 `data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json`。
- Create `scripts/metagent/build_gold_drivers.py` — 离线写 `data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json`。
- Modify `scripts/metagent/full344_pathway_scorecard.py` — 加载 sidecar、计算并聚合新列。
- Create tests: `tests/test_pathway_relevant_set.py`, `tests/test_driver_gold.py`, `tests/test_pathway_recall_driver_metrics.py`; extend `tests/test_full344_pathway_scorecard.py`.

---

### Task 1: Relevant-set core (RaMP) — Jaccard + duplicates

**Files:**
- Create: `concord/agent/pathway_relevant_set.py`
- Test: `tests/test_pathway_relevant_set.py`

**Interfaces:**
- Produces: `jaccard(a: set, b: set) -> float`; `build_relevant_set_ramp(conn, gt_pathway_ramp_id: str, *, jaccard_threshold: float = 0.3) -> set[str]` (returns normalized pathway names; always includes the GT pathway's own normalized name).
- Consumes: `concord.agent.pathway_prediction.norm_name`.

- [ ] **Step 1: Write the failing test** (uses an in-memory sqlite fixture mimicking the real schema)

```python
# tests/test_pathway_relevant_set.py
from __future__ import annotations

import sqlite3

import pytest

from concord.agent import pathway_relevant_set as prs


def _ramp_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE pathway(pathwayRampId TEXT, sourceId TEXT, type TEXT,
                             pathwayCategory TEXT, pathwayName TEXT);
        CREATE TABLE analytehaspathway(rampId TEXT, pathwayRampId TEXT, pathwaySource TEXT);
        CREATE TABLE pathway_duplicates(pathwayRampId1 TEXT, pathwayRampId2 TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO pathway VALUES (?,?,?,?,?)",
        [
            ("P_GT", "map1", "kegg", "c", "Alanine metabolism"),
            ("P_DUP", "wp1", "wiki", "c", "Alanine Metabolism"),   # duplicate name/source
            ("P_NEAR", "map2", "kegg", "c", "Aspartate metabolism"),  # high overlap
            ("P_FAR", "map3", "kegg", "c", "Steroid biosynthesis"),   # no overlap
            ("P_HUGE", "map4", "kegg", "c", "Metabolism"),            # shares some, low jaccard
        ],
    )
    members = []
    for r in ["a", "b", "c", "d"]:
        members.append((r, "P_GT", "kegg"))
    for r in ["a", "b", "c", "e"]:   # 3/5 overlap with GT -> jaccard 3/5=0.6
        members.append((r, "P_NEAR", "kegg"))
    members.append(("z", "P_FAR", "kegg"))
    for r in ["a", "m1", "m2", "m3", "m4", "m5", "m6"]:  # shares 1, union large -> low jaccard
        members.append((r, "P_HUGE", "kegg"))
    conn.executemany("INSERT INTO analytehaspathway VALUES (?,?,?)", members)
    conn.execute("INSERT INTO pathway_duplicates VALUES ('P_GT','P_DUP')")
    conn.commit()
    return conn


def test_jaccard():
    assert prs.jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert prs.jaccard({"a"}, set()) == 0.0
    assert prs.jaccard({"a", "b", "c"}, {"a"}) == pytest.approx(1 / 3)


def test_relevant_set_includes_gt_dup_and_near_excludes_far_and_huge():
    conn = _ramp_conn()
    rel = prs.build_relevant_set_ramp(conn, "P_GT", jaccard_threshold=0.3)
    assert "alanine metabolism" in rel        # GT itself (normalized)
    assert "aspartate metabolism" in rel       # near neighbor (jaccard 0.6)
    assert "steroid biosynthesis" not in rel   # disjoint
    assert "metabolism" not in rel             # giant pathway, low jaccard
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_pathway_relevant_set.py -q`
Expected: FAIL with `ModuleNotFoundError: concord.agent.pathway_relevant_set`.

- [ ] **Step 3: Write minimal implementation**

```python
# concord/agent/pathway_relevant_set.py
"""Deterministic relevant-pathway-set construction for recall@k metrics.

Decision① (locked 2026-06-22): relevant set = GT pathway
+ RaMP pathway_duplicates + member-overlap (Jaccard >= threshold) neighbors.
Returned as a set of normalized pathway names (via norm_name).
"""

from __future__ import annotations

import sqlite3

from concord.agent.pathway_prediction import norm_name


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _members_ramp(conn: sqlite3.Connection, pathway_ramp_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT rampId FROM analytehaspathway WHERE pathwayRampId=?",
        (pathway_ramp_id,),
    )
    return {r[0] for r in rows}


def _name_ramp(conn: sqlite3.Connection, pathway_ramp_id: str) -> str | None:
    row = conn.execute(
        "SELECT pathwayName FROM pathway WHERE pathwayRampId=?",
        (pathway_ramp_id,),
    ).fetchone()
    return row[0] if row else None


def build_relevant_set_ramp(
    conn: sqlite3.Connection,
    gt_pathway_ramp_id: str,
    *,
    jaccard_threshold: float = 0.3,
) -> set[str]:
    relevant: set[str] = set()
    gt_name = _name_ramp(conn, gt_pathway_ramp_id)
    if gt_name:
        relevant.add(norm_name(gt_name))
    gt_members = _members_ramp(conn, gt_pathway_ramp_id)
    if not gt_members:
        return relevant

    # duplicates (cross-source equivalents)
    for col_self, col_other in (
        ("pathwayRampId1", "pathwayRampId2"),
        ("pathwayRampId2", "pathwayRampId1"),
    ):
        for (other_id,) in conn.execute(
            f"SELECT {col_other} FROM pathway_duplicates WHERE {col_self}=?",
            (gt_pathway_ramp_id,),
        ):
            nm = _name_ramp(conn, other_id)
            if nm:
                relevant.add(norm_name(nm))

    # member-overlap neighbors: only pathways sharing >=1 member with GT
    placeholders = ",".join("?" * len(gt_members))
    candidate_ids = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT pathwayRampId FROM analytehaspathway "
            f"WHERE rampId IN ({placeholders})",
            tuple(gt_members),
        )
    }
    for cand in candidate_ids:
        if cand == gt_pathway_ramp_id:
            continue
        if jaccard(gt_members, _members_ramp(conn, cand)) >= jaccard_threshold:
            nm = _name_ramp(conn, cand)
            if nm:
                relevant.add(norm_name(nm))
    return relevant
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_pathway_relevant_set.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add concord/agent/pathway_relevant_set.py tests/test_pathway_relevant_set.py
git commit -m "feat(bench): RaMP relevant-pathway-set builder (jaccard + duplicates)"
```

---

### Task 2: Relevant-set core (model-org: human1 / recon2)

**Files:**
- Modify: `concord/agent/pathway_relevant_set.py`
- Test: `tests/test_pathway_relevant_set.py`

**Interfaces:**
- Produces: `build_relevant_set_modelorg(conn, gt_pathway_name: str, source: str, *, jaccard_threshold: float = 0.3) -> set[str]` — matches GT by normalized `pathway_name` within `pathway_member` rows of the given `source` (`human1`/`recon2`), builds member sets from `member_mam_id`/`member_chebi_id`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_pathway_relevant_set.py
def _members_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE pathway_member(pathway_namespace TEXT, pathway_label_slug TEXT, "
        "pathway_name TEXT, member_chebi_id TEXT, member_mam_id TEXT, source TEXT)"
    )
    rows = []
    for m in ["c1", "c2", "c3", "c4"]:
        rows.append(("HUMAN1", "gt", "Acyl-CoA hydrolysis", m, m + "c", "human1"))
    for m in ["c1", "c2", "c3", "x"]:  # jaccard 3/5 = 0.6
        rows.append(("HUMAN1", "near", "Fatty acyl oxidation", m, m + "c", "human1"))
    rows.append(("HUMAN1", "far", "Glycolysis", "z", "zc", "human1"))
    rows.append(("RECON2", "other", "Acyl-CoA hydrolysis", "c1", "c1c", "recon2"))  # wrong source
    conn.executemany("INSERT INTO pathway_member VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return conn


def test_relevant_set_modelorg_matches_name_within_source():
    conn = _members_conn()
    rel = prs.build_relevant_set_modelorg(
        conn, "Acyl-CoA hydrolysis", "human1", jaccard_threshold=0.3
    )
    assert "acyl-coa hydrolysis" in rel
    assert "fatty acyl oxidation" in rel
    assert "glycolysis" not in rel
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_pathway_relevant_set.py::test_relevant_set_modelorg_matches_name_within_source -q`
Expected: FAIL with `AttributeError: build_relevant_set_modelorg`.

- [ ] **Step 3: Write minimal implementation** (append to module)

```python
def _member_key(chebi_id: str | None, mam_id: str | None) -> str | None:
    return (chebi_id or mam_id) or None


def _members_by_name(
    conn: sqlite3.Connection, pathway_name_norm: str, source: str
) -> dict[str, set[str]]:
    """Return {normalized_pathway_name: member-key set} for one source."""
    grouped: dict[str, set[str]] = {}
    for nm, chebi, mam in conn.execute(
        "SELECT pathway_name, member_chebi_id, member_mam_id "
        "FROM pathway_member WHERE source=?",
        (source,),
    ):
        key = _member_key(chebi, mam)
        if key is None:
            continue
        grouped.setdefault(norm_name(nm), set()).add(key)
    return grouped


def build_relevant_set_modelorg(
    conn: sqlite3.Connection,
    gt_pathway_name: str,
    source: str,
    *,
    jaccard_threshold: float = 0.3,
) -> set[str]:
    gt_norm = norm_name(gt_pathway_name)
    relevant: set[str] = {gt_norm}
    grouped = _members_by_name(conn, gt_norm, source)
    gt_members = grouped.get(gt_norm, set())
    if not gt_members:
        return relevant
    for name_norm, members in grouped.items():
        if name_norm == gt_norm:
            continue
        if jaccard(gt_members, members) >= jaccard_threshold:
            relevant.add(name_norm)
    return relevant
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_pathway_relevant_set.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add concord/agent/pathway_relevant_set.py tests/test_pathway_relevant_set.py
git commit -m "feat(bench): model-org (human1/recon2) relevant-set builder"
```

---

### Task 3: Recall@k / hit@k / MRR metric function

**Files:**
- Modify: `concord/agent/pathway_prediction.py` (append at end of file)
- Test: `tests/test_pathway_recall_driver_metrics.py`

**Interfaces:**
- Produces: `pathway_recall_metrics(predicted_names: list[str], relevant_names: set[str], *, k: int = 3) -> dict[str, float|bool|int]` with keys `recall_at_k`, `hit_at_k`, `mrr`, `n_relevant`, `n_predicted_considered`. Names compared after `norm_name`. `predicted_names` is the ordered list (primary first, then alternatives). Empty `relevant_names` → all-zero metrics (caller decides abstain handling).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pathway_recall_driver_metrics.py
from __future__ import annotations

import pytest

from concord.agent.pathway_prediction import pathway_recall_metrics


def test_recall_hit_mrr_basic():
    pred = ["Tyrosine metabolism", "Glutathione metabolism", "Aspirin"]
    rel = {"tyrosine metabolism", "catecholamine biosynthesis"}
    m = pathway_recall_metrics(pred, rel, k=3)
    assert m["hit_at_k"] is True
    assert m["recall_at_k"] == pytest.approx(0.5)   # 1 of 2 relevant retrieved
    assert m["mrr"] == pytest.approx(1.0)            # relevant at rank 1
    assert m["n_relevant"] == 2


def test_recall_rank2_mrr_half_and_k_truncates():
    pred = ["Wrong", "Right pathway", "Right pathway too"]
    rel = {"right pathway", "right pathway too"}
    assert pathway_recall_metrics(pred, rel, k=1)["hit_at_k"] is False
    m2 = pathway_recall_metrics(pred, rel, k=3)
    assert m2["mrr"] == pytest.approx(0.5)
    assert m2["recall_at_k"] == pytest.approx(1.0)


def test_recall_empty_relevant_is_zero():
    m = pathway_recall_metrics(["X"], set(), k=3)
    assert m["hit_at_k"] is False
    assert m["recall_at_k"] == 0.0
    assert m["mrr"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_pathway_recall_driver_metrics.py -q`
Expected: FAIL with `ImportError: cannot import name 'pathway_recall_metrics'`.

- [ ] **Step 3: Write minimal implementation** (append to `concord/agent/pathway_prediction.py`)

```python
def pathway_recall_metrics(
    predicted_names: list[str],
    relevant_names: set[str],
    *,
    k: int = 3,
) -> dict[str, Any]:
    """recall@k / hit@k / MRR of ordered predicted pathway names against a
    relevant-name set. All comparisons are on norm_name."""
    rel = {norm_name(n) for n in relevant_names if n}
    topk = [norm_name(n) for n in predicted_names[:k] if n]
    retrieved = {n for n in topk if n in rel}
    recall_at_k = (len(retrieved) / len(rel)) if rel else 0.0
    hit_at_k = bool(retrieved)
    mrr = 0.0
    for idx, name in enumerate(topk, start=1):
        if name in rel:
            mrr = 1.0 / idx
            break
    return {
        "recall_at_k": recall_at_k,
        "hit_at_k": hit_at_k,
        "mrr": mrr,
        "n_relevant": len(rel),
        "n_predicted_considered": len(topk),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_pathway_recall_driver_metrics.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add concord/agent/pathway_prediction.py tests/test_pathway_recall_driver_metrics.py
git commit -m "feat(bench): recall@k / hit@k / MRR pathway metric"
```

---

### Task 4: Gold-driver builder + driver-id resolver (RaMP)

**Files:**
- Create: `concord/agent/driver_gold.py`
- Test: `tests/test_driver_gold.py`

**Interfaces:**
- Produces:
  - `resolve_to_ramp_id(conn, compound_id: str) -> str | None` — accepts `KEGG:Cxxxxx`, `Cxxxxx`, `CHEBI:nnnn`, `chebi:nnnn`; maps to `RAMP_C_*` via `source` table.
  - `build_gold_drivers_ramp(conn, input_metabolite_ids: list[str], gt_pathway_ramp_id: str) -> set[str]` — returns the subset of input compounds (as RAMP_C ids) that are members of the GT pathway.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_driver_gold.py
from __future__ import annotations

import sqlite3

from concord.agent import driver_gold as dg


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE source(sourceId TEXT, rampId TEXT, IDtype TEXT,
                            geneOrCompound TEXT, commonName TEXT,
                            priorityHMDBStatus TEXT, dataSource TEXT, pathwayCount INT);
        CREATE TABLE analytehaspathway(rampId TEXT, pathwayRampId TEXT, pathwaySource TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO source(sourceId,rampId,IDtype,geneOrCompound) VALUES (?,?,?,?)",
        [
            ("kegg:C00048", "RAMP_C_1", "kegg", "compound"),
            ("kegg:C00051", "RAMP_C_2", "kegg", "compound"),
            ("kegg:C99999", "RAMP_C_3", "kegg", "compound"),  # not a GT member
            ("chebi:16828", "RAMP_C_1", "chebi", "compound"),  # alt xref of same compound
        ],
    )
    conn.executemany(
        "INSERT INTO analytehaspathway VALUES (?,?,?)",
        [("RAMP_C_1", "P_GT", "kegg"), ("RAMP_C_2", "P_GT", "kegg")],
    )
    conn.commit()
    return conn


def test_resolve_handles_prefixes():
    conn = _conn()
    assert dg.resolve_to_ramp_id(conn, "C00048") == "RAMP_C_1"
    assert dg.resolve_to_ramp_id(conn, "KEGG:C00048") == "RAMP_C_1"
    assert dg.resolve_to_ramp_id(conn, "CHEBI:16828") == "RAMP_C_1"
    assert dg.resolve_to_ramp_id(conn, "C00000") is None


def test_gold_drivers_are_input_intersect_pathway_members():
    conn = _conn()
    gold = dg.build_gold_drivers_ramp(conn, ["C00048", "C00051", "C99999"], "P_GT")
    assert gold == {"RAMP_C_1", "RAMP_C_2"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_driver_gold.py -q`
Expected: FAIL with `ModuleNotFoundError: concord.agent.driver_gold`.

- [ ] **Step 3: Write minimal implementation**

```python
# concord/agent/driver_gold.py
"""Deterministic gold-driver construction for driver precision/recall.

Decision② (locked 2026-06-22): gold drivers (sub6 + hmdb_ramp only) =
input metabolites that are members of the ground-truth RaMP pathway.
human1/recon2 have no gold driver subset -> caller emits null (N/A).
Identity key is the RaMP compound id (RAMP_C_*).
"""

from __future__ import annotations

import sqlite3


def _kegg_source_id(compound_id: str) -> str | None:
    s = compound_id.strip()
    low = s.lower()
    if low.startswith("kegg:"):
        s = s.split(":", 1)[1]
    if s and s[0] in {"C", "c"} and s[1:].isdigit():
        return f"kegg:{s.upper()}"
    return None


def _chebi_source_id(compound_id: str) -> str | None:
    low = compound_id.strip().lower()
    if low.startswith("chebi:"):
        num = low.split(":", 1)[1]
        if num.isdigit():
            return f"chebi:{num}"
    return None


def resolve_to_ramp_id(conn: sqlite3.Connection, compound_id: str) -> str | None:
    for source_id in (_kegg_source_id(compound_id), _chebi_source_id(compound_id)):
        if source_id is None:
            continue
        row = conn.execute(
            "SELECT rampId FROM source WHERE sourceId=? AND geneOrCompound='compound' LIMIT 1",
            (source_id,),
        ).fetchone()
        if row:
            return row[0]
    return None


def _pathway_member_ramp_ids(
    conn: sqlite3.Connection, gt_pathway_ramp_id: str
) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT rampId FROM analytehaspathway WHERE pathwayRampId=?",
            (gt_pathway_ramp_id,),
        )
    }


def build_gold_drivers_ramp(
    conn: sqlite3.Connection,
    input_metabolite_ids: list[str],
    gt_pathway_ramp_id: str,
) -> set[str]:
    members = _pathway_member_ramp_ids(conn, gt_pathway_ramp_id)
    gold: set[str] = set()
    for cid in input_metabolite_ids:
        ramp_id = resolve_to_ramp_id(conn, cid)
        if ramp_id is not None and ramp_id in members:
            gold.add(ramp_id)
    return gold
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_driver_gold.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add concord/agent/driver_gold.py tests/test_driver_gold.py
git commit -m "feat(bench): RaMP gold-driver builder + id resolver"
```

---

### Task 5: Driver precision/recall metric function

**Files:**
- Modify: `concord/agent/pathway_prediction.py` (append)
- Test: `tests/test_pathway_recall_driver_metrics.py` (extend)

**Interfaces:**
- Produces: `driver_pr_metrics(predicted_ids: set[str], gold_ids: set[str] | None) -> dict[str, Any] | None` — returns `None` when `gold_ids is None` (N/A strata); else `{precision, recall, n_predicted, n_gold, n_hit}`. Empty predicted with non-empty gold → precision 0.0, recall 0.0. Empty gold (set, not None) → precision 0.0 if any predicted else 1.0, recall 1.0.

- [ ] **Step 1: Write the failing test** (append)

```python
# append to tests/test_pathway_recall_driver_metrics.py
from concord.agent.pathway_prediction import driver_pr_metrics


def test_driver_pr_none_when_gold_na():
    assert driver_pr_metrics({"RAMP_C_1"}, None) is None


def test_driver_pr_basic():
    m = driver_pr_metrics({"RAMP_C_1", "RAMP_C_9"}, {"RAMP_C_1", "RAMP_C_2"})
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(0.5)
    assert m["n_hit"] == 1


def test_driver_pr_empty_predicted():
    m = driver_pr_metrics(set(), {"RAMP_C_1"})
    assert m["precision"] == 0.0
    assert m["recall"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_pathway_recall_driver_metrics.py -q`
Expected: FAIL with `ImportError: cannot import name 'driver_pr_metrics'`.

- [ ] **Step 3: Write minimal implementation** (append to `concord/agent/pathway_prediction.py`)

```python
def driver_pr_metrics(
    predicted_ids: set[str],
    gold_ids: set[str] | None,
) -> dict[str, Any] | None:
    """Driver precision/recall on a shared identity key (RAMP_C ids).
    Returns None for N/A strata (gold_ids is None)."""
    if gold_ids is None:
        return None
    hit = predicted_ids & gold_ids
    precision = (
        (len(hit) / len(predicted_ids))
        if predicted_ids
        else (1.0 if not gold_ids else 0.0)
    )
    recall = (len(hit) / len(gold_ids)) if gold_ids else 1.0
    return {
        "precision": precision,
        "recall": recall,
        "n_predicted": len(predicted_ids),
        "n_gold": len(gold_ids),
        "n_hit": len(hit),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_pathway_recall_driver_metrics.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add concord/agent/pathway_prediction.py tests/test_pathway_recall_driver_metrics.py
git commit -m "feat(bench): driver precision/recall metric"
```

---

### Task 6: Offline build scripts → sidecar annotations

**Files:**
- Create: `scripts/metagent/build_relevant_pathway_sets.py`
- Create: `scripts/metagent/build_gold_drivers.py`
- Test: `tests/test_build_sidecars.py`

**Interfaces:**
- Consumes: `build_relevant_set_ramp`, `build_relevant_set_modelorg`, `build_gold_drivers_ramp`.
- Produces (committed artifacts):
  - `data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json` = `{task_id: {"source": str, "relevant_names": [str], "size": int}}`
  - `data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json` = `{task_id: {"gold_ramp_ids": [str]} | null}`
- Both scripts expose `stratum_of(task_id: str) -> str` and `build_all(...)` for unit testing without the big DB.

- [ ] **Step 1: Write the failing test** (tests the pure dispatch + assembly, not the heavy DB)

```python
# tests/test_build_sidecars.py
from __future__ import annotations

from scripts.metagent import build_relevant_pathway_sets as brs
from scripts.metagent import build_gold_drivers as bgd


def test_stratum_of():
    assert brs.stratum_of("s4_cooke_2025_human1_group1") == "human1"
    assert brs.stratum_of("s4_cooke_2025_recon2_2_subsystem27") == "recon2"
    assert brs.stratum_of("hmdb_ramp_easy_kegg_RAMP_P_1_rep0") == "hmdb_ramp"
    assert brs.stratum_of("sub6_easy_compound_only_enrich_mammalian_RAMP_P_1_seed0") == "sub6"


def test_gold_drivers_na_for_modelorg():
    assert bgd.stratum_of("s4_cooke_2025_human1_group1") == "human1"
    # human1/recon2 must map to null gold
    assert bgd.is_na_stratum("human1") is True
    assert bgd.is_na_stratum("recon2") is True
    assert bgd.is_na_stratum("sub6") is False
    assert bgd.is_na_stratum("hmdb_ramp") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_build_sidecars.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/metagent/build_relevant_pathway_sets.py
#!/usr/bin/env python3
"""Build relevant-pathway-set sidecar for easy_v3 (Decision①)."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from concord.agent.pathway_relevant_set import (
    build_relevant_set_modelorg,
    build_relevant_set_ramp,
)

DEFAULT_BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
DEFAULT_RAMP = Path("/data/weiwentao/llm_agent_metabolomics/ramp.sqlite")
DEFAULT_MEMBERS = ROOT / "data/concord/pathway_members.sqlite"
DEFAULT_OUT = ROOT / "data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json"


def stratum_of(task_id: str) -> str:
    if "human1" in task_id:
        return "human1"
    if "recon2_2" in task_id or "recon2" in task_id:
        return "recon2"
    if "hmdb_ramp" in task_id:
        return "hmdb_ramp"
    if task_id.startswith("sub6"):
        return "sub6"
    return "other"


def build_all(
    benchmark_rows: list[dict],
    ramp_conn: sqlite3.Connection,
    members_conn: sqlite3.Connection,
    *,
    jaccard_threshold: float = 0.3,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in benchmark_rows:
        task_id = row["task_id"]
        gt = row["ground_truth"]["perturbed_pathway"]
        stratum = stratum_of(task_id)
        if stratum in {"sub6", "hmdb_ramp"}:
            names = build_relevant_set_ramp(
                ramp_conn, gt["id"], jaccard_threshold=jaccard_threshold
            )
            source = "ramp"
        elif stratum in {"human1", "recon2"}:
            names = build_relevant_set_modelorg(
                members_conn, gt["name"], stratum, jaccard_threshold=jaccard_threshold
            )
            source = stratum
        else:
            names = set()
            source = "other"
        out[task_id] = {
            "source": source,
            "relevant_names": sorted(names),
            "size": len(names),
        }
    return out


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--ramp", type=Path, default=DEFAULT_RAMP)
    ap.add_argument("--members", type=Path, default=DEFAULT_MEMBERS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--jaccard-threshold", type=float, default=0.3)
    args = ap.parse_args()
    rows = _load_jsonl(args.benchmark)
    ramp_conn = sqlite3.connect(f"file:{args.ramp}?mode=ro", uri=True)
    members_conn = sqlite3.connect(f"file:{args.members}?mode=ro", uri=True)
    out = build_all(rows, ramp_conn, members_conn, jaccard_threshold=args.jaccard_threshold)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(out)} relevant-sets -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```python
# scripts/metagent/build_gold_drivers.py
#!/usr/bin/env python3
"""Build gold-driver sidecar for easy_v3 (Decision②); sub6/hmdb_ramp only."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from concord.agent.driver_gold import build_gold_drivers_ramp

DEFAULT_BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
DEFAULT_RAMP = Path("/data/weiwentao/llm_agent_metabolomics/ramp.sqlite")
DEFAULT_OUT = ROOT / "data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json"

_NA = {"human1", "recon2"}


def stratum_of(task_id: str) -> str:
    if "human1" in task_id:
        return "human1"
    if "recon2_2" in task_id or "recon2" in task_id:
        return "recon2"
    if "hmdb_ramp" in task_id:
        return "hmdb_ramp"
    if task_id.startswith("sub6"):
        return "sub6"
    return "other"


def is_na_stratum(stratum: str) -> bool:
    return stratum in _NA


def build_all(benchmark_rows: list[dict], ramp_conn: sqlite3.Connection) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {}
    for row in benchmark_rows:
        task_id = row["task_id"]
        stratum = stratum_of(task_id)
        if is_na_stratum(stratum) or stratum == "other":
            out[task_id] = None
            continue
        gt = row["ground_truth"]["perturbed_pathway"]
        input_ids = [m["id"] for m in row["input"]["differential_metabolites"]]
        gold = build_gold_drivers_ramp(ramp_conn, input_ids, gt["id"])
        out[task_id] = {"gold_ramp_ids": sorted(gold)}
    return out


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--ramp", type=Path, default=DEFAULT_RAMP)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    rows = _load_jsonl(args.benchmark)
    ramp_conn = sqlite3.connect(f"file:{args.ramp}?mode=ro", uri=True)
    out = build_all(rows, ramp_conn)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n_gold = sum(1 for v in out.values() if v is not None)
    print(f"wrote {len(out)} rows ({n_gold} with gold drivers) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_build_sidecars.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Generate the real sidecars and commit** (needs ramp.sqlite present)

```bash
PYTHONPATH=. python scripts/metagent/build_relevant_pathway_sets.py
PYTHONPATH=. python scripts/metagent/build_gold_drivers.py
# sanity: every task_id covered, gold null only for human1/recon2
PYTHONPATH=. python -c "import json; \
r=json.load(open('data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json')); \
g=json.load(open('data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json')); \
print('relevant', len(r), 'gold', len(g), 'gold_na', sum(v is None for v in g.values()))"
git add scripts/metagent/build_relevant_pathway_sets.py scripts/metagent/build_gold_drivers.py \
        tests/test_build_sidecars.py \
        data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json \
        data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json
git commit -m "feat(bench): offline build scripts + committed relevant-set/gold-driver sidecars"
```

Expected output: `relevant 344 gold 344 gold_na 181` (181 = human1 117 + recon2 64).

---

### Task 7: Wire recall@k + driver P/R into the scorecard

**Files:**
- Modify: `scripts/metagent/full344_pathway_scorecard.py`
- Test: `tests/test_full344_pathway_scorecard.py` (extend)

**Interfaces:**
- Consumes: sidecars from Task 6; `pathway_recall_metrics`, `driver_pr_metrics`, `resolve_to_ramp_id`.
- Produces: per-row keys `recall_at_k`, `hit_at_k`, `mrr`, `driver_precision`, `driver_recall` (latter two `None` for N/A strata); aggregate block `recall_driver` in summary; new columns in the markdown report. **Existing exact/semantic columns unchanged.**

Note on predicted-driver resolution: driver claims live in the dump's structured claims (`claim_type=DRIVER_METABOLITE`, field `compound_id`). The scorecard already reads the per-task dump; extract those `compound_id`s, resolve each via `resolve_to_ramp_id` against ramp.sqlite **at report time only if available**, else fall back to comparing already-RAMP_C ids. To keep eval DB-free, store the resolver result is NOT needed — driver claims' compound_id are KEGG/CHEBI; resolve them with a tiny committed lookup built in Task 6b is overkill. Decision: scorecard resolves predicted driver ids via the **gold sidecar's reverse map is not available**, so resolve at report time using ramp.sqlite when `--ramp` is passed; if absent, driver P/R is reported as `null` with a `driver_resolver_unavailable` note. This keeps the default scorecard runnable without the big DB while enabling full driver metrics when the DB is present.

- [ ] **Step 1: Write the failing test** (extend existing test file)

```python
# append to tests/test_full344_pathway_scorecard.py
def test_recall_and_driver_columns_present(tmp_path: Path) -> None:
    # minimal sidecars
    rel = {"t1": {"source": "ramp", "relevant_names": ["tyrosine metabolism"], "size": 1}}
    gold = {"t1": {"gold_ramp_ids": ["RAMP_C_1"]}}
    rel_path = tmp_path / "rel.json"
    gold_path = tmp_path / "gold.json"
    rel_path.write_text(json.dumps(rel), encoding="utf-8")
    gold_path.write_text(json.dumps(gold), encoding="utf-8")

    prediction = {
        "primary": {"pathway_id": "KEGG:1", "pathway_name": "Tyrosine metabolism",
                    "supporting_claim_indices": [0]},
        "alternatives": [],
        "abstain": False,
    }
    row = scorecard.recall_driver_row(
        task_id="t1",
        prediction=prediction,
        driver_predicted_ramp_ids={"RAMP_C_1"},
        relevant_sidecar=rel,
        gold_sidecar=gold,
        k=3,
    )
    assert row["hit_at_k"] is True
    assert row["recall_at_k"] == 1.0
    assert row["driver_precision"] == 1.0
    assert row["driver_recall"] == 1.0


def test_driver_metrics_none_for_na_stratum() -> None:
    gold = {"t2": None}
    rel = {"t2": {"source": "human1", "relevant_names": ["x"], "size": 1}}
    prediction = {"primary": {"pathway_id": "", "pathway_name": "X",
                              "supporting_claim_indices": []},
                  "alternatives": [], "abstain": False}
    row = scorecard.recall_driver_row(
        task_id="t2", prediction=prediction, driver_predicted_ramp_ids=set(),
        relevant_sidecar=rel, gold_sidecar=gold, k=3,
    )
    assert row["driver_precision"] is None
    assert row["driver_recall"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_full344_pathway_scorecard.py::test_recall_and_driver_columns_present -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'recall_driver_row'`.

- [ ] **Step 3: Write minimal implementation** (add function + call sites in scorecard)

```python
# add near the metric helpers in scripts/metagent/full344_pathway_scorecard.py
from concord.agent.pathway_prediction import (
    pathway_recall_metrics,
    driver_pr_metrics,
)


def _ordered_predicted_names(prediction: dict) -> list[str]:
    entries = []
    primary = prediction.get("primary")
    if isinstance(primary, dict) and primary.get("pathway_name"):
        entries.append(primary["pathway_name"])
    for alt in prediction.get("alternatives") or []:
        if isinstance(alt, dict) and alt.get("pathway_name"):
            entries.append(alt["pathway_name"])
    return entries


def recall_driver_row(
    *,
    task_id: str,
    prediction: dict,
    driver_predicted_ramp_ids: set[str],
    relevant_sidecar: dict,
    gold_sidecar: dict,
    k: int = 3,
) -> dict:
    rel_entry = relevant_sidecar.get(task_id) or {}
    relevant_names = set(rel_entry.get("relevant_names") or [])
    recall = pathway_recall_metrics(
        _ordered_predicted_names(prediction), relevant_names, k=k
    )
    gold_entry = gold_sidecar.get(task_id, None)
    gold_ids = None if gold_entry is None else set(gold_entry.get("gold_ramp_ids") or [])
    driver = driver_pr_metrics(driver_predicted_ramp_ids, gold_ids)
    return {
        "recall_at_k": recall["recall_at_k"],
        "hit_at_k": recall["hit_at_k"],
        "mrr": recall["mrr"],
        "n_relevant": recall["n_relevant"],
        "driver_precision": None if driver is None else driver["precision"],
        "driver_recall": None if driver is None else driver["recall"],
    }
```

Then in the existing `rows_for_full344` / `summarize` flow: load the two sidecars (CLI args `--relevant-sidecar`, `--gold-sidecar` with the Task 6 defaults), and for each task collect `DRIVER_METABOLITE` `compound_id`s from the dump, resolve via `resolve_to_ramp_id(ramp_conn, cid)` when `--ramp` provided (else empty set + note), call `recall_driver_row`, and merge its keys into the row. In `summarize`, average `recall_at_k`, `mrr`, `hit_at_k` per stratum, and average `driver_precision`/`driver_recall` over non-null rows only. Add a `recall_driver` block to the markdown writer with one row per stratum + overall.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/test_full344_pathway_scorecard.py -q`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/metagent/full344_pathway_scorecard.py tests/test_full344_pathway_scorecard.py
git commit -m "feat(bench): wire recall@k + driver P/R columns into full344 scorecard"
```

---

### Task 8: Regenerate the scorecard report on existing dumps + sanity gate

**Files:**
- Modify: `reports/reports_v2/2026-06-19_full344_pathway_scorecard.md` (regenerated artifact)

- [ ] **Step 1: Run the full repo gate (no regression)**

Run: `PYTHONPATH=. pytest tests/test_pathway_relevant_set.py tests/test_driver_gold.py tests/test_pathway_recall_driver_metrics.py tests/test_build_sidecars.py tests/test_full344_pathway_scorecard.py -q`
Expected: all PASS.

- [ ] **Step 2: Regenerate scorecard against existing dumps**

```bash
PYTHONPATH=. python scripts/metagent/full344_pathway_scorecard.py \
  --ramp /data/weiwentao/llm_agent_metabolomics/ramp.sqlite
```
Expected: report now contains a `recall@k / hit@k / MRR` table for all four strata and `driver precision/recall` for sub6 + hmdb_ramp (human1/recon2 show `N/A`).

- [ ] **Step 3: Eyeball sanity** — confirm sub6/hmdb_ramp `hit@3` ≥ old `top-k name-exact`, and driver P/R are in (0,1]; human1/recon2 driver columns read `N/A`.

- [ ] **Step 4: Commit the regenerated report**

```bash
git add reports/reports_v2/2026-06-19_full344_pathway_scorecard.md \
        reports/reports_v2/2026-06-19_full344_pathway_scorecard.json
git commit -m "report(bench): regenerate full344 scorecard with recall@k + driver P/R"
```

---

## Self-Review

**Spec coverage:**
- 1A recall@k vs relevant set → Tasks 1,2 (builder), 3 (metric), 6 (sidecar), 7 (wire), 8 (report). ✓
- 1B driver P/R → Tasks 4 (gold builder), 5 (metric), 6 (sidecar), 7 (wire), 8 (report). ✓
- Decision① (GT + duplicates + Jaccard neighbors) → Task 1. ✓
- Decision② (sub6/hmdb_ramp spiked members; human1/recon2 N/A) → Tasks 4, 6 (`is_na_stratum`), 5 (`None` passthrough). ✓
- Keep old metrics → Task 7 note "existing columns unchanged". ✓
- No verifier/ edits, no B1 asset edits → all files under concord/agent, scripts/metagent, tests, data/benchmark. ✓

**Type consistency:** `build_relevant_set_ramp(conn, id, *, jaccard_threshold)` and `build_relevant_set_modelorg(conn, name, source, *, jaccard_threshold)` used identically in Task 6. `build_gold_drivers_ramp(conn, input_ids, gt_id)` and `resolve_to_ramp_id(conn, cid)` consistent across Tasks 4,6,7. `pathway_recall_metrics(names, set, *, k)` / `driver_pr_metrics(set, set|None)` consistent across Tasks 3,5,7. ✓

**Placeholder scan:** Task 7 Step 3 prose describes the `rows_for_full344`/`summarize` merge without full code because it edits an existing multi-function flow; the new pure function `recall_driver_row` (the testable unit) is fully specified and tested. Acceptable: the gate is the unit test on `recall_driver_row`; the merge is mechanical wiring around an existing function the implementer can read.

## Open Questions (non-blocking)

- θ=0.3 Jaccard 是默认；若 relevant-set 过大/过小，Task 8 eyeball 后可调 `--jaccard-threshold` 重建 sidecar（不改代码）。
- `recall@k` 默认 k=3（对齐现有 top-k 口径）；如需 k=5 仅改 scorecard CLI。
- 预测驱动解析依赖 report-time 的 ramp.sqlite；不带 `--ramp` 时 driver 列记 null + note，eval 默认仍可跑。
