#!/usr/bin/env python
"""Prove the commit protection works end to end, in plain PASS/FAIL lines.

  python scripts/prove_commit_protection.py                     dry run in a TEMPORARY repository
  python scripts/prove_commit_protection.py --live --i-am-the-lead
                                                                 also check THIS repository's install,
                                                                 then run the same proof against main's tip

The proof (in a throwaway repository, never in yours): install; --check OK; a code commit on main
is refused; a companion commit is allowed; `git merge --no-ff` from a worktree on main is allowed;
the previous hooks directory's post-commit hook still fires; --uninstall restores the previous
core.hooksPath. `--live` never changes the current repository: it runs `--check` and `--status`
there (read-only) and then repeats the temporary-repository proof with the hook files taken from
THIS repository's main tip, so what is proven is what main will install.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("scripts/install_git_hooks.py", "scripts/hooks/rules_common.py", "scripts/hooks/git_native_pre_commit.py",
         "scripts/hooks/reference_transaction.py")
IDENT = ["-c", "user.name=prove", "-c", "user.email=prove@example.invalid"]


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "BLARAI_GIT_RULES_OVERRIDE"}


def git(repo: Path, *args: str, hooks: bool = True) -> subprocess.CompletedProcess:
    pre = [] if hooks else ["-c", "core.hooksPath=__no_hooks__"]
    return subprocess.run(["git", "-C", str(repo), *IDENT, *pre, *args], capture_output=True, text=True, env=_env())


def source_files(live_repo: Path | None) -> dict[str, bytes]:
    """The hook files to put on the temporary repo's main: this checkout's files, or live main's tip."""
    names = list(FILES) + [f"scripts/githooks/{p.name}" for p in sorted((ROOT / "scripts" / "githooks").iterdir())]
    out: dict[str, bytes] = {}
    for n in names:
        if live_repo is None:
            out[n] = (ROOT / n).read_bytes()
        else:
            r = subprocess.run(["git", "-C", str(live_repo), "show", f"main:{n}"], capture_output=True, env=_env())
            if r.returncode != 0:
                raise SystemExit(f"main of {live_repo} lacks {n}: the hooks are not on main yet")
            out[n] = r.stdout
    return out


def proof(files: dict[str, bytes], keep: bool) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    tmp = Path(tempfile.mkdtemp(prefix="prove-commit-protection-"))

    def rec(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    try:
        repo = tmp / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        for rel, data in files.items():
            dst = repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
        (repo / "f.txt").write_text("x")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "init", hooks=False)
        marker = tmp / "post-commit-ran.txt"
        prev = tmp / "previous hooks"
        prev.mkdir()
        hook = prev / "post-commit"
        hook.write_text(f'#!/bin/sh\necho fired >> "{marker.as_posix()}"\n', newline="\n")
        hook.chmod(0o755)
        git(repo, "config", "core.hooksPath", str(prev))
        installer = [sys.executable, str(repo / "scripts" / "install_git_hooks.py"), "--repo", str(repo)]
        inst = subprocess.run(installer, capture_output=True, text=True, env=_env())
        rec("install", inst.returncode == 0, inst.stdout.strip() or inst.stderr.strip())
        chk = subprocess.run(installer + ["--check"], capture_output=True, text=True, env=_env())
        rec("--check reports OK", chk.returncode == 0, chk.stdout.strip())

        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("x = 1\n")
        git(repo, "add", "src/a.py")
        r = git(repo, "commit", "-q", "-m", "code on main")
        rec("a code commit on main is refused", r.returncode != 0 and "BLOCKED" in r.stderr, r.stderr.strip()[-160:])
        git(repo, "reset", "-q")
        (repo / "src" / "a.py").unlink()

        (repo / "docs" / "reviews").mkdir(parents=True)
        (repo / "docs" / "reviews" / "r.md").write_text("review\n")
        git(repo, "add", "docs/reviews/r.md")
        r = git(repo, "commit", "-q", "-m", "companion")
        rec("a companion commit on main is allowed", r.returncode == 0, r.stderr.strip()[-160:])
        rec("the previous hooks dir's post-commit still fires", marker.exists(), str(marker))

        git(repo, "checkout", "-q", "-b", "feat/x", hooks=False)
        (repo / "services").mkdir()
        (repo / "services" / "app.py").write_text("y = 2\n")
        git(repo, "add", "services/app.py")
        git(repo, "commit", "-q", "-m", "feature work", hooks=False)
        wt = tmp / "wt"
        git(repo, "worktree", "add", "-q", str(wt), "main", hooks=False)
        r = git(wt, "merge", "--no-ff", "-q", "-m", "Merge feat/x", "feat/x")
        rec("`git merge --no-ff` from a worktree on main is allowed", r.returncode == 0, r.stderr.strip()[-160:])

        un = subprocess.run(installer + ["--uninstall"], capture_output=True, text=True, env=_env())
        now = git(repo, "config", "--get", "core.hooksPath").stdout.strip()
        rec("--uninstall restores the previous hooks path", un.returncode == 0 and now == str(prev), f"now {now!r}")
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"(kept {tmp})")
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="also check this repository's install (read-only)")
    ap.add_argument("--i-am-the-lead", action="store_true", help="required with --live")
    ap.add_argument("--keep", action="store_true", help="keep the temporary repository")
    a = ap.parse_args(argv)
    if a.live and not a.i_am_the_lead:
        print("--live is for the lead only: pass --i-am-the-lead")
        return 2
    results: list[tuple[str, bool, str]] = []
    live_repo = None
    if a.live:
        live_repo = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                                        cwd=str(ROOT)).stdout.strip())
        inst = [sys.executable, str(ROOT / "scripts" / "install_git_hooks.py"), "--repo", str(live_repo)]
        c = subprocess.run(inst + ["--check"], capture_output=True, text=True, env=_env())
        results.append(("LIVE: --check on this repository", c.returncode == 0, c.stdout.strip()))
        s = subprocess.run(inst + ["--status"], capture_output=True, text=True, env=_env())
        print(s.stdout.strip())
    results += proof(source_files(live_repo), a.keep)
    failed = 0
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok or not detail else f"  [{detail}]"))
        failed += not ok
    print("ALL PASS" if not failed else f"{failed} FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
