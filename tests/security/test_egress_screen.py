"""Egress-machinery mechanism locks — exfil screen + PA carve-out (C3, H-b).

Sprint 17 "The Boot Cluster", criterion C3 (ADR-027 egress machinery,
STAGED/DORMANT), stream H-b. These tests lock the *mechanism* that WOULD screen
and adjudicate outbound network egress when web features ship (post-#556). They
change no runtime behaviour: the air-gap stays welded this sprint (the live
egress allowlist is loopback + vsock only, ADR-020), so the carve-out below is
dormant in production — its allowlist default is EMPTY and every external URL is
still denied.

Locks (this file's share of the C3 mechanism locks, SDV §4):
  * the exfil screen BLOCKS on a secret/PII payload (fail-closed, ADR-027 §4);
  * an allowlisted, PA-adjudicated egress is auto-approved + logged (ADR-027 §2),
    exercised with a TEST allowlist entry since the live list has no external
    endpoints;
  * an off-allowlist external URL is hard-denied (RULE 3 DENY_EXTERNAL_NETWORK);
  * the carve-out is DORMANT by default (empty allowlist → external still denied);
  * THE SEAM LOCK — a simulated detection through the screen FIRES
    egress_guard.trip() over stream H-a's real wiring (guarded with
    importorskip so it SKIPS cleanly until H-a's interface merges; the
    Orchestrator verifies it RUNS-and-passes at the H-b merge-gate).

This file is distinct from tests/security/test_egress_core.py (stream H-a) and
tests/security/test_production_posture.py (stream J) to avoid collisions.
"""

from __future__ import annotations

import logging

import pytest

from shared.security import exfil_screen
from shared.security.exfil_screen import Detection, screen
from services.policy_agent.src.car import build_car
from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker
from shared.schemas.car import ActionVerb, Sensitivity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A TEST-ONLY allowlist entry. The LIVE allowlist (owned by stream H-a) has NO
# external endpoints this sprint — the air-gap is welded. We inject this purely
# to exercise the auto-approve mechanism; it never touches the live default.
_TEST_ALLOWED_HOST = "kagi.com"
_TEST_ALLOWLIST: frozenset[str] = frozenset({_TEST_ALLOWED_HOST})


def _egress_car(resource: str) -> object:
    """Build a CAR representing an outbound egress action to ``resource``."""
    return build_car(
        source_agent="assistant_orchestrator",
        destination_service="assistant_orchestrator",
        verb=ActionVerb.EXECUTE,
        resource=resource,
        sensitivity=Sensitivity.INTERNAL,
        parameters_schema={},
        session_id="test-egress",
    )


# ---------------------------------------------------------------------------
# Exfil screen — block-on-detection (ADR-027 §4)
# ---------------------------------------------------------------------------


class TestExfilScreenBlocksOnDetection:
    """The outbound screen fails closed on any secret/PII (ADR-027 §4)."""

    def test_clean_payload_is_not_blocked(self) -> None:
        """A payload with no secrets/PII passes — blocked=False, no labels."""
        result = screen("the weather in Paris tomorrow afternoon")
        assert isinstance(result, Detection)
        assert result.blocked is False
        assert result.detected is False
        assert result.labels == ()
        assert result.spans == ()

    def test_blocks_on_secret_credential_payload(self) -> None:
        """A PEM private key in the payload BLOCKS the egress (fail-closed)."""
        payload = (
            "please upload this:\n"
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA1234567890abcdef\n"
            "-----END RSA PRIVATE KEY-----\n"
        )
        result = screen(payload)
        assert result.blocked is True
        assert "PRIVATE_KEY_PEM" in result.labels
        # The report carries labels + offsets, never the raw secret value.
        assert "BEGIN RSA PRIVATE KEY" not in result.reason

    def test_blocks_on_generic_secret_assignment(self) -> None:
        """A generic ``api_key=<value>`` assignment BLOCKS (credential layer)."""
        result = screen("config: api_key=sk_live_ABCDEF0123456789ghij")
        assert result.blocked is True
        assert "SECRET_ASSIGNMENT" in result.labels

    def test_blocks_on_pii_payload_via_reused_pgov_path(self) -> None:
        """PII (an SSN) BLOCKS — and the hit is attributed to the reused PGOV
        recognizer path (the single source of truth, not a re-implementation)."""
        result = screen("ship to John, SSN 123-45-6789, thanks")
        assert result.blocked is True
        assert "SSN" in result.labels
        # The SSN hit must come from the reused PGOV path, proving reuse.
        assert any(s.label == "SSN" and s.source == "pgov" for s in result.spans)

    def test_blocks_on_email_pii(self) -> None:
        """An email address is PII and BLOCKS the outbound payload."""
        result = screen("contact me at alice.smith@example.com")
        assert result.blocked is True
        assert "EMAIL" in result.labels

    def test_bytes_payload_is_screened(self) -> None:
        """A bytes payload is decoded and screened (not silently skipped)."""
        result = screen(b"my ssn is 123-45-6789")
        assert result.blocked is True
        assert "SSN" in result.labels

    def test_undecodable_bytes_block_fail_closed(self) -> None:
        """A non-UTF-8 payload cannot be proven clean → BLOCK (fail-closed)."""
        result = screen(b"\xff\xfe\x00\x01 invalid utf-8 \x80")
        assert result.blocked is True
        assert result.labels == ("UNDECODABLE_PAYLOAD",)

    def test_screen_never_raises_on_recognizer_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If a recognizer blows up, the screen BLOCKS rather than failing open."""

        def _boom(_text: str) -> list:
            raise RuntimeError("recognizer exploded")

        monkeypatch.setattr(exfil_screen, "_find_pii_spans", _boom)
        result = screen("anything at all")
        assert result.blocked is True
        assert result.labels == ("SCREEN_ERROR",)

    def test_spans_carry_offsets_not_raw_values(self) -> None:
        """Detection spans expose label + offsets only — never the raw secret."""
        result = screen("ssn 123-45-6789")
        assert result.spans
        for span in result.spans:
            assert isinstance(span.start, int) and isinstance(span.end, int)
            assert span.end > span.start
            assert span.source in {"pgov", "secret"}


# ---------------------------------------------------------------------------
# PA DENY_EXTERNAL_NETWORK carve-out (ADR-027 §2) — auto-approve / deny / dormant
# ---------------------------------------------------------------------------


class TestPaEgressCarveOut:
    """The PA RULE 3 carve-out: allowlisted egress auto-approved, off-list denied,
    EMPTY-by-default (dormant). RULE 3 lives in DeterministicPolicyChecker — the
    single source of truth enforced at both the PA boundary and the AO tool loop.
    """

    def test_off_allowlist_external_url_is_hard_denied(self) -> None:
        """An external URL NOT on the allowlist stays DENY_EXTERNAL_NETWORK."""
        car = _egress_car("https://evil-exfil.example.com/steal")
        result = DeterministicPolicyChecker.check(car, egress_allowlist=_TEST_ALLOWLIST)
        assert result == ("DENY", "DENY_EXTERNAL_NETWORK")

    def test_allowlisted_egress_is_auto_approved(self) -> None:
        """An external URL whose host IS allowlisted is auto-approved (None)."""
        car = _egress_car("https://kagi.com/search?q=weather")
        result = DeterministicPolicyChecker.check(car, egress_allowlist=_TEST_ALLOWLIST)
        assert result is None  # None == ALLOW / proceed (ADR-027 §2 auto-approve)

    def test_allowlisted_egress_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ADR-027 §2 requires every auto-approved call be logged to the audit
        stream. Assert the carve-out emits the auto-APPROVED log line."""
        car = _egress_car("https://kagi.com/search?q=weather")
        with caplog.at_level(
            logging.INFO, logger="services.policy_agent.src.gpu_inference"
        ):
            result = DeterministicPolicyChecker.check(
                car, egress_allowlist=_TEST_ALLOWLIST
            )
        assert result is None
        assert any(
            "auto-APPROVED" in rec.message and "kagi.com" in rec.message
            for rec in caplog.records
        ), "auto-approved egress must be logged (ADR-027 §2)"

    def test_allowlist_host_match_ignores_port_and_path(self) -> None:
        """Host-based allowlisting: the same host on a different port/path matches
        (the allowlist is host-scoped, not full-URL-scoped)."""
        car = _egress_car("https://kagi.com:443/api/v1/search")
        result = DeterministicPolicyChecker.check(car, egress_allowlist=_TEST_ALLOWLIST)
        assert result is None

    def test_subdomain_is_not_allowlisted_by_host_entry(self) -> None:
        """Fail-closed host match: a subdomain of an allowlisted host is NOT
        itself allowlisted (no implicit wildcard) — it stays denied."""
        car = _egress_car("https://evil.kagi.com.attacker.example/x")
        result = DeterministicPolicyChecker.check(car, egress_allowlist=_TEST_ALLOWLIST)
        assert result == ("DENY", "DENY_EXTERNAL_NETWORK")

    @pytest.mark.parametrize(
        "scheme_url",
        [
            "http://kagi.com/x",
            "https://kagi.com/x",
        ],
    )
    def test_allowlist_applies_across_http_and_https(self, scheme_url: str) -> None:
        """The carve-out matches on host regardless of http/https scheme."""
        car = _egress_car(scheme_url)
        result = DeterministicPolicyChecker.check(car, egress_allowlist=_TEST_ALLOWLIST)
        assert result is None

    def test_non_http_scheme_to_allowlisted_host_still_denied(self) -> None:
        """Defence in depth: a non-web exfil scheme (ftp/ws/gopher) to an
        otherwise-allowlisted host is still DENIED — the carve-out is for web
        egress, not arbitrary protocols."""
        for url in (
            "ftp://kagi.com/x",
            "ws://kagi.com/x",
            "gopher://kagi.com/x",
        ):
            car = _egress_car(url)
            result = DeterministicPolicyChecker.check(
                car, egress_allowlist=_TEST_ALLOWLIST
            )
            assert result == ("DENY", "DENY_EXTERNAL_NETWORK"), url


class TestPaEgressCarveOutDormant:
    """The carve-out's LIVE posture (2026-07-02 web_search go-live, #719):
    the default allowlist holds EXACTLY ``kagi.com`` — the one host the
    web_search feature needs (ADR-027 §1/§2 activation record). Everything
    off-list is still RULE-3 denied; adding ANY host without its own
    go-live ceremony breaks the exact-set lock below loudly."""

    def test_default_allowlist_denies_off_list_external(self) -> None:
        """With no allowlist argument (the live runtime path), an external URL
        whose host is NOT allowlisted is denied — the welded posture for
        every host except the one vetted feature endpoint."""
        car = _egress_car("https://api.example.com/v1/data")
        result = DeterministicPolicyChecker.check(car)  # no egress_allowlist
        assert result == ("DENY", "DENY_EXTERNAL_NETWORK")

    def test_class_default_allowlist_is_exactly_kagi(self) -> None:
        """The shipped class default is EXACTLY ``{"kagi.com"}`` (web_search
        go-live, #719 / ADR-027 activation record 2026-07-02). If a future
        change adds ANY host without its own reviewed go-live ceremony —
        or empties it outside the documented re-weld procedure — THIS lock
        breaks loudly (the one-list, one-ceremony-per-host guarantee)."""
        assert DeterministicPolicyChecker._EGRESS_ALLOWLIST == frozenset(
            {"kagi.com"}
        )

    def test_default_allowlist_approves_the_kagi_endpoint(self) -> None:
        """The live runtime path auto-approves the ONE vetted feature endpoint
        (the ADR-027 §2 carve-out doing its job post-ceremony)."""
        car = _egress_car("https://kagi.com/api/v1/search")
        result = DeterministicPolicyChecker.check(car)  # no egress_allowlist
        assert result is None

    def test_explicit_empty_allowlist_denies_external(self) -> None:
        """An explicitly empty allowlist denies too (no accidental allow-all)."""
        car = _egress_car("https://kagi.com/search")
        result = DeterministicPolicyChecker.check(car, egress_allowlist=frozenset())
        assert result == ("DENY", "DENY_EXTERNAL_NETWORK")

    def test_carveout_does_not_disturb_existing_deny_rules(self) -> None:
        """The carve-out is additive: a restricted-path CAR still DENIES on
        RULE 1 (the carve-out only touches RULE 3 external URLs)."""
        car = _egress_car("/etc/shadow")
        result = DeterministicPolicyChecker.check(car, egress_allowlist=_TEST_ALLOWLIST)
        assert result == ("DENY", "DENY_RESTRICTED_PATH")


# ---------------------------------------------------------------------------
# THE SEAM LOCK — a simulated detection FIRES egress_guard.trip() (real wiring).
# ---------------------------------------------------------------------------


class TestExfilScreenSeamToEgressGuard:
    """The block-on-detect seam: a screen block fires the kill-switch auto-trip
    over stream H-a's real egress_guard interface (ADR-027 §3/§4).

    INTEGRATION NOTE: stream H-a (branch sprint17/ha-egress-core) exposes
    egress_guard.register_screener()/trip() and merges BEFORE H-b. In this
    isolated worktree (base main@148f3e1) that interface does not yet exist, so
    this test SKIPS cleanly via the capability check below. The Orchestrator
    verifies it RUNS-and-passes (not skips) at the H-b merge-gate after H-a lands.
    """

    def _require_egress_guard_interface(self) -> object:
        """Skip cleanly unless H-a's register_screener()/trip() are present."""
        egress_guard = pytest.importorskip(
            "shared.security.egress_guard",
            reason="egress_guard module absent",
        )
        if not hasattr(egress_guard, "trip") or not hasattr(
            egress_guard, "register_screener"
        ):
            pytest.skip(
                "stream H-a egress_guard.register_screener()/trip() not yet "
                "merged into this worktree base (main@148f3e1) — the seam test "
                "RUNS-and-passes at the H-b merge-gate after H-a lands"
            )
        return egress_guard

    def test_block_fires_egress_guard_trip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A simulated detection through screen_and_enforce() calls
        egress_guard.trip() exactly once with the block reason (the real wiring,
        block-on-detect → auto-trip, ADR-027 §3/§4)."""
        egress_guard = self._require_egress_guard_interface()

        tripped: list[str] = []
        monkeypatch.setattr(
            egress_guard, "trip", lambda reason: tripped.append(reason)
        )

        # A payload that the screen MUST block (an SSN — reused PGOV path).
        detection = exfil_screen.screen_and_enforce("leak: ssn 123-45-6789")

        assert detection.blocked is True
        assert len(tripped) == 1, "block-on-detect must fire trip() exactly once"
        assert "exfil screen blocked egress" in tripped[0]

    def test_clean_payload_does_not_fire_trip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A clean payload does NOT trip the kill-switch (no false positive)."""
        egress_guard = self._require_egress_guard_interface()

        tripped: list[str] = []
        monkeypatch.setattr(
            egress_guard, "trip", lambda reason: tripped.append(reason)
        )

        detection = exfil_screen.screen_and_enforce("the weather in Paris")

        assert detection.blocked is False
        assert tripped == [], "a clean payload must not trip the kill-switch"

    def test_screen_registers_as_a_screener(self) -> None:
        """The screen fn can be registered via H-a's register_screener() — the
        wiring contract H-b depends on (arm() invokes registered screeners)."""
        egress_guard = self._require_egress_guard_interface()
        # Must not raise; H-a's register_screener accepts a screen callable.
        egress_guard.register_screener(exfil_screen.screen)
