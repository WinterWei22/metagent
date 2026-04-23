"""Verifier-readiness tests for Track D tools.

Every test has two flavours — mock (default, always runs) and real (gated
on `@pytest.mark.requires_hmdb_db` / `requires_ramp_db`, skipped when the
env var is unset). Split by class so pytest's collection shows both
flavours and the mock path stays green even on a barebones CI.

Strict-vs-flexible comparison: the mock path asserts against the fixture
JSON byte-for-byte. The real path uses flexible comparators (InChIKey
connectivity hash rather than full stereo key, formula that matches either
the neutral or protonated form, exact mass within 1.01 Da) — the audit
found that HMDB's current curation stores some zwitterions as protonated
cations (notably L-carnitine) and some compounds with stereo-specific
InChIKeys (glucose as α-D-glucopyranose) that differ from the fixture.
See reports/integration_report_de_2026-04-23.md § D-1, D-2 for the
full analysis.
"""
from __future__ import annotations

import json
import os
import sys
import unittest.mock as mock
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from schemas.molecule import MetaboliteInfoRequest
from schemas.pathway import PathwayContextRequest
from tools.metabolite_info import fetch_metabolite_info
from tools.metabolite_info.errors import IdentifierFormatError
from tools.pathway_context import pathway_context
from tools.pathway_context.errors import MetaboliteNotInNetworkError


_FIXTURE = json.loads(
    (_REPO_ROOT / "tests" / "fixtures" / "hmdb_ids" / "expected.json").read_text()
)


# ---------------------------------------------------------------------------
# Shared assertion helpers.
# ---------------------------------------------------------------------------


def _assert_strict_match(resp, expected: dict) -> None:
    """Mock-path comparator: fields must match the fixture exactly."""
    assert resp.found is True, f"expected found=True for {expected['hmdb_id']}"
    assert resp.primary_name == expected["primary_name"]
    assert resp.molecular_formula == expected["molecular_formula"]
    assert resp.inchikey == expected["inchikey"]
    assert resp.cross_refs.get("kegg") == expected["kegg_id"]
    assert resp.exact_mass is not None
    assert abs(resp.exact_mass - expected["exact_mass"]) < 0.01


def _assert_flexible_match(resp, expected: dict) -> None:
    """Real-path comparator tolerant of HMDB's curation choices.

    Specifically allows:
    - InChIKey match on the connectivity block only (first 14 chars) so
      stereo-specific HMDB entries (α- vs β-glucose) pass.
    - Formula match on either the neutral form in the fixture or the
      protonated-cation form (one extra H) for zwitterions.
    - Exact mass within either 0.01 Da (same protonation state) or 1.05 Da
      (fixture neutral vs HMDB cation) of the expected value.
    - `primary_name` checked via lowercased substring containment of the
      fixture's name; tolerates "D-Glucose" vs "Glucose" etc.
    """
    assert resp.found is True, f"expected found=True for {expected['hmdb_id']}"

    fix_name = expected["primary_name"].lower()
    got_name = (resp.primary_name or "").lower()
    # Either the fixture name appears in the real name, or the first word does.
    assert got_name in fix_name or fix_name.split("-")[-1].strip() in got_name or fix_name.split()[0] in got_name, (
        f"name mismatch: expected approx {expected['primary_name']!r}, got {resp.primary_name!r}"
    )

    # Formula: accept neutral or +1 H.
    fix_f = expected["molecular_formula"]
    assert resp.molecular_formula in {fix_f, _plus_one_hydrogen(fix_f)}, (
        f"formula mismatch: expected {fix_f!r} (or +1H cation), got {resp.molecular_formula!r}"
    )

    # InChIKey: compare connectivity block only.
    fix_ik = expected["inchikey"].split("-")[0]
    assert resp.inchikey is not None and resp.inchikey.startswith(fix_ik), (
        f"inchikey connectivity mismatch: expected {fix_ik!r}, got {resp.inchikey!r}"
    )

    # Exact mass: within 0.01 (same form) OR within 1.05 (cation vs neutral).
    assert resp.exact_mass is not None
    delta = abs(resp.exact_mass - expected["exact_mass"])
    assert delta < 0.01 or abs(delta - 1.00728) < 0.05, (
        f"exact_mass drift: expected {expected['exact_mass']}, got {resp.exact_mass} (Δ={delta})"
    )


def _plus_one_hydrogen(formula: str) -> str:
    """Return `formula` with one more H atom, keeping Hill order. Approximate
    but sufficient for the zwitterion case — only the H count changes."""
    import re

    m = re.match(r"(C\d*)(H)(\d*)(.*)$", formula)
    if not m:
        return formula  # defensive: can't parse, fall back to mismatch
    c, h_letter, h_count, rest = m.groups()
    new_h = (int(h_count) if h_count else 1) + 1
    return f"{c}{h_letter}{new_h}{rest}"


# ---------------------------------------------------------------------------
# Test 1: fetch_metabolite_info — fixture roundtrip.
# ---------------------------------------------------------------------------


class TestMetaboliteRoundtripMock:
    """Strict fixture-vs-tool comparison against the in-tmp HMDB SQLite."""

    def test_every_fixture_entry_roundtrips(self, mock_hmdb_db):
        for entry in _FIXTURE["entries"]:
            resp = fetch_metabolite_info(
                MetaboliteInfoRequest(identifier=entry["hmdb_id"], id_type="hmdb")
            )
            _assert_strict_match(resp, entry)


@pytest.mark.requires_hmdb_db
class TestMetaboliteRoundtripReal:
    """Flexible comparison against the live HMDB dump.

    Guards against the fixture-vs-DB drift documented in the audit report
    (glucose stored as α-form; L-carnitine stored as cation).
    """

    @pytest.fixture(autouse=True)
    def _require(self, has_hmdb_db):
        if not has_hmdb_db:
            pytest.skip(
                "HMDB SQLite not found at METAGENT_HMDB_PATH; "
                "run tools/metabolite_info/build_hmdb_db.py first."
            )

    def test_every_fixture_entry_roundtrips(self):
        for entry in _FIXTURE["entries"]:
            resp = fetch_metabolite_info(
                MetaboliteInfoRequest(identifier=entry["hmdb_id"], id_type="hmdb")
            )
            _assert_flexible_match(resp, entry)


# ---------------------------------------------------------------------------
# Test 2: nonexistent identifier → found=False.
# ---------------------------------------------------------------------------


class TestNonexistentIdMock:
    def test_fake_hmdb_returns_found_false(self, mock_hmdb_db):
        resp = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier="HMDB9999999", id_type="hmdb")
        )
        assert resp.found is False
        assert resp.primary_name is None
        assert resp.molecular_formula is None
        assert resp.cross_refs == {}
        assert resp.source is None

    def test_fake_inchikey_returns_found_false(self, mock_hmdb_db):
        resp = fetch_metabolite_info(
            MetaboliteInfoRequest(
                identifier="ZZZZZZZZZZZZZZ-ZZZZZZZZZZ-Z", id_type="inchikey"
            )
        )
        assert resp.found is False

    def test_empty_identifier_raises(self, mock_hmdb_db):
        with pytest.raises(IdentifierFormatError):
            fetch_metabolite_info(
                MetaboliteInfoRequest.model_construct(identifier="", id_type="auto")
            )


@pytest.mark.requires_hmdb_db
class TestNonexistentIdReal:
    @pytest.fixture(autouse=True)
    def _require(self, has_hmdb_db):
        if not has_hmdb_db:
            pytest.skip("HMDB SQLite not found at METAGENT_HMDB_PATH")

    def test_fake_hmdb_returns_found_false(self):
        resp = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier="HMDB9999999", id_type="hmdb")
        )
        # The real HMDB may have the PubChem fallback off; we only assert no
        # invention, i.e., empty response.
        assert resp.found is False, (
            f"HMDB9999999 should be unknown; got invented fields "
            f"(primary_name={resp.primary_name!r})"
        )
        assert resp.primary_name is None
        assert resp.molecular_formula is None


# ---------------------------------------------------------------------------
# Test 3: pathway_context cooccurrence_score — real > random.
# ---------------------------------------------------------------------------


class TestCooccurrenceMock:
    def test_real_neighbour_scores_higher_than_random(self, mock_ramp_db):
        # Pyruvate co-observed with glucose (shares glycolysis) vs with caffeine
        # (disjoint pathway set).
        with_real = pathway_context(PathwayContextRequest(
            metabolite_id="HMDB0000243",
            co_observed_ids=["HMDB0000122"],
        ))
        with_random = pathway_context(PathwayContextRequest(
            metabolite_id="HMDB0000243",
            co_observed_ids=["HMDB0001847"],
        ))
        assert with_real.cooccurrence_score > with_random.cooccurrence_score
        assert 0.0 <= with_random.cooccurrence_score <= 1.0
        assert 0.0 <= with_real.cooccurrence_score <= 1.0


@pytest.mark.requires_ramp_db
class TestCooccurrenceReal:
    @pytest.fixture(autouse=True)
    def _require(self, has_ramp_db):
        if not has_ramp_db:
            pytest.skip("RaMP SQLite not found at METAGENT_RAMP_PATH")

    def test_real_neighbour_scores_higher_than_random(self):
        with_real = pathway_context(PathwayContextRequest(
            metabolite_id="HMDB0000243",
            co_observed_ids=["HMDB0000122"],  # glucose, shares glycolysis
        ))
        with_random = pathway_context(PathwayContextRequest(
            metabolite_id="HMDB0000243",
            co_observed_ids=["HMDB9999998", "HMDB9999999"],  # unresolvable
        ))
        assert with_real.cooccurrence_score > with_random.cooccurrence_score, (
            f"cooccurrence_score monotonicity broken: "
            f"real={with_real.cooccurrence_score}, random={with_random.cooccurrence_score}"
        )


# ---------------------------------------------------------------------------
# Test 3b: hit_count is per-pathway (pins the P-1 fix).
#
# Added after Track D landed `fix(pathway_context): per-pathway hit_count`
# (commit 7d8b097). Before that fix, every PathwayEntry in a response
# carried the same `1 + len(cooccurring)` aggregate regardless of which
# pathway the focal and co-observed metabolites actually belonged to. See
# reports/integration_report_de_2026-04-23.md § P-1 for the rationale and
# reports/pathway_context_fix_plan_2026-04-23.md § 1 (P-1) for the fix.
# ---------------------------------------------------------------------------


class TestPerPathwayHitCountMock:
    def test_hit_count_varies_per_pathway_in_mixed_overlap(self, mock_ramp_db):
        """Query designed to produce mixed counts in the mini RaMP:

        Pyruvate (focal) sits in THREE pathways:
          - glycolysis-kegg, glycolysis-reactome, alanine-kegg

        Co-observed: [alanine]. Alanine is only in alanine-kegg.

        Expected hit_counts (one per pathway):
          - glycolysis-kegg:     1  (pyruvate only)
          - glycolysis-reactome: 1  (pyruvate only)
          - alanine-kegg:        2  (pyruvate + alanine)

        The pre-fix code would return [2, 2, 2] because it computed
        `1 + len(cooccurring) = 2` for every pathway.
        """
        resp = pathway_context(PathwayContextRequest(
            metabolite_id="HMDB0000243",
            co_observed_ids=["HMDB0000161"],
        ))
        counts_by_name = {p.name: p.hit_count for p in resp.pathways}
        # Pin the exact shape — mixed values, alanine pathway gets the
        # boost, glycolysis pathways do not.
        assert 3 == len(counts_by_name), f"expected 3 pathways, got {list(counts_by_name)}"
        assert sorted(counts_by_name.values()) == [1, 1, 2], (
            f"hit_count distribution must be [1, 1, 2]; got {sorted(counts_by_name.values())}"
        )
        assert counts_by_name.get("Alanine, aspartate and glutamate metabolism") == 2, (
            "alanine-metabolism pathway should have hit_count=2 "
            "(focal pyruvate + co-observed alanine)"
        )
        # Either of the glycolysis entries should have hit_count=1 — alanine
        # isn't in them.
        for name, hit in counts_by_name.items():
            if "Glycolysis" in name:
                assert hit == 1, (
                    f"{name!r} should have hit_count=1 (alanine not a member); "
                    f"got {hit}. Likely regression of P-1."
                )

    def test_hit_count_never_counts_unresolvable(self, mock_ramp_db):
        """Unresolvable co-observed IDs contribute nothing to hit_count."""
        resp = pathway_context(PathwayContextRequest(
            metabolite_id="HMDB0000122",
            co_observed_ids=["HMDB9999998", "HMDB9999999"],
        ))
        # Glucose sits in 2 pathways (glycolysis-kegg + glycolysis-reactome).
        # With only unresolvable co-obs, each pathway's hit_count must be 1
        # (focal only).
        for p in resp.pathways:
            assert p.hit_count == 1, (
                f"{p.name!r}: unresolvable co-obs should not lift hit_count; "
                f"got {p.hit_count}"
            )


@pytest.mark.requires_ramp_db
class TestPerPathwayHitCountReal:
    @pytest.fixture(autouse=True)
    def _require(self, has_ramp_db):
        if not has_ramp_db:
            pytest.skip("RaMP SQLite not found at METAGENT_RAMP_PATH")

    def test_hit_count_has_variance_under_mixed_co_obs(self):
        """On real RaMP, glucose's 10 pathways include some that share
        pyruvate / alanine and some that don't. The post-fix distribution
        must have at least two distinct hit_count values; the pre-fix
        distribution was always a single uniform value."""
        resp = pathway_context(PathwayContextRequest(
            metabolite_id="HMDB0000122",
            co_observed_ids=["HMDB0000243", "HMDB0000161"],
        ))
        counts = [p.hit_count for p in resp.pathways]
        distinct = set(counts)
        assert len(distinct) >= 2, (
            f"real RaMP hit_count collapsed to a single value {distinct}; "
            "P-1 may have regressed (pre-fix always returned one uniform count)."
        )
        # Sanity: no hit_count can exceed focal + |co_obs| = 3.
        assert max(counts) <= 3
        assert min(counts) >= 1

    def test_hit_count_unchanged_when_co_obs_is_empty(self):
        """When no co-observed metabolites are passed, every pathway's
        hit_count must be exactly 1 (focal-only membership)."""
        resp = pathway_context(PathwayContextRequest(
            metabolite_id="HMDB0000122",
        ))
        for p in resp.pathways:
            assert p.hit_count == 1, (
                f"empty co_observed_ids ⇒ hit_count must be 1 for every "
                f"pathway; got {p.hit_count} on {p.name!r}"
            )


# ---------------------------------------------------------------------------
# Test 4: orphan metabolite handled cleanly.
# ---------------------------------------------------------------------------


class TestOrphanMetaboliteMock:
    def test_orphan_raises_metabolite_not_in_network(self, mock_ramp_db):
        # HMDB0000050 (adenosine) is seeded in the mini RaMP with a source row
        # but no analytehaspathway rows — the classic "resolves but no pathway"
        # case.
        with pytest.raises(MetaboliteNotInNetworkError):
            pathway_context(PathwayContextRequest(metabolite_id="HMDB0000050"))

    def test_fake_id_also_raises(self, mock_ramp_db):
        with pytest.raises(MetaboliteNotInNetworkError):
            pathway_context(PathwayContextRequest(metabolite_id="HMDB9999999"))


@pytest.mark.requires_ramp_db
class TestOrphanMetaboliteReal:
    @pytest.fixture(autouse=True)
    def _require(self, has_ramp_db):
        if not has_ramp_db:
            pytest.skip("RaMP SQLite not found at METAGENT_RAMP_PATH")

    def test_fake_id_raises(self):
        # A structurally valid but non-existent HMDB ID must raise cleanly,
        # not fabricate pathways.
        with pytest.raises(MetaboliteNotInNetworkError):
            pathway_context(PathwayContextRequest(metabolite_id="HMDB9999999"))


# ---------------------------------------------------------------------------
# Test 5: plausibility_summary is templated — no LLM call.
# ---------------------------------------------------------------------------


def _tripwire(*_a, **_kw):  # pragma: no cover - only fires on regression
    raise AssertionError(
        "common.llm_client.chat was invoked during pathway_context. "
        "The plausibility_summary is supposed to be templated; any LLM "
        "call is a trust-anchor violation."
    )


class TestTemplatedSummaryMock:
    def test_no_llm_across_five_queries(self, mock_ramp_db):
        from common import llm_client

        queries = [
            ("HMDB0000243", []),
            ("HMDB0000122", ["HMDB0000243"]),
            ("HMDB0000161", []),
            ("HMDB0001847", ["HMDB0000122", "HMDB0000243"]),
            ("HMDB0000243", ["HMDB0000161"]),
        ]
        with mock.patch.object(llm_client, "chat", _tripwire), \
             mock.patch.object(llm_client, "chat_raw", _tripwire):
            for mid, co in queries:
                resp = pathway_context(PathwayContextRequest(
                    metabolite_id=mid, co_observed_ids=co
                ))
                assert resp.plausibility_summary  # non-empty
                assert len(resp.plausibility_summary.split()) < 120
                # Fail on LLM-smell tokens that would reveal a template bypass.
                low = resp.plausibility_summary.lower()
                for smell in ("based on my analysis", "as an ai", "i believe", "it seems"):
                    assert smell not in low, f"LLM-smell token {smell!r} in summary"


@pytest.mark.requires_ramp_db
class TestTemplatedSummaryReal:
    @pytest.fixture(autouse=True)
    def _require(self, has_ramp_db):
        if not has_ramp_db:
            pytest.skip("RaMP SQLite not found at METAGENT_RAMP_PATH")

    def test_no_llm_against_live_ramp(self):
        from common import llm_client

        with mock.patch.object(llm_client, "chat", _tripwire), \
             mock.patch.object(llm_client, "chat_raw", _tripwire):
            for mid in ["HMDB0000122", "HMDB0000243", "HMDB0000161", "HMDB0001847", "HMDB0000289"]:
                try:
                    resp = pathway_context(PathwayContextRequest(metabolite_id=mid))
                except MetaboliteNotInNetworkError:
                    # Acceptable — the tool correctly raised instead of
                    # fabricating; we're only checking "no LLM was called",
                    # which is proved by the tripwire not having fired.
                    continue
                assert resp.plausibility_summary
                assert len(resp.plausibility_summary.split()) < 120


# ---------------------------------------------------------------------------
# Test 6: KEGG → HMDB roundtrip via cross-refs.
# ---------------------------------------------------------------------------


class TestKeggHmdbRoundtripMock:
    def test_kegg_then_hmdb_yields_same_compound(self, mock_hmdb_db):
        by_kegg = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier="C00031", id_type="kegg")
        )
        assert by_kegg.found is True
        hmdb = by_kegg.cross_refs.get("hmdb")
        assert hmdb, "KEGG→HMDB roundtrip blocked: no hmdb cross-ref"
        by_hmdb = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier=hmdb, id_type="hmdb")
        )
        assert by_hmdb.found is True
        # Back-roundtrip: same KEGG ID, same InChIKey.
        assert by_hmdb.cross_refs.get("kegg") == by_kegg.cross_refs.get("kegg")
        assert by_hmdb.inchikey == by_kegg.inchikey


@pytest.mark.requires_hmdb_db
class TestKeggHmdbRoundtripReal:
    @pytest.fixture(autouse=True)
    def _require(self, has_hmdb_db):
        if not has_hmdb_db:
            pytest.skip("HMDB SQLite not found at METAGENT_HMDB_PATH")

    def test_kegg_then_hmdb_yields_same_compound(self):
        # Per the audit, real HMDB resolves glucose to KEGG C00221, not C00031.
        # We pick caffeine here because its KEGG ID (C07481) is stable across
        # HMDB curation — caffeine has no stereoisomer ambiguity.
        by_kegg = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier="C07481", id_type="kegg")
        )
        if not by_kegg.found:
            pytest.skip(
                "C07481 (caffeine) not in this HMDB dump; KEGG coverage is ~3%, "
                "so this roundtrip isn't guaranteed for every compound."
            )
        hmdb = by_kegg.cross_refs.get("hmdb")
        assert hmdb, "KEGG→HMDB cross-ref missing in real dump"
        by_hmdb = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier=hmdb, id_type="hmdb")
        )
        assert by_hmdb.found is True
        # Connectivity-only InChIKey comparison (same argument as roundtrip real).
        assert by_hmdb.inchikey is not None and by_kegg.inchikey is not None
        assert by_hmdb.inchikey.split("-")[0] == by_kegg.inchikey.split("-")[0]


# ---------------------------------------------------------------------------
# Test 7: cross-tool InChIKey consistency (SMILES → InChIKey).
# ---------------------------------------------------------------------------


class TestCrossToolInchikeyConsistencyMock:
    def test_stored_inchikey_matches_rdkit_recomputed(self, mock_hmdb_db):
        """Within a single row, SMILES and InChIKey must agree on connectivity.

        Compared on the 14-character connectivity block only: our mock SMILES
        entries (drawn from public pages) sometimes differ in stereo detail
        from the fixture's InChIKey stereo block, and that drift is not a
        tool defect. What matters is that the bonds and atoms agree.
        """
        from common.rdkit_utils import inchikey as rdkit_inchikey

        for entry in _FIXTURE["entries"]:
            resp = fetch_metabolite_info(
                MetaboliteInfoRequest(identifier=entry["hmdb_id"], id_type="hmdb")
            )
            if not (resp.smiles and resp.inchikey):
                continue
            computed = rdkit_inchikey(resp.smiles)
            assert computed is not None, f"{entry['hmdb_id']}: RDKit failed on stored SMILES"
            assert computed.split("-")[0] == resp.inchikey.split("-")[0], (
                f"{entry['hmdb_id']}: connectivity mismatch — "
                f"stored={resp.inchikey!r}, computed={computed!r}"
            )


@pytest.mark.requires_hmdb_db
class TestCrossToolInchikeyConsistencyReal:
    @pytest.fixture(autouse=True)
    def _require(self, has_hmdb_db):
        if not has_hmdb_db:
            pytest.skip("HMDB SQLite not found at METAGENT_HMDB_PATH")

    def test_stored_inchikey_matches_rdkit_recomputed(self):
        from common.rdkit_utils import inchikey as rdkit_inchikey

        mismatches: list[str] = []
        for entry in _FIXTURE["entries"]:
            resp = fetch_metabolite_info(
                MetaboliteInfoRequest(identifier=entry["hmdb_id"], id_type="hmdb")
            )
            if not (resp.found and resp.smiles and resp.inchikey):
                continue
            computed = rdkit_inchikey(resp.smiles)
            if computed != resp.inchikey:
                mismatches.append(
                    f"{entry['hmdb_id']}: stored={resp.inchikey}, "
                    f"computed={computed}, smiles={resp.smiles}"
                )
        # In real HMDB all 10 audit fixtures passed this check; we treat
        # any mismatch as a hard failure because SMILES↔InChIKey inconsistency
        # within a single row indicates data corruption.
        assert not mismatches, "\n".join(mismatches)
