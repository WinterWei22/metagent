"""Prompt builder for the Sub-6B ReAct agent path (phase A1).

The single-call path keeps using ``evaluation.sub6.prompts.build_messages``;
this module only handles the new ReAct flow. Loading the template from a
markdown file (``prompts/agent/sub6b_react_prompt.md``) keeps the prose
out of Python source so prompt iteration does not require a code edit.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from evaluation.sub6.prompts import render_metabolite_block

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROMPT_PATH = _REPO_ROOT / "prompts" / "agent" / "sub6b_react_prompt.md"

# Newline-anchored so backtick references inside the prelude HTML comment
# (e.g. "delimited by `## SYSTEM` and `## USER` headers") do not match.
_SYSTEM_HEADER = "\n## SYSTEM\n"
_USER_HEADER = "\n## USER\n"


@lru_cache(maxsize=1)
def _load_template() -> tuple[str, str]:
    """Read the prompt file and split into (system_template, user_template).

    Section bodies are everything after each header up to the next header
    (or EOF). Whitespace is trimmed.

    Cached because the file is small and ReAct runs read it once per task.
    """
    if not _PROMPT_PATH.is_file():
        raise FileNotFoundError(
            f"sub6b ReAct prompt missing at {_PROMPT_PATH}; run "
            "phase A1 from a clean checkout"
        )
    text = _PROMPT_PATH.read_text(encoding="utf-8")

    # Skip the leading HTML comment block (if any) for cleanliness.
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


def render_react_user_prompt(metabolites: list[dict]) -> str:
    _, user_template = _load_template()
    return user_template.format(
        metabolite_block=render_metabolite_block(metabolites)
    )


def build_react_messages(metabolites: list[dict]) -> list[dict]:
    """Produce the initial message list for the Sub-6B ReAct loop."""
    system_body, _ = _load_template()
    return [
        {"role": "system", "content": system_body},
        {"role": "user", "content": render_react_user_prompt(metabolites)},
    ]
