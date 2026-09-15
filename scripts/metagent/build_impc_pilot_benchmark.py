#!/usr/bin/env python3
"""IMPC KO 试点 benchmark 构造(证明"扰动锚定 + 非循环硬 gold"设计可行)。

源:Metabolomics Workbench ST001154(IMPC 小鼠血浆代谢组,CC BY 4.0)
  30 个基因 KO(各 6 样)vs Genotype:Null(40 样,对照)。
每个 KO:KO vs Null 差异代谢物(log2FC + Welch t)→ 输入;
gold = 被敲基因 → 酶 → 通路(锚在基因缺陷上,非循环;不来自富集本体)。

输入数据须先由 fetch 脚本落到 SCRATCH/impc/{data,factors}.json(MW REST API)。
用法:python scripts/metagent/build_impc_pilot_benchmark.py <impc_dir> <out_dir>
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from scipy.stats import ttest_ind

# gold 注释(我的领域判断,全量建时应换 UniProt/KEGG 程序化 gene→enzyme→pathway)
# 只给我有把握的代谢酶;非代谢/信号基因标 non_metabolic(作 hard-negative 特异性对照)
GOLD = {
    "Ahcy":  ("S-adenosylhomocysteine hydrolase", "Cysteine and methionine metabolism / one-carbon", "confident"),
    "Dhfr":  ("dihydrofolate reductase", "One carbon pool by folate", "confident"),
    "G6pd2": ("glucose-6-phosphate dehydrogenase", "Pentose phosphate pathway", "confident"),
    "Idh1":  ("isocitrate dehydrogenase 1", "Citrate cycle (TCA)", "confident"),
    "Galc":  ("galactosylceramidase", "Sphingolipid metabolism", "confident"),
    "Gnpda1":("glucosamine-6-phosphate deaminase", "Amino sugar and nucleotide sugar metabolism", "confident"),
    "Mvk":   ("mevalonate kinase", "Terpenoid backbone / steroid biosynthesis", "confident"),
    "Pmm2":  ("phosphomannomutase 2", "Fructose and mannose metabolism / N-glycosylation", "confident"),
    "Pipox": ("pipecolate oxidase (sarcosine oxidase family)", "Lysine degradation", "moderate"),
    "Phyh":  ("phytanoyl-CoA 2-hydroxylase", "Fatty acid alpha-oxidation (peroxisomal)", "moderate"),
    "Mmachc":("cobalamin (B12) processing (MMACHC)", "Cobalamin metabolism (methylmalonate/homocysteine)", "moderate"),
    "Lmbrd1":("cobalamin metabolism (LMBRD1)", "Cobalamin metabolism", "moderate"),
    "Npc2":  ("NPC intracellular cholesterol transporter 2", "Cholesterol/sphingolipid transport", "moderate"),
    "Atp5b": ("ATP synthase F1 beta", "Oxidative phosphorylation", "moderate"),
    "Atp6v0d1": ("V-type ATPase subunit", "Oxidative phosphorylation / lysosomal acidification", "moderate"),
    # non-metabolic / signaling / structural → hard-negative 特异性对照
    "A2m": (None, None, "non_metabolic"), "C8a": (None, None, "non_metabolic"),
    "Cdk4": (None, None, "non_metabolic"), "Plk1": (None, None, "non_metabolic"),
    "Nek2": (None, None, "non_metabolic"), "Pttg1": (None, None, "non_metabolic"),
    "Rock1": (None, None, "non_metabolic"), "Iqgap1": (None, None, "non_metabolic"),
    "Dync1li1": (None, None, "non_metabolic"), "Ptpn12": (None, None, "non_metabolic"),
    "Ywhaz": (None, None, "non_metabolic"), "Sra1": (None, None, "non_metabolic"),
    "Ulk3": (None, None, "non_metabolic"), "Pebp1": (None, None, "non_metabolic"),
    "Mfap4": (None, None, "non_metabolic"),
}

TOP_N = 20        # 取每个 KO 的 top-N 差异代谢物作输入
MIN_PER_GROUP = 3 # 每组至少几个非缺失值才算


def _to_float(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def main():
    impc = Path(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    fac = list(json.load(open(impc / "factors.json")).values())
    data = list(json.load(open(impc / "data.json")).values())
    samp2geno = {r["local_sample_id"]: r["factors"].replace("Genotype:", "") for r in fac}
    null_samples = [s for s, g in samp2geno.items() if g == "Null"]
    ko_genes = sorted({g for g in samp2geno.values() if g != "Null"})

    # 每 KO 的样本
    ko2samples = defaultdict(list)
    for s, g in samp2geno.items():
        if g != "Null":
            ko2samples[g].append(s)

    # 对每个基因，逐代谢物算 KO vs Null 差异
    def diff_for(gene):
        ko_s = ko2samples[gene]
        rows = []
        seen_names = set()
        for r in data:
            name = r.get("metabolite_name") or r.get("refmet_name")
            if not name:
                continue
            D = r["DATA"]
            ko_v = [v for v in (_to_float(D.get(s)) for s in ko_s) if v is not None]
            nl_v = [v for v in (_to_float(D.get(s)) for s in null_samples) if v is not None]
            if len(ko_v) < MIN_PER_GROUP or len(nl_v) < MIN_PER_GROUP:
                continue
            mk = sum(ko_v) / len(ko_v); mn = sum(nl_v) / len(nl_v)
            log2fc = math.log2(mk / mn) if mn > 0 else 0.0
            try:
                p = float(ttest_ind(ko_v, nl_v, equal_var=False).pvalue)
            except Exception:
                p = 1.0
            key = name.strip().lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            rows.append({"name": name, "refmet": r.get("refmet_name") or "",
                         "log2fc": round(log2fc, 3), "p": p,
                         "analysis": r.get("analysis_summary")})
        # 排序:p 升序，取 top-N（真实差异列表口径）
        rows.sort(key=lambda x: (x["p"], -abs(x["log2fc"])))
        return rows

    # sanity 打印
    print("=== SANITY: top-8 differential metabolites for known enzyme KOs ===")
    for g in ["G6pd2", "Ahcy", "Idh1", "Pmm2"]:
        rows = diff_for(g)
        print(f"\n[{g}] gold={GOLD[g][1]}")
        for r in rows[:8]:
            print(f"   {r['name'][:42]:<44} log2FC={r['log2fc']:+.2f} p={r['p']:.2e} ({r['analysis']})")

    # 建全部任务
    tasks = []
    for g in ko_genes:
        rows = diff_for(g)
        top = [r for r in rows if r["p"] < 0.05][:TOP_N] or rows[:TOP_N]
        enzyme, pathway, conf = GOLD.get(g, (None, None, "unknown"))
        tasks.append({
            "task_id": f"impc_ko_{g}",
            "source": "Metabolomics Workbench ST001154 (IMPC, CC BY 4.0)",
            "perturbation": {"type": "gene_knockout", "gene": g, "organism": "Mus musculus"},
            "input": {"differential_metabolites": [
                {"name": r["name"], "refmet": r["refmet"], "log2fc": r["log2fc"], "p": r["p"]} for r in top]},
            "gold": {"defective_enzyme": enzyme, "perturbed_pathway": pathway,
                     "gold_confidence": conf, "gold_anchor": "gene_knockout (non-circular)"},
            "n_differential": len(top),
        })
    (out / "impc_pilot_tasks.jsonl").write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in tasks) + "\n", encoding="utf-8")

    # summary
    from collections import Counter
    conf_c = Counter(t["gold"]["gold_confidence"] for t in tasks)
    summary = {"n_tasks": len(tasks), "n_ko_genes": len(ko_genes), "n_null_controls": len(null_samples),
               "gold_confidence_breakdown": dict(conf_c),
               "hard_gold_metabolic": sum(1 for t in tasks if t["gold"]["gold_confidence"] in ("confident", "moderate")),
               "hard_negative_nonmetabolic": conf_c.get("non_metabolic", 0),
               "avg_n_differential": round(sum(t["n_differential"] for t in tasks) / len(tasks), 1)}
    (out / "impc_pilot_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n=== BUILD SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
