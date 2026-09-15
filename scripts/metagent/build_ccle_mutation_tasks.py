#!/usr/bin/env python3
"""CCLE 癌症代谢突变 → benchmark 任务(人类、非循环硬 gold、工具匹配)。

源:CCLE metabolomics(928 系×225 代谢物,Broad)+ CCLE mutation MAF。
每个代谢酶基因:突变系 vs WT 差异代谢物 → 输入;gold=被突变酶的通路(锚在突变上,非循环)。
solvability filter:诊断 biomarker(底物应升)显著+方向对才保留。

用法:python scripts/metagent/build_ccle_mutation_tasks.py <ccle_dir> <out_dir>
"""
from __future__ import annotations
import csv, json, math, sys
from pathlib import Path
from scipy.stats import ttest_ind

# 代谢酶基因 → (诊断 biomarker 在 CCLE 225-panel 的列名, gold 通路, hotspot 过滤 or None)
GENES = {
    "IDH1": ("2-hydroxyglutarate", "Citrate cycle (TCA) / 2-HG (isocitrate dehydrogenase)", ["R132"]),
    "IDH2": ("2-hydroxyglutarate", "Citrate cycle (TCA) / 2-HG (isocitrate dehydrogenase)", ["R140", "R172"]),
    "FH":   ("fumarate/maleate/alpha-ketoisovalerate", "Citrate cycle (TCA) (fumarate hydratase)", None),
    "SDHA": ("succinate/methylmalonate", "Citrate cycle (TCA) (succinate dehydrogenase)", None),
    "SDHB": ("succinate/methylmalonate", "Citrate cycle (TCA) (succinate dehydrogenase)", None),
    "SDHC": ("succinate/methylmalonate", "Citrate cycle (TCA) (succinate dehydrogenase)", None),
    "SDHD": ("succinate/methylmalonate", "Citrate cycle (TCA) (succinate dehydrogenase)", None),
}
TOP_N = 15


def load_ccle_met(p):
    rows = list(csv.reader(open(p)))
    hdr = rows[0]; mets = hdr[2:]
    line2vals = {}
    for r in rows[1:]:
        vals = {}
        for i, m in enumerate(mets):
            try: vals[m] = float(r[2 + i])
            except (ValueError, IndexError): pass
        line2vals[r[0]] = vals  # CCLE_ID
    return mets, line2vals


def mutant_lines(maf, gene, hotspots):
    f = open(maf); hdr = f.readline().rstrip("\n").split("\t")
    ig = hdr.index("Hugo_Symbol"); ip = hdr.index("Protein_Change")
    ivc = hdr.index("Variant_Classification"); itb = hdr.index("Tumor_Sample_Barcode")
    out = set()
    for ln in f:
        p = ln.rstrip("\n").split("\t")
        if len(p) <= max(ig, ip, ivc, itb) or p[ig] != gene: continue
        if hotspots:
            if any(h in p[ip] for h in hotspots): out.add(p[itb])
        else:
            if p[ivc] in ("Missense_Mutation", "Nonsense_Mutation", "Frame_Shift_Del",
                          "Frame_Shift_Ins", "Splice_Site", "In_Frame_Del"): out.add(p[itb])
    return out


def main():
    ccle = Path(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    mets, line2vals = load_ccle_met(ccle / "ccle_metabolomics.csv")
    all_lines = set(line2vals)
    tasks = []; log = []
    for gene, (biomarker, pathway, hotspots) in GENES.items():
        mut = mutant_lines(ccle / "ccle_mutations.txt", gene, hotspots) & all_lines
        wt = all_lines - mut
        if len(mut) < 1:
            log.append(f"{gene}: 0 mutant lines with metabolomics — skip"); continue
        # per-metabolite differential (mut vs wt)
        diff = []
        for m in mets:
            mv = [line2vals[l][m] for l in mut if m in line2vals[l]]
            wv = [line2vals[l][m] for l in wt if m in line2vals[l]]
            if len(mv) < 1 or len(wv) < 3: continue
            mm = sum(mv) / len(mv); mw = sum(wv) / len(wv)
            try: p = float(ttest_ind(mv, wv, equal_var=False).pvalue) if len(mv) >= 2 else 1.0
            except Exception: p = 1.0
            diff.append({"name": m, "delta": round(mm - mw, 3), "p": round(p, 4)})
        # solvability: biomarker up + (sig if n>=2)
        bm = next((d for d in diff if d["name"] == biomarker), None)
        solv = bm is not None and bm["delta"] > 0 and (bm["p"] < 0.05 or len(mut) < 2)
        diff.sort(key=lambda x: (x["p"], -abs(x["delta"])))
        top = diff[:TOP_N]
        tasks.append({
            "task_id": f"ccle_mut_{gene}",
            "source": "CCLE metabolomics (Broad, Li et al Nat Med 2019) + CCLE mutation MAF",
            "perturbation": {"type": "somatic_mutation", "gene": gene, "n_mutant_lines": len(mut),
                             "mutant_lines": sorted(mut)},
            "input": {"differential_metabolites": [{"name": d["name"], "delta": d["delta"], "p": d["p"]} for d in top]},
            "gold": {"mutated_enzyme": gene, "perturbed_pathway": pathway,
                     "diagnostic_biomarker": biomarker, "gold_anchor": "somatic_mutation (non-circular)",
                     "solvability": "PASS" if solv else "WEAK"},
        })
        log.append(f"{gene}: {len(mut)} mut lines; biomarker {biomarker} delta={bm['delta'] if bm else 'NA'} "
                   f"p={bm['p'] if bm else 'NA'} -> {'PASS' if solv else 'WEAK'}")
    (out / "ccle_mutation_tasks.jsonl").write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in tasks) + "\n", encoding="utf-8")
    summary = {"n_tasks": len(tasks), "n_pass": sum(1 for t in tasks if t["gold"]["solvability"] == "PASS"),
               "genes": [t["perturbation"]["gene"] for t in tasks], "log": log}
    (out / "ccle_mutation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
