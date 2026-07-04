r"""Unit tests for the turn-scoped Hello egress envelope (ADR-023 Am.4, #723 rung 3).

Covers the pure state machine (:class:`EgressEnvelopeManager`), the query
extractor, and the production ``consent_fn`` (:func:`request_egress_fingerprint`)
routing to the shared operator-approval verifier — all WITHOUT a biometric device
(the consent callback is injected / the verifier is a mock). The end-to-end tool
loop wiring is exercised in test_retrieval_tools.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.assistant_orchestrator.src.egress_envelope import (
    EgressEnvelopeManager,
    extract_query,
    request_egress_fingerprint,
)


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------


class _ConsentRecorder:
    """A stub consent_fn recording (query, n) calls and returning a fixed verdict
    (or a per-call sequence)."""

    def __init__(self, verdicts: list[bool] | bool = True) -> None:
        self.calls: list[tuple[str, int]] = []
        self._verdicts = verdicts

    def __call__(self, query: str, n: int) -> bool:
        self.calls.append((query, n))
        if isinstance(self._verdicts, bool):
            return self._verdicts
        return self._verdicts[len(self.calls) - 1]


class TestEgressEnvelopeManager:
    def test_gate_without_begin_turn_is_denied_fail_closed(self) -> None:
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        decision = mgr.gate("s1", "q", consent_fn=consent)
        assert decision.allowed is False
        assert decision.fingerprinted is False
        assert consent.calls == []  # never prompted — no envelope armed

    def test_first_egress_fingerprints_then_window_covers_up_to_n(self) -> None:
        """N=3: query 1 fingerprints; 2 and 3 ride the open window (no re-prompt);
        query 4 (beyond N) triggers a fresh fingerprint."""
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        mgr.begin_turn("s1", 3)

        d1 = mgr.gate("s1", "q1", consent_fn=consent)
        d2 = mgr.gate("s1", "q2", consent_fn=consent)
        d3 = mgr.gate("s1", "q3", consent_fn=consent)
        d4 = mgr.gate("s1", "q4", consent_fn=consent)

        assert [d.allowed for d in (d1, d2, d3, d4)] == [True, True, True, True]
        # Only q1 and q4 required a fingerprint.
        assert [d.fingerprinted for d in (d1, d2, d3, d4)] == [True, False, False, True]
        assert consent.calls == [("q1", 3), ("q4", 3)]

    def test_n_equals_1_fingerprints_every_query(self) -> None:
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        mgr.begin_turn("s1", 1)
        for q in ("q1", "q2", "q3"):
            d = mgr.gate("s1", q, consent_fn=consent)
            assert d.allowed and d.fingerprinted
        assert consent.calls == [("q1", 1), ("q2", 1), ("q3", 1)]

    def test_denied_fingerprint_latches_for_the_turn(self) -> None:
        """A denied first fingerprint ends egress for the turn — a later egress is
        refused WITHOUT re-prompting (a fooled model cannot retry past a refusal)."""
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(False)
        mgr.begin_turn("s1", 3)

        d1 = mgr.gate("s1", "q1", consent_fn=consent)
        d2 = mgr.gate("s1", "q2", consent_fn=consent)

        assert d1.allowed is False and d1.fingerprinted is True
        assert d2.allowed is False and d2.fingerprinted is False
        assert consent.calls == [("q1", 3)]  # prompted once, then latched denied

    def test_consent_fn_exception_is_fail_closed(self) -> None:
        mgr = EgressEnvelopeManager()

        def _boom(query: str, n: int) -> bool:
            raise RuntimeError("verifier blew up")

        mgr.begin_turn("s1", 3)
        d = mgr.gate("s1", "q1", consent_fn=_boom)
        assert d.allowed is False
        # And it latched — a second egress is refused without another attempt.
        d2 = mgr.gate("s1", "q2", consent_fn=_ConsentRecorder(True))
        assert d2.allowed is False

    def test_begin_turn_resets_the_envelope(self) -> None:
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        mgr.begin_turn("s1", 3)
        mgr.gate("s1", "q1", consent_fn=consent)  # fingerprint window opens
        mgr.begin_turn("s1", 3)  # NEW turn — must re-fingerprint
        d = mgr.gate("s1", "q_new", consent_fn=consent)
        assert d.fingerprinted is True
        assert consent.calls == [("q1", 3), ("q_new", 3)]

    def test_begin_turn_clamps_n_below_one_to_one(self) -> None:
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        mgr.begin_turn("s1", 0)  # nonsensical N — floored to 1 (fingerprint every)
        d1 = mgr.gate("s1", "q1", consent_fn=consent)
        d2 = mgr.gate("s1", "q2", consent_fn=consent)
        assert d1.fingerprinted and d2.fingerprinted

    def test_sessions_are_independent(self) -> None:
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        mgr.begin_turn("s1", 3)
        mgr.begin_turn("s2", 3)
        mgr.gate("s1", "a", consent_fn=consent)  # opens s1 window
        d = mgr.gate("s2", "b", consent_fn=consent)  # s2 still needs its own fp
        assert d.fingerprinted is True


class TestExtractQuery:
    def test_valid_query(self) -> None:
        assert extract_query('{"query":"bitcoin price"}') == "bitcoin price"

    def test_missing_query_field(self) -> None:
        assert extract_query('{"max_results":5}') == "(query unavailable)"

    def test_malformed_json(self) -> None:
        assert extract_query("not json") == "(query unavailable)"

    def test_empty_args(self) -> None:
        assert extract_query("") == "(query unavailable)"

    def test_non_string_query(self) -> None:
        assert extract_query('{"query":123}') == "(query unavailable)"

    def test_blank_query_falls_back(self) -> None:
        assert extract_query('{"query":"   "}') == "(query unavailable)"

    def test_long_query_capped_at_200(self) -> None:
        long_q = "x" * 500
        out = extract_query('{"query":"' + long_q + '"}')
        assert len(out) == 200


# ---------------------------------------------------------------------------
# The production consent_fn — routes to the shared operator-approval verifier
# ---------------------------------------------------------------------------


class _RecordingVerifier:
    """A mock ApprovalVerifier capturing the context it was handed."""

    def __init__(self, approved: bool) -> None:
        self._approved = approved
        self.seen: list[Any] = []

    def verify(self, context: Any) -> Any:
        from shared.security.escalation_consent import ApprovalResult

        self.seen.append(context)
        if self._approved:
            return ApprovalResult.allow(verifier_identity="mock-hello")
        return ApprovalResult.deny("mock deny", verifier_identity="mock-hello")


@pytest.fixture(autouse=True)
def _isolate_verifier() -> Any:
    """Snapshot + clear the process verifier registry around each test so a mock
    never leaks and the dormant default is restored."""
    from shared.security.escalation_consent import (
        active_verifier,
        clear_verifier,
        register_verifier,
    )

    saved = active_verifier()
    clear_verifier()
    yield
    clear_verifier()
    if saved is not None:
        register_verifier(saved)


class TestRequestEgressFingerprint:
    def test_no_verifier_registered_is_denied(self) -> None:
        # Dormant default (no operator surface wired) → fail-closed deny.
        assert request_egress_fingerprint("q", 3, timeout_s=1.0) is False

    def test_approved_verifier_allows_and_context_is_egress_shaped(self) -> None:
        from shared.security.escalation_consent import register_verifier

        verifier = _RecordingVerifier(approved=True)
        register_verifier(verifier)
        assert request_egress_fingerprint("bitcoin price", 3, timeout_s=1.0) is True
        # The context routed to the verifier is EGRESS-shaped: source="egress"
        # (so the Hello dialog reads as an egress consent) and the query + the
        # "up to N" bound are surfaced (the operator must SEE the query to judge).
        ctx = verifier.seen[0]
        assert ctx.source == "egress"
        assert ctx.tool_name == "web_search"
        assert "bitcoin price" in ctx.action_summary
        assert "up to 3 searches" in ctx.action_summary

    def test_denied_verifier_denies(self) -> None:
        from shared.security.escalation_consent import register_verifier

        register_verifier(_RecordingVerifier(approved=False))
        assert request_egress_fingerprint("q", 3, timeout_s=1.0) is False

    def test_singular_search_wording_for_n_1(self) -> None:
        from shared.security.escalation_consent import register_verifier

        verifier = _RecordingVerifier(approved=True)
        register_verifier(verifier)
        request_egress_fingerprint("q", 1, timeout_s=1.0)
        assert "up to 1 search " in verifier.seen[0].action_summary + " "
