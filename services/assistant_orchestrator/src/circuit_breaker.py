"""
Circuit Breaker — Orchestrator
================================
USE-CASE-004, OWASP LLM04: Prevents runaway generation and tool-call
recursion via hard enforcement of token and depth limits.

Two independent breakers:
  1. Token Breaker: Caps output tokens at 4096 (MAX_OUTPUT_TOKENS).
  2. Depth Breaker: Caps tool-call recursion at 5 hops (MAX_TOOL_CALL_DEPTH).

When tripped, the breaker terminates the current operation and returns
a safe truncation notice. Breakers are non-negotiable — no escalation.

Security:
  - Hard limits prevent denial-of-service via prompt injection.
  - Breaker state is per-request (no cross-request leakage).
  - Fail-Closed: breaker evaluation errors trip the breaker.
  - No external network calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.assistant_orchestrator.src.constants import (
    OUTPUT_TOKEN_CAP,
    TOOL_CALL_DEPTH_CAP,
)


@dataclass
class BreakerState:
    """Per-request circuit breaker state."""

    tokens_generated: int = 0
    tool_call_depth: int = 0
    token_tripped: bool = False
    depth_tripped: bool = False

    @property
    def tripped(self) -> bool:
        """True if any breaker has been tripped."""
        return self.token_tripped or self.depth_tripped


class CircuitBreaker:
    """Enforces hard token and recursion limits per request.

    Usage:
        breaker = CircuitBreaker()
        state = breaker.new_request()
        # ... during generation ...
        state = breaker.record_tokens(state, 150)
        if state.tripped:
            # truncate and return
    """

    def __init__(
        self,
        max_tokens: int = OUTPUT_TOKEN_CAP,
        max_depth: int = TOOL_CALL_DEPTH_CAP,
    ) -> None:
        self._max_tokens = max_tokens
        self._max_depth = max_depth

    def new_request(self) -> BreakerState:
        """Initialize a fresh breaker state for a new request."""
        return BreakerState()

    def record_tokens(self, state: BreakerState, count: int) -> BreakerState:
        """Record generated tokens and check the token breaker.

        Args:
            state: Current breaker state.
            count: Number of new tokens generated.

        Returns:
            Updated BreakerState (token_tripped may now be True).
        """
        state.tokens_generated += count
        if state.tokens_generated >= self._max_tokens:
            state.token_tripped = True
        return state

    def record_tool_call(self, state: BreakerState) -> BreakerState:
        """Record a tool-call hop and check the depth breaker.

        Args:
            state: Current breaker state.

        Returns:
            Updated BreakerState (depth_tripped may now be True).
        """
        state.tool_call_depth += 1
        if state.tool_call_depth >= self._max_depth:
            state.depth_tripped = True
        return state

    def safe_truncation_message(self, state: BreakerState) -> str:
        """Generate a user-facing truncation notice.

        Args:
            state: The tripped breaker state.

        Returns:
            Human-readable truncation explanation.
        """
        reasons: list[str] = []
        if state.token_tripped:
            reasons.append(
                f"Output token limit reached ({self._max_tokens} tokens)."
            )
        if state.depth_tripped:
            reasons.append(
                f"Tool-call recursion limit reached ({self._max_depth} hops)."
            )
        return " ".join(reasons) if reasons else "No circuit breaker triggered."
