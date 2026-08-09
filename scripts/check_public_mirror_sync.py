"""
BlarAI public-mirror bookkeeping-drift check
=============================================
The public snapshot publisher tracks "what was last actually published" in a
local bookkeeping ref (default ``refs/public-snapshots/main``) rather than
trusting the remote's tip directly. That ref only advances when the publisher
itself runs; anything else that moves the remote (a hand-patched fix pushed
via a temp worktree, a partially-failed prior push) leaves it pointing at a
stale commit. The next scheduled publish then fails non-fast-forward, and
because that failure surfaces only as Task Scheduler's ``LastTaskResult``,
nothing else ever reads, it can sit unnoticed for days (Vikunja #1104).

This script makes that drift observable on demand: it resolves the
bookkeeping ref, resolves the remote's actual tip, and reports whether they
agree. It does not publish anything and does not modify the bookkeeping ref -
realigning it is a deliberate act (see the fix recipe in the DRIFT report),
not something this tool does for you.

Exit code: 0 when the bookkeeping ref matches the remote tip (or when
``--no-fetch`` is used and the cached remote-tracking ref matches). Non-zero
on drift, on a resolution failure, or if git itself cannot be reached -
fail-closed: an inconclusive check is never reported as "in sync".

Usage (from repo root, or anywhere with --repo):
  python scripts/check_public_mirror_sync.py
  python scripts/check_public_mirror_sync.py --repo C:/Users/mrbla/BlarAI
  python scripts/check_public_mirror_sync.py --remote public --remote-branch main \\
      --bookkeeping-ref refs/public-snapshots/main
  python scripts/check_public_mirror_sync.py --no-fetch   # use cached remote-tracking refs
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_GIT_TIMEOUT_S = 30.0
_FETCH_TIMEOUT_S = 120.0


def _run_git(args: list[str], repo: Path, timeout: float = _GIT_TIMEOUT_S) -> tuple[int, str, str]:
    """Run ``git <args>`` in *repo*. Returns ``(returncode, stdout, stderr)``.

    A git invocation that cannot even start (missing git, bad cwd, timeout) is
    reported as returncode ``-1`` with the exception text in stderr - never a
    silent ``None``, so every caller has an explicit failure to report.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", f"git could not run: {exc}"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def resolve_ref(ref: str, repo: Path) -> tuple[str | None, str]:
    """Resolve *ref* to a commit SHA. Returns ``(sha, detail)``.

    ``sha`` is ``None`` if the ref does not exist or does not dereference to a
    commit - a missing ref is reported as such, never silently treated as
    "up to date" or skipped.
    """
    code, out, err = _run_git(
        ["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"], repo
    )
    if code != 0:
        return None, err or f"ref {ref!r} does not resolve to a commit"
    return out, ""


def fetch_remote(remote: str, repo: Path) -> tuple[bool, str]:
    """Fetch *remote* into *repo*'s remote-tracking refs. Returns ``(ok, detail)``."""
    # '--' marks *remote* as the repository argument even if it starts with
    # '-' (e.g. a CLI-supplied --remote value) - a remote name is data, never
    # a flag, regardless of what it looks like.
    code, _out, err = _run_git(["fetch", "--", remote], repo, timeout=_FETCH_TIMEOUT_S)
    if code != 0:
        return False, err or f"git fetch {remote!r} failed (exit {code})"
    return True, ""


def commits_between(base: str, tip: str, repo: Path) -> int | None:
    """Count commits reachable from *tip* but not *base*. ``None`` if git could
    not compute it - the caller must not treat that as zero."""
    code, out, _err = _run_git(["rev-list", "--count", f"{base}..{tip}"], repo)
    if code != 0 or not out.isdigit():
        return None
    return int(out)


def _drift_description(bookkeeping_sha: str, remote_sha: str, repo: Path) -> str:
    """Describe how *bookkeeping_sha* and *remote_sha* differ, in commit counts
    where derivable. Never guesses a direction it has not measured."""
    behind = commits_between(bookkeeping_sha, remote_sha, repo)
    ahead = commits_between(remote_sha, bookkeeping_sha, repo)
    if behind is None or ahead is None:
        return "differ by an unknown number of commits (count derivation failed)"
    if behind and ahead:
        return f"diverged ({behind} behind, {ahead} ahead)"
    if behind:
        return f"{behind} commit(s) behind"
    if ahead:
        return f"{ahead} commit(s) ahead"
    return "differ (unexpected: zero commits either direction)"


def check_sync(
    repo: Path,
    remote: str,
    remote_branch: str,
    bookkeeping_ref: str,
    do_fetch: bool = True,
) -> tuple[bool, str]:
    """Check whether *bookkeeping_ref* matches *remote*/*remote_branch*.

    Returns ``(in_sync, report)`` - *report* is always a human-readable
    summary, whether in sync or not, so a caller always has something to
    print or log. Fail-closed throughout: any resolution failure reports
    NOT in sync rather than being skipped or treated as success.
    """
    if do_fetch:
        ok, detail = fetch_remote(remote, repo)
        if not ok:
            return False, f"could not fetch {remote!r}: {detail}"

    bookkeeping_sha, bk_detail = resolve_ref(bookkeeping_ref, repo)
    if bookkeeping_sha is None:
        return False, (
            f"bookkeeping ref {bookkeeping_ref!r} does not resolve ({bk_detail}) - "
            f"either nothing has been published yet, or the ref is missing/corrupted"
        )

    remote_ref = f"{remote}/{remote_branch}"
    remote_sha, rm_detail = resolve_ref(remote_ref, repo)
    if remote_sha is None:
        return False, f"{remote_ref!r} does not resolve ({rm_detail})"

    if bookkeeping_sha == remote_sha:
        return True, f"in sync: {bookkeeping_ref} == {remote_ref} @ {bookkeeping_sha[:8]}"

    drift = _drift_description(bookkeeping_sha, remote_sha, repo)
    return False, (
        f"DRIFT: {bookkeeping_ref} @ {bookkeeping_sha[:8]} is {drift} of "
        f"{remote_ref} @ {remote_sha[:8]}.\n"
        f"The next scheduled publish will fail non-fast-forward until this is "
        f"realigned:\n"
        f"  git -C {repo} fetch {remote}\n"
        f"  git -C {repo} update-ref {bookkeeping_ref} {remote_sha}\n"
        f"(only after confirming the tree at {remote_sha} is really what the new "
        f"baseline should be - see Vikunja #1104 for the desync history and the "
        f"leak-gate interaction)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check whether a public-mirror bookkeeping ref matches the remote's actual tip."
    )
    parser.add_argument("--repo", type=Path, default=Path("."), help="Repository root (default: cwd)")
    parser.add_argument("--remote", default="public", help="Public mirror remote name (default: public)")
    parser.add_argument(
        "--remote-branch", default="main", help="Branch on the remote to compare against (default: main)"
    )
    parser.add_argument(
        "--bookkeeping-ref",
        default="refs/public-snapshots/main",
        help="Local ref tracking the last thing actually published (default: refs/public-snapshots/main)",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip 'git fetch' and compare against whatever remote-tracking refs are already present",
    )
    args = parser.parse_args(argv)

    in_sync, report = check_sync(
        repo=args.repo,
        remote=args.remote,
        remote_branch=args.remote_branch,
        bookkeeping_ref=args.bookkeeping_ref,
        do_fetch=not args.no_fetch,
    )
    print(report)
    return 0 if in_sync else 1


if __name__ == "__main__":
    sys.exit(main())
