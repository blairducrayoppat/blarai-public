"""Locks for the git-native reference-transaction guard (#1690): the only ways main moves.

Real git in temp repos, hooks installed by the real installer. Every route that puts a commit
on main without a pre-commit (fast-forward merge, cherry-pick, revert, am, rebase, pull,
commit-tree + update-ref, branch -f, push ., ...) must abort the transaction; `git merge
--no-ff` and companion-only commits must pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_hook_helpers import commit, env, git, head, inst, installer, make_repo, mark_slow_except, quiet, stage, tiered  # noqa: E402


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


def seeded(tmp: Path, name: str, **kw) -> Path:
    """Repo on main, hooks installed, plus a branch feat/x holding one code commit; on main."""
    repo = make_repo(tmp, name, branch="feat/x", **kw)
    stage(repo, "services/app.py")
    quiet(repo, "commit", "-q", "-m", "feature work")
    quiet(repo, "checkout", "-q", kw.get("trunk", "main"))
    return repo


def feat_sha(repo) -> str:
    return git(repo, "rev-parse", "feat/x").stdout.strip()


def on_main(repo, *args) -> subprocess.CompletedProcess:
    return git(repo, *args)


# ---- routes that must be BLOCKED (name, action(repo) -> CompletedProcess) ---------------------------------
def r_ff_merge(repo):
    return git(repo, "merge", "feat/x")


def r_ff_only(repo):
    return git(repo, "merge", "--ff-only", "feat/x")


def r_cherry_pick(repo):
    return git(repo, "cherry-pick", feat_sha(repo))


def r_revert(repo):
    assert git(repo, "merge", "--no-ff", "-q", "-m", "Merge feat/x", "feat/x").returncode == 0
    return git(repo, "revert", "--no-edit", "-m", "1", "HEAD")


def r_am(repo):
    patch = git(repo, "format-patch", "-1", "feat/x", "--stdout").stdout
    (repo.parent / "p.patch").write_text(patch, encoding="utf-8", newline="\n")
    return git(repo, "am", str(repo.parent / "p.patch"))


def r_rebase(repo):
    return git(repo, "rebase", "feat/x")


def r_pull(repo):
    return git(repo, "pull", "-q", ".", "feat/x")


def r_commit_tree_update_ref(repo):
    tree = git(repo, "rev-parse", "feat/x^{tree}").stdout.strip()
    sha = git(repo, "commit-tree", tree, "-p", head(repo), "-m", "plumbing").stdout.strip()
    return git(repo, "update-ref", "refs/heads/main", sha)


def r_branch_f(repo):
    git(repo, "checkout", "-q", "feat/x", check=True)
    return git(repo, "branch", "-f", "main", "feat/x")


def r_push_dot(repo):
    quiet(repo, "checkout", "-q", "feat/x")  # git refuses to push into the checked-out branch itself
    return git(repo, "push", "-q", ".", "feat/x:main")


def r_squash(repo):
    assert git(repo, "merge", "--squash", "feat/x").returncode == 0
    return commit(repo)


def r_delete_branch(repo):
    git(repo, "checkout", "-q", "feat/x", check=True)
    return git(repo, "branch", "-D", "main")


def r_update_ref_delete(repo):
    return git(repo, "update-ref", "-d", "refs/heads/main")


def r_rename_main(repo):
    git(repo, "checkout", "-q", "feat/x", check=True)
    return git(repo, "branch", "-m", "main", "oldmain")


def r_reset_rewind(repo):
    stage(repo, "docs/reviews/r.md")
    assert commit(repo).returncode == 0
    return git(repo, "reset", "--soft", "HEAD~1")


def r_no_verify(repo):
    stage(repo, "services/b.py")
    return commit(repo, "--no-verify")


def r_merge_commit_with_wrong_first_parent(repo):
    # a merge commit whose first parent is NOT the old tip: feature-first merge landed on main
    tree = git(repo, "rev-parse", "feat/x^{tree}").stdout.strip()
    sha = git(repo, "commit-tree", tree, "-p", feat_sha(repo), "-p", head(repo), "-m", "reversed").stdout.strip()
    return git(repo, "update-ref", "refs/heads/main", sha)


BLOCKED = {
    "fast-forward merge": r_ff_merge, "merge --ff-only": r_ff_only, "cherry-pick": r_cherry_pick,
    "revert of a merge": r_revert, "am": r_am, "rebase": r_rebase, "pull .": r_pull,
    "commit-tree + update-ref": r_commit_tree_update_ref, "branch -f main": r_branch_f,
    "push . feat:main": r_push_dot, "merge --squash + commit": r_squash, "branch -D main": r_delete_branch,
    "update-ref -d": r_update_ref_delete, "branch -m main": r_rename_main, "reset --soft rewind": r_reset_rewind,
    "commit --no-verify": r_no_verify, "reversed merge parents": r_merge_commit_with_wrong_first_parent,
}


@pytest.mark.parametrize("route", tiered(sorted(BLOCKED), {"fast-forward merge", "push . feat:main", "branch -D main", "commit-tree + update-ref"}))
def test_route_to_main_is_blocked(route, tmp):
    repo = seeded(tmp, "r")
    main_before = git(repo, "rev-parse", "main").stdout.strip()
    git(repo, "merge", "--abort")  # no-op safety
    r = BLOCKED[route](repo)
    after = git(repo, "rev-parse", "main")
    if route == "revert of a merge":
        main_before = git(repo, "rev-parse", "main~1").stdout.strip() if after.returncode == 0 else main_before
    assert r.returncode != 0, (route, r.stdout, r.stderr)
    # main either did not move, or (for deletions) is still present
    assert after.returncode == 0, route
    if route not in ("revert of a merge", "reset --soft rewind"):
        assert after.stdout.strip() == main_before, route
    assert "BLOCKED" in r.stderr or "aborted" in r.stderr or "reference-transaction" in r.stderr, r.stderr
    # no code from the feature branch is on main
    assert "services/app.py" not in git(repo, "ls-tree", "-r", "--name-only", "main").stdout or route == "revert of a merge"


# ---- routes that must be ALLOWED --------------------------------------------------------------------------
def test_merge_no_ff_is_allowed_and_names_a_merge_commit(tmp):
    repo = seeded(tmp, "r")
    r = git(repo, "merge", "--no-ff", "-q", "-m", "Merge feat/x", "feat/x")
    assert r.returncode == 0, r.stderr
    assert len(git(repo, "rev-list", "--parents", "-n", "1", "main").stdout.split()) == 3


def test_companion_only_commit_is_allowed(tmp):
    repo = seeded(tmp, "r")
    stage(repo, "docs/journal_fragments/j.md", "LESSONS.md")
    assert commit(repo).returncode == 0
    stage(repo, "docs/reviews/r2.md")
    assert commit(repo).returncode == 0  # a second one on top: old..new walks both


def test_creating_and_working_on_other_branches_is_untouched(tmp):
    repo = seeded(tmp, "r")
    assert git(repo, "branch", "newb", "main").returncode == 0
    assert git(repo, "checkout", "-q", "-b", "feat/y").returncode == 0
    stage(repo, "services/c.py")
    assert commit(repo).returncode == 0
    assert git(repo, "branch", "-f", "newb", "feat/y").returncode == 0
    assert git(repo, "tag", "t1").returncode == 0
    assert git(repo, "stash", "list").returncode == 0
    assert git(repo, "branch", "-D", "newb").returncode == 0


def test_an_installed_repository_is_protected_whatever_its_files_say(tmp):
    repo = seeded(tmp, "r", blarai=False)
    assert git(repo, "merge", "--ff-only", "feat/x").returncode != 0


def test_hooks_work_inside_linked_worktrees(tmp):
    repo = seeded(tmp, "r")
    git(repo, "checkout", "-q", "feat/x", check=True)
    wt = tmp / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "main", check=True)
    assert git(wt, "merge", "--ff-only", "feat/x").returncode != 0  # blocked from a linked worktree
    quiet(wt, "reset", "-q", "--hard", "main")  # a blocked merge leaves its checked-out files behind
    assert git(wt, "merge", "--no-ff", "-q", "-m", "Merge feat/x", "feat/x").returncode == 0
    stage(wt, "docs/reviews/z.md")
    assert commit(wt).returncode == 0


def test_unborn_main_root_commit_via_plumbing_is_refused(tmp):
    repo = make_repo(tmp, "u")
    tree = git(repo, "write-tree").stdout.strip()
    sha = git(repo, "commit-tree", tree, "-m", "root").stdout.strip()
    r = git(repo, "update-ref", "refs/heads/master", sha)  # a protected ref that does not exist: cannot be verified
    assert r.returncode != 0 and "cannot be verified" in r.stderr
    assert git(repo, "rev-parse", "--verify", "-q", "refs/heads/master").returncode != 0


def test_modified_hook_files_refuse_an_update_of_main(tmp):
    repo = seeded(tmp, "r")
    p = inst(repo) / "hooks" / "rules_common.py"
    p.write_text(p.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8", newline="\n")
    r = git(repo, "merge", "--no-ff", "-q", "-m", "Merge feat/x", "feat/x")
    assert r.returncode != 0 and "differ" in r.stderr
    quiet(repo, "merge", "--abort")
    q = inst(repo) / "hooks" / "reference_transaction.py"
    q.write_text("import sys\nsys.exit(0)\n", encoding="utf-8", newline="\n")
    p.write_text(p.read_text(encoding="utf-8").replace("\n# edited\n", ""), encoding="utf-8", newline="\n")
    r = git(repo, "merge", "--no-ff", "-q", "-m", "Merge feat/x", "feat/x")
    assert r.returncode != 0 and "differ" in r.stderr  # a replaced guard is not run


def test_working_tree_hook_edits_in_any_worktree_change_nothing(tmp):
    # The hooks run from the installed copy: a no-op guard written into a worktree's scripts/ is never run.
    repo = seeded(tmp, "r")
    git(repo, "checkout", "-q", "feat/x", check=True)
    p = repo / "scripts" / "hooks" / "reference_transaction.py"
    p.write_text("import sys\nsys.exit(0)\n", encoding="utf-8", newline="\n")  # a no-op guard
    r = git(repo, "branch", "-f", "main", "feat/x")
    assert r.returncode != 0 and "BLOCKED" in r.stderr
    assert "services/app.py" not in git(repo, "ls-tree", "-r", "--name-only", "main").stdout


def test_override_allows_and_logs_with_the_ref_rule(tmp):
    repo = seeded(tmp, "r")
    log = tmp / "ov.log"
    r = git(repo, "merge", "--ff-only", "-q", "feat/x", env_extra={
        "BLARAI_GIT_RULES_OVERRIDE": "LA approved ff", "BLARAI_GIT_RULES_OVERRIDE_LOG": str(log)})
    assert r.returncode == 0, r.stderr
    rec = json.loads(log.read_text().splitlines()[-1])
    assert rec["rule"] == "ref-update-main" and rec["reason"] == "LA approved ff"


def test_override_blank_or_unwritable_log_stays_blocked(tmp):
    repo = seeded(tmp, "r")
    assert git(repo, "merge", "--ff-only", "feat/x", env_extra={"BLARAI_GIT_RULES_OVERRIDE": " "}).returncode != 0
    bad = tmp / "afile"
    bad.write_text("x")
    r = git(repo, "merge", "--ff-only", "feat/x", env_extra={
        "BLARAI_GIT_RULES_OVERRIDE": "r", "BLARAI_GIT_RULES_OVERRIDE_LOG": str(bad / "s" / "l.log")})
    assert r.returncode != 0


def test_broken_reference_transaction_script_aborts(tmp):
    repo = seeded(tmp, "r", edits=[("scripts/hooks/reference_transaction.py", "def check(", "def check_(")])
    r = git(repo, "merge", "--no-ff", "-q", "-m", "m", "feat/x")
    assert r.returncode != 0  # the guard faults (AttributeError): fail closed


def test_missing_python_script_aborts_main_updates_only(tmp):
    repo = seeded(tmp, "r")
    (inst(repo) / "hooks" / "reference_transaction.py").unlink()
    assert git(repo, "merge", "--no-ff", "-q", "-m", "m", "feat/x").returncode != 0
    assert git(repo, "branch", "newb", "feat/x").returncode == 0  # other refs never reach the script


def test_only_prepared_state_is_judged(tmp):
    repo = seeded(tmp, "r")
    # the shim exits 0 for `committed`/`aborted` without running python: simulate directly
    shim = inst(repo) / "githooks" / "reference-transaction"
    for state in ("committed", "aborted"):
        p = subprocess.run(["sh", shim.as_posix(), state], input=f"{'0' * 40} {'1' * 40} refs/heads/main\n",
                           capture_output=True, text=True, cwd=str(repo), env=env())
        assert p.returncode == 0, (state, p.stderr)


# ---- toggles and mutants: the probes must be able to fail -----------------------------------------------------
RT = "scripts/hooks/reference_transaction.py"
SCENARIOS = [  # (name, action, repo kwargs, expect_ok)
    ("ff merge", r_ff_merge, {}, False),
    ("merge --no-ff", lambda r: git(r, "merge", "--no-ff", "-q", "-m", "m", "feat/x"), {}, True),
    ("cherry-pick", r_cherry_pick, {}, False),
    ("branch -D main", r_delete_branch, {}, False),
    ("reset --soft rewind", r_reset_rewind, {}, False),
    ("reversed merge parents", r_merge_commit_with_wrong_first_parent, {}, False),
]


def run_scenarios(tmp: Path, tag: str, edits=(), only=None):
    out = {}
    for i, (name, action, kw, _) in enumerate(SCENARIOS):
        if only and name not in only:
            continue
        repo = seeded(tmp, f"{tag}{i}", edits=edits, **kw)
        out[name] = action(repo).returncode == 0
    return out


def test_scenarios_pass_on_the_real_hook(tmp):
    assert run_scenarios(tmp, "real") == {name: e for name, _, _, e in SCENARIOS}


def test_toggle_hooks_path_unset_means_ff_merge_lands(tmp):
    repo = seeded(tmp, "r")
    assert installer(repo, "--uninstall").returncode == 0
    assert git(repo, "merge", "--ff-only", "feat/x").returncode == 0  # documented: not installed => off


MUTANTS = {  # name: (file, old, new, scenarios that must change)
    "companion check ignored": (RT, "        if problems:\n            return (f\"commit", "        if False:\n            return (f\"commit", ["cherry-pick"]),
    "deletion allowed": (RT, '        return f"deleting {ref} is not allowed (git branch -d/-D/-m, update-ref -d)."', "        return None", ["branch -D main"]),
    "ancestor check removed": (RT, '    if _run(["merge-base", "--is-ancestor", old, new]).returncode != 0:', "    if False:", ["reset --soft rewind"]),
}


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_mutant_is_caught(name, tmp):
    rel, old, new, targets = MUTANTS[name]
    expected = {n: e for n, _, _, e in SCENARIOS if n in targets}
    got = run_scenarios(tmp, "m", edits=[(rel, old, new)], only=targets)
    assert got != expected, f"mutant survived: {name}"


mark_slow_except(globals(), {
    "test_route_to_main_is_blocked", "test_merge_no_ff_is_allowed_and_names_a_merge_commit",
    "test_an_installed_repository_is_protected_whatever_its_files_say", "test_toggle_hooks_path_unset_means_ff_merge_lands",
})
