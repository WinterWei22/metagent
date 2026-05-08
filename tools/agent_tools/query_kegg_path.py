"""Tool 3 — KEGG reaction-graph reachability between two compounds.

Wraps :func:`tools.kegg.reachability.is_compound_a_upstream_of_compound_b`.
The KEGG sqlite path resolves to ``data/kegg/reaction_graph.sqlite`` by
default (matches the verifier's Layer 6d convention), overridable via
``METAGENT_KEGG_GRAPH_PATH``.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from tools.agent_tools.schemas import KeggPathInput, truncate_to_budget
from tools.kegg.reachability import is_compound_a_upstream_of_compound_b

logger = logging.getLogger(__name__)

_KEGG_ENV_VAR = "METAGENT_KEGG_GRAPH_PATH"
_DEFAULT_KEGG_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "kegg" / "reaction_graph.sqlite"
)


def _resolve_kegg_db() -> Path | None:
    explicit = os.environ.get(_KEGG_ENV_VAR)
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    return _DEFAULT_KEGG_PATH if _DEFAULT_KEGG_PATH.is_file() else None


def query_kegg_path(payload: dict[str, Any]) -> dict[str, Any]:
    """BFS reachability check.

    Output shape (success):
        {
            "compound_a": str,         # input echoed
            "compound_b": str,
            "resolved_a": str | None,  # cpd:Cxxxxx
            "resolved_b": str | None,
            "is_reachable": bool,      # forward direction A→B
            "direction": "forward" | "reverse" | "bidirectional" | "none",
            "shortest_path": [str, ...] | None,
            "path_length": int | None,
            "max_path_length": int,
            "notes": [str, ...],
        }
    """
    args = KeggPathInput.model_validate(payload)

    db_path = _resolve_kegg_db()
    if db_path is None:
        return {
            "error": "kegg_graph_unavailable",
            "fallback_suggested": (
                f"KEGG reaction graph not found (set {_KEGG_ENV_VAR} or "
                "place sqlite at data/kegg/reaction_graph.sqlite); use "
                "query_pathway_membership for pathway-level evidence instead"
            ),
        }

    conn = sqlite3.connect(str(db_path))
    try:
        result = is_compound_a_upstream_of_compound_b(
            args.compound_a,
            args.compound_b,
            conn=conn,
            max_path_length=args.max_path_length,
        )
    except Exception as exc:  # pragma: no cover — DB schema drift, etc.
        logger.exception("query_kegg_path: unexpected failure")
        return {
            "error": f"unexpected_error: {type(exc).__name__}: {exc}",
            "fallback_suggested": "drop the directional claim or restate it as a co-membership claim",
        }
    finally:
        conn.close()

    resolved_a = result.source_compounds[0] if result.source_compounds else None
    resolved_b = result.target_compounds[0] if result.target_compounds else None

    out: dict[str, Any] = {
        "compound_a": args.compound_a,
        "compound_b": args.compound_b,
        "resolved_a": resolved_a,
        "resolved_b": resolved_b,
        "is_reachable": result.is_reachable,
        "direction": result.direction,
        "shortest_path": result.shortest_path,
        "path_length": result.path_length,
        "max_path_length": result.max_path_length,
        "notes": result.notes[:5],
    }
    return truncate_to_budget(out, truncatable_key="notes")
