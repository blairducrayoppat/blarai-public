"""The one place that knows how to recognise this machine's host name, the operator's account name and its volume serial numbers in file content.

Used by the gate lock (``tests/security/test_no_host_identity_in_tree.py``), the in-place scrub
(``scripts/scrub_public_identifiers.py``), the Hugging Face preflight (``scripts/hf_publish.py``) and the community-export
scrub and verifier. Neither name is written here. Two sources name them and recognition uses both:

  * DIGESTS: sha256 of the lower-cased name, for every host and account this repository has carried. Append, never remove.
    A digest recognises the name on any account and any machine, so a control does not weaken when it runs as another user.
  * The live machine: ``COMPUTERNAME`` / ``platform.node()`` and ``USERNAME`` / ``getpass``. These give the string a REWRITE needs;
    a rewrite must first confirm the live name's digest is pinned, or it would rewrite some other account's name.

How content is read (``views``): the raw bytes; UTF-16 or UTF-32 text decoded when a byte-order mark or the NUL pattern of ASCII text says so (UTF-32 without a mark needs 95% NULs in the three high bytes of each four), else the bytes
with NULs removed (a UTF-16 fragment of an ASCII name inside an ASCII file); each of those with JSON escape sequences (``\\n``,
``\\t``, ``\\"``, ``\\\\``, ``\\/``, ``\\xHH``, ``\\uHHHH``) DECODED to the bytes they stand for, and with numeric HTML entities
(``&#NNN;``, ``&#xHH;``) decoded; and every one of those readings again with ANSI escape sequences (colour codes) replaced by a
separator, percent-decoded, and percent-decoded then ANSI-stripped, so a name after a JSON-escaped or percent-encoded colour code
is seen. gzip members are decompressed and read the same way, recursively. A token is a
run of ASCII letters and digits in any view, lower-cased. The host name is recognised as a whole token and as a substring of a
longer token (glue such as ``<host>x`` or ``<host>1``), because at its length a false match is not plausible. The account name is
recognised as a whole token and as a token that is the name with digits before or after it; at four or five letters a letter-glue
rule would fire on ordinary words.

VOLUME SERIALS (``find_serial_hits``): a stable machine identifier printed by ``dir``, ``vol`` and ``fsutil``. Two rules, both read in
every view above. (1) LIVE: the serial of every local fixed volume, read at run time (``live_volume_serials``, GetVolumeInformationW),
is recognised as ``XXXX-XXXX`` (either hex case), ``XXXXXXXX`` and decimal, by the sha256 of its canonical eight-digit form computed
from that live read; no serial is written in the repository, and a digest of a 32-bit value is reversible in seconds, so none is pinned
either. The lock fails, never skips, when no fixed volume serial can be read. (2) HEADER: the text ``Volume Serial Number is`` followed
by a serial (``XXXX-XXXX`` or eight hex digits, 0x prefix allowed), or the fsutil form ``Volume Serial Number :`` plus a serial, in a tracked file, from any machine; the placeholder ``XXXX-XXXX`` is not a serial.
HONEST LIMIT of the serial rules: rule 1 knows only the volumes mounted when it runs (a removable, network or unmounted volume, or the
serial of another machine, is not known, and only rule 2 covers a serial from elsewhere); rule 2 reads the English header, so a
serial under a localised or reworded label (``Numero de serie``, ``Serial:``) or printed bare is seen only when it is a live serial;
the forms are matched as whole tokens (an optional 0x prefix and leading zeros of a decimal included), so a serial glued to
letters is not seen; not seen either: a signed 32-bit decimal (a serial of 2**31 or more printed negative), an unpadded hex or dashed
form of a serial below 0x10000000 (leading zeros dropped), a header label with other words between ``Number`` and the serial. A
decimal below 2**32 anywhere that equals a live serial is a finding (a collision costs one false report, never a silent pass); the same encodings the name rules do not see
(base64, split, other scripts) are not seen here either.

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

import bz2
import ctypes
import getpass
import gzip
import hashlib
import io
import lzma
import os
import platform
import re
import tarfile
import zipfile
import zlib
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
# What reading a gzip member can raise: a bad header, CRC or trailing bytes (OSError), truncation (EOFError), a damaged deflate body (zlib.error).
READ_ERRORS = (OSError, EOFError, zlib.error)
GZIP_MAX_DEPTH = 4

SERIAL_PLACEHOLDER = b"XXXX-XXXX"
# A serial as the rules read it: dashed (either hex case), eight hex digits, and a decimal; each a whole token.
# An optional 0x / 0X prefix (what fsutil and hex() print) is part of the token; leading zeros of a decimal are too.
_SERIAL_DASHED_RE = re.compile(rb"(?<![0-9A-Za-z])(?:0[xX])?([0-9A-Fa-f]{4})-([0-9A-Fa-f]{4})(?![0-9A-Za-z])")
_SERIAL_HEX8_RE = re.compile(rb"(?<![0-9A-Za-z])(?:0[xX])?([0-9A-Fa-f]{8})(?![0-9A-Za-z])")
_SERIAL_DEC_RE = re.compile(rb"(?<![0-9A-Za-z])0*[0-9]{1,10}(?![0-9A-Za-z])")
# The header ``dir`` / ``vol`` print; the serial part is group 1. The placeholder is not hex, so it never matches.
# Whitespace is any ASCII whitespace (a line break included) or a UTF-8 non-breaking space; the label is ``Volume Serial Number``
# followed by ``is`` (dir, vol) or a colon (fsutil), then the serial with an optional 0x prefix.
_WS = rb"(?:\s|\xc2\xa0)"
SERIAL_HEADER_RE = re.compile(
    rb"Volume" + _WS + rb"+Serial" + _WS + rb"+Number(?:" + _WS + rb"+is" + _WS + rb"+|" + _WS + rb"*:" + _WS + rb"*)(?:0[xX])?"
    rb"((?:[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4})|(?:[0-9A-Fa-f]{8}))(?![0-9A-Za-z])", re.IGNORECASE)


# Windows machine / domain account SIDs: ``S-1-5-21-<a>-<b>-<c>`` with an optional relative id. The three sub-authorities
# identify the machine or domain and become ``SID_DOMAIN_PLACEHOLDER``; the relative id is kept (1001, 513 ...: evidence about
# the account's role, not about the machine). Well-known SIDs (S-1-5-32-*, S-1-16-*, S-1-15-2-* AppContainer, S-1-5-18/114)
# are generic and never match this pattern.
SID_DOMAIN_PLACEHOLDER = b"__MACHINE__"
MACHINE_SID_RE = re.compile(rb"(?<![A-Za-z0-9])S-1-5-21-[0-9]+-[0-9]+-[0-9]+(-[0-9]+)?", re.IGNORECASE)

# What the REWRITE reads (raw bytes), against what the lock reads (decoded views): a SID after a JSON escape (\n, \r, \t, \"), a
# percent-escape, a \xHH / \uHHHH escape or an ANSI colour code is a SID at a boundary in the decoded view, so the rewrite accepts
# those boundaries too; its first letter may itself be written \u0053 / \x53 (either case). A shape beyond these (the digits
# escaped, an HTML entity, a doubled encoding) is seen by the lock and not rewritten: a hand edit.
_SID_ANSI_BEFORE = b"|".join(rb"(?<=\x1b\[[0-9;?]{%d}[A-Za-z])" % n for n in range(0, 8))
_SID_BOUNDARY_BEFORE = (rb"(?:(?<![A-Za-z0-9])|(?<=\\[ntrfb\"\\/])|(?<=%[0-9A-Fa-f]{2})|(?<=\\x[0-9A-Fa-f]{2})|(?<=\\u[0-9A-Fa-f]{4})|"
                        + _SID_ANSI_BEFORE + rb")")
SID_REWRITE_RE = re.compile(_SID_BOUNDARY_BEFORE + rb"(?:S|\\u00[57]3|\\x[57]3)-1-5-21-[0-9]+-[0-9]+-[0-9]+(-[0-9]+)?", re.IGNORECASE)


def rewrite_machine_sids(data: bytes) -> tuple[bytes, int]:
    """Every machine/domain account SID in ``data`` with its sub-authorities replaced; the relative id stays."""
    return SID_REWRITE_RE.subn(lambda m: b"S-1-5-21-" + SID_DOMAIN_PLACEHOLDER + (m.group(1) or b""), data)


# Microsoft-account and Microsoft Entra ID (Azure AD) account SIDs: ``S-1-11-96-<...>`` and ``S-1-12-1-<...>``. Every
# sub-authority after the identifier authority (11 or 12) names one person's cloud account (there is no relative id to keep), so
# ``S-1-11-__ACCOUNT__`` / ``S-1-12-__ACCOUNT__`` replace the whole SID: the authority says which kind of account, and no
# sub-authority, not even the fixed first one, stays, so the placeholder never reads as the shape. No well-known SID lives under
# either prefix.
# The rewrite reads the same boundaries and first-letter escapes as ``SID_REWRITE_RE``; any other shape is seen by the lock and
# left for a hand edit.
ACCOUNT_SID_PLACEHOLDER = b"__ACCOUNT__"
ACCOUNT_SID_RE = re.compile(rb"(?<![A-Za-z0-9])S-1-(?:11-96|12-1)(?:-[0-9]+)+", re.IGNORECASE)
ACCOUNT_SID_REWRITE_RE = re.compile(_SID_BOUNDARY_BEFORE + rb"(?:S|\\u00[57]3|\\x[57]3)-1-(?:(11)-96|(12)-1)(?:-[0-9]+)+", re.IGNORECASE)


def rewrite_account_sids(data: bytes) -> tuple[bytes, int]:
    """Every Microsoft-account and Entra ID account SID in ``data`` with everything after its identifier authority replaced."""
    return ACCOUNT_SID_REWRITE_RE.subn(lambda m: b"S-1-" + (m.group(1) or m.group(2)) + b"-" + ACCOUNT_SID_PLACEHOLDER, data)


def sid_rewrite_would_change(data: bytes, _depth: int = 0) -> bool:
    """True when the scrub's rewrite (``scrub_public_identifiers.scrub_bytes`` with the SID rule on) would change ``data``. It
    follows the same container dispatch: a gzip member is decompressed, UTF-16 text is decoded (BOM or alternating NULs), and
    ``SID_REWRITE_RE`` is applied to the plain, decompressed or decoded bytes. Content the rewrite cannot read (damage, undecodable
    text, a gzip nested deeper than ``GZIP_MAX_DEPTH``) is not a SID finding and returns False here: ``unreadable_reason`` names it, and every check path reports it as unreadable."""
    return _rewrite_would_change(data, SID_REWRITE_RE, _depth)


def account_sid_rewrite_would_change(data: bytes, _depth: int = 0) -> bool:
    """``sid_rewrite_would_change`` for the account-SID rewrite (``ACCOUNT_SID_REWRITE_RE``): same container dispatch, same
    treatment of content it cannot read."""
    return _rewrite_would_change(data, ACCOUNT_SID_REWRITE_RE, _depth)


def _rewrite_would_change(data: bytes, pattern: re.Pattern[bytes], _depth: int) -> bool:
    if data.startswith(GZIP_MAGIC):
        try:
            inner = gzip.decompress(data)
        except READ_ERRORS:
            return False
        return _depth < GZIP_MAX_DEPTH and _rewrite_would_change(inner, pattern, _depth + 1)
    enc = looks_utf16(data)
    if enc:
        try:
            data = split_bom(data, enc)[1].decode(enc).encode("utf-8")
        except UnicodeError:
            return False
    return pattern.search(data) is not None


def utf16_problem(data: bytes) -> str | None:
    """Why ``data``, read as UTF-16 text (a BOM, or alternating NULs, as ``looks_utf16`` says), cannot be decoded; None for data that is
    not UTF-16 text or that decodes. An odd-length NUL-heavy binary and a lone surrogate both land here."""
    enc = looks_utf16(data)
    if not enc:
        return None
    try:
        split_bom(data, enc)[1].decode(enc)
    except UnicodeError:
        return "unreadable: wide-character (UTF-16 or UTF-32) text that does not decode (an odd length or a lone surrogate); its content is not checked"
    return None


def unreadable_reason(data: bytes, _depth: int = 0) -> str | None:
    """Why the rewrite cannot read ``data``, or None. The same dispatch as ``scrub_bytes``: a gzip member that does not decompress
    (trailing bytes, truncation, a damaged deflate body) or nests deeper than ``GZIP_MAX_DEPTH``, and UTF-16 text that does not
    decode. Every path that reads or rewrites a file reports this as a finding with this reason; none raises on it."""
    if data.startswith(GZIP_MAGIC):
        try:
            inner = gzip.decompress(data)
        except READ_ERRORS:
            return "unreadable: gzip member that cannot be read (trailing bytes or damage); its content is not checked"
        if _depth >= GZIP_MAX_DEPTH:
            return "unreadable (nesting depth): gzip nested deeper than four; its content is not checked"
        return unreadable_reason(inner, _depth + 1)
    return utf16_problem(data)


def find_sid_hits(data: bytes) -> bool:
    """True when any view of the bytes (JSON escapes, percent, UTF-16, gzip) carries a machine/domain account SID, or when the
    rewrite would change the bytes in any container it reads (``sid_rewrite_would_change``): the lock is never narrower than the
    rewrite, so ``--check`` cannot certify a file the rewrite still has work on."""
    return sid_rewrite_would_change(data) or any(MACHINE_SID_RE.search(v) for v in views(data))


def find_account_sid_hits(data: bytes) -> bool:
    """True when any view of the bytes carries a Microsoft-account (``S-1-11-96-*``) or Entra ID (``S-1-12-1-*``) account SID,
    or when the account-SID rewrite would change the bytes in any container it reads: never narrower than the rewrite."""
    return account_sid_rewrite_would_change(data) or any(ACCOUNT_SID_RE.search(v) for v in views(data))


# Containers the account-SID rule opens wherever it applies (every tracked file): gzip, bzip2, xz, zip and tar, nested to
# ACCOUNT_CONTAINER_MAX_DEPTH, each member decompressed under ACCOUNT_CONTAINER_MAX_BYTES. Anything it cannot read (damage,
# truncation, trailing bytes, an encrypted or oversized member, deeper nesting, another archive format) is a finding, never a pass.
ACCOUNT_CONTAINER_MAX_DEPTH = 16
ACCOUNT_CONTAINER_MAX_BYTES = 256 * 1024 * 1024
ACCOUNT_SID_PRESENT = "Microsoft-account or Entra ID account SID present (S-1-11-96-... / S-1-12-1-...)"
_OTHER_ARCHIVE_MAGICS = ((b"7z\xbc\xaf\x27\x1c", "7z"), (b"Rar!", "rar"), (b"\x28\xb5\x2f\xfd", "zstd"), (b"MSCF", "cab"))
_CONTAINER_SUFFIXES = {".gz": "gzip", ".tgz": "gzip", ".bz2": "bzip2", ".xz": "xz", ".zip": "zip", ".jar": "zip", ".whl": "zip",
                       ".tar": "tar", ".7z": "7z", ".rar": "rar", ".zst": "zstd", ".cab": "cab"}


class _Unreadable(Exception):
    pass


def _container_kind(data: bytes, name: str) -> str | None:
    if data.startswith(GZIP_MAGIC):
        return "gzip"
    if data.startswith(b"BZh"):
        return "bzip2"
    if data.startswith(b"\xfd7zXZ\x00"):
        return "xz"
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return "zip"
    if data[257:262] == b"ustar":
        return "tar"
    for magic, kind in _OTHER_ARCHIVE_MAGICS:
        if data.startswith(magic):
            return kind
    return _CONTAINER_SUFFIXES.get(Path(name).suffix.lower())


def _decompress_all(data: bytes, kind: str) -> bytes:
    """Every member of a gzip / bzip2 / xz stream, bounded; damage, truncation or trailing bytes raise ``_Unreadable``."""
    out = bytearray()
    rest = data
    while rest:
        d = zlib.decompressobj(31) if kind == "gzip" else bz2.BZ2Decompressor() if kind == "bzip2" else lzma.LZMADecompressor()
        try:
            out += d.decompress(rest, ACCOUNT_CONTAINER_MAX_BYTES + 1 - len(out))
        except (OSError, EOFError, ValueError, zlib.error, lzma.LZMAError) as e:
            raise _Unreadable(f"{kind} stream that cannot be read ({type(e).__name__})") from e
        if len(out) > ACCOUNT_CONTAINER_MAX_BYTES:
            raise _Unreadable(f"{kind} stream over the size this lock reads")
        if not d.eof:
            raise _Unreadable(f"{kind} stream that is truncated")
        rest = d.unused_data
        if kind == "gzip" and not rest.strip(b"\x00"):
            break  # zero padding after the last gzip member, as gzip.decompress accepts it
    return bytes(out)


def account_sid_container_problems(data: bytes, name: str = "", _depth: int = 0) -> list[str]:
    """Why ``data`` cannot be certified free of a Microsoft-account or Entra ID account SID: ``ACCOUNT_SID_PRESENT`` for content
    (``find_account_sid_hits``), prefixed ``<kind> member #n:`` inside a container, a member NAME carrying one, and every
    container it cannot read. Empty means clean. Never raises on content."""
    kind = _container_kind(data, name)
    if kind is None:
        problem = utf16_problem(data)
        if problem:
            return [problem]
        return [ACCOUNT_SID_PRESENT] if find_account_sid_hits(data) else []
    if _depth >= ACCOUNT_CONTAINER_MAX_DEPTH:
        return [f"unreadable (nesting depth): {kind} nested deeper than {ACCOUNT_CONTAINER_MAX_DEPTH}; its content is not checked"]
    try:
        if kind in ("gzip", "bzip2", "xz"):
            return account_sid_container_problems(_decompress_all(data, kind), "", _depth + 1)
        if kind == "zip":
            return _archive_members_problems(_zip_members(data), "zip", _depth)
        if kind == "tar":
            return _archive_members_problems(_tar_members(data), "tar", _depth)
    except _Unreadable as e:
        return [f"unreadable: {e}; its content is not checked"]
    return [f"unreadable: {kind} archive, a format this lock does not read; unpack, check and repack by hand"]


def _archive_members_problems(members: list[tuple[str, bytes | None]], kind: str, depth: int) -> list[str]:
    out: list[str] = []
    for n, (member_name, body) in enumerate(members):
        label = f"{kind} member #{n}"
        if find_account_sid_hits(member_name.encode("utf-8", "surrogatepass")):
            out.append(f"{label}: NAME carries a Microsoft-account or Entra ID account SID")
        if body is not None:
            out += [f"{label}: {m}" for m in account_sid_container_problems(body, member_name, depth + 1)]
    return out


def _zip_members(data: bytes) -> list[tuple[str, bytes | None]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if sum(i.file_size for i in infos) > ACCOUNT_CONTAINER_MAX_BYTES:
                raise _Unreadable("zip archive over the size this lock reads")
            if any(i.flag_bits & 0x1 for i in infos):
                raise _Unreadable("zip archive with an encrypted member")
            return [(i.filename, None if i.is_dir() else z.read(i)) for i in infos]
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError, EOFError, zlib.error, ValueError) as e:
        raise _Unreadable(f"zip archive that cannot be opened ({type(e).__name__})") from e


def _tar_members(data: bytes) -> list[tuple[str, bytes | None]]:
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as t:
            members = t.getmembers()
            if sum(m.size for m in members) > ACCOUNT_CONTAINER_MAX_BYTES:
                raise _Unreadable("tar archive over the size this lock reads")
            out: list[tuple[str, bytes | None]] = []
            for m in members:
                f = t.extractfile(m) if m.isfile() else None
                out.append((m.name, f.read() if f is not None else None))
            return out
    except (tarfile.TarError, OSError, EOFError, ValueError) as e:
        raise _Unreadable(f"tar archive that cannot be opened ({type(e).__name__})") from e


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


# Byte-order marks by the encoding name ``looks_utf16`` returns. The UTF-32 marks come first: a UTF-32-LE mark starts with the UTF-16-LE one.
BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe\x00\x00", "utf-32-le"), (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"),
)


def looks_utf16(data: bytes) -> str | None:
    """The wide-character encoding (UTF-16 or UTF-32, either byte order) the bytes say, by a byte-order mark or, without one, by the
    NUL pattern of ASCII text; None for anything else. UTF-32 is tried before UTF-16 because ASCII in UTF-32 is also 75% NUL bytes.
    Every reader and the rewrite use this one detection, so the lock and the rewrite cannot disagree about which text is wide."""
    for mark, enc in BOMS:
        if data.startswith(mark):
            return enc
    sample = data[:4096]
    sample = sample[:len(sample) // 4 * 4]
    if len(sample) >= 16:
        le = sum(sample[i::4].count(0) for i in (1, 2, 3))
        be = sum(sample[i::4].count(0) for i in (0, 1, 2))
        need = len(sample) // 4 * 3 * 95 // 100
        if le >= need and le >= be:
            return "utf-32-le"
        if be >= need:
            return "utf-32-be"
    sample = data[:4096]
    if len(sample) >= 8 and sample.count(b"\0") * 2 >= len(sample) * 0.8:
        return "utf-16-le" if sample[1:2] == b"\0" else "utf-16-be"
    return None


def split_bom(data: bytes, enc: str) -> tuple[bytes, bytes]:
    """(byte-order mark, the rest) for text in ``enc`` as ``looks_utf16`` named it."""
    for mark, name in BOMS:
        if name == enc and data.startswith(mark):
            return mark, data[len(mark):]
    return b"", data


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
        except READ_ERRORS:
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


def live_volume_serials() -> frozenset[int]:
    """The serial number of every local fixed volume (GetVolumeInformationW); empty when none can be read (not Windows, no ctypes
    support, every call failed). An empty result is a failure for the lock, never a pass."""
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        buf = ctypes.create_unicode_buffer(1024)
        n = kernel32.GetLogicalDriveStringsW(len(buf), buf)
        if not 0 < n <= len(buf):
            return frozenset()
        roots = [r for r in buf[:n].split("\0") if r]
        serials: set[int] = set()
        for root in roots:
            if kernel32.GetDriveTypeW(root) != 3:  # DRIVE_FIXED
                continue
            serial = ctypes.c_uint32(0)
            if kernel32.GetVolumeInformationW(root, None, 0, ctypes.byref(serial), None, None, None, 0):
                serials.add(serial.value)
        return frozenset(serials)
    except (AttributeError, OSError, ValueError):
        return frozenset()


def serial_digest(serial: int) -> str:
    return hashlib.sha256(f"{serial:08X}".encode("ascii")).hexdigest()


def serial_digests(serials: frozenset[int] | None = None) -> frozenset[str]:
    """Digests of the live fixed-volume serials (or of the given ones); empty when none are readable."""
    return frozenset(serial_digest(s) for s in (live_volume_serials() if serials is None else serials))


def find_serial_hits(data: bytes, digests: frozenset[str]) -> set[str]:
    """Which serial rules the bytes trip in any view: ``live`` (a live serial in a dashed, bare-hex or decimal form) and
    ``header`` (``Volume Serial Number is`` plus a serial). Never returns the serial itself."""
    found: set[str] = set()
    for view in views(data):
        if "header" not in found and SERIAL_HEADER_RE.search(view):
            found.add("header")
        if "live" in found or not digests:
            continue
        for m in _SERIAL_DASHED_RE.finditer(view):
            if hashlib.sha256((m.group(1) + m.group(2)).upper()).hexdigest() in digests:
                found.add("live")
                break
        else:
            for m in _SERIAL_HEX8_RE.finditer(view):
                if hashlib.sha256(m.group(1).upper()).hexdigest() in digests:
                    found.add("live")
                    break
            else:
                for m in _SERIAL_DEC_RE.finditer(view):
                    value = int(m.group(0))
                    if value < 1 << 32 and serial_digest(value) in digests:
                        found.add("live")
                        break
    return found


def serial_res(serials: frozenset[int]) -> list[re.Pattern[bytes]]:
    """The live serials in the forms the lock reads, as whole-token patterns (dashed and bare hex in either case, decimal)."""
    out: list[re.Pattern[bytes]] = []
    for s in sorted(serials):
        hexs = f"{s:08X}"
        out.append(re.compile(rb"(?<![0-9A-Za-z])(?:0[xX])?" + hexs[:4].encode() + rb"-" + hexs[4:].encode() + rb"(?![0-9A-Za-z])", re.IGNORECASE))
        out.append(re.compile(rb"(?<![0-9A-Za-z])(?:0[xX])?" + hexs.encode() + rb"(?![0-9A-Za-z])", re.IGNORECASE))
        out.append(re.compile(rb"(?<![0-9A-Za-z])0*" + str(s).encode() + rb"(?![0-9A-Za-z])"))
    return out


def rewrite_serials(data: bytes, serials: frozenset[int]) -> tuple[bytes, int]:
    """The header's serial and each given serial (dashed, bare hex, decimal) replaced by ``SERIAL_PLACEHOLDER``; (bytes, count)."""
    data, total = SERIAL_HEADER_RE.subn(lambda m: m.group(0)[:m.start(1) - m.start(0)] + SERIAL_PLACEHOLDER, data)
    for pat in serial_res(serials):
        data, n = pat.subn(SERIAL_PLACEHOLDER, data)
        total += n
    return data, total


def redact_serials(text: str, digests: frozenset[str]) -> str:
    """The text with every serial the lock recognises (a header's, or one of ``digests``) replaced by ``SERIAL_PLACEHOLDER``, so
    a report that names a file can never print one. A serial still recognised afterwards (an encoded form) replaces the whole
    text with a fixed notice. With no digests there is nothing to compare, and only the header's serial is replaced."""
    data = text.encode("utf-8", "surrogatepass")
    data = SERIAL_HEADER_RE.sub(lambda m: m.group(0)[:m.start(1) - m.start(0)] + SERIAL_PLACEHOLDER, data)
    if digests:
        data = _SERIAL_DASHED_RE.sub(
            lambda m: SERIAL_PLACEHOLDER if hashlib.sha256((m.group(1) + m.group(2)).upper()).hexdigest() in digests else m.group(0), data)
        data = _SERIAL_HEX8_RE.sub(
            lambda m: SERIAL_PLACEHOLDER if hashlib.sha256(m.group(1).upper()).hexdigest() in digests else m.group(0), data)
        data = _SERIAL_DEC_RE.sub(
            lambda m: SERIAL_PLACEHOLDER if int(m.group(0)) < 1 << 32 and serial_digest(int(m.group(0))) in digests else m.group(0), data)
        if find_serial_hits(data, digests):
            return "<redacted: a volume serial in an encoded form>"
    return data.decode("utf-8", "surrogatepass")


def digests_with_live(host: str | None, user: str | None) -> tuple[frozenset[str], frozenset[str]]:
    """The pinned digests plus the live machine's, so a renamed box is still recognised."""
    h = HOST_DIGESTS | ({digest(host)} if host else set())
    u = USER_DIGESTS | ({digest(user)} if user else set())
    return frozenset(h), frozenset(u)


def path_in_scope(rel_posix: str, scope: tuple[str, ...]) -> bool:
    """True when a repository-relative POSIX path is one of the scope entries, sits under one that names a directory, or starts
    with one that ends in ``*`` (a name prefix)."""
    for entry in scope:
        if entry.endswith("*") and rel_posix.startswith(entry[:-1]):
            return True
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
