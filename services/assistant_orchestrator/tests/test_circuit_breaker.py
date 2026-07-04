"""
Circuit Breaker Tests — Assistant Orchestrator
================================================
Tests for token and depth limit enforcement.
"""

from __future__ import annotations

import pytest

from services.assistant_orchestrator.src.circuit_breaker import CircuitBreaker


class TestTokenBreaker:
    """Token cap enforcement."""

    def test_under_limit_not_tripped(self) -> None:
        cb = CircuitBreaker(max_tokens=100, max_depth=5)
        state = cb.new_request()
        state = cb.record_tokens(state, 50)
        assert not state.tripped

    def test_at_limit_trips(self) -> None:
        cb = CircuitBreaker(max_tokens=100, max_depth=5)
        state = cb.new_request()
        state = cb.record_tokens(state, 100)
        assert state.token_tripped
        assert state.tripped

    def test_incremental_accumulation(self) -> None:
        cb = CircuitBreaker(max_tokens=100, max_depth=5)
        state = cb.new_request()
        state = cb.record_tokens(state, 30)
        state = cb.record_tokens(state, 30)
        assert not state.tripped
        state = cb.record_tokens(state, 50)
        assert state.token_tripped


class TestDepthBreaker:
    """Tool-call recursion depth enforcement."""

    def test_under_limit_not_tripped(self) -> None:
        cb = CircuitBreaker(max_tokens=4096, max_depth=5)
        state = cb.new_request()
        for _ in range(4):
            state = cb.record_tool_call(state)
        assert not state.depth_tripped

    def test_at_limit_trips(self) -> None:
        cb = CircuitBreaker(max_tokens=4096, max_depth=5)
        state = cb.new_request()
        for _ in range(5):
            state = cb.record_tool_call(state)
        assert state.depth_tripped
        assert state.tripped


class TestBreakerOverLimit:
    """Over-limit accumulation must still trip and record true totals."""

    def test_single_record_far_over_token_cap_trips(self) -> None:
        cb = CircuitBreaker(max_tokens=100, max_depth=5)
        state = cb.new_request()
        state = cb.record_tokens(state, 10_000)
        assert state.token_tripped
        assert state.tripped
        assert state.tokens_generated == 10_000

    def test_depth_records_past_cap_continue_to_trip(self) -> None:
        cb = CircuitBreaker(max_tokens=4096, max_depth=3)
        state = cb.new_request()
        for _ in range(10):
            state = cb.record_tool_call(state)
        assert state.depth_tripped
        assert state.tool_call_depth == 10

    def test_record_after_trip_still_accumulates(self) -> None:
        """Breaker does not block further accumulation — trip flag is sticky."""
        cb = CircuitBreaker(max_tokens=100, max_depth=5)
        state = cb.new_request()
        state = cb.record_tokens(state, 200)
        assert state.token_tripped
        state = cb.record_tokens(state, 50)
        assert state.tokens_generated == 250
        assert state.token_tripped  # still tripped


class TestSimultaneousTrip:
    """Both breakers can trip on the same request state."""

    def test_both_breakers_trip_independently(self) -> None:
        cb = CircuitBreaker(max_tokens=100, max_depth=3)
        state = cb.new_request()
        state = cb.record_tokens(state, 150)
        for _ in range(3):
            state = cb.record_tool_call(state)
        assert state.token_tripped
        assert state.depth_tripped
        assert state.tripped

    def test_truncation_message_lists_both_reasons(self) -> None:
        cb = CircuitBreaker(max_tokens=100, max_depth=3)
        state = cb.new_request()
        state = cb.record_tokens(state, 150)
        for _ in range(3):
            state = cb.record_tool_call(state)
        msg = cb.safe_truncation_message(state)
        assert "100 tokens" in msg
        assert "3 hops" in msg


class TestNewRequestIsolation:
    """Every new_request() yields a fresh, untripped state."""

    def test_new_request_returns_fresh_state(self) -> None:
        cb = CircuitBreaker(max_tokens=100, max_depth=5)
        s1 = cb.new_request()
        s1 = cb.record_tokens(s1, 200)
        assert s1.token_tripped

        s2 = cb.new_request()
        assert s2.tokens_generated == 0
        assert s2.tool_call_depth == 0
        assert not s2.token_tripped
        assert not s2.depth_tripped
        assert not s2.tripped

    def test_states_are_independent_instances(self) -> None:
        cb = CircuitBreaker()
        s1 = cb.new_request()
        s2 = cb.new_request()
        assert s1 is not s2
        cb.record_tokens(s1, 50)
        assert s2.tokens_generated == 0


class TestTruncationMessage:
    """Safe truncation notice generation."""

    def test_token_truncation_message(self) -> None:
        cb = CircuitBreaker(max_tokens=100, max_depth=5)
        state = cb.new_request()
        state = cb.record_tokens(state, 200)
        msg = cb.safe_truncation_message(state)
        assert "100 tokens" in msg

    def test_no_trip_message(self) -> None:
        cb = CircuitBreaker()
        state = cb.new_request()
        msg = cb.safe_truncation_message(state)
        assert "No circuit breaker" in msg
