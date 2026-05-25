"""Layer factual_sub6 — verify Type FACTUAL / GROUNDED metabolite-ID claims on Sub-6 tasks.

Background (W12 C7 sprint, 2026-05-23):
B1 D2's Layer A (grounded.py) and Layer B (factual.py) read
``IdentificationReport.candidates[*].metabolite_info.cross_refs``, which
is the spectrum-centric shape. Sub-6's ``SubsixSourceReport`` carries
``differential_metabolites`` instead — a flat list of compound dicts
with ``kegg_id`` / ``hmdb_id`` / ``chebi_id`` / ``inchikey`` /
``inchikey_first_block`` / ``name``. Without a Sub-6 friendly layer,
``verifier.agent._verify_per_claim_sub6`` routes FACTUAL / GROUNDED
claims through its fall-through bucket (line 658-685), producing an
``UNVERIFIABLE_V0`` verdict that is informationally empty.

W11 UV diagnosis attributed 181/226 (80.1 %) of C7 namespace_form
claims to this fall-through. This layer is the Sub-6 friendly
counterpart B1's Layer A/B cannot be, scoped to the W12 sprint:

  Data sources allowed:
    1. SubsixSourceReport.differential_metabolites[*]
    2. data/benchmark/sub6/curated_hmdb_mammalian.jsonl (lazy module cache)

  Data sources disallowed for this sprint:
    - External RaMP DB lookup (engineering doubles, triggers
      verifier-modify-warning unnecessarily)

Verdict policy:

* Subject metabolite resolves in source pool + claimed ID matches the
  metabolite's matching field → ``SUPPORTED``
* Subject metabolite resolves + claimed ID differs from field
  → ``CONTRADICTED`` (``correction`` populated)
* Subject metabolite does not resolve in any pool → ``UNVERIFIABLE_V0``
* No identifier extractable from ``claim_text`` → ``UNVERIFIABLE_V0``

Wired in via verifier/agent.py:_verify_per_claim_sub6 in the D4 commit
(⚠️-modify); this commit is pure-add and does not change dispatcher.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from schemas.sub6_report import SubsixSourceReport
from verifier.schemas import (
    ClaimVerdict,
    ClassifiedClaim,
    VerifiedClaim,
)


_CURATED_PATH = Path("data/benchmark/sub6/curated_hmdb_mammalian.jsonl")

# Identifier extraction patterns. Order matters: more specific first.
# All case-insensitive on the keyword; the captured ID is normalised on
# comparison so we accept the various surface forms ConcordMet emits
# (e.g. "KEGG ID C00082", "KEGG:C00082", "kegg id c00082").
_ID_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # InChIKey: 14-char block optionally followed by -10char-1char tail
    ("inchikey", re.compile(
        r"\b(?:InChIKey|InChi[Kk]ey|inchikey)\s*[:=]?\s*"
        r"([A-Z]{14}(?:-[A-Z]{10}-[A-Z])?)\b"
    )),
    # ChEBI: optional CHEBI: prefix
    ("chebi_id", re.compile(
        r"\b(?:CHEBI|ChEBI)(?:\s+ID)?\s*[:=]?\s*"
        r"(CHEBI:?\d+|\d+)\b",
        re.IGNORECASE,
    )),
    # HMDB
    ("hmdb_id", re.compile(
        r"\b(?:HMDB(?:\s+ID)?)\s*[:=]?\s*(HMDB\d+)\b",
        re.IGNORECASE,
    )),
    # KEGG compound (C-prefix five-digit, common LLM surface form)
    ("kegg_id", re.compile(
        r"\b(?:KEGG(?:\s+ID)?|KEGG\s+compound)\s*[:=]?\s*(C\d{5})\b",
        re.IGNORECASE,
    )),
    # -----------------------------------------------------------------
    # W13.A — extended surface forms (append-only; do not reorder above)
    # -----------------------------------------------------------------
    # KEGG drug D-prefix (e.g. "KEGG ID D00188" for pantothenate)
    ("kegg_id", re.compile(
        r"\b(?:KEGG(?:\s+ID)?|KEGG\s+compound|KEGG\s+drug)\s*[:=]?\s*(D\d{5})\b",
        re.IGNORECASE,
    )),
    # Bare KEGG-style ID in parentheses ("L-tyrosine (C00082)")
    # The leading '(' acts as the boundary so we don't match arbitrary
    # 'C12345' inside running text. Accept C- and D-prefix.
    ("kegg_id", re.compile(r"\(([CD]\d{5})\)")),
    # PubChem CID — "PubChem CID 6057" with the full keyword
    ("pubchem_cid", re.compile(
        r"\bPubChem\s*CID:?\s*(\d{1,9})\b",
        re.IGNORECASE,
    )),
    # PubChem CID — bare "CID 6057" with just CID keyword
    ("pubchem_cid", re.compile(
        r"\bCID:?\s*(\d{1,9})\b",
    )),
    # PubChem CID — URL form
    # "pubchem.ncbi.nlm.nih.gov/compound/6057" with or without scheme
    ("pubchem_cid", re.compile(
        r"pubchem\.ncbi\.nlm\.nih\.gov/compound/(\d+)",
        re.IGNORECASE,
    )),
    # ChEBI with underscore separator: "CHEBI_17895"
    ("chebi_id", re.compile(
        r"\bCHEBI_(\d+)\b",
        re.IGNORECASE,
    )),
    # ChEBI IRI form: "http://purl.obolibrary.org/obo/CHEBI_17895"
    ("chebi_id", re.compile(
        r"obo/CHEBI_(\d+)",
        re.IGNORECASE,
    )),
    # -----------------------------------------------------------------
    # Bare InChIKey 14-block at end of claim (fallback for "X has InChIKey Y" where
    # the keyword form already matched above; this is only reached if no other id
    # found). Must come last.
    ("inchikey_short", re.compile(r"(?<![A-Za-z0-9])([A-Z]{14})(?![A-Za-z0-9])")),
)


def _extract_id(claim_text: str) -> tuple[str | None, str | None]:
    """Return ``(id_type, id_value)`` for the first identifier we find.

    ``id_type`` is one of the keys in ``_ID_PATTERNS``; ``id_value`` is
    the captured surface form (normalised on comparison, not here).
    """
    for id_type, pat in _ID_PATTERNS:
        m = pat.search(claim_text)
        if m:
            return id_type, m.group(1)
    return None, None


def _norm_chebi(s: str) -> str:
    """Normalise a ChEBI surface form to ``CHEBI:NNNN``."""
    s = s.strip().upper()
    s = re.sub(r"^CHEBI\s*[:_]?\s*", "", s)
    return f"CHEBI:{s}" if s else ""


def _norm_inchikey(s: str) -> str:
    """Take the 14-char first block (case-insensitive)."""
    return s.strip().upper().split("-")[0]


@lru_cache(maxsize=1)
def _load_curated() -> list[dict]:
    """Lazy-load the curated mammalian compound pool. Returns [] if
    file missing — the layer then degrades to ``UNVERIFIABLE_V0`` for
    out-of-task lookups, which is the correct behaviour."""
    if not _CURATED_PATH.is_file():
        return []
    out: list[dict] = []
    with _CURATED_PATH.open() as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _find_by_subject(pool: list[dict], subject: str) -> dict | None:
    """Case-insensitive exact-name match against a metabolite pool.

    W13.A fallback: when exact-match fails, retry with subject-name
    normalisation (Greek-letter → Roman, NFKD-strip accents, whitespace
    → hyphen). See verifier/helpers/subject_normalizer.py.
    """
    if not subject:
        return None
    target = subject.strip().lower()
    for m in pool:
        if (m.get("name") or "").strip().lower() == target:
            return m
    # W13.A — normalised-form fallback
    from verifier.helpers.subject_normalizer import normalize_subject_name
    target_norm = normalize_subject_name(subject)
    if not target_norm:
        return None
    for m in pool:
        name = m.get("name") or ""
        if normalize_subject_name(name) == target_norm:
            return m
    return None


def _compare_id(
    metabolite: dict, id_type: str, id_value: str
) -> tuple[bool | None, str | None]:
    """Compare a claimed identifier against a metabolite's matching field.

    Returns ``(match, field_value)`` where ``match`` is:
      * ``True``  — field present and matches
      * ``False`` — field present and differs
      * ``None``  — field absent on this metabolite (cannot judge)
    ``field_value`` is the metabolite's value used in the comparison
    (for evidence / correction rendering).
    """
    if id_type == "kegg_id":
        field_val = metabolite.get("kegg_id")
        if not field_val:
            return None, None
        return id_value.strip().upper() == str(field_val).strip().upper(), str(field_val)

    if id_type == "hmdb_id":
        field_val = metabolite.get("hmdb_id")
        if not field_val:
            return None, None
        return id_value.strip().upper() == str(field_val).strip().upper(), str(field_val)

    if id_type == "chebi_id":
        field_val = metabolite.get("chebi_id")
        if not field_val:
            return None, None
        return _norm_chebi(id_value) == _norm_chebi(str(field_val)), str(field_val)

    if id_type == "pubchem_cid":
        # W13.A — PubChem CID comparison. Curated pool stores as int;
        # differential_metabolites fixtures use str. Normalise to str
        # without leading zeros so "0006057" matches "6057".
        field_val = metabolite.get("pubchem_cid")
        if field_val is None or field_val == "":
            return None, None
        claimed = str(id_value).strip().lstrip("0") or "0"
        field_norm = str(field_val).strip().lstrip("0") or "0"
        return claimed == field_norm, str(field_val)

    if id_type in ("inchikey", "inchikey_short"):
        ik_full = metabolite.get("inchikey") or ""
        ik_short = metabolite.get("inchikey_first_block") or ""
        if not (ik_full or ik_short):
            return None, None
        claimed_first = _norm_inchikey(id_value)
        for candidate in (ik_full, ik_short):
            if candidate and _norm_inchikey(candidate) == claimed_first:
                return True, candidate
        return False, ik_short or ik_full

    return None, None


def verify_factual_sub6(
    claim: ClassifiedClaim,
    source_report: SubsixSourceReport,
) -> VerifiedClaim:
    """Verify one FACTUAL / GROUNDED metabolite-ID claim on a Sub-6 task."""
    diff_metab = list(source_report.differential_metabolites or [])

    id_type, id_value = _extract_id(claim.claim_text)
    if id_type is None or id_value is None:
        return _uv(
            claim,
            evidence=(
                "Layer factual_sub6: no KEGG / HMDB / CHEBI / InChIKey "
                "identifier could be extracted from the claim text. "
                "Cannot verify."
            ),
        )

    # Step 1: subject lookup in differential_metabolites.
    metab = _find_by_subject(diff_metab, claim.subject or "")
    if metab is not None:
        match, field_val = _compare_id(metab, id_type, id_value)
        if match is True:
            return _supported(claim, metab, id_type, id_value, field_val,
                              source="differential_metabolites")
        if match is False:
            return _contradicted(claim, metab, id_type, id_value, field_val,
                                 source="differential_metabolites")
        # match is None — subject found but ID field absent: fall through to curated

    # Step 2: curated mammalian pool fallback.
    curated = _load_curated()
    metab_c = _find_by_subject(curated, claim.subject or "")
    if metab_c is not None:
        match, field_val = _compare_id(metab_c, id_type, id_value)
        if match is True:
            return _supported(claim, metab_c, id_type, id_value, field_val,
                              source="curated_hmdb_mammalian")
        if match is False:
            return _contradicted(claim, metab_c, id_type, id_value, field_val,
                                 source="curated_hmdb_mammalian")
        # match is None — subject in curated but the relevant field absent

    # Step 3: subject not found anywhere → UV.
    return _uv(
        claim,
        evidence=(
            f"Layer factual_sub6: subject {(claim.subject or '?')!r} not found "
            f"in differential_metabolites ({len(diff_metab)} entries) or "
            f"curated_hmdb_mammalian ({len(curated)} entries). "
            f"Cannot verify claimed {id_type}={id_value!r}."
        ),
    )


# ---------------------------------------------------------------------------
# VerifiedClaim constructors
# ---------------------------------------------------------------------------


def _supported(
    claim: ClassifiedClaim,
    metabolite: dict,
    id_type: str,
    id_value: str,
    field_value: str | None,
    source: str,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.SUPPORTED,
        evidence=(
            f"{source}: {(metabolite.get('name') or '?')!r} has "
            f"{id_type}={field_value!r}, matches claim {id_value!r}."
        ),
        extracted_fields=claim.extracted_fields,
        verifier_layer="factual_sub6",
        tool_called=source,
        trace_summary=f"factual_sub6 {id_type} match in {source}",
    )


def _contradicted(
    claim: ClassifiedClaim,
    metabolite: dict,
    id_type: str,
    id_value: str,
    field_value: str | None,
    source: str,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.CONTRADICTED,
        evidence=(
            f"{source}: {(metabolite.get('name') or '?')!r} has "
            f"{id_type}={field_value!r}, claim says {id_value!r}."
        ),
        correction=str(field_value) if field_value else None,
        extracted_fields=claim.extracted_fields,
        verifier_layer="factual_sub6",
        tool_called=source,
        trace_summary=f"factual_sub6 {id_type} mismatch in {source}",
    )


def _uv(claim: ClassifiedClaim, evidence: str) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        evidence=evidence,
        extracted_fields=claim.extracted_fields,
        verifier_layer="factual_sub6",
        trace_summary="factual_sub6 unverifiable",
    )
