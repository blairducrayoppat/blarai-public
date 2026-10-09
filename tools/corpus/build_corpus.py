"""Build the read-only reference-corpus store from extractor JSONL (#1616).

Imports NOTHING from the ZIM ecosystem: ``libzim`` is GPL-3.0-or-later and this
tree ships PolyForm Noncommercial plus a commercial licence. The seam is JSONL,
which is data. An ``import libzim`` added anywhere here re-creates the licensing
problem the split exists to prevent.

Compression is ``zlib`` from the standard library rather than zstd: zstd would
buy roughly 15% on this corpus, which does not justify a new runtime dependency
in a system whose dependencies are governed. Short chunks compress badly alone,
so a preset dictionary trained on a corpus sample is stored in ``meta`` and used
for every chunk — most of the gap, with per-chunk random access preserved.

Usage:
  python -m tools.corpus.build_corpus <in.jsonl[.zst] …> <out.db>
      [--source-sha256 …] [--manifest PATH]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sqlite3
import sys
import time
import zlib
from pathlib import Path

#: Bumped whenever the schema or the chunking contract changes. The reader
#: refuses a store whose version it does not recognise rather than guessing at
#: an older layout and returning plausible text from the wrong offsets.
SCHEMA_VERSION: int = 3

_ZDICT_BYTES: int = 32 * 1024
_ZLEVEL: int = 6

_SCHEMA = """
PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;

-- A corpus is built from one or more SOURCES and may be refreshed in parts.
-- The archive date belongs HERE, per source, not once for the whole store: a
-- partial refresh from a newer archive must not relabel the articles it did
-- not touch. That is the same defect as stamping one date on every article,
-- one level up.
CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    kind          TEXT NOT NULL DEFAULT 'wikipedia',
    archive_date  TEXT,
    source_sha256 TEXT,
    ingested_utc  TEXT NOT NULL
);

-- last_edited / revision_id are PER-ARTICLE provenance from the source, NOT
-- the archive's build date: 99.2% of articles were last edited before the
-- archive was assembled, so one corpus-wide date overstates the currency of
-- almost everything. NULL means the source carried no date and is reported as
-- unknown, never back-filled — a substituted date is a confident lie.
-- UNIQUE(source_id, path) is the update identity: a re-ingest replaces.
CREATE TABLE IF NOT EXISTS articles (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES sources(id),
    path        TEXT NOT NULL,
    title       TEXT NOT NULL,
    last_edited TEXT,
    revision_id INTEGER,
    UNIQUE(source_id, path)
);

CREATE TABLE IF NOT EXISTS chunks (
    id         INTEGER PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id),
    ordinal    INTEGER NOT NULL DEFAULT 0,
    section    TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL DEFAULT 'prose',
    z          BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_article ON chunks(article_id);

-- contentless FTS5: the index alone. The text lives once, compressed, in
-- chunks.z; an ordinary FTS5 table would store a second uncompressed copy of
-- every passage. contentless_delete=1 (SQLite 3.43+) is what makes a PARTIAL
-- refresh possible at all — without it a contentless index cannot delete, so a
-- re-ingested article's superseded text would keep being served forever.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
    USING fts5(body, content='', contentless_delete=1, tokenize='porter unicode61');

-- Redirects are 36% of the archive and are Wikipedia's alias system. Without
-- them a reader searching the common name ("JFK") finds nothing.
CREATE TABLE IF NOT EXISTS aliases (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES sources(id),
    alias       TEXT NOT NULL,
    target_path TEXT NOT NULL,
    anchor      TEXT
);
CREATE INDEX IF NOT EXISTS idx_aliases_alias ON aliases(alias);
CREATE INDEX IF NOT EXISTS idx_aliases_target ON aliases(source_id, target_path);

-- Image paths per article, so the later images work can locate bytes in the
-- retained archive. Paths only; no bytes are copied here.
CREATE TABLE IF NOT EXISTS article_images (
    article_id INTEGER NOT NULL REFERENCES articles(id),
    ordinal    INTEGER NOT NULL,
    path       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_article_images ON article_images(article_id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _open_jsonl(path: str) -> io.TextIOBase:
    if path.endswith(".zst"):
        import zstandard as zstd  # BUILD-side only, never a runtime import

        return io.TextIOWrapper(
            zstd.ZstdDecompressor().stream_reader(open(path, "rb")), encoding="utf-8"
        )
    return open(path, encoding="utf-8")


def _train_dictionary(paths: list[str]) -> bytes:
    buf = bytearray()
    with _open_jsonl(paths[0]) as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if "x" in rec:
                buf.extend(rec["x"].encode("utf-8"))
            if len(buf) >= _ZDICT_BYTES * 4:
                break
    return bytes(buf[-_ZDICT_BYTES:])


def _compress(text: str, zdict: bytes) -> bytes:
    co = zlib.compressobj(_ZLEVEL, zlib.DEFLATED, -zlib.MAX_WBITS, zdict=zdict)
    return co.compress(text.encode("utf-8")) + co.flush()


def decompress(blob: bytes, zdict: bytes) -> str:
    do = zlib.decompressobj(-zlib.MAX_WBITS, zdict=zdict)
    return (do.decompress(blob) + do.flush()).decode("utf-8")


#: Record kinds the builder knows. An UNRECOGNISED kind is COUNTED and
#: reported, never silently skipped: the previous build swallowed every alias
#: record through a bare `except: continue` because alias lines have no "x"
#: field — 4,327 records in a 400-article test, and ~10M projected, gone with
#: no counter and no log.
_TEXT_KINDS = {"chunk", "facts", "caption"}


def build(
    jsonl_paths: list[str],
    db_path: str,
    source_sha256: str | None = None,
    source_kind: str = "wikipedia",
    with_tables: bool = True,
) -> dict:
    """Build the store. ``with_tables=False`` skips table records at BUILD time.

    The extractor also has a --no-tables flag, but an extraction-time switch
    alone would make "drop tables later" a three-hour re-extraction rather than
    the two-hour rebuild #1639 assumes. Keeping the records in the JSONL and
    filtering here is what makes that reversal actually cheap.
    """
    t0 = time.perf_counter()
    zdict = _train_dictionary(jsonl_paths)

    db = sqlite3.connect(db_path)
    db.executescript(_SCHEMA)

    # One source row per extractor shard-set, from the sidecar metadata. Every
    # shard's sidecar is read, and the fields that tie a store to the code that
    # extracted it must AGREE across shards (G2): a store assembled from shards
    # of two different extractions is refused, not averaged.
    provenance = _shard_provenance(jsonl_paths)
    src_meta = provenance["first_sidecar"]
    source_name = src_meta.get("source_name") or Path(jsonl_paths[0]).stem
    archive_date = src_meta.get("archive_date", "unknown")
    extraction_with_tables = provenance["with_tables"]
    effective_with_tables = with_tables and extraction_with_tables != "0"
    db.execute(
        "INSERT OR IGNORE INTO sources(name,kind,archive_date,source_sha256,ingested_utc)"
        " VALUES(?,?,?,?,?)",
        (source_name, source_kind, archive_date, source_sha256 or "",
         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
    )
    source_id = db.execute(
        "SELECT id FROM sources WHERE name=?", (source_name,)
    ).fetchone()[0]

    article_ids: dict[str, int] = {}
    stats = dict(
        articles=0, dated=0, chunks=0, facts=0, captions=0, aliases=0,
        image_refs=0, unknown_kind=0, malformed=0, raw_chars=0, comp_bytes=0,
        tables=0, tables_skipped=0,
    )
    next_article = 1
    next_chunk = 1
    art_rows: list[tuple] = []
    chunk_rows: list[tuple] = []
    fts_rows: list[tuple] = []
    alias_rows: list[tuple] = []
    image_rows: list[tuple] = []

    def flush() -> None:
        if art_rows:
            db.executemany(
                "INSERT OR IGNORE INTO articles"
                "(id,source_id,path,title,last_edited,revision_id) VALUES(?,?,?,?,?,?)",
                art_rows,
            )
            art_rows.clear()
        if chunk_rows:
            db.executemany(
                "INSERT INTO chunks(id,article_id,ordinal,section,kind,z)"
                " VALUES(?,?,?,?,?,?)",
                chunk_rows,
            )
            chunk_rows.clear()
        if fts_rows:
            db.executemany("INSERT INTO chunks_fts(rowid, body) VALUES(?,?)", fts_rows)
            fts_rows.clear()
        if alias_rows:
            db.executemany(
                "INSERT INTO aliases(source_id,alias,target_path,anchor)"
                " VALUES(?,?,?,?)",
                alias_rows,
            )
            alias_rows.clear()
        if image_rows:
            db.executemany(
                "INSERT INTO article_images(article_id,ordinal,path) VALUES(?,?,?)",
                image_rows,
            )
            image_rows.clear()

    def article_id_for(rec: dict) -> int:
        nonlocal next_article
        path = rec["p"]
        aid = article_ids.get(path)
        if aid is None:
            aid = next_article
            article_ids[path] = aid
            art_rows.append(
                (aid, source_id, path, rec.get("t", path), rec.get("d"), rec.get("r"))
            )
            next_article += 1
            stats["articles"] += 1
            if rec.get("d"):
                stats["dated"] += 1
        return aid

    for jsonl_path in jsonl_paths:
        with _open_jsonl(jsonl_path) as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    stats["malformed"] += 1
                    continue
                kind = rec.get("k")

                if kind == "alias":
                    if rec.get("a") and rec.get("p"):
                        alias_rows.append(
                            (source_id, rec["a"], rec["p"], rec.get("h"))
                        )
                        stats["aliases"] += 1
                    else:
                        stats["malformed"] += 1
                elif kind == "images":
                    paths = rec.get("paths") or []
                    if rec.get("p") and paths:
                        aid = article_id_for(rec)
                        for i, p in enumerate(paths):
                            image_rows.append((aid, i, p))
                        stats["image_refs"] += len(paths)
                    else:
                        stats["malformed"] += 1
                elif kind in _TEXT_KINDS:
                    if rec.get("tbl") and not with_tables:
                        stats["tables_skipped"] += 1
                        continue
                    text = rec.get("x")
                    if not text or not rec.get("p"):
                        stats["malformed"] += 1
                        continue
                    aid = article_id_for(rec)
                    blob = _compress(text, zdict)
                    chunk_kind = (
                        "table" if rec.get("tbl")
                        else "facts" if kind == "facts"
                        else "caption" if kind == "caption"
                        else "prose"
                    )
                    chunk_rows.append(
                        (next_chunk, aid, int(rec.get("o", 0)),
                         rec.get("s", ""), chunk_kind, blob)
                    )
                    # rowid ties the contentless index to chunks.id — the ONLY
                    # link between a search hit and its text.
                    fts_rows.append((next_chunk, text))
                    next_chunk += 1
                    stats["chunks"] += 1
                    stats["facts"] += kind == "facts"
                    stats["captions"] += kind == "caption"
                    stats["tables"] += bool(rec.get("tbl"))
                    stats["raw_chars"] += len(text)
                    stats["comp_bytes"] += len(blob)
                else:
                    # LOUD, not silent. This is the branch that ate every alias.
                    stats["unknown_kind"] += 1

                if len(chunk_rows) >= 20_000 or len(alias_rows) >= 50_000:
                    flush()
    flush()

    db.executemany(
        "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
        [
            ("schema_version", str(SCHEMA_VERSION)),
            ("zdict_b64", base64.b64encode(zdict).decode("ascii")),
            ("chunk_count", str(stats["chunks"])),
            ("article_count", str(stats["articles"])),
            ("alias_count", str(stats["aliases"])),
            ("with_tables", "1" if effective_with_tables else "0"),
            ("build_with_tables", "1" if with_tables else "0"),
            ("extraction_with_tables", extraction_with_tables),
            ("repo_commit", provenance["repo_commit"]),
            ("extract_rules_sha256", provenance["extract_rules_sha256"]),
            ("articles_with_edit_date", str(stats["dated"])),
            ("built_utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        ],
    )
    db.commit()
    db.execute("PRAGMA optimize")
    db.close()

    size = Path(db_path).stat().st_size
    return {
        **stats,
        "db_bytes": size,
        "bytes_per_chunk": round(size / max(1, stats["chunks"]), 1),
        "text_ratio": round(stats["comp_bytes"] / max(1, stats["raw_chars"]), 4),
        "source_name": source_name,
        "archive_date": archive_date,
        "with_tables": effective_with_tables,
        "repo_commit": provenance["repo_commit"],
        "extract_rules_sha256": provenance["extract_rules_sha256"],
        "seconds": round(time.perf_counter() - t0, 1),
    }


#: Sidecar fields that tie a store to the extraction that produced it (G2).
_PROVENANCE_FIELDS: tuple[str, ...] = ("repo_commit", "extract_rules_sha256", "with_tables")


def _shard_provenance(jsonl_paths: list[str]) -> dict:
    """Read every shard's ``<shard>.meta.json`` and reconcile the G2 fields.

    Returns the first sidecar (for source name and archive date) and, for each
    provenance field, the single value the sidecars agree on, rendered as a
    string (``"1"``/``"0"`` for ``with_tables``), or ``"unknown"`` when no
    sidecar carries it. Raises ``ValueError`` when two sidecars carry
    DIFFERENT values for a field: a store must describe one extraction.
    A field missing from every sidecar is reported on stderr, because a store
    that cannot name its rules cannot be tied to a baseline.
    """
    sidecars: list[tuple[str, dict]] = []
    missing: list[str] = []
    for path in jsonl_paths:
        meta_path = Path(path + ".meta.json")
        if meta_path.is_file():
            sidecars.append((path, json.loads(meta_path.read_text(encoding="utf-8"))))
        else:
            missing.append(path)
    if sidecars and missing:
        raise ValueError(
            "shards with no sidecar alongside shards that have one: "
            + ", ".join(missing)
            + " -- the store would sign provenance for text it cannot vouch for"
        )
    reconciled: dict = {"first_sidecar": sidecars[0][1] if sidecars else {}}
    for field in _PROVENANCE_FIELDS:
        seen: dict[str, str] = {}
        for path, meta in sidecars:
            if field not in meta or meta[field] is None:
                continue
            value = meta[field]
            if field == "with_tables":
                falsy = isinstance(value, str) and value.strip().lower() in {"", "0", "false", "no"}
                value = "0" if (falsy or not value) else "1"
            seen[str(value)] = path
        if len(seen) > 1:
            raise ValueError(
                f"shard sidecars disagree on {field}: "
                + ", ".join(f"{v!r} in {p}" for v, p in sorted(seen.items()))
                + " -- refusing to build one store from two extractions"
            )
        if seen:
            reconciled[field] = next(iter(seen))
        else:
            reconciled[field] = "unknown"
            print(
                f"WARNING: no shard sidecar records {field}; the store will say 'unknown'",
                file=sys.stderr,
            )
    return reconciled


def write_manifest(db_path: str, manifest_path: str, extra: dict | None = None) -> str:
    """Write the integrity manifest the runtime reader verifies against.

    The corpus is integrity-signed rather than encrypted (LA decision D1): it is
    public content, so confidentiality buys nothing and a decrypt on every read
    costs latency — but INTEGRITY still matters, because a corrupted or swapped
    store feeds the assistant plausible text from nowhere WITH a citation
    attached. The reader refuses on a mismatch; this file is the other half.
    """
    digest = hashlib.sha256()
    with open(db_path, "rb") as fh:
        for block in iter(lambda: fh.read(8 << 20), b""):
            digest.update(block)
    payload = {
        "sha256": digest.hexdigest(),
        "schema_version": SCHEMA_VERSION,
        "bytes": Path(db_path).stat().st_size,
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **(extra or {}),
    }
    Path(manifest_path).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return payload["sha256"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help="JSONL shard(s), last arg is the DB")
    ap.add_argument("--source-sha256", default=None)
    ap.add_argument("--source-kind", default="wikipedia")
    ap.add_argument("--manifest", default=None)
    ap.add_argument(
        "--no-tables",
        action="store_true",
        help="skip table records already present in the JSONL, so dropping "
             "tables is a rebuild rather than a re-extraction",
    )
    args = ap.parse_args(argv)
    *jsonl, db_path = args.inputs
    if not jsonl:
        print("need at least one JSONL input and an output DB", file=sys.stderr)
        return 2
    if Path(db_path).exists():
        print(f"refusing to overwrite existing store: {db_path}", file=sys.stderr)
        return 2
    stats = build(jsonl, db_path, args.source_sha256, args.source_kind,
                  with_tables=not args.no_tables)
    manifest = args.manifest or (db_path + ".manifest.json")
    stats["manifest"] = manifest
    stats["sha256"] = write_manifest(
        db_path,
        manifest,
        {
            "archive_date": stats["archive_date"],
            "rules_sha256": stats["extract_rules_sha256"],
            "repo_commit": stats["repo_commit"],
            "with_tables": stats["with_tables"],
        },
    )
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
