"""
Tests — Policy Agent IPC Listener (P1.6)
==========================================
services/policy_agent/src/ipc.py

All tests use dev_mode=True (TCP loopback on 127.0.0.1).

Groups:
  A. TestDefaultDenyHandler — Fail-Closed default behaviour.
  B. TestPolicyAgentListenerProperties — properties, construction.
  C. TestPolicyAgentListenerHandleRequest — request routing, fail-closed.
  D. TestPolicyAgentListenerHandleConnection — transport-level I/O.
  E. TestPolicyAgentListenerLifecycle — start/stop.
  F. TestPolicyAgentListenerEndToEnd — full client→listener→handler flow.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
from pathlib import Path

import pytest

from shared.ipc.protocol import (
    AdjudicationRequest,
    AdjudicationResponse,
    MessageFramer,
    MessageType,
)
from shared.ipc.vsock import (
    VsockAddress,
    VsockConfig,
    VsockListener,
    VsockTransport,
    _HEADER_FORMAT,
)
from services.policy_agent.src.ipc import (
    PolicyAgentListener,
    default_deny_handler,
)


# =====================================================================
# Helpers
# =====================================================================


def _make_config(*, port: int = 0) -> VsockConfig:
    """Create a dev-mode VsockConfig with an ephemeral port."""
    return VsockConfig(
        address=VsockAddress(cid=0, port=port),
        timeout_ms=2_000,
        max_message_bytes=65_536,
    )


def _allow_handler(car_json: str, request_id: str) -> AdjudicationResponse:
    """Test handler that always ALLOWs."""
    return AdjudicationResponse(
        decision="ALLOW",
        jwt_token="test-jwt-token",
        car_hash="abc123hash",
        request_id=request_id,
    )


def _deny_handler(car_json: str, request_id: str) -> AdjudicationResponse:
    """Test handler that always DENYs."""
    return AdjudicationResponse(
        decision="DENY",
        request_id=request_id,
        error="blocked_by_test",
    )


def _error_handler(car_json: str, request_id: str) -> AdjudicationResponse:
    """Test handler that raises an exception."""
    raise RuntimeError("Handler exploded on purpose")


# =====================================================================
# Group A: Default deny handler
# =====================================================================


class TestDefaultDenyHandler:
    """The Fail-Closed default when no adjudicator is configured."""

    def test_returns_deny(self) -> None:
        resp = default_deny_handler('{"action":"READ"}', "r1")
        assert resp.decision == "DENY"

    def test_includes_error_reason(self) -> None:
        resp = default_deny_handler("{}", "r2")
        assert "NO_ADJUDICATOR_CONFIGURED" in resp.error

    def test_preserves_request_id(self) -> None:
        resp = default_deny_handler("{}", "r3")
        assert resp.request_id == "r3"


# =====================================================================
# Group B: PolicyAgentListener properties
# =====================================================================


class TestPolicyAgentListenerProperties:
    """Construction and property access."""

    def test_initial_counts_zero(self) -> None:
        pal = PolicyAgentListener(_make_config(), dev_mode=True)
        assert pal.request_count == 0
        assert pal.rejection_count == 0

    def test_not_running_initially(self) -> None:
        pal = PolicyAgentListener(_make_config(), dev_mode=True)
        assert pal.running is False

    def test_default_handler_is_deny(self) -> None:
        pal = PolicyAgentListener(_make_config(), dev_mode=True)
        # Invoke the default handler directly.
        resp = pal.handler("{}", "test")
        assert resp.decision == "DENY"

    def test_custom_handler_assigned(self) -> None:
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )
        resp = pal.handler("{}", "test")
        assert resp.decision == "ALLOW"

    def test_listener_property_accessible(self) -> None:
        pal = PolicyAgentListener(_make_config(), dev_mode=True)
        assert isinstance(pal.listener, VsockListener)


# =====================================================================
# Group C: handle_request — request routing and fail-closed
# =====================================================================


class TestPolicyAgentListenerHandleRequest:
    """Unit tests for handle_request with raw JSON bytes."""

    def test_valid_adjudication_request_allow(self) -> None:
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )

        req = AdjudicationRequest(car_json='{"verb":"READ"}', request_id="r1")
        raw = framer.encode_request(req)
        resp_bytes = pal.handle_request(raw)

        # Decode response.
        msg_type, rid, payload = framer.decode(resp_bytes)
        assert msg_type == MessageType.ADJUDICATION_RESPONSE
        resp = AdjudicationResponse.from_dict(payload)
        assert resp.decision == "ALLOW"
        assert resp.jwt_token == "test-jwt-token"
        assert pal.request_count == 1
        assert pal.rejection_count == 0

    def test_valid_adjudication_request_deny(self) -> None:
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_deny_handler, dev_mode=True
        )

        req = AdjudicationRequest(car_json='{"verb":"DELETE"}', request_id="r2")
        raw = framer.encode_request(req)
        resp_bytes = pal.handle_request(raw)

        msg_type, rid, payload = framer.decode(resp_bytes)
        resp = AdjudicationResponse.from_dict(payload)
        assert resp.decision == "DENY"
        assert pal.rejection_count == 1

    def test_heartbeat_request(self) -> None:
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )

        raw = framer.encode_heartbeat("hb1")
        resp_bytes = pal.handle_request(raw)

        msg_type, rid, payload = framer.decode(resp_bytes)
        assert msg_type == MessageType.HEARTBEAT
        assert payload["status"] == "alive"
        assert pal.request_count == 1
        # Heartbeats are not rejections.
        assert pal.rejection_count == 0

    def test_error_message_acknowledged(self) -> None:
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )

        raw = framer.encode_error("client error", "e1")
        resp_bytes = pal.handle_request(raw)

        msg_type, rid, payload = framer.decode(resp_bytes)
        assert msg_type == MessageType.ERROR
        assert pal.rejection_count == 1

    def test_missing_car_json_rejected(self) -> None:
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )

        # Build a request with empty car_json.
        raw = framer.encode(
            MessageType.ADJUDICATION_REQUEST,
            {"car_json": "", "request_id": "r3"},
            "r3",
        )
        resp_bytes = pal.handle_request(raw)

        msg_type, rid, payload = framer.decode(resp_bytes)
        assert msg_type == MessageType.ERROR
        assert pal.rejection_count == 1

    def test_missing_request_id_rejected(self) -> None:
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )

        raw = framer.encode(
            MessageType.ADJUDICATION_REQUEST,
            {"car_json": '{"a":1}', "request_id": ""},
            "",
        )
        resp_bytes = pal.handle_request(raw)

        msg_type, rid, payload = framer.decode(resp_bytes)
        assert msg_type == MessageType.ERROR
        assert pal.rejection_count == 1

    def test_malformed_json_returns_error(self) -> None:
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )

        resp_bytes = pal.handle_request(b"not json at all")
        framer = MessageFramer()
        msg_type, _, payload = framer.decode(resp_bytes)
        assert msg_type == MessageType.ERROR
        assert pal.rejection_count == 1

    def test_handler_exception_produces_deny(self) -> None:
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_error_handler, dev_mode=True
        )

        req = AdjudicationRequest(car_json='{"v":"EXEC"}', request_id="r4")
        raw = framer.encode_request(req)
        resp_bytes = pal.handle_request(raw)

        msg_type, rid, payload = framer.decode(resp_bytes)
        assert msg_type == MessageType.ADJUDICATION_RESPONSE
        resp = AdjudicationResponse.from_dict(payload)
        assert resp.decision == "DENY"
        assert "Handler error" in resp.error
        assert pal.rejection_count == 1

    def test_response_message_type_rejected(self) -> None:
        """Sending ADJUDICATION_RESPONSE type to the listener is rejected."""
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )

        raw = framer.encode(
            MessageType.ADJUDICATION_RESPONSE,
            {"decision": "ALLOW"},
            "r5",
        )
        resp_bytes = pal.handle_request(raw)

        msg_type, _, payload = framer.decode(resp_bytes)
        assert msg_type == MessageType.ERROR
        assert pal.rejection_count == 1

    def test_request_count_increments(self) -> None:
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )

        req = AdjudicationRequest(car_json='{"v":"R"}', request_id="r6")
        raw = framer.encode_request(req)

        pal.handle_request(raw)
        pal.handle_request(raw)
        pal.handle_request(raw)
        assert pal.request_count == 3
        assert pal.rejection_count == 0

    def test_handshake_request_returns_operational(self) -> None:
        """Boot-Phase-3: HANDSHAKE_REQUEST yields HANDSHAKE_RESPONSE/OPERATIONAL.

        Regression for the production boot defect where the PA returned
        "Unsupported message type: HANDSHAKE_REQUEST", causing the gateway
        to fail-close after 3 retries.  The fix mirrors the AO handler at
        entrypoint.py::_handle_connection.
        """
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )

        raw = framer.encode_handshake_request("hs1")
        resp_bytes = pal.handle_request(raw)

        msg_type, rid, payload = framer.decode(resp_bytes)
        assert msg_type == MessageType.HANDSHAKE_RESPONSE
        assert payload.get("status") == "OPERATIONAL"
        # Handshake is not a rejection.
        assert pal.rejection_count == 0
        assert pal.request_count == 1

    def test_handshake_request_not_unsupported(self) -> None:
        """HANDSHAKE_REQUEST no longer yields 'Unsupported message type' error."""
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )

        raw = framer.encode_handshake_request("hs2")
        resp_bytes = pal.handle_request(raw)

        msg_type, _, payload = framer.decode(resp_bytes)
        assert msg_type != MessageType.ERROR, (
            f"PA returned error on HANDSHAKE_REQUEST: {payload}"
        )


# =====================================================================
# Group D: handle_connection — transport-level I/O
# =====================================================================


class TestPolicyAgentListenerHandleConnection:
    """Tests handle_connection with real VsockTransport over TCP loopback."""

    def test_handle_connection_roundtrip(self) -> None:
        """Client sends AdjudicationRequest, gets response via handle_connection."""
        cfg = _make_config(port=0)
        pal = PolicyAgentListener(cfg, handler=_allow_handler, dev_mode=True)
        assert pal.start() is True
        port = pal.listener.bound_port
        assert port is not None

        connection_ok: list[bool] = [False]

        def server_loop() -> None:
            st = pal.listener.accept()
            if st is not None:
                connection_ok[0] = pal.handle_connection(st)
                st.close()

        t = threading.Thread(target=server_loop, daemon=True)
        t.start()

        # Client connects and sends.
        framer = MessageFramer()
        client_cfg = _make_config(port=port)
        client = VsockTransport(client_cfg, dev_mode=True)
        assert client.connect() is True

        req = AdjudicationRequest(car_json='{"v":"READ"}', request_id="r10")
        raw_request = framer.encode_request(req)
        assert client.send(raw_request) is True

        # Client receives response.
        raw_response = client.receive()
        assert raw_response is not None

        msg_type, rid, payload = framer.decode(raw_response)
        assert msg_type == MessageType.ADJUDICATION_RESPONSE
        resp = AdjudicationResponse.from_dict(payload)
        assert resp.decision == "ALLOW"
        assert resp.jwt_token == "test-jwt-token"

        client.close()
        t.join(timeout=2.0)
        assert connection_ok[0] is True

        pal.stop()

    def test_handle_connection_broken_transport(self) -> None:
        """handle_connection returns False when transport yields None."""
        cfg = _make_config()
        pal = PolicyAgentListener(cfg, handler=_allow_handler, dev_mode=True)

        # Create a transport that's not connected — receive() → None.
        fake_transport = VsockTransport(cfg, dev_mode=True)
        assert pal.handle_connection(fake_transport) is False


# =====================================================================
# Group E: Lifecycle — start/stop
# =====================================================================


class TestPolicyAgentListenerLifecycle:
    """Start/stop lifecycle."""

    def test_start_sets_running(self) -> None:
        pal = PolicyAgentListener(_make_config(), dev_mode=True)
        assert pal.start() is True
        assert pal.running is True
        pal.stop()

    def test_stop_clears_running(self) -> None:
        pal = PolicyAgentListener(_make_config(), dev_mode=True)
        pal.start()
        pal.stop()
        assert pal.running is False

    def test_double_stop_is_safe(self) -> None:
        pal = PolicyAgentListener(_make_config(), dev_mode=True)
        pal.start()
        pal.stop()
        pal.stop()  # Should not raise.
        assert pal.running is False

    def test_serve_forever_processes_request_and_exits_on_stop(self) -> None:
        pal = PolicyAgentListener(
            _make_config(port=0),
            handler=_allow_handler,
            dev_mode=True,
        )
        assert pal.start() is True
        port = pal.listener.bound_port
        assert port is not None

        stop_event = threading.Event()
        loop_thread = threading.Thread(
            target=pal.serve_forever,
            args=(stop_event,),
            daemon=True,
        )
        loop_thread.start()

        framer = MessageFramer()
        client = VsockTransport(_make_config(port=int(port)), dev_mode=True)
        assert client.connect() is True

        req = AdjudicationRequest(car_json='{"verb":"READ"}', request_id="loop-1")
        assert client.send(framer.encode_request(req)) is True

        raw_resp = client.receive()
        assert raw_resp is not None
        resp = framer.decode_response(raw_resp)
        assert resp.decision == "ALLOW"

        client.close()
        stop_event.set()
        pal.stop()
        loop_thread.join(timeout=2.0)

        assert not loop_thread.is_alive()
        assert pal.request_count >= 1


# =====================================================================
# Group F: End-to-end — full client→listener→handler flow
# =====================================================================


class TestPolicyAgentListenerEndToEnd:
    """Full integration: client connects, sends CAR, gets JWT back."""

    def test_full_allow_flow(self) -> None:
        """Client → PA → ALLOW + JWT → Client."""
        cfg = _make_config(port=0)
        pal = PolicyAgentListener(cfg, handler=_allow_handler, dev_mode=True)
        assert pal.start() is True
        port = pal.listener.bound_port
        assert port is not None

        def server_loop() -> None:
            st = pal.listener.accept()
            if st is not None:
                pal.handle_connection(st)
                st.close()

        t = threading.Thread(target=server_loop, daemon=True)
        t.start()

        framer = MessageFramer()
        client_cfg = _make_config(port=port)
        client = VsockTransport(client_cfg, dev_mode=True)
        assert client.connect() is True

        req = AdjudicationRequest(
            car_json='{"verb":"READ","resource":"/data","agent":"assistant"}',
            request_id="e2e-1",
        )
        assert client.send(framer.encode_request(req)) is True

        raw_resp = client.receive()
        assert raw_resp is not None
        resp = framer.decode_response(raw_resp)
        assert resp.decision == "ALLOW"
        assert resp.jwt_token == "test-jwt-token"
        assert resp.request_id == "e2e-1"

        client.close()
        t.join(timeout=2.0)
        pal.stop()
        assert pal.request_count == 1
        assert pal.rejection_count == 0

    def test_full_deny_flow(self) -> None:
        """Client → PA → DENY → Client (no JWT)."""
        cfg = _make_config(port=0)
        pal = PolicyAgentListener(cfg, handler=_deny_handler, dev_mode=True)
        assert pal.start() is True
        port = pal.listener.bound_port
        assert port is not None

        def server_loop() -> None:
            st = pal.listener.accept()
            if st is not None:
                pal.handle_connection(st)
                st.close()

        t = threading.Thread(target=server_loop, daemon=True)
        t.start()

        framer = MessageFramer()
        client = VsockTransport(_make_config(port=int(port)), dev_mode=True)
        assert client.connect() is True

        req = AdjudicationRequest(
            car_json='{"verb":"DELETE","resource":"/secrets"}',
            request_id="e2e-2",
        )
        assert client.send(framer.encode_request(req)) is True

        raw_resp = client.receive()
        assert raw_resp is not None
        resp = framer.decode_response(raw_resp)
        assert resp.decision == "DENY"
        assert resp.jwt_token == ""
        assert resp.error == "blocked_by_test"

        client.close()
        t.join(timeout=2.0)
        pal.stop()
        assert pal.rejection_count == 1

    def test_full_handler_error_flow(self) -> None:
        """Client → PA → handler exception → DENY + error → Client."""
        cfg = _make_config(port=0)
        pal = PolicyAgentListener(
            cfg, handler=_error_handler, dev_mode=True
        )
        assert pal.start() is True
        port = pal.listener.bound_port
        assert port is not None

        def server_loop() -> None:
            st = pal.listener.accept()
            if st is not None:
                pal.handle_connection(st)
                st.close()

        t = threading.Thread(target=server_loop, daemon=True)
        t.start()

        framer = MessageFramer()
        client = VsockTransport(_make_config(port=int(port)), dev_mode=True)
        assert client.connect() is True

        req = AdjudicationRequest(car_json='{"v":"X"}', request_id="e2e-3")
        assert client.send(framer.encode_request(req)) is True

        raw_resp = client.receive()
        assert raw_resp is not None
        resp = framer.decode_response(raw_resp)
        assert resp.decision == "DENY"
        assert "Handler error" in resp.error

        client.close()
        t.join(timeout=2.0)
        pal.stop()

    def test_heartbeat_through_connection(self) -> None:
        """Client sends heartbeat → PA responds with alive."""
        cfg = _make_config(port=0)
        pal = PolicyAgentListener(
            cfg, handler=_allow_handler, dev_mode=True
        )
        assert pal.start() is True
        port = pal.listener.bound_port
        assert port is not None

        def server_loop() -> None:
            st = pal.listener.accept()
            if st is not None:
                pal.handle_connection(st)
                st.close()

        t = threading.Thread(target=server_loop, daemon=True)
        t.start()

        framer = MessageFramer()
        client = VsockTransport(_make_config(port=int(port)), dev_mode=True)
        assert client.connect() is True

        hb_data = framer.encode_heartbeat("hb-e2e")
        assert client.send(hb_data) is True

        raw_resp = client.receive()
        assert raw_resp is not None
        msg_type, rid, payload = framer.decode(raw_resp)
        assert msg_type == MessageType.HEARTBEAT
        assert payload["status"] == "alive"

        client.close()
        t.join(timeout=2.0)
        pal.stop()


# =====================================================================
# Group G: P0-1 — mTLS CN vs source_agent validation
# =====================================================================


class TestCNValidation:
    """handle_request peer_cn vs car.source_agent validation (P0-1)."""

    def _make_car_json(self, source_agent: str = "blarai-orchestrator") -> str:
        return json.dumps({
            "source_agent": source_agent,
            "destination_service": "substrate",
            "verb": "READ",
            "resource": "substrate.vector_store",
            "sensitivity": "INTERNAL",
            "session_id": "sess-cn-test-001",
            "request_id": "car-req-cn-001",
        })

    def test_handle_request_skips_cn_validation_when_peer_cn_none(
        self,
    ) -> None:
        """peer_cn=None (dev_mode) → CN validation skipped, allow handler invoked."""
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )
        car_json = self._make_car_json(source_agent="blarai-orchestrator")
        req = AdjudicationRequest(car_json=car_json, request_id="cn-skip-1")
        raw = framer.encode_request(req)

        resp_bytes = pal.handle_request(raw, peer_cn=None)
        resp = framer.decode_response(resp_bytes)
        assert resp.decision == "ALLOW"

    def test_handle_request_allows_on_cn_match(self) -> None:
        """peer_cn matches car.source_agent → CN validation passes."""
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )
        car_json = self._make_car_json(source_agent="blarai-orchestrator")
        req = AdjudicationRequest(car_json=car_json, request_id="cn-match-1")
        raw = framer.encode_request(req)

        resp_bytes = pal.handle_request(raw, peer_cn="blarai-orchestrator")
        resp = framer.decode_response(resp_bytes)
        assert resp.decision == "ALLOW"
        assert resp.error == ""

    def test_handle_request_denies_on_cn_mismatch(self) -> None:
        """peer_cn != car.source_agent → DENY + SOURCE_AGENT_CN_MISMATCH."""
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )
        car_json = self._make_car_json(source_agent="blarai-coder")
        req = AdjudicationRequest(car_json=car_json, request_id="cn-mismatch-1")
        raw = framer.encode_request(req)

        initial_rejections = pal.rejection_count
        resp_bytes = pal.handle_request(raw, peer_cn="blarai-orchestrator")
        resp = framer.decode_response(resp_bytes)
        assert resp.decision == "DENY"
        assert resp.error == "SOURCE_AGENT_CN_MISMATCH"
        assert pal.rejection_count == initial_rejections + 1

    def test_handle_request_cn_mismatch_does_not_call_handler(self) -> None:
        """CN mismatch → handler is never invoked (short-circuit)."""
        handler_calls: list[str] = []

        def counting_handler(
            car_json: str, request_id: str
        ) -> AdjudicationResponse:
            handler_calls.append(request_id)
            return AdjudicationResponse(
                decision="ALLOW", request_id=request_id
            )

        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=counting_handler, dev_mode=True
        )
        car_json = self._make_car_json(source_agent="attacker-agent")
        req = AdjudicationRequest(car_json=car_json, request_id="cn-nohandler-1")
        raw = framer.encode_request(req)

        pal.handle_request(raw, peer_cn="blarai-orchestrator")
        assert handler_calls == [], "Handler must not be called on CN mismatch"

    def test_handle_request_cn_mismatch_increments_rejection_count(
        self,
    ) -> None:
        """Each CN mismatch increments rejection_count by exactly 1."""
        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )
        framer2 = MessageFramer()
        for i in range(3):
            car_json = self._make_car_json(source_agent=f"agent-{i}")
            req = AdjudicationRequest(
                car_json=car_json, request_id=f"cn-count-{i}"
            )
            raw = framer2.encode_request(req)
            pal.handle_request(raw, peer_cn="different-peer")

        assert pal.rejection_count == 3

    def test_handle_connection_passes_peer_cn_to_handle_request(
        self,
    ) -> None:
        """handle_connection extracts transport.peer_cn and passes it through."""
        from unittest.mock import MagicMock

        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )
        car_json = self._make_car_json(source_agent="blarai-orchestrator")
        req = AdjudicationRequest(car_json=car_json, request_id="conn-cn-1")
        raw = framer.encode_request(req)

        # Build a mock transport with a matching peer_cn.
        transport = MagicMock()
        transport.receive.return_value = raw
        transport.peer_cn = "blarai-orchestrator"
        transport.send.return_value = True

        result = pal.handle_connection(transport)
        assert result is True

        # Verify the response that was sent is ALLOW.
        sent_bytes = transport.send.call_args[0][0]
        resp = framer.decode_response(sent_bytes)
        assert resp.decision == "ALLOW"

    def test_handle_connection_cn_mismatch_sends_deny(self) -> None:
        """handle_connection with mismatched peer_cn sends DENY response."""
        from unittest.mock import MagicMock

        framer = MessageFramer()
        pal = PolicyAgentListener(
            _make_config(), handler=_allow_handler, dev_mode=True
        )
        car_json = self._make_car_json(source_agent="blarai-coder")
        req = AdjudicationRequest(car_json=car_json, request_id="conn-mismatch-1")
        raw = framer.encode_request(req)

        transport = MagicMock()
        transport.receive.return_value = raw
        transport.peer_cn = "blarai-orchestrator"  # mismatch
        transport.send.return_value = True

        pal.handle_connection(transport)

        sent_bytes = transport.send.call_args[0][0]
        resp = framer.decode_response(sent_bytes)
        assert resp.decision == "DENY"
        assert resp.error == "SOURCE_AGENT_CN_MISMATCH"
