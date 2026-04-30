"""Unit tests for evaluation.sub6.compound_lookup."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from evaluation.sub6.compound_lookup import CompoundEntry, CompoundLookup


def _write_curated(tmp_path: Path, recs: list[dict]) -> Path:
    p = tmp_path / "curated.jsonl"
    with p.open("w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    return p


def test_resolve_by_kegg(tmp_path):
    p = _write_curated(
        tmp_path,
        [
            {
                "name": "L-Tyrosine",
                "inchikey_first_block": "OUYCCCASQSFEME",
                "kegg_id": "C00082",
            }
        ],
    )
    look = CompoundLookup.from_curated(p)
    assert look.resolve("C00082") == "OUYCCCASQSFEME"
    assert look.resolve("c00082") == "OUYCCCASQSFEME"  # case-insensitive
    assert look.resolve("C99999") is None


def test_resolve_by_name_punctuation_insensitive(tmp_path):
    p = _write_curated(
        tmp_path,
        [
            {
                "name": "L-Tyrosine",
                "inchikey_first_block": "OUYCCCASQSFEME",
                "kegg_id": "C00082",
            }
        ],
    )
    look = CompoundLookup.from_curated(p)
    assert look.resolve("L-Tyrosine") == "OUYCCCASQSFEME"
    assert look.resolve("l tyrosine") == "OUYCCCASQSFEME"
    assert look.resolve("l-tyrosine") == "OUYCCCASQSFEME"
    assert look.resolve("LTyrosine") == "OUYCCCASQSFEME"


def test_kegg_to_inchikey_set_drops_unknown(tmp_path):
    p = _write_curated(
        tmp_path,
        [
            {
                "name": "Tyrosine",
                "inchikey_first_block": "OUYCCCASQSFEME",
                "kegg_id": "C00082",
            },
            {
                "name": "Fumarate",
                "inchikey_first_block": "VZCYOOQTPOCHFL",
                "kegg_id": "C00122",
            },
        ],
    )
    look = CompoundLookup.from_curated(p)
    out = look.kegg_to_inchikey_set(["C00082", "C99999", "C00122"])
    assert out == {"OUYCCCASQSFEME", "VZCYOOQTPOCHFL"}


def test_reverse_lookup(tmp_path):
    p = _write_curated(
        tmp_path,
        [
            {
                "name": "Tyrosine",
                "inchikey_first_block": "OUYCCCASQSFEME",
                "kegg_id": "C00082",
            },
        ],
    )
    look = CompoundLookup.from_curated(p)
    assert look.kegg_for("OUYCCCASQSFEME") == "C00082"
    assert look.name_for("OUYCCCASQSFEME") == "Tyrosine"


def test_loads_real_curated_file_if_present():
    """Smoke test on the real curated pool — guard against schema drift."""
    real = (
        Path(_REPO_ROOT)
        / "data"
        / "benchmark"
        / "sub6"
        / "curated_hmdb_mammalian.jsonl"
    )
    if not real.exists():
        pytest.skip("real curated pool not available")
    look = CompoundLookup.from_curated(real)
    assert len(look) >= 100
    # Pyruvate is one of the lowest-numbered KEGG IDs in the mammalian pool;
    # if this resolves the loader is wired up correctly.
    assert look.resolve("C00022") is not None
