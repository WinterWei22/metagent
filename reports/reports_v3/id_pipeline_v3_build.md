# MetAgent v3 — InChIKey ID 解析管道：构建与流程说明

**日期**: 2026-06-24
**核心文件**:
- `scripts/metagent/build_inchikey_xref.py` — ETL 脚本
- `data/concord/inchikey_xref.sqlite` — 结果数据库（402K 行）
- `concord/lookup/inchikey_xref.py` — 线程安全查询接口
- `concord/agent/tool_handlers.py:_ids_to_refs()` — PA 工具适配层

---

## 1. 背景与动机

v3 之前（v3 benchmark 及以前），MetAgent Stage 2 依赖输入中预填充的 KEGG ID（`kegg_id` 字段）。v4 benchmark 去掉了预填充 ID，代谢物仅以 `{name, smiles, inchikey}` 形式呈现，要求系统自动完成：

```
InChIKey → KEGG / HMDB / ChEBI → PA 工具（ORA/PSEA/Mummichog/FELLA/RaMP）
```

为此构建了聚合的 InChIKey 交叉引用表。

---

## 2. 数据来源

| 来源 | 覆盖内容 | 文件/端点 |
|---|---|---|
| PubChem CID-Identifiers | CID → {KEGG, HMDB, ChEBI, LIPIDMAPS} | `ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/CID-Identifiers.tsv.gz`（94 MB）|
| PubChem CID-InChI-Key | CID → InChIKey | `ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/CID-InChI-Key.gz`（6.2 GB）|
| HMDB JSON | InChIKey → HMDB ID（全量 217K）| `/home/weiwentao/workspace/Enzyme_Networks/data/enzyme_networks/MetaKG/hmdb_metabolites.json` |

PubChem 两个文件通过 CID 做 JOIN，再与 HMDB JSON 合并补充 PubChem 未覆盖的条目。

---

## 3. ETL 流程（`build_inchikey_xref.py`）

```
Pass 1: CID-Identifiers.tsv.gz
    扫描 12M 行，筛选含 KEGG/HMDB/ChEBI/LIPIDMAPS 的 CID
    → 388,888 个 CID，452,052 条 xref 行
    → 内存字典 {CID: {kegg, hmdb, chebi, lipidmaps}}

Pass 2: CID-InChI-Key.gz
    扫描 123M 行，JOIN InChIKey → CID → xref
    → 386,546 个唯一 InChIKey 匹配
    → 写入 SQLite 临时表

Pass 3: HMDB JSON fallback
    扫描 217K HMDB 条目，补充 PubChem 未覆盖的 InChIKey
    → 新增 15,778 行

最终写入: data/concord/inchikey_xref.sqlite
总计 402,324 行，耗时 ~247 秒
```

### SQLite Schema

```sql
CREATE TABLE inchikey_xref (
    inchikey     TEXT PRIMARY KEY,
    chebi_id     TEXT,   -- "CHEBI:15422" 格式
    kegg_id      TEXT,   -- "C00002" 格式
    hmdb_id      TEXT,   -- "HMDB0000538" 格式
    lipidmaps_id TEXT    -- "LMFA..." 格式
);
CREATE INDEX idx_kegg  ON inchikey_xref(kegg_id);
CREATE INDEX idx_hmdb  ON inchikey_xref(hmdb_id);
CREATE INDEX idx_chebi ON inchikey_xref(chebi_id);
```

### 全库覆盖统计

| 字段 | 行数 | 覆盖率 |
|---|---:|---:|
| 总行数 | 402,324 | — |
| chebi_id | 179,184 | 44.5% |
| hmdb_id | 217,906 | 54.2% |
| kegg_id | 26,920 | 6.7% |
| lipidmaps_id | 41,405 | 10.3% |

> KEGG 覆盖率低（6.7%）是 PubChem 本身对 KEGG 收录有限的正常现象；在基准集实际化合物上 KEGG 覆盖达 75.8%（因基准集偏向生物学相关代谢物）。

---

## 4. 查询接口

```python
from concord.lookup.inchikey_xref import InchikeyXrefLookup

lkp = InchikeyXrefLookup()  # 线程安全，每线程独立 sqlite 连接
rec = lkp.lookup("WQZGKKKJIJFFOK-GASJEMHNSA-N")  # 葡萄糖
# XrefRecord(inchikey='...', chebi_id='CHEBI:4167', kegg_id='C00031',
#            hmdb_id='HMDB0304632', lipidmaps_id=None)
```

`InchikeyXrefLookup` 使用 `threading.local` 确保每线程独立连接，适合 `k=10` 并发评测。

---

## 5. PA 工具适配层（`_ids_to_refs`）

`concord/agent/tool_handlers.py` 中的 `_ids_to_refs()` 是 InChIKey → PA 工具的统一入口：

```
LLM 传入 compound_ids=["WQZGKKKJIJFFOK-GASJEMHNSA-N", ...]
  ↓
_detect_input_namespace()   → 识别 27 字符 InChIKey 格式
  ↓
InchikeyXrefLookup.lookup() → 查 inchikey_xref.sqlite
  ↓
SimpleNamespace ref = {
    primary_id      = "CHEBI:4167",
    chebi_id        = "CHEBI:4167",
    kegg_compound_id = "KEGG:C00031",
    hmdb_id         = "HMDB:HMDB0304632",
    inchikey        = "WQZGKKKJIJFFOK-GASJEMHNSA-N",
}
  ↓
各 PA wrapper 取所需字段:
  sspa          → chebi_id / primary_id（Reactome）
  run_ramp      → hmdb_id → inchikey fallback
  metaboanalystr → hmdb_id（KEGG ORA）
  mummichog     → chebi_id → ChebiLookup（质量）
  fella         → kegg_compound_id → ChEBI→KEGG fallback
```

未命中 xref 时自动 fallback 到 `_enrich_ref_via_chebi()`（ChEBI sqlite 路径），不中断流程。

---

## 6. 基准集实际覆盖（v4 filtered，4,352 代谢物）

| ID 字段 | 覆盖数 | 覆盖率 |
|---|---:|---:|
| ChEBI | 4,307 | 99.0% |
| HMDB | 3,468 | 79.7% |
| KEGG | 3,300 | 75.8% |

v4 filtered 通过剔除 xref 全空的代谢物（1,851 个），所有保留代谢物均有至少一个可用 PA 工具 ID。

---

## 7. 不可恢复的 miss 分析（原始 v4 中的 13%）

| 类别 | 数量 | 原因 |
|---|---:|---|
| MAMxxx（GEM 内部 ID，无外部注释）| 146 | Human1/Recon2.2 特有代谢物，KEGG/HMDB/ChEBI 均无收录，GEM 自身 `metabolites.tsv` 也无 xref |
| 带电/同位素 InChIKey 变体（-L/-M/-O）| ~15 | PubChem CID-InChI-Key 仅收 neutral 标准形式（-N/-S 结尾）|
| VMH 药物代谢物缩写 | ~9 | 无通路意义的药物中间体 |

尝试通过 Human1 GEM XML 注释（`inchi` 字段）补充 InChIKey→注释映射，仅恢复 5/170，原因：GEM 中仅 444/8461 代谢物有 InChI，且带注释的 MAMxxx 正是那些已有外部 ID 的条目（已在 xref 中）。

---

## 8. 重建步骤

```bash
# 1. 下载 PubChem 文件（需 ~8 GB 磁盘）
mkdir -p /tmp/pubchem_dl
wget -c "https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/CID-Identifiers.tsv.gz" \
     -O /tmp/pubchem_dl/CID-Identifiers.tsv.gz
wget -c "https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/CID-InChI-Key.gz" \
     -O /tmp/pubchem_dl/CID-InChI-Key.gz

# 2. 验证 gzip 完整性
gzip -t /tmp/pubchem_dl/CID-InChI-Key.gz && echo OK

# 3. 运行 ETL（~4 分钟）
PYTHONPATH=. python3 scripts/metagent/build_inchikey_xref.py

# 4. 验证
sqlite3 data/concord/inchikey_xref.sqlite \
    "SELECT COUNT(*), SUM(kegg_id IS NOT NULL), SUM(hmdb_id IS NOT NULL) FROM inchikey_xref;"
# 期望: 402324 | 26920 | 217906
```

> PubChem CID-InChI-Key.gz 每季度更新，重建后行数可能略有差异。
