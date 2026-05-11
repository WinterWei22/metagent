"""Test for phase A3 D4a — Layer 6d KEGG SQL warning fix.

Pre-A3, ``_phrase_to_kegg_id`` queried ``pathwaySourceId`` and
``pathwaySource`` from the RaMP ``pathway`` table. Neither column
exists; sqlite raised "no such column", the surrounding try/except
caught it, and the function returned ``None`` for every input. KEGG
pathway-pair claims were forced to ``UNVERIFIABLE_V0``.

These tests confirm:
  (1) the corrected SQL returns a real KEGG pathway ID for a
      well-known phrase (no exception, returns non-None)
  (2) the regex-normalisation that follows the SQL still works
      (returns ``hsa<NNNNN>`` shape)

They run against the real RaMP sqlite at ``$METAGENT_RAMP_PATH`` and
are skipped when that DB is not available (CI without DB).
"""
from __future__ import annotations

import os
import sqlite3
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from verifier.layers.pathway_relationship import _phrase_to_kegg_id


_RAMP_PATH = os.environ.get(
    "METAGENT_RAMP_PATH",
    "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite",
)
_HAS_RAMP = os.path.isfile(_RAMP_PATH)
_SKIP_REASON = f"RaMP sqlite not available at {_RAMP_PATH}"


@pytest.fixture
def ramp_cursor():
    if not _HAS_RAMP:
        pytest.skip(_SKIP_REASON)
    conn = sqlite3.connect(f"file:{_RAMP_PATH}?mode=ro", uri=True)
    try:
        yield conn.cursor()
    finally:
        conn.close()


class TestSqlFixD4a:
    def test_glycolysis_resolves_to_hsa_pathway_id(self, ramp_cursor):
        """A common KEGG pathway phrase must now resolve to ``hsa00010``."""
        result = _phrase_to_kegg_id(ramp_cursor, "Glycolysis / Gluconeogenesis")
        assert result is not None
        assert result.startswith("hsa")
        assert result[3:].isdigit()
        assert len(result[3:]) == 5

    def test_unknown_phrase_returns_none_not_raise(self, ramp_cursor):
        """Phrase that doesn't match any KEGG pathway returns None cleanly."""
        result = _phrase_to_kegg_id(ramp_cursor, "this_phrase_will_not_match_any_real_pathway_xyz")
        assert result is None

    def test_no_sql_warning_logged(self, ramp_cursor, caplog):
        """Pre-A3, sqlite raised "no such column: pathwaySourceId" which the
        outer try/except converted to a warning. Post-A3 there should be
        no such warning under normal queries."""
        import logging
        caplog.set_level(logging.WARNING, logger="verifier.layers.pathway_relationship")
        # Run a few different phrases.
        for phrase in [
            "Pyrimidine metabolism",
            "TCA cycle",
            "Glycolysis / Gluconeogenesis",
            "no-such-pathway-xyz",
        ]:
            _phrase_to_kegg_id(ramp_cursor, phrase)
        sql_warnings = [
            r for r in caplog.records
            if "no such column" in r.getMessage()
        ]
        assert sql_warnings == [], (
            f"Expected no 'no such column' warnings, got "
            f"{[r.getMessage() for r in sql_warnings]}"
        )

    def test_pyrimidine_metabolism_known_kegg_id(self, ramp_cursor):
        """Pyrimidine metabolism = hsa00240. Sanity-pin a verifiable mapping."""
        result = _phrase_to_kegg_id(ramp_cursor, "Pyrimidine metabolism")
        assert result == "hsa00240"
