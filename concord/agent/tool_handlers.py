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


def _ids_to_refs(compound_ids: list[str]) -> list[SimpleNamespace]:
    """Build duck-typed CompoundRef objects from string IDs.

    The PA wrappers read attributes via `getattr(ref, "chebi_id", None)`,
    `getattr(ref, "kegg_compound_id", None)`, etc. — they do not require
    a real `CompoundRef` dataclass instance, which would force us to
    look up an InChIKey before we even call the tool. A `SimpleNamespace`
    with the right attributes duck-types correctly.
    """
    refs: list[SimpleNamespace] = []
    for raw in compound_ids:
        s = raw.strip()
        primary_id = s
        chebi_id = hmdb_id = kegg = lipidmaps = None
        if s.upper().startswith("CHEBI:"):
            chebi_id = s
            primary_id = s
        elif s.upper().startswith("HMDB"):
            # accept "HMDB:HMDB0000122" or "HMDB0000122"
            normalised = s if s.upper().startswith("HMDB:") else f"HMDB:{s}"
            hmdb_id = normalised
            primary_id = normalised
        elif s.upper().startswith("KEGG:"):
            kegg = s
            primary_id = s
        elif s.startswith("C") and len(s) >= 6 and s[1:].lstrip("0").isdigit():
            # bare KEGG cpd ID like "C00031"
            kegg = f"KEGG:{s}"
            primary_id = kegg
        elif s.upper().startswith("LM") or s.upper().startswith("LIPIDMAPS:"):
            normalised = s if s.upper().startswith("LIPIDMAPS:") else f"LIPIDMAPS:{s}"
            lipidmaps = normalised
            primary_id = normalised

        refs.append(SimpleNamespace(
            primary_id=primary_id,
            chebi_id=chebi_id,
            hmdb_id=hmdb_id,
            kegg_compound_id=kegg,
            lipidmaps_id=lipidmaps,
            inchikey="",
            display_name="",
        ))
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


def handle_run_sspa_ora(arguments: dict[str, Any]) -> dict[str, Any]:
    err = _validate_compound_ids(arguments, "run_sspa_ora")
    if err:
        return err
    try:
        from concord.wrappers.sspa_wrapper import run_sspa
    except ImportError as exc:
        return _err(
            "run_sspa_ora",
            error="wrapper_unavailable",
            fallback_suggested=(
                "use run_ramp_enrichment (multi-DB ORA, broader namespace "
                "coverage) or run_metaboanalystr_psea (KEGG-specific ORA) "
                "instead"
            ),
            reason=f"sspa wrapper import failed: {exc}",
        )
    refs = _ids_to_refs(arguments["compound_ids"])
    top_n = _top_n_or_default(arguments)
    raw = run_sspa(compound_refs=refs)
    pathways = (raw.get("pathways") or [])[:top_n]
    trimmed = {**raw, "pathways": pathways}
    n_paths, n_refs = _count_pathways_compounds(trimmed)
    return _ok(
        "run_sspa_ora", trimmed,
        n_pathways=n_paths, n_compound_refs=n_refs,
    )


def handle_run_ramp_enrichment(arguments: dict[str, Any]) -> dict[str, Any]:
    err = _validate_compound_ids(arguments, "run_ramp_enrichment")
    if err:
        return err
    try:
        from concord.wrappers.ramp_wrapper import run_ramp_enrichment
    except ImportError as exc:
        return _err(
            "run_ramp_enrichment",
            error="wrapper_unavailable",
            fallback_suggested=(
                "RaMP-DB sqlite missing; use run_sspa_ora (Reactome ORA) "
                "or run_metaboanalystr_psea (KEGG ORA) for a partial "
                "namespace replacement"
            ),
            reason=f"ramp wrapper import failed: {exc}",
        )
    refs = _ids_to_refs(arguments["compound_ids"])
    top_n = _top_n_or_default(arguments)
    raw = run_ramp_enrichment(refs, top_n=top_n)
    pathways = (raw.get("pathways") or [])[:top_n]
    trimmed = {**raw, "pathways": pathways}
    n_paths, n_refs = _count_pathways_compounds(trimmed)
    return _ok(
        "run_ramp_enrichment", trimmed,
        n_pathways=n_paths, n_compound_refs=n_refs,
    )


def handle_run_metaboanalystr_psea(arguments: dict[str, Any]) -> dict[str, Any]:
    err = _validate_compound_ids(arguments, "run_metaboanalystr_psea")
    if err:
        return err
    try:
        from concord.wrappers.metaboanalystr_wrapper import (
            run_metaboanalystr_psea,
        )
    except ImportError as exc:
        return _err(
            "run_metaboanalystr_psea",
            error="wrapper_unavailable",
            fallback_suggested=(
                "Docker R unavailable; use run_sspa_ora for an "
                "alternative ORA verdict, or skip the KEGG-only "
                "paradigm and rely on run_ramp_enrichment's KEGG slice"
            ),
            reason=f"metaboanalystr wrapper import failed: {exc}",
        )
    refs = _ids_to_refs(arguments["compound_ids"])
    top_n = _top_n_or_default(arguments)
    raw = run_metaboanalystr_psea(refs)
    pathways = (raw.get("pathways") or [])[:top_n]
    trimmed = {**raw, "pathways": pathways}
    n_paths, n_refs = _count_pathways_compounds(trimmed)
    return _ok(
        "run_metaboanalystr_psea", trimmed,
        n_pathways=n_paths, n_compound_refs=n_refs,
    )


def handle_run_mummichog(arguments: dict[str, Any]) -> dict[str, Any]:
    err = _validate_compound_ids(arguments, "run_mummichog")
    if err:
        return err
    try:
        from concord.wrappers.mummichog_wrapper import (
            run_mummichog_for_compound_set,
        )
    except ImportError as exc:
        return _err(
            "run_mummichog",
            error="wrapper_unavailable",
            fallback_suggested=(
                "mummichog venv missing; skip the m/z-direct paradigm and "
                "rely on the ORA tools — note that lipid pathways may be "
                "under-represented without mummichog"
            ),
            reason=f"mummichog wrapper import failed: {exc}",
        )
    refs = _ids_to_refs(arguments["compound_ids"])
    top_n = _top_n_or_default(arguments)
    raw = run_mummichog_for_compound_set(refs)
    pathways = (raw.get("pathways") or [])[:top_n]
    trimmed = {**raw, "pathways": pathways}
    n_paths, n_refs = _count_pathways_compounds(trimmed)
    return _ok(
        "run_mummichog", trimmed,
        n_pathways=n_paths, n_compound_refs=n_refs,
    )


def handle_run_fella_rwr(arguments: dict[str, Any]) -> dict[str, Any]:
    err = _validate_compound_ids(arguments, "run_fella_rwr")
    if err:
        return err
    try:
        from concord.wrappers.fella_wrapper import run_fella_rwr
    except ImportError as exc:
        return _err(
            "run_fella_rwr",
            error="wrapper_unavailable",
            fallback_suggested=(
                "Docker R unavailable; skip the network/diffusion "
                "paradigm and rely on ORA + mummichog. Indirect "
                "pathway involvement may be missed."
            ),
            reason=f"fella wrapper import failed: {exc}",
        )
    refs = _ids_to_refs(arguments["compound_ids"])
    top_n = _top_n_or_default(arguments)
    raw = run_fella_rwr(refs)
    pathways = (raw.get("pathways") or [])[:top_n]
    trimmed = {**raw, "pathways": pathways}
    n_paths, n_refs = _count_pathways_compounds(trimmed)
    return _ok(
        "run_fella_rwr", trimmed,
        n_pathways=n_paths, n_compound_refs=n_refs,
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
