"""W14.A noise-pattern detection for grammar.validate().

Identifies meta-filler / template-boilerplate / self-reference / pasted-
prompt-fragment claim text that should be DROPPED at validation time —
not routed through layer dispatch where it would consume verifier cycles
and surface as UNVERIFIABLE_V0.

Source data (W11 C8 + C9 §0 re-classification, commit 2026-05-25):
14 / 148 W11 C8+C9 claims are strict_noise. Patterns below derive from
that sample.

Pure helper: no I/O, no LLM call. Called by `verifier.grammar.validate()`
BEFORE the BANNED_HEDGES check so meta-filler intent surfaces with the
explicit `noise pattern: ...` drop_reason rather than coincidentally
tripping a hedge match.
"""
from __future__ import annotations

import re


# Each pattern is (label, compiled regex). Label appears in drop_reason
# for downstream attribution. All matches case-insensitive.
_NOISE_PATTERN_REGEXES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Chinese meta-filler / template
    ("meta_filler_zh",   re.compile(r"以上是分析结果|总结如下|如上所述|进一步研究需要|进一步研究表明")),
    # English meta-filler
    ("meta_filler_en",   re.compile(r"\bin\s+summary\b|\bin\s+conclusion\b|\bto\s+summari[sz]e\b", re.IGNORECASE)),
    # Self-reference (claim refers to earlier output rather than carrying content)
    ("self_reference",   re.compile(r"\bas\s+(?:mentioned|noted|stated|described)\s+above\b|\bsee\s+above\b|\bas\s+previously\s+(?:mentioned|stated)\b", re.IGNORECASE)),
    # Template boilerplate — generic "future work" / placeholder framing
    ("template_boilerplate", re.compile(r"\bfuture\s+work\b|\bfurther\s+research\s+(?:is\s+needed|will\s+be|suggests|requires?)\b", re.IGNORECASE)),
    # Pasted prompt fragment ("as a metabolomics analyst" / "you are a ...")
    ("prompt_fragment",  re.compile(r"\bas\s+a\s+metabolomics\s+(?:analyst|expert|researcher)\b|\byou\s+are\s+a\s+(?:metabolomics|biology|biochemistry)\s+", re.IGNORECASE)),
)


def is_noise_claim(claim_text: str) -> str | None:
    """Return the matched pattern label if `claim_text` is a noise claim,
    else None.

    The label form (e.g. ``"meta_filler_en"``) is intended to be embedded
    in a ``drop_reason`` string so the downstream verdict trace explains
    which sub-class of noise was detected.
    """
    if not isinstance(claim_text, str) or not claim_text.strip():
        return None
    for label, pat in _NOISE_PATTERN_REGEXES:
        if pat.search(claim_text):
            return label
    return None
