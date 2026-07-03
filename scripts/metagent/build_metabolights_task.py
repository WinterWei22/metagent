#!/usr/bin/env python3
"""MetaboLights 研究(MAF + sample metadata)→ benchmark 任务(自动、免下载、MAF 自带 SMILES/InChI)。

MAF: metabolite_identification / smiles / inchi + per-sample abundance 列。
sample metadata: Sample Name → Factor Value[分组]。case vs control 差异 → gold=已知扰动酶/通路。
用法:python build_metabolights_task.py <maf.tsv> <sample.txt> <group_kw> <case_val> <ctrl_val> <task_id> <gold_pathway> <biomarker> <out.jsonl>
"""
import json, math, sys
from scipy.stats import ttest_ind
try:
    from rdkit import Chem
    def ikey(inchi, smiles):
        try:
            if inchi and inchi.startswith('InChI='): return Chem.InchiToInchiKey(inchi)
        except Exception: pass
        try:
            m = Chem.MolFromSmiles(smiles); return Chem.MolToInchiKey(m) if m else None
        except Exception: return None
except ImportError:
    def ikey(inchi, smiles): return None


def main():
    maf, smeta, gkw, case, ctrl, tid, gold, biomarker, out = sys.argv[1:10]
    # sample metadata: Sample Name -> group
    srows = [l.rstrip('\n').split('\t') for l in open(smeta)]
    sh = [h.strip().strip('"') for h in srows[0]]
    sn_i = sh.index('Sample Name')
    g_i = next(i for i, h in enumerate(sh) if gkw in h)
    samp_group = {r[sn_i].strip('"'): r[g_i].strip('"') for r in srows[1:] if len(r) > max(sn_i, g_i)}
    # MAF
    mrows = [l.rstrip('\n').split('\t') for l in open(maf)]
    mh = mrows[0]
    ni = mh.index('metabolite_identification'); smi = mh.index('smiles'); ini = mh.index('inchi')
    scols = {i: mh[i] for i in range(len(mh)) if mh[i] in samp_group}
    case_c = [i for i in scols if samp_group[mh[i]] == case]
    ctrl_c = [i for i in scols if samp_group[mh[i]] == ctrl]
    print(f"case({case})={len(case_c)} ctrl({ctrl})={len(ctrl_c)} samples")

    def fv(r, i):
        try: v = float(r[i]); return v if v > 0 else None
        except (TypeError, ValueError, IndexError): return None

    diff = []
    for r in mrows[1:]:
        name = r[ni].strip()
        if not name: continue
        a = [fv(r, i) for i in case_c]; a = [x for x in a if x]
        b = [fv(r, i) for i in ctrl_c]; b = [x for x in b if x]
        if len(a) < 3 or len(b) < 3: continue
        l2 = math.log2((sum(a)/len(a))/(sum(b)/len(b)))
        p = float(ttest_ind(a, b, equal_var=False).pvalue)
        if p < 0.05 and abs(l2) > 0.3:
            diff.append({"name": name, "smiles": r[smi].strip(), "inchikey": ikey(r[ini].strip(), r[smi].strip()) or "",
                         "log2fc": round(l2, 2), "p": round(p, 4)})
    diff.sort(key=lambda x: x["p"])
    diff = [d for d in diff if d["inchikey"]]  # 只留能解析的
    bm = next((d for d in diff if biomarker.lower() in d["name"].lower()), None)
    task = {
        "task_id": "sub6_easy_" + tid, "orig_task_id": tid, "pathway_family": "TCA/oncometabolite" if "TCA" in gold else "other",
        "source": f"MetaboLights {maf.split('/')[-1].split('_')[1]}",
        "input": {"differential_metabolites": [{"name": d["name"], "smiles": d["smiles"], "inchikey": d["inchikey"]} for d in diff[:15]]},
        "ground_truth": {"perturbed_pathway": {"id": "", "name": gold, "ontology": "curated"}},
        "_diff_stats": diff[:15], "_biomarker": bm,
    }
    with open(out, "a") as f: f.write(json.dumps(task, ensure_ascii=False) + "\n")
    print(f"[{tid}] n_diff={len(diff)} | biomarker {biomarker}: {bm}")
    print("  top-6:", [(d['name'], d['log2fc']) for d in diff[:6]])


if __name__ == "__main__":
    main()
