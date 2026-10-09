"""Install-step hardening (#1690, review round 3 R1-R4): the hooks run from a copy inside the git
common dir, recorded at install; scope is the recorded repository identity; --check/--status/--update;
the text guard refuses main-moving commands before git touches files; the proof script.

Real git, real installer, temp repos.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_hook_helpers import (  # noqa: E402
    approved,
    GUARD, ROOT, commit, env, git, head, inst, installer, make_repo, mark_slow_except, quiet, record, stage, tiered,
)

PROVE = ROOT / "scripts" / "prove_commit_protection.py"


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


def seeded(tmp: Path, name: str, **kw) -> Path:
    repo = make_repo(tmp, name, branch="feat/x", **kw)
    stage(repo, "services/app.py")
    quiet(repo, "commit", "-q", "-m", "feature work")
    quiet(repo, "checkout", "-q", "main")
    return repo


def out(repo, *args) -> str:
    return git(repo, *args).stdout.strip()


def guard(cmd, cwd, script=GUARD):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)})
    r = subprocess.run([sys.executable, str(script)], input=payload, capture_output=True, text=True, env=env(), timeout=90)
    return r.returncode, r.stderr


# ---- R3: no checkout, branch or edit can change what git runs -------------------------------------------
def test_installing_checkout_on_a_branch_without_the_hooks_does_not_turn_protection_off(tmp):
    repo = seeded(tmp, "r")
    quiet(repo, "checkout", "-q", "-b", "old", "main")
    quiet(repo, "rm", "-rq", "scripts")
    quiet(repo, "commit", "-q", "-m", "an old branch without the hooks")  # primary now has no scripts/ at all
    assert not (repo / "scripts" / "githooks").exists()
    wt = tmp / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "main", check=True)
    stage(wt, "src/a.py")
    r = commit(wt)
    assert r.returncode != 0 and "src/a.py" in r.stderr, "a code commit on main must still be refused"
    git(wt, "reset", "-q")
    assert installer(repo, "--check").returncode == 0
    assert git(wt, "merge", "--no-ff", "-q", "-m", "Merge feat/x", "feat/x").returncode == 0


def test_installing_checkout_on_a_guard_edit_branch_still_allows_the_sanctioned_merge(tmp):
    repo = seeded(tmp, "r")
    quiet(repo, "checkout", "-q", "-b", "guard-edit", "main")
    p = repo / "scripts" / "hooks" / "rules_common.py"
    p.write_text(p.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8", newline="\n")
    quiet(repo, "commit", "-qam", "edit the guard on a branch")
    wt = tmp / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "main", check=True)
    assert git(wt, "merge", "--no-ff", "-q", "-m", "Merge feat/x", "feat/x").returncode == 0
    stage(wt, "src/a.py")
    assert commit(wt).returncode != 0


def test_check_fails_when_installed_files_are_missing_or_differ(tmp):
    repo = make_repo(tmp, "r")
    assert installer(repo, "--check").returncode == 0
    f = inst(repo) / "hooks" / "reference_transaction.py"
    saved = f.read_bytes()
    f.unlink()
    r = installer(repo, "--check")
    assert r.returncode == 1 and "missing" in r.stdout
    f.write_bytes(saved + b"\n# changed\n")
    r = installer(repo, "--check")
    assert r.returncode == 1 and "differs from the recorded hash" in r.stdout
    f.write_bytes(saved)
    assert installer(repo, "--check").returncode == 0


def test_check_fails_when_the_hooks_directory_is_gone_or_hookspath_is_elsewhere(tmp):
    repo = make_repo(tmp, "r")
    shutil.rmtree(inst(repo))
    assert installer(repo, "--check").returncode == 1
    assert approved(repo, "test", "--accept-drift").returncode == 0  # re-copies from main
    assert installer(repo, "--check").returncode == 0
    git(repo, "config", "core.hooksPath", "elsewhere", check=True)
    r = installer(repo, "--check")
    assert r.returncode == 1 and "protection is OFF" in r.stdout


def test_update_follows_a_legitimate_hook_change_on_main_and_is_logged(tmp):
    repo = make_repo(tmp, "r")
    quiet(repo, "checkout", "-q", "-b", "hook-change")
    p = repo / "scripts" / "hooks" / "reference_transaction.py"
    p.write_text(p.read_text(encoding="utf-8") + "\n# a legitimate change\n", encoding="utf-8", newline="\n")
    quiet(repo, "commit", "-qam", "change a hook")
    quiet(repo, "checkout", "-q", "main")
    assert git(repo, "merge", "--no-ff", "-q", "-m", "Merge hook-change", "hook-change").returncode == 0
    r = installer(repo, "--check")
    assert r.returncode == 1 and "run --update" in r.stdout  # main moved ahead of the installed copy
    assert "older copy" in installer(repo, "--status").stdout  # still ON, and says it is stale
    u = approved(repo, "merged hook-change")
    assert u.returncode == 0 and "updated" in u.stdout
    assert installer(repo, "--check").returncode == 0
    log = [json.loads(line) for line in (repo / ".git" / "blarai-install.log").read_text().splitlines()]
    assert log[-1]["action"] == "update" and log[-1]["reason"] == "merged hook-change"
    assert installer(repo, "--update").stdout.startswith("already up to date")


def test_status_says_in_plain_language_whether_protection_is_on(tmp):
    repo = make_repo(tmp, "r")
    s = installer(repo, "--status")
    assert s.returncode == 0 and "Commit protection is ON" in s.stdout
    assert "Three things would turn it off" in s.stdout and s.stdout.count("\n  ") >= 3
    git(repo, "config", "--unset", "core.hooksPath", check=True)
    s = installer(repo, "--status")
    assert s.returncode == 1 and "OFF or BROKEN" in s.stdout and "core.hooksPath" in s.stdout


# ---- R1: scope is the recorded identity, not CLAUDE.md content --------------------------------------------
def test_merging_a_branch_that_deletes_claude_md_does_not_switch_the_guard_off(tmp):
    repo = make_repo(tmp, "r", branch="nocl")
    quiet(repo, "rm", "-q", "CLAUDE.md")
    stage(repo, "services/evil.py")
    quiet(repo, "commit", "-q", "-m", "delete CLAUDE.md, add code")
    quiet(repo, "checkout", "-q", "main")
    assert git(repo, "merge", "--no-ff", "-q", "-m", "Merge nocl", "nocl").returncode == 0  # the sanctioned route
    assert not (repo / "CLAUDE.md").exists()
    stage(repo, "services/app.py")
    r = commit(repo)
    assert r.returncode != 0 and "services/app.py" in r.stderr
    quiet(repo, "reset", "-q")
    stage(repo, "docs/reviews/ok.md")
    assert commit(repo).returncode == 0


# ---- R2: orphan HEAD, deletions and renames of main -------------------------------------------------------
def orphan_head(repo):
    quiet(repo, "checkout", "-q", "--orphan", "orp")
    quiet(repo, "rm", "--cached", "-rfq", ".", check=False)
    (repo / "x.txt").write_text("x")
    quiet(repo, "add", "x.txt")
    quiet(repo, "commit", "-q", "-m", "orphan root")


@pytest.mark.parametrize("how", tiered(["branch -D", "branch --delete --force", "update-ref -d", "update-ref --stdin",
                                        "branch -m orp main", "branch -M orp main"], {0, 3}))
def test_orphan_head_cannot_delete_or_replace_main(tmp, how):
    repo = seeded(tmp, "r")
    old = out(repo, "rev-parse", "main")
    orphan_head(repo)
    if how == "update-ref --stdin":
        r = subprocess.run(["git", "-C", str(repo), "update-ref", "--stdin"], input="delete refs/heads/main\n",
                           capture_output=True, text=True, env=env())
    else:
        r = git(repo, *{"branch -D": ["branch", "-D", "main"], "branch --delete --force": ["branch", "--delete", "--force", "main"],
                        "update-ref -d": ["update-ref", "-d", "refs/heads/main"],
                        "branch -m orp main": ["branch", "-m", "orp", "main"],
                        "branch -M orp main": ["branch", "-M", "orp", "main"]}[how])
    assert r.returncode != 0, how
    assert out(repo, "rev-parse", "main") == old


def test_a_forced_update_of_main_is_judged_from_its_real_value(tmp):
    repo = make_repo(tmp, "r", branch="feat/c")
    stage(repo, "docs/reviews/c.md")
    quiet(repo, "commit", "-q", "-m", "a companion-only commit")
    # `branch -f` reports an all-zero old value: judged from main's real tip it is a companion-only
    # fast-forward (allowed); a code commit is refused.
    assert git(repo, "branch", "-f", "main", "feat/c").returncode == 0
    stage(repo, "services/code.py")
    quiet(repo, "commit", "-q", "-m", "code")
    r = git(repo, "branch", "-f", "main", "feat/c")
    assert r.returncode != 0 and "services/code.py" in r.stderr


def test_a_repository_pointed_at_our_hooks_is_blocked_and_a_clone_is_untouched(tmp):
    repo = seeded(tmp, "r")
    other = tmp / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "main", check=True)
    (other / "f.txt").write_text("x")
    git(other, "add", "f.txt", check=True)
    quiet(other, "commit", "-q", "-m", "init")
    (other / "a.py").write_text("x")
    git(other, "add", "a.py", check=True)
    # the hooks live in ONE repository's git dir and only ever run for it: pointing another repository at
    # them is an inconsistency, so a commit on its main is blocked (never waved through as "not ours")
    r = git(other, "-c", f"core.hooksPath={(inst(repo) / 'githooks').as_posix()}", "commit", "-q", "-m", "code on main")
    assert r.returncode != 0 and "install record does not match this repository" in r.stderr
    clone = tmp / "clone"
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True, capture_output=True, env=env())
    (clone / "b.py").write_text("y")
    git(clone, "add", "b.py", check=True)
    assert git(clone, "commit", "-q", "-m", "code in a clone").returncode == 0  # a clone has no hooksPath


# ---- R4: what a blocked update says, and the text guard refusing before git touches files -----------------------
def test_a_blocked_fast_forward_names_git_reset_merge(tmp):
    repo = seeded(tmp, "r")
    r = git(repo, "merge", "--ff-only", "feat/x")
    assert r.returncode != 0 and "git reset --merge" in r.stderr and "git merge --no-ff" in r.stderr
    assert git(repo, "reset", "--merge").returncode == 0
    assert git(repo, "merge", "--no-ff", "-q", "-m", "Merge feat/x", "feat/x").returncode == 0


MAIN_ROUTE_BLOCKED = ["git merge feat/x", "git merge --ff-only feat/x", "git merge --ff feat/x", "git merge --squash feat/x",
                      "git pull", "git pull origin main", "git cherry-pick abc123", "git revert HEAD", "git rebase feat/x",
                      "git am p.patch", "git reset --hard HEAD~1", "git reset --keep HEAD~1"]
MAIN_ROUTE_ALLOWED = ["git merge --no-ff feat/x", "git merge --no-ff -m x feat/x", "git merge --abort", "git reset --merge",
                      "git rebase --abort", "git cherry-pick --abort", "git reset --soft HEAD", "git reset HEAD",
                      "git checkout -b feat/y && git merge feat/x"]


@pytest.mark.parametrize("cmd", tiered(MAIN_ROUTE_BLOCKED, {0, 1, 4, 5, 6, 10}))
def test_text_guard_refuses_main_moving_commands_before_git_touches_files(tmp, cmd):
    repo = seeded(tmp, "r")
    code, err = guard(cmd, repo)
    assert code == 2 and "BLOCKED" in err, (cmd, err)
    assert "--no-ff" in err or "reset --merge" in err or "feature branch" in err


def test_text_guard_allows_the_sanctioned_forms_and_everything_off_main(tmp):
    repo = seeded(tmp, "r")
    for cmd in MAIN_ROUTE_ALLOWED:
        assert guard(cmd, repo)[0] == 0, cmd
    quiet(repo, "checkout", "-q", "feat/x")
    for cmd in ("git merge main", "git pull", "git rebase main", "git cherry-pick abc123", "git reset --hard HEAD~1"):
        # on a feature branch only the user-level destructive hook has a say about reset --hard
        assert guard(cmd, repo)[0] == 0, cmd


# ---- S1: ANY inconsistency between the install record and the repository blocks main --------------------------
def _edit_record(repo, fn):
    p = repo / ".git" / "blarai-install.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    fn(rec)
    p.write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8", newline="\n")


def _unrelated_commit(repo) -> str:
    empty = subprocess.run(["git", "-C", str(repo), "mktree"], input="", capture_output=True, text=True, env=env()).stdout.strip()
    return subprocess.run(["git", "-C", str(repo), "commit-tree", empty, "-m", "unrelated"], capture_output=True,
                          text=True, env=env(), input="").stdout.strip()


RECORD_EDITS = {
    "common_dir": lambda r, repo: r.__setitem__("common_dir", "C:/nowhere/.git"),
    "repo_roots": lambda r, repo: r.__setitem__("repo_roots", ["a" * 40]),
    "garbled": None,
    "source_commit": lambda r, repo: r.__setitem__("source_commit", _unrelated_commit(repo)),
    "unknown version": lambda r, repo: r.__setitem__("version", 2),
    "missing field": lambda r, repo: r.pop("interpreter_hash"),
    "wrong type": lambda r, repo: r.__setitem__("hook_count", "17"),
    "roots not a list": lambda r, repo: r.__setitem__("repo_roots", "abc"),
    "hook hash": lambda r, repo: r["hooks"].__setitem__("hooks/rules_common.py", "0" * 40),
    "interpreter hash": lambda r, repo: r.__setitem__("interpreter_hash", "0" * 40),
    "base interpreter sha256": lambda r, repo: r.__setitem__("base_interpreter_sha256", "0" * 64),
    "pyvenv cfg hash": lambda r, repo: r.__setitem__("pyvenv_cfg_sha256", "f" * 64),
}


@pytest.mark.parametrize("name", tiered(sorted(RECORD_EDITS), {"common_dir", "repo_roots", "garbled"}))
def test_any_record_inconsistency_blocks_code_commits_and_main_updates(tmp, name):
    repo = seeded(tmp, "r")
    feat = out(repo, "rev-parse", "feat/x")
    if name == "garbled":
        (repo / ".git" / "blarai-install.json").write_text("{not json", encoding="utf-8")
    else:
        _edit_record(repo, lambda r: RECORD_EDITS[name](r, repo))
    stage(repo, "src/a.py")
    r = commit(repo)
    assert r.returncode != 0 and ("install record" in r.stderr or "recorded base python" in r.stderr), (name, r.stderr)
    git(repo, "reset", "-q")
    r = git(repo, "update-ref", "refs/heads/main", feat)
    assert r.returncode != 0 and ("install record" in r.stderr or "recorded base python" in r.stderr), (name, r.stderr)
    assert out(repo, "rev-parse", "main") != feat
    c = installer(repo, "--check")
    assert c.returncode == 1 and "NOT OK" in c.stdout, name


# ---- the proof script (temp-repo mode only) ---------------------------------------------------------------
def test_prove_script_passes_in_a_temporary_repository_and_live_mode_needs_the_lead_flag(tmp):
    r = subprocess.run([sys.executable, str(PROVE)], capture_output=True, text=True, env=env(), timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    for line in ("--check reports OK", "a code commit on main is refused", "a companion commit on main is allowed",
                 "`git merge --no-ff` from a worktree on main is allowed", "post-commit still fires",
                 "--uninstall restores the previous hooks path"):
        assert any(ln.startswith("PASS") and line in ln for ln in r.stdout.splitlines()), (line, r.stdout)
    assert "FAIL" not in r.stdout and "ALL PASS" in r.stdout
    live = subprocess.run([sys.executable, str(PROVE), "--live"], capture_output=True, text=True, env=env(), timeout=60)
    assert live.returncode == 2 and "--i-am-the-lead" in live.stdout


mark_slow_except(globals(), {
    "test_any_record_inconsistency_blocks_code_commits_and_main_updates",
    "test_installing_checkout_on_a_branch_without_the_hooks_does_not_turn_protection_off",
    "test_check_fails_when_installed_files_are_missing_or_differ",
    "test_status_says_in_plain_language_whether_protection_is_on",
    "test_merging_a_branch_that_deletes_claude_md_does_not_switch_the_guard_off",
    "test_orphan_head_cannot_delete_or_replace_main",
    "test_a_forced_update_of_main_is_judged_from_its_real_value",
    "test_a_repository_pointed_at_our_hooks_is_blocked_and_a_clone_is_untouched",
    "test_a_blocked_fast_forward_names_git_reset_merge",
    "test_text_guard_refuses_main_moving_commands_before_git_touches_files",
    "test_text_guard_allows_the_sanctioned_forms_and_everything_off_main",
    "test_prove_script_passes_in_a_temporary_repository_and_live_mode_needs_the_lead_flag",
    "test_update_follows_a_legitimate_hook_change_on_main_and_is_logged",
})


# ---- mutants: the new controls must be able to fail (slow tier) ------------------------------------------------
RC = "scripts/hooks/rules_common.py"
RT = "scripts/hooks/reference_transaction.py"


def _record_scenario(field_edit):
    def scenario(tmp, edits):  # with an inconsistent record even a companion commit on main is refused (fail closed)
        repo = make_repo(tmp, "i", edits=edits)
        _edit_record(repo, field_edit)
        stage(repo, "docs/reviews/r.md")
        return commit(repo).returncode != 0
    return scenario


s_record_common = _record_scenario(lambda r: r.__setitem__("common_dir", "C:/nowhere/.git"))
s_record_roots = _record_scenario(lambda r: r.__setitem__("repo_roots", ["a" * 40]))


def s_zero_old(tmp, edits):  # `branch -f` of a companion-only descendant is judged from the real tip -> allowed
    repo = make_repo(tmp, "z", branch="feat/c", edits=edits)
    stage(repo, "docs/reviews/c.md")
    quiet(repo, "commit", "-q", "-m", "companion")
    return git(repo, "branch", "-f", "main", "feat/c").returncode == 0


def s_check_vs_main(tmp, edits):  # --check fails when main moved ahead of the installed copy
    repo = make_repo(tmp, "c", branch="hook-change", edits=edits)
    own_installer = repo / "scripts" / "install_git_hooks.py"  # the (possibly mutated) copy in the repo
    p = repo / "scripts" / "hooks" / "reference_transaction.py"
    p.write_text(p.read_text(encoding="utf-8") + "\n# change\n", encoding="utf-8", newline="\n")
    quiet(repo, "commit", "-qam", "change")
    quiet(repo, "checkout", "-q", "main")
    git(repo, "merge", "--no-ff", "-q", "-m", "m", "hook-change")
    r = subprocess.run([sys.executable, str(own_installer), "--repo", str(repo), "--check"], capture_output=True,
                       text=True, env=env(), timeout=120)
    return r.returncode != 0


def s_missing_file(tmp, edits):  # a deleted installed hook file is detected (count check)
    repo = make_repo(tmp, "m", edits=edits)
    (inst(repo) / "githooks" / "post-merge").unlink()
    stage(repo, "docs/reviews/r.md")
    return commit(repo).returncode != 0


def s_text_main_route(tmp, edits):
    repo = seeded(tmp, "t", edits=edits)
    return guard("git merge feat/x", repo, script=repo / "scripts" / "hooks" / "git_rules_guard.py")[0] == 2


MUTANTS = {  # name: (scenario, expected unmutated result, edits)
    "record mismatch ignored (common dir)": (s_record_common, True, [
        ("scripts/hooks/git_native_pre_commit.py", "    if broken:\n        return 1, (rc.MISMATCH", '    if broken:\n        return 0, "", ""  # the old behaviour: not ours, allow\n    if False:\n        return 1, (rc.MISMATCH'),
        ("scripts/hooks/reference_transaction.py", "    if broken:\n        return 1, (rc.MISMATCH", '    if broken:\n        return 0, "", ""  # the old behaviour: not ours, allow\n    if False:\n        return 1, (rc.MISMATCH'),
    ]),
    "recorded roots not checked": (s_record_roots, True, [(RC, "        if not set(roots) <= real:", "        if False:")]),
    "forced update not resolved to the real tip": (s_zero_old, True, [(RT, "        if old == rc.ZERO_OID:  # an unspecified old value", "        if False:  # an unspecified old value")]),
    "check ignores main": (s_check_vs_main, True, [("scripts/install_git_hooks.py", '    if rec["hooks"] != dict(sorted(source.items())):', "    if False:")]),
    "file count not checked": (s_missing_file, True, [
        ("scripts/githooks/_lib.sh", '    if [ "$#" -ne "$_want_n" ]; then', "    if false; then"),
        (RC, '        problems.append(f"{missing}: recorded but missing")', "        pass"),
    ]),
    "main-route text rule off": (s_text_main_route, True, [("scripts/hooks/git_rules_guard.py", "                if on_main:\n                    raise Violation(\"main-route\", msg)", "                if False:\n                    raise Violation(\"main-route\", msg)")]),
}


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_install_hardening_mutant_is_caught(name, tmp):
    scenario, expected, edits = MUTANTS[name]
    assert scenario(tmp / "real", []) is expected, f"{name}: the unmutated control must hold"
    assert scenario(tmp / "mut", edits) is not expected, f"mutant survived: {name}"
