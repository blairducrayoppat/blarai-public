"""
Integration: REAL cleaner pipeline through the REAL ingest coordinator (#655).

Merge-time integration test (the #655 merge runbook item 4).  During the
UC-002/003 build, each side mocked the other: the ingest-UX tests
(``services/ui_gateway/tests/test_ingest_coordinator.py``) inject a
``FakePipeline``, and the cleaner corpus tests
(``services/cleaner/tests/test_clean_html_corpus.py``) never touch the
coordinator.  This file is the seam lock: it drives the real
``services.cleaner.src.pipeline`` (real trafilatura extraction →
normalization → sanitization → verdict) THROUGH the real
``IngestCoordinator`` — via the coordinator's own default lazy loader, so
the production wiring path (``_load_real_pipeline``) is exercised too —
using the tracked HTML fixtures from the cleaner corpus.

What stays stubbed: the IPC/AO transport seam only (the same scripted
``transport_call`` shape the coordinator unit tests use) — that seam is
covered on the AO side by
``services/assistant_orchestrator/tests/test_knowledge_bank_wiring.py``.
The coverage target here is the cleaner↔coordinator integration:

  (a) the preview carries the REAL extracted title + word count;
  (b) the encrypted staging file decrypts back to exactly the real
      cleaned text (and never holds plaintext on disk);
  (c) ``content_sha256`` is sha256 of that real cleaned text;
  (d) the INGEST_SUBMIT frame carries the real metadata and the approve
      flow emits the INGEST_DECISION frame for the same document;
  (e) the real quarantine verdicts (paywall teaser → LOW_TEXT_LENGTH,
      injection page → INJECTION_PATTERN_DETECTED) flow through the
      coordinator: still submitted (L0 pending IS the quarantine,
      ADR-030 §6), preview names the verdict + reasons, and the
      SANITIZED text — forged spotlighting delimiter already stripped —
      is what lands in encrypted staging.

Oracle strategy: the real pipeline is deterministic (same input →
byte-identical ``CleanResult``, locked by the corpus tests), so each test
computes the expected result by calling ``clean_html`` directly and
asserts the coordinator's observable outputs against it — both sides
real, no canned values.

Model-free; no AO; no network (extraction-only posture, ADR-030 §4); no
real %LOCALAPPDATA% (staging/userdata are tmp_path-injected and the root
conftest redirects LOCALAPPDATA besides).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from services.cleaner.src.pipeline import (
    CLEANER_VERSION,
    MIN_WORDS_HTML,
    REASON_INJECTION_PATTERN_DETECTED,
    REASON_LOW_TEXT_LENGTH,
    CleanResult,
    clean_html,
)
from services.ui_gateway.src.ingest_coordinator import (
    IngestCommand,
    IngestCoordinator,
)
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.ingest_staging import read_staged

_FIXTURES = (
    Path(__file__).resolve().parents[2] / "services" / "cleaner" / "tests" / "fixtures"
)

_SESSION = "sess-integration"


def _fixture_path(name: str) -> Path:
    path = _FIXTURES / name
    assert path.is_file(), f"tracked cleaner fixture missing: {path}"
    return path


def _real_result(name: str) -> CleanResult:
    """The deterministic real-pipeline oracle for a tracked HTML fixture.

    Mirrors exactly what the coordinator's FILE-mode HTML branch does:
    strict-UTF-8 read → ``clean_html(raw_html)`` with no source_url.
    """
    raw = _fixture_path(name).read_text(encoding="utf-8", errors="strict")
    return clean_html(raw)


class ScriptedTransport:
    """The stubbed IPC/AO seam — identical shape to the coordinator unit
    tests' ``FakeTransportCall`` (the seam itself is covered AO-side by
    test_knowledge_bank_wiring.py)."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self._responses: list[dict[str, Any]] = []

    def script(self, response: dict[str, Any]) -> None:
        self._responses.append(response)

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


def _make_real_coordinator(
    tmp_path: Path,
) -> tuple[IngestCoordinator, ScriptedTransport, Path, FieldCipher]:
    """A coordinator with the REAL default pipeline loader (no injection).

    ``pipeline_loader`` is deliberately NOT passed: the coordinator falls
    back to ``_load_real_pipeline`` and lazily imports the real cleaner —
    the exact production wiring this merge-time test exists to prove.
    """
    transport = ScriptedTransport()
    cipher = FieldCipher(derive_subkeys(b"\x42" * 32))
    staging_dir = tmp_path / "staging"
    userdata_dir = tmp_path / "userdata"
    userdata_dir.mkdir(parents=True, exist_ok=True)
    coordinator = IngestCoordinator(
        transport_call=transport,
        cipher_provider=lambda: cipher,
        staging_dir_provider=lambda: staging_dir,
        userdata_dir=userdata_dir,
    )
    return coordinator, transport, staging_dir, cipher


def _ingest_fixture(coordinator: IngestCoordinator, name: str) -> str:
    """Drive /ingest with the ABSOLUTE path of a tracked fixture (FILE
    mode → strict-UTF-8 read → the real ``clean_html``)."""
    return asyncio.run(
        coordinator.handle_command(
            _SESSION, IngestCommand(verb="ingest", arg=str(_fixture_path(name)))
        )
    )


def _decide(coordinator: IngestCoordinator, verb: str) -> str:
    return asyncio.run(
        coordinator.handle_command(_SESSION, IngestCommand(verb=verb, arg=""))
    )


# ---------------------------------------------------------------------------
# Clean article: real extraction flows end to end through the coordinator
# ---------------------------------------------------------------------------


class TestRealCleanArticleThroughCoordinator:
    """news_quantum.html — a real clean verdict drives the full flow."""

    def test_preview_carries_real_extracted_title_and_word_count(
        self, tmp_path: Path
    ) -> None:
        expected = _real_result("news_quantum.html")
        # Oracle sanity: this is the corpus-locked REAL extraction, not a fake.
        assert expected.status == "clean"
        assert expected.title == "Quantum Leap in Local AI"
        assert expected.word_count >= MIN_WORDS_HTML

        coordinator, _, _, _ = _make_real_coordinator(tmp_path)
        reply = _ingest_fixture(coordinator, "news_quantum.html")

        assert "Ingest preview" in reply
        # (a) REAL extracted metadata in the preview — not mock values.
        assert f"- Title: {expected.title}" in reply
        assert f"- Words: {expected.word_count}" in reply
        assert "- Byline: Jane Mercer" in reply
        assert "QUARANTINED" not in reply
        # The real extracted body (boilerplate stripped) is what is shown.
        assert "speculative decoding scheme" in reply
        assert "SUBSCRIBE NOW" not in reply  # ad chrome never reached the preview

    def test_staged_file_encrypts_exactly_the_real_cleaned_text(
        self, tmp_path: Path
    ) -> None:
        expected = _real_result("news_quantum.html")
        coordinator, transport, staging_dir, cipher = _make_real_coordinator(tmp_path)
        _ingest_fixture(coordinator, "news_quantum.html")

        payload = _envelope(transport.sent[0])["payload"]
        doc_uuid = str(payload["doc_uuid"])
        staged = staging_dir / f"{doc_uuid}.bin"
        assert staged.exists()
        # (b) never plaintext on disk ...
        raw = staged.read_bytes()
        assert expected.text.encode("utf-8") not in raw
        assert b"speculative decoding scheme" not in raw
        # ... and decrypts back to EXACTLY the real pipeline's cleaned text.
        assert read_staged(doc_uuid, cipher, staging_dir) == expected.text

    def test_content_sha256_matches_real_cleaned_text(self, tmp_path: Path) -> None:
        expected = _real_result("news_quantum.html")
        coordinator, transport, _, _ = _make_real_coordinator(tmp_path)
        _ingest_fixture(coordinator, "news_quantum.html")

        payload = _envelope(transport.sent[0])["payload"]
        # (c) the coordinator hashed the REAL cleaned text, byte-exact.
        expected_sha = hashlib.sha256(expected.text.encode("utf-8")).hexdigest()
        assert payload["content_sha256"] == expected_sha

    def test_submit_frame_carries_real_metadata_and_approve_emits_decision(
        self, tmp_path: Path
    ) -> None:
        expected = _real_result("news_quantum.html")
        coordinator, transport, _, _ = _make_real_coordinator(tmp_path)
        reply = _ingest_fixture(coordinator, "news_quantum.html")
        assert "Ingest preview" in reply

        # (d) INGEST_SUBMIT carries the real metadata, consistent with (a)-(c).
        envelope = _envelope(transport.sent[0])
        assert envelope["type"] == "INGEST_SUBMIT"
        payload = envelope["payload"]
        assert payload["title"] == expected.title
        assert payload["byline"] == expected.byline == "Jane Mercer"
        assert payload["published_date"] == expected.published_date == "2026-05-14"
        assert payload["word_count"] == expected.word_count
        assert payload["cleaner_version"] == expected.cleaner_version == CLEANER_VERSION
        assert payload["content_sha256"] == hashlib.sha256(
            expected.text.encode("utf-8")
        ).hexdigest()
        assert payload["source_type"] == "file"
        assert payload["source_ref"].endswith("news_quantum.html")
        assert payload["staging_path"].endswith(f"{payload['doc_uuid']}.bin")

        # Approve: the decision frame targets the same real document.
        pending = coordinator.pending_for(_SESSION)
        assert pending is not None
        assert pending.title == expected.title
        assert pending.word_count == expected.word_count
        transport.script({
            "ok": True, "doc_uuid": pending.doc_uuid, "state": "approved",
            "chunk_count": 3, "error_code": "", "message": "",
        })
        decision_reply = _decide(coordinator, "approve")

        decision = _envelope(transport.sent[1])
        assert decision["type"] == "INGEST_DECISION"
        assert decision["payload"] == {
            "doc_uuid": payload["doc_uuid"],
            "decision": "approve",
        }
        assert "Approved" in decision_reply
        assert expected.title is not None and expected.title in decision_reply
        assert coordinator.pending_for(_SESSION) is None


# ---------------------------------------------------------------------------
# Quarantine verdicts: real adversarial fixtures through the coordinator
# ---------------------------------------------------------------------------


class TestRealQuarantineThroughCoordinator:
    """The real pipeline's conservative verdicts drive the pending flow:
    quarantined documents STILL submit (L0 pending IS the quarantine,
    ADR-030 §6 — /approve is the override), and the preview carries the
    verdict, the reasons, and the reviewable text."""

    def test_paywall_teaser_quarantines_with_low_text_length(
        self, tmp_path: Path
    ) -> None:
        expected = _real_result("paywall_teaser.html")
        # Oracle sanity: the REAL pipeline quarantines this tracked fixture.
        assert expected.status == "quarantined"
        assert REASON_LOW_TEXT_LENGTH in expected.reasons

        coordinator, transport, _, _ = _make_real_coordinator(tmp_path)
        reply = _ingest_fixture(coordinator, "paywall_teaser.html")

        # (e) the real quarantine verdict reaches the operator ...
        assert "QUARANTINED" in reply
        assert REASON_LOW_TEXT_LENGTH in reply
        assert f"- Words: {expected.word_count}" in reply
        # ... with the real teaser text still carried for review.
        assert "internal memo circulated last week" in reply
        # ... and the document still submitted into the pending state.
        assert len(transport.sent) == 1
        payload = _envelope(transport.sent[0])["payload"]
        assert payload["content_sha256"] == hashlib.sha256(
            expected.text.encode("utf-8")
        ).hexdigest()
        assert coordinator.pending_for(_SESSION) is not None

    def test_injection_page_quarantines_and_stages_sanitized_text(
        self, tmp_path: Path
    ) -> None:
        forged_delimiter = "<|GROUNDED_CONTEXT_BEGIN|>"
        raw_fixture = _fixture_path("injection_attack.html").read_text(
            encoding="utf-8"
        )
        assert forged_delimiter in raw_fixture  # the attack is really in the input

        expected = _real_result("injection_attack.html")
        assert expected.status == "quarantined"
        assert REASON_INJECTION_PATTERN_DETECTED in expected.reasons

        coordinator, transport, staging_dir, cipher = _make_real_coordinator(tmp_path)
        reply = _ingest_fixture(coordinator, "injection_attack.html")

        # The verdict + reason surface in the preview; text stays reviewable.
        assert "QUARANTINED" in reply
        assert REASON_INJECTION_PATTERN_DETECTED in reply
        assert "router placement" in reply
        # The forged delimiter was stripped by the real sanitizer before the
        # preview AND before staging — what decrypts back is the SANITIZED
        # text, byte-exact, with the attack delimiter gone.
        assert forged_delimiter not in reply
        doc_uuid = str(_envelope(transport.sent[0])["payload"]["doc_uuid"])
        staged_plaintext = read_staged(doc_uuid, cipher, staging_dir)
        assert staged_plaintext == expected.text
        assert forged_delimiter not in staged_plaintext

    def test_quarantined_document_can_be_rejected(self, tmp_path: Path) -> None:
        coordinator, transport, _, _ = _make_real_coordinator(tmp_path)
        _ingest_fixture(coordinator, "paywall_teaser.html")
        pending = coordinator.pending_for(_SESSION)
        assert pending is not None

        transport.script({
            "ok": True, "doc_uuid": pending.doc_uuid, "state": "rejected",
            "chunk_count": 0, "error_code": "", "message": "",
        })
        reply = _decide(coordinator, "reject")

        decision = _envelope(transport.sent[1])
        assert decision["type"] == "INGEST_DECISION"
        assert decision["payload"]["decision"] == "reject"
        assert "Rejected" in reply
        assert coordinator.pending_for(_SESSION) is None
