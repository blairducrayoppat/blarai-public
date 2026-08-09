"""
Tests for scripts/check_public_mirror_sync.py — the public-mirror bookkeeping-
drift check (Vikunja #1104: the recurring class where a hand-patch to the
public remote outruns the local bookkeeping ref and the next scheduled
publish fails non-fast-forward, silently).

Driven through REAL throwaway git repos built in tmp_path (a 'local' repo with
a 'public' remote pointing at a second 'remote' repo) rather than mocked git
calls - the seams doctrine: a mocked git response cannot tell us the actual
rev-parse/rev-list/fetch invocations are correct.

scripts/ is not on the standing gate path (shared/ services/ launcher/
tests/integration/ tests/security/); run this file explicitly:
    python -m pytest scripts/tests/test_check_public_mirror_sync.py -q
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

# Import the script directly by file path (scripts/ is not a package).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "check_public_mirror_sync.py"
_spec = importlib.util.spec_from_file_location("check_public_mirror_sync", _SCRIPT)
assert _spec and _spec.loader
cpms = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cpms
_spec.loader.exec_module(cpms)

_BOOKKEEPING_REF = "refs/public-snapshots/main"


# ---------------------------------------------------------------------------
# Throwaway repo helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "main"], path)
    _git(["config", "user.email", "test@example.com"], path)
    _git(["config", "user.name", "Test"], path)


def _commit(path: Path, message: str) -> str:
    fname = f"{message.replace(' ', '_')}.txt"
    (path / fname).write_text(message, encoding="utf-8")
    _git(["add", fname], path)
    _git(["commit", "-q", "-m", message], path)
    return _git(["rev-parse", "HEAD"], path)


def _make_local_and_remote(tmp_path: Path) -> tuple[Path, Path, str]:
    """Build 'remote' (one seed commit) and 'local' (a 'public' remote pointing
    at it, fetched, main checked out at the seed). Returns (local, remote, seed_sha)."""
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    _init_repo(remote)
    seed_sha = _commit(remote, "seed")
    _init_repo(local)
    _git(["remote", "add", "public", str(remote)], local)
    _git(["fetch", "-q", "public"], local)
    _git(["reset", "-q", "--hard", "public/main"], local)
    return local, remote, seed_sha


def _set_bookkeeping_ref(local: Path, sha: str) -> None:
    _git(["update-ref", _BOOKKEEPING_REF, sha], local)


# ---------------------------------------------------------------------------
# check_sync — the core comparison
# ---------------------------------------------------------------------------


def test_in_sync_when_bookkeeping_matches_remote_tip(tmp_path: Path) -> None:
    local, _remote, seed_sha = _make_local_and_remote(tmp_path)
    _set_bookkeeping_ref(local, seed_sha)

    in_sync, report = cpms.check_sync(local, "public", "main", _BOOKKEEPING_REF, do_fetch=True)

    assert in_sync is True
    assert seed_sha[:8] in report


def test_drift_behind_when_remote_advanced_without_the_ref(tmp_path: Path) -> None:
    local, remote, seed_sha = _make_local_and_remote(tmp_path)
    _set_bookkeeping_ref(local, seed_sha)
    # Simulate a hand-patch landing straight on the remote (#1104's actual class).
    new_tip = _commit(remote, "hand-patched readme fix")

    in_sync, report = cpms.check_sync(local, "public", "main", _BOOKKEEPING_REF, do_fetch=True)

    assert in_sync is False
    assert "DRIFT" in report
    assert "1 commit(s) behind" in report
    assert new_tip[:8] in report
    assert "#1104" in report  # points a reader at the desync history


def test_drift_ahead_when_bookkeeping_ref_outruns_the_remote(tmp_path: Path) -> None:
    local, _remote, seed_sha = _make_local_and_remote(tmp_path)
    # Simulate the 'push failure leaves the ref one commit ahead' signature.
    ahead_sha = _commit(local, "locally recorded but never actually pushed")
    _set_bookkeeping_ref(local, ahead_sha)

    in_sync, report = cpms.check_sync(local, "public", "main", _BOOKKEEPING_REF, do_fetch=True)

    assert in_sync is False
    assert "1 commit(s) ahead" in report
    assert seed_sha[:8] in report


def test_diverged_reports_both_directions(tmp_path: Path) -> None:
    local, remote, _seed_sha = _make_local_and_remote(tmp_path)
    # Remote gets a patch nobody's bookkeeping ref has ever seen...
    remote_only = _commit(remote, "remote-only patch")
    # ...while local independently recorded a DIFFERENT commit as published.
    local_only = _commit(local, "local-only commit never actually pushed")
    _set_bookkeeping_ref(local, local_only)

    in_sync, report = cpms.check_sync(local, "public", "main", _BOOKKEEPING_REF, do_fetch=True)

    assert in_sync is False
    assert "diverged" in report
    assert "1 behind" in report
    assert "1 ahead" in report
    assert remote_only[:8] in report


def test_unresolvable_remote_branch_is_reported_not_crashed(tmp_path: Path) -> None:
    local, _remote, seed_sha = _make_local_and_remote(tmp_path)
    _set_bookkeeping_ref(local, seed_sha)

    in_sync, report = cpms.check_sync(
        local, "public", "this-branch-does-not-exist", _BOOKKEEPING_REF, do_fetch=True
    )

    assert in_sync is False
    assert "does not resolve" in report
    assert "public/this-branch-does-not-exist" in report


def test_missing_bookkeeping_ref_is_reported_not_crashed(tmp_path: Path) -> None:
    local, _remote, _seed_sha = _make_local_and_remote(tmp_path)
    # No _set_bookkeeping_ref call - the ref was never created.

    in_sync, report = cpms.check_sync(local, "public", "main", _BOOKKEEPING_REF, do_fetch=True)

    assert in_sync is False
    assert "does not resolve" in report
    assert "not been published yet" in report or "missing" in report


def test_no_fetch_compares_against_cached_remote_tracking_ref(tmp_path: Path) -> None:
    local, remote, seed_sha = _make_local_and_remote(tmp_path)
    _set_bookkeeping_ref(local, seed_sha)
    # Remote moves AFTER our last fetch; with --no-fetch we must not see it.
    _commit(remote, "published after our last fetch")

    in_sync, report = cpms.check_sync(local, "public", "main", _BOOKKEEPING_REF, do_fetch=False)

    assert in_sync is True, report  # still in sync against the stale cached public/main
    assert seed_sha[:8] in report


def test_fetch_failure_is_reported_not_raised(tmp_path: Path) -> None:
    local, _remote, seed_sha = _make_local_and_remote(tmp_path)
    _set_bookkeeping_ref(local, seed_sha)

    in_sync, report = cpms.check_sync(local, "nonexistent-remote", "main", _BOOKKEEPING_REF, do_fetch=True)

    assert in_sync is False
    assert "could not fetch" in report


# ---------------------------------------------------------------------------
# main() — driven through the real CLI entry point, not check_sync directly
# ---------------------------------------------------------------------------


def test_main_exits_zero_when_in_sync(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    local, _remote, seed_sha = _make_local_and_remote(tmp_path)
    _set_bookkeeping_ref(local, seed_sha)

    code = cpms.main(["--repo", str(local), "--remote", "public"])

    assert code == 0
    assert "in sync" in capsys.readouterr().out


def test_main_exits_nonzero_on_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    local, remote, seed_sha = _make_local_and_remote(tmp_path)
    _set_bookkeeping_ref(local, seed_sha)
    _commit(remote, "hand-patched again")

    code = cpms.main(["--repo", str(local), "--remote", "public"])

    assert code == 1
    assert "DRIFT" in capsys.readouterr().out
