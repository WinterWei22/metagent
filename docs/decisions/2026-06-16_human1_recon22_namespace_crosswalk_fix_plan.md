# Human1/Recon2.2 命名空间 crosswalk 修复计划

Date: 2026-06-16
Status: PLANNED(未动工,先评审)
Track: 独立于 W22 主线的"覆盖边界"修复轨道
Owner intent anchor: `project_w21_hypothesis_intent`(分母永不剔除)、`feedback_verifier_modification_policy`(三档)、`feedback_verifier_side_marginal_returns`

## 1. 问题(已用真实数据证实)

D8 结果:Cooke Human1/Recon2.2 层(181 任务,占 benchmark 53%)结构化臂 supported 仅 **0.78%**、通路 ID 命中 **0.00%**、几乎全 UV。这不是 bug,是命名空间没覆盖。

数据契约(实测一个 Human1 任务):
- **输入代谢物**:Human1 `MAM#####` ID(如 `MAM02776`),不是 KEGG/HMDB
- **Ground truth 通路**:`{id: "group1", name: "Acyl-CoA hydrolysis", ontology: "Human1"}` —— `groupN` 是 Cooke 自建的子系统分组标签,**无任何外部通路 ID**

W22 verifier 现状(`verifier/helpers/pathway_namespace.py:canonical_pathway_id`):只认 KEGG/Reactome/WP/SMPDB/mummichog。遇到 `group1` 或 Human1 子系统名 → 返回 `None` → 无法 ID 匹配。

## 2. 根因:两个独立的 gap

**Gap A —— 代谢物命名空间(上游,决定 PA 工具能否产出有意义的 carrier)**
输入是 MAM ID,5 个 PA 工具(mummichog/RaMP/…)只认 KEGG/HMDB。MAM 不映射 → 富集跑空 → 全 UV。

**Gap B —— 通路匹配(verifier 侧,决定预测能否对上 ground truth)**
Ground truth 通路只有 `groupN` + 名字,**没有外部 ID**。ID-exact 匹配在这一层**物理上不可能**,唯一可行路径是**按名字匹配**(= GeneAgent 名字匹配思路的合法应用)。

## 3. 现成资产(已在硬盘上确认)

| 文件 | 作用 | 覆盖率(实测) |
|---|---|---|
| `…/tier_a_cooke/aux/human_gem_metabolites.tsv`(12626 行) | MAM → KEGG/HMDB/ChEBI/… | MAM→KEGG **52.2%**、MAM→HMDB **38.5%** |
| `…/tier_a_cooke/aux/pathway_dict_human1.tsv` | `groupN` → 通路名 | 全覆盖(分组定义表) |
| `…/tier_a_cooke/aux/pathway_dict_recon2.tsv` | Recon2.2 分组 → 名 | 同上 |
| `/data/weiwentao/…/raw/cooke2025/metab_dict.tsv` | MAR/MAM/Name 对照 | 备用 |

## 4. 诚实天花板(必须先讲,防过度承诺 / 防变指标游戏)

- 代谢物只有 ~52% 能进 KEGG → Human1 富集本质上只在**一半代谢物**上跑,救回率被这个钉死。
- 通路只能**名字语义匹配**,天生比 Sub-6 的 ID-exact 松。这一层**永远达不到** Sub-6 的严谨度。
- 现实目标:把 Human1 supported 从 0.78% 抬到**估计 15–30%(仅可映射子集上)**,且**必须分开报 "ID-exact" 与 "name-match" 两个数**,name-match 数永远带"较松"标注。
- 不剔分母:映射不到的代谢物/通路仍留在 UV 里诚实计数,救回的才算 supported。

## 5. 分阶段方案(全程 flag-off / paired / 离线优先)

### Phase 0 —— 诊断:哪个 gap 是主因($0 离线,先做,设 gate)
读 D8 那 179 个 Human1/Recon dump:
- 模型到底有没有产出富集 carrier?(若代谢物没映射→carrier 空→Gap A 主导)
- 若有 carrier,它们的通路名能不能跟 `groupN` 名字语义对上?(Gap B)
- **gate**:据此决定先建哪个、是否两个都要。若 carrier 普遍空 → 先 Gap A;若 carrier 有但名字对不上 → 先 Gap B。**两个 gap 的相对大小没量化前不写生产代码。**

### Phase 1 —— Gap A:代谢物 crosswalk(新增,不改 PA 工具内部)
- 新 helper `verifier/helpers/human1_metabolite_crosswalk.py`(**Add ✅**):从 `human_gem_metabolites.tsv` 建 MAM(去 compartment 后缀)→ KEGG/HMDB 解析器。
- 作为**输入适配层**只对 Human1/Recon 这一层生效:PA 工具收到 KEGG/HMDB 而非 MAM。**不动 PA 工具内部、不动 B1-core。**
- flag:`METAGENT_ENABLE_HUMAN1_CROSSWALK`,默认 off。

### Phase 2 —— Gap B:通路名匹配兜底(新增,复用现有 fuzzy)
- 新 helper `verifier/helpers/human1_pathway_match.py`(**Add ✅**):用 `pathway_dict_*.tsv` 把 ground truth `groupN` 解析成名字,复用现有 `verifier/helpers/fuzzy_match.py` 做**保守阈值**的名字语义匹配。
- **只在 ID-exact 失败、且 ontology∈{Human1,Recon2.2} 时**才启用 name-match 兜底,不污染 Sub-6 的 ID-exact 路径。
- 若要动 `pathway_namespace.py` / `method_aware_enrichment.py` → 那是 **Modify ⚠,动工前 ping**;优先用新 helper + 调用点包一层,留在 Add 范围。

### Phase 3 —— 离线重验 179 个($0,paired)
- 同一批 D8 dump 上,开/关 crosswalk 两臂对比,**分 Human1 / Recon2.2 两小层**出 supported/UV、ID-exact 命中、name-match 命中。
- 与 D8 基线(0.78%)对照,量化救回量。

### Phase 4 —— 验真(死命令,防名字匹配注水)
- 抽 ~15 条 name-match 救回的 claim,人工核对名字是否真等价(不是凑字面)。**≥80% 才算可信**,低于则报数 + 明标"需复查"。
- name-match 是最容易变成指标游戏的地方,这一关不过不许进生产。

## 6. 死命令合规检查
- 分母永不剔除(W21):映射不到的仍计 UV。✅
- verifier 三档:全部走新 helper = Add ✅;碰 `pathway_namespace`/`method_aware_enrichment` = Modify ⚠ 先 ping。
- 边际递减(`feedback_verifier_side_marginal_returns`):本修复开的是当前 0% 的一层、占 benchmark 53%,不是"已覆盖层 <5pp"的小修,过门槛;但仍用 Phase 0 gate 先确认 headroom 再建。
- flag 默认 off;paired/离线优先;不改 B1-core / W17 schema;14-fail floor;name-match 分开报且带"较松"标注。
- 不写 paper narrative;cost 若涉 LLM 从实际 token 算。

## 7. 不做什么
- 不学 GeneAgent 的"verifier 用参数知识编证据从不弃权"(毁 faithfulness)。
- 不学 GeneAgent 的"不支持内容删掉不进分母"(违反分母死命令)。
- 不把 Human1 name-match 数混进 W22 总成绩单的 ID-exact 指标。

## 8. 完成标志
Phase 3 给出分层救回数 + Phase 4 验真 ≥80%,master log 报"Human1/Recon2.2 从 0.78% → X%(name-match,较松,仅 52% 可映射子集)",ping PI 决定是否落地 flag。
