"""#1584: the canary against the postures that actually occur, and the path
that actually runs in production.

Split from ``test_trust_spine_canary.py`` because these are the locks the first
version of that suite did not have, and the review that found them is worth
keeping legible: every test here corresponds to something reproduced against
the shipped code.

  * the canary fired an ERROR-level finding on every boot of a deliberately
    welded system, because the UNPROVEN branch gated on the one weld mechanism
    this codebase does not use
  * no test drove the real egress door's ALLOW direction -- the single path
    that executes in production
  * the posture-independence lock asserted a property of a string literal
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from shared.security.trust_spine_canary import (
    PROVEN,
    REFUTED,
    UNPROVEN,
    probe_dispatch_door,
    probe_egress_door,
)

_REPO = Path(__file__).resolve().parents[2]
_AO_CONFIG = _REPO / "services" / "assistant_orchestrator" / "config"


class _V:
    def __init__(self, name: str) -> None:
        self.name = name


ALLOW = _V("ALLOW")
DENY = _V("DENY")


def _outcome(report, direction: str) -> str:
    return next(p.outcome for p in report.probes if p.direction == direction)


def _detail(report, direction: str) -> str:
    return next(p.detail for p in report.probes if p.direction == direction)


# ---------------------------------------------------------------------------
# The weld postures.
# ---------------------------------------------------------------------------


def test_a_welded_door_is_UNPROVEN_not_a_finding() -> None:
    """The live weld is REGISTRATION, not an empty allowlist.

    ``_maybe_register_web_search`` returns at its first line when the capability
    flag is off, and returns False when the sealed search key is absent. Either
    way no adjudicator is registered and the door correctly denies everything --
    with the allowlist still populated, so the old empty-allowlist gate never
    fired and the canary logged a FINDING at ERROR on every boot.
    """
    report = probe_egress_door(
        lambda url, purpose: (DENY, "no adjudicator registered"),
        allowlist={"kagi.com"},
        egress_expected_live=False,
    )

    assert _outcome(report, "allow") == UNPROVEN
    assert not report.findings, (
        "a deliberately welded door is not a finding. An alarm that fires on "
        "every boot of a healthy system is an alarm nobody reads."
    )
    assert not report.alive
    assert "not enabled" in _detail(report, "allow")


def test_a_door_that_SHOULD_be_live_and_is_not_IS_a_finding() -> None:
    """The toggle: UNPROVEN must not swallow the real outage."""
    report = probe_egress_door(
        lambda url, purpose: (DENY, "no adjudicator registered"),
        allowlist={"kagi.com"},
        egress_expected_live=True,
    )

    assert _outcome(report, "allow") == REFUTED
    assert report.findings


def test_the_guest_topology_has_no_web_search_and_must_stay_quiet() -> None:
    """guest_runtime.toml has no ``[web_search]`` section at all, and this
    change adds the canary to it."""
    guest = tomllib.load((_AO_CONFIG / "guest_runtime.toml").open("rb"))
    assert "web_search" not in guest, (
        "guest_runtime.toml gained a web_search section; this test's premise "
        "no longer holds and the canary's guest behaviour needs re-checking"
    )

    report = probe_egress_door(
        lambda url, purpose: (DENY, "no adjudicator"),
        allowlist={"kagi.com"},
        egress_expected_live=False,
    )
    assert not report.findings


# ---------------------------------------------------------------------------
# The production path, which had no test at all.
# ---------------------------------------------------------------------------


def test_the_REAL_egress_door_proves_ALIVE_with_the_real_adjudicator() -> None:
    """The one path that executes in production: the real record-free door, the
    real registered adjudicator, the live allowlist.

    Every other allow-direction test uses a stub.
    """
    from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker
    from services.ui_gateway.src.url_adjudicator import (
        make_request_keyed_url_adjudicate,
        make_url_adjudicator,
    )
    from shared.security import guarded_fetch

    before = guarded_fetch._adjudicator
    try:
        guarded_fetch.register_url_adjudicator(
            make_url_adjudicator(make_request_keyed_url_adjudicate())
        )
        report = probe_egress_door(
            guarded_fetch._adjudicate_uncorded,
            allowlist=DeterministicPolicyChecker._EGRESS_ALLOWLIST,
            egress_expected_live=True,
        )
    finally:
        guarded_fetch._adjudicator = before

    assert report.alive, report.render()
    assert not report.findings, report.render()


def test_registering_the_adjudicator_left_no_residue() -> None:
    """The test above mutates process-global state. A leak would flip
    ``test_a_bare_process_cannot_prove_the_egress_door_alive`` in the sibling
    file, depending on test order."""
    from shared.security import guarded_fetch

    assert guarded_fetch._adjudicator is None


# ---------------------------------------------------------------------------
# The claims that were false, held structurally now.
# ---------------------------------------------------------------------------


def test_the_canary_uses_the_RECORD_FREE_door() -> None:
    """It must not append to the signed audit chain.

    The first version used the recording door and asserted -- in the module, the
    service, both config files and the journal -- that canary receipts were
    distinguishable by a reserved purpose. That was structurally impossible:
    ``build_receipt`` takes no purpose. Review reproduced a canary allow-receipt
    identical in every readable field to a real egress allow, so every boot
    would have appended a signed row asserting outbound access was authorised
    when nothing was fetched.
    """
    import services.assistant_orchestrator.src.entrypoint as ao

    tree = ast.parse(Path(ao.__file__).read_text(encoding="utf-8"))
    method = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_run_trust_spine_canary"
    )
    attrs = {n.attr for n in ast.walk(method) if isinstance(n, ast.Attribute)}

    assert "_adjudicate_uncorded" in attrs, (
        "the canary is not using the record-free door, so it is writing rows "
        "into the audit chain"
    )


def test_the_recording_door_still_wraps_the_record_free_one() -> None:
    """The cost of writing nothing, held rather than ignored.

    The canary does not exercise the receipt wrapper. So ``_adjudicate`` must
    still delegate to ``_adjudicate_uncorded``, or the two could diverge and the
    canary would be probing a path production does not take.
    """
    from shared.security import guarded_fetch

    tree = ast.parse(Path(guarded_fetch.__file__).read_text(encoding="utf-8"))
    wrapper = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_adjudicate"
    )
    assert any(
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Name)
        and inner.func.id == "_adjudicate_uncorded"
        for inner in ast.walk(wrapper)
    ), "_adjudicate no longer delegates to _adjudicate_uncorded"


def test_the_denied_payload_is_posture_independent_FOR_REAL(monkeypatch) -> None:
    """Drive the REAL dispatch door under three egress postures.

    The earlier lock asserted that a string constant contained ``/tmp/export/``
    and no ``http`` -- a claim about a literal, not about posture independence.
    """
    from services.assistant_orchestrator.src.entrypoint import (
        _adjudicate_tool_dispatch,
    )
    from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker

    for posture in (
        frozenset(),
        frozenset({"kagi.com"}),
        frozenset({"a.example", "b.example"}),
    ):
        monkeypatch.setattr(
            DeterministicPolicyChecker, "_EGRESS_ALLOWLIST", posture
        )
        report = probe_dispatch_door(_adjudicate_tool_dispatch)
        assert _outcome(report, "deny") == PROVEN, (
            f"the denial is posture-dependent: allowlist={sorted(posture)} gave "
            f"{_detail(report, 'deny')}"
        )
