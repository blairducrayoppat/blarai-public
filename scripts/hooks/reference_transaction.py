#!/usr/bin/env python
# enforces-rule: git_discipline.absolute_rules.never-commit-work-directly-to-main -- git reference-transaction hook: judges every update of refs/heads/main|master (merge --no-ff, companion commits only); off when core.hooksPath is not set
"""Git-native reference-transaction guard: the only ways main moves.

git runs this hook (state `prepared`, stdin lines `<old> <new> <ref>`) before any reference
transaction is committed; a non-zero exit aborts it. For updates to refs/heads/main|master in a
BlarAI repository (scope = the identity recorded at install) an update is allowed only if
  (a) the new commit is a TWO-parent merge commit whose first parent is the old value, whose
      second parent is on a local non-main branch, and whose tree equals what `git merge-tree
      --write-tree old second` produces (what `git merge --no-ff` makes: no octopus, no
      unrelated histories, no hand-resolved or smuggled changes, no `-s ours`), or
  (b) old is an ancestor of new and every commit in old..new has exactly one parent and changes
      only companion paths (rules_common: allowlist, data/prose extensions, plain 100644
      files, size cap, safe path shape), or
  (c) the override variable is set (logged).
Deleting main, creating main, rewinding or rewriting it, and every other route (fast-forward
merge, cherry-pick, revert, am, rebase, pull, commit-tree + update-ref, branch -f,
push . HEAD:main, merge --squash + commit) abort the transaction. The hook files in the working
tree must equal the blobs of main's old tip. Only refs/heads/main|master are judged.

Fail direction: CLOSED. Any internal error exits 1. A repository whose HEAD positively holds no
BlarAI marker exits 0; an unborn HEAD cannot be scoped and is refused for main updates.

Scope is the repository identity recorded at install, not CLAUDE.md content and not HEAD; a
deletion or `-f` update (old value all-zero) is judged from the ref's real current value.
Ref names are matched case-insensitively. Off wherever core.hooksPath is unset.
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

ROUTE = ("Work lands on main only by `git merge --no-ff <branch>` (never fast-forward, cherry-pick, "
         "revert, am, rebase, pull or ref plumbing); companion-only commits (docs/journal "
         "fragments, ledger, reviews, ...) are also allowed. To resolve a conflict, merge main INTO "
         "the feature branch first, on the branch. If git was running a merge, pull, cherry-pick or "
         "revert it has ALREADY updated your files: run `git reset --merge` (it keeps your own "
         "uncommitted edits), then `git merge --no-ff <branch>`.")


def _run(args: list[str], input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=30,
                          encoding="utf-8", errors="replace", input=input)


def _short(oid: str) -> str:
    return oid[:10]


def _judge_merge(old: str, new: str, parents: list[str]) -> str | None:
    """(a): None only for a merge commit that `git merge --no-ff <second parent>` would have made."""
    if len(parents) != 3:
        return f"merge commit {_short(new)} has {len(parents) - 1} parents; octopus merges are not allowed."
    second = parents[2]
    contains = _run(["for-each-ref", "--contains", second, "--format=%(refname)", "refs/heads"])
    if contains.returncode != 0:
        raise RuntimeError("cannot list the branches containing the second parent")
    branches = [r for r in contains.stdout.split() if r.lower() not in rc.PROTECTED_REFS]
    if not branches:
        return (f"the second parent {_short(second)} of merge commit {_short(new)} is on no local "
                "non-main branch (merge a branch, not a loose commit).")
    mt = _run(["merge-tree", "--write-tree", "--no-messages", old, second])
    first = mt.stdout.split("\n", 1)[0].strip()
    if mt.returncode != 0 or not first:
        return (f"merge commit {_short(new)} cannot be reproduced by `git merge {_short(second)}` "
                "(conflicts, unrelated histories, or an unreadable merge); resolve conflicts on the "
                "feature branch by merging main into it, then merge the branch.")
    tree = _run(["rev-parse", f"{new}^{{tree}}"]).stdout.strip()
    if tree != first:
        return (f"merge commit {_short(new)} does not equal the merge of its parents (its tree "
                "differs from `git merge-tree`): changes smuggled into a merge, `-s ours`, or a "
                "hand-edited merge are not allowed.")
    return None


def _is_pack_refs_prune(old: str, ref: str) -> bool:
    """`git pack-refs` / `git gc` delete the LOOSE ref after writing it to packed-refs: the ref keeps
    its value. That shows as old -> zero with packed-refs already holding `old ref` and no
    packed-refs.lock (a real deletion of a packed ref holds that lock while it is prepared)."""
    common = _run(["rev-parse", "--path-format=absolute", "--git-common-dir"]).stdout.strip()
    if not common:
        return False
    packed = Path(common) / "packed-refs"
    if (Path(common) / "packed-refs.lock").exists() or not packed.is_file():
        return False
    want = f"{old} {ref}"
    return any(line.strip() == want for line in packed.read_text(encoding="utf-8", errors="replace").splitlines())


def judge(old: str, new: str, ref: str) -> str | None:
    """None if the update of `ref` is allowed, else the reason (naming commit and route)."""
    if new == rc.ZERO_OID and old != rc.ZERO_OID and _is_pack_refs_prune(old, ref):
        return None
    if new == rc.ZERO_OID:
        return f"deleting {ref} is not allowed (git branch -d/-D/-m, update-ref -d)."
    if old == rc.ZERO_OID:
        return f"creating {ref} at {_short(new)} cannot be verified (git branch main, first commit)."
    parents = _run(["rev-list", "--parents", "-n", "1", new]).stdout.split()
    if not parents:
        raise RuntimeError(f"cannot read commit {_short(new)}")
    if len(parents) >= 3 and parents[1] == old:
        return _judge_merge(old, new, parents)
    if _run(["merge-base", "--is-ancestor", old, new]).returncode != 0:
        return (f"{ref} would move from {_short(old)} to {_short(new)}, which is not a descendant "
                "(history rewrite, reset, rebase).")
    listing = _run(["rev-list", "--reverse", "--parents", f"{old}..{new}"])
    if listing.returncode != 0:
        raise RuntimeError("cannot list the commits of the update")
    for line in listing.stdout.splitlines():
        ids = line.split()
        if len(ids) != 2:
            return (f"commit {_short(ids[0])} on the way to {ref} has {len(ids) - 1} parents; "
                    "only single-parent companion commits or a --no-ff merge commit may land.")
        _, problems = rc.commit_problems(_run, ids[0], has_parent=True)
        if problems:
            return (f"commit {_short(ids[0])} would land on {ref} but is not a companion commit:\n  "
                    + "\n  ".join(problems[:10]))
    return None


def check(state: str, stdin: str) -> tuple[int, str, str]:
    if state != "prepared":
        return 0, "", ""
    entries = [ln.rstrip("\r").split(" ", 2) for ln in stdin.splitlines() if ln.strip()]
    judged = [e for e in entries if len(e) == 3 and e[2].strip().lower() in rc.PROTECTED_REFS]
    if not judged:
        return 0, "", ""
    rec = rc.load_record(COMMON)
    broken = rc.record_problems(_run, rec, INSTALL)
    if broken:
        return 1, (rc.MISMATCH + ":\n  " + "\n  ".join(broken[:12])), "record-mismatch"
    for old, new, ref in judged:
        ref = ref.strip()
        if old == rc.ZERO_OID:  # an unspecified old value (`branch -f`, a deletion): the ref's real tip
            cur = _run(["rev-parse", "-q", "--verify", ref])
            if cur.returncode == 0 and cur.stdout.strip():
                old = cur.stdout.strip()
        why = judge(old, new, ref)
        if why:
            return 1, f"{why}\n{ROUTE}", "ref-update-main"
    return 0, "", ""


def main() -> int:
    state = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        code, message, rule = check(state, sys.stdin.read())
    except BaseException as exc:  # noqa: BLE001 - fail closed on anything
        code, message, rule = 1, f"git reference-transaction guard fault ({type(exc).__name__}: {exc}); refusing.", "guard-error"
    if code == 0:
        return 0
    reason = rc.override_reason()
    if reason:
        try:
            rc.log_override(reason, "git reference-transaction", rule)
        except BaseException as exc:  # noqa: BLE001
            message += f"\nOverride set but the override log failed ({type(exc).__name__}); refusing."
        else:
            sys.stderr.write(f"git-rules reference-transaction OVERRIDDEN ({rule}): {reason}\n")
            return 0
    try:
        sys.stderr.buffer.write(("BLOCKED by the git-native reference-transaction guard "
                                 "(scripts/hooks/reference_transaction.py).\n" + message + "\n"
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
