r"""Egress-stack activation-proving against NON-LOOPBACK traffic (Vikunja #643, Tier A.3).

WHAT THIS FILE PROVES (and how it differs from the loopback-level proofs)
========================================================================
The egress stack — the raw-socket guard (ADR-020), the auto-trip kill-switch
(ADR-027 §3), the deny-by-default external allowlist (ADR-027 §1), and the wired
outbound exfil screen (ADR-027 rule 4 / Vikunja #634) — is armed on every boot but
has, until now, only been exercised against LOOPBACK traffic. The existing proofs
in ``test_egress_core.py`` and ``test_egress_screen_wiring.py`` connect over
``127.0.0.1`` and *force* the per-socket external-screen tag on
(``client._screen_outbound_enabled = True``) because an RFC-5737 TEST-NET address
is unroutable and a real connect to it cannot drive a send.

#643 is the INCREMENT: prove the whole stack against genuinely NON-LOOPBACK
traffic, end to end, without forcing any internal flag — the destination-scoped
tagging path fires *by itself* because the destination really is a non-loopback
INET address on the widened allowlist.

THE NON-LOOPBACK ENDPOINT MECHANISM (the scope decision — Option A: self-contained
sandbox harness with a throwaway local "external" endpoint)
==================================================================================
A same-host connection to one of the box's OWN LAN IPs (e.g. ``192.168.x.y``)
travels through the real OS network stack — the accepted peer's address is the
LAN IP, not ``127.0.0.1`` — yet it never leaves the machine: there is no router
hop and no internet. To the egress guard the destination is EXTERNAL
(``_is_loopback_host`` is False, so it is permitted ONLY if explicitly
allowlisted, and a non-loopback bind / off-allowlist connect auto-trips). To the
OS it loops back locally. That is exactly the air-gap-safe sandbox the LA chose:
a real external-shaped round-trip with zero real external connection.

  * Discovery: ``socket.gethostbyname(socket.gethostname())``; if that yields a
    loopback (``127.x``) address or fails, enumerate the host's IPv4 addresses via
    ``getaddrinfo`` and take the first non-loopback one. If NO non-loopback local
    address exists (a fully air-gapped box with only a loopback interface), the
    whole module SKIPS gracefully (``pytest.skip``) — it never fails for want of a
    LAN address, and it NEVER attempts a real external/internet connection.
  * Listener: bound to ``(addr, 0)`` (ephemeral port) **before** the guard is
    armed. This is deliberate: once armed, the guard correctly REFUSES a
    non-loopback bind (it would create an externally-reachable listener — the
    air-gap forbids ingress, ADR-027 / SECURITY_ROADMAP §6 Decision-7). The
    sandbox stands its endpoint up first, then arms, so arming finds an already-
    bound socket — matching how a real already-listening external service would
    look to a freshly-armed guard.
  * Deny-by-default target: allowlist the throwaway endpoint's EXACT
    ``(addr, port)``, then aim the deny-by-default connect at the SAME ``addr`` on
    a DIFFERENT (unbound) port. That is off-allowlist (the allowlist is
    host+port-scoped), so the guard auto-trips it BEFORE any OS connection attempt
    — robust on a box with only one non-loopback address, and requiring no second
    reachable host.

THROWAWAY DATA ONLY (ADR-027 Decision 8 — dev-mode sandbox)
===========================================================
The "planted secret" is a FAKE PEM private-key header (the literal label string,
no real key material) and a fake SSN — throwaway test fixtures, never a real
credential. The trip-reason assertion proves the audit label travels while the
raw secret value does NOT (the exfil screen reports labels + offsets only).

ISOLATION
=========
Every test runs under the autouse ``_pristine_guard`` fixture (the same reset
pattern as ``test_egress_core.py``: disarm + clear screeners + clear arm-hooks +
clear external allowlist + release the trip latch, before AND after), so neither
the process-wide ``socket`` patch, a registered screener, the wired arm-hook, nor
a latched trip can bleed across tests or into the wider suite. The root
``conftest.py`` redirects ``%LOCALAPPDATA%`` — no real user data is touched. All
sockets are closed in ``finally``. The listener is bound pre-arm and closed after,
so the guard never sees a leaked non-loopback bind.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from typing import Optional

import pytest

from shared.security import egress_guard, exfil_screen

# A FAKE PEM private-key header — throwaway test fixture, NOT a real key (no key
# material follows the label). The real exfil screen's PRIVATE_KEY_PEM recognizer
# matches the header line itself, so this is sufficient to drive a positive
# detection without ever embedding a real credential (ADR-027 Decision 8).
_PLANTED_PEM_SECRET = b"-----BEGIN RSA PRIVATE KEY-----"
_PEM_LABEL = "PRIVATE_KEY_PEM"

# A second throwaway secret (a fake SSN) routed through the reused PGOV PII path,
# used to double-check the label-not-raw-value discipline on a different recognizer.
_PLANTED_SSN_SECRET = b"exfil attempt: ssn 123-45-6789 leaving the host"
_SSN_RAW = "123-45-6789"

# A benign payload that must pass the screen cleanly and be delivered.
_CLEAN_PAYLOAD = b"the weather in Paris is mild today"

_SOCK_TIMEOUT = 3.0


# ===========================================================================
# Non-loopback local-address discovery (the air-gap-safe sandbox endpoint).
# ===========================================================================
def _discover_non_loopback_ipv4() -> Optional[str]:
    """Return a usable NON-LOOPBACK local IPv4 address, or ``None`` if none exists.

    Tries ``gethostbyname(gethostname())`` first (the primary host address); if
    that is loopback or fails, enumerates the host's IPv4 addresses and takes the
    first non-loopback one. Returns ``None`` only when the box genuinely has no
    non-loopback IPv4 interface (a fully air-gapped machine) — the caller then
    SKIPS rather than fails. Never performs any external connection: address
    discovery is purely local (name resolution + interface enumeration).
    """
    candidates: list[str] = []

    try:
        primary = socket.gethostbyname(socket.gethostname())
        if not ipaddress.ip_address(primary).is_loopback:
            candidates.append(primary)
    except (OSError, ValueError):
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            try:
                if not ipaddress.ip_address(addr).is_loopback and addr not in candidates:
                    candidates.append(addr)
            except ValueError:
                continue
    except OSError:
        pass

    return candidates[0] if candidates else None


# Resolved ONCE at import (before any arm()) so binding the listener uses the real
# stdlib socket and discovery is never attempted under an armed guard. A None
# result skips the whole module: the sandbox cannot run without a non-loopback
# address, and that is a graceful skip, not a failure.
_NON_LOOPBACK_ADDR: Optional[str] = _discover_non_loopback_ipv4()

pytestmark = pytest.mark.skipif(
    _NON_LOOPBACK_ADDR is None,
    reason=(
        "no non-loopback local IPv4 address available — the #643 sandbox needs one "
        "to stand up a throwaway 'external' endpoint that round-trips same-host "
        "(a fully air-gapped box with only a loopback interface skips this proof)"
    ),
)


@pytest.fixture(autouse=True)
def _pristine_guard() -> None:
    """Fully reset egress_guard before AND after each test (machinery + latch).

    Mirrors the reset used by ``test_egress_core.py``: disarm (releases the trip
    latch via rearm()), clear screeners, clear arm-hooks, clear the external
    allowlist, and belt-and-braces rearm — so no global ``socket`` patch,
    registered screener, wired arm-hook, widened endpoint, or latched trip can
    bleed across tests or into the wider suite.
    """

    def _reset() -> None:
        egress_guard.disarm()
        egress_guard.clear_screeners()
        egress_guard.clear_arm_hooks()
        egress_guard.clear_external_allowlist()
        egress_guard.rearm()

    _reset()
    yield
    _reset()


def _bind_throwaway_listener() -> tuple[socket.socket, str, int]:
    """Bind a throwaway TCP listener on the non-loopback address (ephemeral port).

    Bound with the REAL stdlib socket BEFORE the guard is armed — once armed the
    guard refuses a non-loopback bind (correctly; that is a tested property). The
    caller arms only after this returns, then closes the listener in ``finally``.
    """
    assert _NON_LOOPBACK_ADDR is not None  # guarded by pytestmark skipif
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.settimeout(_SOCK_TIMEOUT)
    srv.bind((_NON_LOOPBACK_ADDR, 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    return srv, _NON_LOOPBACK_ADDR, port


def _serve_one_recv(srv: socket.socket, sink: dict) -> threading.Thread:
    """Accept one connection on ``srv`` and record the first recv into ``sink``.

    Runs in a daemon thread so a never-arriving connection cannot hang the test
    (the socket timeout bounds the accept). The recorded bytes confirm a payload
    actually traversed the OS network stack to the listener (the round-trip proof).
    """

    def _serve() -> None:
        try:
            conn, _peer = srv.accept()
            try:
                sink["data"] = conn.recv(1024)
            finally:
                conn.close()
        except OSError as exc:  # timeout / closed — recorded, never raised out of thread
            sink["error"] = repr(exc)

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return thread


def _free_ephemeral_port_on(addr: str) -> int:
    """Reserve-then-release an ephemeral port on ``addr`` and return its number.

    Used to obtain a DIFFERENT, currently-unbound port on the same non-loopback
    address for the deny-by-default target. Bound and immediately closed with the
    REAL stdlib socket BEFORE arming, so the guard never sees the bind; the port is
    free (nothing listening) when the off-allowlist connect is later attempted, but
    the guard refuses that connect BEFORE any OS attempt, so reachability is moot.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((addr, 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


# ===========================================================================
# Proof 1 — Deny-by-default holds + auto-trips on a non-allowlisted destination.
# ===========================================================================
class TestProof1DenyByDefaultAndAutoTrip:
    """A connect to a NON-LOOPBACK address that is NOT on the allowlist raises
    ``EgressDenied`` AND auto-trips the kill-switch (``is_tripped()``).

    The allowlisted throwaway endpoint is admitted on its exact ``(addr, port)``;
    the deny-by-default connect targets the SAME non-loopback addr on a DIFFERENT
    (unbound) port — off-allowlist (host+port-scoped), so the guard refuses it
    BEFORE the OS attempts any connection (no real external attempt is made).
    """

    def test_offlist_non_loopback_connect_denied_and_auto_trips(self) -> None:
        srv, addr, allowed_port = _bind_throwaway_listener()
        denied_port = _free_ephemeral_port_on(addr)
        # Guard against the (astronomically unlikely) ephemeral-port collision so
        # the "different port" really is off-allowlist.
        if denied_port == allowed_port:
            denied_port = allowed_port + 1

        offlist_sock: socket.socket | None = None
        try:
            egress_guard.allow_external_endpoint(addr, allowed_port)
            egress_guard.arm()
            assert egress_guard.is_tripped() is False, "default-off at arm (not tripped)"

            offlist_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            offlist_sock.settimeout(_SOCK_TIMEOUT)
            with pytest.raises(egress_guard.EgressDenied):
                offlist_sock.connect((addr, denied_port))
        finally:
            for sk in (offlist_sock, srv):
                if sk is not None:
                    sk.close()

        assert egress_guard.is_tripped() is True, (
            "an off-allowlist non-loopback connect MUST auto-trip the kill-switch"
        )
        reason = egress_guard.trip_reason()
        assert reason is not None and addr in reason, (
            "the trip reason must name the off-allowlist destination"
        )

    def test_offlist_connect_cuts_all_subsequent_egress(self) -> None:
        """After the auto-trip, the kill-switch is latched — even the allowlisted
        endpoint is now refused with ``EgressTripped`` (ALL egress cut, ADR-027 §3)."""
        srv, addr, allowed_port = _bind_throwaway_listener()
        denied_port = _free_ephemeral_port_on(addr)
        if denied_port == allowed_port:
            denied_port = allowed_port + 1

        offlist_sock: socket.socket | None = None
        post_trip_sock: socket.socket | None = None
        try:
            egress_guard.allow_external_endpoint(addr, allowed_port)
            egress_guard.arm()

            offlist_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            offlist_sock.settimeout(_SOCK_TIMEOUT)
            with pytest.raises(egress_guard.EgressDenied):
                offlist_sock.connect((addr, denied_port))
            assert egress_guard.is_tripped() is True

            # Now even the ALLOWLISTED endpoint is cut — the trip is global, latched.
            post_trip_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            post_trip_sock.settimeout(_SOCK_TIMEOUT)
            with pytest.raises(egress_guard.EgressTripped):
                post_trip_sock.connect((addr, allowed_port))
        finally:
            for sk in (offlist_sock, post_trip_sock, srv):
                if sk is not None:
                    sk.close()


# ===========================================================================
# Proof 2 — The allowlisted endpoint is permitted (real same-host connect; no trip).
# ===========================================================================
class TestProof2AllowlistedEndpointPermitted:
    """A connect to the throwaway allowlisted non-loopback endpoint is NOT
    ``EgressDenied`` — it actually connects same-host — and does NOT trip.

    This exercises the REAL destination-scoped tagging path: connecting to a
    genuine non-loopback INET host on the widened allowlist sets
    ``_screen_outbound_enabled`` BY ITSELF (no forced flag), unlike the loopback-
    level proofs that must set it directly.
    """

    def test_allowlisted_non_loopback_connect_permitted_and_does_not_trip(self) -> None:
        srv, addr, port = _bind_throwaway_listener()
        sink: dict = {}
        client: socket.socket | None = None
        try:
            egress_guard.allow_external_endpoint(addr, port)
            egress_guard.arm()
            thread = _serve_one_recv(srv, sink)

            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(_SOCK_TIMEOUT)
            # Must NOT raise — the endpoint is allowlisted and reachable same-host.
            client.connect((addr, port))

            # The REAL tagging path fired by itself for a genuine external dest.
            assert getattr(client, "_screen_outbound_enabled") is True, (
                "a connect to an allowlisted NON-LOOPBACK endpoint must tag the "
                "socket for outbound screening (destination-scoped, ADR-027 rule 4)"
            )
            thread.join(timeout=_SOCK_TIMEOUT)
        finally:
            for sk in (client, srv):
                if sk is not None:
                    sk.close()

        assert egress_guard.is_tripped() is False, (
            "connecting to the allowlisted endpoint must NOT trip the kill-switch"
        )

    def test_loopback_still_permitted_alongside_allowlisted_external(self) -> None:
        """Sanity: widening one external endpoint does not disturb the loopback
        baseline — a loopback round-trip still passes and stays unscreened/untagged."""
        srv, addr, port = _bind_throwaway_listener()
        try:
            egress_guard.allow_external_endpoint(addr, port)
            egress_guard.arm()

            lo_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            lo_srv.settimeout(_SOCK_TIMEOUT)
            lo_srv.bind(("127.0.0.1", 0))  # loopback bind allowed even when armed
            lo_srv.listen(1)
            lo_port = lo_srv.getsockname()[1]
            lo_sink: dict = {}
            lo_client: socket.socket | None = None
            try:
                lo_thread = _serve_one_recv(lo_srv, lo_sink)
                lo_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                lo_client.settimeout(_SOCK_TIMEOUT)
                lo_client.connect(("127.0.0.1", lo_port))
                assert getattr(lo_client, "_screen_outbound_enabled") is False, (
                    "a loopback socket must NEVER be tagged for screening"
                )
                lo_client.sendall(b"loopback-ping")
                lo_thread.join(timeout=_SOCK_TIMEOUT)
                assert lo_sink.get("data") == b"loopback-ping"
            finally:
                for sk in (lo_client, lo_srv):
                    if sk is not None:
                        sk.close()
        finally:
            srv.close()
        assert egress_guard.is_tripped() is False


# ===========================================================================
# Proof 3 — The wired exfil-screen blocks a planted secret on the REAL external
# path (EgressTripped + trip, with the LABEL in the reason, never the raw secret).
# ===========================================================================
class TestProof3WiredScreenBlocksPlantedSecret:
    """A payload carrying a PLANTED secret, sent to the allowlisted non-loopback
    endpoint, raises ``EgressTripped`` and trips the kill-switch — the REAL wired
    exfil screen → real trip handshake against genuinely external-shaped traffic.
    The trip reason carries the detection LABEL, never the raw secret value.
    """

    def test_planted_pem_secret_to_external_blocks_and_trips(self) -> None:
        srv, addr, port = _bind_throwaway_listener()
        sink: dict = {}
        client: socket.socket | None = None
        try:
            egress_guard.allow_external_endpoint(addr, port)
            exfil_screen.wire_into_egress_guard()  # wire the REAL screen
            egress_guard.arm()
            assert egress_guard.registered_screener_count() == 1, (
                "arm() must run the wired arm-hook, registering the real screen"
            )
            _serve_one_recv(srv, sink)

            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(_SOCK_TIMEOUT)
            client.connect((addr, port))
            assert getattr(client, "_screen_outbound_enabled") is True

            with pytest.raises(egress_guard.EgressTripped):
                client.sendall(_PLANTED_PEM_SECRET)
        finally:
            for sk in (client, srv):
                if sk is not None:
                    sk.close()

        assert egress_guard.is_tripped() is True, "a detected secret MUST trip"
        reason = egress_guard.trip_reason()
        assert reason is not None
        # The trip reason carries the screen's audit context + the detection LABEL.
        assert "exfil screen" in reason, "the trip reason must come from the real screen"
        assert _PEM_LABEL in reason, (
            f"the trip reason must carry the detection label {_PEM_LABEL!r}"
        )
        # ...and MUST NOT carry the raw matched secret bytes.
        assert "BEGIN RSA PRIVATE KEY" not in reason, (
            "the trip reason must NOT leak the raw secret value (labels + offsets only)"
        )

    def test_planted_ssn_secret_to_external_blocks_without_leaking_value(self) -> None:
        """A different recognizer layer (the reused PGOV PII path, an SSN) likewise
        blocks + trips on the external send, and the raw SSN never reaches the
        trip reason — double-checking the label-not-raw-value discipline."""
        srv, addr, port = _bind_throwaway_listener()
        sink: dict = {}
        client: socket.socket | None = None
        try:
            egress_guard.allow_external_endpoint(addr, port)
            exfil_screen.wire_into_egress_guard()
            egress_guard.arm()
            _serve_one_recv(srv, sink)

            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(_SOCK_TIMEOUT)
            client.connect((addr, port))
            with pytest.raises(egress_guard.EgressTripped):
                client.sendall(_PLANTED_SSN_SECRET)
        finally:
            for sk in (client, srv):
                if sk is not None:
                    sk.close()

        assert egress_guard.is_tripped() is True
        reason = egress_guard.trip_reason() or ""
        assert _SSN_RAW not in reason, "the trip reason must NOT leak the raw SSN value"

    def test_secret_blocked_before_delivery_to_listener(self) -> None:
        """Block-on-detection means the secret is refused BEFORE it leaves: the
        listener never receives the planted-secret bytes (the screen sits in front
        of the actual ``send`` to the OS).

        NOTE on what the listener observes: the TCP handshake completes at
        ``connect`` time, so the server's ``accept`` returns and a ``recv`` is
        pending. When ``sendall`` is refused by the screen and the ``finally``
        closes the client socket, the server's ``recv`` returns ``b""`` — the
        standard end-of-stream signal for a peer that closed without sending. So
        the listener sees EITHER nothing (timeout) OR an empty close — never the
        planted secret bytes. The load-bearing assertion is precisely that: the
        secret content did not reach the wire.
        """
        srv, addr, port = _bind_throwaway_listener()
        sink: dict = {}
        client: socket.socket | None = None
        try:
            egress_guard.allow_external_endpoint(addr, port)
            exfil_screen.wire_into_egress_guard()
            egress_guard.arm()
            thread = _serve_one_recv(srv, sink)

            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(_SOCK_TIMEOUT)
            client.connect((addr, port))
            with pytest.raises(egress_guard.EgressTripped):
                client.sendall(_PLANTED_PEM_SECRET)
            # Give the server thread a moment; it must NOT have received the secret.
            thread.join(timeout=1.0)
        finally:
            for sk in (client, srv):
                if sk is not None:
                    sk.close()

        delivered = sink.get("data")
        # The listener received nothing (None) or an empty end-of-stream close
        # (b"") from the refused send + socket close — but NEVER the secret bytes.
        assert not delivered, (
            "block-on-detection: the planted secret must NOT be delivered to the "
            f"listener (the screen refuses the send before the OS); got {delivered!r}"
        )
        assert _PLANTED_PEM_SECRET not in (delivered or b""), (
            "the planted-secret bytes must never reach the listener"
        )


# ===========================================================================
# Proof 4 — A clean payload round-trips: delivered to the listener; no trip.
# ===========================================================================
class TestProof4CleanPayloadRoundTrips:
    """A benign payload to the allowlisted non-loopback endpoint passes the REAL
    wired screen, is DELIVERED to the listener (recv confirms the round-trip over
    the real OS network stack), and does NOT trip the kill-switch.
    """

    def test_clean_payload_delivered_and_does_not_trip(self) -> None:
        srv, addr, port = _bind_throwaway_listener()
        sink: dict = {}
        client: socket.socket | None = None
        try:
            egress_guard.allow_external_endpoint(addr, port)
            exfil_screen.wire_into_egress_guard()  # REAL screen wired + armed
            egress_guard.arm()
            thread = _serve_one_recv(srv, sink)

            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(_SOCK_TIMEOUT)
            client.connect((addr, port))
            assert getattr(client, "_screen_outbound_enabled") is True, (
                "the clean send still travels the screened external path"
            )
            client.sendall(_CLEAN_PAYLOAD)
            thread.join(timeout=_SOCK_TIMEOUT)
        finally:
            for sk in (client, srv):
                if sk is not None:
                    sk.close()

        assert sink.get("data") == _CLEAN_PAYLOAD, (
            "the clean payload MUST round-trip to the listener over the real "
            "(same-host, non-loopback) network path"
        )
        assert egress_guard.is_tripped() is False, "a clean external send must NOT trip"
        assert egress_guard.trip_reason() is None

    def test_clean_then_secret_on_same_endpoint(self) -> None:
        """Realistic sequence on one endpoint: a clean payload is delivered, THEN a
        planted secret on the same socket blocks + trips — proving the screen is
        live on every send, not just the first."""
        srv, addr, port = _bind_throwaway_listener()
        sink: dict = {}
        client: socket.socket | None = None
        try:
            egress_guard.allow_external_endpoint(addr, port)
            exfil_screen.wire_into_egress_guard()
            egress_guard.arm()
            thread = _serve_one_recv(srv, sink)

            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(_SOCK_TIMEOUT)
            client.connect((addr, port))

            # First send is clean — delivered, no trip.
            client.sendall(_CLEAN_PAYLOAD)
            thread.join(timeout=_SOCK_TIMEOUT)
            assert sink.get("data") == _CLEAN_PAYLOAD
            assert egress_guard.is_tripped() is False

            # Second send on the SAME tagged socket carries a secret — blocks + trips.
            with pytest.raises(egress_guard.EgressTripped):
                client.sendall(_PLANTED_PEM_SECRET)
        finally:
            for sk in (client, srv):
                if sk is not None:
                    sk.close()

        assert egress_guard.is_tripped() is True
        assert _PEM_LABEL in (egress_guard.trip_reason() or "")


# ===========================================================================
# Sandbox-mechanism self-check — the discovery + same-host round-trip the four
# proofs rest on actually behaves as documented (a failure here explains a skip).
# ===========================================================================
class TestSandboxMechanism:
    """Lock the harness's own assumptions: the discovered address is non-loopback,
    and a same-host round-trip to it works with the guard DISARMED (the baseline
    the armed proofs build on). This makes a discovery/round-trip problem surface
    as a clear, self-describing failure rather than a confusing proof failure.
    """

    def test_discovered_address_is_non_loopback(self) -> None:
        assert _NON_LOOPBACK_ADDR is not None  # guarded by skipif
        assert not ipaddress.ip_address(_NON_LOOPBACK_ADDR).is_loopback, (
            f"the sandbox endpoint address {_NON_LOOPBACK_ADDR!r} must be non-loopback"
        )

    def test_same_host_round_trip_works_disarmed(self) -> None:
        """With the guard DISARMED, a same-host connect to the non-loopback address
        round-trips (the OS loops it back locally) — the mechanism the armed proofs
        rely on. No external connection is made: the peer is the box's own LAN IP."""
        srv, addr, port = _bind_throwaway_listener()
        sink: dict = {}
        client: socket.socket | None = None
        try:
            assert egress_guard.is_armed() is False, "this baseline runs disarmed"
            thread = _serve_one_recv(srv, sink)
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(_SOCK_TIMEOUT)
            client.connect((addr, port))
            client.sendall(b"sandbox-self-check")
            thread.join(timeout=_SOCK_TIMEOUT)
        finally:
            for sk in (client, srv):
                if sk is not None:
                    sk.close()
        assert sink.get("data") == b"sandbox-self-check", (
            "same-host non-loopback round-trip must work (the sandbox precondition)"
        )
