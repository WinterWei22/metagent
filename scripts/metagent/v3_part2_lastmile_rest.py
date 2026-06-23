"""V3 Part 2 — last-mile online resolution of residual-B metabolites.

Input: /tmp/residual_B.json (list of {key:[stratum,id_type,id], cands:{ns:ext}}).
For each residual metabolite, chase a SMILES via cached REST calls:
  1. PubChem CID            -> CanonicalSMILES
  2. BiGG Models metabolite -> database_links (InChIKey / CHEBI / KEGG)
       -> InChIKey -> PubChem CanonicalSMILES
       -> new CHEBI -> local ChEBI SMILES
       -> KEGG -> KEGG MOL -> RDKit SMILES
  3. KEGG (direct)          -> KEGG MOL -> RDKit SMILES

All REST responses cached to a JSON file so re-runs are free. Polite delay
between live calls. Writes a resolved map + prints newly-closed count.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from rdkit import Chem
from rdkit import RDLogger

from concord.lookup.chebi import ChebiLookup

RDLogger.DisableLog("rdApp.*")

ROOT = Path(__file__).resolve().parents[2]
RESIDUAL = Path("/tmp/residual_B.json")
OUT_DIR = ROOT / "data/metagent/v3_part2_coverage"
CACHE = OUT_DIR / "lastmile_cache.json"
RESOLVED = OUT_DIR / "lastmile_resolved.json"
CHEM_PROP = ROOT / "data/concord/metanetx_cache/chem_prop_full.tsv"


def build_block14_index(needed_block14: set[str]) -> dict[str, str]:
    """inchikey block14 -> SMILES from full chem_prop (col7=inchikey, col8=smiles)."""
    idx: dict[str, str] = {}
    with CHEM_PROP.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 9:
                continue
            ik, smi = p[7].strip(), p[8].strip()
            if not ik or not smi:
                continue
            blk = ik.split("-")[0]
            if blk in needed_block14 and blk not in idx:
                idx[blk] = smi
    return idx

UA = {"User-Agent": "curl/7"}


def load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    return {}


_cache = load_cache()


def _get(url: str, *, kind: str) -> str | None:
    """Cached GET returning text, or None on failure. `kind` namespaces cache."""
    ck = f"{kind}::{url}"
    if ck in _cache:
        v = _cache[ck]
        return v if v else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            text = r.read().decode("utf-8", "replace")
        _cache[ck] = text
        time.sleep(0.2)
    except Exception:
        _cache[ck] = ""
        text = None
        time.sleep(0.1)
    return text or None


def pubchem_cid_smiles(cid: str) -> str | None:
    t = _get(
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}"
        f"/property/CanonicalSMILES/TXT",
        kind="pc_cid",
    )
    return t.strip().splitlines()[0] if t and t.strip() else None


def pubchem_ik_smiles(ik: str) -> str | None:
    t = _get(
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/inchikey/{ik}"
        f"/property/CanonicalSMILES/TXT",
        kind="pc_ik",
    )
    return t.strip().splitlines()[0] if t and t.strip() else None


def kegg_mol_smiles(kid: str) -> str | None:
    kid = kid.split(":")[-1]
    t = _get(f"https://rest.kegg.jp/get/cpd:{kid}/mol", kind="kegg_mol")
    if not t or "M  END" not in t:
        return None
    try:
        mol = Chem.MolFromMolBlock(t)
        return Chem.MolToSmiles(mol) if mol else None
    except Exception:
        return None


def bigg_links(bigg: str) -> dict:
    t = _get(
        f"http://bigg.ucsd.edu/api/v2/universal/metabolites/{bigg}",
        kind="bigg",
    )
    if not t:
        return {}
    try:
        d = json.loads(t)
    except Exception:
        return {}
    out = {}
    for k, v in (d.get("database_links") or {}).items():
        if v:
            out[k] = v[0].get("id")
    return out


def main() -> int:
    chebi = ChebiLookup()
    items = json.loads(RESIDUAL.read_text())
    resolved: dict[str, str] = {}
    by_path = {"pubchem_cid": 0, "bigg_inchikey": 0, "bigg_chebi": 0,
               "bigg_kegg": 0, "kegg_direct": 0, "bigg_block14": 0}

    # pre-fetch all BiGG links (cached) and collect needed block14 keys
    bigg_ik: dict[str, str] = {}
    needed_block14: set[str] = set()
    for it in items:
        bigg = it["cands"].get("BIGG")
        if bigg:
            links = bigg_links(bigg)
            ik = links.get("InChI Key")
            if ik:
                bigg_ik[bigg] = ik
                needed_block14.add(ik.split("-")[0])
    block14_smiles = build_block14_index(needed_block14)

    for it in items:
        key = "|".join(it["key"])
        c = it["cands"]
        smiles = None

        if c.get("PUBCHEM"):
            smiles = pubchem_cid_smiles(c["PUBCHEM"])
            if smiles:
                by_path["pubchem_cid"] += 1

        if not smiles and c.get("BIGG"):
            links = bigg_links(c["BIGG"])
            ik = links.get("InChI Key")
            if ik:
                smiles = pubchem_ik_smiles(ik)
                if smiles:
                    by_path["bigg_inchikey"] += 1
                if not smiles and ik.split("-")[0] in block14_smiles:
                    smiles = block14_smiles[ik.split("-")[0]]
                    by_path["bigg_block14"] += 1
            if not smiles and links.get("CHEBI"):
                try:
                    rec = chebi.get_compound(links["CHEBI"])
                    if rec and rec.smiles:
                        smiles = rec.smiles
                        by_path["bigg_chebi"] += 1
                except Exception:
                    pass
            if not smiles and links.get("KEGG Compound"):
                smiles = kegg_mol_smiles(links["KEGG Compound"])
                if smiles:
                    by_path["bigg_kegg"] += 1

        if not smiles and c.get("KEGG"):
            smiles = kegg_mol_smiles(c["KEGG"])
            if smiles:
                by_path["kegg_direct"] += 1

        if smiles:
            resolved[key] = smiles

    CACHE.write_text(json.dumps(_cache))
    RESOLVED.write_text(json.dumps(resolved, indent=2))

    n = len(items)
    print(f"residual B = {n}")
    print(f"newly resolved online = {len(resolved)} ({100*len(resolved)/n:.0f}%)")
    print("by path:", by_path)
    print(f"still unresolved = {n - len(resolved)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
