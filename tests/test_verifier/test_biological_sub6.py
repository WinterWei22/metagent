"""Unit tests for Layer 6c — biological_sub6 verifier (Sub-6 BIOLOGICAL claims).

Covers the existing dispatch tree (SUPPORTED via top_pathways /
UNVERIFIABLE_V0 disease guard / UNSUPPORTED fallback) plus the
contra-path branch added by ``track_layer6c_contra_path``.

The contra path requires both a real RaMP-DB (with ``source`` +
``pathway`` + ``analytehaspathway`` tables) AND a KEGG alias DB
(``compound_aliases`` table). Both are built in-process from sqlite
files under ``tmp_path`` so the test is self-contained and runs in CI
without any environment dependencies.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from schemas.sub6_report import SubsixSourceReport
from verifier.layers.biological_sub6 import (
    _MIN_KNOWN_PATHWAYS_FOR_CONTRA_DEFAULT,
    verify_biological_sub6,
)
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_kegg_db(path: Path, aliases: list[tuple[str, str]]) -> None:
    """Build a minimal compound_aliases table at ``path``.

    ``aliases`` is a list of ``(alias_lowercase, cpd:CXXXXX)`` pairs.
    """
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE compound_aliases (
            alias TEXT NOT NULL,
            compound_id TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY (alias, compound_id)
        )
        """
    )
    cur.execute("CREATE INDEX idx_compound_aliases_alias ON compound_aliases(alias)")
    cur.executemany(
        "INSERT OR IGNORE INTO compound_aliases (alias, compound_id, source) VALUES (?, ?, 'name')",
        aliases,
    )
    conn.commit()
    conn.close()


def _build_ramp_db(
    path: Path,
    *,
    pathways: list[tuple[str, str, str, str]],
    sources: list[tuple[str, str]],
    memberships: list[tuple[str, str]],
) -> None:
    """Build a minimal RaMP-like sqlite at ``path``.

    Args:
        pathways:    list of ``(pathwayRampId, sourceId, type, pathwayName)``
        sources:     list of ``(sourceId='kegg:CXXXXX', rampCompoundId)``
        memberships: list of ``(rampCompoundId, pathwayRampId)``
    """
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE pathway (
            pathwayRampId VARCHAR(30) PRIMARY KEY,
            sourceId VARCHAR(30),
            type VARCHAR(30),
            pathwayCategory VARCHAR(30),
            pathwayName VARCHAR(250) COLLATE NOCASE
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE source (
            sourceId VARCHAR(30) NOT NULL,
            rampId VARCHAR(30),
            IDtype VARCHAR(30),
            geneOrCompound VARCHAR(30),
            commonName VARCHAR(256),
            priorityHMDBStatus VARCHAR(32),
            dataSource VARCHAR(32),
            pathwayCount INTEGER DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE analytehaspathway (
            rampId VARCHAR(30),
            pathwayRampId VARCHAR(30),
            pathwaySource VARCHAR(30)
        )
        """
    )
    cur.executemany(
        "INSERT INTO pathway (pathwayRampId, sourceId, type, pathwayCategory, pathwayName) VALUES (?, ?, ?, NULL, ?)",
        pathways,
    )
    cur.executemany(
        "INSERT INTO source (sourceId, rampId, IDtype, geneOrCompound, commonName) VALUES (?, ?, 'kegg', 'compound', NULL)",
        sources,
    )
    cur.executemany(
        "INSERT INTO analytehaspathway VALUES (?, ?, 'kegg')",
        memberships,
    )
    conn.commit()
    conn.close()


@pytest.fixture
def small_dbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """Build self-contained KEGG + RaMP DBs and point env vars at them.

    Compound layout:
      - Tyrosine            (cpd:C00082, ramp RC_TYR)  — 5 pathway memberships
      - GlcNAc-1-P          (cpd:C04256, ramp RC_GLC)  — 4 pathway memberships
      - Pantothenic acid    (cpd:C00864, ramp RC_PAN)  — 5 pathway memberships
      - Foobarine           (cpd:C99999, ramp RC_FOO)  — only 1 pathway
                                                          (under threshold)

    Pathway layout:
      - P_TYRMET   "Tyrosine metabolism"      (kegg)
      - P_HEXOSAMINE "Hexosamine pathway"     (kegg)
      - P_MEVALONATE "Mevalonate pathway"     (kegg)
      - P_FATTY    "Fatty acid synthesis"     (kegg)
      - P_LIPID    "Lipid metabolism"         (kegg)
      - P_ALONE    "Solitary niche pathway"   (kegg)
      - P_CITRATE  "Citric acid cycle"        (kegg)

    Memberships designed so:
      - Tyrosine ∈ {Tyrosine metabolism, Lipid metabolism, Fatty acid
        synthesis, Citric acid cycle, Hexosamine pathway} — 5 known
      - GlcNAc-1-P ∈ {Hexosamine pathway, Citric acid cycle, Fatty acid
        synthesis, Lipid metabolism} — 4 known
      - Pantothenic acid ∈ {Citric acid cycle, Lipid metabolism,
        Fatty acid synthesis, Tyrosine metabolism, Hexosamine pathway}
        — 5 known but NOT in mevalonate pathway (the contra case)
      - Foobarine ∈ {Solitary niche pathway} — 1 known, under threshold
    """
    ramp_path = tmp_path / "ramp_test.sqlite"
    kegg_path = tmp_path / "kegg_test.sqlite"

    pathways = [
        ("P_TYRMET",     "map00350", "kegg", "Tyrosine metabolism"),
        ("P_HEXOSAMINE", "map00520", "kegg", "Hexosamine pathway"),
        ("P_MEVALONATE", "map00900", "kegg", "Mevalonate pathway"),
        ("P_FATTY",      "map00061", "kegg", "Fatty acid synthesis"),
        ("P_LIPID",      "map01100", "kegg", "Lipid metabolism"),
        ("P_ALONE",      "map99999", "kegg", "Solitary niche pathway"),
        ("P_CITRATE",    "map00020", "kegg", "Citric acid cycle"),
    ]
    sources = [
        ("kegg:C00082", "RC_TYR"),
        ("kegg:C04256", "RC_GLC"),
        ("kegg:C00864", "RC_PAN"),
        ("kegg:C99999", "RC_FOO"),
    ]
    memberships = [
        # Tyrosine — 5 known
        ("RC_TYR", "P_TYRMET"),
        ("RC_TYR", "P_LIPID"),
        ("RC_TYR", "P_FATTY"),
        ("RC_TYR", "P_CITRATE"),
        ("RC_TYR", "P_HEXOSAMINE"),
        # GlcNAc-1-P — 4 known incl. hexosamine pathway
        ("RC_GLC", "P_HEXOSAMINE"),
        ("RC_GLC", "P_CITRATE"),
        ("RC_GLC", "P_FATTY"),
        ("RC_GLC", "P_LIPID"),
        # Pantothenic acid — 5 known, NOT mevalonate
        ("RC_PAN", "P_CITRATE"),
        ("RC_PAN", "P_LIPID"),
        ("RC_PAN", "P_FATTY"),
        ("RC_PAN", "P_TYRMET"),
        ("RC_PAN", "P_HEXOSAMINE"),
        # Foobarine — only 1
        ("RC_FOO", "P_ALONE"),
    ]
    _build_ramp_db(
        ramp_path,
        pathways=pathways,
        sources=sources,
        memberships=memberships,
    )
    aliases = [
        ("tyrosine",         "cpd:C00082"),
        ("l-tyrosine",       "cpd:C00082"),
        ("glcnac-1-p",       "cpd:C04256"),
        ("n-acetylglucosamine 1-phosphate", "cpd:C04256"),
        ("pantothenic acid", "cpd:C00864"),
        ("vitamin b5",       "cpd:C00864"),
        ("foobarine",        "cpd:C99999"),
    ]
    _build_kegg_db(kegg_path, aliases)

    monkeypatch.setenv("METAGENT_RAMP_PATH", str(ramp_path))
    monkeypatch.setenv("METAGENT_KEGG_PATH", str(kegg_path))
    return str(ramp_path), str(kegg_path)


@pytest.fixture
def task() -> SubsixSourceReport:
    """A SubsixSourceReport whose top_pathways DOES NOT include the
    pathways named in our test claims, so the existing top_pathways /
    RaMP-pathway-name SUPPORTED branch never fires — every claim hits
    the new contra path."""
    return SubsixSourceReport(
        task_id="contra_test_task",
        task_type="compound_only_enrichment",
        ground_truth_pathway={
            "pathway_id": "RAMP_P_999998",
            "pathway_name": "Unrelated reference pathway",
        },
        ground_truth_signal_compounds=[],
        ground_truth_noise_compounds=[],
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_999998",
                    "pathway_name": "Unrelated reference pathway",
                    "fdr": 0.001,
                },
            ],
        },
    )


def _claim(text: str, *, subject: str | None = None) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_text=text,
        subject=subject,
        claim_type=ClaimType.BIOLOGICAL,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(),
    )


# ---------------------------------------------------------------------------
# CONTRA PATH
# ---------------------------------------------------------------------------


def test_biological_contra_compound_not_in_pathway(task, small_dbs):
    """RaMP knows Pantothenic acid is in 5 pathways; mevalonate isn't one."""
    r = verify_biological_sub6(
        _claim(
            "Pantothenic acid links to the mevalonate pathway",
            subject="Pantothenic acid",
        ),
        task,
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED, (
        f"expected CONTRADICTED, got {r.verdict.value}: {r.evidence}"
    )
    assert r.correction is not None
    # top-3 actual pathways should be in correction
    assert any(
        p in (r.correction or "")
        for p in ["Lipid metabolism", "Fatty acid synthesis", "Citric acid cycle"]
    )
    assert r.enrichment_context is not None
    te = r.enrichment_context.tool_evidence
    assert te.get("membership_check") == "no_intersection"
    assert te.get("n_pathways_known") == 5
    assert te.get("min_known_threshold") == 3
    assert "kegg:C00864" not in str(te), "kegg: prefix should be stripped from cpd id"
    assert te.get("kegg_compound_id") == "cpd:C00864"


def test_biological_contra_via_text_token_when_subject_is_pathway(task, small_dbs):
    """Subject can be the pathway name (extractor sometimes mislabels);
    helper falls back to scanning capitalised tokens in claim text."""
    r = verify_biological_sub6(
        _claim(
            "Pantothenic acid is involved in the mevalonate pathway.",
            subject="mevalonate pathway",  # subject IS pathway-suffixed → skipped
        ),
        task,
    )
    # Should still find 'Pantothenic' via title-token scan.
    assert r.verdict == ClaimVerdict.CONTRADICTED


# ---------------------------------------------------------------------------
# SUPPORTED rescue (false-negative recovery)
# ---------------------------------------------------------------------------


def test_biological_supp_when_overlap_exists(task, small_dbs):
    """GlcNAc-1-P IS in hexosamine pathway → overlap > 0 → SUPPORTED."""
    r = verify_biological_sub6(
        _claim(
            "GlcNAc-1-P elevation reflects compensatory hexosamine pathway activation",
            subject="GlcNAc-1-P",
        ),
        task,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED, (
        f"expected SUPPORTED, got {r.verdict.value}: {r.evidence}"
    )
    te = r.enrichment_context.tool_evidence
    assert te.get("membership_check") == "overlap_positive"
    assert te.get("overlap_count") >= 1


# ---------------------------------------------------------------------------
# Under-characterised compound stays UNSUPPORTED (threshold guard)
# ---------------------------------------------------------------------------


def test_biological_unsupp_when_compound_underexplored(task, small_dbs):
    """Foobarine has only 1 known pathway in RaMP — below threshold of 3.
    Even though hexosamine pathway is not in its memberships, we cannot
    contra it (data is too sparse). Falls through to UNSUPPORTED."""
    r = verify_biological_sub6(
        _claim(
            "Foobarine is part of the hexosamine pathway",
            subject="Foobarine",
        ),
        task,
    )
    assert r.verdict == ClaimVerdict.UNSUPPORTED, (
        f"expected UNSUPPORTED (under-characterised), got {r.verdict.value}: {r.evidence}"
    )


# ---------------------------------------------------------------------------
# Existing branches — must not regress
# ---------------------------------------------------------------------------


def test_biological_unverif_disease_keyword_unchanged(task, small_dbs):
    """Disease keyword still triggers UNVERIFIABLE_V0 BEFORE contra path."""
    r = verify_biological_sub6(
        _claim(
            "Tyrosine metabolism is dysregulated in Parkinson's disease.",
            subject="Tyrosine metabolism",
        ),
        task,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_biological_no_compound_resolution_unchanged(task, small_dbs):
    """Claim with no resolvable compound subject AND a recognisable pathway
    phrase falls through to the historical UNSUPPORTED branch."""
    r = verify_biological_sub6(
        _claim(
            "An unknown intermediate is involved in the mevalonate pathway",
            subject=None,
        ),
        task,
    )
    # No compound → contra helper returns None → historical UNSUPPORTED.
    # (Note: regex extracts 'mevalonate pathway' as the phrase, so the
    # branch that runs is the final fallback.)
    assert r.verdict == ClaimVerdict.UNSUPPORTED


def test_biological_supported_via_top_pathways_unchanged(small_dbs):
    """Claim's pathway IS in top_pathways — original SUPPORTED branch still
    fires before reaching the contra path."""
    task_with_top = SubsixSourceReport(
        task_id="supp_via_top",
        task_type="compound_only_enrichment",
        ground_truth_pathway={
            "pathway_id": "RAMP_P_TYR",
            "pathway_name": "Tyrosine metabolism",
        },
        ground_truth_signal_compounds=[],
        ground_truth_noise_compounds=[],
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_TYR",
                    "pathway_name": "Tyrosine metabolism",
                    "fdr": 1e-10,
                },
            ],
        },
    )
    r = verify_biological_sub6(
        _claim(
            "Tyrosine metabolism plays a role in mammalian biology.",
            subject="Tyrosine metabolism",
        ),
        task_with_top,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    # Source is the top_pathways match, not the new contra helper.
    assert r.tool_called == "ramp_enrichment_result"


def test_biological_unverif_when_no_pathway_in_claim(task, small_dbs):
    """Claim has no pathway phrase / ID — historical UNVERIFIABLE_V0
    short-circuit still fires before the contra helper."""
    r = verify_biological_sub6(
        _claim(
            "Tyrosine plays a fundamental biological role",
            subject="Tyrosine",
        ),
        task,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


# ---------------------------------------------------------------------------
# Threshold tunability via env var
# ---------------------------------------------------------------------------


def test_biological_contra_threshold_tunable_via_env(
    task, small_dbs, monkeypatch
):
    """Setting MIN_KNOWN_PATHWAYS to 6 makes Pantothenic acid (5 known)
    drop below threshold → UNSUPPORTED instead of CONTRADICTED."""
    monkeypatch.setenv("METAGENT_LAYER6C_MIN_KNOWN_PATHWAYS", "6")
    r = verify_biological_sub6(
        _claim(
            "Pantothenic acid links to the mevalonate pathway",
            subject="Pantothenic acid",
        ),
        task,
    )
    assert r.verdict == ClaimVerdict.UNSUPPORTED


def test_biological_default_threshold_is_three():
    assert _MIN_KNOWN_PATHWAYS_FOR_CONTRA_DEFAULT == 3
