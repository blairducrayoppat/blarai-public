"""
Tests — EncryptedKnowledgeBank.get_knowledge_image (UC-010/UC-003 WS3)
=====================================================================
The PER-DOCUMENT-grain single-record decrypt-quarantine read, mirroring
``get_generated_image`` but keyed by ``(doc_uuid, image_id)``.  Built-ahead for
the display corridor's strictest set-membership grain (the renderer resolves by
image_id alone today; this is the ceremony successor for per-doc plumbing).

Locks:
  * round-trip: a stored (doc_uuid, image_id) returns a KnowledgeImage whose
    data == the original PNG.
  * unstored id → None.
  * an image stored under doc A is NOT returned for doc B (per-document
    membership) → None.
  * tamper / wrong-identity decrypt → None (decrypt-quarantine), never partial.

Reuses the deterministic stub-embedder fixtures from ``test_knowledge_bank`` so
no ONNX model is required (worktree-safe). ``test_knowledge_bank.py`` is NOT
modified (owned by another author) — only imported.
"""

from __future__ import annotations

import uuid

import pytest

from services.assistant_orchestrator.src.knowledge_bank import (
    EncryptedKnowledgeBank,
    KnowledgeImage,
)
from services.assistant_orchestrator.tests.test_knowledge_bank import (
    _make_bank,
    _submit,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\x03" * 16


@pytest.fixture()
def bank() -> EncryptedKnowledgeBank:
    b = _make_bank()
    yield b
    b.close()


def _doc(bank: EncryptedKnowledgeBank, ref: str | None = None) -> str:
    # A distinct source_ref+content per doc so two docs do NOT dedup-replace each
    # other (the default _submit shares one source_ref → a second submit reaps
    # the first via dedup; the per-doc-membership test needs both rows to survive).
    if ref is None:
        return _submit(bank).doc_uuid
    return _submit(
        bank,
        source_ref=ref,
        content=f"Distinct article body for {ref} — kept separate for dedup.",
    ).doc_uuid


def _store(bank: EncryptedKnowledgeBank, doc_uuid: str, image_id: str) -> None:
    bank.store_image(
        image_id=image_id,
        doc_uuid=doc_uuid,
        image_bytes=_PNG,
        mime="image/png",
        alt="a diagram",
        source_url="https://example.org/img/d.png",
        approval_state="pending",
    )


def test_round_trip(bank: EncryptedKnowledgeBank) -> None:
    doc_uuid = _doc(bank)
    image_id = uuid.uuid4().hex
    _store(bank, doc_uuid, image_id)
    got = bank.get_knowledge_image(doc_uuid, image_id)
    assert isinstance(got, KnowledgeImage)
    assert got.image_id == image_id
    assert got.doc_uuid == doc_uuid
    assert got.mime == "image/png"
    assert got.data == _PNG
    assert got.alt == "a diagram"


def test_unstored_id_returns_none(bank: EncryptedKnowledgeBank) -> None:
    doc_uuid = _doc(bank)
    assert bank.get_knowledge_image(doc_uuid, uuid.uuid4().hex) is None


def test_wrong_doc_returns_none(bank: EncryptedKnowledgeBank) -> None:
    """An image stored under doc A is NOT returned for doc B — per-document
    membership (the WHERE clause keys on BOTH ids)."""
    doc_a = _doc(bank, ref="https://example.org/a")
    doc_b = _doc(bank, ref="https://example.org/b")
    image_id = uuid.uuid4().hex
    _store(bank, doc_a, image_id)
    # Same image_id, wrong doc → None.
    assert bank.get_knowledge_image(doc_b, image_id) is None
    # And the correct (doc_a, image_id) still resolves.
    assert bank.get_knowledge_image(doc_a, image_id) is not None


def test_tamper_decrypts_to_none(bank: EncryptedKnowledgeBank) -> None:
    """A tampered ``data`` ciphertext fails authentication → decrypt-quarantine
    → None, never partial plaintext."""
    doc_uuid = _doc(bank)
    image_id = uuid.uuid4().hex
    _store(bank, doc_uuid, image_id)
    # Corrupt the encrypted data column directly on the connection.
    row = bank._conn.execute(
        "SELECT data FROM knowledge_images WHERE doc_uuid=? AND image_id=?",
        (doc_uuid, image_id),
    ).fetchone()
    corrupted = bytes(row[0])
    corrupted = corrupted[:-1] + bytes([corrupted[-1] ^ 0xFF])
    with bank._conn:
        bank._conn.execute(
            "UPDATE knowledge_images SET data=? WHERE doc_uuid=? AND image_id=?",
            (corrupted, doc_uuid, image_id),
        )
    assert bank.get_knowledge_image(doc_uuid, image_id) is None
