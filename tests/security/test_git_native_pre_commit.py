"""Locks for the git-native pre-commit guard, its installer and the text guard's hook-disable
rules (#1690).

The hook runs INSIDE git, so these tests drive REAL git in temp repos with core.hooksPath set
by the real installer. Where git itself cannot stop something (`--no-verify`, a missing
core.hooksPath) the test says so and asserts what does: the text guard, or nothing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_hook_helpers import (  # noqa: E402
    GUARD, ROOT, commit, env, git, head, inst, installer, make_repo, mark_slow_except, record, stage, tiered,
)

import hashlib  # noqa: E402


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


# ---- the hook, through real git ---------------------------------------------------------------
def test_code_commit_on_main_is_rejected(tmp):
    repo = make_repo(tmp, "r")
    before = head(repo)
    stage(repo, "src/a.py", "docs/reviews/r.md")
    r = commit(repo)
    assert r.returncode != 0
    assert "BLOCKED" in r.stderr and "src/a.py" in r.stderr and "feature branch" in r.stderr
    assert "git merge --no-ff" in r.stderr and "fast-forward main" not in r.stderr
    assert head(repo) == before


def test_companion_only_commit_on_main_passes(tmp):
    repo = make_repo(tmp, "r")
    stage(repo, "docs/journal_fragments/a.md", "docs/reviews/r.md", "LESSONS.md", "PERFORMANCE_LOG.md",
          "docs/performance/run.json", "docs/research/fig.svg", "docs/research/p.png")
    r = commit(repo)
    assert r.returncode == 0, r.stderr


def test_companion_lookalikes_and_code_in_docs_are_rejected(tmp):
    repo = make_repo(tmp, "r")
    for rel in ("docs/reviews_evil/x.md", "CLAUDE.md", "docs/research/run.py", "docs/reviews/.gitattributes"):
        git(repo, "reset", "-q")
        stage(repo, rel)
        assert commit(repo).returncode != 0, rel


def _rc():
    sys.path.insert(0, str(ROOT / "scripts" / "hooks"))
    try:
        import rules_common
    finally:
        sys.path.pop(0)
    return rules_common


def _problem(path, status="A", newmode="100644", oldmode="000000", size=10, tracked=None):
    rc = _rc()
    sha = "a" * 40
    c = rc.Change(oldmode, newmode, "0" * 40, sha, status, path)
    return rc.change_problem(c, {sha: size}, lambda: tracked or {})


@pytest.mark.parametrize("path", [
    "docs/reviews_evil/x.md", "CLAUDE.md", "docs/ROADMAP.md.py", "scripts/x.py", "tests/t.py", "services/a.py",
    "docs/research/run.py", "docs/research/run.sh", "docs/research/x.ps1", "docs/research/x.html",
    "docs/research/x.xml", "docs/research/x.log", "docs/research/x", "docs/research/x.PY",
    "docs/reviews/.gitattributes", "docs/reviews/.gitmodules", "docs/reviews/.gitignore", "docs/reviews/.hidden.md",
    "docs/research/a\\b.md", "docs/research/../../services/evil.md", "docs/research/./x.md", "docs/research//x.md",
    "docs/research./x.md", "docs/research/x.md.", "docs/research/x.md ", "docs/research/s:stream.md",
    "docs/research/e\u0301.md", "Docs/research/x.md", ".claude/settings.json", "scripts/githooks/pre-commit",
])
def test_unit_non_companion_paths_are_refused(path):
    assert _problem(path) is not None, path


@pytest.mark.parametrize("path", [
    "docs/journal_fragments/a.md", "docs/ledger/x.json", "docs/performance/run.jsonl", "docs/research/t.csv",
    "docs/research/cfg.yaml", "docs/research/cfg.yml", "docs/research/fig.svg", "docs/research/p.png",
    "docs/research/p.jpg", "docs/research/n.txt", "LESSONS.md", "PERFORMANCE_LOG.md", "docs/archive/v/old.md",
    "docs/research/\u00e9.md",
])
def test_unit_companion_paths_are_accepted(path):
    assert _problem(path) is None, (path, _problem(path))


def test_unit_modes_sizes_and_duplicates():
    assert "symlink" in _problem("docs/research/l.md", newmode="120000")
    assert "gitlink" in _problem("docs/research/s.md", newmode="160000")
    assert "executable" in _problem("docs/research/x.md", newmode="100755")
    assert "mode change" in _problem("docs/research/x.md", status="M", oldmode="100755", newmode="100644")
    assert "larger" in _problem("docs/research/big.json", size=2 * 1024 * 1024 + 1)
    assert _problem("docs/research/ok.json", size=2 * 1024 * 1024) is None
    assert "variant" in _problem("docs/research/notes.md", tracked={"docs/research/notes.md": {"docs/research/Notes.md"}})
    assert _problem("docs/research/Notes.md", tracked={"docs/research/notes.md": {"docs/research/Notes.md"}}) is None
    assert _problem("docs/research/old.py", status="D") is None  # deleting an existing file is always fine
    assert _problem("docs/research/old.py", status="M", oldmode="100644") is not None  # modifying one is not


def test_symlink_gitlink_executable_and_mode_change_are_rejected(tmp):
    repo = make_repo(tmp, "r")
    # symlink (mode 120000), written straight into the index so the test works without symlink rights
    sha = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input="../../services/app.py",
                         capture_output=True, text=True, env=env()).stdout.strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{sha},docs/research/link.md", check=True)
    r = commit(repo)
    assert r.returncode != 0 and "symlink" in r.stderr
    git(repo, "reset", "-q")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head(repo)},docs/research/sub", check=True)
    r = commit(repo)
    assert r.returncode != 0 and "gitlink" in r.stderr
    git(repo, "reset", "-q")
    (repo / "docs" / "research").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "research" / "tool.md").write_text("x")
    git(repo, "add", "docs/research/tool.md", check=True)
    git(repo, "update-index", "--chmod=+x", "docs/research/tool.md", check=True)
    r = commit(repo)
    assert r.returncode != 0 and "executable" in r.stderr


def test_oversize_and_path_tricks_are_rejected(tmp):
    repo = make_repo(tmp, "r")
    big = repo / "docs" / "research" / "big.json"
    big.parent.mkdir(parents=True)
    big.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    git(repo, "add", "docs/research/big.json", check=True)
    r = commit(repo)
    assert r.returncode != 0 and "larger" in r.stderr
    git(repo, "reset", "-q")
    for bad in ("docs/research/a\\b.md", "docs/research/../../services/evil.md"):
        sha = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input="x",
                             capture_output=True, text=True, env=env()).stdout.strip()
        git(repo, "reset", "-q")
        up = git(repo, "update-index", "--add", "--cacheinfo", f"100644,{sha},{bad}")
        if up.returncode != 0:
            continue  # git itself refused the path
        assert commit(repo).returncode != 0, bad


def test_case_variant_of_an_existing_tracked_path_is_rejected(tmp):
    repo = make_repo(tmp, "r", branch="feat/x")
    stage(repo, "docs/research/Notes.md")
    assert commit(repo).returncode == 0
    git(repo, "checkout", "-q", "main", check=True)
    git(repo, "merge", "--no-ff", "-q", "-m", "m", "feat/x", check=True)
    sha = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input="y", capture_output=True,
                         text=True, env=env()).stdout.strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"100644,{sha},docs/research/notes.md", check=True)
    r = commit(repo)
    assert r.returncode != 0 and "variant" in r.stderr


def test_existing_py_in_allowlisted_dir_can_be_deleted_but_not_modified(tmp):
    def seed(repo):
        (repo / "docs" / "reviews").mkdir(parents=True)
        (repo / "docs" / "reviews" / "old.py").write_text("print(1)\n")
        git(repo, "add", "docs/reviews/old.py", check=True)
        git(repo, "commit", "-q", "-m", "seed", check=True)

    repo = make_repo(tmp, "r", pre_install=seed)
    (repo / "docs" / "reviews" / "old.py").write_text("print(2)\n")
    git(repo, "add", "docs/reviews/old.py", check=True)
    assert commit(repo).returncode != 0  # modified .py refused on main
    git(repo, "reset", "-q")
    (repo / "docs" / "reviews" / "old.py").write_text("print(1)\n")
    git(repo, "rm", "-q", "docs/reviews/old.py", check=True)
    assert commit(repo).returncode == 0, "deleting an existing file in an allowlisted dir must work"


def test_deletion_outside_the_allowlist_is_rejected(tmp):
    repo = make_repo(tmp, "r")
    git(repo, "rm", "-q", "f.txt", check=True)
    r = commit(repo)
    assert r.returncode != 0 and "f.txt" in r.stderr


def test_commit_on_feature_branch_passes(tmp):
    repo = make_repo(tmp, "r", branch="feat/x")
    stage(repo, "src/a.py", "scripts/b.py")
    assert commit(repo).returncode == 0


def test_master_is_protected_too(tmp):
    repo = make_repo(tmp, "r", trunk="master", branch="master")
    stage(repo, "src/a.py")
    assert commit(repo).returncode != 0


def test_clean_merge_no_ff_into_main_passes(tmp):
    repo = make_repo(tmp, "r", branch="feat/x")
    stage(repo, "src/a.py")
    assert commit(repo).returncode == 0
    git(repo, "checkout", "-q", "main", check=True)
    r = git(repo, "merge", "--no-ff", "-q", "-m", "Merge feat/x", "feat/x")
    assert r.returncode == 0, r.stderr
    assert len(git(repo, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()) == 3  # two parents


def test_squash_merge_then_commit_of_code_on_main_is_rejected(tmp):
    repo = make_repo(tmp, "r", branch="feat/x")
    stage(repo, "src/a.py")
    assert commit(repo).returncode == 0
    git(repo, "checkout", "-q", "main", check=True)
    assert git(repo, "merge", "--squash", "feat/x").returncode == 0
    r = commit(repo)
    assert r.returncode != 0 and "src/a.py" in r.stderr


def test_forged_merge_head_and_mode_do_not_help(tmp):
    repo = make_repo(tmp, "r")
    (repo / ".git" / "MERGE_HEAD").write_text(head(repo) + "\n")
    (repo / ".git" / "MERGE_MODE").write_text("no-ff\n")
    stage(repo, "src/a.py")
    r = commit(repo)
    assert r.returncode != 0 and "src/a.py" in r.stderr


def test_detached_head_is_rejected(tmp):
    repo = make_repo(tmp, "r", branch="detached")
    stage(repo, "docs/reviews/r.md")  # even a companion file: the branch cannot be determined
    r = commit(repo)
    assert r.returncode != 0 and "detached" in r.stderr


def test_empty_and_allow_empty_commits_on_main_are_rejected(tmp):
    repo = make_repo(tmp, "r")
    r = commit(repo, "--allow-empty")
    assert r.returncode != 0 and "empty commit" in r.stderr
    stage(repo, "docs/reviews/r.md")
    assert commit(repo, "--allow-empty").returncode == 0  # a staged companion is present: not an empty commit
    assert commit(repo, "--allow-empty").returncode != 0


def test_an_installed_repository_is_protected_whatever_its_files_say(tmp):
    # Scope is the identity recorded at install, not CLAUDE.md: a repo without the marker file is guarded too.
    repo = make_repo(tmp, "r", blarai=False)
    stage(repo, "src/a.py")
    r = commit(repo)
    assert r.returncode != 0 and "src/a.py" in r.stderr


def test_unborn_main_is_fail_closed_and_unborn_feature_is_not(tmp):
    repo = make_repo(tmp, "u", branch="feat/x")
    stage(repo, "src/a.py")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/master", check=True)  # HEAD on a protected name with no commit yet
    r = commit(repo)
    assert r.returncode != 0 and "unborn" in r.stderr
    git(repo, "symbolic-ref", "HEAD", "refs/heads/fresh", check=True)
    assert commit(repo).returncode == 0  # an unborn feature branch's first commit is fine


def test_commit_with_paths_is_judged_on_what_will_be_committed(tmp):
    repo = make_repo(tmp, "r")
    (repo / "f.txt").write_text("changed")  # tracked, modified, NOT staged
    r = commit(repo, "f.txt")  # git commit <path> commits it: the hook sees it in the temp index
    assert r.returncode != 0 and "f.txt" in r.stderr


def test_commit_dash_a_is_judged_on_what_will_be_committed(tmp):
    repo = make_repo(tmp, "r")
    (repo / "f.txt").write_text("changed")
    r = commit(repo, "-a")
    assert r.returncode != 0 and "f.txt" in r.stderr


# ---- Q1: scope and the guard's own files come from HEAD, not the working tree ----------------------
def test_scope_comes_from_head_not_the_working_tree(tmp):
    repo = make_repo(tmp, "r")
    git(repo, "rm", "-q", "CLAUDE.md", check=True)  # (a) staged removal + code in one commit
    stage(repo, "src/a.py")
    assert commit(repo).returncode != 0
    git(repo, "reset", "-q", "--soft", "HEAD")
    git(repo, "reset", "-q")
    (repo / "CLAUDE.md").write_text("")  # (b) emptied in the working tree, unstaged
    stage(repo, "src/a.py")
    r = commit(repo)
    assert r.returncode != 0 and "src/a.py" in r.stderr


@pytest.mark.parametrize("rel,patch", tiered([
    ("hooks/rules_common.py", lambda s: s.replace('"docs/research/",', '"docs/research/", "services/",', 1)),
    ("githooks/reference-transaction", lambda s: s + "\n# tampered\n"),
    ("githooks/post-commit", lambda s: s + "\n# tampered\n"),
    ("hooks/git_native_pre_commit.py", lambda s: s.replace("def check()", "def check_orig()", 1) + "\ndef check():\n    return 0, '', ''\n"),
    ("githooks/_lib.sh", lambda s: s + "\n# tampered\n"),
], {0}))
def test_modified_guard_files_refuse_a_commit_on_main(tmp, rel, patch):
    repo = make_repo(tmp, "r")
    p = inst(repo) / rel
    p.write_text(patch(p.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    stage(repo, "docs/reviews/r.md")  # a perfectly good companion commit
    r = commit(repo)
    assert r.returncode != 0
    assert "differ" in r.stderr or "missing" in r.stderr or "BLOCKED" in r.stderr, r.stderr


def test_tampered_pre_commit_shim_is_a_documented_limit(tmp):
    # The shim is the first code git runs, so it cannot verify itself: an unstaged edit that
    # makes it `exit 0` switches the pre-commit layer off. The reference-transaction hook (a
    # different file) still judges the update of main, and the text guard blocks shell edits.
    repo = make_repo(tmp, "r")
    (inst(repo) / "githooks" / "pre-commit").write_text("#!/bin/sh\nexit 0\n", newline="\n")
    stage(repo, "src/a.py")
    r = commit(repo)  # pre-commit is off, but the update of main is refused while any hook file differs
    assert r.returncode != 0 and "reference-transaction" in r.stderr and "differ" in r.stderr
    # Documented limit: edit BOTH shims to `exit 0` and nothing in git stops the commit.
    (inst(repo) / "githooks" / "reference-transaction").write_text("#!/bin/sh\nexit 0\n", newline="\n")
    assert commit(repo).returncode == 0


def test_missing_or_extra_guard_files_refuse_a_commit_on_main(tmp):
    repo = make_repo(tmp, "r")
    (inst(repo) / "hooks" / "reference_transaction.py").unlink()
    stage(repo, "docs/reviews/r.md")
    r = commit(repo)
    assert r.returncode != 0 and "BLOCKED" in r.stderr
    repo2 = make_repo(tmp, "r2")
    (inst(repo2) / "githooks" / "post-index-change").write_text("#!/bin/sh\nexit 0\n")
    stage(repo2, "docs/reviews/r.md")
    r = commit(repo2)
    assert r.returncode != 0 and "BLOCKED" in r.stderr


def test_deleting_or_switching_the_working_tree_hook_folder_changes_nothing(tmp):
    # The hooks run from <git-common-dir>/blarai-hooks, not from any checkout: a branch without
    # scripts/githooks, or a deleted folder, leaves the protection exactly as it was (the old design's R3).
    repo = make_repo(tmp, "r")
    import shutil
    shutil.rmtree(repo / "scripts" / "githooks")
    shutil.rmtree(repo / "scripts" / "hooks")
    stage(repo, "src/a.py")
    r = commit(repo)
    assert r.returncode != 0 and "src/a.py" in r.stderr
    assert installer(repo, "--check").returncode == 0


def test_guard_edits_are_allowed_on_a_feature_branch(tmp):
    repo = make_repo(tmp, "r", branch="feat/x")
    p = repo / "scripts" / "hooks" / "rules_common.py"
    p.write_text(p.read_text(encoding="utf-8") + "\n# edited on a branch\n", encoding="utf-8", newline="\n")
    git(repo, "add", "scripts/hooks/rules_common.py", check=True)
    assert commit(repo).returncode == 0


# ---- what git cannot stop, and what does ---------------------------------------------------------
def guard(cmd, cwd, env_extra=None):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)})
    r = subprocess.run([sys.executable, str(GUARD)], input=payload, capture_output=True, text=True,
                       env=env(env_extra), timeout=90)
    return r.returncode, r.stderr


def test_no_verify_defeats_the_hook_and_the_text_guard_blocks_the_command(tmp):
    repo = make_repo(tmp, "r")
    stage(repo, "src/b.py")
    # Documented limit: git cannot stop --no-verify for pre-commit (the reference-transaction
    # hook still judges the update of main, so the commit itself is aborted there).
    r = commit(repo, "--no-verify")
    assert r.returncode != 0 and "reference-transaction" in r.stderr
    for cmd in ("git commit --no-verify -m x", "git commit -n -m x", "git commit -nm x", "git commit -m x -n",
                "git commit --no-ver -m x", "git commit -sn -m x", "git merge --no-verify feat/x",
                "git -c core.hooksPath=/dev/null commit -m x", "git -ccore.hookspath=x status",
                "git config core.hooksPath /dev/null", "git config --local --unset core.hooksPath",
                "git config --unset core.hookspath", "git --config-env=core.hooksPath=H commit -m x",
                "git config blarai.previoushookspath /x", "git config --unset blarai.previoushookspath",
                "python scripts/install_git_hooks.py --uninstall", "python3 scripts/install_git_hooks.py --un",
                "py ./scripts/install_git_hooks.py --uninstall",
                "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=x git commit -m x"):
        code, err = guard(cmd, repo)
        assert code == 2, (cmd, err)


def test_text_guard_still_allows_ordinary_commits_and_hook_install(tmp):
    repo = make_repo(tmp, "r", branch="feat/x")
    for cmd in ("git commit -m x", "git commit -m 'about --no-verify and -n'", "git config user.name t",
                "git config --get core.hooksPath", "git commit --verify -m x", "git status -n",
                "python scripts/install_git_hooks.py", "python scripts/install_git_hooks.py --check",
                "git log -n 5", "echo python scripts/install_git_hooks.py --uninstall"):
        code, err = guard(cmd, repo)
        assert code == 0 or "--get" in cmd, (cmd, err)


def test_hooks_path_unset_means_the_control_is_off(tmp):
    repo = make_repo(tmp, "r", install=False)  # documented: no core.hooksPath => no enforcement
    stage(repo, "src/a.py")
    assert commit(repo).returncode == 0
    repo2 = make_repo(tmp, "r2")
    assert installer(repo2, "--uninstall").returncode == 0
    stage(repo2, "src/a.py")
    assert commit(repo2).returncode == 0
    repo3 = make_repo(tmp, "r3")
    git(repo3, "config", "core.hooksPath", "elsewhere", check=True)  # pointed elsewhere: also off
    stage(repo3, "src/a.py")
    assert commit(repo3).returncode == 0


# ---- override ----------------------------------------------------------------------------------------
def test_override_allows_and_logs(tmp):
    repo = make_repo(tmp, "r")
    log = tmp / "ov.log"
    stage(repo, "src/a.py")
    r = commit(repo, env_extra={"BLARAI_GIT_RULES_OVERRIDE": "LA approved hotfix", "BLARAI_GIT_RULES_OVERRIDE_LOG": str(log)})
    assert r.returncode == 0, r.stderr
    rules = [json.loads(line)["rule"] for line in log.read_text().splitlines()]
    assert rules[0] == "commit-on-main" and all(json.loads(line)["reason"] == "LA approved hotfix"
                                                for line in log.read_text().splitlines())


def test_override_blank_or_unwritable_log_stays_blocked(tmp):
    repo = make_repo(tmp, "r")
    stage(repo, "src/a.py")
    assert commit(repo, env_extra={"BLARAI_GIT_RULES_OVERRIDE": "  ", "BLARAI_GIT_RULES_OVERRIDE_LOG": str(tmp / "x.log")}).returncode != 0
    bad = tmp / "afile"
    bad.write_text("x")
    r = commit(repo, env_extra={"BLARAI_GIT_RULES_OVERRIDE": "r", "BLARAI_GIT_RULES_OVERRIDE_LOG": str(bad / "sub" / "l.log")})
    assert r.returncode != 0


def test_override_not_logged_when_nothing_to_override(tmp):
    repo = make_repo(tmp, "r", branch="feat/x")
    log = tmp / "none.log"
    stage(repo, "src/a.py")
    assert commit(repo, env_extra={"BLARAI_GIT_RULES_OVERRIDE": "r", "BLARAI_GIT_RULES_OVERRIDE_LOG": str(log)}).returncode == 0
    assert not log.exists()


# ---- fail closed -----------------------------------------------------------------------------------------
def test_broken_or_missing_hook_script_rejects_the_commit(tmp):
    repo = make_repo(tmp, "r", branch="feat/x")  # even on a feature branch: the guard cannot run
    stage(repo, "src/a.py")
    script = inst(repo) / "hooks" / "git_native_pre_commit.py"
    script.write_text("import nonexistent_module_xyz\n")
    assert commit(repo).returncode != 0
    script.unlink()
    r = commit(repo)
    assert r.returncode != 0 and "missing" in r.stderr
    script.write_text("raise SystemExit(7)\n")
    assert commit(repo).returncode != 0


def test_unreadable_repository_state_fails_closed(tmp):
    mutant = ("scripts/hooks/rules_common.py", '"--diff-filter=ACMRTD"]', '"--diff-filter=ZZZ"]')
    r2 = make_repo(tmp, "r2", edits=[mutant])
    stage(r2, "docs/reviews/r.md")
    assert commit(r2).returncode != 0  # git diff errors on a bad filter: the hook must refuse, not allow


# ---- one definition ----------------------------------------------------------------------------------------
def test_guard_and_hooks_share_one_definition():
    sys.path.insert(0, str(ROOT / "scripts" / "hooks"))
    try:
        import git_native_pre_commit as hook
        import git_rules_guard as g
        import reference_transaction as rt
        import rules_common as rc
    finally:
        sys.path.pop(0)
    assert g.COMPANION_ALLOWLIST is rc.COMPANION_ALLOWLIST and hook.rc is rc and rt.rc is rc
    assert g.PROTECTED_BRANCHES is rc.PROTECTED_BRANCHES
    src = GUARD.read_text(encoding="utf-8")
    assert "COMPANION_ALLOWLIST = (" not in src and "frozenset({" not in src


# ---- installer ---------------------------------------------------------------------------------------------
def test_installer_is_idempotent_and_check_works(tmp):
    repo = make_repo(tmp, "r", install=False)
    assert installer(repo, "--check").returncode == 1
    r1 = installer(repo)
    assert r1.returncode == 0 and "installed" in r1.stdout
    cfg1 = (repo / ".git" / "config").read_text()
    r2 = installer(repo)
    assert r2.returncode == 0 and "already installed" in r2.stdout
    assert (repo / ".git" / "config").read_text() == cfg1
    assert git(repo, "config", "--local", "--get", "core.hooksPath").stdout.strip() == (inst(repo) / "githooks").resolve().as_posix()
    assert installer(repo, "--check").returncode == 0
    assert installer(repo, "--uninstall").returncode == 0
    assert git(repo, "config", "--local", "--get", "core.hooksPath").returncode != 0
    assert installer(repo, "--check").returncode == 1
    assert installer(repo, "--uninstall").returncode == 0  # idempotent too


def test_installer_refuses_when_main_lacks_the_hook_files(tmp):
    repo = make_repo(tmp, "r", install=False)
    git(repo, "rm", "-rq", "scripts/githooks", check=True)
    git(repo, "commit", "-q", "-m", "drop hooks", check=True)
    r = installer(repo)
    assert r.returncode != 0 and "lacks" in (r.stdout + r.stderr)
    assert git(repo, "config", "--local", "--get", "core.hooksPath").returncode != 0
    assert installer(repo, "--check").returncode != 0


def test_installer_setting_covers_linked_worktrees(tmp):
    repo = make_repo(tmp, "r", branch="feat/x")  # primary on a feature branch; main exists
    wt = tmp / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "main", check=True)  # a linked worktree ON main
    assert git(wt, "config", "--get", "core.hooksPath").stdout.strip() == (inst(repo) / "githooks").resolve().as_posix()
    stage(wt, "src/a.py")
    assert commit(wt).returncode != 0
    git(wt, "reset", "-q")
    stage(wt, "docs/reviews/z.md")
    assert commit(wt).returncode == 0


# ---- toggles and mutants: the probes must be able to fail ---------------------------------------------------
H = "scripts/hooks/git_native_pre_commit.py"
RC = "scripts/hooks/rules_common.py"
SCENARIOS = [  # (name, repo kwargs, files to stage, commit args, expect_ok)
    ("code on main", {}, ["src/a.py"], [], False),
    ("companion on main", {}, ["docs/reviews/r.md"], [], True),
    ("allow-empty on main", {}, [], ["--allow-empty"], False),
    ("code on detached head", {"branch": "detached"}, ["src/a.py"], [], False),
    ("code on feature", {"branch": "feat/x"}, ["src/a.py"], [], True),
    ("py under docs on main", {}, ["docs/research/x.py"], [], False),
    ("tampered rules_common on main", {"tamper": ("hooks/rules_common.py", "append")}, ["docs/reviews/r.md"], [], False),
    ("no-op pre-commit python on main", {"tamper": ("hooks/git_native_pre_commit.py", "noop")}, ["src/a.py"], [], False),
]


# A replaced guard that knows the protocol: it exits 0 AND prints the affirmative token for its own bytes.
TOKEN_NOOP = (
    "import hashlib, os, sys" + chr(10)
    + "sys.stdout.write('BLARAI-GUARD-OK ' + hashlib.sha256(open(__file__, 'rb').read()).hexdigest() + chr(10))" + chr(10)
    + "sys.stdout.flush()" + chr(10) + "os._exit(0)" + chr(10))


def run_scenarios(tmp: Path, tag: str, edits=(), only=None):
    out = {}
    for i, (name, kw, files, args, _) in enumerate(SCENARIOS):
        if only and name not in only:
            continue
        kw = dict(kw)
        tamper = kw.pop("tamper", False)
        repo = make_repo(tmp, f"{tag}{i}", edits=edits, **kw)
        if tamper:
            rel, how = tamper
            p = inst(repo) / rel
            body = TOKEN_NOOP if how == "noop" else p.read_text(encoding="utf-8") + "\n# t\n"
            p.write_text(body, encoding="utf-8", newline="\n")
        if files:
            stage(repo, *files)
        out[name] = commit(repo, *args).returncode == 0
    return out


def test_scenarios_pass_on_the_real_hook(tmp):
    assert run_scenarios(tmp, "real") == {name: e for name, _, _, _, e in SCENARIOS}


MUTANTS = {  # name: (file, old, new, scenarios that must change)
    "empty commit allowed": (H, "    if not changes:\n", "    if False:\n", ["allow-empty on main"]),
    "problems ignored": (H, "    if problems:\n", "    if False:\n", ["code on main"]),
    "main not protected": (RC, 'frozenset({"main", "master"})', 'frozenset({"trunk"})', ["code on main"]),
    "detached head allowed": (H, "    if not branch:\n", "    if False:\n", ["code on detached head"]),
    "extensions not checked": (RC, "    if ext not in ALLOWED_EXTENSIONS:", "    if False:", ["py under docs on main"]),
    "shim verification skipped": ("scripts/githooks/pre-commit", "main|master) verify_install || exit 1 ;;", "main|master) : ;;", ["no-op pre-commit python on main"]),
    "companions rejected": (RC, '    return any(p == e or (e.endswith("/") and p.startswith(e)) for e in COMPANION_ALLOWLIST)', "    return False", ["companion on main"]),
}


# The reference-transaction hook independently refuses the same commits (defence in depth), which
# would hide a weakened pre-commit. These runs neutralise it (in the initial commit, so the
# integrity check still passes) to judge pre-commit ALONE.
NO_REF_TX = ("scripts/githooks/reference-transaction", "# Git-native reference-transaction shim:", "exit 0\n# Git-native reference-transaction shim:")


@pytest.mark.slow
def test_scenarios_pass_with_pre_commit_alone(tmp):
    got = run_scenarios(tmp, "alone", edits=[NO_REF_TX])
    assert got == {name: e for name, _, _, _, e in SCENARIOS}


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_mutant_is_caught(name, tmp):
    rel, old, new, targets = MUTANTS[name]
    expected = {n: e for n, _, _, _, e in SCENARIOS if n in targets}
    got = run_scenarios(tmp, "m", edits=[NO_REF_TX, (rel, old, new)], only=targets)
    assert got != expected, f"mutant survived: {name}"


mark_slow_except(globals(), {
    "test_code_commit_on_main_is_rejected", "test_companion_only_commit_on_main_passes",
    "test_unit_non_companion_paths_are_refused", "test_unit_companion_paths_are_accepted",
    "test_unit_modes_sizes_and_duplicates", "test_commit_on_feature_branch_passes",
    "test_modified_guard_files_refuse_a_commit_on_main",
    "test_deleting_or_switching_the_working_tree_hook_folder_changes_nothing",
    "test_no_verify_defeats_the_hook_and_the_text_guard_blocks_the_command",
    "test_hooks_path_unset_means_the_control_is_off", "test_override_allows_and_logs",
    "test_guard_and_hooks_share_one_definition", "test_installer_is_idempotent_and_check_works",
})
