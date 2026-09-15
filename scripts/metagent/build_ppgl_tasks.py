#!/usr/bin/env python3
"""PPGL(嗜铬细胞瘤/副神经节瘤)代谢突变 → benchmark 任务。

源:Richter et al. Genet Med 2019(PMID 30050099),Supp1 = 395 样本 × 14 代谢物(ng/mg)
+ 每样本 somatic 突变基因。人类、已发表、非循环硬 gold(gold=被突变酶),工具匹配。
每代谢酶突变组 vs 非代谢驱动 PPGL 对照 → 差异代谢物;solvability=诊断 biomarker 升+显著。

用法:python scripts/metagent/build_ppgl_tasks.py <supp1.xlsx> <out_dir>
"""
from __future__ import annotations
import json, math, sys
from pathlib import Path
import openpyxl
from scipy.stats import ttest_ind

# 代谢酶突变组 → (成员基因, 诊断 biomarker 列, gold 通路)
GROUPS = {
    "SDHx (succinate dehydrogenase)": (
        {"SDHB", "SDHC", "SDHD", "SDHA", "SDHAF2", "SDHC promoter methylation"},
        "SUC(ng/mg)", "Citrate cycle (TCA) — succinate dehydrogenase deficiency"),
    "FH (fumarate hydratase)": ({"FH"}, "FUM(ng/mg)", "Citrate cycle (TCA) — fumarate hydratase deficiency"),
    "IDH (isocitrate dehydrogenase)": ({"IDH1", "IDH2"}, "2HG(ng/mg)", "Citrate cycle (TCA) — IDH / 2-hydroxyglutarate"),
    "MDH2 (malate dehydrogenase)": ({"MDH2"}, "MAL(ng/mg)", "Citrate cycle (TCA) — malate dehydrogenase deficiency"),
}
# 非代谢驱动(对照):PPGL 但无直接 TCA 酶缺陷
CONTROL_GENES = {"RET", "NF1", "VHL", "EPAS1", "HRAS", "TMEM127", "MAX", "KIF1B", "ATRX^", "None", "None "}


def main():
    xlsx = Path(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    ws = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)["Raw data"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = list(rows[0]); data = rows[1:]
    gi = next(i for i, h in enumerate(hdr) if h and "Mutated gene" in str(h))
    met_cols = [(i, h) for i, h in enumerate(hdr) if h and "ng/mg" in str(h)]

    def gene(r): return str(r[gi]).strip() if r[gi] is not None else ""
    controls = [r for r in data if gene(r) in CONTROL_GENES]

    def fval(r, i):
        try: v = float(r[i]); return v if v > 0 else None
        except (TypeError, ValueError): return None

    def differential(mut_rows):
        out_d = []
        for i, name in met_cols:
            mv = [fval(r, i) for r in mut_rows]; mv = [x for x in mv if x]
            cv = [fval(r, i) for r in controls]; cv = [x for x in cv if x]
            if len(mv) < 1 or len(cv) < 3: continue
            mm = sum(mv) / len(mv); mc = sum(cv) / len(cv)
            l2 = math.log2(mm / mc)
            try: p = float(ttest_ind(mv, cv, equal_var=False).pvalue) if len(mv) >= 2 else 1.0
            except Exception: p = 1.0
            out_d.append({"name": name.replace("(ng/mg)", "").strip(), "log2fc": round(l2, 2), "p": round(p, 4)})
        out_d.sort(key=lambda x: (x["p"], -abs(x["log2fc"])))
        return out_d

    tasks = []; log = []
    for label, (genes, biomarker, pathway) in GROUPS.items():
        mut = [r for r in data if gene(r) in genes]
        if not mut:
            log.append(f"{label}: 0 samples — skip"); continue
        diff = differential(mut)
        bmn = biomarker.replace("(ng/mg)", "").strip()
        bm = next((d for d in diff if d["name"] == bmn), None)
        # PASS: 诊断 biomarker 升高且(统计显著 或 effect 巨大——低 n 时 t 检验受限但效应确凿)
        solv = bm is not None and bm["log2fc"] > 0 and (bm["p"] < 0.05 or bm["log2fc"] > 1.5)
        tasks.append({
            "task_id": f"ppgl_{label.split()[0].lower()}",
            "source": "Richter et al. Genet Med 2019 (PMID 30050099) Supp1",
            "perturbation": {"type": "somatic/germline_mutation", "gene_group": label,
                             "genes": sorted(genes), "n_mutant": len(mut), "organism": "Homo sapiens"},
            "input": {"differential_metabolites": diff},
            "gold": {"mutated_enzyme": label, "perturbed_pathway": pathway,
                     "diagnostic_biomarker": bmn, "gold_anchor": "mutation (non-circular)",
                     "solvability": "PASS" if solv else "WEAK"},
            "n_control": len(controls),
        })
        log.append(f"{label}: n_mut={len(mut)} | {bmn} log2fc={bm['log2fc'] if bm else 'NA'} "
                   f"p={bm['p'] if bm else 'NA'} -> {'PASS' if solv else 'WEAK'}")

    (out / "ppgl_tasks.jsonl").write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in tasks) + "\n")
    summary = {"n_tasks": len(tasks), "n_control": len(controls),
               "n_pass": sum(1 for t in tasks if t["gold"]["solvability"] == "PASS"), "log": log}
    (out / "ppgl_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n=== SDHx task 输入(top-6 差异代谢物) ===")
    t0 = next(t for t in tasks if "sdhx" in t["task_id"])
    for d in t0["input"]["differential_metabolites"][:6]:
        print(f"   {d['name']:<8} log2fc={d['log2fc']:+.2f} p={d['p']}")


if __name__ == "__main__":
    main()
