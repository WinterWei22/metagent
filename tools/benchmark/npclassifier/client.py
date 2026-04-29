"""NPClassifier client with file-cache and resumable pool classification.

NPClassifier (https://npclassifier.gnps2.org) provides a 3-level natural-product
taxonomy: superclass / class / pathway, plus an explicit ``isglycoside`` flag.
This module mirrors the structure of ``tools.benchmark.classyfire.client`` but
talks to a single GET endpoint and treats compound-level HTTP 500s (the API's
response to invalid SMILES) as permanent failures.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import requests


BASE_URL = "https://npclassifier.gnps2.org"
ENDPOINT = f"{BASE_URL}/classify"


class NPClassifierNetworkError(RuntimeError):
    """Raised when NPClassifier cannot be reached after retries."""


@dataclass
class NPClassifierResult:
    inchikey: str
    smiles: str
    superclass: list[str] = field(default_factory=list)
    class_: list[str] = field(default_factory=list)
    pathway: list[str] = field(default_factory=list)
    isglycoside: bool = False
    fetched_at: str = ""
    api_endpoint: str = ENDPOINT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NPClassifierResult":
        return cls(
            inchikey=data["inchikey"],
            smiles=data.get("smiles") or "",
            superclass=list(data.get("superclass") or []),
            class_=list(data.get("class_") or []),
            pathway=list(data.get("pathway") or []),
            isglycoside=bool(data.get("isglycoside") or False),
            fetched_at=data.get("fetched_at") or "",
            api_endpoint=data.get("api_endpoint") or ENDPOINT,
        )


def inchikey_first_block(inchikey: str) -> str:
    return inchikey.strip().removeprefix("InChIKey=").split("-", 1)[0]


def cache_path_for(cache_dir: Path, inchikey: str) -> Path:
    return cache_dir / f"{inchikey_first_block(inchikey)}.json"


def classify_compound_npc(
    smiles: str,
    inchikey: str,
    *,
    cache_dir: Path,
    timeout_sec: float = 30,
    max_retries: int = 3,
) -> NPClassifierResult | None:
    """Query NPClassifier for a single compound.

    Cache is consulted first; both successful classifications and permanent
    failures are written to disk so subsequent runs skip them. An empty-array
    response (NPClassifier could not assign a natural-product taxonomy) is
    cached as a successful result with empty lists, distinct from a failure.
    Permanent compound-level failures (HTTP 500 / malformed response) return
    ``None``. Transient infrastructure failures raise
    :class:`NPClassifierNetworkError` so callers can pause a long run instead
    of silently marking every compound failed.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_path_for(cache_dir, inchikey)
    cached = _read_cache(cache_path)
    if cached is not None:
        return cached
    if _failure_is_cached(cache_path):
        return None

    if not smiles:
        _write_failure_cache(cache_path, inchikey, "missing_smiles")
        return None

    try:
        payload = _request_classify(smiles, timeout_sec=timeout_sec, max_retries=max_retries)
    except _PermanentFailure as exc:
        _write_failure_cache(cache_path, inchikey, exc.reason)
        return None

    result = _parse_result(payload, inchikey=inchikey, smiles=smiles)
    _write_success_cache(cache_path, result, raw_response=payload)
    return result


def classify_pool_npc(
    compounds: Iterable[dict],
    *,
    cache_dir: Path,
    request_interval_sec: float = 1.0,
    progress_callback: Callable | None = None,
    checkpoint_path: Path | None = None,
) -> list[NPClassifierResult]:
    """Batch-classify compounds with cache-first rate limiting and checkpointing."""
    ordered = _dedupe_compounds(compounds)
    processed = _load_checkpoint(checkpoint_path)
    results: list[NPClassifierResult] = []

    for idx, compound in enumerate(ordered, start=1):
        inchikey = compound["inchikey"]
        smiles = compound.get("smiles") or ""
        key = inchikey_first_block(inchikey)
        cache_path = cache_path_for(cache_dir, inchikey)
        cache_exists = cache_path.exists()

        if key in processed:
            cached = _read_cache(cache_path)
            if cached is not None:
                results.append(cached)
            _emit(progress_callback, idx, len(ordered), key, "checkpoint_skip")
            continue

        if not cache_exists:
            _sleep_before_request(request_interval_sec)

        try:
            result = classify_compound_npc(smiles, inchikey, cache_dir=cache_dir)
        except NPClassifierNetworkError as exc:
            _emit(progress_callback, idx, len(ordered), key, f"network_pause_60s:{exc}")
            time.sleep(60)
            try:
                result = classify_compound_npc(smiles, inchikey, cache_dir=cache_dir)
            except NPClassifierNetworkError:
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


class _PermanentFailure(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _request_classify(smiles: str, *, timeout_sec: float, max_retries: int) -> dict[str, Any]:
    encoded = urllib.parse.quote(smiles, safe="")
    url = f"{ENDPOINT}?smiles={encoded}"
    response = _request("GET", url, timeout_sec=timeout_sec, max_retries=max_retries)
    if response.status_code == 500:
        raise _PermanentFailure("http_500")
    if 400 <= response.status_code < 500:
        raise _PermanentFailure(f"http_{response.status_code}")
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
        if response.status_code in {429, 502, 503, 504} and attempt < max_retries:
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2**attempt, 30)
            time.sleep(delay)
            continue
        if response.status_code in {429, 502, 503, 504}:
            raise NPClassifierNetworkError(
                f"NPClassifier returned HTTP {response.status_code} after retries."
            )
        return response
    if last_network_exc is not None:
        raise NPClassifierNetworkError(f"NPClassifier network failure: {last_network_exc}") from last_network_exc
    raise NPClassifierNetworkError("NPClassifier did not return a usable response after retries.")


def _json_response(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise _PermanentFailure("non_json_response") from exc
    if not isinstance(data, dict):
        raise _PermanentFailure("unexpected_json_shape")
    return data


def _parse_result(payload: dict[str, Any], *, inchikey: str, smiles: str) -> NPClassifierResult:
    return NPClassifierResult(
        inchikey=inchikey.strip().removeprefix("InChIKey="),
        smiles=smiles,
        superclass=_string_list(payload.get("superclass_results")),
        class_=_string_list(payload.get("class_results")),
        pathway=_string_list(payload.get("pathway_results")),
        isglycoside=bool(payload.get("isglycoside") or False),
        fetched_at=datetime.now(timezone.utc).isoformat(),
        api_endpoint=ENDPOINT,
    )


def _string_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _read_cache(path: Path) -> NPClassifierResult | None:
    if not path.exists():
        return None
    with path.open() as fh:
        data = json.load(fh)
    if data.get("status") != "ok":
        return None
    return NPClassifierResult.from_dict(data["result"])


def _failure_is_cached(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open() as fh:
        data = json.load(fh)
    return data.get("status") == "failed"


def _write_success_cache(
    path: Path,
    result: NPClassifierResult,
    *,
    raw_response: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "ok",
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "result": result.to_dict(),
        "raw_response": raw_response,
    }
    _atomic_json_write(path, payload)


def _write_failure_cache(path: Path, inchikey: str, reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(
        path,
        {
            "status": "failed",
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
