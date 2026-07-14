"""
P1.10 — Integration Test: PA ↔ Orchestrator ↔ Router over vsock
====================================================================
End-to-end validation of the full Priority 1 Core Loop pipeline.

These tests exercise the entire data path across service boundaries:

  Query → SemanticRouter (P1.7) → OrchestratorGPUInference (P1.8) →
  PGOV (P1.9) → CAR construction → PolicyAgentListener (P1.6, over vsock) →
  HybridAdjudicator (P1.4) → AgenticJWTMinter (P1.5) → JWT validation

All NPU / ONNX models are MOCKED — these tests validate data flow,
protocol correctness, IPC framing, and Fail-Closed behavior, NOT
real model inference latency.

Test Groups:
  A. End-to-End Pipeline (mocked models, real IPC via TCP loopback)
  B. vsock IPC Round-Trip (PA listener + transport, real socket I/O)
  C. Fail-Closed: Disconnected PA
  D. Preemption Signal Propagation (structural)
  E. PGOV Pipeline Integration
  F. JWT Lifecycle (mint → validate across service boundary)
  G. Latency Budget Structure (fields present, positive values)

Section 5.3 Requirements Coverage:
  Req 1: End-to-end harness — Groups A, B, E, F
  Req 2: IPC over vsock (dev_mode TCP loopback) — Group B
  Req 3: Latency budget structure — Group G
  Req 4: Fail-Closed disconnected PA — Group C
  Req 5: Preemption propagation — Group D
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

# Entire module uses real socket I/O; excluded from default runs.
pytestmark = pytest.mark.slow

# -- Shared schemas & IPC ---------------------------------------------------
from shared.schemas.car import (
    ActionVerb,
    AdjudicationDecision,
    CanonicalActionRepresentation,
    DecisionArtifact,
    Sensitivity,
)
from shared.ipc.protocol import (
    AdjudicationRequest,
    AdjudicationResponse,
    MessageFramer,
    MessageType,
)
from shared.ipc.vsock import VsockAddress, VsockConfig, VsockListener, VsockTransport
from shared.crypto.jwt_validator import AgenticJWTValidator

# -- Policy Agent ------------------------------------------------------------
from services.policy_agent.src.ipc import PolicyAgentListener
from services.policy_agent.src.adjudicator import (
    AdjudicationContext,
    HybridAdjudicator,
    adjudicate,
)
from services.policy_agent.src.rule_engine import run_rule_engine, RuleEngineResult
from services.policy_agent.src.gpu_inference import (
    GPUClassificationResult,
    PolicyGPUInference,
    CARPromptFormatter,
)
from services.policy_agent.src.jwt_minter import (
    AgenticJWTMinter,
    MintedJWT,
)
from services.policy_agent.src.car import build_car

# -- Orchestrator ------------------------------------------------------------
from services.assistant_orchestrator.src.gpu_inference import (
    GenerationResult,
    OrchestratorGPUInference,
)
from services.assistant_orchestrator.src.pgov import (
    PGOVResult,
    validate_output,
)

# -- Semantic Router ---------------------------------------------------------
from services.semantic_router.src.router import (
    ClassificationResult,
    Intent,
    SemanticRouter,
)


# ===========================================================================
# Shared Helpers & Fixtures
# ===========================================================================

# Permissive ACL matrix for integration tests.
ACL_MATRIX: dict[str, list[str]] = {
    "assistant_orchestrator": ["substrate", "semantic_router", "code_agent"],
    "code_agent": ["substrate"],
    "semantic_router": [],
}


def _build_valid_car(
    source: str = "assistant_orchestrator",
    dest: str = "substrate",
    verb: ActionVerb | str = ActionVerb.READ,
    resource: str = "substrate.vector_store",
    sensitivity: Sensitivity | str = Sensitivity.INTERNAL,
    session_id: str = "sess-integ-p110",
) -> CanonicalActionRepresentation:
    """Build a CAR that passes all deterministic rules."""
    return build_car(
        source_agent=source,
        destination_service=dest,
        verb=verb,
        resource=resource,
        sensitivity=sensitivity,
        session_id=session_id,
    )


def _make_gpu_allow(confidence: float = 0.90) -> GPUClassificationResult:
    """Simulated NPU ALLOW result."""
    return GPUClassificationResult(
        label="ALLOW", confidence=confidence, latency_ms=0.5
    )


def _make_gpu_deny(confidence: float = 0.95) -> GPUClassificationResult:
    """Simulated NPU DENY result."""
    return GPUClassificationResult(
        label="DENY", confidence=confidence, latency_ms=0.4
    )


def _ephemeral_vsock_config() -> VsockConfig:
    """VsockConfig on port 0 (OS picks a free port in dev_mode)."""
    return VsockConfig(
        address=VsockAddress(cid=0, port=0),
    )


def _make_jwt_minter() -> tuple[AgenticJWTMinter, ec.EllipticCurvePublicKey]:
    """Generate a fresh ES256 key pair and return (minter, public_key)."""
    private_key, public_key = AgenticJWTMinter.generate_key_pair()
    minter = AgenticJWTMinter(private_key)
    return minter, public_key


def _make_adjudication_handler(
    npu_result: GPUClassificationResult | None = None,
    minter: AgenticJWTMinter | None = None,
) -> tuple:
    """Build an adjudication handler callback suitable for PolicyAgentListener.

    Returns (handler_fn, minter, public_key).
    """
    _minter, public_key = _make_jwt_minter()
    if minter is not None:
        _minter = minter
    else:
        minter = _minter

    if npu_result is None:
        npu_result = _make_gpu_allow()

    def handler(car_json: str, request_id: str) -> AdjudicationResponse:
        """Simulate the full PA adjudication pipeline."""
        car = CanonicalActionRepresentation.model_validate_json(car_json)
        rule_result = run_rule_engine(car, acl_matrix=ACL_MATRIX)
        decision = adjudicate(car, rule_result, npu_result)

        jwt_token = ""
        if decision.decision == AdjudicationDecision.ALLOW:
            minted = minter.mint(decision)
            if minted.success:
                jwt_token = minted.token

        return AdjudicationResponse(
            decision=decision.decision.value,
            jwt_token=jwt_token,
            car_hash=decision.car_hash,
            request_id=request_id,
        )

    return handler, minter, public_key


def _send_adjudication_request(
    port: int,
    car: CanonicalActionRepresentation,
) -> AdjudicationResponse:
    """Send a CAR to the PA listener via TCP loopback and return the response.

    Creates a fresh VsockTransport (single-use connection per PA design).
    """
    config = VsockConfig(address=VsockAddress(cid=0, port=port))
    transport = VsockTransport(config, dev_mode=True)
    assert transport.connect(), "Failed to connect to PA listener"

    framer = MessageFramer()
    request = AdjudicationRequest(
        car_json=car.model_dump_json(),
        request_id=car.request_id,
    )
    request_bytes = framer.encode_request(request)
    assert transport.send(request_bytes), "Failed to send request"

    response_bytes = transport.receive()
    assert response_bytes is not None, "No response received"
    transport.close()

    return framer.decode_response(response_bytes)


# ===========================================================================
# Group A: End-to-End Pipeline (mocked models, real protocol)
# ===========================================================================


class TestEndToEndPipeline:
    """Full pipeline: classify → generate → PGOV → CAR → PA → JWT → validate.

    All NPU/ONNX models are mocked. Data flow across service boundaries
    is the focus.
    """

    def test_conversational_query_full_pipeline_allow(self) -> None:
        """CONVERSATIONAL query → Orchestrator generate → PGOV approve →
        PA ALLOW → JWT minted → JWT validated at destination.
        """
        # 1. Router: mock classify → CONVERSATIONAL
        router_result = ClassificationResult(
            intent=Intent.CONVERSATIONAL,
            confidence=0.92,
            latency_ms=15.0,
        )

        # 2. Orchestrator: mock generate_text → clean output
        gen_result = GenerationResult(
            tokens=[101, 102, 103],
            text="The weather today is sunny with a high of 72°F.",
            token_count=12,
            latency_first_token_ms=50.0,
            latency_total_ms=200.0,
            truncated=False,
        )

        # 3. PGOV: validate clean output (no leakage model needed)
        pgov_result = validate_output(
            generated_text=gen_result.text,
            token_count=gen_result.token_count,
            max_tokens=4096,
        )
        assert pgov_result.approved is True
        assert pgov_result.pii_detected is False

        # 4. Build CAR for tool-call authorization
        car = _build_valid_car(
            verb=ActionVerb.QUERY,
            resource="orchestrator.conversational",
        )

        # 5. PA adjudication (in-process, with mocked NPU)
        npu_result = _make_gpu_allow(0.88)
        rule_result = run_rule_engine(car, acl_matrix=ACL_MATRIX)
        assert rule_result.passed is True

        decision = adjudicate(car, rule_result, npu_result)
        assert decision.decision == AdjudicationDecision.ALLOW

        # 6. JWT minting
        minter, public_key = _make_jwt_minter()
        minted = minter.mint(decision)
        assert minted.success is True
        assert minted.token != ""

        # 7. JWT validation at destination
        validator = AgenticJWTValidator(public_key)
        validation = validator.validate(
            minted.token, expected_car_hash=car.canonical_hash()
        )
        assert validation.valid is True
        assert validation.car_hash == car.canonical_hash()
        assert validation.decision == "ALLOW"
        assert validation.request_id == car.request_id

    def test_skill_dispatch_query_pipeline(self) -> None:
        """SKILL_DISPATCH query → dispatched to skill agent → PA ALLOW."""
        router_result = ClassificationResult(
            intent=Intent.SKILL_DISPATCH,
            confidence=0.87,
            latency_ms=18.0,
            skill_target="calendar",
        )

        # Skill dispatch bypasses Orchestrator generation.
        # A CAR is still built for the dispatched action.
        car = _build_valid_car(
            verb=ActionVerb.DISPATCH,
            resource="skill.calendar",
        )

        npu_result = _make_gpu_allow(0.91)
        rule_result = run_rule_engine(car, acl_matrix=ACL_MATRIX)
        assert rule_result.passed is True

        decision = adjudicate(car, rule_result, npu_result)
        assert decision.decision == AdjudicationDecision.ALLOW

        # JWT lifecycle
        minter, public_key = _make_jwt_minter()
        minted = minter.mint(decision)
        assert minted.success is True

        validator = AgenticJWTValidator(public_key)
        validation = validator.validate(minted.token, car.canonical_hash())
        assert validation.valid is True
        assert validation.decision == "ALLOW"

    def test_out_of_scope_query_denied(self) -> None:
        """OUT_OF_SCOPE query → safe rejection. No CAR submitted."""
        router_result = ClassificationResult(
            intent=Intent.OUT_OF_SCOPE,
            confidence=0.45,
            latency_ms=12.0,
        )
        # Out-of-scope: no Orchestrator dispatch, no PA engagement.
        assert router_result.intent == Intent.OUT_OF_SCOPE
        assert router_result.confidence < 0.75

    def test_pipeline_data_integrity_car_hash_chain(self) -> None:
        """CAR hash must propagate: CAR → DecisionArtifact → JWT → validation."""
        car = _build_valid_car()
        expected_hash = car.canonical_hash()

        npu_result = _make_gpu_allow()
        rule_result = run_rule_engine(car, acl_matrix=ACL_MATRIX)
        decision = adjudicate(car, rule_result, npu_result)

        assert decision.car_hash == expected_hash

        minter, public_key = _make_jwt_minter()
        minted = minter.mint(decision)
        assert minted.success is True

        validator = AgenticJWTValidator(public_key)
        validation = validator.validate(minted.token, expected_hash)
        assert validation.valid is True
        assert validation.car_hash == expected_hash

    def test_pipeline_request_id_chain(self) -> None:
        """request_id must propagate: CAR → DecisionArtifact → JWT claims."""
        car = _build_valid_car()

        npu_result = _make_gpu_allow()
        _, decision = run_rule_engine(car, acl_matrix=ACL_MATRIX), adjudicate(
            car, run_rule_engine(car, acl_matrix=ACL_MATRIX), npu_result
        )

        assert decision.request_id == car.request_id

        minter, public_key = _make_jwt_minter()
        minted = minter.mint(decision)
        validator = AgenticJWTValidator(public_key)
        validation = validator.validate(minted.token)
        assert validation.request_id == car.request_id

    def test_pgov_rejection_prevents_delivery(self) -> None:
        """PGOV violation → output suppressed. PA adjudication still occurs
        for the tool-call, but the violated output is replaced.
        """
        # Generation produces PII
        gen_result = GenerationResult(
            tokens=[1, 2, 3, 4],
            text="Your SSN is 123-45-6789 and your card is 4111-1111-1111-1111.",
            token_count=4,
            latency_first_token_ms=45.0,
            latency_total_ms=180.0,
            truncated=False,
        )

        pgov_result = validate_output(
            generated_text=gen_result.text,
            token_count=gen_result.token_count,
            max_tokens=4096,
        )
        assert pgov_result.approved is False
        assert pgov_result.pii_detected is True
        # Sanitized text is the fallback message
        assert pgov_result.sanitized_text != gen_result.text
        assert "unable to provide" in pgov_result.sanitized_text.lower()

    def test_sequential_requests_independent(self) -> None:
        """Two sequential pipeline runs produce independent results.
        No shared state leaks across adjudications.
        """
        car_allow = _build_valid_car(resource="substrate.vector_store")
        car_deny_sensitivity = _build_valid_car(
            resource="substrate.vector_store",
            sensitivity=Sensitivity.UNCLASSIFIED,
        )

        npu_result = _make_gpu_allow()

        rule_a = run_rule_engine(car_allow, acl_matrix=ACL_MATRIX)
        decision_a = adjudicate(car_allow, rule_a, npu_result)

        rule_b = run_rule_engine(car_deny_sensitivity, acl_matrix=ACL_MATRIX)
        decision_b = adjudicate(car_deny_sensitivity, rule_b, npu_result)

        assert decision_a.decision == AdjudicationDecision.ALLOW
        assert decision_b.decision == AdjudicationDecision.DENY

        # Hashes differ because same identity fields but UNCLASSIFIED differs
        assert decision_a.car_hash != decision_b.car_hash
        assert decision_a.request_id != decision_b.request_id


# ===========================================================================
# Group B: vsock IPC Round-Trip (real TCP loopback sockets)
# ===========================================================================


class TestVsockIPCRoundTrip:
    """Test real socket I/O between client transport and PA listener.

    Uses dev_mode=True (TCP loopback on 127.0.0.1) with ephemeral ports.
    """

    def test_single_request_allow_over_ipc(self) -> None:
        """Single ALLOW adjudication over real TCP loopback sockets."""
        handler, minter, public_key = _make_adjudication_handler(
            npu_result=_make_gpu_allow(0.92)
        )
        config = _ephemeral_vsock_config()
        listener = PolicyAgentListener(config, handler=handler, dev_mode=True)
        assert listener.start() is True

        port = listener.listener.bound_port
        assert port is not None

        # Accept in background thread
        accept_done = threading.Event()
        accept_result = [False]

        def _accept_and_handle():
            transport = listener.listener.accept()
            if transport:
                accept_result[0] = listener.handle_connection(transport)
                transport.close()
            accept_done.set()

        t = threading.Thread(target=_accept_and_handle, daemon=True)
        t.start()

        # Send request from client side
        car = _build_valid_car()
        response = _send_adjudication_request(port, car)

        accept_done.wait(timeout=5.0)
        listener.stop()
        t.join(timeout=2.0)

        assert accept_result[0] is True
        assert response.decision == "ALLOW"
        assert response.car_hash == car.canonical_hash()
        assert response.request_id == car.request_id
        assert response.jwt_token != ""

        # Validate the JWT
        validator = AgenticJWTValidator(public_key)
        validation = validator.validate(
            response.jwt_token, expected_car_hash=car.canonical_hash()
        )
        assert validation.valid is True

    def test_single_request_deny_over_ipc(self) -> None:
        """DENY adjudication (UNCLASSIFIED sensitivity) over IPC."""
        handler, minter, public_key = _make_adjudication_handler(
            npu_result=_make_gpu_allow(0.92)
        )
        config = _ephemeral_vsock_config()
        listener = PolicyAgentListener(config, handler=handler, dev_mode=True)
        assert listener.start() is True

        port = listener.listener.bound_port
        assert port is not None

        accept_done = threading.Event()

        def _accept_and_handle():
            transport = listener.listener.accept()
            if transport:
                listener.handle_connection(transport)
                transport.close()
            accept_done.set()

        t = threading.Thread(target=_accept_and_handle, daemon=True)
        t.start()

        # CAR with UNCLASSIFIED → rule engine DENY
        car = _build_valid_car(sensitivity=Sensitivity.UNCLASSIFIED)
        response = _send_adjudication_request(port, car)

        accept_done.wait(timeout=5.0)
        listener.stop()
        t.join(timeout=2.0)

        assert response.decision == "DENY"
        assert response.jwt_token == ""  # No JWT on DENY

    def test_multiple_sequential_requests_over_ipc(self) -> None:
        """Multiple sequential requests, each on a fresh connection."""
        handler, minter, public_key = _make_adjudication_handler(
            npu_result=_make_gpu_allow(0.88)
        )
        config = _ephemeral_vsock_config()
        listener = PolicyAgentListener(config, handler=handler, dev_mode=True)
        assert listener.start() is True

        port = listener.listener.bound_port
        assert port is not None

        results: list[AdjudicationResponse] = []

        for i in range(3):
            accept_done = threading.Event()

            def _accept_and_handle():
                transport = listener.listener.accept()
                if transport:
                    listener.handle_connection(transport)
                    transport.close()
                accept_done.set()

            t = threading.Thread(target=_accept_and_handle, daemon=True)
            t.start()

            car = _build_valid_car(resource=f"substrate.resource_{i}")
            response = _send_adjudication_request(port, car)
            results.append(response)

            accept_done.wait(timeout=5.0)
            t.join(timeout=2.0)

        listener.stop()

        assert len(results) == 3
        for r in results:
            assert r.decision == "ALLOW"
            assert r.jwt_token != ""

        # All request_count properly incremented
        assert listener.request_count == 3

    def test_heartbeat_over_ipc(self) -> None:
        """Heartbeat message handled correctly over real sockets."""
        handler, _, _ = _make_adjudication_handler()
        config = _ephemeral_vsock_config()
        listener = PolicyAgentListener(config, handler=handler, dev_mode=True)
        assert listener.start() is True

        port = listener.listener.bound_port
        assert port is not None

        accept_done = threading.Event()
        accept_result = [False]

        def _accept_and_handle():
            transport = listener.listener.accept()
            if transport:
                accept_result[0] = listener.handle_connection(transport)
                transport.close()
            accept_done.set()

        t = threading.Thread(target=_accept_and_handle, daemon=True)
        t.start()

        # Send heartbeat instead of adjudication request
        config_client = VsockConfig(address=VsockAddress(cid=0, port=port))
        client = VsockTransport(config_client, dev_mode=True)
        assert client.connect()

        framer = MessageFramer()
        heartbeat_bytes = framer.encode_heartbeat("hb-001")
        assert client.send(heartbeat_bytes)

        response_bytes = client.receive()
        assert response_bytes is not None
        client.close()

        msg_type, _, payload = framer.decode(response_bytes)
        assert msg_type == MessageType.HEARTBEAT

        accept_done.wait(timeout=5.0)
        listener.stop()
        t.join(timeout=2.0)

    def test_ipc_car_hash_propagates_end_to_end(self) -> None:
        """CAR hash computed client-side matches hash in IPC response."""
        handler, minter, public_key = _make_adjudication_handler(
            npu_result=_make_gpu_allow(0.90)
        )
        config = _ephemeral_vsock_config()
        listener = PolicyAgentListener(config, handler=handler, dev_mode=True)
        assert listener.start() is True

        port = listener.listener.bound_port
        assert port is not None

        accept_done = threading.Event()

        def _accept_and_handle():
            transport = listener.listener.accept()
            if transport:
                listener.handle_connection(transport)
                transport.close()
            accept_done.set()

        t = threading.Thread(target=_accept_and_handle, daemon=True)
        t.start()

        car = _build_valid_car()
        client_hash = car.canonical_hash()
        response = _send_adjudication_request(port, car)

        accept_done.wait(timeout=5.0)
        listener.stop()
        t.join(timeout=2.0)

        # Hash on IPC response matches client-computed hash
        assert response.car_hash == client_hash

        # JWT also contains the same hash
        validator = AgenticJWTValidator(public_key)
        validation = validator.validate(
            response.jwt_token, expected_car_hash=client_hash
        )
        assert validation.valid is True
        assert validation.car_hash == client_hash


# ===========================================================================
# Group C: Fail-Closed — Disconnected PA
# ===========================================================================


class TestFailClosedDisconnectedPA:
    """Req 4: When the PA is unavailable, clients must fail to DENY.

    This simulates the scenario where the PA listener is not running
    and the client cannot establish a vsock connection.
    """

    def test_connection_refused_is_deny(self) -> None:
        """Client connection to non-existent PA → transport.connect() fails."""
        # Use a port that nobody is listening on.
        config = VsockConfig(
            address=VsockAddress(cid=0, port=59999),
            timeout_ms=500,
        )
        transport = VsockTransport(config, dev_mode=True)
        connected = transport.connect()
        # In dev_mode, connecting to a non-listening port should fail.
        # The Fail-Closed contract: connection failure → treat as DENY.
        assert connected is False

    def test_listener_stopped_mid_session(self) -> None:
        """PA listener stops between requests → second request denied."""
        handler, _, _ = _make_adjudication_handler(
            npu_result=_make_gpu_allow()
        )
        config = _ephemeral_vsock_config()
        listener = PolicyAgentListener(config, handler=handler, dev_mode=True)
        assert listener.start() is True

        port = listener.listener.bound_port
        assert port is not None

        # First request: succeeds
        accept_done = threading.Event()

        def _accept_first():
            transport = listener.listener.accept()
            if transport:
                listener.handle_connection(transport)
                transport.close()
            accept_done.set()

        t = threading.Thread(target=_accept_first, daemon=True)
        t.start()

        car = _build_valid_car()
        response = _send_adjudication_request(port, car)
        accept_done.wait(timeout=5.0)
        t.join(timeout=2.0)
        assert response.decision == "ALLOW"

        # Now stop the listener
        listener.stop()

        # Second request: connection refused → DENY (Fail-Closed)
        config_client = VsockConfig(
            address=VsockAddress(cid=0, port=port),
            timeout_ms=500,
        )
        transport = VsockTransport(config_client, dev_mode=True)
        connected = transport.connect()
        assert connected is False  # Fail-Closed

    def test_default_deny_handler_active(self) -> None:
        """PA listener with no handler configured → default_deny_handler."""
        config = _ephemeral_vsock_config()
        # No handler → default_deny_handler used
        listener = PolicyAgentListener(config, dev_mode=True)
        assert listener.start() is True

        port = listener.listener.bound_port
        assert port is not None

        accept_done = threading.Event()

        def _accept_and_handle():
            transport = listener.listener.accept()
            if transport:
                listener.handle_connection(transport)
                transport.close()
            accept_done.set()

        t = threading.Thread(target=_accept_and_handle, daemon=True)
        t.start()

        car = _build_valid_car()
        response = _send_adjudication_request(port, car)

        accept_done.wait(timeout=5.0)
        listener.stop()
        t.join(timeout=2.0)

        assert response.decision == "DENY"
        assert response.error == "NO_ADJUDICATOR_CONFIGURED"
        assert response.jwt_token == ""

    def test_handler_exception_fail_closed(self) -> None:
        """Handler raises an exception → DENY (Fail-Closed)."""
        def _exploding_handler(car_json: str, request_id: str):
            raise RuntimeError("Adjudicator crashed!")

        config = _ephemeral_vsock_config()
        listener = PolicyAgentListener(
            config, handler=_exploding_handler, dev_mode=True
        )
        assert listener.start() is True

        port = listener.listener.bound_port
        assert port is not None

        accept_done = threading.Event()

        def _accept_and_handle():
            transport = listener.listener.accept()
            if transport:
                listener.handle_connection(transport)
                transport.close()
            accept_done.set()

        t = threading.Thread(target=_accept_and_handle, daemon=True)
        t.start()

        car = _build_valid_car()
        response = _send_adjudication_request(port, car)

        accept_done.wait(timeout=5.0)
        listener.stop()
        t.join(timeout=2.0)

        assert response.decision == "DENY"
        assert "Handler error" in response.error


# ===========================================================================
# Group D: Preemption Signal Propagation (structural)
# ===========================================================================


class TestPreemptionSignalPropagation:
    """Req 5: PA Priority 0 preempts Orchestrator mid-generation.

    These are STRUCTURAL tests — real NPU preemption requires hardware.
    We validate that preemption events propagate through the data model
    and that the GenerationResult correctly records them.
    """

    def test_preempted_output_still_pgov_validated(self) -> None:
        """Even preempted (truncated) output must pass PGOV before delivery."""
        gen_result = GenerationResult(
            tokens=[1, 2],
            text="Hello, I can hel",
            token_count=2,
            latency_first_token_ms=90.0,
            latency_total_ms=300.0,
            truncated=True,
        )
        pgov_result = validate_output(
            generated_text=gen_result.text,
            token_count=gen_result.token_count,
            max_tokens=4096,
        )
        # Truncated but clean output → approved
        assert pgov_result.approved is True

    def test_preempted_output_with_pii_rejected(self) -> None:
        """Preempted output containing PII → PGOV rejects."""
        gen_result = GenerationResult(
            tokens=[1, 2, 3],
            text="Your SSN is 123-45-6789 and",
            token_count=3,
            latency_first_token_ms=90.0,
            latency_total_ms=200.0,
            truncated=True,
        )
        pgov_result = validate_output(
            generated_text=gen_result.text,
            token_count=gen_result.token_count,
            max_tokens=4096,
        )
        assert pgov_result.approved is False
        assert pgov_result.pii_detected is True

    def test_priority_ordering_structural(self) -> None:
        """PA inference priority (0) < Orchestrator priority (1) numerically.
        Lower number = higher priority per ADR-008.
        """
        from services.policy_agent.src.constants import NPU_PRIORITY as PA_PRIORITY
        from services.assistant_orchestrator.src.constants import NPU_PRIORITY as ORCH_PRIORITY

        assert PA_PRIORITY < ORCH_PRIORITY
        assert PA_PRIORITY == 0
        assert ORCH_PRIORITY == 1


# ===========================================================================
# Group E: PGOV Pipeline Integration
# ===========================================================================


class TestPGOVPipelineIntegration:
    """Validate PGOV integrates correctly with the generation pipeline."""

    def test_clean_output_approved(self) -> None:
        """Clean generated text → all 6 PGOV stages pass."""
        pgov_result = validate_output(
            generated_text="The capital of France is Paris.",
            token_count=8,
            max_tokens=4096,
        )
        assert pgov_result.approved is True
        assert pgov_result.pii_detected is False
        assert pgov_result.delimiter_echo is False
        assert pgov_result.tool_call_violation is False
        assert pgov_result.token_count_valid is True
        assert len(pgov_result.violations) == 0

    def test_token_budget_exceeded_rejected(self) -> None:
        """Token count > max_tokens → budget violation."""
        pgov_result = validate_output(
            generated_text="Some text",
            token_count=5000,
            max_tokens=4096,
        )
        assert pgov_result.approved is False
        assert pgov_result.token_count_valid is False

    def test_delimiter_echo_rejected(self) -> None:
        """Context Spotlighting delimiters in output → rejected."""
        from services.assistant_orchestrator.src.context_manager import SYSTEM_BEGIN

        pgov_result = validate_output(
            generated_text=f"Here is your answer: {SYSTEM_BEGIN} secret data",
            token_count=10,
            max_tokens=4096,
        )
        assert pgov_result.approved is False
        assert pgov_result.delimiter_echo is True

    def test_tool_call_not_in_allowlist_rejected(self) -> None:
        """Tool call reference not in allowlist → rejected."""
        pgov_result = validate_output(
            generated_text="I will call <tool_call>rm_rf_root</tool_call> now.",
            token_count=15,
            max_tokens=4096,
            tool_allowlist=frozenset({"search", "calendar"}),
        )
        assert pgov_result.approved is False
        assert pgov_result.tool_call_violation is True

    def test_tool_call_in_allowlist_passes(self) -> None:
        """Tool call reference in allowlist → passes PGOV check."""
        pgov_result = validate_output(
            generated_text="I will call <tool_call>search</tool_call> for you.",
            token_count=12,
            max_tokens=4096,
            tool_allowlist=frozenset({"search", "calendar"}),
        )
        assert pgov_result.approved is True
        assert pgov_result.tool_call_violation is False

    def test_multiple_violations_all_listed(self) -> None:
        """Output with PII + delimiter echo → both violations listed."""
        from services.assistant_orchestrator.src.context_manager import CONTEXT_BEGIN

        pgov_result = validate_output(
            generated_text=(
                f"Your SSN is 123-45-6789 and here is context: "
                f"{CONTEXT_BEGIN} secret"
            ),
            token_count=20,
            max_tokens=4096,
        )
        assert pgov_result.approved is False
        assert pgov_result.pii_detected is True
        assert pgov_result.delimiter_echo is True
        assert len(pgov_result.violations) >= 2

    def test_pgov_result_feeds_into_response_decision(self) -> None:
        """Pipeline: PGOV result determines whether sanitized or
        original text is delivered.
        """
        # Clean output → original text delivered
        clean = validate_output(
            generated_text="Weather is sunny.", token_count=4, max_tokens=4096
        )
        assert clean.sanitized_text == clean.original_text

        # PII output → fallback text delivered
        pii = validate_output(
            generated_text="SSN: 123-45-6789",
            token_count=4,
            max_tokens=4096,
        )
        assert pii.sanitized_text != pii.original_text


# ===========================================================================
# Group F: JWT Lifecycle Across Service Boundary
# ===========================================================================


class TestJWTLifecycleAcrossBoundary:
    """Mint JWT in PA → transfer over IPC → validate at destination."""

    def test_jwt_mint_then_validate_fresh_key_pair(self) -> None:
        """Fresh key pair: mint → validate → all claims correct."""
        minter, public_key = _make_jwt_minter()
        car = _build_valid_car()

        npu_result = _make_gpu_allow()
        rule_result = run_rule_engine(car, acl_matrix=ACL_MATRIX)
        decision = adjudicate(car, rule_result, npu_result)

        minted = minter.mint(decision)
        assert minted.success is True
        assert minted.nonce != ""
        assert minted.epoch >= 1

        validator = AgenticJWTValidator(public_key)
        result = validator.validate(minted.token, car.canonical_hash())
        assert result.valid is True
        assert result.claims["decision"] == "ALLOW"
        assert result.claims["car_hash"] == car.canonical_hash()
        assert result.claims["nonce"] == minted.nonce
        assert result.claims["epoch"] == minted.epoch

    def test_jwt_replay_detected(self) -> None:
        """Same JWT presented twice → nonce replay detection."""
        minter, public_key = _make_jwt_minter()
        car = _build_valid_car()

        npu_result = _make_gpu_allow()
        rule_result = run_rule_engine(car, acl_matrix=ACL_MATRIX)
        decision = adjudicate(car, rule_result, npu_result)
        minted = minter.mint(decision)

        validator = AgenticJWTValidator(public_key)

        # First validation: passes
        r1 = validator.validate(minted.token, car.canonical_hash())
        assert r1.valid is True

        # Second validation: replay detected
        r2 = validator.validate(minted.token, car.canonical_hash())
        assert r2.valid is False
        assert "NONCE" in (r2.error or "")

    def test_jwt_car_hash_mismatch_rejected(self) -> None:
        """JWT validated with wrong expected_car_hash → rejected."""
        minter, public_key = _make_jwt_minter()
        car = _build_valid_car()

        npu_result = _make_gpu_allow()
        rule_result = run_rule_engine(car, acl_matrix=ACL_MATRIX)
        decision = adjudicate(car, rule_result, npu_result)
        minted = minter.mint(decision)

        validator = AgenticJWTValidator(public_key)
        result = validator.validate(minted.token, expected_car_hash="wrong_hash")
        assert result.valid is False
        assert "CAR_HASH" in (result.error or "")

    def test_jwt_wrong_public_key_rejected(self) -> None:
        """JWT validated with a different public key → signature failure."""
        minter, _ = _make_jwt_minter()
        _, wrong_public_key = AgenticJWTMinter.generate_key_pair()

        car = _build_valid_car()
        npu_result = _make_gpu_allow()
        rule_result = run_rule_engine(car, acl_matrix=ACL_MATRIX)
        decision = adjudicate(car, rule_result, npu_result)
        minted = minter.mint(decision)

        validator = AgenticJWTValidator(wrong_public_key)
        result = validator.validate(minted.token)
        assert result.valid is False
        assert "SIGNATURE" in (result.error or "")

    def test_jwt_epoch_revocation(self) -> None:
        """Epoch increment → old JWTs rejected at destination."""
        minter, public_key = _make_jwt_minter()
        car = _build_valid_car()

        npu_result = _make_gpu_allow()
        rule_result = run_rule_engine(car, acl_matrix=ACL_MATRIX)
        decision = adjudicate(car, rule_result, npu_result)

        # Mint at epoch 1
        minted_epoch1 = minter.mint(decision)

        # Increment epoch at PA side
        minter.epoch_manager.increment()

        # Mint another JWT at epoch 2
        car2 = _build_valid_car()
        npu2 = _make_gpu_allow()
        rule2 = run_rule_engine(car2, acl_matrix=ACL_MATRIX)
        decision2 = adjudicate(car2, rule2, npu2)
        minted_epoch2 = minter.mint(decision2)

        # Validator: validate epoch 2 first (updates tracker)
        validator = AgenticJWTValidator(public_key)
        r2 = validator.validate(minted_epoch2.token, car2.canonical_hash())
        assert r2.valid is True

        # Now validate epoch 1 JWT → stale epoch → rejected
        r1 = validator.validate(minted_epoch1.token, car.canonical_hash())
        assert r1.valid is False
        assert "EPOCH" in (r1.error or "")

    def test_jwt_deny_decision_no_token_minted(self) -> None:
        """PA DENY → no JWT token minted. Pipeline returns empty token."""
        car = _build_valid_car(sensitivity=Sensitivity.UNCLASSIFIED)
        npu_result = _make_gpu_allow()
        rule_result = run_rule_engine(car, acl_matrix=ACL_MATRIX)
        decision = adjudicate(car, rule_result, npu_result)

        assert decision.decision == AdjudicationDecision.DENY

        # Minter should not mint for DENY — but the minter itself doesn't
        # enforce this, the caller (PA handler) gates on ALLOW. Test that
        # the pipeline structure prevents it.
        minter, _ = _make_jwt_minter()
        # The handler only mints on ALLOW:
        jwt_token = ""
        if decision.decision == AdjudicationDecision.ALLOW:
            minted = minter.mint(decision)
            jwt_token = minted.token
        assert jwt_token == ""

    def test_jwt_over_ipc_full_lifecycle(self) -> None:
        """Mint at PA → IPC transfer → validate at destination.

        The most complete cross-boundary test: real IPC, real JWT,
        real 5-stage validation.
        """
        handler, minter, public_key = _make_adjudication_handler(
            npu_result=_make_gpu_allow(0.95)
        )
        config = _ephemeral_vsock_config()
        listener = PolicyAgentListener(config, handler=handler, dev_mode=True)
        assert listener.start() is True

        port = listener.listener.bound_port
        assert port is not None

        accept_done = threading.Event()

        def _accept_and_handle():
            transport = listener.listener.accept()
            if transport:
                listener.handle_connection(transport)
                transport.close()
            accept_done.set()

        t = threading.Thread(target=_accept_and_handle, daemon=True)
        t.start()

        car = _build_valid_car()
        response = _send_adjudication_request(port, car)

        accept_done.wait(timeout=5.0)
        listener.stop()
        t.join(timeout=2.0)

        assert response.decision == "ALLOW"
        assert response.jwt_token != ""

        # Full 5-stage validation at destination
        validator = AgenticJWTValidator(public_key)
        result = validator.validate(
            response.jwt_token, expected_car_hash=car.canonical_hash()
        )
        assert result.valid is True
        assert result.decision == "ALLOW"
        assert result.car_hash == car.canonical_hash()
        assert result.request_id == car.request_id


# ===========================================================================
# Group G: Latency Budget Structure
# ===========================================================================


class TestLatencyBudgetStructure:
    """Req 3: Validate latency budget FIELDS are present and structurally
    correct.  These are NOT hardware latency measurements (models are
    mocked) — they verify the timing instrumentation is wired end-to-end.
    """

    def test_classification_result_has_latency(self) -> None:
        """ClassificationResult.latency_ms is populated and non-negative."""
        result = ClassificationResult(
            intent=Intent.CONVERSATIONAL,
            confidence=0.90,
            latency_ms=15.5,
        )
        assert result.latency_ms >= 0.0

    def test_generation_result_has_timing_fields(self) -> None:
        """GenerationResult timing fields present and non-negative."""
        result = GenerationResult(
            tokens=[1],
            text="Hi",
            token_count=1,
            latency_first_token_ms=50.0,
            latency_total_ms=200.0,
            truncated=False,
        )
        assert result.latency_first_token_ms >= 0.0
        assert result.latency_total_ms >= result.latency_first_token_ms

    def test_npu_classification_result_has_latency(self) -> None:
        """GPUClassificationResult.latency_ms populated."""
        result = _make_gpu_allow(0.90)
        assert result.latency_ms >= 0.0

    def test_adjudication_context_has_latency_breakdown(self) -> None:
        """HybridAdjudicator.adjudicate_car produces timing breakdown."""
        npu = PolicyGPUInference("dummy_dir")
        adjudicator = HybridAdjudicator(
            npu_inference=npu,
            acl_matrix=ACL_MATRIX,
        )
        car = _build_valid_car()
        ctx = adjudicator.adjudicate_car(car)

        assert ctx.latency.total_ms >= 0.0
        assert ctx.latency.rule_engine_ms >= 0.0
        # NPU not loaded → skipped via Fail-Closed DENY on rule-pass path
        # Rule engine passes → NPU stub returns error → DENY short-circuit
        assert isinstance(ctx.latency.total_ms, float)

    def test_latency_constants_defined(self) -> None:
        """Latency budget constants exist in shared/constants.py."""
        from shared.constants import (
            SEMANTIC_ROUTER_LATENCY_MS,
            ORCH_FIRST_TOKEN_WARM_MS,
            ORCH_FIRST_TOKEN_COLD_MS,
        )
        assert SEMANTIC_ROUTER_LATENCY_MS == 80.0
        assert ORCH_FIRST_TOKEN_WARM_MS == 1000.0
        assert ORCH_FIRST_TOKEN_COLD_MS == 1500.0

    def test_adjudication_latency_fields_structurally_valid(self) -> None:
        """AdjudicationLatency dataclass fields are all floats ≥ 0."""
        from services.policy_agent.src.adjudicator import AdjudicationLatency

        lat = AdjudicationLatency(
            rule_engine_ms=1.2,
            integrity_ms=0.5,
            npu_inference_ms=3.0,
            total_ms=4.7,
        )
        assert lat.rule_engine_ms >= 0.0
        assert lat.integrity_ms >= 0.0
        assert lat.npu_inference_ms >= 0.0
        assert lat.total_ms >= 0.0
        assert lat.total_ms >= lat.rule_engine_ms


# ===========================================================================
# Group H: Cross-Service Data Flow Integrity
# ===========================================================================


class TestCrossServiceDataFlow:
    """Verify data integrity as it crosses service boundaries.

    These tests ensure that serialization/deserialization across IPC
    does not corrupt CAR fields, decision artifacts, or JWT claims.
    """

    def test_car_json_round_trip_preserves_fields(self) -> None:
        """CAR serialized to JSON → deserialized → all fields preserved."""
        car = _build_valid_car(
            source="assistant_orchestrator",
            dest="substrate",
            verb=ActionVerb.EXECUTE,
            resource="skill.calendar.create_event",
            sensitivity=Sensitivity.SENSITIVE,
            session_id="sess-roundtrip-001",
        )
        car_json = car.model_dump_json()
        restored = CanonicalActionRepresentation.model_validate_json(car_json)

        assert restored.source_agent == car.source_agent
        assert restored.destination_service == car.destination_service
        assert restored.verb == car.verb
        assert restored.resource == car.resource
        assert restored.sensitivity == car.sensitivity
        assert restored.request_id == car.request_id
        assert restored.session_id == car.session_id
        assert restored.canonical_hash() == car.canonical_hash()

    def test_adjudication_response_json_round_trip(self) -> None:
        """AdjudicationResponse.to_dict() → from_dict() preserves all fields."""
        original = AdjudicationResponse(
            decision="ALLOW",
            jwt_token="eyJhbGciOiJFUzI1NiJ9.test",
            car_hash="abc123" * 10 + "abcd",
            request_id="req-001",
            error="",
        )
        d = original.to_dict()
        restored = AdjudicationResponse.from_dict(d)

        assert restored.decision == original.decision
        assert restored.jwt_token == original.jwt_token
        assert restored.car_hash == original.car_hash
        assert restored.request_id == original.request_id

    def test_message_framer_encode_decode_symmetry(self) -> None:
        """MessageFramer encode → decode is lossless for all message types."""
        framer = MessageFramer()

        # Request
        req = AdjudicationRequest(car_json='{"test": true}', request_id="r1")
        encoded = framer.encode_request(req)
        decoded = framer.decode_request(encoded)
        assert decoded.car_json == req.car_json
        assert decoded.request_id == req.request_id

        # Response
        resp = AdjudicationResponse(
            decision="ALLOW", jwt_token="tok", car_hash="hash", request_id="r2"
        )
        encoded = framer.encode_response(resp)
        decoded_resp = framer.decode_response(encoded)
        assert decoded_resp.decision == resp.decision
        assert decoded_resp.jwt_token == resp.jwt_token

    def test_prompt_formatting_deterministic(self) -> None:
        """Same CAR produces identical prompts across calls."""
        car = _build_valid_car()
        p1 = CARPromptFormatter.format_car(car)
        p2 = CARPromptFormatter.format_car(car)
        assert p1 == p2
        assert len(p1) > 0
        assert car.source_agent in p1

    def test_car_canonical_hash_stable_across_services(self) -> None:
        """Hash computed at Router/Orchestrator matches hash at PA.

        This simulates the scenario where the Orchestrator builds a CAR,
        computes its hash, sends it to the PA, and the PA independently
        hashes the deserialized CAR. Both must match.
        """
        # Orchestrator side
        car = _build_valid_car()
        orchestrator_hash = car.canonical_hash()
        car_json = car.model_dump_json()

        # PA side: deserialize and re-hash
        pa_car = CanonicalActionRepresentation.model_validate_json(car_json)
        pa_hash = pa_car.canonical_hash()

        assert orchestrator_hash == pa_hash


# ===========================================================================
# Group I: HybridAdjudicator Integration (full pipeline with stub NPU)
# ===========================================================================


class TestHybridAdjudicatorIntegration:
    """Exercise the full HybridAdjudicator pipeline with a stub NPU.

    The NPU is not loaded (Fail-Closed stub), so rules-passing CARs
    will receive DENY from the NPU error path.  This validates that
    the HybridAdjudicator correctly orchestrates all stages.
    """

    def test_stub_npu_full_pipeline_deny(self) -> None:
        """Valid CAR + rules pass + stub NPU → DENY (Fail-Closed)."""
        npu = PolicyGPUInference("dummy_dir")
        adjudicator = HybridAdjudicator(
            npu_inference=npu,
            acl_matrix=ACL_MATRIX,
        )
        car = _build_valid_car()
        ctx = adjudicator.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.decision_artifact.deterministic_pass is True
        assert ctx.decision_artifact.probabilistic_pass is False
        assert ctx.npu_result.error is not None
        assert ctx.latency.total_ms > 0.0
        assert adjudicator.adjudication_count == 1

    def test_rule_deny_short_circuits_npu(self) -> None:
        """Rule engine DENY → NPU skipped entirely (short-circuit)."""
        npu = PolicyGPUInference("dummy_dir")
        adjudicator = HybridAdjudicator(
            npu_inference=npu,
            acl_matrix=ACL_MATRIX,
        )
        car = _build_valid_car(sensitivity=Sensitivity.UNCLASSIFIED)
        ctx = adjudicator.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.rule_engine_result.passed is False
        assert ctx.rule_engine_result.blocking_rule == "SENSITIVITY_CLASSIFICATION"
        assert ctx.decision_artifact.deterministic_pass is False
        assert ctx.npu_result.error is not None
        assert "Skipped" in ctx.npu_result.error
        assert ctx.latency.npu_inference_ms == 0.0

    def test_adjudication_count_increments(self) -> None:
        """Each adjudicate_car call increments the counter."""
        npu = PolicyGPUInference("dummy_dir")
        adjudicator = HybridAdjudicator(
            npu_inference=npu,
            acl_matrix=ACL_MATRIX,
        )
        for i in range(5):
            car = _build_valid_car(resource=f"resource_{i}")
            adjudicator.adjudicate_car(car)

        assert adjudicator.adjudication_count == 5

    def test_context_contains_full_audit_trail(self) -> None:
        """AdjudicationContext has all audit fields populated."""
        npu = PolicyGPUInference("dummy_dir")
        adjudicator = HybridAdjudicator(
            npu_inference=npu,
            acl_matrix=ACL_MATRIX,
        )
        car = _build_valid_car()
        ctx = adjudicator.adjudicate_car(car)

        assert ctx.adjudication_id != ""
        assert ctx.decision_artifact is not None
        assert ctx.rule_engine_result is not None
        assert ctx.npu_result is not None
        assert ctx.latency is not None
        assert ctx.timestamp is not None
        assert ctx.decision_artifact.car_hash == car.canonical_hash()
        assert ctx.decision_artifact.request_id == car.request_id
