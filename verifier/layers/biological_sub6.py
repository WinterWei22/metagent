"""Sub-6 biological-claim layer (Q1(b) routing).

The default Layer C ``biological.py`` is spectrum-centric: it reads
``source_report.candidates[*].pathway_context`` and resolves subjects to
candidates. Sub-6 tasks have no candidates — they have an enrichment
result and ground-truth pathway/compound metadata. This layer is the
Sub-6 friendly counterpart, dispatched by ``verifier.agent.verify_sub6``
when ``claim_type == ClaimType.BIOLOGICAL`` is encountered with a
``SubsixSourceReport``.

What it can verify in v0:

* Pathway-membership claims of the form "compound X is in pathway Y" —
  resolved via the RaMP ``analytehaspathway`` table by InChIKey lookup
  through the curated mammalian pool.
* Pathway-name plausibility claims of the form "Y plays a role in
  metabolism" — checked by name-matching Y against the task's
  ``ground_truth_pathway`` and ``ramp_enrichment_result.top_pathways``.
* **CONTRADICTED** verdicts (added 2026-05-06 via track_layer6c_contra_path):
  when both compound and pathway resolve through the alias /
  ``analytehaspathway`` chain and RaMP knows the compound's pathway
  membership exhaustively (≥ ``MIN_KNOWN_PATHWAYS_FOR_CONTRA`` other
  pathways) but the claimed pathway is not among them, the claim is
  marked CONTRADICTED with the top-3 actual pathways supplied as
  correction. See §3 of
  ``reports/verifier/layer6c_contra_path_2026-05-06.md``.

What it cannot verify (returns ``UNVERIFIABLE_V0``):

* Disease / clinical-significance claims ("X is dysregulated in
  Parkinson's disease"). Sub-6 has no curated disease-pathway database
  in v0; any disease string in the claim → UNVERIFIABLE_V0.
* Free-text "biological role" claims with no concrete pathway or
  compound name.

This layer reuses helper logic from Layer 6a (set_enrichment) for the
pathway-name match path. It deliberately does NOT import or modify
``layers/biological.py``; the two run side-by-side with a clean
type-based dispatch in ``agent.verify_sub6``.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Iterable

from schemas.sub6_report import SubsixSourceReport
from verifier.layers.pathway_relationship import (
    _get_connection as _ramp_connection,
    _resolve_db_path as _resolve_ramp_path,
    _resolve_pathway as _resolve_ramp_pathway,
    _reverse_match_pathways as _ramp_reverse_match_pathways,
)
from verifier.layers.set_enrichment import (
    _PATHWAY_PHRASE_RE,
    _normalise,
    _PATHWAY_ID_RE,
    _pathway_match_from_dict,
)
from verifier.schemas import (
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
    EnrichmentContext,
    VerifiedClaim,
)

logger = logging.getLogger(__name__)


# Default minimum number of *other* known pathway memberships required
# before the layer will declare a claim CONTRADICTED. Below the threshold
# the compound is considered under-characterised in RaMP and "no membership
# found" is treated as missing data, not as evidence of contradiction.
# Tunable via env var for ablations / future calibration.
_MIN_KNOWN_PATHWAYS_FOR_CONTRA_DEFAULT = 3


def _min_known_pathways_for_contra() -> int:
    raw = os.environ.get("METAGENT_LAYER6C_MIN_KNOWN_PATHWAYS")
    if raw is None:
        return _MIN_KNOWN_PATHWAYS_FOR_CONTRA_DEFAULT
    try:
        v = int(raw)
        return v if v >= 1 else _MIN_KNOWN_PATHWAYS_FOR_CONTRA_DEFAULT
    except ValueError:
        return _MIN_KNOWN_PATHWAYS_FOR_CONTRA_DEFAULT


# Disease-keyword detection — if a claim names a disease, v0 cannot
# verify it (no curated disease DB).
_DISEASE_KEYWORDS = re.compile(
    r"\b(?:"
    r"disease|disorder|deficienc(?:y|ies)|syndrome|"
    r"cancer|tumor|tumour|carcinoma|leukemia|leukaemia|"
    r"diabetes|diabetic|"
    r"alzheimer|parkinson|huntington|"
    r"phenylketonuria|alkaptonuria|tyrosinemia|galactosemia|"
    r"dysregulated|dysregulation|pathology|pathological|"
    r"clinical|therapeutic|targeted by|treatment for"
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def verify_biological_sub6(
    claim: ClassifiedClaim,
    source_report: SubsixSourceReport,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> VerifiedClaim:
    """Verify one BIOLOGICAL claim against a Sub-6 source report."""
    text = claim.claim_text or ""

    # Disease / clinical claims: declared limitation in v0.
    if _DISEASE_KEYWORDS.search(text):
        return _unverifiable(
            claim,
            evidence=(
                "Disease / clinical-significance claims fall outside "
                "Sub-6 v0 scope: no curated disease-pathway DB is "
                "available. Treat as a declared limitation rather than "
                "a contradiction."
            ),
            ctx=EnrichmentContext(),
        )

    # Pathway-name plausibility against ground-truth + top-10.
    pathway_name = (
        claim.extracted_fields.pathway_name
        or _first_phrase(text)
    )
    pathway_id = (
        claim.extracted_fields.pathway_id
        or _first_id(text)
    )

    if not pathway_name and not pathway_id:
        return _unverifiable(
            claim,
            evidence=(
                "Layer biological_sub6 found no pathway phrase / ID and "
                "no concrete entity to verify. Free-text biological "
                "role claims are out of v0 scope."
            ),
            ctx=EnrichmentContext(),
        )

    # Compare against ground-truth pathway + top_pathways[:10].
    candidates: list[dict] = []
    gt = source_report.ground_truth_pathway or {}
    if gt:
        candidates.append(gt)
    candidates.extend(
        (source_report.ramp_enrichment_result or {}).get("top_pathways", [])[:10]
    )

    matched_top = [
        _pathway_match_from_dict(p, rank=i + 1)
        for i, p in enumerate(candidates[:3])
    ]

    norm_text = _normalise(text)
    norm_claim = _normalise(pathway_name) if pathway_name else None

    for i, p in enumerate(candidates):
        canon = _normalise(p.get("pathway_name") or "")
        canon_id = (p.get("pathway_id") or p.get("pathway_external_id") or "").lower()

        if pathway_id and canon_id == pathway_id.lower():
            return _supported(
                claim,
                evidence=(
                    f"Pathway ID {pathway_id!r} matches "
                    f"{p.get('pathway_name')!r} in task context "
                    f"({_kind_for_index(i)})."
                ),
                ctx=EnrichmentContext(
                    claimed_pathway=pathway_name,
                    claimed_pathway_id=pathway_id,
                    matched_top_pathways=matched_top,
                    pathway_match_method="id",
                ),
            )
        if norm_claim and canon and (
            canon == norm_claim or norm_claim in canon or canon in norm_claim
        ):
            return _supported(
                claim,
                evidence=(
                    f"Pathway phrase {pathway_name!r} matches "
                    f"{p.get('pathway_name')!r} in task context "
                    f"({_kind_for_index(i)})."
                ),
                ctx=EnrichmentContext(
                    claimed_pathway=pathway_name,
                    matched_top_pathways=matched_top,
                    pathway_match_method=(
                        "exact" if canon == norm_claim else "substring_either"
                    ),
                ),
            )
        # Reverse: canonical name appears verbatim in claim text.
        if canon and len(canon) >= 5 and canon in norm_text:
            return _supported(
                claim,
                evidence=(
                    f"Canonical name {p.get('pathway_name')!r} appears in "
                    f"claim text ({_kind_for_index(i)})."
                ),
                ctx=EnrichmentContext(
                    claimed_pathway=p.get("pathway_name"),
                    matched_top_pathways=matched_top,
                    pathway_match_method="substring_either",
                ),
            )

    # No match in ground truth or top_pathways. Fall back to RaMP
    # membership check by direct ID lookup, when one is supplied.
    if pathway_id:
        db = _resolve_ramp_path(db_path)
        if conn is not None or db is not None:
            with _ramp_connection(conn=conn, path=db) as cursor:
                hits = _resolve_ramp_pathway(cursor, pathway_id)
                if hits:
                    return _supported(
                        claim,
                        evidence=(
                            f"Pathway ID {pathway_id!r} resolves to "
                            f"{hits[0]} in RaMP, but is not in this "
                            "task's enrichment context. SUPPORTED on "
                            "membership, not on relevance."
                        ),
                        ctx=EnrichmentContext(
                            claimed_pathway_id=pathway_id,
                            matched_top_pathways=matched_top,
                            pathway_match_method="id",
                        ),
                    )

    # ------------------------------------------------------------------
    # Compound × pathway membership check (track_layer6c_contra_path).
    # Returns one of {SUPPORTED, CONTRADICTED, UNSUPPORTED, None} —
    # None means the helper couldn't make a call (resolution failed,
    # DB unavailable, etc.); fall through to the historical UNSUPPORTED.
    # ------------------------------------------------------------------
    contra_check = _check_compound_pathway_membership_in_ramp(
        claim=claim,
        text=text,
        pathway_phrase=pathway_name,
        pathway_id=pathway_id,
        ramp_db_path=db_path,
        ramp_conn=conn,
        matched_top=matched_top,
    )
    if contra_check is not None:
        return contra_check

    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.BIOLOGICAL,
        claim_subtype=claim.claim_subtype if claim.claim_subtype != ClaimSubtype.UNKNOWN else ClaimSubtype.PATHWAY_MEMBERSHIP,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNSUPPORTED,
        evidence=(
            f"Pathway {(pathway_name or pathway_id)!r} not present in "
            "this task's ground_truth_pathway, top_pathways[:10], or "
            "RaMP. Treated as unsupported (no positive evidence) rather "
            "than contradicted."
        ),
        extracted_fields=claim.extracted_fields,
        verifier_layer="biological_sub6",
        trace_summary="pathway not found in task context or RaMP",
        enrichment_context=EnrichmentContext(
            claimed_pathway=pathway_name,
            claimed_pathway_id=pathway_id,
            matched_top_pathways=matched_top,
            pathway_match_method="none",
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_phrase(text: str) -> str | None:
    m = _PATHWAY_PHRASE_RE.search(text)
    return m.group(0).strip() if m else None


def _first_id(text: str) -> str | None:
    m = _PATHWAY_ID_RE.search(text)
    return m.group(1) if m else None


def _kind_for_index(i: int) -> str:
    return "ground_truth_pathway" if i == 0 else f"top_pathways[{i - 1}]"


def _supported(
    claim: ClassifiedClaim, *, evidence: str, ctx: EnrichmentContext,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.BIOLOGICAL,
        claim_subtype=claim.claim_subtype if claim.claim_subtype != ClaimSubtype.UNKNOWN else ClaimSubtype.PATHWAY_MEMBERSHIP,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.SUPPORTED,
        evidence=evidence,
        extracted_fields=claim.extracted_fields,
        verifier_layer="biological_sub6",
        tool_called="ramp_enrichment_result",
        trace_summary="pathway present in task context",
        enrichment_context=ctx,
    )


def _unverifiable(
    claim: ClassifiedClaim, *, evidence: str, ctx: EnrichmentContext,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.BIOLOGICAL,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        evidence=evidence,
        extracted_fields=claim.extracted_fields,
        verifier_layer="biological_sub6",
        trace_summary="biological_sub6 unverifiable",
        enrichment_context=ctx,
    )


# ---------------------------------------------------------------------------
# Contra-path helper (track_layer6c_contra_path)
# ---------------------------------------------------------------------------


# Capitalised compound-name tokens to scan for in claim text when
# claim.subject is empty or unhelpful (e.g. when the extractor put a
# pathway name in the subject slot).
_TITLE_TOKEN_RE = re.compile(r"\b([A-Z][A-Za-z0-9-]+(?:\s+[A-Z]?[a-z]+){0,2})\b")
_ACRONYM_RE = re.compile(r"\b([A-Z]{2,8}(?:-[A-Z][a-zA-Z0-9]+)?)\b")


def _check_compound_pathway_membership_in_ramp(
    *,
    claim: ClassifiedClaim,
    text: str,
    pathway_phrase: str | None,
    pathway_id: str | None,
    ramp_db_path: str | None,
    ramp_conn: sqlite3.Connection | None,
    matched_top: list,
) -> VerifiedClaim | None:
    """Resolve compound + claimed pathway through KEGG aliases + RaMP and
    decide between SUPPORTED / CONTRADICTED / UNSUPPORTED / None.

    Returns:
        ``None`` when resolution failed (compound or pathway unresolvable,
        DB unavailable, compound absent from RaMP source). The caller
        falls through to the historical UNSUPPORTED branch.
        ``VerifiedClaim(verdict=SUPPORTED)`` when ``analytehaspathway``
        confirms the compound IS in at least one of the resolved
        pathways (false-negative rescue).
        ``VerifiedClaim(verdict=CONTRADICTED)`` when the compound has
        ≥ ``MIN_KNOWN_PATHWAYS_FOR_CONTRA`` pathway memberships and the
        claimed pathway is not among them. Carries top-3 actual pathways
        as ``correction``.
        ``VerifiedClaim(verdict=UNSUPPORTED)`` when the compound has
        fewer than the threshold pathway memberships (under-characterised
        in RaMP) — preserves the historical "no positive evidence" verdict.
    """
    # Lazy imports — keep module import cheap when only Layer A–F is hit.
    try:
        from tools.kegg.reachability import resolve_compound_to_kegg
    except Exception:  # pragma: no cover — stdlib import only
        return None

    db = _resolve_ramp_path(ramp_db_path)
    if ramp_conn is None and db is None:
        return None

    # Step 1: open RaMP read-only.
    try:
        ramp_ctx = _ramp_connection(conn=ramp_conn, path=db)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("biological_sub6 contra: RaMP connection failed: %s", exc)
        return None

    # Step 2: open the KEGG alias DB used by resolve_compound_to_kegg.
    # It lives at data/kegg/reaction_graph.sqlite by convention; allow
    # override via METAGENT_KEGG_PATH (same env Layer 6d uses).
    kegg_path = os.environ.get("METAGENT_KEGG_PATH")
    if not kegg_path:
        from pathlib import Path as _Path
        default_kegg = (
            _Path(__file__).resolve().parents[2] / "data" / "kegg" / "reaction_graph.sqlite"
        )
        if default_kegg.exists():
            kegg_path = str(default_kegg)
    if not kegg_path:
        return None

    kegg_conn: sqlite3.Connection | None = None
    try:
        kegg_conn = sqlite3.connect(f"file:{kegg_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        logger.debug("biological_sub6 contra: KEGG connect failed: %s", exc)
        return None

    try:
        with ramp_ctx as cursor:
            # Step 3: resolve compound subject → cpd:C-id.
            cpd_id = _resolve_compound_subject(claim, text, kegg_conn)
            if not cpd_id:
                return None

            # Step 4: cpd:C-id → RaMP rampId (source.sourceId='kegg:CXXXXX').
            ramp_id = _kegg_to_ramp_id(cursor, cpd_id)
            if not ramp_id:
                # Compound not in RaMP — can't query analytehaspathway.
                return None

            # Step 5: resolve claimed pathway → list of pathwayRampIds.
            pway_ids = _resolve_claimed_pathway_ids(
                cursor, pathway_phrase, pathway_id, text,
            )
            if not pway_ids:
                return None

            # Step 6: overlap check.
            overlap = _membership_overlap(cursor, ramp_id, pway_ids)

            if overlap > 0:
                # False-negative rescue: claim's pathway IS one of the
                # compound's known memberships in RaMP.
                ctx = EnrichmentContext(
                    claimed_pathway=pathway_phrase,
                    claimed_pathway_id=pathway_id,
                    matched_top_pathways=matched_top,
                    pathway_match_method="substring_either",
                    tool_evidence={
                        "ramp_compound_id": ramp_id,
                        "ramp_pathway_ids_claimed": list(pway_ids),
                        "membership_check": "overlap_positive",
                        "overlap_count": overlap,
                    },
                )
                return _supported(
                    claim,
                    evidence=(
                        f"RaMP analytehaspathway confirms compound "
                        f"({ramp_id}, derived from {cpd_id}) is in at least "
                        f"one of the {len(pway_ids)} resolved pathways for "
                        f"the claim ({overlap} membership row(s))."
                    ),
                    ctx=ctx,
                )

            # No overlap — check if RaMP knows enough about this compound
            # to draw a contra conclusion.
            n_known = _count_known_pathways(cursor, ramp_id)
            min_thresh = _min_known_pathways_for_contra()

            if n_known < min_thresh:
                # Under-characterised compound; "no membership found" could
                # just be missing data. Fall through to UNSUPPORTED via the
                # caller. Surface n_known so the caller can audit.
                return None

            # CONTRADICTED — RaMP knows this compound's pathway memberships
            # exhaustively, and the claimed pathway is not one of them.
            top3 = _top_actual_pathways(cursor, ramp_id, k=3)
            top3_names = [name for _id, name, _kind in top3]
            correction = (
                "; ".join(top3_names)
                if top3_names
                else None
            )
            evidence = (
                f"RaMP-DB knows compound {cpd_id} (ramp_id={ramp_id}) is in "
                f"{n_known} pathways; the claimed pathway "
                f"{(pathway_phrase or pathway_id)!r} is not among them. "
                f"Top-3 actual pathways: "
                f"{', '.join(top3_names) if top3_names else '(none)'}."
            )

            ctx = EnrichmentContext(
                claimed_pathway=pathway_phrase,
                claimed_pathway_id=pathway_id,
                matched_top_pathways=matched_top,
                pathway_match_method="none",
                tool_evidence={
                    "ramp_compound_id": ramp_id,
                    "kegg_compound_id": cpd_id,
                    "ramp_pathway_ids_claimed": list(pway_ids),
                    "membership_check": "no_intersection",
                    "n_pathways_known": n_known,
                    "min_known_threshold": min_thresh,
                    "top_actual_pathways": top3_names,
                },
            )
            return VerifiedClaim(
                claim_id=claim.claim_id,
                claim_text=claim.claim_text,
                claim_type=ClaimType.BIOLOGICAL,
                claim_subtype=(
                    claim.claim_subtype
                    if claim.claim_subtype != ClaimSubtype.UNKNOWN
                    else ClaimSubtype.PATHWAY_MEMBERSHIP
                ),
                subject=claim.subject,
                subject_kind=claim.subject_kind,
                candidate_ref=claim.candidate_ref,
                verdict=ClaimVerdict.CONTRADICTED,
                evidence=evidence,
                correction=correction,
                extracted_fields=claim.extracted_fields,
                verifier_layer="biological_sub6",
                tool_called="ramp_db",
                trace_summary=(
                    f"compound {cpd_id} known in {n_known} pathways but "
                    f"claimed pathway not among them"
                ),
                enrichment_context=ctx,
            )
    finally:
        try:
            kegg_conn.close()
        except Exception:
            pass


def _resolve_compound_subject(
    claim: ClassifiedClaim,
    text: str,
    kegg_conn: sqlite3.Connection,
) -> str | None:
    """Resolve a free-text compound subject to a cpd:C-id.

    Order of attempts:
      1. ``claim.subject`` — preferred when populated and not a pathway name.
      2. Capitalised compound-shaped tokens in claim text (1-3 words).
      3. All-caps acronyms of length ≥ 2 (e.g. "FAD", "NAD", "FPP").

    Returns ``None`` when nothing resolves.
    """
    from tools.kegg.reachability import resolve_compound_to_kegg

    # Filter out subjects that are obviously pathway names — the
    # extractor sometimes puts "tyrosine metabolism" in the subject slot.
    subject = (claim.subject or "").strip()
    pathway_suffixes = (
        "metabolism", "biosynthesis", "degradation", "catabolism",
        "anabolism", "synthesis", "cycle", "pathway", "pathways",
    )
    if subject and not any(
        subject.lower().endswith(s) or s in subject.lower()
        for s in pathway_suffixes
    ):
        cpd, _src = resolve_compound_to_kegg(subject, conn=kegg_conn)
        if cpd:
            return cpd

    # Fallback: scan text for plausible compound tokens. The Title-Case
    # regex ``[A-Z][a-z]+(?:[\s-][A-Z]?[a-z]+){0,2}`` permits the second/
    # third token to be lowercase (so we capture "Citric acid" /
    # "Pantothenic acid"); however that also lets stopwords like "is",
    # "in", "of" sneak in. Strip trailing stopwords before resolution.
    candidates: list[str] = []
    for m in _TITLE_TOKEN_RE.finditer(text or ""):
        tok = m.group(1).strip()
        if len(tok) >= 4:
            candidates.append(tok)
    for m in _ACRONYM_RE.finditer(text or ""):
        tok = m.group(1).strip()
        if 2 <= len(tok) <= 12:
            candidates.append(tok)

    seen: set[str] = set()
    for tok in candidates:
        for variant in _strip_trailing_stopwords(tok):
            key = variant.lower()
            if key in seen:
                continue
            seen.add(key)
            cpd, _src = resolve_compound_to_kegg(variant, conn=kegg_conn)
            if cpd:
                return cpd
    return None


_TRAILING_STOPWORDS = frozenset({
    "the", "and", "or", "is", "are", "was", "were", "be", "been",
    "in", "on", "of", "for", "to", "from", "with", "by", "via",
    "into", "through", "as", "at", "this", "that", "these", "those",
    "a", "an",
})


def _strip_trailing_stopwords(token: str) -> list[str]:
    """Yield progressively shorter prefixes of ``token`` with trailing
    stopwords removed. Lets the resolver try ["Pantothenic acid is",
    "Pantothenic acid", "Pantothenic"] in turn."""
    words = token.split()
    yield_seen: set[str] = set()
    out: list[str] = []
    while words:
        candidate = " ".join(words)
        if candidate.lower() not in yield_seen:
            yield_seen.add(candidate.lower())
            out.append(candidate)
        if words[-1].lower() in _TRAILING_STOPWORDS:
            words = words[:-1]
        else:
            break
    return out


def _kegg_to_ramp_id(cursor: sqlite3.Cursor, cpd_id: str) -> str | None:
    """cpd:CXXXXX → first matching RaMP rampId via source.sourceId='kegg:CXXXXX'."""
    if not cpd_id:
        return None
    short = cpd_id.replace("cpd:", "") if cpd_id.startswith("cpd:") else cpd_id
    cursor.execute(
        "SELECT rampId FROM source WHERE IDtype='kegg' AND sourceId=? LIMIT 1",
        (f"kegg:{short}",),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def _resolve_claimed_pathway_ids(
    cursor: sqlite3.Cursor,
    pathway_phrase: str | None,
    pathway_id: str | None,
    text: str,
) -> list[str]:
    """Resolve a claimed pathway phrase / ID into a list of RaMP pathwayIds.

    Tries (in order):
      1. ``pathway_id`` direct lookup via Layer 6d's ``_resolve_pathway``.
      2. ``pathway_phrase`` substring match via the same helper.
      3. **RaMP reverse-match** of ``pathway.pathwayName`` against
         ``text`` — catches pathway names that the regex missed
         ("DNA synthesis", "salvage pathway", "uracil degradation").
         Mirrors Layer 6d's reverse-match fallback policy (RD-001 fix).
    """
    out: list[str] = []
    if pathway_id:
        rows = _resolve_ramp_pathway(cursor, pathway_id)
        out.extend(rows[:5])
    if pathway_phrase:
        rows = _resolve_ramp_pathway(cursor, pathway_phrase)
        out.extend(rows[:5])
        # Also try stripping trailing pathway-suffix terms — RaMP names
        # like "Pyrimidine biosynthesis" are missed by a substring query
        # on "Pyrimidine biosynthesis pathway" because the canonical
        # name is shorter than the query. Both directions of substring
        # are needed.
        stripped = re.sub(
            r"\s+(?:pathway|pathways|cycle)\s*$", "", pathway_phrase, flags=re.IGNORECASE
        ).strip()
        if stripped and stripped.lower() != pathway_phrase.lower():
            rows = _resolve_ramp_pathway(cursor, stripped)
            out.extend(rows[:5])
    # Always combine with reverse-match against the full claim text —
    # catches names that the regex missed entirely (e.g. "salvage pathway"
    # phrases that strip to a too-short stem).
    rev = _ramp_reverse_match_pathways(
        cursor, text or "", exclude_ids=set(out), limit=5,
    )
    out.extend(rid for _name, rid in rev)
    # Dedupe preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for rid in out:
        if rid in seen:
            continue
        seen.add(rid)
        deduped.append(rid)
    return deduped


def _membership_overlap(
    cursor: sqlite3.Cursor, ramp_compound_id: str, pathway_ids: Iterable[str],
) -> int:
    pathway_ids = list(pathway_ids)
    if not pathway_ids:
        return 0
    placeholders = ",".join("?" * len(pathway_ids))
    cursor.execute(
        f"SELECT COUNT(*) FROM analytehaspathway "
        f"WHERE rampId=? AND pathwayRampId IN ({placeholders})",
        (ramp_compound_id, *pathway_ids),
    )
    return int(cursor.fetchone()[0])


def _count_known_pathways(cursor: sqlite3.Cursor, ramp_compound_id: str) -> int:
    cursor.execute(
        "SELECT COUNT(DISTINCT pathwayRampId) FROM analytehaspathway WHERE rampId=?",
        (ramp_compound_id,),
    )
    return int(cursor.fetchone()[0])


_GENERIC_PATHWAY_NAMES = frozenset({
    # Reactome / SMPDB top-level clusters that surface for almost any
    # compound and are useless as a "correction" target.
    "metabolism", "disease", "metabolic pathway", "metabolism overview",
    "biological oxidations", "signaling pathways", "signal transduction",
    "developmental biology", "cell cycle", "s phase", "m phase",
    "g1 phase", "g2 phase", "homeostasis", "transport of small molecules",
})


def _top_actual_pathways(
    cursor: sqlite3.Cursor, ramp_compound_id: str, *, k: int = 3,
) -> list[tuple[str, str, str | None]]:
    """Return up to ``k`` (pathwayRampId, pathwayName, type) tuples for the
    compound, ranked so that the result is useful as a correction target.

    Sort priority (lower = better):
      1. ``type`` priority — kegg > wikipathways > smpdb > reactome > hmdb
         (KEGG names are the canonical metabolic pathways that LLMs are
         most likely to have meant)
      2. exclude generic top-level clusters from
         ``_GENERIC_PATHWAY_NAMES`` (when possible — fall back if doing
         so would empty the list)
      3. shorter canonical name as a tiebreaker proxy for "most central"

    Pulls a candidate set wider than ``k`` and post-filters in Python so
    we don't have to reach for SQL-side type ordering.
    """
    cursor.execute(
        "SELECT a.pathwayRampId, p.pathwayName, p.type FROM analytehaspathway a "
        "JOIN pathway p ON a.pathwayRampId = p.pathwayRampId "
        "WHERE a.rampId = ? "
        "ORDER BY length(p.pathwayName) ASC LIMIT 50",
        (ramp_compound_id,),
    )
    rows = list(cursor.fetchall())
    if not rows:
        return []

    type_rank = {
        "kegg": 0,
        "wikipathways": 1,
        "smpdb": 2,
        "reactome": 3,
        "hmdb": 4,
    }

    def is_generic(name: str) -> bool:
        return (name or "").strip().lower() in _GENERIC_PATHWAY_NAMES

    def sort_key(row: tuple[str, str, str | None]) -> tuple[int, int, int]:
        _id, name, kind = row
        return (
            type_rank.get((kind or "").lower(), 9),
            0 if not is_generic(name) else 1,
            len(name or ""),
        )

    rows.sort(key=sort_key)
    # Filter out generics first, but if filtering would empty the result,
    # accept generics as a fallback.
    non_generic = [r for r in rows if not is_generic(r[1] or "")]
    chosen = (non_generic if non_generic else rows)[:k]
    return chosen
