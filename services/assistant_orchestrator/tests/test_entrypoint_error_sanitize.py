"""Tier-1 error-sanitize hardening — AO entrypoint (Vikunja #560).

Verifies that the malformed-message error path in _handle_connection sends a
sanitized client message (no raw exception detail) while retaining the full
diagnostic in the server log.

TEETH: the pre-fix behavior sent ``f"Malformed message: {exc}"`` which
included the raw ValueError detail.  These tests would FAIL against that
behavior (lesson 30).
"""

from __future__ import annotations

import logging
import re

import pytest

from shared.ipc.protocol import MessageFramer, MessageType
from services.assistant_orchestrator.src.entrypoint import AssistantOrchestratorService


class _FakeTransport:
    def __init__(self, inbound: bytes | None) -> None:
        self._inbound = inbound
        self.sent: list[bytes] = []

    def receive(self) -> bytes | None:
        return self._inbound

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True


class TestEntrypointMalformedMessageSanitized:
    """_handle_connection: malformed frame → sanitized error frame."""

    def test_client_receives_no_raw_exception_detail(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """TEETH: pre-fix sent f'Malformed message: {exc}' which included the
        raw JSONDecodeError text.  This assertion would FAIL against that."""
        service = AssistantOrchestratorService("dummy.toml")
        framer = MessageFramer()
        transport = _FakeTransport(b"definitely-not-valid-json-bytes")

        with caplog.at_level(logging.ERROR):
            result = service._handle_connection(transport)

        assert result is True
        assert len(transport.sent) == 1

        msg_type, _rid, payload = framer.decode(transport.sent[0])
        assert msg_type == MessageType.ERROR

        client_error = str(payload.get("error", ""))

        # Raw exception detail must NOT appear client-side.
        assert "Malformed JSON" not in client_error, (
            "Raw exception class leaked to client (pre-fix behavior — TEETH failure)"
        )
        assert "JSONDecodeError" not in client_error, (
            "Raw exception class leaked to client (pre-fix behavior — TEETH failure)"
        )
        assert "Expecting value" not in client_error, (
            "Internal decode detail leaked to client (pre-fix behavior — TEETH failure)"
        )

    def test_client_receives_generic_message_with_correlation_id(self) -> None:
        """Sanitized message follows 'malformed message [<8-hex>]' contract."""
        service = AssistantOrchestratorService("dummy.toml")
        framer = MessageFramer()
        transport = _FakeTransport(b"not-json")

        service._handle_connection(transport)

        _msg_type, _rid, payload = framer.decode(transport.sent[0])
        client_error = str(payload.get("error", ""))

        assert "malformed message" in client_error.lower(), (
            f"Expected generic 'malformed message [cid]' prefix, got: {client_error!r}"
        )
        assert re.search(r"\[[0-9a-f]{8}\]", client_error), (
            f"No 8-hex correlation id in client error: {client_error!r}"
        )

    def test_failure_signal_still_delivered(self) -> None:
        """The client still receives an ERROR frame — failure is not swallowed."""
        service = AssistantOrchestratorService("dummy.toml")
        framer = MessageFramer()
        transport = _FakeTransport(b"garbage")

        result = service._handle_connection(transport)

        assert result is True  # handled (not crashed)
        assert len(transport.sent) == 1
        msg_type, _rid, _payload = framer.decode(transport.sent[0])
        assert msg_type == MessageType.ERROR

    def test_full_diagnostic_logged_server_side(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Log must carry the raw decode error so ops can diagnose the cause."""
        service = AssistantOrchestratorService("dummy.toml")
        framer = MessageFramer()
        transport = _FakeTransport(b"bad")

        with caplog.at_level(
            logging.ERROR,
            logger="services.assistant_orchestrator.src.entrypoint",
        ):
            service._handle_connection(transport)

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_records, "No ERROR log record emitted for malformed message"

        log_text = " ".join(r.getMessage() for r in error_records)
        # The raw decode error should appear in the log.
        assert "malformed" in log_text.lower(), (
            "Server log does not mention the decode failure"
        )

    def test_correlation_id_present_in_both_log_and_client_message(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """cid in client message must also appear in the server log."""
        service = AssistantOrchestratorService("dummy.toml")
        framer = MessageFramer()
        transport = _FakeTransport(b"not-json")

        with caplog.at_level(
            logging.ERROR,
            logger="services.assistant_orchestrator.src.entrypoint",
        ):
            service._handle_connection(transport)

        _msg_type, _rid, payload = framer.decode(transport.sent[0])
        client_error = str(payload.get("error", ""))
        match = re.search(r"\[([0-9a-f]{8})\]", client_error)
        assert match, f"No cid in client error: {client_error!r}"
        cid = match.group(1)

        full_log = " ".join(r.getMessage() for r in caplog.records)
        assert cid in full_log, (
            f"cid={cid!r} in client message but not in server log — "
            f"cannot correlate error to diagnostic"
        )
