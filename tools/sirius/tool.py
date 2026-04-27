"""SIRIUS CLI wrapper for molecular formula and fragmentation-tree annotation."""
from __future__ import annotations

import csv
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Protocol
from urllib.parse import quote

import requests
from dotenv import load_dotenv

from tools.sirius.errors import (
    SiriusNoFormulaError,
    SiriusNotInstalledError,
    SiriusParseError,
    SiriusTimeoutError,
)
from tools.sirius.ms_writer import write_ms_file
from tools.sirius.schemas import SiriusAnnotateRequest, SiriusAnnotateResponse
from tools.sirius.tree_parser import parse_tree_file, parse_tree_json


@dataclass(frozen=True)
class SiriusRunResult:
    """Locations produced by one SIRIUS run."""

    output_dir: Path
    sirius_version: str


class SiriusRunner(Protocol):
    """Minimal runner interface used by real and mock execution paths."""

    def run(
        self,
        *,
        input_ms: Path,
        output_dir: Path,
        req: SiriusAnnotateRequest,
        sirius_bin: str,
        sirius_version: str,
    ) -> SiriusRunResult:
        ...


def sirius_annotate(
    req: SiriusAnnotateRequest,
    *,
    runner: SiriusRunner | None = None,
) -> SiriusAnnotateResponse:
    """Annotate one MS/MS spectrum using SIRIUS formula trees."""
    if req.spectrum.ionization_mode == "negative":
        raise NotImplementedError("sirius_annotate v0 supports positive ionization only.")

    if runner is None:
        sirius_bin = _resolve_sirius_binary()
        sirius_version = _get_sirius_version(
            sirius_bin,
            timeout_seconds=min(req.timeout_seconds, 30),
        )
        active_runner: SiriusRunner = RealSiriusRunner()
    else:
        sirius_bin = "mock-sirius"
        sirius_version = "mock"
        active_runner = runner

    with tempfile.TemporaryDirectory(prefix="metagent_sirius_") as tmp:
        tmp_path = Path(tmp)
        input_ms = write_ms_file(req.spectrum, tmp_path / "query.ms", compound_id="query")
        output_dir = tmp_path / "sirius_out"

        result = _run_with_timeout(
            active_runner,
            input_ms=input_ms,
            output_dir=output_dir,
            req=req,
            sirius_bin=sirius_bin,
            sirius_version=sirius_version,
        )

        project_file = _sirius6_project_file(result.output_dir)
        if project_file.exists() and not list(result.output_dir.rglob("formula_candidates.tsv")):
            formula, formula_score, fragments = _parse_sirius6_project(
                project_file,
                sirius_bin=sirius_bin,
                timeout_seconds=req.timeout_seconds,
            )
        else:
            formula, formula_score = _parse_top_formula(result.output_dir)
            tree_path = _find_tree_json(result.output_dir, formula)
            fragments = parse_tree_file(tree_path, formula_score=formula_score)

    explain = (
        f"SIRIUS {sirius_version} predicted precursor formula {formula} "
        f"with score {formula_score:.3f} and returned {len(fragments)} "
        "fragment tree nodes."
    )
    return SiriusAnnotateResponse(
        predicted_formula=formula,
        formula_score=formula_score,
        fragments=fragments,
        tree_node_count=len(fragments),
        sirius_version=sirius_version,
        explain=explain,
    )


class RealSiriusRunner:
    """Run the installed SIRIUS CLI."""

    def run(
        self,
        *,
        input_ms: Path,
        output_dir: Path,
        req: SiriusAnnotateRequest,
        sirius_bin: str,
        sirius_version: str,
    ) -> SiriusRunResult:
        cmd = [
            sirius_bin,
            "--log",
            "WARNING",
            "-i",
            str(input_ms),
            "-o",
            str(output_dir),
            "formula",
            "--no-recalibration",
            "--candidates",
            "1",
            "-p",
            req.instrument_preset,
            "--compound-timeout",
            str(req.timeout_seconds),
            "--tree-timeout",
            str(req.timeout_seconds),
        ]
        try:
            completed = subprocess.run(
                cmd,
                check=False,
                text=True,
                capture_output=True,
                timeout=req.timeout_seconds,
            )
        except subprocess.TimeoutExpired as e:
            raise SiriusTimeoutError(
                f"SIRIUS did not finish within {req.timeout_seconds}s."
            ) from e

        combined = "\n".join([completed.stdout or "", completed.stderr or ""]).strip()
        if "Please Login" in combined or "Login ERROR" in combined:
            raise SiriusNotInstalledError(
                "SIRIUS is installed but this build requires login before "
                f"running formula trees: {combined[:500]}"
            )

        if completed.returncode != 0:
            raise SiriusParseError(
                f"SIRIUS exited with code {completed.returncode}: {combined[:500]}"
            )

        if not output_dir.exists() and not _sirius6_project_file(output_dir).exists():
            raise SiriusParseError(
                "SIRIUS completed but produced neither an output directory nor "
                f"a SIRIUS 6 project file for {output_dir}."
            )

        return SiriusRunResult(output_dir=output_dir, sirius_version=sirius_version)


class MockSiriusRunner:
    """Deterministic mock runner for unit tests and examples.

    If ``fixture_dir`` is provided, the runner first looks for files under that
    directory. Otherwise it writes built-in handcrafted SIRIUS-like outputs for
    glucose, caffeine, and L-carnitine.
    """

    def __init__(self, fixture_dir: str | Path | None = None) -> None:
        self.fixture_dir = Path(fixture_dir) if fixture_dir is not None else None

    def run(
        self,
        *,
        input_ms: Path,
        output_dir: Path,
        req: SiriusAnnotateRequest,
        sirius_bin: str,
        sirius_version: str,
    ) -> SiriusRunResult:
        compound = _mock_compound_for(req.spectrum.precursor_mz)
        if self.fixture_dir is not None:
            fixture = self.fixture_dir / compound
            if fixture.exists():
                shutil.copytree(fixture, output_dir, dirs_exist_ok=True)
                return SiriusRunResult(output_dir=output_dir, sirius_version=sirius_version)

        _write_mock_output(output_dir, compound)
        return SiriusRunResult(output_dir=output_dir, sirius_version=sirius_version)


def _run_with_timeout(
    runner: SiriusRunner,
    *,
    input_ms: Path,
    output_dir: Path,
    req: SiriusAnnotateRequest,
    sirius_bin: str,
    sirius_version: str,
) -> SiriusRunResult:
    queue: Queue[tuple[str, SiriusRunResult | BaseException]] = Queue(maxsize=1)

    def target() -> None:
        try:
            queue.put(
                (
                    "ok",
                    runner.run(
                        input_ms=input_ms,
                        output_dir=output_dir,
                        req=req,
                        sirius_bin=sirius_bin,
                        sirius_version=sirius_version,
                    ),
                )
            )
        except BaseException as e:
            queue.put(("err", e))

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=req.timeout_seconds)
    if thread.is_alive():
        raise SiriusTimeoutError(
            f"SIRIUS runner did not finish within {req.timeout_seconds}s."
        )

    status, payload = queue.get_nowait()
    if status == "err":
        raise payload
    return payload  # type: ignore[return-value]


def _resolve_sirius_binary() -> str:
    load_dotenv()
    configured = os.environ.get("METAGENT_SIRIUS_PATH") or os.environ.get("SIRIUS_PATH")
    if configured:
        path = Path(configured).expanduser()
        if path.exists() and os.access(path, os.X_OK):
            return str(path)
        raise SiriusNotInstalledError(
            f"Configured SIRIUS executable does not exist or is not executable: {configured}"
        )

    path_hit = shutil.which("sirius")
    if path_hit:
        return path_hit

    raise SiriusNotInstalledError(
        "SIRIUS executable was not found. Set METAGENT_SIRIUS_PATH=/path/to/sirius "
        "or put sirius on PATH."
    )


def _get_sirius_version(sirius_bin: str, *, timeout_seconds: int = 30) -> str:
    try:
        completed = subprocess.run(
            [sirius_bin, "--version"],
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as e:
        raise SiriusNotInstalledError(f"SIRIUS executable not found: {sirius_bin}") from e
    except subprocess.TimeoutExpired as e:
        raise SiriusTimeoutError("SIRIUS --version timed out.") from e

    if completed.returncode != 0:
        raise SiriusNotInstalledError(
            f"SIRIUS executable failed version check: {(completed.stderr or completed.stdout)[:500]}"
        )
    text = "\n".join([completed.stdout or "", completed.stderr or ""])
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("SIRIUS "):
            return stripped.split("SIRIUS ", 1)[1].strip()
    return "unknown"


def _parse_top_formula(output_dir: Path) -> tuple[str, float]:
    candidates = sorted(output_dir.rglob("formula_candidates.tsv"))
    if not candidates:
        raise SiriusNoFormulaError(
            f"SIRIUS output under {output_dir} did not contain formula_candidates.tsv."
        )

    try:
        with candidates[0].open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            row = next(reader, None)
    except OSError as e:
        raise SiriusParseError(f"Could not read {candidates[0]}: {e}") from e

    if not row:
        raise SiriusNoFormulaError("SIRIUS formula_candidates.tsv is empty.")

    formula = _row_first(row, ("formula", "molecularFormula", "molecular_formula"))
    if not formula:
        raise SiriusParseError("formula_candidates.tsv has no formula column.")

    score_raw = _row_first(
        row,
        (
            "confidenceScore",
            "confidence",
            "score",
            "formulaScore",
            "SiriusScore",
            "explainedIntensity",
        ),
    )
    return formula, _normalise_score(score_raw)


def _find_tree_json(output_dir: Path, formula: str) -> Path:
    json_files = sorted(output_dir.rglob("*.json"))
    if not json_files:
        raise SiriusParseError(f"SIRIUS output under {output_dir} has no tree JSON file.")

    formula_safe = formula.replace("+", "").replace("-", "")
    for path in json_files:
        name = path.stem.replace("+", "").replace("-", "")
        if formula_safe in name:
            return path
    return json_files[0]


def _sirius6_project_file(output_dir: Path) -> Path:
    if output_dir.suffix == ".sirius":
        return output_dir
    if output_dir.suffix:
        return output_dir.with_suffix(output_dir.suffix + ".sirius")
    return output_dir.with_suffix(".sirius")


def _parse_sirius6_project(
    project_file: Path,
    *,
    sirius_bin: str,
    timeout_seconds: int,
) -> tuple[str, float, list]:
    base_url = _existing_service_url()
    proc: subprocess.Popen | None = None
    owns_service = False
    if base_url is None:
        port = _free_port()
        proc = subprocess.Popen(
            [sirius_bin, "service", "--headless", "-p", str(port), "-s"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        base_url = f"http://127.0.0.1:{port}"
        owns_service = True
    try:
        _wait_for_service(base_url, timeout_seconds=max(min(timeout_seconds, 90), 30))
        project_id = f"metagent_{os.getpid()}_{int(time.time() * 1000)}"
        opened = requests.put(
            f"{base_url}/api/projects/{project_id}",
            params={"pathToProject": str(project_file)},
            timeout=10,
        )
        opened.raise_for_status()

        features = _get_json(
            f"{base_url}/api/projects/{project_id}/aligned-features"
        )
        if not features:
            raise SiriusNoFormulaError("SIRIUS 6 project contains no aligned features.")
        feature_id = str(features[0]["alignedFeatureId"])

        formulas = _get_json(
            f"{base_url}/api/projects/{project_id}/aligned-features/{feature_id}/formulas"
        )
        if not formulas:
            raise SiriusNoFormulaError("SIRIUS 6 project contains no formula candidates.")
        top = sorted(formulas, key=lambda row: row.get("rank", 999999))[0]
        formula_id = str(top["formulaId"])
        formula = str(top["molecularFormula"])
        formula_score = _normalise_score(str(top.get("siriusScoreNormalized", "")))

        tree = _get_json(
            f"{base_url}/api/projects/{project_id}/aligned-features/{feature_id}"
            f"/formulas/{quote(formula_id, safe='')}/fragtree"
        )
        fragments = parse_tree_json(tree, formula_score=formula_score)
        return formula, formula_score, fragments
    except requests.RequestException as e:
        raise SiriusParseError(f"Could not read SIRIUS 6 project via REST API: {e}") from e
    finally:
        if owns_service:
            try:
                requests.post(f"{base_url}/actuator/shutdown", timeout=2)
            except requests.RequestException:
                pass
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()


def _get_json(url: str):
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _existing_service_url() -> str | None:
    for base_url in ("http://127.0.0.1:8765", "http://localhost:8765"):
        try:
            resp = requests.get(f"{base_url}/actuator/health", timeout=1)
            if resp.status_code == 200:
                return base_url
        except requests.RequestException:
            continue
    return None


def _wait_for_service(base_url: str, *, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            resp = requests.get(f"{base_url}/actuator/health", timeout=2)
            if resp.status_code == 200:
                return
        except requests.RequestException as e:
            last_error = e
        time.sleep(0.5)
    raise SiriusTimeoutError(f"SIRIUS REST service did not start: {last_error}")


def _row_first(row: dict[str, str], keys: tuple[str, ...]) -> str:
    lower = {key.lower(): value for key, value in row.items()}
    for key in keys:
        value = lower.get(key.lower())
        if value not in (None, ""):
            return value
    return ""


def _normalise_score(value: str) -> float:
    if not value:
        return 1.0
    try:
        score = float(value)
    except ValueError:
        return 1.0
    if 0.0 <= score <= 1.0:
        return score
    if 1.0 < score <= 100.0:
        return score / 100.0
    return max(0.0, min(score, 1.0))


def _mock_compound_for(precursor_mz: float) -> str:
    known = {
        "glucose": 181.0707,
        "caffeine": 195.0877,
        "lcarnitine": 162.1125,
    }
    return min(known, key=lambda name: abs(known[name] - precursor_mz))


def _write_mock_output(output_dir: Path, compound: str) -> None:
    formula, score, tree = _mock_payload(compound)
    compound_dir = output_dir / "query"
    tree_dir = compound_dir / "trees"
    tree_dir.mkdir(parents=True, exist_ok=True)
    (compound_dir / "formula_candidates.tsv").write_text(
        "formula\tconfidenceScore\n" f"{formula}\t{score:.3f}\n",
        encoding="utf-8",
    )
    (tree_dir / f"{formula}.json").write_text(
        json.dumps(tree, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _mock_payload(compound: str) -> tuple[str, float, dict[str, object]]:
    if compound == "caffeine":
        return (
            "C8H10N4O2",
            0.91,
            {
                "fragments": [
                    {"id": 0, "molecularFormula": "C8H11N4O2", "mz": 195.0877, "intensity": 100.0},
                    {"id": 1, "molecularFormula": "C7H8N3O", "mz": 150.0774, "intensity": 55.0},
                    {"id": 2, "molecularFormula": "C6H8N3O", "mz": 138.0668, "intensity": 80.0},
                ],
                "losses": [
                    {"source": 0, "target": 1, "molecularFormula": "CH3NO"},
                    {"source": 1, "target": 2, "molecularFormula": "C"},
                ],
            },
        )
    if compound == "lcarnitine":
        return (
            "C7H15NO3",
            0.88,
            {
                "fragments": [
                    {"id": 0, "molecularFormula": "C7H16NO3", "mz": 162.1125, "intensity": 100.0},
                    {"id": 1, "molecularFormula": "C4H8O3", "mz": 104.0473, "intensity": 72.0},
                    {"id": 2, "molecularFormula": "C3H9N", "mz": 60.0808, "intensity": 58.0},
                ],
                "losses": [
                    {"source": 0, "target": 1, "molecularFormula": "C3H9N"},
                    {"source": 0, "target": 2, "molecularFormula": "C4H7O3"},
                ],
            },
        )
    return (
        "C6H12O6",
        0.95,
        {
            "fragments": [
                {"id": 0, "molecularFormula": "C6H13O6", "mz": 181.0707, "intensity": 100.0},
                {"id": 1, "molecularFormula": "C6H11O5", "mz": 163.0600, "intensity": 85.3},
                {"id": 2, "molecularFormula": "C6H9O4", "mz": 145.0495, "intensity": 42.1},
                {"id": 3, "molecularFormula": "C6H7O3", "mz": 127.0390, "intensity": 38.0},
            ],
            "losses": [
                {"source": 0, "target": 1, "molecularFormula": "H2O"},
                {"source": 1, "target": 2, "molecularFormula": "H2O"},
                {"source": 2, "target": 3, "molecularFormula": "H2O"},
            ],
        },
    )
