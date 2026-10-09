#!/usr/bin/env python
# enforces-rule: git_discipline.absolute_rules.never-commit-work-directly-to-main -- runs inside git (core.hooksPath), so no parser differential; off when core.hooksPath is not set
"""Git-native pre-commit guard: no work commits on main.

Runs inside git itself for every `git commit` in a repository whose core.hooksPath points at
scripts/githooks (scripts/install_git_hooks.py sets it). Scope is the repository
identity recorded at install (git common dir + root commit), never CLAUDE.md content and never HEAD;
ANY inconsistency between the install record and this repository blocks (the hooks only run for it).
On main/master it requires:
  * the INSTALLED guard files (<git-common-dir>/blarai-hooks) to equal the recorded hashes;
  * a non-empty staged set made only of companion changes (rules_common: allowlisted paths, data
    and prose extensions, plain 100644 files, size cap, safe path shape).
Anything else exits 1 and git aborts the commit. Clean merges (`git merge --no-ff`) never run
pre-commit; the reference-transaction hook judges every update of main.

Fail direction: CLOSED. Any internal error, detached HEAD, unborn main (scope unreadable), or
unreadable repository state in a BlarAI repository exits 1. A repository whose HEAD positively
holds no BlarAI marker exits 0.

Override: BLARAI_GIT_RULES_OVERRIDE=<reason> in the process environment allows the commit and
appends to the override log (BLARAI_GIT_RULES_OVERRIDE_LOG).

Limits: the hook is OFF wherever core.hooksPath is unset or points elsewhere, and `git commit
--no-verify` skips it (the PreToolUse text guard blocks that flag; git itself cannot).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rules_common as rc  # noqa: E402

INSTALL = Path(__file__).resolve().parents[1]  # <git-common-dir>/blarai-hooks (the INSTALLED copy)
COMMON = INSTALL.parent

ROUTE = ("Work goes on a feature branch (git checkout -b <branch>, or a worktree) and lands on "
         "main with `git merge --no-ff <branch>` (never fast-forward). To resolve a conflict, "
         "merge main INTO the feature branch first, on the branch.")


def _run(args: list[str], input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=30,
                          encoding="utf-8", errors="replace", input=input)


def check() -> tuple[int, str, str]:
    """(exit code, message, rule). 0 = allow."""
    rec = rc.load_record(COMMON)
    head = _run(["symbolic-ref", "-q", "--short", "HEAD"])
    branch = head.stdout.strip() if head.returncode == 0 else ""
    if _run(["rev-parse", "-q", "--verify", "HEAD^{commit}"]).returncode != 0:  # unborn HEAD
        if branch in rc.PROTECTED_BRANCHES:
            return 1, (f"first commit on unborn '{branch}' is refused. Start on a feature branch."), "unborn-main"
        return 0, "", ""
    if not branch:
        return 1, "cannot determine the current branch (detached HEAD); commit on a branch.", "branch-unknown"
    if branch not in rc.PROTECTED_BRANCHES:
        return 0, "", ""
    broken = rc.record_problems(_run, rec, INSTALL)
    if broken:
        return 1, (rc.MISMATCH + ":\n  " + "\n  ".join(broken[:12])), "record-mismatch"
    changes, problems = rc.staged_problems(_run)
    if not changes:
        return 1, (f"empty commit on '{branch}' (nothing staged, or --allow-empty). Commits on "
                   f"{branch} carry companion files only."), "commit-on-main"
    if problems:
        shown = "\n  ".join(problems[:15]) + ("\n  ..." if len(problems) > 15 else "")
        return 1, (f"commit on '{branch}' contains changes that are not companion changes:\n  {shown}\n"
                   f"{ROUTE} Companion commits touch only: {', '.join(rc.COMPANION_ALLOWLIST)} "
                   "(plain data/prose files)."), "commit-on-main"
    return 0, "", ""


def main() -> int:
    try:
        code, message, rule = check()
    except BaseException as exc:  # noqa: BLE001 - fail closed on anything
        code, message, rule = 1, f"git-native pre-commit guard fault ({type(exc).__name__}: {exc}); refusing.", "guard-error"
    if code == 0:
        return 0
    reason = rc.override_reason()
    if reason:
        try:
            rc.log_override(reason, "git commit (pre-commit hook)", rule)
        except BaseException as exc:  # noqa: BLE001
            message += f"\nOverride set but the override log failed ({type(exc).__name__}); refusing."
        else:
            sys.stderr.write(f"git-rules pre-commit OVERRIDDEN ({rule}): {reason}\n")
            return 0
    try:
        sys.stderr.buffer.write(("BLOCKED by the git-native pre-commit guard "
                                 "(scripts/hooks/git_native_pre_commit.py).\n" + message + "\n"
                                 f"Operator override (set by hand, logged): {rc.OVERRIDE_ENV}=<reason>\n"
                                 ).encode("utf-8", errors="replace"))
        sys.stderr.flush()
    except BaseException:  # noqa: BLE001
        pass
    return 1


if __name__ == "__main__":
    _code = main()
    if _code == 0:
        sys.stdout.buffer.write((rc.allow_token(__file__) + "\n").encode("ascii"))  # bytes: no CRLF translation
        sys.stdout.buffer.flush()
    os._exit(_code)
