"""V3 Part 2 — closure test using full MetaNetX chem_prop (MNX -> SMILES).

After downloading the full chem_prop.tsv, measure how much of the human1/recon22
gap closes via: {our id} -> MNX (direct, or BiGG->MNX via local full chem_xref)
-> SMILES from full chem_prop. This is the decisive "can we hit ~95%" number.
"""
from __future__ import annotations

import csv
from pathlib import Path

from concord.lookup.chebi import ChebiLookup

ROOT = Path(__file__).resolve().parents[2]
CHEM_PROP = ROOT / "data/concord/metanetx_cache/chem_prop_full.tsv"
CHEM_XREF = Path(
    "/home/weiwentao/workspace/llm_agent_metabolomics/"
    "metagent_day1_v5_investigation/data/investigation/metanetx_cache/chem_xref.tsv"
)
HUMAN_GEM = ROOT / "data/reference/human_gem_metabolites.tsv"
UNRESOLVED = ROOT / "data/metagent/v3_part2_coverage/unresolved.csv"

XREF = {"metKEGGID": "KEGG", "metHMDBID": "HMDB", "metChEBIID": "CHEBI",
        "metPubChemID": "PUBCHEM", "metLipidMapsID": "LIPIDMAPS",
        "metMetaNetXID": "MNX", "metBiGGID": "BIGG"}


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
    gem, bigg_index = load_gem()

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

    rows = [r for r in csv.DictReader(UNRESOLVED.open())
            if r["stratum"] in ("human1", "recon22")]
    item_c = {(r["id"], r["id_type"]): cands(r["id"], r["id_type"]) for r in rows}
    need_bigg = {c["BIGG"] for c in item_c.values() if c.get("BIGG")}
    need_mnx = {c["MNX"] for c in item_c.values() if c.get("MNX")}

    # BiGG -> MNX from local full chem_xref
    bigg2mnx = {}
    with CHEM_XREF.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 2 or ":" not in p[0]:
                continue
            pfx, ext = p[0].split(":", 1)
            if pfx.lower() in ("biggm", "bigg.metabolite") and ext in need_bigg:
                bigg2mnx.setdefault(ext, p[1])

    all_mnx = set(need_mnx) | set(bigg2mnx.values())

    # MNX -> SMILES from full chem_prop (col 8)
    mnx2smiles = {}
    with CHEM_PROP.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 9:
                continue
            if p[0] in all_mnx and p[8].strip():
                mnx2smiles[p[0]] = p[8].strip()

    closed = 0
    for k, c in item_c.items():
        m = c.get("MNX") or (bigg2mnx.get(c["BIGG"]) if c.get("BIGG") else None)
        if m and m in mnx2smiles:
            closed += 1

    n = len(item_c)
    # combine with the already-resolved A bucket for headline strata coverage
    print(f"human1+recon22 previously-unresolved = {n}")
    print(f"  BiGG->MNX mapped     = {len(bigg2mnx)}/{len(need_bigg)}")
    print(f"  MNX->SMILES in chem_prop = {len(mnx2smiles)}/{len(all_mnx)}")
    print(f"  NEWLY closed via full chem_prop = {closed} ({100*closed/n:.0f}% of gap)")
    print()
    # headline: prior A-bucket counts from coverage_by_stratum baseline + max probe
    print("Combined structure coverage (A_offline 65.7%/65.3% + these):")
    print(f"  human1+recon22 gap of {n} -> {closed} closed -> residual {n-closed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
