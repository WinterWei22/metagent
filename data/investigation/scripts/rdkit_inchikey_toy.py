"""§2.6 RDKit InChIKey reconciler — 30-line toy.

Goal: 验证同一化合物的不同 source SMILES(立体异构 / tautomer / 加合物)
能否在 InChIKey 第一层 14 字符 block 上聚类。

Usage:
    python data/investigation/scripts/rdkit_inchikey_toy.py
"""
from __future__ import annotations

from collections import defaultdict

from rdkit import Chem
from rdkit.Chem import inchi


# 同化合物多 source SMILES 测试集
# (compound, smiles, source_note)
CASES = [
    # Glucose: D-glucose 多 SMILES 表达(开链 vs 环状 vs 不同立体)
    ("D-Glucose",       "OCC(O)C(O)C(O)C(O)C=O",                       "open chain Fischer"),
    ("D-Glucose",       "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",      "alpha cyclic, ChEBI"),
    ("D-Glucose",       "OC[C@H]1OC(O)[C@@H](O)[C@H](O)[C@H]1O",       "beta cyclic, PubChem CID 5793"),
    ("D-Glucose",       "C(C1C(C(C(C(O1)O)O)O)O)O",                    "no stereo, KEGG cpd lookup"),
    # Lactic acid: L / D / racemic
    ("Lactic acid",     "CC(O)C(=O)O",                                 "no stereo (HMDB synonym)"),
    ("Lactic acid",     "C[C@H](O)C(=O)O",                             "L-(+)-lactic, ChEBI"),
    ("Lactic acid",     "C[C@@H](O)C(=O)O",                            "D-(-)-lactic, ChEBI"),
    # Caffeine: tautomers / unambiguous
    ("Caffeine",        "CN1C=NC2=C1C(=O)N(C)C(=O)N2C",                "PubChem CID 2519"),
    ("Caffeine",        "Cn1cnc2c1c(=O)n(C)c(=O)n2C",                  "lowercase aromatic (same)"),
    # Glycine: simplest amino acid
    ("Glycine",         "NCC(=O)O",                                    "no stereo"),
    ("Glycine",         "C(C(=O)O)N",                                  "different atom order"),
    # ATP partial: just for diversity demonstration
    ("Adenine",         "Nc1ncnc2[nH]cnc12",                           "tautomer 1"),
    ("Adenine",         "Nc1ncnc2nc[nH]c12",                           "tautomer 2"),
]


def smi_to_inchikey(smiles: str) -> tuple[str | None, str | None]:
    """Return (full_inchikey, block14) or (None, None) on parse failure."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None, None
    inchi_str = inchi.MolToInchi(mol)
    if not inchi_str:
        return None, None
    ikey = inchi.InchiToInchiKey(inchi_str)
    if not ikey:
        return None, None
    return ikey, ikey.split("-")[0]   # first 14 chars (skeleton hash)


def main() -> None:
    by_block: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    print(f"{'compound':<14} {'block14':<15} {'full InChIKey':<29} note")
    print("-" * 90)
    for compound, smi, note in CASES:
        full, block = smi_to_inchikey(smi)
        if full is None:
            print(f"{compound:<14} {'PARSE_FAIL':<15} {'-':<29} {note}")
            continue
        by_block[block].append((compound, full, note))
        print(f"{compound:<14} {block:<15} {full:<29} {note}")

    print("\n=== Cluster by InChIKey block14 (first 14 chars) ===")
    for block, items in by_block.items():
        compounds_seen = {c for c, _, _ in items}
        n_compounds = len(compounds_seen)
        # If a block14 maps to >1 distinct compound name → false-merge (collision)
        # If multiple SMILES of one compound DON'T share a block14 → false-split
        flag = " ⚠️ COLLISION" if n_compounds > 1 else ""
        print(f"  block={block} n={len(items):<2} compounds={sorted(compounds_seen)}{flag}")

    # 检测 false-split: 同 compound 跨多 block
    by_compound: dict[str, set[str]] = defaultdict(set)
    for compound, smi, note in CASES:
        _, block = smi_to_inchikey(smi)
        if block:
            by_compound[compound].add(block)
    print("\n=== False-split check (same compound → >1 block14) ===")
    for compound, blocks in by_compound.items():
        if len(blocks) > 1:
            print(f"  ⚠️ FALSE-SPLIT  {compound}: {len(blocks)} blocks {sorted(blocks)}")
        else:
            print(f"  ✓ SINGLE-BLOCK {compound}: {next(iter(blocks))}")


if __name__ == "__main__":
    main()
