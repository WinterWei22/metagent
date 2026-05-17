"""W7 D1/D2 — Gate-2 metric variant unit tests."""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.analyze.gate2_variants import (
    metric_v1_cohort, metric_v2_cohort, metric_v3_cohort,
    _fuzzy_consensus_top_v1, _weighted_top_v3, _consensus_top_v2,
    variant_verdict,
)


def _mk_row(method_names: dict[str, list[str]],
             gt_name: str = "Glycolysis Gluconeogenesis") -> dict:
    row = {"task_id": "t", "ground_truth_pathway_name": gt_name}
    for m, names in method_names.items():
        row[m] = {"pathways": [{"pathway_name": n} for n in names]}
    return row


# ---------------------------------------------------------------------------
# V1 — token-Jaccard fuzzy intersection
# ---------------------------------------------------------------------------


def test_v1_happy_path_two_paradigms_agree():
    row = _mk_row({
        "sspa_ora": ["Glycolysis Gluconeogenesis"],
        "mummichog": ["Glycolysis Gluconeogenesis"],
    })
    top = _fuzzy_consensus_top_v1(row, threshold=0.5)
    assert any("glycolysis" in n.lower() for n in top), \
        f"expected glycolysis in consensus, got {top}"


def test_v1_strict_vs_fuzzy_lift():
    # Same biology, slightly different naming → strict fails, fuzzy passes.
    row = _mk_row({
        "ramp": ["Arachidonic acid metabolism"],
        "mummichog": ["Arachidonic acid biosynthesis"],
    })
    fuzzy = _fuzzy_consensus_top_v1(row, threshold=0.5)
    assert len(fuzzy) >= 1, "fuzzy should connect 'metabolism' vs 'biosynthesis' variants"


def test_v1_stopword_doesnt_force_match():
    # Both contain 'metabolism' (a stopword) but nothing else common → no overlap
    row = _mk_row({
        "ramp": ["Lipid metabolism"],
        "mummichog": ["Carbohydrate metabolism"],
    })
    fuzzy = _fuzzy_consensus_top_v1(row, threshold=0.5)
    assert fuzzy == [], "stopword-only overlap should not produce consensus"


def test_v1_false_positive_ascorbate_vs_tyrosine_rejected():
    # The W6 sanity Check 2 false positive: 'ascorbate' vs 'tyrosine' have no
    # token overlap → fuzzy correctly rejects (the W6 strict-normalize bug was
    # different — it normalized punctuation and accidentally string-matched
    # other names; our token-Jaccard catches none of that).
    row = _mk_row({
        "ramp": ["Ascorbate and aldarate metabolism"],
        "mummichog": ["Tyrosine metabolism"],
    })
    fuzzy = _fuzzy_consensus_top_v1(row, threshold=0.5)
    assert fuzzy == [], f"ascorbate vs tyrosine should not consensus, got {fuzzy}"


def test_v1_cohort_lift_when_consensus_hits_gt():
    rows = [_mk_row({
        "ramp": ["Lipid metabolism"],  # baseline misses
        "sspa_ora": ["Glycolysis Gluconeogenesis"],
        "mummichog": ["Glycolysis Gluconeogenesis"],
    }, gt_name="Glycolysis Gluconeogenesis") for _ in range(10)]
    m = metric_v1_cohort(rows)
    assert m["cond_b"]["mean_precision"] > m["cond_a"]["mean_precision"]


# ---------------------------------------------------------------------------
# V2 — compound-level membership
# ---------------------------------------------------------------------------


def test_v2_pathway_member_overlap_supports_pathway():
    row = _mk_row({
        "ramp": ["Alanine, aspartate and glutamate metabolism"],
    }, gt_name="Alanine, aspartate and glutamate metabolism")
    # Use a faked input set that overlaps the real HUMAN1 pathway members.
    # HUMAN1:alanine_aspartate_and_glutamate_metabolism has CHEBI:17544,
    # CHEBI:16015, CHEBI:15570, CHEBI:15422, ... (verified at ETL time)
    inp = {"t": {"CHEBI:17544", "CHEBI:16015", "CHEBI:15570"}}
    top = _consensus_top_v2(row, inp["t"], min_overlap=2, top_n=10)
    # Any of the top-10 pathway names should match the GT (which itself is in
    # ramp's top-10), via name-fuzzy.
    assert len(top) >= 1


def test_v2_missing_membership_doesnt_crash():
    row = _mk_row({"ramp": ["A pathway with no member table entry"]})
    inp = {"CHEBI:99999"}
    top = _consensus_top_v2(row, inp, min_overlap=2)
    assert top == []


def test_v2_min_overlap_boundary():
    row = _mk_row({"ramp": ["Alanine, aspartate and glutamate metabolism"]})
    inp_lo = {"CHEBI:17544"}                  # 1 member
    inp_hi = {"CHEBI:17544", "CHEBI:16015"}   # 2 members
    assert _consensus_top_v2(row, inp_lo, min_overlap=2) == []
    assert len(_consensus_top_v2(row, inp_hi, min_overlap=2)) >= 1


def test_v2_cohort_independent_of_v1():
    """V2 metric should be computable without invoking V1."""
    rows = [_mk_row({"ramp": ["Glycolysis Gluconeogenesis"]},
                      gt_name="Glycolysis Gluconeogenesis")]
    m = metric_v2_cohort(rows, task_input_chebi={"t": set()})
    assert "metric_pass" in m


# ---------------------------------------------------------------------------
# V3 — paradigm-weighted soft score (rank-weighted union)
# ---------------------------------------------------------------------------


def test_v3_weighted_top_prefers_multi_method_support():
    row = _mk_row({
        # 'X' appears at rank 0 in 3 methods → very high score
        "sspa_ora": ["X", "Y", "Z"],
        "ramp": ["X", "A", "B"],
        "PSEA": ["X", "C", "D"],
        # 'Z' appears at rank 2 only in sspa → low score
    })
    top = _weighted_top_v3(row)
    assert top[0] == "X", f"X must rank #1 in weighted union, got {top[:3]}"


def test_v3_no_intersection_required():
    # FELLA returns 0 pathways (W5 D5 known characteristic); V3 should
    # still rank pathways from the other methods.
    row = _mk_row({
        "sspa_ora": ["Pathway A"],
        "ramp": ["Pathway A"],
        "PSEA": ["Pathway A"],
        "mummichog": ["Pathway B"],
        "FELLA": [],
    })
    top = _weighted_top_v3(row)
    assert "Pathway A" in top


def test_v3_cohort_lift_on_constructed_data():
    rows = [_mk_row({
        "ramp": ["Other"],
        "sspa_ora": ["Glycolysis Gluconeogenesis"],
        "PSEA": ["Glycolysis Gluconeogenesis"],
        "mummichog": ["Glycolysis Gluconeogenesis"],
    }, gt_name="Glycolysis Gluconeogenesis") for _ in range(10)]
    m = metric_v3_cohort(rows)
    assert m["cond_b"]["mean_precision"] >= 1.0


def test_variant_verdict_green_yellow_red():
    base = {"sign_test_p": 0.05, "sign_test_pos": 5, "sign_test_neg": 0}
    green = {**base, "delta_precision_mean": 0.10}
    assert variant_verdict(green) == "GREEN"
    yellow = {**base, "delta_precision_mean": 0.01}
    assert variant_verdict(yellow) == "YELLOW"
    red = {**base, "delta_precision_mean": -0.05}
    assert variant_verdict(red) == "RED"
