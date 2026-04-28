"""Unit tests for ``tools.benchmark.massbank_downloader``.

The unit tests never touch the network. The single integration test marked
with ``@pytest.mark.integration`` actually clones the MassBank-data repo and
is skipped by default — set ``METAGENT_RUN_INTEGRATION=1`` to enable.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from tools.benchmark.massbank_downloader import (
    CHECKPOINT_MARKER,
    CLONE_DIR_NAME,
    DownloadResult,
    MassBankDownloadError,
    _discover_contributors,
    download_massbank,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_clone(parent: Path, contributors: dict[str, int]) -> Path:
    """Build a fake clone at ``parent/MassBank-data`` with the given record counts."""
    clone = parent / CLONE_DIR_NAME
    clone.mkdir(parents=True, exist_ok=True)
    (clone / ".git").mkdir(exist_ok=True)
    for name, n in contributors.items():
        cdir = clone / name
        cdir.mkdir(exist_ok=True)
        for i in range(n):
            (cdir / f"{name}{i:05d}.txt").write_text("ACCESSION: TEST\n//\n")
    return clone


# ---------------------------------------------------------------------------
# Checkpoint behaviour
# ---------------------------------------------------------------------------


def test_skip_if_already_downloaded(tmp_path: Path) -> None:
    """Existing checkpoint marker → no git/zip invocation, ``skipped=True``."""
    clone = _make_fake_clone(tmp_path, {"RIKEN": 3, "BSU": 2})
    (clone / CHECKPOINT_MARKER).write_text("git\t1700000000\n")

    with mock.patch("tools.benchmark.massbank_downloader._download_via_git") as m_git, \
         mock.patch("tools.benchmark.massbank_downloader._download_via_zip") as m_zip:
        result = download_massbank(target_dir=tmp_path)

    m_git.assert_not_called()
    m_zip.assert_not_called()
    assert isinstance(result, DownloadResult)
    assert result.skipped is True
    assert result.used_method == "cached"
    assert result.downloaded_dir == clone
    assert result.total_records == 5
    assert set(result.contributor_dirs) == {"RIKEN", "BSU"}


def test_force_refresh_ignores_marker(tmp_path: Path) -> None:
    """``force_refresh=True`` runs git despite marker presence."""
    clone = _make_fake_clone(tmp_path, {"RIKEN": 1})
    (clone / CHECKPOINT_MARKER).write_text("git\t1700000000\n")

    def _stub_git(clone_dir: Path, *, force_refresh: bool) -> None:
        # Simulate a successful clone-after-rm.
        clone_dir.mkdir(parents=True, exist_ok=True)
        (clone_dir / "RIKEN").mkdir(exist_ok=True)
        (clone_dir / "RIKEN" / "RIKEN00001.txt").write_text("ACCESSION: T\n//\n")

    with mock.patch(
        "tools.benchmark.massbank_downloader._download_via_git", side_effect=_stub_git
    ) as m_git, mock.patch(
        "tools.benchmark.massbank_downloader._git_available", return_value=True
    ):
        result = download_massbank(target_dir=tmp_path, force_refresh=True)

    m_git.assert_called_once()
    assert result.skipped is False
    assert result.used_method == "git"


# ---------------------------------------------------------------------------
# Method selection
# ---------------------------------------------------------------------------


def test_zip_fallback_when_git_missing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """``use_git=True`` but ``git`` not on PATH → method is ``"zip"``."""

    def _stub_zip(parent: Path, clone_dir: Path, *, force_refresh: bool) -> None:
        clone_dir.mkdir(parents=True, exist_ok=True)
        (clone_dir / "RIKEN").mkdir()
        (clone_dir / "RIKEN" / "x.txt").write_text("ACCESSION: T\n//\n")

    with mock.patch(
        "tools.benchmark.massbank_downloader._git_available", return_value=False
    ), mock.patch(
        "tools.benchmark.massbank_downloader._download_via_zip", side_effect=_stub_zip
    ) as m_zip:
        result = download_massbank(target_dir=tmp_path)

    m_zip.assert_called_once()
    assert result.used_method == "zip"
    assert "falling back to HTTP zip" in caplog.text


def test_explicit_use_git_false_uses_zip(tmp_path: Path) -> None:
    """``use_git=False`` always picks zip even if git is available."""

    def _stub_zip(parent: Path, clone_dir: Path, *, force_refresh: bool) -> None:
        clone_dir.mkdir(parents=True, exist_ok=True)
        (clone_dir / "RIKEN").mkdir()
        (clone_dir / "RIKEN" / "x.txt").write_text("ACCESSION: T\n//\n")

    with mock.patch(
        "tools.benchmark.massbank_downloader._git_available", return_value=True
    ), mock.patch(
        "tools.benchmark.massbank_downloader._download_via_zip", side_effect=_stub_zip
    ) as m_zip:
        result = download_massbank(target_dir=tmp_path, use_git=False)

    m_zip.assert_called_once()
    assert result.used_method == "zip"


# ---------------------------------------------------------------------------
# Target dir resolution
# ---------------------------------------------------------------------------


def test_env_var_used_when_target_dir_none(tmp_path: Path) -> None:
    """``METAGENT_MASSBANK_DIR`` is honoured when ``target_dir`` is None."""
    target = tmp_path / "from-env"
    _make_fake_clone(target, {"RIKEN": 2})
    (target / CLONE_DIR_NAME / CHECKPOINT_MARKER).touch()

    with mock.patch.dict(os.environ, {"METAGENT_MASSBANK_DIR": str(target)}):
        result = download_massbank(target_dir=None)
    assert result.downloaded_dir == target / CLONE_DIR_NAME
    assert result.skipped is True


def test_explicit_target_dir_overrides_env(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit"
    _make_fake_clone(explicit, {"BSU": 1})
    (explicit / CLONE_DIR_NAME / CHECKPOINT_MARKER).touch()

    with mock.patch.dict(os.environ, {"METAGENT_MASSBANK_DIR": str(tmp_path / "env")}):
        result = download_massbank(target_dir=explicit)
    assert result.downloaded_dir == explicit / CLONE_DIR_NAME


# ---------------------------------------------------------------------------
# Contributor discovery
# ---------------------------------------------------------------------------


def test_discover_contributors_filters_by_request(tmp_path: Path) -> None:
    clone = _make_fake_clone(tmp_path, {"RIKEN": 3, "BSU": 2, "MSSJ": 1})
    all_ = _discover_contributors(clone, requested=None)
    assert set(all_) == {"RIKEN", "BSU", "MSSJ"}

    only_riken = _discover_contributors(clone, requested=["RIKEN"])
    assert set(only_riken) == {"RIKEN"}

    case_insensitive = _discover_contributors(clone, requested=["riken"])
    assert set(case_insensitive) == {"RIKEN"}


def test_discover_contributors_skips_dirs_without_txt(tmp_path: Path) -> None:
    """Dirs like ``docs/`` or ``.github/`` should be invisible."""
    clone = _make_fake_clone(tmp_path, {"RIKEN": 1})
    (clone / "docs").mkdir()  # no .txt
    (clone / "docs" / "README.md").write_text("# docs")
    (clone / ".github").mkdir()
    (clone / ".github" / "workflows").mkdir()
    discovered = _discover_contributors(clone, requested=None)
    assert set(discovered) == {"RIKEN"}


def test_discover_contributors_warns_on_missing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    clone = _make_fake_clone(tmp_path, {"RIKEN": 1})
    _discover_contributors(clone, requested=["RIKEN", "NOSUCH"])
    assert "NOSUCH" in caplog.text


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_clone_dir_exists_but_not_git_raises(tmp_path: Path) -> None:
    """Refuse to overwrite a non-git ``MassBank-data`` directory."""
    clone = tmp_path / CLONE_DIR_NAME
    clone.mkdir()
    (clone / "user_file.txt").write_text("user data")

    with mock.patch(
        "tools.benchmark.massbank_downloader._git_available", return_value=True
    ), pytest.raises(MassBankDownloadError, match="not a git clone"):
        download_massbank(target_dir=tmp_path)


def test_git_failure_raises(tmp_path: Path) -> None:
    """A non-zero git exit code surfaces as :class:`MassBankDownloadError`."""
    fake_completed = mock.Mock()
    fake_completed.returncode = 128
    fake_completed.stderr = "fatal: could not read Username for 'https://github.com'"
    with mock.patch(
        "tools.benchmark.massbank_downloader._git_available", return_value=True
    ), mock.patch(
        "tools.benchmark.massbank_downloader.subprocess.run",
        return_value=fake_completed,
    ), pytest.raises(MassBankDownloadError, match="git command failed"):
        download_massbank(target_dir=tmp_path)


def test_existing_git_clone_runs_pull(tmp_path: Path) -> None:
    """Existing ``.git`` dir and no checkpoint → run ``git pull`` (not clone)."""
    clone = _make_fake_clone(tmp_path, {"RIKEN": 1})
    # No checkpoint marker — must trigger a pull.
    pull_completed = mock.Mock(returncode=0, stderr="", stdout="Already up to date.\n")
    with mock.patch(
        "tools.benchmark.massbank_downloader._git_available", return_value=True
    ), mock.patch(
        "tools.benchmark.massbank_downloader.subprocess.run",
        return_value=pull_completed,
    ) as m_run:
        result = download_massbank(target_dir=tmp_path)

    # Must have been a `git pull`, not a `git clone`.
    cmd = m_run.call_args[0][0]
    assert "pull" in cmd
    assert "clone" not in cmd
    assert result.used_method == "git"
    assert result.skipped is False
    assert (clone / CHECKPOINT_MARKER).exists()


# ---------------------------------------------------------------------------
# Disk space warning
# ---------------------------------------------------------------------------


def test_low_disk_space_logs_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """When free space is below threshold, a warning is logged but not raised."""
    fake_usage = mock.Mock(total=10 * 1024 ** 3, used=9 * 1024 ** 3, free=1 * 1024 ** 3)

    def _stub_git(clone_dir: Path, *, force_refresh: bool) -> None:
        clone_dir.mkdir(parents=True, exist_ok=True)
        (clone_dir / "RIKEN").mkdir(exist_ok=True)
        (clone_dir / "RIKEN" / "x.txt").write_text("//\n")

    with mock.patch(
        "tools.benchmark.massbank_downloader._git_available", return_value=True
    ), mock.patch(
        "tools.benchmark.massbank_downloader.shutil.disk_usage", return_value=fake_usage
    ), mock.patch(
        "tools.benchmark.massbank_downloader._download_via_git", side_effect=_stub_git
    ):
        download_massbank(target_dir=tmp_path)

    assert "below" in caplog.text and "warn threshold" in caplog.text


# ---------------------------------------------------------------------------
# Integration test (network-touching, opt-in)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("METAGENT_RUN_INTEGRATION") != "1",
    reason="set METAGENT_RUN_INTEGRATION=1 to actually hit GitHub",
)
def test_real_git_clone(tmp_path: Path) -> None:
    """Actually clone MassBank-data — slow, network-bound."""
    result = download_massbank(target_dir=tmp_path)
    assert result.downloaded_dir.is_dir()
    assert result.total_records > 0
    assert "RIKEN" in result.contributor_dirs
