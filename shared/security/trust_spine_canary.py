"""Prove an adjudication door is ALIVE, not merely not-yet-denying (#1584).

A fail-closed door that never loaded looks exactly like a door that loaded and
has had nothing to deny. Both produce silence, so "no denials" is not evidence
that anything is running.

WHAT A PROBE ESTABLISHES
------------------------
PROVEN    the door was driven and gave the verdict it had to give.
REFUTED   the door was driven and gave the WRONG verdict. A finding.
UNPROVEN  the probe could not establish anything, and says why.

UNPROVEN is first-class. Folding "I could not tell" into "fine" reproduces the
silence this module exists to break; folding it into "finding" cries outage at
a door that is shut on purpose.

BOTH DIRECTIONS, ALWAYS
-----------------------
A canary asserting only "this was denied" passes just as cleanly when the door
denies EVERYTHING -- which is its own outage, and is the shipped behaviour of
any process where no adjudicator was registered, since the egress door fails
closed. So every door gets a paired probe that must be ALLOWED, and a door is
ALIVE only when both directions are PROVEN.

WHAT COUNTS AS A DENIAL
-----------------------
Only the refusal that was asked for. A door reporting that it could not
adjudicate, a verdict of an unreadable shape, an ESCALATE that routes to
operator consent, or a refusal by some other rule are each REFUTED -- the
scorer is deny-by-default about what it will accept as proof (principle 2).
Scoring "something came back" as a refusal is how a canary certifies a door
whose rule engine has crashed.

WHERE IT RUNS
-------------
ONE CANARY PER DOOR, IN THE PROCESS THAT OWNS THAT DOOR, AFTER WIRING. The
doors resolve their adjudicators from process-local state, so a probe run
anywhere else measures an empty process rather than the running system.

WHAT THIS IS NOT
----------------
Not an adjudicator (principle 5). It renders no verdict and opens no door; it
calls the one door and compares what came back against what had to. It writes
nothing -- see :data:`WHY_NO_RECEIPTS`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

__all__ = [
    "CANARY_DENIED_HOST",
    "CANARY_EXFIL_ARGS",
    "CANARY_PURPOSE",
    "EXPECTED_DISPATCH_RULE",
    "PROVEN",
    "REFUTED",
    "UNPROVEN",
    "WHY_NO_RECEIPTS",
    "CanaryReport",
    "ProbeResult",
    "probe_dispatch_door",
    "probe_egress_door",
]

PROVEN = "PROVEN"
REFUTED = "REFUTED"
UNPROVEN = "UNPROVEN"

#: The purpose every canary adjudication carries, so its verdict receipt is
#: distinguishable from a record of something the operator did (#1542).
#:
#: RESERVED. It must never appear in a real purpose set -- in particular not in
#: ``PASTE_IS_CONSENT_PURPOSES``, where it would let a canary host allowlist
#: itself. A gate test holds that.
CANARY_PURPOSE: str = "canary/trust-spine-liveness"

#: The host the egress canary asks for and must be refused. ``.invalid`` is
#: reserved by RFC 2606 and resolves nowhere, so this probe cannot become a
#: request even if every layer above it failed at once.
CANARY_DENIED_HOST: str = "canary.invalid"

#: The tool-argument payload the dispatch canary sends to be denied.
#:
#: Trips RULE 2 (DENY_EXFILTRATION) on the CAR's own parameters, which is the
#: point: it is INDEPENDENT OF EGRESS POSTURE. The obvious choice -- an
#: external URL -- is not, because the same dispatch is allowed or denied
#: depending on whether a ceremony has populated the egress allowlist, so a
#: canary built on it would report an outage every time the door was working
#: exactly as configured.
CANARY_EXFIL_ARGS: str = '{"path": "/tmp/export/trust-spine-canary"}'


@dataclass(frozen=True)
class ProbeResult:
    """What one probe established, and what it could not."""

    door: str
    direction: str
    """``deny`` or ``allow`` -- what the door HAD to say."""

    outcome: str
    detail: str

    @property
    def is_finding(self) -> bool:
        """True only for REFUTED. UNPROVEN is a gap, not a finding."""
        return self.outcome == REFUTED


@dataclass(frozen=True)
class CanaryReport:
    """Every probe for one door, and the one-line verdict over them."""

    door: str
    probes: tuple[ProbeResult, ...] = field(default_factory=tuple)

    @property
    def alive(self) -> bool:
        """True only when BOTH directions were PROVEN.

        Not "no findings". A door with one PROVEN probe and one UNPROVEN has not
        been shown to be alive -- it has been shown not to be obviously broken,
        which is the distinction this whole module exists to hold.
        """
        directions = {p.direction for p in self.probes if p.outcome == PROVEN}
        return directions >= {"deny", "allow"}

    @property
    def findings(self) -> tuple[ProbeResult, ...]:
        return tuple(p for p in self.probes if p.is_finding)

    def render(self) -> str:
        head = (
            f"{self.door}: ALIVE" if self.alive
            else f"{self.door}: NOT PROVEN ALIVE"
        )
        lines = [head]
        for probe in self.probes:
            lines.append(f"  [{probe.outcome}] must {probe.direction}: {probe.detail}")
        return "\n".join(lines)


#: The rule the dispatch deny-probe must be refused BY. Checking only that
#: "something came back" is how the first version of this canary certified a
#: door whose rule engine had crashed: ``_adjudicate_tool_dispatch`` catches
#: every exception and returns ``("DENY", "ADJUDICATION_ERROR")``, which is the
#: door saying it COULD NOT ADJUDICATE, and the probe read it as proof of
#: health. It also scored ``("ALLOW", rule)`` as a refusal -- so a door that
#: ALLOWED the exfiltration payload was reported ALIVE.
EXPECTED_DISPATCH_RULE: str = "DENY_EXFILTRATION"

#: The verdict a door returns when it could not adjudicate at all. Never a
#: proof of anything: it is the door reporting its own failure.
DISPATCH_ERROR_RULE: str = "ADJUDICATION_ERROR"


def _score_dispatch_denial(verdict: object) -> ProbeResult:
    """Score the dispatch deny probe. DENY, by the expected rule, or nothing.

    Deny-by-default in the scorer itself (principle 2): every shape that is not
    positively recognised as the refusal we asked for is REFUTED, never
    charitably read as one.
    """
    def _refuted(detail: str) -> ProbeResult:
        return ProbeResult("dispatch", "deny", REFUTED, detail)

    if verdict is None:
        return _refuted(
            "an exfiltration payload was ALLOWED. The door is reachable and is "
            "not refusing what it must refuse."
        )
    if not (isinstance(verdict, tuple) and len(verdict) == 2):
        return _refuted(
            f"the door returned {verdict!r}, which is not a (decision, rule) "
            "pair. A verdict this probe cannot read is not a refusal."
        )
    decision, rule = verdict
    if str(rule) == DISPATCH_ERROR_RULE:
        return _refuted(
            f"the door returned {verdict!r} -- it could NOT ADJUDICATE. That is "
            "the door reporting its own failure, and reading it as a refusal is "
            "how a canary certifies a broken rule engine."
        )
    if str(decision).upper() != "DENY":
        return _refuted(
            f"the door returned {verdict!r}. Only DENY is a refusal; ESCALATE "
            "routes to operator consent and can be approved."
        )
    if str(rule) != EXPECTED_DISPATCH_RULE:
        return _refuted(
            f"the exfiltration payload was denied by {rule!r}, not "
            f"{EXPECTED_DISPATCH_RULE!r}. The denial moved, so this probe is no "
            "longer testing the rule it was built to test."
        )
    return ProbeResult(
        "dispatch", "deny", PROVEN,
        f"an exfiltration payload was refused by {EXPECTED_DISPATCH_RULE}",
    )


#: WHY THIS CANARY WRITES NO VERDICT RECEIPT.
#:
#: It adjudicates through ``_adjudicate_uncorded`` rather than ``_adjudicate``,
#: so nothing is appended to the signed audit chain.
#:
#: The first version used the recording door and claimed -- in this module, in
#: the service, in both config files and in the journal -- that canary receipts
#: were distinguishable by a reserved purpose. That was structurally
#: impossible: ``build_receipt`` takes no purpose, and ``_record_verdict``
#: passes the purpose only into an opaque identity hash. Review reproduced a
#: canary allow-receipt and a real web_search allow-receipt with every readable
#: field identical. So every boot would have appended a signed, durable row
#: asserting EGRESS TO KAGI.COM WAS AUTHORISED when no fetch happened, and an
#: auditor counting how often BlarAI was permitted to reach the internet would
#: have been counting boots.
#:
#: Not writing the row is the fix, not marking it: structural absence over
#: configuration (principle 4). The cost is that the recording WRAPPER is not
#: exercised here, which is stated rather than papered over --
#: ``test_the_recording_door_still_wraps_the_adjudication`` holds the two in
#: step instead.
WHY_NO_RECEIPTS: str = (
    "the canary adjudicates without recording, so it cannot forge a row in the "
    "record it exists to protect"
)


def _score_egress(result: object, direction: str, host: str) -> ProbeResult:
    """Score one egress probe. Deny-by-default about what it will call a denial.

    An earlier version asked only "is this an ALLOW?" and scored everything else
    as a proven refusal -- so a malformed verdict, or ``None``, counted as the
    door working. Only a recognised DENY is a denial here.
    """
    def _named(verdict: object) -> str:
        return str(getattr(verdict, "name", verdict)).upper()

    if not (isinstance(result, tuple) and len(result) == 2):
        return ProbeResult(
            "egress", direction, REFUTED,
            f"the door returned {result!r}, which is not a (verdict, reason) "
            "pair. A verdict this probe cannot read is not a verdict.",
        )
    verdict, reason = result
    name = _named(verdict)

    if direction == "deny":
        if name == "DENY":
            return ProbeResult("egress", "deny", PROVEN, f"{host} was refused")
        return ProbeResult(
            "egress", "deny", REFUTED,
            f"{host} returned {name!r}, not DENY. Only an explicit DENY is a "
            "refusal -- ESCALATE routes to consent and can be approved.",
        )

    if name == "ALLOW":
        return ProbeResult("egress", "allow", PROVEN, f"{host} was allowed")
    return ProbeResult(
        "egress", "allow", REFUTED,
        f"{host} is on the live egress allowlist and outbound search is enabled, "
        f"and the door returned {name!r} ({reason}). Either no adjudicator is "
        "registered in this process -- the fail-closed default, which looks "
        "identical to health from the deny side -- or the door and the allowlist "
        "disagree.",
    )


class _DispatchDoor(Protocol):
    def __call__(self, tool_name: str, tool_args: str, session_id: str) -> object: ...


def probe_dispatch_door(
    door: _DispatchDoor,
    *,
    allowed_tool: str = "get_current_time",
    session_id: str = "trust-spine-canary",
) -> CanaryReport:
    """Drive the REAL tool-dispatch door in both directions.

    ``door`` is the door function itself -- ``_adjudicate_tool_dispatch`` --
    never the checker beneath it. Calling the checker would prove the checker's
    logic and say nothing about whether anything calls it, and that distinction
    is the entire subject here.

    The door's contract: ``None`` allows; a ``(decision, rule)`` tuple refuses.
    """
    probes: list[ProbeResult] = []

    # -- must DENY: an exfiltration payload, independent of egress posture ----
    try:
        verdict = door(allowed_tool, CANARY_EXFIL_ARGS, session_id)
    except Exception as exc:  # noqa: BLE001 - a door that raises is a finding
        probes.append(ProbeResult(
            "dispatch", "deny", REFUTED,
            f"the door raised {type(exc).__name__}: {exc}",
        ))
    else:
        probes.append(_score_dispatch_denial(verdict))

    # -- must ALLOW: the paired half ----------------------------------------
    try:
        verdict = door(allowed_tool, "", session_id)
    except Exception as exc:  # noqa: BLE001
        probes.append(ProbeResult(
            "dispatch", "allow", REFUTED,
            f"the door raised {type(exc).__name__} on a benign action: {exc}",
        ))
    else:
        if verdict is None:
            probes.append(ProbeResult(
                "dispatch", "allow", PROVEN,
                f"a benign {allowed_tool} dispatch was allowed",
            ))
        else:
            probes.append(ProbeResult(
                "dispatch", "allow", REFUTED,
                f"a benign {allowed_tool} dispatch was REFUSED ({verdict}). The "
                "door is denying everything, which is its own outage and is what "
                "a deny-only canary would have reported as health.",
            ))

    return CanaryReport("dispatch", tuple(probes))


def probe_egress_door(
    adjudicate: Callable[[str, str], object],
    *,
    allowlist: frozenset[str] | set[str] | None,
    egress_expected_live: bool,
) -> CanaryReport:
    """Drive the REAL egress adjudication in both directions.

    ``adjudicate`` MUST be ``guarded_fetch._adjudicate_uncorded`` -- the
    adjudication -- and NOT ``_adjudicate``, which is the recording wrapper.
    See :data:`WHY_NO_RECEIPTS`.

    Neither probe issues a fetch; adjudication only. The denied probe
    additionally targets a host that resolves nowhere.

    ``egress_expected_live`` is the caller's answer to "is this door supposed to
    be open?", and it decides whether the allow probe can establish anything at
    all.

    IT IS NOT THE ALLOWLIST, and the distinction is the contract. A door can be
    shut by an empty allowlist OR by its capability never registering an
    adjudicator, and in the second case the allowlist stays populated while the
    door refuses everything -- correctly. A canary that inferred "shut" from the
    allowlist alone therefore reports a finding on a system that is working
    exactly as configured, and an alarm that fires on a healthy boot is an alarm
    nobody reads. The caller owns this answer because only the caller knows
    whether registration was attempted and succeeded.
    """
    probes: list[ProbeResult] = []
    denied_url = f"https://{CANARY_DENIED_HOST}/trust-spine-canary"

    # -- must DENY: a host that can never be on any allowlist -----------------
    try:
        result = adjudicate(denied_url, CANARY_PURPOSE)
    except Exception as exc:  # noqa: BLE001
        probes.append(ProbeResult(
            "egress", "deny", REFUTED,
            f"the door raised {type(exc).__name__}: {exc}",
        ))
    else:
        probes.append(_score_egress(result, "deny", CANARY_DENIED_HOST))

    # -- must ALLOW: only meaningful where the door is supposed to be open ----
    permitted = sorted(allowlist or ())
    if not egress_expected_live or not permitted:
        why = (
            "the egress allowlist is EMPTY" if not permitted
            else "outbound search is not enabled on this machine"
        )
        probes.append(ProbeResult(
            "egress", "allow", UNPROVEN,
            f"{why}, so a refusal is correct and this probe cannot distinguish "
            "a door that is deliberately shut from one that never loaded. "
            "Nothing is wrong; nothing is proven.",
        ))
        return CanaryReport("egress", tuple(probes))

    allowed_url = f"https://{permitted[0]}/trust-spine-canary"
    try:
        result = adjudicate(allowed_url, CANARY_PURPOSE)
    except Exception as exc:  # noqa: BLE001
        probes.append(ProbeResult(
            "egress", "allow", REFUTED,
            f"the door raised {type(exc).__name__} on a permitted host: {exc}",
        ))
    else:
        probes.append(_score_egress(result, "allow", permitted[0]))

    return CanaryReport("egress", tuple(probes))
