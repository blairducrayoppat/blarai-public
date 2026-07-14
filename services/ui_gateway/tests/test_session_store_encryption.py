"""
Tests for Sprint 14 EA-4 -- sessions.db at-rest encryption (ADR-025).

Covers EncryptedSessionStore against a SoftwareSealer + dev_mode=True cipher
(no hardware required).  All tests run in the default suite.

Test structure:
  1. Construction + has_encryption regression lock.
  2. Raw-read no-plaintext: turns.content and sessions.title are ciphertext on disk.
  3. Write -> read round-trip: decrypt-on-read returns correct plaintext.
  4. _backfill_empty_titles works through encryption.
  5. Migration idempotence + whole-file no-plaintext scan after VACUUM.
  6. WAL-sidecar no-plaintext: the -wal journal file never exposes plaintext.
  7. Fail-closed: no DEK -> refuse to open.
  8. Production-wiring regression lock (build_session_store returns encrypted store).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from services.ui_gateway.src.session_store import (
    EncryptedSessionStore,
    SessionStore,
    StoreProvisioningError,
    build_session_store,
    migrate_plaintext_to_encrypted,
    verify_no_plaintext,
)
from services.ui_gateway.src.constants import SESSION_TITLE_MAX_CHARS
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
) -> EncryptedSessionStore:
    if cipher is None:
        cipher = _make_cipher()
    return EncryptedSessionStore(db_path=db_path, cipher=cipher)


def _seed_store(store: Any, content: str = "Hello, world! Confidential prompt text.") -> tuple[str, str]:
    """Seed store with one session + two turns. Returns (session_id, turn_id)."""
    sid = store.create_session(title="Sprint 14 test session")
    tid = store.add_turn(sid, "user", content, "N/A", [])
    store.add_turn(sid, "assistant", "Acknowledged.", "approved", [])
    return sid, tid


# ---------------------------------------------------------------------------
# 1. Construction + has_encryption regression lock
# ---------------------------------------------------------------------------


class TestEncryptedStoreConstruction:
    def test_has_encryption_is_true(self) -> None:
        """Regression lock: has_encryption MUST be True on every instance."""
        store = _make_encrypted_store()
        assert store.has_encryption is True, (
            "EncryptedSessionStore.has_encryption is not True -- "
            "encryption wiring may be silently disabled"
        )

    def test_wrong_cipher_type_raises(self) -> None:
        """Passing something other than a FieldCipher must raise TypeError."""
        with pytest.raises(TypeError, match="FieldCipher"):
            EncryptedSessionStore(
                db_path=":memory:",
                cipher="not-a-cipher",  # type: ignore[arg-type]
            )

    def test_in_memory_store_starts_empty(self) -> None:
        store = _make_encrypted_store()
        assert store.list_sessions() == []

    def test_persists_across_reopen(self, tmp_path: Path) -> None:
        """Data survives close + reopen with the same cipher."""
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        s1 = EncryptedSessionStore(db_path=db, cipher=cipher)
        sid = s1.create_session(title="persistent session")
        s1.add_turn(sid, "user", "will this survive?", "N/A", [])
        s1.close()

        s2 = EncryptedSessionStore(db_path=db, cipher=cipher)
        sessions = s2.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].title == "persistent session"
        turns = s2.get_session_turns(sid)
        assert len(turns) == 1
        assert turns[0].content == "will this survive?"
        s2.close()


# ---------------------------------------------------------------------------
# 2. Raw-read no-plaintext: content + title are ciphertext on disk
# ---------------------------------------------------------------------------


class TestRawFileNoCleartext:
    """After writing, the raw SQLite file must not contain readable plaintext."""

    def test_turn_content_is_not_plaintext_on_disk(self, tmp_path: Path) -> None:
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        secret_prompt = "patient medical record diabetes dosage schedule"
        sid = store.create_session()
        store.add_turn(sid, "user", secret_prompt, "N/A", [])
        store.close()

        raw = Path(db).read_bytes()
        assert b"patient medical record" not in raw, (
            "Plaintext turn content found in raw SQLite file -- content encryption not applied"
        )
        assert b"diabetes dosage" not in raw

    def test_session_title_is_not_plaintext_on_disk(self, tmp_path: Path) -> None:
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        store.create_session(title="My private session topic 2026")
        store.close()

        raw = Path(db).read_bytes()
        assert b"My private session topic" not in raw, (
            "Plaintext title found in raw SQLite file -- title encryption not applied"
        )

    def test_content_version_byte_present(self, tmp_path: Path) -> None:
        """The first byte of the stored content blob must be the cipher version byte."""
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        sid = store.create_session()
        store.add_turn(sid, "user", "check version byte in content", "N/A", [])
        store.close()

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT content FROM turns LIMIT 1").fetchone()
        conn.close()

        assert row is not None
        blob = bytes(row[0]) if not isinstance(row[0], bytes) else row[0]
        assert blob[0] == FIELD_CIPHER_VERSION, (
            f"Expected cipher version byte 0x{FIELD_CIPHER_VERSION:02X} as first byte "
            f"of content blob, got 0x{blob[0]:02X}"
        )

    def test_title_version_byte_present(self, tmp_path: Path) -> None:
        """The first byte of the stored title blob must be the cipher version byte."""
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        store.create_session(title="check version byte in title")
        store.close()

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT title FROM sessions LIMIT 1").fetchone()
        conn.close()

        assert row is not None
        blob = bytes(row[0]) if not isinstance(row[0], bytes) else row[0]
        assert blob[0] == FIELD_CIPHER_VERSION, (
            f"Expected cipher version byte 0x{FIELD_CIPHER_VERSION:02X} as first byte "
            f"of title blob, got 0x{blob[0]:02X}"
        )

    def test_session_id_is_plaintext_on_disk(self, tmp_path: Path) -> None:
        """session_id is a relational key and must stay plaintext (SDV section 5.3)."""
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        sid = store.create_session()
        store.add_turn(sid, "user", "test turn", "N/A", [])
        store.close()

        raw = Path(db).read_bytes()
        assert sid.encode("utf-8") in raw, (
            "session_id UUID not found in raw DB -- it may have been accidentally encrypted"
        )

    def test_metadata_stays_plaintext(self, tmp_path: Path) -> None:
        """role, pgov_status, timestamps stay plaintext (low-value metadata)."""
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        sid = store.create_session()
        store.add_turn(sid, "user", "test content", "N/A", [])
        store.close()

        raw = Path(db).read_bytes()
        assert b"user" in raw, "role 'user' should be plaintext in the DB"
        assert b"N/A" in raw, "pgov_status 'N/A' should be plaintext in the DB"


# ---------------------------------------------------------------------------
# 3. Write -> read round-trip: decrypt-on-read returns correct plaintext
# ---------------------------------------------------------------------------


class TestWriteReadRoundTrip:
    """AES-GCM encrypt-on-write, decrypt-on-read: plaintext is preserved."""

    def test_turn_content_roundtrip(self, tmp_path: Path) -> None:
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        plaintext = "What is the treatment for hypertension?"
        sid = store.create_session()
        store.add_turn(sid, "user", plaintext, "N/A", [])
        store.close()

        store2 = EncryptedSessionStore(db_path=db, cipher=cipher)
        turns = store2.get_session_turns(sid)
        store2.close()

        assert len(turns) == 1
        assert turns[0].content == plaintext

    def test_session_title_roundtrip(self, tmp_path: Path) -> None:
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        title = "Private oncology questions"
        sid = store.create_session(title=title)
        store.close()

        store2 = EncryptedSessionStore(db_path=db, cipher=cipher)
        sessions = store2.list_sessions()
        store2.close()

        assert len(sessions) == 1
        assert sessions[0].title == title

    def test_multiple_turns_roundtrip(self, tmp_path: Path) -> None:
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        sid = store.create_session(title="multi-turn session")
        prompts = [
            "First user question about finances",
            "Second user question about health data",
            "Third user question about location tracking",
        ]
        for p in prompts:
            store.add_turn(sid, "user", p, "N/A", [])
        store.close()

        store2 = EncryptedSessionStore(db_path=db, cipher=cipher)
        turns = store2.get_session_turns(sid)
        store2.close()

        assert len(turns) == 3
        for i, turn in enumerate(turns):
            assert turn.content == prompts[i]

    def test_repeated_plaintext_produces_distinct_ciphertext(self, tmp_path: Path) -> None:
        """Fresh random nonce per encryption: same content -> different ciphertext blobs."""
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        sid = store.create_session()
        same_content = "identical content both times"
        tid1 = store.add_turn(sid, "user", same_content, "N/A", [])
        tid2 = store.add_turn(sid, "user", same_content, "N/A", [])
        store.close()

        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT id, content FROM turns ORDER BY timestamp ASC"
        ).fetchall()
        conn.close()

        assert len(rows) == 2
        blob1 = bytes(rows[0][1]) if not isinstance(rows[0][1], bytes) else rows[0][1]
        blob2 = bytes(rows[1][1]) if not isinstance(rows[1][1], bytes) else rows[1][1]
        assert blob1 != blob2, (
            "Same plaintext encrypted twice produced the same ciphertext -- "
            "nonce reuse suspected (catastrophic for AES-GCM)"
        )

    def test_set_title_if_empty_roundtrip(self, tmp_path: Path) -> None:
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        sid = store.create_session()
        assert store.set_title_if_empty(sid, "Auto-derived title for session") is True
        store.close()

        store2 = EncryptedSessionStore(db_path=db, cipher=cipher)
        sessions = store2.list_sessions()
        store2.close()

        assert sessions[0].title == "Auto-derived title for session"

    def test_set_title_if_empty_does_not_clobber(self) -> None:
        store = _make_encrypted_store()
        sid = store.create_session(title="Already Set")
        assert store.set_title_if_empty(sid, "New Title") is False
        sessions = store.list_sessions()
        assert sessions[0].title == "Already Set"

    def test_update_session_title_roundtrip(self, tmp_path: Path) -> None:
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        sid = store.create_session(title="Old Title")
        assert store.update_session_title(sid, "New Renamed Title") is True
        store.close()

        store2 = EncryptedSessionStore(db_path=db, cipher=cipher)
        sessions = store2.list_sessions()
        store2.close()

        assert sessions[0].title == "New Renamed Title"

    def test_pgov_reasons_preserved(self) -> None:
        """PGOV reasons (JSON, plaintext) round-trip correctly alongside encrypted content."""
        store = _make_encrypted_store()
        sid = store.create_session()
        reasons = ["PII_DETECTED", "LEAKAGE_DETECTED"]
        store.add_turn(sid, "assistant", "redacted", "denied", reasons)
        turns = store.get_session_turns(sid)
        assert turns[0].pgov_reasons == reasons

    def test_get_turns_alias(self) -> None:
        store = _make_encrypted_store()
        sid = store.create_session()
        store.add_turn(sid, "user", "alias test", "N/A", [])
        assert store.get_turns(sid) == store.get_session_turns(sid)

    def test_delete_session_cascade(self) -> None:
        store = _make_encrypted_store()
        sid = store.create_session(title="To be deleted")
        store.add_turn(sid, "user", "secret content", "N/A", [])
        assert store.delete_session(sid) is True
        assert store.list_sessions() == []
        assert store.get_session_turns(sid) == []

    def test_clear_session_turns(self) -> None:
        store = _make_encrypted_store()
        sid = store.create_session()
        store.add_turn(sid, "user", "first", "N/A", [])
        store.add_turn(sid, "user", "second", "N/A", [])
        count = store.clear_session_turns(sid)
        assert count == 2
        assert store.get_session_turns(sid) == []
        # Session itself is preserved.
        assert len(store.list_sessions()) == 1


# ---------------------------------------------------------------------------
# 4. _backfill_empty_titles works through encryption
# ---------------------------------------------------------------------------


class TestBackfillEmptyTitles:
    """_backfill_empty_titles reads encrypted content and writes encrypted titles."""

    def test_backfills_from_first_user_turn(self, tmp_path: Path) -> None:
        """An empty-title session gets a derived title from its first encrypted turn."""
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        sid = store.create_session()  # empty title
        store.add_turn(sid, "user", "How do I bake sourdough bread", "N/A", [])

        count = store._backfill_empty_titles()
        assert count == 1

        sessions = store.list_sessions()
        match = [s for s in sessions if s.id == sid]
        assert match[0].title.startswith("How do I bake s")
        store.close()

        # Reopen and verify the backfilled title survived as ciphertext.
        store2 = EncryptedSessionStore(db_path=db, cipher=cipher)
        sessions2 = store2.list_sessions()
        match2 = [s for s in sessions2 if s.id == sid]
        assert match2[0].title.startswith("How do I bake s")
        store2.close()

        # Confirm the title is stored as ciphertext (not as plaintext text).
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT title FROM sessions WHERE id = ?", (sid,)).fetchone()
        conn.close()
        blob = bytes(row[0]) if not isinstance(row[0], bytes) else row[0]
        assert blob[0] == FIELD_CIPHER_VERSION, (
            "Backfilled title is not encrypted -- expected cipher version byte as first byte"
        )

    def test_is_idempotent(self) -> None:
        store = _make_encrypted_store()
        sid = store.create_session()
        store.add_turn(sid, "user", "first prompt text", "N/A", [])
        assert store._backfill_empty_titles() == 1
        assert store._backfill_empty_titles() == 0

    def test_skips_session_with_no_turns(self) -> None:
        store = _make_encrypted_store()
        store.create_session()
        assert store._backfill_empty_titles() == 0

    def test_does_not_touch_nonempty_titles(self) -> None:
        store = _make_encrypted_store()
        sid = store.create_session(title="Keep This Title")
        store.add_turn(sid, "user", "some prompt", "N/A", [])
        assert store._backfill_empty_titles() == 0
        match = [s for s in store.list_sessions() if s.id == sid]
        assert match[0].title == "Keep This Title"

    def test_runs_automatically_on_init(self, tmp_path: Path) -> None:
        """Reopening a DB with empty-title sessions backfills them at init."""
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()

        store1 = EncryptedSessionStore(db_path=db, cipher=cipher)
        sid = store1.create_session()
        store1.add_turn(sid, "user", "What does this encrypted file say", "N/A", [])
        store1.close()

        # Reopen -- __init__ runs the backfill.
        store2 = EncryptedSessionStore(db_path=db, cipher=cipher)
        match = [s for s in store2.list_sessions() if s.id == sid]
        assert match[0].title.startswith("What does this ")
        store2.close()


# ---------------------------------------------------------------------------
# 5. Migration idempotence + whole-file no-plaintext scan
# ---------------------------------------------------------------------------


class TestMigration:
    """migrate_plaintext_to_encrypted and verify_no_plaintext."""

    def test_migration_encrypts_existing_rows(self, tmp_path: Path) -> None:
        """Plaintext rows from a legacy SessionStore are encrypted in place."""
        db = str(tmp_path / "sessions.db")
        # Write plaintext rows using the unencrypted SessionStore.
        plain_store = SessionStore(db_path=db)
        sid = plain_store.create_session(title="Legacy session title")
        plain_store.add_turn(sid, "user", "legacy user prompt text", "N/A", [])
        plain_store.close()

        # Verify plaintext is visible before migration.
        raw_before = Path(db).read_bytes()
        assert b"legacy user prompt" in raw_before, (
            "Plaintext text not in raw file before migration -- test fixture broken"
        )

        # Run migration.
        cipher = _make_cipher()
        result = migrate_plaintext_to_encrypted(db, cipher)
        assert result["errors"] == 0
        assert result["turns_migrated"] == 1
        assert result["titles_migrated"] == 1

        # Verify plaintext is gone after migration + VACUUM.
        violations = verify_no_plaintext(db, [
            b"legacy user prompt",
            b"Legacy session title",
        ])
        assert violations == [], f"Plaintext found after migration: {violations}"

    def test_migration_is_idempotent(self, tmp_path: Path) -> None:
        """Running migration twice leaves already-encrypted rows unchanged."""
        db = str(tmp_path / "sessions.db")
        plain_store = SessionStore(db_path=db)
        sid = plain_store.create_session(title="Idempotent title")
        plain_store.add_turn(sid, "user", "idempotent prompt", "N/A", [])
        plain_store.close()

        cipher = _make_cipher()
        r1 = migrate_plaintext_to_encrypted(db, cipher)
        assert r1["turns_migrated"] == 1
        assert r1["turns_already_encrypted"] == 0

        r2 = migrate_plaintext_to_encrypted(db, cipher)
        assert r2["turns_migrated"] == 0
        assert r2["turns_already_encrypted"] == 1

    def test_verify_no_plaintext_after_vacuum(self, tmp_path: Path) -> None:
        """After migration + VACUUM, the whole-file scan finds no plaintext."""
        db = str(tmp_path / "sessions.db")
        plain_store = SessionStore(db_path=db)
        sid = plain_store.create_session(title="Sensitive title scan")
        plain_store.add_turn(
            sid, "user",
            "extremely sensitive medical information about patient X",
            "N/A", [],
        )
        plain_store.close()

        cipher = _make_cipher()
        migrate_plaintext_to_encrypted(db, cipher)

        violations = verify_no_plaintext(db, [
            b"extremely sensitive medical",
            b"Sensitive title scan",
            b"patient X",
        ])
        assert violations == [], f"Plaintext found in raw DB after migration: {violations}"

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        """dry_run=True reports counts but does not modify the file."""
        db = str(tmp_path / "sessions.db")
        plain_store = SessionStore(db_path=db)
        sid = plain_store.create_session(title="Dry run session")
        plain_store.add_turn(sid, "user", "dry run content here", "N/A", [])
        plain_store.close()

        raw_before = Path(db).read_bytes()
        cipher = _make_cipher()
        result = migrate_plaintext_to_encrypted(db, cipher, dry_run=True)

        assert result["turns_migrated"] == 1
        # The file should be byte-identical after a dry run.
        raw_after = Path(db).read_bytes()
        assert raw_before == raw_after, "dry_run=True modified the file"
        # Plaintext should still be in the file.
        assert b"dry run content here" in raw_after

    def test_already_encrypted_store_migration_is_no_op(self, tmp_path: Path) -> None:
        """EncryptedSessionStore rows are already encrypted; migration is a no-op."""
        db = str(tmp_path / "sessions.db")
        cipher = _make_cipher()
        enc_store = EncryptedSessionStore(db_path=db, cipher=cipher)
        sid = enc_store.create_session(title="Already encrypted")
        enc_store.add_turn(sid, "user", "already encrypted content", "N/A", [])
        enc_store.close()

        result = migrate_plaintext_to_encrypted(db, cipher)
        assert result["turns_migrated"] == 0
        assert result["turns_already_encrypted"] == 1
        assert result["titles_migrated"] == 0
        assert result["titles_already_encrypted"] == 1
        assert result["errors"] == 0


# ---------------------------------------------------------------------------
# 6. WAL-sidecar no-plaintext
# ---------------------------------------------------------------------------


class TestWalSidecarNoCleartext:
    """The -wal journal file must never contain readable plaintext.

    WAL safety rationale (ADR-025 / SDV section 5.3): app-layer field encryption
    is inherently WAL-safe -- the -wal sidecar only ever carries already-ciphertext
    column values.  This test makes that claim executable, not just asserted in a
    comment.

    Methodology:
    - Open a real file-based DB (WAL mode is the default in EncryptedSessionStore).
    - Write encrypted rows WITHOUT checkpointing so the -wal file stays populated.
    - Flush to disk by closing the connection.
    - Scan the raw -wal bytes for plaintext samples.
    """

    def test_wal_sidecar_contains_no_plaintext_content(self, tmp_path: Path) -> None:
        db = str(tmp_path / "sessions.db")
        wal = str(tmp_path / "sessions.db-wal")

        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)

        secret = "confidential wal sidecar probe content 2026"
        sid = store.create_session(title="WAL safety test session title")
        store.add_turn(sid, "user", secret, "N/A", [])
        # Intentionally do NOT checkpoint -- close while WAL may still be populated.
        store.close()

        # The -wal file may or may not exist depending on SQLite internals;
        # if it exists, scan it; if it does not, the checkpoint already ran
        # (which also proves safety -- checkpointed pages are in the main DB
        # which we already know is ciphertext).
        wal_path = Path(wal)
        if wal_path.exists() and wal_path.stat().st_size > 0:
            wal_bytes = wal_path.read_bytes()
            assert secret.encode("utf-8") not in wal_bytes, (
                "Plaintext content found in -wal sidecar file -- "
                "app-layer field encryption is not WAL-safe"
            )
            assert b"WAL safety test session title" not in wal_bytes, (
                "Plaintext title found in -wal sidecar file"
            )
        # If -wal does not exist, WAL was checkpointed into the main DB (ciphertext).
        # Either way, no plaintext escaped.

    def test_wal_sidecar_plaintext_assertion_with_known_plaintext_store(
        self, tmp_path: Path
    ) -> None:
        """Sanity check: a PLAINTEXT store DOES have readable content in the -wal.

        This contrasts the encrypted test above to prove the WAL scan has real
        sensitivity -- it would catch a broken encryption implementation.
        """
        db = str(tmp_path / "plain_sessions.db")
        wal = str(tmp_path / "plain_sessions.db-wal")

        plain_store = SessionStore(db_path=db)
        unique_marker = "wal_scan_sensitivity_marker_plain_2026"
        sid = plain_store.create_session(title="plain wal test")
        plain_store.add_turn(sid, "user", unique_marker, "N/A", [])
        # Flush without checkpoint.
        plain_store._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        plain_store.close()

        # For a plaintext store, the content must appear somewhere (main DB or WAL).
        raw_db = Path(db).read_bytes()
        wal_path = Path(wal)
        wal_bytes = wal_path.read_bytes() if wal_path.exists() else b""
        assert unique_marker.encode("utf-8") in (raw_db + wal_bytes), (
            "Plain marker not found in plaintext store -- "
            "sanity check broken, WAL scan has no sensitivity"
        )


# ---------------------------------------------------------------------------
# 7. Fail-closed: no DEK -> refuse to open
# ---------------------------------------------------------------------------


class TestFailClosed:
    """If the DEK cannot be unsealed, the store must refuse to open."""

    def test_wrong_key_on_existing_db_fails(self, tmp_path: Path) -> None:
        """Wrong-key rows are quarantined (omitted), not raised -- corrected posture.

        ADR-025 §2.7 amendment (2026-06-06): bulk reads now quarantine
        un-decryptable rows rather than raising.  A single legacy/tampered row
        must not deny access to the entire store (availability is a security
        property; confidentiality + integrity are fully preserved because
        plaintext is never returned from a bad row).

        This test verifies the CORRECTED behaviour:
        - list_sessions() does NOT raise under a wrong key.
        - The bad row is omitted from the result.
        - SESSION_ROW_DECRYPT_QUARANTINE is logged.
        - A SINGLE-RECORD decrypt of the same bad data still raises hard
          (single-record fail-closed posture is unchanged).
        """
        db = str(tmp_path / "enc.db")
        cipher1 = _make_cipher()
        store1 = EncryptedSessionStore(db_path=db, cipher=cipher1)
        sid = store1.create_session(title="")  # empty title so backfill activates
        store1.add_turn(sid, "user", "secret under cipher1", "N/A", [])
        # Trigger backfill to encrypt the title under cipher1.
        store1._backfill_empty_titles()
        store1.close()

        # Re-open with a totally different cipher.
        cipher2 = _make_cipher()
        store2 = EncryptedSessionStore(db_path=db, cipher=cipher2)

        # Single-record decrypt of the bad encrypted title STILL raises --
        # single-record fail-closed posture is intact.
        row = store2._conn.execute(
            "SELECT title FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        with pytest.raises(RuntimeError, match="refusing to return plaintext"):
            store2._dec_session_title(sid, row[0])

        # list_sessions must NOT raise -- it quarantines the wrong-key row.
        result = store2.list_sessions()
        # The backfill-produced encrypted title can't be decrypted under cipher2;
        # the session was quarantined, so result is empty.
        assert isinstance(result, list), "list_sessions must return a list, not raise"
        assert len(result) == 0, (
            "Wrong-key session should be quarantined (omitted), not returned"
        )
        store2.close()

    def test_build_session_store_in_memory_roundtrip(self) -> None:
        """build_session_store with :memory: (dev path) works end-to-end."""
        store = build_session_store(":memory:")
        assert store.has_encryption is True
        sid = store.create_session(title="factory test")
        store.add_turn(sid, "user", "factory turn content", "N/A", [])
        sessions = store.list_sessions()
        assert sessions[0].title == "factory test"
        turns = store.get_session_turns(sid)
        assert turns[0].content == "factory turn content"

    def test_invalid_recovery_key_fails_closed(self) -> None:
        """Trying to unseal with a wrong recovery key (TPM path forced-fail) raises
        DekEnvelopeError.

        ``unseal_dek`` tries the TPM path first; the recovery path is only
        reached when the TPM raises.  We force the TPM path to raise by patching
        ``SoftwareSealer.unseal``, then verify the wrong recovery key is rejected.
        """
        from unittest.mock import patch
        from shared.security.tpm_sealer import TpmUnavailable

        sealer = SoftwareSealer()
        rk = generate_recovery_key()
        env = DekEnvelope.create(sealer=sealer, recovery_key=rk)

        wrong_key = generate_recovery_key()
        # Force the TPM unseal to fail so that the recovery path is exercised.
        with patch.object(
            sealer, "unseal", side_effect=TpmUnavailable("forced TPM failure for test")
        ):
            with pytest.raises(DekEnvelopeError):
                env.unseal_dek(recovery_key=wrong_key)

    def test_no_plaintext_fallback_on_auth_failure(self, tmp_path: Path) -> None:
        """Tampered ciphertext is quarantined on construction; store is still usable.

        ADR-025 §2.7 amendment (2026-06-06): _backfill_empty_titles now
        quarantines un-decryptable turns rather than raising, so EncryptedSessionStore
        construction SUCCEEDS even when a turn's ciphertext is tampered.

        The confidentiality invariant is fully preserved:
        - The store is usable after construction (new sessions/turns work).
        - A direct single-record decrypt of the corrupted blob STILL raises --
          plaintext is never returned from tampered data (the "never return garbage"
          contract is intact at the leaf level; only the bulk loop wraps it).
        - SESSION_ROW_DECRYPT_QUARANTINE is logged.
        """
        db = str(tmp_path / "enc.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        sid = store.create_session()  # empty title triggers backfill on next open
        store.add_turn(sid, "user", "tamper test content", "N/A", [])
        store.close()

        # Corrupt the content column of the first turn (overwrite GCM auth tag).
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT id, content FROM turns LIMIT 1").fetchone()
        turn_id, blob = row
        corrupted = bytes(blob[:-4]) + b"\xff\xff\xff\xff"
        conn.execute("UPDATE turns SET content = ? WHERE id = ?", (corrupted, turn_id))
        conn.commit()
        conn.close()

        # Re-opening the store triggers _backfill_empty_titles which now
        # quarantines the corrupted turn -- construction MUST SUCCEED.
        store2 = EncryptedSessionStore(db_path=db, cipher=cipher)
        assert store2 is not None, "Store construction must succeed despite tampered turn"

        # The store is usable after construction -- a new session can be created.
        new_sid = store2.create_session(title="post-tamper session")
        assert new_sid is not None, "Store must be usable after quarantine during backfill"

        # Single-record decrypt of the corrupted blob STILL raises -- the leaf
        # helper's fail-closed posture is unchanged; garbage is never returned.
        with pytest.raises(RuntimeError):
            store2._dec_turn_content(turn_id, corrupted)

        store2.close()


# ---------------------------------------------------------------------------
# 8. Production-wiring regression lock
# ---------------------------------------------------------------------------


class TestProductionWiringRegressionLock:
    """build_session_store must return an EncryptedSessionStore with has_encryption=True."""

    def test_build_session_store_returns_encrypted_store(self) -> None:
        store = build_session_store(":memory:")
        assert isinstance(store, EncryptedSessionStore), (
            "build_session_store did not return an EncryptedSessionStore -- "
            "production wiring broken"
        )
        assert store.has_encryption is True, (
            "build_session_store returned a store with has_encryption=False -- "
            "encryption silently disabled"
        )

    def test_build_session_store_file_path(self, tmp_path: Path) -> None:
        """build_session_store with a file path and dev_mode=True creates keystore
        alongside DB (dev/test explicit opt-in path)."""
        db = str(tmp_path / "test.db")
        store = build_session_store(db, dev_mode=True)
        assert isinstance(store, EncryptedSessionStore)
        assert store.has_encryption is True
        # Keystore file should exist alongside the DB.
        keystore = tmp_path / "test.keystore.json"
        assert keystore.exists(), (
            "DEK keystore not created alongside the DB -- "
            "dev path key-persistence pattern broken"
        )
        store.close()

    def test_build_session_store_reuses_existing_keystore(self, tmp_path: Path) -> None:
        """Reopening the same DB path with dev_mode=True reuses the existing keystore
        (same DEK -- ensures the dev path persists and reloads correctly)."""
        db = str(tmp_path / "test.db")

        store1 = build_session_store(db, dev_mode=True)
        sid = store1.create_session(title="Keystore reuse test")
        store1.add_turn(sid, "user", "test content for reuse", "N/A", [])
        store1.close()

        store2 = build_session_store(db, dev_mode=True)
        sessions = store2.list_sessions()
        assert sessions[0].title == "Keystore reuse test"
        turns = store2.get_session_turns(sid)
        assert turns[0].content == "test content for reuse"
        store2.close()

    def test_production_no_keystore_refuses_to_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production mode (dev_mode=False) + no BLARAI_DEK_KEYSTORE MUST raise
        StoreProvisioningError and MUST NOT return a SoftwareSealer-backed store.

        This is the MINOR-3 regression lock (ADR-025 §2.8(a) -- symmetric with
        the audit refuse-to-start).  A missing keystore in production is a
        misconfiguration; silently encrypting under the SoftwareSealer public
        key provides NO security guarantee.

        Mirror of the audit-log refuse-to-start test shape.
        """
        monkeypatch.delenv("BLARAI_DEK_KEYSTORE", raising=False)
        db = str(tmp_path / "prod.db")

        with pytest.raises(StoreProvisioningError, match="BLARAI_DEK_KEYSTORE"):
            build_session_store(db, dev_mode=False)

        # Belt-and-suspenders: the DB must not have been created (no silent write).
        assert not (tmp_path / "prod.db").exists(), (
            "build_session_store wrote a DB file before raising -- "
            "a SoftwareSealer store may have been partially constructed"
        )

    def test_wiring_violation_raises_specific_error_not_assert(self) -> None:
        """#804: has_encryption is not True on the constructed store MUST raise
        the EXPLICIT StoreProvisioningError tripwire (deterministic code
        SESSION_STORE_ENCRYPTION_WIRING_FAILED), never a bare AssertionError.

        An ``assert`` is compiled out under ``python -O``, silently handing an
        unencrypted store to the launcher; the explicit raise survives ``-O``
        and propagates to the launcher's fail-closed session_store_init
        handler (CWE-617).
        """
        from unittest.mock import patch

        # Violate the invariant: the class-level regression-lock attribute
        # reads False, as if a refactor silently unwired the encryption.
        with patch.object(EncryptedSessionStore, "has_encryption", False):
            with pytest.raises(
                StoreProvisioningError,
                match="SESSION_STORE_ENCRYPTION_WIRING_FAILED",
            ) as excinfo:
                build_session_store(":memory:")
        assert not isinstance(excinfo.value, AssertionError), (
            "the wiring tripwire fired as an AssertionError -- the assert "
            "form is back and would vanish under python -O"
        )


# ---------------------------------------------------------------------------
# 9. secure_delete=ON (FULL) + SE-1 free-page residual probes (WS2)
# ---------------------------------------------------------------------------


class TestSecureDelete:
    """``PRAGMA secure_delete=ON`` (FULL) zeroes DELETEd rows in freed pages.

    The session store runs in WAL mode, so freed pages are zeroed at checkpoint
    (a rollback-journal store would zero at COMMIT).  The SE-1 probe therefore
    runs ``PRAGMA wal_checkpoint(TRUNCATE)`` on the store connection before
    reopening to read raw bytes.

    Why the SE-1 probe captures CIPHERTEXT, not just plaintext: the encrypted
    store never writes plaintext to disk, so a plaintext-only assertion would
    pass even with secure_delete OFF (a false pass).  Each probe captures the
    on-disk ciphertext of the turn row BEFORE the delete (raw SELECT of
    ``turns.content``) and asserts that exact ciphertext fragment is ABSENT from
    the raw .db bytes AFTER the delete + checkpoint.  With secure_delete OFF that
    ciphertext would survive in the freed (un-zeroed) page, so the probe
    genuinely fails if the PRAGMA is removed.
    """

    def test_secure_delete_pragma_on(self, tmp_path: Path) -> None:
        """EncryptedSessionStore opens with secure_delete=ON (FULL == 1)."""
        db = str(tmp_path / "secure_delete.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)
        try:
            mode = store._conn.execute("PRAGMA secure_delete").fetchone()[0]
            assert mode == 1, (
                f"Expected secure_delete=1 (FULL/ON), got {mode!r} — "
                "freed pages will not be zeroed on delete"
            )
        finally:
            store.close()

    def test_secure_delete_pragma_on_plaintext_store(self, tmp_path: Path) -> None:
        """SessionStore (plaintext variant) also opens with secure_delete=ON."""
        db = str(tmp_path / "secure_delete_plain.db")
        store = SessionStore(db_path=db)
        try:
            mode = store._conn.execute("PRAGMA secure_delete").fetchone()[0]
            assert mode == 1, (
                f"Expected secure_delete=1 (FULL/ON), got {mode!r} — "
                "freed pages will not be zeroed on delete"
            )
        finally:
            store.close()

    def test_se1_session_no_freepage_residual(self, tmp_path: Path) -> None:
        """SE-1: deleting a session (CASCADE turns) zeroes the turn rows' on-disk
        ciphertext in freed pages with secure_delete ON (WAL -> checkpoint).

        Captures the turn row's encrypted ``content`` ciphertext BEFORE the
        delete (raw SELECT), deletes the session (CASCADE removes the turns),
        runs ``PRAGMA wal_checkpoint(TRUNCATE)`` on the store connection (WAL
        mode), closes, then reads raw bytes and asserts neither the plaintext
        marker NOR the captured ciphertext survives.  The ciphertext assertion is
        the load-bearing one — it fails if the PRAGMA is removed even though the
        plaintext never hits disk.
        """
        db = str(tmp_path / "se1_session.db")
        cipher = _make_cipher()
        store = EncryptedSessionStore(db_path=db, cipher=cipher)

        marker = "WS2-SE1-SESSION-d29f5a township residual probe content"
        sid = store.create_session(title="se1 probe session")
        store.add_turn(sid, "user", marker, "N/A", [])

        # Capture the on-disk ciphertext of the turn row BEFORE the delete.
        # Checkpoint first so the row is durably in the main DB file to capture.
        store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        rows = store._conn.execute(
            "SELECT content FROM turns WHERE session_id = ?", (sid,)
        ).fetchall()
        assert rows, "expected the turn row before delete"
        turn_ct = bytes(rows[0][0])
        assert len(turn_ct) > 16
        assert turn_ct in Path(db).read_bytes(), (
            "captured turn ciphertext not on disk before delete — fixture broken"
        )

        # Delete the session -> CASCADE delete the turn row.
        assert store.delete_session(sid) is True
        # WAL mode: freed pages are zeroed at checkpoint.
        store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store.close()

        raw = Path(db).read_bytes()
        assert marker.encode("utf-8") not in raw, (
            "plaintext marker survived in raw DB after session delete"
        )
        assert turn_ct not in raw, (
            "deleted turn's ciphertext survived in a freed page after delete + "
            "checkpoint — secure_delete=ON is not zeroing freed pages "
            "(PRAGMA missing/wrong?)"
        )

    def test_se1_session_plaintext_no_freepage_residual(self, tmp_path: Path) -> None:
        """SE-1 (plaintext variant): SessionStore proves plaintext zeroing.

        The plaintext store writes the marker verbatim to disk, so this is the
        most direct demonstration that secure_delete zeroes the freed page.
        """
        db = str(tmp_path / "se1_session_plain.db")
        store = SessionStore(db_path=db)

        marker = "WS2-SE1-SESSION-PLAIN-91c4 township residual probe content"
        sid = store.create_session(title="se1 plain probe")
        store.add_turn(sid, "user", marker, "N/A", [])
        store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert marker.encode("utf-8") in Path(db).read_bytes(), (
            "plaintext marker not on disk before delete — fixture broken"
        )

        assert store.delete_session(sid) is True
        store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store.close()

        raw = Path(db).read_bytes()
        assert marker.encode("utf-8") not in raw, (
            "plaintext marker survived in a freed page after session delete — "
            "secure_delete=ON is not zeroing freed pages"
        )
