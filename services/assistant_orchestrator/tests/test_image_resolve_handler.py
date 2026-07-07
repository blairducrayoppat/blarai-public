"""
Tests — AO IMAGE_RESOLVE_REQUEST handler (UC-010/UC-003 WS3, ADR-033 §D)
=======================================================================
``AssistantOrchestratorService._handle_image_resolve_request`` decrypts a stored
``blarai-img://<id>`` and streams the bytes back as chunked
IMAGE_RESOLVE_RESPONSE frames; an unknown id / decrypt-quarantine / no bank all
collapse to the SINGLE found=false placeholder frame.

The handler only touches ``self._knowledge`` + ``self._framer``, so these tests
bind the unbound method to a minimal stand-in (no GPU model, no listener, no
config) — the AO process is never started.  A fake transport captures the sent
frames; the assembled body is checked byte-identical against the original PNG.

CRITICAL DORMANCY LOCK: ``image_gen.is_available()`` (and any model load) is
NEVER called on the resolve path — this is a decrypt-quarantine READ, not a
generation.  A test patches ``is_available`` to RAISE; the handler must succeed.

Reuses the deterministic stub-embedder bank fixtures from ``test_knowledge_bank``
so no ONNX model is required (worktree-safe).
"""

from __future__ import annotations

import uuid

import pytest

from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)
from services.assistant_orchestrator.src.knowledge_bank import (
    EncryptedKnowledgeBank,
)
from services.assistant_orchestrator.tests.test_knowledge_bank import (
    _make_bank,
    _submit,
)
from shared.ipc.protocol import MessageFramer
from shared.ipc.resolve_channel import ResolveAssembler

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\x03" * 64
# A multi-chunk image: > RESOLVE_CHUNK_DATA_BYTES so chunking is exercised.
from shared.ipc.resolve_channel import RESOLVE_CHUNK_DATA_BYTES

_BIG_PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * ((RESOLVE_CHUNK_DATA_BYTES * 2) // 256 + 1)


class _FakeTransport:
    """Captures every frame the handler sends."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send(self, frame: bytes) -> bool:
        self.sent.append(frame)
        return True


class _Harness:
    """Minimal stand-in carrying just what the handler reads."""

    def __init__(self, knowledge) -> None:
        self._knowledge = knowledge
        self._framer = MessageFramer()

    # Bind the real (unbound) handler method.
    _handle_image_resolve_request = (
        AssistantOrchestratorService._handle_image_resolve_request
    )


@pytest.fixture()
def bank() -> EncryptedKnowledgeBank:
    b = _make_bank()
    yield b
    b.close()


def _assemble(frames: list[bytes]) -> ResolveAssembler:
    asm = ResolveAssembler()
    for f in frames:
        asm.feed(f)
    return asm


def _store_generated(bank: EncryptedKnowledgeBank, data: bytes) -> str:
    image_id = uuid.uuid4().hex
    bank.store_generated_image(
        image_id=image_id, session_id="s1", image_bytes=data,
        mime="image/png", prompt="a red cube",
    )
    return image_id


# ---------------------------------------------------------------------------
# Found — streams the decrypted bytes byte-identically
# ---------------------------------------------------------------------------


def test_found_streams_bytes_identical(bank: EncryptedKnowledgeBank) -> None:
    image_id = _store_generated(bank, _PNG)
    t = _FakeTransport()
    harness = _Harness(bank)
    ok = harness._handle_image_resolve_request(
        t, "r1", {"image_id": image_id}
    )
    assert ok is True
    asm = _assemble(t.sent)
    assert asm.complete and asm.found is True
    assert asm.mime == "image/png"
    assert asm.body() == _PNG


def test_found_multichunk_round_trip(bank: EncryptedKnowledgeBank) -> None:
    image_id = _store_generated(bank, _BIG_PNG)
    t = _FakeTransport()
    ok = _Harness(bank)._handle_image_resolve_request(t, "r2", {"image_id": image_id})
    assert ok is True
    assert len(t.sent) >= 2  # multi-chunk
    assert _assemble(t.sent).body() == _BIG_PNG


# ---------------------------------------------------------------------------
# Placeholder — unknown id / no bank / bad id / quarantine
# ---------------------------------------------------------------------------


def test_unstored_id_single_placeholder(bank: EncryptedKnowledgeBank) -> None:
    t = _FakeTransport()
    ok = _Harness(bank)._handle_image_resolve_request(
        t, "r3", {"image_id": uuid.uuid4().hex}
    )
    assert ok is True
    assert len(t.sent) == 1
    asm = _assemble(t.sent)
    assert asm.complete and asm.found is False


def test_no_bank_single_placeholder() -> None:
    t = _FakeTransport()
    ok = _Harness(None)._handle_image_resolve_request(
        t, "r4", {"image_id": uuid.uuid4().hex}
    )
    assert ok is True
    assert _assemble(t.sent).found is False


def test_empty_id_single_placeholder(bank: EncryptedKnowledgeBank) -> None:
    t = _FakeTransport()
    ok = _Harness(bank)._handle_image_resolve_request(t, "r5", {"image_id": ""})
    assert ok is True
    assert _assemble(t.sent).found is False


def test_quarantine_returns_placeholder(bank: EncryptedKnowledgeBank) -> None:
    """A tampered stored row decrypt-quarantines → placeholder, never partial."""
    image_id = _store_generated(bank, _PNG)
    row = bank._conn.execute(
        "SELECT data FROM generated_images WHERE image_id=?", (image_id,)
    ).fetchone()
    corrupted = bytes(row[0])
    corrupted = corrupted[:-1] + bytes([corrupted[-1] ^ 0xFF])
    with bank._conn:
        bank._conn.execute(
            "UPDATE generated_images SET data=? WHERE image_id=?",
            (corrupted, image_id),
        )
    t = _FakeTransport()
    ok = _Harness(bank)._handle_image_resolve_request(t, "r6", {"image_id": image_id})
    assert ok is True
    assert _assemble(t.sent).found is False


# ---------------------------------------------------------------------------
# DORMANCY LOCK — no model load / is_available() ever consulted
# ---------------------------------------------------------------------------


def test_resolve_never_touches_image_gen(
    bank: EncryptedKnowledgeBank, monkeypatch
) -> None:
    """The resolve path is a decrypt READ, NOT a generation — it must never call
    image_gen.is_available() (nor load a model).  Patch is_available to RAISE: a
    successful resolve proves the model surface is never touched."""
    import shared.inference.image_gen as ig

    def _boom() -> bool:
        raise AssertionError(
            "image_gen.is_available() called on the resolve path (no model load "
            "is permitted here)"
        )

    monkeypatch.setattr(ig, "is_available", _boom)

    image_id = _store_generated(bank, _PNG)
    t = _FakeTransport()
    ok = _Harness(bank)._handle_image_resolve_request(t, "r7", {"image_id": image_id})
    assert ok is True
    assert _assemble(t.sent).body() == _PNG
