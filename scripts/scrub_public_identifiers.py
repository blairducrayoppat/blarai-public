"""Scrub this machine's host name and the operator's account name from TRACKED files, in place, deterministically, and hold
the line on where the account name may appear.

Run:  python scripts/scrub_public_identifiers.py                 (rewrites; log to docs/reviews/public-identifier-scrub-log-<stamp>.md)
      python scripts/scrub_public_identifiers.py --check         (exit 1 if anything in scope still carries an identifier)
      python scripts/scrub_public_identifiers.py --log <path>    (rewrites; named log)

Recognition is ``scripts/identity_lock.py`` (digests plus the live machine; every view of the bytes, gzip members and UTF-16
included). The rewrite uses the live names and REFUSES unless each live name's digest is pinned there: run under another account
it would otherwise rewrite that account's name into the operator's placeholder. Two rewrites, nothing else:
  1. HOST NAME, every tracked file: becomes ``__HOST__``, any letter case, including glue (``<host>x``).
  2. OPERATOR ACCOUNT NAME, inside ``USER_SCOPE`` only (the containment studies and the performance records): becomes
     ``__USER__`` as a word (letters are the boundary; a JSON escape, an ANSI colour code, a percent-escape or a digit beside it
     does not hide it). A credential-store row (``"kind": "secret"``) is clean when its path no longer carries the name:
     ``C:\\Users\\__USER__\\.ssh``. The store names themselves are standard and hide nothing (see the round-2 review).

Outside the scope the account name is a working path this checkout needs, under a RATCHET: ``scripts/identity_user_baseline.json``
records, per file, how many tokens carried the name when the lock was set. ``--check`` and the gate fail when a file not listed
carries it, when a listed file carries MORE or FEWER than its listed count (the count follows the file down; at none, drop it
from the list), and when the list is anything but a subset-with-lower-or-equal-counts of the reference (``reference_baseline``). A person fixes a new occurrence by
hand (``%USERPROFILE%`` or ``__USER__``); the scrub does not rewrite outside the scope.

Bytes outside a match are untouched: line endings, byte-order marks, JSON layout and every number stay as they were. gzip members
are decompressed, scrubbed and recompressed with a fixed header (``gzip_bytes``); the deflate body depends on the zlib build, which
the log records;
UTF-16 files are decoded, scrubbed and re-encoded with their byte-order mark. Files are taken from ``git ls-files`` only. Other
binary files that carry an identifier are reported, not rewritten, and the run exits 1; so is a tracked file whose NAME carries one.

The log records, per changed file, the occurrences replaced and the sha256 of the LF-normalised bytes before and after. Neither
name is written to the log, the baseline or this file.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import identity_lock as il  # noqa: E402

HOST_PLACEHOLDER = b"__HOST__"
USER_PLACEHOLDER = b"__USER__"
USER_BASELINE_PATH = "scripts/identity_user_baseline.json"

# Where the operator's account name is scrubbed. A path that names a file is that file; a directory is everything under it.
USER_SCOPE: tuple[str, ...] = (
    "docs/research/windows-containment-comparison-2026-10",
    "docs/research/windows-containment-comparison-2026-10-10.md",
    "docs/research/containment-evidence-2026-10-05",
    "docs/performance",
    "PERFORMANCE_LOG.md",
)

# Boundaries for the account name: letters never touch it; a JSON escape, an ANSI colour code (up to seven bytes between
# ESC [ and the final letter), a percent-escape or a \\xHH / \\uHHHH escape may.
_ANSI_BRANCHES = b"|".join(rb"(?<=\x1b\[[0-9;?]{%d}[A-Za-z])" % n for n in range(0, 8))
_BOUNDARY_BEFORE = rb"(?:(?<![A-Za-z])|(?<=\\[ntrfb\"\\/])|(?<=%[0-9A-Fa-f]{2})|(?<=\\x[0-9A-Fa-f]{2})|(?<=\\u[0-9A-Fa-f]{4})|" + _ANSI_BRANCHES + rb")"
_BOUNDARY_AFTER = rb"(?![A-Za-z])"


def repo_root(start: Path) -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def lf_sha256(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def host_re(host: str) -> re.Pattern[bytes]:
    return re.compile(re.escape(host.encode("utf-8")), re.IGNORECASE)


def user_re(user: str) -> re.Pattern[bytes]:
    return re.compile(_BOUNDARY_BEFORE + re.escape(user.encode("utf-8")) + _BOUNDARY_AFTER, re.IGNORECASE)


def gzip_bytes(data: bytes) -> bytes:
    """gzip with a fixed 10-byte header (mtime 0, XFL 0, OS 255). The deflate body is whatever this interpreter's zlib build
    produces (zlib and zlib-ng differ), so the log records ``zlib.ZLIB_RUNTIME_VERSION``; the decompressed content is what the
    lock and the digests after decompression certify."""
    comp = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    body = comp.compress(data) + comp.flush()
    header = b"\x1f\x8b\x08\x00" + b"\x00\x00\x00\x00" + b"\x00\xff"
    trailer = (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "little") + (len(data) & 0xFFFFFFFF).to_bytes(4, "little")
    return header + body + trailer


# ---- credential-store rows ---------------------------------------------------------------------------------------------------

def json_secret_paths(data: bytes) -> list[str]:
    """Every ``path`` of a ``kind: secret`` row in a JSON document (gzip members included); empty when not JSON."""
    if data.startswith(il.GZIP_MAGIC):
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError):
            return []
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("kind") == "secret" and isinstance(node.get("path"), str):
                found.append(node["path"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    return found


def secret_rows_carrying_the_name(data: bytes, user_digests: frozenset[str]) -> int:
    return sum(1 for s in json_secret_paths(data) if il.find_hits(s.encode("utf-8"), frozenset(), user_digests)[1])


# ---- rewrite -----------------------------------------------------------------------------------------------------------------

def scrub_text(data: bytes, *, host: str | None, user: str | None, in_scope: bool) -> tuple[bytes, dict[str, int]]:
    counts = {"host": 0, "user": 0}
    if host:
        data, n = host_re(host).subn(HOST_PLACEHOLDER, data)
        counts["host"] += n
    if user and in_scope:
        data, n = user_re(user).subn(USER_PLACEHOLDER, data)
        counts["user"] += n
    return data, counts


def scrub_bytes(data: bytes, **kw) -> tuple[bytes, dict[str, int]]:
    """Dispatch on container: gzip member, UTF-16 text, or plain bytes."""
    if data.startswith(il.GZIP_MAGIC):
        try:
            inner = gzip.decompress(data)
        except (OSError, EOFError):
            return data, {"host": 0, "user": 0, "unreadable": 1}  # a member with trailing bytes: reported, never silently kept
        new, counts = scrub_bytes(inner, **kw)
        if new == inner:
            return data, counts
        return gzip_bytes(new), counts
    enc = il.looks_utf16(data)
    if enc:
        bom = data[:2] if data[:2] in (b"\xff\xfe", b"\xfe\xff") else b""
        text = data[len(bom):].decode(enc)
        new, counts = scrub_text(text.encode("utf-8"), **kw)
        return bom + new.decode("utf-8").encode(enc), counts
    return scrub_text(data, **kw)


def is_opaque_binary(data: bytes) -> bool:
    return b"\0" in data and not data.startswith(il.GZIP_MAGIC) and il.looks_utf16(data) is None


# ---- ratchet -----------------------------------------------------------------------------------------------------------------

def load_user_baseline(root: Path) -> dict[str, int]:
    p = root / USER_BASELINE_PATH
    if not p.exists():
        return {}
    return {k: int(v) for k, v in json.loads(p.read_text(encoding="utf-8"))["files"].items()}


FIRST_LANDING = "the baseline first lands in this history; nothing earlier to compare with"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True)


WINDOW = 20  # baseline versions (commits that changed the file on the first-parent line) the reference reads


def _parse_baseline(raw: bytes) -> dict[str, int] | None:
    try:
        return {k: int(v) for k, v in json.loads(raw.decode("utf-8"))["files"].items()}
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError, AttributeError, TypeError):
        return None


def _is_legacy_list_shape(raw: bytes) -> bool:
    """The pre-dict schema (``files`` a list of path strings, no counts): a version that predates the ratchet's counts, read as no version."""
    try:
        files = json.loads(raw.decode("utf-8")).get("files")
        return isinstance(files, list) and all(isinstance(f, str) for f in files)
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return False


def reference_baseline(root: Path) -> tuple[dict[str, int] | None, str]:
    """(the copy of the baseline this checkout must not exceed, reason it is missing).

    The reference is the pointwise MINIMUM over the last ``WINDOW`` versions of the baseline on the first-parent line of
    ``main`` (HEAD itself on main, a branch, or a detached HEAD alike): a file counts only if every version lists it, at its lowest
    count. A growth that merged without a gate run stays visible until ``WINDOW`` later baseline changes, so one skipped gate
    cannot make it the reference; its remedy is to bring the content (and count) back down.
    Every condition that leaves the comparison unable to run is a reason the caller reports, never a pass: a shallow clone, no
    commit yet, a ``main`` that does not resolve, a copy that is not a readable baseline. A version in the legacy list schema
    (every element a path string) reads as no version, as a deletion does; when no version with counts is left, that is a finding. The reference is a window of the first-parent line, so a branch lands with
    ``git merge --no-ff``: a fast-forward puts every intermediate development version of the branch on that line. The window
    is a horizon: a growth that merged ungated becomes the reference after ``WINDOW`` (20) later baseline versions.
    HONEST LIMIT: the comparison cannot see a growth older than ``WINDOW`` versions, nor tell a fast-forwarded branch's
    intermediate counts from main's own. The one silent case is FIRST_LANDING:
    the baseline was added in this history and ``main`` never carried one (no list-shape version either).
    """
    if _git(root, "rev-parse", "--is-shallow-repository").stdout.decode().strip() == "true":
        return None, "this is a shallow clone: the history the comparison reads is missing (git fetch --unshallow)"
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if head.returncode != 0:
        return None, "HEAD has no commit yet: nothing to compare the baseline with (commit first)"
    main = _git(root, "rev-parse", "--verify", "--quiet", "main^{commit}")
    ref = "main"
    if main.returncode != 0:
        return None, "main does not resolve in this checkout (fetch main before running the gate)"
    log = _git(root, "log", "--first-parent", "--format=%H", "-n", str(WINDOW), ref, "--", USER_BASELINE_PATH)
    if log.returncode != 0:
        return None, f"git log of {ref} failed; the comparison cannot run"
    versions: list[dict[str, int]] = []
    skipped_legacy = False
    for sha in log.stdout.decode().split():
        show = _git(root, "show", f"{sha}:{USER_BASELINE_PATH}")
        if show.returncode != 0:
            continue  # the commit deleted the file: no version to read
        if _is_legacy_list_shape(show.stdout):
            skipped_legacy = True
            continue  # the list schema carries no counts: no version to read, as for a deletion
        parsed = _parse_baseline(show.stdout)
        if parsed is None:
            return None, f"{sha[:10]}:{USER_BASELINE_PATH} is not a readable baseline"
        versions.append(parsed)
    if versions:
        keys = set(versions[0]).intersection(*versions[1:])
        return {k: min(v[k] for v in versions) for k in keys}, ""
    if skipped_legacy:
        return None, f"{ref} carries only legacy list-shape baselines: no version with counts to compare with"
    added = _git(root, "log", "--diff-filter=A", "--format=%H", "-n", "1", "HEAD", "--", USER_BASELINE_PATH).stdout.decode().strip()
    if added and _git(root, "merge-base", "--is-ancestor", added, ref).returncode != 0:
        return None, FIRST_LANDING
    return None, f"{ref} carries no {USER_BASELINE_PATH}"


def fork_baseline(root: Path) -> dict[str, int] | None:
    """The baseline as it stood where this branch left main (None when unknown); names what main changed behind a branch."""
    base = _git(root, "merge-base", "HEAD", "main")
    head = _git(root, "rev-parse", "HEAD")
    if base.returncode != 0 or base.stdout.strip() == head.stdout.strip():
        return None  # no fork point, or HEAD is main itself (or behind it): nothing main changed behind this checkout
    show = _git(root, "show", f"{base.stdout.decode().strip()}:{USER_BASELINE_PATH}")
    return _parse_baseline(show.stdout) if show.returncode == 0 else None


def save_user_baseline(root: Path, counts: dict[str, int]) -> None:
    body = {
        "what": "tracked files outside scrub_public_identifiers.USER_SCOPE that carried the operator account name when the lock was set "
                "(2026-10-14, #1765), with the number of tokens carrying it; a file not listed that carries the name fails the gate, a "
                "listed file carries exactly its count (a count follows the file down; a file carrying none is dropped), and the list may "
                "only be a subset of the reference copy with lower or equal counts",
        "count": len(counts),
        "files": dict(sorted(counts.items())),
    }
    (root / USER_BASELINE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / USER_BASELINE_PATH).write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8", newline="\n")


def ratchet_violations(root: Path, files: list[Path], user_digests: frozenset[str], baseline: dict[str, int],
                       main_baseline: dict[str, int] | None, missing_reason: str = "",
                       fork: dict[str, int] | None = None) -> list[str]:
    """Every way the account name's footprint outside USER_SCOPE could have grown (see the module docstring).

    ``main_baseline`` is the reference copy (``reference_baseline``); when it is None the comparison did not run, which is a
    finding unless ``missing_reason`` is FIRST_LANDING. ``fork`` is the baseline where the branch left main: an entry main
    removed or lowered since then is named as main's change, not the branch's.
    """
    problems: list[str] = []
    if main_baseline is None and missing_reason != FIRST_LANDING:
        problems.append(f"ratchet: the branch comparison did not run: {missing_reason or 'no reference baseline given'}")
    seen: set[str] = set()
    for p in files:
        r = rel(root, p)
        if r == USER_BASELINE_PATH or il.path_in_scope(r, USER_SCOPE):
            continue
        n = il.count_user_hits(p.read_bytes(), user_digests)
        if r in baseline:
            seen.add(r)
            if n == 0:
                problems.append(f"{r}: listed in the baseline but carries the name no more; drop it from the list")
            elif n > baseline[r]:
                problems.append(f"{r}: carries the operator name {n} times, baseline allows {baseline[r]}; new content must not add it")
            elif n < baseline[r]:
                problems.append(f"{r}: carries the operator name {n} time(s), listed {baseline[r]}; lower the listed count to {n} (a count follows the file down)")
        elif n:
            problems.append(f"{r}: operator user name in a file outside the baseline (new content must not carry it; use %USERPROFILE% or __USER__)")
    for r in sorted(set(baseline) - seen):
        problems.append(f"{r}: listed in the baseline but not tracked; drop it from the list")
    if main_baseline is not None and main_baseline != baseline:
        for r, n in baseline.items():
            if r not in main_baseline:
                if fork is not None and r in fork and baseline[r] <= fork[r]:
                    problems.append(f"{r}: main dropped this file from the baseline after this branch was cut; merge main (not a growth by this branch)")
                else:
                    problems.append(f"{r}: added to the baseline on this branch; the list never grows")
            elif n > main_baseline[r]:
                if fork is not None and r in fork and n <= fork[r]:
                    problems.append(f"{r}: main lowered this count to {main_baseline[r]} after this branch was cut ({fork[r]}); merge main (not a raise by this branch)")
                else:
                    problems.append(f"{r}: baseline count raised on this branch ({main_baseline[r]} -> {n}); the counts never rise")
    return problems


# ---- check -------------------------------------------------------------------------------------------------------------------

def check(root: Path, files: list[Path], host: str | None, user: str | None) -> list[str]:
    hd, ud = il.digests_with_live(host, user)
    problems: list[str] = []
    for p in files:
        r = rel(root, p)
        if il.name_in_path(r, hd, ud):
            problems.append(f"{r}: file NAME carries an identifier (rename it)")
        data = p.read_bytes()
        hosts, users = il.find_hits(data, hd, ud)
        if hosts:
            problems.append(f"{r}: host name present")
        if users and il.path_in_scope(r, USER_SCOPE):
            problems.append(f"{r}: operator user name present")
        if p.suffix.lower() in (".json", ".gz"):
            bad = secret_rows_carrying_the_name(data, ud)
            if bad:
                problems.append(f"{r}: {bad} credential-store row(s) carry the operator name")
    reference, reason = reference_baseline(root)
    problems += ratchet_violations(root, files, ud, load_user_baseline(root), reference, reason, fork_baseline(root))
    return problems


# ---- main --------------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report, change nothing; exit 1 on any finding")
    ap.add_argument("--log", type=Path, help="Markdown log to write (default: docs/reviews/public-identifier-scrub-log-<stamp>.md)")
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    args = ap.parse_args(argv)

    root = repo_root(args.repo)
    host, user = il.live_names()
    if host is None or user is None:
        ap.error("the host or user name is not readable on this machine (COMPUTERNAME / USERNAME); refusing")
    files = [p for p in il.read_tracked(root) if p.is_file()]

    if args.check:
        problems = check(root, files, host, user)
        for line in problems:
            print("FAIL", line)
        if reference_baseline(root) == (None, FIRST_LANDING):
            print(f"NOTE ratchet: branch comparison skipped: {FIRST_LANDING}")
        print(f"scrub_public_identifiers --check: {len(problems)} finding(s) in {len(files)} tracked files")
        return 1 if problems else 0

    host_pinned, user_pinned = il.live_names_are_pinned()
    if not (host_pinned and user_pinned):
        ap.error("the live host or user name is not one of the pinned identities in scripts/identity_lock.py; refusing to rewrite "
                 "(running as another account would rewrite that account's name into the operator's placeholder)")

    from datetime import datetime

    log_path = args.log or root / "docs" / "reviews" / f"public-identifier-scrub-log-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.md"
    hd, ud = il.digests_with_live(host, user)
    rows: list[str] = []
    skipped: list[str] = []
    residual: list[str] = []
    named: list[str] = []
    totals = {"host": 0, "user": 0}
    for p in files:
        r = rel(root, p)
        if r == USER_BASELINE_PATH:
            continue
        if il.name_in_path(r, hd, ud):
            named.append(r)
        data = p.read_bytes()
        in_scope = il.path_in_scope(r, USER_SCOPE)
        if is_opaque_binary(data):
            hosts, users = il.find_hits(data, hd, ud)
            if hosts or (users and in_scope):
                skipped.append(r)
            continue
        new, counts = scrub_bytes(data, host=host, user=user, in_scope=in_scope)
        if counts.get("unreadable"):
            hosts, users = il.find_hits(data, hd, ud)
            if hosts or (users and in_scope):
                skipped.append(f"{r} (gzip member with trailing bytes)")
            continue
        hosts, users = il.find_hits(new, hd, ud)
        if hosts or (users and in_scope):
            residual.append(r)  # a shape the lock sees and the rewrite does not clear (identity_lock HONEST LIMIT)
        if new == data:
            continue
        p.write_bytes(new)
        for k in totals:
            totals[k] += counts[k]
        rows.append(f"| `{r}` | {counts['host']} | {counts['user']} | `{lf_sha256(data)}` | `{lf_sha256(new)}` |")

    log_lines = [
        "# Public-identifier scrub log",
        "",
        f"Rewrote {len(rows)} tracked file(s): host-name occurrences {totals['host']} (whole tree), operator user-name occurrences {totals['user']} (USER_SCOPE only). "
        "Identifiers are not written here; `scripts/scrub_public_identifiers.py --check` and `tests/security/test_no_host_identity_in_tree.py` verify the result.",
        "",
        f"Interpreter: Python {sys.version.split()[0]}, zlib {zlib.ZLIB_RUNTIME_VERSION} (gzip bodies are reproducible with this zlib build; "
        "the decompressed content is what the lock certifies).",
        "",
        "| file | host | user | sha256 before (LF) | sha256 after (LF) |",
        "|---|---|---|---|---|",
        *rows,
    ]
    if skipped:
        log_lines += ["", "Binary files carrying an identifier, NOT rewritten (exit 1):", *[f"- `{s}`" for s in skipped]]
    if residual:
        log_lines += ["", "Files still carrying an identifier in a shape the rewrite does not clear (hand edit; exit 1):", *[f"- `{s}`" for s in residual]]
    if named:
        log_lines += ["", "Tracked file NAMES carrying an identifier, NOT renamed (exit 1):", *[f"- `{s}`" for s in named]]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8", newline="\n")
    print(f"rewrote {len(rows)} file(s); log {log_path}")
    if skipped or named or residual:
        print(f"WARNING: {len(skipped)} binary file(s), {len(residual)} unrewritable shape(s) and {len(named)} file name(s) still carry an identifier; see the log")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
