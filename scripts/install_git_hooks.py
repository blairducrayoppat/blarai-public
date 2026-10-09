#!/usr/bin/env python
"""Install, update, check or remove the repo's git-native hooks.

  python scripts/install_git_hooks.py              install (copy the hooks from main's tip)
  python scripts/install_git_hooks.py --update --dry-run
                                                   stage main's tip, print the sanitised review (drift of the
                                                   installed copy, the proposed change, a DIGEST), change nothing
  python scripts/install_git_hooks.py --update --reason "<why>" --approve <digest> [--accept-drift]
                                                   apply exactly what that digest covers; any mismatch exit 3
  python scripts/install_git_hooks.py --check      exit 0 only if installed, intact AND equal to main
  python scripts/install_git_hooks.py --status     plain-language: is protection ON, what turns it off
  python scripts/install_git_hooks.py --uninstall  restore the previous hooks path

The hook files are COPIED from the repository's main branch tip (git show main:<path>, hashes
verified) into <git-common-dir>/blarai-hooks/{githooks,hooks}, and core.hooksPath is set to that
ABSOLUTE directory. No branch checkout in any worktree can change or remove them, and linked
worktrees on any branch are covered. <git-common-dir>/blarai-install.json records what was
installed: the repository identity (root commit hashes + common dir), every hook file's hash, the
interpreter (absolute path + hash) and the main commit the copy came from. The shims verify the
installed files against that record before running them. An existing core.hooksPath (or the
default .git/hooks) is kept: stored in the repo config key blarai.previoushookspath (mirrored in
<git-common-dir>/blarai-previous-hooks) and chained to after our logic passes.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "hooks"))
import rules_common as rc  # noqa: E402

KEY = "core.hooksPath"
PREV_KEY = "blarai.previoushookspath"
ORIG_KEY = "blarai.originalhookspath"  # the hooks path from BEFORE the first install: survives record loss
DEFAULT = "@default"
PASSTHROUGH = ("post-commit", "post-merge", "post-checkout", "post-rewrite", "prepare-commit-msg",
               "commit-msg", "pre-push", "pre-merge-commit", "applypatch-msg", "pre-applypatch",
               "post-applypatch")
SHIMS = ("_lib.sh", "pre-commit", "reference-transaction", *PASSTHROUGH)
PY_MODULES = ("git_native_pre_commit.py", "reference_transaction.py", "rules_common.py")
SOURCES = {"githooks": "scripts/githooks", "hooks": "scripts/hooks"}
MIRROR = "blarai-previous-hooks"
LOG = "blarai-install.log"


def _git(repo: Path, *args: str, check: bool = False, input: str | None = None, binary: bool = False):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=check, input=input,
                          **({} if binary else {"text": True}))


def _toplevel(repo: Path) -> Path:
    r = _git(repo, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        raise SystemExit(f"not a git repository: {repo}")
    return Path(r.stdout.strip())


_COMMON: dict[str, Path] = {}


def _common(repo: Path) -> Path:
    """The git common directory; one answer per repository path for the life of this process
    (an install or check never moves it, and each uncached call is a process spawn)."""
    key = str(repo)
    if key not in _COMMON:
        r = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if r.returncode != 0:
            raise SystemExit("cannot resolve the git common directory")
        _COMMON[key] = Path(r.stdout.strip())
    return _COMMON[key]


def _hashes(repo: Path, paths: list[Path]) -> list[str]:
    """git's own `hash-object --no-filters` of each file, in ONE process instead of one per file.

    Fail-closed: any failure, or an answer count that differs from the request, returns "" for
    every path, which no recorded hash equals, so a caller's comparison fails exactly as it
    does for an unreadable file. A path holding a newline cannot ride --stdin-paths and falls
    back to one call per file."""
    if not paths:
        return []
    if any("\n" in str(p) or "\r" in str(p) for p in paths):
        return [_git(repo, "hash-object", "--no-filters", "--", str(p)).stdout.strip() for p in paths]
    try:
        payload = "".join(f"{p}\n" for p in paths).encode("utf-8")
    except UnicodeEncodeError:
        return [""] * len(paths)
    r = _git(repo, "hash-object", "--no-filters", "--stdin-paths", input=payload, binary=True)
    out = r.stdout.decode("ascii", "replace").split()
    return out if r.returncode == 0 and len(out) == len(paths) else [""] * len(paths)


def _blobs(repo: Path, shas: list[str]) -> list[bytes | None]:
    """The content of each blob in ONE `cat-file --batch` process; None for anything that is
    missing, is not a blob, was not the object asked for, or whose reply does not parse or was cut
    off (the caller refuses on None). Entries parsed intact before git failed keep their bytes, so
    a refusal names the object that is actually bad."""
    if not shas:
        return []
    r = _git(repo, "cat-file", "--batch", input="".join(f"{s}\n" for s in shas).encode("ascii"), binary=True)
    data, pos, out = r.stdout, 0, []
    for sha in shas:
        nl = data.find(b"\n", pos)
        head = data[pos:nl].split(b" ") if nl >= 0 else []
        if len(head) == 2 and head[1] in (b"missing", b"ambiguous"):
            out.append(None)
            pos = nl + 1
            continue
        if len(head) != 3 or head[0] != sha.encode("ascii") or head[1] != b"blob" or not head[2].isdigit():
            out.append(None)
            if nl < 0 or len(head) < 3 or head[0] != sha.encode("ascii") or not head[2].isdigit():
                out.extend([None] * (len(shas) - len(out)))
                break
            pos = nl + 1 + int(head[2]) + 1
            continue
        size = int(head[2])
        out.append(data[nl + 1:nl + 1 + size] if len(data) >= nl + 1 + size else None)
        pos = nl + 1 + size + 1
    return out


def _inst(repo: Path) -> Path:
    return _common(repo) / rc.INSTALL_DIR


def hooks_path(repo: Path) -> str:
    return (_inst(repo) / "githooks").resolve().as_posix()


def _effective(repo: Path) -> str | None:
    r = _git(repo, "config", "--get", KEY)
    return r.stdout.strip() if r.returncode == 0 else None


def _is_ours(value: str | None, repo: Path) -> bool:
    """True if a core.hooksPath value is one of OUR installed directories (never a 'previous' path)."""
    if not value:
        return False
    norm = value.replace("\\", "/").rstrip("/")
    return norm == hooks_path(repo) or norm.endswith(f"/{rc.INSTALL_DIR}/githooks")


def _original(repo: Path) -> str | None:
    r = _git(repo, "config", "--local", "--get", ORIG_KEY)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _recover_hint(repo: Path) -> str:
    """The command that fixes things: --update when the hooks are installed here, the plain install otherwise."""
    if _is_ours(_effective(repo), repo):
        return "python scripts/install_git_hooks.py --update"
    return "python scripts/install_git_hooks.py"


def _previous(repo: Path) -> str | None:
    r = _git(repo, "config", "--local", "--get", PREV_KEY)
    return r.stdout.strip() if r.returncode == 0 else None


def _main_ref(repo: Path) -> str:
    for name in ("main", "master"):
        if _git(repo, "rev-parse", "-q", "--verify", f"refs/heads/{name}").returncode == 0:
            return name
    raise SystemExit("neither main nor master exists: the hooks are installed from main's tip")


def _source(repo: Path, ref: str) -> dict[str, str]:
    """{installed key: blob sha} of the hook files at `ref`. SystemExit if any is missing."""
    want = [f"{SOURCES['githooks']}/{n}" for n in SHIMS] + [f"{SOURCES['hooks']}/{n}" for n in PY_MODULES]
    r = _git(repo, "ls-tree", "-r", "-z", ref, "--", SOURCES["githooks"], *[f"{SOURCES['hooks']}/{n}" for n in PY_MODULES])
    found: dict[str, str] = {}
    for rec in r.stdout.split("\0"):
        if rec:
            meta, _, path = rec.partition("\t")
            found[path] = meta.split(" ")[2]
    missing = [p for p in want if p not in found]
    if missing:
        raise SystemExit(f"main's tip lacks {', '.join(missing)}: merge the hook files to main first")
    out: dict[str, str] = {}
    for path, sha in found.items():
        for sub, base in SOURCES.items():
            if path.startswith(base + "/") and path.count("/") == base.count("/") + 1:
                out[f"{sub}/{path.rsplit('/', 1)[1]}"] = sha
    return out


def _interpreter(repo: Path) -> tuple[str, str]:
    exe = Path(sys.executable).absolute().as_posix()
    h = _git(repo, "hash-object", "--no-filters", "--", exe)
    if h.returncode != 0:
        raise SystemExit(f"cannot hash the interpreter {exe}")
    return exe, h.stdout.strip()


def _roots(repo: Path, ref: str) -> list[str]:
    r = _git(repo, "rev-list", "--max-parents=0", ref)
    roots = sorted(x for x in r.stdout.split() if x)
    if r.returncode != 0 or not roots:
        raise SystemExit("cannot read the repository's root commits")
    return roots


def _replace(src: Path, dst: Path) -> None:
    """os.replace with a short retry: Windows refuses to replace a file another process has open."""
    for attempt in range(100):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 99:
                raise
            time.sleep(0.02)


def _build(repo: Path, source: dict[str, str], tmp: Path) -> Path:
    """Write every hook file into the (unique, pre-created) temp directory and verify each hash."""
    blobs = _blobs(repo, list(source.values()))
    dsts = []
    for (key, sha), blob in zip(source.items(), blobs):
        if blob is None:
            raise SystemExit(f"cannot read blob {sha} for {key}")
        dst = tmp / key
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(blob)
        if key.startswith("githooks/"):
            dst.chmod(0o755)
        dsts.append(dst)
    for (key, sha), got in zip(source.items(), _hashes(repo, dsts)):
        if got != sha:
            raise SystemExit(f"{key}: written copy does not match main's blob")
    return tmp


BIDI = frozenset("؜‎‏‪‫‬‭‮⁦⁧⁨⁩")
LINE_WRAP = 200          # characters of escaped text per displayed line; longer lines CONTINUE, never end
FILE_CAP = 64 * 1024     # a changed file whose review output exceeds this is refused, not abbreviated
TOTAL_CAP = 256 * 1024
EXIT_NOT_APPROVED = 3
EXIT_UNSAFE = 4


def _esc_tokens(text: str) -> list[str]:
    out = []
    for ch in text:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif 0x20 <= o < 0x7F:
            out.append(ch)
        elif o < 0x100:
            out.append(f"\\x{o:02x}")
        elif o < 0x10000:
            out.append(f"\\u{o:04x}")
        else:
            out.append(f"\\U{o:08x}")
    return out


def _esc(text: str) -> str:
    """A printable, unambiguous rendering: every character outside printable ASCII is shown as an escape
    (\\xNN, \\uNNNN, \\UNNNNNNNN) and a backslash as two backslashes, so nothing printed can move the cursor,
    recolour, reorder or hide text. Nothing is ever cut: every character of the input appears in the output."""
    return "".join(_esc_tokens(text))


def _wrap(text: str) -> list[str]:
    """The escaped text as display lines of at most LINE_WRAP characters (an escape is never split). Every
    line after the first is a continuation; no character is dropped."""
    lines, cur, n = [], [], 0
    for tok in _esc_tokens(text):
        if n + len(tok) > LINE_WRAP and cur:
            lines.append("".join(cur))
            cur, n = [], 0
        cur.append(tok)
        n += len(tok)
    lines.append("".join(cur))
    return lines


def _unsafe(blob: bytes) -> str | None:
    """Why a file is refused as an approval basis: NUL, ESC, bidi controls or non-UTF-8 bytes."""
    if b"\0" in blob:
        return "contains NUL"
    if b"\x1b" in blob:
        return "contains ESC"
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return "is not valid UTF-8"
    if any(ch in BIDI for ch in text):
        return "contains bidi control characters"
    return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest_lines(commit: str, sha256: dict[str, str], facts: list[str]) -> list[str]:
    return [commit, *[f"{k}:{v}" for k, v in sorted(sha256.items())], *sorted(facts)]


def _digest(commit: str, sha256: dict[str, str], facts: list[str]) -> str:
    """What the lead approves: the source commit, the sorted path:sha256 of every file to install, and every
    other fact the update would install or accept (interpreter pin, chained previous hooks, accepted drift)."""
    return _sha256("\n".join(_digest_lines(commit, sha256, facts)).encode("utf-8"))


def _policy_problems(source: dict[str, str]) -> list[str]:
    """Names that must never be installed: case-variant aliases (one file on Windows) and any file in
    scripts/githooks that is not an allowlisted hook name (it would become a live git hook without the shim's checks)."""
    out: list[str] = []
    folded: dict[str, list[str]] = {}
    for key in sorted(source):
        folded.setdefault(key.casefold(), []).append(key)
    for keys in folded.values():
        if len(keys) > 1:
            out.append("ALIAS: " + " and ".join(_esc(k) for k in keys) + " differ only in case and are one file on Windows")
    for key in sorted(source):
        if key.startswith("githooks/") and key.split("/", 1)[1] not in SHIMS:
            out.append(f"{_esc(key)} is not an allowlisted hook name (a file in scripts/githooks becomes a live git hook "
                       "that runs without the shim's checks)")
    return out


def _stage(repo: Path, ref: str) -> dict:
    """Stage main's tip ONCE into a UNIQUE temp folder in the git common dir (a concurrent review cannot touch
    it): resolve the commit, read every blob from THAT commit, write the hash-verified copy. Display, digest and
    installation all use this staged copy; main is never re-read afterwards. Refuses (exit 4) names that
    must never be installed."""
    commit = _git(repo, "rev-parse", "--verify", f"refs/heads/{ref}").stdout.strip()
    if not commit:
        raise SystemExit(f"cannot resolve {ref}")
    source = _source(repo, commit)
    bad = _policy_problems(source)
    if bad:
        print(f"REFUSED (exit {EXIT_UNSAFE}): {'; '.join(bad)}. Nothing changed and no flag overrides this; fix main's "
              f"scripts/githooks first.")
        raise SystemExit(EXIT_UNSAFE)
    tmp = Path(tempfile.mkdtemp(prefix=rc.INSTALL_DIR + ".new-", dir=_common(repo)))
    try:
        _build(repo, source, tmp)
        exe, exe_hash = _interpreter(repo)
        interp = rc.interpreter_facts(_run, exe)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if not interp["base_interpreter_hash"] or not interp["base_interpreter_sha256"]:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SystemExit(f"cannot hash the base interpreter {interp['base_interpreter']}")
    return {"ref": ref, "commit": commit, "source": source, "dir": tmp, "interpreter": exe,
            "interpreter_hash": exe_hash, "interp": interp, "facts": []}


CHAIN_MAX_FILES = 100


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _chained(top: Path, prev: str) -> tuple[list[tuple[str, str]], list[str]]:
    """The hook files of the previous hooks folder that our shims chain to: ([(name, sha256 of EVERY byte)],
    problems). A folder with more than CHAIN_MAX_FILES files is a problem (refused, never half-bound)."""
    folder = _common(top) / "hooks" if prev == DEFAULT else Path(prev)
    if not folder.is_absolute():
        folder = top / folder
    out: list[tuple[str, str]] = []
    problems: list[str] = []
    if folder.is_dir():
        names = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.endswith(".sample"))
        if len(names) > CHAIN_MAX_FILES:
            problems.append(f"the chained previous hooks folder holds {len(names)} files, over the {CHAIN_MAX_FILES} "
                            "that can be bound by hash")
        out = [(p.name, _file_sha256(p)) for p in names[:CHAIN_MAX_FILES]]
    return out, problems


def _prev_now(top: Path) -> tuple[str, str]:
    """What the shims chain to TODAY: the mirror file's value and the config key's value."""
    mirror = _common(top) / MIRROR
    return (mirror.read_text(encoding="utf-8").strip() if mirror.is_file() else "(missing)",
            _previous(top) or "(unset)")


def _bind(top: Path, staged: dict, prev: str, drift: list | None) -> list[tuple[str, str]]:
    """Set the facts the digest binds besides the files: interpreter pin, previous hooks path and the files in
    it, and every drifted installed file (path, kind, sha256)."""
    i = staged["interp"]
    chained, staged["chain_problems"] = _chained(top, prev)
    mirror_now, config_now = _prev_now(top)
    facts = [f"interpreter:{staged['interpreter']}", f"interpreter_hash:{staged['interpreter_hash']}",
             f"interpreter_real:{i['interpreter_real']}", f"pyvenv_cfg_sha256:{i['pyvenv_cfg_sha256']}",
             f"base_interpreter:{i['base_interpreter']}", f"base_interpreter_hash:{i['base_interpreter_hash']}",
             f"base_interpreter_sha256:{i['base_interpreter_sha256']}",
             f"previous_hooks_path:{prev}", f"mirror_file_now:{mirror_now}", f"config_previous_now:{config_now}",
             *[f"chained:{n}:{h}" for n, h in chained]]
    if drift is None:
        facts.append("drift:record-unreadable")
        inst = _inst(top)
        facts += [f"installed:{k}:{_sha256((inst / k).read_bytes())}" for k in _files(inst)]
    else:
        facts += [f"drift:{k}:{kind}:{sha}" for k, kind, sha in drift]
    staged["facts"] = facts
    return chained


def _staged_digest(staged: dict) -> str:
    """Recomputed from the bytes now on disk in the staged folder."""
    on_disk = {k: _sha256((staged["dir"] / k).read_bytes()) for k in staged["source"]}
    return _digest(staged["commit"], on_disk, staged["facts"])


def _staged_lines(staged: dict) -> list[str]:
    on_disk = {k: _sha256((staged["dir"] / k).read_bytes()) for k in staged["source"]}
    return _digest_lines(staged["commit"], on_disk, staged["facts"])


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.is_dir() else []


def _restore_exact(repo: Path, inst: Path, old_dir: Path) -> list[str]:
    """Put the pre-update copy back and VERIFY it. No file that existed before is ever deleted first: each is
    rewritten beside and switched in with os.replace (a case-only rename is a second atomic rename), so a file
    that cannot be touched (locked) simply keeps its content, which is either the old or the new verified copy.
    Returns the problems that remain (empty = the installed set equals the pre-update copy, names included)."""
    problems: list[str] = []
    old_files = _files(old_dir)
    for key in old_files:
        try:
            names = set(_files(inst))
            have = inst / key
            if key in names and have.read_bytes() == (old_dir / key).read_bytes():
                continue
            side = have.with_name(have.name + ".restore")
            shutil.copy2(old_dir / key, side)
            variants = [n for n in names if n.casefold() == key.casefold() and n != key]
            if variants:
                _replace(side, inst / variants[0])
                _replace(inst / variants[0], have)
            else:
                _replace(side, have)
        except BaseException as exc:  # noqa: BLE001 - every failure is collected, the loop must not stop
            problems.append(f"{key}: could not be restored ({exc!r})")
    keep = set(old_files)
    for extra in [f for f in _files(inst) if f not in keep]:
        try:
            (inst / extra).unlink()
        except OSError as exc:
            problems.append(f"{extra}: could not be removed ({exc!r})")
    names = set(_files(inst))
    for key in old_files:
        if key not in names or (inst / key).read_bytes() != (old_dir / key).read_bytes():
            problems.append(f"{key}: does not equal the pre-update copy after the restore")
    return problems


def _materialise(repo: Path, staged: dict, prev: str | None, digest: str) -> dict:
    """Install the verified copy and write the record; main is never unprotected, whatever fails.

    A directory cannot be renamed over a non-empty directory (POSIX) or at all (Windows), so the folder keeps
    its name and every file is switched in individually with os.replace (atomic per file); no installed file is
    ever deleted first. The record is moved aside before the first switch and written back last: while it is
    absent every shim refuses (S1), so every intermediate state, including a crash or power cut, refuses main.
    The old folder is kept whole as blarai-hooks.prev (and the old record as <record>.prev). On any failure the
    old files are restored by atomic replacement and verified by comparison; only then is the old record put
    back. If the restore cannot complete (a file stays locked) the record stays aside and the install FAILS
    CLOSED (every commit refused until --update), with .prev kept as the recovery source."""
    inst = _inst(repo)
    common = _common(repo)
    tmp, source = staged["dir"], staged["source"]
    if _staged_digest(staged) != digest:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SystemExit("the staged copy changed after it was shown: nothing installed")
    old_dir = inst.with_name(rc.INSTALL_DIR + ".prev")
    rec_path = common / rc.RECORD_NAME
    rec_old = common / (rc.RECORD_NAME + ".prev")
    shutil.rmtree(old_dir, ignore_errors=True)
    if inst.is_dir():
        shutil.copytree(inst, old_dir)
    rec_old.unlink(missing_ok=True)
    had_record = rec_path.is_file()
    try:
        if had_record:
            _replace(rec_path, rec_old)  # from here until the new record lands, every shim refuses
        for key in source:
            dst = inst / key
            dst.parent.mkdir(parents=True, exist_ok=True)
            variants = [f for f in _files(inst) if f.casefold() == key.casefold() and f != key]
            if variants:  # a case-variant of this name is one file on Windows: swap the content, then rename
                _replace(tmp / key, inst / variants[0])
                _replace(inst / variants[0], dst)
            else:
                _replace(tmp / key, dst)
        folded = {k.casefold() for k in source}
        for stale in [f for f in _files(inst) if f.casefold() not in folded]:
            (inst / stale).unlink()
        for (key, sha), got in zip(source.items(), _hashes(repo, [inst / key for key in source])):
            if got != sha:
                raise SystemExit(f"{key}: installed copy does not match main's blob after the swap")
        rec = _write_record(repo, staged, prev)
    except BaseException:
        problems = _restore_exact(repo, inst, old_dir) if old_dir.is_dir() else []
        if not problems and had_record and rec_old.is_file():
            try:
                _replace(rec_old, rec_path)
            except OSError as exc:
                problems.append(f"the old install record could not be put back ({exc!r})")
        shutil.rmtree(tmp, ignore_errors=True)
        if problems:
            print("FAIL-CLOSED: the update failed and the old copy could not be fully restored: "
                  + "; ".join(problems) + f". The install record stays aside so EVERY commit is refused until "
                  f"`python scripts/install_git_hooks.py --update` succeeds; {old_dir} and {rec_old} hold the "
                  "previous state.", file=sys.stderr)
        else:
            shutil.rmtree(old_dir, ignore_errors=True)
            rec_old.unlink(missing_ok=True)
        raise
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(old_dir, ignore_errors=True)
    rec_old.unlink(missing_ok=True)
    return rec


def _write_record(repo: Path, staged: dict, prev: str | None) -> dict:
    ref, source = staged["ref"], staged["source"]
    exe, exe_hash = _interpreter(repo)
    interp = staged["interp"]
    rec = {
        "version": 1,
        "common_dir": _common(repo).resolve().as_posix(),
        "repo_roots": _roots(repo, staged["commit"]),
        "source_branch": ref,
        "source_commit": staged["commit"],
        "interpreter": exe,
        "interpreter_hash": exe_hash,
        "interpreter_real": interp["interpreter_real"],
        "pyvenv_cfg_sha256": interp["pyvenv_cfg_sha256"],
        "base_interpreter": interp["base_interpreter"],
        "base_interpreter_hash": interp["base_interpreter_hash"],
        "base_interpreter_sha256": interp["base_interpreter_sha256"],
        "hook_count": len(source),
        "hook_count_str": str(len(source)),
        "previous_hooks_path": prev,
        "installed_at": time.strftime("%Y-%m-%d %H:%M:%S%z"),
        "hooks": dict(sorted(source.items())),
    }
    target = _common(repo) / rc.RECORD_NAME
    tmp = target.with_name(f"{target.name}.new-{os.getpid()}")
    tmp.write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8", newline="\n")
    _replace(tmp, target)
    return rec


def _log(repo: Path, **fields) -> None:
    with (_common(repo) / LOG).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S%z"), **fields}) + "\n")


def install(top: Path, reason: str = "", approve: str = "", dry_run: bool = False, accept_drift: bool = False) -> int:
    ref = _main_ref(top)
    cur = _effective(top)
    value = hooks_path(top)
    if _is_ours(cur, top):
        if (_common(top) / rc.RECORD_NAME).is_file() and not _check_problems(top, record_only=True):
            print(f"already installed: {KEY} = {value}. Run --check to verify it, --update after main's hook files change.")
            return 0
        # Installed but the record is lost or damaged: never record our own folder as the "previous"
        # hooks path. Behave as --update (rebuild from main's tip and the stored original path).
        return update(top, reason, approve, dry_run, accept_drift)
    if dry_run:
        print(f"dry run: would install the hooks from {ref} into {_inst(top)} and set {KEY}; nothing changed")
        return 0
    staged = _stage(top, ref)
    prev = cur if cur is not None else DEFAULT
    try:
        if _original(top) is None:
            _git(top, "config", "--local", ORIG_KEY, prev, check=True)  # written once, never overwritten while set
        _bind(top, staged, prev, [])
        if staged["chain_problems"]:
            print(f"REFUSED (exit {EXIT_UNSAFE}): {'; '.join(staged['chain_problems'])}. Nothing changed.")
            return EXIT_UNSAFE
        rec = _materialise(top, staged, prev, _staged_digest(staged))
    finally:
        shutil.rmtree(staged["dir"], ignore_errors=True)
    _git(top, "config", "--local", PREV_KEY, prev, check=True)
    (_common(top) / MIRROR).write_text(prev + "\n", encoding="utf-8", newline="\n")
    _git(top, "config", "--local", KEY, value, check=True)
    _log(top, action="install", source_commit=rec["source_commit"], reason=reason)
    shown = "the default .git/hooks" if prev == DEFAULT else prev
    print(f"installed: hooks copied from {ref} ({rec['source_commit'][:10]}) to {_inst(top)}; {KEY} = {value}; "
          f"interpreter {rec['interpreter']} recorded; previous hooks path {shown} is chained to (stored in {PREV_KEY})")
    return 0


def _drift(top: Path, old: dict) -> list[tuple[str, str, str]] | None:
    """Installed copy against the install record: [(file, DRIFT|MISSING|UNRECORDED, installed sha256)]; None if
    there is no usable record (the baseline is then unknown)."""
    recorded = old.get("hooks")
    if not isinstance(recorded, dict) or not recorded:
        return None
    inst = _inst(top)
    out: list[tuple[str, str, str]] = []
    keys = sorted(set(recorded) | set(_files(inst)))
    present = [k for k in keys if k in recorded and (inst / k).is_file()]
    got = dict(zip(present, _hashes(top, [inst / k for k in present])))
    for key in keys:
        path = inst / key
        if key not in recorded:
            out.append((key, "UNRECORDED", _sha256(path.read_bytes())))
        elif not path.is_file():
            out.append((key, "MISSING", ""))
        elif got[key] != recorded[key]:
            out.append((key, "DRIFT", _sha256(path.read_bytes())))
    return out


def _lines(blob: bytes) -> list[str]:
    return blob.decode("utf-8", "replace").split("\n")


def _udiff(a: bytes, b: bytes, name_a: str, name_b: str) -> tuple[list[str], int, int]:
    """Sanitised unified diff (split on newline only, so carriage returns and other separators stay inside
    their line and are shown as escapes). A long line CONTINUES on following lines marked [cont]; nothing is cut.
    Returns (printable lines, insertions, deletions)."""
    out, ins, dele = [], 0, 0
    for n, line in enumerate(difflib.unified_diff(_lines(a), _lines(b), name_a, name_b, lineterm="")):
        if n < 2:
            out.append(line[:4] + _esc(line[4:]))
            continue
        ins += line.startswith("+")
        dele += line.startswith("-")
        chunks = _wrap(line[1:])
        out.append(line[:1] + chunks[0])
        out += ["[cont] " + c for c in chunks[1:]]
    return out, ins, dele


def _review(top: Path, staged: dict, old: dict, digest: str, prev: str, chained: list[tuple[str, str]],
            drift: list[tuple[str, str, str]] | None) -> dict:
    """Print what --update is about to trust, sanitised and complete: the source commit, the DRIFT of the
    installed copy against the install record, the proposed change (installed copy against the staged copy of
    main, every line in full, each file's byte length and sha256), added, removed and renamed files, the
    interpreter pin, the chained previous hooks, every fact the digest binds, and the DIGEST. A file whose
    review output would exceed the byte caps is refused, never abbreviated."""
    inst, sdir, source, commit = _inst(top), staged["dir"], staged["source"], staged["commit"]
    buf: list[str] = []
    meta = _git(top, "log", "-1", "--format=%an%x09%aI%x09%s", commit).stdout.strip().split("\t", 2) + ["", "", ""]
    buf.append("UPDATE REVIEW (every line below is sanitised: non-ASCII and control characters are shown as escapes; "
               "long lines continue on [cont] lines, nothing is cut)")
    buf.append(f"source: {staged['ref']} {commit} author {_esc(meta[0])} date {_esc(meta[1])} subject {_esc(meta[2])}")
    buf.append(f"previously installed from: {_esc(str(old.get('source_commit')))}")
    total = [0]
    unsafe: list[str] = []

    def body(label: str, lines: list[str], per_file: bool = True) -> None:
        size = sum(len(x) + 5 for x in lines)
        total[0] += size
        if per_file and size > FILE_CAP:
            unsafe.append(f"{label}: the review output is {size} bytes, over the {FILE_CAP} cap per file")
            buf.append(f"    (output withheld: {size} bytes)")
        elif total[0] > TOTAL_CAP:
            unsafe.append(f"{label}: the review output passes the {TOTAL_CAP} byte total cap")
            buf.append(f"    (output withheld: total cap)")
        else:
            buf.extend("    " + x for x in lines)

    buf.append("BASELINE: installed copy against the install record")
    if drift is None:
        buf.append("  DRIFT: the install record is missing or unreadable, so what is installed now cannot be checked "
                   "against what was approved before (needs --accept-drift); installed files, sha256:")
        buf += [f"    {_esc(k)} {_sha256((inst / k).read_bytes())}" for k in _files(inst)]
    elif not drift:
        buf.append("  no drift: every installed file matches the record")
    for key, kind, sha in drift or []:
        buf.append(f"  {kind}: {_esc(key)} installed sha256 {sha or 'none'} (needs --accept-drift)")
        rec_sha = (old.get("hooks") or {}).get(key)
        blob = _git(top, "cat-file", "blob", str(rec_sha), binary=True) if rec_sha else None
        cur = (inst / key).read_bytes() if (inst / key).is_file() else b""
        if blob is not None and blob.returncode == 0:
            lines, _, _ = _udiff(blob.stdout, cur, f"recorded/{_esc(key)}", f"installed/{_esc(key)}")
            body(f"drift {_esc(key)}", lines)
        else:
            buf.append("    (the recorded content is not in the repository: hashes only)")

    buf.append("PROPOSED CHANGE: installed copy against the staged copy of main's tip")
    have = set(_files(inst))
    have_fold = {h.casefold(): h for h in have}
    added = sorted(set(source) - have)
    src_fold = {k.casefold() for k in source}
    removed = sorted(h for h in have - set(source) if h.casefold() not in src_fold)
    renamed = [(have_fold[k.casefold()], k) for k in added if k.casefold() in have_fold]
    ins = dele = changed = 0
    for key in sorted(source):
        new = (sdir / key).read_bytes()
        exists = (inst / key).is_file()
        cur = (inst / key).read_bytes() if exists else b""
        if exists and cur == new:
            continue
        changed += exists
        buf.append(f"  file {_esc(key)} ({'CHANGED' if exists else 'ADDED'}): {len(new)} bytes, sha256 {_sha256(new)}")
        why = _unsafe(new)
        if why:
            unsafe.append(f"{_esc(key)} {why}")
        lines, i, d = _udiff(cur, new, f"installed/{_esc(key)}", f"{staged['ref']}/{_esc(key)}")
        ins, dele = ins + i, dele + d
        body(_esc(key), lines)
    for key in removed:
        lines, i, d = _udiff((inst / key).read_bytes(), b"", f"installed/{_esc(key)}", "/dev/null")
        dele += d
        buf.append(f"  file {_esc(key)} will be REMOVED")
        body(_esc(key), lines)
    for was, now in renamed:
        buf.append(f"  RENAME: installed {_esc(was)} -> {_esc(now)} (names differ only in case; the old name is replaced)")
    buf.append(f"files added: {', '.join(_esc(k) for k in added) or 'none'}")
    buf.append(f"files removed: {', '.join(_esc(k) for k in removed) or 'none'}")
    i = staged["interp"]
    buf.append(f"interpreter: recorded {_esc(str(old.get('interpreter')))} ({str(old.get('interpreter_hash'))[:12]}) -> "
               f"now {_esc(staged['interpreter'])} ({staged['interpreter_hash'][:12]})")
    buf.append(f"interpreter pin: real path {_esc(i['interpreter_real'])}; pyvenv.cfg sha256 "
               f"{i['pyvenv_cfg_sha256'] or 'none'}; base python {_esc(i['base_interpreter'])} (sha256 {i['base_interpreter_sha256']}; the hooks run THIS file, "
               "not the venv launcher)")
    was_prev = old.get("previous_hooks_path")
    buf.append(f"PREVIOUS HOOKS (chained to after our checks): recorded {_esc(str(was_prev))} -> proposed {_esc(prev)}"
               + ("  CHANGED" if was_prev != prev else ""))
    mirror_now, config_now = _prev_now(top)
    buf.append(f"  what the shims chain to TODAY: mirror file {_esc(mirror_now)}; config key {_esc(config_now)}"
               + ("  MISMATCH with the install record (the update rewrites both to the proposed path)"
                  if (mirror_now, config_now) != (str(was_prev), str(was_prev)) else ""))
    buf += [f"  chained file {_esc(n)} sha256 {h}" for n, h in chained] or ["  (no hook files in that folder)"]
    unsafe += staged["chain_problems"]
    stat = f"{changed} changed, {len(added)} added, {len(removed)} removed, +{ins} -{dele} lines"
    buf.append(f"diff stat: {stat}")
    buf.append("DIGEST COVERS (these exact lines, joined by newlines, are hashed):")
    buf += [f"  {_esc(x)}" for x in _staged_lines(staged)]
    buf.append(f"DIGEST: {digest}")
    print("\n".join(buf))
    return {"stat": stat, "added": added, "removed": removed, "renamed": renamed, "drift": drift, "unsafe": unsafe}


def update(top: Path, reason: str = "", approve: str = "", dry_run: bool = False, accept_drift: bool = False) -> int:
    if not _is_ours(_effective(top), top):
        print("not installed here (core.hooksPath is not the installed folder): run python scripts/install_git_hooks.py")
        return 1
    ref = _main_ref(top)
    try:
        old = rc.load_record(_common(top))
    except RuntimeError:
        old = {}
    staged = _stage(top, ref)
    try:
        return _update_staged(top, staged, old, reason, approve, dry_run, accept_drift)
    finally:
        shutil.rmtree(staged["dir"], ignore_errors=True)


def _update_staged(top: Path, staged: dict, old: dict, reason: str, approve: str, dry_run: bool,
                   accept_drift: bool) -> int:
    ref, source, new_commit = staged["ref"], staged["source"], staged["commit"]
    if old.get("source_commit") == new_commit and old.get("hooks") == dict(sorted(source.items())) \
            and not _check_problems(top):
        print(f"already up to date with {ref} ({new_commit[:10]})")
        return 0
    # The previous hooks path comes from the key that survives record loss, never from the current value
    # (which is our own folder) and never invented.
    prev = _original(top) or old.get("previous_hooks_path") or _previous(top) or DEFAULT
    if _is_ours(prev, top):
        prev = DEFAULT
    damaged = bool(_check_problems(top, record_only=True))
    drift = _drift(top, old)
    chained = _bind(top, staged, prev, drift)
    digest = _staged_digest(staged)
    facts = _review(top, staged, old, digest, prev, chained, drift)
    if facts["unsafe"]:
        print(f"REFUSED (exit {EXIT_UNSAFE}): {'; '.join(facts['unsafe'])}. The review cannot be trusted to show every "
              f"byte, or the content can mislead a terminal: nothing changed and no flag overrides this. Review the "
              f"file by hand (git -C <repo> show {new_commit}:scripts/hooks/<name>, then diff it against the "
              f"installed copy in .git/blarai-hooks), or merge the change to main in smaller steps.")
        return EXIT_UNSAFE
    if dry_run:
        print(f'dry run: nothing changed. To apply exactly this: --update --reason "<why>" --approve {digest}'
              + (" --accept-drift" if facts["drift"] is None or facts["drift"] else ""))
        return 0
    need = []
    if not reason.strip():
        need.append('--reason "<why>"')
    if not approve:
        need.append(f"--approve {digest}")
    elif approve.strip().lower() != digest:
        print(f"NOT APPLIED (exit {EXIT_NOT_APPROVED}): you approved {_esc(approve)[:80]} but the staged copy is "
              f"{digest}: what you read is not what would be installed. Nothing changed.")
        return EXIT_NOT_APPROVED
    if (facts["drift"] is None or facts["drift"]) and not accept_drift:
        need.append("--accept-drift")
    if need:
        print(f"NOT APPLIED (exit {EXIT_NOT_APPROVED}): read the review above, then re-run with {' and '.join(need)}. "
              "--update trusts whatever main holds; approving the digest is the review of these changes.")
        return EXIT_NOT_APPROVED
    rec = _materialise(top, staged, prev, digest)
    _git(top, "config", "--local", PREV_KEY, prev, check=True)
    (_common(top) / MIRROR).write_text(prev + "\n", encoding="utf-8", newline="\n")
    if _original(top) is None:
        _git(top, "config", "--local", ORIG_KEY, prev, check=True)
    _log(top, action="update", from_commit=old.get("source_commit"), source_commit=rec["source_commit"],
         reason=reason.strip(), record_damaged=damaged, digest=digest, diff_stat=facts["stat"],
         files_added=facts["added"], files_removed=facts["removed"], files_renamed=facts["renamed"],
         drift=facts["drift"], accepted_drift=bool(accept_drift), previous_hooks_path=prev,
         interpreter=staged["interpreter"], interpreter_hash=staged["interpreter_hash"],
         interpreter_real=staged["interp"]["interpreter_real"],
         pyvenv_cfg_sha256=staged["interp"]["pyvenv_cfg_sha256"],
         base_interpreter=staged["interp"]["base_interpreter"],
         base_interpreter_hash=staged["interp"]["base_interpreter_hash"],
         base_interpreter_sha256=staged["interp"]["base_interpreter_sha256"])
    print(f"updated: hooks re-copied from {ref} ({rec['source_commit'][:10]}); previous hooks path "
          f"{'the default .git/hooks' if prev == DEFAULT else prev} kept; logged in {LOG}")
    return 0


def _run(args: list[str], input: str | None = None):
    return subprocess.run(["git", *args], capture_output=True, text=True, input=input)


DEGRADED = "previous hooks path"


def _previous_problems(top: Path, rec: dict) -> list[str]:
    """The chained previous-hooks path (config key and mirror file) must equal the install record; otherwise an
    unreviewed folder of hooks runs on every hook event while the install still looks intact (DEGRADED)."""
    want = rec.get("previous_hooks_path")
    out: list[str] = []
    if _previous(top) != want:
        out.append(f"the {DEGRADED} in .git/config ({_previous(top)!r}) differs from the install record ({want!r})")
    mirror = _common(top) / MIRROR
    got = mirror.read_text(encoding="utf-8").strip() if mirror.is_file() else None
    if got != want:
        out.append(f"the {DEGRADED} in {MIRROR} ({got!r}) differs from the install record ({want!r})")
    return out


def _check_problems(top: Path, record_only: bool = False) -> list[str]:
    """Everything that makes protection OFF or stale. Empty list = installed, intact and equal to main.
    record_only: only the record/installed-files consistency (not the comparison with main's tip)."""
    out: list[str] = []
    value = hooks_path(top)
    cur = _effective(top)
    if cur != value:
        out.append(f"core.hooksPath is {cur!r}, not the installed folder {value!r} (protection is OFF)")
        return out
    try:
        rec = rc.load_record(_common(top))
    except RuntimeError as exc:
        return out + [str(exc)]
    cwd = os.getcwd()
    os.chdir(top)
    try:
        bad = rc.record_problems(_run, rec, _inst(top))
    finally:
        os.chdir(cwd)
    if bad:
        return out + [f"{rc.MISMATCH}: " + "; ".join(bad)]
    out += _previous_problems(top, rec)
    if record_only:
        return out
    ref = _main_ref(top)
    source = _source(top, ref)
    if rec["hooks"] != dict(sorted(source.items())):
        diff = sorted(k for k in set(source) | set(rec["hooks"]) if source.get(k) != rec["hooks"].get(k))
        out.append(f"the installed hooks differ from {ref}'s tip ({', '.join(diff[:5])}): run --update")
    return out


def check(top: Path) -> int:
    problems = _check_problems(top)
    if problems:
        print("NOT OK: " + "; ".join(problems) + f". Recover: {_recover_hint(top)}")
        return 1
    rec = rc.load_record(_common(top))
    print(f"OK: installed from {rec['source_branch']} {rec['source_commit'][:10]}, intact, equal to main's tip; "
          f"{KEY} = {hooks_path(top)}; previous hooks path: {_previous(top) or '(none recorded)'}")
    return 0


def status(top: Path) -> int:
    problems = _check_problems(top)
    stale = [p for p in problems if "'s tip" in p]
    degraded = [p for p in problems if DEGRADED in p]
    hard = [p for p in problems if p not in stale and p not in degraded]
    if hard:
        print("Commit protection is OFF or BROKEN in this repository.")
        for p in hard:
            print(f"  - {p}")
        print(f"Fix: {_recover_hint(top)}")
        if _is_ours(_effective(top), top):
            print("(Until it runs, commits are blocked on EVERY branch and worktree: the guard fails closed.)")
        return 1
    if degraded:
        print("Commit protection is DEGRADED: main is still protected, but hooks you did not review would run too.")
        for p in degraded:
            print(f"  - {p} (DRIFT)")
        print(f"Fix: {_recover_hint(top)} (it shows the previous hooks and their hashes before anything changes).")
        return 1
    print("Commit protection is ON for this repository: a commit or any other update of main is checked by "
          "git itself before it happens.")
    if stale:
        print("  Note: main's hook files have changed since the copy was made: run --update (still ON with the older copy).")
    print("Three things would turn it off:")
    print(f"  1. core.hooksPath in .git/config no longer points at {hooks_path(top)}.")
    print(f"  2. The installed files or the record ({_common(top) / rc.RECORD_NAME}) inside .git are changed or deleted.")
    print("  3. The recorded base Python program (the hooks run it directly, verified by sha256 first) is moved, deleted or replaced.")
    print("`--check` proves 1-3 hold right now and that the copy equals main; it cannot prove they stay true.")
    return 0


def uninstall(top: Path) -> int:
    if not _is_ours(_effective(top), top):
        print(f"nothing to remove: {KEY} is {_effective(top)!r}, not the installed folder")
        return 0
    prev = _original(top)
    if prev is None:  # installed by an older version: fall back to the chained path only if it is not ours
        fallback = _previous(top)
        prev = fallback if fallback and not _is_ours(fallback, top) else None
    if prev is None or _is_ours(prev, top):
        print("refusing to uninstall: the hooks path from before the install is unknown "
              f"({ORIG_KEY} is not set), so restoring it would guess. Set it by hand "
              f"(git config --local {KEY} <the old path>, or git config --local --unset {KEY} for the default) "
              "and remove the installed copies yourself.")
        return 1
    _git(top, "config", "--local", "--unset", KEY)
    if prev != DEFAULT and _effective(top) != prev:
        _git(top, "config", "--local", KEY, prev, check=True)
    _git(top, "config", "--local", "--unset", PREV_KEY)
    _git(top, "config", "--local", "--unset", ORIG_KEY)
    common = _common(top)
    _log(top, action="uninstall", restored=prev)
    (common / MIRROR).unlink(missing_ok=True)
    (common / rc.RECORD_NAME).unlink(missing_ok=True)
    shutil.rmtree(_inst(top), ignore_errors=True)
    print(f"uninstalled: {KEY} restored to {prev if prev and prev != DEFAULT else '(unset)'}; installed copies removed")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=".", help="repository (default: current directory)")
    ap.add_argument("--reason", default="", help="why (required by --update; recorded in the install log)")
    ap.add_argument("--approve", default="", metavar="DIGEST", help="--update only: the DIGEST printed by the review; "
                    "the installer re-stages main and refuses on any mismatch")
    ap.add_argument("--accept-drift", action="store_true", help="--update only: also accept that the installed copy "
                    "differs from the install record (or that the record is unreadable)")
    ap.add_argument("--dry-run", action="store_true", help="--update only: print the review, change nothing")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--update", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--status", action="store_true")
    g.add_argument("--uninstall", action="store_true")
    a = ap.parse_args(argv)
    top = _toplevel(Path(a.repo))
    if a.check:
        return check(top)
    if a.status:
        return status(top)
    if a.uninstall:
        return uninstall(top)
    if a.update:
        return update(top, a.reason, a.approve, a.dry_run, a.accept_drift)
    return install(top, a.reason, a.approve, a.dry_run, a.accept_drift)


if __name__ == "__main__":
    sys.exit(main())
