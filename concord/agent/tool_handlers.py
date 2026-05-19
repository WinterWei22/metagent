"""W8 D2 — 9 ConcordMet LLM function-tool handlers.

Each handler is invoked by `concord.agent.tool_dispatcher.dispatch()`
after the dispatcher has parsed the OpenAI-style tool_call, coerced
its `arguments` to a dict, and consulted the per-call dedup cache.

Handler contract (uniform envelope):

  Success:
      {
          "ok": True,
          "result": <serialised wrapper output>,
          "_tool_name": "<name>",
          "_n_pathways": <int, if applicable>,
          "_n_compound_refs": <int, if applicable>,
      }

  Argument-validation failure (LLM sent a malformed call):
      {
          "error": "<short reason>",
          "fallback_suggested": "<concrete fix the LLM can act on>",
          "_tool_name": "<name>",
      }

  Wrapper unavailable (import failed; env missing the heavy dep):
      {
          "error": "wrapper_unavailable",
          "reason": "<exception detail>",
          "fallback_suggested": "<name of another tool covering the same paradigm>",
          "_tool_name": "<name>",
      }

  Data unavailable (sqlite cohort lookup miss; expected gap):
      {
          "error": "data_not_available" | "not_found",
          "reason": "<...>",
          "fallback_suggested": "<...>",
          "_tool_name": "<name>",
      }

Handlers **never raise**: any unexpected exception is caught by the
dispatcher and wrapped in the standard error envelope so the LLM can
react rather than crash the ReAct loop.

Imports of the underlying wrapper modules are deferred to call-time so
(a) environments missing sspa / Docker R / mummichog venv can still
import this package and stub the missing handler with a clean
`wrapper_unavailable` envelope, and (b) unit tests can
`monkeypatch.setattr` the wrapper's module-level function and have the
handler pick up the patched value via a fresh module-attribute lookup.
"""
from __future__ import annotations

import dataclasses
import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument adapters
# ---------------------------------------------------------------------------


def _err(
    tool_name: str,
    *,
    error: str,
    fallback_suggested: str,
    **extra: Any,
) -> dict[str, Any]:
    """Build a structured error envelope. Never raises."""
    out: dict[str, Any] = {
        "error": error,
        "fallback_suggested": fallback_suggested,
        "_tool_name": tool_name,
    }
    out.update(extra)
    return out


def _ok(
    tool_name: str,
    result: Any,
    **meta: Any,
) -> dict[str, Any]:
    """Build a success envelope with optional `_meta` fields prefixed `_`."""
    out: dict[str, Any] = {
        "ok": True,
        "result": result,
        "_tool_name": tool_name,
    }
    for k, v in meta.items():
        out[f"_{k}"] = v
    return out


def _validate_compound_ids(
    arguments: dict[str, Any],
    tool_name: str,
) -> dict[str, Any] | None:
    """Common validator for the 5 PA tools. Returns error envelope or None."""
    cid = arguments.get("compound_ids")
    if cid is None:
        return _err(
            tool_name,
            error="missing required field 'compound_ids'",
            fallback_suggested=(
                "pass 'compound_ids' as a non-empty JSON array of ID strings, "
                "e.g. [\"CHEBI:17234\", \"C00031\"]"
            ),
        )
    if not isinstance(cid, list):
        return _err(
            tool_name,
            error=(
                f"'compound_ids' must be a list of strings, "
                f"got {type(cid).__name__}"
            ),
            fallback_suggested=(
                "wrap your compound IDs as a JSON array, "
                "e.g. [\"CHEBI:17234\"]"
            ),
        )
    if not cid:
        return _err(
            tool_name,
            error="'compound_ids' must be non-empty",
            fallback_suggested="pass at least one compound identifier",
        )
    if not all(isinstance(x, str) and x.strip() for x in cid):
        return _err(
            tool_name,
            error="each element of 'compound_ids' must be a non-empty string",
            fallback_suggested=(
                "use ID strings like 'CHEBI:17234' / 'KEGG:C00031' / "
                "'HMDB0000122' / 'LIPIDMAPS:LMFA01030001'"
            ),
        )
    return None


# Module-level lazy singleton for the ChEBI sqlite lookup. The handler
# wraps every call in a try/except so a missing sqlite (un-seeded dev
# env) silently falls back to the no-enrichment legacy path.
_CHEBI_LOOKUP_SINGLETON: Any = None  # ChebiLookup | None | False (False = unavailable)


def _get_chebi_lookup():
    """Lazy-load + cache the ChebiLookup singleton.

    Returns the ChebiLookup instance on success, or None if the sqlite
    is missing (so callers fall back to the legacy no-enrichment path
    without raising). Cached at module scope so the per-call setup
    cost is paid once per process.
    """
    global _CHEBI_LOOKUP_SINGLETON
    if _CHEBI_LOOKUP_SINGLETON is None:
        try:
            from concord.lookup.chebi import ChebiLookup
            _CHEBI_LOOKUP_SINGLETON = ChebiLookup()
        except (FileNotFoundError, ImportError):
            _CHEBI_LOOKUP_SINGLETON = False
    return _CHEBI_LOOKUP_SINGLETON if _CHEBI_LOOKUP_SINGLETON else None


def _detect_input_namespace(s: str) -> str | None:
    """Best-effort namespace detector for a raw ID string.

    Returns "CHEBI" / "HMDB" / "KEGG" / "LIPIDMAPS" / "INCHIKEY", or
    None if the string doesn't match any known shape.
    """
    s_up = s.upper()
    if s_up.startswith("CHEBI:") or (s.isdigit() and len(s) <= 7):
        return "CHEBI"
    if s_up.startswith("HMDB"):
        return "HMDB"
    if s_up.startswith("KEGG:") or (
        s.startswith("C") and len(s) >= 6 and s[1:].lstrip("0").isdigit()
    ):
        return "KEGG"
    if s_up.startswith("LIPIDMAPS:") or s_up.startswith("LM"):
        return "LIPIDMAPS"
    if len(s) == 27 and s.count("-") == 2 and all(
        part.isalnum() for part in s.split("-")
    ):
        return "INCHIKEY"
    return None


def _fetch_all_xrefs_for_chebi(lookup, chebi_numeric: str) -> dict[str, str]:
    """Query compound_xref via the ChebiLookup connection to fetch
    one cross-reference per external namespace.

    Returns a dict like ``{"HMDB": "HMDB0000053", "KEGG": "C00280",
    "LIPIDMAPS": "LMST02030001", "INCHIKEY": "..."}``. The query
    picks the LEXICALLY FIRST external_id per namespace so the result
    is deterministic across runs even when ChEBI has multiple xrefs
    for the same (chebi_id, ns) pair (e.g. CAS + KEGG cpd ids both
    sit in the KEGG namespace bucket — we prefer 'Cxxxxx' shape).
    """
    out: dict[str, str] = {}
    with lookup._conn() as c:
        # For KEGG: filter to "Cxxxxx" pattern, prefer those over CAS.
        # For other namespaces: take the lexically-smallest id.
        rows = c.execute(
            "SELECT external_ns, external_id FROM compound_xref "
            "WHERE chebi_id = ? "
            "  AND external_ns IN ('HMDB', 'KEGG', 'LIPIDMAPS') "
            "ORDER BY external_ns, external_id",
            (chebi_numeric,),
        ).fetchall()
    for ns, ext in rows:
        if ns == "KEGG":
            # Strong preference: Cxxxxx ALWAYS wins over CAS RN. The
            # compound_xref table commingles both in the same KEGG
            # bucket; iterating in sorted order means CAS lands first
            # (numeric < alpha), so we must override when we later
            # see a Cxxxxx form rather than skip it.
            is_cpd_id = (
                ext.startswith("C")
                and len(ext) >= 4
                and ext[1:].lstrip("0").isdigit()
            )
            if is_cpd_id:
                out["KEGG"] = ext  # upgrade past any earlier CAS
            elif out.get("KEGG") is None:
                out["KEGG"] = ext  # CAS only if no Cxxxxx will come later
        else:
            if out.get(ns) is None:
                out[ns] = ext
    return out


def _enrich_ref_via_chebi(s: str, ns_hint: str | None) -> dict[str, Any]:
    """Resolve an input ID string to ChEBI + fetch all cross-references.

    Returns a dict suitable for SimpleNamespace splat
    ({primary_id, chebi_id, hmdb_id, kegg_compound_id, lipidmaps_id,
    inchikey, display_name}). When the ChEBI sqlite is unavailable or
    the input doesn't resolve, returns a minimal dict matching the
    legacy single-namespace behavior (so wrappers still get something
    even when the enrichment path fails).
    """
    lookup = _get_chebi_lookup()
    rec = None
    if lookup is not None and ns_hint:
        if ns_hint == "CHEBI":
            num = s.replace("CHEBI:", "").replace("chebi:", "").strip()
            try:
                rec = lookup.get_compound(num)
            except (ValueError, TypeError):
                rec = None
        elif ns_hint == "HMDB":
            ext_id = s.replace("HMDB:", "").replace("hmdb:", "").strip()
            rec = lookup.lookup_by_xref("HMDB", ext_id)
        elif ns_hint == "KEGG":
            ext_id = s.replace("KEGG:", "").replace("kegg:", "").strip()
            rec = lookup.lookup_by_xref("KEGG", ext_id)
        elif ns_hint == "LIPIDMAPS":
            ext_id = s.replace("LIPIDMAPS:", "").replace("lipidmaps:", "").strip()
            rec = lookup.lookup_by_xref("LIPIDMAPS", ext_id)
        elif ns_hint == "INCHIKEY":
            recs = lookup.lookup_by_inchikey(s)
            rec = recs[0] if recs else None

    if rec is not None:
        xrefs = _fetch_all_xrefs_for_chebi(lookup, rec.chebi_id)
        primary_id = rec.primary_id
        return {
            "primary_id": primary_id,
            "chebi_id": primary_id,
            "hmdb_id": f"HMDB:{xrefs['HMDB']}" if xrefs.get("HMDB") else None,
            "kegg_compound_id": f"KEGG:{xrefs['KEGG']}" if xrefs.get("KEGG") else None,
            "lipidmaps_id": f"LIPIDMAPS:{xrefs['LIPIDMAPS']}" if xrefs.get("LIPIDMAPS") else None,
            "inchikey": rec.inchikey or "",
            "display_name": rec.name or "",
        }

    # Legacy fallback — single namespace populated, no enrichment
    return _legacy_single_namespace_dict(s, ns_hint)


def _legacy_single_namespace_dict(s: str, ns_hint: str | None) -> dict[str, Any]:
    """Single-namespace SimpleNamespace shape — used when ChEBI lookup
    misses or is unavailable. Preserves the W8 D2 behavior for unknown
    IDs so wrappers still see *something* to try."""
    primary_id = s
    chebi_id = hmdb_id = kegg = lipidmaps = None
    inchikey = ""
    if ns_hint == "CHEBI":
        primary_id = s if s.upper().startswith("CHEBI:") else f"CHEBI:{s}"
        chebi_id = primary_id
    elif ns_hint == "HMDB":
        primary_id = s if s.upper().startswith("HMDB:") else f"HMDB:{s}"
        hmdb_id = primary_id
    elif ns_hint == "KEGG":
        primary_id = s if s.upper().startswith("KEGG:") else f"KEGG:{s}"
        kegg = primary_id
    elif ns_hint == "LIPIDMAPS":
        primary_id = s if s.upper().startswith("LIPIDMAPS:") else f"LIPIDMAPS:{s}"
        lipidmaps = primary_id
    elif ns_hint == "INCHIKEY":
        primary_id = f"INCHIKEY:{s}"
        inchikey = s
    # else: unknown — primary_id=s, all xref fields None
    return {
        "primary_id": primary_id,
        "chebi_id": chebi_id,
        "hmdb_id": hmdb_id,
        "kegg_compound_id": kegg,
        "lipidmaps_id": lipidmaps,
        "inchikey": inchikey,
        "display_name": "",
    }


def _ids_to_refs(compound_ids: list[str]) -> list[SimpleNamespace]:
    """Build duck-typed CompoundRef objects from string IDs, enriched
    via ChebiLookup + compound_xref so every available cross-reference
    is populated (W9 D2a fix).

    Each ref carries: primary_id, chebi_id, hmdb_id, kegg_compound_id,
    lipidmaps_id, inchikey, display_name. PA wrappers read whichever
    field their id_type negotiation prefers (ramp auto path: hmdb →
    inchikey; metaboanalystr_psea: hmdb default; fella:
    kegg_compound_id with ChEBI→KEGG xref fallback).

    The enrichment is per-input (one ChEBI sqlite query + one xref
    query per compound_id), which on a 9-compound task costs ~20 ms
    total. Falls back silently to the legacy single-namespace shape
    when ChEBI sqlite is unavailable or an input doesn't resolve.
    """
    refs: list[SimpleNamespace] = []
    for raw in compound_ids:
        s = raw.strip()
        ns_hint = _detect_input_namespace(s)
        enriched = _enrich_ref_via_chebi(s, ns_hint)
        refs.append(SimpleNamespace(**enriched))
    return refs


def _top_n_or_default(arguments: dict[str, Any], default: int = 10) -> int:
    """Clamp top_n to [1, 50] and default to 10. Returns int."""
    raw = arguments.get("top_n", default)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(50, n))


# ---------------------------------------------------------------------------
# 5 PA handlers (sspa / ramp / metaboanalystr / mummichog / fella)
# ---------------------------------------------------------------------------


def _count_pathways_compounds(result: dict[str, Any]) -> tuple[int, int]:
    pathways = result.get("pathways") or []
    n_paths = len(pathways)
    n_refs = sum(len(p.get("metabolites_hit") or []) for p in pathways)
    return n_paths, n_refs


# Errors that signal "heavy dep missing in this env" and should be
# converted to a wrapper_unavailable envelope rather than propagated up.
# Note: ModuleNotFoundError is a subclass of ImportError (Py 3.6+); we
# list both for clarity. FileNotFoundError covers Docker subprocesses /
# venv path resolution failing before they even spawn.
_WRAPPER_UNAVAILABLE_ERRORS = (ImportError, ModuleNotFoundError, FileNotFoundError)


# W9 D2c: sentinels that mark a wrapper-INTERNAL runtime error (the
# wrapper imported + ran, but the underlying tool errored). The
# normaliser is contracted to surface such errors via `notes` (and the
# D2b stubs we wrote always inject `wrapper_error: <message>` when the
# raw wrapper output carried `error`). On detection, the handler
# rewrites the envelope as `wrapper_runtime_error` so the LLM gets a
# clean fail-fast signal instead of an ok=True envelope with 0 pathways
# (which D5 showed the LLM misreads as a shape gap).
_WRAPPER_ERROR_NOTE_PREFIX = "wrapper_error:"


def _detect_wrapper_internal_error(result_dict: dict[str, Any]) -> str | None:
    """Check a serialised EnrichmentResult for wrapper-internal error
    sentinels. Returns the error message (for envelope.reason) or None.

    Detection sources (in order of precedence):
      1. `notes` string containing `wrapper_error:` prefix (D2b stub
         pattern — preserves the underlying message after the colon).
      2. `error` field (some normalisers may surface error here too).

    Restricted to those two locations to avoid false positives — the
    EnrichmentResult schema's other string fields (tool_version,
    db_release, etc.) may legitimately mention "error" or contain
    arbitrary debug content that should NOT trigger envelope rewrite.
    """
    notes = result_dict.get("notes")
    if isinstance(notes, str) and _WRAPPER_ERROR_NOTE_PREFIX in notes:
        # Extract the portion after the `wrapper_error:` prefix; the
        # D2b stub uses the format `<existing_notes>; wrapper_error: <msg>`
        idx = notes.find(_WRAPPER_ERROR_NOTE_PREFIX)
        return notes[idx + len(_WRAPPER_ERROR_NOTE_PREFIX):].strip()
    err = result_dict.get("error")
    if err:
        return str(err)
    return None


# Per-tool fallback message map for wrapper_runtime_error envelopes.
# Each entry tells the LLM what to do when the wrapper errored at
# runtime (NOT the same as wrapper_unavailable — env is fine, the
# underlying tool just crashed).
_WRAPPER_RUNTIME_ERROR_FALLBACKS: dict[str, str] = {
    "run_sspa_ora": (
        "sspa wrapper ran but errored at runtime; try run_ramp_enrichment "
        "or run_metaboanalystr_psea for alternative ORA verdicts"
    ),
    "run_ramp_enrichment": (
        "ramp wrapper ran but errored at runtime; try run_sspa_ora or "
        "run_metaboanalystr_psea for alternative ORA verdicts"
    ),
    "run_metaboanalystr_psea": (
        "MetaboAnalystR R subprocess errored at runtime; try run_ramp_enrichment "
        "or run_sspa_ora; if R container needs reset, ping the operator"
    ),
    "run_mummichog": (
        "mummichog ran but errored at runtime; skip the m/z-direct paradigm "
        "this turn and rely on the ORA tools"
    ),
    "run_fella_rwr": (
        "FELLA R subprocess errored at runtime (currently 'argument is of "
        "length zero' on every sub6b-v3 task — W9 D4 stretch target); skip "
        "the network/diffusion paradigm and rely on ORA + mummichog"
    ),
}


def _maybe_escalate_wrapper_error(
    tool_name: str,
    result_dict: dict[str, Any],
) -> dict[str, Any] | None:
    """If `result_dict` shows a wrapper-internal error, return a
    `wrapper_runtime_error` envelope; otherwise return None and the
    caller proceeds with the normal `_ok` envelope.

    Centralised so all 5 PA handlers share one detection + escalation
    path (W9 D2c).
    """
    err_msg = _detect_wrapper_internal_error(result_dict)
    if err_msg is None:
        return None
    return _err(
        tool_name,
        error="wrapper_runtime_error",
        fallback_suggested=_WRAPPER_RUNTIME_ERROR_FALLBACKS.get(
            tool_name,
            "wrapper ran but errored at runtime; switch tool or accept the gap",
        ),
        reason=err_msg,
    )


def handle_run_sspa_ora(arguments: dict[str, Any]) -> dict[str, Any]:
    err = _validate_compound_ids(arguments, "run_sspa_ora")
    if err:
        return err
    refs = _ids_to_refs(arguments["compound_ids"])
    top_n = _top_n_or_default(arguments)
    try:
        # Both the top-level wrapper module import AND the call body
        # are guarded — `sspa_wrapper` itself imports fine, but its
        # body lazy-imports the heavy `sspa` pkg only when run_sspa()
        # touches the pathway DB. A pre-D3 smoke surfaced this gap.
        from concord.wrappers.sspa_wrapper import run_sspa
        raw = run_sspa(compound_refs=refs)
    except _WRAPPER_UNAVAILABLE_ERRORS as exc:
        return _err(
            "run_sspa_ora",
            error="wrapper_unavailable",
            fallback_suggested=(
                "use run_ramp_enrichment (multi-DB ORA, broader namespace "
                "coverage) or run_metaboanalystr_psea (KEGG-specific ORA) "
                "instead"
            ),
            reason=f"sspa unavailable: {type(exc).__name__}: {exc}",
        )
    pathways = (raw.get("pathways") or [])[:top_n]
    trimmed = {**raw, "pathways": pathways}
    # W9 D2c: escalate wrapper-internal error sentinels in notes/error
    escalated = _maybe_escalate_wrapper_error("run_sspa_ora", trimmed)
    if escalated is not None:
        return escalated
    n_paths, n_refs = _count_pathways_compounds(trimmed)
    return _ok(
        "run_sspa_ora", trimmed,
        n_pathways=n_paths, n_compound_refs=n_refs,
    )


def handle_run_ramp_enrichment(arguments: dict[str, Any]) -> dict[str, Any]:
    err = _validate_compound_ids(arguments, "run_ramp_enrichment")
    if err:
        return err
    refs = _ids_to_refs(arguments["compound_ids"])
    top_n = _top_n_or_default(arguments)
    try:
        from concord.wrappers.ramp_wrapper import run_ramp_enrichment
        from concord.normalize.ramp_norm import normalize_ramp_output
        raw = run_ramp_enrichment(refs, top_n=top_n)
    except _WRAPPER_UNAVAILABLE_ERRORS as exc:
        return _err(
            "run_ramp_enrichment",
            error="wrapper_unavailable",
            fallback_suggested=(
                "RaMP-DB sqlite missing; use run_sspa_ora (Reactome ORA) "
                "or run_metaboanalystr_psea (KEGG ORA) for a partial "
                "namespace replacement"
            ),
            reason=f"ramp unavailable: {type(exc).__name__}: {exc}",
        )
    # W9 D2b: wire normalize_ramp_output so the envelope carries a v0.3.1
    # EnrichmentResult with per-source namespace prefixes (REACT / KEGG /
    # WP / SMPDB) rather than the raw `{"report": EnrichmentReport, ...}`
    # dict whose top-level `pathways` key is empty.
    enriched = normalize_ramp_output(raw, top_n=top_n)
    result_dict = dataclasses.asdict(enriched)
    # W9 D2c: escalate wrapper-internal error sentinels (notes / error)
    escalated = _maybe_escalate_wrapper_error("run_ramp_enrichment", result_dict)
    if escalated is not None:
        return escalated
    return _ok(
        "run_ramp_enrichment", result_dict,
        n_pathways=len(enriched.pathways),
        n_compound_refs=sum(len(p.metabolites_hit) for p in enriched.pathways),
    )


def handle_run_metaboanalystr_psea(arguments: dict[str, Any]) -> dict[str, Any]:
    err = _validate_compound_ids(arguments, "run_metaboanalystr_psea")
    if err:
        return err
    refs = _ids_to_refs(arguments["compound_ids"])
    top_n = _top_n_or_default(arguments)
    try:
        from concord.wrappers.metaboanalystr_wrapper import (
            run_metaboanalystr_psea,
        )
        from concord.normalize.metaboanalystr_norm import (
            normalize_metaboanalystr_output,
        )
        raw = run_metaboanalystr_psea(refs)
    except _WRAPPER_UNAVAILABLE_ERRORS as exc:
        return _err(
            "run_metaboanalystr_psea",
            error="wrapper_unavailable",
            fallback_suggested=(
                "Docker R unavailable; use run_sspa_ora for an "
                "alternative ORA verdict, or skip the KEGG-only "
                "paradigm and rely on run_ramp_enrichment's KEGG slice"
            ),
            reason=f"metaboanalystr unavailable: {type(exc).__name__}: {exc}",
        )
    # W9 D2b: wire normalize_metaboanalystr_output so the envelope
    # carries v0.3.1 EnrichmentResult with KEGG: / SMPDB: namespace
    # prefixes (per the psea wrapper's `library` parameter), rather
    # than the raw `{"raw": <R JSON>, ...}` dict.
    enriched = normalize_metaboanalystr_output(raw, top_n=top_n)
    result_dict = dataclasses.asdict(enriched)
    # W9 D2c: escalate wrapper-internal error sentinels (notes / error)
    escalated = _maybe_escalate_wrapper_error("run_metaboanalystr_psea", result_dict)
    if escalated is not None:
        return escalated
    return _ok(
        "run_metaboanalystr_psea", result_dict,
        n_pathways=len(enriched.pathways),
        n_compound_refs=sum(len(p.metabolites_hit) for p in enriched.pathways),
    )


def handle_run_mummichog(arguments: dict[str, Any]) -> dict[str, Any]:
    err = _validate_compound_ids(arguments, "run_mummichog")
    if err:
        return err
    refs = _ids_to_refs(arguments["compound_ids"])
    top_n = _top_n_or_default(arguments)
    try:
        from concord.wrappers.mummichog_wrapper import (
            run_mummichog_for_compound_set,
        )
        from concord.normalize.mummichog_norm import normalize_mummichog_output
        raw = run_mummichog_for_compound_set(refs)
    except _WRAPPER_UNAVAILABLE_ERRORS as exc:
        return _err(
            "run_mummichog",
            error="wrapper_unavailable",
            fallback_suggested=(
                "mummichog venv missing; skip the m/z-direct paradigm and "
                "rely on the ORA tools — note that lipid pathways may be "
                "under-represented without mummichog"
            ),
            reason=f"mummichog unavailable: {type(exc).__name__}: {exc}",
        )
    # W9 D2b: wire normalize_mummichog_output so the envelope carries a
    # v0.3.1 EnrichmentResult with MUMM:-prefixed pathway_ids, not the
    # raw wrapper dict with bare pathway names.
    enriched = normalize_mummichog_output(raw, top_n=top_n)
    result_dict = dataclasses.asdict(enriched)
    # W9 D2c: escalate wrapper-internal error sentinels (notes / error)
    escalated = _maybe_escalate_wrapper_error("run_mummichog", result_dict)
    if escalated is not None:
        return escalated
    return _ok(
        "run_mummichog", result_dict,
        n_pathways=len(enriched.pathways),
        n_compound_refs=sum(len(p.metabolites_hit) for p in enriched.pathways),
    )


def handle_run_fella_rwr(arguments: dict[str, Any]) -> dict[str, Any]:
    err = _validate_compound_ids(arguments, "run_fella_rwr")
    if err:
        return err
    refs = _ids_to_refs(arguments["compound_ids"])
    top_n = _top_n_or_default(arguments)
    try:
        from concord.wrappers.fella_wrapper import run_fella_rwr
        from concord.normalize.fella_norm import normalize_fella_output
        raw = run_fella_rwr(refs)
    except _WRAPPER_UNAVAILABLE_ERRORS as exc:
        return _err(
            "run_fella_rwr",
            error="wrapper_unavailable",
            fallback_suggested=(
                "Docker R unavailable; skip the network/diffusion "
                "paradigm and rely on ORA + mummichog. Indirect "
                "pathway involvement may be missed."
            ),
            reason=f"fella unavailable: {type(exc).__name__}: {exc}",
        )
    # W9 D2b: wire normalize_fella_output so the envelope follows v0.3.1
    # schema even when the FELLA R subprocess errors out (current state:
    # "argument is of length zero" 100% on sub6b-v3 — W9 D4 stretch
    # target). The normaliser's notes field preserves the wrapper-
    # reported error for D2c to escalate to envelope-level.
    enriched = normalize_fella_output(raw, top_n=top_n)
    result_dict = dataclasses.asdict(enriched)
    # Pass wrapper-internal error through `notes` (D2c hook). The
    # normaliser sets a default notes value ("fella fella_rwr"); append
    # the wrapper error rather than skip when notes is non-empty.
    wrapper_err = raw.get("error")
    if wrapper_err:
        existing = result_dict.get("notes") or ""
        suffix = f"wrapper_error: {wrapper_err}"
        result_dict["notes"] = (
            f"{existing}; {suffix}" if existing else suffix
        )
    # W9 D2c: escalate wrapper-internal error sentinels (notes / error)
    escalated = _maybe_escalate_wrapper_error("run_fella_rwr", result_dict)
    if escalated is not None:
        return escalated
    return _ok(
        "run_fella_rwr", result_dict,
        n_pathways=len(enriched.pathways),
        n_compound_refs=sum(len(p.metabolites_hit) for p in enriched.pathways),
    )


# ---------------------------------------------------------------------------
# 3 reconciliation handlers + 1 literature handler
# ---------------------------------------------------------------------------


_PATHWAY_MEMBERS_DB = Path("data/concord/pathway_members.sqlite")


def handle_lookup_chebi(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_id = arguments.get("id")
    if not raw_id or not isinstance(raw_id, str):
        return _err(
            "lookup_chebi",
            error="missing 'id' (must be a non-empty string)",
            fallback_suggested=(
                "pass id like 'CHEBI:17234' / 'C00031' / 'HMDB0000122' "
                "/ 'LMFA01030001' / a compound name / InChIKey"
            ),
        )
    namespace = (arguments.get("namespace") or "").strip().upper() or None

    try:
        from concord.lookup.chebi import ChebiLookup
    except ImportError as exc:
        return _err(
            "lookup_chebi",
            error="wrapper_unavailable",
            fallback_suggested="install concord.lookup or run reconcile_inchikey",
            reason=str(exc),
        )
    try:
        lookup = ChebiLookup()
    except FileNotFoundError as exc:
        return _err(
            "lookup_chebi",
            error="data_not_available",
            fallback_suggested="run `python -m concord.etl.chebi_etl --with-isa`",
            reason=str(exc),
        )

    s = raw_id.strip()
    rec = None

    def _try_xref(ns: str, ext_id: str) -> Any:
        prefix = f"{ns}:"
        cleaned = ext_id[len(prefix):] if ext_id.upper().startswith(prefix) else ext_id
        return lookup.lookup_by_xref(ns, cleaned)

    # 1. Explicit ChEBI form, or numeric, or namespace=CHEBI
    if namespace == "CHEBI" or s.upper().startswith("CHEBI:") or s.isdigit():
        try:
            rec = lookup.get_compound(s)
        except (ValueError, TypeError):
            rec = None
    elif namespace == "INCHIKEY" or (len(s) == 27 and s.count("-") == 2):
        rs = lookup.lookup_by_inchikey(s)
        rec = rs[0] if rs else None
    elif namespace == "HMDB" or s.upper().startswith("HMDB"):
        rec = _try_xref("HMDB", s)
    elif namespace == "LIPIDMAPS" or s.upper().startswith("LM"):
        rec = _try_xref("LIPIDMAPS", s)
    elif namespace == "KEGG" or (
        s.startswith("C") and len(s) >= 6 and s[1:].lstrip("0").isdigit()
    ):
        rec = _try_xref("KEGG", s)
    else:
        # NAME / SMILES fallback — name lookup tries both
        rs = lookup.lookup_by_name(s)
        rec = rs[0] if rs else None

    if rec is None:
        return _err(
            "lookup_chebi",
            error="not_found",
            fallback_suggested=(
                "try search_literature for biological context, or "
                "reconcile_inchikey if you have multiple ID variants"
            ),
            queried_id=s,
            namespace_hint=namespace,
        )
    # Map ChebiLookup's `name` to `display_name` so the output is schema-
    # consistent with CompoundRef (concord/schema/enrichment.py). Keep
    # both keys for trace/audit.
    raw = dataclasses.asdict(rec)
    raw["display_name"] = raw.get("name") or ""
    return _ok("lookup_chebi", raw)


def handle_reconcile_inchikey(arguments: dict[str, Any]) -> dict[str, Any]:
    refs_in = arguments.get("refs")
    if not isinstance(refs_in, list) or not refs_in:
        return _err(
            "reconcile_inchikey",
            error="'refs' must be a non-empty list",
            fallback_suggested=(
                "pass refs like [{\"display_name\": \"glucose\", "
                "\"inchikey\": \"WQZGKKKJIJFFOK-GASJEMHNSA-N\"}, ...]"
            ),
        )
    try:
        from concord.reconcile.inchikey import (
            cluster_by_block14,
            detect_charge_stereo_conflict,
        )
    except ImportError as exc:
        return _err(
            "reconcile_inchikey",
            error="wrapper_unavailable",
            fallback_suggested="install concord.reconcile or skip ID-cluster reconciliation",
            reason=str(exc),
        )
    # Build duck-typed refs the reconcile module can iterate
    refs: list[Any] = []
    for r in refs_in:
        if isinstance(r, dict):
            refs.append(SimpleNamespace(**r))
        elif isinstance(r, str):
            refs.append(SimpleNamespace(inchikey=r, display_name="", primary_id=""))
        else:
            refs.append(r)
    clusters = cluster_by_block14(refs)
    conflict = detect_charge_stereo_conflict(refs)
    cluster_summary = {b14: len(items) for b14, items in clusters.items() if b14}
    return _ok(
        "reconcile_inchikey",
        {
            "n_clusters": len(cluster_summary),
            "conflict_type": conflict.conflict_type,
            "n_distinct_block14": conflict.n_distinct_block14,
            "n_distinct_full": conflict.n_distinct_full,
            "block14s": list(conflict.block14s),
            "cluster_sizes_by_block14": cluster_summary,
        },
        n_input_refs=len(refs),
    )


def handle_query_pathway_members(arguments: dict[str, Any]) -> dict[str, Any]:
    pid = arguments.get("pathway_id")
    if not pid or not isinstance(pid, str):
        return _err(
            "query_pathway_members",
            error="missing 'pathway_id' (must be a non-empty namespaced string)",
            fallback_suggested=(
                "pass pathway_id like 'WP:WP167' / 'KEGG:hsa00590' / "
                "'HUMAN1:alanine_aspartate_and_glutamate_metabolism'"
            ),
        )
    s = pid.strip()
    if ":" not in s:
        return _err(
            "query_pathway_members",
            error="pathway_id must be namespace-prefixed 'NS:slug'",
            fallback_suggested=(
                "prefix with namespace: 'KEGG:hsa00590' / 'WP:WP167' / "
                "'HUMAN1:<slug>' / 'RECON2:<slug>'"
            ),
            received=s,
        )
    ns, slug = s.split(":", 1)
    ns_upper = ns.upper()
    if ns_upper not in {"HUMAN1", "RECON2"}:
        # W8 known data gap: pathway_members.sqlite was built for the
        # Cooke benchmark (HUMAN1 + RECON2 GEMs). Other namespaces have
        # no compound-roster data yet. Return a structured envelope so
        # the LLM can fall back to per-method `metabolites_hit`.
        return _err(
            "query_pathway_members",
            error="data_not_available",
            fallback_suggested=(
                f"pathway_members.sqlite only indexes HUMAN1 + RECON2; "
                f"for namespace '{ns_upper}', inspect the "
                "`metabolites_hit` list inside an EnrichmentResult "
                "(e.g. from run_ramp_enrichment) — it carries the "
                "method-specific compound roster"
            ),
            received_namespace=ns_upper,
            supported_namespaces=["HUMAN1", "RECON2"],
        )
    if not _PATHWAY_MEMBERS_DB.exists():
        return _err(
            "query_pathway_members",
            error="data_not_available",
            fallback_suggested=(
                "run `python -m concord.etl.pathway_members_etl` to "
                "build the sqlite"
            ),
            reason=f"sqlite not found at {_PATHWAY_MEMBERS_DB}",
        )
    conn = sqlite3.connect(f"file:{_PATHWAY_MEMBERS_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT member_chebi_id FROM pathway_member "
            "WHERE pathway_namespace = ? AND pathway_label_slug = ?",
            (ns_upper, slug),
        ).fetchall()
    finally:
        conn.close()
    members = [r[0] for r in rows if r[0]]
    if not members:
        return _err(
            "query_pathway_members",
            error="not_found",
            fallback_suggested=(
                "double-check the pathway slug; HUMAN1 slugs are "
                "snake_case like 'alanine_aspartate_and_glutamate_metabolism'"
            ),
            received=s,
        )
    return _ok(
        "query_pathway_members",
        {"pathway_id": s, "member_chebi_ids": members},
        n_members=len(members),
    )


def handle_search_literature(arguments: dict[str, Any]) -> dict[str, Any]:
    query = arguments.get("query")
    if not query or not isinstance(query, str):
        return _err(
            "search_literature",
            error="missing 'query' (must be a non-empty string)",
            fallback_suggested="pass a focused biological-context query",
        )
    max_results = arguments.get("max_results", 5)
    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        max_results = 5
    max_results = max(1, min(20, max_results))
    try:
        from tools.agent_tools import search_literature as b1_lit
    except ImportError as exc:
        return _err(
            "search_literature",
            error="wrapper_unavailable",
            fallback_suggested="B1 literature wrapper missing; skip the biological-context lookup",
            reason=str(exc),
        )
    raw = b1_lit.search_literature({"query": query, "max_results": max_results})
    n = (raw.get("n_results")
         if isinstance(raw.get("n_results"), int)
         else len(raw.get("results") or []))
    return _ok("search_literature", raw, n_results=n)


# ---------------------------------------------------------------------------
# Registry (consumed by tool_dispatcher.HANDLERS)
# ---------------------------------------------------------------------------


HANDLERS: dict[str, Any] = {
    "run_sspa_ora": handle_run_sspa_ora,
    "run_ramp_enrichment": handle_run_ramp_enrichment,
    "run_metaboanalystr_psea": handle_run_metaboanalystr_psea,
    "run_mummichog": handle_run_mummichog,
    "run_fella_rwr": handle_run_fella_rwr,
    "lookup_chebi": handle_lookup_chebi,
    "reconcile_inchikey": handle_reconcile_inchikey,
    "query_pathway_members": handle_query_pathway_members,
    "search_literature": handle_search_literature,
}
