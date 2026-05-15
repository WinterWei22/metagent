"""RDKit InChIKey reconciler(W3 D5).

API:
    compute_inchikey(smiles_or_inchi)
        → "BLOCK14-STEREOLAYER-CHARGEFLAG" or None

    cluster_by_block14(compound_refs)
        → {block14: [CompoundRef, ...]}  group by connectivity hash

    detect_charge_stereo_conflict(refs)
        → ConflictReport with conflict_type ∈ {charge,stereo,tautomer,none}

Q-04 end-to-end story:
    α/β-D-glucopyranose InChIKey block14 differ from open-chain Fischer
    glucose SMILES. **Reconciliation 不仅靠 block14**;还要走 ChEBI is_a
    hierarchy(via ChebiLookup.climb_to_canonical)找共同 ancestor。
    本模块的 reconcile_with_chebi() 把两条路径串起来。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

ConflictType = Literal["none", "charge", "stereo", "tautomer", "connectivity"]


@dataclass(frozen=True)
class ConflictReport:
    """Diff between InChIKey variants for ostensibly-same compound."""
    conflict_type: ConflictType
    n_distinct_block14: int
    n_distinct_full: int
    block14s: tuple[str, ...] = ()
    full_inchikeys: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconcileResult:
    """High-level reconciliation: do these refs represent the same compound?"""
    is_same_compound: bool
    canonical_chebi_id: str | None     # the ChEBI ancestor all refs converge on
    method: Literal["block14", "chebi_is_a", "both", "none"]
    n_refs: int
    note: str = ""


# ---------------------------------------------------------------------------
# compute_inchikey
# ---------------------------------------------------------------------------


def compute_inchikey(smiles_or_inchi: str) -> str | None:
    """RDKit-derived full 27-char InChIKey from SMILES or InChI input.

    Returns None on parse failure(silently — Q-04 false-split research path).
    """
    if not smiles_or_inchi or not isinstance(smiles_or_inchi, str):
        return None
    s = smiles_or_inchi.strip()
    if not s:
        return None
    try:
        from rdkit import Chem
        from rdkit.Chem import inchi
    except ImportError:  # pragma: no cover
        logger.warning("RDKit not available")
        return None

    mol = None
    if s.upper().startswith("INCHI="):
        mol = Chem.MolFromInchi(s)
    else:
        mol = Chem.MolFromSmiles(s)
    if mol is None:
        return None
    try:
        inchi_str = inchi.MolToInchi(mol)
        if not inchi_str:
            return None
        ikey = inchi.InchiToInchiKey(inchi_str)
        return ikey or None
    except Exception:  # pragma: no cover
        return None


def block14(inchikey: str) -> str:
    """Return first 14 chars(connectivity hash);empty string on bad input."""
    if not inchikey or not isinstance(inchikey, str):
        return ""
    return inchikey.split("-")[0]


# ---------------------------------------------------------------------------
# cluster_by_block14
# ---------------------------------------------------------------------------


def _get_inchikey(ref: Any) -> str | None:
    """Extract InChIKey from CompoundRef / CompoundRecord / dict / raw str."""
    if ref is None:
        return None
    if isinstance(ref, str):
        return ref or None
    return getattr(ref, "inchikey", None) or None


def cluster_by_block14(refs: list[Any]) -> dict[str, list[Any]]:
    """Group refs by InChIKey block14(connectivity hash).

    Refs without InChIKey go into key ``""``。
    """
    out: dict[str, list[Any]] = {}
    for ref in refs:
        ik = _get_inchikey(ref)
        b14 = block14(ik) if ik else ""
        out.setdefault(b14, []).append(ref)
    return out


# ---------------------------------------------------------------------------
# detect_charge_stereo_conflict
# ---------------------------------------------------------------------------


def detect_charge_stereo_conflict(refs: list[Any]) -> ConflictReport:
    """Classify the kind of InChIKey disagreement among refs.

    InChIKey layout:  ``AAAAAAAAAAAAAA-BBBBBBBBBB-X``
        block14  = connectivity (skeleton hash)
        layer2   = stereo + isotope (10 chars)
        layer3   = charge / protonation flag (1 char: N=neutral, M=anion, P=cation)

    Returns ConflictReport.conflict_type:
        "none"         all InChIKeys identical
        "connectivity" different block14
        "charge"       same block14 + layer2, differ at layer3
        "stereo"       same block14, differ at layer2(stereo layer)
        "tautomer"     same block14 + layer3, differ at layer2 with specific markers
                       (Sprint W4 refines tautomer detection;currently lumped into "stereo")
    """
    iks = [_get_inchikey(r) for r in refs]
    iks_clean = [ik for ik in iks if ik]
    if len(iks_clean) <= 1:
        return ConflictReport(
            conflict_type="none",
            n_distinct_block14=len(set(block14(ik) for ik in iks_clean)),
            n_distinct_full=len(set(iks_clean)),
            block14s=tuple(set(block14(ik) for ik in iks_clean)),
            full_inchikeys=tuple(set(iks_clean)),
        )

    full_set = set(iks_clean)
    block14s = {block14(ik) for ik in iks_clean}
    if len(full_set) == 1:
        return ConflictReport(
            conflict_type="none",
            n_distinct_block14=1,
            n_distinct_full=1,
            block14s=tuple(block14s),
            full_inchikeys=tuple(full_set),
        )
    if len(block14s) > 1:
        return ConflictReport(
            conflict_type="connectivity",
            n_distinct_block14=len(block14s),
            n_distinct_full=len(full_set),
            block14s=tuple(sorted(block14s)),
            full_inchikeys=tuple(sorted(full_set)),
        )

    # Same block14, different full → must differ at layer 2 or layer 3.
    def _split3(ik: str) -> tuple[str, str, str]:
        parts = ik.split("-")
        if len(parts) >= 3:
            return parts[0], parts[1], parts[2]
        return ik, "", ""

    layer2_set = {_split3(ik)[1] for ik in iks_clean}
    layer3_set = {_split3(ik)[2] for ik in iks_clean}

    if len(layer2_set) == 1 and len(layer3_set) > 1:
        conflict_type = "charge"
    elif len(layer2_set) > 1 and len(layer3_set) == 1:
        conflict_type = "stereo"
    else:
        conflict_type = "stereo"  # both layers differ → lump under stereo for W3

    return ConflictReport(
        conflict_type=conflict_type,
        n_distinct_block14=1,
        n_distinct_full=len(full_set),
        block14s=tuple(block14s),
        full_inchikeys=tuple(sorted(full_set)),
        details={
            "layer2_distinct": sorted(layer2_set),
            "layer3_distinct": sorted(layer3_set),
        },
    )


# ---------------------------------------------------------------------------
# reconcile_with_chebi — Q-04 fix:integrate ChEBI is_a 上爬
# ---------------------------------------------------------------------------


def reconcile_with_chebi(
    refs: list[Any],
    chebi_lookup: Any,
    *,
    max_depth: int = 3,
) -> ReconcileResult:
    """Decide whether `refs` represent the same compound.

    Strategy(Q-04 fix):
      1. Cluster by block14 — same block14 → likely same compound, return is_same=True
      2. If different block14, walk each ref's ChEBI ancestors via
         ``chebi_lookup.climb_to_canonical(chebi_id, max_depth=max_depth)``
         and check for ≥1 common ancestor → if yes, return is_same=True with that
         common ancestor as canonical
      3. Otherwise → is_same=False

    Args:
        refs: list of CompoundRecord or CompoundRef-like
              (must expose `chebi_id` or `primary_id` attribute and `inchikey`)
        chebi_lookup: ChebiLookup instance(for `climb_to_canonical` and `get_compound`)

    Returns ReconcileResult.
    """
    if len(refs) <= 1:
        return ReconcileResult(
            is_same_compound=True,
            canonical_chebi_id=getattr(refs[0], "chebi_id", None) if refs else None,
            method="none",
            n_refs=len(refs),
            note="single or empty input — trivially same",
        )

    # Step 1: block14 cluster
    by_block = cluster_by_block14(refs)
    block14s_non_empty = [b for b in by_block if b]
    if len(block14s_non_empty) == 1:
        # All refs share connectivity hash → same compound
        canon = getattr(refs[0], "chebi_id", None)
        return ReconcileResult(
            is_same_compound=True,
            canonical_chebi_id=canon,
            method="block14",
            n_refs=len(refs),
            note=f"all {len(refs)} refs share block14={block14s_non_empty[0]}",
        )

    # Step 2: walk ChEBI is_a ancestors
    ref_chebis: list[str] = []
    for r in refs:
        cid = getattr(r, "chebi_id", None)
        if cid:
            ref_chebis.append(str(cid).replace("CHEBI:", ""))

    if len(ref_chebis) < 2:
        return ReconcileResult(
            is_same_compound=False,
            canonical_chebi_id=None,
            method="none",
            n_refs=len(refs),
            note=f"different block14 ({len(block14s_non_empty)} clusters) + "
                 f"insufficient ChEBI IDs ({len(ref_chebis)}/{len(refs)}) for is_a climb",
        )

    chains: list[set[str]] = []
    for cid in ref_chebis:
        ancestors = set(chebi_lookup.climb_to_canonical(cid, max_depth=max_depth))
        ancestors.add(cid)
        chains.append(ancestors)
    common = set.intersection(*chains) if chains else set()
    if common:
        # Pick the "deepest" common ancestor (the one closest to all refs)
        # For Q-04 sugar case: D-glucopyranose (4167) is shared depth-1 by α/β
        # but for α-D-glucopyranose vs Fischer-form open-chain glucose, common
        # ancestor at depth 2-3 = D-glucose / glucose
        canon = sorted(common, key=lambda x: int(x) if x.isdigit() else 1e9)[0]
        return ReconcileResult(
            is_same_compound=True,
            canonical_chebi_id=canon,
            method="chebi_is_a",
            n_refs=len(refs),
            note=f"different block14 but share ChEBI ancestor {canon} via is_a "
                 f"(max_depth={max_depth})",
        )

    return ReconcileResult(
        is_same_compound=False,
        canonical_chebi_id=None,
        method="none",
        n_refs=len(refs),
        note=f"different block14 ({len(block14s_non_empty)} clusters) + "
             f"no common ChEBI ancestor within depth={max_depth}",
    )
