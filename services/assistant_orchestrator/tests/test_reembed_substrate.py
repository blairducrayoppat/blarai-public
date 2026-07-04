"""
Tests for the substrate re-embed migration (128 -> 512 token window, #655).

The migration is exercised with STUB embed functions only (the real run is a
manual live-box ceremony, never a test): ``fake_embed_128`` writes the store;
``fake_embed_512`` (a deterministically DIFFERENT embedder) plays the wider
window, so a successful migration is detectable as changed-and-verified
vectors plus the substrate_meta bump.
"""

from __future__ import annotations

import sqlite3
import zlib
from pathlib import Path

import numpy as np
import pytest

from services.assistant_orchestrator.src.reembed_substrate import (
    TARGET_EMBED_MAX_TOKENS,
    reembed_substrate,
)
from services.assistant_orchestrator.src.substrate import (
    EMBED_DIM,
    EncryptedSubstrateStore,
    SubstrateStore,
)
from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.tpm_sealer import SoftwareSealer


def _bag_embed(texts: list[str], salt: int) -> np.ndarray:
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for word in t.lower().split():
            out[i, (zlib.crc32(word.encode()) + salt) % EMBED_DIM] += 1.0
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (out / norms).astype(np.float32)


def fake_embed_128(texts: list[str]) -> np.ndarray:
    """Stands in for the legacy 128-token embedding."""
    return _bag_embed(texts, salt=0)


def fake_embed_512(texts: list[str]) -> np.ndarray:
    """Stands in for the 512-token embedding (deterministically different)."""
    return _bag_embed(texts, salt=7)


def _make_cipher() -> FieldCipher:
    env = DekEnvelope.create(
        sealer=SoftwareSealer(), recovery_key=generate_recovery_key()
    )
    return FieldCipher(derive_subkeys(env.unseal_dek()))


@pytest.fixture()
def seeded(tmp_path: Path) -> tuple[str, FieldCipher]:
    """A file-backed encrypted substrate with docs + turns at the 'old' window."""
    db = str(tmp_path / "substrate.db")
    cipher = _make_cipher()
    store = EncryptedSubstrateStore(
        db_path=db, embed_fn=fake_embed_128, cipher=cipher,
        embed_cache_idle_unload_s=0,
    )
    store.ingest_document("cars.txt", "engine pistons crankshaft turbocharger")
    store.ingest_document("garden.txt", "tomatoes basil compost watering")
    store.ingest_turn("sess-A", 0, "my sister Dana likes hiking", "Noted.")
    store.close()
    return db, cipher


def _read_embeddings(db: str) -> dict[int, bytes]:
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT id, embedding FROM substrate_chunks").fetchall()
    conn.close()
    return {int(r[0]): bytes(r[1]) for r in rows}


def _read_meta(db: str) -> str | None:
    """Read substrate_meta.embed_max_tokens (None when unset)."""
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT value FROM substrate_meta WHERE key='embed_max_tokens'"
    ).fetchone()
    conn.close()
    return str(row[0]) if row is not None else None


class TestReembed:
    def test_migrates_all_rows_and_bumps_meta(
        self, seeded: tuple[str, FieldCipher]
    ) -> None:
        db, cipher = seeded
        before = _read_embeddings(db)
        result = reembed_substrate(db, cipher, fake_embed_512)
        assert result["skipped"] == 0
        assert result["migrated"] == 3
        assert result["errors"] == 0
        assert result["verified"] == 3
        assert result["verify_failures"] == 0

        after = _read_embeddings(db)
        changed = sum(1 for k in before if before[k] != after[k])
        assert changed == 3  # every embedding ciphertext was rewritten

        conn = sqlite3.connect(db)
        meta = conn.execute(
            "SELECT value FROM substrate_meta WHERE key='embed_max_tokens'"
        ).fetchone()
        conn.close()
        assert meta is not None and meta[0] == str(TARGET_EMBED_MAX_TOKENS)

    def test_idempotent_second_run_skips(
        self, seeded: tuple[str, FieldCipher]
    ) -> None:
        db, cipher = seeded
        reembed_substrate(db, cipher, fake_embed_512)
        second = reembed_substrate(db, cipher, fake_embed_512)
        assert second == {
            "migrated": 0,
            "errors": 0,
            "skipped": 1,
            "verified": 0,
            "verify_failures": 0,
            "quarantined": 0,
        }

    def test_dry_run_writes_nothing(self, seeded: tuple[str, FieldCipher]) -> None:
        db, cipher = seeded
        before = _read_embeddings(db)
        result = reembed_substrate(db, cipher, fake_embed_512, dry_run=True)
        assert result["migrated"] == 3
        assert _read_embeddings(db) == before  # untouched
        conn = sqlite3.connect(db)
        meta = conn.execute(
            "SELECT value FROM substrate_meta WHERE key='embed_max_tokens'"
        ).fetchone()
        conn.close()
        assert meta is None  # no meta bump on dry run

    def test_store_retrieval_works_after_migration(
        self, seeded: tuple[str, FieldCipher]
    ) -> None:
        """A store re-opened with the NEW embedder retrieves correctly — the
        end-to-end point of the migration (query + rows share one window)."""
        db, cipher = seeded
        reembed_substrate(db, cipher, fake_embed_512)
        store = EncryptedSubstrateStore(
            db_path=db, embed_fn=fake_embed_512, cipher=cipher,
            embed_cache_idle_unload_s=0,
        )
        try:
            hits = store.retrieve("turbocharger engine", k_docs=1, k_turns=0)
            assert hits and hits[0].source == "cars.txt"
        finally:
            store.close()

    def test_corrupt_row_counted_as_error_others_migrate(
        self, seeded: tuple[str, FieldCipher]
    ) -> None:
        db, cipher = seeded
        conn = sqlite3.connect(db)
        row_id = int(conn.execute("SELECT id FROM substrate_chunks LIMIT 1").fetchone()[0])
        conn.execute(
            "UPDATE substrate_chunks SET text=? WHERE id=?",
            (b"\x01" + b"tampered" * 6, row_id),
        )
        conn.commit()
        conn.close()

        result = reembed_substrate(db, cipher, fake_embed_512)
        assert result["errors"] == 1
        assert result["migrated"] == 2
        assert result["verified"] == 2
        assert result["verify_failures"] == 0
        assert result["quarantined"] == 0
        # errors > 0 → the meta stamp is withheld (#655 review FIX 3).
        assert _read_meta(db) is None

    def test_errors_leave_meta_unset_and_healthy_rerun_migrates(
        self, seeded: tuple[str, FieldCipher]
    ) -> None:
        """EXACT review repro: a broken-embedder run reports errors=3 yet
        used to stamp the meta anyway, so the healthy re-run was SKIPPED and
        the store stayed un-migrated forever.  Locked: failed run → meta
        unset; healthy re-run actually migrates."""

        def broken_embed(texts: list[str]) -> np.ndarray:
            return np.zeros((len(texts), 3), dtype=np.float32)  # bad shape

        db, cipher = seeded
        first = reembed_substrate(db, cipher, broken_embed)
        assert first["errors"] == 3
        assert first["migrated"] == 0
        assert _read_meta(db) is None  # NOT stamped on a failed run

        second = reembed_substrate(db, cipher, fake_embed_512)
        assert second["skipped"] == 0  # the re-run is NOT skipped ...
        assert second["migrated"] == 3  # ... and actually migrates
        assert second["errors"] == 0
        assert _read_meta(db) == str(TARGET_EMBED_MAX_TOKENS)

    def test_quarantined_rows_with_flag_stamp_meta(
        self, seeded: tuple[str, FieldCipher]
    ) -> None:
        """--accept-quarantined: a genuinely-undecryptable row is reported
        under 'quarantined' (not 'errors') and does not block the stamp."""
        db, cipher = seeded
        conn = sqlite3.connect(db)
        row_id = int(
            conn.execute("SELECT id FROM substrate_chunks LIMIT 1").fetchone()[0]
        )
        conn.execute(
            "UPDATE substrate_chunks SET text=? WHERE id=?",
            (b"\x01" + b"tampered" * 6, row_id),
        )
        conn.commit()
        conn.close()

        result = reembed_substrate(
            db, cipher, fake_embed_512, accept_quarantined=True
        )
        assert result["quarantined"] == 1
        assert result["errors"] == 0
        assert result["migrated"] == 2
        assert result["verified"] == 2
        assert _read_meta(db) == str(TARGET_EMBED_MAX_TOKENS)
        # Idempotent thereafter.
        second = reembed_substrate(db, cipher, fake_embed_512)
        assert second["skipped"] == 1

    def test_plaintext_rows_migrate_raw(self, tmp_path: Path) -> None:
        """Pre-encryption (plaintext) stores re-embed without a cipher round."""
        db = str(tmp_path / "plain.db")
        store = SubstrateStore(db_path=db, embed_fn=fake_embed_128)
        store.ingest_document("notes.txt", "alpha beta gamma engine words")
        store.close()

        result = reembed_substrate(db, _make_cipher(), fake_embed_512)
        assert result["migrated"] == 1
        assert result["errors"] == 0
        assert result["verified"] == 1

        conn = sqlite3.connect(db)
        raw = conn.execute("SELECT embedding FROM substrate_chunks").fetchone()[0]
        conn.close()
        vec = np.frombuffer(raw, dtype=np.float32)
        expected = fake_embed_512(["alpha beta gamma engine words"])[0]
        np.testing.assert_allclose(vec, expected, rtol=1e-6)

    def test_bad_embed_fn_shape_is_an_error_not_a_write(
        self, seeded: tuple[str, FieldCipher]
    ) -> None:
        db, cipher = seeded
        before = _read_embeddings(db)

        def bad_embed(texts: list[str]) -> np.ndarray:
            return np.zeros((len(texts), 3), dtype=np.float32)

        result = reembed_substrate(db, cipher, bad_embed)
        assert result["errors"] == 3
        assert result["migrated"] == 0
        assert _read_embeddings(db) == before  # nothing half-written
        assert _read_meta(db) is None  # and no meta stamp on a failed run

    def test_runnable_module_importable(self) -> None:
        """The manual live-box entry point exists (never executed in tests)."""
        from services.assistant_orchestrator.src import reembed_substrate as mod

        assert callable(mod._main)
        assert mod.TARGET_EMBED_MAX_TOKENS == 512
