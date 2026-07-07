"""
vsock IPC Listener — Policy Agent
====================================
USE-CASE-001, P1.6: Exposes the Policy Agent's adjudication API over
vsock + mTLS.
S15-EA-4d: Fidelity-2 host-mode transport wired here.

All inter-agent communication flows through this listener. The protocol:
  1. Agent connects via vsock + mTLS (or TCP loopback in dev_mode).
  2. Agent sends a length-prefixed AdjudicationRequest (serialized CAR).
  3. PA deserializes the CAR, invokes the adjudication handler.
  4. PA returns a length-prefixed AdjudicationResponse (JWT or DENY).

The adjudication handler is injected as a callback — this decouples the
IPC layer from the HybridAdjudicator + AgenticJWTMinter implementations,
enabling clean unit testing and future handler swapping.

Security:
  - Production host-mode (default): loopback + mTLS — zero external
    network exposure, air-gap compliant (fidelity-2 / SDV §4).
  - Production guest-mode (reserved, #615): AF_HYPERV + mTLS.
  - mTLS mandatory in production — bare connections rejected.
  - Maximum message size enforced (prevents unbounded reads).
  - Fail-Closed: any parsing error, handler failure, or connection
    issue produces a DENY response. No request is silently dropped.
  - No external network calls.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Protocol

from shared.ipc.protocol import (
    AdjudicationRequest,
    AdjudicationResponse,
    MessageFramer,
    MessageType,
)
from shared.ipc.vsock import VsockConfig, VsockListener, VsockTransport
from shared.schemas.car import CanonicalActionRepresentation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Adjudication handler protocol
# ---------------------------------------------------------------------------


class AdjudicationHandler(Protocol):
    """Protocol for the adjudication callback.

    The PolicyAgentListener delegates adjudication to a handler
    conforming to this interface. In production, this is wired to
    HybridAdjudicator + AgenticJWTMinter. In tests, a stub or mock.
    """

    def __call__(
        self, car_json: str, request_id: str
    ) -> AdjudicationResponse: ...


def default_deny_handler(
    car_json: str, request_id: str
) -> AdjudicationResponse:
    """Fail-Closed default: deny all requests.

    Used when no adjudicator is configured — ensures the listener
    never silently accepts requests without a handler.
    """
    return AdjudicationResponse(
        decision="DENY",
        request_id=request_id,
        error="NO_ADJUDICATOR_CONFIGURED",
    )


# ---------------------------------------------------------------------------
# Policy Agent Listener
# ---------------------------------------------------------------------------


class PolicyAgentListener:
    """vsock listener for the Policy Agent adjudication API.

    Lifecycle:
      1. __init__: Configure vsock address, mTLS certs, and handler.
      2. start(): Bind and listen for incoming agent connections.
      3. handle_connection(transport): Process one request/response on
         an accepted connection.
      4. handle_request(raw_data): Process raw JSON bytes, return
         response JSON bytes.
      5. stop(): Shutdown the listener.

    The listener processes one request per connection (single-use
    connections per architectural design). The caller controls the
    accept loop.
    """

    def __init__(
        self,
        config: VsockConfig,
        *,
        handler: AdjudicationHandler | None = None,
        dev_mode: bool = False,
        host_mode: bool = True,
    ) -> None:
        self._config = config
        self._handler: AdjudicationHandler = handler or default_deny_handler
        self._dev_mode = dev_mode
        self._host_mode = host_mode
        self._listener = VsockListener(config, dev_mode=dev_mode, host_mode=host_mode)
        self._framer = MessageFramer(config.max_message_bytes)
        self._running = False
        self._request_count = 0
        self._rejection_count = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def request_count(self) -> int:
        """Total number of requests processed."""
        return self._request_count

    @property
    def rejection_count(self) -> int:
        """Total number of requests rejected (DENY or error)."""
        return self._rejection_count

    @property
    def running(self) -> bool:
        """Whether the listener is currently accepting connections."""
        return self._running

    @property
    def handler(self) -> AdjudicationHandler:
        """The current adjudication handler."""
        return self._handler

    @property
    def listener(self) -> VsockListener:
        """The underlying VsockListener (for bound_port access in tests)."""
        return self._listener

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Bind to the vsock address and begin listening.

        Returns:
            True if the listener started successfully.
            False on any error (Fail-Closed — service does not degrade).
        """
        if self._listener.start():
            self._running = True
            return True
        return False

    def stop(self) -> None:
        """Shutdown the listener and release resources."""
        self._running = False
        self._listener.stop()

    def serve_forever(
        self,
        stop_event: threading.Event,
        *,
        idle_sleep_s: float = 0.01,
    ) -> None:
        """Run the real accept/dispatch/respond service loop.

        The loop exits when either:
          - ``stop_event`` is set by the caller, or
          - ``stop()`` has been called and ``running`` is False.

        Args:
            stop_event: External shutdown signal from the service lifecycle.
            idle_sleep_s: Sleep duration used after empty accept() polls.
        """
        while self._running and not stop_event.is_set():
            try:
                transport = self._listener.accept()
                if transport is None:
                    if idle_sleep_s > 0:
                        time.sleep(idle_sleep_s)
                    continue

                try:
                    ok = self.handle_connection(transport)
                    if not ok:
                        logger.warning(
                            "PolicyAgentListener connection handling failed (Fail-Closed)."
                        )
                except Exception as exc:  # noqa: BLE001
                    self._rejection_count += 1
                    logger.error(
                        "PolicyAgentListener service loop handler error (Fail-Closed): %s",
                        exc,
                    )
                finally:
                    transport.close()

            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "PolicyAgentListener accept loop error (Fail-Closed): %s",
                    exc,
                )
                if idle_sleep_s > 0:
                    time.sleep(idle_sleep_s)

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    def handle_request(self, raw_data: bytes, *, peer_cn: str | None = None) -> bytes:
        """Process a single adjudication request from raw JSON bytes.

        This is the core processing method. It:
          1. Decodes the JSON envelope.
          2. Routes by message type.
          3. For ADJUDICATION_REQUEST: parses the CAR, validates peer_cn
             against car.source_agent (when peer_cn is not None), then
             calls the handler.
          4. Returns encoded response bytes (JSON, no framing header).

        Args:
            raw_data: JSON-encoded message bytes (framing header already
                      stripped by VsockTransport.receive()).
            peer_cn: mTLS peer certificate Common Name extracted from the
                     accepted connection.  None in dev_mode (skips CN
                     validation so tests continue to work without certs).

        Returns:
            JSON-encoded response bytes for VsockTransport.send().

        Fail-Closed: malformed input, CN mismatch, or handler failure
            returns DENY/ERROR response.
        """
        self._request_count += 1

        try:
            msg_type, request_id, payload = self._framer.decode(raw_data)
        except ValueError as exc:
            self._rejection_count += 1
            return self._framer.encode_error(
                f"Malformed message: {exc}"
            )

        # Route by message type.
        if msg_type == MessageType.HEARTBEAT:
            return self._framer.encode_heartbeat(request_id)

        if msg_type == MessageType.ERROR:
            # Client sent us an error — acknowledge and log.
            logger.warning(
                "Client error received: %s", payload.get("error", "")
            )
            self._rejection_count += 1
            return self._framer.encode_error(
                "Error acknowledged", request_id
            )

        if msg_type == MessageType.HANDSHAKE_REQUEST:
            # Boot-Phase-3: gateway probes PA liveness before accepting
            # connections.  Respond OPERATIONAL so the gateway can proceed.
            return self._framer.encode_handshake_response(
                "OPERATIONAL",
                request_id=request_id,
            )

        if msg_type != MessageType.ADJUDICATION_REQUEST:
            self._rejection_count += 1
            return self._framer.encode_error(
                f"Unsupported message type: {msg_type.value}",
                request_id,
            )

        # Parse the adjudication request.
        adj_request = AdjudicationRequest.from_dict(payload)
        if not adj_request.car_json or not adj_request.request_id:
            self._rejection_count += 1
            return self._framer.encode_error(
                "Missing car_json or request_id",
                request_id,
            )

        # P0-1: Validate peer CN against car.source_agent (mTLS identity binding).
        # Skip when peer_cn is None — dev_mode has no cert, tests must not break.
        if peer_cn is not None:
            try:
                car = CanonicalActionRepresentation.model_validate_json(
                    adj_request.car_json
                )
                if car.source_agent != peer_cn:
                    logger.warning(
                        "CN mismatch: peer_cn=%r car.source_agent=%r — DENY",
                        peer_cn,
                        car.source_agent,
                    )
                    self._rejection_count += 1
                    return self._framer.encode_response(
                        AdjudicationResponse(
                            decision="DENY",
                            request_id=adj_request.request_id,
                            error="SOURCE_AGENT_CN_MISMATCH",
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "CN validation failed (Fail-Closed): %s", exc
                )
                self._rejection_count += 1
                return self._framer.encode_response(
                    AdjudicationResponse(
                        decision="DENY",
                        request_id=adj_request.request_id,
                        error="SOURCE_AGENT_CN_VALIDATION_ERROR",
                    )
                )

        # Invoke the adjudication handler.
        try:
            response = self._handler(
                adj_request.car_json, adj_request.request_id
            )
        except Exception as exc:
            logger.error("Adjudication handler failed: %s", exc)
            self._rejection_count += 1
            return self._framer.encode_response(
                AdjudicationResponse(
                    decision="DENY",
                    request_id=adj_request.request_id,
                    error=f"Handler error: {exc}",
                )
            )

        if response.decision != "ALLOW":
            self._rejection_count += 1

        return self._framer.encode_response(response)

    def handle_connection(self, transport: VsockTransport) -> bool:
        """Process a single request/response cycle on a connection.

        Reads one framed message from the transport, processes it via
        handle_request(), and sends the framed response back.

        The peer_cn from the transport's mTLS certificate is forwarded
        to handle_request() for CN vs source_agent validation.

        Args:
            transport: An accepted VsockTransport connection.

        Returns:
            True if the request was processed and response sent.
            False if the connection was broken or data was unreadable.
        """
        raw = transport.receive()
        if raw is None:
            return False

        response_bytes = self.handle_request(raw, peer_cn=transport.peer_cn)
        return transport.send(response_bytes)
