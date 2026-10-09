"""Tests for the read-only reference-corpus tier (#1616).

Hermetic: every test builds its own miniature corpus through the REAL builder
and reads it through the REAL reader. Nothing depends on the 118 GiB archive or
on anything under B:, so this runs in a clean checkout.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from shared.corpus import (
    CorpusError,
    ReferenceCorpus,
    default_manifest_path,
    fts_match_expr,
)
from tools.corpus.build_corpus import build, write_manifest

_ARTICLES = [
    (
        "Ancient Greece",
        "greece",
        "",
        "Ancient Greece was a civilization belonging to a period of Greek history "
        "from the Greek Dark Ages of the 12th to 9th centuries BC to the end of "
        "classical antiquity, comprising a loose collection of city states.",
    ),
    (
        "Ancient Greece",
        "greece",
        "Chronology",
        "Scholars mark Ancient Greece as beginning with Mycenaean Greece, which "
        "declined during the Bronze Age collapse around 1100 BC, three centuries "
        "before the urban poleis began to form in the eighth century BC.",
    ),
    (
        "Solar eclipse",
        "eclipse",
        "",
        "A solar eclipse occurs when the Moon passes between Earth and the Sun, "
        "thereby obscuring the view of the Sun from a small part of Earth, "
        "totally or partially.",
    ),
    (
        "Photosynthesis",
        "photo",
        "",
        "Photosynthesis is a system of biological processes by which phototrophic "
        "organisms convert light energy into chemical energy, storing it in "
        "organic compounds which can later be used to fuel metabolism.",
    ),
    (
        "Turbocharger",
        "turbo",
        "",
        "A turbocharger is a device that increases an internal combustion engine "
        "power output by forcing extra compressed air into the combustion chamber, "
        "raising output without enlarging displacement.",
    ),
]


#: Per-article provenance, keyed by path. "turbo" deliberately has NONE — the
#: 13% of the real corpus that carries no date must be representable, and the
#: reader has to say so rather than borrowing the archive's date.
_DATES: dict[str, tuple[str | None, int | None]] = {
    "greece": ("2026-08-21", 137056001),
    "eclipse": ("2024-03-09", 120000042),
    "photo": ("2025-11-06", 130500777),
    "turbo": (None, None),
}


def _write_jsonl(path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for title, apath, section, text in _ARTICLES:
            rec: dict[str, object] = {
                "k": "chunk",
                "t": title,
                "p": apath,
                "s": section,
                "x": text,
            }
            edited, rev = _DATES[apath]
            if edited:
                rec["d"] = edited
            if rev is not None:
                rec["r"] = rev
            fh.write(json.dumps(rec) + "\n")


@pytest.fixture()
def corpus_db(tmp_path: Path) -> Path:
    jsonl = tmp_path / "in.jsonl"
    db = tmp_path / "corpus.db"
    _write_jsonl(jsonl)
    # The archive date now lives on the SOURCE row, supplied by the extractor's
    # sidecar, so a partial refresh cannot relabel articles it never touched.
    (tmp_path / "in.jsonl.meta.json").write_text(
        json.dumps(
            {"source_name": "wikipedia_en_test_2026-08", "archive_date": "2026-08-25"}
        ),
        encoding="utf-8",
    )
    build([str(jsonl)], str(db))
    write_manifest(str(db), str(default_manifest_path(db)))
    return db


def _fake_embed(texts: list[str]) -> np.ndarray:
    """Deterministic bag-of-words unit vectors — shared words mean similar."""
    import zlib as _z

    dim = 256
    out = np.zeros((len(texts), dim), dtype=np.float32)
    for i, text in enumerate(texts):
        for word in text.lower().split():
            out[i, _z.crc32(word.encode()) % dim] += 1.0
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (out / norms).astype(np.float32)


class TestRoundTrip:
    def test_text_survives_compression_exactly(self, corpus_db: Path) -> None:
        """A zlib preset dictionary is easy to get subtly wrong, and a wrong
        dictionary yields plausible-but-corrupt text rather than an error."""
        with ReferenceCorpus(corpus_db) as corpus:
            hits = corpus.search("photosynthesis phototrophic organisms", k=1)
            assert hits, "no hit for a phrase that is present verbatim"
            expected = next(a[3] for a in _ARTICLES if a[0] == "Photosynthesis")
            assert hits[0].text == expected

    def test_metadata_is_carried(self, corpus_db: Path) -> None:
        with ReferenceCorpus(corpus_db) as corpus:
            assert corpus.snapshot_date in ("2026-08-25", "unknown")
            assert corpus.article_count == 4  # 5 chunks across 4 distinct paths
            assert corpus.chunk_count == 5

    def test_citation_names_the_articles_own_date_not_the_archives(
        self, corpus_db: Path
    ) -> None:
        """The whole point of #1616's date handling: an article last edited in
        2024 sitting in a 2026 archive must not be presented as 2026 content."""
        with ReferenceCorpus(corpus_db) as corpus:
            hits = corpus.search("moon passes between earth and the sun", k=1)
            assert hits and hits[0].title == "Solar eclipse"
            cite = hits[0].citation(corpus.snapshot_date)
            assert "last edited 2024-03-09" in cite, cite
            assert "rev 120000042" in cite, cite
            # the archive date is still present, answering a DIFFERENT question
            assert "2026-08-25" in cite, cite

    def test_an_article_without_a_date_says_so_rather_than_borrowing_one(
        self, corpus_db: Path
    ) -> None:
        """Back-filling the archive date here would be the exact misdirection
        the per-article date exists to remove."""
        with ReferenceCorpus(corpus_db) as corpus:
            hits = corpus.search("turbocharger compressed air combustion", k=1)
            assert hits and hits[0].title == "Turbocharger"
            assert hits[0].last_edited is None
            assert hits[0].revision_id is None
            cite = hits[0].citation(corpus.snapshot_date)
            assert "not recorded" in cite, cite
            assert "last edited 2026-08-25" not in cite, cite

    def test_dates_survive_the_reranker(self, corpus_db: Path) -> None:
        """The re-rank path rebuilds every hit — an easy place to drop a field."""
        with ReferenceCorpus(corpus_db, embed_fn=_fake_embed) as corpus:
            hits = corpus.search("Mycenaean Bronze Age collapse", k=2)
            assert hits
            top = next(h for h in hits if h.title == "Ancient Greece")
            assert top.last_edited == "2026-08-21"
            assert top.revision_id == 137056001


class TestSearch:
    def test_finds_the_right_article(self, corpus_db: Path) -> None:
        with ReferenceCorpus(corpus_db) as corpus:
            hits = corpus.search("moon passes between earth and the sun", k=1)
            assert hits and hits[0].title == "Solar eclipse"

    def test_returns_nothing_rather_than_padding(self, corpus_db: Path) -> None:
        """A caller that always receives k hits cannot tell coverage from noise."""
        with ReferenceCorpus(corpus_db) as corpus:
            assert corpus.search("zzzzqqqq nonexistentterm", k=3) == []

    def test_char_budget_is_enforced(self, corpus_db: Path) -> None:
        with ReferenceCorpus(corpus_db) as corpus:
            hits = corpus.search("Greece Greek", k=5, max_chars=200)
            assert len(hits) == 1, "budget did not stop the second chunk"

    def test_vector_score_is_none_without_an_embedder(self, corpus_db: Path) -> None:
        """Honestly unmeasured, never a fabricated confidence value."""
        with ReferenceCorpus(corpus_db) as corpus:
            hits = corpus.search("solar eclipse", k=1)
            assert hits and hits[0].vector_score is None

    def test_reranker_reorders_and_scores(self, corpus_db: Path) -> None:
        with ReferenceCorpus(corpus_db, embed_fn=_fake_embed) as corpus:
            hits = corpus.search("engine compressed air combustion chamber", k=2)
            assert hits
            assert hits[0].title == "Turbocharger"
            assert hits[0].vector_score is not None
            assert -1.0 - 1e-6 <= hits[0].vector_score <= 1.0 + 1e-6
            scores = [h.vector_score for h in hits]
            assert scores == sorted(scores, reverse=True), "not ordered by relevance"

    def test_candidate_pool_is_bounded(self, corpus_db: Path) -> None:
        """An encyclopedia's common term matches millions of rows; the SQL must
        never fetchall() them (the failure #1617 recorded on the other tier)."""
        with ReferenceCorpus(corpus_db) as corpus:
            hits = corpus.search("Greece eclipse photosynthesis turbocharger", k=4, candidates=2)
            assert len(hits) <= 2

    @pytest.mark.parametrize(
        "query",
        ['it is a "test"', "AND OR NOT", "*", "col:umn", "", "   ", "-", "()"],
    )
    def test_hostile_queries_do_not_raise(self, corpus_db: Path, query: str) -> None:
        """FTS5 treats punctuation as query syntax, so a raw string is both an
        injection surface and an OperationalError waiting for an apostrophe."""
        with ReferenceCorpus(corpus_db) as corpus:
            assert isinstance(corpus.search(query, k=2), list)

    def test_match_expr_strips_syntax(self) -> None:
        expr = fts_match_expr('drop table; "x" AND *')
        assert ";" not in expr
        assert "*" not in expr


class TestFailsClosed:
    def test_missing_store_refuses(self, tmp_path: Path) -> None:
        with pytest.raises(CorpusError, match="not found"):
            ReferenceCorpus(tmp_path / "nope.db")

    def test_unknown_schema_version_refuses(self, corpus_db: Path) -> None:
        """Reading an unrecognised layout on a guess returns plausible text from
        the wrong offsets, which is worse than refusing."""
        db = sqlite3.connect(corpus_db)
        db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        db.commit()
        db.close()
        # Re-sign so the refusal under test is the schema check, not integrity.
        write_manifest(str(corpus_db), str(default_manifest_path(corpus_db)))
        with pytest.raises(CorpusError, match="schema"):
            ReferenceCorpus(corpus_db)

    def test_manifest_mismatch_refuses_to_serve(
        self, corpus_db: Path, tmp_path: Path
    ) -> None:
        manifest = tmp_path / "corpus.manifest.json"
        manifest.write_text(json.dumps({"sha256": "00" * 32}), encoding="utf-8")
        with pytest.raises(CorpusError, match="integrity"):
            ReferenceCorpus(corpus_db, manifest_path=manifest)

    def test_matching_manifest_opens(self, corpus_db: Path, tmp_path: Path) -> None:
        """The toggle half: the probe must PASS on an intact store, or the
        failure case above proves only that the reader can raise."""
        digest = hashlib.sha256(corpus_db.read_bytes()).hexdigest()
        manifest = tmp_path / "corpus.manifest.json"
        manifest.write_text(json.dumps({"sha256": digest}), encoding="utf-8")
        with ReferenceCorpus(corpus_db, manifest_path=manifest) as corpus:
            assert corpus.chunk_count == 5

    def test_missing_manifest_refuses_when_one_is_demanded(
        self, corpus_db: Path, tmp_path: Path
    ) -> None:
        with pytest.raises(CorpusError, match="manifest missing"):
            ReferenceCorpus(corpus_db, manifest_path=tmp_path / "absent.json")

    def test_no_manifest_beside_the_store_refuses(self, corpus_db: Path) -> None:
        """#1616 pre-merge review finding 2: an empty ``manifest_path`` used to
        open the store UNVERIFIED. Now the default is the builder's manifest
        beside the store, and its absence is a refusal, not a skip."""
        default_manifest_path(corpus_db).unlink()
        with pytest.raises(CorpusError, match="manifest missing"):
            ReferenceCorpus(corpus_db)

    def test_default_manifest_is_verified_not_just_present(self, corpus_db: Path) -> None:
        """The default manifest is VERIFIED: a wrong digest there refuses exactly
        like an explicit one."""
        default_manifest_path(corpus_db).write_text(
            json.dumps({"sha256": "00" * 32}), encoding="utf-8"
        )
        with pytest.raises(CorpusError, match="integrity"):
            ReferenceCorpus(corpus_db)

    def test_verified_reader_handoff_skips_rehash(
        self, corpus_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second reader of the same bytes may reuse a verification rather than
        re-hash the file, and only by holding the verified reader."""
        first = ReferenceCorpus(corpus_db)
        calls: list[Path] = []
        monkeypatch.setattr(
            ReferenceCorpus, "_verify", lambda self, m: calls.append(m) or "x"
        )
        with ReferenceCorpus(corpus_db, verified_by=first) as second:
            assert second.verified_sha256 == first.verified_sha256
        assert calls == []
        first.close()

    def test_verified_reader_of_another_store_refuses(
        self, corpus_db: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "other.db"
        other.write_bytes(corpus_db.read_bytes())
        write_manifest(str(other), str(default_manifest_path(other)))
        with ReferenceCorpus(other) as verified_other:
            with pytest.raises(CorpusError, match="same store"):
                ReferenceCorpus(corpus_db, verified_by=verified_other)

    def test_verified_by_and_manifest_together_refuse(
        self, corpus_db: Path
    ) -> None:
        with ReferenceCorpus(corpus_db) as first:
            with pytest.raises(CorpusError, match="not both"):
                ReferenceCorpus(
                    corpus_db,
                    manifest_path=default_manifest_path(corpus_db),
                    verified_by=first,
                )

    def test_store_is_opened_read_only(self, corpus_db: Path) -> None:
        """A retrieval tier must not be able to mutate its own corpus."""
        with ReferenceCorpus(corpus_db) as corpus:
            with pytest.raises(sqlite3.OperationalError):
                corpus._db.execute("DELETE FROM chunks")
