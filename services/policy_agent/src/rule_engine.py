"""
Deterministic Rule Engine — Policy Agent
==========================================
USE-CASE-001, P1.2: First stage of hybrid adjudication pipeline.

The rule engine applies hard-coded, version-controlled rules to CARs.
Rules are deterministic (no ML) — same input always produces same output.

Rule categories (execution order):
  1. STRUCTURAL:  CAR completeness, field validation.
  2. SENSITIVITY: Sensitivity-level routing (PUBLIC → allow, UNCLASSIFIED → deny).
  3. ACL:         Source-agent → destination-service permission matrix.
  4. RATE:        Per-agent sliding-window rate limiting.
  5. RESOURCE:    Resource-specific deny lists (fnmatch patterns).

Any DENY is final — no appeal. ALLOW passes to the probabilistic stage.
True short-circuit: subsequent rules are NOT evaluated after a DENY.
RATE counter is incremented only after ACL passes (prevents abuse via
denied agents inflating rate counters).

Security:
  - Fail-Closed: if ANY rule cannot evaluate, the result is DENY.
  - Rules are loaded from versioned TOML configs at boot (P1.2).
  - No external network calls.
"""

from __future__ import annotations

import fnmatch
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum

from shared.schemas.car import CanonicalActionRepresentation
from services.policy_agent.src.config_loader import ResourceDenyRule


class RuleVerdict(str, Enum):
    """Outcome of a single rule evaluation."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    SKIP = "SKIP"  # Rule does not apply to this CAR


@dataclass(frozen=True)
class RuleResult:
    """Result from a single rule evaluation."""

    rule_name: str
    verdict: RuleVerdict
    reason: str


@dataclass(frozen=True)
class RuleEngineResult:
    """Aggregated result from the deterministic rule engine."""

    passed: bool
    """True if ALL applicable rules returned ALLOW or SKIP."""

    results: tuple[RuleResult, ...]
    """Ordered results from each evaluated rule (short-circuit: may be < 5)."""

    blocking_rule: str | None = None
    """Name of the first rule that returned DENY, if any."""


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Per-agent sliding-window rate limiter.

    Thread-safety: NOT thread-safe. The Policy Agent runs a single-threaded
    event loop per the architectural design (vsock listener is sequential).

    The rate limiter tracks request timestamps per agent identity. When
    ``check_and_record`` is called, expired entries outside the window are
    purged, the current count is checked against the budget, and if allowed
    the request timestamp is recorded.
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    @property
    def max_requests(self) -> int:
        return self._max_requests

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    def check_and_record(self, agent_id: str) -> tuple[bool, int]:
        """Check if the agent is within its rate budget and record the request.

        Args:
            agent_id: Source agent identity (mTLS CN).

        Returns:
            (allowed, current_count) — allowed is True if within budget.
            If allowed, the request is recorded. If denied, it is NOT recorded
            (the agent is already over budget — no point inflating further).
        """
        now = time.monotonic()
        window = self._windows[agent_id]

        # Purge expired entries
        cutoff = now - self._window_seconds
        while window and window[0] < cutoff:
            window.popleft()

        current = len(window)
        if current >= self._max_requests:
            return False, current

        window.append(now)
        return True, current + 1

    def current_count(self, agent_id: str) -> int:
        """Return the current request count for an agent (after purging)."""
        now = time.monotonic()
        window = self._windows[agent_id]
        cutoff = now - self._window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        return len(window)

    def reset(self, agent_id: str | None = None) -> None:
        """Reset rate limiter state.

        Args:
            agent_id: If provided, reset only this agent. Otherwise reset all.
        """
        if agent_id is None:
            self._windows.clear()
        else:
            self._windows.pop(agent_id, None)


# ---------------------------------------------------------------------------
# Individual rule evaluators
# ---------------------------------------------------------------------------

def evaluate_structural(car: CanonicalActionRepresentation) -> RuleResult:
    """STRUCTURAL: Verify CAR completeness and field validity.

    Fail-Closed: incomplete CARs are DENIED.
    """
    if not car.is_complete():
        return RuleResult(
            rule_name="STRUCTURAL_COMPLETENESS",
            verdict=RuleVerdict.DENY,
            reason="CAR is incomplete — missing required fields.",
        )
    return RuleResult(
        rule_name="STRUCTURAL_COMPLETENESS",
        verdict=RuleVerdict.ALLOW,
        reason="CAR is structurally complete.",
    )


def evaluate_sensitivity(car: CanonicalActionRepresentation) -> RuleResult:
    """SENSITIVITY: Route based on declared sensitivity level.

    UNCLASSIFIED payloads are Fail-Closed DENIED.
    """
    from shared.schemas.car import Sensitivity

    if car.sensitivity == Sensitivity.UNCLASSIFIED:
        return RuleResult(
            rule_name="SENSITIVITY_CLASSIFICATION",
            verdict=RuleVerdict.DENY,
            reason="UNCLASSIFIED sensitivity — Fail-Closed.",
        )
    return RuleResult(
        rule_name="SENSITIVITY_CLASSIFICATION",
        verdict=RuleVerdict.ALLOW,
        reason=f"Sensitivity classified as {car.sensitivity.value}.",
    )


def evaluate_acl(
    car: CanonicalActionRepresentation,
    acl_matrix: dict[str, list[str]] | None = None,
) -> RuleResult:
    """ACL: Verify source_agent is permitted to access destination_service.

    Args:
        car: The CAR to evaluate.
        acl_matrix: Mapping of source_agent → list of allowed destination_services.
            If None, Fail-Closed DENY.
    """
    if acl_matrix is None:
        return RuleResult(
            rule_name="ACL_PERMISSION",
            verdict=RuleVerdict.DENY,
            reason="ACL matrix not loaded — Fail-Closed.",
        )

    allowed = acl_matrix.get(car.source_agent, [])
    if car.destination_service in allowed:
        return RuleResult(
            rule_name="ACL_PERMISSION",
            verdict=RuleVerdict.ALLOW,
            reason=f"{car.source_agent} → {car.destination_service} permitted.",
        )
    return RuleResult(
        rule_name="ACL_PERMISSION",
        verdict=RuleVerdict.DENY,
        reason=f"{car.source_agent} is not permitted to access {car.destination_service}.",
    )


def evaluate_rate(
    car: CanonicalActionRepresentation,
    rate_limiter: RateLimiter,
) -> RuleResult:
    """RATE: Per-agent sliding-window rate limiting.

    Args:
        car: The CAR to evaluate.
        rate_limiter: Active RateLimiter instance.

    Returns:
        ALLOW if within budget (request is recorded).
        DENY if over budget (request is NOT recorded).
    """
    allowed, count = rate_limiter.check_and_record(car.source_agent)
    if not allowed:
        return RuleResult(
            rule_name="RATE_LIMIT",
            verdict=RuleVerdict.DENY,
            reason=(
                f"{car.source_agent} exceeded rate limit: "
                f"{count}/{rate_limiter.max_requests} in "
                f"{rate_limiter.window_seconds}s window."
            ),
        )
    return RuleResult(
        rule_name="RATE_LIMIT",
        verdict=RuleVerdict.ALLOW,
        reason=(
            f"{car.source_agent} within rate limit: "
            f"{count}/{rate_limiter.max_requests}."
        ),
    )


def evaluate_resource(
    car: CanonicalActionRepresentation,
    deny_rules: list[ResourceDenyRule],
) -> RuleResult:
    """RESOURCE: Resource-specific deny list evaluation.

    Rules are evaluated in order. First matching rule triggers DENY.
    Verb constraint: if the rule specifies a verb, it only matches CARs
    with that exact verb. If verb is None, it matches all verbs.

    Args:
        car: The CAR to evaluate.
        deny_rules: Ordered list of ResourceDenyRule from deny_list.toml.
    """
    for rule in deny_rules:
        # Verb filter: skip rule if verb is specified and doesn't match
        if rule.verb is not None and car.verb.value != rule.verb:
            continue
        if fnmatch.fnmatch(car.resource, rule.resource_pattern):
            return RuleResult(
                rule_name="RESOURCE_DENY_LIST",
                verdict=RuleVerdict.DENY,
                reason=rule.reason,
            )
    return RuleResult(
        rule_name="RESOURCE_DENY_LIST",
        verdict=RuleVerdict.ALLOW,
        reason="Resource not on deny list.",
    )


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------

def run_rule_engine(
    car: CanonicalActionRepresentation,
    acl_matrix: dict[str, list[str]] | None = None,
    *,
    rate_limiter: RateLimiter | None = None,
    resource_deny_list: list[ResourceDenyRule] | None = None,
) -> RuleEngineResult:
    """Execute the full deterministic rule pipeline on a CAR.

    Execution order: STRUCTURAL → SENSITIVITY → ACL → RATE → RESOURCE.
    True short-circuit: any DENY terminates the pipeline immediately.
    Subsequent rules are NOT evaluated (prevents RATE counter inflation
    on structurally invalid or ACL-denied requests).

    RATE and RESOURCE rules are optional. If their parameters are None,
    the corresponding stage is skipped (backward-compatible with P1.0/P1.1
    callers that only pass acl_matrix).

    Args:
        car: The CAR to adjudicate.
        acl_matrix: Source-agent → destination permission matrix.
        rate_limiter: Active RateLimiter instance (keyword-only, optional).
        resource_deny_list: Ordered deny rules (keyword-only, optional).

    Returns:
        RuleEngineResult with aggregated verdicts from evaluated rules.
    """
    results: list[RuleResult] = []

    # Stage 1: STRUCTURAL
    r = evaluate_structural(car)
    results.append(r)
    if r.verdict == RuleVerdict.DENY:
        return RuleEngineResult(passed=False, results=tuple(results), blocking_rule=r.rule_name)

    # Stage 2: SENSITIVITY
    r = evaluate_sensitivity(car)
    results.append(r)
    if r.verdict == RuleVerdict.DENY:
        return RuleEngineResult(passed=False, results=tuple(results), blocking_rule=r.rule_name)

    # Stage 3: ACL
    r = evaluate_acl(car, acl_matrix)
    results.append(r)
    if r.verdict == RuleVerdict.DENY:
        return RuleEngineResult(passed=False, results=tuple(results), blocking_rule=r.rule_name)

    # Stage 4: RATE (optional — skip if no rate_limiter provided)
    if rate_limiter is not None:
        r = evaluate_rate(car, rate_limiter)
        results.append(r)
        if r.verdict == RuleVerdict.DENY:
            return RuleEngineResult(
                passed=False, results=tuple(results), blocking_rule=r.rule_name,
            )

    # Stage 5: RESOURCE (optional — skip if no deny list provided)
    if resource_deny_list is not None:
        r = evaluate_resource(car, resource_deny_list)
        results.append(r)
        if r.verdict == RuleVerdict.DENY:
            return RuleEngineResult(
                passed=False, results=tuple(results), blocking_rule=r.rule_name,
            )

    return RuleEngineResult(passed=True, results=tuple(results))
