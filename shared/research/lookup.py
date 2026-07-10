"""#746 research substrate (slice 1) — deterministic-first local doc lookup.

The reactive research point for the coding fleet: a coder (or the plan
grounder) calls this ON A NAMED GAP — an unknown symbol, an exact error line,
a concrete question. PULL not PUSH: nothing here fires unprompted.

Deterministic-first ladder (the #746 golden rule):

  1. :func:`exact_lookup` — exact-match against the DevDocs symbol index.
     No model, no fuzz: the input (or a dotted-identifier token inside it,
     e.g. the exception name in an error line) either resolves exactly or it
     does not.
  2. :func:`search_docs` — only then, ranked lexical retrieval: a locally
     implemented BM25 (Robertson/Okapi weighting, pure Python, no new deps)
     over the page store. Scores are normalized by the query's maximum
     achievable BM25 mass, so every score lives in (0, 1] and the module-level
     :data:`RELEVANCE_FLOOR` is a stable gate — **nothing above the floor
     means the corpus holds no high-value answer: STOP, return ``[]``** (the
     caller moves on instead of ingesting noise).
  3. :func:`semantic_rerank` — a NAMED SEAM for the follow-up slice, today a
     deterministic identity pass (see its docstring).

Zero egress: every byte read comes from the local index file. Excerpts are
control-stripped, whitespace-collapsed and hard-capped before they can ride
into any prompt (mirrors ``shared/fleet/context_pack.py`` token hygiene).

Failure posture: these coder-facing calls PROPAGATE
:class:`~shared.research.docset_index.CorpusMissingError` (a loud miss naming
``scripts/stage_docsets.py``) rather than silently returning ``[]`` — a
missing corpus is an operator problem, not a "no results" answer. The
plan-grounding wrapper (``plan_grounding.ground_goal``) is the one
degrade-gracefully consumer and catches it there.
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass

from shared.research.docset_index import (
    DocsetIndex,
    PageRow,
    ensure_index,
    normalize_symbol,
    tokenize,
)

# ---------------------------------------------------------------------------
# Tunables (module-level by contract — tests and callers may read/patch them)
# ---------------------------------------------------------------------------

#: The STOP gate: a normalized score below this returns nothing at all.
#: CALIBRATED on the real 2026-07 corpus (13,803 pages), 2026-07-06: real
#: queries put their top hit at 0.47-0.91 (worst measured: "how to parse iso
#: 8601 datetime string python" -> 0.485/0.466); junk tops out at 0.26
#: ("purple elephant birthday cake recipe" -> 0.264 — off-corpus English
#: colliding with MDN example prose — is the class this floor must stop;
#: gibberish -> 0.14; one real term drowned in seven unknowns -> 0.02).
#: 0.35 keeps every measured real answer and stops every measured junk class.
RELEVANCE_FLOOR = 0.35

#: Hard cap on every excerpt that can ride into a prompt.
EXCERPT_MAX_CHARS = 800

#: BM25 parameters (standard Robertson defaults).
_BM25_K1 = 1.5
_BM25_B = 0.75

#: Bounded attempts: at most this many unique query terms are scored.
_MAX_QUERY_TERMS = 24
#: Bounded attempts: at most this many exact hits are returned.
_EXACT_MAX_HITS = 8
#: At most this many candidate tokens are tried in the error-text fallback.
_EXACT_MAX_TOKENS = 8
#: Query text longer than this is truncated before tokenizing (an error dump
#: is useful; a megabyte of log is not a query).
_MAX_QUERY_CHARS = 2000

#: Score tiers for exact hits (definitionally relevant, always above floor).
_EXACT_SCORE = 1.0
_EXACT_TOKEN_SCORE = 0.9

#: Sources that duplicate one another's content (the official python text
#: archive mirrors the DevDocs python docset). When two hits share a
#: normalized title across a group, only the better-scored one is returned.
_DUP_SOURCE_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"python~3.11", "python-3.11-official-text"}),
)

#: Dotted-identifier extractor for the error-text exact fallback:
#: ``json.decoder.JSONDecodeError`` out of a traceback line, ``ValueError``
#: out of an error message. Deterministic, no fuzz.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")

#: Characters stripped from anything that can enter a prompt: ASCII controls
#: PLUS Unicode format/direction controls (zero-widths, bidi embeddings and
#: isolates — the trojan-source class; MDN pages really do carry U+2068/2069
#: around inline code) and the BOM. Excerpts must be visually unambiguous.
_PROMPT_UNSAFE_RANGES: tuple[tuple[int, int], ...] = (
    (0x00, 0x08), (0x0B, 0x0C), (0x0E, 0x1F), (0x7F, 0x7F),  # ASCII controls
    (0x200B, 0x200F),  # zero-widths + LRM/RLM
    (0x2028, 0x2029),  # line/paragraph separators
    (0x202A, 0x202E),  # bidi embeddings/overrides
    (0x2060, 0x2069),  # word joiner + invisibles + bidi isolates
    (0xFEFF, 0xFEFF),  # BOM / zero-width no-break space
)
_CTRL_RE = re.compile(
    "[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _PROMPT_UNSAFE_RANGES) + "]"
)


@dataclass(frozen=True)
class DocHit:
    """One retrieval result. ``score`` is 1.0/0.9 for exact tiers, else the
    floor-gated normalized BM25 score in (0, 1]. ``excerpt`` is prompt-safe:
    control-stripped, single-line, <= :data:`EXCERPT_MAX_CHARS`."""

    source: str
    title: str
    path: str
    score: float
    excerpt: str


# ---------------------------------------------------------------------------
# Default index (lazy, process-wide; tests inject their own via ``index=``)
# ---------------------------------------------------------------------------

_default_index_lock = threading.Lock()
_default_index: DocsetIndex | None = None


def _get_index(index: DocsetIndex | None) -> DocsetIndex:
    global _default_index
    if index is not None:
        return index
    with _default_index_lock:
        if _default_index is None:
            _default_index = ensure_index()
        return _default_index


def reset_default_index() -> None:
    """Drop the process-wide index handle (next call re-opens it)."""
    global _default_index
    with _default_index_lock:
        if _default_index is not None:
            _default_index.close()
            _default_index = None


# ---------------------------------------------------------------------------
# Excerpting (prompt hygiene lives HERE, on the emit path)
# ---------------------------------------------------------------------------


def _clean_snippet(raw: str, *, prefix_ellipsis: bool) -> str:
    """Single-line, control-stripped, capped snippet (the only shape an
    excerpt may take on its way into a prompt)."""
    text = " ".join(_CTRL_RE.sub(" ", raw).split())
    if prefix_ellipsis and text:
        text = "… " + text
    return text[:EXCERPT_MAX_CHARS]


def _excerpt_at(text: str, offset: int) -> str:
    """Excerpt starting at a recorded anchor offset (exact-hit path)."""
    start = max(0, min(offset, len(text)))
    window = text[start : start + EXCERPT_MAX_CHARS * 2]
    return _clean_snippet(window, prefix_ellipsis=start > 0)


def _excerpt_around_terms(text: str, terms: list[str]) -> str:
    """Excerpt windowed at the EARLIEST occurrence of any query term (>= 3
    chars), falling back to the page head. Deterministic by construction."""
    lowered = text.lower()
    best = -1
    for term in terms:
        if len(term) < 3:
            continue
        pos = lowered.find(term)
        if pos >= 0 and (best < 0 or pos < best):
            best = pos
    if best < 0:
        return _clean_snippet(text[: EXCERPT_MAX_CHARS * 2], prefix_ellipsis=False)
    start = max(0, best - 160)
    if start > 0:
        space = text.find(" ", start, start + 40)
        if space >= 0:
            start = space + 1
    window = text[start : start + EXCERPT_MAX_CHARS * 2]
    return _clean_snippet(window, prefix_ellipsis=start > 0)


def _clean_title(raw: str) -> str:
    return " ".join(_CTRL_RE.sub(" ", raw).split())[:160]


# ---------------------------------------------------------------------------
# 1. exact_lookup — deterministic, no model, no fuzz
# ---------------------------------------------------------------------------


def exact_lookup(
    symbol_or_error: str, *, index: DocsetIndex | None = None
) -> list[DocHit]:
    """Exact-match lookup of a symbol or an error line. Deterministic-FIRST.

    Ladder (stops at the first rung that yields hits):

      1. the whole input, spelling-normalized (``json.dumps()`` ->
         ``json.dumps``), against the symbol index — score 1.0;
      2. dotted-identifier tokens extracted from the input (longest first,
         at most ``_EXACT_MAX_TOKENS`` tried — bounded attempts), each matched
         EXACTLY — score 0.9. This is what resolves an error line like
         ``json.decoder.JSONDecodeError: Expecting value`` to its symbol.

    No rung matches => ``[]`` (the caller falls through to
    :func:`search_docs`). Results are deterministic: stable ordering by
    (score desc, source, path, title), capped at ``_EXACT_MAX_HITS``.
    """
    text = str(symbol_or_error or "")[:_MAX_QUERY_CHARS]
    if not text.strip():
        return []
    idx = _get_index(index)

    hits: list[tuple[float, str, str, str, DocHit]] = []
    seen: set[tuple[str, str]] = set()

    def _add(rows: list, score: float) -> None:
        for row in rows:
            key = (row.source, row.path)
            if key in seen:
                continue
            seen.add(key)
            excerpt = ""
            page = idx.page(row.pid)
            if page is not None:
                offset = page.anchors.get(row.frag) if row.frag else None
                if offset is not None:
                    excerpt = _excerpt_at(page.text, offset)
                else:
                    excerpt = _clean_snippet(
                        page.text[: EXCERPT_MAX_CHARS * 2], prefix_ellipsis=False
                    )
            hits.append(
                (
                    score,
                    row.source,
                    row.path,
                    row.name,
                    DocHit(
                        source=row.source,
                        title=_clean_title(row.name),
                        path=row.path,
                        score=score,
                        excerpt=excerpt,
                    ),
                )
            )

    whole = normalize_symbol(text)
    if whole:
        _add(idx.symbol_rows(whole), _EXACT_SCORE)

    if not hits:
        # Only CODE-SHAPED tokens enter the embedded tier: dotted, underscored
        # or carrying an uppercase (``json.dumps``, ``ValueError``,
        # ``snake_case``). A plain lowercase word inside an error line or goal
        # is overwhelmingly English, and several ("with", "for", "type") are
        # also real docset entries — measured on the live corpus, they hijack
        # the exact tier with keyword pages. A deliberate whole-string lookup
        # of such a symbol still works: that is rung 1, not this fallback.
        tokens = [
            m.group(0)
            for m in _IDENT_RE.finditer(text)
            if "." in m.group(0)
            or "_" in m.group(0)
            or any(ch.isupper() for ch in m.group(0))
        ]
        ordered: list[str] = []
        seen_tokens: set[str] = set()
        for token in tokens:
            norm = normalize_symbol(token)
            if len(norm) >= 3 and norm not in seen_tokens:
                seen_tokens.add(norm)
                ordered.append(norm)
        # Longest token first (most specific), then first appearance — stable.
        first_seen = {token: pos for pos, token in enumerate(ordered)}
        ordered.sort(key=lambda t: (-len(t), first_seen[t]))
        for norm in ordered[:_EXACT_MAX_TOKENS]:
            _add(idx.symbol_rows(norm), _EXACT_TOKEN_SCORE)
            if len(hits) >= _EXACT_MAX_HITS:
                break

    # STABLE sort by score tier only: within a tier, insertion order stands —
    # whole-string matches lead, then token matches in specificity order
    # (longest token first), each already deterministic (symbol_rows orders by
    # source/path/name). A path-alphabetical re-sort would bury the most
    # specific match under an accidental early path.
    hits.sort(key=lambda item: -item[0])
    return [item[4] for item in hits[:_EXACT_MAX_HITS]]


# ---------------------------------------------------------------------------
# 2. search_docs — locally-implemented BM25, floor-gated
# ---------------------------------------------------------------------------


def _idf(df: int, n_pages: int) -> float:
    """Lucene-style non-negative BM25 idf; df=0 (unknown term) gets the
    maximum — unknown terms COUNT in the normalizer, so a query dominated by
    things the corpus has never seen cannot fake relevance."""
    return math.log(1.0 + (n_pages - df + 0.5) / (df + 0.5))


def search_docs(
    query: str, k: int = 4, *, index: DocsetIndex | None = None
) -> list[DocHit]:
    """Ranked local doc search — the SECOND rung, after :func:`exact_lookup`.

    Deterministic BM25 (k1=1.5, b=0.75) over the local page store, normalized
    to (0, 1] by the query's maximum achievable score mass (every unique query
    term contributes its idf to the denominator, unknown terms included).
    Pages below :data:`RELEVANCE_FLOOR` are dropped; **no page above the floor
    returns ``[]``** — the STOP behavior. Ties break by ascending page id
    (page ids are deterministic for a given corpus), duplicate-content sources
    are collapsed by title (:data:`_DUP_SOURCE_GROUPS`), and the top-*k*
    survivors pass through the :func:`semantic_rerank` seam (identity today).
    """
    if k <= 0:
        return []
    text = str(query or "")[:_MAX_QUERY_CHARS]
    if not text.strip():
        return []
    idx = _get_index(index)
    if idx.n_pages <= 0:
        return []

    terms: list[str] = []
    seen_terms: set[str] = set()
    for term in tokenize(text):
        if term not in seen_terms:
            seen_terms.add(term)
            terms.append(term)
        if len(terms) >= _MAX_QUERY_TERMS:
            break
    if not terms:
        return []

    k1, b = _BM25_K1, _BM25_B
    idfs = {term: _idf(idx.df(term), idx.n_pages) for term in terms}
    max_mass = sum(idf * (k1 + 1.0) for idf in idfs.values())
    if max_mass <= 0.0:
        return []

    scores: dict[int, float] = {}
    for term in terms:
        idf = idfs[term]
        if idf <= 0.0:
            continue
        for pid, tf in idx.postings(term):
            length_norm = 1.0 - b + b * (idx.doc_length(pid) / idx.avgdl)
            scores[pid] = scores.get(pid, 0.0) + (
                idf * (tf * (k1 + 1.0)) / (tf + k1 * length_norm)
            )

    floor = RELEVANCE_FLOOR
    ranked = sorted(
        (
            (score / max_mass, pid)
            for pid, score in scores.items()
            if score / max_mass >= floor
        ),
        key=lambda item: (-item[0], item[1]),
    )
    if not ranked:
        return []  # STOP: the corpus holds no high-value answer for this query.

    hits: list[DocHit] = []
    kept_titles: list[tuple[str, str]] = []  # (normalized title, source)
    for norm_score, pid in ranked:
        if len(hits) >= k:
            break
        page = idx.page(pid)
        if page is None:
            continue
        if _is_duplicate(page, kept_titles):
            continue
        title = _clean_title(page.title) or page.path
        kept_titles.append((_title_key(title), page.source))
        hits.append(
            DocHit(
                source=page.source,
                title=title,
                path=page.path,
                score=round(norm_score, 6),
                excerpt=_excerpt_around_terms(page.text, terms),
            )
        )
    return semantic_rerank(hits, text)


def _title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _is_duplicate(page: PageRow, kept: list[tuple[str, str]]) -> bool:
    """True when *page* duplicates an already-kept hit from its dup-group
    (e.g. the same python doc present as both DevDocs page and official-text
    page). The HIGHER-ranked copy was kept first; this one is skipped."""
    key = _title_key(page.title)
    if not key:
        return False
    for kept_key, kept_source in kept:
        if kept_key != key or kept_source == page.source:
            continue
        for group in _DUP_SOURCE_GROUPS:
            if page.source in group and kept_source in group:
                return True
    return False


# ---------------------------------------------------------------------------
# 3. semantic_rerank — the NAMED SEAM (identity in this slice)
# ---------------------------------------------------------------------------


def semantic_rerank(hits: list[DocHit], query: str) -> list[DocHit]:
    """SEAM (deliberately unwired, #746 slice 1): semantic re-ranking of
    lexically-retrieved hits.

    Today this is a deterministic identity pass — it returns *hits* unchanged
    — so the deterministic-first contract holds and the pipeline shape is
    already correct. The follow-up slice plugs the UC-002 embedding machinery
    in here (`shared/inference` embeddings — bge-small-en-v1.5 with the
    ``[embeddings].device`` NPU offload knob, the same encoder the knowledge
    bank uses) to re-order *hits* by cosine similarity against *query*.
    Contract for that follow-up: it may REORDER hits, never add ones the
    lexical floor rejected — the RELEVANCE_FLOOR STOP stays authoritative.
    """
    return list(hits)


__all__ = [
    "DocHit",
    "EXCERPT_MAX_CHARS",
    "RELEVANCE_FLOOR",
    "exact_lookup",
    "reset_default_index",
    "search_docs",
    "semantic_rerank",
]
