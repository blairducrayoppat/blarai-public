"""Shared helpers for the git-native hook tests (real git, temp repos, the real installer)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "install_git_hooks.py"
GUARD = ROOT / "scripts" / "hooks" / "git_rules_guard.py"
MARKER_DOC = "<blarai_project_instructions>x</blarai_project_instructions>\n"
HOOK_FILES = tuple(
    sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "scripts" / "githooks").iterdir())
) + (
    "scripts/hooks/git_native_pre_commit.py", "scripts/hooks/reference_transaction.py",
    "scripts/hooks/rules_common.py", "scripts/hooks/git_rules_guard.py",
    "scripts/install_git_hooks.py", ".claude/settings.json",
)


def env(extra=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "BLARAI_GIT_RULES_OVERRIDE"}
    e.update(extra or {})
    return e


def git(repo, *args, env_extra=None, check=False):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True, env=env(env_extra), check=check, timeout=120)


def quiet(repo, *args, check=True):
    """git with hooks switched off: fixture setup only, never the behaviour under test."""
    return git(repo, "-c", "core.hooksPath=__no_hooks__", *args, check=check)


def installer(repo, *flags):
    return subprocess.run([sys.executable, str(INSTALLER), "--repo", str(repo), *flags],
                          capture_output=True, text=True, env=env(), timeout=120)


def approved(repo, reason="test", *flags, plain=False, run=None):
    """The two-step --update the lead performs: a dry run prints the review and its DIGEST, then the same command
    with --reason and --approve <digest>. Returns the dry run itself when there is nothing to approve."""
    run = run or installer
    base = () if plain else ("--update",)
    dry = run(repo, *base, "--dry-run")
    m = re.search(r"^DIGEST: ([0-9a-f]{64})$", dry.stdout, re.M)
    if not m:
        return run(repo, "--reason", reason, *flags) if plain and "dry run: would install" in dry.stdout else dry
    return run(repo, *base, "--reason", reason, "--approve", m.group(1), *flags)


def make_repo(tmp: Path, name: str, *, branch="main", trunk="main", blarai=True, install=True, edits=(),
              pre_install=None) -> Path:
    """A repo whose initial commit holds CLAUDE.md and every hook file, on `trunk`; optionally
    switched to `branch` (or detached) after the real installer ran."""
    repo = tmp / name
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", trunk, check=True)
    for rel in HOOK_FILES:
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, dst)
    for rel, old, new in edits:
        p = repo / rel
        src = p.read_text(encoding="utf-8")
        assert old in src, (rel, old)
        p.write_text(src.replace(old, new, 1), encoding="utf-8", newline="\n")
    if blarai:
        (repo / "CLAUDE.md").write_text(MARKER_DOC)
    (repo / "f.txt").write_text("x")
    git(repo, "add", ".", check=True)
    git(repo, "commit", "-q", "-m", "init", check=True)
    if pre_install:
        pre_install(repo)
    if install:
        r = installer(repo)
        assert r.returncode == 0, r.stdout + r.stderr
    if branch == "detached":
        quiet(repo, "checkout", "-q", "--detach")
    elif branch != trunk:
        quiet(repo, "checkout", "-q", "-b", branch)
    return repo


def stage(repo: Path, *rels: str) -> None:
    for rel in rels:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(p.read_text() + "x" if p.exists() else "change")
    git(repo, "add", *rels, check=True)


def commit(repo: Path, *args: str, env_extra=None):
    return git(repo, "commit", "-q", "-m", "msg", *args, env_extra=env_extra)


def inst(repo) -> Path:
    """The INSTALLED hook copies: <git-common-dir>/blarai-hooks (what git actually runs)."""
    return Path(repo) / ".git" / "blarai-hooks"


def record(repo) -> dict:
    import json
    return json.loads((Path(repo) / ".git" / "blarai-install.json").read_text(encoding="utf-8"))


def head(repo) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


# ---- test tiers: a FAST CORE stays in the standing gate; the exhaustive remainder is `slow` ----------
def tiered(cases, keep):
    """Parametrize list where only `keep` (values or int indices) stay fast; the rest are slow."""
    keep = set(keep)
    out = []
    for i, c in enumerate(cases):
        try:
            hit = i in keep or c in keep
        except TypeError:
            hit = i in keep
        args = c if isinstance(c, tuple) else (c,)
        out.append(c if hit else pytest.param(*args, marks=pytest.mark.slow))
    return out


def mark_slow_except(namespace, keep):
    """Mark every test_* function in `namespace` slow unless its name is in `keep`."""
    for name, obj in list(namespace.items()):
        if name.startswith("test_") and callable(obj) and name not in keep:
            obj.pytestmark = [*getattr(obj, "pytestmark", []), pytest.mark.slow]
