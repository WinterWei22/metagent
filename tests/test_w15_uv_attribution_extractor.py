"""W15 D1 RED — UV claim pool extractor (3 cases).

Pins the contract a `scripts/metagent/w15_uv_attribution.extract_uv_claim_pool`
function must satisfy for the audit pipeline:

  1. Count matches W14 final-iter UV aggregate (901 ± 2 tolerance per HG-1)
  2. All extracted claims carry verdict == 'UNVERIFIABLE_V0' (no leak of
     SUPPORTED / UNSUPPORTED / CONTRADICTED)
  3. Schema completeness — each claim has claim_id / claim_text /
     claim_type / verifier_layer / task_id / verdict / evidence

W14 path-x trace files live at
`data/concord/w14_path_x_post_noise_cap/path_x_full/<task_id>.json`
(63 files). The script extracts UV from the final iter of each task's
stringified VerifiedIdentification verdict repr (same approach as
W11 / W13.C extractors).

Expected at RED: all 3 cases FAIL (ImportError / AttributeError —
extract_uv_claim_pool not yet implemented).
"""
from __future__ import annotations

from pathlib import Path

# Locate trace dir relative to repo root (conftest.py adds ROOT to sys.path).
_W14_TRACE_DIR = (
    Path(__file__).resolve().parents[1]
    / "data" / "concord" / "w14_path_x_post_noise_cap" / "path_x_full"
)


def test_extractor_count_matches_w14_baseline():
    """Case 1 — extracted UV count = 901 ± 2 (per W14 close-out 44.25 %
    × 2036 total claims).

    Expected at RED: FAIL (extractor module not yet importable).
    """
    from scripts.metagent.w15_uv_attribution import extract_uv_claim_pool

    pool = extract_uv_claim_pool(_W14_TRACE_DIR)
    assert 899 <= len(pool) <= 903, (
        f"UV count {len(pool)} outside HG-1 tolerance 901 ± 2"
    )


def test_extractor_only_uv_verdicts():
    """Case 2 — every extracted claim has verdict == 'UNVERIFIABLE_V0'.
    No leak of other verdict types.

    Expected at RED: FAIL.
    """
    from scripts.metagent.w15_uv_attribution import extract_uv_claim_pool

    pool = extract_uv_claim_pool(_W14_TRACE_DIR)
    assert pool, "extractor returned empty pool"
    bad = [c for c in pool if c.get("verdict") != "UNVERIFIABLE_V0"]
    assert not bad, (
        f"non-UV verdicts leaked: {len(bad)} claims, first: {bad[:2]!r}"
    )


def test_extractor_schema_has_required_fields():
    """Case 3 — each claim has the schema the downstream classifier
    requires: claim_id, claim_text, claim_type, verifier_layer,
    task_id, verdict, evidence.

    Expected at RED: FAIL.
    """
    from scripts.metagent.w15_uv_attribution import extract_uv_claim_pool

    pool = extract_uv_claim_pool(_W14_TRACE_DIR)
    assert pool, "extractor returned empty pool"
    required = {
        "claim_id", "claim_text", "claim_type",
        "verifier_layer", "task_id", "verdict", "evidence",
    }
    sample = pool[:10]  # spot 10 to catch missing keys per row
    for i, c in enumerate(sample):
        missing = required - set(c.keys())
        assert not missing, (
            f"claim[{i}] missing fields: {missing}; keys present: "
            f"{sorted(c.keys())}"
        )
