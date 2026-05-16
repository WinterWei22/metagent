"""W6 D2-D4 — pathway-name fuzzy match + paradigm-consensus + Gate-2 metrics."""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.analyze.pathway_match import (
    pathway_name_overlap, best_matching_rank, _tokenize, STOPWORDS,
)
from concord.analyze.paradigm_consensus import (
    paradigm_for, consensus_levels,
    metric_1_ground_truth_consensus_level, metric_1_cohort,
    metric_2_cohort, cohort_verdict,
    ALL_METHODS, ORA_METHODS,
)


# ---------------------------------------------------------------------------
# pathway_match
# ---------------------------------------------------------------------------


def test_tokenize_drops_stopwords_and_short():
    toks = _tokenize("Alanine, aspartate and glutamate metabolism")
    # 'metabolism', 'and' dropped
    assert "alanine" in toks and "aspartate" in toks and "glutamate" in toks
    assert "metabolism" not in toks and "and" not in toks


def test_pathway_name_overlap_exact():
    assert pathway_name_overlap(
        "Arachidonic acid metabolism",
        "Arachidonic acid metabolism",
    ) is True


def test_pathway_name_overlap_partial_pass():
    # acid + arachidonic overlap with arachidonic acid synthesis
    assert pathway_name_overlap(
        "Arachidonic acid metabolism",
        "Arachidonic acid biosynthesis",
    ) is True


def test_pathway_name_overlap_unrelated_reject():
    assert pathway_name_overlap(
        "Arachidonic acid metabolism",
        "Galactose metabolism",
    ) is False


def test_pathway_name_overlap_stopwords_alone_reject():
    # only stopwords overlapping → 0 content tokens → 0 jaccard
    assert pathway_name_overlap(
        "Metabolism of amino acids",
        "Other general metabolism pathway",
    ) is False


def test_best_matching_rank_first_hit():
    gt = "Arachidonic acid metabolism"
    candidates = [
        "Free fatty acid receptors",
        "Arachidonic acid biosynthesis",
        "Other",
    ]
    assert best_matching_rank(gt, candidates) == 1


def test_best_matching_rank_no_hit_returns_none():
    gt = "Arachidonic acid metabolism"
    assert best_matching_rank(gt, ["Glycolysis", "Citric acid cycle"]) is None


# ---------------------------------------------------------------------------
# paradigm_consensus
# ---------------------------------------------------------------------------


def test_paradigm_for_buckets():
    assert paradigm_for("sspa_ora") == "ora"
    assert paradigm_for("ramp") == "ora"
    assert paradigm_for("PSEA") == "ora"
    assert paradigm_for("mummichog") == "mz"
    assert paradigm_for("FELLA") == "net"


def test_paradigm_for_unknown():
    with pytest.raises(ValueError):
        paradigm_for("xyz")


def _mk_row(method_pathway_names: dict[str, list[str]],
             gt_name: str = "Glycolysis") -> dict:
    row = {"task_id": "t", "ground_truth_pathway_name": gt_name}
    for m, names in method_pathway_names.items():
        row[m] = {"pathways": [{"pathway_name": n} for n in names]}
    return row


def test_consensus_levels_solo_paradigms():
    row = _mk_row({
        "sspa_ora": ["A"], "ramp": ["B"], "PSEA": ["C"],
        "mummichog": ["D"], "FELLA": ["E"],
    })
    lv = consensus_levels(row)
    assert lv["A"] == 1 and lv["B"] == 1 and lv["C"] == 1
    assert lv["D"] == 2
    assert lv["E"] == 3


def test_consensus_levels_cross_paradigm():
    row = _mk_row({
        "sspa_ora": ["P"], "mummichog": ["P"], "FELLA": ["P"],
    })
    lv = consensus_levels(row)
    assert lv["P"] == 5  # all 3 paradigms


def test_consensus_levels_two_paradigms():
    row = _mk_row({
        "sspa_ora": ["Q"], "mummichog": ["Q"], "FELLA": ["other"],
    })
    lv = consensus_levels(row)
    assert lv["Q"] == 4  # ORA + m/z (no Network)


def test_metric_1_ground_truth_supported_at_cross_paradigm():
    row = _mk_row({
        "sspa_ora": ["Glycolysis"], "mummichog": ["Glycolysis"],
    }, gt_name="Glycolysis")
    assert metric_1_ground_truth_consensus_level(row) == 4


def test_metric_1_cohort_pass_threshold():
    # 10 rows: 1 supports GT cross-paradigm (Level 4), rest don't.
    # cond_a = 0, cond_b = 0.1 → delta 10pp → PASS
    rows = [_mk_row({"sspa_ora": ["glycolysis gluconeogenesis"],
                      "mummichog": ["glycolysis gluconeogenesis"]},
                     gt_name="Glycolysis gluconeogenesis")]
    rows += [_mk_row({"ramp": ["citrate cycle krebs"]},
                       gt_name="Pentose phosphate") for _ in range(9)]
    m1 = metric_1_cohort(rows)
    assert m1["cond_a_supported_pct"] == 0.0
    assert m1["cond_b_supported_pct"] == 0.1
    assert m1["delta_pp"] == pytest.approx(10.0, abs=0.01)
    assert m1["metric_1_pass"] is True


def test_metric_1_cohort_fail_when_below_3pp():
    # All 10 rows: ORA-only support of GT; cond_a = 1.0, cond_b = 0.0
    rows = [_mk_row({"ramp": ["arachidonic acid metabolism"]},
                      gt_name="Arachidonic acid metabolism")] * 10
    m1 = metric_1_cohort(rows)
    assert m1["cond_a_supported_pct"] == 1.0
    assert m1["cond_b_supported_pct"] == 0.0
    assert m1["metric_1_pass"] is False


def test_metric_2_pass_when_consensus_beats_ramp():
    # 10 rows: in 5, cross-paradigm consensus hits gt, RaMP misses (+50% precision)
    rows = []
    for i in range(5):
        rows.append(_mk_row({
            "sspa_ora": ["glycolysis_gluconeogenesis"],
            "mummichog": ["glycolysis_gluconeogenesis"],
            "ramp": ["Lipid metabolism"],
        }, gt_name="Glycolysis Gluconeogenesis"))
    for i in range(5):
        rows.append(_mk_row({
            "sspa_ora": ["Other"], "ramp": ["Other"], "PSEA": ["Other"],
            "mummichog": ["Stuff"], "FELLA": ["Things"],
        }, gt_name="Glycolysis"))
    m2 = metric_2_cohort(rows, n_bootstrap=50, seed=1)
    assert m2["cond_b"]["mean_precision"] > m2["cond_a"]["mean_precision"]
    assert m2["delta_precision_mean"] >= 0.03  # ≥3pp lift
    assert m2["metric_2_pass"] is True


def test_cohort_verdict_combinations():
    m1_pass = {"metric_1_pass": True}
    m1_fail = {"metric_1_pass": False}
    m2_pass = {"metric_2_pass": True}
    m2_fail = {"metric_2_pass": False}
    assert cohort_verdict(m1_pass, m2_pass) == "GREEN"
    assert cohort_verdict(m1_pass, m2_fail) == "YELLOW"
    assert cohort_verdict(m1_fail, m2_pass) == "YELLOW"
    assert cohort_verdict(m1_fail, m2_fail) == "RED"


def test_all_methods_list_complete():
    assert set(ALL_METHODS) == {
        "sspa_ora", "ramp", "PSEA", "mummichog", "FELLA",
    }
