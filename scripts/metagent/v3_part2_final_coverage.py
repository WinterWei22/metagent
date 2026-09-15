"""V3 Part 2 — FINAL structure coverage after adding full MetaNetX chem_prop.

Resolver chain (all offline now that chem_prop is downloaded):
  local ChEBI (all-namespace xref + direct)  ->
  local MetaNetX sqlite (MNX direct inchikey/chebi)  ->
  full chem_xref BiGG/KEGG/HMDB -> MNX  ->
  full chem_prop MNX -> SMILES

Reports final A (resolved SMILES) / B (xref but no structure) / C (no xref)
per stratum. C = true GEM pseudo-metabolites.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from concord.lookup.chebi import ChebiLookup

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
HUMAN_GEM = ROOT / "data/reference/human_gem_metabolites.tsv"
CHEM_PROP = ROOT / "data/concord/metanetx_cache/chem_prop_full.tsv"
CHEM_XREF = Path(
    "/home/weiwentao/workspace/llm_agent_metabolomics/"
    "metagent_day1_v5_investigation/data/investigation/metanetx_cache/chem_xref.tsv"
)
OUT_MD = ROOT / "reports/reports_v2/2026-06-23_v3_part2_final_coverage.md"

XREF = {"metKEGGID": "KEGG", "metHMDBID": "HMDB", "metChEBIID": "CHEBI",
        "metPubChemID": "PUBCHEM", "metLipidMapsID": "LIPIDMAPS",
        "metMetaNetXID": "MNX", "metBiGGID": "BIGG"}


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
    gem, bigg_index = load_gem()

    with BENCHMARK.open(encoding="utf-8") as fh:
        tasks = [json.loads(line) for line in fh if line.strip()]

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

    # collect distinct metabolites + their candidate xrefs
    seen = {}
    for task in tasks:
        strat = stratum_of(task["task_id"])
        for met in task["input"]["differential_metabolites"]:
            key = (strat, str(met.get("id_type")), str(met.get("id")))
            if key not in seen:
                seen[key] = cands(str(met.get("id")), str(met.get("id_type")))

    # gather needed BiGG/KEGG/HMDB and MNX
    need_xref = defaultdict(set)  # ns -> ext ids
    need_mnx = set()
    for c in seen.values():
        for ns in ("BIGG", "KEGG", "HMDB", "LIPIDMAPS"):
            if c.get(ns):
                need_xref[ns].add(c[ns])
        if c.get("MNX"):
            need_mnx.add(c["MNX"])

    # full chem_xref: {ns}:{ext} -> MNX  (for needed)
    xref2mnx = {}
    pfx_map = {"biggm": "BIGG", "bigg.metabolite": "BIGG", "keggc": "KEGG",
               "kegg.compound": "KEGG", "hmdb": "HMDB", "lipidmaps": "LIPIDMAPS"}
    with CHEM_XREF.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 2 or ":" not in p[0]:
                continue
            pfx, ext = p[0].split(":", 1)
            ns = pfx_map.get(pfx.lower())
            if ns and ext in need_xref.get(ns, ()):
                xref2mnx.setdefault((ns, ext), p[1])
    for (ns, ext), m in xref2mnx.items():
        need_mnx.add(m)

    # full chem_prop: MNX -> SMILES (for needed)
    mnx2smiles = {}
    with CHEM_PROP.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 9:
                continue
            if p[0] in need_mnx and p[8].strip():
                mnx2smiles[p[0]] = p[8].strip()

    def local_smiles(c):
        for ns in ("CHEBI", "KEGG", "HMDB", "PUBCHEM", "LIPIDMAPS"):
            ext = c.get(ns)
            if not ext:
                continue
            try:
                rec = chebi.get_compound(ext) if ns == "CHEBI" else chebi.lookup_by_xref(ns, ext)
            except ValueError:
                rec = None
            if rec and rec.smiles:
                return rec.smiles
        return None

    def resolve(c):
        s = local_smiles(c)
        if s:
            return s
        # MNX direct or via xref bridge -> chem_prop
        mnx = c.get("MNX")
        if not mnx:
            for ns in ("BIGG", "KEGG", "HMDB", "LIPIDMAPS"):
                if c.get(ns) and (ns, c[ns]) in xref2mnx:
                    mnx = xref2mnx[(ns, c[ns])]
                    break
        if mnx and mnx in mnx2smiles:
            return mnx2smiles[mnx]
        return None

    # online last-mile results (PubChem/KEGG/BiGG REST), keyed "strat|id_type|id"
    lastmile_path = ROOT / "data/metagent/v3_part2_coverage/lastmile_resolved.json"
    lastmile = json.loads(lastmile_path.read_text()) if lastmile_path.exists() else {}

    buckets = defaultdict(lambda: {"n": 0, "A": 0, "A_online": 0, "B": 0, "C": 0})
    for (strat, idt, mid), c in seen.items():
        b = buckets[strat]
        b["n"] += 1
        if resolve(c):
            b["A"] += 1
        elif f"{strat}|{idt}|{mid}" in lastmile:
            b["A"] += 1
            b["A_online"] += 1
        elif c:
            b["B"] += 1
        else:
            b["C"] += 1

    def pct(a, n):
        return f"{100*a/n:.1f}%" if n else "n/a"

    lines = [
        "# V3 Part 2 — FINAL structure coverage (post full chem_prop)",
        "",
        "- Date: `2026-06-23` | offline resolver = ChEBI + MetaNetX sqlite +"
        " full chem_xref (BiGG/KEGG/HMDB->MNX) + full chem_prop (MNX->SMILES).",
        "- A = SMILES resolved; B = has xref, still no structure; C = no xref"
        " (true GEM pseudo-metabolite).",
        "",
        "| stratum | distinct | A 已解析 | B 仍缺 | C 占位符 |",
        "|---|---:|---:|---:|---:|",
    ]
    tot = {"n": 0, "A": 0, "B": 0, "C": 0}
    for strat in ("sub6_enrich", "hmdb_ramp_membership", "human1", "recon22"):
        b = buckets[strat]
        for k in tot:
            tot[k] += b[k]
        lines.append(f"| {strat} | {b['n']} | {pct(b['A'],b['n'])} | "
                     f"{pct(b['B'],b['n'])} | {b['C']} ({pct(b['C'],b['n'])}) |")
    lines.append(f"| **TOTAL** | {tot['n']} | **{pct(tot['A'],tot['n'])}** | "
                 f"{pct(tot['B'],tot['n'])} | {tot['C']} ({pct(tot['C'],tot['n'])}) |")
    text = "\n".join(lines) + "\n"
    OUT_MD.write_text(text, encoding="utf-8")
    print(text)
    print(f"Wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
