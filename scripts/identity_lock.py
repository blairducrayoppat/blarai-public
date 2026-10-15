"""The one place that knows how to recognise this machine's host name and the operator's account name in file content.

Used by the gate lock (``tests/security/test_no_host_identity_in_tree.py``), the in-place scrub
(``scripts/scrub_public_identifiers.py``), the Hugging Face preflight (``scripts/hf_publish.py``) and the community-export
scrub and verifier. Neither name is written here. Two sources name them and recognition uses both:

  * DIGESTS: sha256 of the lower-cased name, for every host and account this repository has carried. Append, never remove.
    A digest recognises the name on any account and any machine, so a control does not weaken when it runs as another user.
  * The live machine: ``COMPUTERNAME`` / ``platform.node()`` and ``USERNAME`` / ``getpass``. These give the string a REWRITE needs;
    a rewrite must first confirm the live name's digest is pinned, or it would rewrite some other account's name.

How content is read (``views``): the raw bytes; UTF-16 text decoded when a byte-order mark or alternating NULs say so, else the bytes
with NULs removed (a UTF-16 fragment of an ASCII name inside an ASCII file); each of those with JSON escape sequences (``\\n``,
``\\t``, ``\\"``, ``\\\\``, ``\\/``, ``\\xHH``, ``\\uHHHH``) DECODED to the bytes they stand for, and with numeric HTML entities
(``&#NNN;``, ``&#xHH;``) decoded; and every one of those readings again with ANSI escape sequences (colour codes) replaced by a
separator, percent-decoded, and percent-decoded then ANSI-stripped, so a name after a JSON-escaped or percent-encoded colour code
is seen. gzip members are decompressed and read the same way, recursively. A token is a
run of ASCII letters and digits in any view, lower-cased. The host name is recognised as a whole token and as a substring of a
longer token (glue such as ``<host>x`` or ``<host>1``), because at its length a false match is not plausible. The account name is
recognised as a whole token and as a token that is the name with digits before or after it; at four or five letters a letter-glue
rule would fire on ordinary words.

HONEST LIMIT: not seen, by the shape of the bytes around the name: a name split by punctuation, a soft hyphen, a line break or a
zero-width character; another script or fullwidth letters; base64 or hex; a zip or PNG chunk; a compression other than gzip, or gzip
nested deeper than four; a colour code written as text other than ESC (octal ``\\033[``, ``\\e[``) or as the 8-bit CSI byte; two
escaping schemes nested (a JSON escape, UTF-16, an HTML entity or a second percent-encoding inside percent-encoding; an HTML entity
inside a JSON escape); an HTML hex entity without its semicolon; a letter glued to the account name (four or five letters; the host
name is matched inside longer tokens, the account name is not). Seen but not rewritten, so the scrub run and ``--check`` report the
file for a hand edit: a name percent-encoded byte by byte (the rewrite handles a percent-escape BESIDE the name), a member of a
``.tar.gz`` (the rewrite reads the tar as UTF-16 and leaves it), and any shape outside the plain, JSON-separator, ANSI-separator,
beside-the-name percent-escape, UTF-16 and gzip forms. The digests are reversible by exhaustive search at short name lengths (the
account name is in this repository's working paths; the digest exists to lock, not to hide).
"""

from __future__ import annotations

import getpass
import gzip
import hashlib
import os
import platform
import re
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote_to_bytes

# sha256 of the lower-cased host name, for every machine this repository has carried. Append, never remove.
HOST_DIGESTS: frozenset[str] = frozenset({
    "38570cc4589e2a2c89d165c999d2ad2ae0e3ac02f99243f697d6aab7ba0d280e",  # this machine, scrubbed out 2026-10-14 (#1765)
})
HOST_LENGTHS: frozenset[int] = frozenset({12})
# sha256 of the lower-cased operator account name. Append with HOST_DIGESTS.
USER_DIGESTS: frozenset[str] = frozenset({
    "b28270f19973691fdd4ef572ebf2a0127992a29744cde21ee94d1773da0083cf",  # this machine's operator account
})
USER_LENGTHS: frozenset[int] = frozenset({5})
MIN_NAME_LEN = 4

TOKEN_RE = re.compile(rb"[A-Za-z0-9]+")
JSON_ESCAPE_RE = re.compile(rb"\\(?:x([0-9A-Fa-f]{2})|u([0-9A-Fa-f]{4})|([ntrfb\"\\/]))")
HTML_ENTITY_RE = re.compile(rb"&#(?:x([0-9A-Fa-f]{1,6})|([0-9]{1,7}));")
_JSON_SIMPLE = {b"n": b"\n", b"t": b"\t", b"r": b"\r", b"f": b"\f", b"b": b"\b", b'"': b'"', b"\\": b"\\", b"/": b"/"}
ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")
GZIP_MAGIC = b"\x1f\x8b"


def digest(name: str) -> str:
    return hashlib.sha256(name.lower().encode("utf-8")).hexdigest()


def live_names() -> tuple[str | None, str | None]:
    """(host, user) as this machine reports them; None for a value that is missing or shorter than MIN_NAME_LEN."""
    host = os.environ.get("COMPUTERNAME") or platform.node() or ""
    try:
        user = os.environ.get("USERNAME") or getpass.getuser() or ""
    except Exception:  # getpass raises on accounts without a resolvable name
        user = ""
    return (host if len(host) >= MIN_NAME_LEN else None, user if len(user) >= MIN_NAME_LEN else None)


def live_names_are_pinned() -> tuple[bool, bool]:
    """Whether the live host and user names are the pinned ones; a rewrite must not proceed on another account's name."""
    host, user = live_names()
    return (bool(host) and digest(host) in HOST_DIGESTS, bool(user) and digest(user) in USER_DIGESTS)


def looks_utf16(data: bytes) -> str | None:
    if data.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if data.startswith(b"\xfe\xff"):
        return "utf-16-be"
    sample = data[:4096]
    if len(sample) >= 8 and sample.count(b"\0") * 2 >= len(sample) * 0.8:
        return "utf-16-le" if sample[1:2] == b"\0" else "utf-16-be"
    return None


def _codepoint_bytes(cp: int) -> bytes:
    return chr(cp).encode("utf-8") if cp < 0x110000 and not 0xD800 <= cp <= 0xDFFF else b" "


def _json_unescape(m: re.Match[bytes]) -> bytes:
    if m.group(1):
        return bytes([int(m.group(1), 16)])
    if m.group(2):
        return _codepoint_bytes(int(m.group(2), 16))
    return _JSON_SIMPLE[m.group(3)]


def _html_unescape(m: re.Match[bytes]) -> bytes:
    return _codepoint_bytes(int(m.group(1), 16) if m.group(1) else int(m.group(2)))


def _readings(base: bytes) -> Iterator[bytes]:
    """One byte string and its ANSI-stripped, percent-decoded, and percent-decoded-then-ANSI-stripped forms."""
    yield base
    if b"\x1b[" in base:
        yield ANSI_RE.sub(b" ", base)
    if b"%" in base:
        decoded = unquote_to_bytes(base)
        if decoded != base:
            yield decoded
            if b"\x1b[" in decoded:
                yield ANSI_RE.sub(b" ", decoded)


def views(data: bytes, _depth: int = 0) -> Iterator[bytes]:
    """Every reading of the bytes a token scan must cover (see the module docstring); each distinct view once."""
    if data.startswith(GZIP_MAGIC) and _depth < 4:
        try:
            inner = gzip.decompress(data)
        except (OSError, EOFError):
            inner = None
        if inner is not None:
            yield from views(inner, _depth + 1)
            return
    bases = [data]
    enc = looks_utf16(data)
    if enc:
        try:
            bases.append(data.decode(enc, errors="ignore").encode("utf-8"))
        except UnicodeError:
            pass
    elif b"\0" in data:
        bases.append(data.replace(b"\0", b""))
    for base in list(bases):
        if b"\\" in base:
            unescaped = JSON_ESCAPE_RE.sub(_json_unescape, base)
            if unescaped != base:
                bases.append(unescaped)
        if b"&#" in base:
            entities = HTML_ENTITY_RE.sub(_html_unescape, base)
            if entities != base:
                bases.append(entities)
    seen: set[bytes] = set()
    for base in bases:
        for view in _readings(base):
            if view not in seen:
                seen.add(view)
                yield view


def _host_token_hits(token: bytes, host_digests: frozenset[str]) -> bool:
    if hashlib.sha256(token).hexdigest() in host_digests:
        return True
    for length in HOST_LENGTHS:
        if len(token) > length:
            for i in range(len(token) - length + 1):
                if hashlib.sha256(token[i:i + length]).hexdigest() in host_digests:
                    return True
    return False


def _user_token_hits(token: bytes, user_digests: frozenset[str]) -> bool:
    if hashlib.sha256(token).hexdigest() in user_digests:
        return True
    stem = token.strip(b"0123456789")
    return stem != token and len(stem) >= MIN_NAME_LEN and hashlib.sha256(stem).hexdigest() in user_digests


def find_hits(data: bytes, host_digests: frozenset[str] = HOST_DIGESTS, user_digests: frozenset[str] = USER_DIGESTS) -> tuple[set[bytes], set[bytes]]:
    """(host tokens, user tokens) found in any view of the bytes, lower-cased. Empty sets mean clean."""
    host_hits: set[bytes] = set()
    user_hits: set[bytes] = set()
    for view in views(data):
        seen: set[bytes] = set()
        for m in TOKEN_RE.finditer(view):
            tok = m.group(0).lower()
            if len(tok) < MIN_NAME_LEN or tok in seen:
                continue
            seen.add(tok)
            if _host_token_hits(tok, host_digests):
                host_hits.add(tok)
            if _user_token_hits(tok, user_digests):
                user_hits.add(tok)
    return host_hits, user_hits


def count_user_hits(data: bytes, user_digests: frozenset[str] = USER_DIGESTS) -> int:
    """How many tokens carry the account name (the ratchet's per-file measure).

    Counted in every view the lock reads and the largest per-view count returned, so the ratchet and the lock see the same
    bytes: a name that reaches the file only escaped, percent-encoded, as UTF-16 or inside a gzip member counts as it would
    in plain text. The views overlap (the raw view and the unescaped view carry the same plain-text occurrences), so the
    counts are not summed.
    """
    best = 0
    for view in views(data):
        n = 0
        for m in TOKEN_RE.finditer(view):
            tok = m.group(0).lower()
            if len(tok) >= MIN_NAME_LEN and _user_token_hits(tok, user_digests):
                n += 1
        best = max(best, n)
    return best


def digests_with_live(host: str | None, user: str | None) -> tuple[frozenset[str], frozenset[str]]:
    """The pinned digests plus the live machine's, so a renamed box is still recognised."""
    h = HOST_DIGESTS | ({digest(host)} if host else set())
    u = USER_DIGESTS | ({digest(user)} if user else set())
    return frozenset(h), frozenset(u)


def path_in_scope(rel_posix: str, scope: tuple[str, ...]) -> bool:
    """True when a repository-relative POSIX path is one of the scope entries or sits under one that names a directory."""
    for entry in scope:
        if rel_posix == entry or rel_posix.startswith(entry.rstrip("/") + "/"):
            return True
    return False


def name_in_path(rel_posix: str, host_digests: frozenset[str], user_digests: frozenset[str]) -> bool:
    """A tracked file whose NAME carries an identifier; a scrub cannot fix this, a person renames it."""
    h, u = find_hits(rel_posix.encode("utf-8"), host_digests, user_digests)
    return bool(h or u)


def read_tracked(root: Path) -> list[Path]:
    import subprocess

    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    return [root / p.decode("utf-8") for p in out.split(b"\0") if p]
