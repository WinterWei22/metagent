"""ReAct prompt builder for ConcordMet (W8, track CONCORD).

Loads `prompts/concord/concord_react_prompt.md`, splits on `## SYSTEM`
and `## USER` headers, and renders the user body with the differential-
metabolite block. Mirrors `evaluation/sub6/prompts_agent.py` so the
contract is familiar.

Why a sibling module rather than reusing the B1 builder:
  - System prompt content differs: 9 ConcordMet tools instead of 5,
    grammar-v2 final-message JSON spec, and the "LLM does cross-paradigm
    integration itself, do NOT look for an aggregator tool" rule.
  - Reusing `render_metabolite_block` from B1 is fine (and intended) —
    the bullet shape is the same for sub6b tasks.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from evaluation.sub6.prompts import render_metabolite_block


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROMPT_PATH = _REPO_ROOT / "prompts" / "concord" / "concord_react_prompt.md"

# Newline-anchored so backtick references inside the prelude HTML
# comment don't false-match.
_SYSTEM_HEADER = "\n## SYSTEM\n"
_USER_HEADER = "\n## USER\n"


@lru_cache(maxsize=1)
def _load_template() -> tuple[str, str]:
    """Read the prompt file, split into (system_template, user_template).

    Sections are everything after each header up to the next header (or
    EOF), whitespace-trimmed.
    """
    if not _PROMPT_PATH.is_file():
        raise FileNotFoundError(
            f"ConcordMet ReAct prompt missing at {_PROMPT_PATH}; "
            "W8 D1 should have created it."
        )
    text = _PROMPT_PATH.read_text(encoding="utf-8")
    sys_idx = text.find(_SYSTEM_HEADER)
    usr_idx = text.find(_USER_HEADER, sys_idx + 1)
    if sys_idx == -1 or usr_idx == -1:
        raise ValueError(
            f"prompt file {_PROMPT_PATH} must contain both "
            f"'{_SYSTEM_HEADER}' and '{_USER_HEADER}' headers"
        )
    system_body = text[sys_idx + len(_SYSTEM_HEADER) : usr_idx].strip()
    user_body = text[usr_idx + len(_USER_HEADER) :].strip()
    return system_body, user_body


def render_concord_user_prompt(metabolites: list[dict]) -> str:
    """Render the user-role message body for a single sub6b task."""
    _, user_template = _load_template()
    return user_template.format(
        metabolite_block=render_metabolite_block(metabolites)
    )


def build_concord_react_messages(metabolites: list[dict]) -> list[dict]:
    """Initial OpenAI-style message list for a ConcordMet ReAct task."""
    system_body, _ = _load_template()
    return [
        {"role": "system", "content": system_body},
        {"role": "user", "content": render_concord_user_prompt(metabolites)},
    ]


def get_system_prompt() -> str:
    """Return the system-role body verbatim. Used by tests / inspection."""
    system_body, _ = _load_template()
    return system_body
