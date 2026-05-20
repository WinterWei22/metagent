"""CI guard: BANNED_* in verifier/grammar.py must match the snapshots
embedded in the Sub-6 narrative prompts.

If grammar.py grows a new banned phrase (e.g. D2 / D5 finds another
hallucination pattern) but the prompt files are not updated, the LLM
will keep emitting the phrase, the verifier will silently drop those
claims, and the supported / dropped_by_grammar metric will move for the
wrong reason. Catching the drift in CI keeps the prompt and the
verifier on the same source of truth.

The split is:

* ``_FULL_SNAPSHOT_PROMPTS`` — the system-prompt files that LIST every
  banned token verbatim inside markdown backticks. Each token must
  appear in those files.
* ``_REFERENCE_PROMPTS`` — the feedback turn prompt. It is loaded into
  an LLM session that has already seen the full snapshot via the
  system prompt, so it only needs to NAME the banned categories so the
  model can map a feedback hint back to one of them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from verifier import grammar as G

_REPO = Path(__file__).resolve().parents[1]

_FULL_SNAPSHOT_PROMPTS: tuple[Path, ...] = (
    _REPO / "evaluation" / "sub6" / "prompts.py",
    _REPO / "prompts" / "agent" / "sub6b_react_prompt.md",
)

_REFERENCE_PROMPTS: tuple[Path, ...] = (
    _REPO / "prompts" / "agent" / "sub6b_react_feedback_prompt.md",
)

# Any backtick-delimited span. We match single-backtick spans too because
# the prompts use both ``foo`` (markdown two-backtick) and `foo`
# (single-backtick inline) styles.
_BACKTICK_RE = re.compile(r"``([^`]+?)``|`([^`]+?)`")


def _backtick_tokens(text: str) -> set[str]:
    """Return every token that appears between backticks in ``text``."""
    found: set[str] = set()
    for m in _BACKTICK_RE.finditer(text):
        token = (m.group(1) or m.group(2) or "").strip()
        if token:
            found.add(token)
    return found


_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("BANNED_HEDGES", G.BANNED_HEDGES),
    ("BANNED_DIRECTIONAL", G.BANNED_DIRECTIONAL),
    ("BANNED_ABSTRACT", G.BANNED_ABSTRACT),
    ("BANNED_META", G.BANNED_META),
)


@pytest.mark.parametrize(
    "prompt_path", _FULL_SNAPSHOT_PROMPTS, ids=lambda p: p.name
)
def test_prompt_full_snapshot_includes_every_banned_token(
    prompt_path: Path,
) -> None:
    """Every token in BANNED_HEDGES / DIRECTIONAL / ABSTRACT / META must
    appear (inside backticks) in each full-snapshot prompt file."""
    assert prompt_path.is_file(), f"prompt not found: {prompt_path}"
    text = prompt_path.read_text(encoding="utf-8")
    tokens = _backtick_tokens(text)
    drift: dict[str, list[str]] = {}
    for cat_name, cat_tokens in _CATEGORIES:
        missing = [t for t in cat_tokens if t not in tokens]
        if missing:
            drift[cat_name] = missing
    assert not drift, (
        f"\n{prompt_path.name} drifted from verifier/grammar.py — "
        "re-sync the prompt's banned-snapshot section.\n"
        + "\n".join(f"  {k}: {v}" for k, v in drift.items())
    )


def test_prompt_full_snapshot_mentions_tool_roundtrip_examples() -> None:
    """BANNED_TOOL_ROUNDTRIP_PATTERNS is a regex list, not a token list.
    Verify each full-snapshot prompt at least names the category and
    lists a representative example so the LLM can recognise the shape.
    """
    must_mention = ("KEGG ID", "HMDB ID", "molecular formula")
    for prompt_path in _FULL_SNAPSHOT_PROMPTS:
        text = prompt_path.read_text(encoding="utf-8")
        missing = [m for m in must_mention if m not in text]
        assert not missing, (
            f"{prompt_path.name} does not mention tool-roundtrip "
            f"examples: {missing}"
        )


@pytest.mark.parametrize(
    "prompt_path", _REFERENCE_PROMPTS, ids=lambda p: p.name
)
def test_feedback_prompt_references_banned_categories(
    prompt_path: Path,
) -> None:
    """Feedback turn is loaded into an existing session; it only needs
    to NAME the categories so the model can map a verifier hint to a
    bucket."""
    text = prompt_path.read_text(encoding="utf-8").lower()
    must_reference = ("hedges", "direction", "abstract", "meta", "tool")
    missing = [m for m in must_reference if m not in text]
    assert not missing, (
        f"{prompt_path.name} must reference banned categories by name; "
        f"missing: {missing}"
    )


def test_grammar_banned_directional_excludes_drives() -> None:
    """Regression: ``drives`` / ``driving`` are NOT banned (they are the
    canonical verb for the driver_metabolite grammar). If this fails,
    issue #1 from the D0 review snuck back in."""
    forbidden = {"drives", "driving", "drives the", "driving the"}
    bad = forbidden & set(G.BANNED_DIRECTIONAL)
    assert not bad, (
        f"BANNED_DIRECTIONAL must NOT contain {bad} — they collide "
        "with the legitimate DriverMetaboliteClaim shape."
    )
