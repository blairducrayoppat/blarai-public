"""Tests for the code-enforced egress kill-switch (shared/security/egress_guard.py, ADR-020).

The guard is a process-wide, fail-closed allowlist: loopback (127.0.0.1/::1) and
AF_HYPERV are permitted; every other outbound socket is refused. These tests prove
*both* halves of the contract:

  - external egress is blocked (connect, bind, DNS, disallowed family), AND
  - the legitimate local channels still pass (loopback TCP round-trip, the
    socketpair asyncio relies on, AF_HYPERV construction, loopback DNS).

Every test runs under an autouse fixture that disarms the guard afterwards, so the
global ``socket.socket`` patch can never leak into the wider suite.
"""

from __future__ import annotations

import socket

import pytest

from shared.security import egress_guard


@pytest.fixture(autouse=True)
def _ensure_disarmed() -> None:
    """Guarantee a clean, disarmed socket surface before and after every test."""
    egress_guard.disarm()
    yield
    egress_guard.disarm()


# ---------------------------------------------------------------------------
# DENY side — external egress is refused.
# ---------------------------------------------------------------------------
class TestEgressDenied:
    def test_external_ipv4_connect_denied(self) -> None:
        egress_guard.arm()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(egress_guard.EgressDenied):
                s.connect(("8.8.8.8", 53))
        finally:
            s.close()

    def test_external_hostname_connect_denied(self) -> None:
        egress_guard.arm()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(egress_guard.EgressDenied):
                s.connect(("example.com", 80))
        finally:
            s.close()

    def test_wildcard_and_external_bind_denied(self) -> None:
        egress_guard.arm()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(egress_guard.EgressDenied):
                s.bind(("0.0.0.0", 0))  # wildcard -> externally reachable
            with pytest.raises(egress_guard.EgressDenied):
                s.bind(("", 0))  # INADDR_ANY wildcard
            with pytest.raises(egress_guard.EgressDenied):
                s.bind(("10.255.255.1", 0))  # non-loopback
        finally:
            s.close()

    def test_disallowed_family_denied_at_construction(self) -> None:
        # Pick an address family guaranteed NOT on the allowlist (prefer the
        # meaningful AF_UNIX; fall back so this never skips on a build that lacks
        # it). The guard rejects it before the OS ever sees the family.
        candidates = [
            getattr(socket, "AF_UNIX", None),
            getattr(socket, "AF_BLUETOOTH", None),
            getattr(socket, "AF_IPX", None),
            255,
        ]
        disallowed = next(
            int(f)
            for f in candidates
            if f is not None and int(f) not in egress_guard._ALLOWED_FAMILIES
        )
        egress_guard.arm()
        with pytest.raises(egress_guard.EgressDenied):
            socket.socket(disallowed, socket.SOCK_STREAM)

    def test_external_dns_resolution_denied(self) -> None:
        egress_guard.arm()
        with pytest.raises(egress_guard.EgressDenied):
            socket.getaddrinfo("example.com", 80)

    def test_create_connection_external_denied(self) -> None:
        egress_guard.arm()
        with pytest.raises(egress_guard.EgressDenied):
            socket.create_connection(("8.8.8.8", 53), timeout=2.0)

    def test_udp_sendto_external_denied(self) -> None:
        egress_guard.arm()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            with pytest.raises(egress_guard.EgressDenied):
                s.sendto(b"x", ("8.8.8.8", 53))
        finally:
            s.close()


# ---------------------------------------------------------------------------
# ALLOW side — the legitimate local channels keep working.
# ---------------------------------------------------------------------------
class TestLocalChannelsPass:
    def test_loopback_tcp_roundtrip_allowed(self) -> None:
        """A real 127.0.0.1 listen+connect+send round-trip under the armed guard."""
        egress_guard.arm()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client: socket.socket | None = None
        conn: socket.socket | None = None
        try:
            server.bind(("127.0.0.1", 0))  # loopback bind allowed
            server.listen(1)
            port = server.getsockname()[1]
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", port))  # loopback connect allowed
            conn, _ = server.accept()
            client.sendall(b"ping")
            assert conn.recv(4) == b"ping"
        finally:
            for sk in (conn, client, server):
                if sk is not None:
                    sk.close()

    def test_socketpair_allowed(self) -> None:
        """asyncio's Windows self-pipe uses socketpair() over loopback — must pass."""
        egress_guard.arm()
        a, b = socket.socketpair()
        try:
            a.sendall(b"x")
            assert b.recv(1) == b"x"
        finally:
            a.close()
            b.close()

    def test_afhyperv_construction_not_denied(self) -> None:
        """The guard must permit AF_HYPERV; only hardware/provider absence may fail."""
        egress_guard.arm()
        try:
            s = socket.socket(egress_guard.AF_HYPERV, socket.SOCK_STREAM)
            s.close()
        except egress_guard.EgressDenied:
            pytest.fail("egress guard wrongly denied AF_HYPERV construction")
        except OSError:
            pass  # Hyper-V socket provider absent — the guard still permitted it

    def test_loopback_dns_allowed(self) -> None:
        egress_guard.arm()
        assert socket.getaddrinfo("127.0.0.1", 0)  # numeric loopback
        assert socket.getaddrinfo("localhost", 0)  # loopback name, no external DNS


# ---------------------------------------------------------------------------
# Mechanics — arm/disarm lifecycle and blast radius.
# ---------------------------------------------------------------------------
class TestGuardMechanics:
    def test_not_armed_on_import(self) -> None:
        # Importing the module has no side effects; the autouse fixture leaves it
        # disarmed. A plain external socket *object* constructs fine when disarmed.
        assert egress_guard.is_armed() is False
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.close()

    def test_arm_is_idempotent(self) -> None:
        original = socket.socket
        egress_guard.arm()
        patched = socket.socket
        egress_guard.arm()  # second arm is a no-op
        assert socket.socket is patched
        assert egress_guard.is_armed() is True
        egress_guard.disarm()
        assert socket.socket is original

    def test_disarm_restores_socket_and_getaddrinfo(self) -> None:
        original_socket = socket.socket
        original_gai = socket.getaddrinfo
        egress_guard.arm()
        assert socket.socket is not original_socket
        assert socket.getaddrinfo is not original_gai
        egress_guard.disarm()
        assert socket.socket is original_socket
        assert socket.getaddrinfo is original_gai
        assert egress_guard.is_armed() is False

    def test_egress_denied_is_oserror(self) -> None:
        # vsock's `except OSError` must catch a denial -> degrade to fail-closed.
        assert issubclass(egress_guard.EgressDenied, OSError)

    def test_guard_scope_is_sockets_only(self) -> None:
        """Arming rebinds exactly two socket symbols — nothing else.

        Proves the named pipe (win32 kernel object) and all non-socket surfaces are
        untouched by the guard: its entire blast radius is socket.socket +
        socket.getaddrinfo.
        """
        names = [n for n in dir(socket) if not n.startswith("__")]
        before = {n: getattr(socket, n) for n in names}
        egress_guard.arm()
        changed = {n for n in names if getattr(socket, n) is not before[n]}
        assert changed == {"socket", "getaddrinfo"}
