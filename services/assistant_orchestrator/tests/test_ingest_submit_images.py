"""Regression locks for the AO-side display-only image store/sweep on submit.

UC-003 Workstream B (display-only images) — DORMANT.  The feature code already
exists in ``services/assistant_orchestrator/src/entrypoint.py`` — the
``_store_ingest_images`` method and its call site in ``_handle_ingest_submit``
(gated by ``images_enabled`` resolved from ``[knowledge].images_enabled``).
These tests LOCK its behaviour.

The submit payload may now carry an ``images`` manifest — a list of
``{image_id, staging_path, alt, source_url, mime}`` records (metadata only; the
bytes ride per-image encrypted ``image_staging`` blobs).  These tests write
those blobs FIRST via ``write_staged_image`` using the SAME cipher the handler
uses, so the handler's ``read_staged_image`` succeeds.

THE LOAD-BEARING TEST is
``TestImagesDormantOnSubmit.test_dormant_never_stores_and_sweeps_blobs``:
with ``knowledge_images_enabled=False`` a submit carrying image metadata stores
NOTHING (``bank.store_image`` is NEVER called — proven by a spy that fails if
invoked) AND the per-image staging blobs are DELETED (swept, no orphans), while
the document itself still submits fine.

Reuses the ``_handle_ingest_submit`` harness from ``test_knowledge_bank_wiring``
(``_make_service_with_bank`` / ``_stage_article`` / ``_submit_frame`` /
``_FakeTransport`` / ``_last_result`` / ``_CONTENT``).  No models anywhere.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

from shared.security.field_cipher import FieldCipher
from shared.security.image_staging import (
    image_staging_path_for,
    read_staged_image,
    write_staged_image,
)
from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)
from services.assistant_orchestrator.tests.test_knowledge_bank_wiring import (
    _CONTENT,
    _FakeTransport,
    _last_result,
    _make_resolved_config,
    _make_service_with_bank,
    _stage_article,
    _submit_frame,
)

# Minimal valid-looking PNG/JPEG bytes (the AO never re-sniffs — the binary
# door did that at fetch; here only the round-trip identity matters).
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\x03" * 16
_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x10\x20\x30\x40" * 16


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _staging_dir() -> Path:
    """The canonical (redirected-LOCALAPPDATA) image staging dir."""
    return Path(os.environ["LOCALAPPDATA"]) / "BlarAI" / "ingest_staging"


def _stage_image(
    cipher: FieldCipher, image_bytes: bytes, image_id: str, doc_uuid: str
) -> Path:
    """Write a real encrypted image staging blob under the SAME cipher the
    handler uses, so read_staged_image succeeds."""
    return write_staged_image(image_bytes, image_id, doc_uuid, cipher, _staging_dir())


def _image_meta(image_id: str, doc_uuid: str, **overrides: Any) -> dict[str, str]:
    """A submit-frame image manifest record with the pinned keys."""
    meta: dict[str, str] = {
        "image_id": image_id,
        "staging_path": str(
            image_staging_path_for(image_id, doc_uuid, _staging_dir())
        ),
        "alt": "a diagram",
        "source_url": "https://cdn.example/img.png",
        "mime": "image/png",
    }
    meta.update(overrides)
    return meta


def _make_image_service(
    *, images_enabled: bool,
) -> tuple[Any, Any, FieldCipher, Any]:
    """Service with an in-memory bank + the resolved config's
    knowledge_images_enabled set to the requested posture."""
    service, bank, cipher, audit = _make_service_with_bank()
    service._resolved_config = _make_resolved_config(
        knowledge_images_enabled=images_enabled
    )
    return service, bank, cipher, audit


# ---------------------------------------------------------------------------
# 1. DORMANT — the load-bearing test
# ---------------------------------------------------------------------------


class TestImagesDormantOnSubmit:
    def test_dormant_never_stores_and_sweeps_blobs(self) -> None:
        """knowledge_images_enabled=False + a submit carrying image metadata:
        bank.store_image is NEVER called, the image staging blobs are DELETED
        (swept, no orphans), and the doc still submits fine.  THE load-bearing
        dormant lock."""
        service, bank, cipher, _audit = _make_image_service(images_enabled=False)
        doc_uuid = str(uuid.uuid4())
        _stage_article(cipher, doc_uuid, _CONTENT)

        img_a, img_b = uuid.uuid4().hex, uuid.uuid4().hex
        blob_a = _stage_image(cipher, _PNG_BYTES, img_a, doc_uuid)
        blob_b = _stage_image(cipher, _JPEG_BYTES, img_b, doc_uuid)
        assert blob_a.exists() and blob_b.exists()

        frame = _submit_frame(
            doc_uuid,
            _CONTENT,
            images=(
                _image_meta(img_a, doc_uuid, mime="image/png"),
                _image_meta(img_b, doc_uuid, mime="image/jpeg"),
            ),
        )
        transport = _FakeTransport(frame)
        with patch.object(
            bank,
            "store_image",
            side_effect=AssertionError("store_image must NOT run when dormant"),
        ) as spy:
            assert service._handle_connection(transport) is True

        # store_image was never reached.
        assert spy.call_count == 0
        # The doc still submitted fine.
        result = _last_result(transport)
        assert result["ok"] is True
        assert result["state"] == "pending"
        assert bank.image_count() == 0  # nothing stored
        # The staging blobs were swept (no orphans left behind).
        assert not blob_a.exists()
        assert not blob_b.exists()


# ---------------------------------------------------------------------------
# 2. ENABLED + pending doc → store each image, then sweep
# ---------------------------------------------------------------------------


class TestImagesEnabledOnPending:
    def test_enabled_stores_each_image_and_sweeps_blobs(self) -> None:
        """knowledge_images_enabled=True + a fresh pending row: bank.store_image
        is called once per image with the decrypted bytes + the right metadata,
        and the staging blobs are deleted after."""
        service, bank, cipher, _audit = _make_image_service(images_enabled=True)
        doc_uuid = str(uuid.uuid4())
        _stage_article(cipher, doc_uuid, _CONTENT)

        img_a, img_b = uuid.uuid4().hex, uuid.uuid4().hex
        blob_a = _stage_image(cipher, _PNG_BYTES, img_a, doc_uuid)
        blob_b = _stage_image(cipher, _JPEG_BYTES, img_b, doc_uuid)

        frame = _submit_frame(
            doc_uuid,
            _CONTENT,
            images=(
                _image_meta(
                    img_a, doc_uuid, alt="alt A",
                    source_url="https://cdn.example/a.png", mime="image/png",
                ),
                _image_meta(
                    img_b, doc_uuid, alt="alt B",
                    source_url="https://cdn.example/b.jpg", mime="image/jpeg",
                ),
            ),
        )
        transport = _FakeTransport(frame)
        assert service._handle_connection(transport) is True
        assert _last_result(transport)["ok"] is True

        # Both images persisted with the round-tripped bytes + metadata.
        images = bank.get_images_for_doc(doc_uuid)
        assert len(images) == 2
        by_id = {img.image_id: img for img in images}
        assert by_id[img_a].data == _PNG_BYTES
        assert by_id[img_a].mime == "image/png"
        assert by_id[img_a].alt == "alt A"
        assert by_id[img_a].source_url == "https://cdn.example/a.png"
        assert by_id[img_a].approval_state == "pending"
        assert by_id[img_b].data == _JPEG_BYTES
        assert by_id[img_b].mime == "image/jpeg"
        # The staging blobs were deleted after the row persisted.
        assert not blob_a.exists()
        assert not blob_b.exists()

    def test_enabled_store_image_called_with_expected_args(self) -> None:
        """A spy on store_image captures the exact call shape for one image."""
        service, bank, cipher, _audit = _make_image_service(images_enabled=True)
        doc_uuid = str(uuid.uuid4())
        _stage_article(cipher, doc_uuid, _CONTENT)
        img = uuid.uuid4().hex
        _stage_image(cipher, _PNG_BYTES, img, doc_uuid)

        frame = _submit_frame(
            doc_uuid,
            _CONTENT,
            images=(
                _image_meta(
                    img, doc_uuid, alt="the alt text",
                    source_url="https://cdn.example/p.png", mime="image/png",
                ),
            ),
        )
        real_store = bank.store_image
        seen: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def _spy(*args: Any, **kwargs: Any) -> Any:
            seen.append((args, kwargs))
            return real_store(*args, **kwargs)

        with patch.object(bank, "store_image", side_effect=_spy):
            service._handle_connection(_FakeTransport(frame))

        assert len(seen) == 1
        args, kwargs = seen[0]
        # The handler passes the image_id, doc_uuid, decrypted bytes, mime, alt,
        # source_url positionally + approval_state="pending" as a kwarg.
        assert args[0] == img
        assert args[1] == doc_uuid
        assert args[2] == _PNG_BYTES
        assert args[3] == "image/png"
        assert args[4] == "the alt text"
        assert args[5] == "https://cdn.example/p.png"
        assert kwargs.get("approval_state") == "pending"


# ---------------------------------------------------------------------------
# 3. already_ingested → store NOTHING, sweep blobs
# ---------------------------------------------------------------------------


class TestImagesOnAlreadyIngested:
    def test_already_ingested_stores_no_images_and_sweeps(self) -> None:
        """Even with images enabled, a dedup already_ingested verdict stores NO
        images (no new row) and sweeps the staging blobs."""
        service, bank, cipher, _audit = _make_image_service(images_enabled=True)

        # First submit + approve the source so a re-submit dedups.
        first_uuid = str(uuid.uuid4())
        _stage_article(cipher, first_uuid, _CONTENT)
        service._handle_connection(_FakeTransport(_submit_frame(first_uuid, _CONTENT)))
        bank.approve(first_uuid)
        assert bank.image_count() == 0

        # Re-submit the SAME source (same source_ref) → already_ingested.
        second_uuid = str(uuid.uuid4())
        _stage_article(cipher, second_uuid, _CONTENT)
        img = uuid.uuid4().hex
        blob = _stage_image(cipher, _PNG_BYTES, img, second_uuid)

        frame = _submit_frame(
            second_uuid, _CONTENT, images=(_image_meta(img, second_uuid),)
        )
        transport = _FakeTransport(frame)
        with patch.object(
            bank,
            "store_image",
            side_effect=AssertionError("no image stored on already_ingested"),
        ) as spy:
            service._handle_connection(transport)

        result = _last_result(transport)
        assert result["ok"] is True
        assert result["state"] == "already_ingested"
        assert spy.call_count == 0
        assert bank.image_count() == 0  # no image row minted
        assert not blob.exists()  # swept anyway — no orphan


# ---------------------------------------------------------------------------
# 4. Fail-safe — one bad image never fails the whole submit
# ---------------------------------------------------------------------------


class TestImageStoreFailSafe:
    def test_missing_blob_image_does_not_fail_submit(self) -> None:
        """One image whose staging blob is missing does NOT fail the submit —
        the doc result is still ok; other images still process."""
        service, bank, cipher, _audit = _make_image_service(images_enabled=True)
        doc_uuid = str(uuid.uuid4())
        _stage_article(cipher, doc_uuid, _CONTENT)

        good = uuid.uuid4().hex
        missing = uuid.uuid4().hex  # never staged → read_staged_image raises
        _stage_image(cipher, _PNG_BYTES, good, doc_uuid)

        frame = _submit_frame(
            doc_uuid,
            _CONTENT,
            images=(
                _image_meta(missing, doc_uuid, alt="missing"),
                _image_meta(good, doc_uuid, alt="good"),
            ),
        )
        transport = _FakeTransport(frame)
        assert service._handle_connection(transport) is True

        result = _last_result(transport)
        assert result["ok"] is True  # the doc submitted despite the bad image
        assert result["state"] == "pending"
        # Only the good image persisted; the missing one was dropped, not fatal.
        images = bank.get_images_for_doc(doc_uuid)
        assert {img.image_id for img in images} == {good}

    def test_corrupt_blob_image_does_not_fail_submit(self) -> None:
        """An image whose staging blob is corrupt (decrypt fails) is dropped,
        the submit still succeeds, and a good sibling still stores."""
        service, bank, cipher, _audit = _make_image_service(images_enabled=True)
        doc_uuid = str(uuid.uuid4())
        _stage_article(cipher, doc_uuid, _CONTENT)

        good = uuid.uuid4().hex
        corrupt = uuid.uuid4().hex
        _stage_image(cipher, _PNG_BYTES, good, doc_uuid)
        corrupt_blob = _stage_image(cipher, _JPEG_BYTES, corrupt, doc_uuid)
        # Tamper the GCM tag so the AAD-bound decrypt fails on read. XOR the last
        # byte to GUARANTEE a change — a naive "replace with \x00" is a no-op
        # ~1/256 of the time (when the tag byte is already \x00), which made this
        # lock flaky across the full suite.
        _tampered = bytearray(corrupt_blob.read_bytes())
        _tampered[-1] ^= 0xFF
        corrupt_blob.write_bytes(bytes(_tampered))

        frame = _submit_frame(
            doc_uuid,
            _CONTENT,
            images=(
                _image_meta(corrupt, doc_uuid, alt="corrupt"),
                _image_meta(good, doc_uuid, alt="good"),
            ),
        )
        transport = _FakeTransport(frame)
        assert service._handle_connection(transport) is True
        assert _last_result(transport)["ok"] is True
        images = bank.get_images_for_doc(doc_uuid)
        assert {img.image_id for img in images} == {good}
        # The corrupt blob is swept too (finally-delete), no orphan.
        assert not corrupt_blob.exists()


# ---------------------------------------------------------------------------
# 5. Staging round-trip sanity (the test scaffolding itself)
# ---------------------------------------------------------------------------


class TestStagingRoundTripSanity:
    def test_written_blob_reads_back_under_same_cipher(self) -> None:
        """Sanity that the test's own staging write/read mirrors the handler's
        (same cipher, canonical path) so the dormant/enabled assertions are
        exercising the real path, not a stub."""
        _service, _bank, cipher, _audit = _make_image_service(images_enabled=True)
        doc_uuid = str(uuid.uuid4())
        img = uuid.uuid4().hex
        path = _stage_image(cipher, _PNG_BYTES, img, doc_uuid)
        assert path.exists()
        assert path.read_bytes() != _PNG_BYTES  # encrypted on disk
        got = read_staged_image(img, doc_uuid, cipher, _staging_dir())
        assert got == _PNG_BYTES
