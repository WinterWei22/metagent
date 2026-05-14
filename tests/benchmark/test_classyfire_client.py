from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tools.benchmark.classyfire.client import (  # noqa: E402
    ClassyFireResult,
    cache_path_for,
    classify_compound,
    classify_pool,
)


INCHIKEY = "WQZGKKKJIJFFOK-GASJEMHNSA-N"
INCHIKEY2 = "RYYVLZVUVIJVGH-UHFFFAOYSA-N"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = json.dumps(self._payload)

    def json(self) -> dict:
        return self._payload


def entity(inchikey: str = INCHIKEY, direct_parent: str = "Hexoses") -> dict:
    return {
        "inchikey": f"InChIKey={inchikey}",
        "kingdom": {"name": "Organic compounds"},
        "superclass": {"name": "Organic oxygen compounds"},
        "class": {"name": "Organooxygen compounds"},
        "subclass": {"name": "Carbohydrates and carbohydrate conjugates"},
        "direct_parent": {"name": direct_parent},
        "intermediate_nodes": [{"name": "Monosaccharides"}],
        "molecular_framework": "Aliphatic heteromonocyclic compounds",
        "substituents": ["Hexose monosaccharide"],
        "description": "A hexose.",
        "classification_version": "2.1",
    }


def write_cached_result(cache_dir: Path, inchikey: str) -> None:
    result = ClassyFireResult(
        inchikey=inchikey,
        kingdom="Organic compounds",
        superclass="Organic oxygen compounds",
        class_="Organooxygen compounds",
        subclass="Carbohydrates and carbohydrate conjugates",
        direct_parent="Hexoses",
        intermediate_nodes=["Monosaccharides"],
        molecular_framework=None,
        substituents=[],
        description="cached",
        full_taxonomy="Organic compounds > Organic oxygen compounds > Organooxygen compounds",
        fetched_at="2026-04-29T00:00:00+00:00",
        api_version="2.1",
    )
    cache_path_for(cache_dir, inchikey).parent.mkdir(parents=True, exist_ok=True)
    cache_path_for(cache_dir, inchikey).write_text(
        json.dumps({"status": "ok", "result": result.to_dict()})
    )


def test_classify_compound_cache_hit(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    write_cached_result(cache_dir, INCHIKEY)
    calls = []
    monkeypatch.setattr("requests.request", lambda *a, **k: calls.append((a, k)))

    result = classify_compound(INCHIKEY, "C(C1C(C(C(C(O1)O)O)O)O)O", cache_dir=cache_dir)

    assert result is not None
    assert result.direct_parent == "Hexoses"
    assert calls == []


def test_classify_compound_cache_miss_then_hit(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        return FakeResponse(200, entity())

    monkeypatch.setattr("requests.request", fake_request)

    first = classify_compound(INCHIKEY, "C(C1C(C(C(C(O1)O)O)O)O)O", cache_dir=cache_dir)
    second = classify_compound(INCHIKEY, "C(C1C(C(C(C(O1)O)O)O)O)O", cache_dir=cache_dir)

    assert first is not None
    assert second is not None
    assert first.full_taxonomy.endswith("Hexoses")
    assert second.direct_parent == "Hexoses"
    assert len(calls) == 1


def test_classify_compound_handles_404(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        return FakeResponse(404, {"error": "not found"})

    monkeypatch.setattr("requests.request", fake_request)

    result = classify_compound(INCHIKEY, "", cache_dir=cache_dir)

    assert result is None
    assert len(calls) == 1
    cached = json.loads(cache_path_for(cache_dir, INCHIKEY).read_text())
    assert cached["status"] == "failed"


def test_classify_pool_resumes_from_checkpoint(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    checkpoint = tmp_path / "checkpoint.json"
    write_cached_result(cache_dir, INCHIKEY)
    checkpoint.write_text(json.dumps({"processed_keys": [INCHIKEY.split("-", 1)[0]]}))
    calls = []
    sleeps = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        return FakeResponse(200, entity(INCHIKEY2, direct_parent="Xanthines"))

    monkeypatch.setattr("requests.request", fake_request)
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    results = classify_pool(
        [
            {"inchikey": INCHIKEY, "smiles": "glucose"},
            {"inchikey": INCHIKEY2, "smiles": "Cn1cnc2c1c(=O)n(C)c(=O)n2C"},
        ],
        cache_dir=cache_dir,
        request_interval_sec=0.01,
        checkpoint_path=checkpoint,
    )

    assert [r.inchikey for r in results] == [INCHIKEY, INCHIKEY2]
    assert len(calls) == 1
    assert sleeps == [0.01]
    saved = json.loads(checkpoint.read_text())
    assert sorted(saved["processed_keys"]) == sorted(
        [INCHIKEY.split("-", 1)[0], INCHIKEY2.split("-", 1)[0]]
    )
