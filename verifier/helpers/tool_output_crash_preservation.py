from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

from verifier.metrics import compute_claim_metrics
from verifier.schemas import ClassifiedClaim, VerifiedClaim


def run_with_partial_persistence(
    claims: Iterable[ClassifiedClaim],
    *,
    verifier: Callable[[ClassifiedClaim], VerifiedClaim],
    state_path: str | Path,
    task_id: str,
) -> list[VerifiedClaim]:
    verified: list[VerifiedClaim] = []
    for claim in claims:
        result = verifier(claim)
        verified.append(result)
        write_partial_claims(state_path, task_id=task_id, claims=verified)
    return verified


def write_partial_claims(state_path: str | Path, *, task_id: str, claims: list[VerifiedClaim]) -> None:
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"task_id": task_id, "claims_v1": [_dump_claim(claim) for claim in claims]}
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def read_persisted_claims(state_path: str | Path) -> list[dict]:
    return json.loads(Path(state_path).read_text(encoding="utf-8")).get("claims_v1", [])


def retroactive_compute_claim_metrics(state_path: str | Path):
    claims = [VerifiedClaim(**row) for row in read_persisted_claims(state_path)]
    return compute_claim_metrics(claims, claims)


def _dump_claim(claim: VerifiedClaim) -> dict:
    if hasattr(claim, "model_dump"):
        return claim.model_dump(mode="json")
    return claim.dict()
