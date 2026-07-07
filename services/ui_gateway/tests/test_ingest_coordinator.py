"""Tests for the gateway-side ingest coordinator (#655 Stage B).

Covers: command parsing (all three /ingest modes + refusals), the coordinator
with a MOCKED cleaner pipeline (clean + quarantined + cleaner-unavailable +
encrypted staging + INGEST_SUBMIT payload shape including the REQUIRED
content_sha256), the one-pending-slot state machine, and the bare-URL
disambiguation helpers.  Model-free; no AO; no real %LOCALAPPDATA% (staging
dirs are tmp_path-injected and the root conftest redirects LOCALAPPDATA
besides).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from services.ui_gateway.src.ingest_coordinator import (
    CleanerUnavailableError,
    DEFAULT_INGEST_MAX_BYTES,
    EGRESS_ACTIVATION_GATE,
    IngestCommand,
    IngestCoordinator,
    bare_url_nudge,
    is_bare_url,
    parse_ingest_command,
)
from shared.ipc.parse_channel import PARSE_BODY_MAX_BYTES, ParseResponse
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.ingest_staging import (
    CIPHER_ENVELOPE_OVERHEAD_BYTES,
    DEFAULT_STAGING_MAX_BYTES,
    read_staged,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeCleanResult:
    """Shape-faithful stand-in for services.cleaner.src.pipeline.CleanResult."""

    status: str = "clean"
    text: str = "The cleaned article body. Multiple sentences of real signal."
    title: str | None = "A Real Headline"
    byline: str | None = None
    published_date: str | None = "2026-06-01"
    word_count: int = 9
    confidence: float = 0.93
    reasons: tuple[str, ...] = ()
    cleaner_version: str = "1.0.0"
    source_format: str = "text"


@dataclass
class FakePipeline:
    """Injectable cleaner pipeline returning canned results + recording calls."""

    result: Any = field(default_factory=FakeCleanResult)
    text_calls: list[str] = field(default_factory=list)
    html_calls: list[str] = field(default_factory=list)

    def clean_text(self, raw_text: str) -> Any:
        self.text_calls.append(raw_text)
        return self.result

    def clean_html(self, raw_html: str, *, source_url: str | None = None) -> Any:
        self.html_calls.append(raw_html)
        return self.result

    def loader(self):
        return self.clean_text, self.clean_html


class FakeTransportCall:
    """Captures encoded ingest frames; replies from a scripted response list."""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.sent: list[bytes] = []
        self._responses = list(responses or [])

    async def __call__(self, message: bytes) -> dict[str, Any]:
        self.sent.append(message)
        if self._responses:
            return self._responses.pop(0)
        # Default: a successful pending submit echoing the sent doc_uuid.
        payload = _envelope(message)["payload"]
        return {
            "ok": True,
            "doc_uuid": payload.get("doc_uuid", ""),
            "state": "pending",
            "chunk_count": 0,
            "error_code": "",
            "message": "",
        }


def _envelope(message: bytes) -> dict[str, Any]:
    return json.loads(message.decode("utf-8"))


def _ok_decision(doc_uuid: str, state: str, chunk_count: int = 0) -> dict[str, Any]:
    return {
        "ok": True,
        "doc_uuid": doc_uuid,
        "state": state,
        "chunk_count": chunk_count,
        "error_code": "",
        "message": "",
    }


def _cipher() -> FieldCipher:
    return FieldCipher(derive_subkeys(b"\x07" * 32))


def _make_coordinator(
    tmp_path: Path,
    *,
    pipeline: FakePipeline | None = None,
    transport: FakeTransportCall | None = None,
    cipher: FieldCipher | None = None,
    max_ingest_bytes: int = DEFAULT_INGEST_MAX_BYTES,
    pipeline_loader=None,
    url_fetch_fn=None,
    guest_parse_available_fn=None,
    guest_parse_fn=None,
) -> tuple[IngestCoordinator, FakePipeline, FakeTransportCall, Path, Path]:
    pipeline = pipeline or FakePipeline()
    transport = transport or FakeTransportCall()
    resolved_cipher = cipher if cipher is not None else _cipher()
    staging_dir = tmp_path / "staging"
    userdata_dir = tmp_path / "userdata"
    userdata_dir.mkdir(parents=True, exist_ok=True)
    coordinator = IngestCoordinator(
        transport_call=transport,
        cipher_provider=lambda: resolved_cipher,
        pipeline_loader=pipeline_loader or pipeline.loader,
        staging_dir_provider=lambda: staging_dir,
        max_ingest_bytes=max_ingest_bytes,
        userdata_dir=userdata_dir,
        url_fetch_fn=url_fetch_fn,
        guest_parse_available_fn=guest_parse_available_fn,
        guest_parse_fn=guest_parse_fn,
    )
    return coordinator, pipeline, transport, staging_dir, userdata_dir


def _run(coro):
    return asyncio.run(coro)


def _ingest(coordinator: IngestCoordinator, arg: str, session: str = "sess-1") -> str:
    return _run(
        coordinator.handle_command(session, IngestCommand(verb="ingest", arg=arg))
    )


def _decide(coordinator: IngestCoordinator, verb: str, session: str = "sess-1") -> str:
    return _run(
        coordinator.handle_command(session, IngestCommand(verb=verb, arg=""))
    )


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------


class TestParseIngestCommand:
    def test_ingest_with_argument(self) -> None:
        cmd = parse_ingest_command("/ingest some pasted text")
        assert cmd == IngestCommand(verb="ingest", arg="some pasted text")

    def test_ingest_bare(self) -> None:
        assert parse_ingest_command("/ingest") == IngestCommand("ingest", "")

    def test_case_insensitive_verb(self) -> None:
        cmd = parse_ingest_command("/Ingest Hello")
        assert cmd is not None and cmd.verb == "ingest" and cmd.arg == "Hello"

    def test_newline_after_verb_is_a_separator(self) -> None:
        cmd = parse_ingest_command("/ingest\nMulti-line pasted article")
        assert cmd is not None
        assert cmd.arg == "Multi-line pasted article"

    def test_approve_and_reject(self) -> None:
        assert parse_ingest_command("/approve") == IngestCommand("approve", "")
        assert parse_ingest_command("/reject") == IngestCommand("reject", "")
        assert parse_ingest_command("  /approve  ") == IngestCommand("approve", "")

    def test_prefix_without_separator_is_not_a_command(self) -> None:
        assert parse_ingest_command("/ingestfoo bar") is None
        assert parse_ingest_command("/approved") is None
        assert parse_ingest_command("/rejection letter") is None

    def test_non_commands_return_none(self) -> None:
        assert parse_ingest_command("hello world") is None
        assert parse_ingest_command("/load notes.txt") is None
        assert parse_ingest_command("") is None


class TestBareUrlDetection:
    def test_bare_url_matches(self) -> None:
        assert is_bare_url("https://example.com/article") is True
        assert is_bare_url("http://example.com") is True
        assert is_bare_url("  https://example.com/a?b=c#d  ") is True
        assert is_bare_url("HTTPS://EXAMPLE.COM/X") is True

    def test_url_in_sentence_does_not_match(self) -> None:
        assert is_bare_url("Check https://example.com please") is False
        assert is_bare_url("https://example.com is interesting") is False

    def test_non_urls_do_not_match(self) -> None:
        assert is_bare_url("hello") is False
        assert is_bare_url("/ingest https://example.com") is False
        assert is_bare_url("ftp://example.com") is False
        assert is_bare_url("") is False

    def test_nudge_offers_ingest_command(self) -> None:
        nudge = bare_url_nudge("https://example.com/story")
        assert "/ingest https://example.com/story" in nudge
        assert "knowledge bank" in nudge


# ---------------------------------------------------------------------------
# /ingest — argument classification + acquisition
# ---------------------------------------------------------------------------


class TestIngestModes:
    def test_empty_argument_returns_usage(self, tmp_path: Path) -> None:
        coordinator, _, transport, _, _ = _make_coordinator(tmp_path)
        reply = _ingest(coordinator, "")
        assert "Usage:" in reply
        assert EGRESS_ACTIVATION_GATE in reply  # usage names the go-live gate
        assert transport.sent == []

    def test_url_mode_refuses_when_guest_parser_unavailable(
        self, tmp_path: Path
    ) -> None:
        fetch_calls: list = []

        def _fetch(url: str, purpose: str):
            fetch_calls.append((url, purpose))
            raise AssertionError("fetch must not run when the guest parser is down")

        coordinator, pipeline, transport, staging_dir, _ = _make_coordinator(
            tmp_path,
            guest_parse_available_fn=lambda: False,
            url_fetch_fn=_fetch,
        )
        reply = _ingest(coordinator, "https://example.com/article")
        assert "unavailable" in reply.lower()
        assert "paste" in reply.lower()  # points to the interim path
        # The capability gate fired BEFORE any fetch — nothing left the box.
        assert fetch_calls == []
        assert transport.sent == []
        assert pipeline.text_calls == [] and pipeline.html_calls == []
        assert not staging_dir.exists()
        assert coordinator.pending_for("sess-1") is None

    def test_http_url_also_gated_on_guest_parser(self, tmp_path: Path) -> None:
        coordinator, _, transport, _, _ = _make_coordinator(
            tmp_path, guest_parse_available_fn=lambda: False
        )
        reply = _ingest(coordinator, "HTTP://example.com/x")
        assert "unavailable" in reply.lower()
        assert transport.sent == []

    def test_paste_mode_uses_clean_text(self, tmp_path: Path) -> None:
        coordinator, pipeline, transport, _, _ = _make_coordinator(tmp_path)
        reply = _ingest(coordinator, "An article body pasted straight into chat.")
        assert pipeline.text_calls == ["An article body pasted straight into chat."]
        assert pipeline.html_calls == []
        assert len(transport.sent) == 1
        assert "Ingest preview" in reply

    def test_file_mode_userdata_text_uses_clean_text(self, tmp_path: Path) -> None:
        coordinator, pipeline, transport, _, userdata = _make_coordinator(tmp_path)
        (userdata / "notes.md").write_text("# markdown body", encoding="utf-8")
        _ingest(coordinator, "notes.md")
        assert pipeline.text_calls == ["# markdown body"]
        payload = _envelope(transport.sent[0])["payload"]
        assert payload["source_type"] == "file"
        assert payload["source_ref"].endswith("notes.md")

    def test_file_mode_html_uses_clean_html(self, tmp_path: Path) -> None:
        coordinator, pipeline, transport, _, userdata = _make_coordinator(tmp_path)
        (userdata / "saved.html").write_text("<html>x</html>", encoding="utf-8")
        _ingest(coordinator, "saved.html")
        assert pipeline.html_calls == ["<html>x</html>"]
        assert pipeline.text_calls == []

    def test_file_mode_absolute_path(self, tmp_path: Path) -> None:
        coordinator, pipeline, transport, _, _ = _make_coordinator(tmp_path)
        outside = tmp_path / "elsewhere" / "doc.txt"
        outside.parent.mkdir(parents=True)
        outside.write_text("absolute path body", encoding="utf-8")
        _ingest(coordinator, str(outside))
        assert pipeline.text_calls == ["absolute path body"]
        payload = _envelope(transport.sent[0])["payload"]
        assert payload["source_type"] == "file"

    def test_absolute_path_missing_is_loud_not_paste(self, tmp_path: Path) -> None:
        coordinator, pipeline, transport, _, _ = _make_coordinator(tmp_path)
        missing = tmp_path / "nope" / "gone.txt"
        reply = _ingest(coordinator, str(missing))
        assert "file not found" in reply.lower()
        assert pipeline.text_calls == []  # never pasted the path string
        assert transport.sent == []

    def test_filename_token_missing_is_loud_not_paste(self, tmp_path: Path) -> None:
        coordinator, pipeline, transport, _, _ = _make_coordinator(tmp_path)
        reply = _ingest(coordinator, "ghost.txt")
        assert "file not found" in reply.lower()
        assert pipeline.text_calls == []
        assert transport.sent == []

    def test_unsupported_extension_refused(self, tmp_path: Path) -> None:
        coordinator, _, transport, _, userdata = _make_coordinator(tmp_path)
        (userdata / "doc.pdf").write_bytes(b"%PDF-fake")
        reply = _ingest(coordinator, str(userdata / "doc.pdf"))
        assert "unsupported file type" in reply.lower()
        assert ".pdf" in reply  # the named deferral is visible
        assert transport.sent == []

    def test_containment_escape_refused(self, tmp_path: Path) -> None:
        coordinator, _, transport, _, _ = _make_coordinator(tmp_path)
        (tmp_path / "secret.txt").write_text("outside userdata", encoding="utf-8")
        reply = _ingest(coordinator, "../secret.txt")
        assert "outside" in reply.lower()
        assert transport.sent == []

    def test_oversize_file_refused_before_read(self, tmp_path: Path) -> None:
        coordinator, pipeline, transport, _, userdata = _make_coordinator(
            tmp_path, max_ingest_bytes=64
        )
        (userdata / "big.txt").write_text("x" * 200, encoding="utf-8")
        reply = _ingest(coordinator, "big.txt")
        assert "cap" in reply.lower()
        assert pipeline.text_calls == []
        assert transport.sent == []

    def test_non_utf8_file_refused(self, tmp_path: Path) -> None:
        coordinator, _, transport, _, userdata = _make_coordinator(tmp_path)
        (userdata / "bin.txt").write_bytes(b"\xff\xfe\x00\x01binary")
        reply = _ingest(coordinator, "bin.txt")
        assert "utf-8" in reply.lower()
        assert transport.sent == []

    def test_multiword_text_is_paste_mode(self, tmp_path: Path) -> None:
        """Multi-word arguments are paste — even when a word looks like a file."""
        coordinator, pipeline, _, _, _ = _make_coordinator(tmp_path)
        _ingest(coordinator, "see notes.txt for details on the matter")
        assert pipeline.text_calls == ["see notes.txt for details on the matter"]


class TestUncPathRejection:
    """UNC/network paths are refused — air-gap posture (#655 review fix 2)."""

    def test_unc_path_refused_naming_air_gap(self, tmp_path: Path) -> None:
        coordinator, pipeline, transport, staging_dir, _ = _make_coordinator(tmp_path)
        reply = _ingest(coordinator, r"\\fileserver\share\doc.html")
        assert "UNC/network path" in reply
        assert "air-gapped" in reply
        # Never cleaned, staged, or submitted — and never read off-host.
        assert pipeline.text_calls == [] and pipeline.html_calls == []
        assert transport.sent == []
        assert not staging_dir.exists()

    def test_long_path_unc_form_refused(self, tmp_path: Path) -> None:
        coordinator, pipeline, transport, _, _ = _make_coordinator(tmp_path)
        reply = _ingest(coordinator, r"\\?\UNC\fileserver\share\doc.txt")
        assert "UNC/network path" in reply
        assert "air-gapped" in reply
        assert pipeline.text_calls == [] and pipeline.html_calls == []
        assert transport.sent == []

    def test_unc_refusal_never_falls_through_to_paste(self, tmp_path: Path) -> None:
        """A refused UNC path is FILE mode — the path string is never pasted."""
        coordinator, pipeline, _, _, _ = _make_coordinator(tmp_path)
        _ingest(coordinator, r"\\host\share\article.md")
        assert pipeline.text_calls == []  # the path string never became content

    def test_local_absolute_path_still_accepted(self, tmp_path: Path) -> None:
        """LOCAL absolute paths remain the deliberate operator convenience."""
        coordinator, pipeline, transport, _, _ = _make_coordinator(tmp_path)
        local = tmp_path / "local" / "doc.txt"
        local.parent.mkdir(parents=True)
        local.write_text("local absolute body", encoding="utf-8")
        reply = _ingest(coordinator, str(local))
        assert "Ingest preview" in reply
        assert pipeline.text_calls == ["local absolute body"]
        assert len(transport.sent) == 1


class TestCipherEnvelopeByteCapSeam:
    """The gateway plaintext cap = staging cap minus the AES-GCM envelope
    (#655 review fix 1): plaintext that passes the gateway must always
    produce a staged ciphertext within the AO's unchanged Stage-A read cap."""

    def test_envelope_overhead_is_derived_not_magic(self) -> None:
        # version(1) + nonce(12) + tag(16) — derived from the field_cipher
        # format constants, locked here so a format change surfaces loudly.
        assert CIPHER_ENVELOPE_OVERHEAD_BYTES == 29

    def test_plaintext_at_effective_cap_stages_within_staging_cap(
        self, tmp_path: Path
    ) -> None:
        effective = DEFAULT_STAGING_MAX_BYTES - CIPHER_ENVELOPE_OVERHEAD_BYTES
        text = "x" * effective  # ASCII: 1 char == 1 byte
        coordinator, _, transport, staging_dir, _ = _make_coordinator(
            tmp_path, pipeline=FakePipeline(result=FakeCleanResult(text=text))
        )
        reply = _ingest(coordinator, "pasted seed text")
        assert "Ingest preview" in reply
        assert len(transport.sent) == 1
        payload = _envelope(transport.sent[0])["payload"]
        staged = staging_dir / f"{payload['doc_uuid']}.bin"
        assert staged.exists()
        # The REAL write_staged output: exactly plaintext + envelope, and
        # within the AO's ciphertext read cap (the Stage-A branch unmoved).
        size = staged.stat().st_size
        assert size == effective + CIPHER_ENVELOPE_OVERHEAD_BYTES
        assert size <= DEFAULT_STAGING_MAX_BYTES

    def test_plaintext_one_byte_over_effective_cap_refused_at_gateway(
        self, tmp_path: Path
    ) -> None:
        effective = DEFAULT_STAGING_MAX_BYTES - CIPHER_ENVELOPE_OVERHEAD_BYTES
        text = "x" * (effective + 1)
        coordinator, _, transport, staging_dir, _ = _make_coordinator(
            tmp_path, pipeline=FakePipeline(result=FakeCleanResult(text=text))
        )
        reply = _ingest(coordinator, "pasted seed text")
        assert "Ingest refused" in reply
        assert f"{effective:,}" in reply  # names the EFFECTIVE plaintext cap
        assert "envelope" in reply
        assert transport.sent == []  # refused at the gateway, not the AO
        assert not staging_dir.exists()

    def test_file_precheck_uses_effective_plaintext_cap(self, tmp_path: Path) -> None:
        staging_cap = 1024
        effective = staging_cap - CIPHER_ENVELOPE_OVERHEAD_BYTES
        coordinator, pipeline, transport, _, userdata = _make_coordinator(
            tmp_path, max_ingest_bytes=staging_cap
        )
        (userdata / "edge.txt").write_text("y" * (effective + 1), encoding="utf-8")
        reply = _ingest(coordinator, "edge.txt")
        assert "Ingest refused" in reply
        assert f"{effective:,}" in reply  # the precheck names the same cap
        assert pipeline.text_calls == []  # refused before the read
        assert transport.sent == []

    def test_file_at_effective_cap_passes_precheck(self, tmp_path: Path) -> None:
        staging_cap = 1024
        effective = staging_cap - CIPHER_ENVELOPE_OVERHEAD_BYTES
        text = "y" * effective
        coordinator, _, transport, staging_dir, userdata = _make_coordinator(
            tmp_path,
            pipeline=FakePipeline(result=FakeCleanResult(text=text)),
            max_ingest_bytes=staging_cap,
        )
        (userdata / "edge.txt").write_text(text, encoding="utf-8")
        reply = _ingest(coordinator, "edge.txt")
        assert "Ingest preview" in reply
        payload = _envelope(transport.sent[0])["payload"]
        staged = staging_dir / f"{payload['doc_uuid']}.bin"
        assert staged.stat().st_size <= staging_cap


# ---------------------------------------------------------------------------
# /ingest — cleaning, staging, submit payload
# ---------------------------------------------------------------------------


class TestIngestSubmitFlow:
    def test_submit_payload_shape_with_required_sha256(self, tmp_path: Path) -> None:
        result = FakeCleanResult(
            text="Cleaned body text.",
            title="Headline",
            byline="A. Writer",
            published_date="2026-05-30",
            word_count=3,
            cleaner_version="1.2.3",
        )
        coordinator, _, transport, staging_dir, _ = _make_coordinator(
            tmp_path, pipeline=FakePipeline(result=result)
        )
        _ingest(coordinator, "raw pasted text")

        envelope = _envelope(transport.sent[0])
        assert envelope["type"] == "INGEST_SUBMIT"
        payload = envelope["payload"]
        expected_sha = hashlib.sha256(b"Cleaned body text.").hexdigest()
        assert payload["content_sha256"] == expected_sha  # REQUIRED + correct
        assert payload["source_type"] == "paste"
        assert payload["source_ref"] == f"paste:{expected_sha}"
        assert payload["title"] == "Headline"
        assert payload["byline"] == "A. Writer"
        assert payload["published_date"] == "2026-05-30"
        assert payload["word_count"] == 3
        assert payload["cleaner_version"] == "1.2.3"
        assert payload["staging_path"].endswith(f"{payload['doc_uuid']}.bin")

    def test_staged_file_is_encrypted_and_round_trips(self, tmp_path: Path) -> None:
        plaintext = "Sensitive cleaned article content for the bank."
        cipher = _cipher()
        # The fake transport reports success but no real AO runs, so the
        # staged file persists (in production the AO deletes it after the
        # pending row lands) — inspect the on-disk blob directly.
        coordinator, _, transport, staging_dir, _ = _make_coordinator(
            tmp_path,
            pipeline=FakePipeline(result=FakeCleanResult(text=plaintext)),
            cipher=cipher,
        )
        _ingest(coordinator, plaintext)

        payload = _envelope(transport.sent[0])["payload"]
        doc_uuid = payload["doc_uuid"]
        staged = staging_dir / f"{doc_uuid}.bin"
        assert staged.exists()
        raw = staged.read_bytes()
        assert plaintext.encode("utf-8") not in raw  # never plaintext on disk
        decrypted = read_staged(doc_uuid, cipher, staging_dir)
        assert decrypted == plaintext

    def test_clean_preview_contains_metadata_and_text(self, tmp_path: Path) -> None:
        result = FakeCleanResult(text="Body here.", title="Headline")
        coordinator, _, _, _, _ = _make_coordinator(
            tmp_path, pipeline=FakePipeline(result=result)
        )
        reply = _ingest(coordinator, "pasted")
        assert "Headline" in reply
        assert "Body here." in reply
        assert "/approve" in reply and "/reject" in reply
        assert "QUARANTINED" not in reply

    def test_quarantined_preview_carries_reasons_and_text(self, tmp_path: Path) -> None:
        result = FakeCleanResult(
            status="quarantined",
            text="Suspicious but reviewable text.",
            reasons=("LOW_EXTRACTION_RATIO", "INJECTION_PATTERN_DETECTED"),
            confidence=0.21,
        )
        coordinator, _, transport, _, _ = _make_coordinator(
            tmp_path, pipeline=FakePipeline(result=result)
        )
        reply = _ingest(coordinator, "pasted suspicious text")
        # Quarantined results STILL submit (L0 pending IS the quarantine) and
        # still carry the cleaned text — approval is the override.
        assert len(transport.sent) == 1
        assert "QUARANTINED" in reply
        assert "LOW_EXTRACTION_RATIO" in reply
        assert "INJECTION_PATTERN_DETECTED" in reply
        assert "Suspicious but reviewable text." in reply
        assert coordinator.pending_for("sess-1") is not None

    def test_cleaner_unavailable_is_loud(self, tmp_path: Path) -> None:
        def _raising_loader():
            raise CleanerUnavailableError(
                "The cleaner pipeline (services.cleaner.src.pipeline) is not "
                "available — ingest cannot run without it (Fail-Closed)."
            )

        coordinator, _, transport, staging_dir, _ = _make_coordinator(
            tmp_path, pipeline_loader=_raising_loader
        )
        reply = _ingest(coordinator, "pasted text")
        assert "cleaner unavailable" in reply.lower()
        assert transport.sent == []
        assert not staging_dir.exists()
        assert coordinator.pending_for("sess-1") is None

    def test_pipeline_exception_is_loud_refusal(self, tmp_path: Path) -> None:
        pipeline = FakePipeline()

        def _broken_clean_text(raw: str):
            raise RuntimeError("boom inside the pipeline")

        coordinator, _, transport, _, _ = _make_coordinator(
            tmp_path,
            pipeline_loader=lambda: (_broken_clean_text, pipeline.clean_html),
        )
        reply = _ingest(coordinator, "pasted text")
        assert "cleaner pipeline raised" in reply.lower()
        assert transport.sent == []

    def test_empty_cleaned_text_refused(self, tmp_path: Path) -> None:
        coordinator, _, transport, _, _ = _make_coordinator(
            tmp_path, pipeline=FakePipeline(result=FakeCleanResult(text="   "))
        )
        reply = _ingest(coordinator, "pasted")
        assert "no text" in reply.lower()
        assert transport.sent == []

    def test_oversize_cleaned_text_refused_before_staging(self, tmp_path: Path) -> None:
        coordinator, _, transport, staging_dir, _ = _make_coordinator(
            tmp_path,
            pipeline=FakePipeline(result=FakeCleanResult(text="y" * 300)),
            max_ingest_bytes=128,
        )
        reply = _ingest(coordinator, "small input, big cleaner output")
        assert "cap" in reply.lower()
        assert transport.sent == []
        assert not staging_dir.exists()

    def test_missing_cipher_refuses_without_staging(self, tmp_path: Path) -> None:
        pipeline = FakePipeline()
        transport = FakeTransportCall()
        staging_dir = tmp_path / "staging"
        coordinator = IngestCoordinator(
            transport_call=transport,
            cipher_provider=lambda: None,  # plaintext store / stub mode
            pipeline_loader=pipeline.loader,
            staging_dir_provider=lambda: staging_dir,
            userdata_dir=tmp_path / "userdata",
        )
        reply = _ingest(coordinator, "pasted text")
        assert "cipher is unavailable" in reply.lower()
        assert transport.sent == []
        assert not staging_dir.exists()

    def test_ao_error_surfaces_and_cleans_staging(self, tmp_path: Path) -> None:
        transport = FakeTransportCall(responses=[{
            "ok": False, "doc_uuid": "", "state": "error", "chunk_count": 0,
            "error_code": "KNOWLEDGE_BANK_DISABLED",
            "message": "The knowledge bank is disabled.",
        }])
        coordinator, _, transport, staging_dir, _ = _make_coordinator(
            tmp_path, transport=transport
        )
        reply = _ingest(coordinator, "pasted text")
        assert "KNOWLEDGE_BANK_DISABLED" in reply
        assert "disabled" in reply
        assert coordinator.pending_for("sess-1") is None
        # The orphaned staging file was removed (fail-safe cleanup).
        assert list(staging_dir.glob("*.bin")) == []

    def test_already_ingested_takes_no_slot(self, tmp_path: Path) -> None:
        transport = FakeTransportCall(responses=[{
            "ok": True, "doc_uuid": "11111111-2222-3333-4444-555555555555",
            "state": "already_ingested", "chunk_count": 0,
            "error_code": "", "message": "",
        }])
        coordinator, _, _, _, _ = _make_coordinator(tmp_path, transport=transport)
        reply = _ingest(coordinator, "pasted text")
        assert "already in the knowledge bank" in reply
        assert coordinator.pending_for("sess-1") is None


# ---------------------------------------------------------------------------
# Pending-slot state machine
# ---------------------------------------------------------------------------


class TestPendingSlot:
    def test_second_ingest_refused_naming_pending_doc(self, tmp_path: Path) -> None:
        coordinator, _, transport, _, _ = _make_coordinator(tmp_path)
        _ingest(coordinator, "first article text")
        pending = coordinator.pending_for("sess-1")
        assert pending is not None

        reply = _ingest(coordinator, "second article text")
        assert "already pending" in reply
        assert pending.label in reply  # names the pending doc
        assert pending.doc_uuid[:8] in reply
        assert len(transport.sent) == 1  # the second never reached the AO

    def test_sessions_are_independent(self, tmp_path: Path) -> None:
        coordinator, _, _, _, _ = _make_coordinator(tmp_path)
        _ingest(coordinator, "article for session one", session="sess-1")
        reply = _ingest(coordinator, "article for session two", session="sess-2")
        assert "Ingest preview" in reply  # not refused — per-session slots
        assert coordinator.pending_for("sess-1") is not None
        assert coordinator.pending_for("sess-2") is not None

    def test_approve_sends_decision_and_clears_slot(self, tmp_path: Path) -> None:
        coordinator, _, transport, _, _ = _make_coordinator(tmp_path)
        _ingest(coordinator, "article text")
        doc_uuid = coordinator.pending_for("sess-1").doc_uuid

        transport._responses = [_ok_decision(doc_uuid, "approved", chunk_count=4)]
        reply = _decide(coordinator, "approve")

        envelope = _envelope(transport.sent[1])
        assert envelope["type"] == "INGEST_DECISION"
        assert envelope["payload"] == {"doc_uuid": doc_uuid, "decision": "approve"}
        assert "Approved" in reply and "4 chunks" in reply
        assert coordinator.pending_for("sess-1") is None

    def test_reject_sends_decision_and_clears_slot(self, tmp_path: Path) -> None:
        coordinator, _, transport, _, _ = _make_coordinator(tmp_path)
        _ingest(coordinator, "article text")
        doc_uuid = coordinator.pending_for("sess-1").doc_uuid

        transport._responses = [_ok_decision(doc_uuid, "rejected")]
        reply = _decide(coordinator, "reject")

        envelope = _envelope(transport.sent[1])
        assert envelope["payload"]["decision"] == "reject"
        assert "Rejected" in reply and "tombstone" in reply
        assert coordinator.pending_for("sess-1") is None

    def test_decision_without_pending_refused(self, tmp_path: Path) -> None:
        coordinator, _, transport, _, _ = _make_coordinator(tmp_path)
        for verb in ("approve", "reject"):
            reply = _decide(coordinator, verb)
            assert "no ingest is pending" in reply.lower()
        assert transport.sent == []

    def test_decision_with_argument_refused(self, tmp_path: Path) -> None:
        coordinator, _, transport, _, _ = _make_coordinator(tmp_path)
        reply = _run(coordinator.handle_command(
            "sess-1", IngestCommand(verb="approve", arg="some-doc")
        ))
        assert "takes no argument" in reply
        assert transport.sent == []

    def test_transient_failure_keeps_slot(self, tmp_path: Path) -> None:
        """A transient failure (transport error, bank disabled) surfaces and
        the slot survives so the operator can retry or /reject."""
        coordinator, _, transport, _, _ = _make_coordinator(tmp_path)
        _ingest(coordinator, "article text")
        doc_uuid = coordinator.pending_for("sess-1").doc_uuid

        transport._responses = [{
            "ok": False, "doc_uuid": doc_uuid, "state": "error",
            "chunk_count": 0, "error_code": "TRANSPORT_ERROR",
            "message": "Could not connect to the Assistant Orchestrator.",
        }]
        reply = _decide(coordinator, "approve")
        assert "TRANSPORT_ERROR" in reply
        assert "still pending" in reply
        assert coordinator.pending_for("sess-1") is not None
        assert coordinator.pending_for("sess-1").doc_uuid == doc_uuid

    def test_deterministic_refusal_clears_slot(self, tmp_path: Path) -> None:
        """INGEST_DECISION_REFUSED is a deterministic state refusal (never
        transient) — the slot no longer matches AO reality and is dropped so
        the operator is not trapped with an unclearable slot."""
        coordinator, _, transport, _, _ = _make_coordinator(tmp_path)
        _ingest(coordinator, "article text")
        doc_uuid = coordinator.pending_for("sess-1").doc_uuid

        transport._responses = [{
            "ok": False, "doc_uuid": doc_uuid, "state": "error",
            "chunk_count": 0, "error_code": "INGEST_DECISION_REFUSED",
            "message": "decide: unknown doc_uuid (Fail-Closed)",
        }]
        reply = _decide(coordinator, "approve")
        assert "INGEST_DECISION_REFUSED" in reply
        assert "slot was cleared" in reply
        assert coordinator.pending_for("sess-1") is None
        # The session can start a fresh ingest immediately.
        next_reply = _ingest(coordinator, "a different article")
        assert "Ingest preview" in next_reply

    def test_slot_clears_then_next_ingest_allowed(self, tmp_path: Path) -> None:
        coordinator, _, transport, _, _ = _make_coordinator(tmp_path)
        _ingest(coordinator, "first article")
        doc_uuid = coordinator.pending_for("sess-1").doc_uuid
        transport._responses = [_ok_decision(doc_uuid, "rejected")]
        _decide(coordinator, "reject")

        reply = _ingest(coordinator, "second article after the decision")
        assert "Ingest preview" in reply
        assert coordinator.pending_for("sess-1") is not None


# ---------------------------------------------------------------------------
# /ingest <url> — UC-003 Stage C host glue (fetch → guest parse → preview)
# ---------------------------------------------------------------------------
# The egress door + the guest parser are INJECTED as fakes — no real fetch, no
# real VM.  These lock the gateway-side flow: capability gate, the one-door
# fetch, the guest parse hop, the host injection compose, and every refusal.


def _fetch_ok(html: str, *, flags: tuple[str, ...] = ()):
    """A fake guarded_fetch door returning a successful body (no real socket)."""

    def _fetch(url: str, purpose: str):
        return SimpleNamespace(
            url=url,
            ok=True,
            content_text=html,
            denied_reason=None,
            injection_flags=tuple(flags),
        )

    return _fetch


def _fetch_denied(reason: str):
    def _fetch(url: str, purpose: str):
        return SimpleNamespace(
            url=url,
            ok=False,
            content_text="",
            denied_reason=reason,
            injection_flags=(),
        )

    return _fetch


def _parse_ok(
    *,
    text: str = (
        "The committee convened in full session and recorded a budget "
        "decision after reviewing every agenda item carefully today."
    ),
    status: str = "clean",
    reasons: tuple[str, ...] = (),
    title: str | None = "Committee Minutes",
    error_code: str = "",
):
    """A fake guest parse round-trip returning a real ParseResponse."""
    response = ParseResponse(
        request_id="r-url",
        status=status,
        text=text,
        title=title,
        byline=None,
        published_date=None,
        word_count=len(text.split()),
        confidence=0.9,
        reasons=reasons,
        error_code=error_code,
    )

    def _parse(html: str, source_url: str):
        return response

    return _parse


_ARTICLE_HTML = (
    "<html><head><title>Committee Minutes</title></head><body><article>"
    "<p>The committee convened in full session and recorded a budget decision "
    "after reviewing every agenda item carefully today.</p></article></body></html>"
)


class TestUrlIngestMode:
    """The active URL path — guest parser available, fetch + parse injected."""

    def _coord(self, tmp_path, *, fetch, parse, available=True):
        coordinator, pipeline, transport, staging_dir, _ = _make_coordinator(
            tmp_path,
            guest_parse_available_fn=lambda: available,
            url_fetch_fn=fetch,
            guest_parse_fn=parse,
        )
        return coordinator, pipeline, transport, staging_dir

    def test_full_flow_fetch_parse_preview(self, tmp_path: Path) -> None:
        coordinator, pipeline, transport, _ = self._coord(
            tmp_path, fetch=_fetch_ok(_ARTICLE_HTML), parse=_parse_ok()
        )
        reply = _ingest(coordinator, "https://example.com/story")
        assert "Ingest preview" in reply
        assert len(transport.sent) == 1
        payload = _envelope(transport.sent[0])["payload"]
        assert payload["source_type"] == "url"
        assert payload["source_ref"] == "https://example.com/story"
        # The host paste/file pipeline never ran — URL mode composes its own.
        assert pipeline.text_calls == [] and pipeline.html_calls == []
        assert coordinator.pending_for("sess-1") is not None

    def test_url_then_approve(self, tmp_path: Path) -> None:
        coordinator, _, transport, _ = self._coord(
            tmp_path, fetch=_fetch_ok(_ARTICLE_HTML), parse=_parse_ok()
        )
        _ingest(coordinator, "https://example.com/story")
        pending = coordinator.pending_for("sess-1")
        assert pending is not None
        transport._responses = [_ok_decision(pending.doc_uuid, "approved", chunk_count=4)]
        reply = _decide(coordinator, "approve")
        assert "Approved" in reply
        assert coordinator.pending_for("sess-1") is None

    def test_fetch_denied_refuses(self, tmp_path: Path) -> None:
        coordinator, _, transport, staging_dir = self._coord(
            tmp_path,
            fetch=_fetch_denied("Policy Agent denied the URL"),
            parse=_parse_ok(),
        )
        reply = _ingest(coordinator, "https://example.com/story")
        assert "refused" in reply.lower()
        assert "Policy Agent denied" in reply
        assert transport.sent == []
        assert not staging_dir.exists()
        assert coordinator.pending_for("sess-1") is None

    def test_guest_parse_none_refuses(self, tmp_path: Path) -> None:
        coordinator, _, transport, _ = self._coord(
            tmp_path, fetch=_fetch_ok(_ARTICLE_HTML), parse=lambda html, url: None
        )
        reply = _ingest(coordinator, "https://example.com/story")
        assert "refused" in reply.lower()
        assert transport.sent == []

    def test_guest_parse_error_status_refuses(self, tmp_path: Path) -> None:
        coordinator, _, transport, _ = self._coord(
            tmp_path,
            fetch=_fetch_ok(_ARTICLE_HTML),
            parse=_parse_ok(status="error", text="", error_code="PARSER_INTERNAL_ERROR"),
        )
        reply = _ingest(coordinator, "https://example.com/story")
        assert "refused" in reply.lower()
        assert "PARSER_INTERNAL_ERROR" in reply
        assert transport.sent == []

    def test_empty_fetch_body_refuses(self, tmp_path: Path) -> None:
        coordinator, _, transport, _ = self._coord(
            tmp_path, fetch=_fetch_ok("   "), parse=_parse_ok()
        )
        reply = _ingest(coordinator, "https://example.com/story")
        assert "empty" in reply.lower()
        assert transport.sent == []

    def test_oversize_fetched_page_refused_before_guest(self, tmp_path: Path) -> None:
        parse_calls: list = []

        def _parse(html: str, url: str):
            parse_calls.append(html)
            return _parse_ok()(html, url)

        big = "x" * (PARSE_BODY_MAX_BYTES + 1)
        coordinator, _, transport, _ = self._coord(
            tmp_path, fetch=_fetch_ok(big), parse=_parse
        )
        reply = _ingest(coordinator, "https://example.com/story")
        assert "cap" in reply.lower()
        assert parse_calls == []  # never reached the guest parse channel
        assert transport.sent == []

    def test_fetch_injection_flag_quarantines_preview(self, tmp_path: Path) -> None:
        coordinator, _, transport, _ = self._coord(
            tmp_path,
            fetch=_fetch_ok(_ARTICLE_HTML, flags=("role-override phrase",)),
            parse=_parse_ok(),
        )
        reply = _ingest(coordinator, "https://example.com/story")
        # The fetch-layer injection flag forces a quarantine verdict in the
        # preview (defense in depth) — the doc still stages pending for review
        # (approval is the override).
        assert "QUARANTINED" in reply
        assert coordinator.pending_for("sess-1") is not None

    def test_real_default_available_is_false_without_manager(
        self, tmp_path: Path
    ) -> None:
        """No injected availability fn → the real default consults the launcher
        singleton, which has no manager parked → unavailable (the URL door stays
        shut by structural absence)."""
        from launcher.guest_parser import set_guest_parser_manager

        set_guest_parser_manager(None)
        coordinator, _, transport, _, _ = _make_coordinator(tmp_path)
        reply = _ingest(coordinator, "https://example.com/story")
        assert "unavailable" in reply.lower()
        assert transport.sent == []


# ---------------------------------------------------------------------------
# Editable preview — edit-before-approve (#663 Workstream A)
# ---------------------------------------------------------------------------
# The operator trims the preview and approves the curated body.  The edited body
# is re-validated through the paste-path scan (no trafilatura re-extraction —
# here an ECHO cleaner stands in, returning its input as the cleaned text so the
# edit actually flows through), then dedup-REPLACES the pending row and is
# approved.  These lock the substitution + the paste correctness trap (carry the
# original source_ref forward; mint a fresh doc_uuid) + the provenance signal.


def _echo_coordinator(
    tmp_path: Path,
    *,
    status: str = "clean",
    reasons: tuple[str, ...] = (),
) -> tuple[IngestCoordinator, FakeTransportCall, dict[str, list[str]], Path, Path]:
    """A coordinator whose cleaner ECHOES its input as the cleaned text.

    The real ``clean_text`` does not re-extract — it normalises + scans +
    verdicts pasted markdown — so an echo (text == input) is the faithful
    stand-in for the re-clean: the 'edited body' actually flows through.
    Returns ``(coordinator, transport, calls, staging_dir, userdata)`` where
    ``calls`` records every clean_text/clean_html invocation.
    """
    calls: dict[str, list[str]] = {"text": [], "html": []}

    def _clean_text(raw: str) -> FakeCleanResult:
        calls["text"].append(raw)
        return FakeCleanResult(
            status=status,
            text=raw,
            title=None,
            byline=None,
            published_date=None,
            word_count=len(raw.split()),
            confidence=0.5 if status == "quarantined" else 1.0,
            reasons=reasons,
            cleaner_version="1.0.0",
            source_format="text",
        )

    def _clean_html(raw: str, *, source_url: str | None = None) -> FakeCleanResult:
        calls["html"].append(raw)
        return _clean_text(raw)

    coordinator, _pipe, transport, staging_dir, userdata = _make_coordinator(
        tmp_path, pipeline_loader=lambda: (_clean_text, _clean_html)
    )
    return coordinator, transport, calls, staging_dir, userdata


def _approve_edit(coordinator: IngestCoordinator, edited: str, session: str = "sess-1") -> str:
    return _run(coordinator.approve_with_edit(session, edited))


#: A re-submit (pending) reply that the coordinator's minted doc_uuid overrides.
_RESUBMIT_PENDING = {
    "ok": True, "doc_uuid": "ignored", "state": "pending",
    "chunk_count": 0, "error_code": "", "message": "",
}


class TestPreviewMeta:
    def test_none_when_no_pending(self, tmp_path: Path) -> None:
        coordinator, _, _, _, _ = _echo_coordinator(tmp_path)
        assert coordinator.preview_meta_for("sess-1") is None

    def test_returns_editable_body_and_handle(self, tmp_path: Path) -> None:
        coordinator, _, _, _, _ = _echo_coordinator(tmp_path)
        _ingest(coordinator, "the original article body to edit")
        meta = coordinator.preview_meta_for("sess-1")
        assert meta is not None
        # The editable body is the cleaned ARTICLE BODY (clean.text), not the
        # rendered preview blob — the exact source the operator edits.
        assert meta["editable_body"] == "the original article body to edit"
        assert meta["source_type"] == "paste"
        assert meta["doc_uuid"] == coordinator.pending_for("sess-1").doc_uuid


class TestApproveWithEdit:
    def test_no_pending_refuses(self, tmp_path: Path) -> None:
        coordinator, transport, _, _, _ = _echo_coordinator(tmp_path)
        reply = _approve_edit(coordinator, "anything")
        assert "no ingest is pending" in reply.lower()
        assert transport.sent == []

    def test_unchanged_body_is_plain_approve(self, tmp_path: Path) -> None:
        """Body unchanged from the cleaner output → plain /approve: NO re-clean,
        NO re-submit, exactly one extra (decision) frame, no edit note."""
        coordinator, transport, calls, _, _ = _echo_coordinator(tmp_path)
        _ingest(coordinator, "the original pasted article body")
        pending = coordinator.pending_for("sess-1")
        calls["text"].clear()
        transport._responses = [_ok_decision(pending.doc_uuid, "approved", chunk_count=3)]

        reply = _approve_edit(coordinator, pending.cleaned_text)

        assert calls["text"] == []  # no re-clean on the unchanged path
        assert len(transport.sent) == 2  # initial submit + the decision only
        decision = _envelope(transport.sent[1])
        assert decision["type"] == "INGEST_DECISION"
        assert decision["payload"] == {"doc_uuid": pending.doc_uuid, "decision": "approve"}
        assert "Approved" in reply and "3 chunks" in reply
        assert "curated edit" not in reply  # no edit note when unedited
        assert coordinator.pending_for("sess-1") is None

    def test_eol_only_change_is_plain_approve(self, tmp_path: Path) -> None:
        """A CRLF-vs-LF difference is not a real edit (EOL-tolerant compare)."""
        coordinator, transport, calls, _, _ = _echo_coordinator(tmp_path)
        _ingest(coordinator, "line one\nline two\nline three")
        pending = coordinator.pending_for("sess-1")
        calls["text"].clear()
        transport._responses = [_ok_decision(pending.doc_uuid, "approved", chunk_count=1)]

        reply = _approve_edit(coordinator, pending.cleaned_text.replace("\n", "\r\n"))

        assert calls["text"] == []  # treated as unchanged
        assert len(transport.sent) == 2
        assert "Approved" in reply

    def test_edited_paste_carries_source_ref_and_mints_fresh_uuid(
        self, tmp_path: Path
    ) -> None:
        """THE PASTE TRAP: an edited paste must dedup-REPLACE its pending row,
        so the re-submit carries the ORIGINAL source_ref forward (NOT a
        recomputed paste:<edited-hash>) and mints a FRESH doc_uuid."""
        coordinator, transport, calls, staging_dir, _ = _echo_coordinator(tmp_path)
        _ingest(coordinator, "original body with an advert line plus real content")
        pending = coordinator.pending_for("sess-1")
        orig_uuid = pending.doc_uuid
        orig_source_ref = pending.source_ref  # paste:<sha(original)>
        orig_sha = pending.content_sha256
        calls["text"].clear()

        transport._responses = [
            _RESUBMIT_PENDING,
            _ok_decision("ignored", "approved", chunk_count=2),
        ]
        edited = "real content only"
        reply = _approve_edit(coordinator, edited)

        # The edited body was re-validated through the paste-path scan.
        assert calls["text"] == [edited]
        # Three frames total: initial submit, the edited re-submit, the decision.
        assert len(transport.sent) == 3
        resubmit = _envelope(transport.sent[1])
        assert resubmit["type"] == "INGEST_SUBMIT"
        rp = resubmit["payload"]
        # Carried forward unchanged → same source_hash → dedup-REPLACE (no orphan).
        assert rp["source_ref"] == orig_source_ref
        assert not rp["source_ref"].endswith(
            hashlib.sha256(edited.encode("utf-8")).hexdigest()
        )
        # Fresh doc_uuid (never reuses the original → no collision-guard trip).
        new_uuid = rp["doc_uuid"]
        assert new_uuid != orig_uuid
        # The edited body's hash + the cleaner's ORIGINAL digest as provenance.
        assert rp["content_sha256"] == hashlib.sha256(edited.encode("utf-8")).hexdigest()
        assert rp["prior_content_sha256"] == orig_sha
        # The decision approves the freshly-staged edited row.
        decision = _envelope(transport.sent[2])
        assert decision["type"] == "INGEST_DECISION"
        assert decision["payload"] == {"doc_uuid": new_uuid, "decision": "approve"}
        # The staged bytes ARE the edited body (not the cleaner's original).
        staged = read_staged(new_uuid, _cipher(), staging_dir)
        assert staged == edited
        assert "Approved" in reply
        assert "curated edit was stored" in reply
        assert coordinator.pending_for("sess-1") is None

    def test_edited_file_carries_path_source_ref_forward(self, tmp_path: Path) -> None:
        """url/file source_ref is already stable; the edit carries it forward too."""
        coordinator, transport, calls, _, _ = _echo_coordinator(tmp_path)
        local = tmp_path / "local" / "doc.txt"
        local.parent.mkdir(parents=True)
        local.write_text("file body with noise and signal", encoding="utf-8")
        _ingest(coordinator, str(local))
        pending = coordinator.pending_for("sess-1")
        orig_source_ref = pending.source_ref  # the resolved file path
        calls["text"].clear()

        transport._responses = [
            _RESUBMIT_PENDING,
            _ok_decision("ignored", "approved", chunk_count=1),
        ]
        reply = _approve_edit(coordinator, "file body, signal only")

        resubmit = _envelope(transport.sent[1])["payload"]
        assert resubmit["source_type"] == "file"
        assert resubmit["source_ref"] == orig_source_ref  # unchanged path
        assert "Approved" in reply

    def test_edited_body_requantined_still_approves_with_note(
        self, tmp_path: Path
    ) -> None:
        """Re-scan that re-flags the edited text LABELS but does not block —
        the operator approval is the override (ADR-030 §6); the reply surfaces
        the flag."""
        coordinator, transport, calls, _, _ = _echo_coordinator(
            tmp_path, status="quarantined", reasons=("INJECTION_PATTERN_DETECTED",)
        )
        _ingest(coordinator, "original suspicious body text here")
        pending = coordinator.pending_for("sess-1")
        calls["text"].clear()
        transport._responses = [
            _RESUBMIT_PENDING,
            _ok_decision("ignored", "approved", chunk_count=1),
        ]
        reply = _approve_edit(coordinator, "edited but still suspicious body")

        assert "Approved" in reply  # stored anyway — approval is the override
        assert "INJECTION_PATTERN_DETECTED" in reply
        assert "stored anyway per your approval" in reply
        assert coordinator.pending_for("sess-1") is None

    def test_edit_to_empty_refused_keeps_slot(self, tmp_path: Path) -> None:
        coordinator, transport, calls, _, _ = _echo_coordinator(tmp_path)
        _ingest(coordinator, "the original body before deletion")
        pending = coordinator.pending_for("sess-1")
        calls["text"].clear()

        reply = _approve_edit(coordinator, "    ")

        assert "nothing to store" in reply.lower()
        # No re-submit (only the initial submit frame) — the slot is preserved.
        assert len(transport.sent) == 1
        assert coordinator.pending_for("sess-1") is pending

    def test_resubmit_transport_failure_keeps_slot(self, tmp_path: Path) -> None:
        coordinator, transport, calls, staging_dir, _ = _echo_coordinator(tmp_path)
        _ingest(coordinator, "original body to edit then fail")
        pending = coordinator.pending_for("sess-1")
        orig_uuid = pending.doc_uuid
        calls["text"].clear()
        transport._responses = [{
            "ok": False, "doc_uuid": "", "state": "error", "chunk_count": 0,
            "error_code": "TRANSPORT_ERROR", "message": "AO unreachable.",
        }]
        reply = _approve_edit(coordinator, "edited body that cannot be submitted")

        assert "Ingest submit failed" in reply
        assert "TRANSPORT_ERROR" in reply
        # The original pending slot survives (operator can retry or /reject).
        assert coordinator.pending_for("sess-1").doc_uuid == orig_uuid
        # The re-submit's orphaned staging file was cleaned up (the initial
        # submit's file persists — the fake AO never deletes it).
        new_uuid = _envelope(transport.sent[1])["payload"]["doc_uuid"]
        assert not (staging_dir / f"{new_uuid}.bin").exists()
        assert (staging_dir / f"{orig_uuid}.bin").exists()
