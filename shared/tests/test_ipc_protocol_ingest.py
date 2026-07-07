"""
Tests for the knowledge-bank ingest IPC message types (UC-002/UC-003, #655).

INGEST_SUBMIT / INGEST_DECISION / INGEST_RESULT follow the existing
MessageType + encode_*/decode_* pattern.  Size discipline is the load-bearing
property: cleaned content rides the encrypted staging file, NEVER the frame —
a typical submit envelope must sit far under the 64 KB cap, and the generic
encode cap still fires on abuse.
"""

from __future__ import annotations

import pytest

from shared.ipc.protocol import (
    DEFAULT_MAX_MESSAGE_BYTES,
    MessageFramer,
    MessageType,
)


@pytest.fixture()
def framer() -> MessageFramer:
    return MessageFramer()


_SUBMIT_KWARGS = dict(
    doc_uuid="0c9adf1e-66cb-4d8e-9b3e-9a4ff1f0a111",
    source_type="url",
    source_ref="https://example.org/articles/turbo-engines",
    staging_path=r"C:\\Users\\op\\AppData\\Local\\BlarAI\\ingest_staging\\0c9adf1e-66cb-4d8e-9b3e-9a4ff1f0a111.bin",
    content_sha256="a" * 64,
    title="How turbochargers work",
    byline="A. Writer",
    published_date="2026-06-01",
    word_count=950,
    cleaner_version="cleaner-v1",
)


class TestMessageTypes:
    def test_ingest_types_exist(self) -> None:
        assert MessageType.INGEST_SUBMIT.value == "INGEST_SUBMIT"
        assert MessageType.INGEST_DECISION.value == "INGEST_DECISION"
        assert MessageType.INGEST_RESULT.value == "INGEST_RESULT"

    def test_ingest_types_decode_round_trip(self, framer: MessageFramer) -> None:
        raw = framer.encode(MessageType.INGEST_SUBMIT, {"doc_uuid": "x"}, "r1")
        msg_type, request_id, payload = framer.decode(raw)
        assert msg_type is MessageType.INGEST_SUBMIT
        assert request_id == "r1"
        assert payload == {"doc_uuid": "x"}


class TestIngestSubmit:
    def test_round_trip(self, framer: MessageFramer) -> None:
        raw = framer.encode_ingest_submit(request_id="req-7", **_SUBMIT_KWARGS)
        msg_type, request_id, payload = framer.decode(raw)
        assert msg_type is MessageType.INGEST_SUBMIT
        assert request_id == "req-7"
        for key, value in _SUBMIT_KWARGS.items():
            assert payload[key] == value

    def test_prior_content_sha256_defaults_empty(self, framer: MessageFramer) -> None:
        """The edit-provenance field is OPTIONAL — a normal submit omits it
        (empty), so the AO records no edit (#663)."""
        _msg, _rid, payload = framer.decode(
            framer.encode_ingest_submit(**_SUBMIT_KWARGS)
        )
        assert payload["prior_content_sha256"] == ""

    def test_prior_content_sha256_round_trips(self, framer: MessageFramer) -> None:
        """An edited re-submit carries the cleaner's ORIGINAL digest so the AO
        records edited=1 + the keyed cleaner digest in the audit chain (#663)."""
        raw = framer.encode_ingest_submit(
            prior_content_sha256="b" * 64, **_SUBMIT_KWARGS
        )
        _msg, _rid, payload = framer.decode(raw)
        assert payload["prior_content_sha256"] == "b" * 64

    def test_content_never_rides_the_frame(self, framer: MessageFramer) -> None:
        """The submit encoder has NO content parameter — the staging file is
        the only content channel (size discipline by construction)."""
        import inspect

        params = inspect.signature(framer.encode_ingest_submit).parameters
        assert "content" not in params

    def test_typical_submit_is_small(self, framer: MessageFramer) -> None:
        raw = framer.encode_ingest_submit(**_SUBMIT_KWARGS)
        assert len(raw) < 4096  # far under the 64 KB envelope

    def test_oversized_metadata_raises_at_encode(
        self, framer: MessageFramer
    ) -> None:
        kwargs = dict(_SUBMIT_KWARGS)
        kwargs["title"] = "x" * (DEFAULT_MAX_MESSAGE_BYTES + 1)
        with pytest.raises(ValueError):
            framer.encode_ingest_submit(**kwargs)

    @pytest.mark.parametrize("bad", ["", "   "])
    def test_missing_content_sha256_fails_closed_at_encode(
        self, framer: MessageFramer, bad: str
    ) -> None:
        """content_sha256 is REQUIRED (#655 review FIX 6): the AO-side
        staged-content cross-check is mandatory, so a frame without the hash
        must never be encodable in the first place."""
        kwargs = dict(_SUBMIT_KWARGS)
        kwargs["content_sha256"] = bad
        with pytest.raises(ValueError, match="content_sha256"):
            framer.encode_ingest_submit(**kwargs)


_IMAGE_RECORDS = (
    {
        "image_id": "ab" * 16,  # uuid4().hex shape
        "staging_path": r"C:\\Users\\op\\AppData\\Local\\BlarAI\\ingest_staging\\0c9adf1e-66cb-4d8e-9b3e-9a4ff1f0a111__abababababababababababababababab.bin",
        "alt": "Turbocharger cutaway diagram",
        "source_url": "https://example.org/img/turbo.png",
        "mime": "image/png",
    },
    {
        "image_id": "cd" * 16,
        "staging_path": r"C:\\path\\0c9adf1e-66cb-4d8e-9b3e-9a4ff1f0a111__cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd.bin",
        "alt": "Compressor wheel",
        "source_url": "https://example.org/img/wheel.jpg",
        "mime": "image/jpeg",
    },
)


class TestIngestSubmitImages:
    """UC-003 Workstream B — the OPTIONAL additive display-only image manifest.

    METADATA ONLY on the frame; bytes ride the encrypted image_staging blob.
    Locked here: absent-field back-compat (existing frames byte-identical),
    round-trip of the five pinned keys, normalisation/projection of stray keys
    (no bytes can ride), and that the manifest only attaches when non-empty.
    """

    def test_absent_images_field_decodes(self, framer: MessageFramer) -> None:
        """A submit with no images (the default) carries NO images key — an
        un-changed pre-Workstream-B frame stays byte-compatible."""
        _msg, _rid, payload = framer.decode(
            framer.encode_ingest_submit(**_SUBMIT_KWARGS)
        )
        assert "images" not in payload

    def test_no_image_submit_byte_identical_to_explicit_empty(
        self, framer: MessageFramer
    ) -> None:
        """Passing ``images=()`` is identical to omitting it — additive default
        leaves the wire bytes unchanged (mirrors prior_content_sha256's shape)."""
        without = framer.encode_ingest_submit(**_SUBMIT_KWARGS)
        explicit_empty = framer.encode_ingest_submit(images=(), **_SUBMIT_KWARGS)
        assert without == explicit_empty

    def test_images_round_trip(self, framer: MessageFramer) -> None:
        raw = framer.encode_ingest_submit(
            images=_IMAGE_RECORDS, request_id="req-img", **_SUBMIT_KWARGS
        )
        msg_type, request_id, payload = framer.decode(raw)
        assert msg_type is MessageType.INGEST_SUBMIT
        assert request_id == "req-img"
        # JSON round-trips the tuple as a list of dicts.
        assert payload["images"] == [dict(r) for r in _IMAGE_RECORDS]

    def test_each_record_is_exactly_the_pinned_keys(
        self, framer: MessageFramer
    ) -> None:
        _msg, _rid, payload = framer.decode(
            framer.encode_ingest_submit(images=_IMAGE_RECORDS, **_SUBMIT_KWARGS)
        )
        for record in payload["images"]:
            assert set(record.keys()) == set(MessageFramer.INGEST_IMAGE_KEYS)

    def test_stray_keys_and_bytes_are_dropped(self, framer: MessageFramer) -> None:
        """A record carrying an extra key (e.g. an accidental bytes blob) is
        PROJECTED onto the five pinned keys — image bytes cannot ride the frame
        by construction."""
        rogue = {
            "image_id": "ef" * 16,
            "staging_path": "p",
            "alt": "a",
            "source_url": "u",
            "mime": "image/png",
            "data": "should-never-ride",  # stray key — must be dropped
        }
        _msg, _rid, payload = framer.decode(
            framer.encode_ingest_submit(images=(rogue,), **_SUBMIT_KWARGS)
        )
        assert "data" not in payload["images"][0]
        assert set(payload["images"][0].keys()) == set(
            MessageFramer.INGEST_IMAGE_KEYS
        )

    def test_missing_record_keys_coerce_to_empty_string(
        self, framer: MessageFramer
    ) -> None:
        sparse = {"image_id": "ab" * 16}  # only one key supplied
        _msg, _rid, payload = framer.decode(
            framer.encode_ingest_submit(images=(sparse,), **_SUBMIT_KWARGS)
        )
        record = payload["images"][0]
        assert record["image_id"] == "ab" * 16
        assert record["alt"] == ""
        assert record["mime"] == ""

    def test_values_coerced_to_str(self, framer: MessageFramer) -> None:
        """Non-string record values are stringified so the JSON envelope is
        deterministic and a numeric/None value never reaches the AO as a
        non-string label."""
        weird = {
            "image_id": "ab" * 16,
            "staging_path": "p",
            "alt": 12345,  # int → str
            "source_url": "u",
            "mime": "image/png",
        }
        _msg, _rid, payload = framer.decode(
            framer.encode_ingest_submit(images=(weird,), **_SUBMIT_KWARGS)
        )
        assert payload["images"][0]["alt"] == "12345"


class TestIngestDecision:
    @pytest.mark.parametrize("decision", ["approve", "reject"])
    def test_round_trip(self, framer: MessageFramer, decision: str) -> None:
        raw = framer.encode_ingest_decision(
            doc_uuid="d-1", decision=decision, request_id="r2"
        )
        msg_type, request_id, payload = framer.decode(raw)
        assert msg_type is MessageType.INGEST_DECISION
        assert payload == {"doc_uuid": "d-1", "decision": decision}

    @pytest.mark.parametrize("bad", ["", "APPROVE", "maybe", "delete"])
    def test_invalid_decision_fails_closed_at_encode(
        self, framer: MessageFramer, bad: str
    ) -> None:
        with pytest.raises(ValueError):
            framer.encode_ingest_decision(doc_uuid="d-1", decision=bad)


class TestIngestResult:
    def test_round_trip_success(self, framer: MessageFramer) -> None:
        raw = framer.encode_ingest_result(
            ok=True,
            doc_uuid="d-9",
            state="approved",
            chunk_count=3,
            request_id="r3",
        )
        result = framer.decode_ingest_result(raw)
        assert result == {
            "ok": True,
            "doc_uuid": "d-9",
            "state": "approved",
            "chunk_count": 3,
            "error_code": "",
            "message": "",
        }

    def test_round_trip_error(self, framer: MessageFramer) -> None:
        raw = framer.encode_ingest_result(
            ok=False,
            doc_uuid="d-9",
            state="error",
            error_code="KNOWLEDGE_BANK_DISABLED",
            message="bank off",
        )
        result = framer.decode_ingest_result(raw)
        assert result["ok"] is False
        assert result["state"] == "error"
        assert result["error_code"] == "KNOWLEDGE_BANK_DISABLED"
        assert result["message"] == "bank off"

    def test_decode_wrong_type_raises(self, framer: MessageFramer) -> None:
        raw = framer.encode_heartbeat("r")
        with pytest.raises(ValueError):
            framer.decode_ingest_result(raw)

    def test_decode_coerces_missing_fields(self, framer: MessageFramer) -> None:
        raw = framer.encode(MessageType.INGEST_RESULT, {}, "r")
        result = framer.decode_ingest_result(raw)
        assert result["ok"] is False  # absent ok decodes fail-closed
        assert result["state"] == "error"
