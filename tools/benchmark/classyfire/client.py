"""ClassyFire client with file-cache and resumable pool classification.

This module is intentionally independent from ``tools/classyfire``. The
benchmark workflow needs per-compound JSON cache files, failure caching, and
checkpoint metadata rather than the verifier tool's SQLite cache.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import requests


BASE_URL = "http://classyfire.wishartlab.com"
QUERY_LABEL = "metagent_benchmark_classyfire"


class ClassyFireNetworkError(RuntimeError):
    """Raised when ClassyFire cannot be reached after retries."""


@dataclass
class ClassyFireResult:
    inchikey: str
    kingdom: str | None
    superclass: str | None
    class_: str | None
    subclass: str | None
    direct_parent: str | None
    intermediate_nodes: list[str]
    molecular_framework: str | None
    substituents: list[str]
    description: str | None
    full_taxonomy: str
    fetched_at: str
    api_version: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClassyFireResult":
        return cls(
            inchikey=data["inchikey"],
            kingdom=data.get("kingdom"),
            superclass=data.get("superclass"),
            class_=data.get("class_"),
            subclass=data.get("subclass"),
            direct_parent=data.get("direct_parent"),
            intermediate_nodes=list(data.get("intermediate_nodes") or []),
            molecular_framework=data.get("molecular_framework"),
            substituents=list(data.get("substituents") or []),
            description=data.get("description"),
            full_taxonomy=data.get("full_taxonomy") or "",
            fetched_at=data.get("fetched_at") or "",
            api_version=data.get("api_version"),
        )


def inchikey_first_block(inchikey: str) -> str:
    return inchikey.strip().removeprefix("InChIKey=").split("-", 1)[0]


def cache_path_for(cache_dir: Path, inchikey: str) -> Path:
    return cache_dir / f"{inchikey_first_block(inchikey)}.json"


def classify_compound(
    inchikey: str,
    smiles: str,
    *,
    cache_dir: Path,
    timeout_sec: float = 30,
    max_retries: int = 3,
) -> ClassyFireResult | None:
    """Query ClassyFire API for one compound.

    Cache is checked first and written for both successful classifications and
    permanent failures. Permanent compound-level failures return None. Network
    connectivity failures raise ``ClassyFireNetworkError`` so callers can pause
    a long run instead of silently marking every compound failed.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_path_for(cache_dir, inchikey)
    cached = _read_cache(cache_path)
    if cached is not None:
        return cached

    try:
        payload = _lookup_by_inchikey(inchikey, timeout_sec=timeout_sec, max_retries=max_retries)
        source = "direct_lookup"
    except _NotFound:
        if not smiles:
            _write_failure_cache(cache_path, inchikey, "not_found_no_smiles", "direct_lookup")
            return None
        time.sleep(5.5)
        payload = _classify_by_structure(
            inchikey=inchikey,
            smiles=smiles,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
        )
        source = "batch_job"
        if payload is None:
            _write_failure_cache(cache_path, inchikey, "not_found_or_rejected", source)
            return None
    except _PermanentFailure as exc:
        _write_failure_cache(cache_path, inchikey, exc.reason, "direct_lookup")
        return None

    result = _parse_result(payload, fallback_inchikey=inchikey)
    _write_success_cache(cache_path, result, source=source, raw_response=payload)
    return result


def classify_pool(
    compounds: Iterable[dict],
    *,
    cache_dir: Path,
    request_interval_sec: float = 5.5,
    progress_callback: Callable | None = None,
    checkpoint_path: Path | None = None,
) -> list[ClassyFireResult]:
    """Batch-classify compounds with cache-first rate limiting and checkpointing."""
    ordered = _dedupe_compounds(compounds)
    processed = _load_checkpoint(checkpoint_path)
    results: list[ClassyFireResult] = []

    for idx, compound in enumerate(ordered, start=1):
        inchikey = compound["inchikey"]
        key = inchikey_first_block(inchikey)
        cache_exists = cache_path_for(cache_dir, inchikey).exists()

        if key in processed:
            cached = _read_cache(cache_path_for(cache_dir, inchikey))
            if cached is not None:
                results.append(cached)
            _emit(progress_callback, idx, len(ordered), key, "checkpoint_skip")
            continue

        if not cache_exists:
            _sleep_before_request(request_interval_sec)

        try:
            result = classify_compound(
                inchikey,
                compound.get("smiles") or "",
                cache_dir=cache_dir,
            )
        except ClassyFireNetworkError:
            _write_checkpoint(checkpoint_path, processed)
            raise
        except Exception as exc:
            result = None
            _emit(progress_callback, idx, len(ordered), key, f"failed:{exc}")

        if result is not None:
            results.append(result)
            status = "classified_cache" if cache_exists else "classified_api"
        else:
            status = "unclassified_cache" if cache_exists else "unclassified_api"

        processed.add(key)
        if len(processed) % 50 == 0:
            _write_checkpoint(checkpoint_path, processed)
        _emit(progress_callback, idx, len(ordered), key, status)

    _write_checkpoint(checkpoint_path, processed)
    return results


class _NotFound(Exception):
    pass


class _PermanentFailure(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _lookup_by_inchikey(inchikey: str, *, timeout_sec: float, max_retries: int) -> dict[str, Any]:
    url = f"{BASE_URL}/entities/{inchikey.strip().removeprefix('InChIKey=')}.json"
    response = _request("GET", url, timeout_sec=timeout_sec, max_retries=max_retries)
    if response.status_code == 404:
        raise _NotFound()
    if response.status_code in {400, 422} or 400 <= response.status_code < 500:
        raise _PermanentFailure(f"http_{response.status_code}")
    return _json_response(response)


def _classify_by_structure(
    *,
    inchikey: str,
    smiles: str,
    timeout_sec: float,
    max_retries: int,
) -> dict[str, Any] | None:
    if not smiles:
        return None
    submitted = _submit_query(inchikey, smiles, timeout_sec=timeout_sec, max_retries=max_retries)
    if submitted is None:
        return None
    query_id = submitted.get("id")
    if query_id is None:
        return None
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        response = _request(
            "GET",
            f"{BASE_URL}/queries/{query_id}.json",
            timeout_sec=timeout_sec,
            max_retries=max_retries,
        )
        if response.status_code == 404:
            return None
        if 400 <= response.status_code < 500:
            return None
        data = _json_response(response)
        status = str(data.get("status") or "").lower()
        if status in {"done", "completed"} or data.get("entities") is not None:
            entities = data.get("entities") or []
            return entities[0] if entities else None
        time.sleep(10)
    return None


def _submit_query(
    inchikey: str,
    smiles: str,
    *,
    timeout_sec: float,
    max_retries: int,
) -> dict[str, Any] | None:
    response = _request(
        "POST",
        f"{BASE_URL}/queries.json",
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        json={
            "label": QUERY_LABEL,
            "query_input": f"{inchikey_first_block(inchikey)}\t{smiles}",
            "query_type": "STRUCTURE",
        },
    )
    if response.status_code in {400, 404, 422} or 400 <= response.status_code < 500:
        return None
    return _json_response(response)


def _request(method: str, url: str, *, timeout_sec: float, max_retries: int, **kwargs: Any) -> requests.Response:
    last_network_exc: requests.RequestException | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.request(method, url, timeout=timeout_sec, **kwargs)
        except requests.RequestException as exc:
            last_network_exc = exc
            time.sleep(min(2**attempt, 30))
            continue
        if response.status_code in {429, 500, 502, 503, 504} and attempt < max_retries:
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2**attempt, 30)
            time.sleep(delay)
            continue
        if response.status_code in {429, 500, 502, 503, 504}:
            raise ClassyFireNetworkError(
                f"ClassyFire returned HTTP {response.status_code} after retries."
            )
        return response
    if last_network_exc is not None:
        raise ClassyFireNetworkError(f"ClassyFire network failure: {last_network_exc}") from last_network_exc
    raise ClassyFireNetworkError("ClassyFire did not return a usable response after retries.")


def _json_response(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise _PermanentFailure("non_json_response") from exc
    if not isinstance(data, dict):
        raise _PermanentFailure("unexpected_json_shape")
    return data


def _parse_result(payload: dict[str, Any], *, fallback_inchikey: str) -> ClassyFireResult:
    nodes = [
        _node_name(payload.get("kingdom")),
        _node_name(payload.get("superclass")),
        _node_name(payload.get("class")),
        _node_name(payload.get("subclass")),
        _node_name(payload.get("direct_parent")),
    ]
    full_taxonomy = " > ".join(node for node in nodes if node)
    return ClassyFireResult(
        inchikey=str(payload.get("inchikey") or fallback_inchikey).removeprefix("InChIKey="),
        kingdom=nodes[0],
        superclass=nodes[1],
        class_=nodes[2],
        subclass=nodes[3],
        direct_parent=nodes[4],
        intermediate_nodes=[
            name for item in payload.get("intermediate_nodes") or []
            if (name := _node_name(item))
        ],
        molecular_framework=payload.get("molecular_framework"),
        substituents=[str(item) for item in payload.get("substituents") or []],
        description=payload.get("description"),
        full_taxonomy=full_taxonomy,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        api_version=payload.get("classification_version"),
    )


def _node_name(value: Any) -> str | None:
    if isinstance(value, dict) and value.get("name"):
        return str(value["name"])
    return None


def _read_cache(path: Path) -> ClassyFireResult | None:
    if not path.exists():
        return None
    with path.open() as fh:
        data = json.load(fh)
    if data.get("status") != "ok":
        return None
    return ClassyFireResult.from_dict(data["result"])


def _write_success_cache(
    path: Path,
    result: ClassyFireResult,
    *,
    source: str,
    raw_response: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "ok",
        "source": source,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "result": result.to_dict(),
        "raw_response": raw_response,
    }
    _atomic_json_write(path, payload)


def _write_failure_cache(path: Path, inchikey: str, reason: str, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(
        path,
        {
            "status": "failed",
            "source": source,
            "inchikey": inchikey,
            "reason": reason,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as fh:
        json.dump(payload, fh, sort_keys=True)
    tmp.replace(path)


def _dedupe_compounds(compounds: Iterable[dict]) -> list[dict]:
    seen: set[str] = set()
    ordered: list[dict] = []
    for compound in compounds:
        inchikey = compound.get("inchikey")
        smiles = compound.get("smiles")
        if not inchikey or not smiles:
            continue
        key = inchikey_first_block(inchikey)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(compound)
    return ordered


def _load_checkpoint(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    with path.open() as fh:
        data = json.load(fh)
    return set(data.get("processed_keys") or [])


def _write_checkpoint(path: Path | None, processed: set[str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(
        path,
        {
            "processed_keys": sorted(processed),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _sleep_before_request(request_interval_sec: float) -> None:
    if request_interval_sec > 0:
        time.sleep(request_interval_sec)


def _emit(callback: Callable | None, *args: Any) -> None:
    if callback is not None:
        callback(*args)
