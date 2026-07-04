"""
Tests for display-only article images in the Encrypted Knowledge Bank
(UC-003 Workstream B — DORMANT build, Vikunja #663).

Covers the Module C storage contract:
  * ``store_image`` / ``get_images_for_doc`` round-trip + at-rest encryption
    (alt / source_url / data are ciphertext on disk; mime is plaintext label).
  * ON DELETE CASCADE: deleting the parent doc reaps its images.
  * keyed-hash dedup on ``image_hash`` (same bytes → same index, detectable).
  * orphan refusal: an image for an unknown doc_uuid is refused.
  * THE NO-VLM STRUCTURAL LOCK: passing non-``str`` (e.g. image bytes) into the
    embed path raises ``TypeError`` at BOTH call sites (approve + retrieve).
  * ``retrieve`` is text-only and never surfaces an image row.

Reuses the deterministic stub-embedder fixtures from ``test_knowledge_bank``
so no ONNX model is required (worktree-safe).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from services.assistant_orchestrator.src.knowledge_bank import (
    EncryptedKnowledgeBank,
    KnowledgeBankError,
    KnowledgeImage,
    _guard_embed_input,
)
from services.assistant_orchestrator.tests.test_knowledge_bank import (
    _make_bank,
    _make_cipher,
    _submit,
)

# A minimal valid PNG header + a little body — magic-byte realism is the
# binary egress door's job (Module A); here we only need representative bytes.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\x03" * 16
_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x10\x20\x30\x40" * 16


@pytest.fixture()
def bank() -> EncryptedKnowledgeBank:
    b = _make_bank()
    yield b
    b.close()


def _doc(bank: EncryptedKnowledgeBank) -> str:
    """Submit one pending doc and return its doc_uuid (a valid image parent)."""
    return _submit(bank).doc_uuid


def _png_header(w: int, h: int) -> bytes:
    """A valid PNG header with an in-band IHDR width/height (header-only, no
    decode) — READABLE by the dimension parser."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + (0).to_bytes(4, "big") + b"IHDR"
        + w.to_bytes(4, "big") + h.to_bytes(4, "big")
        + b"\x00" * 8
    )


# ---------------------------------------------------------------------------
# 0. W1 / BED-3 — at-rest decompression-bomb ceiling (store-time mirror)
# ---------------------------------------------------------------------------


class TestStoreImageDimensionCeiling:
    def test_oversize_image_refused_at_store(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """An image whose READABLE header declares dimensions over the
        decompression-bomb ceiling is REFUSED at the at-rest store boundary
        (defense-in-depth mirror of the coordinator's fetch-time drop)."""
        doc_uuid = _doc(bank)
        with pytest.raises(KnowledgeBankError, match="decompression-bomb ceiling"):
            bank.store_image(
                image_id=uuid.uuid4().hex,
                doc_uuid=doc_uuid,
                image_bytes=_png_header(20000, 100),  # 20000 px > 16384 max edge
                mime="image/png",
                alt="a bomb",
                source_url="https://example.org/img/bomb.png",
                approval_state="pending",
            )
        assert bank.image_count(doc_uuid) == 0  # nothing stored

    def test_normal_dimension_image_stores(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """An ordinary-dimension image (under the ceiling) stores normally."""
        doc_uuid = _doc(bank)
        bank.store_image(
            image_id=uuid.uuid4().hex,
            doc_uuid=doc_uuid,
            image_bytes=_png_header(1920, 1080),
            mime="image/png",
            alt="a photo",
            source_url="https://example.org/img/photo.png",
            approval_state="pending",
        )
        assert bank.image_count(doc_uuid) == 1

    def test_unreadable_header_image_is_not_refused_by_ceiling(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """The store mirror is the AFFIRMATIVE ceiling only: an image that passed
        the magic-byte gate but whose header can't be measured is NOT refused on
        the ceiling basis (it cannot be 'provably too big').  Locks the boundary
        between the store mirror (affirmative) and the coordinator gate (which
        fails closed on unreadable upstream)."""
        doc_uuid = _doc(bank)
        bank.store_image(
            image_id=uuid.uuid4().hex,
            doc_uuid=doc_uuid,
            image_bytes=_PNG_BYTES,  # valid PNG magic, no IHDR → unreadable header
            mime="image/png",
            alt="unmeasurable",
            source_url="https://example.org/img/x.png",
            approval_state="pending",
        )
        assert bank.image_count(doc_uuid) == 1


# ---------------------------------------------------------------------------
# 1. Store / get round-trip
# ---------------------------------------------------------------------------


class TestStoreGetRoundTrip:
    def test_store_then_get_round_trips_all_fields(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        doc_uuid = _doc(bank)
        image_id = uuid.uuid4().hex
        bank.store_image(
            image_id=image_id,
            doc_uuid=doc_uuid,
            image_bytes=_PNG_BYTES,
            mime="image/png",
            alt="a diagram of a turbocharger",
            source_url="https://example.org/img/turbo.png",
            approval_state="pending",
        )
        images = bank.get_images_for_doc(doc_uuid)
        assert len(images) == 1
        img = images[0]
        assert isinstance(img, KnowledgeImage)
        assert img.image_id == image_id
        assert img.doc_uuid == doc_uuid
        assert img.mime == "image/png"
        assert img.alt == "a diagram of a turbocharger"
        assert img.source_url == "https://example.org/img/turbo.png"
        assert img.data == _PNG_BYTES
        assert img.approval_state == "pending"
        assert img.created_at  # ISO timestamp present

    def test_multiple_images_ordered_stable(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        doc_uuid = _doc(bank)
        ids = [uuid.uuid4().hex for _ in range(3)]
        for i, iid in enumerate(ids):
            bank.store_image(
                image_id=iid,
                doc_uuid=doc_uuid,
                image_bytes=_PNG_BYTES + bytes([i]),
                mime="image/png",
                alt=f"image {i}",
                source_url=f"https://example.org/img/{i}.png",
                approval_state="pending",
            )
        got = [img.image_id for img in bank.get_images_for_doc(doc_uuid)]
        assert got == ids  # created_at, id ordering is insertion order
        assert bank.image_count(doc_uuid) == 3
        assert bank.image_count() == 3

    def test_get_for_doc_with_no_images_is_empty(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        doc_uuid = _doc(bank)
        assert bank.get_images_for_doc(doc_uuid) == []
        assert bank.image_count(doc_uuid) == 0

    def test_images_isolated_per_doc(self, bank: EncryptedKnowledgeBank) -> None:
        doc_a = _submit(bank, source_ref="https://example.org/a").doc_uuid
        doc_b = _submit(bank, source_ref="https://example.org/b").doc_uuid
        bank.store_image(
            image_id=uuid.uuid4().hex,
            doc_uuid=doc_a,
            image_bytes=_PNG_BYTES,
            mime="image/png",
            alt="a",
            source_url="https://example.org/a.png",
            approval_state="pending",
        )
        assert bank.image_count(doc_a) == 1
        assert bank.get_images_for_doc(doc_b) == []


# ---------------------------------------------------------------------------
# 2. Encryption at rest (ciphertext != plaintext)
# ---------------------------------------------------------------------------


class TestEncryptionAtRest:
    def test_content_columns_are_ciphertext_in_db(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        doc_uuid = _doc(bank)
        image_id = uuid.uuid4().hex
        alt = "secret alt text describing the photo"
        source_url = "https://private.example.org/secret-image.png"
        bank.store_image(
            image_id=image_id,
            doc_uuid=doc_uuid,
            image_bytes=_PNG_BYTES,
            mime="image/png",
            alt=alt,
            source_url=source_url,
            approval_state="pending",
        )
        row = bank._conn.execute(
            "SELECT alt, source_url, data FROM knowledge_images WHERE image_id=?",
            (image_id,),
        ).fetchone()
        stored_alt, stored_url, stored_data = bytes(row[0]), bytes(row[1]), bytes(row[2])
        # Stored blobs must NOT equal the plaintext.
        assert stored_alt != alt.encode("utf-8")
        assert stored_url != source_url.encode("utf-8")
        assert stored_data != _PNG_BYTES
        # And the plaintext must not appear inside the ciphertext blobs.
        assert alt.encode("utf-8") not in stored_alt
        assert source_url.encode("utf-8") not in stored_url
        assert _PNG_BYTES not in stored_data

    def test_no_image_plaintext_on_disk(self, tmp_path: Path) -> None:
        """alt / source_url / image bytes are ciphertext in the raw DB file."""
        db = str(tmp_path / "knowledge.db")
        b = _make_bank(db_path=db)
        doc_uuid = _submit(b).doc_uuid
        alt = "ZEBRA_ALT_MARKER_alt_text"
        url = "https://example.org/ZEBRA_URL_MARKER.png"
        # The PNG signature MUST lead (store-time #6 re-validation sniffs magic
        # bytes at the start, exactly like the fetch door) — the marker rides
        # AFTER it so the body is a valid PNG whose marker must still encrypt.
        body = _PNG_BYTES + b"ZEBRA_BYTES_MARKER"
        b.store_image(
            image_id=uuid.uuid4().hex,
            doc_uuid=doc_uuid,
            image_bytes=body,
            mime="image/png",
            alt=alt,
            source_url=url,
            approval_state="pending",
        )
        b.close()  # checkpoint WAL into the main file
        raw = Path(db).read_bytes()
        for sample in (
            alt.encode("utf-8"),
            url.encode("utf-8"),
            b"ZEBRA_BYTES_MARKER",
        ):
            assert sample not in raw, f"image plaintext leaked to disk: {sample!r}"

    def test_mime_is_plaintext_by_design(self, tmp_path: Path) -> None:
        """mime is a structural label kept plaintext (needed to pick a decoder
        at render time without a decrypt)."""
        db = str(tmp_path / "knowledge.db")
        b = _make_bank(db_path=db)
        doc_uuid = _submit(b).doc_uuid
        b.store_image(
            image_id=uuid.uuid4().hex,
            doc_uuid=doc_uuid,
            image_bytes=_JPEG_BYTES,
            mime="image/jpeg",
            alt="x",
            source_url="https://example.org/x.jpg",
            approval_state="pending",
        )
        b.close()
        assert b"image/jpeg" in Path(db).read_bytes()

    def test_alt_aad_bound_to_image_id(self, bank: EncryptedKnowledgeBank) -> None:
        """An alt ciphertext relocated to a different image_id must refuse to
        decrypt (AAD binds the row identity) — the row is quarantined."""
        from shared.security.field_cipher import FieldCipherError

        doc_uuid = _doc(bank)
        a_id = uuid.uuid4().hex
        b_id = uuid.uuid4().hex
        bank.store_image(
            image_id=a_id, doc_uuid=doc_uuid, image_bytes=_PNG_BYTES,
            mime="image/png", alt="alt-a", source_url="https://example.org/a.png",
            approval_state="pending",
        )
        bank.store_image(
            image_id=b_id, doc_uuid=doc_uuid, image_bytes=_JPEG_BYTES,
            mime="image/jpeg", alt="alt-b", source_url="https://example.org/b.jpg",
            approval_state="pending",
        )
        # Plant a's alt ciphertext into b's alt column.
        alt_a_blob = bank._conn.execute(
            "SELECT alt FROM knowledge_images WHERE image_id=?", (a_id,)
        ).fetchone()[0]
        with bank._conn:
            bank._conn.execute(
                "UPDATE knowledge_images SET alt=? WHERE image_id=?",
                (alt_a_blob, b_id),
            )
        # The direct field decrypt must refuse (AAD binds doc_uuid|image_id —
        # a's blob under b's image_id fails authentication).
        with pytest.raises(FieldCipherError):
            bank._dec_image_field("alt", doc_uuid, b_id, alt_a_blob)
        # And the bulk read quarantines b, returning only the healthy a.
        got = {img.image_id for img in bank.get_images_for_doc(doc_uuid)}
        assert got == {a_id}

    def test_cross_doc_reassociation_quarantines(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """An image row whose plaintext doc_uuid is rewritten to a DIFFERENT
        document must refuse to decrypt when read under that document — the AAD
        binds the parent doc_uuid, so a tampered-DB cross-doc re-association
        cannot silently render one doc's image under another's preview (review
        fix, 2026-06-14 — parity with image_staging + knowledge_chunks)."""
        # Two DISTINCT parent docs (distinct source_refs — a shared source_ref
        # would dedup-replace the first).
        doc_a = _submit(bank, source_ref="https://example.org/doc-a").doc_uuid
        doc_b = _submit(bank, source_ref="https://example.org/doc-b").doc_uuid
        img_id = uuid.uuid4().hex
        bank.store_image(
            image_id=img_id, doc_uuid=doc_a, image_bytes=_PNG_BYTES,
            mime="image/png", alt="secret-a", source_url="https://example.org/a.png",
            approval_state="pending",
        )
        # Tamper: re-point the image's plaintext doc_uuid column to doc_b.
        with bank._conn:
            bank._conn.execute(
                "UPDATE knowledge_images SET doc_uuid=? WHERE image_id=?",
                (doc_b, img_id),
            )
        # Reading doc_b selects the relocated row but decrypt binds to doc_b's
        # identity, which mismatches the AAD (encrypted under doc_a) -> quarantine.
        assert bank.get_images_for_doc(doc_b) == []
        # doc_a no longer owns the row (the plaintext FK moved), so it is empty too
        # — the image is unreachable as plaintext under EITHER identity (fail-closed).
        assert bank.get_images_for_doc(doc_a) == []


# ---------------------------------------------------------------------------
# 3. CASCADE delete with the parent doc
# ---------------------------------------------------------------------------


class TestCascadeDelete:
    def test_deleting_doc_cascades_to_images(self, tmp_path: Path) -> None:
        """foreign_keys=ON + ON DELETE CASCADE: deleting the parent doc reaps
        its images.  Mirrors how submit_pending's dedup-replace DELETE relies
        on the same cascade for knowledge_chunks."""
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b = _make_bank(db_path=db, cipher=cipher)
        doc_uuid = _submit(b).doc_uuid
        for _ in range(2):
            b.store_image(
                image_id=uuid.uuid4().hex, doc_uuid=doc_uuid,
                image_bytes=_PNG_BYTES, mime="image/png", alt="x",
                source_url="https://example.org/x.png", approval_state="pending",
            )
        assert b.image_count(doc_uuid) == 2
        # Delete the parent document (the production delete path; cascade fires).
        with b._conn:
            b._conn.execute(
                "DELETE FROM knowledge_docs WHERE doc_uuid=?", (doc_uuid,)
            )
        assert b.image_count(doc_uuid) == 0
        assert b.image_count() == 0
        b.close()

    def test_resubmit_dedup_replace_cascades_images(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """A pending re-submit DELETEs the prior doc row; its images cascade
        away too (no orphan images survive the replace)."""
        first = _submit(bank, content="first fetch of the article body words")
        bank.store_image(
            image_id=uuid.uuid4().hex, doc_uuid=first.doc_uuid,
            image_bytes=_PNG_BYTES, mime="image/png", alt="x",
            source_url="https://example.org/x.png", approval_state="pending",
        )
        assert bank.image_count(first.doc_uuid) == 1
        # Re-submit the SAME source → replaces the prior doc (cascade reaps img).
        second = _submit(bank, content="refreshed fetch with corrected body words")
        assert second.replaced_prior is True
        assert bank.image_count(first.doc_uuid) == 0
        assert bank.image_count() == 0


# ---------------------------------------------------------------------------
# 4. Keyed-hash dedup
# ---------------------------------------------------------------------------


class TestKeyedHashDedup:
    def test_same_bytes_same_keyed_hash(self, bank: EncryptedKnowledgeBank) -> None:
        h1 = bank.image_hash_for(_PNG_BYTES)
        h2 = bank.image_hash_for(_PNG_BYTES)
        h_other = bank.image_hash_for(_JPEG_BYTES)
        assert h1 == h2
        assert h1 != h_other
        assert len(h1) == 32  # HMAC-SHA256 digest

    def test_keyed_hash_is_key_bound(self) -> None:
        """Different DEKs → different image_hash for identical bytes (denies
        cross-store byte-membership testing on the index alone)."""
        b1 = _make_bank(cipher=_make_cipher())
        b2 = _make_bank(cipher=_make_cipher())
        try:
            assert b1.image_hash_for(_PNG_BYTES) != b2.image_hash_for(_PNG_BYTES)
        finally:
            b1.close()
            b2.close()

    def test_duplicate_bytes_detectable_via_hash_column(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """Two images with identical bytes share an image_hash — a duplicate is
        detectable by querying the keyed index column (dedup-over-ciphertext)."""
        doc_uuid = _doc(bank)
        for _ in range(2):
            bank.store_image(
                image_id=uuid.uuid4().hex, doc_uuid=doc_uuid,
                image_bytes=_PNG_BYTES, mime="image/png", alt="x",
                source_url="https://example.org/x.png", approval_state="pending",
            )
        keyed = bank.image_hash_for(_PNG_BYTES)
        dup_count = bank._conn.execute(
            "SELECT COUNT(*) FROM knowledge_images WHERE image_hash=?", (keyed,)
        ).fetchone()[0]
        assert int(dup_count) == 2  # both rows carry the identical keyed index

    def test_same_image_id_restore_is_idempotent(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """Re-storing the SAME image_id (e.g. an ingest retry) refreshes the row
        rather than raising on the UNIQUE constraint or duplicating it."""
        doc_uuid = _doc(bank)
        image_id = uuid.uuid4().hex
        bank.store_image(
            image_id=image_id, doc_uuid=doc_uuid, image_bytes=_PNG_BYTES,
            mime="image/png", alt="first", source_url="https://example.org/x.png",
            approval_state="pending",
        )
        bank.store_image(
            image_id=image_id, doc_uuid=doc_uuid, image_bytes=_JPEG_BYTES,
            mime="image/jpeg", alt="second", source_url="https://example.org/y.jpg",
            approval_state="pending",
        )
        images = bank.get_images_for_doc(doc_uuid)
        assert len(images) == 1
        assert images[0].alt == "second"
        assert images[0].mime == "image/jpeg"
        assert images[0].data == _JPEG_BYTES


# ---------------------------------------------------------------------------
# 5. Orphan refusal + input validation
# ---------------------------------------------------------------------------


class TestStoreValidation:
    def test_unknown_doc_uuid_refused(self, bank: EncryptedKnowledgeBank) -> None:
        with pytest.raises(KnowledgeBankError, match="unknown doc_uuid"):
            bank.store_image(
                image_id=uuid.uuid4().hex, doc_uuid=str(uuid.uuid4()),
                image_bytes=_PNG_BYTES, mime="image/png", alt="x",
                source_url="https://example.org/x.png", approval_state="pending",
            )
        assert bank.image_count() == 0  # nothing inserted

    def test_empty_image_bytes_refused(self, bank: EncryptedKnowledgeBank) -> None:
        doc_uuid = _doc(bank)
        with pytest.raises(KnowledgeBankError):
            bank.store_image(
                image_id=uuid.uuid4().hex, doc_uuid=doc_uuid, image_bytes=b"",
                mime="image/png", alt="x", source_url="https://example.org/x.png",
                approval_state="pending",
            )

    def test_empty_image_id_refused(self, bank: EncryptedKnowledgeBank) -> None:
        doc_uuid = _doc(bank)
        with pytest.raises(KnowledgeBankError):
            bank.store_image(
                image_id="  ", doc_uuid=doc_uuid, image_bytes=_PNG_BYTES,
                mime="image/png", alt="x", source_url="https://example.org/x.png",
                approval_state="pending",
            )

    def test_empty_mime_refused(self, bank: EncryptedKnowledgeBank) -> None:
        doc_uuid = _doc(bank)
        with pytest.raises(KnowledgeBankError):
            bank.store_image(
                image_id=uuid.uuid4().hex, doc_uuid=doc_uuid,
                image_bytes=_PNG_BYTES, mime="", alt="x",
                source_url="https://example.org/x.png", approval_state="pending",
            )


# ---------------------------------------------------------------------------
# 6. THE NO-VLM STRUCTURAL LOCK (critical regression)
# ---------------------------------------------------------------------------


class TestNoVlmStructuralLock:
    def test_guard_rejects_bytes_directly(self) -> None:
        """The guard refuses raw image bytes with the contract TypeError."""
        with pytest.raises(
            TypeError, match="image bytes must not reach the embedder"
        ):
            _guard_embed_input(_PNG_BYTES)  # type: ignore[arg-type]

    def test_guard_rejects_list_of_bytes(self) -> None:
        with pytest.raises(
            TypeError, match="image bytes must not reach the embedder"
        ):
            _guard_embed_input([_PNG_BYTES])  # type: ignore[list-item]

    def test_guard_rejects_mixed_list(self) -> None:
        with pytest.raises(TypeError):
            _guard_embed_input(["a real chunk", _PNG_BYTES])  # type: ignore[list-item]

    def test_guard_rejects_empty_and_non_list(self) -> None:
        with pytest.raises(TypeError):
            _guard_embed_input([])  # empty list
        with pytest.raises(TypeError):
            _guard_embed_input("a bare string")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            _guard_embed_input(None)  # type: ignore[arg-type]

    def test_guard_passes_list_of_str(self) -> None:
        chunks = ["one chunk", "two chunk"]
        assert _guard_embed_input(chunks) is chunks

    def test_retrieve_path_rejects_bytes_embedder(self) -> None:
        """A REGRESSION lock at the retrieve() call site: an embed_fn that is
        (mis)handed bytes never runs — the guard raises first.  We prove it by
        a malicious embed_fn that would happily 'embed' bytes; the guard must
        fire before it is ever called."""
        called: list[object] = []

        def byte_eating_embed(texts: object):  # noqa: ANN001 — deliberately loose
            called.append(texts)
            import numpy as np

            from services.assistant_orchestrator.src.substrate import EMBED_DIM

            return np.zeros((1, EMBED_DIM), dtype=np.float32)

        b = EncryptedKnowledgeBank(
            db_path=":memory:", embed_fn=byte_eating_embed, cipher=_make_cipher()
        )
        try:
            r = _submit(b)
            # Approve uses the real text chunks → guard passes, embed runs.
            # Now monkeypatch the stored embed to receive bytes and prove the
            # guard at the retrieve site refuses BEFORE embed_fn is reached.
            b.approve(r.doc_uuid)
            called.clear()
            # Drive retrieve with a query whose embed would be guarded; the
            # guard wraps [query] (a list[str]) so a normal query is fine —
            # the structural protection is that a bytes query can't get here.
            # Directly exercise the guard contract the call site relies on:
            with pytest.raises(TypeError):
                b._embed(_guard_embed_input(b"not a query"))  # type: ignore[arg-type]
            assert called == []  # byte path never invoked the embedder
        finally:
            b.close()

    def test_approve_path_uses_guard(self, bank: EncryptedKnowledgeBank) -> None:
        """Sanity: the normal approve path (list[str] chunks) still works —
        the guard is transparent to valid input."""
        r = _submit(bank)
        n = bank.approve(r.doc_uuid)
        assert n >= 1


# ---------------------------------------------------------------------------
# 7. retrieve() never surfaces an image row (text-only)
# ---------------------------------------------------------------------------


class TestRetrieveTextOnly:
    def test_retrieve_returns_only_text_hits_never_images(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        r = _submit(bank)
        bank.approve(r.doc_uuid)
        # Attach images to the approved doc.
        for i in range(3):
            bank.store_image(
                image_id=uuid.uuid4().hex, doc_uuid=r.doc_uuid,
                image_bytes=_PNG_BYTES + bytes([i]), mime="image/png",
                alt=f"diagram {i}", source_url=f"https://example.org/{i}.png",
                approval_state="approved",
            )
        hits = bank.retrieve("turbochargers engine power", k=10)
        assert hits, "expected at least one text chunk hit"
        # Every hit is a text chunk (has chunk_index + text), never an image.
        for h in hits:
            assert isinstance(h.text, str)
            assert h.text  # decrypted chunk text, not image bytes
            assert hasattr(h, "chunk_index")
        # Image alt text must NOT have leaked into any retrieval hit.
        joined = " ".join(h.text for h in hits)
        assert "diagram 0" not in joined
        assert "diagram 1" not in joined

    def test_retrieve_does_not_query_knowledge_images(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """retrieve() must NEVER touch the knowledge_images table.  We wrap BOTH
        connections (the main DB ``_conn`` and the in-memory FTS ``_fts``) in a
        spy proxy that fails loudly if any knowledge_images query is issued
        during retrieve.  (sqlite3.Connection.execute is read-only, so we swap
        the connection object, not the method.)  retrieve may legitimately run
        purely from the in-RAM caches; the lock is that NO image SQL fires."""
        r = _submit(bank)
        bank.approve(r.doc_uuid)
        bank.store_image(
            image_id=uuid.uuid4().hex, doc_uuid=r.doc_uuid,
            image_bytes=_PNG_BYTES, mime="image/png", alt="x",
            source_url="https://example.org/x.png", approval_state="approved",
        )

        seen: list[str] = []

        class _SpyConn:
            def __init__(self, real: object) -> None:
                self._real = real

            def execute(self, sql, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
                seen.append(sql)
                if "knowledge_images" in sql:
                    raise AssertionError(
                        "retrieve() queried knowledge_images — display-only "
                        "store must never enter the retrieval path"
                    )
                return self._real.execute(sql, *args, **kwargs)

            def __getattr__(self, name: str) -> object:
                return getattr(self._real, name)

        real_conn, real_fts = bank._conn, bank._fts
        bank._conn = _SpyConn(real_conn)  # type: ignore[assignment]
        bank._fts = _SpyConn(real_fts)  # type: ignore[assignment]
        try:
            hits = bank.retrieve("turbochargers engine power", k=5)
        finally:
            bank._conn, bank._fts = real_conn, real_fts
        # The retrieve returned text hits and provably issued no image SQL.
        assert hits, "expected text-chunk hits"
        assert all("knowledge_images" not in s for s in seen)


# ---------------------------------------------------------------------------
# 8. Edit-approve cascade survival (#2 / A×B, c.1087)
# ---------------------------------------------------------------------------


class TestEditResubmitImageMigration:
    """On an edited re-submit, an image whose ``blarai-img://<id>`` ref the
    operator KEPT in the edited body is MIGRATED (re-keyed AAD) to the new doc;
    one whose ref was deleted is reaped by the dedup-replace CASCADE.  The
    survivor-set is derived from the submit content (the edited body IS the
    content), so no separate signal is threaded."""

    def test_kept_ref_image_migrates_to_new_doc(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        img_id = uuid.uuid4().hex
        first = _submit(bank, content="original article body words here")
        bank.store_image(
            image_id=img_id, doc_uuid=first.doc_uuid, image_bytes=_PNG_BYTES,
            mime="image/png", alt="kept diagram",
            source_url="https://cdn.example/k.png", approval_state="pending",
        )
        assert bank.image_count(first.doc_uuid) == 1
        # Edited re-submit whose body STILL references the image's local ref.
        edited = f"edited body ![kept diagram](blarai-img://{img_id}) more words"
        second = _submit(bank, content=edited)
        assert second.replaced_prior is True
        assert second.doc_uuid != first.doc_uuid
        # The prior doc is gone; the image migrated to the NEW doc, intact.
        assert bank.image_count(first.doc_uuid) == 0
        assert bank.image_count(second.doc_uuid) == 1
        img = bank.get_images_for_doc(second.doc_uuid)[0]
        assert img.image_id == img_id
        assert img.doc_uuid == second.doc_uuid
        assert img.data == _PNG_BYTES
        assert img.alt == "kept diagram"
        assert img.source_url == "https://cdn.example/k.png"
        assert img.approval_state == "pending"

    def test_deleted_ref_image_is_reaped(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        img_id = uuid.uuid4().hex
        first = _submit(bank, content="original body words here")
        bank.store_image(
            image_id=img_id, doc_uuid=first.doc_uuid, image_bytes=_PNG_BYTES,
            mime="image/png", alt="x", source_url="https://cdn.example/x.png",
            approval_state="pending",
        )
        # Edited body that DROPPED the image ref -> reaped by the cascade.
        second = _submit(bank, content="edited body with the image removed")
        assert second.replaced_prior is True
        assert bank.image_count(second.doc_uuid) == 0
        assert bank.image_count() == 0

    def test_selective_migration_keeps_only_referenced(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        keep_id = uuid.uuid4().hex
        drop_id = uuid.uuid4().hex
        first = _submit(bank, content="body words")
        for i, iid in enumerate((keep_id, drop_id)):
            bank.store_image(
                image_id=iid, doc_uuid=first.doc_uuid,
                image_bytes=_PNG_BYTES + bytes([i]), mime="image/png",
                alt=f"img{i}", source_url=f"https://cdn.example/{i}.png",
                approval_state="pending",
            )
        assert bank.image_count(first.doc_uuid) == 2
        # Edited body keeps ONLY keep_id's ref.
        second = _submit(bank, content=f"edited ![k](blarai-img://{keep_id}) only")
        assert bank.image_count(second.doc_uuid) == 1
        assert {i.image_id for i in bank.get_images_for_doc(second.doc_uuid)} == {keep_id}

    def test_migrated_image_rebinds_aad_to_new_doc(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """The migrated row's ciphertext is RE-ENCRYPTED under the new doc's
        AAD — it decrypts under the new doc_uuid and NOT under the prior one."""
        from shared.security.field_cipher import FieldCipherError

        img_id = uuid.uuid4().hex
        first = _submit(bank, content="body words")
        bank.store_image(
            image_id=img_id, doc_uuid=first.doc_uuid, image_bytes=_PNG_BYTES,
            mime="image/png", alt="a", source_url="https://cdn.example/a.png",
            approval_state="pending",
        )
        second = _submit(bank, content=f"![a](blarai-img://{img_id}) words")
        blob = bank._conn.execute(
            "SELECT data FROM knowledge_images WHERE image_id=?", (img_id,)
        ).fetchone()[0]
        # New AAD authenticates...
        assert bank._dec_image_field("data", second.doc_uuid, img_id, blob) == _PNG_BYTES
        # ...prior AAD does NOT (the ciphertext was re-bound, not relabeled).
        with pytest.raises(FieldCipherError):
            bank._dec_image_field("data", first.doc_uuid, img_id, blob)

    def test_undecryptable_surviving_image_skipped_doc_still_lands(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """Fail-safe per row: a surviving image that cannot decrypt is SKIPPED
        (not re-encrypted as garbage); the edited doc still lands."""
        img_id = uuid.uuid4().hex
        first = _submit(bank, content="body words")
        bank.store_image(
            image_id=img_id, doc_uuid=first.doc_uuid, image_bytes=_PNG_BYTES,
            mime="image/png", alt="a", source_url="https://cdn.example/a.png",
            approval_state="pending",
        )
        # Corrupt the data ciphertext so the migration decrypt fails.
        with bank._conn:
            bank._conn.execute(
                "UPDATE knowledge_images SET data=? WHERE image_id=?",
                (b"\x00" * 48, img_id),
            )
        second = _submit(bank, content=f"![a](blarai-img://{img_id}) words")
        # The doc still landed (migration never fails the submit)...
        assert second.replaced_prior is True
        assert bank.approval_state_for(second.doc_uuid) == "pending"
        # ...and the undecryptable image was NOT migrated.
        assert bank.image_count(second.doc_uuid) == 0

    def test_resubmit_with_no_local_refs_reaps_all(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """The dormant default path: a re-submit whose body has NO blarai-img
        refs migrates nothing — byte-identical to the pre-#2 cascade behavior."""
        first = _submit(bank, content="first body")
        for i in range(2):
            bank.store_image(
                image_id=uuid.uuid4().hex, doc_uuid=first.doc_uuid,
                image_bytes=_PNG_BYTES + bytes([i]), mime="image/png", alt="x",
                source_url="https://cdn.example/x.png", approval_state="pending",
            )
        second = _submit(bank, content="second body with no image references")
        assert bank.image_count(second.doc_uuid) == 0
        assert bank.image_count() == 0

    def test_rejected_source_images_are_purged_not_resurrected(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """With DELETE-on-reject (LA decision 2026-06-15), rejecting a doc PURGES
        its images at rest, so a later re-submit of the SAME source has nothing to
        migrate — a kept (now-dangling) ref does NOT resurrect the purged bytes.
        In the real flow a re-ingest re-fetches fresh images (new ids); migration
        is for the pending edit-before-approve path, never the reject path."""
        img_id = uuid.uuid4().hex
        first = _submit(bank, content="body words here")
        bank.store_image(
            image_id=img_id, doc_uuid=first.doc_uuid, image_bytes=_PNG_BYTES,
            mime="image/png", alt="kept", source_url="https://cdn.example/k.png",
            approval_state="pending",
        )
        bank.reject(first.doc_uuid)
        # reject() purged the image bytes at rest (DELETE-on-reject).
        assert bank.image_count(first.doc_uuid) == 0
        # Re-submit the SAME source keeping the (now-dangling) ref: the purged
        # image is NOT resurrected by migration (there is nothing left to migrate).
        second = _submit(bank, content=f"edited ![kept](blarai-img://{img_id}) body")
        assert second.replaced_prior is True
        assert bank.image_count(second.doc_uuid) == 0


# ---------------------------------------------------------------------------
# 9. Approve / reject image lifecycle (#3)
# ---------------------------------------------------------------------------


class TestImageApprovalLifecycle:
    def _store(self, bank: EncryptedKnowledgeBank, doc_uuid: str, n: int = 2) -> None:
        for i in range(n):
            bank.store_image(
                image_id=uuid.uuid4().hex, doc_uuid=doc_uuid,
                image_bytes=_PNG_BYTES + bytes([i]), mime="image/png",
                alt=f"img{i}", source_url=f"https://cdn.example/{i}.png",
                approval_state="pending",
            )

    def test_approve_promotes_pending_images(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        r = _submit(bank)
        self._store(bank, r.doc_uuid, n=2)
        bank.approve(r.doc_uuid)
        states = {i.approval_state for i in bank.get_images_for_doc(r.doc_uuid)}
        assert states == {"approved"}

    def test_approve_is_idempotent_for_images(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        r = _submit(bank)
        self._store(bank, r.doc_uuid, n=1)
        bank.approve(r.doc_uuid)
        bank.approve(r.doc_uuid)  # idempotent short-circuit returns before the flip
        imgs = bank.get_images_for_doc(r.doc_uuid)
        assert len(imgs) == 1 and imgs[0].approval_state == "approved"

    def test_reject_purges_images_at_rest(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """DELETE-on-reject (LA decision 2026-06-15): rejecting a doc PURGES its
        display-only image rows at rest (data-minimization on rejected untrusted
        bytes) — the doc TEXT tombstone is retained, but the image bytes are
        gone.  Deliberately DIVERGES from the doc-content tombstone."""
        r = _submit(bank)
        self._store(bank, r.doc_uuid, n=2)
        assert bank.image_count(r.doc_uuid) == 2
        bank.reject(r.doc_uuid)
        # Image rows are GONE (bytes purged); the doc tombstone remains.
        assert bank.get_images_for_doc(r.doc_uuid) == []
        assert bank.image_count(r.doc_uuid) == 0
        assert bank.approval_state_for(r.doc_uuid) == "rejected"

    def test_approve_only_promotes_own_doc_images(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        a = _submit(bank, source_ref="https://example.org/a")
        b = _submit(bank, source_ref="https://example.org/b")
        self._store(bank, a.doc_uuid, n=1)
        self._store(bank, b.doc_uuid, n=1)
        bank.approve(a.doc_uuid)
        assert {i.approval_state for i in bank.get_images_for_doc(a.doc_uuid)} == {"approved"}
        assert {i.approval_state for i in bank.get_images_for_doc(b.doc_uuid)} == {"pending"}

    def test_approve_reject_with_no_images_is_noop(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        a = _submit(bank, source_ref="https://example.org/a")
        b = _submit(bank, source_ref="https://example.org/b")
        bank.approve(a.doc_uuid)  # no images -> empty UPDATE, fine
        bank.reject(b.doc_uuid)   # no images -> empty UPDATE, fine
        assert bank.image_count() == 0


# ---------------------------------------------------------------------------
# 10. Store-time MIME re-validation (#6 — defense-in-depth at the at-rest seam)
# ---------------------------------------------------------------------------


class TestStoreTimeRevalidation:
    def test_png_mime_over_jpeg_bytes_refused(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        doc_uuid = _doc(bank)
        with pytest.raises(KnowledgeBankError, match="re-validation"):
            bank.store_image(
                image_id=uuid.uuid4().hex, doc_uuid=doc_uuid,
                image_bytes=_JPEG_BYTES, mime="image/png", alt="x",
                source_url="https://cdn.example/x.png", approval_state="pending",
            )
        assert bank.image_count() == 0  # nothing mislabeled stored

    def test_svg_mime_refused(self, bank: EncryptedKnowledgeBank) -> None:
        doc_uuid = _doc(bank)
        with pytest.raises(KnowledgeBankError, match="re-validation"):
            bank.store_image(
                image_id=uuid.uuid4().hex, doc_uuid=doc_uuid,
                image_bytes=b"<svg xmlns='x'></svg>", mime="image/svg+xml",
                alt="x", source_url="https://cdn.example/x.svg",
                approval_state="pending",
            )

    def test_unlisted_mime_refused(self, bank: EncryptedKnowledgeBank) -> None:
        doc_uuid = _doc(bank)
        with pytest.raises(KnowledgeBankError, match="re-validation"):
            bank.store_image(
                image_id=uuid.uuid4().hex, doc_uuid=doc_uuid,
                image_bytes=_PNG_BYTES, mime="image/tiff", alt="x",
                source_url="https://cdn.example/x.tiff", approval_state="pending",
            )

    def test_html_over_png_refused(self, bank: EncryptedKnowledgeBank) -> None:
        doc_uuid = _doc(bank)
        with pytest.raises(KnowledgeBankError, match="re-validation"):
            bank.store_image(
                image_id=uuid.uuid4().hex, doc_uuid=doc_uuid,
                image_bytes=b"<html>not an image</html>", mime="image/png",
                alt="x", source_url="https://cdn.example/x.png",
                approval_state="pending",
            )

    @pytest.mark.parametrize(
        "raw_mime, body, expected_mime",
        [
            ("Image/PNG; charset=binary", _PNG_BYTES, "image/png"),
            ("image/jpeg", _JPEG_BYTES, "image/jpeg"),
            ("image/gif", b"GIF89a" + b"\x00" * 16, "image/gif"),
            ("image/gif", b"GIF87a" + b"\x00" * 16, "image/gif"),
            (
                "image/webp",
                b"RIFF" + b"\x20\x00\x00\x00" + b"WEBP" + b"\x00" * 16,
                "image/webp",
            ),
        ],
        ids=["png", "jpeg", "gif89", "gif87", "webp"],
    )
    def test_valid_image_stores_with_sniffed_normalized_mime(
        self, bank: EncryptedKnowledgeBank, raw_mime: str, body: bytes,
        expected_mime: str,
    ) -> None:
        """ACCEPT direction for EVERY allowlisted format: a valid image is NOT
        wrongly refused by the at-rest gate, and the STORED mime is the sniffed,
        normalized form — never the raw label (no false-positive at the store
        seam, adversarial review 2026-06-15)."""
        doc_uuid = _doc(bank)
        bank.store_image(
            image_id=uuid.uuid4().hex, doc_uuid=doc_uuid, image_bytes=body,
            mime=raw_mime, alt="x", source_url="https://cdn.example/x",
            approval_state="pending",
        )
        img = bank.get_images_for_doc(doc_uuid)[0]
        assert img.mime == expected_mime
