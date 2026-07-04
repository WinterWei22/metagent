#!/usr/bin/env python3
"""Miller et al. 2015 (Baylor Global MAPS, J Inherit Metab Dis, PMC4626538) → tasks.

ESM 1 "raw z-score data": col0=BIOCHEMICAL name, col11=KEGG, col17+=specimens
(row0=diagnosis, row2+ per-specimen z-score relative to controls). Mean z-score
across a disorder's specimens = its differential signature vs controls.
gold = known defective enzyme/pathway (non-circular). 21+ IEMs, one file.

用法:python scripts/metagent/build_miller_tasks.py <ESM1.xls> <out.jsonl>
"""
import json, sys
import xlrd

# diagnosis substring → (task_id, enzyme, gold pathway, biomarker keywords, family)
CONFIGS = [
    ("Methylmalonic aciduria", "miller_mma", "MUT (methylmalonyl-CoA mutase)",
     "Propanoate metabolism", ["methylmalonate", "methylmalonic", "methylcitrate", "propionylcarnitine"], "Propanoate"),
    ("Propionic aciduria", "miller_pa", "PCC (propionyl-CoA carboxylase)",
     "Propanoate metabolism", ["propionyl", "methylcitrate", "3-hydroxypropionate", "propionylglycine"], "Propanoate"),
    ("Guanidinoacetate methyltransferase", "miller_gamt", "GAMT",
     "Glycine, serine and threonine metabolism (creatine)", ["guanidinoacetate", "creatine"], "Creatine"),
    ("Homocystinuria", "miller_homocystinuria", "CBS (cystathionine beta-synthase)",
     "Cysteine and methionine metabolism", ["homocystine", "homocysteine", "methionine"], "Methionine"),
    ("Medium chain acyl-CoA dehydrogenase", "miller_mcad", "ACADM (MCAD)",
     "Fatty acid degradation", ["octanoylcarnitine", "hexanoylcarnitine", "decanoylcarnitine", "octenoyl"], "FAO"),
    ("Very-long chain acyl-CoA dehydrogenase", "miller_vlcad", "ACADVL (VLCAD)",
     "Fatty acid degradation", ["tetradecenoyl", "myristoylcarnitine", "tetradecanoyl", "dodecenoyl"], "FAO"),
    ("3-methylcrotonyl CoA carboxylase", "miller_3mcc", "MCCC (3-MCC)",
     "Valine, leucine and isoleucine degradation", ["methylcrotonylglycine", "3-hydroxyisovalerate", "tiglylcarnitine"], "Leucine"),
    ("Isovaleric aciduria", "miller_iva", "IVD (isovaleryl-CoA dehydrogenase)",
     "Valine, leucine and isoleucine degradation", ["isovalerylglycine", "isovalerylcarnitine", "3-hydroxyisovalerate"], "Leucine"),
    ("Maple syrup urine disease", "miller_msud", "BCKDH",
     "Valine, leucine and isoleucine degradation", ["leucine", "isoleucine", "valine", "ketoleucine", "oxo"], "BCAA"),
    ("Phenylketonuria", "miller_pku", "PAH",
     "Phenylalanine metabolism", ["phenylalanine", "phenyllactate", "phenylpyruvate"], "Phenylalanine"),
]
CONTROL = "No biochemical genetic diagnosis"
TOP_N = 15


def main():
    xls, out = sys.argv[1], sys.argv[2]
    wb = xlrd.open_workbook(xls)
    ws = wb.sheet_by_name("raw z-score data")
    nrow, ncol = ws.nrows, ws.ncols
    # specimen columns 17+, diagnosis in row0
    spec_cols = list(range(17, ncol))
    diag = {c: str(ws.cell_value(0, c)).strip() for c in spec_cols}
    # metabolite rows 2+ : name col0, kegg col11
    import re
    UNNAMED = re.compile(r'^X\s*-\s*\d')  # Metabolon unidentified features → drop (like m/z)
    met = []
    for r in range(2, nrow):
        name = str(ws.cell_value(r, 0)).strip()
        if not name or UNNAMED.match(name):
            continue
        kegg = str(ws.cell_value(r, 11)).strip()
        met.append((r, name, kegg))

    def mean_z(rows_cols):
        pass

    tasks = []
    log = []
    for dsub, tid, enzyme, gold, bmkw, fam in CONFIGS:
        cols = [c for c in spec_cols if dsub.lower() in diag[c].lower() and "carrier" not in diag[c].lower()]
        if not cols:
            log.append(f"{dsub}: 0 specimens"); continue
        diff = []
        for r, name, kegg in met:
            zs = []
            for c in cols:
                v = ws.cell_value(r, c)
                if isinstance(v, (int, float)) and abs(float(v)) < 50:  # cap artifacts
                    zs.append(float(v))
            if not zs:
                continue
            mz = sum(zs) / len(zs)
            diff.append({"name": name, "kegg": kegg, "mean_z": round(mz, 2), "n": len(zs)})
        diff.sort(key=lambda x: -abs(x["mean_z"]))
        bm = next((d for d in diff if any(k in d["name"].lower() for k in bmkw)), None)
        solv = bm is not None and bm["mean_z"] > 2  # z>2 = clinically significant elevation
        tasks.append({
            "task_id": tid, "source": "Miller et al. 2015 Baylor MAPS (PMC4626538) ESM1",
            "perturbation": {"type": "inborn_error", "disease": dsub, "defective_enzyme": enzyme,
                             "organism": "Homo sapiens", "n_specimens": len(cols)},
            "input": {"differential_metabolites": [{"name": d["name"], "mean_z": d["mean_z"]} for d in diff[:TOP_N]]},
            "gold": {"defective_enzyme": enzyme, "perturbed_pathway": gold, "diagnostic_biomarker": bmkw[0],
                     "gold_anchor": "inborn error (non-circular)", "solvability": "PASS" if solv else "WEAK"},
            "pathway_family": fam,
        })
        log.append(f"{dsub}: n={len(cols)} | bm {bm['name'] if bm else 'NA'} z={bm['mean_z'] if bm else 'NA'} "
                   f"-> {'PASS' if solv else 'WEAK'}")

    with open(out, "w") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    for l in log:
        print(l)
    npass = sum(1 for t in tasks if t["gold"]["solvability"] == "PASS")
    print(f"\n{npass}/{len(tasks)} PASS")


if __name__ == "__main__":
    main()
