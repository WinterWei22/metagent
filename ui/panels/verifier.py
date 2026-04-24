"""Panel 4 — Verifier (Track V verdict display).

Reads a ``VerifiedIdentification`` dump (from the
``/data/.../verifier_runs/<trace_id>.verifier.json`` sidecar or from a
fresh in-process Live-mode call) and renders four artifacts:

1. **Summary line** — overall verdict + per-verdict-type counts +
   LLM-call-count for budget visibility.
2. **Verdict table** — one row per VerifiedClaim: text · type · verdict
   (HTML colour-coded) · evidence (truncated) · correction (when the
   verifier proposed one).
3. **Rewritten-narrative accordion** — Stage 4's rewritten output,
   shown only when it differs from the source. Closed by default.
4. **Warnings list** — verifier_warnings surfaced from the cascade
   (parse failures, tool errors, etc.). Hidden when empty.

Designed to be **read-only**. The panel does not invoke the verifier
itself — that's `ui.data.runners.run_live_verifier`'s job. The panel
takes a dict (or None) and renders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import gradio as gr


# ---------------------------------------------------------------------------
# Verdict colour scheme — kept in sync with verifier.schemas.ClaimVerdict
# ---------------------------------------------------------------------------

_VERDICT_COLOUR: dict[str, str] = {
    "supported": "#059669",        # emerald — claim verified against source
    "contradicted": "#b91c1c",     # red    — actively disagrees with source
    "unsupported": "#d97706",      # amber  — no source anchor
    "unverifiable_v0": "#6b7280",  # grey   — known v0 limitation
    "error": "#7c3aed",            # purple — tool / parse failure
}

_VERDICT_GLYPH: dict[str, str] = {
    "supported": "✓",
    "contradicted": "✗",
    "unsupported": "?",
    "unverifiable_v0": "—",
    "error": "!",
}

# Verdicts the summary line surfaces explicitly. Anything else is
# bucketed under "other" so a future ClaimVerdict addition does not
# silently disappear.
_SUMMARY_VERDICTS = (
    "supported",
    "contradicted",
    "unsupported",
    "unverifiable_v0",
    "error",
)


# ---------------------------------------------------------------------------
# Output handles
# ---------------------------------------------------------------------------


@dataclass
class VerifierOutputs:
    summary: gr.Markdown
    verdict_table: gr.Dataframe
    rewritten_body: gr.Markdown
    warnings_md: gr.Markdown


def build_panel() -> tuple[gr.Column, VerifierOutputs]:
    with gr.Column(elem_classes=["metagent-panel", "metagent-output-panel"]) as col:
        gr.Markdown("### 🛡 Verifier (Track V)")
        summary = gr.Markdown(
            "_(no verifier verdict yet — pick a fixture or run Live mode)_"
        )
        verdict_table = gr.Dataframe(
            headers=["Claim", "Type", "Verdict", "Evidence", "Correction"],
            datatype=["str", "str", "html", "str", "str"],
            value=[],
            interactive=False,
            wrap=True,
            elem_id="verifier-verdict-table",
        )
        with gr.Accordion("Rewritten narrative (Stage 4)", open=False):
            rewritten_body = gr.Markdown("")
        warnings_md = gr.Markdown("")
    return col, VerifierOutputs(
        summary=summary,
        verdict_table=verdict_table,
        rewritten_body=rewritten_body,
        warnings_md=warnings_md,
    )


# ---------------------------------------------------------------------------
# Render — pure function over the verifier dict
# ---------------------------------------------------------------------------


def render(
    verifier_row: dict[str, Any] | None,
) -> tuple[str, list[list[str]], str, str]:
    """Return ``(summary_md, table_rows, rewritten_md, warnings_md)``.

    All-empty when ``verifier_row`` is None (no sidecar, Live-mode
    cascade not yet run, etc.). Caller maps the tuple positionally
    onto :class:`VerifierOutputs`.
    """
    if not verifier_row:
        return (
            "_(no verifier verdict for this run — Track V was not executed, "
            "or its sidecar is missing)_",
            [],
            "",
            "",
        )

    claims = _select_claims(verifier_row)
    counts = _count_verdicts(claims)
    overall = (verifier_row.get("overall_verdict") or "").strip()
    llm_calls = verifier_row.get("llm_call_count")

    summary = _render_summary(overall, counts, llm_calls, len(claims))
    rows = [_render_row(c) for c in claims]
    rewritten = _render_rewritten(verifier_row)
    warnings_md = _render_warnings(verifier_row)
    return summary, rows, rewritten, warnings_md


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _select_claims(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Prefer claims_v2 (post-rewrite, what the user finally gets). Fall
    back to claims_v1 if v2 is empty (Stage 4 didn't run because nothing
    was actionable). Final fallback to a flat ``verified_claims`` list
    if a future verifier version exposes one."""
    for key in ("claims_v2", "claims_v1", "verified_claims"):
        v = row.get(key)
        if isinstance(v, list) and v:
            return v
    return []


def _count_verdicts(claims: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {v: 0 for v in _SUMMARY_VERDICTS}
    counts["other"] = 0
    for c in claims:
        v = (c.get("verdict") or "").lower()
        if v in counts:
            counts[v] += 1
        else:
            counts["other"] += 1
    return counts


def _render_summary(
    overall: str,
    counts: dict[str, int],
    llm_calls: Any,
    n_claims: int,
) -> str:
    overall_label = overall.replace("_", " ") if overall else "?"
    overall_colour = {
        "verified": "#059669",
        "partially_verified": "#d97706",
        "contradicted": "#b91c1c",
        "failed": "#7c3aed",
    }.get(overall, "#6b7280")
    badges = " · ".join(
        _badge(v, counts[v]) for v in _SUMMARY_VERDICTS if counts.get(v)
    )
    if counts.get("other"):
        badges = (badges + " · " if badges else "") + _badge("other", counts["other"])
    return (
        f"<div style='font-size:0.95em'>"
        f"<strong>Overall: <span style='color:{overall_colour}'>{overall_label}</span></strong>  "
        f"·  {n_claims} claim(s)"
        + (f"  ·  LLM calls used: {llm_calls}" if llm_calls is not None else "")
        + (f"<br/>{badges}" if badges else "")
        + "</div>"
    )


def _badge(verdict: str, count: int) -> str:
    colour = _VERDICT_COLOUR.get(verdict, "#6b7280")
    glyph = _VERDICT_GLYPH.get(verdict, "•")
    return (
        f"<span style='color:{colour};font-weight:600'>"
        f"{glyph} {verdict.replace('_', ' ')} {count}</span>"
    )


def _render_row(claim: dict[str, Any]) -> list[str]:
    verdict = (claim.get("verdict") or "").lower()
    colour = _VERDICT_COLOUR.get(verdict, "#6b7280")
    glyph = _VERDICT_GLYPH.get(verdict, "•")
    badge = (
        f"<span style='color:{colour};font-weight:600;white-space:nowrap'>"
        f"{glyph} {verdict.replace('_', ' ')}</span>"
    )
    return [
        (claim.get("claim_text") or "").strip(),
        (claim.get("claim_type") or "").replace("_claim", ""),
        badge,
        _truncate((claim.get("evidence") or "").strip(), 240),
        (claim.get("correction") or "—").strip(),
    ]


def _truncate(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def _render_rewritten(row: dict[str, Any]) -> str:
    rewritten = (row.get("rewritten_output") or "").strip()
    source = (row.get("source_llm_output") or "").strip()
    if not rewritten:
        return "_(no rewrite available — verifier did not produce one)_"
    if rewritten == source:
        return "_(no rewrite needed — every claim was supported or out of scope)_"
    return rewritten


def _render_warnings(row: dict[str, Any]) -> str:
    warnings = row.get("verification_warnings") or []
    if not warnings:
        return ""
    bullets = "\n".join(f"- {w}" for w in warnings)
    return (
        "<details><summary><strong>Verifier warnings ("
        f"{len(warnings)})</strong></summary>\n\n"
        f"{bullets}\n\n</details>"
    )
