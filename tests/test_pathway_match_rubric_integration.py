"""Integration tests for the RaMP-backed pathway matcher (A1).

Skipped unless ramp.sqlite and the gold registry are present.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.metagent.pathway_match_rubric import MatchTier, build_matcher

_DB = os.environ.get("RAMP_DB_PATH", "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite")
_REG = "data/benchmark/pathway_registry/gold_registry.json"

pytestmark = pytest.mark.skipif(
    not (Path(_DB).exists() and Path(_REG).exists()),
    reason="RaMP DB or gold registry not available",
)


@pytest.fixture(scope="module")
def matcher():
    return build_matcher(_DB, _REG)


def test_gold_predicted_same_pathway_is_exact(matcher):
    # Agent's KEGG-style name for the gold pathway -> EXACT.
    r = matcher.match(predicted="Citric Acid Cycle", gold="Citrate cycle (TCA cycle)")
    assert r.tier is MatchTier.EXACT


def test_propanoate_predicted_bcaa_is_adjacent_not_strict(matcher):
    # The documented soft case: propanoate gold, agent predicts BCAA degradation.
    r = matcher.match(
        predicted="Valine, leucine and isoleucine degradation",
        gold="Propanoate metabolism",
    )
    assert r.tier is MatchTier.ADJACENT
    assert r.lenient_credit and not r.strict_credit


def test_unrelated_prediction_is_miss(matcher):
    r = matcher.match(predicted="Caffeine metabolism", gold="Lysine degradation")
    assert r.tier is MatchTier.MISS


def test_empty_prediction_is_miss(matcher):
    r = matcher.match(predicted="", gold="Propanoate metabolism")
    assert r.tier is MatchTier.MISS


def test_gold_resolves_via_registry_kegg_id(matcher):
    # Predicted given as a KEGG map id resolves directly.
    r = matcher.match(predicted="map00020", gold="Citrate cycle (TCA cycle)")
    assert r.tier is MatchTier.EXACT
