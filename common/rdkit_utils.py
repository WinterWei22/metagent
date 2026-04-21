"""Shared RDKit helpers used by tools handling SMILES.

Kept minimal on purpose. If a helper is used by only one tool, it stays inside
that tool's package. Only genuinely cross-tool utilities live here.
"""
from __future__ import annotations


def is_valid_smiles(smiles: str) -> bool:
    """Return True iff RDKit parses the SMILES without error."""
    from rdkit import Chem

    if not smiles:
        return False
    try:
        mol = Chem.MolFromSmiles(smiles, sanitize=True)
        return mol is not None
    except Exception:
        return False


def canonicalize_smiles(smiles: str) -> str | None:
    """Return RDKit canonical SMILES, or None if unparseable."""
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return Chem.MolToSmiles(mol)


def molecular_formula(smiles: str) -> str | None:
    """Return the Hill-system molecular formula, or None if unparseable."""
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return rdMolDescriptors.CalcMolFormula(mol)


def inchikey(smiles: str) -> str | None:
    """Return the InChIKey for a SMILES, or None if unparseable."""
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return Chem.MolToInchiKey(mol)


def filter_valid_smiles(smiles_list: list[str]) -> list[str]:
    """Return only SMILES that parse. Order preserved, duplicates kept.

    Used by molecule_generate and predict_spectrum to ensure the LLM never sees
    an unparseable candidate.
    """
    return [s for s in smiles_list if is_valid_smiles(s)]
