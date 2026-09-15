"""W14.A D2 RED — concord_react_prompt.md banned-phrase section (3 cases).

Pins the contract that `prompts/concord/concord_react_prompt.md` (W8
ConcordMet system prompt) must add a banned-phrase block instructing
the LLM not to produce meta-filler / template-boilerplate / self-
reference text. This is the upstream half of W14.A — the LLM avoids
emitting strict_noise claims in the first place; the grammar.py noise
detector (see test_grammar_noise_pattern.py) catches anything that
slips through.

Expected at RED: all 3 FAIL (current prompt has no banned-phrase
section per W14 D1 onboarding §0 Tier 2 recon).
"""
from __future__ import annotations

from pathlib import Path


_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "concord" / "concord_react_prompt.md"


def _prompt_text() -> str:
    assert _PROMPT.is_file(), f"prompt file missing at {_PROMPT}"
    return _PROMPT.read_text(encoding="utf-8")


def test_concord_prompt_contains_noise_banned_section():
    """Case 1 — prompt has an explicit banned-phrase section header.

    Expected at RED: FAIL (no such section in current 117-line prompt).
    """
    text = _prompt_text()
    text_lower = text.lower()
    has_section = any(
        kw in text_lower for kw in (
            "## banned phrases",
            "banned phrases — do not write",
            "banned phrases - do not write",
        )
    )
    assert has_section, (
        "concord_react_prompt.md must include a 'BANNED PHRASES' section "
        "header so the LLM can be instructed to avoid noise patterns."
    )


def test_concord_prompt_bans_meta_filler():
    """Case 2 — banned list includes the meta-filler patterns identified
    by §0 re-classification (e.g. "以上是分析结果", "in summary").

    Expected at RED: FAIL.
    """
    text = _prompt_text()
    banned_targets = (
        "以上是分析结果",
        "in summary",
        "in conclusion",
        "future work",
    )
    text_lower = text.lower()
    missing = [t for t in banned_targets if t.lower() not in text_lower]
    assert not missing, (
        f"concord prompt must explicitly ban meta-filler phrases; "
        f"missing: {missing}"
    )


def test_concord_prompt_instructs_against_template_boilerplate():
    """Case 3 — prompt instructs the LLM specifically against
    template-boilerplate / noise patterns (vocabulary that distinguishes
    W14.A noise filtering from the W12 hedge filtering already in the
    prompt).

    Keywords explicitly tied to noise pattern semantics — not the
    existing hedge-language instruction ("waste your output budget"
    already references hedges).

    Expected at RED: FAIL (prompt has no noise/boilerplate-specific
    language).
    """
    text = _prompt_text()
    text_lower = text.lower()
    has_noise_specific = any(
        kw in text_lower for kw in (
            "boilerplate",
            "filler",
            "noise pattern",
            "noise pattern claim",
            "template-style",
            "self-reference",
        )
    )
    assert has_noise_specific, (
        "concord prompt must use noise-pattern-specific instruction "
        "vocabulary (e.g. 'boilerplate', 'filler', 'noise pattern') to "
        "distinguish W14.A noise filtering from the existing hedge "
        "filtering."
    )
