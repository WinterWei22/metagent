"""Prompt builder for the 2D structural consistency judge layer.

Provides system prompt, user prompt builder, and helper functions to extract
pathway name and metabolite SMILES from a claim + source report.
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

STRUCTURAL_CONSISTENCY_SYSTEM_PROMPT = (
    "You are a precise metabolomics structural verifier. "
    "Determine whether a set of metabolites' chemical structures are "
    "consistent with membership in the claimed metabolic pathway. "
    "Output ONLY a single JSON object. "
    "Do NOT include thinking, reasoning, prose, or markdown fences."
)

# ---------------------------------------------------------------------------
# Pathway extraction from claim
# ---------------------------------------------------------------------------

_PATHWAY_ID_RE = re.compile(
    r"\b("
    r"RAMP_P_\d+"
    r"|map\d{5}"
    r"|hsa\d{5}"
    r"|R-HSA-\d+"
    r"|SMP\d+"
    r"|WP\d+"
    r")\b",
    re.IGNORECASE,
)

_PATHWAY_PHRASE_RE = re.compile(
    r"\b("
    r"[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,5}\s+"
    r"(?:metabolism|biosynthesis|degradation|catabolism|anabolism|"
    r"synthesis|disease|syndrome|cycle|oxidations?|signal[l]?ing|"
    r"transduction|disorder|inhibition|production|pathways?)"
    r")\b",
    re.IGNORECASE,
)


def extract_pathway_from_claim(claim: Any) -> str | None:
    """Return pathway name or ID from claim extracted_fields or text regex.

    Typed extracted_fields win over regex.  Returns None when nothing found.
    """
    typed_name = _claim_nested(claim, "extracted_fields", "pathway_name")
    if typed_name:
        return str(typed_name).strip()

    typed_id = _claim_nested(claim, "extracted_fields", "pathway_id")
    if typed_id:
        return str(typed_id).strip()

    text = _get_text(claim)

    m = _PATHWAY_PHRASE_RE.search(text)
    if m:
        return m.group(0).strip()

    m = _PATHWAY_ID_RE.search(text)
    if m:
        return m.group(1)

    return None


# ---------------------------------------------------------------------------
# Metabolite SMILES extraction
# ---------------------------------------------------------------------------


def extract_metabolites_with_smiles(
    source_report: Any,
    max_items: int = 8,
) -> list[dict[str, str]]:
    """Return up to max_items metabolite dicts that have a non-empty SMILES.

    Each returned dict has keys ``name`` and ``smiles``.
    Metabolites with missing or empty SMILES are excluded.
    """
    raw: list[dict[str, Any]] = _get_differential_metabolites(source_report)
    out: list[dict[str, str]] = []
    for m in raw:
        name = str(m.get("name") or "").strip()
        smiles = str(m.get("smiles") or "").strip()
        if smiles:
            out.append({"name": name or "unknown", "smiles": smiles})
        if len(out) >= max_items:
            break
    return out


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_structural_consistency_prompt(
    *,
    claim_text: str,
    pathway_name: str,
    metabolites: list[dict[str, str]],
) -> str:
    """Build the user-facing prompt for the structural consistency LLM judge."""
    lines = [
        "Judge whether the metabolites below are structurally consistent with "
        f"the claimed pathway: {pathway_name!r}.",
        "",
        f"Claim: {claim_text}",
        "",
        "Metabolites (name | SMILES):",
    ]
    for m in metabolites:
        lines.append(f"  - {m['name']}: {m['smiles']}")
    lines += [
        "",
        "Return JSON with fields:",
        '  "verdict": SUPPORTED | UNSUPPORTED | HEDGED | UNVERIFIABLE_V0',
        '  "confidence": float 0.0-1.0',
        '  "evidence_pointer": metabolite(s) or structural feature that is key',
        '  "rationale": brief structural reasoning (1-2 sentences)',
        "",
        "Rules:",
        "  SUPPORTED (confidence >= 0.85): majority of metabolites have structures"
        " consistent with pathway substrate/intermediate/product classes.",
        "  UNSUPPORTED (confidence >= 0.85): metabolite structures clearly"
        " incompatible with the pathway.",
        "  HEDGED (0.50-0.85): mixed evidence or uncertain pathway-structure link.",
        "  UNVERIFIABLE_V0: pathway too vague to assess structurally.",
        "",
        "IMPORTANT: Output ONLY the JSON object. No prose. No fences.",
        '{"verdict":"...","confidence":0.0,"evidence_pointer":"...","rationale":"..."}',
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _claim_nested(claim: Any, *attrs: str) -> Any:
    val = claim
    for attr in attrs:
        if val is None:
            return None
        val = val.get(attr) if isinstance(val, dict) else getattr(val, attr, None)
    return val


def _get_text(claim: Any) -> str:
    text = _claim_nested(claim, "claim_text")
    return str(text) if text else ""


def _get_differential_metabolites(source_report: Any) -> list[dict[str, Any]]:
    if isinstance(source_report, dict):
        raw = source_report.get("differential_metabolites")
    else:
        raw = getattr(source_report, "differential_metabolites", None)
    if not isinstance(raw, list):
        return []
    return [m for m in raw if isinstance(m, dict)]
