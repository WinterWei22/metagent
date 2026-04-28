"""MassBank-data downloader.

Acquires the MassBank-data GitHub repository to a local cache and exposes its
contributor layout for downstream parsing. Supports git clone (preferred,
resumable) and HTTP zip download as a fallback.

Source repository: https://github.com/MassBank/MassBank-data

The repo's top-level layout looks like::

    MassBank-data/
    ├── BAFG/                # contributor dirs, one per provider
    ├── BSU/
    ├── RIKEN/
    │   ├── BSU00001.txt
    │   ├── ...
    └── ...

Each ``.txt`` file is one MassBank record. We only navigate the directory
structure here — record parsing lives in :mod:`tools.benchmark.massbank_parser`.

Environment variables
---------------------
``METAGENT_MASSBANK_DIR``
    Default download target. Falls back to ``data/raw/massbank/`` under the
    project working directory if unset.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from schemas.common import ToolError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_URL_GIT = "https://github.com/MassBank/MassBank-data.git"
REPO_URL_ZIP = "https://github.com/MassBank/MassBank-data/archive/refs/heads/main.zip"
"""HTTP fallback. Equivalent content to the git clone, just no history."""

CHECKPOINT_MARKER = ".download_complete"
"""Sentinel file dropped at the root of the local clone after a successful
download. ``download_massbank`` short-circuits when present."""

CLONE_DIR_NAME = "MassBank-data"
"""Folder name we always clone into, irrespective of the parent dir name."""

DISK_WARN_GB = 5.0
"""Free space threshold below which we warn the user before downloading."""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MassBankDownloadError(ToolError):
    """Unrecoverable error during MassBank download."""

    code = "MASSBANK_DOWNLOAD_ERROR"
    recoverable = False


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class DownloadResult:
    """Outcome of a :func:`download_massbank` call."""

    downloaded_dir: Path
    """Root of the local MassBank-data clone (``<target_dir>/MassBank-data``)."""

    contributor_dirs: dict[str, Path] = field(default_factory=dict)
    """``{contributor_name: path}`` for every top-level dir that holds records.

    A directory is treated as a contributor if it contains at least one
    ``.txt`` file directly under it.
    """

    total_records: int = 0
    """Count of ``.txt`` files across all contributor dirs."""

    download_time_seconds: float = 0.0
    """Wall time spent in git/zip operations. Zero if a checkpoint was hit."""

    used_method: str = "git"
    """``"git"``, ``"zip"``, or ``"cached"``."""

    skipped: bool = False
    """``True`` iff the checkpoint marker was honoured and no download ran."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def download_massbank(
    target_dir: Path | str | None = None,
    contributors: list[str] | None = None,
    use_git: bool = True,
    force_refresh: bool = False,
) -> DownloadResult:
    """Download MassBank-data to a local cache.

    Parameters
    ----------
    target_dir
        Parent directory the clone lands under. If ``None``, falls back to
        ``$METAGENT_MASSBANK_DIR`` and finally to ``./data/raw/massbank``.
        The repo is always cloned into ``<target_dir>/MassBank-data`` so the
        same target_dir can be reused across runs.
    contributors
        Names of contributor subdirectories to surface in
        :attr:`DownloadResult.contributor_dirs`. ``None`` returns all
        contributors found in the clone. Note: filtering is metadata-only —
        ``git clone`` always pulls the whole repo because GitHub does not
        support partial clone of a subset of top-level directories without
        sparse-checkout, which adds complexity not worth it for ~600 MB.
    use_git
        ``True`` (default) uses ``git clone`` / ``git pull`` for resumable,
        history-preserving downloads. ``False`` falls back to a one-shot HTTP
        zip download. The HTTP path is used automatically if ``git`` is not
        on ``$PATH``.
    force_refresh
        If ``True``, ignore the checkpoint marker and re-download (or
        ``git pull`` if the clone exists).

    Returns
    -------
    :class:`DownloadResult`
        Populated with the local clone root, contributor map, and timings.

    Raises
    ------
    :class:`MassBankDownloadError`
        On unrecoverable failures (clone aborted, zip extraction failed,
        target directory not writable, etc.).
    """
    parent = _resolve_target_dir(target_dir)
    parent.mkdir(parents=True, exist_ok=True)
    clone_dir = parent / CLONE_DIR_NAME
    marker = clone_dir / CHECKPOINT_MARKER

    # Short-circuit if checkpoint exists.
    if marker.exists() and not force_refresh:
        logger.info("MassBank: checkpoint hit at %s, skipping download.", clone_dir)
        return DownloadResult(
            downloaded_dir=clone_dir,
            contributor_dirs=_discover_contributors(clone_dir, contributors),
            total_records=_count_records(clone_dir),
            download_time_seconds=0.0,
            used_method="cached",
            skipped=True,
        )

    _check_disk_space(parent)

    method = "git" if (use_git and _git_available()) else "zip"
    if use_git and method == "zip":
        logger.warning(
            "MassBank: git not available on PATH; falling back to HTTP zip download."
        )

    t0 = time.monotonic()
    if method == "git":
        _download_via_git(clone_dir, force_refresh=force_refresh)
    else:
        _download_via_zip(parent, clone_dir, force_refresh=force_refresh)
    elapsed = time.monotonic() - t0

    # Mark complete.
    marker.write_text(f"{method}\t{int(time.time())}\n")

    contributor_dirs = _discover_contributors(clone_dir, contributors)
    total = _count_records(clone_dir)
    logger.info(
        "MassBank: %s download complete in %.1fs (%d contributors, %d records).",
        method, elapsed, len(contributor_dirs), total,
    )
    return DownloadResult(
        downloaded_dir=clone_dir,
        contributor_dirs=contributor_dirs,
        total_records=total,
        download_time_seconds=elapsed,
        used_method=method,
        skipped=False,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _resolve_target_dir(arg: Path | str | None) -> Path:
    """Pick the target dir from the explicit arg, env var, or default."""
    if arg is not None:
        return Path(arg)
    env = os.environ.get("METAGENT_MASSBANK_DIR")
    if env:
        return Path(env)
    return Path("data/raw/massbank")


def _git_available() -> bool:
    return shutil.which("git") is not None


def _check_disk_space(path: Path) -> None:
    """Warn if free space at ``path`` is below ``DISK_WARN_GB``.

    Does not abort — sometimes the user has a remote-mounted cache where
    ``shutil.disk_usage`` lies. We only log.
    """
    try:
        usage = shutil.disk_usage(path)
    except OSError as e:
        logger.warning("MassBank: cannot stat disk usage at %s: %s", path, e)
        return
    free_gb = usage.free / (1024 ** 3)
    if free_gb < DISK_WARN_GB:
        logger.warning(
            "MassBank: free disk at %s is %.2f GB, which is below the %.1f GB "
            "warn threshold. Download is ~600 MB but a full repo + intermediate "
            "files can easily exceed 1 GB.",
            path, free_gb, DISK_WARN_GB,
        )


def _download_via_git(clone_dir: Path, *, force_refresh: bool) -> None:
    """Clone or update the repository.

    - If ``clone_dir`` exists and contains a ``.git`` subdir, run ``git pull``.
    - If ``clone_dir`` exists but is not a git repo, error out (refuse to
      destroy data that may be the user's).
    - Otherwise clone fresh.

    ``force_refresh=True`` removes a stale clone and reclones from scratch.
    """
    if clone_dir.exists():
        if force_refresh:
            logger.info("MassBank: force_refresh=True, removing %s", clone_dir)
            shutil.rmtree(clone_dir)
        elif (clone_dir / ".git").exists():
            logger.info("MassBank: existing clone at %s, running git pull.", clone_dir)
            _run_git(["git", "-C", str(clone_dir), "pull", "--ff-only"], clone_dir)
            return
        else:
            raise MassBankDownloadError(
                f"{clone_dir} exists but is not a git clone. Refusing to "
                "overwrite. Pass force_refresh=True or remove it manually."
            )

    logger.info("MassBank: cloning %s → %s", REPO_URL_GIT, clone_dir)
    _run_git(["git", "clone", "--depth", "1", REPO_URL_GIT, str(clone_dir)], clone_dir.parent)


def _run_git(cmd: list[str], cwd: Path) -> None:
    """Invoke git, surfacing failures as :class:`MassBankDownloadError`."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise MassBankDownloadError(f"git not on PATH: {e}") from e
    if result.returncode != 0:
        raise MassBankDownloadError(
            f"git command failed (exit {result.returncode}): "
            f"{' '.join(cmd)}\nstderr:\n{result.stderr.strip()}"
        )


def _download_via_zip(parent: Path, clone_dir: Path, *, force_refresh: bool) -> None:
    """One-shot HTTP zip download.

    GitHub serves ``main.zip`` which extracts to ``MassBank-data-main/``;
    we rename it to :data:`CLONE_DIR_NAME` for layout consistency.
    """
    import urllib.request
    import zipfile

    if clone_dir.exists():
        if force_refresh:
            logger.info("MassBank: force_refresh=True, removing %s", clone_dir)
            shutil.rmtree(clone_dir)
        else:
            raise MassBankDownloadError(
                f"{clone_dir} exists. Pass force_refresh=True for zip mode."
            )

    zip_path = parent / "_massbank_main.zip"
    logger.info("MassBank: downloading zip %s → %s", REPO_URL_ZIP, zip_path)
    try:
        urllib.request.urlretrieve(REPO_URL_ZIP, zip_path)
    except Exception as e:
        raise MassBankDownloadError(f"zip download failed: {e}") from e

    logger.info("MassBank: extracting %s", zip_path)
    extracted_root = parent / "MassBank-data-main"
    if extracted_root.exists():
        shutil.rmtree(extracted_root)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(parent)
    except zipfile.BadZipFile as e:
        raise MassBankDownloadError(f"corrupt zip: {e}") from e
    finally:
        zip_path.unlink(missing_ok=True)

    if not extracted_root.exists():
        raise MassBankDownloadError(
            f"expected {extracted_root} after zip extraction, not found."
        )
    extracted_root.rename(clone_dir)


def _discover_contributors(
    clone_dir: Path, requested: list[str] | None
) -> dict[str, Path]:
    """Walk the clone root and return the contributor → path map.

    A top-level directory is treated as a contributor if it contains at
    least one ``.txt`` file directly under it. We do a single ``iterdir`` +
    ``glob("*.txt")`` per directory; this stays fast for the ~50
    contributor dirs in MassBank-data.
    """
    if not clone_dir.is_dir():
        return {}
    contributor_dirs: dict[str, Path] = {}
    requested_set = {c.lower() for c in requested} if requested else None
    for child in sorted(clone_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        # Skip docs / scripts / metadata directories that don't hold records.
        # Heuristic: at least one .txt file directly under the dir.
        try:
            has_txt = any(child.glob("*.txt"))
        except OSError:
            continue
        if not has_txt:
            continue
        if requested_set is not None and child.name.lower() not in requested_set:
            continue
        contributor_dirs[child.name] = child

    if requested:
        missing = [c for c in requested if c not in contributor_dirs]
        if missing:
            logger.warning(
                "MassBank: requested contributors not found in clone: %s",
                ", ".join(missing),
            )
    return contributor_dirs


def _count_records(root: Path) -> int:
    """Recursive count of ``.txt`` files under the clone."""
    if not root.is_dir():
        return 0
    return sum(1 for _ in root.rglob("*.txt"))


# ---------------------------------------------------------------------------
# CLI shim — useful for ad-hoc invocations and tests
# ---------------------------------------------------------------------------


def _iter_contributors_for_log(d: dict[str, Path]) -> Iterable[str]:
    return sorted(d.keys())


if __name__ == "__main__":  # pragma: no cover — exercised in integration tests
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-dir", default=None)
    parser.add_argument(
        "--contributors", nargs="*", default=None,
        help="Contributor names to surface in the result (e.g. RIKEN BSU).",
    )
    parser.add_argument("--no-git", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = download_massbank(
        target_dir=args.target_dir,
        contributors=args.contributors,
        use_git=not args.no_git,
        force_refresh=args.force_refresh,
    )
    print(f"downloaded_dir   = {res.downloaded_dir}")
    print(f"used_method      = {res.used_method}")
    print(f"skipped          = {res.skipped}")
    print(f"download_time_s  = {res.download_time_seconds:.2f}")
    print(f"total_records    = {res.total_records}")
    print(f"contributor_dirs = {list(_iter_contributors_for_log(res.contributor_dirs))}")
