"""#1584: the trust-spine canary must catch a door that is not there.

A fail-closed door that never loaded looks exactly like a door that loaded and
has had nothing to deny. The canary exists to tell those apart, so the tests
that matter are the ones where the door is BROKEN in each of the two ways a
door can be broken:

  * it allows what it must refuse  -- the obvious outage
  * it refuses everything          -- the outage a deny-only canary calls health

Both are driven here against doors that behave that way, because a canary that
has only ever seen a working door has not been shown to detect anything.

THE REAL DOORS ARE DRIVEN TOO, at the bottom. Those are the reachability tests:
a canary that proves a stub behaves would be the same defect it exists to find.
"""

from __future__ import annotations

import pytest

from shared.security.trust_spine_canary import (
    CANARY_DENIED_HOST,
    CANARY_EXFIL_ARGS,
    CANARY_PURPOSE,
    PROVEN,
    REFUTED,
    UNPROVEN,
    probe_dispatch_door,
    probe_egress_door,
)


class _Verdict:
    """Minimal stand-in for the egress Verdict enum's shape."""

    def __init__(self, name: str) -> None:
        self.name = name


ALLOW = _Verdict("ALLOW")
DENY = _Verdict("DENY")


def _outcome(report, direction: str) -> str:
    return next(p.outcome for p in report.probes if p.direction == direction)


# ---------------------------------------------------------------------------
# A working door. Everything below is meaningless if this does not pass.
# ---------------------------------------------------------------------------


def test_a_working_dispatch_door_is_proven_alive() -> None:
    def door(tool_name: str, tool_args: str, session_id: str):
        return ("DENY", "DENY_EXFILTRATION") if "/tmp/export/" in tool_args else None

    report = probe_dispatch_door(door)

    assert report.alive
    assert not report.findings
    assert _outcome(report, "deny") == PROVEN
    assert _outcome(report, "allow") == PROVEN


def test_a_working_egress_door_is_proven_alive() -> None:
    def adjudicate(url: str, purpose: str):
        return (ALLOW, None) if "kagi.com" in url else (DENY, "not allowlisted")

    report = probe_egress_door(adjudicate, allowlist={"kagi.com"}, egress_expected_live=True)

    assert report.alive
    assert not report.findings


# ---------------------------------------------------------------------------
# The two ways a door breaks. These are the tests the canary exists for.
# ---------------------------------------------------------------------------


def test_a_dispatch_door_that_allows_everything_is_REFUTED() -> None:
    """The obvious outage: the door is reachable and refuses nothing."""
    report = probe_dispatch_door(lambda *_a, **_k: None)

    assert not report.alive
    assert _outcome(report, "deny") == REFUTED
    assert "ALLOWED" in report.findings[0].detail


def test_a_dispatch_door_that_DENIES_EVERYTHING_is_REFUTED() -> None:
    """The outage a deny-only canary calls health.

    A door that refuses every action passes any check that only asserts "the
    bad thing was refused". It is broken, and the paired allow probe is the
    only thing that says so.
    """
    report = probe_dispatch_door(lambda *_a, **_k: ("DENY", "EVERYTHING"))

    assert not report.alive
    assert _outcome(report, "allow") == REFUTED, (
        "a door refusing a benign action is the outage a deny-only canary calls "
        "health, and only the paired probe can say so"
    )
    assert any("denying everything" in f.detail for f in report.findings)
    # The deny probe ALSO refutes now: the refusal came from the wrong rule, so
    # this probe is no longer testing what it was built to test.
    assert _outcome(report, "deny") == REFUTED
    assert any("not 'DENY_EXFILTRATION'" in f.detail for f in report.findings)


def test_a_dispatch_door_that_CANNOT_ADJUDICATE_is_REFUTED() -> None:
    """The worst case, and the one the first version certified as healthy.

    ``_adjudicate_tool_dispatch`` catches every exception and returns
    ``("DENY", "ADJUDICATION_ERROR")`` -- the door reporting that it could not
    adjudicate at all. Scoring any non-None value as a refusal read that as
    proof of health, so a crashed rule engine logged "dispatch: ALIVE".
    """
    report = probe_dispatch_door(
        lambda tool, args, sid: ("DENY", "ADJUDICATION_ERROR") if args else None
    )

    assert not report.alive
    assert _outcome(report, "deny") == REFUTED
    assert "could NOT ADJUDICATE" in report.findings[0].detail


def test_a_dispatch_door_that_ALLOWS_the_exfil_payload_is_REFUTED() -> None:
    """Reproduced by review against the first version: a door returning
    ``("ALLOW", rule)`` for the exfiltration payload was reported ALIVE."""
    report = probe_dispatch_door(
        lambda tool, args, sid: ("ALLOW", "ok") if args else None
    )

    assert not report.alive
    assert _outcome(report, "deny") == REFUTED
    assert "Only DENY is a refusal" in report.findings[0].detail


def test_an_ESCALATE_is_not_a_refusal() -> None:
    """ESCALATE routes to operator consent and can be approved, so it is not a
    denial and must not be scored as one."""
    report = probe_dispatch_door(
        lambda tool, args, sid: ("ESCALATE", "ESCALATE_CERT_RENEWAL") if args else None
    )

    assert _outcome(report, "deny") == REFUTED


@pytest.mark.parametrize("junk", ["DENIED", True, ("DENY",), ("DENY", "X", "Y"), 0])
def test_an_unreadable_dispatch_verdict_is_REFUTED(junk) -> None:
    """A verdict the probe cannot read is not a refusal. Deny-by-default in the
    scorer itself."""
    report = probe_dispatch_door(lambda tool, args, sid: junk if args else None)

    assert _outcome(report, "deny") == REFUTED
    assert not report.alive


@pytest.mark.parametrize("junk", [None, "DENY", (None, "x"), ("DENY",), 0])
def test_an_unreadable_egress_verdict_is_REFUTED(junk) -> None:
    """Review reproduced ``(None, "x")`` being scored as a proven refusal."""
    report = probe_egress_door(
        lambda url, purpose: junk if "invalid" in url else (ALLOW, None),
        allowlist={"kagi.com"},
        egress_expected_live=True,
    )

    assert _outcome(report, "deny") == REFUTED
    assert not report.alive


def test_a_verdict_spelled_DISALLOW_is_not_read_as_an_allow() -> None:
    """The old predicate was ``name.endswith("ALLOW")``, so DISALLOW counted as
    an allow and a door denying everything was reported as ALLOWING the canary
    host -- a false alarm in the alarming direction."""
    report = probe_egress_door(
        lambda url, purpose: (_Verdict("DISALLOW"), "refused"),
        allowlist={"kagi.com"},
        egress_expected_live=True,
    )

    assert _outcome(report, "deny") == REFUTED, "DISALLOW is not DENY either"
    assert "not DENY" in report.findings[0].detail


def test_an_egress_door_that_DENIES_EVERYTHING_is_REFUTED() -> None:
    """The same trap at the other door, and this is not hypothetical.

    MEASURED 2026-09-20: in a bare Python process ``guarded_fetch._adjudicate``
    refuses a kagi.com URL, because no adjudicator is registered -- the door's
    fail-closed default. From the deny side that is indistinguishable from
    health.
    """
    report = probe_egress_door(
        lambda url, purpose: (DENY, "no adjudicator registered"),
        allowlist={"kagi.com"},
        egress_expected_live=True,
    )

    assert not report.alive
    assert _outcome(report, "deny") == PROVEN
    assert _outcome(report, "allow") == REFUTED
    assert "no adjudicator" in report.findings[0].detail.lower()


def test_an_egress_door_that_allows_the_denied_host_is_REFUTED() -> None:
    report = probe_egress_door(
        lambda url, purpose: (ALLOW, None),
        allowlist={"kagi.com"},
        egress_expected_live=True,
    )

    assert not report.alive
    assert _outcome(report, "deny") == REFUTED
    assert CANARY_DENIED_HOST in report.findings[0].detail or (
        "not DENY" in report.findings[0].detail
    )


def test_a_door_that_RAISES_is_a_finding_not_a_skip() -> None:
    """Fail-loud. An exception in a liveness check must not read as 'unknown'."""

    def exploding(*_args, **_kwargs):
        raise RuntimeError("adjudicator exploded")

    dispatch = probe_dispatch_door(exploding)
    assert not dispatch.alive
    assert all(p.outcome == REFUTED for p in dispatch.probes)
    assert "RuntimeError" in dispatch.probes[0].detail

    egress = probe_egress_door(exploding, allowlist={"kagi.com"}, egress_expected_live=True)
    assert not egress.alive
    assert all(p.outcome == REFUTED for p in egress.probes)


# ---------------------------------------------------------------------------
# UNPROVEN is not a pass, and not a finding.
# ---------------------------------------------------------------------------


def test_an_empty_allowlist_makes_the_allow_probe_UNPROVEN() -> None:
    """A deliberately welded door must not raise a false alarm -- and must not
    be reported as alive either."""
    report = probe_egress_door(
        lambda url, purpose: (DENY, "allowlist empty"), allowlist=frozenset(), egress_expected_live=True
    )

    assert _outcome(report, "deny") == PROVEN
    assert _outcome(report, "allow") == UNPROVEN
    assert not report.findings, "a welded door is not a finding"
    assert not report.alive, (
        "a door with one proven direction and one unproven has NOT been shown "
        "alive -- only shown not to be obviously broken"
    )
    assert "cannot distinguish" in _detail(report, "allow")


def _detail(report, direction: str) -> str:
    return next(p.detail for p in report.probes if p.direction == direction)


def test_alive_requires_BOTH_directions_proven() -> None:
    """The property the whole module turns on, asserted directly."""
    both = probe_egress_door(
        lambda url, purpose: (ALLOW, None) if "kagi" in url else (DENY, "no"),
        allowlist={"kagi.com"},
        egress_expected_live=True,
    )
    assert both.alive

    one = probe_egress_door(
        lambda url, purpose: (DENY, "everything"), allowlist=frozenset(), egress_expected_live=True
    )
    assert not one.alive


# ---------------------------------------------------------------------------
# Not an adjudicator, and it cannot become one.
# ---------------------------------------------------------------------------


def test_the_canary_purpose_is_reserved() -> None:
    """It must never be a purpose that grants anything.

    In particular not ``PASTE_IS_CONSENT_PURPOSES`` (#1586), where a purpose
    allowlists its OWN host -- a canary carrying it could allowlist
    canary.invalid and its deny probe would start passing for the worst
    possible reason.
    """
    from services.ui_gateway.src.url_adjudicator import PASTE_IS_CONSENT_PURPOSES

    assert CANARY_PURPOSE not in PASTE_IS_CONSENT_PURPOSES
    assert CANARY_PURPOSE.startswith("canary/")
    # NOT "so a receipt reader can filter it" -- the earlier rationale, which
    # was false: build_receipt takes no purpose, so no reader ever sees it. The
    # canary writes no receipt at all now; this asserts only that the purpose
    # cannot become one that GRANTS something.


def test_the_canary_renders_no_verdict_of_its_own() -> None:
    """Principle 5: one adjudication door. By syntax tree, so a future edit that
    starts deciding fails here rather than at review."""
    import ast
    from pathlib import Path

    import shared.security.trust_spine_canary as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute)
        else node.func.id if isinstance(node.func, ast.Name) else ""
        for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    forbidden = {"check", "adjudicate_car", "register_url_adjudicator",
                 "clear_url_adjudicator", "fetch_external", "execute"}
    assert not (called & forbidden), (
        f"the canary calls {sorted(called & forbidden)}. It drives ONE door and "
        "compares the answer; it never decides and never registers a decider."
    )


def test_the_denied_host_can_never_resolve() -> None:
    """RFC 2606 reserves .invalid. The denied probe must not be able to become a
    real request even if every layer above it failed at once."""
    assert CANARY_DENIED_HOST.endswith(".invalid")


def test_the_denied_payload_is_posture_independent() -> None:
    """The negative probe must not depend on whether a ceremony has run.

    An external-URL payload would be allowed or denied depending on the egress
    allowlist, so a canary built on it would report an outage every time the
    door was working exactly as configured. This trips RULE 2 on the CAR's own
    parameters instead.
    """
    assert "/tmp/export/" in CANARY_EXFIL_ARGS
    assert "http" not in CANARY_EXFIL_ARGS


# ---------------------------------------------------------------------------
# The real doors. Reachability, not behaviour-of-a-stub.
# ---------------------------------------------------------------------------


def test_the_REAL_dispatch_door_is_proven_alive() -> None:
    """Drives ``_adjudicate_tool_dispatch`` itself.

    Not the checker beneath it: calling the checker would prove the checker's
    logic and say nothing about whether anything calls it, which is the whole
    subject.
    """
    from services.assistant_orchestrator.src.entrypoint import (
        _adjudicate_tool_dispatch,
    )

    report = probe_dispatch_door(_adjudicate_tool_dispatch)

    assert report.alive, report.render()
    assert not report.findings, report.render()


def test_the_REAL_dispatch_doors_denial_is_the_rule_we_expect() -> None:
    """Pin WHICH rule fires, so a future rule change that silently moves the
    denial elsewhere is visible."""
    from services.assistant_orchestrator.src.entrypoint import (
        _adjudicate_tool_dispatch,
    )

    report = probe_dispatch_door(_adjudicate_tool_dispatch)
    assert "DENY_EXFILTRATION" in _detail(report, "deny")


def test_the_REAL_egress_door_refuses_the_canary_host() -> None:
    """The deny half against the real door.

    The allow half is NOT asserted here, and that is the finding this module
    was built around: in a bare process no adjudicator is registered, so the
    real door refuses everything. Proving the egress door ALIVE requires
    running inside the service that registered its adjudicator -- which is why
    the canary is per-door and in-process.
    """
    from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker
    from shared.security import guarded_fetch

    report = probe_egress_door(
        guarded_fetch._adjudicate_uncorded,
        allowlist=DeterministicPolicyChecker._EGRESS_ALLOWLIST,
        egress_expected_live=True,
    )

    assert _outcome(report, "deny") == PROVEN, report.render()


def test_a_bare_process_cannot_prove_the_egress_door_alive() -> None:
    """The measurement that answered the ticket's open question.

    Recorded as a test because it is the reason the canary is per-door and
    in-process, and because if this ever STOPS being true -- if a bare import
    starts registering an adjudicator -- that is a governance change nobody
    asked for.
    """
    from shared.security import guarded_fetch

    assert guarded_fetch._adjudicator is None, (
        "an adjudicator is registered by bare import. The egress door's "
        "registration is supposed to happen in the live service, and a canary "
        "running anywhere else is supposed to be unable to prove it alive."
    )


# ---------------------------------------------------------------------------
# Reachability. On THIS ticket above all: a canary nothing calls is the defect
# the canary exists to detect, wearing the canary's name.
# ---------------------------------------------------------------------------


def _ao_source() -> str:
    from pathlib import Path

    import services.assistant_orchestrator.src.entrypoint as module

    return Path(module.__file__).read_text(encoding="utf-8")


def test_the_boot_path_actually_calls_the_canary() -> None:
    """By syntax tree, and from the boot method specifically -- not merely
    'the name appears in the file'."""
    import ast

    tree = ast.parse(_ao_source())
    callers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and inner.func.attr == "_run_trust_spine_canary"
            for inner in ast.walk(node)
        )
    }
    assert callers, (
        "nothing calls _run_trust_spine_canary. A liveness canary that never "
        "runs is exactly the silence it was built to break."
    )


def test_the_canary_runs_AFTER_the_egress_adjudicator_is_registered() -> None:
    """Ordering is the whole design.

    Run before registration, the egress door has no adjudicator and fails closed
    to DENY -- so the deny probe passes, the allow probe fails, and the canary
    reports a false finding at every boot. Measured 2026-09-20: that is exactly
    what a bare process sees.
    """
    source = _ao_source()
    register = source.index("self._maybe_register_web_search(resolved)")
    canary = source.index("self._run_trust_spine_canary(resolved,")
    assert register < canary, (
        "the canary runs before the egress adjudicator is registered, so it "
        "would report a finding on every boot of a healthy system"
    )


def test_the_flag_resolves_from_the_config_file() -> None:
    """The flag must be readable, or the canary can never be turned on and the
    whole thing is dormant by accident rather than by decision."""
    import tomllib
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    for name in ("default.toml", "guest_runtime.toml"):
        config = tomllib.load(
            (repo / "services" / "assistant_orchestrator" / "config" / name).open("rb")
        )
        assert "trust_spine_canary" in config, f"{name} has no canary section"
        assert config["trust_spine_canary"]["enabled"] is True, (
            f"{name} ships the canary OFF. It writes nothing to the audit chain "
            "and opens no door, and a canary that does not run is exactly the "
            "silence it exists to break."
        )

    source = _ao_source()
    assert 'config_data.get("trust_spine_canary", {})' in source
    assert "trust_spine_canary_enabled=bool(" in source


def test_the_canary_is_silent_when_the_flag_is_off(monkeypatch) -> None:
    """The toggle. Off must mean NO PROBES AT ALL -- not probes whose results
    are discarded, which would still write verdict receipts.

    An earlier version of this test asserted an empty list that nothing ever
    appended to, which passes whatever the code does. It is observed here by
    replacing both probes and checking neither was reached.
    """
    import shared.security.trust_spine_canary as canary_module

    called: list[str] = []
    monkeypatch.setattr(
        canary_module, "probe_dispatch_door",
        lambda *_a, **_k: called.append("dispatch"),
    )
    monkeypatch.setattr(
        canary_module, "probe_egress_door",
        lambda *_a, **_k: called.append("egress"),
    )

    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )

    service = AssistantOrchestratorService.__new__(AssistantOrchestratorService)

    class _Off:
        trust_spine_canary_enabled = False

    service._run_trust_spine_canary(_Off(), egress_live=True)
    assert called == [], f"the canary probed with the flag OFF: {called}"

    # The other half: with the flag ON it must actually probe, or "off means
    # silent" would be satisfied by a canary that never runs at all.
    class _On:
        trust_spine_canary_enabled = True

    service._run_trust_spine_canary(_On(), egress_live=True)
    assert called == ["dispatch", "egress"], (
        f"with the flag ON the canary probed {called} -- it must drive BOTH doors"
    )


def test_a_canary_failure_never_stops_the_service(monkeypatch) -> None:
    """A liveness check that can stop the service becomes an outage."""

    class _Resolved:
        trust_spine_canary_enabled = True

    import shared.security.trust_spine_canary as canary_module

    monkeypatch.setattr(
        canary_module, "probe_dispatch_door",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("canary exploded")),
    )

    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )

    service = AssistantOrchestratorService.__new__(AssistantOrchestratorService)
    service._run_trust_spine_canary(_Resolved(), egress_live=True)  # must not raise
