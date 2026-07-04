"""
Personal Knowledge Substrate (USE-CASE-002) — MVP slice
========================================================
A locally-hosted, semantically-indexed store of the user's own data that
survives restarts and gives BlarAI persistent memory across sessions. Two
things are indexed:

  * **documents** — every loaded PDF/txt/md, chunked and embedded.
  * **conversation turns** — every PGOV-approved user+assistant pair, embedded,
    so "what did I tell you last week about my sister?" works because the past
    turn is actually retrievable, not because it happened to still be in the
    context window.

On each new prompt the user's text is embedded and the most relevant chunks
(documents + past turns) are retrieved and injected as grounded context — and
because they are untrusted text from the user's own history, they pass through
the same Layer 1 + 2 prompt-injection defences (delimiter neutralisation +
per-load datamarking) that a freshly-loaded document does. That wiring lives in
the Orchestrator; this module owns storage, embedding-orchestration, and search.

Design decisions (recorded in ADR-016):
  * **Embedding model is REUSED**, not added. The store takes an injected
    ``embed_fn`` — the same bge-small-en-v1.5 ONNX embedder the output validator
    (PGOV Stage 5 leakage detector) already loads. One model, one stack.
  * **Storage** is a side SQLite file (``substrate.db``) — one ``substrate_chunks``
    table holding the vector (as a float32 BLOB) alongside its source metadata,
    plus a ``substrate_meta`` table for the embedding dimension/version.
  * **Vector search** is brute-force cosine over L2-normalised vectors (a single
    numpy matrix multiply). At a single user's scale — thousands of 384-dim
    vectors — this is sub-millisecond and needs no extra dependency. HNSW
    (hnswlib) was the planned index but ships no wheel for this Python and would
    not build; brute-force is sufficient here and the search is kept behind a
    private method so an ANN index can slot in unchanged if scale ever demands.
  * **At-rest encryption (Sprint 14, ADR-025)** — ``text``, ``embedding``, and
    ``source`` (filename) are AES-256-GCM encrypted on write and decrypted on
    read. The DEK is dual-wrapped (TPM + offline recovery key). Embeddings are
    decrypted ONCE at unlock into an in-RAM boot cache; ``_search_kind`` runs
    over the plaintext vectors in memory, decrypting only the top-k matched
    text per query. ``source`` uses a deterministic keyed-hash column
    (``source_hash``) so uniqueness/dedup remains functional on ciphertext.
    See ``EncryptedSubstrateStore`` for the encrypted variant.
  * **Isochronous-timing side-channel hardening** (Use Cases §002 ISSUE-007) is
    DEFERRED to the multi-VM architecture, not built — it defends against a
    compromised co-resident agent observing IPC latency, a threat that does not
    exist in single-process BlarAI. Noted, not implemented (ADR-016 §Deferred).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, NamedTuple

logger = logging.getLogger(__name__)


def _harden_db_file_dacl(db_path: str) -> None:
    """Apply the #637 owner-only DACL to the substrate DB file (defense-in-depth).

    DATA_MAP §7 item 1: lock ``substrate.db`` (the assistant's long-term memory)
    to (current user + SYSTEM) full control on top of the at-rest encryption.
    Owner-preserving + fail-safe (``shared.security.file_dacl`` never raises and
    never blocks access).  A no-op for ``:memory:`` stores and on non-Windows
    hosts.  Called after ``sqlite3.connect`` so the DB file exists on disk.
    """
    if db_path == ":memory:":
        return
    from shared.security.file_dacl import ensure_owner_only_dacl

    ensure_owner_only_dacl(db_path)

EMBED_DIM: int = 384

# Chunking defaults. Tokens are approximated as ~4 characters, so ~512 tokens is
# ~2048 chars with ~64-token (~256 char) overlap — the redirect's default.
CHUNK_CHARS: int = 2048
CHUNK_OVERLAP_CHARS: int = 256

# Retrieval defaults: a small budget split between documents and past turns.
DEFAULT_K_DOCS: int = 2
DEFAULT_K_TURNS: int = 4

# Embedding-cache idle-unload (Vikunja #611, ADR-025 §3 / feasibility study §3
# mitigation 2). The decrypted embedding matrix is the largest and longest-lived
# plaintext-derived secret in RAM; dropping it after a window of retrieval
# inactivity (and zeroing the numpy buffers in place) shrinks both the
# live-memory exposure window AND the 32 GB footprint, reloading lazily on the
# next retrieval. Default 900 s (15 min). A value <= 0 DISABLES idle-unload
# entirely (today's always-resident behaviour). The default is a placeholder
# sized to the first-query-after-idle re-decrypt cost, which is an on-box
# measurement (Testing-Data-Capture rule) — see the #611 journal entry.
DEFAULT_EMBED_CACHE_IDLE_UNLOAD_S: int = 900

# How often the idle-monitor thread wakes to check the idle deadline. Kept small
# relative to the idle window so the unload fires close to the deadline, but
# bounded so a tiny test-injected timeout still polls promptly. The effective
# tick is ``min(this, idle_window)`` so sub-second test timeouts stay responsive.
_IDLE_MONITOR_MAX_TICK_S: float = 30.0

EmbedFn = Callable[[list[str]], Any]  # list[str] -> np.ndarray (N, 384) L2-normalised

# Legacy embedding window: pre-#655 substrate stores never wrote
# substrate_meta.embed_max_tokens — their rows were embedded through the
# PGOV leakage detector's 128-token path.  An absent/unreadable meta key
# therefore means "this store's vectors are 128-token vectors".
LEGACY_EMBED_MAX_TOKENS: int = 128


def stored_embed_max_tokens(db_path: str) -> int:
    """Read ``substrate_meta.embed_max_tokens`` from an existing store.

    Returns the stored window, or :data:`LEGACY_EMBED_MAX_TOKENS` (128) when
    the file / table / key is absent or unreadable — i.e. a store the #655
    re-embed migration has not touched.  The AO binds the substrate's
    ``embed_fn`` at THIS window so post-migration ingests and queries match
    the stored vectors instead of re-creating the mixed-depth store
    ADR-031 §3 rejects.

    Opens read-only (URI mode) so probing never creates or mutates a
    database file.
    """
    if db_path == ":memory:":
        return LEGACY_EMBED_MAX_TOKENS
    from pathlib import Path

    try:
        uri = f"file:{Path(db_path).as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM substrate_meta WHERE key='embed_max_tokens'"
            ).fetchone()
        finally:
            conn.close()
        return int(row[0]) if row is not None else LEGACY_EMBED_MAX_TOKENS
    except (sqlite3.Error, ValueError, TypeError):
        return LEGACY_EMBED_MAX_TOKENS


class RetrievedChunk(NamedTuple):
    """A single retrieval hit."""

    kind: str       # 'doc' | 'turn'
    source: str     # filename (doc) or session id (turn)
    session_id: str
    text: str
    score: float    # cosine similarity (0..1)


def chunk_text(
    text: str,
    chunk_chars: int = CHUNK_CHARS,
    overlap_chars: int = CHUNK_OVERLAP_CHARS,
) -> list[str]:
    """Split *text* into overlapping character windows.

    Prefers to break on a newline or space near the window edge so chunks fall
    on natural boundaries rather than mid-word. Returns ``[]`` for empty input.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    step = max(1, chunk_chars - overlap_chars)
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        # Snap the end back to a nearby whitespace boundary if we cut mid-word.
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n"), window.rfind(" "))
            if cut > chunk_chars // 2:
                end = start + cut
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start += step
    return chunks


_SCHEMA = """
CREATE TABLE IF NOT EXISTS substrate_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL CHECK(kind IN ('doc', 'turn')),
    source      TEXT NOT NULL,
    session_id  TEXT NOT NULL DEFAULT '',
    chunk_index INTEGER NOT NULL DEFAULT 0,
    text        TEXT NOT NULL,
    embedding   BLOB NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chunk_identity
    ON substrate_chunks(kind, source, session_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_chunk_kind ON substrate_chunks(kind);

CREATE TABLE IF NOT EXISTS substrate_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Schema additions for encrypted variant (Sprint 14, ADR-025).
# source_hash: deterministic keyed HMAC-SHA256 of the normalised source filename;
# used as the uniqueness/dedup key so idx_chunk_identity works on ciphertext.
# source (renamed to encrypted source): AES-GCM(source) for decrypt-on-read display.
_ENCRYPTED_SCHEMA_MIGRATIONS = [
    # Add source_hash column (populated on ingest; NULL-able initially for migration).
    "ALTER TABLE substrate_chunks ADD COLUMN source_hash BLOB",
    # Add encryption version marker so we can detect already-encrypted rows.
    "INSERT OR IGNORE INTO substrate_meta(key, value) VALUES('encryption_version', '1')",
]

# Name of the new unique index that replaces idx_chunk_identity for encrypted stores.
_ENC_IDX_NAME = "idx_chunk_identity_enc"


class SubstrateStore:
    """SQLite-backed vector store with brute-force cosine retrieval.

    Args:
        db_path: Path to the substrate SQLite file (``:memory:`` for tests).
        embed_fn: Callable mapping ``list[str]`` to an ``(N, 384)`` numpy array
            of L2-normalised float32 embeddings (the PGOV bge-small embedder).
    """

    def __init__(self, db_path: str, embed_fn: EmbedFn) -> None:
        self._embed = embed_fn
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        _harden_db_file_dacl(db_path)
        # secure_delete=ON (FULL): DELETEd rows are zeroed in freed pages instead
        # of just being marked free. Substrate uses the DEFAULT rollback journal,
        # so freed pages are zeroed at COMMIT (WAL stores zero at checkpoint).
        self._conn.execute("PRAGMA secure_delete=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO substrate_meta(key, value) VALUES('embed_dim', ?)",
            (str(EMBED_DIM),),
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO substrate_meta(key, value) VALUES('embed_model', ?)",
            ("bge-small-en-v1.5",),
        )
        self._conn.commit()
        logger.info("SubstrateStore initialised: %s", db_path)

    def close(self) -> None:
        self._conn.close()

    # ── Ingest ──────────────────────────────────────────────────────────

    def ingest_document(self, filename: str, text: str, session_id: str = "") -> int:
        """Chunk, embed, and store a document. Returns the chunk count.

        Re-ingesting the same filename replaces its prior chunks (so reloading a
        changed file refreshes the index rather than duplicating it).
        """
        chunks = chunk_text(text)
        if not chunks:
            return 0
        import numpy as np

        embeddings = np.asarray(self._embed(chunks), dtype=np.float32)
        now = datetime.now(timezone.utc).isoformat()

        # Replace any prior chunks for this document.
        self._conn.execute(
            "DELETE FROM substrate_chunks WHERE kind='doc' AND source=?", (filename,)
        )
        self._conn.executemany(
            "INSERT INTO substrate_chunks"
            "(kind, source, session_id, chunk_index, text, embedding, created_at) "
            "VALUES('doc', ?, ?, ?, ?, ?, ?)",
            [
                (filename, session_id, i, chunk, embeddings[i].tobytes(), now)
                for i, chunk in enumerate(chunks)
            ],
        )
        self._conn.commit()
        logger.info("Substrate ingested document %s (%d chunks)", filename, len(chunks))
        return len(chunks)

    def ingest_turn(
        self, session_id: str, turn_index: int, user_text: str, assistant_text: str
    ) -> int:
        """Embed and store one approved user+assistant turn pair. Returns 1 (0 if empty).

        Idempotent per (session_id, turn_index): re-ingesting replaces the row.
        """
        if not user_text.strip() and not assistant_text.strip():
            return 0
        combined = f"User: {user_text.strip()}\nAssistant: {assistant_text.strip()}".strip()
        import numpy as np

        embedding = np.asarray(self._embed([combined]), dtype=np.float32)[0]
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO substrate_chunks"
            "(kind, source, session_id, chunk_index, text, embedding, created_at) "
            "VALUES('turn', ?, ?, ?, ?, ?, ?)",
            (session_id, session_id, turn_index, combined, embedding.tobytes(), now),
        )
        self._conn.commit()
        return 1

    # ── Retrieve ────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        k_docs: int = DEFAULT_K_DOCS,
        k_turns: int = DEFAULT_K_TURNS,
        exclude_session: str | None = None,
    ) -> list[RetrievedChunk]:
        """Return the top document + turn chunks most similar to *query*.

        Args:
            query: The user's prompt to retrieve memory for.
            k_docs: Max document chunks to return.
            k_turns: Max conversation-turn chunks to return.
            exclude_session: If set, turns from this session are excluded — the
                current conversation is already in the live context window, so
                re-retrieving it wastes budget. Documents are not excluded.

        Returns:
            Document hits then turn hits, each sorted by descending similarity.
        """
        if not query.strip():
            return []
        import numpy as np

        q = np.asarray(self._embed([query]), dtype=np.float32)[0]

        results: list[RetrievedChunk] = []
        results.extend(self._search_kind(q, "doc", k_docs, None))
        results.extend(self._search_kind(q, "turn", k_turns, exclude_session))
        return results

    def _search_kind(
        self, query_vec: Any, kind: str, k: int, exclude_session: str | None
    ) -> list[RetrievedChunk]:
        """Brute-force top-k cosine search within one kind."""
        if k <= 0:
            return []
        import numpy as np

        if exclude_session:
            rows = self._conn.execute(
                "SELECT id, embedding FROM substrate_chunks "
                "WHERE kind=? AND session_id<>?",
                (kind, exclude_session),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, embedding FROM substrate_chunks WHERE kind=?", (kind,)
            ).fetchall()
        if not rows:
            return []

        ids = [r[0] for r in rows]
        matrix = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(
            len(rows), EMBED_DIM
        )
        # Vectors are L2-normalised, so dot product == cosine similarity.
        scores = matrix @ query_vec
        top = np.argsort(scores)[::-1][:k]

        hits: list[RetrievedChunk] = []
        for idx in top:
            chunk_id = ids[int(idx)]
            row = self._conn.execute(
                "SELECT kind, source, session_id, text FROM substrate_chunks WHERE id=?",
                (chunk_id,),
            ).fetchone()
            if row is None:
                continue
            hits.append(RetrievedChunk(
                kind=row[0], source=row[1], session_id=row[2], text=row[3],
                score=float(scores[int(idx)]),
            ))
        return hits

    def next_turn_index(self, session_id: str) -> int:
        """Return the next free turn index for a session (max existing + 1)."""
        row = self._conn.execute(
            "SELECT MAX(chunk_index) FROM substrate_chunks "
            "WHERE kind='turn' AND session_id=?",
            (session_id,),
        ).fetchone()
        return (row[0] + 1) if row and row[0] is not None else 0

    # ── Introspection (tests / diagnostics) ─────────────────────────────

    def count(self, kind: str | None = None) -> int:
        if kind:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM substrate_chunks WHERE kind=?", (kind,)
            )
        else:
            cur = self._conn.execute("SELECT COUNT(*) FROM substrate_chunks")
        return int(cur.fetchone()[0])


# ============================================================================
# Encrypted variant (Sprint 14, ADR-025)
# ============================================================================


def _natural_row_id(kind: str, source_hash: bytes, session_id: str, chunk_index: int) -> str:
    """Canonical natural-row identity for AAD binding (ADR-025 §2.4).

    Format: ``kind|<source_hash_hex>|session_id|chunk_index``

    The source_hash is the 32-byte HMAC keyed index of the normalised source
    bytes; it is used instead of the raw source so the AAD is stable even after
    the source column is encrypted.  Using the hex representation keeps the
    identity as a printable ASCII string for ``make_aad_for``.
    """
    return f"{kind}|{source_hash.hex()}|{session_id}|{chunk_index}"


def _normalize_source(source: str) -> bytes:
    """Return the canonical bytes representation of a source/filename for hashing.

    Normalisation: strip leading/trailing whitespace; encode as UTF-8.
    This matches the normalisation that was in place before encryption so
    re-ingest hashes match on re-provisioned stores.
    """
    return source.strip().encode("utf-8")


class EncryptedSubstrateStore:
    """AES-GCM-encrypted variant of SubstrateStore (Sprint 14, ADR-025).

    Sensitive columns encrypted on write / decrypted on read:
    - ``text`` (document/turn text)
    - ``embedding`` (float32 BLOB — decrypted ONCE at unlock into the boot cache)
    - ``source`` (filename)

    The ``source_hash`` column (HMAC-SHA256 under ``k_idx``) provides a
    deterministic dedup key so ``idx_chunk_identity_enc`` and re-ingest work
    on ciphertext.  The ``source`` column stores AES-GCM(source) for
    decrypt-on-read display.

    AAD for each field is ``substrate_chunks|<column>|<natural_row_id>``, where
    ``natural_row_id = kind|<source_hash_hex>|session_id|chunk_index`` (stable
    natural key; AUTOINCREMENT ``id`` is excluded per ADR-025 §2.4).

    Embedding boot cache: all embeddings are decrypted ONCE at construction into
    ``_embed_cache`` (a dict keyed by row id → numpy float32 vector).  Vector
    search runs over the plaintext in-memory cache; only the top-k matched text
    is decrypted per query.

    Idle-unload (Vikunja #611): the decrypted embedding matrix is the largest and
    longest-lived plaintext-derived secret in RAM.  When ``embed_cache_idle_unload_s``
    is positive (the default), a daemon monitor thread drops the cache after that
    many seconds without a retrieval — calling :meth:`unload_embed_cache`, which
    **zeroes every numpy buffer in place** (``arr[:] = 0`` genuinely overwrites the
    plaintext vectors, unlike the immutable-``bytes`` DEK which cannot be cleared)
    and clears the dict.  The next :meth:`retrieve` reloads the cache lazily from
    the (still-encrypted) DB.  This shrinks both the live-memory exposure window
    and the 32 GB footprint.  A value ``<= 0`` disables idle-unload entirely
    (always-resident behaviour).  All cache state transitions are serialised by
    ``self._lock`` so a unload-vs-reload race cannot corrupt the cache.

    Fail-Closed: if the DEK cannot be unsealed the constructor raises
    ``DekEnvelopeError`` and the store refuses to open.

    ``has_encryption: bool = True`` — production-wiring regression lock.

    Args:
        db_path:  Path to the substrate SQLite file (``:memory:`` for tests).
        embed_fn: Callable mapping ``list[str]`` to an ``(N, 384)`` numpy array.
        cipher:   :class:`~shared.security.field_cipher.FieldCipher` instance,
                  constructed by the caller after unsealing the DEK envelope.
        embed_cache_idle_unload_s: Seconds of retrieval inactivity after which the
                  embedding cache is unloaded and its buffers zeroed; the cache
                  reloads lazily on the next retrieval.  ``<= 0`` disables
                  idle-unload (the cache stays resident for the store's lifetime).
                  Defaults to :data:`DEFAULT_EMBED_CACHE_IDLE_UNLOAD_S` (900 s).
    """

    #: Regression-lock attribute: any code that constructs the store can assert
    #: ``store.has_encryption is True`` to detect a future silent-wiring failure.
    has_encryption: bool = True

    def __init__(
        self,
        db_path: str,
        embed_fn: EmbedFn,
        cipher: "FieldCipher",  # type: ignore[name-defined]  # noqa: F821
        embed_cache_idle_unload_s: int = DEFAULT_EMBED_CACHE_IDLE_UNLOAD_S,
    ) -> None:
        from shared.security.field_cipher import FieldCipher  # local import; no circular dep
        if not isinstance(cipher, FieldCipher):
            raise TypeError(
                "EncryptedSubstrateStore requires a FieldCipher instance; "
                f"got {type(cipher).__name__!r}.  Pass a FieldCipher derived "
                "from the unsealed DEK."
            )
        self._embed = embed_fn
        self._cipher = cipher
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        _harden_db_file_dacl(db_path)
        # secure_delete=ON (FULL): DELETEd rows are zeroed in freed pages instead
        # of just being marked free. Substrate uses the DEFAULT rollback journal,
        # so freed pages are zeroed at COMMIT (WAL stores zero at checkpoint).
        self._conn.execute("PRAGMA secure_delete=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO substrate_meta(key, value) VALUES('embed_dim', ?)",
            (str(EMBED_DIM),),
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO substrate_meta(key, value) VALUES('embed_model', ?)",
            ("bge-small-en-v1.5",),
        )
        # Apply encrypted-schema additions (idempotent via try/except).
        self._apply_encrypted_schema()
        self._conn.commit()

        # ── Embedding-cache state + idle-unload (Vikunja #611) ────────────
        # All cache transitions (load / unload / lazy-reload) and the
        # last-access timestamp are guarded by this lock so a retrieval racing
        # the idle monitor cannot corrupt the cache.  RLock because a write path
        # (_invalidate_embed_cache → _load_embed_cache) re-enters under the lock.
        self._lock = threading.RLock()
        #: True once the cache has been unloaded for idleness; the next retrieval
        #: lazily reloads and flips this back to False.  An empty corpus is NOT
        #: "unloaded" — the distinction matters so a genuinely empty store does
        #: not pay a pointless reload on every query.
        self._cache_unloaded: bool = False
        #: Monotonic timestamp of the last retrieval, for the idle deadline.
        self._last_access: float = time.monotonic()
        self._idle_unload_s: int = int(embed_cache_idle_unload_s)

        # Embedding boot cache: decrypt all embeddings ONCE into RAM.
        self._embed_cache: dict[int, Any] = {}
        self._load_embed_cache()

        # Idle-monitor thread lifecycle (opt-in via config; default ON).
        self._idle_stop = threading.Event()
        self._idle_thread: threading.Thread | None = None
        if self._idle_unload_s > 0:
            self._idle_thread = threading.Thread(
                target=self._idle_monitor_loop,
                name="substrate-embed-idle-unload",
                daemon=True,
            )
            self._idle_thread.start()

        logger.info(
            "EncryptedSubstrateStore initialised: %s (%d cached embeddings, "
            "idle_unload_s=%d)",
            db_path,
            len(self._embed_cache),
            self._idle_unload_s,
        )

    def _apply_encrypted_schema(self) -> None:
        """Idempotent application of encrypted-schema migrations."""
        # Add source_hash column if absent.
        cols = {
            row[1]
            for row in self._conn.execute(
                "PRAGMA table_info(substrate_chunks)"
            ).fetchall()
        }
        if "source_hash" not in cols:
            self._conn.execute(
                "ALTER TABLE substrate_chunks ADD COLUMN source_hash BLOB"
            )
        # Add encryption version marker.
        self._conn.execute(
            "INSERT OR IGNORE INTO substrate_meta(key, value) "
            "VALUES('encryption_version', '1')"
        )
        # Create the encrypted-variant unique index on source_hash (not raw source).
        # The old idx_chunk_identity on raw source stays for backward compatibility
        # during migration; we add the new one here.
        self._conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_ENC_IDX_NAME} "
            "ON substrate_chunks(kind, source_hash, session_id, chunk_index)"
        )

    def _load_embed_cache(self) -> None:
        """Decrypt all embeddings ONCE into the in-RAM boot cache.

        Runs at construction time so every subsequent query runs over plaintext
        vectors without per-query decrypt cost.  Rows without a source_hash
        (pre-migration plaintext rows) are loaded raw.

        Bulk-read quarantine policy (ADR-025 §2.7 amendment, 2026-06-06):
        A single un-decryptable embedding row (e.g. encrypted under the old dev
        SoftwareSealer key after a dev→production DEK transition) must NOT abort
        boot and brick the AO substrate store.  Applying hard fail-closed here
        converts a confidentiality control into a self-inflicted availability DoS
        — one legacy row denies every healthy row (CIA triad: availability is a
        security property).  Quarantine posture: skip the bad row, exclude it
        from ``_embed_cache``, emit a stable WARNING event code
        ``SUBSTRATE_ROW_DECRYPT_QUARANTINE``, and continue.  The downstream
        ``_search_kind`` already handles a cache miss by substituting a zero
        vector (the row scores at the bottom); for quarantined rows we further
        exclude them from the candidate id set so they are never scored at all.
        Plaintext is never returned; tampered data is never trusted.
        Single-record/ingest/write paths retain hard fail-closed.
        """
        import numpy as np
        from shared.security.field_cipher import FIELD_CIPHER_VERSION, FieldCipherError

        rows = self._conn.execute(
            "SELECT id, kind, source_hash, session_id, chunk_index, embedding "
            "FROM substrate_chunks"
        ).fetchall()
        quarantined: int = 0
        for row_id, kind, source_hash_blob, session_id, chunk_index, emb_blob in rows:
            if source_hash_blob is None:
                # Pre-migration plaintext row — load raw (migration not yet run).
                vec = np.frombuffer(emb_blob, dtype=np.float32).copy()
            elif len(emb_blob) > 0 and emb_blob[0] == FIELD_CIPHER_VERSION:
                # Encrypted row — quarantine on decrypt failure (ADR-025 §2.7).
                nat_id = _natural_row_id(kind, bytes(source_hash_blob), session_id, chunk_index)
                from shared.security.field_cipher import make_aad_for
                aad = make_aad_for("substrate_chunks", "embedding", nat_id)
                try:
                    plaintext = self._cipher.decrypt(bytes(emb_blob), aad=aad)
                except FieldCipherError as exc:
                    quarantined += 1
                    logger.warning(
                        "SUBSTRATE_ROW_DECRYPT_QUARANTINE "
                        "event=SUBSTRATE_ROW_DECRYPT_QUARANTINE "
                        "row_id=%d nat_id=%r reason=%r -- embedding excluded from boot cache",
                        row_id,
                        nat_id,
                        str(exc),
                    )
                    continue  # row stays absent from _embed_cache; never scored
                vec = np.frombuffer(plaintext, dtype=np.float32).copy()
            else:
                # Plaintext row that has been migrated (source_hash present but not encrypted).
                vec = np.frombuffer(emb_blob, dtype=np.float32).copy()
            self._embed_cache[row_id] = vec
        if quarantined:
            logger.warning(
                "SUBSTRATE_ROW_DECRYPT_QUARANTINE summary: %d embedding row(s) quarantined "
                "in _load_embed_cache -- check key rotation / dev->prod key transition",
                quarantined,
            )

    def _invalidate_embed_cache(self) -> None:
        """Reload the embed cache after a WRITE that changed the embeddings.

        Distinct from :meth:`unload_embed_cache` (the idle path): a write means
        the *data changed*, so the cache is rebuilt eagerly from the new rows and
        the store stays in the loaded state.  Idle-unload, by contrast, frees the
        cache while the data is *unchanged* and defers re-decrypt to the next
        retrieval.  Both share :meth:`_load_embed_cache` as the single reload
        path.  Held under ``self._lock`` so a concurrent retrieval/idle-unload
        cannot observe a half-cleared cache.
        """
        with self._lock:
            self._zero_and_clear_cache()
            self._load_embed_cache()
            # A write reloads the cache eagerly — it is resident again, so the
            # store is no longer in the idle-unloaded state.
            self._cache_unloaded = False

    def _zero_and_clear_cache(self) -> None:
        """Zero every cached numpy buffer IN PLACE, then clear the dict.

        ``arr[:] = 0`` overwrites the backing store of each plaintext embedding
        vector — this is the genuine in-RAM scrub the #611 feasibility study
        calls out: numpy arrays are *mutable*, so unlike the immutable-``bytes``
        DEK these buffers can actually be overwritten before they are dropped.
        Caller MUST hold ``self._lock``.  Fail-safe: a per-buffer error never
        aborts the scrub of the remaining buffers.
        """
        for arr in self._embed_cache.values():
            try:
                arr[:] = 0
            except Exception:  # noqa: BLE001 — best-effort scrub; never raise
                pass
        self._embed_cache.clear()

    def unload_embed_cache(self) -> bool:
        """Drop the decrypted embedding cache and zero its buffers (Vikunja #611).

        Idempotent: a no-op (returns ``False``) if the cache is already in the
        unloaded state.  On the first call it zeroes every cached numpy buffer in
        place (genuinely overwriting the plaintext vectors), clears the dict, and
        marks the store "needs reload" so the next :meth:`retrieve` repopulates
        the cache lazily from the still-encrypted DB rows (the SAME rows — the
        data is unchanged; only the in-RAM plaintext copy is freed).

        Thread-safe: serialised by ``self._lock`` against retrieval/reload.

        Returns:
            ``True`` if this call performed an unload; ``False`` if it was a
            no-op (already unloaded).
        """
        with self._lock:
            if self._cache_unloaded:
                return False
            n = len(self._embed_cache)
            self._zero_and_clear_cache()
            self._cache_unloaded = True
            logger.info(
                "EncryptedSubstrateStore.unload_embed_cache: zeroed + dropped %d "
                "cached embedding vector(s); will reload lazily on next retrieve",
                n,
            )
            return True

    def _ensure_cache_loaded(self) -> None:
        """Lazily reload the embedding cache if it was idle-unloaded.

        Called at the top of each retrieval (under ``self._lock``).  Re-decrypts
        the SAME rows :meth:`unload_embed_cache` freed.  A no-op when the cache is
        already resident, so the steady-state retrieval path pays only a flag check.
        """
        if self._cache_unloaded:
            self._load_embed_cache()
            self._cache_unloaded = False
            logger.info(
                "EncryptedSubstrateStore: lazily reloaded %d embedding vector(s) "
                "after idle-unload",
                len(self._embed_cache),
            )

    def _idle_monitor_loop(self) -> None:
        """Daemon loop: unload the cache after ``_idle_unload_s`` of inactivity.

        Wakes on a bounded tick, and when the idle deadline has passed calls
        :meth:`unload_embed_cache`.  Fail-safe: any exception is logged and
        swallowed so the monitor can never crash the store or a retrieval; the
        loop simply continues to the next tick.  Stops promptly when
        ``self._idle_stop`` is set by :meth:`close`.
        """
        idle_s = self._idle_unload_s
        # Poll frequently enough to fire near the deadline, but never longer than
        # the idle window itself (so sub-second test timeouts stay responsive).
        tick = min(_IDLE_MONITOR_MAX_TICK_S, float(idle_s))
        tick = max(tick, 0.001)
        while not self._idle_stop.wait(tick):
            try:
                with self._lock:
                    if self._cache_unloaded or not self._embed_cache:
                        # Already unloaded, or nothing resident to unload — skip
                        # this tick (an empty cache never needs scrubbing).
                        continue
                    idle_for = time.monotonic() - self._last_access
                    due = idle_for >= idle_s
                if due:
                    self.unload_embed_cache()
            except Exception as exc:  # noqa: BLE001 — monitor must never crash
                logger.warning(
                    "Substrate idle-unload monitor tick failed (continuing): %s",
                    exc,
                )

    def close(self) -> None:
        """Close the store: stop the idle monitor, scrub the cache, close the DB.

        Clean lifecycle (no leaked thread): signals the idle monitor to stop and
        joins it, then zeroes any still-resident embedding buffers before closing
        the connection.  Idempotent and fail-safe.
        """
        # Stop the idle monitor first so it cannot touch a closing store.
        self._idle_stop.set()
        thread = self._idle_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        self._idle_thread = None
        # Scrub any plaintext vectors still resident at shutdown.
        with self._lock:
            self._zero_and_clear_cache()
            self._cache_unloaded = True
        self._conn.close()

    # ── Ingest ──────────────────────────────────────────────────────────

    def ingest_document(self, filename: str, text: str, session_id: str = "") -> int:
        """Chunk, embed, encrypt, and store a document. Returns the chunk count.

        Re-ingesting the same filename replaces its prior chunks (so reloading a
        changed file refreshes the index rather than duplicating it).
        Dedup uses the keyed source_hash, so ciphertext uniqueness is preserved.
        """
        chunks = chunk_text(text)
        if not chunks:
            return 0
        import numpy as np
        from shared.security.field_cipher import make_aad_for

        embeddings = np.asarray(self._embed(chunks), dtype=np.float32)
        now = datetime.now(timezone.utc).isoformat()

        # Compute the source_hash for the filename (deterministic keyed index).
        source_norm = _normalize_source(filename)
        source_hash = self._cipher.keyed_index(source_norm)

        # Replace any prior chunks for this document (dedup by source_hash).
        self._conn.execute(
            "DELETE FROM substrate_chunks WHERE kind='doc' AND source_hash=?",
            (source_hash,),
        )

        rows: list[tuple[Any, ...]] = []
        for i, chunk in enumerate(chunks):
            nat_id = _natural_row_id("doc", source_hash, session_id, i)
            enc_text = self._cipher.encrypt(
                chunk.encode("utf-8"),
                aad=make_aad_for("substrate_chunks", "text", nat_id),
            )
            enc_emb = self._cipher.encrypt(
                embeddings[i].tobytes(),
                aad=make_aad_for("substrate_chunks", "embedding", nat_id),
            )
            enc_source = self._cipher.encrypt(
                source_norm,
                aad=make_aad_for("substrate_chunks", "source", nat_id),
            )
            rows.append((
                enc_source,    # source column (AES-GCM ciphertext)
                source_hash,   # source_hash column (HMAC — deterministic dedup key)
                session_id,
                i,
                enc_text,      # text column (AES-GCM ciphertext, stored as BLOB)
                enc_emb,       # embedding column (AES-GCM ciphertext)
                now,
            ))

        self._conn.executemany(
            "INSERT INTO substrate_chunks"
            "(kind, source, source_hash, session_id, chunk_index, text, embedding, created_at) "
            "VALUES('doc', ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        self._invalidate_embed_cache()
        logger.info(
            "EncryptedSubstrateStore ingested document %s (%d chunks)", filename, len(chunks)
        )
        return len(chunks)

    def ingest_turn(
        self, session_id: str, turn_index: int, user_text: str, assistant_text: str
    ) -> int:
        """Embed, encrypt, and store one approved user+assistant turn pair.

        Returns 1 (0 if empty). Idempotent per (session_id, turn_index).
        For turns, ``source == session_id`` so the keyed hash is applied to
        the session_id bytes.
        """
        if not user_text.strip() and not assistant_text.strip():
            return 0
        combined = f"User: {user_text.strip()}\nAssistant: {assistant_text.strip()}".strip()
        import numpy as np
        from shared.security.field_cipher import make_aad_for

        embedding = np.asarray(self._embed([combined]), dtype=np.float32)[0]
        now = datetime.now(timezone.utc).isoformat()

        # For turns, source == session_id.
        source_norm = _normalize_source(session_id)
        source_hash = self._cipher.keyed_index(source_norm)

        nat_id = _natural_row_id("turn", source_hash, session_id, turn_index)
        enc_text = self._cipher.encrypt(
            combined.encode("utf-8"),
            aad=make_aad_for("substrate_chunks", "text", nat_id),
        )
        enc_emb = self._cipher.encrypt(
            embedding.tobytes(),
            aad=make_aad_for("substrate_chunks", "embedding", nat_id),
        )
        enc_source = self._cipher.encrypt(
            source_norm,
            aad=make_aad_for("substrate_chunks", "source", nat_id),
        )

        self._conn.execute(
            "INSERT OR REPLACE INTO substrate_chunks"
            "(kind, source, source_hash, session_id, chunk_index, text, embedding, created_at) "
            "VALUES('turn', ?, ?, ?, ?, ?, ?, ?)",
            (enc_source, source_hash, session_id, turn_index, enc_text, enc_emb, now),
        )
        self._conn.commit()
        self._invalidate_embed_cache()
        return 1

    # ── Retrieve ────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        k_docs: int = DEFAULT_K_DOCS,
        k_turns: int = DEFAULT_K_TURNS,
        exclude_session: str | None = None,
    ) -> list[RetrievedChunk]:
        """Return the top document + turn chunks most similar to *query*.

        Uses the in-RAM embedding boot cache for vector search; only the top-k
        matched text fields are decrypted per query.

        Idle-unload (Vikunja #611): if the cache was idle-unloaded it is reloaded
        lazily here under ``self._lock`` (race-safe against the idle monitor), so
        a retrieval after an idle-unload returns identical results to one before
        it.  The last-access clock is bumped so active use defers the next unload.
        """
        if not query.strip():
            return []
        import numpy as np

        # Embed the query OUTSIDE the cache lock (model inference must not
        # serialise on the cache); the cache-dependent search runs under the lock.
        q = np.asarray(self._embed([query]), dtype=np.float32)[0]

        with self._lock:
            # Lazily re-decrypt the SAME rows if the cache was idle-unloaded, then
            # search while still holding the lock so the monitor cannot free the
            # cache mid-query.
            self._ensure_cache_loaded()
            results: list[RetrievedChunk] = []
            results.extend(self._search_kind(q, "doc", k_docs, None))
            results.extend(self._search_kind(q, "turn", k_turns, exclude_session))
            # Bump the idle clock AFTER a successful search so active use keeps the
            # cache resident.
            self._last_access = time.monotonic()
        return results

    def _search_kind(
        self, query_vec: Any, kind: str, k: int, exclude_session: str | None
    ) -> list[RetrievedChunk]:
        """Brute-force top-k cosine search over the in-RAM embedding cache.

        Bulk-read quarantine policy (ADR-025 §2.7 amendment, 2026-06-06):
        A single un-decryptable top-k chunk must not abort the whole query and
        deny the caller all retrieval results.  When text or source decrypt fails,
        the chunk is quarantined: omitted from the returned hits, logged at
        WARNING with stable event code ``SUBSTRATE_ROW_DECRYPT_QUARANTINE``.
        Plaintext is never returned from a bad row; tampered data is never trusted.
        """
        if k <= 0:
            return []
        import numpy as np
        from shared.security.field_cipher import FIELD_CIPHER_VERSION, FieldCipherError, make_aad_for

        if exclude_session:
            rows = self._conn.execute(
                "SELECT id, kind, source_hash, session_id, chunk_index "
                "FROM substrate_chunks WHERE kind=? AND session_id<>?",
                (kind, exclude_session),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, kind, source_hash, session_id, chunk_index "
                "FROM substrate_chunks WHERE kind=?",
                (kind,),
            ).fetchall()
        if not rows:
            return []

        # Build matrix from boot cache (plaintext vectors in RAM).
        # Rows quarantined in _load_embed_cache are absent from _embed_cache, so
        # they never appear as candidates here — we only score rows we can read.
        ids = [r[0] for r in rows]
        vecs = []
        valid_ids: list[int] = []
        valid_rows: list[Any] = []
        for i, row_id in enumerate(ids):
            if row_id in self._embed_cache:
                vecs.append(self._embed_cache[row_id])
                valid_ids.append(row_id)
                valid_rows.append(rows[i])
            else:
                # Cache miss — row was quarantined at boot or missing; skip.
                logger.warning(
                    "embed_cache miss for row_id=%d (quarantined at boot or missing) -- "
                    "excluded from search results",
                    row_id,
                )

        if not vecs:
            return []

        matrix = np.vstack(vecs)
        scores = matrix @ query_vec
        top = np.argsort(scores)[::-1][:k]

        hits: list[RetrievedChunk] = []
        quarantined: int = 0
        for idx in top:
            row_id = valid_ids[int(idx)]
            meta_row = valid_rows[int(idx)]
            _, row_kind, source_hash_blob, session_id, chunk_index = meta_row

            # Fetch encrypted text and source for decryption.
            enc_row = self._conn.execute(
                "SELECT text, source FROM substrate_chunks WHERE id=?",
                (row_id,),
            ).fetchone()
            if enc_row is None:
                continue
            enc_text, enc_source = enc_row

            # Decrypt text (the expensive path — only for top-k hits).
            # Quarantine on failure: omit this chunk, log the event, continue.
            # (ADR-025 §2.7 amendment — bulk quarantine, not hard fail-closed.)
            if source_hash_blob is not None and enc_text[0:1] and enc_text[0] == FIELD_CIPHER_VERSION:
                nat_id = _natural_row_id(row_kind, bytes(source_hash_blob), session_id, chunk_index)
                try:
                    text = self._cipher.decrypt(
                        bytes(enc_text),
                        aad=make_aad_for("substrate_chunks", "text", nat_id),
                    ).decode("utf-8")
                except FieldCipherError as exc:
                    quarantined += 1
                    logger.warning(
                        "SUBSTRATE_ROW_DECRYPT_QUARANTINE "
                        "event=SUBSTRATE_ROW_DECRYPT_QUARANTINE "
                        "row_id=%d nat_id=%r field=text reason=%r -- chunk excluded from retrieve",
                        row_id,
                        nat_id,
                        str(exc),
                    )
                    continue  # skip this chunk entirely
            else:
                # Plaintext row (pre-migration or in-memory store).
                text = enc_text if isinstance(enc_text, str) else enc_text.decode("utf-8")

            # Decrypt source (display only).
            # Quarantine on failure: omit this chunk, log the event, continue.
            if source_hash_blob is not None and enc_source[0:1] and enc_source[0] == FIELD_CIPHER_VERSION:
                nat_id = _natural_row_id(row_kind, bytes(source_hash_blob), session_id, chunk_index)
                try:
                    source = self._cipher.decrypt(
                        bytes(enc_source),
                        aad=make_aad_for("substrate_chunks", "source", nat_id),
                    ).decode("utf-8")
                except FieldCipherError as exc:
                    quarantined += 1
                    logger.warning(
                        "SUBSTRATE_ROW_DECRYPT_QUARANTINE "
                        "event=SUBSTRATE_ROW_DECRYPT_QUARANTINE "
                        "row_id=%d nat_id=%r field=source reason=%r -- chunk excluded from retrieve",
                        row_id,
                        nat_id,
                        str(exc),
                    )
                    continue  # skip this chunk entirely
            else:
                source = enc_source if isinstance(enc_source, str) else enc_source.decode("utf-8")

            hits.append(RetrievedChunk(
                kind=row_kind,
                source=source,
                session_id=session_id,
                text=text,
                score=float(scores[int(idx)]),
            ))
        if quarantined:
            logger.warning(
                "SUBSTRATE_ROW_DECRYPT_QUARANTINE summary: %d chunk(s) quarantined "
                "in _search_kind(kind=%r) -- check key rotation / dev->prod key transition",
                quarantined,
                kind,
            )
        return hits

    def next_turn_index(self, session_id: str) -> int:
        """Return the next free turn index for a session (max existing + 1)."""
        row = self._conn.execute(
            "SELECT MAX(chunk_index) FROM substrate_chunks "
            "WHERE kind='turn' AND session_id=?",
            (session_id,),
        ).fetchone()
        return (row[0] + 1) if row and row[0] is not None else 0

    # ── Introspection (tests / diagnostics) ─────────────────────────────

    def count(self, kind: str | None = None) -> int:
        if kind:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM substrate_chunks WHERE kind=?", (kind,)
            )
        else:
            cur = self._conn.execute("SELECT COUNT(*) FROM substrate_chunks")
        return int(cur.fetchone()[0])


# ============================================================================
# Migration utility (ADR-025 §3)
# ============================================================================


def migrate_plaintext_to_encrypted(
    db_path: str,
    cipher: "FieldCipher",  # type: ignore[name-defined]  # noqa: F821
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Encrypt plaintext rows in an existing substrate.db in place.

    Algorithm:
    1. Open the DB.
    2. Apply encrypted-schema additions (source_hash column + enc index).
    3. For each row without source_hash (plaintext):
       a. Read raw source, text, embedding.
       b. Compute source_hash = cipher.keyed_index(normalised_source).
       c. Encrypt source, text, embedding with correct AAD.
       d. Write back encrypted values + source_hash.
    4. Skip rows that already have source_hash (already migrated — idempotent).
    5. VACUUM to scrub freed pages containing old plaintext.

    Returns a dict with counts: {"migrated": N, "already_encrypted": M, "errors": K}.

    Args:
        db_path:  Path to the SQLite file.
        cipher:   :class:`~shared.security.field_cipher.FieldCipher` instance.
        dry_run:  If True, do not write anything; just report what would be done.
    """
    from shared.security.field_cipher import FIELD_CIPHER_VERSION, make_aad_for

    conn = sqlite3.connect(db_path, check_same_thread=False)
    try:
        # Apply schema additions.
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(substrate_chunks)").fetchall()
        }
        if "source_hash" not in cols:
            conn.execute(
                "ALTER TABLE substrate_chunks ADD COLUMN source_hash BLOB"
            )
        conn.execute(
            "INSERT OR IGNORE INTO substrate_meta(key, value) "
            "VALUES('encryption_version', '1')"
        )
        conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_ENC_IDX_NAME} "
            "ON substrate_chunks(kind, source_hash, session_id, chunk_index)"
        )
        conn.commit()

        rows = conn.execute(
            "SELECT id, kind, source, source_hash, session_id, chunk_index, text, embedding "
            "FROM substrate_chunks"
        ).fetchall()

        migrated = 0
        already_encrypted = 0
        errors = 0

        for (row_id, kind, source_raw, source_hash_blob,
             session_id, chunk_index, text_raw, emb_raw) in rows:

            if source_hash_blob is not None:
                # Already has a source_hash — check if it was actually encrypted.
                # The version byte on text distinguishes.
                if isinstance(text_raw, (bytes, bytearray)) and len(text_raw) > 0 and text_raw[0] == FIELD_CIPHER_VERSION:
                    already_encrypted += 1
                    continue
                elif isinstance(text_raw, str):
                    # source_hash present but text is plaintext string — partial migration.
                    pass
                else:
                    already_encrypted += 1
                    continue

            try:
                # Decode raw source.
                if isinstance(source_raw, (bytes, bytearray)):
                    source_str = bytes(source_raw).decode("utf-8")
                else:
                    source_str = str(source_raw)

                source_norm = _normalize_source(source_str)
                sh = cipher.keyed_index(source_norm)

                nat_id = _natural_row_id(kind, sh, session_id, chunk_index)

                # Encode text if it's a str.
                if isinstance(text_raw, str):
                    text_bytes = text_raw.encode("utf-8")
                else:
                    text_bytes = bytes(text_raw)

                enc_text = cipher.encrypt(
                    text_bytes,
                    aad=make_aad_for("substrate_chunks", "text", nat_id),
                )
                enc_emb = cipher.encrypt(
                    bytes(emb_raw) if not isinstance(emb_raw, bytes) else emb_raw,
                    aad=make_aad_for("substrate_chunks", "embedding", nat_id),
                )
                enc_source = cipher.encrypt(
                    source_norm,
                    aad=make_aad_for("substrate_chunks", "source", nat_id),
                )

                if not dry_run:
                    conn.execute(
                        "UPDATE substrate_chunks SET source=?, source_hash=?, text=?, embedding=? "
                        "WHERE id=?",
                        (enc_source, sh, enc_text, enc_emb, row_id),
                    )
                migrated += 1

            except Exception as exc:  # noqa: BLE001
                logger.error("Migration error on row %d: %s", row_id, exc)
                errors += 1

        if not dry_run:
            conn.commit()
            # VACUUM to scrub freed pages that still contain old plaintext.
            conn.execute("VACUUM")

        return {"migrated": migrated, "already_encrypted": already_encrypted, "errors": errors}
    finally:
        conn.close()


def verify_no_plaintext(
    db_path: str,
    plaintext_samples: list[bytes],
) -> list[str]:
    """Whole-file scan asserting no plaintext sample appears in raw DB bytes.

    Reads the raw file bytes (post-VACUUM) and searches for each supplied
    sample. Returns a list of violation strings (empty = all clear).

    Args:
        db_path:          Path to the SQLite file.
        plaintext_samples: List of plaintext byte strings to search for.
    """
    import re
    from pathlib import Path

    raw = Path(db_path).read_bytes()
    violations: list[str] = []
    for sample in plaintext_samples:
        if len(sample) < 4:
            continue  # too short to be meaningful
        if sample in raw:
            violations.append(
                f"Plaintext sample found in raw DB file: {sample[:40]!r}..."
            )
    return violations
