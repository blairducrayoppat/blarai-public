"""
Tests for ADR-025 §2.7 amendment — substrate store bulk-read quarantine posture.

Sprint 15 follow-up #618 (class-audit sibling of the session-store fix).

Covers three scenarios:
  (a) Embeddings written under cipher A, store re-opened under cipher B →
      construction SUCCEEDS (bad embeddings quarantined, not a boot crash),
      store is usable, embedding cache is empty so retrieve returns no hits.
  (b) A corrupted chunk among several good chunks → retrieve() returns the
      good hits and omits the bad one, no raise, event logged.
  (c) Single-record/leaf decrypt (direct _cipher.decrypt call) STILL raises
      FieldCipherError — confidentiality lock is preserved.

All tests use :memory: or tmp_path.  NEVER write to %LOCALAPPDATA%.
"""

from __future__ import annotations

import logging
import sqlite3
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from services.assistant_orchestrator.src.substrate import (
    EMBED_DIM,
    EncryptedSubstrateStore,
    _natural_row_id,
    _normalize_source,
)
from shared.security.dek_envelope import (
    DekEnvelope,
    generate_recovery_key,
)
from shared.security.field_cipher import (
    FIELD_CIPHER_VERSION,
    FieldCipher,
    FieldCipherError,
    derive_subkeys,
    make_aad_for,
)
from shared.security.tpm_sealer import SoftwareSealer


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_substrate_encryption.py)
# ---------------------------------------------------------------------------


def fake_embed(texts: list[str]) -> np.ndarray:
    """Deterministic bag-of-words embedder: shared words → similar vectors."""
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for word in t.lower().split():
            out[i, zlib.crc32(word.encode()) % EMBED_DIM] += 1.0
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (out / norms).astype(np.float32)


def _make_cipher() -> FieldCipher:
    """Build a FieldCipher from a freshly-generated DEK (SoftwareSealer path)."""
    sealer = SoftwareSealer()
    rk = generate_recovery_key()
    env = DekEnvelope.create(sealer=sealer, recovery_key=rk)
    dek = env.unseal_dek()
    return FieldCipher(derive_subkeys(dek))


def _make_store(
    db_path: str = ":memory:",
    cipher: FieldCipher | None = None,
) -> EncryptedSubstrateStore:
    if cipher is None:
        cipher = _make_cipher()
    return EncryptedSubstrateStore(db_path=db_path, embed_fn=fake_embed, cipher=cipher)


def _inject_bad_row(
    db_path: str,
    cipher_bad: FieldCipher,
    *,
    kind: str = "doc",
    source: str = "bad.txt",
    session_id: str = "",
    chunk_index: int = 0,
    text: str = "this row is encrypted under the wrong key",
) -> int:
    """Insert a substrate_chunks row encrypted under *cipher_bad* into an existing DB.

    Returns the new row's AUTOINCREMENT id.  The injected row will fail to
    decrypt when the store is opened with a different cipher, exercising the
    quarantine path.
    """
    source_norm = _normalize_source(source)
    source_hash = cipher_bad.keyed_index(source_norm)
    nat_id = _natural_row_id(kind, source_hash, session_id, chunk_index)

    emb = fake_embed([text])[0]
    enc_text = cipher_bad.encrypt(
        text.encode("utf-8"),
        aad=make_aad_for("substrate_chunks", "text", nat_id),
    )
    enc_emb = cipher_bad.encrypt(
        emb.tobytes(),
        aad=make_aad_for("substrate_chunks", "embedding", nat_id),
    )
    enc_source = cipher_bad.encrypt(
        source_norm,
        aad=make_aad_for("substrate_chunks", "source", nat_id),
    )

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO substrate_chunks"
        "(kind, source, source_hash, session_id, chunk_index, text, embedding, created_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        (kind, enc_source, source_hash, session_id, chunk_index, enc_text, enc_emb, now),
    )
    row_id: int = cur.lastrowid  # type: ignore[assignment]
    conn.commit()
    conn.close()
    return row_id


# ---------------------------------------------------------------------------
# (a) Embeddings under cipher A, store re-opened under cipher B
#     → construction SUCCEEDS, store usable, bad embeddings quarantined
# ---------------------------------------------------------------------------


class TestBootCacheQuarantine:
    """Scenario (a): mismatched DEK on existing rows must not crash boot."""

    def test_construction_succeeds_with_mismatched_key(self, tmp_path: Path) -> None:
        """Opening an encrypted DB with the wrong cipher must SUCCEED.

        The old posture (FieldCipherError propagating out of _load_embed_cache)
        bricks AO startup on any dev→prod key transition.  The quarantine posture
        (ADR-025 §2.7 amendment) must allow construction to complete.
        """
        db = str(tmp_path / "enc.db")
        cipher_a = _make_cipher()
        store_a = _make_store(db_path=db, cipher=cipher_a)
        store_a.ingest_document("private.txt", "confidential document text here")
        store_a.close()

        cipher_b = _make_cipher()
        # Must not raise.
        store_b = _make_store(db_path=db, cipher=cipher_b)
        assert store_b is not None
        store_b.close()

    def test_store_usable_after_quarantine_boot(self, tmp_path: Path) -> None:
        """After quarantined boot the store is queryable (count works, retrieve doesn't crash)."""
        db = str(tmp_path / "enc.db")
        cipher_a = _make_cipher()
        store_a = _make_store(db_path=db, cipher=cipher_a)
        store_a.ingest_document("private.txt", "confidential document text here")
        store_a.close()

        cipher_b = _make_cipher()
        store_b = _make_store(db_path=db, cipher=cipher_b)
        # DB row still exists; count() queries the DB directly.
        assert store_b.count() == 1
        # Retrieve returns no hits (bad row absent from cache).
        hits = store_b.retrieve("confidential document text", k_docs=2, k_turns=2)
        assert hits == [], f"Expected no hits with wrong key, got {hits}"
        store_b.close()

    def test_new_rows_after_quarantine_boot_are_accessible(self, tmp_path: Path) -> None:
        """Rows ingested under cipher B after a quarantined boot are retrievable."""
        db = str(tmp_path / "enc.db")
        cipher_a = _make_cipher()
        store_a = _make_store(db_path=db, cipher=cipher_a)
        store_a.ingest_document("old.txt", "old data encrypted under cipher a")
        store_a.close()

        cipher_b = _make_cipher()
        store_b = _make_store(db_path=db, cipher=cipher_b)
        store_b.ingest_document("new.txt", "turbocharger engine pistons cylinders")
        hits = store_b.retrieve("turbocharger engine", k_docs=1, k_turns=0)
        assert len(hits) == 1
        assert hits[0].source == "new.txt"
        store_b.close()

    def test_quarantine_warning_emitted(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A WARNING with SUBSTRATE_ROW_DECRYPT_QUARANTINE must be logged on quarantine."""
        db = str(tmp_path / "enc.db")
        cipher_a = _make_cipher()
        store_a = _make_store(db_path=db, cipher=cipher_a)
        store_a.ingest_document("secret.txt", "secret content for warning test")
        store_a.close()

        cipher_b = _make_cipher()
        with caplog.at_level(logging.WARNING, logger="services.assistant_orchestrator.src.substrate"):
            _make_store(db_path=db, cipher=cipher_b)

        assert any(
            "SUBSTRATE_ROW_DECRYPT_QUARANTINE" in r.message for r in caplog.records
        ), (
            "Expected SUBSTRATE_ROW_DECRYPT_QUARANTINE WARNING log on quarantined boot; "
            f"got: {[r.message for r in caplog.records]}"
        )


# ---------------------------------------------------------------------------
# (b) Corrupted chunk among several good chunks
#     → retrieve returns good hits, omits bad one, no raise
# ---------------------------------------------------------------------------


class TestRetrieveQuarantine:
    """Scenario (b): one bad chunk in the top-k result set must be quarantined."""

    def test_good_hits_returned_bad_omitted(self, tmp_path: Path) -> None:
        """retrieve() returns good hits and silently omits a bad chunk.

        Setup: store has two good chunks under cipher_good, plus one chunk
        injected under cipher_bad (simulating a legacy row).  The bad chunk
        is loaded into the embed cache under cipher_bad, so it IS scored by
        the query — but decrypting its text/source fails with the good cipher,
        triggering the quarantine path.
        """
        db = str(tmp_path / "enc.db")
        cipher_good = _make_cipher()
        store = _make_store(db_path=db, cipher=cipher_good)

        # Ingest two good docs.
        store.ingest_document("cars.txt", "engine engine pistons pistons turbocharger crankshaft")
        store.ingest_document("garden.txt", "tomatoes basil compost watering irrigation harvest")
        store.close()

        # Inject a bad row (encrypted under a different cipher).
        cipher_bad = _make_cipher()
        bad_row_id = _inject_bad_row(
            db,
            cipher_bad,
            kind="doc",
            source="bad.txt",
            session_id="",
            chunk_index=0,
            text="engine engine engine turbocharger pistons",  # high-score words
        )

        # Re-open with good cipher.  The bad row's embedding cannot be decrypted,
        # so it is quarantined in _load_embed_cache and excluded from scoring.
        store2 = _make_store(db_path=db, cipher=cipher_good)
        hits = store2.retrieve("turbocharger engine pistons", k_docs=3, k_turns=0)

        # Should get 2 hits (the two good docs), NOT the bad row.
        hit_sources = {h.source for h in hits}
        assert "cars.txt" in hit_sources, f"Expected cars.txt in hits, got {hit_sources}"
        assert "bad.txt" not in hit_sources, (
            f"bad.txt must be quarantined, but appeared in hits: {hit_sources}"
        )
        assert all(h.text for h in hits), "All returned hits must have non-empty text"
        store2.close()

    def test_retrieve_does_not_raise_on_bad_chunk(self, tmp_path: Path) -> None:
        """retrieve() must not raise even when a top-k chunk is un-decryptable."""
        db = str(tmp_path / "enc.db")
        cipher_good = _make_cipher()
        store = _make_store(db_path=db, cipher=cipher_good)
        store.ingest_document("doc.txt", "alpha beta gamma delta epsilon")
        store.close()

        cipher_bad = _make_cipher()
        _inject_bad_row(db, cipher_bad, kind="doc", source="evil.txt", chunk_index=1)

        store2 = _make_store(db_path=db, cipher=cipher_good)
        # Must not raise.
        try:
            hits = store2.retrieve("alpha beta gamma", k_docs=5, k_turns=0)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"retrieve() raised unexpectedly: {exc!r}")
        store2.close()

    def test_quarantine_log_emitted_on_retrieve(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A WARNING with SUBSTRATE_ROW_DECRYPT_QUARANTINE is emitted when a
        top-k chunk decrypt fails during retrieve().

        Because the embed cache quarantine path already excludes bad embeddings
        from scoring at boot, we need a row whose embedding IS decryptable (same
        cipher) but whose text is corrupted so the text-decrypt path fires.
        We achieve this by injecting a row under cipher_good then directly
        corrupting its text blob in the DB.
        """
        db = str(tmp_path / "enc.db")
        cipher_good = _make_cipher()
        store = _make_store(db_path=db, cipher=cipher_good)
        store.ingest_document("cars.txt", "turbocharger engine pistons crankshaft")
        store.ingest_document("target.txt", "turbocharger turbocharger engine boost boost")
        store.close()

        # Corrupt the text blob of the target row so it fails to decrypt.
        conn = sqlite3.connect(db)
        target_row = conn.execute(
            "SELECT id, text FROM substrate_chunks WHERE source IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if target_row:
            row_id, blob = target_row
            # Flip some bytes in the middle of the ciphertext (after header).
            corrupted = bytearray(bytes(blob))
            mid = len(corrupted) // 2
            corrupted[mid] ^= 0xFF
            conn.execute("UPDATE substrate_chunks SET text=? WHERE id=?", (bytes(corrupted), row_id))
            conn.commit()
        conn.close()

        store2 = _make_store(db_path=db, cipher=cipher_good)
        with caplog.at_level(logging.WARNING, logger="services.assistant_orchestrator.src.substrate"):
            hits = store2.retrieve("turbocharger engine boost", k_docs=3, k_turns=0)

        # The corrupted row must be absent from hits.
        assert isinstance(hits, list), "retrieve() must return a list"

        # Check that the quarantine event code was logged (may be from boot cache
        # or from the text-decrypt path during retrieve).
        all_messages = " ".join(r.message for r in caplog.records)
        assert "SUBSTRATE_ROW_DECRYPT_QUARANTINE" in all_messages, (
            "Expected SUBSTRATE_ROW_DECRYPT_QUARANTINE in WARNING logs; "
            f"got: {[r.message for r in caplog.records]}"
        )
        store2.close()


# ---------------------------------------------------------------------------
# (c) Single-record / leaf decrypt still raises (confidentiality lock preserved)
# ---------------------------------------------------------------------------


class TestSingleRecordFailClosed:
    """Scenario (c): direct _cipher.decrypt with wrong key still raises FieldCipherError."""

    def test_direct_decrypt_wrong_key_raises(self) -> None:
        """FieldCipher.decrypt with a mismatched key raises FieldCipherError.

        This confirms the confidentiality lock is not broken by the bulk quarantine
        amendment: the leaf decrypt path remains hard fail-closed.
        """
        cipher_a = _make_cipher()
        cipher_b = _make_cipher()

        blob = cipher_a.encrypt(
            b"very private substrate content",
            aad=make_aad_for("substrate_chunks", "text", "doc|aabbcc|sess|0"),
        )

        with pytest.raises(FieldCipherError):
            cipher_b.decrypt(
                blob,
                aad=make_aad_for("substrate_chunks", "text", "doc|aabbcc|sess|0"),
            )

    def test_direct_decrypt_tampered_blob_raises(self) -> None:
        """FieldCipher.decrypt with tampered ciphertext raises FieldCipherError."""
        cipher = _make_cipher()
        aad = make_aad_for("substrate_chunks", "text", "doc|aabbcc|sess|0")
        blob = cipher.encrypt(b"original content", aad=aad)

        # Tamper with a byte in the ciphertext (past the version+nonce header).
        header = 1 + 12  # version byte + nonce
        tampered = bytearray(blob)
        tampered[header] ^= 0xAA

        with pytest.raises(FieldCipherError):
            cipher.decrypt(bytes(tampered), aad=aad)

    def test_direct_decrypt_wrong_aad_raises(self) -> None:
        """FieldCipher.decrypt with mismatched AAD raises FieldCipherError."""
        cipher = _make_cipher()
        aad_correct = make_aad_for("substrate_chunks", "text", "doc|aabbcc|sess|0")
        aad_wrong = make_aad_for("substrate_chunks", "text", "doc|aabbcc|sess|1")

        blob = cipher.encrypt(b"row 0 content", aad=aad_correct)

        with pytest.raises(FieldCipherError):
            cipher.decrypt(blob, aad=aad_wrong)
