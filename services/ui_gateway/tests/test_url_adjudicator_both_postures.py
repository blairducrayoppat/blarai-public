"""Both egress postures, through ONE adjudicator, at once (#977, #1586).

**The thing that could not be tested before this change.** `register_url_adjudicator`
fills a module-global slot, and two runtime components filled it with DIFFERENT
policies: the launcher registered "the paste IS the consent for that one URL"
(ADR-027 Amendment 1), the Assistant Orchestrator registered the standing
allowlist. Only one could occupy the slot, so one of the two policies governed
BOTH postures — and no test could assert that each behaves correctly, because the
other was not reachable in the same process.

**Not a race, which is worse.** The slot is LAST-write-wins (the register function
overwrites unconditionally); the AO guards its own call with
`active_url_adjudicator() is None` and the launcher does not. So the operator
policy won whenever the launcher ran at all, in either boot order — deterministic,
not a startup edge case. The runbook, this file and three code comments all said
"first-wins" because they inherited it from a docstring; claim-register row 2 had
recorded the truth all along (#1586 review, finding 5).

`docs/runbooks/web_search_go_live.md` recorded that as a governance question about
which adjudicator should win. It was not one. Both answers are correct for their own
request, the information needed to tell them apart is already in the CAR, and the
"conflict" was a wiring accident (#1586).

**What these assert.** One `make_request_keyed_url_adjudicate`, driven with real
CARs through the real `DeterministicPolicyChecker`:

  * an operator paste authorises its OWN host, and a second paste on a different
    host authorises ITS host and not the first one's — per adjudication, not a
    stuck allowlist;
  * a non-paste purpose adjudicates against the STANDING allowlist, so the exact
    same URL that a paste would authorise is DENIED when the purpose is anything
    else. **This is the load-bearing negative**: it is what stops paste-is-consent
    leaking to every other egress purpose;
  * an unrecognised, missing or malformed purpose falls to the standing allowlist,
    never to paste-is-consent — the deny-by-default direction;
  * the image weld still fires ahead of all of it.

The safety of the whole design rests on `purpose` being unforgeable from the model
side, which is proved separately and continuously by
`tests/security/test_purpose_unforgeable.py`.
"""

from __future__ import annotations

import pytest

from services.ui_gateway.src.url_adjudicator import (
    IMAGE_INGEST_DENY_PURPOSES,
    PASTE_IS_CONSENT_PURPOSES,
    build_url_car,
    make_request_keyed_url_adjudicate,
    make_url_adjudicator,
)
from shared.schemas.car import AdjudicationDecision
from shared.security.guarded_fetch import Verdict

_PASTE = "uc003-url-ingest"
_SEARCH = "web_search"
_STANDING = frozenset({"kagi.com"})


@pytest.fixture(autouse=True)
def _paste_purpose_is_still_the_one_named() -> None:
    """If the paste-is-consent purpose is ever renamed, these tests must not
    silently keep passing against a string nothing uses."""
    assert _PASTE in PASTE_IS_CONSENT_PURPOSES, (
        f"{_PASTE!r} is no longer a paste-is-consent purpose; this whole module "
        "is asserting against a value the code does not use"
    )


class TestOneAdjudicatorServesBothPostures:
    """The same callable, two requests, two different allowlist policies."""

    def test_an_operator_paste_authorises_ITS_OWN_host(self) -> None:
        adjudicate = make_request_keyed_url_adjudicate(egress_allowlist=_STANDING)
        car = build_url_car("https://example.org/article", _PASTE)
        assert adjudicate(car) is AdjudicationDecision.ALLOW

    def test_a_SECOND_paste_on_another_host_authorises_ITS_host_not_the_first(
        self,
    ) -> None:
        """Per adjudication, not a stuck allowlist. A cache or a carried-over
        frozenset would make the first host permanently allowed, which is the
        difference between 'the operator pasted this' and 'the operator pasted
        something once'."""
        adjudicate = make_request_keyed_url_adjudicate(egress_allowlist=_STANDING)
        first = build_url_car("https://example.org/article", _PASTE)
        second = build_url_car("https://other.example.net/page", _PASTE)

        assert adjudicate(first) is AdjudicationDecision.ALLOW
        assert adjudicate(second) is AdjudicationDecision.ALLOW

        # And the first host is not still authorised for a NON-paste purpose.
        assert (
            adjudicate(build_url_car("https://example.org/article", _SEARCH))
            is AdjudicationDecision.DENY
        )

    def test_the_standing_posture_ALLOWS_its_own_allowlisted_host(self) -> None:
        adjudicate = make_request_keyed_url_adjudicate(egress_allowlist=_STANDING)
        car = build_url_car("https://kagi.com/api/v1/search", _SEARCH)
        assert adjudicate(car) is AdjudicationDecision.ALLOW

    def test_BOTH_postures_are_correct_from_the_SAME_callable(self) -> None:
        """The whole point, in one test: one adjudicator, both policies live.

        Before #1586 this could not be written — the two policies were two
        callables competing for one module-global slot, so a process had exactly
        one of these behaviours and the other was unreachable.
        """
        adjudicate = make_request_keyed_url_adjudicate(egress_allowlist=_STANDING)

        paste_to_arbitrary = build_url_car("https://example.org/a", _PASTE)
        search_to_standing = build_url_car("https://kagi.com/api/v1/search", _SEARCH)
        search_to_arbitrary = build_url_car("https://example.org/a", _SEARCH)

        assert adjudicate(paste_to_arbitrary) is AdjudicationDecision.ALLOW
        assert adjudicate(search_to_standing) is AdjudicationDecision.ALLOW
        assert adjudicate(search_to_arbitrary) is AdjudicationDecision.DENY, (
            "a non-paste purpose reached an arbitrary host — paste-is-consent has "
            "leaked out of its purpose and now authorises any destination"
        )


class TestTheSELECTED_ALLOWLIST_IsExactlyWhatWasIntended:
    """Assert the POLICY, not only its outcome (#1586 review, finding 7).

    The review found a mutant that adds an extra host to the paste allowlist and
    survives every test — and it was right that it is *equivalent* as long as
    nothing looks at the allowlist: the set is only ever compared against the
    resource it was derived from, so "authorises exactly this host" and
    "authorises this host and anything else" produce identical verdicts.

    Which means the disposition's headline claim — that a paste authorises ITS
    host and nothing more — was unfalsifiable by construction. That is not a
    claim worth making; it is a claim worth TESTING, and the allowlist handed to
    the checker is the artifact it is about. Capturing it at that seam is the
    difference between asserting the policy and asserting a coincidence.
    """

    @staticmethod
    def _captured_allowlist(
        monkeypatch: pytest.MonkeyPatch, url: str, purpose: str, standing
    ):
        from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker

        seen: list = []
        real = DeterministicPolicyChecker.check

        def _spy(car, egress_allowlist=None):
            seen.append(egress_allowlist)
            return real(car, egress_allowlist=egress_allowlist)

        monkeypatch.setattr(DeterministicPolicyChecker, "check", staticmethod(_spy))
        make_request_keyed_url_adjudicate(egress_allowlist=standing)(
            build_url_car(url, purpose)
        )
        assert len(seen) == 1, f"the checker was called {len(seen)} times, expected 1"
        return seen[0]

    def test_a_paste_selects_EXACTLY_its_own_host_and_nothing_else(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        got = self._captured_allowlist(
            monkeypatch, "https://example.org/article", _PASTE, _STANDING
        )
        assert got == frozenset({"example.org"}), (
            f"the paste branch handed the checker {got!r}. It must be EXACTLY the "
            "one host the operator pasted — an extra entry authorises a "
            "destination nobody pasted, and no verdict-level test can see it"
        )

    def test_a_standing_purpose_selects_EXACTLY_the_standing_allowlist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        got = self._captured_allowlist(
            monkeypatch, "https://kagi.com/api/v1/search", _SEARCH, _STANDING
        )
        assert got == _STANDING, (
            f"the standing branch handed the checker {got!r}, not the standing "
            "allowlist it was given"
        )

    def test_the_paste_allowlist_does_not_CARRY_OVER_between_adjudications(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The per-adjudication property, now observable rather than inferred."""
        first = self._captured_allowlist(
            monkeypatch, "https://example.org/a", _PASTE, _STANDING
        )
        second = self._captured_allowlist(
            monkeypatch, "https://other.example.net/b", _PASTE, _STANDING
        )
        assert first == frozenset({"example.org"})
        assert second == frozenset({"other.example.net"}), (
            f"the second paste was adjudicated against {second!r} — the allowlist "
            "carried state across adjudications"
        )


class TestPasteIsConsentDoesNotLeakToOtherPurposes:
    """The negative half, which is the one that matters."""

    @pytest.mark.parametrize(
        ("label", "purpose"),
        [
            ("web_search", _SEARCH),
            ("a purpose nobody registered", "some-future-tool"),
            ("empty string", ""),
            ("a near-miss of the real one", "uc003-url-ingest "),
            ("a case variant", "UC003-URL-INGEST"),
        ],
    )
    def test_a_NON_paste_purpose_cannot_reach_an_arbitrary_host(
        self, label: str, purpose: str
    ) -> None:
        """Deny-by-default on the purpose→policy map.

        An unrecognised purpose must fall to the STANDING allowlist — the
        restrictive branch — never to paste-is-consent. Backwards, any purpose
        nobody thought about would authorise its own destination, which is the
        model claiming the operator pasted something.
        """
        adjudicate = make_request_keyed_url_adjudicate(egress_allowlist=_STANDING)
        car = build_url_car("https://attacker.example/x", purpose)
        assert adjudicate(car) is AdjudicationDecision.DENY, (
            f"{label}: purpose {purpose!r} reached an arbitrary host"
        )

    @pytest.mark.parametrize(
        ("label", "schema"),
        [
            ("no purpose key", {"method": "GET"}),
            ("purpose is None", {"purpose": None, "method": "GET"}),
            ("purpose is not a string", {"purpose": 17, "method": "GET"}),
            ("parameters_schema is empty", {}),
        ],
    )
    def test_a_MALFORMED_purpose_falls_to_the_restrictive_branch(
        self, label: str, schema: dict
    ) -> None:
        """A missing or wrong-typed purpose must not crash and must not widen.

        The failure mode of a mistake here has to be a refused fetch.
        """
        adjudicate = make_request_keyed_url_adjudicate(egress_allowlist=_STANDING)
        # The CAR is a pydantic model, not a dataclass — model_copy, not
        # dataclasses.replace (which raises TypeError and would turn every case
        # here into an ERROR that says nothing about the control).
        car = build_url_car("https://attacker.example/x", _PASTE).model_copy(
            update={"parameters_schema": schema}
        )
        assert adjudicate(car) is AdjudicationDecision.DENY, (
            f"{label}: a malformed purpose reached an arbitrary host"
        )

    def test_an_UNHASHABLE_purpose_RETURNS_deny_rather_than_raising(self) -> None:
        """The adjudicate fn's contract is TOTAL: it returns a decision.

        A mutation run found the `isinstance(purpose, str)` guard survivable —
        both with and without it the DOOR ends at DENY, so no door-level test
        could tell the difference. They differ in HOW: without the guard, an
        unhashable purpose (a list, a dict) makes `purpose in frozenset` raise
        `TypeError: unhashable type`, which escapes `_adjudicate` and is caught
        by `make_url_adjudicator`'s blanket except.

        Relying on the caller's except is fail-closed by accident rather than by
        design, and it is one refactor away from not being true — `_adjudicate`
        is called directly by the smoke script and by these tests. So the
        contract is asserted HERE, at the fn, not at the door.
        """
        adjudicate = make_request_keyed_url_adjudicate(egress_allowlist=_STANDING)
        car = build_url_car("https://attacker.example/x", _PASTE).model_copy(
            update={"parameters_schema": {"purpose": [_PASTE], "method": "GET"}}
        )
        assert adjudicate(car) is AdjudicationDecision.DENY, (
            "an unhashable purpose did not return DENY — if it raised, the "
            "adjudicate fn is no longer total and only the door's blanket except "
            "is keeping this fail-closed"
        )

    def test_an_unparseable_paste_is_REFUSED_not_silently_allowed(self) -> None:
        """A paste with no extractable host is refused BY THIS LAYER.

        `make_operator_url_adjudicate`'s docstring claimed an empty allowlist
        would make RULE 3 deny it — "refused, never silently allowed". That is
        false and this test is how it was found (#1586): RULE 3 only fires on a
        resource that STARTS WITH an external-network scheme, so a resource with
        no scheme skips it and falls through to ALLOW. Measured: the old
        adjudicator returns ALLOW here.

        Nothing was exploitable — the door's https-only validation refuses such a
        resource independently — but a fail-closed claim resting entirely on the
        next layer is how a layer gets deleted later. The refusal is explicit now.
        """
        adjudicate = make_request_keyed_url_adjudicate(egress_allowlist=_STANDING)
        car = build_url_car("not-a-url-at-all", _PASTE)
        assert adjudicate(car) is AdjudicationDecision.DENY


    @pytest.mark.parametrize(
        ("label", "purpose"),
        [
            ("paste branch", _PASTE),
            ("standing branch", _SEARCH),
            ("unrecognised purpose", "some-future-tool"),
        ],
    )
    def test_a_HOSTLESS_resource_is_refused_on_EVERY_branch(
        self, label: str, purpose: str
    ) -> None:
        """#1586 review finding 2: the refusal shipped on ONE branch.

        The first version of this change refused a hostless resource on the paste
        branch, with a comment explaining at length why leaning on RULE 3 to
        catch it was wrong — and left the else branch doing exactly that.
        Measured: `web_search` + `"not-a-url-at-all"` returned ALLOW.

        RULE 3 only fires on a resource that STARTS WITH an external-network
        scheme, so one with no scheme falls through to ALLOW. Parametrized over
        both branches and an unrecognised purpose, because the defect was that a
        single-branch test could not see the other one.
        """
        adjudicate = make_request_keyed_url_adjudicate(egress_allowlist=_STANDING)
        car = build_url_car("not-a-url-at-all", purpose)
        assert adjudicate(car) is AdjudicationDecision.DENY, (
            f"{label}: a resource with no extractable host was ALLOWED"
        )

    def test_the_checker_is_STILL_consulted_on_the_paste_branch(self) -> None:
        """#1586 review finding 7: the `check` call in the paste branch was
        uncovered, and could be deleted wholesale with the suite green.

        Paste-is-consent authorises a HOST. It does not authorise everything
        about the request — the checker's non-egress rules still fire, and this
        is the one resource shape the reviewer found where they do. Without this,
        the paste branch reads as a tautology: build an allowlist from the URL,
        then check the URL against it.
        """
        adjudicate = make_request_keyed_url_adjudicate(egress_allowlist=_STANDING)
        car = build_url_car("https://a.example.com/../../../certs/renew/x", _PASTE)
        assert adjudicate(car) is AdjudicationDecision.DENY, (
            "the restricted-path rule did not fire on the paste branch — "
            "paste-is-consent is authorising more than the host"
        )


class TestTheImageWeldStillFiresFirst:
    """BED-1 survives the unification: the image purpose is denied at the door
    wrapper, before any allowlist policy is selected at all."""

    def test_the_image_purpose_is_denied_even_on_its_own_host(self) -> None:
        assert "uc003-image-ingest" in IMAGE_INGEST_DENY_PURPOSES
        adjudicator = make_url_adjudicator(
            make_request_keyed_url_adjudicate(egress_allowlist=_STANDING)
        )
        assert (
            adjudicator("https://example.org/pic.png", "uc003-image-ingest")
            is Verdict.DENY
        )

    def test_the_image_purpose_is_denied_even_if_it_were_a_paste_purpose(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Order of operations, asserted rather than assumed: the weld is ahead
        of the policy selection, so it does not depend on the image purpose being
        absent from the paste set."""
        import services.ui_gateway.src.url_adjudicator as mod

        monkeypatch.setattr(
            mod,
            "PASTE_IS_CONSENT_PURPOSES",
            frozenset({"uc003-url-ingest", "uc003-image-ingest"}),
        )
        adjudicator = make_url_adjudicator(
            make_request_keyed_url_adjudicate(egress_allowlist=_STANDING)
        )
        assert (
            adjudicator("https://example.org/pic.png", "uc003-image-ingest")
            is Verdict.DENY
        )


class TestTheDoorWrapperStillFailsClosed:
    """The unification must not have loosened the wrapper's error handling."""

    def test_a_raising_adjudicate_is_DENY(self) -> None:
        def _boom(_car: object) -> AdjudicationDecision:
            raise RuntimeError("policy agent unavailable")

        assert make_url_adjudicator(_boom)("https://kagi.com/x", _SEARCH) is (
            Verdict.DENY
        )

    def test_a_non_decision_return_is_DENY(self) -> None:
        assert make_url_adjudicator(lambda _car: "ALLOW")(  # type: ignore[arg-type,return-value]
            "https://kagi.com/x", _SEARCH
        ) is Verdict.DENY
