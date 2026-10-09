# enforces-rule: critical_rules.git-has-no-human-safety-net -- git add -A and commit-on-main halves; destructive verbs are the external hook
# enforces-rule: git_discipline.shared_tree.no-git-add-a-ever
# enforces-rule: git_discipline.absolute_rules.never-commit-work-directly-to-main
"""Locks for scripts/hooks/git_rules_guard.py (#1690).

Every case drives the REAL script through stdin JSON, the way Claude Code runs a PreToolUse
hook. Exit 2 = blocked, exit 0 = allowed. Real temp git repos back the branch, MERGE_HEAD,
staged-set, alias and scope cases. Toggle tests prove a disabled guard blocks nothing; mutant
tests prove the probes can fail.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_hook_helpers import mark_slow_except, tiered  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hooks" / "git_rules_guard.py"
MARKER_DOC = "<blarai_project_instructions version='t'>x</blarai_project_instructions>\n"


def _git(cwd: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    r = subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True, text=True, check=True, env=env,
    )
    return r.stdout.strip()


def _mkrepo(path: Path, branch: str, blarai: bool = True) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("x")
    if blarai:
        (path / "CLAUDE.md").write_text(MARKER_DOC)
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "init")
    if branch != "main":
        _git(path, "checkout", "-q", "-b", branch)
    return path


def _stage(repo: Path, *rels: str) -> None:
    for rel in rels:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((p.read_text() if p.exists() else "") + "change")
    _git(repo, "add", *rels)


@pytest.fixture(scope="module")
def repos(tmp_path_factory):
    root = tmp_path_factory.mktemp("repos")
    r = {"root": root}
    r["main"] = _mkrepo(root / "main repo", "main")  # path with a space
    r["feat"] = _mkrepo(root / "feat", "feat/x")
    r["master"] = _mkrepo(root / "master", "main")
    _git(r["master"], "branch", "-m", "master")
    r["detached"] = _mkrepo(root / "detached", "main")
    _git(r["detached"], "checkout", "-q", "--detach")
    r["nonblarai"] = _mkrepo(root / "nonblarai", "main", blarai=False)
    # a REAL merge in progress on main
    m = _mkrepo(root / "merging", "feat/m")
    (m / "g.txt").write_text("g")
    _git(m, "add", "g.txt")
    _git(m, "commit", "-q", "-m", "feat work")
    _git(m, "checkout", "-q", "main")
    _git(m, "merge", "--no-ff", "--no-commit", "feat/m")
    r["merging"] = m
    # forged: MERGE_HEAD only, no MERGE_MODE
    f = _mkrepo(root / "forged", "main")
    _git(f, "checkout", "-q", "-b", "side")
    (f / "side.txt").write_text("s")
    _git(f, "add", "side.txt")
    _git(f, "commit", "-q", "-m", "side")
    side = _git(f, "rev-parse", "HEAD")
    _git(f, "checkout", "-q", "main")
    (f / ".git" / "MERGE_HEAD").write_text(side + "\n")  # resolves, not an ancestor, no MERGE_MODE
    r["forged"] = f
    # stale: a finished merge, MERGE_HEAD + MERGE_MODE re-planted pointing at merged history
    s = _mkrepo(root / "stale", "feat/s")
    (s / "g.txt").write_text("g")
    _git(s, "add", "g.txt")
    _git(s, "commit", "-q", "-m", "feat work")
    _git(s, "checkout", "-q", "main")
    _git(s, "merge", "--no-ff", "-q", "-m", "merge", "feat/s")
    (s / ".git" / "MERGE_HEAD").write_text(_git(s, "rev-parse", "feat/s") + "\n")
    (s / ".git" / "MERGE_MODE").write_text("no-ff\n")
    r["stale"] = s
    # forged-full: MERGE_HEAD (not an ancestor) AND MERGE_MODE both written by hand
    ff = _mkrepo(root / "forged_full", "main")
    _git(ff, "checkout", "-q", "-b", "side")
    (ff / "side.txt").write_text("s")
    _git(ff, "add", "side.txt")
    _git(ff, "commit", "-q", "-m", "side")
    side2 = _git(ff, "rev-parse", "HEAD")
    _git(ff, "checkout", "-q", "main")
    (ff / ".git" / "MERGE_HEAD").write_text(side2 + "\n")
    (ff / ".git" / "MERGE_MODE").write_text("no-ff\n")
    r["forged_full"] = ff
    # companion commits: staged sets on main
    r["comp_ok"] = _mkrepo(root / "comp_ok", "main")
    _stage(r["comp_ok"], "docs/journal_fragments/a.md", "docs/reviews/r.md", "LESSONS.md")
    r["comp_bad"] = _mkrepo(root / "comp_bad", "main")
    _stage(r["comp_bad"], "docs/reviews/r.md", "scripts/x.py")
    r["comp_code"] = _mkrepo(root / "comp_code", "main")
    _stage(r["comp_code"], "CLAUDE.md")
    r["comp_lookalike"] = _mkrepo(root / "comp_lookalike", "main")
    _stage(r["comp_lookalike"], "docs/reviews_evil/x.md")
    r["comp_feat"] = _mkrepo(root / "comp_feat", "feat/c")
    _stage(r["comp_feat"], "scripts/x.py")
    # aliases
    al = _mkrepo(root / "alias", "feat/a")
    _git(al, "config", "alias.aa", "add -A")
    _git(al, "config", "alias.ca", "commit -a")
    _git(al, "config", "alias.st", "status -s")
    _git(al, "config", "alias.sh", "!git add -A")
    r["alias"] = al
    return r


def run(command, cwd, tool="Bash", script=SCRIPT, env_extra=None, raw_stdin=None):
    env = {k: v for k, v in os.environ.items()
           if k != "BLARAI_GIT_RULES_OVERRIDE" and not k.startswith("GIT_")}
    env.setdefault("BLARAI_GIT_RULES_OVERRIDE_LOG", str(Path(str(cwd)) / "_override.log"))
    env.update(env_extra or {})
    payload = raw_stdin if raw_stdin is not None else json.dumps(
        {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd)})
    return subprocess.run([sys.executable, str(script)], input=payload, capture_output=True,
                          text=True, env=env, timeout=90)


def blocked(command, cwd, **kw):
    r = run(command, cwd, **kw)
    return r.returncode == 2, r


def _fmt(cmd, repos):
    return cmd.replace("{feat}", str(repos["feat"]).replace("\\", "/")).replace(
        "{main}", str(repos["main"]).replace("\\", "/"))


# ---- blanket staging: blocked wherever you are in a BlarAI repo ---------------------------
BLANKET = [
    "git add -A", "git add .", "git add --all", "git add -- .", "git add *",
    "git add -Av", "git add -fA", "git add ./", "git add :/", "git add ':/*'", "git add ':(top)'",
    "git add -u", "git add --update", "git add -uv", "git add --al", "git add --upd",
    "git add --no-ignore-removal", "git stage -A", "git stage .",
    "git commit -a -m x", "git commit -am 'x'", "git commit --all -m x", "git commit -sam x",
    "git commit --al -m x", "git commit -m x :/", "git commit -m x -- .", "git commit -m x *",
    "cd {feat} && git add -A", "git -C {feat} add -A", 'git -C "{feat}" add .',
    "echo hi; git add -A", "git status | cat && git add .", "true || git add --all",
    "GIT_AUTHOR_NAME=x git add -A", "git -c core.x=1 add -A", "(git add -A)",
    "bash -c 'git add -A'", 'pwsh -Command "git add -A"', "bash -ce 'git add -A'",
    "timeout 5 git add -A", "nice git add -A", "sudo git add .", "env GIT_X=1 git add -A",
    "command git add -A", "xargs git add -A", "eval git add -A", 'eval "git add -A"',
    "echo `git add -A`", "echo $(git add -A)", "echo 'git add -A' | bash",
    "bash <<'EOF'\ngit add -A\nEOF", "cmd /c git add -A", "/usr/bin/git add -A",
    "C:/Program Files/Git/cmd/git.exe add -A",
    "git aa", "git ca -m x", "git sh", "git -c alias.zz='add -A' zz",
]


FAST_BLANKET = ["git add -A", "git add .", "git add -u", "git add --al", "git stage -A", "git commit -am 'x'",
                "cd {feat} && git add -A", "bash -c 'git add -A'", "timeout 5 git add -A", "git aa",
                "git commit -m x :/", "echo `git add -A`"]


@pytest.mark.parametrize("cmd", tiered(BLANKET, FAST_BLANKET))
def test_blanket_forms_blocked(cmd, repos):
    cwd = repos["alias"] if cmd.split()[:2] in (["git", "aa"], ["git", "ca"], ["git", "sh"]) else repos["feat"]
    is_blocked, r = blocked(_fmt(cmd, repos), cwd)
    assert is_blocked, (cmd, r.stderr)
    assert "BLOCKED" in r.stderr


@pytest.mark.parametrize("cmd", tiered(["git add -A", "git -C '{feat}' add .", "git commit -am x",
                                        "Set-Location {feat}; git add --all", "& git add -A",
                                        "git add -u", "iex 'git add -A'", "Invoke-Expression 'git add .'",
                                        "Start-Process git -ArgumentList 'add -A'"], {0, 6}))
def test_blanket_forms_blocked_in_powershell(cmd, repos):
    assert blocked(_fmt(cmd, repos), repos["feat"], tool="PowerShell")[0], cmd


# ---- allowed: read-only git, explicit paths, the project's merge ritual ---------------------
ALLOW = [
    "git status", "git log --oneline main", "git diff --stat", "git show HEAD",
    "git add a.py b/c.py", "git add -- docs/x.md", "git add 'dir with space/f.md'",
    "git add -p x.py", "git add docs/.", "git add -N a.py", "git stage a.py", "git add --patch",
    "git commit -m 'msg'", "git commit -m \"fix: add -A handling\"",
    "git commit -m 'uses git add -A in prose' -- a.py",
    "git commit --verify -m x", "git commit -m '-a flag note'", "git commit -m $'don\\'t'",
    "git worktree add C:/Users/mrbla/blarai-wt-x -b feat/x main",
    "git merge --no-ff feat/x -m 'Merge feat/x'", "git merge --no-ff feat/x",
    "git checkout -b feat/new", "git branch --show-current", "git branch",
    "git switch -c feat/y", "git push origin feat/x", "git fetch", "git stash list",
    "ls -la && echo git add -A", "echo 'git add -A'", "grep -r 'git add -A' docs/",
    "grep -r git add docs/", "python -m pytest tests/security -q", "pip install gitpython",
    "cat .gitignore", "git-lfs version", "git st", "git -c alias.zz='status -s' zz",
    "git add a.py && git commit -m 'x'",
    "git commit -m \"$(cat <<'EOF'\nfeat: heredoc message\n\ngit add -A is forbidden\nDon't sweep.\n\nCo-Authored-By: X\nEOF\n)\"",
    "git add a.py\ngit commit -m \"$(cat <<'EOF'\nline with 'quote and \"dq\n\nEOF\n)\"",
    "eval \"$(ssh-agent)\"; git status", "cat <<'EOF'\ngit add -A\nEOF",
    "gh pr create --title 'git add -A rule' --body 'x'",
]


@pytest.mark.parametrize("cmd", ALLOW)
def test_allowed_on_feature_branch(cmd, repos):
    cwd = repos["alias"] if cmd.startswith("git st") else repos["feat"]
    is_blocked, r = blocked(cmd, cwd)
    assert not is_blocked, (cmd, r.stderr)


def test_non_shell_tools_and_non_git_untouched(repos):
    assert run("git add -A", repos["feat"], tool="Edit").returncode == 0
    assert run("echo hello", repos["main"]).returncode == 0
    assert run("", repos["main"]).returncode == 0


def test_powershell_merge_ritual_allowed(repos):
    for cmd in ["git add a.py; git commit -m 'x'", "git status", "git branch --show-current",
                "git commit -m @'\ngit add -A\n'@", "git merge --no-ff feat/x"]:
        assert not blocked(cmd, repos["feat"], tool="PowerShell")[0], cmd


# ---- scope: BlarAI repositories only ----------------------------------------------------------
def test_non_blarai_repo_passes_untouched(repos):
    nb = repos["nonblarai"]
    for cmd in ["git commit -m x", "git add -A", "git commit -am x", "git add -u && git commit -m x"]:
        assert not blocked(cmd, nb)[0], cmd


def test_dash_C_into_non_blarai_repo_from_blarai_cwd_passes(repos):
    assert not blocked(f"git -C '{repos['nonblarai']}' commit -m x", repos["feat"])[0]


def test_not_a_repository_passes(repos):
    assert not blocked("git commit -m x", repos["root"])[0]


def test_nonexistent_dir_under_blarai_tree_fails_closed(repos):
    feat = str(repos["feat"]).replace("\\", "/")
    is_blocked, r = blocked(f"cd {feat}/not-yet && git add -A", repos["main"])
    assert is_blocked and "does not exist yet" in r.stderr


def test_worktree_of_blarai_is_in_scope(repos, tmp_path):
    wt = tmp_path / "wt"
    _git(repos["feat"], "worktree", "add", "-q", str(wt), "-b", "feat/wt")
    assert blocked("git add -A", wt)[0]


# ---- commit on main --------------------------------------------------------------------------
def test_commit_on_main_blocked_when_nothing_staged_or_wrong_paths(repos):
    for key in ("main", "master", "comp_bad", "comp_code", "comp_lookalike"):
        is_blocked, r = blocked("git commit -m x", repos[key])
        assert is_blocked and "feature branch" in r.stderr, key
    assert blocked("git commit --no-edit", repos["main"])[0]


def test_commit_on_main_with_pathspecs_blocked(repos):
    assert blocked("git commit -m x -- f.txt", repos["comp_ok"])[0]
    assert blocked("git commit -m x f.txt", repos["comp_ok"])[0]


def test_companion_commit_on_main_allowed(repos):
    for cmd in ["git commit -m 'docs: journal'", "git commit --no-edit -m x",
                "git commit -m \"$(cat <<'EOF'\ndocs: x\nEOF\n)\""]:
        is_blocked, r = blocked(cmd, repos["comp_ok"])
        assert not is_blocked, (cmd, r.stderr)


def test_companion_message_names_the_allowlist_and_offender(repos):
    _, r = blocked("git commit -m x", repos["comp_bad"])
    assert "scripts/x.py" in r.stderr and "docs/journal_fragments/" in r.stderr


def test_companion_commit_must_not_stage_in_the_same_call(repos):
    is_blocked, r = blocked("git add LESSONS.md && git commit -m x", repos["comp_ok"])
    assert is_blocked and "separate calls" in r.stderr


def test_non_main_commit_with_code_allowed(repos):
    assert not blocked("git commit -m x", repos["comp_feat"])[0]


def test_allow_empty_on_main_blocked_even_with_merge(repos):
    assert blocked("git commit --allow-empty -m x", repos["main"])[0]
    assert blocked("git commit --allow-empty -m x", repos["merging"])[0]
    assert blocked("git commit --allow-empty -m x", repos["comp_ok"])[0]
    assert not blocked("git commit --allow-empty -m x", repos["feat"])[0]


def test_merge_state_never_allows_a_commit_on_main(repos):
    # No merge exception exists: a real, forged, forged-with-MERGE_MODE or stale merge state
    # all read the same as no merge. Merge commits come from `git merge`, never `git commit`.
    for key in ("merging", "forged", "forged_full", "stale"):
        for cmd in ("git commit --no-edit", "git commit -m 'Merge feat/m'"):
            is_blocked, r = blocked(cmd, repos[key])
            assert is_blocked and "main INTO the feature branch" in r.stderr, (key, cmd)


def test_clean_merge_on_main_is_not_a_commit(repos):
    assert not blocked("git merge --no-ff feat/m -m 'Merge feat/m'", repos["merging"])[0]


def test_merge_on_main_allowed(repos):
    assert not blocked("git merge --no-ff feat/x -m 'Merge'", repos["main"])[0]


def test_target_resolved_from_cd_and_dash_C(repos):
    main, feat = repos["main"], repos["feat"]
    assert blocked(f'git -C "{main}" commit -m x', feat)[0]
    assert blocked(f'cd "{main}" && git commit -m x', feat)[0]
    assert not blocked(f'git -C "{feat}" commit -m x', main)[0]
    assert not blocked(f'cd "{feat}" && git commit -m x', main)[0]
    assert blocked(f"git -C '{main}' commit -m x", feat)[0]


def test_msys_style_path(repos):
    p = str(repos["main"]).replace("\\", "/")
    msys = "/" + p[0].lower() + p[2:] if len(p) > 2 and p[1] == ":" else p
    assert blocked(f'cd "{msys}" && git commit -m x', repos["feat"])[0]


def test_push_location_moves_target_in_powershell(repos):
    assert blocked(f"Push-Location '{repos['main']}'; git commit -m x", repos["feat"], tool="PowerShell")[0]


def test_unknown_target_blocks(repos):
    for cmd, cwd in [("git commit -m x", repos["detached"]),
                     ('cd "$SOMEWHERE" && git commit -m x', repos["feat"]),
                     ("git --git-dir=/x/.git commit -m x", repos["feat"])]:
        is_blocked, r = blocked(cmd, cwd)
        assert is_blocked, cmd
        assert "cannot determine" in r.stderr, (cmd, r.stderr)


# ---- state drift: a commit is alone in its call ---------------------------------------------------
DRIFT = [
    "git checkout -b feat/q && git commit -m x", "git switch -c feat/q; git commit -m x",
    "git checkout - && git commit -m x", "git checkout main && git commit -m x",
    "git symbolic-ref HEAD refs/heads/main && git commit -m x",
    "git reset --soft HEAD~1 && git commit -m x", "git restore --staged a && git commit -m x",
    "git merge --no-commit feat/x && git commit -m x", "git merge --no-ff feat/x && git commit -m x",
    "git pull && git commit -m x", "git rebase main && git commit -m x",
    "git cherry-pick abc && git commit -m x", "git revert abc && git commit -m x",
    "git am p.patch && git commit -m x", "git stash pop && git commit -m x",
    "git stash apply && git commit -m x", "git worktree add ../w && git commit -m x",
    "git worktree remove ../w && git commit -m x", "git read-tree HEAD && git commit -m x",
    "git branch -f main HEAD && git commit -m x", "git branch -M x && git commit -m x",
    "git update-ref refs/heads/main HEAD && git commit -m x",
]


@pytest.mark.parametrize("cmd", tiered(DRIFT, {"git checkout -b feat/q && git commit -m x",
                                              "git merge --no-ff feat/x && git commit -m x",
                                              "git symbolic-ref HEAD refs/heads/main && git commit -m x"}))
def test_commit_sharing_a_call_with_a_state_change_blocked(cmd, repos):
    is_blocked, r = blocked(cmd, repos["feat"])
    assert is_blocked and "separate calls" in r.stderr, (cmd, r.stderr)


def test_state_changes_alone_are_allowed(repos):
    for cmd in ["git checkout -b feat/q", "git merge --no-commit feat/x", "git stash pop",
                "git worktree add ../w", "git reset --soft HEAD~1", "git branch -f x HEAD"]:
        assert not blocked(cmd, repos["feat"])[0], cmd


def test_add_then_commit_blocked_on_main_but_not_on_feature(repos):
    assert blocked("git add a.py && git commit -m x", repos["comp_ok"])[0]
    assert not blocked("git add a.py && git commit -m x", repos["feat"])[0]


def test_git_dir_family_blocks_commits(repos):
    feat = repos["feat"]
    for cmd, tool in [("GIT_DIR=../main/.git git commit -m x", "Bash"),
                      ("export GIT_DIR=../main/.git; git commit -m x", "Bash"),
                      ("GIT_WORK_TREE=. git commit -m x", "Bash"),
                      ("GIT_INDEX_FILE=/tmp/i git commit -m x", "Bash"),
                      ("$env:GIT_DIR = '../main/.git'; git commit -m x", "PowerShell")]:
        assert blocked(cmd, feat, tool=tool)[0], cmd
    is_blocked, r = blocked("git commit -m x", feat, env_extra={"GIT_DIR": str(repos["main"] / ".git")})
    assert is_blocked and "GIT_DIR" in r.stderr
    assert not blocked("git status", feat, env_extra={"GIT_DIR": str(feat / ".git")})[0]


# ---- fail closed -----------------------------------------------------------------------------
def test_unparseable_git_command_blocked(repos):
    is_blocked, r = blocked("git commit -m 'unterminated", repos["feat"])
    assert is_blocked and "fail-closed" in r.stderr


def test_unparseable_non_git_command_passes(repos):
    assert run("echo 'unterminated", repos["main"]).returncode == 0


def test_bad_stdin_blocked(repos):
    for raw in ("{not json", "[]", json.dumps({"tool_name": "Bash", "tool_input": "git add -A"})):
        r = run("x", repos["feat"], raw_stdin=raw)
        assert r.returncode == 2 and "fail-closed" in r.stderr, raw


# ---- override --------------------------------------------------------------------------------
def test_override_logs_and_allows(repos, tmp_path):
    log = tmp_path / "ov.log"
    env = {"BLARAI_GIT_RULES_OVERRIDE": "LA approved hotfix", "BLARAI_GIT_RULES_OVERRIDE_LOG": str(log)}
    r = run("git add -A", repos["feat"], env_extra=env)
    assert r.returncode == 0
    rec = json.loads(log.read_text().splitlines()[-1])
    assert rec["reason"] == "LA approved hotfix" and rec["rule"] == "blanket-add"
    assert rec["command"] == "git add -A"
    run("git commit -m x", repos["main"], env_extra=env)
    assert json.loads(log.read_text().splitlines()[-1])["rule"] == "commit-on-main"


def test_override_not_logged_when_allowed_anyway(repos, tmp_path):
    log = tmp_path / "ov2.log"
    run("git status", repos["feat"], env_extra={"BLARAI_GIT_RULES_OVERRIDE": "r",
                                                "BLARAI_GIT_RULES_OVERRIDE_LOG": str(log)})
    assert not log.exists()


def test_blank_override_ignored_and_command_text_cannot_self_override(repos, tmp_path):
    env = {"BLARAI_GIT_RULES_OVERRIDE": "   ", "BLARAI_GIT_RULES_OVERRIDE_LOG": str(tmp_path / "x.log")}
    assert run("git add -A", repos["feat"], env_extra=env).returncode == 2
    assert blocked("BLARAI_GIT_RULES_OVERRIDE=why git add -A", repos["feat"])[0]


def test_override_with_unwritable_log_stays_blocked(repos, tmp_path):
    bad = tmp_path / "afile"
    bad.write_text("x")
    env = {"BLARAI_GIT_RULES_OVERRIDE": "r", "BLARAI_GIT_RULES_OVERRIDE_LOG": str(bad / "sub" / "l.log")}
    assert run("git add -A", repos["feat"], env_extra=env).returncode == 2


# ---- wiring: .claude/settings.json is the only way the guard is reached ------------------------
def _hook_entry():
    cfg = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    # Exactly one PreToolUse entry runs the git guard; the doctrine-delivery hook (#1700)
    # is a separate entry with its own lock in test_doctrine_rules.py.
    entries = [e for e in cfg["hooks"]["PreToolUse"]
               if any("git_rules_guard.py" in h.get("command", "") for h in e.get("hooks", []))]
    assert len(entries) == 1
    return entries[0]


def test_settings_wiring_shape():
    e = _hook_entry()
    assert e["matcher"] == "Bash|PowerShell"
    h = e["hooks"][0]
    assert h["type"] == "command" and h["shell"] == "bash"
    assert "${CLAUDE_PROJECT_DIR" in h["command"] and "scripts/hooks/git_rules_guard.py" in h["command"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required to execute the hook command")
def test_settings_command_executes_the_guard_and_fails_closed_without_the_script(repos, tmp_path):
    cmd = _hook_entry()["hooks"][0]["command"]
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git add -A"},
                          "cwd": str(repos["feat"])})
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT).replace("\\", "/")}
    env.pop("BLARAI_GIT_RULES_OVERRIDE", None)
    r = subprocess.run(["bash", "-c", cmd], input=payload, capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2 and "BLOCKED" in r.stderr
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path).replace("\\", "/")  # script absent: fail CLOSED
    r = subprocess.run(["bash", "-c", cmd], input=payload, capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2 and "missing" in r.stderr
    r = subprocess.run(["bash", "-c", cmd], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}),
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2  # even an `ls`: a missing guard blocks the shell until restored
    env["BLARAI_GIT_RULES_OVERRIDE"] = "restore the guard"
    r = subprocess.run(["bash", "-c", cmd], input=payload, capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0


def test_option_tables_cover_real_git():
    out = {}
    for sub in ("add", "commit"):
        r = subprocess.run(["git", sub, "--git-completion-helper"], capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip("git completion helper unavailable")
        out[sub] = {o for o in r.stdout.split() if o.startswith("--") and o != "--"}
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import git_rules_guard as g
    finally:
        sys.path.pop(0)
    for sub, table in (("add", g._ADD_LONG), ("commit", g._COMMIT_LONG)):
        have = {o.rstrip("=") for o in table}
        missing = {o.rstrip("=") for o in out[sub]} - have
        assert not missing, (sub, missing)


# ---- toggle + mutants: the probes must be able to fail ----------------------------------------
def _variant(tmp_path: Path, name: str, old: str, new: str) -> Path:
    common = SCRIPT.parent / "rules_common.py"
    (tmp_path / "rules_common.py").write_text(common.read_text(encoding="utf-8"), encoding="utf-8")
    src = SCRIPT.read_text(encoding="utf-8")
    p = tmp_path / name
    if src.count(old) >= 1:
        p.write_text(src.replace(old, new, 1), encoding="utf-8")
    else:  # the anchor lives in the shared definitions
        csrc = common.read_text(encoding="utf-8")
        assert csrc.count(old) >= 1, f"mutation anchor missing: {old!r}"
        (tmp_path / "rules_common.py").write_text(csrc.replace(old, new, 1), encoding="utf-8")
        p.write_text(src, encoding="utf-8")
    return p


PROBES = [  # (command, repo key, expect_blocked)
    ("git add -A", "feat", True), ("git add .", "feat", True), ("git commit -am x", "feat", True),
    ("git add -Av", "feat", True), ("git add -u", "feat", True), ("git add --al", "feat", True),
    ("git commit -m x :/", "feat", True), ("git stage -A", "feat", True),
    ("timeout 5 git add -A", "feat", True), ("eval git add -A", "feat", True),
    ("git commit -m x", "main", True), ("git commit -m x", "master", True),
    ("git commit -m x", "detached", True), ("git commit --allow-empty -m x", "merging", True),
    ("git commit --no-edit", "forged", True), ("git commit -m x", "stale", True),
    ("git commit --no-edit", "forged_full", True),
    ("X=-A; git add $X", "feat", True), ("git add $(echo -A)", "feat", True),
    ("git commit -m x $(echo -a)", "feat", True), ("echo -A | xargs git add", "feat", True),
    ("git a{dd,} -A", "feat", True), (r"git ad\d -A", "feat", True),
    (r"git $'\x61dd' -A", "feat", True), ("git add -- -A", "feat", False), ('g"it" add -A', "feat", True),
    ("git commit -m \"$(cat <<'EOF'\nmsg\nEOF\n)\"", "feat", False),
    ("git commit -m x", "comp_bad", True), ("git commit -m x", "comp_lookalike", True),
    ("git checkout -b feat/q && git commit -m x", "feat", True),
    ("git add a.py && git commit -m x", "comp_ok", True),
    ("GIT_DIR=x git commit -m x", "feat", True), ("git aa", "alias", True),
    ("cd {feat}/missing && git add -A", "main", True),
    ("cd '{main}' && git commit -m x", "feat", True),
    ("git commit -m 'unterminated", "feat", True),
    ("git commit --no-edit", "merging", True), ("git add a.py", "feat", False),
    ("git commit -m '-a x'", "feat", False), ("git commit -m x", "comp_ok", False),
    ("git commit -m x", "nonblarai", False), ("git add -A", "nonblarai", False),
    ("git st", "alias", False), ("git commit -m x", "comp_feat", False),
]


def _verdicts(script, repos):
    from concurrent.futures import ThreadPoolExecutor

    def one(p):
        c, k, _ = p
        return run(_fmt(c, repos), repos[k], script=script).returncode == 2

    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(one, PROBES))


def test_probes_pass_on_real_script(repos):
    assert _verdicts(SCRIPT, repos) == [e for _, _, e in PROBES]


def test_toggle_disabled_guard_blocks_nothing(repos, tmp_path):
    off = _variant(tmp_path, "off.py", "ENABLED = True", "ENABLED = False")
    for cmd, key, _ in PROBES:
        assert run(_fmt(cmd, repos), repos[key], script=off).returncode == 0, cmd


MUTANTS = {
    "drop -A detection": ('if "A" in a or "u" in a or', 'if "Z" in a or "u" in a or'),
    "drop -u detection": ('if "A" in a or "u" in a or', 'if "A" in a or "Z" in a or'),
    "no abbreviation matching": ("    return [u for u in names if u.startswith(name)]", "    return [name]"),
    "main not protected": ('frozenset({"main", "master"})', 'frozenset({"trunk"})'),
    "dynamic add args ignored": ('        if DYN in a:\n            return a.replace(DYN, "<expansion>")', "        if False:\n            return a"),
    "dynamic commit args ignored": ("            if flags.dynamic:", "            if False:"),
    "stdin args ignored": ('if inv.sub in ("add", "commit") and inv.piped_args and in_scope(inv.dir):', "if False:"),
    "brace expansion literal": ('if j < n and cmd[j] == "}" and ("," in cmd[i + 1:j] or ".." in cmd[i + 1:j]):', "if False:"),
    "literal-git prefilter": ('        analyze(cmd, shell, cwd)\n        return 0, ""',
                              '        if "git" not in cmd.lower():\n            return 0, ""\n        analyze(cmd, shell, cwd)\n        return 0, ""'),
    "ansi-c not decoded": ('elif e == "x":', 'elif e == "Q":'),
    "double dash flags still flags": ('        elif a == "--":\n            only_paths = True\n        elif a.startswith("--"):\n            if set(', '        elif a == "--":\n            pass\n        elif a.startswith("--"):\n            if set('),
    "unparseable fails open": ('    if quote:\n        raise Unparseable("unbalanced quote")', "    if False:\n        pass"),
    "dot not blanket": (r'^(?:\./?|', r'^(?:\.\./?|'),
    "any staged path accepted": ("if changes and not problems:", "if changes:"),
    "state drift ignored": ("if _is_state_op(other) or (other.sub == \"add\" and on_main):", "if False:"),
    "env drift ignored": ('if inv.drift or any(v in os.environ for v in DRIFT_ENV_VARS):', "if False:"),
    "scope ignored": ("scoped = rules_common.commit_scope(lambda a: _run_git(probe, *a))", "scoped = True"),
    "wrapper scan limited to head": ("        for j, t in enumerate(tokens):\n            if _git_head(t):", "        for j, t in enumerate(tokens[:1]):\n            if _git_head(t):"),
    "alias lookup off": ('r = _run_git(inv.dir, "config", "--get-regexp", r"^alias\\.")', 'r = subprocess.CompletedProcess([], 1, "", "")'),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_mutant_is_caught(name, repos, tmp_path):
    old, new = MUTANTS[name]
    mutant = _variant(tmp_path, "mut.py", old, new)
    assert _verdicts(mutant, repos) != [e for _, _, e in PROBES], f"mutant survived: {name}"


mark_slow_except(globals(), {
    "test_blanket_forms_blocked", "test_blanket_forms_blocked_in_powershell", "test_allowed_on_feature_branch",
    "test_non_shell_tools_and_non_git_untouched", "test_powershell_merge_ritual_allowed",
    "test_non_blarai_repo_passes_untouched", "test_commit_on_main_blocked_when_nothing_staged_or_wrong_paths",
    "test_companion_commit_on_main_allowed", "test_merge_state_never_allows_a_commit_on_main",
    "test_commit_sharing_a_call_with_a_state_change_blocked", "test_git_dir_family_blocks_commits",
    "test_unparseable_git_command_blocked", "test_unparseable_non_git_command_passes", "test_bad_stdin_blocked",
    "test_override_logs_and_allows", "test_blank_override_ignored_and_command_text_cannot_self_override",
    "test_override_with_unwritable_log_stays_blocked", "test_settings_wiring_shape",
    "test_settings_command_executes_the_guard_and_fails_closed_without_the_script",
    "test_option_tables_cover_real_git", "test_probes_pass_on_real_script", "test_toggle_disabled_guard_blocks_nothing",
})
