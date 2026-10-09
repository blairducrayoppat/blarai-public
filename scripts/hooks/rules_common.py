"""Definitions and checks shared by the PreToolUse text guard, the git-native pre-commit hook
and the git-native reference-transaction hook.

One definition of: which branches are protected, what marks a BlarAI repository (read from
HEAD, never from the working tree the committer controls), which paths and file kinds may ride
a direct commit on main (the companion allowlist, tightened by extension, mode, size and path
shape), the hook-file integrity check, and how an operator override is logged. All enforcement
layers import this module, so they cannot drift apart.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PROTECTED_BRANCHES = frozenset({"main", "master"})
PROTECTED_REFS = frozenset({"refs/heads/main", "refs/heads/master"})
SCOPE_MARKER = "blarai_project_instructions"
OVERRIDE_ENV = "BLARAI_GIT_RULES_OVERRIDE"
OVERRIDE_LOG_ENV = "BLARAI_GIT_RULES_OVERRIDE_LOG"
ZERO_OID = "0" * 40

# Companion commits: the ticket/journal/ledger surfaces CLAUDE.md names as the atomic
# companions of a ship. They carry no behaviour, so they need no gate; code, tests, config,
# CLAUDE.md and scripts always ride a feature branch. A trailing "/" marks a directory.
COMPANION_ALLOWLIST = (
    "docs/journal_fragments/", "docs/ledger/", "BUILD_JOURNAL.md",
    "docs/BUILD_JOURNAL_ANTHOLOGY.md", "LESSONS.md", "FIELD_NOTES.md",
    "docs/sprints/ACTIVE_SPRINT.md", "docs/ROADMAP.md", "docs/DECISION_REGISTER.md",
    "docs/archive/", "PERFORMANCE_LOG.md", "docs/performance/", "docs/reviews/",
    "docs/research/",
)
# Data and prose only: nothing that runs. Applied to every added or modified file (deleting
# an existing file of any type is allowed). Existing .py/.sh files in allowlisted directories
# stay tracked; new or modified ones are refused on main and ride a branch.
ALLOWED_EXTENSIONS = frozenset(
    {".md", ".txt", ".json", ".jsonl", ".csv", ".yaml", ".yml", ".svg", ".png", ".jpg"})
MAX_FILE_BYTES = 2 * 1024 * 1024
ALLOWED_MODE = "100644"  # rejects symlink 120000, gitlink 160000, executable 100755, mode changes
DOTFILE_ALLOWLIST: tuple[str, ...] = ()  # explicit tiny list of dotfiles allowed on main (none)

INSTALL_DIR = "blarai-hooks"  # <git-common-dir>/blarai-hooks/{githooks,hooks}: the INSTALLED copies
RECORD_NAME = "blarai-install.json"  # <git-common-dir>/blarai-install.json: what was installed, from where

Runner = Callable[..., "object"]  # run(["git-subcommand", ...], input=None) -> CompletedProcess


def is_companion(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(p == e or (e.endswith("/") and p.startswith(e)) for e in COMPANION_ALLOWLIST)


def marker_in(path: Path) -> bool:
    """Working-tree CLAUDE.md names the BlarAI project instructions (best-effort fallback only)."""
    try:
        return SCOPE_MARKER in (path / "CLAUDE.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def override_reason() -> str:
    return os.environ.get(OVERRIDE_ENV, "").strip()


def log_override(reason: str, cmd: str, rule: str) -> None:
    """Append one JSON line to the override log (raises OSError if it cannot be written)."""
    path = Path(
        os.environ.get(OVERRIDE_LOG_ENV) or Path.home() / ".claude" / "logs" / "git_rules_override.log"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S%z"), "reason": reason, "rule": rule, "command": cmd}
    with path.open("a", encoding="utf-8", errors="replace") as fh:
        fh.write(json.dumps(rec) + "\n")


# ---- scope: read from a COMMIT, never from the working tree -------------------------------------
def commit_scope(run: Runner, commit: str = "HEAD") -> bool | None:
    """True if `commit` holds a CLAUDE.md naming the BlarAI project instructions, False if it
    positively does not, None if the commit does not exist (unborn HEAD)."""
    if run(["rev-parse", "-q", "--verify", f"{commit}^{{commit}}"]).returncode != 0:
        return None
    shown = run(["show", f"{commit}:CLAUDE.md"])
    return shown.returncode == 0 and SCOPE_MARKER in shown.stdout


# ---- what a direct commit on main may contain ---------------------------------------------------
@dataclass(frozen=True)
class Change:
    oldmode: str
    newmode: str
    oldsha: str
    newsha: str
    status: str
    path: str


def parse_raw_z(out: str) -> list[Change]:
    parts = out.split("\0")
    changes: list[Change] = []
    i = 0
    while i < len(parts) - 1:
        meta = parts[i]
        if not meta.startswith(":"):
            i += 1
            continue
        f = meta[1:].split(" ")
        changes.append(Change(f[0], f[1], f[2], f[3], f[4][:1], parts[i + 1]))
        i += 2
    return changes


def _path_problem(p: str) -> str | None:
    comps = p.split("/")
    if "\\" in p:
        return "backslash in path"
    if ":" in p:
        return "':' in path (NTFS stream)"
    if any(c in ("", ".", "..") for c in comps):
        return "'..' or empty path component"
    if any(c.endswith((".", " ")) for c in comps):
        return "trailing dot or space in a path component"
    if unicodedata.normalize("NFC", p) != p:
        return "path is not NFC-normalised"
    if any(c.startswith(".") for c in comps) and p not in DOTFILE_ALLOWLIST:
        return "dotfile (.gitattributes/.gitmodules/.gitignore and friends are not companions)"
    return None


def change_problem(c: Change, sizes: dict[str, int], tracked_keys: Callable[[], dict[str, set[str]]]) -> str | None:
    """First reason a staged/committed change is not a companion, or None."""
    if not is_companion(c.path):
        return "outside the companion allowlist"
    why = _path_problem(c.path)
    if why:
        return why
    if c.status == "D":
        return None
    if c.newmode != ALLOWED_MODE:
        kind = {"120000": "symlink", "160000": "gitlink/submodule", "100755": "executable"}.get(
            c.newmode, f"mode {c.newmode}")
        return f"{kind} (only plain 100644 files)"
    if c.oldmode not in ("000000", ALLOWED_MODE):
        return f"mode change {c.oldmode} -> {c.newmode}"
    ext = os.path.splitext(c.path)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"file type '{ext or '(none)'}' can run or change behaviour; allowed: {' '.join(sorted(ALLOWED_EXTENSIONS))}"
    if sizes[c.newsha] > MAX_FILE_BYTES:
        return f"file larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"
    if c.status == "A":
        key = unicodedata.normalize("NFC", c.path).casefold()
        clash = tracked_keys().get(key, set()) - {c.path}
        if clash:
            return f"case/normalisation variant of existing tracked path {sorted(clash)[0]}"
    return None


def _tracked_keys(run: Runner, commit: str | None) -> Callable[[], dict[str, set[str]]]:
    cache: list[dict[str, set[str]]] = []

    def get() -> dict[str, set[str]]:
        if not cache:
            keys: dict[str, set[str]] = {}
            if commit is not None:
                r = run(["ls-tree", "-r", "--name-only", "-z", commit])
                if r.returncode != 0:
                    raise RuntimeError("cannot list tracked paths")
                for name in r.stdout.split("\0"):
                    if name:
                        keys.setdefault(unicodedata.normalize("NFC", name).casefold(), set()).add(name)
            cache.append(keys)
        return cache[0]

    return get


def _problems(changes: list[Change], run: Runner, tracked_commit: str | None) -> list[str]:
    tracked = _tracked_keys(run, tracked_commit)
    shas = sorted({c.newsha for c in changes if c.status != "D" and c.newmode == ALLOWED_MODE})
    sizes: dict[str, int] = {}
    if shas:
        r = run(["cat-file", "--batch-check=%(objectsize)"], input="\n".join(shas) + "\n")
        lines = r.stdout.splitlines()
        if r.returncode != 0 or len(lines) != len(shas) or not all(x.strip().isdigit() for x in lines):
            raise RuntimeError("cannot read the sizes of the changed files")
        sizes = {sha: int(x) for sha, x in zip(shas, lines)}
    out = []
    for c in changes:
        why = change_problem(c, sizes, tracked)
        if why:
            out.append(f"{c.path}: {why}")
    return out


def staged_problems(run: Runner) -> tuple[list[Change], list[str]]:
    """(changes, problems) for the staged set: what `git commit` would record."""
    r = run(["diff", "--cached", "--raw", "--no-renames", "-z", "--diff-filter=ACMRTD"])
    if r.returncode != 0:
        raise RuntimeError("cannot read the staged set")
    changes = parse_raw_z(r.stdout)
    return changes, _problems(changes, run, "HEAD")


def commit_problems(run: Runner, commit: str, has_parent: bool) -> tuple[list[Change], list[str]]:
    """(changes, problems) for one single-parent (or root) commit's own diff."""
    r = run(["diff-tree", "--no-commit-id", "--raw", "-r", "--root", "--no-renames", "-z",
             "--diff-filter=ACMRTD", commit])
    if r.returncode != 0:
        raise RuntimeError(f"cannot read the diff of {commit[:10]}")
    changes = parse_raw_z(r.stdout)
    return changes, _problems(changes, run, f"{commit}^" if has_parent else None)


# ---- the installed hooks and the repository identity: both recorded at install time -----------------
MISMATCH = "install record does not match this repository: run install_git_hooks.py --check / --update (the lead)"
_HEX = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def load_record(common: Path) -> dict:
    """The install record, or RuntimeError (every caller fails closed)."""
    try:
        rec = json.loads((common / RECORD_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"{MISMATCH} (cannot read {common / RECORD_NAME}: {exc})")
    return rec


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _is_int(x) -> bool:
    return type(x) is int


def _is_hex(x) -> bool:
    return isinstance(x, str) and bool(_HEX.match(x))


def record_problems(run: Runner, rec, inst: Path) -> list[str]:
    """Every inconsistency between the install record / installed copies and the repository the hook is
    running in. The hooks live in this repository's common dir and only ever run for it, so ANY
    problem means block (never "not BlarAI, allow"). Empty list = consistent."""
    if not isinstance(rec, dict):
        return ["the record is not a JSON object"]
    probs: list[str] = []
    if rec.get("version") != 1 or not _is_int(rec.get("version")):
        probs.append(f"unknown record schema version {rec.get('version')!r}")
    for key in ("common_dir", "interpreter", "source_branch", "hook_count_str"):
        if not isinstance(rec.get(key), str) or not rec.get(key):
            probs.append(f"field {key!r} is missing or not a string")
    roots, hooks = rec.get("repo_roots"), rec.get("hooks")
    if not isinstance(roots, list) or not roots or not all(_is_hex(r) for r in roots):
        probs.append("field 'repo_roots' is missing or not a list of commit ids")
    if not isinstance(hooks, dict) or not hooks or not all(isinstance(k, str) and _is_hex(v) for k, v in hooks.items()):
        probs.append("field 'hooks' is missing or not a map of file -> hash")
    if not _is_int(rec.get("hook_count")) or (isinstance(hooks, dict) and rec.get("hook_count") != len(hooks)):
        probs.append("field 'hook_count' is missing, not an integer, or inconsistent with 'hooks'")
    elif rec.get("hook_count_str") != str(rec.get("hook_count")):
        probs.append("field 'hook_count_str' is inconsistent with 'hook_count'")
    for key in ("interpreter_hash", "source_commit", "base_interpreter_hash", "base_interpreter_sha256"):
        if not _is_hex(rec.get(key)):
            probs.append(f"field {key!r} is missing or not a hash")
    for key in ("interpreter_real", "base_interpreter"):
        if not isinstance(rec.get(key), str) or not rec.get(key):
            probs.append(f"field {key!r} is missing or not a string")
    if not isinstance(rec.get("pyvenv_cfg_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}|", rec.get("pyvenv_cfg_sha256", "x")):
        probs.append("field 'pyvenv_cfg_sha256' is missing or not a sha256 (or empty)")
    if probs:
        return probs
    cd = run(["rev-parse", "--path-format=absolute", "--git-common-dir"])
    actual = cd.stdout.strip()
    if cd.returncode != 0 or not actual:
        raise RuntimeError("cannot resolve the git common directory")
    if not _same_path(actual, rec["common_dir"]):
        probs.append(f"the recorded git dir {rec['common_dir']} is not this repository's ({actual})")
    if not _same_path(actual, str(inst.parent)):
        probs.append(f"the hooks are installed in {inst.parent} but run in the repository {actual}")
    ref = next((b for b in ("main", "master") if run(["rev-parse", "-q", "--verify", f"refs/heads/{b}"]).returncode == 0), None)
    if ref is None:
        probs.append("this repository has neither main nor master")
    else:
        real = set(run(["rev-list", "--max-parents=0", f"refs/heads/{ref}"]).stdout.split())
        if not set(roots) <= real:
            probs.append("the recorded root commit(s) are not root commits of this repository")
        if run(["merge-base", "--is-ancestor", rec["source_commit"], f"refs/heads/{ref}"]).returncode != 0:
            probs.append(f"the recorded source commit is not an ancestor of {ref}")
    probs += installed_problems(run, inst, rec)
    h = run(["hash-object", "--no-filters", "--", rec["interpreter"]])
    if h.returncode != 0 or h.stdout.strip() != rec["interpreter_hash"]:
        probs.append(f"the recorded interpreter {rec['interpreter']} is missing or changed")
    else:
        now = interpreter_facts(run, rec["interpreter"])
        for key in ("interpreter_real", "pyvenv_cfg_sha256", "base_interpreter", "base_interpreter_hash",
                    "base_interpreter_sha256"):
            if now.get(key) != rec[key]:
                probs.append(f"the recorded interpreter's {key} changed (a pyvenv.cfg repoint or a replaced base python)")
    return probs


def interpreter_facts(run: Runner, exe: str) -> dict:
    """What decides which Python really runs for a recorded interpreter path: its resolved real path, the sha256
    of the pyvenv.cfg beside it (empty if none), and the base interpreter named by that cfg's `home` (the path
    and its git blob hash; the interpreter itself when there is no cfg). The launcher stub of a venv is the same
    file for every venv, so its hash alone pins nothing."""
    real = os.path.realpath(exe).replace("\\", "/")
    parent = Path(exe).parent
    cfg = next((d / "pyvenv.cfg" for d in (parent, parent.parent) if (d / "pyvenv.cfg").is_file()), None)
    cfg_sha, base = "", Path(exe)
    if cfg is not None:
        raw = cfg.read_bytes()
        cfg_sha = hashlib.sha256(raw).hexdigest()
        for line in raw.decode("utf-8", "replace").splitlines():
            k, _, v = line.partition("=")
            if k.strip().lower() == "home" and v.strip():
                base = Path(v.strip()) / Path(exe).name
    h = run(["hash-object", "--no-filters", "--", str(base)])
    try:
        base_sha256 = hashlib.sha256(base.read_bytes()).hexdigest()
    except OSError:
        base_sha256 = ""
    return {"interpreter_real": real, "pyvenv_cfg_sha256": cfg_sha, "base_interpreter": base.as_posix(),
            "base_interpreter_hash": h.stdout.strip() if h.returncode == 0 else "",
            "base_interpreter_sha256": base_sha256}


GUARD_OK = "BLARAI-GUARD-OK"


def allow_token(script: str) -> str:
    """The affirmative proof a guard prints on stdout when (and only when) it allows: the token plus the sha256
    of the guard script it ran. The shim computes that sha256 itself and treats anything else, including a bare
    exit 0, as a refusal."""
    return f"{GUARD_OK} {hashlib.sha256(Path(script).read_bytes()).hexdigest()}"


def installed_problems(run: Runner, inst: Path, rec: dict) -> list[str]:
    """The installed hook files must equal the recorded hashes: none changed, missing or extra."""
    recorded: dict[str, str] = rec["hooks"]
    problems: list[str] = []
    actual: list[str] = []
    for sub in ("githooks", "hooks"):
        d = inst / sub
        if d.is_dir():
            actual += [f"{sub}/{n}" for n in sorted(os.listdir(d)) if (d / n).is_file() and n != "__pycache__"]
    for extra in sorted(set(actual) - set(recorded)):
        problems.append(f"{extra}: installed but not recorded")
    present = [p for p in recorded if p in actual]
    for missing in sorted(set(recorded) - set(actual)):
        problems.append(f"{missing}: recorded but missing")
    if present:
        have = run(["hash-object", "--no-filters", "--", *[str(inst / p) for p in present]])
        hashes = have.stdout.split()
        if have.returncode != 0 or len(hashes) != len(present):
            raise RuntimeError("cannot hash the installed hook files")
        for p, h in zip(present, hashes):
            if h != recorded[p]:
                problems.append(f"{p}: differs from the recorded hash")
    if len(recorded) != rec["hook_count"]:
        problems.append("the install record is inconsistent (hook_count)")
    return problems
