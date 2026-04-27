"""SQLite cache for permanent ClassyFire responses."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from tools.classyfire.schemas import ClassifyStructureResponse


DEFAULT_CACHE_PATH = Path("data/classyfire_cache.sqlite")


def resolve_cache_path() -> Path:
    return Path(os.environ.get("METAGENT_CLASSYFIRE_CACHE_PATH", DEFAULT_CACHE_PATH))


class ClassyfireCache:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else resolve_cache_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS classyfire_cache (
                    inchikey TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    source TEXT NOT NULL
                )
                """
            )

    def get(self, inchikey: str) -> ClassifyStructureResponse | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT response_json FROM classyfire_cache WHERE inchikey = ?",
                (inchikey,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        payload["source"] = "cache"
        return ClassifyStructureResponse.model_validate(payload)

    def put(self, inchikey: str, response: ClassifyStructureResponse, source: str) -> None:
        payload = response.model_dump(by_alias=True)
        payload["source"] = "api"
        fetched_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO classyfire_cache
                    (inchikey, response_json, fetched_at, source)
                VALUES (?, ?, ?, ?)
                """,
                (inchikey, json.dumps(payload, sort_keys=True), fetched_at, source),
            )
