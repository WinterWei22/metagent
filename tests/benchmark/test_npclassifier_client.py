from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tools.benchmark.npclassifier.client import (  # noqa: E402
    NPClassifierResult,
    cache_path_for,
    classify_compound_npc,
    classify_pool_npc,
)


INCHIKEY = "REFJWTPEDVJJIY-UHFFFAOYSA-N"  # quercetin
INCHIKEY2 = "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"  # ethanol
SMILES_QUERCETIN = "O=C1C(O)=C(Oc2cc(O)cc(O)c12)c1ccc(O)c(O)c1"
SMILES_ETHANOL = "CCO"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


def npc_payload(superclass: list[str], class_: list[str], pathway: list[str], isglycoside: bool = False) -> dict:
    return {
        "superclass_results": superclass,
        "class_results": class_,
        "pathway_results": pathway,
        "isglycoside": isglycoside,
    }


def write_cached_result(cache_dir: Path, inchikey: str, smiles: str = "") -> None:
    result = NPClassifierResult(
        inchikey=inchikey,
        smiles=smiles,
        superclass=["Flavonoids"],
        class_=["Flavonols"],
        pathway=["Shikimates and Phenylpropanoids"],
        isglycoside=False,
        fetched_at="2026-04-29T00:00:00+00:00",
    )
    cache_path_for(cache_dir, inchikey).parent.mkdir(parents=True, exist_ok=True)
    cache_path_for(cache_dir, inchikey).write_text(
        json.dumps({"status": "ok", "result": result.to_dict()})
    )


def test_classify_compound_cache_hit(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    write_cached_result(cache_dir, INCHIKEY, smiles=SMILES_QUERCETIN)
    calls = []
    monkeypatch.setattr("requests.request", lambda *a, **k: calls.append((a, k)))

    result = classify_compound_npc(SMILES_QUERCETIN, INCHIKEY, cache_dir=cache_dir)

    assert result is not None
    assert result.superclass == ["Flavonoids"]
    assert result.class_ == ["Flavonols"]
    assert result.pathway == ["Shikimates and Phenylpropanoids"]
    assert calls == []


def test_classify_compound_cache_miss_then_hit(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        return FakeResponse(
            200,
            npc_payload(["Flavonoids"], ["Flavonols"], ["Shikimates and Phenylpropanoids"]),
        )

    monkeypatch.setattr("requests.request", fake_request)

    first = classify_compound_npc(SMILES_QUERCETIN, INCHIKEY, cache_dir=cache_dir)
    second = classify_compound_npc(SMILES_QUERCETIN, INCHIKEY, cache_dir=cache_dir)

    assert first is not None
    assert second is not None
    assert first.superclass == ["Flavonoids"]
    assert second.class_ == ["Flavonols"]
    assert len(calls) == 1
    assert calls[0][0] == "GET"
    assert "smiles=" in calls[0][1]


def test_classify_compound_handles_invalid_smiles(tmp_path, monkeypatch):
    """HTTP 500 (NPClassifier's response to invalid SMILES) → permanent failure."""
    cache_dir = tmp_path / "cache"
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        return FakeResponse(500, text="<h1>500 Internal Server Error</h1>")

    monkeypatch.setattr("requests.request", fake_request)

    result = classify_compound_npc("NOTASMILES", INCHIKEY, cache_dir=cache_dir)

    assert result is None
    assert len(calls) == 1
    cached = json.loads(cache_path_for(cache_dir, INCHIKEY).read_text())
    assert cached["status"] == "failed"
    assert cached["reason"] == "http_500"


def test_empty_array_response_treated_as_ok(tmp_path, monkeypatch):
    """Compound NPClassifier cannot place → empty arrays, status=ok (not a failure)."""
    cache_dir = tmp_path / "cache"

    def fake_request(method, url, **kwargs):
        return FakeResponse(200, npc_payload([], [], [], isglycoside=False))

    monkeypatch.setattr("requests.request", fake_request)

    result = classify_compound_npc(SMILES_ETHANOL, INCHIKEY2, cache_dir=cache_dir)

    assert result is not None
    assert result.superclass == []
    assert result.class_ == []
    assert result.pathway == []
    cached = json.loads(cache_path_for(cache_dir, INCHIKEY2).read_text())
    assert cached["status"] == "ok"


def test_classify_pool_resumes_from_checkpoint(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    checkpoint = tmp_path / "checkpoint.json"
    write_cached_result(cache_dir, INCHIKEY)
    checkpoint.write_text(json.dumps({"processed_keys": [INCHIKEY.split("-", 1)[0]]}))
    calls = []
    sleeps = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        return FakeResponse(
            200,
            npc_payload(["Fatty acyls"], ["Fatty alcohols"], ["Fatty acids"]),
        )

    monkeypatch.setattr("requests.request", fake_request)
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    results = classify_pool_npc(
        [
            {"inchikey": INCHIKEY, "smiles": SMILES_QUERCETIN},
            {"inchikey": INCHIKEY2, "smiles": SMILES_ETHANOL},
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
