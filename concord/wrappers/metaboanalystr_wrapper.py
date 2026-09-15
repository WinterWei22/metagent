"""MetaboAnalystR wrapper via persistent docker exec (W5 D1).

Three method entry points (PSEA / MSEA / Mummichog R-side):
    run_metaboanalystr_psea(compound_set, ...)   — Pathway Set Enrichment
    run_metaboanalystr_msea(compound_set, ...)   — Metabolite Set Enrichment
    run_metaboanalystr_mummichog(peaks, ...)     — m/z-driven (R port of mummichog)

All share a single ``DockerRSession`` (persistent container) so per-call
overhead is just ``docker exec`` (~50-200ms after first warm-up).

Normalize functions in concord/normalize/metaboanalystr_norm.py.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any, Literal

from concord.wrappers._docker_r_session import (
    DEFAULT_CONTAINER,
    DEFAULT_IMAGE,
    DockerRSession,
)

logger = logging.getLogger(__name__)

# Module-level shared session — caller can override via container_name= arg
# to use a different persistent container (e.g. for testing)
_SHARED: dict[str, DockerRSession] = {}


def _get_session(container_name: str, image: str) -> DockerRSession:
    key = f"{image}::{container_name}"
    if key not in _SHARED:
        _SHARED[key] = DockerRSession(image=image, container_name=container_name)
    return _SHARED[key]


def _compound_refs_to_kegg_ids(compound_refs: list[Any]) -> list[str]:
    """Pull KEGG cpd IDs from CompoundRef list (strip 'KEGG:' prefix).

    MetaboAnalystR queries by KEGG cpd internally (or HMDB / ChEBI),
    so we extract the most-Reactome-tagged available ID.
    """
    out: list[str] = []
    seen: set[str] = set()
    for ref in compound_refs:
        if ref is None:
            continue
        kegg = getattr(ref, "kegg_compound_id", None)
        if kegg:
            k = kegg.replace("KEGG:", "").strip()
            if k and k not in seen:
                seen.add(k); out.append(k)
    return out


def _compound_refs_to_hmdb_ids(compound_refs: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for ref in compound_refs:
        h = getattr(ref, "hmdb_id", None)
        if h:
            h = h.replace("HMDB:", "").strip()
            if h and h not in seen:
                seen.add(h); out.append(h)
    return out


def run_metaboanalystr_psea(
    compound_set: list[Any],
    *,
    library: Literal["kegg", "smpdb"] = "kegg",
    id_type: Literal["hmdb", "kegg"] = "hmdb",
    container_name: str = DEFAULT_CONTAINER,
    image: str = DEFAULT_IMAGE,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run MetaboAnalystR Pathway Set Enrichment Analysis (PSEA).

    Args:
        compound_set: list of CompoundRef. HMDB or KEGG cpd ID consumed.
        library: pathway library ("kegg" or "smpdb")
        id_type: which CompoundRef ID to pass to MetaboAnalystR
        container_name: persistent container name
        image: docker image tag
        timeout: hard timeout for docker exec

    Returns:
        dict with keys:
            "raw": list of pathway results (id, name, p_value, fdr, hits_ids)
            "method": "metaboanalystr_psea"
            "n_input": int
            "n_input_resolved": int
            "wall_time_sec": float
            "tool_version": str
            "db_release": str
            "parameters": dict echo

    Raises:
        ValueError on empty compound_set or invalid library/id_type
        DockerNotAvailable / ContainerNotRunning / TimeoutError on infra
    """
    if not compound_set:
        # Spec: empty → empty result, no raise
        return {
            "raw": [], "method": "metaboanalystr_psea",
            "n_input": 0, "n_input_resolved": 0,
            "wall_time_sec": 0.0, "tool_version": "metaboanalystr-unknown",
            "db_release": library, "parameters": {
                "library": library, "id_type": id_type,
            },
        }

    ids = (
        _compound_refs_to_hmdb_ids(compound_set) if id_type == "hmdb"
        else _compound_refs_to_kegg_ids(compound_set)
    )
    if not ids:
        return {
            "raw": [], "method": "metaboanalystr_psea",
            "n_input": 0, "n_input_resolved": 0,
            "wall_time_sec": 0.0, "tool_version": "metaboanalystr-unknown",
            "db_release": library, "parameters": {
                "library": library, "id_type": id_type,
            },
        }

    session = _get_session(container_name, image)
    request = {
        "method": "metaboanalystr_psea",
        "params": {
            "compounds": ids,
            "id_type": id_type,
            "library": library,
        },
    }
    t0 = time.time()
    response = session.exec_request(request, timeout=timeout)
    wall = time.time() - t0

    if not response.ok:
        # Surface the error but in a structured form caller can normalize
        return {
            "raw": [], "method": "metaboanalystr_psea",
            "n_input": len(ids), "n_input_resolved": 0,
            "wall_time_sec": wall, "tool_version": "metaboanalystr-unknown",
            "db_release": library,
            "parameters": {"library": library, "id_type": id_type},
            "error": response.data.get("error", "unknown"),
        }

    return {
        "raw": response.data.get("pathways", []),
        "method": "metaboanalystr_psea",
        "n_input": len(ids),
        "n_input_resolved": int(response.data.get("n_resolved", len(ids))),
        "wall_time_sec": wall,
        "tool_version": str(response.data.get("tool_version", "MetaboAnalystR")),
        "db_release": str(response.data.get("db_release", library)),
        "parameters": {"library": library, "id_type": id_type},
    }


def run_metaboanalystr_msea(
    compound_set: list[Any],
    *,
    library: Literal["kegg", "smpdb"] = "smpdb",
    id_type: Literal["hmdb", "kegg"] = "hmdb",
    container_name: str = DEFAULT_CONTAINER,
    image: str = DEFAULT_IMAGE,
    timeout: int = 120,
) -> dict[str, Any]:
    """Metabolite Set Enrichment Analysis (MSEA) — disease / biofluid sets.

    Same I/O shape as PSEA.
    """
    if not compound_set:
        return {
            "raw": [], "method": "metaboanalystr_msea",
            "n_input": 0, "n_input_resolved": 0,
            "wall_time_sec": 0.0, "tool_version": "metaboanalystr-unknown",
            "db_release": library, "parameters": {
                "library": library, "id_type": id_type,
            },
        }

    ids = (
        _compound_refs_to_hmdb_ids(compound_set) if id_type == "hmdb"
        else _compound_refs_to_kegg_ids(compound_set)
    )
    if not ids:
        return {
            "raw": [], "method": "metaboanalystr_msea",
            "n_input": 0, "n_input_resolved": 0,
            "wall_time_sec": 0.0, "tool_version": "metaboanalystr-unknown",
            "db_release": library, "parameters": {
                "library": library, "id_type": id_type,
            },
        }

    session = _get_session(container_name, image)
    request = {
        "method": "metaboanalystr_msea",
        "params": {
            "compounds": ids, "id_type": id_type, "library": library,
        },
    }
    t0 = time.time()
    response = session.exec_request(request, timeout=timeout)
    wall = time.time() - t0

    if not response.ok:
        return {
            "raw": [], "method": "metaboanalystr_msea",
            "n_input": len(ids), "n_input_resolved": 0,
            "wall_time_sec": wall, "tool_version": "metaboanalystr-unknown",
            "db_release": library,
            "parameters": {"library": library, "id_type": id_type},
            "error": response.data.get("error", "unknown"),
        }

    return {
        "raw": response.data.get("pathways", []),
        "method": "metaboanalystr_msea",
        "n_input": len(ids),
        "n_input_resolved": int(response.data.get("n_resolved", len(ids))),
        "wall_time_sec": wall,
        "tool_version": str(response.data.get("tool_version", "MetaboAnalystR")),
        "db_release": str(response.data.get("db_release", library)),
        "parameters": {"library": library, "id_type": id_type},
    }


def run_metaboanalystr_mummichog(
    peaks: list[Any],
    *,
    mode: Literal["positive", "negative"] = "positive",
    container_name: str = DEFAULT_CONTAINER,
    image: str = DEFAULT_IMAGE,
    timeout: int = 180,
) -> dict[str, Any]:
    """MetaboAnalystR's R port of mummichog (m/z driven enrichment)."""
    if not peaks:
        return {
            "raw": [], "method": "metaboanalystr_mummichog",
            "n_input": 0, "n_input_resolved": 0,
            "wall_time_sec": 0.0, "tool_version": "metaboanalystr-unknown",
            "db_release": "human_mfn",
            "parameters": {"mode": mode},
        }

    session = _get_session(container_name, image)
    request = {
        "method": "metaboanalystr_mummichog",
        "params": {
            "peaks": [asdict(p) for p in peaks],
            "mode": mode,
        },
    }
    t0 = time.time()
    response = session.exec_request(request, timeout=timeout)
    wall = time.time() - t0

    if not response.ok:
        return {
            "raw": [], "method": "metaboanalystr_mummichog",
            "n_input": len(peaks), "n_input_resolved": 0,
            "wall_time_sec": wall, "tool_version": "metaboanalystr-unknown",
            "db_release": "human_mfn", "parameters": {"mode": mode},
            "error": response.data.get("error", "unknown"),
        }

    return {
        "raw": response.data.get("pathways", []),
        "method": "metaboanalystr_mummichog",
        "n_input": len(peaks),
        "n_input_resolved": int(response.data.get("n_significant", 0)),
        "wall_time_sec": wall,
        "tool_version": str(response.data.get("tool_version", "MetaboAnalystR")),
        "db_release": "human_mfn",
        "parameters": {"mode": mode},
    }
