"""Recognition and ratchet for tracker numbers in research files (stdlib only; shares the reading approach of ``identity_lock``).

A research file is one whose content is published as a measurement record. It carries no tracker reference, no fixture name that
embeds one and no session token, and no file or folder NAME embeds a four-digit one (a three-digit number in a name is not seen;
see REMAINING LIMITS). Patterns (each read in every ``identity_lock.views`` reading
of the bytes: raw, JSON escapes undone, HTML numeric entities undone, UTF-16, gzip, percent- and ANSI-decoded):

  tracker-ref      ``#`` plus three to five digits not followed by another digit and not preceded by ``#`` or ``&``. A number
                   glued to a word is a finding too; the only glue that passes is an allowlisted ``owner/repo`` slug.
  fixture-prefix   ``p`` or ``P`` plus four or five digits plus ``-`` or ``_``, not preceded by a letter or digit.
  session-token    ``S`` plus four or five digits plus ``-``, not preceded by a letter or digit.
  name-number      a path segment inside the scope carrying a standalone four-digit number that is not the year of a date.
  malformed-opt-in a file with a KEY-SHAPED line that did not parse as opted in (see SCOPE): a typo in an opt-in fails closed
                   instead of leaving the author believing the file is locked. Prose and inline-code mentions are not key-shaped.

UPSTREAM EXEMPTION: a ``#N`` directly preceded by an allowlisted upstream repository slug, then optional spaces and an optional
``PR`` or ``issue`` word, is an upstream reference and passes. A bare ``#N`` is a finding even when it is an upstream number: the
record must name the repository. A slug outside ``UPSTREAM_SLUGS`` is a finding.

DATE RULE (name-number): a standalone four-digit run is the year of a date, and not a finding, only when it is 1900 to 2099 and
followed by a separator (``-``, ``_`` or ``.``) and a month 01 to 12 not followed by another digit (YYYY-MM-DD, YYYY_MM, YYYY.MM.DD),
the same rule as the evidence repository's gate. A YYYYMMDD run is eight digits and never a standalone four-digit run. Every other
four-digit run is a finding: a plain year (``2026``) and a month-day stamp (``1015``) included; a version form passes only under
the VERSION RULE below.
REMAINING LIMITS (recorded 2026-10-15): a tracker number from 1900 to 2099 written directly before a separator and a valid month
reads as a date and is not seen; a run of five or more digits in a name is not a standalone four-digit run and is not seen; a
number glued to letters (``pr1786``) is seen, a number inside a longer digit run is not. Directories above a scope root and
top-level probe files are outside the scope the operator fixed. A three-digit tracker number in a name is not seen (recorded
2026-10-15; nine banked performance names carry one, and hardware forms such as ``arc140v`` would be false positives for a
three-digit rule). A misspelt key, a plural key outside a front matter and a TOML (``+++``) front matter are neither
opted in nor key-shaped and leave the file silently unscoped (recorded 2026-10-15). Ordinary text that opens a line with the key
words and a colon (``Research scope: ...``), a front-matter title naming them and an indented code block are key-shaped and fail
closed as a malformed opt-in. A file whose text is UTF-16, or whose suffix is not in the list below (``.mdx``), is not read for the opt-in
and is silently unscoped (recorded 2026-10-15; write the document as UTF-8 ``.md``).
VERSION RULE (name-number): a run from 2000 to 2099 directly followed by a dot and a digit (``2026.4``), or directly after ``ov`` or
``openvino`` (any case) and followed by an underscore and a digit (``ov2026_2_1_0``, the shape ``benchmark_kv_cache_sweep``,
``benchmark_prefill``, ``benchmark_prefix_caching_ab``, ``benchmark_spec_decode_ab`` and ``vlm_perf`` write), is a software version
and passes. Nothing looser in SHAPE: ``ov1406_2``, ``run_2026`` and ``2026_2`` are findings. NOT narrow in RANGE (recorded
2026-10-15): a tracker number from 2000 to 2099 written as a version (``NNNN.<digit>``, ``ov<NNNN>_<digit>``) reads as a version
and is not seen.

KNOWN FAIL-CLOSED FALSE POSITIVES: a CSS colour (hash and three digits) and an ordinal (hash and three digits) match tracker-ref; a probe that writes
HTML or numbered lists writes them another way (``rgb(...)``, ``No. 100``). A short commit hash or an hour-minute stamp that
contains a four-digit run in a name is refused (three banked names carry a hash and are baselined). A refused commit, never a
silent pass.

SCOPE, by path in the git INDEX (never the working copy, so an unstaged edit cannot hide a finding):
  * every file under ``tools/probes/<name>/`` (a probe directory)                                           [baselined]
  * ``docs/performance/*.json`` (that directory's top level only)                                           [baselined]
  * ``PERFORMANCE_LOG.md`` entries: from a marker line (``<!-- research-scope: tracker-free -->``; case, indent, trailing space,
    CRLF and ``-``, ``_``, a space or nothing between the two words tolerated) through the entry's own heading (the first heading
    of any level 1-6 outside a fenced code block after the marker) up to, not including, the next heading outside a fenced code
    block whose level is less than or equal to the own heading's level (deeper sub-headings stay inside the entry), or the end of
    the file; a second marker before the own heading ends the first entry. A fence closes on the opening
    character with at least the opening length. Any other key-shaped line outside a fenced block is malformed. [never baselined]
  * ``docs/research/PREFLIGHT_RESEARCH_COMMIT.md``                                                        [never baselined]
  * any tracked ``.md``, ``.markdown``, ``.txt`` or ``.rst`` file whose leading front matter (optional byte-order mark, optional
    blank lines, then ``---`` ... ``---`` or ``...``) carries a ``research-scope: tracker-free`` line (key case, indent, quotes,
    trailing space, a trailing ``#`` comment and ``-``, ``_``, a space or nothing between the two words tolerated), journal
    fragments included                                                                                [never baselined]
KEY-SHAPED: outside a fenced code block a line that starts, after indentation, with the key word and a colon or with ``<!--`` and
the key word, and any line naming the key word inside a leading front matter block. A tracked file of those suffixes with such a
line that did not parse as opted in is a malformed-opt-in finding and is never baselined. A sentence that merely mentions the key
is not key-shaped.

RATCHET (``scripts/research_tracker_baseline.json``, counts and paths only, read from the INDEX): a baselined file may carry at most
its listed count per pattern and its name finding only when listed; a file in scope and not listed carries zero; a listed count
above the file's fails until lowered in the same change; a listed file that is gone or out of scope fails. ``--write-baseline`` only
creates the file (no baseline at ``--base-ref`` yet) or lowers the one there, and baselines only files tracked at ``--base-ref``;
``--add-existing-names`` additionally lets it list name findings of files already tracked at the base ref (a rule that newly catches
banked names); it needs ``--base-ref`` to be main's tip or the merge base with main. ``--reference-ref REF``
refuses a baseline that grew: on a branch against the version at ``git merge-base HEAD REF``; on the main line against the
pointwise minimum of the last WINDOW (20) baseline versions on the first-parent line (see ``reference_baseline``); a name entry the
reference lacks passes when the path was tracked at the reference commit. A shallow clone, an unresolved ref and an index with no
probe, performance or checklist file exit 2. LANDING: a branch that touches the baseline or this script lands with
``git merge --no-ff``; a fast-forward puts every intermediate baseline version on the first-parent line, the minimum falls to
the lowest of them and main's own baseline reads as a rise. A ref that does
not resolve exits 2 naming it, and only a baseline absent from the reference history counts as new. Output names the pattern, never the matched text; paths print with every run of four or more digits
that is not a date masked.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import identity_lock as il  # noqa: E402

BASELINE_PATH = "scripts/research_tracker_baseline.json"
PERF_LOG = "PERFORMANCE_LOG.md"
PREFLIGHT = "docs/research/PREFLIGHT_RESEARCH_COMMIT.md"
FRONT_MATTER_SUFFIXES = (".md", ".markdown", ".txt", ".rst")
UPSTREAM_SLUGS = (
    "microsoft/mxc",
    "anthropics/sandbox-runtime",
    "nolabs-ai/nono",
    "openvinotoolkit/openvino",
    "openvinotoolkit/openvino.genai",
    "huggingface/optimum-intel",
)
CONTENT_PATTERNS = ("tracker-ref", "fixture-prefix", "session-token")
NAME_PATTERN = "name-number"
MALFORMED_PATTERN = "malformed-opt-in"
ALL_PATTERNS = CONTENT_PATTERNS + (NAME_PATTERN, MALFORMED_PATTERN)

_PATTERN_RES = {
    "tracker-ref": re.compile(rb"(?<![#&])#[0-9]{3,5}(?![0-9])"),
    "fixture-prefix": re.compile(rb"(?<![A-Za-z0-9])p[0-9]{4,5}[-_]", re.IGNORECASE),
    "session-token": re.compile(rb"(?<![A-Za-z0-9])S[0-9]{4,5}-"),
}
_SLUG_ALT = "|".join(re.escape(s) for s in sorted(UPSTREAM_SLUGS, key=len, reverse=True))
_UPSTREAM_TAIL_RE = re.compile(
    rb"(?<![\w./-])(?:" + _SLUG_ALT.encode() + rb")(?:[ \t]+(?:PR|issue)[ \t]+|[ \t]*)$", re.IGNORECASE)
_NUM4_RE = re.compile(r"(?<![0-9])[0-9]{4}(?![0-9])")
_LONG_RUN_RE = re.compile(r"[0-9]{4,}")
_MONTH_TAIL_RE = re.compile(r"[-_.](?:0[1-9]|1[0-2])(?![0-9])")
_COMPACT_DATE_RE = re.compile(r"(?:19|20)[0-9]{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])")
_WORDS = rb"research[-_ ]?scope"
_FRONT_KEY_RE = re.compile(
    rb"^[ \t]*" + _WORDS + rb"[ \t]*:[ \t]*[\"']?tracker-free[\"']?[ \t]*(?:#.*)?\r?$", re.IGNORECASE)
_HEADING_RE = re.compile(rb"^ {0,3}(#{1,6})(?:[ \t]|\r?$)")
_MARKER_RE = re.compile(rb"^[ \t]*<!--[ \t]*" + _WORDS + rb"[ \t]*:[ \t]*tracker-free[ \t]*-->[ \t]*\r?$", re.IGNORECASE)
_KEY_SHAPED_RE = re.compile(rb"^[ \t]*(?:" + _WORDS + rb"[ \t]*:|<!--[ \t]*" + _WORDS + rb")", re.IGNORECASE)
_SCOPE_WORD_RE = re.compile(_WORDS, re.IGNORECASE)
_FENCE_OPEN_RE = re.compile(rb"^ {0,3}(`{3,}|~{3,})(.*)$")
# A software version, not a tracker number: 2000 to 2099 directly followed by a dot and a digit (2026.4), or directly after
# ov or openvino (any letter case) and followed by an underscore and a digit (ov2026_2_1_0, the shape the benchmark harnesses
# write). Nothing looser: ov1406_2, run_2026 and 2026_2 stay findings.
_VERSION_AFTER_RE = re.compile(r"20[0-9]{2}\.[0-9]")
_VERSION_OV_RE = re.compile(r"(?<![A-Za-z])(?:ov|openvino)20[0-9]{2}_[0-9]", re.IGNORECASE)
WINDOW = 20  # baseline versions on the first-parent line the reference reads when HEAD is on the main line


class LockError(RuntimeError):
    """The lock cannot see its subject (git missing or failing, a reference that does not resolve); never a skip."""


@dataclass
class FileResult:
    path: str
    kind: str  # "probe" | "perf" | "preflight" | "marked-file" | "log-entries" | "malformed"
    counts: dict[str, int] = field(default_factory=dict)
    lines: dict[str, list[int]] = field(default_factory=dict)

    @property
    def baselinable(self) -> bool:
        return self.kind in ("probe", "perf")


# ---- git ------------------------------------------------------------------------------------------------------------------------

def _git(root: Path, args: list[str], stdin: bytes | None = None) -> bytes:
    try:
        r = subprocess.run(["git", *args], cwd=root, input=stdin, capture_output=True)
    except (OSError, ValueError) as exc:
        raise LockError(f"git cannot be run: {exc}") from exc
    if r.returncode != 0:
        raise LockError(f"git {args[0]} failed: {r.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return r.stdout


def index_entries(root: Path) -> dict[str, str]:
    """Path -> blob sha for every regular entry in the index (submodules skipped)."""
    out = _git(root, ["ls-files", "-s", "-z"])
    entries: dict[str, str] = {}
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        mode, sha, _stage = meta.decode().split()
        if mode != "160000":
            entries[path.decode("utf-8")] = sha
    return entries


def read_blobs(root: Path, shas: list[str]) -> dict[str, bytes]:
    """Blob bytes by sha, one ``git cat-file --batch`` call."""
    uniq = sorted(set(shas))
    if not uniq:
        return {}
    raw = _git(root, ["cat-file", "--batch"], ("\n".join(uniq) + "\n").encode())
    blobs: dict[str, bytes] = {}
    pos = 0
    while pos < len(raw):
        eol = raw.index(b"\n", pos)
        head = raw[pos:eol].split()
        if len(head) != 3:
            raise LockError("git cat-file returned an unreadable record")
        size = int(head[2])
        blobs[head[0].decode()] = raw[eol + 1:eol + 1 + size]
        pos = eol + 1 + size + 1
    if any(s not in blobs for s in uniq):
        raise LockError("git cat-file did not return every blob")
    return blobs


def tracked_at(root: Path, ref: str) -> set[str]:
    out = _git(root, ["ls-tree", "-r", "--name-only", "-z", ref])
    return {p.decode("utf-8") for p in out.split(b"\0") if p}


def _git_rc(root: Path, args: list[str]) -> tuple[int, bytes]:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True)
    except (OSError, ValueError) as exc:
        raise LockError(f"git cannot be run: {exc}") from exc
    return r.returncode, r.stdout


def resolve_ref(root: Path, ref: str) -> str:
    """The commit a ref names; raises LockError naming the ref when it does not resolve."""
    rc, out = _git_rc(root, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
    if rc != 0 or not out.strip():
        raise LockError(f"the reference '{ref}' does not resolve to a commit in this checkout (fetch it before running the gate)")
    return out.decode().strip()


def reference_baseline(root: Path, ref: str) -> dict | None:
    """The baseline this checkout must not exceed, or None when none exists yet (the baseline is new in this history).

    HEAD not on the history of ``ref`` (a branch): the version at ``git merge-base HEAD ref``, so a main that lowered the
    baseline since the fork does not fail a branch that never touched it. HEAD on the history of ``ref`` (main itself, or a
    commit on it): the pointwise MINIMUM over the last WINDOW versions of the baseline on the first-parent line of HEAD, a file
    or name counting only if every version lists it, so a growth that merged without a gate run stays visible until WINDOW
    later baseline changes. HONEST LIMIT: a growth older than WINDOW versions is not seen."""
    resolve_ref(root, ref)
    rc0, shallow = _git_rc(root, ["rev-parse", "--is-shallow-repository"])
    if rc0 != 0 or shallow.strip() != b"false":
        raise LockError("this is a shallow clone (or its depth cannot be read): the baseline history the reference reads is "
                        "truncated; run `git fetch --unshallow`")
    rc, _ = _git_rc(root, ["merge-base", "--is-ancestor", "HEAD", ref])
    if rc not in (0, 1):
        raise LockError(f"cannot relate HEAD to '{ref}' (shallow clone?)")
    if rc == 1:
        rc2, base = _git_rc(root, ["merge-base", "HEAD", ref])
        if rc2 != 0 or not base.strip():
            raise LockError(f"HEAD and '{ref}' share no history; the comparison cannot run")
        sha = base.decode().strip()
        at_ref = tracked_at(root, sha)
        if BASELINE_PATH not in at_ref:
            return None
        found = load_baseline_text(_git(root, ["show", f"{sha}:{BASELINE_PATH}"]).decode("utf-8"))
        found["tracked"] = at_ref
        return found
    shas = _git(root, ["log", "--first-parent", "--format=%H", "-n", str(WINDOW), "HEAD", "--", BASELINE_PATH]).decode().split()
    versions: list[dict] = []
    for sha in shas:
        rc3, out = _git_rc(root, ["show", f"{sha}:{BASELINE_PATH}"])
        if rc3 != 0:
            continue  # the commit deleted the file: no version to read
        versions.append(load_baseline_text(out.decode("utf-8")))
    if not versions:
        return None
    paths = set(versions[0]["counts"]).intersection(*(set(v["counts"]) for v in versions[1:]))
    counts: dict[str, dict[str, int]] = {}
    for path in paths:
        pats = set(versions[0]["counts"][path]).intersection(*(set(v["counts"][path]) for v in versions[1:]))
        counts[path] = {p: min(v["counts"][path][p] for v in versions) for p in pats}
    names = set(versions[0]["names"]).intersection(*(set(v["names"]) for v in versions[1:]))
    return {"counts": counts, "names": sorted(names), "tracked": tracked_at(root, shas[-1])}


# ---- scope ----------------------------------------------------------------------------------------------------------------------

def path_kind(path: str) -> str | None:
    seg = path.split("/")
    if len(seg) >= 4 and seg[0] == "tools" and seg[1] == "probes":
        return "probe"
    if len(seg) == 3 and seg[0] == "docs" and seg[1] == "performance" and seg[2].lower().endswith(".json"):
        return "perf"
    if path == PREFLIGHT:
        return "preflight"
    return None


def fence_flags(lines: list[bytes]) -> list[bool]:
    """Per line: True when the line is a fence line or inside a fenced code block (CommonMark: the closing fence uses the
    opening character, is at least as long and carries nothing but spaces after it)."""
    flags: list[bool] = []
    fence: tuple[bytes, int] | None = None
    for line in lines:
        text = line.rstrip(b"\r")
        if fence is None:
            m = _FENCE_OPEN_RE.match(text)
            if m and not (m.group(1)[:1] == b"`" and b"`" in m.group(2)):
                fence = (m.group(1)[:1], len(m.group(1)))
                flags.append(True)
            else:
                flags.append(False)
            continue
        flags.append(True)
        stripped = text.strip(b" \t")
        if len(stripped) >= fence[1] and stripped == fence[0] * len(stripped) and len(text) - len(text.lstrip(b" ")) <= 3:
            fence = None
    return flags


def _front_matter_span(lines: list[bytes]) -> tuple[int, int] | None:
    """[start, end) line indexes of the leading front matter block, when it is opened and closed."""
    i = 0
    while i < len(lines) and not lines[i].strip().strip(b"\xef\xbb\xbf"):
        i += 1
    if i >= len(lines) or lines[i].strip().strip(b"\xef\xbb\xbf") != b"---":
        return None
    for j in range(i + 1, len(lines)):
        if lines[j].strip() in (b"---", b"..."):
            return i + 1, j
    return None


def opt_in_status(data: bytes) -> tuple[bool, list[int]]:
    """(opted in, 1-based lines that are key-shaped but did not resolve to an opt-in).

    Opted in: the leading front matter carries the key. Key-shaped: outside a fenced code block a line that starts, after
    indentation, with the key word and a colon or with ``<!--`` and the key word; any line naming the key word inside the leading
    front matter. Prose and inline-code mentions are neither."""
    lines = data.split(b"\n")
    span = _front_matter_span(lines)
    if span and any(_FRONT_KEY_RE.match(lines[k].lstrip(b"\xef\xbb\xbf")) for k in range(*span)):
        return True, []
    flags = fence_flags(lines)
    bad = [k + 1 for k, line in enumerate(lines)
           if (span and span[0] <= k < span[1] and _SCOPE_WORD_RE.search(line))
           or (not flags[k] and _KEY_SHAPED_RE.match(line.lstrip(b"\xef\xbb\xbf")))]
    return False, bad


def has_tracker_free_front_matter(data: bytes) -> bool:
    return opt_in_status(data)[0]


def _heading_level(line: bytes) -> int:
    """ATX heading level 1-6 of a line (up to three spaces of indent, then 1-6 hashes, then a space, tab or the line end), else 0."""
    m = _HEADING_RE.match(line)
    return len(m.group(1)) if m else 0


def marked_entries(lines: list[bytes]) -> list[tuple[int, int]]:
    """[start, end) line indexes of every marked PERFORMANCE_LOG entry; see the module docstring for the boundaries."""
    out: list[tuple[int, int]] = []
    n = len(lines)
    flags = fence_flags(lines)
    covered = 0
    for i, line in enumerate(lines):
        if i < covered or not _MARKER_RE.match(line):
            continue
        heading = None
        level = 0
        end = n
        for j in range(i + 1, n):
            cur = lines[j]
            if heading is None and _MARKER_RE.match(cur):
                end = j
                break
            if flags[j]:
                continue
            cur_level = _heading_level(cur)
            if not cur_level:
                continue
            if heading is None:
                heading = j
                level = cur_level
            elif cur_level <= level:
                end = j
                break
        out.append((i, end))
        covered = end
    return out


def malformed_log_lines(lines: list[bytes]) -> list[int]:
    """1-based lines of PERFORMANCE_LOG.md that are key-shaped outside a fenced block and are not a valid marker."""
    flags = fence_flags(lines)
    return [i + 1 for i, line in enumerate(lines) if not flags[i] and _KEY_SHAPED_RE.match(line) and not _MARKER_RE.match(line)]


def _name_segments(path: str, kind: str) -> list[str]:
    seg = path.split("/")
    return seg[2:] if kind in ("probe", "perf") else seg[-1:]


def _is_version(s: str, m: re.Match[str]) -> bool:
    a = m.start()
    return bool(_VERSION_AFTER_RE.match(s, a) or _VERSION_OV_RE.match(s, max(0, a - 2)) or _VERSION_OV_RE.match(s, max(0, a - 8)))


def _is_year_of_date(s: str, m: re.Match[str]) -> bool:
    n = int(m.group())
    return 1900 <= n <= 2099 and bool(_MONTH_TAIL_RE.match(s, m.end()))


def _not_a_tracker(s: str, m: re.Match[str]) -> bool:
    return _is_year_of_date(s, m) or _is_version(s, m)


def name_number_hits(path: str, kind: str) -> int:
    hits = 0
    for s in _name_segments(path, kind):
        hits += sum(1 for m in _NUM4_RE.finditer(s) if not _not_a_tracker(s, m))
    return hits


def mask_numbers(path: str) -> str:
    """The path as printed: every run of four or more digits reads ``NNNN`` unless it is the year of a date or a compact date."""
    def sub(m: re.Match[str]) -> str:
        run = m.group()
        if len(run) == 8 and _COMPACT_DATE_RE.fullmatch(run):
            return run
        if len(run) == 4 and _not_a_tracker(m.string, m):
            return run
        return "NNNN"
    return _LONG_RUN_RE.sub(sub, path)


# ---- content --------------------------------------------------------------------------------------------------------------------

def scan_bytes(data: bytes, line_offset: int = 0) -> tuple[dict[str, int], dict[str, list[int]]]:
    """Per content pattern: the highest non-exempt match count over all readings, and the lines of the first reading reaching it."""
    counts = dict.fromkeys(CONTENT_PATTERNS, 0)
    lines: dict[str, list[int]] = {p: [] for p in CONTENT_PATTERNS}
    for v in il.views(data):
        for name, rx in _PATTERN_RES.items():
            found: list[int] = []
            for m in rx.finditer(v):
                if name == "tracker-ref":
                    head = v[max(0, m.start() - 120):m.start()].rsplit(b"\n", 1)[-1]
                    if _UPSTREAM_TAIL_RE.search(head):
                        continue
                found.append(v.count(b"\n", 0, m.start()) + 1 + line_offset)
            if len(found) > counts[name]:
                counts[name] = len(found)
                lines[name] = found
    return counts, lines


def _zero() -> tuple[dict[str, int], dict[str, list[int]]]:
    return dict.fromkeys(ALL_PATTERNS, 0), {p: [] for p in ALL_PATTERNS}


def scan_index(root: Path) -> dict[str, FileResult]:
    """Every in-scope file of the index with its findings (zero counts included)."""
    entries = index_entries(root)
    kinds = {p: path_kind(p) for p in entries}
    want = [sha for p, sha in entries.items()
            if kinds[p] or p == PERF_LOG or p.lower().endswith(FRONT_MATTER_SUFFIXES)]
    blobs = read_blobs(root, want)
    results: dict[str, FileResult] = {}
    for path, sha in entries.items():
        kind = kinds[path]
        data = blobs.get(sha)
        if data is None:
            continue
        if path == PERF_LOG:
            raw_lines = data.split(b"\n")
            spans = marked_entries(raw_lines)
            bad = malformed_log_lines(raw_lines)
            if spans or bad:
                counts, lines = _zero()
                for a, b in spans:
                    c, ln = scan_bytes(b"\n".join(raw_lines[a:b]), a)
                    for p in CONTENT_PATTERNS:
                        counts[p] += c[p]
                        lines[p] += ln[p]
                counts[MALFORMED_PATTERN] = len(bad)
                lines[MALFORMED_PATTERN] = bad
                results[path] = FileResult(path, "log-entries", counts, lines)
            continue
        is_text = path.lower().endswith(FRONT_MATTER_SUFFIXES)
        if kind is None and is_text:
            opted, bad = opt_in_status(data)
            if opted:
                kind = "marked-file"
            elif bad:
                counts, lines = _zero()
                counts[MALFORMED_PATTERN] = len(bad)
                lines[MALFORMED_PATTERN] = bad
                results[path] = FileResult(path, "malformed", counts, lines)
                continue
        if kind is None:
            continue
        counts, lines = scan_bytes(data)
        counts[NAME_PATTERN] = name_number_hits(path, kind)
        counts[MALFORMED_PATTERN] = 0
        lines[NAME_PATTERN] = []
        lines[MALFORMED_PATTERN] = []
        results[path] = FileResult(path, kind, counts, lines)
    return results


# ---- baseline and ratchet -------------------------------------------------------------------------------------------------------

def load_baseline_text(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("counts"), dict) or not isinstance(data.get("names"), list):
        raise LockError("the baseline is not a mapping with 'counts' and 'names'")
    return data


def load_baseline(root: Path) -> dict:
    """The baseline as the INDEX holds it; an untracked or unstaged baseline has no effect."""
    sha = index_entries(root).get(BASELINE_PATH)
    if sha is not None:
        return load_baseline_text(read_blobs(root, [sha])[sha].decode("utf-8"))
    return {"counts": {}, "names": []}


def current_baseline_shape(results: dict[str, FileResult]) -> dict:
    counts: dict[str, dict[str, int]] = {}
    names: list[str] = []
    for path, r in sorted(results.items()):
        if not r.baselinable:
            continue
        per = {p: r.counts.get(p, 0) for p in CONTENT_PATTERNS if r.counts.get(p, 0)}
        if per:
            counts[path] = per
        if r.counts.get(NAME_PATTERN, 0):
            names.append(path)
    return {"counts": counts, "names": names}


def violations(results: dict[str, FileResult], baseline: dict) -> list[str]:
    out: list[str] = []
    b_counts: dict[str, dict[str, int]] = baseline["counts"]
    b_names: set[str] = set(baseline["names"])
    for path, per in b_counts.items():
        for p, n in per.items():
            if p not in CONTENT_PATTERNS or not isinstance(n, int) or n < 1:
                out.append(f"{mask_numbers(path)}: baseline entry for pattern '{p}' is malformed")
    for path in sorted(set(b_counts) | b_names):
        r = results.get(path)
        if r is None:
            out.append(f"{mask_numbers(path)}: baselined file is gone or no longer in scope; drop it from the baseline")
        elif not r.baselinable:
            out.append(f"{mask_numbers(path)}: file is never baselined; drop it from the baseline")
    for path, r in sorted(results.items()):
        shown = mask_numbers(path)
        listed = r.baselinable
        for p in CONTENT_PATTERNS:
            c = r.counts.get(p, 0)
            allowed = b_counts.get(path, {}).get(p, 0) if listed else 0
            if c > allowed:
                where = f" at line(s) {sorted(set(r.lines.get(p, [])))}" if r.lines.get(p) else ""
                out.append(f"{shown}: pattern '{p}' x{c} exceeds the allowed {allowed}{where}")
            elif c < allowed:
                out.append(f"{shown}: pattern '{p}' x{c} is below the baseline {allowed}; lower the baseline in this change")
        if r.counts.get(MALFORMED_PATTERN, 0):
            where = f" at line(s) {r.lines[MALFORMED_PATTERN]}" if r.lines.get(MALFORMED_PATTERN) else ""
            out.append(f"{shown}: pattern '{MALFORMED_PATTERN}': the scope word is present but the opt-in did not parse{where}")
        has_name = r.counts.get(NAME_PATTERN, 0) > 0
        is_listed = listed and path in b_names
        if has_name and not is_listed:
            out.append(f"{shown}: pattern '{NAME_PATTERN}' in the file's own name")
        elif is_listed and not has_name:
            out.append(f"{shown}: pattern '{NAME_PATTERN}' is gone; drop the path from the baseline in this change")
    return out


def reference_violations(baseline: dict, reference: dict) -> list[str]:
    """The baseline may only fall against the reference. A name entry the reference lacks is admitted when the path was already
    tracked at the reference commit (a banked file that a tightened rule newly catches is not growth) and refused for a path
    that is new since."""
    out: list[str] = []
    tracked = reference.get("tracked", set())
    for path, per in baseline["counts"].items():
        for p, n in per.items():
            if n > reference["counts"].get(path, {}).get(p, 0):
                out.append(f"{mask_numbers(path)}: baseline count for '{p}' rose against the reference")
    for path in set(baseline["names"]) - set(reference["names"]):
        if path not in tracked:
            out.append(f"{mask_numbers(path)}: baseline gained a name entry against the reference")
    return out


def check(root: Path, reference_ref: str | None = None) -> list[str]:
    results = scan_index(root)
    if not {r.kind for r in results.values()} & {"probe", "perf", "preflight"}:
        raise LockError("the index holds no probe, performance or checklist file: an empty or failed checkout; the lock sees nothing")
    baseline = load_baseline(root)
    out = violations(results, baseline)
    if reference_ref:
        reference = reference_baseline(root, reference_ref)  # an unresolvable ref raises: never "a new baseline"
        if reference is not None:
            out += reference_violations(baseline, reference)
    return out


def write_baseline(root: Path, base_ref: str, add_existing_names: bool = False) -> tuple[list[str], dict | None]:
    """(errors, new baseline). Creates the file or lowers it; never raises a count or adds a path.

    With ``add_existing_names`` a name finding may be listed for a file already tracked at ``base_ref``."""
    results = scan_index(root)
    base_commit = resolve_ref(root, base_ref)
    if add_existing_names:
        main_tip = resolve_ref(root, "main")
        rc, mb = _git_rc(root, ["merge-base", "HEAD", "main"])
        if base_commit not in {main_tip, mb.decode().strip() if rc == 0 else ""}:
            return [f"--add-existing-names needs --base-ref to be main's tip or the merge base with main, not '{base_ref}'"], None
    at_base = tracked_at(root, base_ref)
    has_existing = BASELINE_PATH in at_base
    existing = (load_baseline_text(_git(root, ["show", f"{base_ref}:{BASELINE_PATH}"]).decode("utf-8"))
                if has_existing else {"counts": {}, "names": []})
    shape = current_baseline_shape(results)
    errors: list[str] = []
    for path, r in sorted(results.items()):
        has = any(r.counts.get(p, 0) for p in ALL_PATTERNS)
        if has and not r.baselinable:
            errors.append(f"{mask_numbers(path)}: findings in a file that is never baselined; remove them")
        elif has and path not in at_base:
            errors.append(f"{mask_numbers(path)}: findings in a file not tracked at {base_ref}; a new file starts at zero")
    if has_existing:
        for path, per in shape["counts"].items():
            for p, n in per.items():
                if n > existing["counts"].get(path, {}).get(p, 0):
                    errors.append(f"{mask_numbers(path)}: '{p}' would raise the baseline; refused")
        if not add_existing_names:
            for path in set(shape["names"]) - set(existing["names"]):
                errors.append(f"{mask_numbers(path)}: name entry would be added to the baseline; refused")
    if errors:
        return errors, None
    return [], shape


# ---- CLI ------------------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Research-file tracker-number lock and ratchet.")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--base-ref", default="main")
    ap.add_argument("--reference-ref", default=None)
    ap.add_argument("--add-existing-names", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        if args.check:
            bad = check(root, args.reference_ref)
            for line in bad:
                print(line)
            print(f"research tracker lock: {'FAIL' if bad else 'ok'} ({len(bad)} finding(s))")
            return 1 if bad else 0
        errors, shape = write_baseline(root, args.base_ref, args.add_existing_names)
        for line in errors:
            print(line)
        if shape is None:
            print("research tracker lock: baseline NOT written")
            return 1
        (root / BASELINE_PATH).parent.mkdir(parents=True, exist_ok=True)
        (root / BASELINE_PATH).write_text(json.dumps(shape, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"baseline written: {len(shape['counts'])} content file(s), {len(shape['names'])} name file(s)")
        return 0
    except LockError as exc:
        print(f"research tracker lock: cannot run: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
