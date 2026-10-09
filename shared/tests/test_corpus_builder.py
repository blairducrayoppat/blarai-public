"""Regression tests for the corpus store builder (#1616).

**Why this file exists.** The builder dispatched on record kind inside a bare
``except Exception: continue``. Alias records carry no ``x`` field, so every
one of them raised and was swallowed: 4,327 records in a 400-article trial,
about ten million projected, gone with no counter, no log and no difference in
the exit code. The same catch-all would have eaten any malformed article line.

A silent drop is the worst failure this pipeline has, because the output still
looks like a corpus. Every test below asserts that a record the builder cannot
use is COUNTED — ``unknown_kind`` or ``malformed`` — rather than disappearing.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.corpus.build_corpus import SCHEMA_VERSION, build, decompress


def _jsonl(tmp_path: Path, *records: dict) -> str:
    path = tmp_path / "in.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return str(path)


def _build(tmp_path: Path, *records: dict) -> tuple[dict, sqlite3.Connection]:
    db_path = tmp_path / "corpus.db"
    stats = build([_jsonl(tmp_path, *records)], str(db_path))
    return stats, sqlite3.connect(db_path)


ARTICLE = {"k": "chunk", "t": "Dog", "p": "Dog", "s": "", "o": 0,
           "x": "The dog is a domesticated descendant of the grey wolf."}


class TestAliasesSurviveTheBuild:
    """Finding 8c: every alias record was silently eaten by a catch-all."""

    def test_an_alias_becomes_a_row_and_is_counted(self, tmp_path: Path) -> None:
        stats, db = _build(
            tmp_path, ARTICLE, {"k": "alias", "a": "JFK", "p": "John_F._Kennedy"}
        )
        rows = db.execute("SELECT alias, target_path, anchor FROM aliases").fetchall()
        assert rows == [("JFK", "John_F._Kennedy", None)]
        assert stats["aliases"] == 1
        assert stats["unknown_kind"] == 0
        assert stats["malformed"] == 0

    def test_a_stub_anchor_is_stored_with_its_alias(self, tmp_path: Path) -> None:
        _, db = _build(
            tmp_path, ARTICLE,
            {"k": "alias", "a": "Perch (fish)", "p": "Perch", "h": "Species"},
        )
        assert db.execute("SELECT anchor FROM aliases").fetchone() == ("Species",)

    def test_an_alias_does_not_invent_an_article(self, tmp_path: Path) -> None:
        """An alias names a target; it is not evidence the target was extracted."""
        stats, db = _build(tmp_path, {"k": "alias", "a": "JFK", "p": "John_F._Kennedy"})
        assert stats["articles"] == 0
        assert db.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0


class TestUnusableRecordsAreCountedNotDropped:
    @pytest.mark.parametrize(
        "record",
        [
            pytest.param({"k": "alias", "a": "JFK"}, id="alias-without-target"),
            pytest.param({"k": "alias", "p": "John_F._Kennedy"}, id="alias-without-name"),
            pytest.param({"k": "images", "p": "Dog", "paths": []}, id="images-empty"),
            pytest.param({"k": "images", "paths": ["a.webp"]}, id="images-without-path"),
            pytest.param({"k": "chunk", "p": "Dog", "x": ""}, id="chunk-empty-text"),
            pytest.param({"k": "chunk", "x": "text"}, id="chunk-without-path"),
        ],
    )
    def test_a_malformed_record_increments_malformed(
        self, tmp_path: Path, record: dict
    ) -> None:
        stats, _ = _build(tmp_path, ARTICLE, record)
        assert stats["malformed"] == 1, f"{record} vanished without a counter"

    def test_an_unreadable_line_increments_malformed(self, tmp_path: Path) -> None:
        path = tmp_path / "in.jsonl"
        path.write_text(json.dumps(ARTICLE) + "\n{not json\n", encoding="utf-8")
        stats = build([str(path)], str(tmp_path / "corpus.db"))
        assert stats["malformed"] == 1

    @pytest.mark.parametrize("kind", ["video", "", None])
    def test_an_unknown_kind_increments_unknown_kind(
        self, tmp_path: Path, kind: str | None
    ) -> None:
        stats, _ = _build(tmp_path, ARTICLE, {"k": kind, "p": "Dog", "x": "hello"})
        assert stats["unknown_kind"] == 1
        assert stats["chunks"] == 1  # only the real article


class TestTextIsRetrievable:
    def test_a_chunk_round_trips_through_compression(self, tmp_path: Path) -> None:
        stats, db = _build(tmp_path, ARTICLE)
        zdict = db.execute("SELECT value FROM meta WHERE key='zdict_b64'").fetchone()[0]
        import base64

        blob, = db.execute("SELECT z FROM chunks").fetchone()
        assert decompress(blob, base64.b64decode(zdict)) == ARTICLE["x"]
        assert stats["chunks"] == 1

    def test_a_search_hit_resolves_to_its_own_chunk(self, tmp_path: Path) -> None:
        """rowid is the ONLY link between a contentless index and the text."""
        other = {**ARTICLE, "o": 1, "x": "Cats are obligate carnivores, unlike dogs."}
        _, db = _build(tmp_path, ARTICLE, other)
        hits = db.execute(
            "SELECT c.ordinal FROM chunks_fts f JOIN chunks c ON c.id = f.rowid"
            " WHERE chunks_fts MATCH 'carnivores'"
        ).fetchall()
        assert hits == [(1,)]

    def test_record_kinds_land_in_their_own_chunk_kind(self, tmp_path: Path) -> None:
        _, db = _build(
            tmp_path,
            ARTICLE,
            {"k": "facts", "t": "Dog", "p": "Dog", "o": 1, "x": "Family = Canidae"},
            {"k": "caption", "t": "Dog", "p": "Dog", "o": 2, "x": "A dog", "i": "d.webp"},
            {**ARTICLE, "o": 3, "x": "Breed | Origin", "tbl": 1},
        )
        kinds = dict(
            db.execute("SELECT kind, COUNT(*) FROM chunks GROUP BY kind").fetchall()
        )
        assert kinds == {"prose": 1, "facts": 1, "caption": 1, "table": 1}


class TestStoreProvenance:
    def test_the_schema_version_is_recorded(self, tmp_path: Path) -> None:
        _, db = _build(tmp_path, ARTICLE)
        version = db.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert version == str(SCHEMA_VERSION)

    def test_an_article_without_a_date_is_stored_as_unknown_never_backfilled(
        self, tmp_path: Path
    ) -> None:
        stats, db = _build(tmp_path, ARTICLE)
        assert db.execute("SELECT last_edited FROM articles").fetchone() == (None,)
        assert stats["dated"] == 0

    def test_images_are_recorded_in_document_order(self, tmp_path: Path) -> None:
        _, db = _build(
            tmp_path, ARTICLE,
            {"k": "images", "t": "Dog", "p": "Dog", "paths": ["a.webp", "b.webp"]},
        )
        rows = db.execute(
            "SELECT ordinal, path FROM article_images ORDER BY ordinal"
        ).fetchall()
        assert rows == [(0, "a.webp"), (1, "b.webp")]


class TestTablesCanBeDroppedAtBuildTime:
    """#1639 claims dropping tables later is a cheap rebuild. That is only true
    if the BUILDER can skip them: with an extraction-time flag alone, the
    reversal would cost a three-hour re-extraction instead of a two-hour
    rebuild. The table records stay in the JSONL and are filtered here."""

    @staticmethod
    def _records() -> list[dict]:
        return [
            {"k": "chunk", "t": "Ohio", "p": "ohio", "s": "", "o": 0,
             "x": "Ohio is a state in the Midwestern region of the United States, "
                  "bordered by Lake Erie to the north and the Ohio River to the south."},
            {"k": "chunk", "t": "Ohio", "p": "ohio", "s": "Results", "o": 1, "tbl": 1,
             "x": "County | Votes | % \nFranklin | 412,000 | 64.9\nCuyahoga | 398,000 | 66.2"},
        ]

    def _build(self, tmp_path, with_tables):
        jsonl = tmp_path / f"in_{with_tables}.jsonl"
        with open(jsonl, "w", encoding="utf-8") as fh:
            for rec in self._records():
                fh.write(json.dumps(rec) + "\n")
        (tmp_path / f"in_{with_tables}.jsonl.meta.json").write_text(
            json.dumps({"source_name": "s", "archive_date": "2026-08-25"}),
            encoding="utf-8",
        )
        db = tmp_path / f"c_{with_tables}.db"
        return db, build([str(jsonl)], str(db), with_tables=with_tables)

    def test_tables_are_included_by_default(self, tmp_path: Path) -> None:
        db, stats = self._build(tmp_path, True)
        assert stats["tables"] == 1 and stats["tables_skipped"] == 0
        kinds = [r[0] for r in sqlite3.connect(db).execute(
            "SELECT kind FROM chunks").fetchall()]
        assert "table" in kinds

    def test_tables_can_be_skipped_without_re_extracting(self, tmp_path: Path) -> None:
        db, stats = self._build(tmp_path, False)
        assert stats["tables"] == 0
        assert stats["tables_skipped"] == 1, "the table record was not skipped"
        assert stats["chunks"] == 1, "prose should survive"
        kinds = [r[0] for r in sqlite3.connect(db).execute(
            "SELECT kind FROM chunks").fetchall()]
        assert "table" not in kinds

    def test_the_store_records_which_way_it_was_built(self, tmp_path: Path) -> None:
        """A store that cannot say whether it holds tables cannot be compared
        against a baseline measured on one that did."""
        for flag, expected in ((True, "1"), (False, "0")):
            db, _ = self._build(tmp_path, flag)
            got = sqlite3.connect(db).execute(
                "SELECT value FROM meta WHERE key='with_tables'").fetchone()
            assert got == (expected,)


class TestTheStoreNamesItsExtraction:
    """#1616 pre-merge review finding 3 (G2): the builder read only the first
    shard's sidecar and dropped repo_commit / extract_rules_sha256, and
    ``meta.with_tables`` recorded the BUILD flag even when the extraction had
    dropped tables. A store must name the extraction it was built from."""

    _REC = {"k": "chunk", "t": "Ohio", "p": "ohio", "s": "", "o": 0,
            "x": "Ohio is a state in the Midwestern region of the United States, "
                 "bordered by Lake Erie to the north and the Ohio River to the south."}

    def _shard(self, tmp_path: Path, name: str, sidecar: dict) -> str:
        path = tmp_path / f"{name}.jsonl"
        rec = dict(self._REC, p=f"ohio-{name}", t=f"Ohio {name}")
        path.write_text(json.dumps(rec) + "\n", encoding="utf-8")
        (tmp_path / f"{name}.jsonl.meta.json").write_text(
            json.dumps({"source_name": "s", "archive_date": "2026-08-25", **sidecar}),
            encoding="utf-8",
        )
        return str(path)

    _TIE = {"repo_commit": "abc123", "extract_rules_sha256": "f" * 64, "with_tables": True}

    def test_agreeing_sidecars_are_written_into_the_store(self, tmp_path: Path) -> None:
        from shared.corpus import ReferenceCorpus, default_manifest_path
        from tools.corpus.build_corpus import write_manifest

        a = self._shard(tmp_path, "a", self._TIE)
        b = self._shard(tmp_path, "b", self._TIE)
        db = tmp_path / "c.db"
        stats = build([a, b], str(db))
        assert stats["repo_commit"] == "abc123"
        write_manifest(str(db), str(default_manifest_path(db)))
        with ReferenceCorpus(db) as corpus:
            assert corpus.repo_commit == "abc123"
            assert corpus.extract_rules_sha256 == "f" * 64
            assert corpus.with_tables == "1"

    def test_disagreeing_sidecars_are_refused(self, tmp_path: Path) -> None:
        a = self._shard(tmp_path, "a", self._TIE)
        b = self._shard(tmp_path, "b", {**self._TIE, "extract_rules_sha256": "0" * 64})
        with pytest.raises(ValueError, match="disagree on extract_rules_sha256"):
            build([a, b], str(tmp_path / "c.db"))

    def test_disagreement_in_a_later_shard_is_seen(self, tmp_path: Path) -> None:
        """TOGGLE: the old builder read only the FIRST sidecar, so a mismatch in
        the third shard passed. The refusal must come from reading every one."""
        a = self._shard(tmp_path, "a", self._TIE)
        b = self._shard(tmp_path, "b", self._TIE)
        c = self._shard(tmp_path, "c", {**self._TIE, "repo_commit": "zzz999"})
        with pytest.raises(ValueError, match="disagree on repo_commit"):
            build([a, b, c], str(tmp_path / "c.db"))

    def test_a_shard_without_a_sidecar_among_sidecared_shards_is_refused(
        self, tmp_path: Path
    ) -> None:
        """TOGGLE: a shard with no sidecar was merged silently, so the store
        signed the other shards' repo_commit / rules sha for text it could not
        vouch for. Some-but-not-all sidecars must refuse."""
        a = self._shard(tmp_path, "a", self._TIE)
        b = self._shard(tmp_path, "b", self._TIE)
        (tmp_path / "b.jsonl.meta.json").unlink()
        with pytest.raises(ValueError, match="no sidecar"):
            build([a, b], str(tmp_path / "c.db"))

    def test_a_string_false_in_a_sidecar_is_not_read_as_true(self, tmp_path: Path) -> None:
        """TOGGLE: bool("false") is True, so a hand-edited or re-serialised sidecar
        recorded an extraction WITHOUT tables as one with them."""
        a = self._shard(tmp_path, "a", {**self._TIE, "with_tables": "false"})
        db = tmp_path / "c.db"
        build([a], str(db), with_tables=True)
        meta = dict(sqlite3.connect(db).execute("SELECT key, value FROM meta").fetchall())
        assert meta["extraction_with_tables"] == "0"
        assert meta["with_tables"] == "0"

    def test_an_extraction_without_tables_is_not_recorded_as_having_them(
        self, tmp_path: Path
    ) -> None:
        a = self._shard(tmp_path, "a", {**self._TIE, "with_tables": False})
        db = tmp_path / "c.db"
        build([a], str(db), with_tables=True)
        meta = dict(sqlite3.connect(db).execute("SELECT key, value FROM meta").fetchall())
        assert meta["with_tables"] == "0"
        assert meta["build_with_tables"] == "1"
        assert meta["extraction_with_tables"] == "0"

    def test_the_manifest_carries_the_rules_sha(self, tmp_path: Path) -> None:
        from tools.corpus.build_corpus import main

        a = self._shard(tmp_path, "a", self._TIE)
        db = tmp_path / "c.db"
        assert main([a, str(db)]) == 0
        manifest = json.loads((tmp_path / "c.db.manifest.json").read_text(encoding="utf-8"))
        assert manifest["rules_sha256"] == "f" * 64
        assert manifest["repo_commit"] == "abc123"
