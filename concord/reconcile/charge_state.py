"""RDKit Uncharger + tautomer canonicalization (W4 Background F).

Standardizes input compounds via:
  - RDKit MolStandardize.charge.Uncharger — strips ionization to neutral form
  - RDKit MolStandardize.tautomer.TautomerEnumerator — picks canonical tautomer

Used by D5 Fig 3 v2 Panel B to upgrade Session 4 "raw" cross-source InChIKey
disagreement(59.1% full / 5.5% block14)to "reconciled" numbers — quantifies
how much disagreement is purely artifact of charge / tautomer choice.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciledStructure:
    original_inchikey: str | None
    reconciled_inchikey: str | None
    reconciled_smiles: str | None
    changed: bool                       # True iff InChIKey shifted
    layers_changed: tuple[str, ...]     # ("charge",) / ("tautomer",) / ("charge", "tautomer")


def _smiles_to_mol(smiles: str):
    from rdkit import Chem
    if not smiles or not isinstance(smiles, str):
        return None
    mol = Chem.MolFromSmiles(smiles.strip())
    return mol


def _mol_to_inchikey(mol) -> str | None:
    if mol is None:
        return None
    from rdkit.Chem import inchi
    try:
        ik = inchi.InchiToInchiKey(inchi.MolToInchi(mol))
        return ik or None
    except Exception:
        return None


def uncharge_compound(smiles: str) -> str | None:
    """Return uncharged canonical SMILES via RDKit MolStandardize.Uncharger.

    Returns None on parse failure. Input already-neutral compound returns
    canonical (possibly identical) SMILES.
    """
    from rdkit import Chem
    from rdkit.Chem.MolStandardize import rdMolStandardize
    mol = _smiles_to_mol(smiles)
    if mol is None:
        return None
    try:
        uncharger = rdMolStandardize.Uncharger()
        unc = uncharger.uncharge(mol)
        return Chem.MolToSmiles(unc) if unc is not None else None
    except Exception as e:
        logger.warning("Uncharger failure on %r: %s", smiles[:60], e)
        return None


def canonicalize_tautomer(smiles: str) -> str | None:
    """Return canonical-tautomer SMILES via TautomerEnumerator."""
    from rdkit import Chem
    from rdkit.Chem.MolStandardize import rdMolStandardize
    mol = _smiles_to_mol(smiles)
    if mol is None:
        return None
    try:
        enum = rdMolStandardize.TautomerEnumerator()
        canon = enum.Canonicalize(mol)
        return Chem.MolToSmiles(canon) if canon is not None else None
    except Exception as e:
        logger.warning("Tautomer canonicalize failure on %r: %s", smiles[:60], e)
        return None


def reconcile_inchikey_layer(
    smiles: str, *, layer: Literal["charge", "tautomer", "both"] = "both",
) -> ReconciledStructure:
    """Apply charge / tautomer standardization to SMILES → re-derive InChIKey.

    Args:
        smiles: input SMILES
        layer: which standardization to apply.

    Returns:
        ReconciledStructure with original / reconciled InChIKeys + diff metadata.
    """
    mol = _smiles_to_mol(smiles)
    if mol is None:
        return ReconciledStructure(
            original_inchikey=None, reconciled_inchikey=None,
            reconciled_smiles=None, changed=False, layers_changed=(),
        )
    orig_ik = _mol_to_inchikey(mol)
    rec_smi = smiles
    layers: list[str] = []
    # InChIKey-based change detection avoids false positives from canonical
    # SMILES rewrites that don't change the underlying chemistry
    if layer in ("charge", "both"):
        unc = uncharge_compound(rec_smi)
        if unc is not None:
            unc_ik = _mol_to_inchikey(_smiles_to_mol(unc))
            pre_ik = _mol_to_inchikey(_smiles_to_mol(rec_smi))
            if unc_ik and pre_ik and unc_ik != pre_ik:
                layers.append("charge")
            rec_smi = unc
    if layer in ("tautomer", "both"):
        tau = canonicalize_tautomer(rec_smi)
        if tau is not None:
            tau_ik = _mol_to_inchikey(_smiles_to_mol(tau))
            pre_ik = _mol_to_inchikey(_smiles_to_mol(rec_smi))
            if tau_ik and pre_ik and tau_ik != pre_ik:
                layers.append("tautomer")
            rec_smi = tau
    rec_mol = _smiles_to_mol(rec_smi) if rec_smi else None
    rec_ik = _mol_to_inchikey(rec_mol)
    return ReconciledStructure(
        original_inchikey=orig_ik, reconciled_inchikey=rec_ik,
        reconciled_smiles=rec_smi,
        changed=(orig_ik != rec_ik and rec_ik is not None),
        layers_changed=tuple(layers),
    )
