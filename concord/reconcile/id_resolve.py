"""Cross-namespace ID → CompoundRef resolver (W4 D2).

Shared abstraction used by sspa / mummichog / RaMP normalizers. Replaces the
W3 hotfix's ad-hoc ``_parse_da_metabolites + _build_metabolites_hit`` pair
inside sspa_norm.py.

Algorithm:
  For each raw_id in input:
    1. ChebiLookup.lookup_by_xref(source_ns, raw_id) → ChEBI compound (hit)
       → CompoundRef(primary_id="CHEBI:...", inchikey from ChEBI sqlite,
                     {ns}_id populated)
    2. Source_ns == "CHEBI": direct ChebiLookup.get_compound(raw_id)
    3. Source_ns == "INCHIKEY": raw_id is the InChIKey itself →
       CompoundRef(primary_id="INCHIKEY:<ik>", inchikey=raw_id,
                   chebi_id=None unless lookup_by_inchikey hits)
    4. Xref miss + ChebiLookup.lookup_by_inchikey for any embedded structure data
       → still no hit? → fallback: CompoundRef(primary_id="<NS>:<raw_id>",
       inchikey="<placeholder>") IFF caller supplied an explicit inchikey-by-id
       fallback dict; else UnresolvedId(reason="inchikey_miss")
    5. Invalid format (empty / whitespace) → UnresolvedId(reason="invalid_format")

Priority(per Q05-NEW-5):chebi → lipidmaps → hmdb → kegg → inchikey
implemented via ``resolve_primary_id``.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from concord.schema.enrichment import (
    COMPOUND_NAMESPACES,
    CompoundRef,
    UnresolvedId,
    resolve_primary_id,
)

logger = logging.getLogger(__name__)

SourceNamespace = Literal["CHEBI", "KEGG", "HMDB", "LIPIDMAPS", "INCHIKEY"]
_KEGG_DRUG_NS = {"KEGG_DRUG", "KEGG_GLYCAN"}  # tolerated synonyms; routed as "KEGG"


def _canonical_ns(ns: str) -> str:
    """Normalize source namespace strings to whitelist values."""
    s = ns.strip().upper()
    if s in _KEGG_DRUG_NS:
        return "KEGG"
    return s


def _build_chebi_ref(
    chebi_rec: Any, raw_id: str, source_ns: str,
) -> CompoundRef | None:
    """Construct CompoundRef from a ChebiLookup CompoundRecord + original
    raw_id metadata for traceability.

    Returns None if chebi_rec lacks InChIKey (v0.3 validator rejects).
    """
    ik = (chebi_rec.inchikey or "").strip()
    if not ik:
        return None

    extras: dict[str, str | None] = {
        "chebi_id": chebi_rec.primary_id,
        "kegg_compound_id": None,
        "hmdb_id": None,
        "lipidmaps_id": None,
        "pubchem_cid": None,
    }
    if source_ns == "KEGG":
        extras["kegg_compound_id"] = f"KEGG:{raw_id}"
    elif source_ns == "HMDB":
        extras["hmdb_id"] = f"HMDB:{raw_id}"
    elif source_ns == "LIPIDMAPS":
        extras["lipidmaps_id"] = f"LIPIDMAPS:{raw_id}"

    primary_id = resolve_primary_id(chebi_id=chebi_rec.primary_id, inchikey=ik)
    return CompoundRef(
        primary_id=primary_id,
        inchikey=ik,
        display_name=chebi_rec.name,
        **extras,
    )


def _build_fallback_ref(
    raw_id: str,
    source_ns: str,
    inchikey: str | None,
) -> CompoundRef | None:
    """Construct CompoundRef when ChebiLookup misses.

    Requires an inchikey (caller-provided or extracted from raw_id). Returns
    None if no inchikey available → caller logs UnresolvedId.
    """
    if not inchikey:
        return None
    ik = inchikey.strip()
    if not ik:
        return None
    if source_ns == "INCHIKEY":
        primary_id = f"INCHIKEY:{ik}"
    elif source_ns in COMPOUND_NAMESPACES:
        primary_id = f"{source_ns}:{raw_id}"
    else:
        # Unknown ns → INCHIKEY fallback
        primary_id = f"INCHIKEY:{ik}"
    extras: dict[str, str | None] = {
        "chebi_id": None, "kegg_compound_id": None, "hmdb_id": None,
        "lipidmaps_id": None, "pubchem_cid": None,
    }
    if source_ns == "KEGG":
        extras["kegg_compound_id"] = f"KEGG:{raw_id}"
    elif source_ns == "HMDB":
        extras["hmdb_id"] = f"HMDB:{raw_id}"
    elif source_ns == "LIPIDMAPS":
        extras["lipidmaps_id"] = f"LIPIDMAPS:{raw_id}"
    return CompoundRef(primary_id=primary_id, inchikey=ik,
                       display_name=raw_id, **extras)


def resolve_ids_to_compound_refs(
    raw_ids: list[str],
    source_namespace: str,
    chebi_lookup: Any,
    *,
    inchikey_by_raw: dict[str, str] | None = None,
) -> tuple[list[CompoundRef], list[UnresolvedId]]:
    """Convert a list of raw external IDs → (resolved CompoundRefs, unresolved IDs).

    Args:
        raw_ids: external IDs in ``source_namespace``. Duplicates deduped.
        source_namespace: one of {"CHEBI", "KEGG", "HMDB", "LIPIDMAPS", "INCHIKEY"}.
            "KEGG_DRUG" / "KEGG_GLYCAN" tolerated and routed as "KEGG".
        chebi_lookup: ChebiLookup instance for cross-namespace lookup.
        inchikey_by_raw: optional map ``{raw_id: known_inchikey}`` used as
            fallback if ChebiLookup misses (e.g., mummichog could provide
            EmpCompound-derived InChIKey).

    Returns:
        (resolved_refs, unresolved_ids) — order in ``raw_ids`` preserved
        (dedup keeps first occurrence). v0.3 validator pre-applied to refs.
    """
    if not raw_ids:
        return [], []

    src = _canonical_ns(source_namespace)
    if src not in COMPOUND_NAMESPACES:
        logger.warning("resolve_ids: source_namespace %r not in whitelist %s",
                       source_namespace, COMPOUND_NAMESPACES)

    seen: set[str] = set()
    resolved: list[CompoundRef] = []
    unresolved: list[UnresolvedId] = []
    inchikey_by_raw = inchikey_by_raw or {}

    for raw in raw_ids:
        if not isinstance(raw, str):
            raw = str(raw)
        rid = raw.strip()
        if not rid:
            unresolved.append(UnresolvedId(raw_id=raw, source_namespace=src,
                                           reason="invalid_format"))
            continue
        if rid in seen:
            continue
        seen.add(rid)

        chebi_rec = None
        if src == "CHEBI":
            chebi_rec = chebi_lookup.get_compound(rid)
        elif src == "INCHIKEY":
            # raw_id is InChIKey itself — try lookup_by_inchikey first
            hits = chebi_lookup.lookup_by_inchikey(rid, use_block14=False)
            chebi_rec = hits[0] if hits else None
        else:
            chebi_rec = chebi_lookup.lookup_by_xref(src, rid)

        # 1. ChEBI hit path
        if chebi_rec is not None:
            ref = _build_chebi_ref(chebi_rec, rid, src)
            if ref is not None:
                resolved.append(ref)
                continue
            # ChEBI hit but no InChIKey (rare) → fall through to fallback

        # 2. Fallback: use caller-provided inchikey or raw==inchikey
        fallback_ik = inchikey_by_raw.get(rid)
        if src == "INCHIKEY" and not fallback_ik:
            fallback_ik = rid
        ref = _build_fallback_ref(rid, src, fallback_ik)
        if ref is not None:
            resolved.append(ref)
            continue

        # 3. No InChIKey anywhere → unresolved
        unresolved.append(UnresolvedId(
            raw_id=rid, source_namespace=src,
            reason="xref_miss" if chebi_rec is None else "inchikey_miss",
        ))

    return resolved, unresolved
