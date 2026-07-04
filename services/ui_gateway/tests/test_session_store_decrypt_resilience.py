"""
Regression tests for ADR-025 §2.7 amendment -- bulk-read decrypt resilience.

Sprint 15 follow-up #618 (2026-06-06): EncryptedSessionStore bulk readers
(list_sessions, get_session_turns, _backfill_empty_titles) now quarantine
un-decryptable rows rather than raising.  These tests lock that corrected
posture and confirm the confidentiality/integrity invariants are untouched.

All tests use tmp_path / :memory: and NEVER touch the real %LOCALAPPDATA%.
LOCALAPPDATA isolation is provided by the root conftest.py (process-lifetime
redirect) and the ui_gateway conftest.py (per-test autouse monkeypatch).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from services.ui_gateway.src.session_store import EncryptedSessionStore
from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.tpm_sealer import SoftwareSealer


# ---------------------------------------------------------------------------
# Helpers (mirror the pattern from test_session_store_encryption.py)
# ---------------------------------------------------------------------------


def _make_cipher() -> FieldCipher:
    """Build a FieldCipher from a freshly-generated DEK (SoftwareSealer path)."""
    sealer = SoftwareSealer()
    rk = generate_recovery_key()
    env = DekEnvelope.create(sealer=sealer, recovery_key=rk)
    dek = env.unseal_dek()
    return FieldCipher(derive_subkeys(dek))


def _make_store(db_path: str, cipher: FieldCipher | None = None) -> EncryptedSessionStore:
    if cipher is None:
        cipher = _make_cipher()
    return EncryptedSessionStore(db_path=db_path, cipher=cipher)


# ---------------------------------------------------------------------------
# Test 1 -- list_sessions quarantines rows encrypted under a different key
# ---------------------------------------------------------------------------


class TestListSessionsQuarantinesBadKey:
    """list_sessions does not raise when rows are encrypted under a foreign key."""

    def test_two_sessions_wrong_key_quarantined(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """2 sessions encrypted under cipher_a; re-open under cipher_b.

        Expected: list_sessions returns [] (both rows quarantined), no raise,
        SESSION_ROW_DECRYPT_QUARANTINE event logged with count summary.
        """
        db = str(tmp_path / "enc.db")
        cipher_a = _make_cipher()
        store_a = _make_store(db_path=db, cipher=cipher_a)

        sid1 = store_a.create_session(title="Session Alpha")
        store_a.add_turn(sid1, "user", "first content", "N/A", [])
        sid2 = store_a.create_session(title="Session Beta")
        store_a.add_turn(sid2, "user", "second content", "N/A", [])
        store_a.close()

        cipher_b = _make_cipher()  # completely different DEK
        store_b = _make_store(db_path=db, cipher=cipher_b)

        with caplog.at_level(logging.WARNING, logger="services.ui_gateway.src.session_store"):
            result = store_b.list_sessions()

        store_b.close()

        # Must not raise -- correct posture.
        assert isinstance(result, list), "list_sessions must return a list, not raise"

        # Both cipher_a rows are quarantined -- result is empty.
        assert len(result) == 0, (
            f"Expected 0 sessions (both quarantined), got {len(result)}"
        )

        # Stable event code must appear in logs.
        quarantine_logs = [
            r for r in caplog.records
            if "SESSION_ROW_DECRYPT_QUARANTINE" in r.getMessage()
        ]
        assert len(quarantine_logs) >= 1, (
            "Expected at least one SESSION_ROW_DECRYPT_QUARANTINE log entry; "
            f"got {len(quarantine_logs)}"
        )

        # Summary warning with count must also appear.
        summary_logs = [
            r for r in caplog.records
            if "SESSION_ROW_DECRYPT_QUARANTINE summary" in r.getMessage()
        ]
        assert len(summary_logs) == 1, (
            "Expected exactly one summary warning; "
            f"got {len(summary_logs)}"
        )
        assert "2" in summary_logs[0].getMessage(), (
            "Summary warning should mention the count '2'"
        )

    def test_good_session_returned_alongside_bad(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One session encrypted under cipher_a, one created under cipher_b.

        list_sessions under cipher_b should return only the cipher_b session.
        """
        db = str(tmp_path / "mix.db")
        cipher_a = _make_cipher()
        store_a = _make_store(db_path=db, cipher=cipher_a)
        store_a.create_session(title="Old session under cipher_a")
        store_a.close()

        # Open under cipher_b and add a new session -- this one will be decryptable.
        cipher_b = _make_cipher()
        store_b = _make_store(db_path=db, cipher=cipher_b)
        sid_new = store_b.create_session(title="New session under cipher_b")
        store_b.add_turn(sid_new, "user", "new content", "N/A", [])

        with caplog.at_level(logging.WARNING, logger="services.ui_gateway.src.session_store"):
            result = store_b.list_sessions()

        store_b.close()

        assert isinstance(result, list)
        # Only the cipher_b session should be returned.
        result_ids = [s.id for s in result]
        assert sid_new in result_ids, "New (cipher_b) session must appear in result"
        # The cipher_a session should have been quarantined.
        assert len(result) == 1, (
            f"Expected only 1 session (cipher_a one quarantined), got {len(result)}: "
            f"{result_ids}"
        )

        # Quarantine event must be logged for the old session.
        quarantine_logs = [
            r for r in caplog.records
            if "SESSION_ROW_DECRYPT_QUARANTINE" in r.getMessage()
        ]
        assert len(quarantine_logs) >= 1


# ---------------------------------------------------------------------------
# Test 2 -- get_session_turns quarantines un-decryptable turns
# ---------------------------------------------------------------------------


class TestGetSessionTurnsQuarantinesBadTurn:
    """get_session_turns skips un-decryptable turns and returns the good ones."""

    def test_one_bad_turn_quarantined_rest_returned(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A session with 3 turns; one turn's ciphertext is corrupted.

        get_session_turns returns the 2 good turns, quarantines the 1 bad
        turn, and logs SESSION_ROW_DECRYPT_QUARANTINE.  Does not raise.
        """
        db = str(tmp_path / "turns.db")
        cipher = _make_cipher()
        store = _make_store(db_path=db, cipher=cipher)
        sid = store.create_session(title="Turns test session")
        tid1 = store.add_turn(sid, "user", "good turn one", "N/A", [])
        tid2 = store.add_turn(sid, "assistant", "good turn two", "approved", [])
        tid3 = store.add_turn(sid, "user", "good turn three", "N/A", [])
        store.close()

        # Corrupt exactly one turn's content (overwrite the GCM auth tag).
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT id, content FROM turns WHERE id = ?", (tid2,)
        ).fetchone()
        assert row is not None, "turn tid2 must exist"
        _, blob = row
        corrupted = bytes(blob[:-4]) + b"\xff\xff\xff\xff"
        conn.execute("UPDATE turns SET content = ? WHERE id = ?", (corrupted, tid2))
        conn.commit()
        conn.close()

        store2 = _make_store(db_path=db, cipher=cipher)

        with caplog.at_level(logging.WARNING, logger="services.ui_gateway.src.session_store"):
            turns = store2.get_session_turns(sid)

        store2.close()

        # Must not raise.
        assert isinstance(turns, list)

        # Only the 2 good turns are returned; the bad one is quarantined.
        returned_ids = {t.id for t in turns}
        assert tid1 in returned_ids, "Good turn tid1 must be in result"
        assert tid3 in returned_ids, "Good turn tid3 must be in result"
        assert tid2 not in returned_ids, "Corrupted turn tid2 must be quarantined"
        assert len(turns) == 2, f"Expected 2 good turns, got {len(turns)}"

        # Quarantine event logged.
        quarantine_logs = [
            r for r in caplog.records
            if "SESSION_ROW_DECRYPT_QUARANTINE" in r.getMessage()
        ]
        assert len(quarantine_logs) >= 1

        # Summary logged.
        summary_logs = [
            r for r in caplog.records
            if "SESSION_ROW_DECRYPT_QUARANTINE summary" in r.getMessage()
        ]
        assert len(summary_logs) == 1

    def test_single_record_leaf_decrypt_still_raises(self, tmp_path: Path) -> None:
        """Directly calling _dec_turn_content on a corrupted blob still raises.

        The leaf helper's hard fail-closed posture is unchanged -- only the
        bulk loop that calls it wraps the exception.  Plaintext is never
        returned from tampered data.
        """
        db = str(tmp_path / "leaf.db")
        cipher = _make_cipher()
        store = _make_store(db_path=db, cipher=cipher)
        sid = store.create_session(title="Leaf test")
        tid = store.add_turn(sid, "user", "leaf content", "N/A", [])
        store.close()

        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT content FROM turns WHERE id = ?", (tid,)
        ).fetchone()
        blob = row[0]
        corrupted = bytes(blob[:-4]) + b"\xde\xad\xbe\xef"
        conn.close()

        store2 = _make_store(db_path=db, cipher=cipher)
        with pytest.raises(RuntimeError, match="refusing to return plaintext"):
            store2._dec_turn_content(tid, corrupted)
        store2.close()


# ---------------------------------------------------------------------------
# Test 3 -- _backfill_empty_titles quarantines un-decryptable turns at boot
# ---------------------------------------------------------------------------


class TestBackfillQuarantinesOnBoot:
    """Construction succeeds even when a backfill turn cannot be decrypted."""

    def test_construction_succeeds_with_corrupted_backfill_turn(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Empty-title session with one un-decryptable turn.

        EncryptedSessionStore() construction MUST succeed -- _backfill_empty_titles
        quarantines the bad turn and the session retains an empty title rather
        than aborting the entire store initialisation.
        """
        db = str(tmp_path / "boot.db")
        cipher = _make_cipher()
        store = _make_store(db_path=db, cipher=cipher)
        sid = store.create_session()  # empty title -- triggers backfill on next open
        tid = store.add_turn(sid, "user", "backfill content", "N/A", [])
        store.close()

        # Corrupt the only user turn's ciphertext.
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT content FROM turns WHERE id = ?", (tid,)
        ).fetchone()
        blob = row[0]
        corrupted = bytes(blob[:-4]) + b"\xba\xdc\x0f\xfe"
        conn.execute("UPDATE turns SET content = ? WHERE id = ?", (corrupted, tid))
        conn.commit()
        conn.close()

        # Construction must succeed -- quarantine is the new posture.
        with caplog.at_level(logging.WARNING, logger="services.ui_gateway.src.session_store"):
            store2 = EncryptedSessionStore(db_path=db, cipher=cipher)

        assert store2 is not None, "Construction must succeed despite corrupted backfill turn"

        # Store must be usable after construction.
        new_sid = store2.create_session(title="post-boot session")
        store2.add_turn(new_sid, "user", "post-boot content", "N/A", [])
        sessions = store2.list_sessions()
        returned_ids = {s.id for s in sessions}
        # The new session is readable; the corrupted empty-title session is quarantined
        # in list_sessions if title is empty-string (no-op for empty-string path, passes
        # through as empty title).  The store is functional.
        assert new_sid in returned_ids

        store2.close()

        # Quarantine event must have been logged during backfill.
        quarantine_logs = [
            r for r in caplog.records
            if "SESSION_ROW_DECRYPT_QUARANTINE" in r.getMessage()
        ]
        assert len(quarantine_logs) >= 1, (
            "Expected SESSION_ROW_DECRYPT_QUARANTINE log during backfill; "
            f"got {len(quarantine_logs)}"
        )

    def test_leaf_decrypt_still_raises_after_successful_boot(
        self, tmp_path: Path
    ) -> None:
        """After a successful boot with a quarantined turn, leaf decrypt still raises.

        The 'never return garbage' invariant survives the bulk-quarantine change.
        """
        db = str(tmp_path / "boot_leaf.db")
        cipher = _make_cipher()
        store = _make_store(db_path=db, cipher=cipher)
        sid = store.create_session()
        tid = store.add_turn(sid, "user", "leaf invariant content", "N/A", [])
        store.close()

        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT content FROM turns WHERE id = ?", (tid,)
        ).fetchone()
        blob = row[0]
        corrupted = bytes(blob[:-4]) + b"\xca\xfe\xba\xbe"
        conn.execute("UPDATE turns SET content = ? WHERE id = ?", (corrupted, tid))
        conn.commit()
        conn.close()

        # Boot succeeds.
        store2 = EncryptedSessionStore(db_path=db, cipher=cipher)

        # Direct leaf decrypt still raises -- plaintext is never returned.
        with pytest.raises(RuntimeError, match="refusing to return plaintext"):
            store2._dec_turn_content(tid, corrupted)

        store2.close()
