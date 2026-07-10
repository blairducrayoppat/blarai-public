"""#746 research substrate (slice 1) — build + load the LOCAL docset index.

Builds a single self-contained SQLite index from the LA-approved, hash-pinned
docset corpus staged at ``models/docsets/`` and persists it to the gitignored
``models/docsets/index/``. ALL input is local disk; this module performs ZERO
network I/O (locked by the repo-wide egress scan in
``tests/security/test_no_external_egress.py`` plus the stricter per-module test
in ``shared/tests/test_research_substrate.py``).

Corpus shape (see ``docs/research/docset-manifest-2026-07.json``):

  * DevDocs docsets — ``devdocs/<slug>/index.json`` (``{"entries": [{name,
    path, type}, ...]}``: the exact-match SYMBOL surface) + ``db.json`` (a JSON
    object mapping page-path -> HTML string: the page-text surface).
  * readthedocs/official zip bundles — ``*.zip`` with ``.html`` members
    (stripped to text) or ``.txt`` members (taken verbatim). Zips carry no
    entry index, so they contribute pages only (searchable, not exact-lookup).

Design decisions taken in this slice (each deliberate):

  * **Manifest-driven build.** The build reads ``MANIFEST.sha256.json`` inside
    the corpus dir and processes ONLY the artifacts it lists, re-verifying
    every SHA-256 pin before parsing (fail-closed: a missing or tampered file
    refuses the whole build). Stray directories in the staging area — e.g. the
    empty ``devdocs/pytest/`` left by the stager (pytest is not on DevDocs) —
    are ignored by construction.
  * **SQLite, plain tables, stdlib only.** No FTS5 (a compile-option
    dependency), no pickle (an arbitrary-code-execution surface on load), no
    new packages. BM25 is implemented locally in ``lookup.py`` over an
    inverted ``postings`` table, so query-time RAM stays flat (b-tree lookups,
    never a full-index load) on the 31.3 GB-ceiling box.
  * **Anchors recorded at strip time.** DevDocs entry paths carry ``#fragment``
    element ids; the HTML stripper records the text offset of each id the
    symbol index needs, so an exact hit excerpts the text at the symbol's
    definition rather than the page head.
  * **Deterministic.** Page ids follow manifest order; postings are written in
    term order with ascending page ids; identical corpus in => identical
    lookup results out (regression-locked).
  * **Atomic persist.** The build writes ``<name>.building`` and
    ``os.replace``s it over the final path, so a reader never sees a partial
    index. (Two simultaneous builders race benignly — last replace wins.)

The corpus itself is NEVER required at query time: page text, titles and
anchors are all embedded in the index file. The corpus (when present) is used
to detect staleness — a re-staged corpus (manifest bytes changed) marks the
index stale and :func:`ensure_index` rebuilds it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / paths
# ---------------------------------------------------------------------------

#: Bump on any schema/tokenizer/ingest change — a version mismatch marks the
#: index stale and :func:`ensure_index` rebuilds from the corpus.
#: v2: readthedocs single-page HTML bundles split into per-section pages.
INDEX_SCHEMA_VERSION = 2

#: Per-page stored-text cap (chars). Generous by design: it guards against
#: pathological pages without truncating real definitional content (the
#: largest real page, python's ``library/stdtypes``, strips to ~360k chars and
#: IS trimmed; the p99 page is far below the cap).
PAGE_TEXT_CAP = 200_000

#: Per-token length cap (defends the postings table against minified junk).
_TOKEN_MAX_LEN = 80

#: Title cap — a title is a label, not a paragraph.
_TITLE_MAX = 160

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS_DIR = _REPO_ROOT / "models" / "docsets"
DEFAULT_INDEX_DIR = DEFAULT_CORPUS_DIR / "index"
INDEX_FILENAME = "docset_index.sqlite3"
CORPUS_MANIFEST_NAME = "MANIFEST.sha256.json"

#: The one sanctioned way to (re)provision the corpus — named in every refusal.
STAGE_SCRIPT = "scripts/stage_docsets.py"

#: Zip members that are site chrome / build residue, not documentation.
_ZIP_SKIP_BASENAMES = frozenset(
    {"genindex.html", "search.html", "searchindex.js", ".buildinfo", "objects.inv"}
)
_ZIP_SKIP_DIR_PARTS = frozenset({"_static", "_images", "_sources", "_downloads"})

#: readthedocs "htmlzip" bundles are SINGLE-page HTML (sphinx singlehtml —
#: the staged pytest bundle is one 4.3 MB page with ~1,200 ``<section id>``
#: elements). Indexed whole, one page would hit the text cap AND destroy
#: retrieval granularity, so zip HTML is split into per-section pages at
#: ``<section id="...">`` boundaries (a linear split — non-overlapping
#: segments in document order; a parent section keeps its preamble, nested
#: sections get their own page). Fragments below this floor carry no
#: standalone value and are FOLDED into the neighboring segment instead of
#: emitted (no text is dropped).
_MIN_SECTION_CHARS = 120

_SECTION_SPLIT_RE = re.compile(r'<section\b[^>]*\bid="([^"]+)"[^>]*>')


# ---------------------------------------------------------------------------
# Errors (all fail-closed)
# ---------------------------------------------------------------------------


class ResearchIndexError(RuntimeError):
    """Base for every research-substrate index failure."""


class CorpusMissingError(ResearchIndexError):
    """The staged docset corpus (or its manifest) is absent — cannot build."""


class CorpusIntegrityError(ResearchIndexError):
    """A staged artifact is missing or fails its SHA-256 pin — refuse to build."""


class IndexNotBuiltError(ResearchIndexError):
    """No persisted index exists at the index path."""


class StaleIndexError(ResearchIndexError):
    """The persisted index no longer matches the corpus manifest or schema."""


def _corpus_missing(detail: str) -> CorpusMissingError:
    return CorpusMissingError(
        f"{detail} — the local docset corpus is not staged. BlarAI research "
        f"retrieval is local-only (zero egress); provision the corpus with "
        f"`python {STAGE_SCRIPT}` (LA-approved pins, #746) and retry."
    )


# ---------------------------------------------------------------------------
# Tokenizer + symbol normalization (SHARED by build and query — must match)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*")


def tokenize(text: str) -> list[str]:
    """Deterministic lexical tokens of *text* (lowercased).

    Dotted identifiers are kept whole AND split into parts — ``json.dumps``
    emits ``json.dumps``, ``json``, ``dumps`` — so a query matches both the
    qualified and bare spellings exactly as the pages were indexed.
    """
    out: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        token = match.group(0)[:_TOKEN_MAX_LEN]
        out.append(token)
        if "." in token:
            out.extend(part for part in token.split(".") if part)
    return out


def normalize_symbol(raw: str) -> str:
    """Normalize a symbol spelling for exact-match lookup.

    Lowercase, whitespace-collapsed, quotes/backticks trimmed, one trailing
    ``()`` and trailing ``:``/``.`` dropped — so ``json.dumps()``,
    ``JSON.DUMPS`` and ``json.dumps:`` all resolve to ``json.dumps``. This is
    spelling normalization only, never fuzzy matching.
    """
    text = " ".join(str(raw).split()).strip().strip("'\"`").strip()
    if text.endswith("()"):
        text = text[:-2]
    return text.rstrip(":.").lower()


# ---------------------------------------------------------------------------
# HTML -> text stripping (stdlib HTMLParser; records anchors + titles)
# ---------------------------------------------------------------------------

_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "math"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "section", "article", "aside", "li", "ul", "ol", "table",
        "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "dt",
        "dd", "dl", "br", "hr", "header", "footer", "nav", "figure",
        "figcaption", "details", "summary",
    }
)


class _TextExtractor(HTMLParser):
    """Strip HTML to whitespace-normalized text, recording the text offset of
    every ``id`` attribute in *wanted_ids* (the fragments the symbol index
    points at) plus the first ``<h1>`` and ``<title>`` for titling."""

    def __init__(self, wanted_ids: frozenset[str], cap: int) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._len = 0
        self._cap = cap
        self._skip_depth = 0
        self._pre_depth = 0
        self._wanted = wanted_ids
        self.anchors: dict[str, int] = {}
        self._h1_parts: list[str] = []
        self._h1_active = False
        self._h1_done = False
        self._title_parts: list[str] = []
        self._title_active = False
        self._title_done = False
        self._heading_parts: list[str] = []
        self._heading_active = False
        self._heading_done = False

    # -- emission ----------------------------------------------------------

    def _emit(self, piece: str) -> None:
        if not piece or self._len >= self._cap:
            return
        room = self._cap - self._len
        piece = piece[:room]
        self._parts.append(piece)
        self._len += len(piece)

    def _separator(self, sep: str) -> None:
        if self._len == 0 or self._len >= self._cap:
            return
        last = self._parts[-1][-1]
        if last in (" ", "\n"):
            if sep == "\n" and last == " ":
                # Upgrade a pending space to a block break (length unchanged).
                self._parts[-1] = self._parts[-1][:-1] + "\n"
            return
        self._emit(sep)

    # -- parser hooks --------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._separator("\n")
        if tag == "pre":
            self._pre_depth += 1
        if self._wanted:
            elem_id = next((v for k, v in attrs if k == "id" and v), None)
            if elem_id and elem_id in self._wanted and elem_id not in self.anchors:
                if self._len < self._cap:
                    self.anchors[elem_id] = self._len
        if tag == "h1" and not self._h1_done:
            self._h1_active = True
        elif tag == "title" and not self._title_done:
            self._title_active = True
        if tag in _HEADING_TAGS and not self._heading_done:
            self._heading_active = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            return
        if tag in _BLOCK_TAGS:
            self._separator("\n")
        if self._wanted:
            elem_id = next((v for k, v in attrs if k == "id" and v), None)
            if elem_id and elem_id in self._wanted and elem_id not in self.anchors:
                if self._len < self._cap:
                    self.anchors[elem_id] = self._len

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "pre":
            self._pre_depth = max(0, self._pre_depth - 1)
        if tag in _BLOCK_TAGS:
            self._separator("\n")
        if tag == "h1" and self._h1_active:
            self._h1_active = False
            self._h1_done = True
        elif tag == "title" and self._title_active:
            self._title_active = False
            self._title_done = True
        if tag in _HEADING_TAGS and self._heading_active:
            self._heading_active = False
            self._heading_done = True

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._h1_active:
            self._h1_parts.append(data)
        if self._title_active:
            self._title_parts.append(data)
        if self._heading_active:
            self._heading_parts.append(data)
        if self._pre_depth:
            self._emit(data.replace("\r", ""))
            return
        collapsed = " ".join(data.split())
        if collapsed:
            if data[:1].isspace():
                self._separator(" ")
            self._emit(collapsed)
            if data[-1:].isspace():
                self._separator(" ")
        elif data:
            self._separator(" ")

    # -- results -------------------------------------------------------------

    @property
    def text(self) -> str:
        return "".join(self._parts)

    @staticmethod
    def _heading_clean(parts: list[str]) -> str:
        # Sphinx headings end in a "¶" headerlink glyph — not part of a title.
        return " ".join("".join(parts).split()).rstrip(" ¶")[:_TITLE_MAX]

    @property
    def h1_text(self) -> str:
        return self._heading_clean(self._h1_parts)

    @property
    def title_text(self) -> str:
        return self._heading_clean(self._title_parts)

    @property
    def first_heading(self) -> str:
        """Text of the FIRST heading (h1-h6) — titles section fragments whose
        top heading is an h2/h3 rather than an h1."""
        return self._heading_clean(self._heading_parts)


def strip_html(
    html_text: str, *, wanted_ids: frozenset[str] = frozenset(), cap: int | None = None
) -> _TextExtractor:
    """Strip *html_text*; returns the extractor carrying text/anchors/titles.

    Fail-soft: a malformed document yields whatever text was extracted before
    the parser gave up (HTMLParser is non-raising by design)."""
    extractor = _TextExtractor(wanted_ids, cap if cap is not None else PAGE_TEXT_CAP)
    extractor.feed(html_text)
    extractor.close()
    return extractor


# ---------------------------------------------------------------------------
# Manifest reading + integrity verification
# ---------------------------------------------------------------------------


def _read_manifest(corpus_dir: Path) -> tuple[list[dict[str, object]], str]:
    """Load the corpus manifest; returns (artifacts, sha256-of-manifest-bytes).

    Raises :class:`CorpusMissingError` when the corpus dir or manifest is
    absent — the message names :data:`STAGE_SCRIPT` (the ticket's refusal
    contract)."""
    if not corpus_dir.is_dir():
        raise _corpus_missing(f"corpus dir {corpus_dir} does not exist")
    manifest_path = corpus_dir / CORPUS_MANIFEST_NAME
    if not manifest_path.is_file():
        raise _corpus_missing(f"corpus manifest {manifest_path} does not exist")
    raw = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(raw).hexdigest()
    try:
        manifest = json.loads(raw.decode("utf-8"))
        artifacts = manifest["artifacts"]
        if not isinstance(artifacts, list) or not artifacts:
            raise KeyError("artifacts")
    except (ValueError, KeyError, TypeError) as exc:
        raise CorpusIntegrityError(
            f"corpus manifest {manifest_path} is unreadable or empty ({exc!r}); "
            f"re-stage with `python {STAGE_SCRIPT}`."
        ) from exc
    return artifacts, manifest_sha


def _verify_artifact(corpus_dir: Path, artifact: dict[str, object]) -> Path:
    """SHA-256-verify one manifest artifact; returns its resolved path.

    Fail-closed: a missing file or a hash mismatch refuses the build — the
    pinned corpus is the trust root for everything this index feeds into
    fleet prompts."""
    rel = str(artifact.get("file", ""))
    expected = str(artifact.get("sha256", ""))
    path = corpus_dir / rel
    if not rel or not expected:
        raise CorpusIntegrityError(
            f"manifest artifact {artifact.get('name', '?')!r} lacks file/sha256 "
            f"pins; re-stage with `python {STAGE_SCRIPT}`."
        )
    if not path.is_file():
        raise CorpusIntegrityError(
            f"staged artifact missing: {path} (manifest {artifact.get('name')!r}); "
            f"re-stage with `python {STAGE_SCRIPT}`."
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise CorpusIntegrityError(
            f"SHA-256 mismatch for {path}: manifest pins {expected}, file is "
            f"{actual}. The staged corpus does not match its recorded pins — "
            f"refusing to index it. Re-stage with `python {STAGE_SCRIPT}`."
        )
    return path


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildStats:
    """Community-grade record of one index build."""

    index_path: Path
    index_bytes: int
    n_pages: int
    n_symbols: int
    n_terms: int
    n_postings: int
    avgdl: float
    build_seconds: float
    per_source_pages: dict[str, int]


class _Builder:
    """Accumulates pages/symbols/postings during one build (single-use)."""

    def __init__(self) -> None:
        self.pages: list[tuple[int, str, str, str, str, int, str]] = []
        self.symbols: list[tuple[str, str, str, str, str, int, str]] = []
        self.postings: dict[str, list[str]] = {}
        self.n_postings = 0
        self._next_pid = 1

    def add_page(
        self, source: str, path: str, title: str, text: str, anchors: dict[str, int]
    ) -> int:
        pid = self._next_pid
        self._next_pid += 1
        counts = Counter(tokenize(text))
        doc_len = sum(counts.values())
        for term in counts:
            self.postings.setdefault(term, []).append(f"{pid}:{counts[term]}")
        self.n_postings += len(counts)
        anchors_json = json.dumps(anchors, sort_keys=True, separators=(",", ":"))
        self.pages.append(
            (pid, source, title[:_TITLE_MAX], path, text, doc_len, anchors_json)
        )
        return pid

    def add_symbol(
        self, source: str, name: str, kind: str, path: str, pid: int, frag: str
    ) -> None:
        norm = normalize_symbol(name)
        if norm:
            self.symbols.append((norm, name[:_TITLE_MAX], source, kind, path, pid, frag))


def _ingest_devdocs(builder: _Builder, slug: str, index_path: Path, db_path: Path) -> int:
    """Ingest one DevDocs docset: db.json pages + index.json symbol entries."""
    with index_path.open(encoding="utf-8") as handle:
        entries_raw = json.load(handle).get("entries", [])
    with db_path.open(encoding="utf-8") as handle:
        db: dict[str, str] = json.load(handle)

    # Group entries per page path; collect the fragments each page must anchor.
    entries_by_page: dict[str, list[tuple[str, str, str, str]]] = {}
    wanted_ids: dict[str, set[str]] = {}
    bare_names: dict[str, str] = {}
    for entry in entries_raw:
        name = str(entry.get("name", "")).strip()
        full_path = str(entry.get("path", "")).strip()
        kind = str(entry.get("type", "")).strip()
        if not name or not full_path:
            continue
        page_path, _, frag = full_path.partition("#")
        entries_by_page.setdefault(page_path, []).append((name, kind, full_path, frag))
        if frag:
            wanted_ids.setdefault(page_path, set()).add(frag)
        else:
            bare_names.setdefault(page_path, name)

    n_pages = 0
    for page_path, html_text in db.items():
        extractor = strip_html(
            str(html_text),
            wanted_ids=frozenset(wanted_ids.get(page_path, ())),
            cap=PAGE_TEXT_CAP,
        )
        title = (
            extractor.h1_text
            or extractor.title_text
            or bare_names.get(page_path, "")
            or page_path
        )
        pid = builder.add_page(slug, page_path, title, extractor.text, extractor.anchors)
        n_pages += 1
        for name, kind, full_path, frag in entries_by_page.get(page_path, ()):
            builder.add_symbol(slug, name, kind, full_path, pid, frag)
    # Entries pointing at pages absent from db.json are dangling — skipped
    # (counted implicitly: symbols only ever attach to ingested pages).
    return n_pages


def _split_html_sections(html_text: str) -> list[tuple[str, str]]:
    """Linear split of *html_text* at ``<section id="...">`` boundaries.

    Returns ``[(section_id, html_fragment), ...]`` in document order; the
    fragment before the first section carries id ``""``. A document with no
    sections returns a single ``("", whole)`` — the caller indexes it as one
    page (which is why the FIXTURE-sized multi-file bundles are unaffected)."""
    pieces = _SECTION_SPLIT_RE.split(html_text)
    out: list[tuple[str, str]] = [("", pieces[0])]
    for i in range(1, len(pieces), 2):
        out.append((pieces[i], pieces[i + 1]))
    return out


def _ingest_zip_html(
    builder: _Builder, source: str, member: str, raw_html: str, basename: str
) -> int:
    """Index one zip HTML member, section-split with small-fragment folding.

    Fragments stripping to fewer than ``_MIN_SECTION_CHARS`` chars are folded
    into the previous emitted page (or forward into the next one when nothing
    was emitted yet) — granularity without dropping text."""
    segments = _split_html_sections(raw_html)
    if len(segments) == 1:
        extractor = strip_html(raw_html, cap=PAGE_TEXT_CAP)
        title = extractor.h1_text or extractor.title_text or basename
        if not extractor.text.strip():
            return 0
        builder.add_page(source, member, title, extractor.text, {})
        return 1

    emitted: list[tuple[str, str, str]] = []  # (path, title, text)
    pending_prefix = ""
    for section_id, fragment in segments:
        extractor = strip_html(fragment, cap=PAGE_TEXT_CAP)
        text = extractor.text.strip()
        if not text:
            continue
        if len(text) < _MIN_SECTION_CHARS:
            if emitted:
                path, title, prev_text = emitted[-1]
                emitted[-1] = (path, title, (prev_text + "\n" + text)[:PAGE_TEXT_CAP])
            else:
                pending_prefix = (pending_prefix + "\n" + text).strip()
            continue
        if pending_prefix:
            text = (pending_prefix + "\n" + text)[:PAGE_TEXT_CAP]
            pending_prefix = ""
        title = (
            extractor.first_heading
            or (section_id.replace("-", " ").replace("_", " ").strip() if section_id else "")
            or basename
        )
        path = f"{member}#{section_id}" if section_id else member
        emitted.append((path, title[:_TITLE_MAX], text))
    if pending_prefix:  # every fragment was tiny — keep the text as one page
        emitted.append((member, basename, pending_prefix[:PAGE_TEXT_CAP]))
    for path, title, text in emitted:
        builder.add_page(source, path, title, text, {})
    return len(emitted)


def _ingest_zip(builder: _Builder, source: str, zip_path: Path) -> int:
    """Ingest a readthedocs/official zip: ``.html`` stripped (section-split —
    the readthedocs "htmlzip" is ONE giant sphinx-singlehtml page), ``.txt``
    verbatim. Site chrome (genindex/search/_static/...) is skipped; zips carry
    no entry index so they contribute searchable pages only."""
    n_pages = 0
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            if member.endswith("/"):
                continue
            parts = member.split("/")
            if any(part in _ZIP_SKIP_DIR_PARTS for part in parts):
                continue
            basename = parts[-1]
            if basename in _ZIP_SKIP_BASENAMES:
                continue
            lower = basename.lower()
            if lower.endswith((".html", ".htm")):
                raw = archive.read(member).decode("utf-8", errors="replace")
                n_pages += _ingest_zip_html(builder, source, member, raw, basename)
            elif lower.endswith(".txt"):
                text = (
                    archive.read(member)
                    .decode("utf-8", errors="replace")
                    .replace("\r", "")[:PAGE_TEXT_CAP]
                )
                if not text.strip():
                    continue
                first_line = next(
                    (line.strip() for line in text.splitlines() if line.strip()), ""
                )
                builder.add_page(
                    source, member, first_line[:_TITLE_MAX] or basename, text, {}
                )
                n_pages += 1
    return n_pages


def build_index(
    corpus_dir: Path | None = None, index_dir: Path | None = None
) -> BuildStats:
    """Build the docset index from the staged corpus and persist it atomically.

    Refuses (raises) when the corpus dir/manifest is absent
    (:class:`CorpusMissingError`, naming ``scripts/stage_docsets.py``) or when
    any artifact fails its SHA-256 pin (:class:`CorpusIntegrityError`). ZERO
    network I/O — every byte read comes from local disk.
    """
    corpus = Path(corpus_dir) if corpus_dir is not None else DEFAULT_CORPUS_DIR
    out_dir = Path(index_dir) if index_dir is not None else DEFAULT_INDEX_DIR
    started = time.perf_counter()

    artifacts, manifest_sha = _read_manifest(corpus)
    verified: dict[str, Path] = {}
    for artifact in artifacts:
        verified[str(artifact.get("file", ""))] = _verify_artifact(corpus, artifact)

    builder = _Builder()
    per_source: dict[str, int] = {}
    for artifact in artifacts:  # manifest order => deterministic page ids
        rel = str(artifact.get("file", ""))
        name = str(artifact.get("name", rel))
        path = verified[rel]
        if rel.startswith("devdocs/") and rel.endswith("/db.json"):
            slug = rel.split("/")[1]
            index_json = corpus / "devdocs" / slug / "index.json"
            if f"devdocs/{slug}/index.json" not in verified:
                raise CorpusIntegrityError(
                    f"devdocs docset {slug!r} has db.json but no manifest-pinned "
                    f"index.json; re-stage with `python {STAGE_SCRIPT}`."
                )
            per_source[slug] = _ingest_devdocs(builder, slug, index_json, path)
        elif rel.endswith(".zip"):
            per_source[name] = _ingest_zip(builder, name, path)
        # index.json artifacts are consumed alongside their db.json; anything
        # else in the manifest is ignored (manifest-driven, fail-safe).

    if not builder.pages:
        raise CorpusIntegrityError(
            f"corpus at {corpus} produced zero pages — nothing to index; "
            f"re-stage with `python {STAGE_SCRIPT}`."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = out_dir / INDEX_FILENAME
    tmp_path = out_dir / (INDEX_FILENAME + ".building")
    if tmp_path.exists():
        tmp_path.unlink()

    n_tokens_total = sum(row[5] for row in builder.pages)
    avgdl = n_tokens_total / len(builder.pages)

    con = sqlite3.connect(tmp_path)
    try:
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        con.execute(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        con.execute(
            "CREATE TABLE pages (pid INTEGER PRIMARY KEY, source TEXT NOT NULL,"
            " title TEXT NOT NULL, path TEXT NOT NULL, text TEXT NOT NULL,"
            " dl INTEGER NOT NULL, anchors TEXT NOT NULL)"
        )
        con.execute(
            "CREATE TABLE symbols (norm TEXT NOT NULL, name TEXT NOT NULL,"
            " source TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL,"
            " pid INTEGER NOT NULL, frag TEXT NOT NULL)"
        )
        con.execute(
            "CREATE TABLE postings (term TEXT PRIMARY KEY, df INTEGER NOT NULL,"
            " entries TEXT NOT NULL)"
        )
        con.executemany(
            "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?)", builder.pages
        )
        con.executemany(
            "INSERT INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?)",
            sorted(builder.symbols),
        )
        con.executemany(
            "INSERT INTO postings VALUES (?, ?, ?)",
            (
                (term, len(plist), ",".join(plist))
                for term, plist in sorted(builder.postings.items())
            ),
        )
        con.execute("CREATE INDEX ix_symbols_norm ON symbols (norm)")
        build_seconds = time.perf_counter() - started
        meta_rows = [
            ("schema_version", str(INDEX_SCHEMA_VERSION)),
            ("manifest_sha256", manifest_sha),
            ("built_utc", datetime.now(timezone.utc).isoformat()),
            ("n_pages", str(len(builder.pages))),
            ("avgdl", repr(avgdl)),
            ("build_seconds", f"{build_seconds:.2f}"),
            ("per_source_pages", json.dumps(per_source, sort_keys=True)),
        ]
        con.executemany("INSERT INTO meta VALUES (?, ?)", meta_rows)
        con.commit()
    finally:
        con.close()
    os.replace(tmp_path, final_path)

    stats = BuildStats(
        index_path=final_path,
        index_bytes=final_path.stat().st_size,
        n_pages=len(builder.pages),
        n_symbols=len(builder.symbols),
        n_terms=len(builder.postings),
        n_postings=builder.n_postings,
        avgdl=avgdl,
        build_seconds=time.perf_counter() - started,
        per_source_pages=dict(sorted(per_source.items())),
    )
    logger.info(
        "docset index built: %d pages, %d symbols, %d terms, %.1f MB in %.1fs -> %s",
        stats.n_pages, stats.n_symbols, stats.n_terms,
        stats.index_bytes / 1e6, stats.build_seconds, final_path,
    )
    return stats


# ---------------------------------------------------------------------------
# Load / query primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolRow:
    """One exact-match symbol entry (from a DevDocs index.json)."""

    norm: str
    name: str
    source: str
    kind: str
    path: str
    pid: int
    frag: str


@dataclass(frozen=True)
class PageRow:
    """One stored page (text + anchors embedded — corpus not needed at query)."""

    pid: int
    source: str
    title: str
    path: str
    text: str
    dl: int
    anchors: dict[str, int]


class DocsetIndex:
    """Read-only handle over the persisted index (thread-safe via a lock).

    Exposes the data primitives ``lookup.py`` ranks over: symbol rows, term
    postings/df, page rows, and the collection stats (N, avgdl). Holds page
    LENGTHS in RAM (~10k ints); page TEXT stays on disk until asked for.
    """

    def __init__(self, path: Path, con: sqlite3.Connection) -> None:
        self._path = path
        self._con = con
        self._lock = threading.Lock()
        with self._lock:
            meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
            self._doc_lengths: dict[int, int] = dict(
                con.execute("SELECT pid, dl FROM pages").fetchall()
            )
        self.schema_version = int(meta.get("schema_version", "0"))
        self.manifest_sha256 = str(meta.get("manifest_sha256", ""))
        self.n_pages = len(self._doc_lengths)
        self.avgdl = float(meta.get("avgdl", "0") or 0.0) or max(
            1.0, sum(self._doc_lengths.values()) / max(1, self.n_pages)
        )

    @property
    def path(self) -> Path:
        return self._path

    def doc_length(self, pid: int) -> int:
        return self._doc_lengths.get(pid, 0)

    def symbol_rows(self, norm: str) -> list[SymbolRow]:
        """Exact-match rows for a normalized symbol (deterministic order)."""
        with self._lock:
            rows = self._con.execute(
                "SELECT norm, name, source, kind, path, pid, frag FROM symbols"
                " WHERE norm = ? ORDER BY source, path, name",
                (norm,),
            ).fetchall()
        return [SymbolRow(*row) for row in rows]

    def df(self, term: str) -> int:
        with self._lock:
            row = self._con.execute(
                "SELECT df FROM postings WHERE term = ?", (term,)
            ).fetchone()
        return int(row[0]) if row else 0

    def postings(self, term: str) -> list[tuple[int, int]]:
        """``[(pid, tf), ...]`` for *term*, ascending pid; ``[]`` when unknown."""
        with self._lock:
            row = self._con.execute(
                "SELECT entries FROM postings WHERE term = ?", (term,)
            ).fetchone()
        if not row or not row[0]:
            return []
        out: list[tuple[int, int]] = []
        for pair in row[0].split(","):
            pid_str, _, tf_str = pair.partition(":")
            out.append((int(pid_str), int(tf_str)))
        return out

    def page(self, pid: int) -> PageRow | None:
        with self._lock:
            row = self._con.execute(
                "SELECT pid, source, title, path, text, dl, anchors FROM pages"
                " WHERE pid = ?",
                (pid,),
            ).fetchone()
        if row is None:
            return None
        try:
            anchors = {str(k): int(v) for k, v in json.loads(row[6]).items()}
        except (ValueError, TypeError, AttributeError):
            anchors = {}
        return PageRow(row[0], row[1], row[2], row[3], row[4], row[5], anchors)

    def page_by_path(self, source: str, path: str) -> PageRow | None:
        """The page at (*source*, *path*), or ``None`` — the by-name twin of
        :meth:`page` (page paths are unique within a source)."""
        with self._lock:
            row = self._con.execute(
                "SELECT pid FROM pages WHERE source = ? AND path = ?"
                " ORDER BY pid LIMIT 1",
                (source, path),
            ).fetchone()
        return self.page(int(row[0])) if row else None

    def close(self) -> None:
        with self._lock:
            self._con.close()

    def __enter__(self) -> "DocsetIndex":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _current_manifest_sha(corpus_dir: Path) -> str | None:
    manifest_path = corpus_dir / CORPUS_MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _sqlite_ro_uri(path: Path) -> str:
    """Read-only sqlite URI for *path*, escaping the characters that would
    corrupt URI parsing (%, #, ?, space) — NOT urllib (see the zero-egress
    lock: this package imports no urllib at all)."""
    text = path.as_posix()
    for char in ("%", "#", "?", " "):
        text = text.replace(char, f"%{ord(char):02X}")
    return f"file:{text}?mode=ro"


def load_index(
    index_dir: Path | None = None, corpus_dir: Path | None = None
) -> DocsetIndex:
    """Open the persisted index read-only.

    Raises :class:`IndexNotBuiltError` when no index file exists, and
    :class:`StaleIndexError` when its schema version differs from the code or
    (when the corpus is present) its recorded manifest hash no longer matches
    the staged manifest — a re-staged corpus invalidates the derived index.
    The index is self-contained, so a present index with an ABSENT corpus
    still loads (retrieval keeps working; staleness simply can't be checked).
    """
    out_dir = Path(index_dir) if index_dir is not None else DEFAULT_INDEX_DIR
    corpus = Path(corpus_dir) if corpus_dir is not None else DEFAULT_CORPUS_DIR
    path = out_dir / INDEX_FILENAME
    if not path.is_file():
        raise IndexNotBuiltError(
            f"no docset index at {path}; build one with "
            f"shared.research.docset_index.build_index() (corpus staged by "
            f"`python {STAGE_SCRIPT}`)."
        )
    con = sqlite3.connect(_sqlite_ro_uri(path), uri=True, check_same_thread=False)
    try:
        index = DocsetIndex(path, con)
    except sqlite3.Error as exc:
        con.close()
        raise StaleIndexError(f"index at {path} is unreadable: {exc}") from exc
    if index.schema_version != INDEX_SCHEMA_VERSION:
        index.close()
        raise StaleIndexError(
            f"index schema v{index.schema_version} != code v{INDEX_SCHEMA_VERSION}"
            f" — rebuild via ensure_index()."
        )
    current_sha = _current_manifest_sha(corpus)
    if current_sha is not None and current_sha != index.manifest_sha256:
        index.close()
        raise StaleIndexError(
            f"index at {path} was built from a different corpus manifest — "
            f"the staged corpus changed; rebuild via ensure_index()."
        )
    return index


def ensure_index(
    index_dir: Path | None = None, corpus_dir: Path | None = None
) -> DocsetIndex:
    """Load the index, building it from the staged corpus when missing/stale.

    The one-time build takes tens of seconds on the full corpus (logged);
    every later call loads instantly. Corpus absent AND no usable index =>
    :class:`CorpusMissingError` naming ``scripts/stage_docsets.py``.
    """
    try:
        return load_index(index_dir=index_dir, corpus_dir=corpus_dir)
    except (IndexNotBuiltError, StaleIndexError) as exc:
        logger.info("docset index unavailable (%s); building from corpus", exc)
    build_index(corpus_dir=corpus_dir, index_dir=index_dir)
    return load_index(index_dir=index_dir, corpus_dir=corpus_dir)
