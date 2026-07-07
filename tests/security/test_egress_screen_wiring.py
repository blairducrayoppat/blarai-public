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
        """Calling the wiring twice does not stack a second screener (both the
        arm-hook and register_screener de-duplicate)."""
        exfil_screen.wire_into_egress_guard()
        exfil_screen.wire_into_egress_guard()
        egress_guard.arm()
        assert egress_guard.registered_screener_count() == 1
