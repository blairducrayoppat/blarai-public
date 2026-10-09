"""Pure text-extraction rules for the reference corpus (#1616).

**This module imports nothing from the ZIM ecosystem.** It is plain text
processing over HTML strings, which is why it can live in this repository at
all: ``libzim`` is GPL-3.0-or-later and this tree ships PolyForm Noncommercial
plus a commercial licence. The GPL boundary is the ``import libzim`` statement,
and that statement lives in a thin driver outside this repository which opens
the archive, iterates entries, and calls the functions below.

That split is not only a licensing device. Every rule here was previously
unreachable by the test suite, which is how a set of defects reached the edge
of a four-hour extraction run: 21.5% of article pages emitting nothing at all,
``&amp;`` deleted rather than decoded ("Rag & Bone" -> "Rag Bone"), ``km²``
silently reduced to ``km`` in prose that still read as fact, infoboxes
truncated at the first nested table, and redirect targets truncated at an
apostrophe. Each was found by hand. Each is now pinned by a golden-fixture test
against real article HTML in ``shared/tests/fixtures/corpus/``.

If you change a rule here, the fixtures will tell you what it does to real
Wikipedia pages before it costs another four hours.
"""

from __future__ import annotations

import html as _html
import re
import unicodedata
from typing import NamedTuple

# Measured: 85.9% of articles carry both, and they co-occur 363/363. 99.2% were
# last edited BEFORE the archive build date -- an earlier "35.3%" was the
# fraction older than the calendar year, a different question.
# The oldid separator may be '&' or '&amp;', so the pattern does not anchor on
# one; an earlier version did and measured 0% coverage, which looked exactly
# like the field being absent.
_LAST_EDITED = re.compile(r'title="Last edited on ([0-9]{4}-[0-9]{2}-[0-9]{2})"')
_OLDID = re.compile(r"oldid=(\d+)")


# ---------------------------------------------------------------------------
# Namespace filtering
# ---------------------------------------------------------------------------

# NOTE the absent alternations. `I/ M/ X/ -/` are LEGACY ZIM namespace prefixes
# that do not exist in this archive (assets live under `_assets_/`). Leaving
# them in matched real article TITLES containing a slash and silently dropped
# 766 entries in a full scan: I/O_virtualization, M/M/1_queue, X/Open,
# M/S_Estonia and friends. Incidence is trivial; the cost of noticing later is
# a four-hour re-extraction, which is why it is fixed here rather than tracked.
_NON_ARTICLE = re.compile(
    r"^(User:|Talk:|Wikipedia:|File:|Template:|Category:|Portal:|Draft:|Help:|"
    r"MediaWiki:|Module:|Special:|Book:|TimedText:|_assets_/)",
    re.IGNORECASE,
)


def is_article_path(path: str) -> bool:
    """Is this ZIM path in the article namespace?

    The public form of the namespace filter, so the driver never reaches
    for a private name to make the one decision it is allowed to make.
    """
    return not _NON_ARTICLE.match(path or "")

# Sections carrying no retrievable prose. A retrieved chunk of reference list is
# worse than no chunk: plausible, on-topic, empty. Exact-match on the LEAF
# heading. "notes and references" was added after review found it indexed.
_DEAD_SECTIONS = {
    "references", "external links", "see also", "further reading", "notes",
    "bibliography", "sources", "citations", "footnotes", "gallery",
    "navigation menu", "contents", "explanatory notes", "works cited",
    "notes and references", "references and notes", "sources and references",
}

# ---------------------------------------------------------------------------
# Superscripts and subscripts
# ---------------------------------------------------------------------------

# Citation superscripts are noise; EXPONENT superscripts are the fact itself.
# Stripping both produced clean prose stating falsehoods -- "2.77 km ... or
# 60.3% is used for agricultural purposes" (km² became km), "accelerating at
# 1 g, 9.8 m/s" (m/s² became m/s). Measured: 3,293 citation sups vs 25 content
# sups in live paragraphs, and the split is exact -- every citation carries a
# class matching /reference|mw-ref/, no content sup does.
_SUP_CHROME = re.compile(
    r'<sup[^>]*class="[^"]*(?:reference|mw-ref|noexcerpt|'
    r'navigation-not-searchable)[^"]*"[^>]*>.*?</sup>',
    re.S | re.I,
)
_SUP_ANY = re.compile(r"<sup[^>]*>(.*?)</sup>", re.S | re.I)
_SUB_ANY = re.compile(r"<sub[^>]*>(.*?)</sub>", re.S | re.I)

_SUPERS = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "n": "ⁿ", "i": "ⁱ",
}
_SUBS = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "+": "₊", "-": "₋",
}


def _script_repl(table: dict[str, str], marker: str):
    """Fold a sup/sub into the PRECEDING text with no separating space.

    The trap the review caught in the obvious fix: simply keeping the tag and
    letting the generic tag-stripper run yields "2.77 km 2", which is a
    different wrong answer. The inner text must join without a space.
    """

    def repl(m: re.Match[str]) -> str:
        inner = _WS.sub("", _TAG.sub("", m.group(1)))
        if not inner:
            return ""
        if all(ch in table for ch in inner):
            return "".join(table[ch] for ch in inner)
        return f"{marker}{inner}"

    return repl


# ---------------------------------------------------------------------------
# Block elements
# ---------------------------------------------------------------------------

_STRIP_BLOCKS = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.S | re.I)
_FIGURE = re.compile(r"<figure\b.*?</figure>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_EDIT_MARK = re.compile(r"\[\s*edit\s*\]", re.I)
_CITE_MARK = re.compile(r"\[\s*\d+\s*\]")

_PARA = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S | re.I)
_LI = re.compile(r"<li\b[^>]*>(.*?)</li>", re.S | re.I)
_FIGCAP = re.compile(r"<figcaption[^>]*>(.*?)</figcaption>", re.S | re.I)
_FIGURE_BLOCK = re.compile(r"<figure\b[^>]*>(.*?)</figure>", re.S | re.I)
_IMG_SRC = re.compile(r'<img[^>]+src="([^"]+)"', re.I)
_HEADING = re.compile(r"<h([2-6])[^>]*>(.*?)</h\1>", re.S | re.I)
_TABLE_OPEN = re.compile(r"<table\b[^>]*>", re.I)
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S | re.I)
_CSS_NOISE = re.compile(r"/\*.*?\*/|\.mw-[\w-]+|\{[^}]*\}|@media[^{]*", re.S)
_INFOBOX_CLASS = re.compile(r'class="[^"]*infobox[^"]*"', re.I)
_NAVBOX_CLASS = re.compile(r'class="[^"]*(?:navbox|vertical-navbox|sistersitebox|metadata)[^"]*"', re.I)

#: Below this a paragraph alone is a fragment. MEASURED: only 1.26% of live
#: paragraph text falls under it, and inspection showed the losses are table
#: legends and "Last updated:" stubs.
MIN_CHARS = 110
MERGE_TARGET = 700
MAX_CHARS = 2400          # measured: 0 of 2,031 real chunks ever exceeded it

#: List items are merged as RUNS, never filtered per item. A per-item floor was
#: proposed at 60 chars and measured wrong: it rescues 15 of 29 vanished
#: articles, because a disambiguation entry ("Abernathy, Texas , a city") is 25
#: characters by construction. The value of a disambiguation page is the WHOLE
#: list as one passage, so the existing consecutive-short merge is applied to
#: list runs instead of a threshold.
LIST_RUN_MIN = 60         # a merged RUN must reach this to be emitted


def _clean(fragment: str) -> str:
    """HTML fragment -> plain text, preserving exponents and ampersands."""
    text = _STRIP_BLOCKS.sub(" ", fragment)
    text = _SUP_CHROME.sub(" ", text)
    text = _SUP_ANY.sub(_script_repl(_SUPERS, "^"), text)
    text = _SUB_ANY.sub(_script_repl(_SUBS, "_"), text)
    text = _TAG.sub(" ", text)
    # unescape, NOT delete. Replacing entities with a space turned "Rag & Bone"
    # into "Rag Bone", "J&J" into "J J" and the taxonomic authority
    # "Sakamoto, Iino & Ohkuma 2017" into a different authority. 17.1% of
    # articles carried at least one.
    text = _html.unescape(text)
    text = _EDIT_MARK.sub(" ", text)
    text = _CITE_MARK.sub(" ", text)
    text = unicodedata.normalize("NFC", text)
    return _WS.sub(" ", text).strip()


def _balanced_table(html: str, start: int) -> tuple[int, int]:
    """Return (body_start, body_end) of the table opening at *start*.

    A non-greedy `(.*?)</table>` stops at the first NESTED closing tag, and
    Wikipedia infoboxes routinely embed sub-tables: measured, that truncated
    14.5% of infoboxes partway down, losing 91 rows across 37 articles. This
    counts depth instead.
    """
    open_m = _TABLE_OPEN.search(html, start)
    if not open_m:
        return (-1, -1)
    body = open_m.end()
    depth = 1
    pos = body
    token = re.compile(r"<table\b|</table>", re.I)
    while depth and (m := token.search(html, pos)):
        depth += 1 if m.group(0).lower().startswith("<table") else -1
        pos = m.end()
    return (body, (pos - len("</table>")) if depth == 0 else len(html))


def _iter_tables(html: str):
    """Yield (attrs, body) for every top-level table, depth-balanced."""
    pos = 0
    while (m := _TABLE_OPEN.search(html, pos)) is not None:
        body_start, body_end = _balanced_table(html, m.start())
        if body_start < 0:
            return
        yield m.group(0), html[body_start:body_end]
        pos = body_end + len("</table>")


def _rows(body: str):
    for row in _TR.findall(body):
        cells = [_clean(_CSS_NOISE.sub(" ", c)) for c in _TD.findall(row)]
        yield [c for c in cells if c]


def _infobox_facts(html: str) -> str:
    """Render EVERY infobox as `key = value` lines (3.5% of articles have >1)."""
    out: list[str] = []
    for attrs, body in _iter_tables(html):
        if not _INFOBOX_CLASS.search(attrs):
            continue
        for cells in _rows(body):
            if len(cells) >= 2:
                key, value = cells[0], " ".join(cells[1:])
                if len(key) <= 60 and value and len(value) <= 300:
                    out.append(f"{key} = {value}")
            elif len(cells) == 1 and 12 <= len(cells[0]) <= 200:
                # A colspan row. Infoboxes put the RESULT line here
                # ("Pecan Bowl , L 14-23 vs. North Dakota State"); dropping all
                # single-cell rows discarded 926 of them. Kept bare, with a
                # length band that excludes bare section headers and spacers.
                out.append(cells[0])
    return "\n".join(out[:80])


def _table_text(html: str) -> list[str]:
    """Render non-infobox, non-navbox tables as ` | `-joined rows.

    The single largest remaining drop: ordinary tables carry 17.84% of live
    prose (election results, discographies, climate rows, sports records) and
    were previously discarded entirely.
    """
    blocks: list[str] = []
    for attrs, body in _iter_tables(html):
        if _INFOBOX_CLASS.search(attrs) or _NAVBOX_CLASS.search(attrs):
            continue
        lines = [" | ".join(c) for c in _rows(body) if c]
        lines = [ln for ln in lines if len(ln) >= 12]
        if not lines:
            continue
        text = "\n".join(lines)
        if len(text) >= 120:
            blocks.append(text[:MAX_CHARS])
    return blocks


def _sections(html: str):
    """Yield (breadcrumb, inner_html), lead section first, ancestry preserved."""
    pieces = [
        (int(m.group(1)), _clean(m.group(2)), m.start(), m.end())
        for m in _HEADING.finditer(html)
    ]
    if not pieces:
        yield "", html
        return
    yield "", html[: pieces[0][2]]
    stack: list[tuple[int, str]] = []
    for idx, (level, title, _s, end) in enumerate(pieces):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        nxt = pieces[idx + 1][2] if idx + 1 < len(pieces) else len(html)
        yield " › ".join(t for _, t in stack), html[end:nxt]


def _split_long(text: str):
    if len(text) <= MAX_CHARS:
        yield text
        return
    buf = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(buf) + len(sentence) + 1 > MAX_CHARS and buf:
            yield buf.strip()
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
    if buf.strip():
        yield buf.strip()


def _passages(body: str):
    """Paragraph and list text for a section, short runs merged."""
    stripped = _FIGURE.sub(" ", body)
    pending: list[str] = []

    def flush(floor: int):
        joined = " ".join(pending)
        pending.clear()
        if len(joined) >= floor:
            yield from _split_long(joined)

    for raw in _PARA.findall(stripped):
        para = _clean(raw)
        if not para:
            continue
        if len(para) >= MIN_CHARS and not pending:
            yield from _split_long(para)
            continue
        pending.append(para)
        if len(" ".join(pending)) >= MERGE_TARGET:
            yield from flush(MIN_CHARS)
    yield from flush(MIN_CHARS)

    items = [_clean(x) for x in _LI.findall(stripped)]
    items = [i for i in items if i]
    run: list[str] = []
    for item in items:
        run.append(item)
        if len("; ".join(run)) >= MERGE_TARGET:
            yield from _split_long("; ".join(run))
            run = []
    if run and len("; ".join(run)) >= LIST_RUN_MIN:
        yield from _split_long("; ".join(run))


def _all_images(page: str, limit: int = 60) -> list[str]:
    """Every distinct image path in an article, in document order.

    `_figures` pairs captions with the images inside `<figure>` blocks, which
    is what makes an image RETRIEVABLE. But measured on real articles, most
    images are not in a figure at all — the infobox photo, inline thumbnails,
    map pins — and those were unaddressable: the later images work could not
    even locate their bytes in the archive. One representative case is an
    article whose own headline photograph sits in its infobox.

    So paths are also recorded at ARTICLE scope, unfiltered. Deciding which are
    chrome (Commons logos, map pins) is a retrieval-time judgement that can be
    revised; not writing the path down at all costs a re-extraction.
    """
    seen: list[str] = []
    for src in _IMG_SRC.findall(page):
        path = src.split("?")[0]
        if path not in seen:
            seen.append(path)
        if len(seen) >= limit:
            break
    return seen


def _figures(body: str):
    """Yield (caption, image_path|None) for each figure, PAIRED.

    Two independent findall() passes over the same section do not pair: the
    first <img> is often an infobox logo, not the image the first caption
    describes. Worse, image paths used to be recorded only when a caption
    existed, leaving images in 210 of 414 sampled sections unaddressable.
    Iterating <figure> blocks keeps caption and image together, and a figure
    with no caption still yields its path.
    """
    for block in _FIGURE_BLOCK.findall(body):
        cap = _FIGCAP.search(block)
        img = _IMG_SRC.search(block)
        caption = _clean(cap.group(1)) if cap else ""
        path = img.group(1).split("?")[0] if img else None
        if caption or path:
            yield caption, path


# Section-redirect stubs: `is_redirect` is FALSE, there is no prose and no
# infobox, so these fell between both branches and emitted nothing. They are
# 14% of article-namespace HTML entries and are exactly the alias records the
# contract wants. The URL is SINGLE-quoted and titles contain apostrophes
# ("Now That's What I Call..."), so a naive ([^']+) parse silently truncates to
# a wrong target -- measured on 2 of 295. Anchor to the closing quote+paren.
#: Match the content ATTRIBUTE by its own delimiter, then unwrap the URL from
#: the inside. Matching the inner quotes directly with a backreference fails:
#: the value is `content="0;URL='./Now_That's_What_I_Call...'"`, so `(['"])(.*?)\1`
#: closes on the APOSTROPHE inside the title and banks `Now_That` — a wrong
#: target that looks perfectly valid downstream. Apostrophes are common in
#: article titles, so this silently mis-points a real slice of the aliases.
_META_REFRESH = re.compile(
    r"""<meta[^>]+http-equiv\s*=\s*["']?refresh["']?[^>]*?
        \scontent\s*=\s*(["'])(?P<val>.*?)\1""",
    re.I | re.X | re.S,
)
_REFRESH_URL = re.compile(r"^\s*\d+\s*;\s*url\s*=\s*(?P<url>.*?)\s*$", re.I | re.S)


def _refresh_target(html: str) -> tuple[str, str] | None:
    m = _META_REFRESH.search(html)
    if not m:
        return None
    inner = _REFRESH_URL.match(m.group("val"))
    if not inner:
        return None
    raw = inner.group("url").strip()
    # Strip ONE layer of matched wrapping quotes, from the ends only.
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1]
    raw = _html.unescape(raw).strip()
    raw = raw[2:] if raw.startswith("./") else raw
    target, _, anchor = raw.partition("#")
    return (target, anchor) if target else None




# ---------------------------------------------------------------------------
# One entry -> its records
# ---------------------------------------------------------------------------
#
# This layer used to live in the driver, outside the repository and outside
# pytest, alongside the single ``import libzim``. That put the alias branch,
# the section-stub branch, the infobox floor, the dead-section filter, the
# ordinal sequence and the ``zero_record_entries`` counter beyond the reach of
# any test — which is precisely the population the review's defects came from
# (1a, 1b, 1c, 8b). None of it needs a ZIM archive: it is a title, a path and
# an HTML string in, records out. So it lives here, and the driver is reduced
# to the libzim loop it has to be.

#: Record kinds that carry an ordinal, and therefore constitute "this entry
#: produced something retrievable". An ``images`` record does not: an article
#: with pictures and no text is still an article that emitted no prose, and
#: counting it as a success is how 2.1M dropped pages rendered as a confident
#: number (finding 1c).
_ORDINAL_KINDS = frozenset({"chunk", "facts", "caption"})

#: An infobox shorter than this is a stub table — a single "Coordinates" row,
#: a lone image cell — not a fact block worth a chunk. Previously an unnamed
#: 60 in the driver.
FACTS_MIN_CHARS = 60


class EntryRecords(NamedTuple):
    """What one archive entry yielded, plus the two facts a counter needs.

    ``is_stub`` and ``is_html`` are not decoration: an entry that emitted no
    records is either a section-redirect stub (expected, already counted as an
    alias) or an article that VANISHED (a defect). Without both flags the
    tally cannot tell those apart, which was finding 1c.
    """

    records: list[dict]
    is_stub: bool
    is_html: bool


def redirect_alias(title: str, target: str, anchor: str = "") -> dict | None:
    """The alias record for a redirect, or None when it points out of scope.

    Returns None rather than raising for a filtered target (``Category:``,
    ``User:``) or an empty title: both are ordinary, both mean "no record",
    and neither is an error the caller can act on.
    """
    title = (title or "").strip()
    target = (target or "").strip()
    if not title or not target or _NON_ARTICLE.match(target):
        return None
    rec = {"k": "alias", "a": title, "p": target}
    if anchor:
        rec["h"] = anchor
    return rec


def entry_records(
    title: str, path: str, page: str, *, with_tables: bool = True
) -> EntryRecords:
    """Every record one article-namespace HTML entry yields, in emission order.

    Order is part of the contract and is pinned by test: images first (article
    scope, no ordinal), then the infobox, then each live section's passages,
    captions and tables. Ordinals are assigned in that order and are contiguous
    from zero, because the store keys a chunk by ``(article_id, ordinal)`` and
    a reader reconstructs reading order from it.
    """
    stub = _refresh_target(page)
    if stub is not None:
        rec = redirect_alias(title, stub[0], stub[1])
        return EntryRecords([rec] if rec else [], is_stub=True, is_html=True)

    base: dict = {"t": title, "p": path}
    if (m_date := _LAST_EDITED.search(page)) is not None:
        base["d"] = m_date.group(1)
    if (m_rev := _OLDID.search(page)) is not None:
        base["r"] = int(m_rev.group(1))

    out: list[dict] = []
    if img_paths := _all_images(page):
        out.append({**base, "k": "images", "paths": img_paths})

    ordinal = 0
    fact_text = _infobox_facts(page)
    if len(fact_text) >= FACTS_MIN_CHARS:
        out.append({**base, "k": "facts", "x": fact_text, "o": ordinal})
        ordinal += 1

    for heading, body in _sections(page):
        leaf = heading.rsplit("›", 1)[-1].strip().lower()
        if leaf in _DEAD_SECTIONS:
            continue
        for piece in _passages(body):
            out.append({**base, "k": "chunk", "s": heading, "x": piece, "o": ordinal})
            ordinal += 1
        for caption, img in _figures(body):
            rec = {
                **base, "k": "caption", "s": heading, "o": ordinal,
                "x": caption or f"[image in {heading or title}]",
            }
            if img:
                rec["i"] = img
            out.append(rec)
            ordinal += 1
        if with_tables:
            for block in _table_text(body):
                out.append({
                    **base, "k": "chunk", "s": heading, "x": block,
                    "o": ordinal, "tbl": 1,
                })
                ordinal += 1

    return EntryRecords(out, is_stub=False, is_html=True)


def new_counters() -> dict[str, int]:
    """A fresh run tally. Every key is reported in the shard sidecar.

    The four DISPOSITION counters -- ``redirect_entries``,
    ``non_article_entries``, ``non_html_entries`` and ``html_entries`` --
    plus ``skipped`` account for every entry a run visited, so a rate
    computed from the sidecar names its own denominator instead of being
    paired with one from somewhere else. The driver owns the first three,
    because only it can see an entry it chose not to read; ``tally`` owns
    the rest.
    """
    return dict(
        articles=0, dated=0, chunks=0, facts=0, captions=0, tables=0,
        aliases=0, alias_anchored=0, refresh_stubs=0, html_entries=0,
        image_refs=0, zero_record_entries=0, skipped=0,
        redirect_entries=0, non_article_entries=0, non_html_entries=0,
    )


def tally(counters: dict[str, int], result: EntryRecords) -> None:
    """Fold one entry's result into the run counters.

    ``chunks`` counts prose, table and infobox records but NOT captions, which
    have their own counter; the store holds all four as chunk rows, so the
    sidecar also reports ``store_chunk_rows`` for anyone comparing the two.
    Kept that way deliberately rather than quietly redefined, because the
    projections in the extraction contract were computed against this meaning.
    """
    counters["html_entries"] += result.is_html
    counters["refresh_stubs"] += result.is_stub

    bearing = 0
    dated = False
    for rec in result.records:
        kind = rec.get("k")
        if kind == "alias":
            counters["aliases"] += 1
            counters["alias_anchored"] += "h" in rec
        elif kind == "images":
            counters["image_refs"] += len(rec.get("paths") or ())
        elif kind in _ORDINAL_KINDS:
            bearing += 1
            dated = dated or "d" in rec
            if kind == "caption":
                counters["captions"] += 1
            else:
                counters["chunks"] += 1
                counters["facts"] += kind == "facts"
                counters["tables"] += bool(rec.get("tbl"))

    if bearing:
        counters["articles"] += 1
        counters["dated"] += dated
    elif result.is_html and not result.is_stub:
        # THE COUNTER THAT WAS MISSING. Without it a run's own metadata cannot
        # distinguish "the encyclopedia has 6.8M articles" from "2.1M pages
        # were silently dropped" — an absence rendered as a confident number.
        counters["zero_record_entries"] += 1


# ---------------------------------------------------------------------------
# Entry -> records. The whole per-entry decision, testable.
# ---------------------------------------------------------------------------

#: An infobox rendering shorter than this is a stub or a spacer, not facts.
FACTS_MIN_CHARS = 60

#: Last-resort floor for an article that would otherwise produce NOTHING.
#: MIN_CHARS exists to suppress noise chunks, not to erase articles, and real
#: one-sentence stubs fall under it: "Ensomned is a settlement on the island of
#: Saint Thomas in the United States Virgin Islands" is 89 characters and was
#: the sole content of its page. Wikipedia carries a great many such geography
#: and species stubs. Below THIS floor there is genuinely nothing to retrieve.
STUB_MIN_CHARS = 40


def alias_record(title: str, target_path: str) -> dict | None:
    """Record for a TRUE redirect entry (``is_redirect``), or None to skip.

    The driver supplies the resolved target because resolution is a libzim
    call; the DECISION of whether it becomes a record lives here, where a test
    can reach it.
    """
    title = (title or "").strip()
    if not title or not target_path or _NON_ARTICLE.match(target_path):
        return None
    return {"k": "alias", "a": title, "p": target_path}


def records_for_entry(
    title: str,
    path: str,
    page: str,
    with_tables: bool = True,
) -> list[dict]:
    """Every record one article-namespace HTML entry produces.

    Returns ``[]`` when the entry yields nothing — which the caller MUST count.
    An earlier version left that determination in the driver, where nothing
    tested it, and 21.5% of article pages emitted nothing while the run's own
    metadata reported only the articles that had succeeded.

    Record ORDER is part of the contract and is asserted by the fixtures: the
    infobox first (ordinal 0, the densest facts in the article), then each live
    section's passages, then its captions, then its tables.
    """
    title = (title or path).strip()

    # Section-redirect stubs report is_redirect == False and carry no prose, so
    # they fall between the redirect branch and the article branch.
    hit = _refresh_target(page)
    if hit is not None:
        target, anchor = hit
        rec = alias_record(title, target)
        if rec is None:
            return []
        if anchor:
            # OPAQUE: only ~59% of anchors join to a section this extractor
            # emits. Recorded, never promised to resolve.
            rec["h"] = anchor
        return [rec]

    base: dict = {"t": title, "p": path}
    m_date = _LAST_EDITED.search(page)
    m_rev = _OLDID.search(page)
    if m_date:
        base["d"] = m_date.group(1)
    if m_rev:
        base["r"] = int(m_rev.group(1))

    out: list[dict] = []
    images = _all_images(page)
    if images:
        out.append({**base, "k": "images", "paths": images})

    ordinal = 0
    facts = _infobox_facts(page)
    if len(facts) >= FACTS_MIN_CHARS:
        out.append({**base, "k": "facts", "x": facts, "o": ordinal})
        ordinal += 1

    for heading, body in _sections(page):
        leaf = heading.rsplit("›", 1)[-1].strip().lower()
        if leaf in _DEAD_SECTIONS:
            continue
        for piece in _passages(body):
            out.append({**base, "k": "chunk", "s": heading, "x": piece, "o": ordinal})
            ordinal += 1
        for caption, img in _figures(body):
            rec = {**base, "k": "caption", "s": heading, "o": ordinal,
                   "x": caption or f"[image in {heading or title}]"}
            if img:
                rec["i"] = img
            out.append(rec)
            ordinal += 1
        if with_tables:
            for block in _table_text(body):
                out.append({**base, "k": "chunk", "s": heading, "x": block,
                            "o": ordinal, "tbl": 1})
                ordinal += 1

    if ordinal == 0:
        # LAST RESORT before declaring the article empty. A one-sentence stub is
        # still an article, and an encyclopedia that omits its stubs lies about
        # its coverage just as surely as one that omits its long pages. Take the
        # lead section's prose whatever its length.
        lead = ""
        for heading, body in _sections(page):
            if heading:
                break
            lead = _clean(_FIGURE.sub(" ", body))
            break
        if len(lead) >= STUB_MIN_CHARS:
            out.append({**base, "k": "chunk", "s": "", "x": lead[:MAX_CHARS], "o": 0})
            return out
        # Genuinely nothing to retrieve. The caller MUST count this.
        return []
    return out
