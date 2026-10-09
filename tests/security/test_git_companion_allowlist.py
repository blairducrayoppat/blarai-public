"""Lock: every entry of the companion allowlist (rules_common.COMPANION_ALLOWLIST) names something that exists on
main. A directory entry (trailing "/") needs at least one tracked path under it, a file entry the exact path.
A wrong entry is silent: the companion commit it was meant to allow is refused and nobody learns why.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_hook_helpers import ROOT, commit, git, make_repo, stage  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts" / "hooks"))
import rules_common as rc  # noqa: E402


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


def tracked_on_main() -> list[str]:
    r = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", "main"], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0 and r.stdout.strip(), f"cannot list main's tree: {r.stderr}"
    return r.stdout.splitlines()


def missing_entries(allowlist, paths) -> list[str]:
    """Entries that resolve to no tracked path (a file entry must match exactly, a directory entry by prefix)."""
    return [e for e in allowlist
            if not any(p == e or (e.endswith("/") and p.startswith(e)) for p in paths)]


def test_every_companion_allowlist_entry_exists_on_main():
    assert missing_entries(rc.COMPANION_ALLOWLIST, tracked_on_main()) == []


def test_the_lock_fails_when_an_entry_is_wrong():
    paths = tracked_on_main()
    assert missing_entries(rc.COMPANION_ALLOWLIST + ("docs/BUILD_JOURNAL.md",), paths) == ["docs/BUILD_JOURNAL.md"]
    assert missing_entries(rc.COMPANION_ALLOWLIST + ("docs/nonexistent_dir/",), paths) == ["docs/nonexistent_dir/"]


def test_a_journal_companion_commit_on_main_is_accepted(tmp):
    repo = make_repo(tmp, "r")
    stage(repo, "BUILD_JOURNAL.md")
    r = commit(repo)
    assert r.returncode == 0, r.stderr
    assert git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "2"


def test_the_journal_commit_is_refused_when_the_allowlist_carries_the_wrong_path(tmp):
    repo = make_repo(tmp, "r", edits=[("scripts/hooks/rules_common.py", '"BUILD_JOURNAL.md"', '"docs/BUILD_JOURNAL.md"')])
    stage(repo, "BUILD_JOURNAL.md")
    assert commit(repo).returncode != 0
