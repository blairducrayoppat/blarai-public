"""Hardening locks for the git-native hooks and the text guard's shared allowlist (#1690).

Reproductions, each in a temp repo with real git and the real installer: evil and octopus merges,
unrelated histories, loose second parents, multi-ref transactions, ref spellings, orphan-HEAD scope
bypass; allowlist escapes through the text guard; and a hostile interpreter / environment around
the shims.
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
    approved,
    GUARD, ROOT, commit, env, git, head, inst, installer, make_repo, mark_slow_except, quiet, record, stage, tiered,
)


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


def seeded(tmp: Path, name: str) -> Path:
    repo = make_repo(tmp, name, branch="feat/x")
    stage(repo, "services/app.py")
    quiet(repo, "commit", "-q", "-m", "feature work")
    quiet(repo, "checkout", "-q", "main")
    return repo


def out(repo, *args, **kw) -> str:
    return git(repo, *args, **kw).stdout.strip()


def real_merge_tree(repo, other="feat/x") -> str:
    return git(repo, "merge-tree", "--write-tree", "main", other, check=True).stdout.split()[0]


def commit_tree(repo, tree, *parents, msg="m") -> str:
    args = ["commit-tree", tree, "-m", msg]
    for p in parents:
        args += ["-p", p]
    return git(repo, *args, check=True).stdout.strip()


def update_main(repo, sha):
    return git(repo, "update-ref", "refs/heads/main", sha)


def tree_with_extra_file(repo, base_tree: str, path: str) -> str:
    idx = str(repo.parent / "tmp.index")
    e = {"GIT_INDEX_FILE": idx}
    git(repo, "read-tree", base_tree, env_extra=e, check=True)
    blob = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input="evil", capture_output=True,
                          text=True, env=env()).stdout.strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env_extra=e, check=True)
    return git(repo, "write-tree", env_extra=e, check=True).stdout.strip()


# ---- (1) reference-transaction: merge commits ------------------------------------------------------------
def test_a_merge_equal_to_git_merge_is_allowed_and_an_evil_merge_is_not(tmp):
    repo = seeded(tmp, "r")
    real = real_merge_tree(repo)
    good = commit_tree(repo, real, head(repo), out(repo, "rev-parse", "feat/x"))
    evil = commit_tree(repo, tree_with_extra_file(repo, real, "services/evil.py"), head(repo),
                       out(repo, "rev-parse", "feat/x"))
    r = update_main(repo, evil)
    assert r.returncode != 0 and "does not equal the merge" in r.stderr
    assert "services/evil.py" not in out(repo, "ls-tree", "-r", "--name-only", "main")
    assert update_main(repo, good).returncode == 0, "the merge git itself would have made must pass"


def test_octopus_merge_is_refused(tmp):
    repo = seeded(tmp, "r")
    quiet(repo, "checkout", "-q", "-b", "feat/y", "main")
    stage(repo, "services/y.py")
    quiet(repo, "commit", "-q", "-m", "y")
    quiet(repo, "checkout", "-q", "main")
    tree = out(repo, "rev-parse", "feat/x^{tree}")
    sha = commit_tree(repo, tree, head(repo), out(repo, "rev-parse", "feat/x"), out(repo, "rev-parse", "feat/y"))
    r = update_main(repo, sha)
    assert r.returncode != 0 and "octopus" in r.stderr


def test_unrelated_history_second_parent_is_refused(tmp):
    repo = seeded(tmp, "r")
    quiet(repo, "checkout", "-q", "--orphan", "other")
    quiet(repo, "rm", "-rfq", ".", check=False)
    (repo / "orphan.txt").write_text("o")
    quiet(repo, "add", "orphan.txt")
    quiet(repo, "commit", "-q", "-m", "orphan root")
    quiet(repo, "checkout", "-q", "main")
    r = git(repo, "merge", "--allow-unrelated-histories", "--no-ff", "-q", "-m", "m", "other")
    assert r.returncode != 0
    assert "orphan.txt" not in out(repo, "ls-tree", "-r", "--name-only", "main")
    tree = out(repo, "rev-parse", "other^{tree}")
    sha = commit_tree(repo, tree, head(repo), out(repo, "rev-parse", "other"))
    assert update_main(repo, sha).returncode != 0


def test_second_parent_on_no_local_branch_is_refused(tmp):
    repo = seeded(tmp, "r")
    tree = real_merge_tree(repo)
    loose = commit_tree(repo, out(repo, "rev-parse", "feat/x^{tree}"), msg="loose")  # parentless, referenced by nothing
    sha = commit_tree(repo, tree, head(repo), loose)
    r = update_main(repo, sha)
    assert r.returncode != 0 and ("no local" in r.stderr or "cannot be reproduced" in r.stderr)


def test_merge_s_ours_and_hand_resolved_merges_are_refused(tmp):
    repo = seeded(tmp, "r")
    r = git(repo, "merge", "-s", "ours", "--no-ff", "-q", "-m", "ours", "feat/x")
    assert r.returncode != 0 and "does not equal the merge" in r.stderr


def test_transaction_with_main_not_first_is_judged_as_a_whole(tmp):
    repo = seeded(tmp, "r")
    feat = out(repo, "rev-parse", "feat/x")
    old = head(repo)
    p = subprocess.run(["git", "-C", str(repo), "update-ref", "--stdin"], capture_output=True, text=True, env=env(),
                       input=f"start\nupdate refs/heads/aaa {feat}\nupdate refs/heads/main {feat} {old}\nprepare\ncommit\n")
    assert p.returncode != 0
    assert git(repo, "rev-parse", "--verify", "-q", "refs/heads/aaa").returncode != 0, "the whole transaction aborts"
    assert head(repo) == old


def test_ref_spelling_variants_do_not_move_main(tmp):
    repo = seeded(tmp, "r")
    old = head(repo)
    feat = out(repo, "rev-parse", "feat/x")
    git(repo, "update-ref", "refs/heads/Main", feat)
    git(repo, "update-ref", "refs/heads/MASTER", feat)
    assert head(repo) == old
    assert "services/app.py" not in out(repo, "ls-tree", "-r", "--name-only", "main")


def test_packed_main_is_still_judged(tmp):
    repo = seeded(tmp, "r")
    assert git(repo, "pack-refs", "--all").returncode == 0, "pack-refs/gc must keep working"
    assert git(repo, "gc", "-q").returncode == 0
    assert git(repo, "rev-parse", "--verify", "-q", "refs/heads/main").returncode == 0
    r = git(repo, "update-ref", "refs/heads/main", out(repo, "rev-parse", "feat/x"))
    assert r.returncode != 0


@pytest.mark.parametrize("packed", [False, True])
def test_real_deletions_of_main_are_refused_loose_or_packed(tmp, packed):
    repo = seeded(tmp, "r")
    if packed:
        assert git(repo, "pack-refs", "--all").returncode == 0
        (repo / ".git" / "refs" / "heads" / "main").unlink(missing_ok=True)  # now only in packed-refs
    quiet(repo, "checkout", "-q", "feat/x")
    old = out(repo, "rev-parse", "main")
    assert git(repo, "branch", "-D", "main").returncode != 0
    assert git(repo, "update-ref", "-d", "refs/heads/main").returncode != 0
    assert git(repo, "update-ref", "-d", "refs/heads/main", old).returncode != 0  # explicit old value: still a deletion
    assert git(repo, "rev-parse", "--verify", "-q", "refs/heads/main").returncode == 0


def test_pack_refs_with_loose_and_packed_copies_keeps_main(tmp):
    repo = seeded(tmp, "r")
    assert git(repo, "pack-refs", "--all").returncode == 0
    stage(repo, "docs/reviews/r.md")
    assert commit(repo).returncode == 0  # main is loose again, with an older packed copy
    assert git(repo, "pack-refs", "--all").returncode == 0
    assert git(repo, "rev-parse", "--verify", "-q", "refs/heads/main").returncode == 0


def test_symbolic_ref_to_main_then_commit_is_judged_on_main(tmp):
    repo = seeded(tmp, "r")
    quiet(repo, "checkout", "-q", "feat/x")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main", check=True)  # index still holds feat/x's code
    r = commit(repo)
    assert r.returncode != 0 and "services/app.py" in r.stderr


@pytest.mark.parametrize("orphan_commit", tiered([False, True], {0}))
def test_orphan_head_cannot_switch_the_guard_off(tmp, orphan_commit):
    repo = seeded(tmp, "r")
    quiet(repo, "checkout", "-q", "--orphan", "o")
    if orphan_commit:  # a HEAD whose CLAUDE.md marker is absent: scope must come from main's own tip
        quiet(repo, "rm", "--cached", "-rfq", ".", check=False)  # keep the work tree: it holds the hook files
        (repo / "x.txt").write_text("x")
        quiet(repo, "add", "x.txt")
        quiet(repo, "commit", "-q", "-m", "orphan")
    r = git(repo, "update-ref", "refs/heads/main", out(repo, "rev-parse", "feat/x"))
    assert r.returncode != 0 and "BLOCKED" in r.stderr
    assert git(repo, "rev-parse", "refs/heads/main").stdout.strip() != out(repo, "rev-parse", "feat/x")


def test_only_prepared_state_acts_and_aborted_committed_are_inert(tmp):
    repo = seeded(tmp, "r")
    shim = (inst(repo) / "githooks" / "reference-transaction").as_posix()
    feat = out(repo, "rev-parse", "feat/x")
    for state in ("preparing", "committed", "aborted"):
        p = subprocess.run(["sh", shim, state], input=f"{head(repo)} {feat} refs/heads/main\n", capture_output=True,
                           text=True, cwd=str(repo), env=env())
        assert p.returncode == 0, (state, p.stderr)
    p = subprocess.run(["sh", shim, "prepared"], input=f"{head(repo)} {feat} refs/heads/main\n", capture_output=True,
                       text=True, cwd=str(repo), env=env())
    assert p.returncode != 0


# ---- (2) the text guard shares the one allowlist definition -----------------------------------------------
def guard(cmd, cwd):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)})
    r = subprocess.run([sys.executable, str(GUARD)], input=payload, capture_output=True, text=True, env=env(), timeout=90)
    return r.returncode, r.stderr


def _cacheinfo(repo, mode, content, path):
    sha = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=content, capture_output=True,
                         text=True, env=env()).stdout.strip()
    return git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}").returncode == 0


def test_text_guard_uses_the_shared_allowlist_and_has_no_copy():
    src = GUARD.read_text(encoding="utf-8")
    for needle in ("ALLOWED_EXTENSIONS =", "def _path_problem", "def change_problem", "COMPANION_ALLOWLIST = (",
                   "ALLOWED_MODE ="):
        assert needle not in src, needle
    assert "rules_common.staged_problems" in src


@pytest.mark.parametrize("what", tiered(["symlink", "gitlink", "executable", "py", "sh", "html", "dotfile", "junction-like",
                                         "traversal", "case-variant", "oversize"], {"symlink", "py"}))
def test_text_guard_refuses_allowlist_escapes_on_main(tmp, what):
    repo = make_repo(tmp, "r", branch="feat/x")
    quiet(repo, "checkout", "-q", "main")
    if what == "case-variant":
        stage(repo, "docs/research/Notes.md")
        quiet(repo, "commit", "-q", "-m", "n")
    if what == "symlink":
        _cacheinfo(repo, "120000", "../../services/app.py", "docs/research/link.md")
    elif what == "gitlink":
        git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head(repo)},docs/research/sub", check=True)
    elif what == "executable":
        stage(repo, "docs/research/t.md")
        git(repo, "update-index", "--chmod=+x", "docs/research/t.md", check=True)
    elif what == "py":
        stage(repo, "docs/research/run.py")
    elif what == "sh":
        stage(repo, "docs/reviews/probe.sh")
    elif what == "html":
        stage(repo, "docs/research/page.html")
    elif what == "dotfile":
        stage(repo, "docs/research/.gitattributes")
    elif what == "junction-like":
        if not _cacheinfo(repo, "100644", "x", "docs/research/PROGRA~1.md "):
            return  # git itself refused the path
    elif what == "traversal":
        if not _cacheinfo(repo, "100644", "x", "docs/research/../../scripts/x.md"):
            return  # git itself refused the path
    elif what == "case-variant":
        _cacheinfo(repo, "100644", "x", "docs/research/notes.md")
    elif what == "oversize":
        p = repo / "docs" / "research" / "big.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        git(repo, "add", "docs/research/big.json", check=True)
    code, err = guard("git commit -m x", repo)
    assert code == 2 and "not a companion change" in err, (what, err)


def test_text_guard_allows_a_plain_companion_commit_on_main(tmp):
    repo = make_repo(tmp, "r")
    stage(repo, "docs/research/ok.md", "docs/journal_fragments/j.md")
    assert guard("git commit -m x", repo)[0] == 0


# ---- (3) the shims run only what they verified, with an interpreter they recorded -----------------------------
def code_on_main(tmp, name="r"):
    repo = make_repo(tmp, name)
    stage(repo, "src/a.py")
    return repo


def test_a_planted_python_on_path_and_in_the_repo_is_not_used(tmp):
    repo = code_on_main(tmp)
    fake = tmp / "fakebin"
    fake.mkdir()
    for name in ("python", "python3", "py", "python.exe", "python3.exe", "py.exe"):
        (fake / name).write_text("#!/bin/sh\nexit 0\n", newline="\n")
        (repo / name).write_text("#!/bin/sh\nexit 0\n", newline="\n")
    r = commit(repo, env_extra={"PATH": str(fake) + os.pathsep + os.environ["PATH"]})
    assert r.returncode != 0 and "src/a.py" in r.stderr


def test_python_environment_injection_is_ignored(tmp):
    repo = code_on_main(tmp)
    evil = tmp / "evil"
    evil.mkdir()
    marker = (tmp / "marker.txt").as_posix()
    (evil / "json.py").write_text(f"import os\nopen(r'{marker}', 'w').write('x')\nos._exit(0)\n")
    (evil / "sitecustomize.py").write_text(f"import os\nopen(r'{marker}', 'w').write('s')\nos._exit(0)\n")
    (repo / "sitecustomize.py").write_text(f"import os\nos._exit(0)\n")
    r = commit(repo, env_extra={"PYTHONPATH": str(evil), "PYTHONHOME": str(tmp / "nonexistent"),
                                "PYTHONSTARTUP": str(evil / "sitecustomize.py"), "PYTHONUSERBASE": str(evil)})
    assert r.returncode != 0 and "src/a.py" in r.stderr
    assert not (tmp / "marker.txt").exists()


def test_a_changed_or_missing_recorded_interpreter_fails_closed(tmp):
    repo = make_repo(tmp, "r", branch="feat/x")  # even a feature branch: the guard cannot run
    stage(repo, "src/a.py")
    recfile = repo / ".git" / "blarai-install.json"
    good = recfile.read_text()
    exe_hash = record(repo)["base_interpreter_sha256"]
    recfile.write_text(good.replace(exe_hash, "0" * 64), newline="\n")
    r = commit(repo)
    assert r.returncode != 0 and "recorded base python" in r.stderr
    assert installer(repo, "--check").returncode == 1
    recfile.unlink()
    r = commit(repo)
    assert r.returncode != 0 and "BLOCKED" in r.stderr
    assert approved(repo, "test", "--accept-drift").returncode == 0 and installer(repo, "--check").returncode == 0  # re-record repairs it
    assert commit(repo).returncode == 0


def test_installer_records_an_absolute_interpreter_with_its_hash(tmp):
    repo = make_repo(tmp, "r")
    rec = record(repo)
    assert Path(rec["interpreter"]).is_absolute() and Path(rec["interpreter"]).is_file()
    assert rec["interpreter_hash"] == git(repo, "hash-object", "--", rec["interpreter"]).stdout.strip()
    assert installer(repo, "--uninstall").returncode == 0
    assert not (repo / ".git" / "blarai-install.json").exists()


def test_a_modified_lib_is_caught_before_it_runs(tmp):
    repo = code_on_main(tmp)
    lib = inst(repo) / "githooks" / "_lib.sh"
    lib.write_text(lib.read_text() + "\nrun_guard() { return 0; }\nverify_install() { return 0; }\n", newline="\n")
    r = commit(repo)
    assert r.returncode != 0 and "_lib.sh" in r.stderr and "differs" in r.stderr
    quiet(repo, "checkout", "-q", "-b", "feat/x")  # and the same edit cannot move main from elsewhere
    stage(repo, "services/app.py")
    quiet(repo, "commit", "-q", "-m", "f")
    r = git(repo, "update-ref", "refs/heads/main", out(repo, "rev-parse", "feat/x"))
    assert r.returncode != 0 and "_lib.sh" in r.stderr


def test_a_bom_in_a_guard_module_is_a_difference(tmp):
    repo = make_repo(tmp, "r")
    p = inst(repo) / "hooks" / "rules_common.py"
    p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes().replace(b"\r\n", b"\n"))
    stage(repo, "docs/reviews/r.md")
    r = commit(repo)
    assert r.returncode != 0 and "differ" in r.stderr


def test_a_line_ending_change_in_an_installed_file_is_a_difference(tmp):
    # The installed copies sit inside .git (no attributes, no autocrlf): hashing is byte-exact.
    repo = make_repo(tmp, "r")
    p = inst(repo) / "hooks" / "rules_common.py"
    p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    stage(repo, "docs/reviews/r.md")
    r = commit(repo)
    assert r.returncode != 0 and "differ" in r.stderr


mark_slow_except(globals(), {
    "test_a_merge_equal_to_git_merge_is_allowed_and_an_evil_merge_is_not", "test_packed_main_is_still_judged",
    "test_orphan_head_cannot_switch_the_guard_off", "test_text_guard_uses_the_shared_allowlist_and_has_no_copy",
    "test_text_guard_refuses_allowlist_escapes_on_main", "test_a_planted_python_on_path_and_in_the_repo_is_not_used",
    "test_python_environment_injection_is_ignored", "test_a_changed_or_missing_recorded_interpreter_fails_closed",
    "test_a_modified_lib_is_caught_before_it_runs",
})


# ---- mutants: every new control must be able to fail (slow: opt in with -m slow) -------------------------------
RTP = "scripts/hooks/reference_transaction.py"
NO_REF_TX = ("scripts/githooks/reference-transaction", "# Git-native reference-transaction shim:", "exit 0\n# Git-native reference-transaction shim:")


def _seeded_with(tmp, name, edits):
    repo = make_repo(tmp, name, branch="feat/x", edits=edits)
    stage(repo, "services/app.py")
    quiet(repo, "commit", "-q", "-m", "feature work")
    quiet(repo, "checkout", "-q", "main")
    return repo


def s_evil_merge(tmp, edits):
    repo = _seeded_with(tmp, "e", edits)
    feat = out(repo, "rev-parse", "feat/x")
    evil = commit_tree(repo, tree_with_extra_file(repo, real_merge_tree(repo), "services/evil.py"), head(repo), feat)
    return update_main(repo, evil).returncode != 0


def s_octopus(tmp, edits):
    repo = _seeded_with(tmp, "o", edits)
    quiet(repo, "checkout", "-q", "-b", "feat/y", "main")
    stage(repo, "services/y.py")
    quiet(repo, "commit", "-q", "-m", "y")
    quiet(repo, "checkout", "-q", "main")
    sha = commit_tree(repo, out(repo, "rev-parse", "feat/x^{tree}"), head(repo), out(repo, "rev-parse", "feat/x"),
                      out(repo, "rev-parse", "feat/y"))
    return update_main(repo, sha).returncode != 0


def s_loose_parent(tmp, edits):
    repo = _seeded_with(tmp, "l", edits)
    loose = commit_tree(repo, out(repo, "rev-parse", "feat/x^{tree}"), head(repo), msg="loose")  # related, on no branch
    return update_main(repo, commit_tree(repo, real_merge_tree(repo), head(repo), loose)).returncode != 0


def s_delete_loose_main(tmp, edits):
    repo = _seeded_with(tmp, "d", edits)
    quiet(repo, "checkout", "-q", "feat/x")
    return git(repo, "update-ref", "-d", "refs/heads/main", out(repo, "rev-parse", "main")).returncode != 0


def s_changed_interpreter(tmp, edits):
    repo = make_repo(tmp, "i", branch="feat/x", edits=edits)
    stage(repo, "src/a.py")
    recfile = repo / ".git" / "blarai-install.json"
    recfile.write_text(recfile.read_text().replace(record(repo)["base_interpreter_sha256"], "0" * 64), newline="\n")
    return commit(repo).returncode != 0


def s_env_injection(tmp, edits):
    repo = make_repo(tmp, "n", edits=edits)
    stage(repo, "src/a.py")
    evil = tmp / "evil"
    evil.mkdir()
    (evil / "json.py").write_text(  # exits 0 AND prints the affirmative token for the guard script that imported it
        "import hashlib, os, sys" + chr(10)
        + "sys.stdout.write('BLARAI-GUARD-OK ' + hashlib.sha256(open(sys.argv[0], 'rb').read()).hexdigest() + chr(10))" + chr(10)
        + "sys.stdout.flush()" + chr(10) + "os._exit(0)" + chr(10))
    return commit(repo, env_extra={"PYTHONPATH": str(evil)}).returncode != 0


def s_lib_tamper(tmp, edits):
    repo = make_repo(tmp, "t", edits=edits)
    stage(repo, "src/a.py")
    lib = inst(repo) / "githooks" / "_lib.sh"
    lib.write_text(lib.read_text() + "\nrun_guard() { return 0; }\nverify_install() { return 0; }\n", newline="\n")
    return commit(repo).returncode != 0


HARDENING_MUTANTS = {  # name: (scenario, edits)
    "merge tree not compared": (s_evil_merge, [(RTP, "    if tree != first:", "    if False:")]),
    "octopus allowed": (s_octopus, [(RTP, "    if len(parents) != 3:", "    if False:")]),
    "loose second parent allowed": (s_loose_parent, [(RTP, "    if not branches:", "    if False:")]),
    "every deletion treated as pack-refs": (s_delete_loose_main, [(RTP, '    common = _run(["rev-parse", "--path-format=absolute", "--git-common-dir"]).stdout.strip()\n    if not common:', '    return True\n    if not common:')]),
    "interpreter hash unchecked": (s_changed_interpreter, [("scripts/githooks/_lib.sh", '    if [ "$_have" != "$_pysha" ]; then', "    if false; then")]),
    "isolated python off": (s_env_injection, [("scripts/githooks/_lib.sh", '"$_py" -I -S -B "$_guard"', '"$_py" -B "$_guard"')] * 2),
    "lib check skipped before sourcing": (s_lib_tamper, [NO_REF_TX, ("scripts/githooks/pre-commit", 'if [ -z "$_want" ] || [ "$_want" != "$_lh" ]; then', "if false; then")]),
}
REAL_BLOCKED = {s_evil_merge: True, s_octopus: True, s_loose_parent: True, s_delete_loose_main: True,
                s_changed_interpreter: True, s_env_injection: True, s_lib_tamper: True}


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(HARDENING_MUTANTS))
def test_hardening_mutant_is_caught(name, tmp):
    scenario, edits = HARDENING_MUTANTS[name]
    baseline = scenario(tmp / "real", [NO_REF_TX] if scenario is s_lib_tamper else [])
    assert baseline is True, f"{name}: the unmutated control must block"
    assert scenario(tmp / "mut", edits) is False, f"mutant survived: {name}"
