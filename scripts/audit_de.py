#!/usr/bin/env python3
"""Smoke diagnostic for Tracks D (`fetch_metabolite_info`, `pathway_context`)
and E (`predict_spectrum`).

Runs a canonical glucose query through each tool, reports backend status
and timing, and exits with:

    0  — all three tools ran against their real backends and produced output
    1  — at least one tool ran in mock-only mode (missing env var / backend)
    2  — a tool crashed unexpectedly

Usage:

    python scripts/audit_de.py

The script never modifies any tool, any schema, or any test fixture.
It is read-only against the backends.
"""
from __future__ import annotations

import importlib
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------


def _hmdb_status() -> tuple[bool, str]:
    path = os.environ.get("METAGENT_HMDB_PATH", "")
    if not path:
        return False, "METAGENT_HMDB_PATH unset"
    if not os.path.exists(path):
        return False, f"{path} missing"
    return True, path


def _ramp_status() -> tuple[bool, str]:
    path = os.environ.get("METAGENT_RAMP_PATH", "")
    if not path:
        return False, "METAGENT_RAMP_PATH unset"
    if not os.path.exists(path):
        return False, f"{path} missing"
    return True, path


def _cfm_status() -> tuple[bool, str]:
    url = os.environ.get("METAGENT_CFM_URL", "").strip()
    if not url:
        return False, "METAGENT_CFM_URL unset"
    try:
        import requests

        r = requests.get(url.rstrip("/") + "/healthz", timeout=2.0)
        if r.status_code != 200:
            return False, f"{url} healthz HTTP {r.status_code}"
        try:
            body = r.json()
            ver = body.get("model_version", "unknown")
            return True, f"{url} (model_version={ver})"
        except ValueError:
            return True, f"{url} (healthz 200, body not JSON)"
    except Exception as e:
        return False, f"{url} unreachable: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Result rows
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    name: str
    backend_available: bool
    backend_detail: str
    ran: bool = False
    output_summary: str = ""
    elapsed_ms: float = 0.0
    error: str | None = None

    def status(self) -> str:
        if self.error:
            return "CRASH"
        if not self.backend_available:
            return "MOCK-ONLY"
        if not self.ran:
            return "NO-RUN"
        return "OK"


# ---------------------------------------------------------------------------
# Per-tool probes
# ---------------------------------------------------------------------------


def probe_metabolite_info() -> ToolResult:
    ok, detail = _hmdb_status()
    r = ToolResult(name="fetch_metabolite_info", backend_available=ok, backend_detail=detail)
    try:
        from schemas.molecule import MetaboliteInfoRequest
        from tools.metabolite_info import fetch_metabolite_info

        t0 = time.time()
        resp = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier="HMDB0000122", id_type="hmdb")
        )
        r.elapsed_ms = (time.time() - t0) * 1000
        r.ran = True
        r.output_summary = (
            f"found={resp.found}, "
            f"name={resp.primary_name!r}, "
            f"formula={resp.molecular_formula}, "
            f"kegg={resp.cross_refs.get('kegg')}"
        )
    except Exception as e:
        r.error = f"{type(e).__name__}: {e}"
    return r


def probe_pathway_context() -> ToolResult:
    ok, detail = _ramp_status()
    r = ToolResult(name="pathway_context", backend_available=ok, backend_detail=detail)
    if not ok:
        # No mock backend lives in the tool; without the DB we cannot run
        # even a smoke call. Record the situation and move on.
        r.output_summary = "skipped: RaMP SQLite not configured"
        return r
    try:
        from schemas.pathway import PathwayContextRequest
        from tools.pathway_context import pathway_context

        t0 = time.time()
        resp = pathway_context(
            PathwayContextRequest(metabolite_id="HMDB0000122", neighbour_depth=1)
        )
        r.elapsed_ms = (time.time() - t0) * 1000
        r.ran = True
        r.output_summary = (
            f"{len(resp.pathways)} pathways, "
            f"{len(resp.upstream_neighbours)} up / "
            f"{len(resp.downstream_neighbours)} down, "
            f"score={resp.cooccurrence_score:.2f}"
        )
    except Exception as e:
        r.error = f"{type(e).__name__}: {e}"
    return r


def probe_predict_spectrum() -> ToolResult:
    ok, detail = _cfm_status()
    r = ToolResult(name="predict_spectrum", backend_available=ok, backend_detail=detail)
    if not ok:
        r.output_summary = "skipped: CFM-ID shim unreachable"
        return r
    try:
        from schemas.spectrum import PredictSpectrumRequest
        from tools.spectrum_predict import predict_spectrum

        t0 = time.time()
        resp = predict_spectrum(
            PredictSpectrumRequest(
                smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
                adduct="[M+H]+",
                ionization_mode="positive",
            )
        )
        r.elapsed_ms = (time.time() - t0) * 1000
        r.ran = True
        r.output_summary = (
            f"{len(resp.predicted.mz)} peaks, "
            f"model={resp.model_version}, "
            f"precursor≈{resp.predicted.precursor_mz:.2f}"
        )
    except Exception as e:
        r.error = f"{type(e).__name__}: {e}"
    return r


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------


def _fmt_table(results: list[ToolResult]) -> str:
    cols = ("tool", "backend", "status", "elapsed_ms", "output")
    rows = [
        (
            r.name,
            r.backend_detail,
            r.status(),
            f"{r.elapsed_ms:>7.1f}" if r.ran else "      -",
            r.output_summary or (r.error or "-"),
        )
        for r in results
    ]
    widths = [
        max(len(str(row[i])) for row in (cols,) + tuple(rows))
        for i in range(len(cols))
    ]
    # Cap the backend + output columns so the table stays readable on a
    # standard terminal. Long values get ellipsised.
    widths[1] = min(widths[1], 60)
    widths[4] = min(widths[4], 60)

    def _ellipsis(s: str, w: int) -> str:
        return s if len(s) <= w else s[: w - 1] + "…"

    def _fmt_row(row):
        parts = []
        for i, cell in enumerate(row):
            s = str(cell)
            if i in (1, 4):
                s = _ellipsis(s, widths[i])
            parts.append(s.ljust(widths[i]))
        return "  ".join(parts)

    lines = [_fmt_row(cols), "-" * (sum(widths) + 2 * (len(cols) - 1))]
    lines.extend(_fmt_row(row) for row in rows)
    return "\n".join(lines)


def _exit_code(results: list[ToolResult]) -> int:
    if any(r.error for r in results):
        return 2
    if any(not r.backend_available for r in results):
        return 1
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print("Track D / E audit smoke diagnostic")
    print(f"  repo:  {_REPO_ROOT}")
    print(f"  time:  {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print()

    results: list[ToolResult] = []
    for probe in (probe_metabolite_info, probe_pathway_context, probe_predict_spectrum):
        try:
            results.append(probe())
        except Exception as e:  # defensive: a probe itself should never raise
            tb = traceback.format_exc()
            results.append(ToolResult(
                name=probe.__name__, backend_available=False,
                backend_detail="probe crashed",
                error=f"{type(e).__name__}: {e}\n{tb}",
            ))

    print(_fmt_table(results))
    print()

    rc = _exit_code(results)
    if rc == 0:
        print("All three tools ran against real backends. READY.")
    elif rc == 1:
        print("One or more tools ran in mock-only mode.")
        print("Set the relevant env var to unlock the real path:")
        print("  METAGENT_HMDB_PATH=/path/to/hmdb.sqlite")
        print("  METAGENT_RAMP_PATH=/path/to/ramp.sqlite")
        print("  METAGENT_CFM_URL=http://host:port")
    else:
        print("A tool crashed — see error column. Exit 2.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
