"""Unit tests for ``verifier.source_lookup``."""
from __future__ import annotations

from verifier.source_lookup import find_candidate_by_name, lookup


# ---------------------------------------------------------------------------
# lookup()
# ---------------------------------------------------------------------------


def test_lookup_nested_attribute_path(glucose_report):
    v, ok = lookup(glucose_report, "candidates[0].metabolite_info.molecular_formula")
    assert ok is True
    assert v == "C6H12O6"


def test_lookup_top_level_attribute(glucose_report):
    v, ok = lookup(glucose_report, "neutral_mass_computed")
    assert ok is True
    assert v == 180.0634


def test_lookup_dict_key(glucose_report):
    v, ok = lookup(glucose_report, "candidates[0].metabolite_info.cross_refs[hmdb]")
    assert ok is True
    assert v == "HMDB0250761"


def test_lookup_top_level_dict(glucose_report):
    v, ok = lookup(glucose_report, "tool_versions[cfm-id]")
    assert ok is True
    assert v == "cfm-id-4.4.7"


def test_lookup_nonexistent_attribute(glucose_report):
    v, ok = lookup(glucose_report, "candidates[0].metabolite_info.bogus_field")
    assert ok is False
    assert v is None


def test_lookup_index_out_of_range(glucose_report):
    v, ok = lookup(glucose_report, "candidates[99].candidate.name")
    assert ok is False
    assert v is None


def test_lookup_through_none_intermediate_returns_not_existed(glucose_report):
    # candidates[1] (Glucose in this fixture) has pathway_context=None.
    # Walking through it should return (None, False), not raise.
    v, ok = lookup(glucose_report, "candidates[1].pathway_context.pathways[0].id")
    assert ok is False
    assert v is None


def test_lookup_empty_path_returns_miss(glucose_report):
    v, ok = lookup(glucose_report, "")
    assert ok is False
    assert v is None


def test_lookup_missing_dict_key(glucose_report):
    v, ok = lookup(glucose_report, "candidates[0].metabolite_info.cross_refs[nonexistent]")
    assert ok is False
    assert v is None


# ---------------------------------------------------------------------------
# find_candidate_by_name()
# ---------------------------------------------------------------------------


def test_find_exact_name(glucose_report):
    cr, i = find_candidate_by_name(glucose_report, "D-Gulose")
    assert i == 0
    assert cr.candidate.name == "D-Gulose"


def test_find_case_insensitive(glucose_report):
    cr, i = find_candidate_by_name(glucose_report, "d-gulose")
    assert i == 0


def test_find_synonym(glucose_report):
    # "Gulose" is listed as a synonym; should match via synonyms first,
    # but fuzzy substring on candidate.name also works.
    cr, i = find_candidate_by_name(glucose_report, "Gulose")
    assert i == 0


def test_find_primary_name_via_metabolite_info(caffeine_report):
    cr, i = find_candidate_by_name(caffeine_report, "1,3,7-trimethylxanthine")
    assert i == 0
    assert cr.candidate.name == "Caffeine"


def test_find_miss(glucose_report):
    cr, i = find_candidate_by_name(glucose_report, "Theobromine")
    assert cr is None and i is None


def test_find_empty_name(glucose_report):
    cr, i = find_candidate_by_name(glucose_report, "")
    assert cr is None and i is None
