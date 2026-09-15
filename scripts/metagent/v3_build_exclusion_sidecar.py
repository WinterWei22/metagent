"""V3 Part 2 — build the metabolite exclusion sidecar (2A-3).

Re-resolves every benchmark metabolite via the unified structure index
(ChEBI sqlite + metanetx_struct.sqlite + Human-GEM crosswalk + cached online
last-mile), then classifies the still-unresolved residual and writes a sidecar:

    data/benchmark/metagent_bench_v2/excluded_metabolites_easy_v3.json

Two exclusion classes (transparent, reproducible):
    non_single_structure  -- no-xref pseudo-nodes + polymers/complexes/pools +
                             generic glycans. NOT single molecules; excluded
                             from the structure/embedding axis.
    structure_unavailable -- real-but-obscure conjugates with no public
                             structure record; kept out until external data.

This is a deterministic audit; the only network dependency (BiGG names) is read
from the persisted cache `lastmile_cache.json`.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from concord.lookup.chebi import ChebiLookup

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
HUMAN_GEM = ROOT / "data/reference/human_gem_metabolites.tsv"
STRUCT_DB = ROOT / "data/concord/metanetx_struct.sqlite"
COV_DIR = ROOT / "data/metagent/v3_part2_coverage"
LASTMILE = COV_DIR / "lastmile_resolved.json"
CACHE = COV_DIR / "lastmile_cache.json"
OUT = ROOT / "data/benchmark/metagent_bench_v2/excluded_metabolites_easy_v3.json"

XREF = {"metKEGGID": "KEGG", "metHMDBID": "HMDB", "metChEBIID": "CHEBI",
        "metPubChemID": "PUBCHEM", "metLipidMapsID": "LIPIDMAPS",
        "metMetaNetXID": "MNX", "metBiGGID": "BIGG"}

POLY_KW = ["complex", "psyllium", "guar", "gum", "glucan", "pectin", "cellulose",
           "starch", "dextran", "fiber", "heparin", "mucin", "protein",
           "lipoprotein", "ldl", "hdl", "vldl", "chylomicron", "pool"]
GLYCAN_KW = ["ceramide", "cer)", "(gal)", "(glc)", "(glcnac)", "(lfuc)", "nlc",
             "globo", "ganglioside", "-cer", "fucopentaosyl", "lacto-n"]


def stratum_of(tid: str) -> str:
    if "human1" in tid:
        return "human1"
    if "recon2" in tid:
        return "recon22"
    if tid.startswith("sub6"):
        return "sub6_enrich"
    return "hmdb_ramp_membership"


def load_gem():
    gem, bigg_index = {}, {}
    with HUMAN_GEM.open(encoding="utf-8") as fh:
        import csv
        for row in csv.DictReader(fh, delimiter="\t"):
            mam = (row.get("mets") or "").strip()
            base = mam[:-1] if mam[-1:].islower() else mam
            if base in gem:
                continue
            e = {ns: (row.get(c) or "").split(";")[0].strip()
                 for c, ns in XREF.items()
                 if (row.get(c) or "").split(";")[0].strip().lower() not in ("", "na", "nan")}
            gem[base] = e
            if e.get("BIGG"):
                bigg_index.setdefault(e["BIGG"], base)
    return gem, bigg_index


def main() -> int:
    chebi = ChebiLookup()
    struct = sqlite3.connect(f"file:{STRUCT_DB}?mode=ro", uri=True)
    gem, bigg_index = load_gem()
    lastmile = json.loads(LASTMILE.read_text()) if LASTMILE.exists() else {}
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    def bigg_name(bigg: str) -> str:
        t = cache.get(f"bigg::http://bigg.ucsd.edu/api/v2/universal/metabolites/{bigg}")
        if not t:
            return ""
        try:
            return json.loads(t).get("name") or ""
        except Exception:
            return ""

    def cands(mid, idt):
        c = {}
        if idt == "Human1":
            c.update(gem.get(mid, {}))
        elif idt == "Recon2.2":
            c["BIGG"] = mid
            b = bigg_index.get(mid)
            if b:
                c.update({k: v for k, v in gem.get(b, {}).items() if k not in c})
        else:
            c[{"KEGG": "KEGG", "HMDB": "HMDB", "ChEBI": "CHEBI",
               "PubChem": "PUBCHEM"}.get(idt, idt)] = mid
        return c

    def smiles_for_mnx(mnx):
        row = struct.execute(
            "SELECT smiles FROM mnx_structure WHERE mnx_id=?", (mnx,)).fetchone()
        return row[0] if row and row[0] else None

    def xref_to_mnx(ns, ext):
        row = struct.execute(
            "SELECT mnx_id FROM xref_mnx WHERE ns=? AND ext_id=?", (ns, ext)).fetchone()
        return row[0] if row else None

    def resolve(c):
        for ns in ("CHEBI", "KEGG", "HMDB", "PUBCHEM", "LIPIDMAPS"):
            ext = c.get(ns)
            if not ext:
                continue
            try:
                rec = chebi.get_compound(ext) if ns == "CHEBI" else chebi.lookup_by_xref(ns, ext)
            except ValueError:
                rec = None
            if rec and rec.smiles:
                return True
        mnx = c.get("MNX")
        if not mnx:
            for ns in ("BIGG", "KEGG", "HMDB", "LIPIDMAPS"):
                if c.get(ns):
                    mnx = xref_to_mnx(ns, c[ns])
                    if mnx:
                        break
        return bool(mnx and smiles_for_mnx(mnx))

    tasks = [json.loads(l) for l in BENCHMARK.open(encoding="utf-8") if l.strip()]
    seen = {}
    for t in tasks:
        s = stratum_of(t["task_id"])
        for m in t["input"]["differential_metabolites"]:
            key = (s, str(m.get("id_type")), str(m.get("id")))
            seen.setdefault(key, cands(str(m.get("id")), str(m.get("id_type"))))

    excluded = {}
    counts = {"non_single_structure": 0, "structure_unavailable": 0}
    subcat = {}
    for (strat, idt, mid), c in seen.items():
        if resolve(c):
            continue
        if f"{strat}|{idt}|{mid}" in lastmile:
            continue
        name = bigg_name(c.get("BIGG", "")) if c.get("BIGG") else ""
        low = name.lower()
        if not c:
            cls, sub = "non_single_structure", "pseudo_node_no_xref"
        elif name and any(w in low for w in POLY_KW):
            cls, sub = "non_single_structure", "polymer_complex_pool"
        elif name and any(w in low for w in GLYCAN_KW):
            cls, sub = "non_single_structure", "generic_glycan"
        else:
            cls, sub = "structure_unavailable", "obscure_conjugate_or_unnamed"
        excluded[f"{strat}|{idt}|{mid}"] = {
            "stratum": strat, "id_type": idt, "id": mid,
            "name": name, "exclusion_class": cls, "subcategory": sub,
        }
        counts[cls] += 1
        subcat[sub] = subcat.get(sub, 0) + 1

    payload = {
        "_about": "V3 Part2 structure-axis exclusions; see "
                  "docs/decisions/2026-06-23_v3_part2_embedding_method_upgrade.md",
        "_counts": counts,
        "_subcategories": subcat,
        "excluded": excluded,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print("exclusion counts:", counts)
    print("subcategories:", subcat)
    print(f"total excluded entries = {len(excluded)}")
    print(f"  non_single_structure = {counts['non_single_structure']} (excluded from structure axis)")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
