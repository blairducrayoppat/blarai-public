"""Scrub this machine's host name, volume serial numbers and the operator's account name from TRACKED files, in place, deterministically, and hold
the line on where the account name may appear.

Run:  python scripts/scrub_public_identifiers.py                 (rewrites; log to docs/reviews/public-identifier-scrub-log-<stamp>.md)
      python scripts/scrub_public_identifiers.py --check         (exit 1 if anything in scope still carries an identifier)
      python scripts/scrub_public_identifiers.py --log <path>    (rewrites; named log)
      python scripts/scrub_public_identifiers.py --dir <path> [--check]   (a directory outside git, every file in it, all rules)

Recognition is ``scripts/identity_lock.py`` (digests plus the live machine; every view of the bytes, gzip members and UTF-16
included). The rewrite uses the live names and REFUSES unless each live name's digest is pinned there: run under another account
it would otherwise rewrite that account's name into the operator's placeholder. Five rewrites, nothing else:
  1. HOST NAME, every tracked file: becomes ``__HOST__``, any letter case, including glue (``<host>x``).
  3. VOLUME SERIAL, every tracked file: the serial in a ``Volume Serial Number is`` header (any machine's) and each live fixed
     volume's serial in the dashed, bare-hex and decimal forms become ``XXXX-XXXX``; the log names the file and the count, never
     the serial. A serial in an encoded view the rewrite does not cover is reported for a hand edit, as a name is.
  2. OPERATOR ACCOUNT NAME, inside ``USER_SCOPE`` only (the containment studies and the performance records): becomes
     ``__USER__`` as a word (letters are the boundary; a JSON escape, an ANSI colour code, a percent-escape or a digit beside it
     does not hide it). A credential-store row (``"kind": "secret"``) is clean when its path no longer carries the name:
     ``C:\\Users\\__USER__\\.ssh``. The store names themselves are standard and hide nothing (see the round-2 review).
  4. MACHINE ACCOUNT SID, inside ``SID_SCOPE`` (and every file of a ``--dir`` run): ``S-1-5-21-<a>-<b>-<c>[-<rid>]`` becomes
     ``S-1-5-21-__MACHINE__[-<rid>]``; the relative id stays (it says which account, not which machine). Well-known SIDs
     (``S-1-5-32-*``, ``S-1-16-*``, ``S-1-15-2-*``, ``S-1-5-18``) do not match and stay. Tracked files outside ``SID_SCOPE`` carry
     placeholder and foreign-domain SIDs as evidence and are guarded by ``tests/security/test_no_machine_sid_domain_in_tree.py``.
     The rewrite reads the raw bytes at the boundaries the lock reads its decoded views at (after a JSON escape, a percent-escape,
     an ANSI colour code; the first letter may be a JSON unicode or hex escape); a SID in any other encoding is reported for a hand edit.
     ``--dir`` also fails closed on a SID in a file or folder NAME, on a gzip member it cannot decompress and on an archive: a
     readable zip is scanned member by member and never rewritten, any other archive format is reported (unpack, scrub, repack).
  5. MICROSOFT-ACCOUNT AND ENTRA ID ACCOUNT SID, every tracked file (and every file of a ``--dir`` run): ``S-1-11-96-<...>`` and
     ``S-1-12-1-<...>`` become ``S-1-11-__ACCOUNT__`` and ``S-1-12-__ACCOUNT__``. Every sub-authority names one person's
     cloud account, so none is kept. Same boundaries and escapes as rule 4; any other encoding, a file NAME carrying one and a
     binary file carrying one are reported for a hand edit and the run exits 1; ``--check`` and the gate fail while one remains.
     ``--check``, the gate and the tree-mode residual check open gzip, bzip2, xz, zip and tar in every tracked file, nested to
     ``identity_lock.ACCOUNT_CONTAINER_MAX_DEPTH``, and fail on any container they cannot read
     (``identity_lock.account_sid_container_problems``); the rewrite never edits inside an archive.
     HONEST LIMIT of rule 5, beyond the encodings ``identity_lock`` names: not seen are the binary SID structure (revision byte
     ``01``, then the sub-authority count and little-endian sub-authorities) and its registry-export form (``hex:01,..``); a SID
     glued after a letter or a digit (``userS-1-11-96-...`` is one token, as for rule 4); the sub-authority digits without
     their ``S-1-11-96`` / ``S-1-12-1`` prefix. The last is held, for sub-authorities of eight digits or more, by
     ``tests/security/test_account_sid_scrub.py`` when the current token carries a Microsoft-account or Entra ID SID (no long
     sub-authority of it appears in any tracked file; the test skips, naming why, under a token without one); shorter
     sub-authorities, and a SID that is not the live account's, are not seen in those shapes.

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
import io
import json
import re
import subprocess
import sys
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import identity_lock as il  # noqa: E402

HOST_PLACEHOLDER = b"__HOST__"
USER_PLACEHOLDER = b"__USER__"
SERIAL_PLACEHOLDER = il.SERIAL_PLACEHOLDER
USER_BASELINE_PATH = "scripts/identity_user_baseline.json"

# Where the operator's account name is scrubbed. A path that names a file is that file; a directory is everything under it.
USER_SCOPE: tuple[str, ...] = (
    "docs/research/windows-containment-comparison-2026-10",
    "docs/research/windows-containment-comparison-2026-10-10.md",
    "docs/research/containment-evidence-2026-10-05",
    "docs/performance",
    "PERFORMANCE_LOG.md",
)

# Where a machine/domain account SID is scrubbed and locked in tracked files (same path semantics as USER_SCOPE; an entry ending
# in ``*`` is a name prefix). Every entry matches a tracked file (tests/security/test_machine_sid_scrub.py).
SID_SCOPE: tuple[str, ...] = (
    "docs/performance/mxc_proxy_egress*",
    "docs/performance/mxc_1406_probe_2026-10-11",
    "docs/research/windows-containment-comparison-2026-10/mxc-1406-probe",
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
        except il.READ_ERRORS:
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

def scrub_text(data: bytes, *, host: str | None, user: str | None, in_scope: bool,
               serials: frozenset[int] = frozenset(), sid_scope: bool = False) -> tuple[bytes, dict[str, int]]:
    counts = {"host": 0, "user": 0, "serial": 0, "sid": 0, "account": 0}
    data, n = il.SERIAL_HEADER_RE.subn(lambda m: m.group(0)[:m.start(1) - m.start(0)] + SERIAL_PLACEHOLDER, data)
    counts["serial"] += n
    for pat in il.serial_res(serials):
        data, n = pat.subn(SERIAL_PLACEHOLDER, data)
        counts["serial"] += n
    if host:
        data, n = host_re(host).subn(HOST_PLACEHOLDER, data)
        counts["host"] += n
    if user and in_scope:
        data, n = user_re(user).subn(USER_PLACEHOLDER, data)
        counts["user"] += n
    if sid_scope:
        data, n = il.rewrite_machine_sids(data)
        counts["sid"] += n
    data, n = il.rewrite_account_sids(data)
    counts["account"] += n
    return data, counts


def scrub_bytes(data: bytes, _depth: int = 0, **kw) -> tuple[bytes, dict[str, int]]:
    """Dispatch on container: gzip member, wide-character text (UTF-16 or UTF-32), or plain bytes. Input it cannot read
    (``il.unreadable_reason``) comes back unchanged with ``counts['unreadable']`` set; it never raises on content."""
    unreadable = {"host": 0, "user": 0, "serial": 0, "sid": 0, "account": 0, "unreadable": 1}
    if data.startswith(il.GZIP_MAGIC):
        try:
            inner = gzip.decompress(data)
        except il.READ_ERRORS:
            return data, unreadable  # a member with trailing bytes or damage: reported, never silently kept
        if _depth >= il.GZIP_MAX_DEPTH:
            return data, unreadable
        new, counts = scrub_bytes(inner, _depth + 1, **kw)
        if new == inner:
            return data, counts
        return gzip_bytes(new), counts
    enc = il.looks_utf16(data)
    if enc:
        bom, body = il.split_bom(data, enc)
        try:
            text = body.decode(enc)
        except UnicodeError:
            return data, unreadable
        new, counts = scrub_text(text.encode("utf-8"), **kw)
        return bom + new.decode("utf-8").encode(enc), counts
    return scrub_text(data, **kw)


def is_opaque_binary(data: bytes) -> bool:
    return b"\0" in data and not data.startswith(il.GZIP_MAGIC) and il.looks_utf16(data) is None


# ---- containers the lock cannot read -----------------------------------------------------------------------------------------

_ARCHIVE_MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "zip"), (b"PK\x05\x06", "zip"), (b"7z\xbc\xaf\x27\x1c", "7z"), (b"Rar!", "rar"), (b"BZh", "bzip2"),
    (b"\xfd7zXZ\x00", "xz"), (b"\x28\xb5\x2f\xfd", "zstd"),
)
_ARCHIVE_SUFFIXES = {".zip": "zip", ".jar": "zip", ".whl": "zip", ".7z": "7z", ".rar": "rar", ".tar": "tar", ".tgz": "tar",
                     ".bz2": "bzip2", ".xz": "xz", ".zst": "zstd", ".cab": "cab"}
_ZIP_MAX_BYTES = 256 * 1024 * 1024


def archive_kind(data: bytes, name: str = "") -> str | None:
    """The archive format the bytes (or, failing that, the file name's suffix) say, else None. gzip is not an archive here."""
    for magic, kind in _ARCHIVE_MAGICS:
        if data.startswith(magic):
            return kind
    if data[257:262] == b"ustar":
        return "tar"
    return _ARCHIVE_SUFFIXES.get(Path(name).suffix.lower())


def container_problems(data: bytes, name: str, hd: frozenset[str], ud: frozenset[str], sd: frozenset[str], depth: int = 0) -> list[str]:
    """Why a file cannot be certified clean because of its container; empty for plain text, UTF-16 and a gzip member the lock reads.
    Fails closed: a gzip member that cannot be decompressed (trailing bytes, damage), UTF-16 text that does not decode, an archive format this script does not read
    (unpack, scrub and repack by hand), a zip that cannot be opened, is encrypted or is oversized. A readable zip is scanned
    member by member (names and contents) and never rewritten."""
    if data.startswith(il.GZIP_MAGIC):
        try:
            inner = gzip.decompress(data)
        except il.READ_ERRORS:
            return ["unreadable: gzip member that cannot be read (trailing bytes or damage); its content is not checked"]
        if depth >= il.GZIP_MAX_DEPTH:
            return ["unreadable (nesting depth): gzip nested deeper than four; its content is not checked"]
        return container_problems(inner, "", hd, ud, sd, depth + 1)
    kind = archive_kind(data, name)
    if kind is None:
        problem = il.utf16_problem(data)
        return [problem] if problem else []
    if kind != "zip" or depth >= 3:
        return [f"{kind} archive: its members are not read here; unpack, scrub and repack by hand"]
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if sum(i.file_size for i in infos) > _ZIP_MAX_BYTES:
                return ["zip archive over the size this script reads"]
            out: list[str] = []
            for n, info in enumerate(infos):
                if info.flag_bits & 0x1:
                    return ["zip archive with an encrypted member: its content is not checked"]
                label = f"zip member #{n}"
                member = info.filename.encode("utf-8")
                if (il.name_in_path(info.filename, hd, ud) or il.find_sid_hits(member) or il.find_account_sid_hits(member)
                        or il.find_serial_hits(member, sd)):
                    out.append(f"{label}: NAME carries an identifier")
                if info.is_dir():
                    continue
                body = z.read(info)
                hosts, users = il.find_hits(body, hd, ud)
                if hosts or users or il.find_serial_hits(body, sd) or il.find_sid_hits(body) or il.find_account_sid_hits(body):
                    out.append(f"{label}: identifier present")
                out += [f"{label}: {m}" for m in container_problems(body, info.filename, hd, ud, sd, depth + 1)]
            return out
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError, EOFError, zlib.error):
        return ["zip archive that cannot be opened: its content is not checked"]


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

def check(root: Path, files: list[Path], host: str | None, user: str | None,
          serial_digests: frozenset[str] | None = None) -> list[str]:
    hd, ud = il.digests_with_live(host, user)
    sd = il.serial_digests() if serial_digests is None else serial_digests
    problems: list[str] = []
    if not sd:
        problems.append("volume serials: no local fixed volume serial is readable on this machine; the lock cannot see its subject")
    for p in files:
        r = rel(root, p)
        if il.name_in_path(r, hd, ud):
            problems.append(f"{r}: file NAME carries an identifier (rename it)")
        if il.find_sid_hits(r.encode("utf-8")):
            problems.append(f"{r}: file NAME carries a machine/domain account SID (rename it)")
        if il.find_account_sid_hits(r.encode("utf-8")):
            problems.append(f"{r}: file NAME carries a Microsoft-account or Entra ID account SID (rename it)")
        if il.find_serial_hits(r.encode("utf-8"), sd):
            problems.append(f"{r}: file NAME carries a volume serial number (rename it; tracked file #{files.index(p)})")
        data = p.read_bytes()
        hosts, users = il.find_hits(data, hd, ud)
        if hosts:
            problems.append(f"{r}: host name present")
        if users and il.path_in_scope(r, USER_SCOPE):
            problems.append(f"{r}: operator user name present")
        if il.path_in_scope(r, SID_SCOPE) and il.find_sid_hits(data):
            problems.append(f"{r}: machine/domain account SID present (S-1-5-21-...)")
        account = il.account_sid_container_problems(data, r)
        if il.path_in_scope(r, SID_SCOPE):
            account = [m for m in account if "unreadable" not in m]  # container_problems below names what it cannot read here
        problems += [f"{r}: {m}" for m in account]
        if il.path_in_scope(r, SID_SCOPE):
            problems += [f"{r}: {m}" for m in container_problems(data, r, hd, ud, sd)]
        kinds = il.find_serial_hits(data, sd)
        if "live" in kinds:
            problems.append(f"{r}: volume serial present (a live fixed volume's)")
        if "header" in kinds:
            problems.append(f"{r}: volume serial present (a 'Volume Serial Number is' header)")
        if p.suffix.lower() in (".json", ".gz"):
            bad = secret_rows_carrying_the_name(data, ud)
            if bad:
                problems.append(f"{r}: {bad} credential-store row(s) carry the operator name")
    reference, reason = reference_baseline(root)
    problems += ratchet_violations(root, files, ud, load_user_baseline(root), reference, reason, fork_baseline(root))
    return [il.redact_serials(p, sd) for p in problems]  # a report that names a file never prints a serial the name carries


# ---- a directory outside git ------------------------------------------------------------------------------------------------

def run_dir(ap: argparse.ArgumentParser, directory: Path, *, check_only: bool, log_path: Path | None = None) -> int:
    """Rewrite (or, with ``check_only``, only report) every file under ``directory``: host name, account name, volume serials and
    machine and cloud account SIDs. Files are walked, not taken from git; the account-name ratchet does not apply. Names are never printed.
    Fails closed on what it cannot read: a file or folder NAME carrying an identifier, a gzip member it cannot decompress, an
    archive it cannot open (a readable zip is scanned, never rewritten), and a SID or other identifier left in a shape the
    rewrite does not clear. A rewriting run writes a log (file index, name hash and before/after hashes; no names)."""
    directory = directory.resolve()
    if not directory.is_dir():
        ap.error(f"{directory} is not a directory")
    host, user = il.live_names()
    if host is None or user is None:
        ap.error("the host or user name is not readable on this machine (COMPUTERNAME / USERNAME); refusing")
    if not check_only:
        host_pinned, user_pinned = il.live_names_are_pinned()
        if not (host_pinned and user_pinned):
            ap.error("the live host or user name is not one of the pinned identities in scripts/identity_lock.py; refusing to rewrite")
        if log_path is None:
            try:
                default_root = repo_root(Path.cwd())
            except (subprocess.CalledProcessError, OSError):
                print("scrub_public_identifiers --dir: no --log given and the working directory is not inside a git checkout; "
                      "pass --log with a path outside the folder", file=sys.stderr)
                return 1
            log_path = default_root / "docs" / "reviews" / f"public-identifier-scrub-dir-log-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.md"
        if directory in log_path.resolve().parents:
            ap.error("the log would be written inside the folder being scrubbed; give --log a path outside it")
    hd, ud = il.digests_with_live(host, user)
    serials = il.live_volume_serials()
    sd = il.serial_digests(serials)
    if not sd:
        ap.error("no local fixed volume serial is readable on this machine; refusing")
    # Stage first, write last. Every precondition of the rewrite is proven for every file before any byte is written: the name can be
    # encoded and logged, the file can be read, its content is readable, and a file that would change can be opened for writing. Any
    # failure is a named refusal of the whole run (nothing rewritten, the log still written); a write that fails afterwards is rolled back.
    walk = sorted(x for x in directory.rglob("*") if x.is_file())
    items: list[dict] = []
    refused: list[str] = []
    for n, p in enumerate(walk):
        rel_name = p.relative_to(directory).as_posix()
        try:
            name_b = rel_name.encode("utf-8")
            encodable = True
        except UnicodeEncodeError:
            name_b = rel_name.encode("utf-8", "surrogatepass")
            encodable = False
        sid_name = il.find_sid_hits(name_b)
        account_name = il.find_account_sid_hits(name_b)
        r = f"file #{n}" if (sid_name or account_name or not encodable) else il.redact_serials(rel_name, sd)  # such a name is never printed
        item = {"n": n, "p": p, "rel_name": rel_name, "name_b": name_b, "r": r, "sid_name": sid_name, "account_name": account_name, "encodable": encodable,
                "data": None, "new": None, "archive": False}
        items.append(item)
        if not encodable:
            refused.append(f"{r}: file NAME cannot be encoded as UTF-8, so it cannot be logged (rename it)")
        try:
            data = p.read_bytes()
        except OSError as e:
            refused.append(f"{r}: unreadable: cannot be read ({type(e).__name__})")
            continue
        item["data"] = data
        item["archive"] = archive_kind(data, rel_name) is not None
        if item["archive"] or is_opaque_binary(data):
            continue
        reason = il.unreadable_reason(data)
        if reason:
            refused.append(f"{r}: {reason}")
            continue
        if check_only:
            continue
        try:
            new, _ = scrub_bytes(data, host=host, user=user, in_scope=True, serials=serials, sid_scope=True)
        except (OSError, UnicodeError, ValueError, RecursionError) as e:
            refused.append(f"{r}: could not be processed ({type(e).__name__})")
            continue
        if new != data:
            try:
                with open(p, "r+b"):
                    pass
            except OSError as e:
                refused.append(f"{r}: cannot be written ({type(e).__name__})")
                continue
            item["new"] = new
    changed = 0
    rows: list[str] = []
    if not check_only and not refused:
        written: list[dict] = []
        for item in items:
            if item["new"] is None:
                continue
            try:
                item["p"].write_bytes(item["new"])
            except OSError as e:
                refused.append(f"{item['r']}: write failed ({type(e).__name__}); the files already written were restored")
                for done in written:
                    try:
                        done["p"].write_bytes(done["data"])
                    except OSError:
                        refused.append(f"{done['r']}: could not be restored after a failed run; restore it from its source")
                written = []
                break
            written.append(item)
        if not refused:
            for item in written:
                changed += 1
                rows.append(f"| {item['n']} | `{hashlib.sha256(item['name_b']).hexdigest()[:16]}` | `{lf_sha256(item['data'])}` | `{lf_sha256(item['new'])}` |")
    findings: list[str] = []
    for item in items:
        r, rel_name, data = item["r"], item["rel_name"], item["data"]
        if data is None:
            continue
        if il.name_in_path(rel_name, hd, ud) if item["encodable"] else False:
            findings.append(f"{r}: file NAME carries an identifier (rename it)")
        if item["sid_name"]:
            findings.append(f"{r}: file or folder NAME carries a machine/domain account SID (rename it)")
        if item["account_name"]:
            findings.append(f"{r}: file or folder NAME carries a Microsoft-account or Entra ID account SID (rename it)")
        findings += [f"{r}: {m}" for m in container_problems(data, rel_name, hd, ud, sd)]
        if item["archive"]:
            continue  # reported above; its bytes are not rewritten and a zip's members were scanned
        if item["new"] is not None and changed:
            data = item["new"]
        hosts, users = il.find_hits(data, hd, ud)
        sid = il.find_sid_hits(data) or il.find_account_sid_hits(data)
        if hosts or users or il.find_serial_hits(data, sd) or sid:
            what = "machine/domain or cloud account SID in a shape the rewrite does not clear" if sid and not (hosts or users) and not check_only else "identifier present"
            findings.append(f"{r}: {what}" + (" (binary, not rewritten)" if is_opaque_binary(data) else ""))
    if refused:
        findings = refused + [f"run refused: {len(refused)} problem(s) stopped the rewrite, so nothing was rewritten"] + findings
    findings = list(dict.fromkeys(findings))  # a file named by the stage and by the container check counts once
    for line in findings:
        print("FAIL", line)
    print(f"scrub_public_identifiers --dir{' --check' if check_only else ''}: {changed} file(s) rewritten, {len(findings)} finding(s)")
    if not check_only:
        log_lines = [
            "# Public-identifier scrub log (--dir)", "",
            f"Rewrote {changed} file(s) of a folder outside git; {len(findings)} finding(s) remain. Names and identifiers are not written here: "
            "files are identified by their index in the sorted walk and the first 16 hex digits of the sha256 of the relative name.", "",
            f"Interpreter: Python {sys.version.split()[0]}, zlib {zlib.ZLIB_RUNTIME_VERSION}.", "",
            "| index | name sha256 | sha256 before (LF) | sha256 after (LF) |", "|---|---|---|---|", *rows,
        ]
        if findings:
            log_lines += ["", "Findings (exit 1):", *[f"- {f}" for f in findings]]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8", newline="\n")
        print(f"log {log_path}")
    return 1 if findings else 0


# ---- main --------------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report, change nothing; exit 1 on any finding")
    ap.add_argument("--log", type=Path, help="Markdown log to write (default: docs/reviews/public-identifier-scrub-log-<stamp>.md)")
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--dir", type=Path, help="a directory outside git: every file in it is in scope for every rule (no ratchet); a rewriting run writes --log")
    args = ap.parse_args(argv)

    if args.dir is not None:
        return run_dir(ap, args.dir, check_only=args.check, log_path=args.log)

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

    log_path = args.log or root / "docs" / "reviews" / f"public-identifier-scrub-log-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.md"
    hd, ud = il.digests_with_live(host, user)
    rows: list[str] = []
    skipped: list[str] = []
    residual: list[str] = []
    named: list[str] = []
    totals = {"host": 0, "user": 0, "serial": 0, "sid": 0, "account": 0}
    serials = il.live_volume_serials()
    if not serials:
        ap.error("no local fixed volume serial is readable on this machine; refusing (the rewrite could not clear a live serial)")
    sd = il.serial_digests(serials)
    for p in files:
        r = rel(root, p)
        if r == USER_BASELINE_PATH:
            continue
        shown = il.redact_serials(r, sd)  # the log and the console never print a serial the file name carries
        name_sid = il.find_sid_hits(r.encode("utf-8")) or il.find_account_sid_hits(r.encode("utf-8"))
        if il.name_in_path(r, hd, ud) or il.find_serial_hits(r.encode("utf-8"), sd) or name_sid:
            named.append("a file name carrying a SID" if name_sid else shown)
        data = p.read_bytes()
        in_scope = il.path_in_scope(r, USER_SCOPE)
        sid_scope = il.path_in_scope(r, SID_SCOPE)
        if sid_scope and archive_kind(data, r) is not None:
            skipped.append(f"{shown} (archive, not rewritten)")  # a tracked archive in SID_SCOPE: its bytes are never rewritten
            continue
        if is_opaque_binary(data):
            hosts, users = il.find_hits(data, hd, ud)
            if (hosts or (users and in_scope) or il.find_serial_hits(data, sd) or (sid_scope and il.find_sid_hits(data))
                    or il.account_sid_container_problems(data, r)):
                skipped.append(shown)
            continue
        new, counts = scrub_bytes(data, host=host, user=user, in_scope=in_scope, serials=serials, sid_scope=sid_scope)
        if counts.get("unreadable"):
            hosts, users = il.find_hits(data, hd, ud)
            if hosts or (users and in_scope) or il.find_serial_hits(data, sd) or sid_scope or il.account_sid_container_problems(data, r):
                skipped.append(f"{shown} (unreadable: gzip member with trailing bytes or damage, or UTF-16 text that does not decode)")
            continue
        hosts, users = il.find_hits(new, hd, ud)
        if (hosts or (users and in_scope) or il.find_serial_hits(new, sd) or (sid_scope and il.find_sid_hits(new))
                or il.account_sid_container_problems(new, r)):
            residual.append(shown)  # a shape the lock sees and the rewrite does not clear (identity_lock HONEST LIMIT)
        if new == data:
            continue
        p.write_bytes(new)
        for k in totals:
            totals[k] += counts[k]
        rows.append(f"| `{shown}` | {counts['host']} | {counts['user']} | {counts['serial']} | {counts['sid']} | {counts['account']} | `{lf_sha256(data)}` | `{lf_sha256(new)}` |")

    log_lines = [
        "# Public-identifier scrub log",
        "",
        f"Rewrote {len(rows)} tracked file(s): host-name occurrences {totals['host']} (whole tree), operator user-name occurrences {totals['user']} (USER_SCOPE only), volume-serial occurrences {totals['serial']} (whole tree), machine-SID occurrences {totals['sid']} (SID_SCOPE only), cloud-account-SID occurrences {totals['account']} (whole tree). "
        "Identifiers and serials are not written here; `scripts/scrub_public_identifiers.py --check` and `tests/security/test_no_host_identity_in_tree.py` verify the result.",
        "",
        f"Interpreter: Python {sys.version.split()[0]}, zlib {zlib.ZLIB_RUNTIME_VERSION} (gzip bodies are reproducible with this zlib build; "
        "the decompressed content is what the lock certifies).",
        "",
        "| file | host | user | serial | sid | account sid | sha256 before (LF) | sha256 after (LF) |",
        "|---|---|---|---|---|---|---|---|",
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
