"""Unit tests for evaluation.sub6.metrics."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from evaluation.sub6.compound_lookup import CompoundLookup
from evaluation.sub6.metrics import (
    compute_task_metrics,
    is_pathway_hit,
    task_metrics_to_dict,
)


# ---- pathway-hit fuzzy logic ------------------------------------------------


def test_pathway_hit_substring_both_directions():
    assert is_pathway_hit("Tyrosine", ["Tyrosine metabolism"]) is True
    assert is_pathway_hit("Tyrosine metabolism pathway", ["Tyrosine metabolism"]) is True


def test_pathway_hit_catabolism_matches_metabolism():
    """Eval guide §3 pitfall 3: 'Tyrosine catabolism' should match
    'Tyrosine metabolism' (suffix-token stripping)."""
    assert is_pathway_hit("Tyrosine catabolism", ["Tyrosine metabolism"]) is True
    assert is_pathway_hit("Tyrosine biosynthesis", ["Tyrosine metabolism"]) is True


def test_pathway_hit_combined_name():
    """'Methionine metabolism' should match 'Methionine and cysteine metabolism'
    because {methionine} ⊆ {methionine, cysteine}."""
    assert is_pathway_hit(
        "Methionine metabolism", ["Methionine and cysteine metabolism"]
    ) is True


def test_pathway_miss_disjoint_content():
    assert is_pathway_hit("Glycolysis", ["Tyrosine metabolism"]) is False
    assert is_pathway_hit("Cysteine metabolism", ["Methionine metabolism"]) is False


def test_empty_predicted_misses():
    assert is_pathway_hit("", ["Tyrosine metabolism"]) is False


# ---- end-to-end compute_task_metrics ---------------------------------------


@pytest.fixture
def lookup(tmp_path):
    p = tmp_path / "curated.jsonl"
    recs = [
        {"name": "L-Tyrosine", "kegg_id": "C00082", "inchikey_first_block": "OUYCCCASQSFEME"},
        {"name": "Homogentisate", "kegg_id": "C00544", "inchikey_first_block": "IGMNYECMUMZDDF"},
        {"name": "Fumarate", "kegg_id": "C00122", "inchikey_first_block": "VZCYOOQTPOCHFL"},
        {"name": "Acetoacetate", "kegg_id": "C00164", "inchikey_first_block": "WDJHALXBUFZDSR"},
        {"name": "Pyridoxal phosphate", "kegg_id": "C00018", "inchikey_first_block": "NGVDGCNFYWLIFO"},
    ]
    with p.open("w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    return CompoundLookup.from_curated(p)


def _task() -> dict:
    return {
        "task_id": "test_task",
        "differential_metabolites": [
            {"name": "L-Tyrosine", "kegg_id": "C00082"},
            {"name": "Homogentisate", "kegg_id": "C00544"},
            {"name": "Fumarate", "kegg_id": "C00122"},
            {"name": "Acetoacetate", "kegg_id": "C00164"},  # noise
            {"name": "Pyridoxal phosphate", "kegg_id": "C00018"},  # noise
        ],
        "ground_truth_pathway": {
            "pathway_name": "Tyrosine metabolism",
            "pathway_id": "RAMP_P_000000106",
        },
        "ground_truth_signal_compounds": ["C00082", "C00544", "C00122"],
        "ground_truth_noise_compounds": ["C00164", "C00018"],
        "ramp_enrichment_result": {
            "top_pathways": [
                {"pathway_name": "Tyrosine metabolism"},
                {"pathway_name": "Alkaptonuria"},
                {"pathway_name": "Dopamine beta-hydroxylase deficiency"},
                {"pathway_name": "Phenylalanine metabolism"},
                {"pathway_name": "Catecholamine biosynthesis"},
            ]
        },
    }


def test_perfect_narrative_top1_strict_and_clean(lookup):
    text = (
        "The differential profile points strongly to Tyrosine metabolism. "
        "Key drivers include L-Tyrosine, Homogentisate, and Fumarate, "
        "all of which drive the catabolic chain."
    )
    m = compute_task_metrics(text, _task(), lookup)
    assert m.top1_pathway_strict is True
    assert m.top3_pathway_acceptance is True
    assert m.driver_recall == pytest.approx(1.0)
    assert m.driver_precision == pytest.approx(1.0)
    assert m.false_noise_rate == pytest.approx(0.0)
    assert m.off_pathway_count == 0


def test_top3_acceptance_when_near_miss(lookup):
    text = (
        "Alkaptonuria stands out as the dominant pathway disturbance. "
        "L-Tyrosine and Homogentisate are key drivers."
    )
    m = compute_task_metrics(text, _task(), lookup)
    # Strict miss (top mention is not 'Tyrosine metabolism'):
    assert m.top1_pathway_strict is False
    # Top-3 acceptance hit (Alkaptonuria is in top_pathways[:3]):
    assert m.top3_pathway_acceptance is True


def test_off_pathway_hallucination_counted(lookup):
    text = (
        "Tyrosine metabolism is implicated, but glycolysis and the urea cycle "
        "appear coactivated."
    )
    m = compute_task_metrics(text, _task(), lookup)
    # 'glycolysis' might not match the regex (no follow-on noun) — assert via
    # extracted_pathways instead. urea cycle should be flagged off.
    assert any("urea cycle" in p.lower() for p in m.extracted_pathways)
    assert m.off_pathway_count >= 1


def test_false_noise_driver_pulls_metrics_down(lookup):
    text = (
        "Tyrosine metabolism dominates. "
        "Acetoacetate is the primary driver of the catabolic flux."  # noise mis-cited
    )
    m = compute_task_metrics(text, _task(), lookup)
    assert "Acetoacetate" in m.claimed_drivers
    assert m.false_noise_rate > 0.0
    # Driver precision must drop to <1.0 because noise was counted.
    assert m.driver_precision < 1.0


def test_empty_narrative_yields_zeroes_no_raise(lookup):
    m = compute_task_metrics("", _task(), lookup)
    assert m.top1_pathway_strict is False
    assert m.top3_pathway_acceptance is False
    assert m.driver_precision == 0.0
    assert m.driver_recall == 0.0
    assert m.off_pathway_count == 0


def test_dict_serialisation_round_trip(lookup):
    text = "Tyrosine metabolism. L-Tyrosine drives the pathway."
    m = compute_task_metrics(text, _task(), lookup)
    d = task_metrics_to_dict(m)
    assert isinstance(json.dumps(d), str)
    assert d["task_id"] == "test_task"
    assert d["top1_pathway_strict"] is True
