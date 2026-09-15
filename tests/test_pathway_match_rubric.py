"""Phase A — graded pathway matcher (A1).

Tier logic is tested deterministically with an injected fake resolver so the
RaMP DB is not required for unit tests. The resolver contract:

    resolver.resolve(name_or_id) -> PathwayEntry(ramp_id, normalized_name, metabolites: frozenset[str])
    resolver.discriminative(metabolite_id) -> bool   # rare metabolite (few pathways)

MatchTier ordering (strict short-circuit): EXACT > PARENT_CHILD > ADJACENT > MISS.
strict credit = {EXACT, PARENT_CHILD}; lenient credit adds ADJACENT.
"""
from __future__ import annotations

import pytest

from scripts.metagent.pathway_match_rubric import (
    MatchTier,
    PathwayEntry,
    PathwayMatcher,
)


class FakeResolver:
    """In-memory resolver: name/id -> PathwayEntry, plus a discriminative set."""

    def __init__(self, entries: dict[str, PathwayEntry], discriminative: set[str] | None = None):
        self._entries = entries
        self._discriminative = discriminative or set()

    def resolve(self, name_or_id: str) -> PathwayEntry | None:
        return self._entries.get(name_or_id)

    def discriminative(self, metabolite_id: str) -> bool:
        return metabolite_id in self._discriminative


def _entry(ramp_id: str, name: str, mets: set[str]) -> PathwayEntry:
    return PathwayEntry(ramp_id=ramp_id, normalized_name=name, metabolites=frozenset(mets))


def test_identical_pathway_is_exact():
    # Same underlying pathway resolves to the same ramp_id -> EXACT regardless of surface name.
    tca = _entry("RAMP_TCA", "citrate cycle tca cycle", {"citrate", "succinate", "fumarate", "malate"})
    resolver = FakeResolver({
        "TCA cycle": tca,
        "Citrate cycle (TCA cycle)": tca,
    })
    matcher = PathwayMatcher(resolver)
    result = matcher.match(predicted="TCA cycle", gold="Citrate cycle (TCA cycle)")
    assert result.tier is MatchTier.EXACT


def test_cross_source_same_pathway_is_exact_by_metabolite_identity():
    # Different sources give different ramp_ids but near-identical metabolite sets
    # (e.g. KEGG "Citrate cycle (TCA cycle)" vs WikiPathways "Citric Acid Cycle").
    # Both-way containment ~1.0 -> EXACT.
    core = {"citrate", "aconitate", "isocitrate", "a-ketoglutarate", "succinyl-coa",
            "succinate", "fumarate", "malate", "oxaloacetate"}  # 9 shared
    kegg_tca = _entry("RAMP_KEGG_TCA", "citrate cycle tca cycle", core | {"co2"})       # 10
    wiki_tca = _entry("RAMP_WIKI_TCA", "citric acid cycle", core | {"gtp"})             # 10, both-way 9/10=0.9
    resolver = FakeResolver({"Citric Acid Cycle": wiki_tca, "Citrate cycle (TCA cycle)": kegg_tca})
    matcher = PathwayMatcher(resolver)
    result = matcher.match(predicted="Citric Acid Cycle", gold="Citrate cycle (TCA cycle)")
    assert result.tier is MatchTier.EXACT


def test_submodule_is_parent_child():
    # A predicted sub-module whose metabolites are (nearly) a subset of the broad gold
    # pathway, but the reverse containment is low -> PARENT_CHILD, not EXACT.
    child = _entry("RAMP_BCAA_DEG", "valine leucine and isoleucine degradation",
                   {"valine", "leucine", "isoleucine", "2-oxoisovalerate", "isovaleryl-coa"})  # 5
    parent = _entry("RAMP_AA_META", "amino acid metabolism",
                    {"valine", "leucine", "isoleucine", "2-oxoisovalerate", "isovaleryl-coa",
                     "glycine", "serine", "alanine", "aspartate", "glutamate",
                     "phenylalanine", "tyrosine", "methionine", "lysine", "arginine"})  # 15
    resolver = FakeResolver({"BCAA degradation": child, "Amino acid metabolism": parent})
    matcher = PathwayMatcher(resolver)
    # predicted broad parent when gold is the specific child (or vice versa) -> PARENT_CHILD
    result = matcher.match(predicted="Amino acid metabolism", gold="BCAA degradation")
    assert result.tier is MatchTier.PARENT_CHILD


def test_propanoate_bcaa_shared_specific_is_adjacent():
    # propanoate metabolism and BCAA degradation are distinct pathways (low overlap)
    # but share specific (non-hub) intermediates propionyl-CoA + methylmalonate
    # -> biologically ADJACENT. Must be lenient-only credit (NOT strict), per Option C.
    bcaa = _entry("RAMP_BCAA", "valine leucine and isoleucine degradation",
                  {"valine", "leucine", "isoleucine", "2-oxoisovalerate",
                   "isovaleryl-coa", "3-methylbutyryl-coa", "propionyl-coa", "methylmalonate"})  # 8
    propanoate = _entry("RAMP_PROP", "propanoate metabolism",
                        {"propionyl-coa", "methylmalonyl-coa", "methylmalonate",
                         "2-methylcitrate", "propionate", "acetyl-coa"})  # 6; share propionyl-coa + methylmalonate
    resolver = FakeResolver(
        {"BCAA degradation": bcaa, "Propanoate metabolism": propanoate},
        discriminative={"propionyl-coa", "methylmalonate", "2-methylcitrate"},  # acetyl-coa is a hub, excluded
    )
    matcher = PathwayMatcher(resolver)  # default k_specific=2
    result = matcher.match(predicted="BCAA degradation", gold="Propanoate metabolism")
    assert result.tier is MatchTier.ADJACENT
    assert result.lenient_credit is True
    assert result.strict_credit is False


def test_single_shared_specific_metabolite_is_not_adjacent():
    # Sharing only ONE specific metabolite (< k_specific=2) is not enough for ADJACENT.
    a = _entry("A", "pathway a", {"x1", "x2", "x3", "shared1"})
    b = _entry("B", "pathway b", {"y1", "y2", "y3", "shared1"})
    resolver = FakeResolver({"A": a, "B": b}, discriminative={"shared1"})
    matcher = PathwayMatcher(resolver)
    assert matcher.match("A", "B").tier is MatchTier.MISS


def test_unrelated_pathways_are_miss():
    caffeine = _entry("RAMP_CAFF", "caffeine metabolism",
                      {"caffeine", "theobromine", "paraxanthine", "theophylline", "xanthine"})
    lysine = _entry("RAMP_LYS", "lysine degradation",
                    {"lysine", "saccharopine", "aminoadipate", "glutaryl-coa", "crotonyl-coa"})
    resolver = FakeResolver({"Caffeine Metabolism": caffeine, "Lysine degradation": lysine},
                            discriminative={"saccharopine", "glutaryl-coa", "paraxanthine"})
    matcher = PathwayMatcher(resolver)
    result = matcher.match(predicted="Caffeine Metabolism", gold="Lysine degradation")
    assert result.tier is MatchTier.MISS
    assert result.strict_credit is False and result.lenient_credit is False


def test_shared_ubiquitous_metabolite_is_not_adjacent():
    # Two unrelated pathways sharing only a common cofactor (acetyl-CoA, NOT discriminative)
    # must NOT be judged ADJACENT — guards against ubiquitous-metabolite false positives.
    p1 = _entry("RAMP_P1", "fatty acid biosynthesis",
                {"acetyl-coa", "malonyl-coa", "palmitate", "stearate", "myristate"})
    p2 = _entry("RAMP_P2", "sterol biosynthesis",
                {"acetyl-coa", "mevalonate", "squalene", "lanosterol", "cholesterol"})
    resolver = FakeResolver({"FA biosynthesis": p1, "Sterol biosynthesis": p2},
                            discriminative={"palmitate", "squalene", "mevalonate"})  # acetyl-coa NOT here
    matcher = PathwayMatcher(resolver)
    result = matcher.match(predicted="FA biosynthesis", gold="Sterol biosynthesis")
    assert result.tier is MatchTier.MISS


@pytest.mark.parametrize("dc", [-0.05, 0.0, 0.05])
def test_clearcut_cases_robust_to_threshold_perturbation(dc):
    # EXACT / MISS clear-cut cases must not flip under ±0.05 containment-threshold jitter.
    core = {f"m{i}" for i in range(10)}
    same_a = _entry("A1", "p", core)
    same_b = _entry("A2", "p", core)  # identical -> EXACT
    far_a = _entry("F1", "x", {"a", "b", "c", "d"})
    far_b = _entry("F2", "y", {"w", "x", "y", "z"})  # disjoint -> MISS
    resolver = FakeResolver({"EA": same_a, "EB": same_b, "FA": far_a, "FB": far_b})
    matcher = PathwayMatcher(resolver, tau_exact=0.9 + dc, tau_containment=0.7 + dc)
    assert matcher.match("EA", "EB").tier is MatchTier.EXACT
    assert matcher.match("FA", "FB").tier is MatchTier.MISS
