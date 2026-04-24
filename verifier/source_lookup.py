"""Field-path navigator over ``IdentificationReport``.

Used by Layer A (grounded) to look up the field a claim references in the
pipeline output the LLM was actually given. Pure helper — no LLM calls,
no tool calls, no I/O.

Two public entry points:

* :func:`lookup` walks a dotted/bracketed path and returns
  ``(value, path_existed)``. ``path_existed`` distinguishes "the field
  is None" from "the path is wrong" — both relevant for verifier verdicts:
  the former is data legitimately absent (UNVERIFIABLE_V0 territory), the
  latter is the LLM referring to a structure that does not exist.

* :func:`find_candidate_by_name` resolves "the LLM said something about
  D-Gulose — which CandidateReport does that refer to?" Matches against
  ``candidate.name``, ``metabolite_info.primary_name``, and
  ``metabolite_info.synonyms``. Case-insensitive, whitespace-trimmed.

Path grammar (kept deliberately small)::

    path     := segment ('.' segment)*
    segment  := NAME | NAME '[' SUBSCRIPT ']'
    SUBSCRIPT := DIGITS                    # int index into list
              | TOKEN                      # string key into dict

Examples:

* ``candidates[0].metabolite_info.molecular_formula``
* ``candidates[0].candidate.name``
* ``tool_versions[cfm-id]``
* ``candidates[0].pathway_context.pathways[0].id``
"""
from __future__ import annotations

import re
from typing import Any

from schemas.report import CandidateReport, IdentificationReport


_SEGMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\[([^\]]+)\])?$")


# ---------------------------------------------------------------------------
# Path lookup
# ---------------------------------------------------------------------------


def lookup(report: IdentificationReport, path: str) -> tuple[Any, bool]:
    """Walk ``path`` over ``report``. Return ``(value, path_existed)``.

    * ``path_existed=True, value=<x>``  — every segment resolved.
    * ``path_existed=True, value=None`` — every segment resolved, terminal
      value is legitimately ``None`` (e.g. ``metabolite_info`` is None when
      the lookup degraded). Distinct from "wrong path" so Layer A can pick
      the right verdict.
    * ``path_existed=False, value=None`` — a segment is missing (wrong
      attribute name, out-of-range index, missing dict key, intermediate
      None). Layer A maps this to ``UNSUPPORTED``.

    Never raises on a malformed path or a missing field — verification
    failures are data, not exceptions.
    """
    if not path:
        return None, False

    cur: Any = report
    for raw in path.split("."):
        m = _SEGMENT_RE.match(raw.strip())
        if not m:
            return None, False
        attr, sub = m.group(1), m.group(2)

        cur, ok = _step_attr(cur, attr)
        if not ok:
            return None, False

        if sub is not None:
            cur, ok = _step_subscript(cur, sub.strip())
            if not ok:
                return None, False

    return cur, True


def _step_attr(obj: Any, attr: str) -> tuple[Any, bool]:
    """Resolve ``obj.<attr>`` for Pydantic models or dicts. None propagates miss."""
    if obj is None:
        return None, False
    # Pydantic BaseModel-style
    if hasattr(obj, attr):
        return getattr(obj, attr), True
    # Dict fallback
    if isinstance(obj, dict) and attr in obj:
        return obj[attr], True
    return None, False


def _step_subscript(obj: Any, sub: str) -> tuple[Any, bool]:
    """Resolve ``obj[<sub>]``. Tries int-index first, then dict-key."""
    if obj is None:
        return None, False
    # Int index
    if sub.lstrip("-").isdigit():
        idx = int(sub)
        if isinstance(obj, (list, tuple)) and -len(obj) <= idx < len(obj):
            return obj[idx], True
        return None, False
    # Dict key (string)
    if isinstance(obj, dict):
        return (obj[sub], True) if sub in obj else (None, False)
    return None, False


# ---------------------------------------------------------------------------
# Candidate-by-name lookup
# ---------------------------------------------------------------------------


def find_candidate_by_name(
    report: IdentificationReport, name: str
) -> tuple[CandidateReport | None, int | None]:
    """Return ``(candidate_report, index)`` matching ``name`` if any.

    Match priority (first hit wins):
      1. ``candidate.name`` exact (case-insensitive, trimmed)
      2. ``metabolite_info.primary_name`` exact (when ``metabolite_info`` present)
      3. ``metabolite_info.synonyms`` contains the name (exact, case-insensitive)
      4. ``candidate.name`` substring match (e.g. "Gulose" → "D-Gulose")

    Returns ``(None, None)`` on no hit.
    """
    if not name:
        return None, None
    needle = _norm(name)

    # Exact passes (1, 2, 3) before any fuzzy step.
    for i, cr in enumerate(report.candidates):
        if _norm(cr.candidate.name or "") == needle:
            return cr, i
    for i, cr in enumerate(report.candidates):
        mi = cr.metabolite_info
        if mi is not None and _norm(mi.primary_name or "") == needle:
            return cr, i
    for i, cr in enumerate(report.candidates):
        mi = cr.metabolite_info
        if mi is None:
            continue
        if any(_norm(s) == needle for s in mi.synonyms):
            return cr, i

    # Fuzzy substring on candidate.name only — guard last.
    for i, cr in enumerate(report.candidates):
        cname = _norm(cr.candidate.name or "")
        if cname and (needle in cname or cname in needle):
            return cr, i

    return None, None


def _norm(s: str) -> str:
    return s.strip().lower()
