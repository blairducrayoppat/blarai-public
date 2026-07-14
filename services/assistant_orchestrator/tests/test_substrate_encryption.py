"""
Tests for Sprint 14 EA-3 — substrate.db at-rest encryption (ADR-025).

Covers EncryptedSubstrateStore against a SoftwareSealer + dev_mode=True cipher
(no hardware required).  All tests run in the default suite.

Test structure:
  1. Construction + has_encryption regression lock.
  2. Raw-file no-plaintext: text / embedding / source are ciphertext on disk.
  3. Retrieval equivalence: same top-k hits as the pre-encryption SubstrateStore
     for a fixed query set.
  4. Re-ingest dedup on ciphertext: keyed-hash uniqueness works.
  5. Migration idempotence + whole-file no-plaintext scan.
  6. Fail-closed: no DEK → refuse to open.
  7. Production-wiring regression lock: _build_substrate returns encrypted store.
"""

from __future__ import annotations

import secrets
import sqlite3
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from services.assistant_orchestrator.src.substrate import (
    EMBED_DIM,
    EncryptedSubstrateStore,
    SubstrateStore,
    chunk_text,
    migrate_plaintext_to_encrypted,
    verify_no_plaintext,
)
from shared.security.dek_envelope import (
    DekEnvelope,
    DekEnvelopeError,
    build_envelope,
    generate_recovery_key,
)
from shared.security.field_cipher import (
    FIELD_CIPHER_VERSION,
    FieldCipher,
    derive_subkeys,
)
from shared.security.tpm_sealer import SoftwareSealer


# ---------------------------------------------------------------------------
# Helpers
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


def _make_encrypted_store(
    db_path: str = ":memory:",
    cipher: FieldCipher | None = None,
) -> EncryptedSubstrateStore:
    if cipher is None:
        cipher = _make_cipher()
    return EncryptedSubstrateStore(db_path=db_path, embed_fn=fake_embed, cipher=cipher)


def _seed_store(store: Any) -> None:
    """Seed store with representative documents and turns (same content for both
    SubstrateStore and EncryptedSubstrateStore).

    Content is chosen so the bag-of-words embedder produces clearly distinguishable
    vectors: repeated distinctive words dominate the histogram.
    """
    store.ingest_document(
        "cars.txt",
        "engine engine pistons pistons turbocharger crankshaft combustion cylinder",
    )
    store.ingest_document(
        "garden.txt",
        "tomatoes tomatoes basil basil compost watering irrigation harvest",
    )
    store.ingest_turn("sess-A", 0, "my sister is named Dana hiking trails", "Noted, Dana.")
    store.ingest_turn("sess-A", 1, "the weather today is rainy and cold outside", "Indeed.")


# ---------------------------------------------------------------------------
# 1. Construction + has_encryption regression lock
# ---------------------------------------------------------------------------


class TestEncryptedStoreConstruction:
    def test_has_encryption_is_true(self) -> None:
        """Regression lock: has_encryption MUST be True on every instance."""
        store = _make_encrypted_store()
        assert store.has_encryption is True, (
            "EncryptedSubstrateStore.has_encryption is not True — "
            "encryption wiring may be silently disabled"
        )

    def test_wrong_cipher_type_raises(self) -> None:
        """Passing something other than a FieldCipher must raise TypeError."""
        with pytest.raises(TypeError, match="FieldCipher"):
            EncryptedSubstrateStore(
                db_path=":memory:",
                embed_fn=fake_embed,
                cipher="not-a-cipher",  # type: ignore[arg-type]
            )

    def test_in_memory_store_empty_on_creation(self) -> None:
        store = _make_encrypted_store()
        assert store.count() == 0

    def test_persists_across_reopen(self, tmp_path: Path) -> None:
        """Data survives close + reopen with the same cipher."""
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        s1 = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)
        s1.ingest_document("test.txt", "persistent memory survives restart")
        s1.close()

        s2 = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)
        assert s2.count() == 1
        s2.close()


# ---------------------------------------------------------------------------
# 2. Raw-file no-plaintext: text / embedding / source are ciphertext on disk
# ---------------------------------------------------------------------------


class TestRawFileNoCleartext:
    """After ingest, the raw SQLite file must not contain readable plaintext."""

    def test_text_is_not_plaintext_on_disk(self, tmp_path: Path) -> None:
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)
        plaintext = "oncology results confidential patient record"
        store.ingest_document("2024_oncology.txt", plaintext)
        store.close()

        raw = Path(db).read_bytes()
        # The plaintext text must NOT appear in the raw file.
        assert b"oncology results" not in raw, (
            "Plaintext text found in raw SQLite file — encryption not applied"
        )
        assert b"confidential patient" not in raw

    def test_source_filename_is_not_plaintext_on_disk(self, tmp_path: Path) -> None:
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)
        store.ingest_document("2024_oncology_results.pdf", "some content here for testing")
        store.close()

        raw = Path(db).read_bytes()
        assert b"2024_oncology_results.pdf" not in raw, (
            "Plaintext filename found in raw SQLite file — source encryption not applied"
        )

    def test_embedding_is_not_raw_float32_on_disk(self, tmp_path: Path) -> None:
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)
        # We need to know what the embedding looks like to check.
        text = "turbocharger engine pistons"
        emb = fake_embed([text])[0]
        store.ingest_document("cars.txt", text)
        store.close()

        raw = Path(db).read_bytes()
        # The raw float32 bytes of the embedding should NOT appear verbatim.
        emb_bytes = emb.tobytes()
        assert emb_bytes not in raw, (
            "Raw float32 embedding bytes found in raw SQLite file — embedding encryption not applied"
        )

    def test_version_byte_present_on_text_column(self, tmp_path: Path) -> None:
        """The first byte of the stored text blob must be the cipher version byte."""
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)
        store.ingest_document("doc.txt", "some text content here")
        store.close()

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT text FROM substrate_chunks LIMIT 1").fetchone()
        conn.close()

        assert row is not None
        blob = bytes(row[0]) if not isinstance(row[0], bytes) else row[0]
        assert blob[0] == FIELD_CIPHER_VERSION, (
            f"Expected cipher version byte 0x{FIELD_CIPHER_VERSION:02X} as first byte "
            f"of text blob, got 0x{blob[0]:02X}"
        )

    def test_version_byte_present_on_embedding_column(self, tmp_path: Path) -> None:
        """The first byte of the stored embedding blob must be the cipher version byte."""
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)
        store.ingest_document("doc.txt", "embedding test content")
        store.close()

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT embedding FROM substrate_chunks LIMIT 1").fetchone()
        conn.close()

        assert row is not None
        blob = bytes(row[0]) if not isinstance(row[0], bytes) else row[0]
        assert blob[0] == FIELD_CIPHER_VERSION, (
            f"Expected cipher version byte 0x{FIELD_CIPHER_VERSION:02X} as first byte "
            f"of embedding blob, got 0x{blob[0]:02X}"
        )

    def test_source_hash_column_populated(self, tmp_path: Path) -> None:
        """source_hash column must be populated after ingest."""
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)
        store.ingest_document("report.pdf", "quarterly results")
        store.close()

        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT source_hash FROM substrate_chunks LIMIT 1"
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] is not None, "source_hash is NULL after ingest — dedup key missing"
        sh = bytes(row[0]) if not isinstance(row[0], bytes) else row[0]
        assert len(sh) == 32, f"source_hash should be 32 bytes (HMAC-SHA256), got {len(sh)}"


# ---------------------------------------------------------------------------
# 3. Retrieval equivalence: same top-k hits as unencrypted baseline
# ---------------------------------------------------------------------------


class TestRetrievalEquivalence:
    """EncryptedSubstrateStore.retrieve() must return the same top-k as SubstrateStore."""

    # Queries that are clearly related to one doc — unambiguous top-1 result.
    # The bag-of-words embedder scores on shared words, so use distinctive words.
    DOC_QUERIES = [
        ("turbocharger pistons engine combustion", "cars.txt"),
        ("tomatoes basil compost irrigation", "garden.txt"),
    ]

    def test_doc_retrieval_matches_plaintext_store(self) -> None:
        """Document retrieval top-1 matches the pre-encryption baseline for
        unambiguous queries (where one doc clearly scores higher than the other).
        """
        plain = SubstrateStore(db_path=":memory:", embed_fn=fake_embed)
        enc = _make_encrypted_store()

        _seed_store(plain)
        _seed_store(enc)

        for query, expected_source in self.DOC_QUERIES:
            plain_hits = plain.retrieve(query, k_docs=1, k_turns=0)
            enc_hits = enc.retrieve(query, k_docs=1, k_turns=0)

            assert len(plain_hits) == 1
            assert len(enc_hits) == 1
            assert plain_hits[0].source == expected_source, (
                f"Plain store top-1 for {query!r}: expected {expected_source!r}, "
                f"got {plain_hits[0].source!r}"
            )
            assert enc_hits[0].source == expected_source, (
                f"Enc store top-1 for {query!r}: expected {expected_source!r}, "
                f"got {enc_hits[0].source!r}"
            )

    def test_turn_retrieval_top1_matches_plaintext_store(self) -> None:
        """Turn retrieval top-1 matches the pre-encryption baseline for
        unambiguous queries.
        """
        plain = SubstrateStore(db_path=":memory:", embed_fn=fake_embed)
        enc = _make_encrypted_store()

        _seed_store(plain)
        _seed_store(enc)

        # Query about sister → top turn should be the "sister Dana hiking" turn.
        query = "sister Dana hiking trails"
        plain_hits = plain.retrieve(query, k_docs=0, k_turns=1)
        enc_hits = enc.retrieve(query, k_docs=0, k_turns=1)

        assert len(plain_hits) == 1
        assert len(enc_hits) == 1
        assert "sister" in plain_hits[0].text
        assert "sister" in enc_hits[0].text
        # Both stores should agree on the top hit's text.
        assert plain_hits[0].text == enc_hits[0].text

    def test_combined_retrieval_same_doc_count(self) -> None:
        """Combined doc+turn retrieval returns same number of hits."""
        plain = SubstrateStore(db_path=":memory:", embed_fn=fake_embed)
        enc = _make_encrypted_store()

        _seed_store(plain)
        _seed_store(enc)

        query = "turbocharger pistons engine combustion"
        plain_hits = plain.retrieve(query, k_docs=2, k_turns=2)
        enc_hits = enc.retrieve(query, k_docs=2, k_turns=2)

        assert len(plain_hits) == len(enc_hits), (
            f"Different number of hits for query {query!r}: "
            f"plain={len(plain_hits)}, enc={len(enc_hits)}"
        )

    def test_empty_query_returns_nothing(self) -> None:
        enc = _make_encrypted_store()
        _seed_store(enc)
        assert enc.retrieve("   ") == []

    def test_session_exclusion_works(self) -> None:
        enc = _make_encrypted_store()
        enc.ingest_turn("current", 0, "apples oranges bananas", "fruit noted")
        enc.ingest_turn("past", 0, "apples oranges bananas", "fruit noted")
        hits = enc.retrieve("apples oranges", k_docs=0, k_turns=5, exclude_session="current")
        assert all(h.session_id != "current" for h in hits)
        assert any(h.session_id == "past" for h in hits)

    def test_scores_descending(self) -> None:
        enc = _make_encrypted_store()
        enc.ingest_document("a.txt", "red green blue colors")
        enc.ingest_document("b.txt", "red orange warm colors")
        enc.ingest_document("c.txt", "calculus integrals derivatives")
        hits = enc.retrieve("red colors", k_docs=3, k_turns=0)
        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 4. Re-ingest dedup on ciphertext (keyed-hash uniqueness)
# ---------------------------------------------------------------------------


class TestReIngestDedup:
    """Re-ingesting the same document must dedup (replace, not duplicate)."""

    def test_reingest_same_doc_replaces_not_duplicates(self) -> None:
        enc = _make_encrypted_store()
        enc.ingest_document("notes.txt", "alpha beta gamma")
        enc.ingest_document("notes.txt", "delta epsilon zeta")
        assert enc.count("doc") == 1, (
            f"Expected 1 doc chunk after re-ingest, got {enc.count('doc')}"
        )

    def test_reingest_content_is_updated(self) -> None:
        enc = _make_encrypted_store()
        enc.ingest_document("notes.txt", "alpha beta gamma delta")
        enc.ingest_document("notes.txt", "delta epsilon zeta theta")
        hits = enc.retrieve("delta epsilon", k_docs=1, k_turns=0)
        assert len(hits) == 1
        assert "delta" in hits[0].text

    def test_dedup_works_with_different_cipher_instances_same_dek(
        self, tmp_path: Path
    ) -> None:
        """Two EncryptedSubstrateStore instances with the same DEK dedup correctly."""
        db = str(tmp_path / "enc.db")
        sealer = SoftwareSealer()
        rk = generate_recovery_key()
        keystore = tmp_path / "ks.json"
        env = build_envelope(sealer=sealer, recovery_key=rk, keystore_path=keystore, dev_mode=True)
        dek = env.unseal_dek()
        cipher = FieldCipher(derive_subkeys(dek))

        s1 = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)
        s1.ingest_document("doc.txt", "alpha beta gamma delta epsilon")
        s1.close()

        # Reload with a fresh cipher derived from the SAME DEK.
        cipher2 = FieldCipher(derive_subkeys(dek))
        s2 = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher2)
        s2.ingest_document("doc.txt", "zeta eta theta iota kappa")  # same filename
        assert s2.count("doc") == 1, "Re-ingest with same DEK should dedup"
        s2.close()

    def test_turn_reingest_idempotent(self) -> None:
        enc = _make_encrypted_store()
        enc.ingest_turn("sess", 3, "hello world", "hi there")
        enc.ingest_turn("sess", 3, "hello again world", "hi there again")
        assert enc.count("turn") == 1


# ---------------------------------------------------------------------------
# 5. Migration idempotence + whole-file no-plaintext scan
# ---------------------------------------------------------------------------


class TestMigration:
    """Migrate plaintext rows → encrypted; then verify no plaintext on disk."""

    def test_migrate_populates_source_hash(self, tmp_path: Path) -> None:
        """After migration, all rows have a non-null source_hash."""
        db = str(tmp_path / "plain.db")
        plain = SubstrateStore(db_path=db, embed_fn=fake_embed)
        plain.ingest_document("report.txt", "quarterly results analysis")
        plain.ingest_turn("s", 0, "budget planning", "noted")
        plain.close()

        cipher = _make_cipher()
        stats = migrate_plaintext_to_encrypted(db, cipher)
        assert stats["errors"] == 0
        assert stats["migrated"] == 2

        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT source_hash FROM substrate_chunks").fetchall()
        conn.close()
        assert all(r[0] is not None for r in rows), "Some rows still have NULL source_hash"

    def test_migrate_idempotent(self, tmp_path: Path) -> None:
        """Running migrate twice must not error or re-encrypt already-encrypted rows."""
        db = str(tmp_path / "plain.db")
        plain = SubstrateStore(db_path=db, embed_fn=fake_embed)
        plain.ingest_document("notes.txt", "meeting agenda for today")
        plain.close()

        cipher = _make_cipher()
        stats1 = migrate_plaintext_to_encrypted(db, cipher)
        assert stats1["migrated"] == 1
        assert stats1["errors"] == 0

        stats2 = migrate_plaintext_to_encrypted(db, cipher)
        assert stats2["migrated"] == 0, (
            f"Second migrate should find 0 rows to migrate (already encrypted), "
            f"got {stats2['migrated']}"
        )
        assert stats2["errors"] == 0

    def test_migrate_then_retrieve_works(self, tmp_path: Path) -> None:
        """After migration, EncryptedSubstrateStore retrieves correctly."""
        db = str(tmp_path / "plain.db")

        # Build plaintext store.
        plain = SubstrateStore(db_path=db, embed_fn=fake_embed)
        plain.ingest_document("cars.txt", "engine pistons turbocharger crankshaft")
        plain.ingest_document("garden.txt", "tomatoes basil soil watering compost")
        plain.close()

        cipher = _make_cipher()
        stats = migrate_plaintext_to_encrypted(db, cipher)
        assert stats["errors"] == 0

        # Open encrypted store and verify retrieval.
        enc = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)
        hits = enc.retrieve("how does a turbocharger engine work", k_docs=1, k_turns=0)
        assert len(hits) == 1
        assert hits[0].source == "cars.txt"
        enc.close()

    def test_whole_file_no_plaintext_after_migration(self, tmp_path: Path) -> None:
        """Raw DB bytes must not contain any of the original plaintext strings post-VACUUM."""
        db = str(tmp_path / "plain.db")

        # Representative content that should be encrypted.
        plaintext_doc = "oncology results confidential patient record SENSITIVE"
        plaintext_turn = "my sister Dana loves hiking trails PRIVATE"
        filename = "2024_oncology_results.pdf"

        plain = SubstrateStore(db_path=db, embed_fn=fake_embed)
        plain.ingest_document(filename, plaintext_doc)
        plain.ingest_turn("sess", 0, plaintext_turn, "response text here")
        plain.close()

        cipher = _make_cipher()
        stats = migrate_plaintext_to_encrypted(db, cipher)
        assert stats["errors"] == 0

        # Verify no plaintext survives in raw bytes.
        violations = verify_no_plaintext(
            db,
            [
                plaintext_doc.encode("utf-8"),
                plaintext_turn.encode("utf-8"),
                filename.encode("utf-8"),
            ],
        )
        assert violations == [], (
            f"Plaintext found in raw DB after migration + VACUUM:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# 6. Fail-closed: DEK envelope error propagates; bulk quarantine, not boot crash
# ---------------------------------------------------------------------------


class TestFailClosed:
    """Without a valid DEK the store must refuse to open.
    With a mismatched DEK, bulk reads quarantine bad rows (ADR-025 §2.7 amendment).
    """

    def test_wrong_dek_at_boot_quarantines_not_crashes(self, tmp_path: Path) -> None:
        """Opening an encrypted DB with the wrong DEK must NOT crash the store.

        Bulk-read quarantine posture (ADR-025 §2.7 amendment, 2026-06-06):
        A mismatched DEK on existing rows triggers FieldCipherError inside
        _load_embed_cache.  The quarantine posture must apply: construction
        SUCCEEDS (bad embeddings excluded from the cache), the store is
        queryable for any rows that DO decrypt (or future new rows), and a
        WARNING log with SUBSTRATE_ROW_DECRYPT_QUARANTINE is emitted.
        Plaintext is never returned; tampered data is never trusted.

        This is the boot-time analogue of list_sessions quarantine in the
        session store.  The prior behaviour (FieldCipherError propagating out
        of the constructor) was a self-inflicted availability DoS that would
        brick AO startup on any dev→production key transition.
        """
        db = str(tmp_path / "enc.db")
        cipher_good = _make_cipher()
        store = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher_good)
        store.ingest_document("secret.txt", "very confidential content here")
        store.close()

        # Open with a DIFFERENT cipher (different DEK → wrong key on existing rows).
        # Construction must SUCCEED (quarantine, not crash).
        cipher_bad = _make_cipher()
        store_bad = EncryptedSubstrateStore(
            db_path=db, embed_fn=fake_embed, cipher=cipher_bad
        )
        # Store is usable — count() works, retrieve on empty cache returns [].
        assert store_bad.count() == 1  # row still present in DB, just not cached
        hits = store_bad.retrieve("confidential secret", k_docs=2, k_turns=2)
        # The bad rows are quarantined (absent from cache), so zero hits.
        assert hits == [], (
            "Expected no hits with wrong key (rows quarantined), "
            f"got {hits}"
        )
        store_bad.close()

    def test_single_record_decrypt_still_raises_with_wrong_key(
        self, tmp_path: Path
    ) -> None:
        """Single-record (direct) decrypt of a bad blob still raises FieldCipherError.

        The quarantine posture only applies to bulk loops.  A direct call to
        _cipher.decrypt with mismatched AAD or key must remain hard fail-closed —
        the confidentiality lock is preserved.
        """
        from shared.security.field_cipher import FieldCipherError, make_aad_for

        cipher_good = _make_cipher()
        cipher_bad = _make_cipher()

        # Encrypt a value under the good cipher.
        blob = cipher_good.encrypt(
            b"very confidential content",
            aad=make_aad_for("substrate_chunks", "text", "doc|aabbcc|sess|0"),
        )

        # Decrypting under the bad cipher raises FieldCipherError (hard fail-closed).
        with pytest.raises(FieldCipherError):
            cipher_bad.decrypt(
                blob,
                aad=make_aad_for("substrate_chunks", "text", "doc|aabbcc|sess|0"),
            )

    def test_dek_envelope_error_type(self) -> None:
        """DekEnvelopeError is raised when the DEK cannot be unsealed (no recovery key,
        TPM fails)."""
        import types
        from shared.security import tpm_sealer as ts

        sealer = SoftwareSealer()
        rk = generate_recovery_key()
        env = DekEnvelope.create(sealer=sealer, recovery_key=rk)

        # Patch the sealer to simulate TPM failure and do not supply recovery key.
        env._sealer = types.SimpleNamespace(
            unseal=lambda _: (_ for _ in ()).throw(ts.TpmUnavailable("no chip"))
        )
        with pytest.raises(DekEnvelopeError, match="refusing to open"):
            env.unseal_dek(recovery_key=None)


# ---------------------------------------------------------------------------
# 7. Production-wiring regression lock
# ---------------------------------------------------------------------------


class TestProductionWiringLock:
    """The entrypoint _build_substrate must produce an EncryptedSubstrateStore."""

    def test_build_substrate_returns_encrypted_store(self) -> None:
        """_build_substrate() (mocked PGOV) returns an EncryptedSubstrateStore
        with has_encryption=True — the regression lock that prevents a future
        refactor from silently wiring back to SubstrateStore.

        Uses patch to stub pgov._get_detector inside the entrypoint module
        (which imports pgov at module level).
        """
        import types
        from unittest.mock import patch

        # Build a minimal fake detector with a loaded embed function.  The
        # entrypoint binds embed_documents (meta-driven window, #655 review
        # fix), so the stub must provide it alongside the leakage-path _embed.
        fake_detector = types.SimpleNamespace(
            loaded=True,
            _embed=fake_embed,
            embed_documents=lambda texts, max_length=128: fake_embed(texts),
        )

        # pgov is imported at module level in entrypoint; patch _get_detector on
        # the already-imported module object.
        from services.assistant_orchestrator.src.entrypoint import AssistantOrchestratorService
        from services.assistant_orchestrator.src import pgov as pgov_mod

        with patch.object(pgov_mod, "_get_detector", return_value=fake_detector):
            with patch.dict("os.environ", {"LOCALAPPDATA": "", "BLARAI_DEK_KEYSTORE": ""}, clear=False):
                orch = AssistantOrchestratorService.__new__(AssistantOrchestratorService)
                store = orch._build_substrate()

        # The returned store MUST be an EncryptedSubstrateStore, not a plain SubstrateStore.
        assert store is not None, "_build_substrate returned None (embedding model failed?)"
        assert isinstance(store, EncryptedSubstrateStore), (
            f"_build_substrate returned {type(store).__name__!r}, expected "
            "'EncryptedSubstrateStore' — encryption wiring may be broken"
        )
        assert store.has_encryption is True, (
            "has_encryption is not True on the store returned by _build_substrate"
        )
        store.close()

    def test_has_encryption_attribute_is_class_level(self) -> None:
        """has_encryption must be a class-level boolean, not an instance attribute."""
        assert EncryptedSubstrateStore.has_encryption is True

    def test_plain_substrate_store_does_not_have_has_encryption(self) -> None:
        """SubstrateStore (unencrypted) must NOT have has_encryption=True."""
        # Ensure we are not accidentally marking the plaintext store as encrypted.
        store = SubstrateStore(db_path=":memory:", embed_fn=fake_embed)
        # Either the attribute is absent or is not True.
        enc_flag = getattr(store, "has_encryption", False)
        assert enc_flag is not True, (
            "SubstrateStore.has_encryption is True — this would fool the regression lock"
        )

    def test_wiring_violation_raises_specific_error_not_assert(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """#804: has_encryption is not True on the constructed store MUST fire
        the EXPLICIT StoreProvisioningError tripwire (deterministic code
        AO_SUBSTRATE_ENCRYPTION_WIRING_FAILED), never a bare AssertionError.

        An ``assert`` is compiled out under ``python -O``, silently waving the
        unencrypted store through; the explicit raise survives ``-O``
        (CWE-617).  The factory's outer except contains it: substrate memory
        loud-disabled (None), AO boot unaffected.
        """
        import types
        from unittest.mock import patch

        from services.assistant_orchestrator.src import pgov as pgov_mod
        from services.assistant_orchestrator.src.entrypoint import (
            AssistantOrchestratorService,
        )
        from services.ui_gateway.src.session_store import StoreProvisioningError

        fake_detector = types.SimpleNamespace(
            loaded=True,
            _embed=fake_embed,
            embed_documents=lambda texts, max_length=128: fake_embed(texts),
        )

        with patch.object(pgov_mod, "_get_detector", return_value=fake_detector):
            with patch.dict(
                "os.environ",
                {"LOCALAPPDATA": "", "BLARAI_DEK_KEYSTORE": ""},
                clear=False,
            ):
                # Violate the invariant: the class-level regression-lock
                # attribute reads False, as if a refactor silently unwired
                # the encryption.
                with patch.object(
                    EncryptedSubstrateStore, "has_encryption", False
                ):
                    orch = AssistantOrchestratorService.__new__(
                        AssistantOrchestratorService
                    )
                    with caplog.at_level("ERROR"):
                        store = orch._build_substrate()

        assert store is None, (
            "_build_substrate returned a store despite has_encryption=False — "
            "the wiring tripwire did not fire"
        )
        assert "AO_SUBSTRATE_ENCRYPTION_WIRING_FAILED" in caplog.text
        # Pin the TYPE of the tripwire: the loud-disable record logs the
        # exception object itself ("%s", exc) — it must be the explicit
        # StoreProvisioningError, not an AssertionError (which would mean
        # the assert form is back and would vanish under python -O).
        logged = [
            r.args[0]
            for r in caplog.records
            if r.args and isinstance(r.args[0], BaseException)
        ]
        assert logged, "loud-disable log record carrying the exception not found"
        assert isinstance(logged[0], StoreProvisioningError)
        assert not isinstance(logged[0], AssertionError)


# ---------------------------------------------------------------------------
# 8. Additional coverage: count(), next_turn_index(), multi-chunk doc
# ---------------------------------------------------------------------------


class TestCoverageExtras:
    def test_count_by_kind(self) -> None:
        enc = _make_encrypted_store()
        enc.ingest_document("d.txt", "alpha beta gamma")
        enc.ingest_turn("s", 0, "hello world", "hi")
        assert enc.count("doc") == 1
        assert enc.count("turn") == 1
        assert enc.count() == 2

    def test_next_turn_index(self) -> None:
        enc = _make_encrypted_store()
        assert enc.next_turn_index("sess") == 0
        enc.ingest_turn("sess", 0, "first turn", "reply")
        assert enc.next_turn_index("sess") == 1

    def test_long_document_multiple_chunks(self) -> None:
        enc = _make_encrypted_store()
        text = " ".join(f"sentence{i} about widgets" for i in range(400))
        n = enc.ingest_document("big.txt", text)
        assert n > 1
        assert enc.count("doc") == n

    def test_k_zero_skips_kind(self) -> None:
        enc = _make_encrypted_store()
        enc.ingest_document("d.txt", "alpha beta gamma")
        enc.ingest_turn("s", 0, "alpha beta gamma", "reply")
        assert all(h.kind == "turn" for h in enc.retrieve("alpha", k_docs=0, k_turns=2))

    def test_empty_turn_not_ingested(self) -> None:
        enc = _make_encrypted_store()
        assert enc.ingest_turn("s", 0, "", "") == 0
        assert enc.count("turn") == 0


# ---------------------------------------------------------------------------
# 9. secure_delete=ON (FULL) + SE-1 free-page residual probes (WS2)
# ---------------------------------------------------------------------------


class TestSecureDelete:
    """``PRAGMA secure_delete=ON`` (FULL) zeroes DELETEd rows in freed pages.

    The substrate store uses the DEFAULT rollback journal (no journal_mode
    PRAGMA), so freed pages are zeroed at COMMIT — no checkpoint is required.

    Why the SE-1 probe captures CIPHERTEXT, not just plaintext: the encrypted
    store never writes plaintext to disk, so a plaintext-only assertion would
    pass even with secure_delete OFF (a false pass).  Each probe therefore
    captures the on-disk ciphertext of the stored row BEFORE the delete (raw
    SELECT of the encrypted column) and asserts that exact ciphertext fragment
    is ABSENT from the raw .db bytes AFTER the delete.  With secure_delete OFF
    that ciphertext would survive in the freed (but un-zeroed) page, so the
    probe genuinely fails if the PRAGMA is removed.
    """

    def test_secure_delete_pragma_on(self, tmp_path: Path) -> None:
        """EncryptedSubstrateStore opens with secure_delete=ON (FULL == 1)."""
        db = str(tmp_path / "secure_delete.db")
        cipher = _make_cipher()
        store = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)
        try:
            mode = store._conn.execute("PRAGMA secure_delete").fetchone()[0]
            assert mode == 1, (
                f"Expected secure_delete=1 (FULL/ON), got {mode!r} — "
                "freed pages will not be zeroed on delete"
            )
        finally:
            store.close()

    def test_secure_delete_pragma_on_plaintext_store(self, tmp_path: Path) -> None:
        """SubstrateStore (plaintext variant) also opens with secure_delete=ON."""
        db = str(tmp_path / "secure_delete_plain.db")
        store = SubstrateStore(db_path=db, embed_fn=fake_embed)
        try:
            mode = store._conn.execute("PRAGMA secure_delete").fetchone()[0]
            assert mode == 1, (
                f"Expected secure_delete=1 (FULL/ON), got {mode!r} — "
                "freed pages will not be zeroed on delete"
            )
        finally:
            store.close()

    @staticmethod
    def _big_marked_doc(marker: str, n_chunks: int = 60) -> str:
        """Build a many-chunk document, each chunk carrying the unique marker.

        Re-ingesting over a LARGE prior document frees many pages while the
        small replacement reuses at most one — so the rest stay free and only
        secure_delete zeroes their residual.  This is what makes the probe
        discriminating: a single-chunk doc's freed page tends to be reused by
        the replacement INSERT (overwriting the residual regardless of the
        PRAGMA), masking the control.  Each chunk is ~one page of distinctive
        text so chunks span many DB pages.
        """
        body = (marker + " ") + ("residual probe filler word distinctive " * 60)
        return "\n\n".join(f"{i} {body}" for i in range(n_chunks))

    def test_se1_substrate_reingest_no_freepage_residual(self, tmp_path: Path) -> None:
        """SE-1: re-ingesting a document DELETEs prior chunks; with secure_delete
        ON the prior chunks' on-disk ciphertext is zeroed in the freed pages.

        Captures a prior chunk's encrypted text+embedding ciphertext BEFORE the
        re-ingest (raw SELECT), re-ingests a SMALL replacement under the same
        filename (which DELETEs all the prior chunks at COMMIT — rollback
        journal, no checkpoint needed), then asserts neither the plaintext marker
        NOR the captured ciphertext survives in the raw .db bytes.  The ciphertext
        assertion is the load-bearing one — it fails if the PRAGMA is removed even
        though the plaintext never hits disk.  A large prior document (many
        chunks/pages) is used so the freed pages are NOT all reused by the small
        replacement, making secure_delete the thing that removes the residual.
        """
        db = str(tmp_path / "se1_substrate.db")
        cipher = _make_cipher()
        store = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)

        marker = "WS2-SE1-SUBSTRATE-7f3a9c21residualprobe"
        n = store.ingest_document("marker.txt", self._big_marked_doc(marker))
        assert n > 1, "fixture must produce a multi-chunk document"

        # Capture the on-disk ciphertext of a LATE chunk BEFORE the delete (a late
        # chunk's page is least likely to be reused by the small replacement).
        rows = store._conn.execute(
            "SELECT text, embedding FROM substrate_chunks WHERE kind='doc' "
            "ORDER BY chunk_index DESC"
        ).fetchall()
        assert rows, "expected stored chunks before re-ingest"
        prior_text_ct = bytes(rows[0][0])
        prior_emb_ct = bytes(rows[0][1])
        assert len(prior_text_ct) > 16
        assert prior_text_ct in Path(db).read_bytes(), (
            "captured ciphertext not on disk before delete — fixture broken"
        )

        # Re-ingest the SAME filename with a SMALL replacement -> DELETE prior chunks.
        store.ingest_document("marker.txt", "tomatoes basil compost watering irrigation")
        store.close()

        raw = Path(db).read_bytes()
        assert marker.encode("utf-8") not in raw, (
            "plaintext marker survived in raw DB after re-ingest delete"
        )
        assert prior_text_ct not in raw, (
            "prior chunk's TEXT ciphertext survived in a freed page after delete — "
            "secure_delete=ON is not zeroing freed pages (PRAGMA missing/wrong?)"
        )
        assert prior_emb_ct not in raw, (
            "prior chunk's EMBEDDING ciphertext survived in a freed page after "
            "delete — secure_delete=ON is not zeroing freed pages"
        )

    def test_se1_substrate_plaintext_reingest_no_freepage_residual(
        self, tmp_path: Path
    ) -> None:
        """SE-1 (plaintext variant): SubstrateStore proves plaintext zeroing.

        The plaintext store writes the marker verbatim to disk, so this is the
        most direct demonstration that secure_delete zeroes the freed page — the
        plaintext marker itself is what must vanish after the re-ingest DELETE.
        Uses a large multi-chunk prior document for the same not-all-reused
        reason as the encrypted variant.
        """
        db = str(tmp_path / "se1_substrate_plain.db")
        store = SubstrateStore(db_path=db, embed_fn=fake_embed)

        marker = "WS2-SE1-SUBSTRATE-PLAIN-b4e8residualprobe"
        n = store.ingest_document("marker.txt", self._big_marked_doc(marker))
        assert n > 1, "fixture must produce a multi-chunk document"

        # Sanity: the plaintext marker is on disk before the delete (many copies).
        assert Path(db).read_bytes().count(marker.encode("utf-8")) > 1, (
            "plaintext marker not on disk before delete — fixture broken"
        )

        # Re-ingest a SMALL replacement -> DELETE the large prior document.
        store.ingest_document("marker.txt", "tomatoes basil compost watering irrigation")
        store.close()

        raw = Path(db).read_bytes()
        assert marker.encode("utf-8") not in raw, (
            "plaintext marker survived in a freed page after re-ingest delete — "
            "secure_delete=ON is not zeroing freed pages"
        )

    def test_secure_delete_full_lifecycle_correctness(self, tmp_path: Path) -> None:
        """Correctness smoke: an ingest -> retrieve -> delete -> retrieve lifecycle
        still returns correct results with secure_delete ON (no timing assertion).
        """
        db = str(tmp_path / "se1_lifecycle.db")
        cipher = _make_cipher()
        store = EncryptedSubstrateStore(db_path=db, embed_fn=fake_embed, cipher=cipher)

        store.ingest_document("cars.txt", "engine pistons turbocharger crankshaft")
        store.ingest_document("garden.txt", "tomatoes basil compost watering")

        hits = store.retrieve("turbocharger engine pistons", k_docs=1, k_turns=0)
        assert len(hits) == 1
        assert hits[0].source == "cars.txt"

        # Re-ingest cars.txt (DELETEs its prior chunk under secure_delete) and
        # confirm retrieval still returns the updated content correctly.
        store.ingest_document("cars.txt", "diesel torque horsepower transmission")
        hits2 = store.retrieve("diesel torque horsepower", k_docs=1, k_turns=0)
        assert len(hits2) == 1
        assert hits2[0].source == "cars.txt"
        assert "diesel" in hits2[0].text
        assert store.count("doc") == 2
        store.close()
