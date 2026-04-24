"""Verification layers — one module per claim type.

Each layer exposes a single ``verify_*(claim, source_report) -> VerifiedClaim``
function (or a sibling shape the agent dispatcher expects). Layers are
architecturally parallel and share nothing between themselves; all coupling
is at the ``agent.py`` dispatch boundary.
"""
