"""Smoke tests for ui.panels.verifier.

Pure-render tests over the panel's `render(verifier_row) -> 4-tuple`
function. No Gradio runtime needed (build_panel exercised lightly in
test_app_imports.py)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ui.panels import verifier as V


def _claim(text, ctype, verdict, *, evidence="ev", correction=None):
    return {
        "claim_text": text,
        "claim_type": ctype,
        "verdict": verdict,
        "evidence": evidence,
        "source_field": None,
        "correction": correction,
    }


def _row(claims, *, overall="partially_verified", llm_calls=5,
         rewritten="rewritten", source="source", warnings=None):
    return {
        "trace_id": "t",
        "overall_verdict": overall,
        "claims_v1": claims,
        "claims_v2": claims,
        "rewritten_output": rewritten,
        "source_llm_output": source,
        "llm_call_count": llm_calls,
        "verification_warnings": warnings or [],
    }


def test_render_none_returns_blank_4tuple_with_message():
    summary, rows, rewritten, warnings = V.render(None)
    assert "no verifier verdict" in summary.lower()
    assert rows == []
    assert rewritten == ""
    assert warnings == ""


def test_render_empty_dict_treated_as_none():
    """Falsy verifier_row → same blank-4tuple path."""
    summary, rows, rewritten, warnings = V.render({})
    assert rows == [] and rewritten == "" and warnings == ""


def test_render_basic_verdict_distribution():
    claims = [
        _claim("D-Gulose has C7H14O7", "grounded_claim", "contradicted",
               evidence="source = C6H12O6", correction="C6H12O6"),
        _claim("Glucose evidence_score 0.761", "grounded_claim", "supported"),
        _claim("ppm <1", "grounded_claim", "unsupported"),
        _claim("upstream of pyruvate", "biological_claim", "unverifiable_v0"),
    ]
    summary, rows, rewritten, warnings = V.render(_row(claims))

    # Summary mentions all four counts
    assert "supported 1" in summary
    assert "contradicted 1" in summary
    assert "unsupported 1" in summary
    assert "unverifiable v0 1" in summary

    # Each row has 5 cols (claim, type, verdict-html, evidence, correction)
    assert len(rows) == 4
    for r in rows:
        assert len(r) == 5
    # Verdict cell carries colour/glyph HTML
    assert "color:#b91c1c" in rows[0][2]  # red for contradicted
    assert "color:#059669" in rows[1][2]  # green for supported
    # Correction propagated for contradicted; "—" for non-contradicted
    assert rows[0][4] == "C6H12O6"
    assert rows[1][4] == "—"
    # Type stripped of "_claim" suffix for compactness
    assert rows[3][1] == "biological"


def test_render_uses_v2_when_present():
    """claims_v2 is the post-rewrite, user-visible state. Prefer it."""
    v1 = [_claim("old C7", "grounded_claim", "contradicted")]
    v2 = [_claim("corrected C6", "grounded_claim", "supported")]
    row = {**_row(v1), "claims_v2": v2}
    _, rows, _, _ = V.render(row)
    assert len(rows) == 1
    assert "corrected C6" in rows[0][0]


def test_render_falls_back_to_v1_when_v2_empty():
    v1 = [_claim("only v1", "grounded_claim", "supported")]
    row = {**_row(v1), "claims_v2": []}
    _, rows, _, _ = V.render(row)
    assert len(rows) == 1
    assert "only v1" in rows[0][0]


def test_render_rewritten_shows_when_differs():
    claims = [_claim("c", "grounded_claim", "contradicted",
                    correction="X")]
    row = _row(claims, rewritten="REWRITTEN BODY", source="ORIGINAL BODY")
    _, _, rewritten, _ = V.render(row)
    assert rewritten == "REWRITTEN BODY"


def test_render_rewritten_collapses_when_equals_source():
    row = _row([_claim("c", "grounded_claim", "supported")],
              rewritten="SAME", source="SAME")
    _, _, rewritten, _ = V.render(row)
    assert "no rewrite needed" in rewritten


def test_render_warnings_block_hidden_when_empty():
    _, _, _, warnings = V.render(_row([]))
    assert warnings == ""


def test_render_warnings_block_shown_when_populated():
    row = _row([], warnings=["VERIFICATION_PARSE_FAILED at stage1: ..."])
    _, _, _, warnings = V.render(row)
    assert "Verifier warnings" in warnings
    assert "PARSE_FAILED" in warnings


def test_render_overall_verdict_colour():
    """The summary line colour-codes the top-level overall_verdict."""
    for verdict in ["verified", "partially_verified", "contradicted", "failed"]:
        summary, *_ = V.render(_row([], overall=verdict))
        assert verdict.replace("_", " ") in summary


def test_render_evidence_truncation():
    long_evidence = "x" * 500
    row = _row([_claim("c", "grounded_claim", "supported", evidence=long_evidence)])
    _, rows, _, _ = V.render(row)
    # Truncated to ~240 chars + ellipsis (per panel.py _truncate constant)
    assert len(rows[0][3]) < 250
    assert rows[0][3].endswith("…") or len(rows[0][3]) <= 240