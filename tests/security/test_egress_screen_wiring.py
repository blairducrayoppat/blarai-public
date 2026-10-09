"""End-to-end exfil-screen ↔ egress-guard wiring locks (Vikunja #634).

This file locks the RUNTIME wiring that turns the built-and-unit-tested outbound
exfil screen (``shared/security/exfil_screen.py``) from a module with no caller
into the live outbound-payload screener on the egress path (ADR-027 rule 4).

It exercises the REAL wiring — not a fake screener and not a stub arm path:
  * ``exfil_screen.wire_into_egress_guard()`` registers the REAL
    :func:`exfil_screen.screen` via the documented ``register_arm_hook`` seam, and
  * ``egress_guard.arm()`` (the same call the launcher makes at boot) runs that
    arm-hook so the screener is registered exactly when the guard arms.

The load-bearing contract under test (#634, Option A — destination-scoped
screening): the screener fires ONLY for sends on a socket connected to a vetted
EXTERNAL-allowlisted endpoint. Internal loopback / AF_HYPERV traffic — which
legitimately carries the runtime's own capability JWTs (PA↔AO) and user PII
(prompts) — is NEVER screened. Were it screened, the real screen (which detects
JWT-shaped tokens and reuses the PGOV PII recognizers) would flag the first
internal message and trip the kill-switch — a self-inflicted denial of service.
With the external allowlist EMPTY (today's production baseline) NO socket is ever
tagged, so the registered screener is a behavior-free no-op.

203.0.113.0/24 (RFC 5737 TEST-NET-3) is the external endpoint used here. It is
unroutable, so a real connect to it fails at the OS layer and cannot drive a send;
to prove the TAGGED-socket (external) screen path deterministically — without
network reachability — the external tests use a real loopback connection and force
the per-socket external-screen tag on, exercising the exact send/screen path a
real external-allowlisted socket would take.

ISOLATION: the autouse ``_pristine_guard`` fixture fully resets all egress global
state (disarm + clear screeners + clear arm-hooks + clear external allowlist +
release the trip latch) before and after every test, so neither the process-wide
``socket`` patch, a registered screener, the wired arm-hook, nor a latched trip can
bleed across tests. The root ``conftest.py`` redirects ``%LOCALAPPDATA%`` — no real
user data is touched.
"""

from __future__ import annotations

import array
import socket

import pytest

from shared.security import egress_guard, exfil_screen

# A realistic JWT-shaped capability token — the kind of internal credential the
# PA↔AO path carries on every adjudication. The real exfil screen DETECTS this
# (exfil_screen.py JWT recognizer); it MUST pass untouched on internal loopback.
_JWT_TOKEN = b"eyJhbGciOiJFUzI1NiJ9.eyJzdWIiOiJ4In0.AAAABBBBCCCCDDDDEEEEFFFF"

# A planted secret the real screen blocks (an SSN — via the reused PGOV PII path).
_PLANTED_SECRET = b"exfil attempt: ssn 123-45-6789 leaving the host"

# An RFC 5737 TEST-NET-3 address — documentation/test only, unroutable.
_EXTERNAL_HOST = "203.0.113.10"
_EXTERNAL_PORT = 443


@pytest.fixture(autouse=True)
def _pristine_guard() -> None:
    """Fully reset egress_guard before AND after each test (machinery + latch)."""

    def _reset() -> None:
        egress_guard.disarm()  # also releases the trip latch (rearm())
        egress_guard.clear_screeners()
        egress_guard.clear_arm_hooks()
        egress_guard.clear_external_allowlist()
        egress_guard.rearm()  # belt-and-braces: ensure latch released

    _reset()
    yield
    _reset()


def _free_loopback_listener() -> tuple[socket.socket, int]:
    """Bind a loopback listener under the armed guard and return (sock, port)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))  # loopback bind is allowed even when armed
    srv.listen(1)
    return srv, srv.getsockname()[1]


def _external_tagged_client(port: int) -> socket.socket:
    """Connect a client over loopback, then force the external-screen tag ON.

    Simulates a socket connected to an external-allowlisted endpoint: the bytes
    travel over loopback (deterministic), but ``_screen_outbound_enabled`` is set
    so the send path screens exactly as it would for a real external connection.
    """
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(2.0)
    client.connect(("127.0.0.1", port))
    client._screen_outbound_enabled = True  # type: ignore[attr-defined]
    return client


# ===========================================================================
# Scenario 1 — wired screen + NO external endpoint: internal JWT send passes.
# ===========================================================================
class TestWiredScreenInternalTrafficPasses:
    """With the REAL screen wired (arm-hook) and NO external endpoint allowlisted,
    an internal loopback send carrying a JWT-shaped token passes untouched — the
    screener never fires and the guard never trips. (The self-DoS this scoping
    prevents: an un-scoped screen would flag this JWT and cut all egress.)
    """

    def test_wire_registers_real_screen_at_arm_time(self) -> None:
        """wire_into_egress_guard() + arm() registers the REAL exfil_screen.screen
        as the active screener (the runtime seam, end to end)."""
        assert egress_guard.registered_screener_count() == 0, "clean pre-state"
        exfil_screen.wire_into_egress_guard()
        # The hook is registered but has NOT run yet (no screener until arm()).
        assert egress_guard.registered_screener_count() == 0, (
            "wiring must not register the screener until arm() runs the hook"
        )
        egress_guard.arm()
        assert egress_guard.registered_screener_count() == 1, (
            "arm() must run the wired arm-hook, registering exfil_screen.screen"
        )

    def test_internal_jwt_send_passes_untouched(self) -> None:
        """A JWT-shaped token on an internal loopback send passes — never screened,
        never tripped — even though the REAL screen (which detects JWTs) is wired."""
        exfil_screen.wire_into_egress_guard()
        egress_guard.arm()
        assert egress_guard.external_allowlist() == frozenset(), "no external endpoint"

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            conn, _ = srv.accept()
            client.sendall(_JWT_TOKEN)
            assert conn.recv(256) == _JWT_TOKEN, "internal JWT send must pass intact"
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()

        assert egress_guard.is_tripped() is False, (
            "an internal JWT send must NOT trip the kill-switch (would be a self-DoS)"
        )

    def test_internal_pii_send_passes_untouched(self) -> None:
        """User PII (an SSN) on an internal loopback send passes untouched — the
        real screen would block it on an EXTERNAL send, but internal is never
        screened (prompts legitimately carry PII between local services)."""
        exfil_screen.wire_into_egress_guard()
        egress_guard.arm()

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            conn, _ = srv.accept()
            client.sendall(_PLANTED_SECRET)
            assert conn.recv(256) == _PLANTED_SECRET, "internal PII send must pass intact"
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()
        assert egress_guard.is_tripped() is False


# ===========================================================================
# Scenario 2 — wired screen + one external endpoint allowlisted: a secret blocks,
# a clean payload passes.
# ===========================================================================
class TestWiredScreenExternalTrafficScreened:
    """With the REAL screen wired and one external endpoint allowlisted, a send on
    a socket bound for it that carries a planted secret BLOCKS with EgressTripped
    and trips the kill-switch; a clean payload passes.
    """

    def test_external_allowlist_entry_is_accepted(self) -> None:
        """The TEST-NET external endpoint is admitted to the allowlist (the
        widening mechanism the network-facing era uses; here to scope the tag)."""
        egress_guard.allow_external_endpoint(_EXTERNAL_HOST, _EXTERNAL_PORT)
        assert (_EXTERNAL_HOST, str(_EXTERNAL_PORT)) in egress_guard.external_allowlist()

    def test_planted_secret_to_external_blocks_and_trips(self) -> None:
        """A planted secret on an external-tagged send is BLOCKED (EgressTripped)
        and the kill-switch trips — the REAL screen → real trip handshake."""
        egress_guard.allow_external_endpoint(_EXTERNAL_HOST, _EXTERNAL_PORT)
        exfil_screen.wire_into_egress_guard()
        egress_guard.arm()

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = _external_tagged_client(port)
            conn, _ = srv.accept()
            with pytest.raises(egress_guard.EgressTripped):
                client.sendall(_PLANTED_SECRET)
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()

        assert egress_guard.is_tripped() is True, "a detected secret MUST trip"
        reason = egress_guard.trip_reason()
        assert reason is not None and "exfil screen" in reason, (
            "the trip reason must come from the real exfil screen"
        )
        # The trip reason must carry the label, never the raw secret value.
        assert "123-45-6789" not in reason, "trip reason must not leak the raw secret"

    def test_jwt_to_external_blocks_and_trips(self) -> None:
        """A JWT-shaped token on an external-tagged send is blocked — the exact
        leak this screen exists to stop once egress is enabled."""
        egress_guard.allow_external_endpoint(_EXTERNAL_HOST, _EXTERNAL_PORT)
        exfil_screen.wire_into_egress_guard()
        egress_guard.arm()

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = _external_tagged_client(port)
            conn, _ = srv.accept()
            with pytest.raises(egress_guard.EgressTripped):
                client.sendall(_JWT_TOKEN)
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()
        assert egress_guard.is_tripped() is True

    def test_clean_payload_to_external_passes(self) -> None:
        """A clean payload on an external-tagged send passes the real screen and
        is delivered (no false positive on benign content)."""
        egress_guard.allow_external_endpoint(_EXTERNAL_HOST, _EXTERNAL_PORT)
        exfil_screen.wire_into_egress_guard()
        egress_guard.arm()

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = _external_tagged_client(port)
            conn, _ = srv.accept()
            client.sendall(b"the weather in Paris is mild today")
            assert conn.recv(64) == b"the weather in Paris is mild today"
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()
        assert egress_guard.is_tripped() is False, "a clean external send must not trip"


# ===========================================================================
# Scenario 3 — the dormant no-op invariant (allowlist empty ⇒ screener never fires).
# ===========================================================================
class TestDormantNoOpInvariant:
    """With the external allowlist EMPTY (today's production baseline), the wired
    REAL screen never fires on ANY send — even a send carrying a secret — because
    no socket is ever tagged external. This is what keeps the #634 wiring safe to
    ship today: the screener is registered but behavior-free until egress is
    enabled post-#556.
    """

    def test_secret_on_internal_send_never_screened_when_allowlist_empty(self) -> None:
        """A secret-bearing internal loopback send is delivered untouched — the
        wired real screen is a no-op because nothing is allowlisted external."""
        assert egress_guard.external_allowlist() == frozenset(), "baseline: empty allowlist"
        exfil_screen.wire_into_egress_guard()
        egress_guard.arm()
        assert egress_guard.registered_screener_count() == 1, "screener IS registered"

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            conn, _ = srv.accept()
            # Carries a secret AND a JWT — both would block on an external send.
            client.sendall(_PLANTED_SECRET + b" " + _JWT_TOKEN)
            received = conn.recv(512)
            assert received == _PLANTED_SECRET + b" " + _JWT_TOKEN, (
                "with an empty allowlist the send must pass intact (dormant no-op)"
            )
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()
        assert egress_guard.is_tripped() is False, (
            "dormant invariant: registered screener + empty allowlist ⇒ never trips"
        )

    def test_loopback_socket_never_tagged_when_allowlist_empty(self) -> None:
        """The mechanism behind the dormant no-op: a loopback connect under the
        wired+armed guard never sets the per-socket external-screen flag."""
        exfil_screen.wire_into_egress_guard()
        egress_guard.arm()
        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            conn, _ = srv.accept()
            assert getattr(client, "_screen_outbound_enabled") is False
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()


# ===========================================================================
# Import hygiene — wiring is explicit; importing the module has no side effect.
# ===========================================================================
class TestNoImportTimeSideEffect:
    """Importing exfil_screen registers NOTHING — the no-side-effect promise the
    module docstring makes. Only calling wire_into_egress_guard() registers the
    arm-hook. (The autouse fixture has already cleared state; importing is a no-op.)
    """

    def test_import_alone_registers_no_arm_hook_or_screener(self) -> None:
        # exfil_screen is already imported at module top; the fixture cleared all
        # machinery. Re-importing must not have registered anything.
        import importlib

        importlib.import_module("shared.security.exfil_screen")
        egress_guard.arm()
        assert egress_guard.registered_screener_count() == 0, (
            "importing exfil_screen must NOT register a screener (no side effect)"
        )

    def test_wire_is_idempotent(self) -> None:
        """Calling the wiring repeatedly stacks neither a hook nor a screener.

        This asserted only the SCREENER count while its docstring claimed both
        halves de-duplicated. The arm-hook half was false — the hook was a fresh
        lambda each call, so ``register_arm_hook``'s identity de-duplication
        never matched and three calls stacked three hooks. The screener count
        stayed 1 because ``register_screener`` de-duplicates separately, which is
        precisely what hid the miss. Three calls, not two: two would also pass
        against an off-by-one.
        """
        exfil_screen.wire_into_egress_guard()
        exfil_screen.wire_into_egress_guard()
        exfil_screen.wire_into_egress_guard()
        assert len(egress_guard._arm_hooks) == 1, (
            "the arm-hook stacked — register_arm_hook de-duplicates by identity "
            "and cannot see a fresh lambda"
        )
        egress_guard.arm()
        assert egress_guard.registered_screener_count() == 1


# ===========================================================================
# Scenario 4 — THE OFF-TEST (#1580, claim register claim 12).
# ===========================================================================
class TestTheScreenIsTestedOff:
    """The control this file shipped without.

    Every test above that tags a send as externally scoped registers the screener
    first. So a green suite was consistent with two different worlds: the screen
    blocks, or the test cannot reach the screen. `security_by_design` principle 12
    exists for exactly that ambiguity — a lock ships with a test proving it BLOCKS
    and a toggle proving the probe FAILS when the lock is off.

    Scenario 3 above is NOT that toggle, and the distinction matters. It sends
    over LOOPBACK with the allowlist empty, which proves a SCOPE boundary: the
    socket is never tagged external, so the screener is never consulted. It says
    nothing about whether a screener that IS consulted does anything.

    This scenario holds the destination scoping FIXED — external allowlist
    populated, socket tagged external, same planted secret — and varies ONLY
    whether a screener is registered. Two states, one payload.
    """

    def test_the_same_secret_LEAVES_when_no_screener_is_registered(self) -> None:
        """OFF: external-tagged send, secret payload, NO screener.

        The payload is DELIVERED. That is the point: it shows the send path is
        genuinely reachable and genuinely unguarded without the screen, which is
        what makes the paired ON test evidence rather than decoration.
        """
        egress_guard.allow_external_endpoint(_EXTERNAL_HOST, _EXTERNAL_PORT)
        # Deliberately NOT calling exfil_screen.wire_into_egress_guard().
        egress_guard.arm()
        assert egress_guard.registered_screener_count() == 0, (
            "this test is meaningless with a screener registered — it must "
            "measure the UNGUARDED path"
        )

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = _external_tagged_client(port)
            conn, _ = srv.accept()
            client.sendall(_PLANTED_SECRET)
            received = conn.recv(512)
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()

        assert received == _PLANTED_SECRET, (
            "the secret did not arrive, so this probe never exercised the "
            "unguarded send path and the paired ON test proves nothing"
        )
        assert egress_guard.is_tripped() is False, (
            "nothing should trip with no screener registered"
        )

    def test_the_same_secret_is_BLOCKED_when_the_screener_is_registered(self) -> None:
        """ON: identical setup, identical payload, screener registered.

        Deliberately duplicates the assertion of
        ``test_planted_secret_to_external_blocks_and_trips`` so the pair sits
        together and a reader can see the single varied condition without
        cross-referencing another class.
        """
        egress_guard.allow_external_endpoint(_EXTERNAL_HOST, _EXTERNAL_PORT)
        exfil_screen.wire_into_egress_guard()
        egress_guard.arm()
        assert egress_guard.registered_screener_count() == 1

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = _external_tagged_client(port)
            conn, _ = srv.accept()
            with pytest.raises(egress_guard.EgressTripped):
                client.sendall(_PLANTED_SECRET)
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()

        assert egress_guard.is_tripped() is True

    def test_a_screener_that_RAISES_fails_closed(self) -> None:
        """FAIL-LOUD (principle 11): a broken screen must not become an open door.

        The send path catches a raising screener and trips rather than delivering.
        Asserted here because a screen that silently degrades is worse than none,
        and because the off-test above establishes that an unscreened send DOES
        deliver — so 'blocked' here is a real difference, not the default.
        """

        def _broken(_payload: bytes) -> bool:
            raise RuntimeError("screener exploded")

        egress_guard.allow_external_endpoint(_EXTERNAL_HOST, _EXTERNAL_PORT)
        egress_guard.register_screener(_broken)
        egress_guard.arm()

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = _external_tagged_client(port)
            conn, _ = srv.accept()
            with pytest.raises(egress_guard.EgressTripped):
                client.sendall(_PLANTED_SECRET)
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()

        assert egress_guard.is_tripped() is True, (
            "a raising screener must trip the kill-switch, not fall through"
        )


# ===========================================================================
# Scenario 5 — the review's findings, one lock each (#1580 adversarial review).
# ===========================================================================
class TestTheExternalTagIsEarnedNotAssumed:
    """Finding 1: the off/on pair's varied condition is a hand-set attribute.

    ``_external_tagged_client`` forces ``_screen_outbound_enabled`` rather than
    earning the tag. That is unavoidable — ``_is_external_screen_target`` refuses
    every loopback host by design (the self-DoS guard) and TEST-NET-3 is
    unroutable, so no real connect can earn the tag without real external egress.
    Holding the tag FIXED is what makes the pair's single varied condition honest.

    What it leaves unheld is the other half. "A tagged send is screened" and "the
    right destinations get tagged" are two claims, and forcing the tag proves only
    the first. The production trigger was locked ONLY by
    ``test_egress_sandbox_proving.py``, whose module-level skipif disables it on a
    loopback-only box — the posture this project is built toward — so on such a
    box the trigger had no lock at all.

    These drive the REAL decision and the REAL connect path, with no network.
    """

    def test_an_allowlisted_external_endpoint_IS_a_screen_target(self) -> None:
        egress_guard.allow_external_endpoint(_EXTERNAL_HOST, _EXTERNAL_PORT)
        assert egress_guard._is_external_screen_target(
            socket.AF_INET, (_EXTERNAL_HOST, _EXTERNAL_PORT)
        ) is True, (
            "an allowlisted external endpoint is not a screen target — the forced "
            "tag in the off/on pair is then simulating something that never happens"
        )

    def test_the_SAME_endpoint_is_NOT_a_target_with_an_empty_allowlist(self) -> None:
        """The control, and the production baseline: nothing allowlisted, nothing
        tagged, so the registered screener is a behaviour-free no-op."""
        assert egress_guard.external_allowlist() == frozenset()
        assert egress_guard._is_external_screen_target(
            socket.AF_INET, (_EXTERNAL_HOST, _EXTERNAL_PORT)
        ) is False

    def test_the_allowlist_REFUSES_a_loopback_entry_at_the_door(self) -> None:
        """Lock one of two: loopback cannot enter the external allowlist at all.

        Stronger than expected while writing this — the first draft allowlisted
        loopback and asserted the screen-target decision refused it, and the
        allowlist raised first. Recorded as its own assertion because a guarantee
        found by accident is still a guarantee, and the next person to widen the
        allowlist should see it stated.
        """
        with pytest.raises(ValueError, match="loopback"):
            egress_guard.allow_external_endpoint("127.0.0.1", 9999)

    def test_loopback_is_NEVER_a_target_even_if_the_allowlist_holds_it(self) -> None:
        """Lock two of two, INDEPENDENT of the first: the decision refuses loopback
        on its own, not merely because the allowlist would not hold it.

        The entry is forced directly into ``_external_allowlist``, bypassing the
        validating door above, so only the decision's own loopback rule can produce
        the refusal. Two independent locks on the self-DoS path (principle 3):
        internal IPC carries PA<->AO capability tokens and user prompts, which the
        real screen flags by design, so a single mistake here trips the kill-switch
        on the first internal message.
        """
        egress_guard._external_allowlist.add(("127.0.0.1", "9999"))
        try:
            assert egress_guard._is_external_screen_target(
                socket.AF_INET, ("127.0.0.1", 9999)
            ) is False, (
                "a loopback destination became a screen target — the first "
                "internal PA<->AO message would trip the kill-switch"
            )
        finally:
            egress_guard.clear_external_allowlist()

    @staticmethod
    def _recording_decision(
        monkeypatch: pytest.MonkeyPatch, verdict: bool
    ) -> list[tuple[object, object]]:
        """Stub the decision, RECORDING what the connect path hands it.

        The first version of this returned ``lambda _f, _a: True``, which ignores
        both arguments — so a ``connect()`` passing a hardcoded address, or a
        tagger passing family ``0``, tagged nothing in production and left this
        file 36/36 green. Each of those is a one-line change that disables the
        whole screen, and on a box with no non-loopback interface the only other
        lock (``test_egress_sandbox_proving.py``) skips itself.

        Recording the arguments is what turns "connect calls something" into
        "connect calls the decision with the destination it actually connected to".
        """
        seen: list[tuple[object, object]] = []

        def _decide(family: object, address: object) -> bool:
            seen.append((family, address))
            return verdict

        monkeypatch.setattr(egress_guard, "_is_external_screen_target", _decide)
        return seen

    def test_connect_TAGS_the_socket_and_asks_about_the_REAL_destination(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wiring AND the composition: what does ``connect()`` ask about?

        The decision tests above cannot see a ``_tag_screen_outbound`` that never
        runs, and a decision stub that ignores its arguments cannot see one that
        runs with the wrong ones.
        """
        seen = self._recording_decision(monkeypatch, True)
        egress_guard.arm()
        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            assert getattr(client, "_screen_outbound_enabled", False) is True, (
                "a successful connect to an external destination did not tag the "
                "socket — connect() is not calling _tag_screen_outbound"
            )
            assert seen, "connect() never consulted the screen-target decision"
            family, address = seen[-1]
            assert address == ("127.0.0.1", port), (
                "connect() asked the decision about a DIFFERENT destination than "
                f"the one it connected to: {address!r} vs {('127.0.0.1', port)!r}. "
                "The tag would then be decided for an address nothing is talking to."
            )
            assert family == socket.AF_INET, (
                f"the tagger passed family {family!r} instead of the socket's own "
                f"{socket.AF_INET!r} — the decision refuses a non-INET family, so "
                "this silently disables screening for every socket"
            )
        finally:
            for sk in (client, srv):
                if sk is not None:
                    sk.close()

    def test_connect_ex_TAGS_the_socket_and_asks_about_the_REAL_destination(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``connect_ex`` has its OWN tagging call and had no lock anywhere.

        Not a variant of the test above: it is a second, independent call site in
        ``egress_guard`` (the non-blocking / asyncio connect path). Removing its
        tagging call left the entire security tier green on a box WITH a network
        interface, so unlike the composition gap this one was unlocked everywhere.
        """
        seen = self._recording_decision(monkeypatch, True)
        egress_guard.arm()
        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            rc = client.connect_ex(("127.0.0.1", port))
            assert rc == 0, f"loopback connect_ex failed with {rc}"
            assert getattr(client, "_screen_outbound_enabled", False) is True, (
                "connect_ex did not tag the socket — the non-blocking connect path "
                "is not calling _tag_screen_outbound"
            )
            assert seen and seen[-1][1] == ("127.0.0.1", port)
            assert seen[-1][0] == socket.AF_INET
        finally:
            for sk in (client, srv):
                if sk is not None:
                    sk.close()

    def test_connect_ex_does_NOT_tag_when_the_destination_is_not_external(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The paired control for connect_ex."""
        self._recording_decision(monkeypatch, False)
        egress_guard.arm()
        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect_ex(("127.0.0.1", port))
            assert getattr(client, "_screen_outbound_enabled", False) is False
        finally:
            for sk in (client, srv):
                if sk is not None:
                    sk.close()

    def test_connect_does_NOT_tag_when_the_destination_is_not_external(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The paired control: same connect, decision stubbed FALSE."""
        self._recording_decision(monkeypatch, False)
        egress_guard.arm()
        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            assert getattr(client, "_screen_outbound_enabled", False) is False
        finally:
            for sk in (client, srv):
                if sk is not None:
                    sk.close()


class TestEveryBufferShapeIsScreened:
    """Finding 2: ``array.array("B", secret)`` walked the screen, silently.

    ``_as_payload_bytes`` recognised only bytes/bytearray/memoryview and returned
    ``None`` for anything else, and the caller took ``None`` as "skip this frame".
    Measured on the ON-test's exact setup, the planted secret was DELIVERED with
    no trip and no log — a silent skip in a control path, which principle 11 names
    as a defect outright.

    It also broke the off-test's own logic: the OFF arm reads DELIVERED as proof
    that no screener was registered, and an unscreenable buffer shape produces the
    identical signature. The pair could not distinguish the world it claimed to
    have eliminated.
    """

    @staticmethod
    def _send_secret(payload: object, method: str = "sendall") -> tuple[bool, str]:
        """Send ``payload`` on an external-tagged socket with the REAL screen on.

        Returns ``(delivered, exception_name)``.
        """
        egress_guard.allow_external_endpoint(_EXTERNAL_HOST, _EXTERNAL_PORT)
        exfil_screen.wire_into_egress_guard()
        egress_guard.arm()
        assert egress_guard.registered_screener_count() == 1

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        delivered = False
        exc_name = ""
        try:
            client = _external_tagged_client(port)
            conn, _ = srv.accept()
            conn.settimeout(1.0)
            try:
                getattr(client, method)(payload)
            except BaseException as exc:  # noqa: BLE001 - classifying the outcome
                exc_name = type(exc).__name__
            if not exc_name:
                try:
                    delivered = bool(conn.recv(512))
                except OSError:
                    delivered = False
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()
        return delivered, exc_name

    def test_an_array_payload_reaches_the_screener_as_the_same_bytes(self) -> None:
        """The load-bearing assertion, and the one the end-to-end test cannot make.

        The first version of this class only checked that an ``array.array`` send
        did not deliver and did trip. That passed even with the fix reverted,
        because an unscreenable payload now ALSO trips — "screened and blocked"
        and "unscreenable and refused" produce the identical outcome, which is the
        same two-worlds-one-signature problem the off-test exists to retire.

        This separates them: the buffer must arrive at the screener as the exact
        bytes the kernel would have sent.
        """
        assert egress_guard._as_payload_bytes(
            array.array("B", _PLANTED_SECRET)
        ) == _PLANTED_SECRET

    @pytest.mark.parametrize("method", ["sendall", "send"])
    def test_an_array_payload_is_SCREENED_not_skipped(self, method: str) -> None:
        """The regression, end to end. Same secret, same socket, a non-bytes buffer.

        The trip REASON is asserted, not just the trip: it must name the screen's
        positive detection, so a revert that made the payload unscreenable-and-
        refused cannot masquerade as a payload that was screened and blocked.
        """
        delivered, exc_name = self._send_secret(
            array.array("B", _PLANTED_SECRET), method
        )
        assert not delivered, (
            f"the planted secret LEFT THE HOST via {method}(array.array) — the "
            "screen was skipped for a buffer shape it did not recognise"
        )
        assert exc_name == "EgressTripped"
        assert egress_guard.is_tripped() is True
        reason = egress_guard.trip_reason() or ""
        assert "positive detection" in reason, (
            "the send was refused, but NOT because the screen detected anything — "
            f"the array payload never reached the screener. Trip reason: {reason!r}"
        )

    def test_a_bytes_payload_still_behaves_identically(self) -> None:
        """The control: the shape that always worked must be unchanged.

        Without it, a fix that broke the bytes path while fixing the array path
        would read as success.
        """
        delivered, exc_name = self._send_secret(_PLANTED_SECRET)
        assert not delivered
        assert exc_name == "EgressTripped"

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(object(), id="not-a-buffer"),
            pytest.param("a string", id="str"),
            pytest.param(memoryview(bytearray(b"0123456789"))[::2], id="strided-view"),
        ],
    )
    def test_an_unscreenable_payload_is_REFUSED_without_cutting_all_egress(
        self, payload: object
    ) -> None:
        """Fail-closed, yes. Kill-switch, no — and the difference is measurable.

        This runs BEFORE ``super().send()``, and every payload here is one the raw
        socket itself rejects (TypeError or BufferError). Contrapositive: if the
        socket ACCEPTS a payload it is a C-contiguous buffer, on which the cast
        succeeds — so ``None`` from ``_as_payload_bytes`` means the payload was
        never going to leave.

        The first version of this fix tripped. Tripping cuts ALL egress, including
        the loopback Policy-Agent gateway and the vsock channel, with a
        Lead-Architect-only re-arm — for a local type error that could not leak.
        That is a posture trade I had no business taking silently.
        """
        assert egress_guard._as_payload_bytes(payload) is None
        egress_guard.register_screener(lambda _p: False)
        egress_guard.arm()
        with pytest.raises(egress_guard.EgressDenied):
            egress_guard._screen_outbound(payload)
        assert egress_guard.is_tripped() is False, (
            "an unscreenable payload latched the kill-switch — internal IPC is now "
            "dead until a human re-arms, over a payload the socket would have "
            "refused anyway"
        )

    def test_a_screenable_buffer_is_still_screened_and_still_trips(self) -> None:
        """The control for the test above: the refusal is scoped to the
        unscreenable, and a real detection still cuts egress as it must."""
        egress_guard.allow_external_endpoint(_EXTERNAL_HOST, _EXTERNAL_PORT)
        exfil_screen.wire_into_egress_guard()
        egress_guard.arm()
        with pytest.raises(egress_guard.EgressTripped):
            egress_guard._screen_outbound(array.array("B", _PLANTED_SECRET))
        assert egress_guard.is_tripped() is True


class TestADuplicatedSocketKeepsItsTag:
    """Finding 3: ``dup()`` of a tagged socket returned an unscreened socket.

    ``socket.dup()`` builds ``self.__class__(..., fileno=fd)`` and ``__init__``
    clears the tag for every fileno-built socket — right for ``accept()``, where
    the peer never connected through this guard, wrong for a duplicate of a
    connected socket. Same TCP connection, same destination, screen registered,
    and the secret was DELIVERED.
    """

    def test_a_dup_of_a_tagged_socket_still_screens(self) -> None:
        egress_guard.allow_external_endpoint(_EXTERNAL_HOST, _EXTERNAL_PORT)
        exfil_screen.wire_into_egress_guard()
        egress_guard.arm()

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        duplicate: socket.socket | None = None
        try:
            client = _external_tagged_client(port)
            conn, _ = srv.accept()
            duplicate = client.dup()
            assert getattr(duplicate, "_screen_outbound_enabled", False) is True, (
                "the duplicate lost the external-screen tag — the tag belongs to "
                "the connection, not to the Python object holding the handle"
            )
            with pytest.raises(egress_guard.EgressTripped):
                duplicate.sendall(_PLANTED_SECRET)
        finally:
            for sk in (duplicate, conn, client, srv):
                if sk is not None:
                    sk.close()
        assert egress_guard.is_tripped() is True

    def test_a_dup_of_an_UNTAGGED_socket_stays_untagged(self) -> None:
        """The control: the tag is COPIED, not set. An internal socket's duplicate
        must not become screened, or internal IPC self-trips."""
        egress_guard.arm()
        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        duplicate: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            assert getattr(client, "_screen_outbound_enabled", False) is False
            duplicate = client.dup()
            assert getattr(duplicate, "_screen_outbound_enabled", False) is False
        finally:
            for sk in (duplicate, client, srv):
                if sk is not None:
                    sk.close()


class TestAScreenerRaisingOutsideTheExceptionHierarchy:
    """Finding 5: the fail-loud test certified a class and exercised one instance.

    ``_screen_outbound`` caught ``Exception`` only. A screener raising
    ``SystemExit``, ``KeyboardInterrupt`` or a bare ``BaseException`` never
    delivered the payload — so this was never an open door — but the kill-switch
    did NOT latch and nothing was recorded, so the next send on the next socket
    proceeded as though the screen were healthy.

    The fix RECORDS and re-raises unchanged, and latches only for a failure that
    is neither an Exception nor control flow. Interpreter shutdown and Ctrl-C must
    keep working — swallowing them would be its own defect — and so must the
    loopback IPC a latch would cut.
    """

    @pytest.mark.parametrize(
        "exc_type", [SystemExit, KeyboardInterrupt, GeneratorExit]
    )
    def test_CONTROL_FLOW_is_recorded_and_propagated_but_does_NOT_latch(
        self, exc_type: type[BaseException]
    ) -> None:
        """Ctrl-C through the screener must not cut the runtime's internal IPC.

        The payload is not delivered either way — this arm is above
        ``super().send()`` — so there is no open door in either design. The
        original defect was that NOTHING WAS RECORDED, and a later send then
        proceeded as though the screen were healthy; recording it fixes that.
        Latching does not: it cuts the loopback Policy-Agent gateway and the vsock
        channel until a human re-arms, and an operator interrupt is not an ADR-027
        §3 anomaly. My first fix latched, which was a posture trade taken silently.
        """

        def _raising(_payload: bytes) -> bool:
            raise exc_type("interrupted")

        egress_guard.register_screener(_raising)
        egress_guard.arm()
        with pytest.raises(exc_type):
            egress_guard._screen_outbound(_PLANTED_SECRET)
        assert egress_guard.is_tripped() is False, (
            f"a screener interrupted by {exc_type.__name__} latched the "
            "kill-switch — a Ctrl-C now kills loopback IPC until an operator "
            "re-arms"
        )

    def test_a_NON_control_flow_BaseException_DOES_latch(self) -> None:
        """The control, and the half of finding 5 that was genuinely a hole.

        A screener failing in a way that is neither an Exception nor control flow
        IS a screen failure, and a later send must not proceed as though the
        screen were healthy. Varying only the exception type from the test above.
        """

        def _raising(_payload: bytes) -> bool:
            raise BaseException("screener exploded")  # noqa: TRY002

        egress_guard.register_screener(_raising)
        egress_guard.arm()
        with pytest.raises(BaseException, match="screener exploded"):
            egress_guard._screen_outbound(_PLANTED_SECRET)
        assert egress_guard.is_tripped() is True, (
            "a screener that failed outside the Exception hierarchy left the "
            "kill-switch unlatched — the next send would proceed as if the screen "
            "were healthy"
        )

    def test_a_raising_trip_does_not_replace_the_propagating_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``trip()`` calls ``_alert_operator``, which can raise when logging
        handlers are closed during interpreter shutdown — the exact case the
        BaseException arm exists to survive. The original exception must still be
        the one that arrives, and the latch must still be set.
        """

        def _boom(_reason: str) -> None:
            raise RuntimeError("alerting failed during shutdown")

        monkeypatch.setattr(egress_guard, "_alert_operator", _boom)

        sentinel = BaseException("the original")

        def _raising(_payload: bytes) -> bool:
            raise sentinel

        egress_guard.register_screener(_raising)
        egress_guard.arm()
        with pytest.raises(BaseException) as caught:
            egress_guard._screen_outbound(_PLANTED_SECRET)
        assert caught.value is sentinel, (
            f"the propagating exception was replaced by {caught.value!r} — a "
            "failed operator alert cost the caller its own error"
        )
        assert egress_guard.is_tripped() is True, (
            "the latch was lost because the alert raised; the state is set before "
            "the alert precisely so it survives one"
        )


class TestAnUnreadableVerdictTripsWithAnHonestReason:
    """Finding 6: the trip reason stated a truthiness test the code never made.

    ``_normalise_screen_result``'s fallback branch is reached by ANY value with no
    readable verdict, falsy included — which is correct and fail-closed — but it
    labelled the trip "non-standard TRUTHY verdict", so an operator reading the
    reason for a screener that returned ``0`` was told something false about their
    own system.
    """

    @pytest.mark.parametrize("verdict", [0, "", 0.0, object()])
    def test_an_unreadable_verdict_trips(self, verdict: object) -> None:
        result = egress_guard._normalise_screen_result(verdict)
        assert result is not None and result.detected is True, (
            "a screener verdict with no readable flag was passed as clean — "
            "guessing 'clean' from falsiness is an open door"
        )
        assert "truthy" not in result.reason, (
            f"the trip reason claims a truthiness test that was never made: "
            f"{result.reason!r}"
        )

    @pytest.mark.parametrize("verdict", [None, False])
    def test_an_explicit_clean_verdict_is_still_clean(self, verdict: object) -> None:
        """The control. Fail-closed must not become fail-always."""
        assert egress_guard._normalise_screen_result(verdict) is None
