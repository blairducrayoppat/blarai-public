"""
Production-parity lane — Lock (i): dev→prod key-transition integration tests.

Sprint 16 SDV §4 criterion #6(i) — ticket #619.

WHY THESE TESTS EXIST — the seam they close
============================================
Sprint 15 taught the project that a green suite that mocks the boundary is
not coverage of the boundary.  The specific production-only failure class:
after a key rotation (or any dev→prod transition that replaces the DEK) both
encrypted stores — the session store and the AO substrate — must SERVE the
user, not BRICK.  No test in the pre-Sprint-16 suite exercised the real
integrated open-path (the actual store constructor, the actual decrypt
cascade, the actual quarantine path) across a key change.  These tests fix
that gap.

DESIGN INTENT
=============
Tests assert behaviour AT THE SEAM — the real store open/decrypt path —
not at a mocked boundary.  No production sealer (TpmSealer) is used:
SoftwareSealer stands in for the TPM cascade so the suite runs on any
machine without TPM access (the same pattern the existing decrypt-resilience
tests and the substrate-encryption test suite use).  The SoftwareSealer is
already in production at shared/security/tpm_sealer.py; no new fixture class
is needed.

ISOLATION
=========
All tests use tmp_path only.  The root conftest.py already redirects
LOCALAPPDATA/HOME/XDG_DATA_HOME to a throwaway temp dir at process startup
and unsets BLARAI_DEK_KEYSTORE, so the real user-data directory is never
touched.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
import zlib
from pathlib import Path

import numpy as np
import pytest

from services.assistant_orchestrator.src.substrate import (
    EMBED_DIM,
    EncryptedSubstrateStore,
)
from services.ui_gateway.src.session_store import EncryptedSessionStore
from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.tpm_sealer import SoftwareSealer


# ---------------------------------------------------------------------------
# Shared helpers — SoftwareSealer-backed FieldCipher and store construction
# ---------------------------------------------------------------------------


def _make_cipher() -> FieldCipher:
    """Build a FieldCipher from a freshly-generated DEK using SoftwareSealer.

    SoftwareSealer stands in for the production TpmSealer.  This is the same
    helper pattern used in test_session_store_decrypt_resilience.py and
    test_substrate_decrypt_resilience.py — the canonical SoftwareSealer
    integration-test construction path.
    """
    sealer = SoftwareSealer()
    rk = generate_recovery_key()
    env = DekEnvelope.create(sealer=sealer, recovery_key=rk)
    dek = env.unseal_dek()
    return FieldCipher(derive_subkeys(dek))


def _make_session_store(db_path: str, cipher: FieldCipher | None = None) -> EncryptedSessionStore:
    """Construct a real EncryptedSessionStore at the REAL seam (no mocked boundary)."""
    if cipher is None:
        cipher = _make_cipher()
    return EncryptedSessionStore(db_path=db_path, cipher=cipher)


def _fake_embed(texts: list[str]) -> np.ndarray:
    """Deterministic bag-of-words embedder (mirrors test_substrate_decrypt_resilience)."""
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for word in t.lower().split():
            out[i, zlib.crc32(word.encode()) % EMBED_DIM] += 1.0
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (out / norms).astype(np.float32)


def _make_substrate_store(
    db_path: str = ":memory:",
    cipher: FieldCipher | None = None,
) -> EncryptedSubstrateStore:
    """Construct a real EncryptedSubstrateStore at the REAL seam."""
    if cipher is None:
        cipher = _make_cipher()
    return EncryptedSubstrateStore(db_path=db_path, embed_fn=_fake_embed, cipher=cipher)


# ---------------------------------------------------------------------------
# Lock (i-a): Session store — dev→prod key transition SERVES, not BRICKS
# ---------------------------------------------------------------------------


class TestSessionStoreDevToProdKeyTransition:
    """The session store survives a dev→prod key rotation without bricking.

    Scenario: production cert ceremony provisions a new TpmSealer key and
    rotates the DEK (new cipher_prod != cipher_dev).  The old cipher_dev data
    in the session DB is quarantined (a known, correct, designed posture per
    ADR-025 §2.7 / Sprint 15 EA-8) — the store OPENS and is USABLE, not
    BRICKED.  New sessions written under cipher_prod are immediately readable.

    This is an explicit integration test: it constructs and exercises the REAL
    EncryptedSessionStore constructor and read path, not a mock.
    """

    def test_store_opens_after_key_rotation(self, tmp_path: Path) -> None:
        """After key rotation the store opens (no exception), session is usable."""
        db = str(tmp_path / "sessions.db")
        # Dev path: write sessions under cipher_dev.
        cipher_dev = _make_cipher()
        store_dev = _make_session_store(db_path=db, cipher=cipher_dev)
        sid_dev = store_dev.create_session(title="Dev session")
        store_dev.add_turn(sid_dev, "user", "dev turn content", "N/A", [])
        store_dev.close()

        # Production ceremony: new cipher_prod replaces cipher_dev.
        cipher_prod = _make_cipher()
        # The REAL constructor — must not raise.
        store_prod = _make_session_store(db_path=db, cipher=cipher_prod)
        assert store_prod is not None, "Store must open after key rotation"
        store_prod.close()

    def test_store_usable_after_key_rotation(self, tmp_path: Path) -> None:
        """After key rotation the store can create and read new sessions."""
        db = str(tmp_path / "sessions.db")
        # Write dev-key sessions.
        cipher_dev = _make_cipher()
        store_dev = _make_session_store(db_path=db, cipher=cipher_dev)
        for i in range(3):
            sid = store_dev.create_session(title=f"Dev session {i}")
            store_dev.add_turn(sid, "user", f"dev content {i}", "N/A", [])
        store_dev.close()

        # Open under prod key — dev sessions are quarantined, store is usable.
        cipher_prod = _make_cipher()
        store_prod = _make_session_store(db_path=db, cipher=cipher_prod)

        # Create a new prod-key session.
        sid_new = store_prod.create_session(title="First production session")
        store_prod.add_turn(sid_new, "user", "post-rotation content", "N/A", [])

        # list_sessions returns only the prod-key session; dev sessions quarantined.
        sessions = store_prod.list_sessions()
        session_ids = {s.id for s in sessions}
        assert sid_new in session_ids, "Prod-key session must be listed"
        assert len(sessions) == 1, (
            f"Only 1 prod-key session expected (dev sessions quarantined); "
            f"got {len(sessions)}: {[s.title for s in sessions]}"
        )
        store_prod.close()

    def test_dev_sessions_quarantined_not_surfaced(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Dev-key sessions are quarantined and logged, not silently returned."""
        db = str(tmp_path / "sessions.db")
        cipher_dev = _make_cipher()
        store_dev = _make_session_store(db_path=db, cipher=cipher_dev)
        store_dev.create_session(title="Old dev session A")
        store_dev.create_session(title="Old dev session B")
        store_dev.close()

        cipher_prod = _make_cipher()
        store_prod = _make_session_store(db_path=db, cipher=cipher_prod)

        with caplog.at_level(logging.WARNING, logger="services.ui_gateway.src.session_store"):
            sessions = store_prod.list_sessions()

        store_prod.close()

        # Dev sessions must not appear in results.
        assert len(sessions) == 0, (
            f"Dev sessions must be quarantined; got {len(sessions)}: {[s.title for s in sessions]}"
        )
        # Quarantine event must be logged so the operator knows what happened.
        quarantine_logs = [
            r for r in caplog.records
            if "SESSION_ROW_DECRYPT_QUARANTINE" in r.getMessage()
        ]
        assert len(quarantine_logs) >= 1, (
            "Expected at least one SESSION_ROW_DECRYPT_QUARANTINE log entry; "
            f"got {len(quarantine_logs)}"
        )

    def test_new_prod_turns_immediately_readable(self, tmp_path: Path) -> None:
        """Turns written under the prod key after rotation are immediately readable."""
        db = str(tmp_path / "sessions.db")
        # Dev traffic.
        cipher_dev = _make_cipher()
        store_dev = _make_session_store(db_path=db, cipher=cipher_dev)
        store_dev.create_session(title="Dev leftover")
        store_dev.close()

        cipher_prod = _make_cipher()
        store_prod = _make_session_store(db_path=db, cipher=cipher_prod)

        sid = store_prod.create_session(title="Real conversation")
        tid1 = store_prod.add_turn(sid, "user", "Hello, BlarAI", "N/A", [])
        tid2 = store_prod.add_turn(sid, "assistant", "Hello, how can I help?", "approved", [])
        turns = store_prod.get_session_turns(sid)
        store_prod.close()

        turn_ids = {t.id for t in turns}
        assert tid1 in turn_ids, f"User turn {tid1!r} must be readable"
        assert tid2 in turn_ids, f"Assistant turn {tid2!r} must be readable"
        assert len(turns) == 2, f"Expected 2 turns, got {len(turns)}"

    def test_fail_closed_without_fallback_to_plaintext(self, tmp_path: Path) -> None:
        """Direct decrypt with the wrong key raises, never returns garbage.

        The leaf-decrypt fail-closed invariant (ADR-025) must survive the key
        transition: decrypting cipher_dev content with cipher_prod ALWAYS
        raises, never silently returns wrong bytes.  This locks the
        confidentiality guarantee across the transition.
        """
        db = str(tmp_path / "integrity.db")
        cipher_dev = _make_cipher()
        store_dev = _make_session_store(db_path=db, cipher=cipher_dev)
        sid = store_dev.create_session(title="Integrity check")
        tid = store_dev.add_turn(sid, "user", "very private content", "N/A", [])
        store_dev.close()

        # Read the raw (cipher_dev-encrypted) content blob from the DB.
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT content FROM turns WHERE id = ?", (tid,)
        ).fetchone()
        conn.close()
        assert row is not None
        encrypted_blob = bytes(row[0])

        cipher_prod = _make_cipher()
        store_prod = _make_session_store(db_path=db, cipher=cipher_prod)
        # Leaf decrypt with wrong key must raise (fail-closed).
        with pytest.raises(RuntimeError, match="refusing to return plaintext"):
            store_prod._dec_turn_content(tid, encrypted_blob)
        store_prod.close()


# ---------------------------------------------------------------------------
# Lock (i-b): Substrate store — dev→prod key transition SERVES, not BRICKS
# ---------------------------------------------------------------------------


class TestSubstrateStoreDevToProdKeyTransition:
    """The AO substrate store survives a dev→prod key rotation without bricking.

    Same scenario as the session store tests, but exercising the REAL
    EncryptedSubstrateStore constructor and embedding-cache path.  The critical
    production-only seam: if _load_embed_cache raises on mismatched-key rows
    (the old posture before ADR-025 §2.7 amendment), AO startup bricks after
    any key rotation.
    """

    def test_substrate_opens_after_key_rotation(self, tmp_path: Path) -> None:
        """After key rotation the substrate opens without raising."""
        db = str(tmp_path / "substrate.db")
        cipher_dev = _make_cipher()
        store_dev = _make_substrate_store(db_path=db, cipher=cipher_dev)
        store_dev.ingest_document("private_notes.txt", "sensitive project notes content")
        store_dev.close()

        # Production key rotation — old cipher_dev data cannot decrypt.
        cipher_prod = _make_cipher()
        # REAL constructor — must not raise (the brick-on-key-rotation failure mode).
        store_prod = _make_substrate_store(db_path=db, cipher=cipher_prod)
        assert store_prod is not None, (
            "Substrate store must open after key rotation, not brick AO startup"
        )
        store_prod.close()

    def test_substrate_usable_after_key_rotation(self, tmp_path: Path) -> None:
        """After key rotation the substrate is queryable and new docs are retrievable."""
        db = str(tmp_path / "substrate.db")
        cipher_dev = _make_cipher()
        store_dev = _make_substrate_store(db_path=db, cipher=cipher_dev)
        store_dev.ingest_document("old_doc.txt", "old encrypted content from dev phase")
        store_dev.close()

        cipher_prod = _make_cipher()
        store_prod = _make_substrate_store(db_path=db, cipher=cipher_prod)

        # New prod-key content is immediately accessible.
        store_prod.ingest_document("prod_doc.txt", "production orchestrator memory content")
        hits = store_prod.retrieve("production orchestrator memory", k_docs=2, k_turns=0)
        assert len(hits) >= 1, "Prod-key document must be retrievable after rotation"
        assert hits[0].source == "prod_doc.txt", f"Expected prod_doc.txt, got {hits[0].source}"
        store_prod.close()

    def test_old_dev_content_quarantined_on_retrieve(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Old dev-key embeddings are quarantined on boot, not surfaced as hits."""
        db = str(tmp_path / "substrate.db")
        cipher_dev = _make_cipher()
        store_dev = _make_substrate_store(db_path=db, cipher=cipher_dev)
        # Ingest content that would score highly on a query.
        store_dev.ingest_document(
            "secret.txt",
            "turbocharger engine pistons cylinders horsepower torque",
        )
        store_dev.close()

        cipher_prod = _make_cipher()
        with caplog.at_level(logging.WARNING, logger="services.assistant_orchestrator.src.substrate"):
            store_prod = _make_substrate_store(db_path=db, cipher=cipher_prod)

        hits = store_prod.retrieve("turbocharger engine pistons", k_docs=2, k_turns=0)
        store_prod.close()

        # Dev-key content must not appear in results.
        hit_sources = {h.source for h in hits}
        assert "secret.txt" not in hit_sources, (
            f"Dev-key content 'secret.txt' must be quarantined, not served; "
            f"got hits: {hit_sources}"
        )
        # Quarantine event logged.
        assert any(
            "SUBSTRATE_ROW_DECRYPT_QUARANTINE" in r.message for r in caplog.records
        ), "Expected SUBSTRATE_ROW_DECRYPT_QUARANTINE log on dev-key quarantine"

    def test_dual_store_same_session_serves_not_bricks(self, tmp_path: Path) -> None:
        """Both stores open under the same prod cipher after key rotation.

        In production, the launcher constructs both stores in the same boot
        sequence (Steps 3-5 of launcher/__main__.py).  A key rotation must
        allow BOTH to open without exception.  This test constructs both with
        the same prod cipher (after a simulated rotation) to verify the
        joint-open path.
        """
        session_db = str(tmp_path / "sessions.db")
        substrate_db = str(tmp_path / "substrate.db")

        cipher_dev = _make_cipher()
        # Write dev content to both stores.
        store_s_dev = _make_session_store(db_path=session_db, cipher=cipher_dev)
        sid = store_s_dev.create_session(title="Dev session")
        store_s_dev.add_turn(sid, "user", "dev conversation", "N/A", [])
        store_s_dev.close()

        store_sub_dev = _make_substrate_store(db_path=substrate_db, cipher=cipher_dev)
        store_sub_dev.ingest_document("old.txt", "old context before rotation")
        store_sub_dev.close()

        # Key rotation: both stores opened under prod cipher in one session.
        cipher_prod = _make_cipher()
        store_s_prod = _make_session_store(db_path=session_db, cipher=cipher_prod)
        store_sub_prod = _make_substrate_store(db_path=substrate_db, cipher=cipher_prod)

        # Both are usable.
        new_sid = store_s_prod.create_session(title="Production session post-rotation")
        store_s_prod.add_turn(new_sid, "user", "post-rotation user turn", "N/A", [])
        store_sub_prod.ingest_document("new.txt", "new production context")

        sessions = store_s_prod.list_sessions()
        hits = store_sub_prod.retrieve("production context", k_docs=1, k_turns=0)

        store_s_prod.close()
        store_sub_prod.close()

        assert any(s.id == new_sid for s in sessions), "New prod session must be listed"
        assert len(hits) >= 1, "New prod substrate content must be retrievable"
        assert hits[0].source == "new.txt"
