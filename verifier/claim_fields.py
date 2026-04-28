"""Local typed-field parsing for verifier claims.

This module is intentionally conservative: it extracts first-order fields
that are useful for claim tables and metrics without changing verifier
verdict behaviour. Layers may continue to use their existing text parsers.
"""
from __future__ import annotations

import re

from verifier.schemas import ClaimExtractedFields, ClaimSubtype, ClaimType


_SUBSCRIPT_TRANS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

_FORMULA_RE = re.compile(r"\b(C\d{1,3}H\d{1,3}(?:[A-Z][a-z]?\d{0,3})*)\b")
_MZ_RE = re.compile(r"\bm/z\s*=?\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_PRECURSOR_MZ_RE = re.compile(
    r"\bprecursor\s+m/z\s*[:=]?\s*(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_NEUTRAL_MASS_RE = re.compile(
    r"\bneutral\s+mass(?:\s+\S+){0,4}?\s*[:=]?\s*(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_ADDUCT_RE = re.compile(r"(\[M(?:[+-][A-Za-z0-9]+)+\][+-]?)")
_PMID_RE = re.compile(r"\b(?:PMID|pubmed)[:\s]*(\d{1,9})\b", re.IGNORECASE)
_DOI_RE = re.compile(
    r"\b(?:doi[:\s]*)?(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)",
    re.IGNORECASE,
)
_HMDB_RE = re.compile(r"\b(HMDB\d{6,})\b", re.IGNORECASE)
_KEGG_C_RE = re.compile(r"\b(C\d{5})\b")
_CHEBI_RE = re.compile(r"\bCHEBI[:_-]?(\d+)\b", re.IGNORECASE)
_CID_RE = re.compile(r"\b(?:CID|PubChem\s+CID)[:\s_-]*(\d+)\b", re.IGNORECASE)
_INCHIKEY_RE = re.compile(r"\b([A-Z]{14}-[A-Z]{10}-[A-Z])\b")
_CCMSLIB_RE = re.compile(r"\b(CCMSLIB\d+)\b", re.IGNORECASE)
_SCORE_RE = re.compile(
    r"\b("
    r"evidence[_\s-]*score|candidate[_\s-]*score|B\s*/\s*C|"
    r"predicted[\s-]*spectrum\s+cosine|cosine(?:\s+similarity)?|score"
    r")\b[^\d-]*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_RANK_RE = re.compile(
    r"\b(?:rank(?:ed)?|candidate|top)\s*(?:#|number|no\.?)?\s*(\d+)\b|"
    r"#\s*(\d+)\b",
    re.IGNORECASE,
)
_TOP_CANDIDATE_RE = re.compile(
    r"\b(?:top|highest[-\s]?scoring|best[-\s]?scoring)\s+candidate\b",
    re.IGNORECASE,
)
_PATHWAY_ID_RE = re.compile(
    r"\b(map\d{5}|hsa\d{5}|R-HSA-\d+|SMP\d+|WP\d+)\b",
    re.IGNORECASE,
)
_PATHWAY_NAME_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,4}\s+"
    r"(?:metabolism|biosynthesis|degradation|disease|syndrome|cycle|pathway))\b",
    re.IGNORECASE,
)
_NEUTRAL_LOSS_PATTERNS = (
    re.compile(
        r"(?:neutral\s+)?loss\s+of\s+([A-Za-z0-9₂₃₄.+-]+(?:\s+[A-Za-z]+)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(H2O|H₂O|water|NH3|ammonia|CO2|CO₂|carbon dioxide|CO|carbon monoxide)\b",
        re.IGNORECASE,
    ),
)


def normalize_claim_text(text: str) -> str:
    """Normalize whitespace and unicode subscripts without changing meaning."""
    normalized = text.translate(_SUBSCRIPT_TRANS)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def parse_claim_fields(text: str) -> ClaimExtractedFields:
    """Extract typed fields from claim text using conservative regexes."""
    normalized = normalize_claim_text(text)
    fields = ClaimExtractedFields()

    precursor = _PRECURSOR_MZ_RE.search(normalized)
    if precursor:
        fields.precursor_mz = float(precursor.group(1))

    mz = _MZ_RE.search(normalized)
    if mz:
        parsed_mz = float(mz.group(1))
        fields.mz = parsed_mz
        if fields.precursor_mz is None and _looks_like_precursor_context(normalized, mz.start()):
            fields.precursor_mz = parsed_mz

    formula = _FORMULA_RE.search(normalized)
    if formula:
        fields.formula = formula.group(1)

    neutral_mass = _NEUTRAL_MASS_RE.search(normalized)
    if neutral_mass:
        fields.neutral_mass = float(neutral_mass.group(1))

    adduct = _ADDUCT_RE.search(normalized)
    if adduct:
        fields.adduct = adduct.group(1)

    neutral_loss = _extract_neutral_loss(normalized)
    if neutral_loss:
        fields.neutral_loss = neutral_loss

    pmid = _PMID_RE.search(normalized)
    if pmid:
        fields.pmid = pmid.group(1)

    doi = _DOI_RE.search(normalized)
    if doi:
        fields.doi = doi.group(1).rstrip(".,;:)")

    db_name, db_id = _extract_database_id(normalized)
    if db_id:
        fields.database_name = db_name
        fields.database_id = db_id

    score = _SCORE_RE.search(normalized)
    if score:
        fields.score_name = _normalize_score_name(score.group(1))
        fields.score_value = float(score.group(2))

    rank = _RANK_RE.search(normalized)
    if rank:
        fields.rank = int(next(g for g in rank.groups() if g is not None))
    elif _TOP_CANDIDATE_RE.search(normalized):
        fields.rank = 1

    pathway_id = _PATHWAY_ID_RE.search(normalized)
    if pathway_id:
        fields.pathway_id = pathway_id.group(1)

    pathway_name = _PATHWAY_NAME_RE.search(normalized)
    if pathway_name:
        fields.pathway_name = pathway_name.group(1)

    if fields.mz is not None:
        fields.mz_tolerance_ppm = 5.0

    return fields


def infer_claim_subtype(
    text: str,
    fields: ClaimExtractedFields,
    claim_type: ClaimType | None = None,
) -> ClaimSubtype:
    """Infer a first-pass semantic subtype from parsed fields and route."""
    low = normalize_claim_text(text).lower()

    if fields.pmid:
        return ClaimSubtype.LITERATURE_PMID
    if fields.doi:
        return ClaimSubtype.LITERATURE_DOI
    if fields.database_id:
        return ClaimSubtype.DATABASE_ID
    if fields.neutral_loss:
        return ClaimSubtype.NEUTRAL_LOSS
    if fields.mz is not None and _looks_like_fragment_claim(low):
        return ClaimSubtype.FRAGMENT_ASSIGNMENT
    if "ring cleavage" in low:
        return ClaimSubtype.RING_CLEAVAGE
    if fields.precursor_mz is not None:
        return ClaimSubtype.PRECURSOR_MZ
    if fields.neutral_mass is not None:
        return ClaimSubtype.NEUTRAL_MASS
    if fields.adduct:
        return ClaimSubtype.ADDUCT
    if fields.formula:
        return ClaimSubtype.FORMULA
    if fields.score_name:
        if fields.score_name == "evidence_score":
            return ClaimSubtype.EVIDENCE_SCORE
        if fields.score_name == "candidate_score":
            return ClaimSubtype.CANDIDATE_SCORE
        if fields.score_name == "predicted_cosine":
            return ClaimSubtype.PREDICTED_COSINE
    if fields.rank is not None:
        return ClaimSubtype.RANKING
    if fields.pathway_id or fields.pathway_name:
        return ClaimSubtype.PATHWAY_MEMBERSHIP
    if claim_type == ClaimType.FACTUAL and _looks_like_taxonomy_claim(low):
        return ClaimSubtype.CHEMICAL_TAXONOMY
    if claim_type == ClaimType.BIOLOGICAL:
        return ClaimSubtype.BIOLOGICAL_CONTEXT
    if claim_type == ClaimType.LITERATURE:
        return ClaimSubtype.LITERATURE_FREE_TEXT
    return ClaimSubtype.UNKNOWN


def _looks_like_precursor_context(text: str, mz_start: int) -> bool:
    prefix = text[max(0, mz_start - 24):mz_start].lower()
    return "precursor" in prefix


def _looks_like_fragment_claim(text: str) -> bool:
    return any(
        token in text
        for token in (
            "fragment",
            "fragmentation",
            "peak at",
            "ion",
            "cleavage",
            "scission",
            "loss of",
        )
    )


def _looks_like_taxonomy_claim(text: str) -> bool:
    return any(
        term in text
        for term in (
            "alkaloid",
            "purine",
            "amino acid",
            "monosaccharide",
            "lipid",
            "steroid",
            "flavonoid",
            "terpene",
            "classified as",
            "belongs to",
        )
    )


def _extract_neutral_loss(text: str) -> str | None:
    if "loss" not in text.lower():
        return None
    for pattern in _NEUTRAL_LOSS_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).strip(" .,:;")
    return None


def _extract_database_id(text: str) -> tuple[str | None, str | None]:
    for name, pattern in (
        ("hmdb", _HMDB_RE),
        ("inchikey", _INCHIKEY_RE),
        ("chebi", _CHEBI_RE),
        ("pubchem_cid", _CID_RE),
        ("ccmslib", _CCMSLIB_RE),
        ("kegg", _KEGG_C_RE),
    ):
        m = pattern.search(text)
        if not m:
            continue
        value = m.group(1)
        if name == "chebi" and not value.upper().startswith("CHEBI"):
            value = f"CHEBI:{value}"
        return name, value
    return None, None


def _normalize_score_name(raw: str) -> str:
    value = raw.lower()
    if "evidence" in value:
        return "evidence_score"
    if "cosine" in value:
        return "predicted_cosine"
    if "b" in value and "c" in value or "candidate" in value:
        return "candidate_score"
    return "score"
