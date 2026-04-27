"""HTTP client for the ClassyFire REST API."""
from __future__ import annotations

import os
import time
from threading import Lock
from typing import Any

import requests

from tools.classyfire.errors import (
    ClassyfireAPIError,
    ClassyfireNotFoundError,
    ClassyfireTimeoutError,
)


DEFAULT_BASE_URLS = (
    "https://classyfire.wishartlab.com",
    "http://classyfire.wishartlab.com",
)


class ClassyfireApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout_seconds: float = 30.0,
        poll_timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 2.0,
        min_interval_seconds: float = 1.0,
        session: requests.Session | None = None,
    ):
        env_base_url = os.environ.get("METAGENT_CLASSYFIRE_BASE_URL")
        if base_url or env_base_url:
            self.base_urls = ((base_url or env_base_url or "").rstrip("/"),)
        else:
            self.base_urls = DEFAULT_BASE_URLS
        self.timeout_seconds = timeout_seconds
        self.poll_timeout_seconds = poll_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.min_interval_seconds = min_interval_seconds
        self.session = session or requests.Session()
        self._last_request_at = 0.0
        self._request_lock = Lock()
        self._batch_lock = Lock()

    def lookup_entity(self, inchikey: str) -> dict[str, Any]:
        return self._request_json("GET", f"/entities/{inchikey}.json")

    def classify_via_batch(self, inchikey: str) -> dict[str, Any]:
        with self._batch_lock:
            submitted = self._request_json(
                "POST",
                "/queries.json",
                json={
                    "label": "metagent_query",
                    "query_input": f"InChIKey={inchikey}",
                    "query_type": "STRUCTURE",
                },
            )
            query_id = submitted.get("id")
            if query_id is None:
                raise ClassyfireAPIError("ClassyFire query submission did not return an id.")
            deadline = time.monotonic() + self.poll_timeout_seconds
            while time.monotonic() < deadline:
                result = self._request_json("GET", f"/queries/{query_id}.json")
                if result.get("status") == "DONE" or result.get("entities") is not None:
                    entities = result.get("entities") or []
                    if not entities:
                        raise ClassyfireNotFoundError(
                            f"ClassyFire returned no classification for {inchikey}."
                        )
                    return entities[0]
                time.sleep(self.poll_interval_seconds)
            raise ClassyfireTimeoutError(
                f"ClassyFire batch job {query_id} did not finish within "
                f"{self.poll_timeout_seconds:g} seconds."
            )

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self._throttle()
        last_error: Exception | None = None
        saw_not_found = False
        for base_url in self.base_urls:
            try:
                resp = self.session.request(
                    method,
                    f"{base_url}{path}",
                    timeout=self.timeout_seconds,
                    **kwargs,
                )
            except requests.RequestException as exc:
                last_error = exc
                continue
            if resp.status_code == 404:
                saw_not_found = True
                continue
            if resp.status_code >= 400:
                raise ClassyfireAPIError(
                    f"ClassyFire HTTP {resp.status_code}: {resp.text[:300]}"
                )
            try:
                data = resp.json()
            except ValueError as exc:
                raise ClassyfireAPIError("ClassyFire returned non-JSON response.") from exc
            if not isinstance(data, dict):
                raise ClassyfireAPIError("ClassyFire returned unexpected JSON shape.")
            return data
        if saw_not_found:
            raise ClassyfireNotFoundError(f"ClassyFire has no record for {path}.")
        if last_error is not None:
            raise ClassyfireAPIError(f"ClassyFire request failed: {last_error}") from last_error
        raise ClassyfireAPIError("ClassyFire request failed without a response.")

    def _throttle(self) -> None:
        with self._request_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            if elapsed < self.min_interval_seconds:
                time.sleep(self.min_interval_seconds - elapsed)
            self._last_request_at = time.monotonic()
