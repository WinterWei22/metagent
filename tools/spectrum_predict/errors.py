"""Typed errors for predict_spectrum. Every error is a ToolError subclass
so the orchestrator can pattern-match on `.code` instead of parsing strings.

Three distinct failure modes map to three distinct error classes:

- The SMILES does not parse in RDKit. Fail BEFORE touching the container so
  the verifier agent can immediately try a cleaned-up structure instead of
  waiting 60 s for a timeout.
- The container accepted the request but did not finish in time. CFM-ID is
  known to hang on large/unusual molecules; we surface this as recoverable
  so the orchestrator may drop the candidate and move on.
- The container is unreachable (refused connection, DNS failure, 5xx from a
  reverse proxy). Not recoverable by retry — an operator has to start the
  container.
"""
from __future__ import annotations

from schemas.common import ToolError


class InvalidSmilesError(ToolError):
    """RDKit could not parse the requested SMILES.

    Raised before any HTTP call so invalid input is caught cheaply.
    """

    code = "PREDICT_INVALID_SMILES"
    recoverable = True


class PredictionTimeoutError(ToolError):
    """CFM-ID did not return within the configured timeout.

    Recoverable in the sense that the orchestrator may continue with the
    remaining candidates; a retry with identical inputs is unlikely to help.
    """

    code = "PREDICT_TIMEOUT"
    recoverable = True


class CfmUnavailableError(ToolError):
    """The CFM-ID HTTP shim cannot be reached at METAGENT_CFM_URL.

    Typical causes: the container is not running, the URL is misconfigured,
    or the reverse proxy in front of it is down. Operator intervention
    required; retrying without fixing the environment will not help.
    """

    code = "PREDICT_CFM_UNAVAILABLE"
    recoverable = False
