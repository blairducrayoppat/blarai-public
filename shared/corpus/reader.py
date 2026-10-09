"""Read-only reference-corpus reader (#1616).

A SEPARATE retrieval tier from the operator's knowledge bank, and deliberately
not an extension of it. The bank decrypts its whole corpus into RAM at
construction and ranks every chunk on every query; that is correct at curation
scale (measured at 15 chunks) and impossible at encyclopedia scale. This tier
inverts both choices: nothing is held in RAM, and candidate generation is
approximate BY DESIGN — see :meth:`ReferenceCorpus.search`.

**At rest this store is integrity-signed, not encrypted** (LA decision D1,
2026-09-21, #1616). The content is a public encyclopedia: encryption buys no
confidentiality and costs a decompress-plus-decrypt on every read. What the
operator ASKED and what was RETURNED are private, and those live in the
encrypted session store as they always have. A deliberate, scoped deviation
from the born-encrypted default, recorded in ADR-023 Amendment 5.

Every chunk retrieved from here carries ``Provenance.UNTRUSTED_CORPUS``: the
Layer-3 action lock and datamarking apply in full, so an injection hidden in a
vandalised article still cannot fire a tool.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

#: Schema this reader understands. A store built by a different builder version
#: is REFUSED rather than read on a guess — a silently mis-read store would
#: return plausible text from the wrong offsets.
SUPPORTED_SCHEMA_VERSION: int = 3

#: Default lexical candidate pool handed to the re-ranker. This tier CANNOT
#: rank exactly — tens of millions of chunks make that impossible — so it is
#: approximate by construction rather than by truncating an exact ranker. That
#: distinction is not pedantic: #1617 measured what naive truncation of an
#: exact ranker costs (a chunk at lexical rank 8 of 3000 evicted from the top 4
#: because its vector rank fell outside the pool), and the lesson is that the
#: approximation must be designed, with a defined treatment for a candidate
#: only one limb saw, not bolted on afterwards.
DEFAULT_CANDIDATES: int = 50

#: Hard cap on characters returned to a caller in one search. Matches the
#: assistant's existing retrieval budget: ~1,300 tokens at this corpus's
#: measured 3.09 chars/token, about 0.66 s of prompt processing at the
#: measured 1,960 tok/s. A whole article is ~12,000 tokens and about 6 s.
DEFAULT_MAX_CHARS: int = 4000


def default_manifest_path(db_path: str | Path) -> Path:
    """The manifest the builder writes beside a store: ``<db_path>.manifest.json``."""
    return Path(str(db_path) + ".manifest.json")


class CorpusError(RuntimeError):
    """The store is absent, unreadable, or fails verification.

    Always raised rather than degrading to a partial read: a reference tier
    that quietly returns nothing is indistinguishable from one whose subject
    genuinely is not covered, and the assistant would answer from memory
    without anyone knowing the corpus had dropped out.
    """


@dataclass(frozen=True)
class CorpusHit:
    """One retrieved paragraph, with everything needed to cite it."""

    chunk_id: int
    title: str
    section: str
    path: str
    text: str
    lexical_rank: int
    """0-based rank within the lexical candidate pool."""
    vector_score: float | None = None
    """Cosine similarity to the query, or ``None`` when no re-ranker was given.

    The calibrated number. The lexical rank orders candidates but does not
    measure them — #1617 established that the hard way on the knowledge bank,
    where a rank-derived score was identical for a perfect and a poor match.
    """
    last_edited: str | None = None
    """Date THIS ARTICLE was last edited, from the source archive. May be None.

    Not the archive's build date, which is a property of the download and says
    nothing about how current any single article is: 35.3% of this corpus was
    last edited before the archive was assembled, and the oldest sampled
    article had not been touched in six years. ``None`` means the source
    carried no date, and it is reported as unknown rather than back-filled.
    """
    revision_id: int | None = None
    """Wikipedia revision id of the exact version quoted. May be None.

    An immutable pointer: unlike a date it identifies the precise text, so a
    quotation stays checkable even after the article changes.
    """
    archive_date: str | None = None
    """Build date of the SOURCE ARCHIVE this article came from.

    Per-source, not per-store: a corpus may hold several archives and be
    refreshed in parts, so a single store-wide date would relabel articles a
    later refresh never touched.
    """

    def citation(self, snapshot_date: str | None = None) -> str:
        """Source line naming the ARTICLE's own date, not the archive's.

        The archive date is still shown, because the two answer different
        questions — "how current is this claim" versus "how old is this copy"
        — and collapsing them into one date is what makes a stale article look
        fresh. An article with no recorded date says so, in those words.
        """
        where = f" › {self.section}" if self.section else ""
        if self.last_edited:
            when = f"last edited {self.last_edited}"
        else:
            when = "edit date not recorded in this archive"
        rev = f", rev {self.revision_id}" if self.revision_id is not None else ""
        archive = self.archive_date or snapshot_date or "unknown"
        return (
            f"Wikipedia, '{self.title}'{where} "
            f"({when}{rev}; archive snapshot {archive})"
        )


_FTS_SAFE = re.compile(r"[^\w\s]+", re.UNICODE)
_STOP = frozenset(
    "a an the of and or to in on at for with from by is are was were be been "
    "being as that this these those it its what which who when where why how".split()
)


def fts_match_expr(query: str) -> str:
    """Build a safe FTS5 MATCH expression from free text.

    FTS5 treats punctuation as query syntax, so a raw user string is both an
    injection surface and a source of ``sqlite3.OperationalError`` on ordinary
    apostrophes. Strip to words, drop stop words, OR the remainder.
    """
    words = [w for w in _FTS_SAFE.sub(" ", query).split() if len(w) > 1]
    words = [w for w in words if w.lower() not in _STOP] or words
    return " OR ".join(f'"{w}"' for w in words[:24])


class ReferenceCorpus:
    """Read-only access to a built reference corpus.

    Args:
        db_path: Path to the store built by ``tools/corpus/build_corpus.py``.
        embed_fn: Optional callable mapping ``list[str]`` to an ``(N, D)``
            array of L2-normalised float32 vectors, used to re-rank the lexical
            candidates. Without it, search returns lexical order and every hit
            reports ``vector_score=None`` — honestly unmeasured rather than
            falsely confident.
        manifest_path: The integrity manifest. ``None`` means the manifest the
            builder writes beside the store (``<db_path>.manifest.json``). The
            store's SHA-256 must match it or the reader REFUSES to open, and a
            missing manifest is refused the same way (D1 fail-closed). There is
            no unverified open: a caller cannot skip verification by leaving a
            setting empty.
        verified_by: An open reader of the SAME store that has already verified
            it. Passing one skips re-hashing the file (39 GB for the real store)
            without creating a way to open bytes nobody verified. Mutually
            exclusive with ``manifest_path``.
    """

    def __init__(
        self,
        db_path: str | Path,
        embed_fn: Callable[[list[str]], Any] | None = None,
        manifest_path: str | Path | None = None,
        *,
        verified_by: "ReferenceCorpus | None" = None,
    ) -> None:
        self._path = Path(db_path)
        if not self._path.is_file():
            raise CorpusError(f"reference corpus not found: {self._path}")
        if verified_by is not None:
            if manifest_path is not None:
                raise CorpusError(
                    "pass a manifest or an already-verified reader, not both"
                )
            if (
                not isinstance(verified_by, ReferenceCorpus)
                or not getattr(verified_by, "verified_sha256", "")
                or verified_by._path.resolve() != self._path.resolve()
            ):
                raise CorpusError(
                    "verified_by must be a verified reader of this same store; "
                    "refusing to open unverified bytes"
                )
            # Point-in-time verification inherited by reference: it checks the
            # handle's shape and same-path identity, not the bytes again, so it
            # is a re-hash saver for a second reader of a store this process
            # already verified, never a way to vouch for a store.
            self.verified_sha256: str = verified_by.verified_sha256
        else:
            manifest = (
                Path(manifest_path)
                if manifest_path is not None
                else default_manifest_path(self._path)
            )
            self.verified_sha256 = self._verify(manifest)

        uri = f"file:{self._path.as_posix()}?mode=ro&immutable=1"
        try:
            self._db = sqlite3.connect(uri, uri=True, check_same_thread=False)
        except sqlite3.Error as exc:  # pragma: no cover - platform specific
            raise CorpusError(f"cannot open reference corpus: {exc}") from exc

        meta = dict(self._db.execute("SELECT key, value FROM meta").fetchall())
        version = int(meta.get("schema_version", -1))
        if version != SUPPORTED_SCHEMA_VERSION:
            raise CorpusError(
                f"reference corpus schema {version} is not the supported "
                f"{SUPPORTED_SCHEMA_VERSION}; refusing to read it on a guess"
            )
        self._zdict = base64.b64decode(meta.get("zdict_b64", ""))
        self.snapshot_date: str = meta.get("snapshot_date", "unknown")
        self.chunk_count: int = int(meta.get("chunk_count", 0))
        self.article_count: int = int(meta.get("article_count", 0))
        self.articles_with_edit_date: int = int(
            meta.get("articles_with_edit_date", 0)
        )
        # The build's tie to its extraction (G2): the commit and rules that
        # produced the text, and whether table rows are in it. "unknown" when
        # the store predates the builder recording them.
        self.repo_commit: str = meta.get("repo_commit", "unknown")
        self.extract_rules_sha256: str = meta.get("extract_rules_sha256", "unknown")
        self.with_tables: str = meta.get("with_tables", "unknown")
        self._embed = embed_fn

    # -- integrity ---------------------------------------------------------

    def _verify(self, manifest_path: Path) -> str:
        if not manifest_path.is_file():
            raise CorpusError(f"integrity manifest missing: {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = str(manifest["sha256"]).lower()
        except Exception as exc:
            raise CorpusError(f"integrity manifest unreadable: {exc}") from exc

        digest = hashlib.sha256()
        with open(self._path, "rb") as fh:
            for block in iter(lambda: fh.read(8 << 20), b""):
                digest.update(block)
        actual = digest.hexdigest()
        if actual != expected:
            raise CorpusError(
                "reference corpus FAILED integrity verification "
                f"(expected {expected[:16]}…, got {actual[:16]}…) — refusing to serve"
            )
        return actual

    # -- reading -----------------------------------------------------------

    def _text(self, blob: bytes) -> str:
        do = zlib.decompressobj(-zlib.MAX_WBITS, zdict=self._zdict)
        return (do.decompress(blob) + do.flush()).decode("utf-8")

    def search(
        self,
        query: str,
        k: int = 3,
        candidates: int = DEFAULT_CANDIDATES,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> list[CorpusHit]:
        """Return up to *k* paragraphs, most relevant first.

        Two stages. BM25 over the full-text index supplies ``candidates``
        candidates — bounded, because an encyclopedia's common term matches
        millions of rows and an unbounded fetch is the failure #1617 recorded
        on the other tier. The embedder then scores ONLY those candidates, so
        no pre-embedded vector index exists to build, store or keep in step.

        Returns fewer than *k* hits, or none at all, rather than padding with
        weak matches: a caller that receives three paragraphs always is a
        caller that cannot tell coverage from noise.
        """
        expr = fts_match_expr(query)
        if not expr or k <= 0:
            return []

        rows = self._db.execute(
            "SELECT c.id, c.article_id, c.section, c.z, a.title, a.path, "
            "a.last_edited, a.revision_id, s.archive_date "
            "FROM chunks_fts f "
            "JOIN chunks c ON c.id = f.rowid "
            "JOIN articles a ON a.id = c.article_id "
            "JOIN sources s ON s.id = a.source_id "
            "WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
            (expr, candidates),
        ).fetchall()
        if not rows:
            return []

        hits: list[CorpusHit] = []
        for rank, (cid, _aid, section, blob, title, path, edited, rev, arch) in enumerate(rows):
            try:
                text = self._text(blob)
            except Exception:
                continue  # a corrupt row is skipped, never served as text
            hits.append(
                CorpusHit(
                    chunk_id=int(cid),
                    title=title,
                    section=section or "",
                    path=path,
                    text=text,
                    lexical_rank=rank,
                    last_edited=edited,
                    revision_id=rev,
                    archive_date=arch,
                )
            )
        if not hits:
            return []

        if self._embed is not None:
            hits = self._rerank(query, hits)

        chosen: list[CorpusHit] = []
        used = 0
        for hit in hits[:k]:
            if used + len(hit.text) > max_chars and chosen:
                break
            chosen.append(hit)
            used += len(hit.text)
        return chosen

    def _rerank(self, query: str, hits: list[CorpusHit]) -> list[CorpusHit]:
        import numpy as np

        vectors = np.asarray(
            self._embed([query] + [h.text for h in hits]), dtype=np.float32
        )
        q_vec, doc_vecs = vectors[0], vectors[1:]
        scores = doc_vecs @ q_vec
        scored = [
            CorpusHit(
                chunk_id=h.chunk_id,
                title=h.title,
                section=h.section,
                path=h.path,
                text=h.text,
                lexical_rank=h.lexical_rank,
                vector_score=float(s),
                last_edited=h.last_edited,
                revision_id=h.revision_id,
                archive_date=h.archive_date,
            )
            for h, s in zip(hits, scores)
        ]
        scored.sort(key=lambda h: h.vector_score or 0.0, reverse=True)
        return scored

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "ReferenceCorpus":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
