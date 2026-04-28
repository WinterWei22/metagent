"""Integration test for the NM-002 leakage filter on real GNPS data.

Skipped by default. Set ``METAGENT_RUN_INTEGRATION=1`` to enable. Loads a
slice of the real GNPS enriched CSV and verifies the spike fixture's
known leakage case (``MSBNK-RIKEN-PR309407`` self-match for
glutamyltyrosine, documented in
``reports/spike/negative_mode_spike_2026-04-28.md`` §2.3 / §3 NM-002)
is in the exclusion set.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from tools.benchmark.leakage_filter import build_leakage_filter


GNPS_REAL = Path(
    os.environ.get(
        "METAGENT_GNPS_PATH",
        "/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned_enriched.csv",
    )
)
SPIKE_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures" / "spectra" / "negative_mode" / "glutamyltyrosine_neg.json"
)
KNOWN_LEAKED_GNPS_ID = "MSBNK-RIKEN-PR309407"
GLUTAMYLTYROSINE_INCHIKEY_FIRST = "VVLXCWVSSLFQDS"


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("METAGENT_RUN_INTEGRATION") != "1",
    reason="set METAGENT_RUN_INTEGRATION=1 to actually scan the real GNPS dump",
)
def test_glutamyltyrosine_leakage_detected_in_real_gnps(tmp_path: Path) -> None:
    """The spike fixture's PR309407 self-match must be in the exclusion list.

    To keep the test bounded, we slice the real GNPS dump to the rows whose
    InChIKey first block matches glutamyltyrosine OR whose spectrum_id starts
    with ``MSBNK-RIKEN-PR309407``. That subset (a few hundred rows on the
    real dump) covers every record the filter SHOULD catch for this query.
    """
    if not GNPS_REAL.is_file():
        pytest.skip(f"real GNPS dump not found at {GNPS_REAL}")
    if not SPIKE_FIXTURE.is_file():
        pytest.skip(f"spike fixture missing at {SPIKE_FIXTURE}")

    # Slice the real GNPS dump to the relevant subset.
    sliced = tmp_path / "gnps_slice.csv"
    with GNPS_REAL.open("r", encoding="utf-8", errors="replace", newline="") as src, \
         sliced.open("w", encoding="utf-8", newline="") as dst:
        rd = csv.DictReader(src)
        wr = csv.DictWriter(dst, fieldnames=rd.fieldnames)
        wr.writeheader()
        n_kept = 0
        for row in rd:
            ikey = (row.get("InChIKey_smiles") or "").strip()
            sid = (row.get("spectrum_id") or "").strip()
            if (
                (len(ikey) >= 14 and ikey[:14] == GLUTAMYLTYROSINE_INCHIKEY_FIRST)
                or sid.startswith(KNOWN_LEAKED_GNPS_ID)
            ):
                wr.writerow(row)
                n_kept += 1
        assert n_kept > 0, "expected ≥1 row matching glutamyltyrosine in real GNPS"

    # Build a single-record query pool from the spike fixture.
    fix = json.loads(SPIKE_FIXTURE.read_text())
    queries = [
        {
            "source_id": KNOWN_LEAKED_GNPS_ID,
            "ground_truth": {"inchikey": fix["inchikey"]},
        }
    ]

    res = build_leakage_filter(queries, sliced)

    # The literal RIKEN id must be excluded.
    assert KNOWN_LEAKED_GNPS_ID in res.excluded_gnps_ids, (
        f"expected {KNOWN_LEAKED_GNPS_ID} in exclusion set; got "
        f"{sorted(res.excluded_gnps_ids)[:10]}…"
    )
    # And the audit log must record at least one of the three primary
    # triggers for that record.
    rs = res.exclusion_reasons[KNOWN_LEAKED_GNPS_ID]
    assert any(
        r.startswith(("shares_inchikey_first_block_with_query:",
                      "cross_reference_to_riken:",
                      "exact_source_match:"))
        for r in rs
    ), f"audit log missing recognised trigger reason for {KNOWN_LEAKED_GNPS_ID}: {rs}"

    # And the trigger reason matching the spike-documented case (same
    # InChIKey first-block) must be present.
    assert any(
        r == f"shares_inchikey_first_block_with_query:{GLUTAMYLTYROSINE_INCHIKEY_FIRST}"
        for r in rs
    ), (
        "expected an InChIKey-first-block reason for glutamyltyrosine "
        f"({GLUTAMYLTYROSINE_INCHIKEY_FIRST}); got {rs}"
    )
