"""
RATE + RESOURCE Rule Tests — Policy Agent
=============================================
P1.2: Tests for the new RATE and RESOURCE rules, and the extended
5-stage pipeline (STRUCTURAL → SENSITIVITY → ACL → RATE → RESOURCE).

Also includes Tier-1 security hardening tests for the P-004
external-network deny coverage in deny_list.toml (Section
TestDenyListExternalNetworkSchemes).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from shared.schemas.car import ActionVerb, CanonicalActionRepresentation, Sensitivity
from services.policy_agent.src.config_loader import ResourceDenyRule, load_resource_deny_list
from services.policy_agent.src.rule_engine import (
    RateLimiter,
    RuleVerdict,
    evaluate_rate,
    evaluate_resource,
    run_rule_engine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_car(
    source: str = "orch",
    dest: str = "substrate",
    verb: ActionVerb = ActionVerb.READ,
    resource: str = "substrate.vector_store",
    sensitivity: Sensitivity = Sensitivity.INTERNAL,
) -> CanonicalActionRepresentation:
    return CanonicalActionRepresentation(
        source_agent=source,
        destination_service=dest,
        verb=verb,
        resource=resource,
        request_id="req-rate-1",
        sensitivity=sensitivity,
    )


ACL_MATRIX = {"orch": ["substrate"], "code_agent": ["substrate"]}

DENY_RULES = [
    ResourceDenyRule(verb=None, resource_pattern="system.shutdown", reason="Prohibited"),
    ResourceDenyRule(verb="DELETE", resource_pattern="substrate.*", reason="No delete"),
    ResourceDenyRule(verb="EGRESS", resource_pattern="*", reason="No egress"),
]


# ---------------------------------------------------------------------------
# Rate Limiter Unit Tests
# ---------------------------------------------------------------------------

class TestRateLimiter:
    """Sliding-window rate limiter."""

    def test_within_budget(self) -> None:
        """Requests within budget are allowed."""
        rl = RateLimiter(max_requests=5, window_seconds=60.0)
        for i in range(5):
            allowed, count = rl.check_and_record("agent_a")
            assert allowed, f"Request {i} should be allowed"
            assert count == i + 1

    def test_exceeds_budget(self) -> None:
        """Request exceeding budget is denied."""
        rl = RateLimiter(max_requests=3, window_seconds=60.0)
        for _ in range(3):
            rl.check_and_record("agent_a")
        allowed, count = rl.check_and_record("agent_a")
        assert not allowed
        assert count == 3  # Count doesn't increase on denial

    def test_agents_independent(self) -> None:
        """Different agents have independent budgets."""
        rl = RateLimiter(max_requests=2, window_seconds=60.0)
        rl.check_and_record("a")
        rl.check_and_record("a")
        # Agent 'a' is at budget
        allowed_a, _ = rl.check_and_record("a")
        assert not allowed_a
        # Agent 'b' should still have full budget
        allowed_b, count_b = rl.check_and_record("b")
        assert allowed_b
        assert count_b == 1

    def test_reset_single_agent(self) -> None:
        """Reset a single agent's window."""
        rl = RateLimiter(max_requests=2, window_seconds=60.0)
        rl.check_and_record("agent_a")
        rl.check_and_record("agent_a")
        rl.reset("agent_a")
        allowed, count = rl.check_and_record("agent_a")
        assert allowed
        assert count == 1

    def test_reset_all(self) -> None:
        """Reset all agents."""
        rl = RateLimiter(max_requests=2, window_seconds=60.0)
        rl.check_and_record("a")
        rl.check_and_record("b")
        rl.reset()
        assert rl.current_count("a") == 0
        assert rl.current_count("b") == 0

    def test_current_count(self) -> None:
        """current_count returns count without recording."""
        rl = RateLimiter(max_requests=10, window_seconds=60.0)
        rl.check_and_record("a")
        rl.check_and_record("a")
        assert rl.current_count("a") == 2
        # Calling current_count should not change the count
        assert rl.current_count("a") == 2

    def test_denied_request_not_recorded(self) -> None:
        """Denied requests do NOT inflate the counter."""
        rl = RateLimiter(max_requests=2, window_seconds=60.0)
        rl.check_and_record("a")
        rl.check_and_record("a")
        # Budget exhausted — next request denied but count stays at 2
        rl.check_and_record("a")
        rl.check_and_record("a")
        assert rl.current_count("a") == 2

    def test_sliding_window_evicts_expired_requests(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Entries older than window_seconds are evicted: once the window
        passes, previously over-budget agents should again be within budget.

        RateLimiter reads time via ``time.monotonic`` (rule_engine.py).
        Monkeypatch the module-level ``time.monotonic`` to a fake clock so the
        test is fast and deterministic without a real sleep.
        """
        fake_now = {"t": 1_000.0}

        def _fake_monotonic() -> float:
            return fake_now["t"]

        monkeypatch.setattr(
            "services.policy_agent.src.rule_engine.time.monotonic",
            _fake_monotonic,
        )

        rl = RateLimiter(max_requests=2, window_seconds=0.05)

        allowed_1, count_1 = rl.check_and_record("orch")
        allowed_2, count_2 = rl.check_and_record("orch")
        assert allowed_1 is True and count_1 == 1
        assert allowed_2 is True and count_2 == 2

        # Third request at the same instant must be denied (at capacity).
        allowed_3, count_3 = rl.check_and_record("orch")
        assert allowed_3 is False
        assert count_3 == 2

        # Advance the fake clock past the window — the two earlier timestamps
        # are now older than window_seconds and must be evicted on next check.
        fake_now["t"] += 0.06
        allowed_4, count_4 = rl.check_and_record("orch")
        assert allowed_4 is True
        assert count_4 == 1


# ---------------------------------------------------------------------------
# evaluate_rate Unit Tests
# ---------------------------------------------------------------------------

class TestEvaluateRate:
    """RATE rule evaluator."""

    def test_within_limit_allows(self) -> None:
        rl = RateLimiter(max_requests=10, window_seconds=60.0)
        car = _make_car()
        result = evaluate_rate(car, rl)
        assert result.verdict == RuleVerdict.ALLOW
        assert result.rule_name == "RATE_LIMIT"

    def test_over_limit_denies(self) -> None:
        rl = RateLimiter(max_requests=1, window_seconds=60.0)
        car = _make_car()
        evaluate_rate(car, rl)  # First request OK
        result = evaluate_rate(car, rl)  # Second request denied
        assert result.verdict == RuleVerdict.DENY
        assert "exceeded rate limit" in result.reason


# ---------------------------------------------------------------------------
# evaluate_resource Unit Tests
# ---------------------------------------------------------------------------

class TestEvaluateResource:
    """RESOURCE deny list evaluator."""

    def test_matching_wildcard_denies(self) -> None:
        """Resource matching a deny rule → DENY."""
        car = _make_car(resource="system.shutdown")
        result = evaluate_resource(car, DENY_RULES)
        assert result.verdict == RuleVerdict.DENY
        assert result.rule_name == "RESOURCE_DENY_LIST"
        assert "Prohibited" in result.reason

    def test_non_matching_allows(self) -> None:
        """Resource not on deny list → ALLOW."""
        car = _make_car(resource="substrate.vector_store")
        result = evaluate_resource(car, DENY_RULES)
        assert result.verdict == RuleVerdict.ALLOW

    def test_verb_constrained_deny_matches(self) -> None:
        """DELETE + substrate.* → DENY (verb matches)."""
        car = _make_car(verb=ActionVerb.DELETE, resource="substrate.embeddings")
        result = evaluate_resource(car, DENY_RULES)
        assert result.verdict == RuleVerdict.DENY
        assert "No delete" in result.reason

    def test_verb_constrained_deny_no_match(self) -> None:
        """READ + substrate.* → ALLOW (verb doesn't match DELETE rule)."""
        car = _make_car(verb=ActionVerb.READ, resource="substrate.embeddings")
        result = evaluate_resource(car, DENY_RULES)
        assert result.verdict == RuleVerdict.ALLOW

    def test_egress_wildcard_denies_all(self) -> None:
        """EGRESS + * → DENY (wildcard resource, verb-constrained)."""
        car = _make_car(verb=ActionVerb.EGRESS, resource="anything.at.all")
        result = evaluate_resource(car, DENY_RULES)
        assert result.verdict == RuleVerdict.DENY
        assert "No egress" in result.reason

    def test_empty_deny_list_allows(self) -> None:
        """Empty deny list → ALLOW (no rules to match)."""
        car = _make_car(resource="system.shutdown")
        result = evaluate_resource(car, [])
        assert result.verdict == RuleVerdict.ALLOW

    def test_first_matching_rule_wins(self) -> None:
        """First matching rule triggers DENY (order matters)."""
        rules = [
            ResourceDenyRule(verb=None, resource_pattern="x", reason="rule-A"),
            ResourceDenyRule(verb=None, resource_pattern="x", reason="rule-B"),
        ]
        car = _make_car(resource="x")
        result = evaluate_resource(car, rules)
        assert result.verdict == RuleVerdict.DENY
        assert "rule-A" in result.reason  # First match, not second


# ---------------------------------------------------------------------------
# Extended Pipeline Tests (5-stage)
# ---------------------------------------------------------------------------

class TestExtendedPipeline:
    """Full 5-stage pipeline: STRUCTURAL → SENSITIVITY → ACL → RATE → RESOURCE."""

    def test_all_five_rules_pass(self) -> None:
        """Valid CAR with all rules → 5 results, all ALLOW."""
        rl = RateLimiter(max_requests=100, window_seconds=60.0)
        car = _make_car()
        result = run_rule_engine(
            car,
            acl_matrix=ACL_MATRIX,
            rate_limiter=rl,
            resource_deny_list=DENY_RULES,
        )
        assert result.passed
        assert len(result.results) == 5
        names = [r.rule_name for r in result.results]
        assert names == [
            "STRUCTURAL_COMPLETENESS",
            "SENSITIVITY_CLASSIFICATION",
            "ACL_PERMISSION",
            "RATE_LIMIT",
            "RESOURCE_DENY_LIST",
        ]

    def test_rate_deny_short_circuits_before_resource(self) -> None:
        """RATE DENY → RESOURCE never evaluated (true short-circuit)."""
        rl = RateLimiter(max_requests=1, window_seconds=60.0)
        car = _make_car()
        # Exhaust rate budget
        run_rule_engine(car, acl_matrix=ACL_MATRIX, rate_limiter=rl, resource_deny_list=DENY_RULES)
        # Second request → rate limited
        result = run_rule_engine(
            car, acl_matrix=ACL_MATRIX, rate_limiter=rl, resource_deny_list=DENY_RULES,
        )
        assert not result.passed
        assert result.blocking_rule == "RATE_LIMIT"
        # Result contains only 4 rules (RESOURCE not evaluated)
        assert len(result.results) == 4

    def test_resource_deny_blocks(self) -> None:
        """RESOURCE deny on matching resource."""
        rl = RateLimiter(max_requests=100, window_seconds=60.0)
        car = _make_car(resource="system.shutdown")
        result = run_rule_engine(
            car, acl_matrix=ACL_MATRIX, rate_limiter=rl, resource_deny_list=DENY_RULES,
        )
        assert not result.passed
        assert result.blocking_rule == "RESOURCE_DENY_LIST"

    def test_structural_deny_short_circuits_all(self) -> None:
        """STRUCTURAL DENY → only 1 result (everything else skipped)."""
        rl = RateLimiter(max_requests=100, window_seconds=60.0)
        car = _make_car(source="")  # Incomplete CAR
        result = run_rule_engine(
            car, acl_matrix=ACL_MATRIX, rate_limiter=rl, resource_deny_list=DENY_RULES,
        )
        assert not result.passed
        assert result.blocking_rule == "STRUCTURAL_COMPLETENESS"
        assert len(result.results) == 1

    def test_backward_compat_no_rate_no_resource(self) -> None:
        """Without rate_limiter/resource_deny_list → 3-rule pipeline (P1.0 compat)."""
        car = _make_car()
        result = run_rule_engine(car, acl_matrix=ACL_MATRIX)
        assert result.passed
        assert len(result.results) == 3
        names = [r.rule_name for r in result.results]
        assert names == [
            "STRUCTURAL_COMPLETENESS",
            "SENSITIVITY_CLASSIFICATION",
            "ACL_PERMISSION",
        ]

    def test_rate_not_incremented_on_acl_deny(self) -> None:
        """ACL DENY → RATE not reached → counter not incremented."""
        rl = RateLimiter(max_requests=100, window_seconds=60.0)
        car = _make_car(source="unknown_agent")  # Not in ACL
        result = run_rule_engine(
            car, acl_matrix=ACL_MATRIX, rate_limiter=rl, resource_deny_list=DENY_RULES,
        )
        assert not result.passed
        assert result.blocking_rule == "ACL_PERMISSION"
        # Rate counter should be 0 — RATE was never evaluated
        assert rl.current_count("unknown_agent") == 0

    def test_delete_substrate_denied_by_resource(self) -> None:
        """DELETE on substrate.* caught by resource deny list."""
        rl = RateLimiter(max_requests=100, window_seconds=60.0)
        car = _make_car(verb=ActionVerb.DELETE, resource="substrate.embeddings")
        result = run_rule_engine(
            car, acl_matrix=ACL_MATRIX, rate_limiter=rl, resource_deny_list=DENY_RULES,
        )
        assert not result.passed
        assert result.blocking_rule == "RESOURCE_DENY_LIST"

    def test_egress_verb_denied_by_resource(self) -> None:
        """EGRESS verb unconditionally denied by deny list wildcard."""
        rl = RateLimiter(max_requests=100, window_seconds=60.0)
        car = _make_car(verb=ActionVerb.EGRESS, resource="any.service")
        result = run_rule_engine(
            car, acl_matrix=ACL_MATRIX, rate_limiter=rl, resource_deny_list=DENY_RULES,
        )
        assert not result.passed
        assert result.blocking_rule == "RESOURCE_DENY_LIST"


# ---------------------------------------------------------------------------
# Tier-1 Hardening: P-004 external-network deny_list.toml coverage
# ---------------------------------------------------------------------------


def _load_live_deny_list() -> list[ResourceDenyRule]:
    """Load the canonical deny_list.toml from the PA config directory.

    Resolves relative to this test file: tests/ → .. → config/deny_list.toml.
    Returns the parsed list so tests run against the actual TOML on disk, not
    a hard-coded fixture.
    """
    config_dir = Path(__file__).parent.parent / "config"
    deny_path = config_dir / "deny_list.toml"
    rules = load_resource_deny_list(deny_path)
    assert rules is not None, (
        f"deny_list.toml failed to load from {deny_path}. "
        "Ensure the file exists and is valid TOML."
    )
    return rules


def _make_resource_car(resource: str, verb: ActionVerb = ActionVerb.READ) -> CanonicalActionRepresentation:
    """Minimal CAR for evaluate_resource tests."""
    return CanonicalActionRepresentation(
        source_agent="orch",
        destination_service="substrate",
        verb=verb,
        resource=resource,
        request_id="req-p004-test",
        sensitivity=Sensitivity.INTERNAL,
    )


class TestDenyListExternalNetworkSchemes:
    """Tier-1 hardening: deny_list.toml must deny all external-network URI schemes.

    These tests load the live deny_list.toml from disk and exercise
    evaluate_resource directly.  They are the defence-in-depth layer beneath
    DeterministicPolicyChecker RULE 3: even if a future caller reaches the
    rule engine without going through the DeterministicPolicyChecker, the
    deny list catches every external-network scheme.

    TEETH: before the Tier-1 hardening commit, deny_list.toml contained NO
    URI-scheme patterns — evaluate_resource returned ALLOW for every scheme
    below.  Any regression that strips these entries from deny_list.toml will
    immediately flip these tests back to failing.
    """

    def test_deny_list_http_scheme(self) -> None:
        """deny_list.toml must deny http:// resources via evaluate_resource.

        TEETH: pre-hardening, deny_list.toml had no http:// entry →
        evaluate_resource returned ALLOW.
        """
        rules = _load_live_deny_list()
        car = _make_resource_car("http://attacker.example.com/steal")
        result = evaluate_resource(car, rules)
        assert result.verdict == RuleVerdict.DENY, (
            "http:// resource must be denied by deny_list.toml — pre-hardening "
            "this returned ALLOW (no matching rule existed)"
        )

    def test_deny_list_https_scheme(self) -> None:
        """deny_list.toml must deny https:// resources via evaluate_resource.

        TEETH: pre-hardening, deny_list.toml had no https:// entry →
        evaluate_resource returned ALLOW.
        """
        rules = _load_live_deny_list()
        car = _make_resource_car("https://attacker.example.com/steal")
        result = evaluate_resource(car, rules)
        assert result.verdict == RuleVerdict.DENY, (
            "https:// resource must be denied by deny_list.toml — pre-hardening "
            "this returned ALLOW (no matching rule existed)"
        )

    def test_deny_list_ftp_scheme(self) -> None:
        """deny_list.toml must deny ftp:// resources via evaluate_resource.

        TEETH: pre-hardening, deny_list.toml had no ftp:// entry →
        evaluate_resource returned ALLOW.
        """
        rules = _load_live_deny_list()
        car = _make_resource_car("ftp://attacker.example.com/data.tar.gz")
        result = evaluate_resource(car, rules)
        assert result.verdict == RuleVerdict.DENY, (
            "ftp:// resource must be denied by deny_list.toml — pre-hardening "
            "this returned ALLOW (no matching rule existed)"
        )

    def test_deny_list_ftps_scheme(self) -> None:
        """deny_list.toml must deny ftps:// resources via evaluate_resource.

        TEETH: pre-hardening, deny_list.toml had no ftps:// entry →
        evaluate_resource returned ALLOW.
        """
        rules = _load_live_deny_list()
        car = _make_resource_car("ftps://attacker.example.com/secrets.zip")
        result = evaluate_resource(car, rules)
        assert result.verdict == RuleVerdict.DENY, (
            "ftps:// resource must be denied by deny_list.toml — pre-hardening "
            "this returned ALLOW (no matching rule existed)"
        )

    def test_deny_list_ws_scheme(self) -> None:
        """deny_list.toml must deny ws:// resources via evaluate_resource.

        TEETH: pre-hardening, deny_list.toml had no ws:// entry →
        evaluate_resource returned ALLOW.
        """
        rules = _load_live_deny_list()
        car = _make_resource_car("ws://c2-server.attacker.com/shell")
        result = evaluate_resource(car, rules)
        assert result.verdict == RuleVerdict.DENY, (
            "ws:// resource must be denied by deny_list.toml — pre-hardening "
            "this returned ALLOW (no matching rule existed)"
        )

    def test_deny_list_wss_scheme(self) -> None:
        """deny_list.toml must deny wss:// resources via evaluate_resource.

        TEETH: pre-hardening, deny_list.toml had no wss:// entry →
        evaluate_resource returned ALLOW.
        """
        rules = _load_live_deny_list()
        car = _make_resource_car("wss://c2-server.attacker.com/secure-shell")
        result = evaluate_resource(car, rules)
        assert result.verdict == RuleVerdict.DENY, (
            "wss:// resource must be denied by deny_list.toml — pre-hardening "
            "this returned ALLOW (no matching rule existed)"
        )

    def test_deny_list_gopher_scheme(self) -> None:
        """deny_list.toml must deny gopher:// resources via evaluate_resource.

        TEETH: pre-hardening, deny_list.toml had no gopher:// entry →
        evaluate_resource returned ALLOW.
        """
        rules = _load_live_deny_list()
        car = _make_resource_car("gopher://internal-redis:6379/_SET key exfil")
        result = evaluate_resource(car, rules)
        assert result.verdict == RuleVerdict.DENY, (
            "gopher:// resource must be denied by deny_list.toml — pre-hardening "
            "this returned ALLOW (no matching rule existed)"
        )

    def test_deny_list_legitimate_resource_still_allowed(self) -> None:
        """Sanity: the new URI-scheme entries must not false-positive on
        a legitimate POSIX-path resource."""
        rules = _load_live_deny_list()
        car = _make_resource_car("/home/user/.blarai/workspace/notes.txt")
        result = evaluate_resource(car, rules)
        assert result.verdict == RuleVerdict.ALLOW, (
            "Legitimate POSIX-path resource must not be caught by "
            "the URI-scheme deny rules (false-positive regression)."
        )
