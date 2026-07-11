"""
Tests for the embedding-model identity stamp + fail-closed vector-limb guard
(Vikunja #794 — study §2.2b / verdict row 3, OpenClaw "index identity").

The stores stamp the identity of the embedding model that produced their vectors
(``embed_model`` name + ``embed_model_revision``) into their meta table at build,
and cross-check it at load.  On a mismatch the VECTOR limb is *loud-disabled*
(the ADR-031 §7 middle ground) instead of silently comparing cosine scores from
two different embedding spaces:

  * ``substrate.db`` is vector-only, so a mismatch means retrieve returns no
    memory (no cosine scores from a foreign space);
  * ``knowledge.db`` keeps its BM25/lexical limb — only the cosine limb is
    skipped — because BM25 does not depend on the embedder.

Idempotent migration: a legacy store that predates the revision key is stamped
at the current identity on reopen (INSERT OR IGNORE), producing NO false alarm —
historically only bge-small-en-v1.5 has ever run.

Uses deterministic stub embedders (no ONNX model — worktree-safe), mirroring
``test_knowledge_bank.py``.
"""

from __future__ import annotations

import logging
import uuid
import zlib
from pathlib import Path

import numpy as np
import pytest

from services.assistant_orchestrator.src.knowledge_bank import EncryptedKnowledgeBank
from services.assistant_orchestrator.src.substrate import (
    EMBED_DIM,
    EMBED_MODEL_NAME,
    EMBED_MODEL_REVISION,
    EmbedModelMismatch,
    EncryptedSubstrateStore,
    SubstrateStore,
    detect_embed_model_mismatch,
    embed_model_rebuild_instruction,
    resolve_embed_model_identity,
)
from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.tpm_sealer import SoftwareSealer


# ---------------------------------------------------------------------------
# Helpers (mirror test_knowledge_bank.py — deterministic, no model load)
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


# Vector-only fixtures: query and target share ZERO indexable words
# (BM25-invisible) but map to the SAME unit vector — only the cosine limb can
# surface the target, so a disabled vector limb makes the target unretrievable.
_VEC_QUERY = "ornithopter wing oscillation cadence"
_VEC_TARGET = "submarine ballast chambers regulate buoyancy depth underwater"


def pinned_embed(texts: list[str]) -> np.ndarray:
    """Map the query and the target to the SAME axis (cosine 1.0); else axis 2."""
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        out[i, 0 if t.strip() in (_VEC_QUERY, _VEC_TARGET) else 2] = 1.0
    return out


def poison_embed(_texts: list[str]) -> np.ndarray:
    """An embedder that must never be called (proves the vector limb is skipped)."""
    raise AssertionError("embed_fn called while the vector limb is disabled (#794)")


def _make_cipher() -> FieldCipher:
    sealer = SoftwareSealer()
    env = DekEnvelope.create(sealer=sealer, recovery_key=generate_recovery_key())
    return FieldCipher(derive_subkeys(env.unseal_dek()))


def _submit_approve(bank: EncryptedKnowledgeBank, content: str, **overrides) -> str:
    """Submit + approve one doc, returning its uuid."""
    kwargs = dict(
        doc_uuid=str(uuid.uuid4()),
        source_type="url",
        source_ref=f"https://example.org/{uuid.uuid4().hex}",
        content=content,
        title="Test doc",
        byline="A. Writer",
        published_date="2026-07-10",
        cleaner_version="cleaner-v1",
        word_count=len(content.split()),
    )
    kwargs.update(overrides)
    r = bank.submit_pending(**kwargs)
    bank.approve(r.doc_uuid)
    return r.doc_uuid


# ---------------------------------------------------------------------------
# 1. resolve_embed_model_identity — path parsing + fallbacks (pure function)
# ---------------------------------------------------------------------------


class TestResolveIdentity:
    def test_shipped_posix_path(self) -> None:
        name, rev = resolve_embed_model_identity(
            "models/bge-small-en-v1.5/onnx-fp16/model.onnx"
        )
        assert (name, rev) == ("bge-small-en-v1.5", "onnx-fp16")

    def test_windows_separator_path(self) -> None:
        name, rev = resolve_embed_model_identity(
            r"models\bge-small-en-v1.5\onnx-int8\model.onnx"
        )
        assert (name, rev) == ("bge-small-en-v1.5", "onnx-int8")

    def test_none_falls_back_to_baseline(self) -> None:
        assert resolve_embed_model_identity(None) == (
            EMBED_MODEL_NAME,
            EMBED_MODEL_REVISION,
        )

    def test_empty_string_falls_back(self) -> None:
        assert resolve_embed_model_identity("") == (
            EMBED_MODEL_NAME,
            EMBED_MODEL_REVISION,
        )

    def test_directory_only_path(self) -> None:
        # No trailing filename (no dot) — last two dirs are name + revision.
        assert resolve_embed_model_identity("models/bge-base-en-v1.5/onnx-fp32") == (
            "bge-base-en-v1.5",
            "onnx-fp32",
        )

    def test_single_segment_uses_default_revision(self) -> None:
        assert resolve_embed_model_identity("only-a-model-dir") == (
            "only-a-model-dir",
            EMBED_MODEL_REVISION,
        )

    def test_never_raises_on_odd_input(self) -> None:
        # A dotted single segment reduces to no dir segments → baseline.
        assert resolve_embed_model_identity("model.onnx") == (
            EMBED_MODEL_NAME,
            EMBED_MODEL_REVISION,
        )


# ---------------------------------------------------------------------------
# 2. Plain SubstrateStore — stamp, match, mismatch, migration
# ---------------------------------------------------------------------------


def _substrate_meta(store: SubstrateStore) -> dict[str, str]:
    return dict(store._conn.execute("SELECT key, value FROM substrate_meta").fetchall())


class TestSubstrateIdentity:
    def test_fresh_store_stamps_model_and_revision(self) -> None:
        s = SubstrateStore(":memory:", fake_embed)
        try:
            meta = _substrate_meta(s)
            assert meta["embed_model"] == EMBED_MODEL_NAME
            assert meta["embed_model_revision"] == EMBED_MODEL_REVISION
            assert s.embed_model_mismatch is None
        finally:
            s.close()

    def test_reopen_same_identity_is_clean(self, tmp_path: Path) -> None:
        db = str(tmp_path / "substrate.db")
        s1 = SubstrateStore(db, fake_embed)
        s1.ingest_document("notes.txt", "the quick brown fox jumps")
        s1.close()

        s2 = SubstrateStore(db, fake_embed)
        try:
            assert s2.embed_model_mismatch is None
            hits = s2.retrieve("quick brown fox", k_turns=0)
            assert hits and hits[0].source == "notes.txt"
        finally:
            s2.close()

    def test_reopen_different_revision_disables_vector_limb(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = str(tmp_path / "substrate.db")
        s1 = SubstrateStore(db, fake_embed)
        s1.ingest_document("notes.txt", "the quick brown fox jumps")
        s1.close()

        with caplog.at_level(logging.ERROR):
            s2 = SubstrateStore(db, fake_embed, embed_model_revision="onnx-int8")
        try:
            # Mismatch detected and vector limb disabled.
            assert s2.embed_model_mismatch is not None
            assert s2.embed_model_mismatch.stored_revision == EMBED_MODEL_REVISION
            assert s2.embed_model_mismatch.configured_revision == "onnx-int8"
            # Substrate is vector-only → retrieve returns nothing.
            assert s2.retrieve("quick brown fox", k_turns=0) == []
            # Loud, actionable log naming the class + the BM25 degradation.
            assert "EMBED_MODEL_IDENTITY_MISMATCH" in caplog.text
            assert "onnx-int8" in caplog.text
            assert "loud-disable" in caplog.text.lower()
        finally:
            s2.close()

    def test_reopen_different_model_name_disables_vector_limb(
        self, tmp_path: Path
    ) -> None:
        db = str(tmp_path / "substrate.db")
        s1 = SubstrateStore(db, fake_embed)
        s1.ingest_document("notes.txt", "alpha beta gamma delta")
        s1.close()

        s2 = SubstrateStore(db, fake_embed, embed_model="bge-base-en-v1.5")
        try:
            assert s2.embed_model_mismatch is not None
            assert s2.embed_model_mismatch.configured_model == "bge-base-en-v1.5"
            assert s2.retrieve("alpha beta", k_turns=0) == []
        finally:
            s2.close()

    def test_legacy_store_missing_revision_is_migrated_no_alarm(
        self, tmp_path: Path
    ) -> None:
        """A pre-#794 store lacks embed_model_revision → reopen stamps it at the
        current revision (INSERT OR IGNORE migration) with NO false mismatch."""
        db = str(tmp_path / "substrate.db")
        s1 = SubstrateStore(db, fake_embed)
        s1.ingest_document("notes.txt", "one two three four five")
        # Simulate a pre-#794 store: drop the revision key the old build never wrote.
        s1._conn.execute("DELETE FROM substrate_meta WHERE key='embed_model_revision'")
        s1._conn.commit()
        s1.close()

        s2 = SubstrateStore(db, fake_embed)
        try:
            assert s2.embed_model_mismatch is None  # migrated, not alarmed
            meta = _substrate_meta(s2)
            assert meta["embed_model_revision"] == EMBED_MODEL_REVISION
            # Vector limb still live.
            assert s2.retrieve("two three four", k_turns=0)
        finally:
            s2.close()

    def test_double_open_same_process_is_idempotent(self, tmp_path: Path) -> None:
        db = str(tmp_path / "substrate.db")
        s1 = SubstrateStore(db, fake_embed)
        s1.close()
        s2 = SubstrateStore(db, fake_embed)
        try:
            assert s2.embed_model_mismatch is None
        finally:
            s2.close()


# ---------------------------------------------------------------------------
# 3. EncryptedSubstrateStore — same guard on the production (encrypted) store
# ---------------------------------------------------------------------------


class TestEncryptedSubstrateIdentity:
    def test_fresh_encrypted_store_stamps_revision(self) -> None:
        s = EncryptedSubstrateStore(
            ":memory:", fake_embed, cipher=_make_cipher(), embed_cache_idle_unload_s=0
        )
        try:
            meta = _substrate_meta(s)
            assert meta["embed_model_revision"] == EMBED_MODEL_REVISION
            assert s.embed_model_mismatch is None
        finally:
            s.close()

    def test_reopen_mismatch_disables_vector_limb(self, tmp_path: Path) -> None:
        db = str(tmp_path / "substrate.db")
        cipher = _make_cipher()
        s1 = EncryptedSubstrateStore(
            db, fake_embed, cipher=cipher, embed_cache_idle_unload_s=0
        )
        s1.ingest_document("notes.txt", "encrypted quick brown fox jumps high")
        s1.close()

        s2 = EncryptedSubstrateStore(
            db,
            fake_embed,
            cipher=cipher,
            embed_cache_idle_unload_s=0,
            embed_model_revision="onnx-int8",
        )
        try:
            assert s2.embed_model_mismatch is not None
            assert s2.retrieve("quick brown fox", k_turns=0) == []
        finally:
            s2.close()

    def test_reopen_same_identity_retrieves(self, tmp_path: Path) -> None:
        db = str(tmp_path / "substrate.db")
        cipher = _make_cipher()
        s1 = EncryptedSubstrateStore(
            db, fake_embed, cipher=cipher, embed_cache_idle_unload_s=0
        )
        s1.ingest_document("notes.txt", "sphinx of black quartz judge my vow")
        s1.close()
        s2 = EncryptedSubstrateStore(
            db, fake_embed, cipher=cipher, embed_cache_idle_unload_s=0
        )
        try:
            assert s2.embed_model_mismatch is None
            hits = s2.retrieve("black quartz judge", k_turns=0)
            assert hits and hits[0].source == "notes.txt"
        finally:
            s2.close()


# ---------------------------------------------------------------------------
# 4. EncryptedKnowledgeBank — vector limb disabled, BM25 UNAFFECTED
# ---------------------------------------------------------------------------


class TestKnowledgeBankIdentity:
    def test_fresh_bank_stamps_revision(self) -> None:
        b = EncryptedKnowledgeBank(":memory:", fake_embed, cipher=_make_cipher())
        try:
            row = b._conn.execute(
                "SELECT value FROM knowledge_meta WHERE key='embed_model_revision'"
            ).fetchone()
            assert row[0] == EMBED_MODEL_REVISION
            assert b.embed_model_mismatch is None
        finally:
            b.close()

    def test_mismatch_keeps_bm25_but_drops_vector(self, tmp_path: Path) -> None:
        """On identity mismatch: a BM25-matching query STILL returns the doc
        (lexical limb alive), while a vector-only query returns nothing (cosine
        limb disabled).  This is the loud-disable-of-the-vector-limb-only posture
        the ticket recommends — BM25 unaffected."""
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b1 = EncryptedKnowledgeBank(db, pinned_embed, cipher=cipher)
        # Target is vector-reachable from _VEC_QUERY but shares NO words with it.
        uid = _submit_approve(b1, _VEC_TARGET)
        b1.close()

        # Sanity: with matching identity BOTH limbs work — the vector-only query
        # surfaces the target (proves pinned_embed wiring).
        b_ok = EncryptedKnowledgeBank(db, pinned_embed, cipher=cipher)
        try:
            hits = b_ok.retrieve(_VEC_QUERY, k=3)
            assert any(h.doc_uuid == uid for h in hits)
        finally:
            b_ok.close()

        # Reopen under a DIFFERENT model identity.  Use poison_embed to PROVE the
        # vector limb (and its query-embed call) is skipped entirely.
        b2 = EncryptedKnowledgeBank(
            db, poison_embed, cipher=cipher, embed_model="bge-base-en-v1.5"
        )
        try:
            assert b2.embed_model_mismatch is not None
            # Vector-only query → nothing (cosine limb off, BM25 can't see it).
            assert b2.retrieve(_VEC_QUERY, k=3) == []
            # BM25-matching query (shares the target's own words) STILL returns it.
            bm25_hits = b2.retrieve("submarine ballast buoyancy", k=3)
            assert any(h.doc_uuid == uid for h in bm25_hits)
        finally:
            b2.close()

    def test_mismatch_logs_loudly_with_rebuild_instruction(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b1 = EncryptedKnowledgeBank(db, fake_embed, cipher=cipher)
        b1.close()
        with caplog.at_level(logging.ERROR):
            b2 = EncryptedKnowledgeBank(
                db, fake_embed, cipher=cipher, embed_model_revision="onnx-int8"
            )
        try:
            assert "EMBED_MODEL_IDENTITY_MISMATCH" in caplog.text
            assert "re-embed" in caplog.text.lower()
            assert "bm25" in caplog.text.lower()
        finally:
            b2.close()

    def test_matching_identity_reopen_is_clean(self, tmp_path: Path) -> None:
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b1 = EncryptedKnowledgeBank(db, fake_embed, cipher=cipher)
        uid = _submit_approve(
            b1, "Turbochargers compress intake air to raise engine power output."
        )
        b1.close()
        b2 = EncryptedKnowledgeBank(db, fake_embed, cipher=cipher)
        try:
            assert b2.embed_model_mismatch is None
            hits = b2.retrieve("turbochargers engine power", k=1)
            assert hits and hits[0].doc_uuid == uid
        finally:
            b2.close()

    def test_legacy_bank_missing_revision_is_migrated(self, tmp_path: Path) -> None:
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b1 = EncryptedKnowledgeBank(db, fake_embed, cipher=cipher)
        uid = _submit_approve(b1, "one two three four five six seven eight")
        b1._conn.execute(
            "DELETE FROM knowledge_meta WHERE key='embed_model_revision'"
        )
        b1._conn.commit()
        b1.close()

        b2 = EncryptedKnowledgeBank(db, fake_embed, cipher=cipher)
        try:
            assert b2.embed_model_mismatch is None
            row = b2._conn.execute(
                "SELECT value FROM knowledge_meta WHERE key='embed_model_revision'"
            ).fetchone()
            assert row[0] == EMBED_MODEL_REVISION
            hits = b2.retrieve("three four five", k=2)
            assert any(h.doc_uuid == uid for h in hits)
        finally:
            b2.close()


# ---------------------------------------------------------------------------
# 5. detect_embed_model_mismatch + rebuild instruction — direct unit coverage
# ---------------------------------------------------------------------------


class TestDetectHelper:
    def test_unrecognised_meta_table_fails_safe(self) -> None:
        import sqlite3

        conn = sqlite3.connect(":memory:")
        # No such allowlisted table → fail-safe None, never raises.
        assert (
            detect_embed_model_mismatch(conn, "evil_meta", "m", "r", "x") is None
        )
        conn.close()

    def test_rebuild_instruction_names_both_identities(self) -> None:
        m = EmbedModelMismatch("bge-small-en-v1.5", "onnx-fp16", "bge-base", "onnx-int8")
        msg = embed_model_rebuild_instruction("substrate.db", m)
        assert "bge-small-en-v1.5@onnx-fp16" in msg
        assert "bge-base@onnx-int8" in msg
        assert "re-embed" in msg.lower()
