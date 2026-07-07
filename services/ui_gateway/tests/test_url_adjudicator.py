"""
URL-fetch Policy-Agent adjudicator factory (UC-003 Stage C host glue #655
sub-task 6c).

The reusable core of 6c — CAR construction + ALLOW/DENY/ESCALATE → Verdict
mapping — tested against a FAKE Policy Agent (no GPU, no live fetch).  The
go-live registration is exercised against the real ``guarded_fetch`` seam and
then CLEARED in teardown so no adjudicator leaks into the egress-default tests
(the door must stay deny-by-default everywhere else).
"""

from __future__ import annotations

import pytest

from services.ui_gateway.src.url_adjudicator import (
    IMAGE_INGEST_DENY_PURPOSES,
    URL_INGEST_DESTINATION,
    URL_INGEST_SOURCE_AGENT,
    build_url_car,
    decision_to_verdict,
    make_deterministic_url_adjudicate,
    make_operator_url_adjudicate,
    make_url_adjudicator,
    register_url_ingest_adjudicator,
)
from shared.schemas.car import ActionVerb, AdjudicationDecision, Sensitivity
from shared.security.guarded_fetch import (
    Verdict,
    active_url_adjudicator,
    clear_url_adjudicator,
)


@pytest.fixture(autouse=True)
def _no_adjudicator_leak():
    """The door starts and ends every test with NO adjudicator (deny-default)."""
    clear_url_adjudicator()
    yield
    clear_url_adjudicator()


class TestBuildUrlCar:
    def test_car_is_complete_and_egress(self) -> None:
        car = build_url_car("https://example.com/article", "uc003-url-ingest")
        assert car.is_complete()
        assert car.verb is ActionVerb.EGRESS
        assert car.resource == "https://example.com/article"
        assert car.sensitivity is Sensitivity.PUBLIC
        assert car.source_agent == URL_INGEST_SOURCE_AGENT
        assert car.destination_service == URL_INGEST_DESTINATION
        assert car.request_id  # a correlation id was minted

    def test_purpose_is_recorded_as_metadata(self) -> None:
        car = build_url_car("https://example.com/x", "uc003-url-ingest")
        assert car.parameters_schema["purpose"] == "uc003-url-ingest"
        assert car.parameters_schema["method"] == "GET"

    def test_distinct_request_ids(self) -> None:
        a = build_url_car("https://example.com/a", "p")
        b = build_url_car("https://example.com/b", "p")
        assert a.request_id != b.request_id


class TestDecisionToVerdict:
    def test_allow(self) -> None:
        assert decision_to_verdict(AdjudicationDecision.ALLOW) is Verdict.ALLOW

    def test_deny(self) -> None:
        assert decision_to_verdict(AdjudicationDecision.DENY) is Verdict.DENY

    def test_escalate(self) -> None:
        assert decision_to_verdict(AdjudicationDecision.ESCALATE) is Verdict.ESCALATE


class TestMakeUrlAdjudicator:
    @pytest.mark.parametrize(
        "decision,expected",
        [
            (AdjudicationDecision.ALLOW, Verdict.ALLOW),
            (AdjudicationDecision.DENY, Verdict.DENY),
            (AdjudicationDecision.ESCALATE, Verdict.ESCALATE),
        ],
    )
    def test_maps_pa_decision_to_verdict(self, decision, expected) -> None:
        seen: list = []

        def _pa(car):
            seen.append(car)
            return decision

        adjudicator = make_url_adjudicator(_pa)
        assert adjudicator("https://example.com/a", "uc003-url-ingest") is expected
        # The PA saw a real EGRESS CAR for that URL.
        assert len(seen) == 1
        assert seen[0].verb is ActionVerb.EGRESS
        assert seen[0].resource == "https://example.com/a"

    def test_pa_exception_fails_closed_deny(self) -> None:
        def _pa(car):
            raise RuntimeError("PA unreachable")

        adjudicator = make_url_adjudicator(_pa)
        assert adjudicator("https://example.com/a", "p") is Verdict.DENY

    def test_pa_non_decision_fails_closed_deny(self) -> None:
        def _pa(car):
            return "ALLOW"  # a string, not an AdjudicationDecision

        adjudicator = make_url_adjudicator(_pa)
        assert adjudicator("https://example.com/a", "p") is Verdict.DENY


class TestImagePurposeDeny:
    """BED-1 (UC-003 Workstream B image go-live lock; LA decision 2026-06-15): the
    SHARED adjudicator DENIES the image-ingest purpose until a separate image
    go-live — even when the underlying PA would ALLOW and the adjudicator is
    registered for text URL ingest.  So the image door stays welded by purpose-deny
    + images_enabled, not by the shared not-registered/empty-allowlist locks that
    text go-live releases."""

    def test_image_purpose_denied_even_when_pa_allows(self) -> None:
        called: list = []

        def _pa_allow(car):
            called.append(car)
            return AdjudicationDecision.ALLOW

        adjudicator = make_url_adjudicator(_pa_allow)
        # The image-ingest purpose is DENIED up front — the PA is never consulted.
        assert (
            adjudicator("https://cdn.example/pic.png", "uc003-image-ingest")
            is Verdict.DENY
        )
        assert called == [], "the image-ingest purpose must short-circuit before the PA"

    def test_text_purpose_unaffected_still_allows(self) -> None:
        # The text URL-ingest purpose flows through to the PA verdict unchanged.
        adjudicator = make_url_adjudicator(lambda car: AdjudicationDecision.ALLOW)
        assert (
            adjudicator("https://news.example/article", "uc003-url-ingest")
            is Verdict.ALLOW
        )

    def test_image_denied_through_real_registration_seam(self) -> None:
        # Even with the adjudicator REGISTERED on the door (text go-live posture),
        # an image-purpose fetch is denied; a text-purpose fetch is allowed.
        register_url_ingest_adjudicator(lambda car: AdjudicationDecision.ALLOW)
        door = active_url_adjudicator()
        assert door is not None
        assert door("https://news.example/article", "uc003-url-ingest") is Verdict.ALLOW
        assert door("https://cdn.example/pic.png", "uc003-image-ingest") is Verdict.DENY
        # (the autouse fixture clears the adjudicator after this test)

    def test_deny_set_tracks_the_real_image_fetch_purpose(self) -> None:
        # Coupling lock: the deny-set holds a literal copy of the image fetch
        # purpose (to avoid importing a sibling-module private at module load).
        # Bind it to the REAL constant so a future rename of _IMAGE_FETCH_PURPOSE
        # fails LOUD here instead of silently un-guarding the image door.
        from services.ui_gateway.src.ingest_coordinator import _IMAGE_FETCH_PURPOSE

        assert _IMAGE_FETCH_PURPOSE in IMAGE_INGEST_DENY_PURPOSES


class TestGoLiveRegistration:
    def test_door_is_deny_by_default_until_registered(self) -> None:
        """The autouse fixture guarantees no adjudicator — the dormant default."""
        assert active_url_adjudicator() is None

    def test_register_wires_the_door_then_teardown_clears(self) -> None:
        register_url_ingest_adjudicator(lambda car: AdjudicationDecision.ALLOW)
        adjudicator = active_url_adjudicator()
        assert adjudicator is not None
        # The registered callable maps a PA ALLOW to a door ALLOW.
        assert adjudicator("https://example.com/a", "uc003-url-ingest") is Verdict.ALLOW
        # (the autouse fixture clears it again after this test)


class TestDeterministicUrlAdjudicate:
    """The PRODUCTION adjudicate fn over the REAL DeterministicPolicyChecker.

    These drive the actual rule engine (no fake PA): they prove the door is
    welded by POLICY with the live empty egress allowlist, and that the ADR-027
    §2 carve-out auto-approves an allowlisted host.  This is the third,
    policy-level lock (on top of not-registered + guest_parser disabled).
    """

    def test_empty_allowlist_denies_every_url(self) -> None:
        """The live default (None → the checker's EMPTY class allowlist):
        RULE 3 denies every external URL — the welded air-gap, by policy."""
        adjudicate = make_deterministic_url_adjudicate()  # live default
        car = build_url_car("https://news.example.org/article", "uc003-url-ingest")
        assert adjudicate(car) is AdjudicationDecision.DENY

    def test_explicit_empty_allowlist_denies(self) -> None:
        adjudicate = make_deterministic_url_adjudicate(frozenset())
        car = build_url_car("https://news.example.org/article", "p")
        assert adjudicate(car) is AdjudicationDecision.DENY

    def test_allowlisted_host_is_allowed(self) -> None:
        """ADR-027 §2 carve-out: a URL whose host is on the allowlist
        auto-approves (the door-opening knob the LA populates at go-live)."""
        adjudicate = make_deterministic_url_adjudicate(frozenset({"news.example.org"}))
        car = build_url_car("https://news.example.org/article", "p")
        assert adjudicate(car) is AdjudicationDecision.ALLOW

    def test_off_list_host_denied_even_with_a_populated_allowlist(self) -> None:
        adjudicate = make_deterministic_url_adjudicate(frozenset({"news.example.org"}))
        car = build_url_car("https://evil.example.com/x", "p")
        assert adjudicate(car) is AdjudicationDecision.DENY

    def test_full_door_denies_url_under_live_default(self) -> None:
        """End to end through make_url_adjudicator: with the live empty
        allowlist the door's Verdict on a real URL is DENY."""
        door = make_url_adjudicator(make_deterministic_url_adjudicate())
        assert door("https://news.example.org/article", "uc003-url-ingest") is Verdict.DENY

    def test_full_door_allows_allowlisted_host(self) -> None:
        door = make_url_adjudicator(
            make_deterministic_url_adjudicate(frozenset({"news.example.org"}))
        )
        assert door("https://news.example.org/article", "p") is Verdict.ALLOW

    def test_registration_with_live_default_still_denies(self) -> None:
        """Registering the production adjudicator does NOT open the door while
        the allowlist is empty — the door denies until the allowlist is
        populated (ADR-027 Amendment 1, the LA's go-live governance act)."""
        register_url_ingest_adjudicator(make_deterministic_url_adjudicate())
        door = active_url_adjudicator()
        assert door is not None
        assert door("https://news.example.org/article", "p") is Verdict.DENY
        # (autouse fixture clears the adjudicator after this test)


class TestOperatorUrlAdjudicate:
    """The LIVE "URL = authorization" adjudicate fn (ADR-027 Amendment 1).

    Each operator-pasted URL authorizes ONLY its own host, per-CAR, by rebuilding a
    one-entry egress allowlist from the CAR's own URL (the checker's own host
    normalization).  Drives the REAL DeterministicPolicyChecker (no fake PA).
    """

    def test_public_host_url_is_allowed(self) -> None:
        """A well-formed https URL self-authorizes its own host → ALLOW."""
        adjudicate = make_operator_url_adjudicate()
        car = build_url_car("https://news.example.org/article", "uc003-url-ingest")
        assert adjudicate(car) is AdjudicationDecision.ALLOW

    def test_per_car_not_a_fixed_host(self) -> None:
        """The SAME adjudicator instance allows a DIFFERENT host's URL — the
        allowlist is rebuilt per-CAR from the CAR's own URL, not a standing host."""
        adjudicate = make_operator_url_adjudicate()
        first = build_url_car("https://news.example.org/article", "uc003-url-ingest")
        second = build_url_car("https://other.example.net/page", "uc003-url-ingest")
        assert adjudicate(first) is AdjudicationDecision.ALLOW
        assert adjudicate(second) is AdjudicationDecision.ALLOW

    def test_non_web_egress_scheme_denies(self) -> None:
        """A non-web egress scheme (ftp/ws/gopher) is NOT a fetchable web host, so
        ``_egress_host`` returns None → empty allowlist → RULE 3 (DENY_EXTERNAL_
        NETWORK) denies it (fail-closed: only http/https hosts self-authorize).

        (A bare non-URL string like "not-a-url" is not an external-network action at
        all — the deterministic checker has no egress rule for it — and never reaches
        this adjudicator in production: the door's own SSRF guard rejects a non-https
        URL with "scheme not permitted" BEFORE the PA is consulted.  So the egress
        fail-closed property that THIS function owns is the non-web *scheme* DENY.)"""
        adjudicate = make_operator_url_adjudicate()
        for resource in (
            "ftp://files.example.org/x",
            "ws://socket.example.org/x",
            "gopher://old.example.org/0/x",
        ):
            car = build_url_car(resource, "p")
            assert adjudicate(car) is AdjudicationDecision.DENY, resource

    def test_full_door_allows_pasted_url(self) -> None:
        """End to end through make_url_adjudicator: a pasted https URL maps to a
        door ALLOW (the operator's paste authorizes that one host)."""
        door = make_url_adjudicator(make_operator_url_adjudicate())
        assert door("https://news.example.org/article", "uc003-url-ingest") is Verdict.ALLOW

    def test_does_not_register_anything_at_import(self) -> None:
        """Building the adjudicate fn does NOT register it on the door — the door
        stays deny-by-default until register_url_ingest_adjudicator runs (go-live)."""
        make_operator_url_adjudicate()  # build it — must NOT touch the door registry
        assert active_url_adjudicator() is None
