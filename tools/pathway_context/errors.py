"""Typed errors for pathway_context.

Two shapes of failure:

- The DB doesn't know the metabolite (resolves to an internal analyte but
  the analyte has no pathway rows). This is recoverable — the orchestrator
  can continue with other candidates or fall back to `fetch_metabolite_info`
  alone.

- The RaMP-DB backend itself is unavailable (path unset or file missing /
  corrupt). This is not recoverable from the orchestrator's side: an
  operator must install the DB.

A THIRD state — "the identifier is valid but no analyte row exists at all"
— is treated the same as the first: MetaboliteNotInNetworkError. The
orchestrator cannot tell the difference without another tool call and for
reporting purposes the outcome is identical (no pathway evidence).
"""
from __future__ import annotations

from schemas.common import ToolError


class MetaboliteNotInNetworkError(ToolError):
    """The metabolite ID resolved but is not part of any pathway in RaMP.

    Typical cause: a structurally valid HMDB ID that RaMP's curated set
    does not cover (e.g. a lipid species without pathway annotation, or a
    non-human metabolite when organism='hsa').
    """

    code = "PATHWAY_NOT_IN_NETWORK"
    recoverable = True


class RampUnavailableError(ToolError):
    """The RaMP-DB SQLite backend cannot be opened.

    Caller has to install the DB (see tools/pathway_context/Dockerfile) and
    set METAGENT_RAMP_PATH. Retries will not help until that is done.
    """

    code = "PATHWAY_RAMP_UNAVAILABLE"
    recoverable = False
