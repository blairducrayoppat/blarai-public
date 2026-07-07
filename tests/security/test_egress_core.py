"""Egress-core machinery locks — ADR-027 §1/§3 + rule-4 trip seam (Sprint 17, C3 / H-a).

This file locks the STAGED/DORMANT egress machinery that stream H-a (egress-core)
adds to ``shared/security/egress_guard.py``: the allowlist-widening mechanism
(ADR-027 §1), the anomaly auto-trip kill-switch (ADR-027 §3), and the interface
anchor the exfil-screen stream (H-b) integrates against —
``register_screener()`` + ``trip()`` — plus the launcher's arm-time wiring.

WHAT THIS FILE OWNS (and what it deliberately does NOT)
======================================================
H-a owns this file, ``test_egress_guard.py`` (the ADR-020 baseline locks, untouched
here), and the ``trip()``/``register_screener()`` interface. It does NOT own
``test_production_posture.py`` (stream J) or ``test_egress_screen.py`` (stream H-b,
the exfil-screen module + the PA carve-out). The SEAM tests below exercise the
*wiring* end-to-end with a FAKE screener — they do not import or test H-b's real
screen module (which does not exist on this branch; H-a merges first).

STAGED/DORMANT INVARIANT (the load-bearing assertion)
=====================================================
The machinery changes NO external-egress behavior this sprint: the active
allowlist stays loopback + AF_HYPERV, and the live external allowlist is EMPTY.
``test_dormant_baseline_*`` lock that the door stays shut; the widening
*mechanism* works (``test_widening_mechanism_*``) but is not exercised by runtime
code.

ISOLATION
=========
Every test runs under an autouse fixture that fully resets the guard's global
state (disarm + clear screeners + clear arm-hooks + clear allowlist + release the
trip latch) before and after, so no global ``socket`` patch, registered screener,
or trip-state can leak across tests or into the wider suite. The root
``conftest.py`` redirects ``%LOCALAPPDATA%`` etc. — no real user data is touched.
"""

from __future__ import annotations

import socket

import pytest

from shared.security import egress_guard


@pytest.fixture(autouse=True)
def _pristine_guard() -> None:
    """Guarantee a fully-reset egress_guard before AND after every test.

    Resets the entire machinery surface — not just disarm — so a registered
    screener, arm-hook, widened endpoint, or latched trip from one test can never
    bleed into the next (or into the rest of the suite via the process-wide
    ``socket`` patch).
    """

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


# ===========================================================================
# DoD #5 — THE SEAM LOCK (the interface anchor H-b depends on).
#
# CONTRACT (revised for #634 — destination-scoped screening):
#   A registered screener is invoked ONLY for sends on a socket connected to a
#   vetted EXTERNAL-allowlisted endpoint. Internal loopback / AF_HYPERV traffic
#   is NEVER screened — its frames legitimately carry the runtime's own
#   capability JWTs and user PII, which the real exfil screen would flag, tripping
#   the kill-switch on the first internal message (a self-inflicted DoS). With the
#   external allowlist empty (the dormant baseline this sprint) NO socket is ever
#   tagged, so a registered screener is a behavior-free no-op.
#
# 203.0.113.0/24 (RFC 5737 TEST-NET-3) is unroutable, so a real connect to it
# fails at the OS layer and cannot drive a send. To prove the TAGGED-socket
# behaviour deterministically (without network reachability) these tests use a
# real loopback connection and force the per-socket external tag on — exercising
# the exact send/screen path a real external-allowlisted socket would take.
# ===========================================================================
class TestScreenerSeam:
    """A screener registered via register_screener() is invoked on the egress path
    ONLY for an external-allowlisted destination, and a SIMULATED positive
    detection there FIRES trip(). Internal loopback/vsock sends are never screened.
    Exercises the wiring end-to-end — not just imports.
    """

    @staticmethod
    def _external_tagged_client(port: int) -> socket.socket:
        """Connect a client to the loopback listener on ``port``, then force the
        external-screen tag ON, returning the client socket.

        This simulates a socket connected to an external-allowlisted endpoint:
        the bytes still travel over loopback (deterministic, no network needed),
        but ``_screen_outbound_enabled`` is set so the send path screens exactly
        as it would for a real external connection. (A real connect to an RFC-5737
        TEST-NET address fails at the OS layer and cannot drive a send, so the tag
        is set directly to exercise the send/screen path.) The caller closes it.
        """
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2.0)
        client.connect(("127.0.0.1", port))
        # Connecting to loopback does NOT tag (correct — internal). Force the tag
        # on to exercise the external-destination send/screen path deterministically.
        client._screen_outbound_enabled = True  # type: ignore[attr-defined]
        return client

    # --- Internal traffic is NEVER screened (the load-bearing new invariant) ---

    def test_registered_screener_NOT_invoked_on_loopback(self) -> None:
        """A registered screener does NOT fire on an internal loopback send — the
        socket is untagged (loopback is never an external-screen target)."""
        seen: list[bytes] = []

        def fake_screener(payload: bytes):
            seen.append(payload)
            return egress_guard.ScreenResult(detected=True, reason="should-not-fire")

        egress_guard.register_screener(fake_screener)
        egress_guard.arm()

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            conn, _ = srv.accept()
            # A real JWT-shaped token would be flagged by the real screen; on
            # loopback it MUST pass untouched (internal traffic carries these).
            client.sendall(b"eyJhbGciOiJFUzI1NiJ9.eyJzdWIiOiJ4In0.AAAABBBBCCCC")
            assert conn.recv(128).startswith(b"eyJ"), "loopback send must pass"
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()

        assert seen == [], "the screener MUST NOT fire on an internal loopback send"
        assert egress_guard.is_tripped() is False, "internal traffic must not trip"

    def test_loopback_socket_is_not_tagged_for_screening(self) -> None:
        """After a loopback connect the per-socket external-screen flag stays
        False (the mechanism that scopes screening to external destinations)."""
        egress_guard.arm()
        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            conn, _ = srv.accept()
            assert getattr(client, "_screen_outbound_enabled") is False, (
                "a loopback-connected socket must NOT be tagged for screening"
            )
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()

    # --- External-allowlisted destinations ARE screened ---

    def test_clean_payload_to_external_reaches_screener(self) -> None:
        """A clean payload on an external-tagged socket reaches the screener and
        passes (the screener is invoked on the external egress path)."""
        seen: list[bytes] = []

        def fake_screener(payload: bytes):
            seen.append(payload)
            return None  # clean

        egress_guard.register_screener(fake_screener)
        egress_guard.arm()

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = self._external_tagged_client(port)
            conn, _ = srv.accept()
            client.sendall(b"clean-ping")
            assert conn.recv(64) == b"clean-ping", "clean payload must pass through"
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()

        assert seen == [b"clean-ping"], (
            "the screener MUST be invoked on the external egress path"
        )
        assert egress_guard.is_tripped() is False, "a clean payload must not trip"

    def test_detection_on_external_send_fires_trip_and_blocks(self) -> None:
        """A positive detection on an external-tagged send FIRES trip() and the
        send is refused (ADR-027 rule 4 block-on-detection + §3 trip)."""

        def detecting_screener(payload: bytes):
            if b"SECRET" in payload:
                return egress_guard.ScreenResult(detected=True, reason="seam-test marker")
            return None

        egress_guard.register_screener(detecting_screener)
        egress_guard.arm()

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = self._external_tagged_client(port)
            conn, _ = srv.accept()
            with pytest.raises(egress_guard.EgressTripped):
                client.sendall(b"this carries a SECRET")
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()

        assert egress_guard.is_tripped() is True, "a positive detection MUST trip"
        assert egress_guard.trip_reason() is not None
        assert "seam-test marker" in egress_guard.trip_reason()

    def test_bare_bool_detection_on_external_send_fires_trip(self) -> None:
        """A screener may return a bare ``True`` (not a ScreenResult) and still
        block on an external send — the interface accepts ScreenResult | bool | None."""
        egress_guard.register_screener(lambda payload: b"BAD" in payload)
        egress_guard.arm()

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = self._external_tagged_client(port)
            conn, _ = srv.accept()
            with pytest.raises(egress_guard.EgressTripped):
                client.send(b"contains BAD bytes")
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()
        assert egress_guard.is_tripped() is True

    def test_screener_that_raises_on_external_send_fails_closed(self) -> None:
        """A screener that itself raises on an external send must FAIL CLOSED —
        trip + block, never an open door (a broken screen is the most dangerous
        case). NOTE: it still only runs on a tagged (external) socket."""

        def broken_screener(payload: bytes):
            raise RuntimeError("screener bug")

        egress_guard.register_screener(broken_screener)
        egress_guard.arm()

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = self._external_tagged_client(port)
            conn, _ = srv.accept()
            with pytest.raises(egress_guard.EgressTripped):
                client.sendall(b"anything")
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()
        assert egress_guard.is_tripped() is True

    # --- Dormant no-op invariants ---

    def test_no_screener_registered_is_dormant_noop(self) -> None:
        """With no screener registered (the dormant default), loopback sends pass
        untouched — screening adds no behavior until H-b registers one."""
        egress_guard.arm()
        assert egress_guard.registered_screener_count() == 0
        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            conn, _ = srv.accept()
            client.sendall(b"no-screen")
            assert conn.recv(32) == b"no-screen"
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()
        assert egress_guard.is_tripped() is False

    def test_empty_allowlist_never_tags_so_screener_is_noop(self) -> None:
        """The load-bearing dormant invariant: with the external allowlist EMPTY,
        a real loopback connect never tags the socket, so a registered (would-trip)
        screener never fires — even though it is registered and the guard is armed."""
        assert egress_guard.external_allowlist() == frozenset(), "baseline: empty allowlist"
        fired: list[bytes] = []
        egress_guard.register_screener(
            lambda payload: fired.append(payload) or egress_guard.ScreenResult(
                detected=True, reason="must-not-run"
            )
        )
        egress_guard.arm()
        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            conn, _ = srv.accept()
            client.sendall(b"payload-with-no-screen")
            assert conn.recv(64) == b"payload-with-no-screen"
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()
        assert fired == [], "empty allowlist ⇒ no tag ⇒ screener must never fire"
        assert egress_guard.is_tripped() is False


# ===========================================================================
# DoD #5 (cont.) — arm-time hook wiring (the registration seam, no circ import).
# ===========================================================================
class TestArmHookWiring:
    """The arm-hook seam runs registered setup at arm() time — this is how H-b's
    module wires its screener without egress_guard importing it.
    """

    def test_arm_runs_registered_arm_hook(self) -> None:
        """register_arm_hook(cb) -> cb runs at arm() time."""
        calls: list[str] = []
        egress_guard.register_arm_hook(lambda: calls.append("armed"))
        assert calls == [], "hook must NOT run until arm()"
        egress_guard.arm()
        assert calls == ["armed"], "arm() must run the registered arm-hook"

    def test_arm_hook_registers_screener_end_to_end(self) -> None:
        """The realistic H-b shape: an arm-hook calls register_screener(); after
        arm() the screener is active on the egress path. Under the #634 contract
        the screener fires on an EXTERNAL-allowlisted send (internal loopback is
        never screened), so this drives the external-tagged send/screen path."""

        def hb_style_arm_hook() -> None:
            egress_guard.register_screener(
                lambda payload: egress_guard.ScreenResult(detected=True, reason="hook-wired")
                if b"LEAK" in payload
                else None
            )

        egress_guard.register_arm_hook(hb_style_arm_hook)
        egress_guard.arm()
        assert egress_guard.registered_screener_count() == 1, (
            "the arm-hook must have registered its screener at arm() time"
        )

        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = TestScreenerSeam._external_tagged_client(port)
            conn, _ = srv.accept()
            with pytest.raises(egress_guard.EgressTripped):
                client.sendall(b"a LEAK happens here")
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()
        assert egress_guard.is_tripped() is True

    def test_arm_hook_failure_fails_closed(self) -> None:
        """An arm-hook that raises (e.g. the screen module failed to wire) must
        FAIL CLOSED — trip the kill-switch rather than arm with screening absent."""

        def broken_hook() -> None:
            raise RuntimeError("screen wiring failed")

        egress_guard.register_arm_hook(broken_hook)
        egress_guard.arm()
        assert egress_guard.is_tripped() is True, (
            "a failed arm-hook must trip the kill-switch (un-screened egress is an open door)"
        )

    def test_late_registered_hook_runs_immediately_if_already_armed(self) -> None:
        """If a module is imported after arm() (late), registering its hook runs it
        at once so screening still takes effect."""
        egress_guard.arm()
        calls: list[str] = []
        egress_guard.register_arm_hook(lambda: calls.append("late"))
        assert calls == ["late"], "a hook registered post-arm must run immediately"


# ===========================================================================
# DoD #6 — mechanism locks: deny-by-default holds; widening mechanism works but
# the live list is NOT widened; auto-trip cuts egress + needs LA re-arm.
# ===========================================================================
class TestDormantBaseline:
    """The STAGED/DORMANT invariant: external egress stays fully denied; the live
    external allowlist is empty. (Deny-by-default — the door stays shut.)
    """

    def test_live_external_allowlist_is_empty(self) -> None:
        """No external endpoint is widened in this sprint — the dormant baseline."""
        assert egress_guard.external_allowlist() == frozenset(), (
            "the live external allowlist MUST be empty (machinery dormant; "
            "no Kagi or other external endpoint added this sprint)"
        )

    def test_external_connect_still_denied_by_default(self) -> None:
        """Deny-by-default still holds: an external connect is refused (and trips)."""
        egress_guard.arm()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(egress_guard.EgressDenied):
                s.connect(("8.8.8.8", 53))
        finally:
            s.close()

    def test_loopback_and_vsock_still_pass(self) -> None:
        """The baseline allowlist (loopback + AF_HYPERV) is unchanged by the machinery."""
        egress_guard.arm()
        # loopback round-trip
        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            conn, _ = srv.accept()
            client.sendall(b"ping")
            assert conn.recv(4) == b"ping"
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()
        # AF_HYPERV construction permitted (provider may be absent on a dev box)
        try:
            hv = socket.socket(egress_guard.AF_HYPERV, socket.SOCK_STREAM)
            hv.close()
        except egress_guard.EgressDenied:
            pytest.fail("machinery must not deny AF_HYPERV construction")
        except OSError:
            pass  # provider absent — the guard still permitted it


class TestWideningMechanism:
    """DoD #1 — the allowlist-widening mechanism exists and works (one endpoint at
    a time), WITHOUT widening the live runtime list.
    """

    def test_add_external_endpoint_permits_exactly_that_destination(self) -> None:
        """A widened endpoint is permitted; a different external one stays denied."""
        egress_guard.allow_external_endpoint("203.0.113.10", 443)
        egress_guard.arm()
        # The widened endpoint connects (will fail at the OS layer — unreachable —
        # but NOT with EgressDenied, and it must NOT trip the guard).
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        try:
            try:
                s.connect(("203.0.113.10", 443))
            except egress_guard.EgressDenied:
                pytest.fail("a widened endpoint must NOT be denied by the guard")
            except OSError:
                pass  # unreachable / timeout at the OS layer — guard let it through
        finally:
            s.close()
        assert egress_guard.is_tripped() is False, "a widened endpoint must not trip"

        # A DIFFERENT external endpoint is still denied (one at a time).
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(egress_guard.EgressDenied):
                s2.connect(("198.51.100.7", 443))
        finally:
            s2.close()

    def test_add_endpoint_any_port_wildcard(self) -> None:
        """An endpoint added with the any-port wildcard permits any port on it."""
        egress_guard.allow_external_endpoint("203.0.113.20")  # default port == "*"
        egress_guard.arm()
        for port in (80, 443, 8443):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2)
            try:
                try:
                    s.connect(("203.0.113.20", port))
                except egress_guard.EgressDenied:
                    pytest.fail(f"any-port wildcard must permit port {port}")
                except OSError:
                    pass
            finally:
                s.close()
        assert egress_guard.is_tripped() is False

    def test_widening_loopback_is_rejected(self) -> None:
        """The widener is for EXTERNAL endpoints only — loopback is already allowed."""
        with pytest.raises(ValueError):
            egress_guard.allow_external_endpoint("127.0.0.1", 80)
        with pytest.raises(ValueError):
            egress_guard.allow_external_endpoint("localhost", 80)

    def test_widening_requires_nonempty_host(self) -> None:
        with pytest.raises(ValueError):
            egress_guard.allow_external_endpoint("", 443)

    def test_revoke_removes_endpoint(self) -> None:
        """An endpoint can be removed — the door re-closes (one at a time, both ways)."""
        egress_guard.allow_external_endpoint("203.0.113.30", 443)
        assert ("203.0.113.30", "443") in egress_guard.external_allowlist()
        egress_guard.revoke_external_endpoint("203.0.113.30", 443)
        assert ("203.0.113.30", "443") not in egress_guard.external_allowlist()
        egress_guard.arm()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(egress_guard.EgressDenied):
                s.connect(("203.0.113.30", 443))
        finally:
            s.close()


class TestAutoTripAndReArm:
    """DoD #2 — the anomaly auto-trip cuts ALL egress and requires LA re-arm
    (ADR-027 §3: default-off kill-switch, auto-trip on anomaly, LA-only re-arm).
    """

    def test_offlist_connect_auto_trips(self) -> None:
        """An attempt to reach an off-allowlist address auto-trips the kill-switch."""
        egress_guard.arm()
        assert egress_guard.is_tripped() is False, "default-off (not tripped) at arm"
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(egress_guard.EgressDenied):
                s.connect(("8.8.8.8", 53))
        finally:
            s.close()
        assert egress_guard.is_tripped() is True, "off-allowlist attempt must auto-trip"

    def test_external_bind_auto_trips(self) -> None:
        """A non-loopback (externally-reachable) bind auto-trips (ingress stays NONE)."""
        egress_guard.arm()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(egress_guard.EgressDenied):
                s.bind(("0.0.0.0", 0))
        finally:
            s.close()
        assert egress_guard.is_tripped() is True

    def test_trip_cuts_all_egress_including_loopback(self) -> None:
        """After a trip, even the normally-allowed loopback channel is cut."""
        egress_guard.arm()
        egress_guard.trip("manual trip for test")
        assert egress_guard.is_tripped() is True
        # loopback connect now refused with EgressTripped (a subclass of EgressDenied)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(egress_guard.EgressTripped):
                s.connect(("127.0.0.1", 9))
        finally:
            s.close()
        # AF_HYPERV connect also cut
        try:
            hv = socket.socket(egress_guard.AF_HYPERV, socket.SOCK_STREAM)
            with pytest.raises(egress_guard.EgressTripped):
                hv.connect(("anything", 1))
            hv.close()
        except OSError:
            pass  # provider absent; the construction path is exercised elsewhere

    def test_trip_blocks_dns_resolution(self) -> None:
        """After a trip, even loopback DNS resolution is refused."""
        egress_guard.arm()
        egress_guard.trip("manual trip")
        with pytest.raises(egress_guard.EgressTripped):
            socket.getaddrinfo("127.0.0.1", 0)

    def test_egress_stays_cut_until_rearm(self) -> None:
        """Egress stays cut until the LA-only re-arm clears the latch — there is no
        automatic recovery (ADR-027 §3)."""
        egress_guard.arm()
        egress_guard.trip("anomaly")
        assert egress_guard.is_tripped() is True
        # Re-arming is the only way back.
        egress_guard.rearm()
        assert egress_guard.is_tripped() is False
        assert egress_guard.trip_reason() is None
        # Normal allowlist enforcement resumes: loopback works again...
        srv, port = _free_loopback_listener()
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))
            conn, _ = srv.accept()
            client.sendall(b"back")
            assert conn.recv(4) == b"back"
        finally:
            for sk in (conn, client, srv):
                if sk is not None:
                    sk.close()
        # ...but external is still denied (re-arm does not widen the allowlist).
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(egress_guard.EgressDenied):
                s.connect(("8.8.8.8", 53))
        finally:
            s.close()

    def test_trip_is_idempotent_keeps_first_reason(self) -> None:
        """A second trip keeps the original cause (the first anomaly is the story)."""
        egress_guard.trip("first cause")
        egress_guard.trip("second cause")
        assert egress_guard.trip_reason() == "first cause"

    def test_trip_alerts_operator(self, caplog: pytest.LogCaptureFixture) -> None:
        """A trip alerts the operator (CRITICAL log — the dormant-era alert seam)."""
        import logging

        with caplog.at_level(logging.CRITICAL, logger="shared.security.egress_guard"):
            egress_guard.trip("audit-visible reason")
        assert any(
            "KILL-SWITCH TRIPPED" in rec.message and "audit-visible reason" in rec.message
            for rec in caplog.records
        ), "a trip must emit an operator-visible CRITICAL alert"


# ===========================================================================
# Interface-anchor contract — the exact signatures H-b integrates against.
# ===========================================================================
class TestInterfaceAnchorContract:
    """Lock the exact public surface H-b + the Orchestrator integrate against, so a
    rename is caught here rather than at H-b merge time.
    """

    def test_trip_signature(self) -> None:
        import inspect

        sig = inspect.signature(egress_guard.trip)
        params = list(sig.parameters.values())
        assert [p.name for p in params] == ["reason"], "trip(reason: str) -> None"
        assert sig.return_annotation in (None, "None")

    def test_register_screener_signature(self) -> None:
        import inspect

        sig = inspect.signature(egress_guard.register_screener)
        params = list(sig.parameters.values())
        assert [p.name for p in params] == ["screener"], (
            "register_screener(screener) -> None"
        )

    def test_register_screener_rejects_non_callable(self) -> None:
        with pytest.raises(TypeError):
            egress_guard.register_screener("not a callable")  # type: ignore[arg-type]

    def test_screen_result_is_frozen_dataclass(self) -> None:
        """ScreenResult carries (detected, reason) and is immutable — H-b returns it."""
        r = egress_guard.ScreenResult(detected=True, reason="x")
        assert r.detected is True
        assert r.reason == "x"
        with pytest.raises(Exception):
            r.detected = False  # type: ignore[misc]  (frozen)

    def test_register_screener_is_idempotent(self) -> None:
        def s(payload: bytes):
            return None

        egress_guard.register_screener(s)
        egress_guard.register_screener(s)
        assert egress_guard.registered_screener_count() == 1


# ===========================================================================
# DoD #4 — launcher arm-time wiring is live at boot.
# ===========================================================================
class TestLauncherArmWiring:
    """The launcher's _arm_egress_guard() — called at every production boot — wires
    the screener-registration + auto-trip setup at arm() time (ADR-027).
    """

    def test_launcher_arms_guard_even_without_screen_module(self) -> None:
        """_arm_egress_guard() arms the baseline guard whether or not H-b's
        exfil-screen module is present (it fails toward the MORE restrictive
        posture — the air-gap baseline is the load-bearing control)."""
        from launcher.__main__ import _arm_egress_guard

        assert egress_guard.is_armed() is False
        _arm_egress_guard()
        try:
            assert egress_guard.is_armed() is True, (
                "the launcher must arm the egress guard at boot"
            )
            # Baseline enforcement is live: external egress denied.
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                with pytest.raises(egress_guard.EgressDenied):
                    s.connect(("8.8.8.8", 53))
            finally:
                s.close()
        finally:
            egress_guard.disarm()

    def test_launcher_runs_arm_hooks_so_a_screen_module_would_wire(self) -> None:
        """The launcher path runs arm-hooks — proven by registering a hook before
        the launcher arms and confirming it fired. This is the exact seam H-b's
        module uses (import -> register_arm_hook -> wired at arm())."""
        from launcher.__main__ import _arm_egress_guard

        fired: list[str] = []
        egress_guard.register_arm_hook(lambda: fired.append("wired"))
        _arm_egress_guard()
        try:
            assert fired == ["wired"], (
                "the launcher's arm path must run arm-hooks (the screener-wiring seam)"
            )
        finally:
            egress_guard.disarm()


# ===========================================================================
# Blast-radius — the machinery does not widen the guard's surface.
# ===========================================================================
class TestBlastRadiusUnchanged:
    def test_guard_still_rebinds_only_two_socket_symbols(self) -> None:
        """The ADR-027 machinery must NOT widen the guard's blast radius: arming
        still rebinds exactly socket.socket + socket.getaddrinfo (the named-pipe /
        all non-socket surfaces stay untouched)."""
        names = [n for n in dir(socket) if not n.startswith("__")]
        before = {n: getattr(socket, n) for n in names}
        egress_guard.arm()
        changed = {n for n in names if getattr(socket, n) is not before[n]}
        assert changed == {"socket", "getaddrinfo"}, (
            f"machinery widened the blast radius: {changed}"
        )

    def test_egress_tripped_is_egress_denied_is_oserror(self) -> None:
        """EgressTripped degrades through the same fail-closed except-OSError paths."""
        assert issubclass(egress_guard.EgressTripped, egress_guard.EgressDenied)
        assert issubclass(egress_guard.EgressTripped, OSError)
