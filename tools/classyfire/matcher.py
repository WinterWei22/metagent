"""Claim matching helpers for ClassyFire classifications."""
from __future__ import annotations

import re
from difflib import SequenceMatcher


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if len(t) >= 4]


def matches_claim(claimed_class: str, classifications: list[str]) -> bool:
    """Return True when a free-text class claim is supported by ClassyFire nodes."""
    if not claimed_class or not classifications:
        return False

    nodes = [c.lower() for c in classifications if c]
    claim = claimed_class.strip().lower()
    if not claim:
        return False

    if any(claim in node or node in claim for node in nodes):
        return True

    tokens = _tokens(claim)
    if tokens:
        if all(any(token in node for node in nodes) for token in tokens):
            return True
        if any(any(token in node for node in nodes) for token in tokens):
            return True

    for token in tokens or [claim]:
        for node in nodes:
            node_tokens = _tokens(node) or [node]
            if any(SequenceMatcher(None, token, nt).ratio() >= 0.8 for nt in node_tokens):
                return True
            if SequenceMatcher(None, token, node).ratio() >= 0.8:
                return True

    return False
