#!/usr/bin/env python3
"""把 perturbation benchmark v0 桥接成 MetAgent(v4)输入格式,供 v4_bench_eval 跑。

- 代谢物缩写展开(Phe→phenylalanine 等)+ 滤掉未注释 m/z 特征。
- gold.perturbed_pathway → ground_truth.perturbed_pathway.name(供 scorecard 语义打分)。
- task_id 加 sub6_easy_ 前缀(stratum 检测)。
用法:python scripts/metagent/bridge_perturbation_bench_to_metagent.py <v0.jsonl> <out_bench.jsonl>
"""
import json, re, sys

ABBR = {
    "phe": "phenylalanine", "suc": "succinate", "fum": "fumarate", "mal": "malate",
    "cit": "citrate", "isocit": "isocitrate", "cisac": "cis-aconitate", "keto": "2-oxoglutarate",
    "2hg": "2-hydroxyglutarate", "lac": "lactate", "pyr": "pyruvate", "glu": "glutamate",
    "gln": "glutamine", "asp": "aspartate", "asn": "asparagine",
    "succinate/methylmalonate": "succinate", "fumarate/maleate/alpha-ketoisovalerate": "fumarate",
}
# gold 通路 → 干净可 match 的通路名(供 scorecard)
GOLD_PATHWAY = {
    "TCA": "Citrate cycle (TCA cycle)",
    "Urea cycle": "Urea cycle / arginine biosynthesis",
    "Phenylalanine": "Phenylalanine metabolism",
    "BCAA": "Valine, leucine and isoleucine degradation",
}
MZ = re.compile(r'^[\d.]+_[\d.]+(m/z|n)$|^X\s*-\s*\d')  # 未注释特征


def clean_name(n):
    n = str(n).strip()
    return ABBR.get(n.lower(), n)


def gold_name(t):
    fam = t.get("pathway_family", "")
    if "TCA" in fam: return GOLD_PATHWAY["TCA"]
    if "Urea" in fam: return GOLD_PATHWAY["Urea cycle"]
    if "Phenylalanine" in fam: return GOLD_PATHWAY["Phenylalanine"]
    if "BCAA" in fam: return GOLD_PATHWAY["BCAA"]
    return t["gold"]["perturbed_pathway"]


def main():
    src, out = sys.argv[1], sys.argv[2]
    lines = []
    for l in open(src):
        if not l.strip(): continue
        t = json.loads(l)
        mets = []
        seen = set()
        for m in t["input"]["differential_metabolites"]:
            nm = m.get("name", "")
            if MZ.match(str(nm)): continue          # 滤未注释 m/z
            cn = clean_name(nm)
            if cn.lower() in seen: continue
            seen.add(cn.lower())
            mets.append({"name": cn})
        if len(mets) < 3: continue
        v4 = {
            "task_id": "sub6_easy_" + t["task_id"],
            "orig_task_id": t["task_id"],
            "pathway_family": t.get("pathway_family"),
            "input": {"differential_metabolites": mets[:15]},
            "ground_truth": {"perturbed_pathway": {"id": "", "name": gold_name(t), "ontology": "curated"}},
        }
        lines.append(json.dumps(v4, ensure_ascii=False))
    open(out, "w").write("\n".join(lines) + "\n")
    print(f"wrote {len(lines)} tasks -> {out}")
    for l in lines[:3]:
        d = json.loads(l)
        print(f"  {d['orig_task_id']}: gold='{d['ground_truth']['perturbed_pathway']['name']}' "
              f"mets={[m['name'] for m in d['input']['differential_metabolites'][:6]]}")


if __name__ == "__main__":
    main()
