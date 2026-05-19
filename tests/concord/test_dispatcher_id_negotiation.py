"""W9 D2a — dispatcher id-type negotiation (RED → GREEN).

The D1 RED phase exposed a second bug under the "ramp shape gap"
heading: when the LLM passes KEGG `Cxxxxx` IDs (common sub6b-v3
input), the dispatcher's `_ids_to_refs` builds SimpleNamespace refs
with `kegg_compound_id` set but `hmdb_id=None`. The ramp wrapper's
`id_type="auto"` path checks HMDB first → empty → falls back to
InChIKey → also empty → `n_input=0` → 0 pathways. Same story for
`metaboanalystr_psea` whose default `id_type="hmdb"` ignores KEGG.

The W9 D2a fix: enrich `_ids_to_refs` via `concord.lookup.chebi`
ChebiLookup + compound_xref table so each input ID resolves to a
SimpleNamespace with **every available cross-reference populated**
(chebi_id + kegg_compound_id + hmdb_id + inchikey + lipidmaps_id +
display_name). After this, ramp's auto path sees the HMDB IDs and
gets non-zero `n_input_resolved`; psea's hmdb default also works.

Tests are split into two layers:
  - **Unit** (`test_*_input_enriches_with_xrefs`): exercise
    `_ids_to_refs` directly. RED iff the function does not populate
    all available xrefs.
  - **Integration** (`test_ramp_dispatcher_resolves_kegg_input`):
    drive the full dispatcher → wrapper round-trip and check the
    wrapper's own `n_input_resolved` count, not the envelope-level
    `_n_pathways` (which is the D2b shape-gap concern, not D2a).
    RED iff ramp receives empty input.

D2a leaves D2b (output normaliser) and D2c (wrapper-error
surfacing) untouched — those are separate strict-TDD sub-tasks.
"""
from __future__ import annotations

import pytest


# 6 steroid KEGG IDs verified in ChEBI compound_xref (W9 D2a setup,
# 2026-05-19). Each cross-references to a known HMDB + InChIKey,
# making them ideal for round-trip enrichment tests.
STEROID_KEGG_IDS = [
    "C00280",  # CHEBI:16422 / HMDB0000053 / Androstenedione
    "C00468",  # CHEBI:17263 / HMDB0000145 / Estrone
    "C01227",  # CHEBI:28689 / HMDB0000077 / Dehydroepiandrosterone
    "C03917",  # CHEBI:16330 / HMDB0002961 / Dihydrotestosterone
    "C00535",  # CHEBI:17347 / HMDB0000234 / Testosterone
    "C00951",  # CHEBI:16469 / HMDB0000151 / Estradiol
]


# ---------------------------------------------------------------------------
# Unit tests — _ids_to_refs enrichment
# ---------------------------------------------------------------------------


def test_kegg_input_enriches_with_chebi_hmdb_inchikey():
    """KEGG `Cxxxxx` input → ref has chebi_id + hmdb_id + inchikey
    populated via ChebiLookup."""
    from concord.agent.tool_handlers import _ids_to_refs

    refs = _ids_to_refs(["C00280"])
    assert len(refs) == 1
    r = refs[0]
    # kegg_compound_id always set (input)
    assert r.kegg_compound_id and "C00280" in r.kegg_compound_id, (
        f"kegg_compound_id missing/wrong: {r.kegg_compound_id!r}"
    )
    # chebi_id enriched via lookup
    assert r.chebi_id and "16422" in r.chebi_id, (
        f"chebi_id not enriched from KEGG input: {r.chebi_id!r}"
    )
    # hmdb_id enriched (this is the KEY field ramp's auto path checks)
    assert r.hmdb_id and "HMDB0000053" in r.hmdb_id, (
        f"hmdb_id not enriched from KEGG input: {r.hmdb_id!r}"
    )
    # InChIKey populated (27 chars: AEMFNILZOJDQLW-QAGGRKNESA-N)
    assert r.inchikey and len(r.inchikey) == 27, (
        f"inchikey not enriched: {r.inchikey!r}"
    )
    # Display name populated
    assert r.display_name, "display_name not populated"


def test_chebi_input_enriches_with_kegg_hmdb_inchikey():
    """CHEBI: prefixed input → kegg_compound_id + hmdb_id enriched."""
    from concord.agent.tool_handlers import _ids_to_refs

    refs = _ids_to_refs(["CHEBI:16422"])
    r = refs[0]
    assert r.chebi_id and "16422" in r.chebi_id
    assert r.kegg_compound_id and "C00280" in r.kegg_compound_id, (
        f"kegg_compound_id not enriched from CHEBI input: {r.kegg_compound_id!r}"
    )
    assert r.hmdb_id and "HMDB0000053" in r.hmdb_id


def test_hmdb_input_enriches_with_kegg_chebi_inchikey():
    """HMDB input → kegg + chebi populated."""
    from concord.agent.tool_handlers import _ids_to_refs

    refs = _ids_to_refs(["HMDB0000053"])
    r = refs[0]
    assert r.hmdb_id and "HMDB0000053" in r.hmdb_id
    assert r.kegg_compound_id, (
        f"kegg_compound_id not enriched from HMDB input: {r.kegg_compound_id!r}"
    )
    assert r.chebi_id, (
        f"chebi_id not enriched from HMDB input: {r.chebi_id!r}"
    )


def test_inchikey_input_enriches_with_kegg_chebi_hmdb():
    """Full 27-char InChIKey input → ChEBI lookup_by_inchikey enriches all."""
    from concord.agent.tool_handlers import _ids_to_refs

    refs = _ids_to_refs(["AEMFNILZOJDQLW-QAGGRKNESA-N"])
    r = refs[0]
    assert r.inchikey == "AEMFNILZOJDQLW-QAGGRKNESA-N"
    assert r.kegg_compound_id, (
        f"kegg_compound_id not enriched from InChIKey input: {r.kegg_compound_id!r}"
    )
    assert r.chebi_id and "16422" in r.chebi_id


def test_unknown_id_falls_back_safely():
    """Junk input that doesn't resolve → SimpleNamespace built but
    fields are None / empty. No crash, no exception."""
    from concord.agent.tool_handlers import _ids_to_refs

    refs = _ids_to_refs(["TOTALLY_FAKE_ID_XYZ"])
    assert len(refs) == 1
    r = refs[0]
    # Either all None or display_name empty — point is no crash.
    assert getattr(r, "display_name", "") == ""


# ---------------------------------------------------------------------------
# Integration test — dispatcher → ramp wrapper round-trip
# ---------------------------------------------------------------------------


def test_ramp_dispatcher_resolves_kegg_input():
    """Dispatcher passes KEGG IDs → enriched refs → ramp wrapper's
    auto path picks up HMDB → `n_input_resolved > 0`. Asserts at
    wrapper-internal level (NOT envelope `_n_pathways`); the latter
    depends on D2b output normaliser which is a separate sub-task."""
    from concord.agent.tool_dispatcher import dispatch, reset_call_cache
    reset_call_cache()
    result = dispatch({
        "name": "run_ramp_enrichment",
        "arguments": {
            "compound_ids": STEROID_KEGG_IDS,
            "top_n": 10,
        },
    })
    payload = result.payload
    # Wrapper unavailable → xfail (env scope, not D2a's fault)
    if payload.get("error") == "wrapper_unavailable":
        pytest.xfail(f"env issue: {payload.get('reason')}")
    # The dispatcher should at minimum produce ok=True
    assert payload.get("ok") is True, f"unexpected envelope: {payload!r}"
    raw_result = payload.get("result") or {}
    n_resolved = int(raw_result.get("n_input_resolved", 0) or 0)
    assert n_resolved > 0, (
        f"ramp received 0 input even after D2a enrichment: "
        f"id_type_used={raw_result.get('id_type_used')!r}, "
        f"n_input={raw_result.get('n_input')!r}, "
        f"n_input_resolved={n_resolved}"
    )
