"""The installer must not silently disable an existing hooks directory (#1690, Q6).

The previous core.hooksPath is stored in blarai.previoushookspath and every shim chains to the
same-named hook there after our logic passes. Real git, real installer, fake previous hooks.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_hook_helpers import commit, git, inst, installer, make_repo, mark_slow_except, stage  # noqa: E402


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


def fwd(p: Path) -> str:
    return str(p).replace("\\", "/")


def write_hook(directory: Path, name: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text("#!/bin/sh\n" + body + "\n", newline="\n")


def prev_hooks(tmp: Path, **hooks: str) -> tuple[Path, Path]:
    """A previous hooks dir ('prev hooks': with a space) whose hooks append to a marker file."""
    prev = tmp / "prev hooks"
    marker = tmp / "marker.txt"
    for name, extra in hooks.items():
        write_hook(prev, name.replace("_", "-"), f'echo "{name} $@" >> "{fwd(marker)}"\n{extra}')
    return prev, marker


def with_prev(prev: Path):
    return lambda repo: git(repo, "config", "core.hooksPath", str(prev), check=True)


def marks(marker: Path) -> str:
    return marker.read_text() if marker.exists() else ""


def test_post_commit_of_the_previous_hooks_dir_keeps_running(tmp):
    prev, marker = prev_hooks(tmp, post_commit="")
    repo = make_repo(tmp, "r", branch="feat/x", pre_install=with_prev(prev))
    assert git(repo, "config", "--local", "blarai.previoushookspath").stdout.strip() == str(prev)
    assert git(repo, "config", "core.hooksPath").stdout.strip().endswith("/blarai-hooks/githooks")
    stage(repo, "src/a.py")
    assert commit(repo).returncode == 0
    assert "post_commit" in marks(marker)


def test_other_passthrough_hooks_chain(tmp):
    prev, marker = prev_hooks(tmp, post_checkout="", post_merge="", prepare_commit_msg="", commit_msg="")
    repo = make_repo(tmp, "r", branch="feat/x", pre_install=with_prev(prev))
    stage(repo, "src/a.py")
    assert commit(repo).returncode == 0
    git(repo, "checkout", "-q", "main", check=True)
    assert git(repo, "merge", "--no-ff", "-q", "-m", "m", "feat/x").returncode == 0
    seen = marks(marker)
    for h in ("prepare_commit_msg", "commit_msg", "post_checkout", "post_merge"):
        assert h in seen, (h, seen)


def test_previous_pre_commit_runs_after_ours_and_can_fail_the_commit(tmp):
    prev, marker = prev_hooks(tmp, pre_commit="exit 1")
    repo = make_repo(tmp, "r", branch="feat/x", pre_install=with_prev(prev))
    stage(repo, "src/a.py")
    assert commit(repo).returncode != 0 and "pre_commit" in marks(marker)


def test_our_failure_stops_the_chain(tmp):
    prev, marker = prev_hooks(tmp, pre_commit="")
    repo = make_repo(tmp, "r", pre_install=with_prev(prev))
    stage(repo, "src/a.py")  # code on main: ours rejects first
    assert commit(repo).returncode != 0
    assert marks(marker) == ""


def test_previous_reference_transaction_receives_state_and_stdin(tmp):
    prev, marker = prev_hooks(tmp, reference_transaction='cat >> "%s.stdin"' % fwd(tmp / "marker.txt"))
    repo = make_repo(tmp, "r", branch="feat/x", pre_install=with_prev(prev))
    stage(repo, "src/a.py")
    assert commit(repo).returncode == 0
    assert "reference_transaction prepared" in marks(marker)
    assert "refs/heads/feat/x" in (tmp / "marker.txt.stdin").read_text()


def test_previous_reference_transaction_runs_for_main_updates_too(tmp):
    prev, marker = prev_hooks(tmp, reference_transaction="")
    repo = make_repo(tmp, "r", pre_install=with_prev(prev))
    stage(repo, "docs/reviews/r.md")
    assert commit(repo).returncode == 0
    assert "reference_transaction prepared" in marks(marker)
    marker.unlink()
    stage(repo, "docs/reviews/r2.md")
    assert commit(repo, env_extra=None).returncode == 0


def test_default_git_hooks_dir_is_chained_when_nothing_was_configured(tmp):
    marker = tmp / "marker.txt"

    def seed(repo):
        write_hook(repo / ".git" / "hooks", "post-commit", f'echo default >> "{fwd(marker)}"')

    repo = make_repo(tmp, "r", branch="feat/x", pre_install=seed)
    assert git(repo, "config", "--local", "blarai.previoushookspath").stdout.strip() == "@default"
    stage(repo, "src/a.py")
    assert commit(repo).returncode == 0
    assert "default" in marks(marker)


def test_uninstall_restores_the_previous_value_and_the_old_hook_runs_directly(tmp):
    prev, marker = prev_hooks(tmp, post_commit="")
    repo = make_repo(tmp, "r", branch="feat/x", pre_install=with_prev(prev))
    assert installer(repo, "--uninstall").returncode == 0
    assert git(repo, "config", "core.hooksPath").stdout.strip() == str(prev)
    assert git(repo, "config", "--local", "--get", "blarai.previoushookspath").returncode != 0
    stage(repo, "src/a.py")
    assert commit(repo).returncode == 0
    assert "post_commit" in marks(marker)


def test_uninstall_with_nothing_configured_before_unsets(tmp):
    repo = make_repo(tmp, "r")
    assert installer(repo, "--uninstall").returncode == 0
    assert git(repo, "config", "--local", "--get", "core.hooksPath").returncode != 0
    assert git(repo, "config", "--local", "--get", "blarai.previoushookspath").returncode != 0


def test_install_is_idempotent_and_keeps_the_stored_previous_path(tmp):
    prev, _ = prev_hooks(tmp, post_commit="")
    repo = make_repo(tmp, "r", pre_install=with_prev(prev))
    r = installer(repo)
    assert r.returncode == 0 and "already installed" in r.stdout
    assert git(repo, "config", "--local", "--get", "blarai.previoushookspath").stdout.strip() == str(prev)


def test_check_reports_the_previous_path(tmp):
    prev, _ = prev_hooks(tmp, post_commit="")
    repo = make_repo(tmp, "r", pre_install=with_prev(prev))
    r = installer(repo, "--check")
    assert r.returncode == 0 and str(prev) in r.stdout


def test_install_message_names_the_chained_hooks_dir(tmp):
    prev, _ = prev_hooks(tmp, post_commit="")
    repo = make_repo(tmp, "r", install=False, pre_install=with_prev(prev))
    r = installer(repo)
    assert "chained" in r.stdout and str(prev) in r.stdout


def test_chain_never_loops_when_previous_equals_ours(tmp):
    repo = make_repo(tmp, "r", branch="feat/x")
    own = (inst(repo) / "githooks").resolve().as_posix()
    git(repo, "config", "--local", "blarai.previoushookspath", own, check=True)
    (repo / ".git" / "blarai-previous-hooks").write_text(own + "\n")
    stage(repo, "src/a.py")
    assert commit(repo).returncode == 0  # would recurse forever if the shim chained into itself


def test_missing_previous_dir_is_ignored(tmp):
    repo = make_repo(tmp, "r", branch="feat/x", pre_install=with_prev(tmp / "gone"))
    stage(repo, "src/a.py")
    assert commit(repo).returncode == 0


mark_slow_except(globals(), {
    "test_post_commit_of_the_previous_hooks_dir_keeps_running",
    "test_uninstall_restores_the_previous_value_and_the_old_hook_runs_directly",
})
