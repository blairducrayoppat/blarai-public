"""Recovery from a lost or damaged install record (#1690, S2).

The ORIGINAL hooks path (before the first install) is kept in a separate config key that survives
record loss; the installer never records its own folder as the "previous" path; every recovery message
names --update when the hooks are installed and the plain install only when they are not; --uninstall
restores the original exactly, or refuses rather than guess.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_hook_helpers import approved, commit, env, git, inst, installer, make_repo, mark_slow_except, quiet, stage, tiered  # noqa: E402

ORIG = "blarai.originalhookspath"
PREV = "blarai.previoushookspath"


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


def prev_hooks(tmp: Path) -> tuple[Path, Path]:
    """A previous hooks dir (with a space) whose post-commit appends to a marker file: the LA's dirty-log hook."""
    prev, marker = tmp / "prev hooks", tmp / "marker.txt"
    prev.mkdir(parents=True)
    (prev / "post-commit").write_text(f'#!/bin/sh\necho fired >> "{marker.as_posix()}"\n', newline="\n")
    return prev, marker


def with_prev(prev: Path):
    return lambda repo: git(repo, "config", "core.hooksPath", str(prev), check=True)


def cfg(repo, key, local=True) -> str | None:
    r = git(repo, "config", *(["--local"] if local else []), "--get", key)
    return r.stdout.strip() if r.returncode == 0 else None


def own_installer(repo, *flags):
    """The (possibly mutated) installer copy that lives in the temp repo."""
    return subprocess.run([sys.executable, str(repo / "scripts" / "install_git_hooks.py"), "--repo", str(repo), *flags],
                          capture_output=True, text=True, env=env(), timeout=120)


# ---- fast core: record lost + plain installer + uninstall, and the status wording ---------------------------
def test_record_lost_then_plain_installer_keeps_the_original_path_and_uninstall_restores_it(tmp):
    prev, marker = prev_hooks(tmp)
    repo = make_repo(tmp, "r", branch="feat/x", pre_install=with_prev(prev))
    assert cfg(repo, ORIG) == str(prev)  # written once, at the first install
    (repo / ".git" / "blarai-install.json").unlink()  # the record is lost
    s = installer(repo, "--status")
    assert s.returncode == 1 and "python scripts/install_git_hooks.py --update" in s.stdout
    assert "(first install)" not in s.stdout and "EVERY branch" in s.stdout
    r = approved(repo, "lost record", "--accept-drift", plain=True)  # someone runs the PLAIN installer
    assert r.returncode == 0 and "updated" in r.stdout
    assert cfg(repo, PREV) == str(prev) and cfg(repo, ORIG) == str(prev)  # NOT the installed folder
    assert (repo / ".git" / "blarai-previous-hooks").read_text().strip() == str(prev)
    assert installer(repo, "--check").returncode == 0
    stage(repo, "src/a.py")
    assert commit(repo).returncode == 0 and "fired" in marker.read_text()  # the dirty-log hook still fires
    u = installer(repo, "--uninstall")
    assert u.returncode == 0 and cfg(repo, "core.hooksPath") == str(prev)
    assert cfg(repo, ORIG) is None and cfg(repo, PREV) is None


def test_status_and_check_name_update_when_installed_and_the_plain_install_when_not(tmp):
    repo = make_repo(tmp, "r", install=False)
    s = installer(repo, "--status")
    assert s.returncode == 1 and "Fix: python scripts/install_git_hooks.py" in s.stdout and "--update" not in s.stdout
    c = installer(repo, "--check")
    assert c.returncode == 1 and "--update" not in c.stdout
    assert installer(repo).returncode == 0
    (inst(repo) / "hooks" / "rules_common.py").write_bytes(b"# damaged\n")
    s = installer(repo, "--status")
    assert s.returncode == 1 and "Fix: python scripts/install_git_hooks.py --update" in s.stdout
    c = installer(repo, "--check")
    assert c.returncode == 1 and "Recover: python scripts/install_git_hooks.py --update" in c.stdout


# ---- slow: the rest of S2 -------------------------------------------------------------------------------------
def test_update_rebuilds_a_corrupted_record_from_main_and_the_stored_original_with_a_logged_reason(tmp):
    prev, _ = prev_hooks(tmp)
    repo = make_repo(tmp, "r", pre_install=with_prev(prev))
    (repo / ".git" / "blarai-install.json").write_text("{not json", encoding="utf-8")
    u = approved(repo, "record corrupted", "--accept-drift")
    assert u.returncode == 0 and installer(repo, "--check").returncode == 0
    last = [json.loads(line) for line in (repo / ".git" / "blarai-install.log").read_text().splitlines()][-1]
    assert last["action"] == "update" and last["reason"] == "record corrupted"
    assert json.loads((repo / ".git" / "blarai-install.json").read_text())["previous_hooks_path"] == str(prev)
    # the damage is recorded in the log next to the reason
    assert last["record_damaged"] is True


def test_a_damaged_record_blocks_every_branch_until_update_runs(tmp):
    repo = make_repo(tmp, "r", branch="feat/x")
    rec = repo / ".git" / "blarai-install.json"
    rec.write_text(rec.read_text().replace('"base_interpreter_sha256": "', '"base_interpreter_sha256": "00'), encoding="utf-8")
    stage(repo, "src/a.py")
    r = commit(repo)  # even on a feature branch: fail closed, by design
    assert r.returncode != 0 and "--update" in r.stderr
    quiet(repo, "checkout", "-q", "-b", "other")
    assert commit(repo).returncode != 0
    assert approved(repo, "test").returncode == 0
    assert commit(repo).returncode == 0


def test_uninstall_refuses_rather_than_guess_when_the_original_path_is_unknown(tmp):
    repo = make_repo(tmp, "r")  # nothing was configured before the install: original is "@default"
    git(repo, "config", "--local", "--unset", ORIG, check=True)
    git(repo, "config", "--local", "--unset", PREV, check=True)
    before = cfg(repo, "core.hooksPath")
    u = installer(repo, "--uninstall")
    assert u.returncode == 1 and "refusing to uninstall" in u.stdout
    assert cfg(repo, "core.hooksPath") == before and inst(repo).exists()


def test_uninstall_restores_the_default_when_nothing_was_configured_before(tmp):
    repo = make_repo(tmp, "r")
    assert cfg(repo, ORIG) == "@default"
    (repo / ".git" / "blarai-install.json").unlink()
    assert approved(repo, "lost record", "--accept-drift", plain=True).returncode == 0  # the plain installer on a lost record
    assert cfg(repo, PREV) == "@default"
    u = installer(repo, "--uninstall")
    assert u.returncode == 0 and cfg(repo, "core.hooksPath") is None and cfg(repo, ORIG) is None


def test_the_original_key_is_never_overwritten_while_it_is_set(tmp):
    repo = make_repo(tmp, "r", install=False)
    git(repo, "config", "--local", ORIG, "kept/original", check=True)
    git(repo, "config", "core.hooksPath", "some/other/hooks", check=True)
    assert installer(repo).returncode == 0
    assert cfg(repo, ORIG) == "kept/original" and cfg(repo, PREV) == "some/other/hooks"


mark_slow_except(globals(), {
    "test_record_lost_then_plain_installer_keeps_the_original_path_and_uninstall_restores_it",
    "test_status_and_check_name_update_when_installed_and_the_plain_install_when_not",
})


# ---- mutants (slow) ----------------------------------------------------------------------------------------------
INSTALLER = "scripts/install_git_hooks.py"


def s_own_folder_as_previous(tmp, edits):  # record lost + plain installer must not record our own folder
    prev, _ = prev_hooks(tmp)
    repo = make_repo(tmp, "a", pre_install=with_prev(prev), edits=edits)
    (repo / ".git" / "blarai-install.json").unlink()
    approved(repo, "lost record", "--accept-drift", plain=True, run=own_installer)
    return cfg(repo, PREV) == str(prev)


def s_original_overwritten(tmp, edits):
    repo = make_repo(tmp, "b", install=False, edits=edits)
    git(repo, "config", "--local", ORIG, "kept/original", check=True)
    git(repo, "config", "core.hooksPath", "some/other/hooks", check=True)
    own_installer(repo)
    return cfg(repo, ORIG) == "kept/original"


def s_uninstall_guesses(tmp, edits):  # True = refused (correct)
    repo = make_repo(tmp, "c", edits=edits)
    git(repo, "config", "--local", "--unset", ORIG, check=True)
    git(repo, "config", "--local", "--unset", PREV, check=True)
    return own_installer(repo, "--uninstall").returncode == 1


def s_status_wording(tmp, edits):  # True = names --update when installed
    repo = make_repo(tmp, "d", edits=edits)
    (inst(repo) / "hooks" / "rules_common.py").write_bytes(b"# damaged\n")
    return "Fix: python scripts/install_git_hooks.py --update" in own_installer(repo, "--status").stdout


MUTANTS = {
    "own folder recorded as previous": (s_own_folder_as_previous, [(INSTALLER, '    return norm == hooks_path(repo) or norm.endswith(f"/{rc.INSTALL_DIR}/githooks")', "    return False")]),
    "original path overwritten": (s_original_overwritten, [(INSTALLER, "        if _original(top) is None:\n            _git(top, \"config\", \"--local\", ORIG_KEY, prev, check=True)  # written once", "        if True:\n            _git(top, \"config\", \"--local\", ORIG_KEY, prev, check=True)  # written once")]),
    "uninstall guesses": (s_uninstall_guesses, [(INSTALLER, "    if prev is None or _is_ours(prev, top):", "    if False:")]),
    "status recommends the plain installer": (s_status_wording, [(INSTALLER, '    if _is_ours(_effective(repo), repo):\n        return "python scripts/install_git_hooks.py --update"', '    if False:\n        return "python scripts/install_git_hooks.py --update"')]),
}


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_recovery_mutant_is_caught(name, tmp):
    scenario, edits = MUTANTS[name]
    assert scenario(tmp / "real", []) is True, f"{name}: the unmutated installer must behave"
    assert scenario(tmp / "mut", edits) is False, f"mutant survived: {name}"
