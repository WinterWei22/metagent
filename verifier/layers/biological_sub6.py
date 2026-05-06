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

    # ------------------------------------------------------------------
    # Phase B: build a list of pathway-phrase candidates with provenance.
    # The original logic only used the FIRST phrase _first_phrase produced;
    # Phase A narratives bury the RaMP-resolvable noun in subordinate
    # clauses ("during the X step of de-novo Y"), so we also try the
    # _normalise_phrase variants. Each candidate carries a
    # `phrase_resolution_path` tag so D5 can stratify contra origins.
    # ------------------------------------------------------------------
    extracted_pathway_name = claim.extracted_fields.pathway_name
    first_phrase_pathway = _first_phrase(text)
    pathway_id = (
        claim.extracted_fields.pathway_id
        or _first_id(text)
    )

    pathway_candidates: list[tuple[str, str]] = []  # (phrase, resolution_path)
    seen_phrases: set[str] = set()

    def _push_candidate(phrase: str | None, path: str) -> None:
        if not phrase:
            return
        norm = phrase.strip().lower()
        if not norm or norm in seen_phrases:
            return
        seen_phrases.add(norm)
        pathway_candidates.append((phrase.strip(), path))

    # 1) extracted_fields.pathway_name — same provenance tag as v6/v7-C
    #    used to label "first_phrase" so backward-compat is preserved.
    _push_candidate(extracted_pathway_name, "first_phrase")
    # 2) raw _first_phrase output
    _push_candidate(first_phrase_pathway, "first_phrase")
    # 3) normalised variants (Phase B Fix-1) — only seeded from the
    #    extractor / _first_phrase output. We deliberately do NOT
    #    normalise the raw claim text: that would turn pure-role talk
    #    ("X plays a fundamental biological role") into a 'pathway
    #    candidate' even though the claim has no pathway shape, breaking
    #    the historical UV0 short-circuit.
    base_for_normalise = extracted_pathway_name or first_phrase_pathway
    if base_for_normalise:
        for variant in _normalise_phrase(base_for_normalise):
            _push_candidate(variant, "normalise")

    # If we have absolutely nothing — no pathway-shape phrase AND no
    # pathway_id — keep the historical UVO short-circuit. The reverse-
    # fuzz fall-through stays gated behind "forward resolution had
    # something to try but failed", so pure-role claims like "X plays
    # a fundamental biological role" do not get auto-promoted by
    # compound-side reverse-lookup. This preserves the historical
    # decision boundary in the test suite while still letting Phase A's
    # mechanism-talk claims (which DO carry a phrase-shape via
    # ``_first_phrase`` or ``_normalise_phrase``) flow through to
    # reverse-fuzz when the forward resolver fails.
    if not pathway_candidates and not pathway_id:
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

    # Top-pathways / ground-truth match: ONLY uses the original first_phrase
    # / extracted pathway name — not normalise variants. Rationale: the
    # forward (top_pathways) match path is already permissive (substring +
    # canonical reverse-search); piping multiple normalise variants through
    # it tends to over-resolve borderline phrases ("phospholipid synthesis"
    # → "phospholipid metabolism" matching a generic top pathway) and
    # converts some legitimate v6 contra verdicts into spurious supp. The
    # contra helper below — which checks compound × pathway membership in
    # RaMP — DOES try the full candidate list, so normalise still extends
    # contra resolution as designed.
    forward_resolution_path = "first_phrase"
    forward_pathway_name = extracted_pathway_name or first_phrase_pathway
    norm_claim = _normalise(forward_pathway_name) if forward_pathway_name else None

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
                    claimed_pathway=forward_pathway_name,
                    claimed_pathway_id=pathway_id,
                    matched_top_pathways=matched_top,
                    pathway_match_method="id",
                    tool_evidence={"phrase_resolution_path": forward_resolution_path},
                ),
            )
        if norm_claim and canon and (
            canon == norm_claim or norm_claim in canon or canon in norm_claim
        ):
            return _supported(
                claim,
                evidence=(
                    f"Pathway phrase {forward_pathway_name!r} matches "
                    f"{p.get('pathway_name')!r} in task context "
                    f"({_kind_for_index(i)})."
                ),
                ctx=EnrichmentContext(
                    claimed_pathway=forward_pathway_name,
                    matched_top_pathways=matched_top,
                    pathway_match_method=(
                        "exact" if canon == norm_claim else "substring_either"
                    ),
                    tool_evidence={"phrase_resolution_path": forward_resolution_path},
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
                    tool_evidence={"phrase_resolution_path": forward_resolution_path},
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
                            tool_evidence={"phrase_resolution_path": "first_phrase"},
                        ),
                    )

    # ------------------------------------------------------------------
    # Compound × pathway membership check (track_layer6c_contra_path).
    # Returns one of {SUPPORTED, CONTRADICTED, UNSUPPORTED, None} —
    # None means the helper couldn't make a call (resolution failed,
    # DB unavailable, etc.); fall through to the historical UNSUPPORTED.
    # Phase B: try each pathway candidate in order; first non-None wins.
    # ------------------------------------------------------------------
    contra_resolution_path: str | None = None
    contra_check: VerifiedClaim | None = None
    # Always try at least the first_phrase / extracted phrase first to
    # match v6/v7-C decision points exactly. If that returns None and we
    # have additional candidates (normalise variants), try them too.
    contra_candidates_to_try: list[tuple[str | None, str]] = (
        [(c, p) for c, p in pathway_candidates] or [(None, "first_phrase")]
    )
    for cand_phrase, cand_path in contra_candidates_to_try:
        contra_check = _check_compound_pathway_membership_in_ramp(
            claim=claim,
            text=text,
            pathway_phrase=cand_phrase,
            pathway_id=pathway_id,
            ramp_db_path=db_path,
            ramp_conn=conn,
            matched_top=matched_top,
        )
        if contra_check is not None:
            contra_resolution_path = cand_path
            break

    if contra_check is not None:
        # Tag the verdict with phrase_resolution_path for D5 stratification.
        if contra_check.enrichment_context is not None:
            ev = dict(contra_check.enrichment_context.tool_evidence or {})
            ev.setdefault("phrase_resolution_path", contra_resolution_path or "first_phrase")
            contra_check.enrichment_context.tool_evidence = ev
        return contra_check

    # ------------------------------------------------------------------
    # Phase B Fix-2: reverse-fuzz fall-through. The LLM uses a phrase the
    # forward resolver can't catch (mechanism / role talk like
    # "Pyruvate accumulation indicates remodeled glycolytic balance");
    # query RaMP for the resolved compound's known pathways and check
    # whether any pathway-name stem is word-bounded in the claim text.
    # The matched RaMP pathway then re-enters the contra helper as the
    # pathway_phrase input — same decision tree, just a better input.
    # ------------------------------------------------------------------
    rev_check = _try_reverse_fuzz_recheck(
        claim=claim,
        text=text,
        pathway_id=pathway_id,
        ramp_db_path=db_path,
        ramp_conn=conn,
        matched_top=matched_top,
    )
    if rev_check is not None:
        return rev_check

    # Final UNSUPPORTED fall-through.
    final_phrase_for_evidence = (
        pathway_candidates[0][0] if pathway_candidates else None
    )
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.BIOLOGICAL,
        claim_subtype=claim.claim_subtype if claim.claim_subtype != ClaimSubtype.UNKNOWN else ClaimSubtype.PATHWAY_MEMBERSHIP,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=(
            ClaimVerdict.UNSUPPORTED if (final_phrase_for_evidence or pathway_id)
            else ClaimVerdict.UNVERIFIABLE_V0
        ),
        evidence=(
            f"Pathway {(final_phrase_for_evidence or pathway_id)!r} not present in "
            "this task's ground_truth_pathway, top_pathways[:10], or "
            "RaMP. Treated as unsupported (no positive evidence) rather "
            "than contradicted."
        ) if (final_phrase_for_evidence or pathway_id) else (
            "Layer biological_sub6 found no pathway phrase / ID, and "
            "no compound-side reverse-fuzz hit. Free-text biological "
            "role claims are out of v0 scope."
        ),
        extracted_fields=claim.extracted_fields,
        verifier_layer="biological_sub6",
        trace_summary="pathway not found in task context or RaMP",
        enrichment_context=EnrichmentContext(
            claimed_pathway=final_phrase_for_evidence,
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
# Phase B reverse-fuzz fall-through (track_layer6c_phrase_resolver_phase_b)
# ---------------------------------------------------------------------------


def _try_reverse_fuzz_recheck(
    *,
    claim: ClassifiedClaim,
    text: str,
    pathway_id: str | None,
    ramp_db_path: str | None,
    ramp_conn: sqlite3.Connection | None,
    matched_top: list,
) -> VerifiedClaim | None:
    """Phase B Fix-2 fall-through: when forward pathway resolution fails,
    query RaMP for the resolved compound's known pathways and stem-match
    them against the claim text. The matched RaMP pathway then re-enters
    ``_check_compound_pathway_membership_in_ramp`` as the
    ``pathway_phrase`` input — same decision tree, just a better input.

    Returns ``None`` when the compound doesn't resolve, no eligible RaMP
    pathway stem matches, or the contra helper still returns ``None``.
    """
    # Lazy imports — keep module import cheap.
    try:
        from tools.kegg.reachability import resolve_compound_to_kegg
    except Exception:  # pragma: no cover
        return None

    db = _resolve_ramp_path(ramp_db_path)
    if ramp_conn is None and db is None:
        return None

    # Open RaMP cursor + KEGG conn just like the contra helper does.
    try:
        ramp_ctx = _ramp_connection(conn=ramp_conn, path=db)
    except Exception:  # pragma: no cover
        return None

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
    except sqlite3.Error:
        return None

    try:
        with ramp_ctx as cursor:
            cpd_id = _resolve_compound_subject(claim, text, kegg_conn)
            if not cpd_id:
                return None
            ramp_id = _kegg_to_ramp_id(cursor, cpd_id)
            if not ramp_id:
                return None

            rev_hit = _reverse_fuzz_pathway(
                claim_text=text,
                compound_kegg_id=cpd_id,
                ramp_cursor=cursor,
            )
            if rev_hit is None:
                return None
            rev_pathway_name, rev_stem = rev_hit
    finally:
        if kegg_conn is not None:
            try:
                kegg_conn.close()
            except Exception:  # pragma: no cover
                pass

    # Re-enter the contra helper with the reverse-fuzzed pathway as input.
    # Because the pathway came from this compound's known set, the helper
    # SHOULD return SUPPORTED — but we let the helper decide so the
    # decision tree stays single-source-of-truth.
    re_check = _check_compound_pathway_membership_in_ramp(
        claim=claim,
        text=text,
        pathway_phrase=rev_pathway_name,
        pathway_id=pathway_id,
        ramp_db_path=ramp_db_path,
        ramp_conn=ramp_conn,
        matched_top=matched_top,
    )
    if re_check is None:
        return None

    # Tag the verdict with phrase_resolution_path = "reverse_fuzz" + the
    # matched stem so D5 can audit.
    if re_check.enrichment_context is not None:
        ev = dict(re_check.enrichment_context.tool_evidence or {})
        ev["phrase_resolution_path"] = "reverse_fuzz"
        ev["reverse_fuzz_pathway"] = rev_pathway_name
        ev["reverse_fuzz_stem"] = rev_stem
        re_check.enrichment_context.tool_evidence = ev
    return re_check


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


# ---------------------------------------------------------------------------
# Phase B helpers — pathway phrase resolver loosening (track_layer6c_phrase_resolver_phase_b)
# ---------------------------------------------------------------------------


# Words that lead a clause and never carry standalone pathway meaning.
# Stripped greedily from the front of an LLM phrase before fuzzy lookup.
_NORM_LEAD_WORDS = (
    # determiners / prepositions
    "the", "a", "an", "of", "in", "on", "at", "via", "for", "to",
    "through", "during", "under", "after", "into", "from", "with", "by",
    "about", "without", "along",
    "de-novo", "de novo", "novo",
    # generic prefixes / verb fragments commonly found before pathway
    # nouns in v7-phaseA narratives
    "is", "are", "was", "were", "may", "might", "can", "could", "should",
    "would", "will", "do", "does",
    "reflects", "reflect", "indicates", "indicate", "signals", "signal",
    "suggests", "suggest", "shows", "show", "provides", "provide",
    "denotes", "denote", "links", "link", "underlies", "underlie",
    "marks", "mark", "appears", "appear", "produces", "produce",
    "alters", "alter", "altered", "alterations",
    "primary", "direct", "downstream", "upstream", "key", "central",
    "essential", "important", "secondary", "active",
    "marker", "product", "substrate", "component", "hub", "node",
    "intermediate", "part", "step", "cluster", "consequence", "output",
    "presence", "evidence", "involved", "released", "converted",
    "metabolised", "metabolized", "essential",
    # common adjective decorators
    "elevated", "altered", "changed", "concurrent", "first", "committed",
    "downstream", "upstream",
)
_NORM_LEAD_RE = re.compile(
    r"^(?:" + "|".join(re.escape(w) for w in _NORM_LEAD_WORDS) + r")\b[\s,]*",
    re.IGNORECASE,
)
# "X step of Y" → keep Y. Match anywhere in the phrase.
_NORM_STEP_OF_RE = re.compile(
    r"\b(?:committed\s+|first\s+|second\s+|key\s+|catalytic\s+)?step\s+(?:of|in)\s+(.+)$",
    re.IGNORECASE,
)
# Trailing "X de novo Y" → "X Y" (re-order helps RaMP match generic pathway name)
_NORM_DENOVO_RE = re.compile(
    r"\bde[\s-]?novo\s+", re.IGNORECASE,
)
# Pathway-shape suffix words used for synonym swaps.
_NORM_SUFFIX_SWAPS = (
    (re.compile(r"\bsynthesis\b", re.IGNORECASE), "metabolism"),
    (re.compile(r"\bsynthesis\b", re.IGNORECASE), "biosynthesis"),
    (re.compile(r"\bcycle\b", re.IGNORECASE), "metabolism"),
    (re.compile(r"\bpathway\b", re.IGNORECASE), "metabolism"),
    (re.compile(r"\bturnover\b", re.IGNORECASE), "metabolism"),
    (re.compile(r"\bbreakdown\b", re.IGNORECASE), "metabolism"),
    (re.compile(r"\bdegradation\b", re.IGNORECASE), "metabolism"),
)
# Phrases that, after stripping, are too generic / common to trust as a
# pathway label (ambiguous against many RaMP names).
_NORM_REJECT = frozenset({
    "metabolism", "biosynthesis", "synthesis", "pathway", "pathways",
    "cycle", "cycles", "degradation", "catabolism", "anabolism",
    "signaling", "signalling", "production", "turnover", "breakdown",
    "balance", "homeostasis", "flux", "regulation", "activation",
    "inhibition",
})


def _normalise_phrase(raw: str | None) -> list[str]:
    """Generate candidate normalised pathway phrases from a noisy LLM output.

    Used by ``verify_biological_sub6`` after the existing ``_first_phrase``
    pass fails to resolve. The caller tries each candidate in order against
    ``ground_truth_pathway`` / ``top_pathways`` / RaMP fuzzy lookup; the
    first one that resolves wins.

    Strategy:
      1. Strip leading prepositional / verb-frame stop-words greedily.
      2. If the residual contains an "X step of/in Y" fragment, also try
         ``Y`` alone (LLM phrasing on Phase A narratives often buries the
         RaMP-resolvable noun in a subordinate clause).
      3. Synonym substitutions on suffix words —
         ``synthesis``/``cycle``/``pathway`` → ``metabolism`` —
         to bridge between v7-phaseA wording ("purine de-novo synthesis")
         and RaMP's aggregation level ("Purine metabolism").
      4. Reject candidates whose stripped form is < 5 chars or in the
         too-generic set (``metabolism``, ``cycle``, ``synthesis`` alone).

    Returns a deduplicated list of candidate strings, longest-and-earliest-
    win on iteration. Returns ``[]`` when ``raw`` is empty / nothing
    survives the filters.
    """
    if not raw:
        return []
    text = (raw or "").strip()
    if not text:
        return []

    candidates: list[str] = []

    def _add(p: str) -> None:
        p = (p or "").strip(" ,.;:")
        if not p:
            return
        if len(p) < 5:
            return
        if p.lower() in _NORM_REJECT:
            return
        if any(c.lower() == p.lower() for c in candidates):
            return
        candidates.append(p)

    # 1. Always try the original — keeps backward compat (if it already
    #    resolved we wouldn't be here, but the caller stops at the first
    #    successful match anyway).
    _add(text)

    # 2. Greedy leading-strip — keep removing leading stop-words.
    #    Cap iterations at 8 to be safe against a pathological input.
    s = text
    for _ in range(8):
        new = _NORM_LEAD_RE.sub("", s, count=1)
        if new == s:
            break
        s = new
    if s != text:
        _add(s)

    # 3. "step of/in Y" → also try Y.
    m = _NORM_STEP_OF_RE.search(text)
    if m:
        captured = m.group(1).strip()
        captured = _NORM_DENOVO_RE.sub("", captured).strip(" ,.;:")
        _add(captured)
    # Also on the leading-stripped form, in case "step of" survived the
    # lead-strip.
    m = _NORM_STEP_OF_RE.search(s)
    if m:
        captured = m.group(1).strip()
        captured = _NORM_DENOVO_RE.sub("", captured).strip(" ,.;:")
        _add(captured)

    # 4. Drop "de novo" / "de-novo" qualifiers anywhere — RaMP's
    #    aggregated names don't carry them.
    no_denovo = _NORM_DENOVO_RE.sub("", s).strip(" ,.;:")
    if no_denovo != s:
        _add(no_denovo)

    # 5. Suffix synonym swaps on the most-stripped form.
    base = candidates[-1] if candidates else s
    for pat, replacement in _NORM_SUFFIX_SWAPS:
        if pat.search(base):
            swapped = pat.sub(replacement, base, count=1)
            if swapped.lower() != base.lower():
                _add(swapped)

    # 6. Drop the original from the front if we have a stripped version —
    #    callers prefer the cleaner candidate (it's more likely to resolve).
    if len(candidates) >= 2 and candidates[0].lower() == text.lower():
        head, tail = candidates[0], candidates[1:]
        # Promote the first non-trivial stripped variant ahead of the raw
        # input so the caller exhausts cheap fuzzy lookups first.
        return tail + [head]
    return candidates


# ---------------------------------------------------------------------------
# Phase B Fix-2: _reverse_fuzz_pathway
# ---------------------------------------------------------------------------


# Pathway sources we trust — drops `pfocr` (paper-title noise from PMC
# enrichment hits, e.g. "Outline of the sterol biosynthetic pathway in
# yeast..."). HMDB carries SMPDB-derived names which are mostly real
# pathways with some disease-name noise — included but filtered downstream
# by `_REV_FUZZ_NAME_REJECT_RE`.
_REV_FUZZ_TYPES = ("kegg", "reactome", "wiki", "hmdb")

# Reject RaMP rows whose name looks like a disease / drug-action / paper
# title. The reverse-fuzz heuristic would otherwise stem-match these
# spuriously (e.g. "Methylation" -> any text mentioning methylation).
_REV_FUZZ_NAME_REJECT_RE = re.compile(
    r"\b(?:"
    r"deficien(?:cy|cies)|disease|disorder|syndrome|aciduria|"
    r"alkaptonuria|tyrosinemia|argininemia|citrullinemia|galactosemia|"
    r"phenylketonuria|hyperprolinemia|aminoaciduria|"
    r"action\s+pathway|drug\s+pathway|"
    # paper-title shapes
    r"outline\s+of|incorporation\s+characteristics|"
    r"intersection\s+of|study\s+of|relationship\s+between"
    r")\b",
    re.IGNORECASE,
)

# Stems we never count as "this stem appeared in the claim text" because
# they appear in nearly every metabolic narrative or are too generic.
_REV_FUZZ_GENERIC_STEMS = frozenset({
    "metabolism", "metabolic", "pathway", "pathways", "biosynthesis",
    "synthesis", "degradation", "catabolism", "anabolism", "cycle",
    "cycles", "signaling", "signalling", "reactions", "reaction",
    "interconversion", "transport", "uptake", "secretion", "process",
    "processes", "derivative", "derivatives",
    # stop-words common in titles (in case the reject regex misses)
    "disease", "disorder", "syndrome", "deficiency", "action",
    "outline", "study", "analysis", "intersection", "incorporation",
    "characteristics", "relationship",
    # filler
    "compound", "compounds", "general", "between", "during", "through",
    "downstream", "upstream", "secondary", "primary",
    # Token names common in biology that are too generic
    "human", "humans", "tissue", "tissues", "cellular", "system",
    "regulation", "factor", "level", "levels",
    # Process-name pathways in RaMP HMDB that mostly act as ontology
    # categories rather than discriminative pathway labels.
    "methylation", "phosphorylation", "glycosylation", "oxidation",
    "reduction", "hydrolysis", "isomerization", "transamination",
    "carboxylation", "decarboxylation", "deamination",
})


def _reverse_fuzz_pathway(
    *,
    claim_text: str,
    compound_kegg_id: str,
    ramp_cursor,
    top_n: int = 50,
    min_stem_len: int = 6,
) -> tuple[str, str] | None:
    """Compound-side reverse fuzz: the LLM names a pathway by partial stem
    rather than by RaMP's aggregated name; scan the compound's known
    pathways for any whose stem appears in the claim text.

    Strategy:
      1. Pull the compound's pathways from RaMP (``analytehaspathway`` →
         ``pathway``) restricted to ``_REV_FUZZ_TYPES`` (KEGG / Reactome
         / Wiki / HMDB; drops PFOCR paper noise).
      2. Reject pathway names that look like disease / drug-action /
         paper titles via ``_REV_FUZZ_NAME_REJECT_RE``.
      3. For each surviving pathway, extract distinct ≥``min_stem_len``-
         char alphabetic stems, drop generics from
         ``_REV_FUZZ_GENERIC_STEMS``.
      4. Word-bounded match each stem against ``claim_text``
         (case-insensitive). A pathway "matches" when at least one stem
         hits.
      5. Score each match: ``(longest matched stem chars, # matched stems)``;
         return the highest-scoring pathway.

    Returns ``(pathway_name, matched_stem)`` of the best match, or
    ``None`` when the compound has no eligible pathway after filtering or
    no stem matches.
    """
    if not claim_text or not compound_kegg_id:
        return None
    keg = compound_kegg_id.replace("cpd:", "").strip()
    if not keg:
        return None

    placeholders = ",".join(["?"] * len(_REV_FUZZ_TYPES))
    sql = (
        "SELECT DISTINCT p.pathwayName, s.pathwayCount "
        "FROM source s "
        "JOIN analytehaspathway ahp ON s.rampId = ahp.rampId "
        "JOIN pathway p ON ahp.pathwayRampId = p.pathwayRampId "
        f"WHERE s.sourceId IN (?, ?) AND p.type IN ({placeholders}) "
        "ORDER BY s.pathwayCount DESC "
        "LIMIT ?"
    )
    params = (
        f"kegg:{keg}",
        f"kegg:{keg.lower()}",
        *_REV_FUZZ_TYPES,
        int(top_n),
    )
    try:
        rows = list(ramp_cursor.execute(sql, params))
    except Exception as exc:  # pragma: no cover - defensive on schema drift
        logger.debug("biological_sub6 reverse_fuzz: query failed: %s", exc)
        return None

    seen_names: set[str] = set()
    best: tuple[int, int, str, str] | None = None  # (longest, hit_count, name, stem)

    for row in rows:
        name = (row[0] or "").strip()
        if not name or name.lower() in seen_names:
            continue
        seen_names.add(name.lower())
        if _REV_FUZZ_NAME_REJECT_RE.search(name):
            continue

        # Extract distinct stems ≥ min_stem_len.
        stems = []
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9-]*", name):
            if len(tok) < min_stem_len:
                continue
            if tok.lower() in _REV_FUZZ_GENERIC_STEMS:
                continue
            stems.append(tok)
        if not stems:
            continue

        # Word-bounded match against claim_text.
        matched = []
        for stem in stems:
            if re.search(r"\b" + re.escape(stem) + r"\b", claim_text, re.IGNORECASE):
                matched.append(stem)
        if not matched:
            continue

        longest = max(len(m) for m in matched)
        score = (longest, len(matched), name, matched[0])
        if best is None or score[:2] > best[:2]:
            best = score

    if best is None:
        return None
    _longest, _n, name, stem = best
    return name, stem
