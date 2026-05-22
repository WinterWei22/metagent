"""W12 D2 RED — verifier/layers/set_enrichment.py fuzzy + cross-walk (6 cases, side dish).

C7 namespace_form holds 2/226 (0.9%) SET_ENRICHMENT claims plus a
strategically valuable token-Jaccard + metanetx-cross-walk infrastructure
that future C3 / C1+C2 sprints will reuse. Spec §1 D4 schedules a
⚠️-modify on verifier/layers/set_enrichment.py (B1 D2 commit 2354011
territory); the GREEN commit body must carry
``[verifier-modify-warning]`` plus B1 test no-regression evidence.

Current Layer 6a cascade (verifier/layers/set_enrichment.py:78):
  Stage 1 — exact ID match (regression case 1 anchors this)
  Stage 2 — substring fuzzy (claim ⊂ canonical OR canonical ⊂ claim)
  Stage 3 — canonical name in claim text
  Stage 4 — UNVERIFIABLE_V0

Target post-GREEN cascade adds:
  Stage 2.5 — token-Jaccard ≥ 0.5 via concord/analyze/pathway_match.py
  Stage 3.5 — namespace cross-walk via data/concord/metanetx.sqlite

Expected at RED commit:
  - case 1 (exact ID match) PASS (regression)
  - case 6 (empty enrichment UV) PASS (regression)
  - case 5 (cross-walk no mapping) MAY pass (current code falls through to
    UV anyway, but for a different reason — substring miss not cross-walk
    miss). Marked regression for spec parity but not strictly diagnostic.
  - case 2, 3, 4 FAIL (no fuzzy / no cross-walk yet)
"""
from __future__ import annotations

import pytest

from schemas.sub6_report import SubsixSourceReport
from verifier.layers.set_enrichment import verify_set_enrichment
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _claim(
    text: str,
    *,
    pathway_name: str | None = None,
    pathway_id: str | None = None,
) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_text=text,
        claim_type=ClaimType.SET_ENRICHMENT,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(
            pathway_name=pathway_name,
            pathway_id=pathway_id,
        ),
    )


def _task_with_top_pathway(
    pathway_id: str = "RAMP_P_000000106",
    pathway_name: str = "Tyrosine metabolism",
    external_id: str | None = "map00350",
) -> SubsixSourceReport:
    """Minimal sub6 task with one top_pathways entry."""
    return SubsixSourceReport(
        task_id="w12_fuzzy_test",
        task_type="compound_only_enrichment",
        ground_truth_pathway={
            "pathway_id": pathway_id,
            "pathway_name": pathway_name,
        },
        ground_truth_signal_compounds=[],
        ground_truth_noise_compounds=[],
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": pathway_id,
                    "pathway_name": pathway_name,
                    "pathway_external_id": external_id,
                    "pathway_source": "kegg",
                    "fdr": 1e-10,
                    "matched_compounds": [],
                    "total_pathway_compounds": 50,
                }
            ],
        },
    )


def _task_empty_enrichment() -> SubsixSourceReport:
    return SubsixSourceReport(
        task_id="w12_fuzzy_empty",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "X", "pathway_name": "Y"},
        ground_truth_signal_compounds=[],
        ground_truth_noise_compounds=[],
        ramp_enrichment_result={"top_pathways": []},
    )


# ---------------------------------------------------------------------------
# 6 RED cases
# ---------------------------------------------------------------------------


def test_exact_match_pathway_id_supported():
    """Case 1 (regression) — exact pathway_id match → SUPPORTED.

    Current Stage 1 already handles this. Expected at RED: PASS.
    """
    task = _task_with_top_pathway(pathway_id="RAMP_P_000000106")
    claim = _claim(
        "Tyrosine metabolism is the dominant enriched pathway (RAMP_P_000000106).",
        pathway_name="Tyrosine metabolism",
        pathway_id="RAMP_P_000000106",
    )
    result = verify_set_enrichment(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_fuzzy_name_token_jaccard_above_threshold_supported():
    """Case 2 — token-Jaccard fuzzy name match ≥ 0.5 → SUPPORTED.

    Claim names "Arachidonate eicosanoid pathway" while enrichment top
    pathway is "Arachidonic acid metabolism". After stop-word strip
    ({metabolism, pathway, biosynthesis, ...}) tokens become:
       claim:   {arachidonate, eicosanoid}
       canon:   {arachidonic, acid}
    Jaccard = 0/4 = 0  — would fall through. Use closer pair instead:
       claim:   "Arachidonic acid eicosanoid biosynthesis"  → {arachidonic, acid, eicosanoid}
       canon:   "Arachidonic acid metabolism"                → {arachidonic, acid}
    Jaccard = 2/3 = 0.67 → SUPPORTED.

    Current code (substring fuzzy) won't match these because "Arachidonic
    acid metabolism" is not a substring of "Arachidonic acid eicosanoid
    biosynthesis" nor vice versa. Expected at RED: FAIL.
    """
    task = _task_with_top_pathway(
        pathway_id="HSA00590",
        pathway_name="Arachidonic acid metabolism",
        external_id="hsa00590",
    )
    claim = _claim(
        "Arachidonic acid eicosanoid biosynthesis is enriched.",
        pathway_name="Arachidonic acid eicosanoid biosynthesis",
        pathway_id=None,
    )
    result = verify_set_enrichment(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_fuzzy_match_below_threshold_falls_through():
    """Case 3 — token-Jaccard < 0.5 must NOT match by fuzzy. Without
    namespace cross-walk it falls through to UV (or CONTRADICTED via
    Stage 4). Asserts the FP defense.

    Claim names "Methionine cycle reactions" vs top pathway "Tyrosine
    metabolism" — content tokens {methionine, cycle, reactions} vs
    {tyrosine}; Jaccard = 0 / 4 = 0 < 0.5 → must fall through.

    Current code substring-fuzzy also misses (different words), then
    Stage 4 returns CONTRADICTED ("not in top_pathways[:10]"). After
    GREEN, the same path must still NOT supported-flag.

    Expected at RED: PASS only if current Stage 4 returns CONTRADICTED
    (not SUPPORTED). This is a defensive regression case.
    """
    task = _task_with_top_pathway(
        pathway_id="RAMP_P_000000106", pathway_name="Tyrosine metabolism"
    )
    claim = _claim(
        "Methionine cycle reactions are the strongest signal here.",
        pathway_name="Methionine cycle reactions",
        pathway_id=None,
    )
    result = verify_set_enrichment(claim, task)
    assert result.verdict != ClaimVerdict.SUPPORTED, (
        f"Methionine cycle should NOT match Tyrosine metabolism via fuzzy; "
        f"got verdict={result.verdict!r}, evidence={result.evidence}"
    )


def test_namespace_crosswalk_via_metanetx_supported():
    """Case 4 — claim names pathway in a non-canonical namespace (e.g.
    MUMM:c21_steroid_hormone_biosynthesis_and_metabolism) while enrichment
    top pathway uses the canonical form (RAMP_P_000050099 / "Steroid
    Hormone Biosynthesis"). After GREEN, the namespace cross-walk via
    data/concord/metanetx.sqlite must resolve both to the same canonical
    pathway → SUPPORTED.

    Current code has no cross-walk; Stage 1-3 all miss; Stage 4 gives UV
    (or CONTRADICTED depending on path). Expected at RED: FAIL.
    """
    task = _task_with_top_pathway(
        pathway_id="RAMP_P_000050099",
        pathway_name="Steroid hormone biosynthesis",
        external_id="wp:WP496",
    )
    claim = _claim(
        "MUMM:c21_steroid_hormone_biosynthesis_and_metabolism is the top hit.",
        pathway_name="c21 steroid hormone biosynthesis and metabolism",
        pathway_id="MUMM:c21_steroid_hormone_biosynthesis_and_metabolism",
    )
    result = verify_set_enrichment(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_namespace_crosswalk_no_mapping_uv():
    """Case 5 — non-canonical namespace pathway_id that has NO metanetx
    mapping → falls through to UV (not falsely SUPPORTED).

    Claim names 'GARBAGE_NS:something_not_mapped' vs canonical 'Tyrosine
    metabolism'. Cross-walk lookup returns None for the GARBAGE_NS prefix
    → must remain UV.

    Current code also gives UV / CONTRADICTED (Stage 4) because Stage 1-3
    miss. The shape of the failure differs (current = "no canonical name
    in claim text" vs GREEN = "cross-walk returned no mapping"), but the
    verdict is the same.

    Expected at RED: MAY PASS (verdict matches by coincidence).
    """
    task = _task_with_top_pathway(
        pathway_id="RAMP_P_000000106", pathway_name="Tyrosine metabolism"
    )
    claim = _claim(
        "GARBAGE_NS:something_not_mapped is the leading paradigm hit.",
        pathway_name="something not mapped",
        pathway_id="GARBAGE_NS:something_not_mapped",
    )
    result = verify_set_enrichment(claim, task)
    assert result.verdict in (
        ClaimVerdict.UNVERIFIABLE_V0,
        ClaimVerdict.CONTRADICTED,
    ), (
        f"Unmappable namespace pathway must not be falsely SUPPORTED; "
        f"got verdict={result.verdict!r}, evidence={result.evidence}"
    )


def test_empty_ramp_enrichment_uv():
    """Case 6 (regression) — empty top_pathways list → UV.

    Layer 6a line 84-92 already returns UNVERIFIABLE_V0 with evidence
    "ramp_enrichment_result.top_pathways is empty or missing". Expected
    at RED: PASS.
    """
    task = _task_empty_enrichment()
    claim = _claim(
        "Some pathway is enriched.",
        pathway_name="Some pathway",
        pathway_id="X",
    )
    result = verify_set_enrichment(claim, task)
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0, result.evidence
