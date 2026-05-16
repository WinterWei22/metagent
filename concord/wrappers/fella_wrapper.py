"""FELLA wrapper via persistent docker exec (W5 D2).

FELLA(Bioconductor)does random-walk-with-restart / diffusion on a KEGG
hierarchical graph (pathway-module-enzyme-reaction-compound, 5 layers).
We expose pathway-level scores in v0.3 EnrichmentResult; other layer nodes
go into auxiliary_data for paper-supplementary use.

Shares the persistent ``concord_r_persistent`` container with MetaboAnalystR
to reuse pre-warmed KEGG graph (cached in R global env at container startup).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Literal

from concord.wrappers._docker_r_session import (
    DEFAULT_CONTAINER,
    DEFAULT_IMAGE,
    DockerRSession,
)

logger = logging.getLogger(__name__)

_SHARED: dict[str, DockerRSession] = {}


def _get_session(container_name: str, image: str) -> DockerRSession:
    key = f"{image}::{container_name}"
    if key not in _SHARED:
        _SHARED[key] = DockerRSession(image=image, container_name=container_name)
    return _SHARED[key]


def _compound_refs_to_kegg_ids(compound_refs: list[Any]) -> list[str]:
    out, seen = [], set()
    for ref in compound_refs:
        if ref is None:
            continue
        k = getattr(ref, "kegg_compound_id", None)
        if k:
            k = k.replace("KEGG:", "").strip()
            if k and k not in seen:
                seen.add(k); out.append(k)
    return out


def run_fella_rwr(
    compound_set: list[Any],
    *,
    organism: Literal["hsa", "mmu"] = "hsa",
    container_name: str = DEFAULT_CONTAINER,
    image: str = DEFAULT_IMAGE,
    timeout: int = 60,
) -> dict[str, Any]:
    """Random-walk-with-restart over KEGG graph.

    Args:
        compound_set: list of CompoundRef. KEGG cpd IDs extracted.
        organism: KEGG organism code (hsa = human, mmu = mouse).
        container_name: persistent container.
        timeout: docker exec timeout.

    Returns: dict (see metaboanalystr_wrapper for shape)
    """
    if not compound_set:
        return _empty_result("fella_rwr", organism)
    kegg_ids = _compound_refs_to_kegg_ids(compound_set)
    if not kegg_ids:
        return _empty_result("fella_rwr", organism)

    session = _get_session(container_name, image)
    request = {
        "method": "fella_rwr",
        "params": {"compounds": kegg_ids, "organism": organism},
    }
    t0 = time.time()
    response = session.exec_request(request, timeout=timeout)
    wall = time.time() - t0
    return _build_result(response, "fella_rwr", organism, len(kegg_ids), wall)


def run_fella_diffusion(
    compound_set: list[Any],
    *,
    organism: Literal["hsa", "mmu"] = "hsa",
    container_name: str = DEFAULT_CONTAINER,
    image: str = DEFAULT_IMAGE,
    timeout: int = 60,
) -> dict[str, Any]:
    """Heat-diffusion method over KEGG graph (alternative to RWR)."""
    if not compound_set:
        return _empty_result("fella_diffusion", organism)
    kegg_ids = _compound_refs_to_kegg_ids(compound_set)
    if not kegg_ids:
        return _empty_result("fella_diffusion", organism)

    session = _get_session(container_name, image)
    request = {
        "method": "fella_diffusion",
        "params": {"compounds": kegg_ids, "organism": organism},
    }
    t0 = time.time()
    response = session.exec_request(request, timeout=timeout)
    wall = time.time() - t0
    return _build_result(response, "fella_diffusion", organism, len(kegg_ids), wall)


def _empty_result(method: str, organism: str) -> dict[str, Any]:
    return {
        "raw": [], "method": method,
        "n_input": 0, "n_input_resolved": 0,
        "wall_time_sec": 0.0, "tool_version": "FELLA-unknown",
        "db_release": f"kegg_{organism}",
        "parameters": {"organism": organism},
        "auxiliary_data": {},
    }


def _build_result(response, method: str, organism: str,
                  n_input: int, wall: float) -> dict[str, Any]:
    if not response.ok:
        return {
            "raw": [], "method": method,
            "n_input": n_input, "n_input_resolved": 0,
            "wall_time_sec": wall, "tool_version": "FELLA-unknown",
            "db_release": f"kegg_{organism}",
            "parameters": {"organism": organism},
            "auxiliary_data": {},
            "error": response.data.get("error", "unknown"),
        }
    return {
        "raw": response.data.get("pathways", []),
        "method": method,
        "n_input": n_input,
        "n_input_resolved": int(response.data.get("n_resolved", n_input)),
        "wall_time_sec": wall,
        "tool_version": str(response.data.get("tool_version", "FELLA")),
        "db_release": str(response.data.get("db_release", f"kegg_{organism}")),
        "parameters": {"organism": organism},
        "auxiliary_data": response.data.get("auxiliary_data", {}),
    }
