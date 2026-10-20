"""Lock: the public snapshot leaves out material that belongs in a private folder outside this repository (#1777).

WHAT FAILURE THIS EXISTS FOR
----------------------------
The publisher takes ``main``'s tree whole, so a tracked file that belongs in a private folder is published unless something
holds it back. A tracked ``.publicignore`` names those files and the publisher subtracts the list from the tree before it scans
and commits it. This file locks the tracked side of that control; the publisher's side is exercised by its ``-DryRun``, by its
scratch-repository test and by the shared conformance table ``scripts/publicignore_cases.json``.

WHAT IS LOCKED HERE
-------------------
1. ``.publicignore``, read from the INDEX (``git show :.publicignore``) and never from the working copy, is tracked, parses,
   excludes itself and matches something.
2. Every tracked path whose NAME belongs to a name class below is matched by the list.
3. No tracked blob that the list does not match carries a phrase from ``scripts/publicignore_phrases.json`` (read from the index;
   the joined, sorted phrase set is pinned by a sha256 below, so a changed phrase is a reviewed diff).
4. Every journal fragment the list excludes starts with the marker line below, and no unexcluded tracked file (the journal, its
   archive volumes, the lessons, the field notes, the anthology, anything under ``docs/archive/``) carries the marker, so a
   held-back fragment folded into any public surface fails here.
4b. The filtered tree keeps the anchor paths (``README.md``, ``LICENSE.md``): a list that matches everything would publish an empty tree.
4c. ``scripts/publicignore_anchors.txt`` (read from the index) names the public evidence the posts cite; the list may not exclude
   any path it names (a trailing ``/`` names everything beneath), and an anchor that names no tracked path fails too.
4d. Every tracked path an anchored document cites is itself anchored, or is listed in ``scripts/publicignore_cited_unanchored.txt``
   with a one-line reason (``path | reason``). The documents scanned are every text file the anchors above the
   ``#:cited-only`` line of ``scripts/publicignore_anchors.txt`` name (any extension; a blob that starts with the gzip magic or holds
   a NUL byte in its first 8 KB is binary and not read); the anchors below that line keep the cited paths public and
   are not scanned in turn (one hop, not the closure of the repository). A citation is a path-shaped token that equals a tracked
   file, or a tracked directory of three or more segments; a relative link (``../x.md``) and a directory of one or two segments
   (an area, not a citation) are not read. An allowlist entry that is not tracked, is anchored, is cited by no scanned document or
   has no reason fails too.
5. The matching rules in ``scripts/publicignore.py`` give the answers in ``scripts/publicignore_cases.json`` and refuse what
   they should refuse.
6. Toggles: a planted phrase in an unexcluded scratch file fails the scan and passes once the file is excluded; every spelling of
   the numbered phrase is caught; altered forms (double space, line break, CRLF, tab) are caught; an empty list fails the name and
   self checks; each decoded view catches its plant; an unreadable gzip is reported; an unstaged edit to the list changes
   nothing; the marker checks fail on a fragment without it and on a journal that carries it; a missing list and a missing git
   fail and never skip.

VIEWS EACH SIDE READS
---------------------
This lock reads every blob of the index (binary files as bytes too) under: the raw text lower-cased; whitespace collapsed (line
breaks LF and CRLF, tabs, runs of spaces); UTF-16 little and big endian; gzip, nested up to three deep; ``&amp;`` and numeric
``&#...;`` entities undone; JSON ``\\uXXXX`` escapes undone; a backslash before punctuation dropped (Markdown ``\\_``); percent
escapes decoded (``%20``); every view is decoded first and lower-cased after.
The publisher (agentic-setup, ``publish-public-snapshot.ps1``) reads the tree it is about to publish under two views: one
``git grep -E`` per private pattern (a single line, per-letter case classes, literal spaces), and a normalized view of every blob
(lower-cased, whitespace collapsed, read as UTF-8 and as UTF-16, gzip unpacked up to three deep, backslash-before-punctuation
dropped, percent escapes decoded) searched for the phrases the private file lists. It does not undo entities or JSON escapes. For
those two forms this lock is the only control.

HONEST LIMITS
-------------
The exclusion is a LIST. A new file under a name the classes do not cover is caught only if it carries a phrase. A phrase split
by anything other than whitespace, an entity or a JSON escape, or written with a backslash before punctuation or percent escapes
in place of characters (one view each, never chained), is not seen by either side, and neither are: a plus sign for a space,
double percent encoding, a backslash before a space, a Markdown backslash line break, a doubled backslash before punctuation, a
backslash form and a percent form in the same phrase, a soft hyphen or zero-width character, an en dash or non-breaking hyphen, full-width letters, text inside a deflated
office document, Markdown emphasis or a quote marker inside a phrase, punctuation between the target name and its numbering, a
word, "no." or a leading zero before the number, the target name spaced or with its organisation suffix, and UTF-16 at an odd
offset or after the first 4 KB. The marker is a tripwire on a verbatim fold, not a block: a
fragment folded by hand without its first line is not seen. The scan reads the index, so an untracked file is neither
published nor read.
"""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Iterator, NamedTuple
from urllib.parse import unquote

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
CASES_FILE = SCRIPTS / "publicignore_cases.json"
PHRASES_FILE = SCRIPTS / "publicignore_phrases.json"

sys.path.insert(0, str(SCRIPTS))
import publicignore as pi  # noqa: E402


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        pytest.fail(f"{path} cannot be read: {exc}")


def _phrase_data_from_index(root: Path) -> dict:
    """The phrase file as the INDEX holds it (never the working copy), the same rule as for the list."""
    rel = PHRASES_FILE.relative_to(REPO_ROOT).as_posix()
    cmd = ["git", "-C", str(root), "show", f":{rel}"]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=120)
        if done.returncode != 0:
            raise OSError(done.stderr.decode("utf-8", "replace").strip())
        return json.loads(done.stdout.decode("utf-8"))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        pytest.fail(f"{rel} (index copy) cannot be read: {exc}")


def _load_phrases(root: Path = REPO_ROOT) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """``(target name, plain phrases, numbered spellings)``, each joined from the parts stored in the JSON file.

    The parts live in a file of their own so that this file, the file that implements the rules and the publisher's scratch test
    (which reads the same JSON) carry no phrase, and so the two repositories cannot drift apart. The lock reads the index copy.
    """
    data = _phrase_data_from_index(root)
    target = "".join(data["target"])
    plain = tuple("".join(parts) for parts in data["phrases"])
    n = data["numbering"]
    stem = "".join(n["stem"])
    numbered = tuple(f"{target}{a}{stem}{b}{n['number']}" for a in n["before"] for b in n["after"])
    return target, plain, numbered


TARGET, PLAIN_PHRASES, NUMBERED_PHRASES = _load_phrases()
PRIVATE_PHRASES: tuple[str, ...] = PLAIN_PHRASES + NUMBERED_PHRASES

# sha256 of the sorted phrases joined with newlines (case as stored). Changing a phrase, or the file, fails until this value is
# changed in the same diff, so the phrase set cannot shrink without a reviewer seeing it.
PHRASE_SET_DIGEST = "d88587f8bc62f5c37d765a60032130852d7895d0945aa43defa14beeafc08827"


def phrase_set_digest(phrases: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(phrases)).encode("utf-8")).hexdigest()

# Paths that must survive the filter: a list that matches everything would publish an empty tree.
ANCHOR_PATHS: tuple[str, ...] = ("README.md", "LICENSE.md")
ANCHORS_FILE = "scripts/publicignore_anchors.txt"
CITED_ONLY_MARK = "#:cited-only"
CITED_ALLOWLIST_FILE = "scripts/publicignore_cited_unanchored.txt"

# Name classes, matched anywhere in a tracked path, ignoring case. 1741 is held to digit boundaries so a timestamp or a hash that
# happens to contain it is not mistaken for the ticket.
PRIVATE_NAME_PATTERNS: tuple[str, ...] = (
    TARGET,
    r"(?<!\d)1741(?!\d)",
    r"handback",
    r"review-nep0005-[^/]*-1763",
    r"nep0005-open-questions-[^/]*gate",
)
_NAME_RE = re.compile("|".join(f"(?:{p})" for p in PRIVATE_NAME_PATTERNS), re.IGNORECASE)

FRAGMENT_DIR = "docs/journal_fragments/"
FRAGMENT_MARKER = "<!-- PRIVATE: not for the public journal; excluded by .publicignore -->"
_MARKER_CORE = "private: not for the public journal"
MARKER_DEFINED_IN = "tests/security/test_public_snapshot_excludes_private_material.py"

_WS = re.compile(r"\s+")
_JSON_U = re.compile(r"\\u([0-9a-fA-F]{4})", re.IGNORECASE)
_BACKSLASH_PUNCT = re.compile(r"\\([!-/:-@\[-`{-~])")
_GZIP_MAGIC = b"\x1f\x8b"


class Entry(NamedTuple):
    mode: str
    sha: str
    path: str


# ------------------------------------------------------------------------------------------------ git access (fail, never skip)

def _git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    cmd = ["git", "-C", str(root), "-c", "core.quotepath=false", *args]
    try:
        done = subprocess.run(cmd, input=stdin, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.fail(f"git is not usable ({exc}); this lock cannot be skipped: {' '.join(args)}")
    if done.returncode != 0:
        pytest.fail(f"git {' '.join(args)} failed in {root}: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def tracked_entries(root: Path) -> list[Entry]:
    """Every entry of the index: ``(mode, blob id, path)``, read NUL-separated so no path is ever quoted."""
    out: list[Entry] = []
    for rec in _git(root, "ls-files", "-s", "-z").split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        mode, sha, _stage = meta.decode("ascii").split(" ")
        out.append(Entry(mode, sha, path.decode("utf-8")))
    if not out:
        pytest.fail(f"git reports no tracked files in {root}")
    return out


def load_rules(root: Path) -> pi.Ruleset:
    """The list as the publisher reads it: the INDEX copy, never the working copy."""
    raw = _git(root, "show", f":{pi.IGNORE_FILE}")
    try:
        return pi.parse(raw.decode("utf-8"), f":{pi.IGNORE_FILE}")
    except (UnicodeDecodeError, pi.PublicIgnoreError) as exc:
        pytest.fail(f"{pi.IGNORE_FILE} (index copy) cannot be used: {exc}")


def load_anchors(root: Path) -> list[str]:
    """The anchor entries as the INDEX holds them: one per line, ``#`` lines and blanks ignored, a trailing ``/`` = everything beneath."""
    text = _git(root, "show", f":{ANCHORS_FILE}").decode("utf-8")
    entries = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not entries:
        pytest.fail(f"{ANCHORS_FILE} (index copy) names no anchor")
    return entries


def load_anchor_sections(root: Path) -> tuple[list[str], list[str]]:
    """``(documents' anchors, cited-only anchors)``: the entries above and below the ``#:cited-only`` line; other ``#`` lines are comments."""
    text = _git(root, "show", f":{ANCHORS_FILE}").decode("utf-8")
    primary: list[str] = []
    cited_only: list[str] = []
    bucket = primary
    for ln in text.splitlines():
        ln = ln.strip()
        if ln == CITED_ONLY_MARK:
            bucket = cited_only
        elif ln and not ln.startswith("#"):
            bucket.append(ln)
    return primary, cited_only


def load_cited_allowlist(root: Path) -> dict[str, str]:
    """``{path: reason}`` from the INDEX copy of the allowlist; a line without a ``path | reason`` shape fails (an empty list is valid)."""
    text = _git(root, "show", f":{CITED_ALLOWLIST_FILE}").decode("utf-8")
    entries: dict[str, str] = {}
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        path, sep, reason = (part.strip() for part in ln.partition("|"))
        if not sep or not path or not reason:
            pytest.fail(f"{CITED_ALLOWLIST_FILE}: '{ln}' is not 'path | reason'")
        entries[path] = reason
    return entries


_CITE_TOKEN = re.compile(r"[A-Za-z0-9_.\-/]+")


def _anchor_covers(anchors: list[str], path: str) -> bool:
    return any(path.startswith(a) if a.endswith("/") else path == a for a in anchors)


def citations(text: str, tracked: set[str], dirs: set[str]) -> set[str]:
    """Tracked paths a document names: a token that equals a tracked file, or a tracked directory of three or more segments."""
    found: set[str] = set()
    for tok in _CITE_TOKEN.findall(text):
        while tok.startswith("./"):
            tok = tok[2:]
        tok = tok.rstrip(".,;:").rstrip("/")
        if tok in tracked or (tok in dirs and tok.count("/") >= 2):
            found.add(tok)
    return found


def cited_findings(root: Path, paths: list[str]) -> tuple[list[str], list[str]]:
    """``(paths a scanned document cites that no anchor covers and the allowlist does not hold, allowlist problems)``."""
    primary, cited_only = load_anchor_sections(root)
    anchors = primary + cited_only
    allow = load_cited_allowlist(root)
    tracked = set(paths)
    dirs = {"/".join(p.split("/")[:i]) for p in paths for i in range(1, p.count("/") + 1)}
    cited: set[str] = set()
    for doc in (p for p in paths if _anchor_covers(primary, p)):
        data = _git(root, "show", f":{doc}")
        if data.startswith(_GZIP_MAGIC) or b"\x00" in data[:8192]:
            continue
        cited |= citations(data.decode("utf-8", "replace"), tracked, dirs)
    # a cited directory is covered by an anchor that names it or a folder above it
    unanchored = sorted(c for c in cited if not _anchor_covers(anchors, c + ("/" if c in dirs else "")) and c not in allow)
    problems = [f"{a}: not tracked" for a in allow if a not in tracked and a not in dirs]
    problems += [f"{a}: anchored, so it needs no allowlist line" for a in allow if _anchor_covers(anchors, a + ("/" if a in dirs else ""))]
    problems += [f"{a}: cited by no scanned document" for a in allow if (a in tracked or a in dirs) and a not in cited]
    return unanchored, sorted(problems)


def anchor_findings(paths: list[str], excluded: set[str], anchors: list[str]) -> tuple[list[str], list[str]]:
    """``(anchored paths the list excludes, anchors that name no tracked path)``."""
    removed: list[str] = []
    empty: list[str] = []
    for a in anchors:
        named = [p for p in paths if (p.startswith(a) if a.endswith("/") else p == a)]
        if not named:
            empty.append(a)
        removed += [p for p in named if p in excluded]
    return sorted(set(removed)), empty


def iter_blobs(root: Path, entries: Iterable[Entry]) -> Iterator[tuple[Entry, bytes]]:
    """``(entry, content)`` for each entry that has a blob, read through one ``git cat-file --batch``."""
    try:
        proc = subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        pytest.fail(f"git is not usable ({exc}); this lock cannot be skipped")
    assert proc.stdin is not None and proc.stdout is not None
    try:
        for e in entries:
            if e.mode == "160000":  # a submodule pointer has no blob here
                continue
            proc.stdin.write(e.sha.encode("ascii") + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob":
                pytest.fail(f"git cat-file gave {header!r} for {e.path} ({e.sha})")
            data = proc.stdout.read(int(header[2]))
            proc.stdout.read(1)
            yield e, data
    finally:
        proc.stdin.close()
        proc.wait(timeout=60)


# ------------------------------------------------------------------------------------------------ the checks

def name_class_misses(paths: Iterable[str], rules: pi.Ruleset) -> list[str]:
    """Tracked paths with a name in a private name class that the list does not match."""
    return [p for p in paths if _NAME_RE.search(p) and not rules.matches(p)]


def _text_variants(text: str) -> Iterator[str]:
    """Each decoded view, then lower-cased: an encoded capital letter folds like any other."""
    bases = [text]
    if "&amp;" in text.lower() or "&#" in text:
        bases.append(html.unescape(text))
    if "\\u" in text.lower():
        bases.append(_JSON_U.sub(lambda m: chr(int(m.group(1), 16)), text))
    if "\\" in text:
        bases.append(_BACKSLASH_PUNCT.sub(r"\1", text))
    if "%" in text:
        bases.append(unquote(text))
    for base in bases:
        lowered = base.lower()
        yield lowered
        yield _WS.sub(" ", lowered)


def _texts(data: bytes) -> Iterator[str]:
    yield data.decode("utf-8", "replace")
    if b"\x00" in data[:4096]:
        yield data.decode("utf-16-le", "replace")
        yield data.decode("utf-16-be", "replace")


def phrases_in(data: bytes, needles: tuple[str, ...], depth: int = 0) -> tuple[set[str], list[str]]:
    """Phrases (lower case) found in ``data`` under every view, and the problems that stopped a view from being read."""
    found: set[str] = set()
    problems: list[str] = []
    for text in _texts(data):
        for variant in _text_variants(text):
            found.update(n for n in needles if n in variant)
    if data[:2] == _GZIP_MAGIC:
        if depth >= 3:
            problems.append("gzip nested deeper than three levels")
        else:
            try:
                inner = gzip.decompress(data)
            except (OSError, EOFError, ValueError) as exc:
                problems.append(f"gzip cannot be decompressed ({exc})")
            else:
                inner_found, inner_problems = phrases_in(inner, needles, depth + 1)
                found |= inner_found
                problems += inner_problems
    return found, problems


def scan_entries(root: Path, entries: Iterable[Entry], phrases: tuple[str, ...] = PRIVATE_PHRASES) -> dict[str, list[str]]:
    """``{path: [phrase or problem, ...]}`` for the entries whose blobs carry a phrase or cannot be read."""
    needles = tuple(p.lower() for p in phrases)
    result: dict[str, list[str]] = {}
    for e, data in iter_blobs(root, entries):
        found, problems = phrases_in(data, needles)
        if found or problems:
            result[e.path] = sorted(found) + problems
    return result


def fragments_without_marker(root: Path, entries: list[Entry], excluded: set[str]) -> list[str]:
    """Excluded journal fragments whose first line is not the marker."""
    marker = FRAGMENT_MARKER.encode("utf-8")
    fragments = [e for e in entries if e.path in excluded and e.path.startswith(FRAGMENT_DIR) and e.path.endswith(".md")]
    return [e.path for e, data in iter_blobs(root, fragments) if data.split(b"\n", 1)[0].rstrip(b"\r") != marker]


def check_tree(root: Path) -> dict[str, object]:
    """The whole lock over one repository; a clean tree reports empty or true for every finding."""
    entries = tracked_entries(root)
    paths = [e.path for e in entries]
    rules = load_rules(root)
    excluded = set(rules.excluded_paths(paths))
    published = [e for e in entries if e.path not in excluded]
    # one pass over every published blob: the phrases and the fold marker (the file that defines the marker is exempt)
    scanned = scan_entries(root, published, PRIVATE_PHRASES + (_MARKER_CORE,))
    marker_hits = sorted(p for p, found in scanned.items() if _MARKER_CORE in found and p != MARKER_DEFINED_IN)
    phrase_hits = {p: rest for p, found in scanned.items() if (rest := [f for f in found if f != _MARKER_CORE])}
    present = {e.path for e in published}
    anchored_removed, anchors_empty = anchor_findings(paths, excluded, load_anchors(root))
    cited_unanchored, cited_allowlist_problems = cited_findings(root, paths)
    return {
        "list_is_tracked": pi.IGNORE_FILE in paths,
        "list_excludes_itself": rules.matches(pi.IGNORE_FILE),
        "list_matches_nothing": bool(len(rules)) and not excluded,
        "name_misses": name_class_misses(paths, rules),
        "phrase_hits": phrase_hits,
        "fragments_without_marker": fragments_without_marker(root, entries, excluded),
        "journal_with_marker": marker_hits,
        "anchors_lost": [a for a in ANCHOR_PATHS if a in paths and a not in present],
        "tree_is_empty": not present,
        "anchored_but_excluded": anchored_removed,
        "anchors_naming_nothing": anchors_empty,
        "cited_unanchored": cited_unanchored,
        "cited_allowlist_problems": cited_allowlist_problems,
    }


# ------------------------------------------------------------------------------------------------ the real tree

@pytest.fixture(scope="module")
def real_tree() -> dict[str, object]:
    return check_tree(REPO_ROOT)


def test_list_is_tracked_parses_and_excludes_itself(real_tree: dict[str, object]) -> None:
    assert real_tree["list_is_tracked"], f"{pi.IGNORE_FILE} is not tracked: the publisher reads it from main's tree"
    assert real_tree["list_excludes_itself"], f"{pi.IGNORE_FILE} must match itself"


def test_list_matches_something(real_tree: dict[str, object]) -> None:
    assert not real_tree["list_matches_nothing"], "the list has patterns and matches no tracked path: a broken list"


def test_every_private_name_class_path_is_excluded(real_tree: dict[str, object]) -> None:
    assert real_tree["name_misses"] == [], (
        "tracked paths with a private name that .publicignore does not match (add a pattern, or rename the file): "
        + ", ".join(real_tree["name_misses"])  # type: ignore[arg-type]
    )


def test_no_unexcluded_tracked_file_carries_a_private_phrase(real_tree: dict[str, object]) -> None:
    hits: dict[str, list[str]] = real_tree["phrase_hits"]  # type: ignore[assignment]
    assert hits == {}, "unexcluded tracked files carry private phrases or cannot be read: " + json.dumps(hits, indent=1)


def test_every_excluded_journal_fragment_starts_with_the_marker(real_tree: dict[str, object]) -> None:
    assert real_tree["fragments_without_marker"] == [], (
        f"excluded journal fragments whose first line is not {FRAGMENT_MARKER!r}: "
        + ", ".join(real_tree["fragments_without_marker"])  # type: ignore[arg-type]
    )


def test_no_journal_file_carries_the_marker(real_tree: dict[str, object]) -> None:
    assert real_tree["journal_with_marker"] == [], (
        "a held-back fragment was folded into the public journal: " + ", ".join(real_tree["journal_with_marker"])  # type: ignore[arg-type]
    )


def test_the_filtered_tree_keeps_its_anchor_paths(real_tree: dict[str, object]) -> None:
    assert real_tree["anchors_lost"] == [] and real_tree["tree_is_empty"] is False
    assert set(ANCHOR_PATHS) <= {e.path for e in tracked_entries(REPO_ROOT)}


def test_the_list_excludes_no_anchored_path(real_tree: dict[str, object]) -> None:
    assert real_tree["anchored_but_excluded"] == [], "the list holds back evidence the posts cite: " + ", ".join(real_tree["anchored_but_excluded"])  # type: ignore[arg-type]
    assert real_tree["anchors_naming_nothing"] == [], "anchors that name no tracked path: " + ", ".join(real_tree["anchors_naming_nothing"])  # type: ignore[arg-type]


def test_every_path_an_anchored_document_cites_is_anchored_or_allowlisted(real_tree: dict[str, object]) -> None:
    assert real_tree["cited_unanchored"] == [], (
        "anchored documents cite paths no anchor covers (add each to scripts/publicignore_anchors.txt below the cited-only line, or to "
        "scripts/publicignore_cited_unanchored.txt with a reason): " + ", ".join(real_tree["cited_unanchored"])  # type: ignore[arg-type]
    )
    assert real_tree["cited_allowlist_problems"] == [], "; ".join(real_tree["cited_allowlist_problems"])  # type: ignore[arg-type]


def test_the_anchor_file_names_the_public_evidence() -> None:
    anchors = load_anchors(REPO_ROOT)
    assert {"README.md", "LICENSE.md"} <= set(anchors) and len(anchors) >= 5
    assert any(a.endswith("/") for a in anchors)


def test_the_phrase_set_is_pinned() -> None:
    assert phrase_set_digest(PRIVATE_PHRASES) == PHRASE_SET_DIGEST, (
        "the phrase set changed: review the diff of scripts/publicignore_phrases.json, then update PHRASE_SET_DIGEST in this file"
    )


def test_the_phrases_are_not_written_out_in_the_files_that_implement_the_control() -> None:
    needles = tuple(p.lower() for p in PRIVATE_PHRASES)
    for rel in ("tests/security/test_public_snapshot_excludes_private_material.py", "scripts/publicignore.py",
                "scripts/publicignore_cases.json", "scripts/publicignore_phrases.json", pi.IGNORE_FILE):
        found, problems = phrases_in((REPO_ROOT / rel).read_bytes(), needles)
        assert not found and not problems, f"{rel} carries {found or problems}"


def test_the_phrase_set_covers_every_spelling_of_the_numbering() -> None:
    assert len(PLAIN_PHRASES) >= 11
    assert len(NUMBERED_PHRASES) == 16 and len(set(NUMBERED_PHRASES)) == 16
    assert {p[len(TARGET):] for p in NUMBERED_PHRASES} >= {"-item3", "item3", "_item3", " item 3", "-item-3", "_item_3", "item-3"}


# Built from parts: this file is published and must not carry the wording it keeps out of the reviews.
_UNPOSTED_DRAFT = re.compile(("un" "posted[ -]dra" "ft|dra" "ft v[0-9]").encode(), re.IGNORECASE)


def test_published_reviews_do_not_name_a_numbered_unposted_draft() -> None:
    """A versioned draft that is not published is a tell; every published review says "the evidence write-up (unposted)"."""
    entries = tracked_entries(REPO_ROOT)
    excluded = set(load_rules(REPO_ROOT).excluded_paths([e.path for e in entries]))
    reviews = [e for e in entries if e.path.startswith("docs/reviews/") and e.path not in excluded]
    assert len(reviews) > 50
    hits = [e.path for e, data in iter_blobs(REPO_ROOT, reviews) if _UNPOSTED_DRAFT.search(data)]
    assert hits == [], "numbered unposted-draft wording in a published review: " + ", ".join(hits)


def test_toggle_the_unposted_draft_wording_is_recognised() -> None:
    for text in ("R2-un" "posted-dra" "ft-v5-still", "dra" "ft v5:237", "Un" "posted dra" "ft"):
        assert _UNPOSTED_DRAFT.search(text.encode())
    assert not _UNPOSTED_DRAFT.search(b"the NEP-0005 evidence write-up (unposted)")


def test_the_one_review_of_this_control_is_held_back_by_the_list() -> None:
    rules = load_rules(REPO_ROOT)
    assert rules.matches("docs/reviews/review-1777-public-snapshot-excludes-2026-10-14.md")


# ------------------------------------------------------------------------------------------------ the rules

def _cases() -> list[dict]:
    return _read_json(CASES_FILE)["cases"]


def _case_id(case: dict) -> str:
    return f"{'|'.join(case['lines'])[:40]!r}-{case.get('path', '(parse)')!r}-{case['expect']}"


def test_the_conformance_table_covers_every_kind_of_answer() -> None:
    cases = _cases()
    assert len(cases) >= 40
    assert {c["expect"] for c in cases} == {True, False, "error"}


@pytest.mark.parametrize("case", _cases(), ids=_case_id)
def test_the_matching_rules_give_the_table_answer(case: dict) -> None:
    text = "\n".join(case["lines"])
    if case["expect"] == "error":
        with pytest.raises(pi.PublicIgnoreError):
            rules = pi.parse(text)
            if "path" in case:
                rules.matches(case["path"])
        return
    assert pi.parse(text).matches(case["path"]) is case["expect"]


def test_a_missing_list_is_an_error_not_an_empty_list(tmp_path: Path) -> None:
    with pytest.raises(pi.PublicIgnoreError):
        pi.load(tmp_path / pi.IGNORE_FILE)


def test_an_empty_list_is_valid_and_excludes_nothing() -> None:
    rules = pi.parse("# nothing\n\n")
    assert len(rules) == 0 and rules.excluded_paths(["a/b", "docs/x.md"]) == []


def test_the_rules_are_not_the_library_glob() -> None:
    """The semantics are written down in scripts/publicignore.py and re-implemented by the publisher; fnmatch lets ``*`` cross ``/``."""
    assert not pi.parse("docs/*.md").matches("docs/sub/x.md")
    assert pi.parse("docs/**/x.md").matches("docs/sub/deep/x.md")


# ------------------------------------------------------------------------------------------------ toggles (scratch repositories)

def _scratch(base: Path, files: dict[str, bytes], ignore: str) -> Path:
    base.mkdir(parents=True)
    _git(base, "init", "-q")
    files = {ANCHORS_FILE: b"# none\nREADME.md\n", CITED_ALLOWLIST_FILE: b"# none\n", **files, pi.IGNORE_FILE: ignore.encode("utf-8")}
    for rel, data in files.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _git(base, "add", "--", *files)
    return base


PLANT = PLAIN_PHRASES[0].encode("ascii")
SELF_EXCLUDING = ".publicignore\n"
MARKED = FRAGMENT_MARKER + "\n### 2026-10-01 — A title\n\nbody\n"


def test_toggle_a_planted_phrase_in_an_unexcluded_file_fails_and_passes_once_the_file_is_excluded(tmp_path: Path) -> None:
    files = {"notes/plain.md": b"a line, then " + PLANT + b", then another\n", "notes/clean.md": b"nothing here\n"}
    leaking = check_tree(_scratch(tmp_path / "leaking", files, SELF_EXCLUDING))
    assert list(leaking["phrase_hits"]) == ["notes/plain.md"]  # type: ignore[arg-type]
    held = check_tree(_scratch(tmp_path / "held", files, SELF_EXCLUDING + "notes/plain.md\n"))
    assert held["phrase_hits"] == {} and held["name_misses"] == [] and held["list_excludes_itself"] is True


@pytest.mark.parametrize("spelling", NUMBERED_PHRASES)
def test_toggle_every_spelling_of_the_numbering_is_caught_in_a_file_that_is_not_excluded(tmp_path: Path, spelling: str) -> None:
    root = _scratch(tmp_path / "numbering", {"notes/plain.md": f"see {spelling} here".encode("utf-8")}, SELF_EXCLUDING)
    assert list(check_tree(root)["phrase_hits"]) == ["notes/plain.md"]  # type: ignore[arg-type]


@pytest.mark.parametrize("form", ["double space", "line break", "crlf", "tab", "upper case", "line break and indent"])
def test_toggle_altered_forms_of_every_phrase_with_a_space_are_caught(form: str) -> None:
    needles = tuple(p.lower() for p in PRIVATE_PHRASES)
    spaced = [p for p in PRIVATE_PHRASES if " " in p]
    assert len(spaced) >= 6
    for phrase in spaced:
        text = {
            "double space": phrase.replace(" ", "  "),
            "line break": phrase.replace(" ", "\n"),
            "crlf": phrase.replace(" ", "\r\n"),
            "tab": phrase.replace(" ", "\t"),
            "upper case": phrase.upper(),
            "line break and indent": phrase.replace(" ", "\n   "),
        }[form]
        found, problems = phrases_in(text.encode("utf-8"), needles)
        assert phrase.lower() in found and problems == [], (form, phrase)


def test_toggle_an_empty_list_fails_the_name_class_and_self_exclusion_checks(tmp_path: Path) -> None:
    files = {f"docs/reviews/review-{TARGET}-item3-x.md": b"clean text\n", "docs/reviews/1741-note.md": b"clean text\n"}
    result = check_tree(_scratch(tmp_path / "empty", files, "# nothing is excluded\n"))
    assert result["list_excludes_itself"] is False
    assert sorted(result["name_misses"]) == ["docs/reviews/1741-note.md", f"docs/reviews/review-{TARGET}-item3-x.md"]  # type: ignore[arg-type]


def test_toggle_the_name_classes_each_bite_and_the_digit_boundary_holds() -> None:
    rules = pi.parse("# nothing\n")
    names = [f"a/{TARGET}.md", f"a/{TARGET.upper()}-x.md", f"a/{TARGET[:2].title()}{TARGET[2:].title()}-y.md", "a/x_1741_y.md",
             "a/HANDBACK_z.md", "a/review-nep0005-foo-1763-x.md", "a/nep0005-open-questions-v5-gate-x.md"]
    assert name_class_misses(names, rules) == names
    benign = ["a/x_17410.md", "a/21741.md", "a/review-nep0005-foo-1764.md", "a/nep0005-open-questions/runs/gate.json"]
    assert name_class_misses(benign, rules) == []


@pytest.mark.parametrize("view", ["newline", "case", "gzip", "utf16le", "utf16be", "html", "json", "nested-gzip"])
def test_toggle_each_decoded_view_catches_its_own_plant(view: str) -> None:
    phrase = next(p for p in PLAIN_PHRASES if "&" in p)
    needles = tuple(p.lower() for p in PRIVATE_PHRASES)
    first, _, rest = phrase.partition(" ")
    planted = {
        "newline": f"{first}\n   {rest}".encode(),
        "case": phrase.upper().encode(),
        "gzip": gzip.compress(phrase.encode()),
        "utf16le": phrase.encode("utf-16-le"),
        "utf16be": b"\xfe\xff" + phrase.encode("utf-16-be"),
        "html": phrase.replace("&", "&amp;").encode(),
        "json": phrase.replace("&", "\\u0026").encode(),
        "nested-gzip": gzip.compress(gzip.compress(phrase.encode())),
    }[view]
    found, problems = phrases_in(planted, needles)
    assert phrase.lower() in found and problems == []
    assert phrases_in(b"nothing to see", needles) == (set(), [])


def test_toggle_an_unreadable_gzip_is_reported_not_skipped() -> None:
    needles = tuple(p.lower() for p in PRIVATE_PHRASES)
    truncated = gzip.compress(b"x" * 5000)[:30]
    found, problems = phrases_in(truncated, needles)
    assert found == set() and problems and "gzip" in problems[0]


def test_toggle_an_unstaged_edit_to_the_list_does_not_change_the_answer(tmp_path: Path) -> None:
    files = {"notes/plain.md": b"a line, then " + PLANT + b", then another\n"}
    root = _scratch(tmp_path / "unstaged", files, SELF_EXCLUDING)
    (root / pi.IGNORE_FILE).write_bytes((SELF_EXCLUDING + "notes/plain.md\n").encode("utf-8"))  # edited, not staged
    assert list(check_tree(root)["phrase_hits"]) == ["notes/plain.md"]  # type: ignore[arg-type]
    held = _scratch(tmp_path / "staged", files, SELF_EXCLUDING + "notes/plain.md\n")
    (held / pi.IGNORE_FILE).write_bytes(b"# emptied in the working copy only\n")
    assert check_tree(held)["phrase_hits"] == {}


def test_toggle_a_list_that_is_only_in_the_working_copy_fails_the_check(tmp_path: Path) -> None:
    root = tmp_path / "untracked-list"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "a.md").write_text("x\n")
    (root / pi.IGNORE_FILE).write_text(SELF_EXCLUDING)
    _git(root, "add", "--", "a.md")
    with pytest.raises(pytest.fail.Exception):
        check_tree(root)


def test_toggle_the_marker_checks_fail_on_a_fragment_without_it_and_on_a_journal_that_carries_it(tmp_path: Path) -> None:
    ok = check_tree(_scratch(tmp_path / "ok", {f"{FRAGMENT_DIR}2026-10-01_a.md": MARKED.encode("utf-8")},
                             SELF_EXCLUDING + f"{FRAGMENT_DIR}2026-10-01_a.md\n"))
    assert ok["fragments_without_marker"] == [] and ok["journal_with_marker"] == []
    frag = f"{FRAGMENT_DIR}2026-10-01_a.md"
    for name, body in {"absent": b"### 2026-10-01 \xe2\x80\x94 A title\n\nbody\n",
                       "second line": b"### 2026-10-01 \xe2\x80\x94 A title\n" + FRAGMENT_MARKER.encode() + b"\n",
                       "bom first": b"\xef\xbb\xbf" + MARKED.encode("utf-8")}.items():
        bad = check_tree(_scratch(tmp_path / f"bad-{name.replace(' ', '-')}", {frag: body}, SELF_EXCLUDING + frag + "\n"))
        assert bad["fragments_without_marker"] == [frag], name
    for where in ("BUILD_JOURNAL.md", "docs/archive/journal/2026-01.md"):
        folded = check_tree(_scratch(tmp_path / f"folded-{Path(where).stem}", {frag: MARKED.encode("utf-8"), where: MARKED.encode("utf-8")},
                                     SELF_EXCLUDING + frag + "\n"))
        assert folded["journal_with_marker"] == [where], where
    spelled = check_tree(_scratch(tmp_path / "folded-altered", {frag: MARKED.encode("utf-8"),
                                  "BUILD_JOURNAL.md": b"<!--  PRIVATE:\n  NOT for the public journal -->\n"}, SELF_EXCLUDING + frag + "\n"))
    assert spelled["journal_with_marker"] == ["BUILD_JOURNAL.md"]


def test_toggle_a_fragment_that_is_not_excluded_is_not_asked_for_the_marker(tmp_path: Path) -> None:
    plain = check_tree(_scratch(tmp_path / "public", {f"{FRAGMENT_DIR}2026-10-01_b.md": b"### 2026-10-01 \xe2\x80\x94 T\n"}, SELF_EXCLUDING))
    assert plain["fragments_without_marker"] == []


def test_toggle_a_missing_list_fails_the_check_it_does_not_skip_it(tmp_path: Path) -> None:
    root = tmp_path / "nolist"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "a.md").write_text("x\n")
    _git(root, "add", "--", "a.md")
    with pytest.raises(pytest.fail.Exception):
        check_tree(root)


def test_toggle_git_unavailable_fails_the_check_it_does_not_skip_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if shutil.which("git") is None:  # pragma: no cover - the lock itself needs git to exist at all
        pytest.fail("git is not on PATH")
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(pytest.fail.Exception):
        tracked_entries(REPO_ROOT)


def test_toggle_a_changed_or_dropped_phrase_changes_the_pin() -> None:
    assert phrase_set_digest(PRIVATE_PHRASES[:-1]) != PHRASE_SET_DIGEST
    swapped = PRIVATE_PHRASES[:-1] + ("an unrelated phrase",)
    assert phrase_set_digest(swapped) != PHRASE_SET_DIGEST
    assert phrase_set_digest(reversed(PRIVATE_PHRASES)) == PHRASE_SET_DIGEST


def test_toggle_the_phrase_file_is_read_from_the_index_not_the_working_copy(tmp_path: Path) -> None:
    rel = PHRASES_FILE.relative_to(REPO_ROOT).as_posix()
    root = _scratch(tmp_path / "phrases", {rel: json.dumps({"target": ["x"], "phrases": [["staged"]]}).encode()}, SELF_EXCLUDING)
    (root / rel).write_text(json.dumps({"target": ["x"], "phrases": [["edited"]]}))  # edited, not staged
    assert _phrase_data_from_index(root)["phrases"] == [["staged"]]


def test_toggle_a_list_that_matches_everything_loses_the_anchor_paths(tmp_path: Path) -> None:
    files = {"README.md": b"hello\n", "LICENSE.md": b"terms\n", "docs/a.md": b"x\n"}
    everything = check_tree(_scratch(tmp_path / "everything", files, "*\n"))
    assert everything["anchors_lost"] == ["README.md", "LICENSE.md"] and everything["tree_is_empty"] is True
    narrow = check_tree(_scratch(tmp_path / "narrow", files, SELF_EXCLUDING + "docs/\n"))
    assert narrow["anchors_lost"] == [] and narrow["tree_is_empty"] is False
    readme_gone = check_tree(_scratch(tmp_path / "readme-gone", files, SELF_EXCLUDING + "README.md\n"))
    assert readme_gone["anchors_lost"] == ["README.md"]


@pytest.mark.parametrize("surface", ["LESSONS.md", "FIELD_NOTES.md", "docs/BUILD_JOURNAL_ANTHOLOGY.md", "docs/archive/lessons/LESSONS_ARCHIVE.md",
                                     "docs/archive/anything/else.md", "BUILD_JOURNAL.md", "docs/archive/journal/2026-01.md"])
def test_toggle_the_marker_is_found_on_every_public_journal_and_lesson_surface(tmp_path: Path, surface: str) -> None:
    frag = f"{FRAGMENT_DIR}2026-10-01_a.md"
    root = _scratch(tmp_path / "surface", {frag: MARKED.encode("utf-8"), surface: b"folded: " + MARKED.encode("utf-8")},
                    SELF_EXCLUDING + frag + "\n")
    assert check_tree(root)["journal_with_marker"] == [surface]


@pytest.mark.parametrize("form", ["backslash", "percent"])
def test_toggle_markdown_escape_and_percent_forms_of_every_phrase_are_caught(form: str) -> None:
    needles = tuple(p.lower() for p in PRIVATE_PHRASES)
    esc = lambda t: re.sub(r"([_.&-])", lambda m: chr(92) + m.group(1), t)  # noqa: E731
    for phrase in PRIVATE_PHRASES:
        text = {"backslash": esc(phrase), "percent": phrase.replace(" ", "%20")}[form]
        found, problems = phrases_in(text.encode("utf-8"), needles)
        assert phrase.lower() in found and problems == [], (form, phrase)


def test_toggle_a_list_line_that_reaches_an_anchored_path_is_caught_and_a_clean_list_is_not(tmp_path: Path) -> None:
    files = {ANCHORS_FILE: b"README.md\ndocs/evidence/\ndocs/study.md\n", "README.md": b"r\n", "docs/study.md": b"s\n",
             "docs/evidence/nep0005/run.json": b"{}\n", "docs/evidence/a.json": b"{}\n", "docs/other/x.md": b"x\n"}
    broad = check_tree(_scratch(tmp_path / "broad", files, SELF_EXCLUDING + "**/*nep0005*\n"))
    assert broad["anchored_but_excluded"] == ["docs/evidence/nep0005/run.json"]
    exact = check_tree(_scratch(tmp_path / "exact", files, SELF_EXCLUDING + "docs/study.md\n"))
    assert exact["anchored_but_excluded"] == ["docs/study.md"]
    clean = check_tree(_scratch(tmp_path / "clean", files, SELF_EXCLUDING + "docs/other/\n"))
    assert clean["anchored_but_excluded"] == [] and clean["anchors_naming_nothing"] == []


def test_toggle_an_anchor_that_names_no_tracked_path_is_reported(tmp_path: Path) -> None:
    files = {ANCHORS_FILE: b"README.md\ndocs/gone/\n", "README.md": b"r\n"}
    assert check_tree(_scratch(tmp_path / "stale", files, SELF_EXCLUDING))["anchors_naming_nothing"] == ["docs/gone/"]


def test_toggle_a_path_an_anchored_document_cites_must_be_anchored_or_allowlisted(tmp_path: Path) -> None:
    files = {ANCHORS_FILE: b"README.md\n#:cited-only\ndocs/design/cited.md\n",
             "README.md": b"see docs/design/cited.md and docs/design/other.md and tools/probes/p1/run.py\n",
             "docs/design/cited.md": b"see docs/design/deeper.md\n", "docs/design/other.md": b"o\n", "docs/design/deeper.md": b"d\n",
             "tools/probes/p1/run.py": b"x\n"}
    open_ = check_tree(_scratch(tmp_path / "open", files, SELF_EXCLUDING))
    # cited-only anchors are not scanned in turn, so docs/design/deeper.md is not required
    assert open_["cited_unanchored"] == ["docs/design/other.md", "tools/probes/p1/run.py"]
    held = {**files, CITED_ALLOWLIST_FILE: b"docs/design/other.md | a draft the post does not link\ntools/probes/p1/run.py | the probe is not published\n"}
    ok = check_tree(_scratch(tmp_path / "held", held, SELF_EXCLUDING))
    assert ok["cited_unanchored"] == [] and ok["cited_allowlist_problems"] == []
    anchored = {**files, ANCHORS_FILE: b"README.md\n#:cited-only\ndocs/design/\ntools/probes/p1/\n"}
    assert check_tree(_scratch(tmp_path / "anchored", anchored, SELF_EXCLUDING))["cited_unanchored"] == []


def test_toggle_citations_are_read_from_every_text_file_under_the_anchors_and_not_from_binaries(tmp_path: Path) -> None:
    files = {ANCHORS_FILE: b"README.md\ndocs/ev/\n", "README.md": b"r\n",
             "docs/ev/run.json": b'{"instrument": "tools/probes/arms/effective_access.py"}\n',
             "docs/ev/gate.ps1": b"# see tools/probes/arms/countdown_gate.ps1\n",
             "docs/ev/blob.bin": b"\x00\x01 tools/probes/arms/binary_only.py\n",
             "docs/ev/packed.gz": b"\x1f\x8b tools/probes/arms/packed_only.py\n",
             "tools/probes/arms/effective_access.py": b"x\n", "tools/probes/arms/countdown_gate.ps1": b"x\n",
             "tools/probes/arms/binary_only.py": b"x\n", "tools/probes/arms/packed_only.py": b"x\n"}
    found = check_tree(_scratch(tmp_path / "text", files, SELF_EXCLUDING + "tools/probes/arms/\n"))["cited_unanchored"]
    assert found == ["tools/probes/arms/countdown_gate.ps1", "tools/probes/arms/effective_access.py"]


def test_toggle_a_list_line_that_excludes_a_cited_unanchored_path_is_reported_and_anchoring_it_fails_the_list(tmp_path: Path) -> None:
    files = {ANCHORS_FILE: b"README.md\n", "README.md": b"see docs/adrs/ADR-1.md\n", "docs/adrs/ADR-1.md": b"a\n"}
    cited = check_tree(_scratch(tmp_path / "cited", files, SELF_EXCLUDING + "docs/adrs/*\n"))
    assert cited["cited_unanchored"] == ["docs/adrs/ADR-1.md"]
    with_anchor = {**files, ANCHORS_FILE: b"README.md\n#:cited-only\ndocs/adrs/ADR-1.md\n"}
    covered = check_tree(_scratch(tmp_path / "covered", with_anchor, SELF_EXCLUDING + "docs/adrs/*\n"))
    assert covered["cited_unanchored"] == [] and covered["anchored_but_excluded"] == ["docs/adrs/ADR-1.md"]


def test_toggle_the_citation_reader_takes_files_and_deep_directories_and_leaves_areas_and_prose() -> None:
    tracked = {"a/b/c.md", "x.md", "tools/probes/p1/run.py"}
    dirs = {"a", "a/b", "tools", "tools/probes", "tools/probes/p1"}
    text = "See `a/b/c.md`, (./x.md), tools/probes/p1. Area a/b and a, plus nothing/here.md, docs/gone.md."
    assert citations(text, tracked, dirs) == {"a/b/c.md", "x.md", "tools/probes/p1"}


def test_toggle_the_allowlist_rejects_stale_anchored_unreasoned_and_missing_files(tmp_path: Path) -> None:
    base = {ANCHORS_FILE: b"README.md\n#:cited-only\ndocs/a.md\n", "README.md": b"see docs/a.md and docs/b.md\n",
            "docs/a.md": b"a\n", "docs/b.md": b"b\n", "docs/c.md": b"c\n"}
    bad = {**base, CITED_ALLOWLIST_FILE: b"docs/a.md | anchored already\ndocs/c.md | cited by nobody\ndocs/gone.md | not tracked\ndocs/b.md | cited, fine\n"}
    problems = check_tree(_scratch(tmp_path / "bad", bad, SELF_EXCLUDING))["cited_allowlist_problems"]
    assert problems == ["docs/a.md: anchored, so it needs no allowlist line", "docs/c.md: cited by no scanned document", "docs/gone.md: not tracked"]
    with pytest.raises(pytest.fail.Exception):
        check_tree(_scratch(tmp_path / "noreason", {**base, CITED_ALLOWLIST_FILE: b"docs/b.md\n"}, SELF_EXCLUDING))
    missing = _scratch(tmp_path / "missing", base, SELF_EXCLUDING)
    _git(missing, "rm", "-q", "--cached", "--", CITED_ALLOWLIST_FILE)
    with pytest.raises(pytest.fail.Exception):
        check_tree(missing)


def test_toggle_the_anchor_file_is_read_from_the_index(tmp_path: Path) -> None:
    root = _scratch(tmp_path / "anchors-index", {ANCHORS_FILE: b"README.md\n", "README.md": b"r\n"}, SELF_EXCLUDING)
    (root / ANCHORS_FILE).write_text("docs/nothing/\n")  # edited, not staged
    assert load_anchors(root) == ["README.md"]


def test_toggle_load_phrases_reads_the_index_copy_of_the_root_it_is_given(tmp_path: Path) -> None:
    rel = PHRASES_FILE.relative_to(REPO_ROOT).as_posix()
    staged = {"target": ["x", "y"], "phrases": [["staged", " one"]], "numbering": {"before": [""], "stem": ["s"], "after": [""], "number": "1"}}
    root = _scratch(tmp_path / "load", {rel: json.dumps(staged).encode()}, SELF_EXCLUDING)
    (root / rel).write_text(json.dumps({**staged, "phrases": [["edited", " one"]]}))  # edited, not staged
    target, plain, numbered = _load_phrases(root)
    assert (target, plain, numbered) == ("xy", ("staged one",), ("xys1",))


@pytest.mark.parametrize("form", ["percent upper-case escape", "json upper-case escape"])
def test_toggle_encoded_capital_letters_fold_like_any_other(form: str) -> None:
    needles = tuple(p.lower() for p in PRIVATE_PHRASES)
    phrase = PLAIN_PHRASES[0]
    capital = phrase[0].upper()
    text = {"percent upper-case escape": f"%{ord(capital):02X}" + phrase[1:],
            "json upper-case escape": chr(92) + f"u{ord(capital):04X}" + phrase[1:]}[form]
    found, problems = phrases_in(text.encode("utf-8"), needles)
    assert phrase.lower() in found and problems == []
