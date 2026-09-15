"""Phase B1 D2 — unit tests for ``verifier.grammar.validate``.

Covers each rule the validator must enforce:

* 4 positive shapes parse cleanly.
* Each of the 5 banned-phrase categories (4 substring + 1 regex)
  triggers a drop with a category-tagged reason.
* Missing or empty required fields surface as ``drop_reason``.
* Generic ``enzyme_or_reaction`` (rejected by pydantic validator).
* Empty ``signal_compound_ids`` (rejected by ``min_length=1``).
* Unknown / non-string / missing ``grammar`` field.
* Empty / non-dict input.

Plus a regression case for the D0 review issue #1: "drives" must NOT
fire the directional ban.
"""
from __future__ import annotations

import pytest

from verifier.grammar import ClaimGrammar, validate


# ---------------------------------------------------------------------------
# Positive cases — one per grammar shape
# ---------------------------------------------------------------------------


def test_validate_pathway_membership_positive() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "L-Methionine is a member of cysteine and methionine metabolism",
        "subject": "L-Methionine",
        "pathway_name": "Cysteine and methionine metabolism",
    })
    assert r.is_valid, r.drop_reason
    assert r.grammar == ClaimGrammar.PATHWAY_MEMBERSHIP


def test_validate_metabolite_pathway_link_positive() -> None:
    r = validate({
        "grammar": "metabolite_pathway_link",
        "claim_text": "Arachidonic acid participates in eicosanoid synthesis via cyclooxygenase 2",
        "subject": "Arachidonic acid",
        "pathway_name": "Eicosanoid synthesis",
        "enzyme_or_reaction": "cyclooxygenase 2 (COX-2)",
    })
    assert r.is_valid, r.drop_reason
    assert r.grammar == ClaimGrammar.METABOLITE_PATHWAY_LINK


def test_validate_pathway_enrichment_positive() -> None:
    r = validate({
        "grammar": "pathway_enrichment",
        "claim_text": "17-beta hydroxysteroid dehydrogenase III deficiency is enriched",
        "term_id": "SMP00408",
        "term_name": "17-Beta Hydroxysteroid Dehydrogenase III Deficiency",
        "term_type": "disease",
        "fdr": 0.0,
        "metabolite_set": ["DHEA", "Androstenedione"],
    })
    assert r.is_valid, r.drop_reason
    assert r.grammar == ClaimGrammar.PATHWAY_ENRICHMENT


def test_validate_driver_metabolite_positive() -> None:
    r = validate({
        "grammar": "driver_metabolite",
        "claim_text": "L-Methionine drives cysteine and methionine metabolism",
        "subject": "L-Methionine",
        "pathway_name": "Cysteine and methionine metabolism",
        "signal_compound_ids": ["L-Methionine", "L-Cystine"],
    })
    assert r.is_valid, r.drop_reason
    assert r.grammar == ClaimGrammar.DRIVER_METABOLITE


# ---------------------------------------------------------------------------
# Banned-phrase categories — one negative per category
# ---------------------------------------------------------------------------


def test_validate_drops_hedge_may() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "L-Methionine may participate in cysteine metabolism",
        "subject": "L-Methionine",
        "pathway_name": "Cysteine and methionine metabolism",
    })
    assert not r.is_valid
    assert "hedge" in (r.drop_reason or "")
    assert "may" in (r.drop_reason or "")


def test_validate_drops_hedge_consistent_with() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "Methionine is consistent with sulfur amino-acid metabolism",
        "subject": "L-Methionine",
        "pathway_name": "Sulfur AA",
    })
    assert not r.is_valid
    assert "consistent with" in (r.drop_reason or "")


def test_validate_drops_directional_upstream() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "L-Methionine is upstream of L-Cysteine in transsulfuration",
        "subject": "L-Methionine",
        "pathway_name": "Transsulfuration",
    })
    assert not r.is_valid
    assert "directional" in (r.drop_reason or "")


def test_validate_drops_directional_two_hop() -> None:
    r = validate({
        "grammar": "metabolite_pathway_link",
        "claim_text": "X is a two-hop neighbour of Y in galactose metabolism",
        "subject": "X",
        "pathway_name": "Galactose metabolism",
        "enzyme_or_reaction": "galactokinase",
    })
    assert not r.is_valid
    assert "two-hop" in (r.drop_reason or "")


def test_validate_drops_abstract_cascade() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "Leukotrienes are part of the inflammatory cascade",
        "subject": "Leukotrienes",
        "pathway_name": "Eicosanoid metabolism",
    })
    assert not r.is_valid
    assert "abstract" in (r.drop_reason or "")
    assert "cascade" in (r.drop_reason or "")


def test_validate_drops_abstract_eicosanoid_cluster() -> None:
    r = validate({
        "grammar": "pathway_enrichment",
        "claim_text": "15-HETE is enriched in the eicosanoid cluster",
        "term_id": "FAKE",
        "term_name": "eicosanoid cluster",
        "term_type": "pathway",
    })
    assert not r.is_valid
    assert "eicosanoid cluster" in (r.drop_reason or "")


def test_validate_drops_meta_limited() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "Conclusions are limited to mapped KEGG compounds",
        "subject": "Conclusions",
        "pathway_name": "general",
    })
    assert not r.is_valid
    assert "meta" in (r.drop_reason or "")


def test_validate_drops_meta_omitted() -> None:
    # Use a sentence that only trips BANNED_META (no abstract /
    # directional / hedge overlap) so the drop_reason is unambiguous.
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "Several pathway claims were omitted in this iteration",
        "subject": "Claims",
        "pathway_name": "general",
    })
    assert not r.is_valid
    assert "meta" in (r.drop_reason or "")


def test_validate_drops_tool_roundtrip_kegg_id() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "L-Methionine has KEGG ID C00073",
        "subject": "L-Methionine",
        "pathway_name": "Methionine metabolism",
    })
    assert not r.is_valid
    assert "tool-roundtrip" in (r.drop_reason or "")


def test_validate_drops_tool_roundtrip_hmdb_id() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "L-Cysteine maps to HMDB0000574",
        "subject": "L-Cysteine",
        "pathway_name": "Cysteine metabolism",
    })
    assert not r.is_valid
    assert "tool-roundtrip" in (r.drop_reason or "")


def test_validate_drops_tool_roundtrip_molecular_formula() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "L-Threonine has molecular formula C4H9NO3",
        "subject": "L-Threonine",
        "pathway_name": "Threonine metabolism",
    })
    assert not r.is_valid
    assert "tool-roundtrip" in (r.drop_reason or "")


# ---------------------------------------------------------------------------
# Required-field violations
# ---------------------------------------------------------------------------


def test_validate_drops_missing_pathway_name() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "L-Methionine is a member of something",
        "subject": "L-Methionine",
    })
    assert not r.is_valid
    assert "pathway_name" in (r.drop_reason or "")


def test_validate_drops_empty_subject() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "Something is a member of a pathway",
        "subject": "   ",
        "pathway_name": "Test",
    })
    assert not r.is_valid
    assert "subject" in (r.drop_reason or "")


def test_validate_drops_missing_enzyme() -> None:
    r = validate({
        "grammar": "metabolite_pathway_link",
        "claim_text": "X participates in Y",
        "subject": "X",
        "pathway_name": "Y",
    })
    assert not r.is_valid
    assert "enzyme_or_reaction" in (r.drop_reason or "")


def test_validate_drops_generic_enzyme() -> None:
    r = validate({
        "grammar": "metabolite_pathway_link",
        "claim_text": "L-Methionine participates in methionine metabolism",
        "subject": "L-Methionine",
        "pathway_name": "Methionine metabolism",
        "enzyme_or_reaction": "metabolism",
    })
    assert not r.is_valid
    # Pydantic field_validator rejects this
    assert "schema validation failed" in (r.drop_reason or "") or \
        "generic" in (r.drop_reason or "")


def test_validate_drops_empty_signal_compound_ids() -> None:
    r = validate({
        "grammar": "driver_metabolite",
        "claim_text": "L-Methionine drives methionine metabolism",
        "subject": "L-Methionine",
        "pathway_name": "Methionine metabolism",
        "signal_compound_ids": [],
    })
    assert not r.is_valid
    assert "signal_compound_ids" in (r.drop_reason or "")


def test_validate_drops_bad_term_type() -> None:
    r = validate({
        "grammar": "pathway_enrichment",
        "claim_text": "Tyrosine metabolism is enriched",
        "term_id": "hsa00350",
        "term_name": "Tyrosine metabolism",
        "term_type": "kegg",  # not in Literal["pathway","disease","reactome","go"]
    })
    assert not r.is_valid


# ---------------------------------------------------------------------------
# Grammar field issues
# ---------------------------------------------------------------------------


def test_validate_drops_unknown_grammar_value() -> None:
    r = validate({
        "grammar": "fancy_new_shape",
        "claim_text": "x",
        "subject": "X",
        "pathway_name": "Y",
    })
    assert not r.is_valid
    assert "fancy_new_shape" in (r.drop_reason or "")


def test_validate_drops_missing_grammar_field() -> None:
    r = validate({
        "claim_text": "x",
        "subject": "X",
        "pathway_name": "Y",
    })
    assert not r.is_valid
    assert "grammar" in (r.drop_reason or "")


def test_validate_drops_non_string_grammar() -> None:
    r = validate({"grammar": 42, "claim_text": "x"})
    assert not r.is_valid
    assert "grammar" in (r.drop_reason or "")


# ---------------------------------------------------------------------------
# claim_text issues
# ---------------------------------------------------------------------------


def test_validate_drops_empty_claim_text() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "   ",
        "subject": "X",
        "pathway_name": "Y",
    })
    assert not r.is_valid
    assert "claim_text" in (r.drop_reason or "")


def test_validate_drops_missing_claim_text() -> None:
    r = validate({
        "grammar": "pathway_membership",
        "subject": "X",
        "pathway_name": "Y",
    })
    assert not r.is_valid
    assert "claim_text" in (r.drop_reason or "")


# ---------------------------------------------------------------------------
# Container shape
# ---------------------------------------------------------------------------


def test_validate_drops_empty_dict() -> None:
    r = validate({})
    assert not r.is_valid
    assert "dict" in (r.drop_reason or "")


def test_validate_drops_non_dict_input() -> None:
    r = validate("not a dict")  # type: ignore[arg-type]
    assert not r.is_valid


# ---------------------------------------------------------------------------
# B1 D2 hotfix (Anomaly #2): context-aware skip for tool-roundtrip regex
# ---------------------------------------------------------------------------


def test_validate_kegg_reaction_id_grounded_in_enzyme_field_passes() -> None:
    """``metabolite_pathway_link`` with the same R-id in both
    ``claim_text`` and ``enzyme_or_reaction`` is the intended shape; it
    must NOT trip BANNED_TOOL_ROUNDTRIP_PATTERNS r'\\bR\\d{5}\\b'."""
    r = validate({
        "grammar": "metabolite_pathway_link",
        "claim_text": "Dehydroepiandrosterone participates in steroid hormone biosynthesis via R00521",
        "subject": "Dehydroepiandrosterone",
        "pathway_name": "Steroid hormone biosynthesis",
        "enzyme_or_reaction": "R00521",
    })
    assert r.is_valid, (
        f"R-id grounded in enzyme_or_reaction must pass; got "
        f"drop_reason={r.drop_reason!r}"
    )


def test_validate_kegg_reaction_id_NOT_grounded_still_drops() -> None:
    """If the R-id appears in claim_text but the enzyme field names
    something else (or is absent), the original BANNED_TOOL_ROUNDTRIP
    behaviour must still fire."""
    r = validate({
        "grammar": "metabolite_pathway_link",
        "claim_text": "Cysteine has KEGG reaction R00521",
        "subject": "Cysteine",
        "pathway_name": "Cysteine metabolism",
        "enzyme_or_reaction": "cystathionine beta-synthase",
    })
    assert not r.is_valid
    assert "tool-roundtrip" in (r.drop_reason or "")


def test_validate_map_id_grounded_in_pathway_name_passes() -> None:
    """KEGG ``mapNNNNN`` IDs appearing in both ``claim_text`` and
    ``pathway_name`` (as part of the human-readable name) must pass —
    this is the canonical Sub-6 narrative shape."""
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "Galactose is a member of map00052",
        "subject": "Galactose",
        "pathway_name": "Galactose metabolism (map00052)",
    })
    assert r.is_valid, (
        f"map-id grounded in pathway_name must pass; got "
        f"drop_reason={r.drop_reason!r}"
    )


def test_validate_molecular_formula_NOT_grounded_drops() -> None:
    """Hill-notation formula ``C5H11NO2S`` does not belong in any
    grammar v2 structured field — appearance in claim_text is a
    classic tool-roundtrip and must still be banned."""
    r = validate({
        "grammar": "pathway_membership",
        "claim_text": "L-Methionine has molecular formula C5H11NO2S",
        "subject": "L-Methionine",
        "pathway_name": "Cysteine and methionine metabolism",
    })
    assert not r.is_valid
    assert "tool-roundtrip" in (r.drop_reason or "")


# ---------------------------------------------------------------------------
# Regression: D0 issue #1 — drives / driving must NOT be banned
# ---------------------------------------------------------------------------


def test_validate_does_not_ban_drives_verb() -> None:
    """If this fails, BANNED_DIRECTIONAL caught the canonical
    driver_metabolite verb again (D0 review issue #1)."""
    r = validate({
        "grammar": "driver_metabolite",
        "claim_text": "Arachidonic acid drives arachidonic acid metabolism",
        "subject": "Arachidonic acid",
        "pathway_name": "Arachidonic acid metabolism",
        "signal_compound_ids": ["Arachidonic acid", "15-HETE"],
    })
    assert r.is_valid, (
        f"`drives` triggered drop_reason={r.drop_reason!r} — "
        "BANNED_DIRECTIONAL must NOT include drives/driving"
    )
