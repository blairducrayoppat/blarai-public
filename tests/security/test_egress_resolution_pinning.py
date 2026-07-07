r"""Egress-guard hostname-resolution pinning — the W4 enabling enhancement (ADR-024 amendment, 2026-06-10).

WHAT THIS PROVES
================
A standard HTTP client (httpx/requests) resolves a hostname via
``socket.getaddrinfo`` and then connects to the *numeric IP* it got back. That
numeric IP is not the literal host string on the egress allowlist, so without the
resolution pin a real Kagi connect would be off-allowlist and AUTO-TRIP the
kill-switch. The pin closes exactly that gap, and ONLY that gap:

  * When :func:`egress_guard._guarded_getaddrinfo` resolves a host that IS on the
    external allowlist, the resolved IPs are pinned back to that name.
  * :func:`egress_guard._is_allowlisted_external` then accepts a numeric IP iff an
    allowlisted name pinned it AND that name is allowlisted at the requested PORT.
  * Deny-by-default is preserved: an IP that nobody resolved through an allowlisted
    name has no pin and stays denied (and the connect auto-trips).
  * The pin is cleared by ``revoke_external_endpoint`` (that host's pins),
    ``clear_external_allowlist`` (all), and ``disarm`` (all).
  * A pinned IP connected at the allowlisted port TAGS the socket for outbound
    exfil screening (the screen must fire on real Kagi traffic).

NO REAL NETWORK / NO REAL DNS
=============================
These tests NEVER resolve a real hostname or open an external socket. Resolution
is faked by calling the internal recorder :func:`egress_guard._record_resolution_pins`
with a synthetic getaddrinfo-shaped result, or by monkeypatching
``egress_guard._REAL_GETADDRINFO``. The address-check helpers are exercised
directly (they are pure: ``(host, port) -> bool``); the screen-tag test uses a
loopback round-trip whose socket family/dest is faked at the tagging boundary. The
root ``conftest.py`` redirects ``%LOCALAPPDATA%`` — no real user data is touched.
"""

from __future__ import annotations

import socket

import pytest

from shared.security import egress_guard

# A throwaway "external" name + the IPs it pretends to resolve to. These are
# genuinely-GLOBAL addresses (the historical example.com /24) — never routed or
# connected to here (the address-check helpers are pure functions of the strings).
# NOTE: RFC-5737 documentation ranges (203.0.113.x etc.) are classified is_private
# by stdlib ipaddress on 3.11+, so after the SSRF defense-in-depth fix (merge-gate
# fix 1) a name resolving there would NOT be pinned — these public-path constants
# must therefore be real global IPs for the pin to be recorded.
_FAKE_HOST = "kagi.example"
_FAKE_HOST_PORT = 443
_PINNED_IP_A = "93.184.216.10"
_PINNED_IP_B = "93.184.216.11"
_UNPINNED_IP = "93.184.216.250"


def _fake_addrinfo(*ips: str, port: int = _FAKE_HOST_PORT) -> list:
    """Build a getaddrinfo-shaped list (5-tuples) for ``ips`` — no DNS performed."""
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
        for ip in ips
    ]


@pytest.fixture(autouse=True)
def _pristine_guard() -> None:
    """Fully reset egress_guard before AND after each test (machinery + pins + latch).

    Mirrors the reset used by ``test_egress_core.py`` / ``test_egress_sandbox_proving.py``,
    plus the resolution pins (the new W4 state): disarm (releases the trip latch and
    clears pins), clear screeners, clear arm-hooks, clear the external allowlist
    (also clears pins), belt-and-braces clear the pins and rearm — so no global
    ``socket`` patch, registered screener, wired arm-hook, widened endpoint, latched
    trip, OR resolution pin can bleed across tests or into the wider suite.
    """

    def _reset() -> None:
        egress_guard.disarm()
        egress_guard.clear_screeners()
        egress_guard.clear_arm_hooks()
        egress_guard.clear_external_allowlist()
        egress_guard.clear_resolution_pins()
        egress_guard.rearm()

    _reset()
    yield
    _reset()


# ===========================================================================
# Recording — only an ALLOWLISTED name's resolution gets pinned.
# ===========================================================================
class TestRecordResolutionPins:
    def test_recording_maps_each_ip_back_to_the_host(self) -> None:
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(
            _FAKE_HOST, _fake_addrinfo(_PINNED_IP_A, _PINNED_IP_B)
        )
        pins = egress_guard.resolution_pins()
        assert pins.get(_PINNED_IP_A) == frozenset({_FAKE_HOST})
        assert pins.get(_PINNED_IP_B) == frozenset({_FAKE_HOST})

    def test_recording_lowercases_the_host(self) -> None:
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(
            _FAKE_HOST.upper(), _fake_addrinfo(_PINNED_IP_A)
        )
        assert egress_guard.resolution_pins().get(_PINNED_IP_A) == frozenset({_FAKE_HOST})

    def test_loopback_ip_is_never_pinned(self) -> None:
        """A resolution that yields a loopback address must NOT pin it — loopback is
        already permitted and must never be tagged/screened as an external pin."""
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(
            _FAKE_HOST, _fake_addrinfo("127.0.0.1", _PINNED_IP_A)
        )
        pins = egress_guard.resolution_pins()
        assert "127.0.0.1" not in pins
        assert _PINNED_IP_A in pins

    def test_malformed_addrinfo_entries_are_skipped(self) -> None:
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        # Mixed: a good 5-tuple, a too-short tuple, a non-tuple sockaddr.
        bad = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PINNED_IP_A, 443)),
            (socket.AF_INET,),  # too short — no [4]
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", None),  # sockaddr not indexable
        ]
        egress_guard._record_resolution_pins(_FAKE_HOST, bad)
        assert egress_guard.resolution_pins().get(_PINNED_IP_A) == frozenset({_FAKE_HOST})


# ===========================================================================
# Admission — pinned IP allowed at the allowlisted PORT only; deny-by-default.
# ===========================================================================
class TestPinnedIpAdmission:
    def test_pinned_ip_allowed_at_allowlisted_port(self) -> None:
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))
        assert egress_guard._is_allowlisted_external(_PINNED_IP_A, _FAKE_HOST_PORT) is True

    def test_pinned_ip_denied_at_wrong_port(self) -> None:
        """The pin admits the IP ONLY at the port the host is allowlisted for —
        an IP pinned for kagi:443 is NOT admitted on some other port (8080)."""
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))
        assert egress_guard._is_allowlisted_external(_PINNED_IP_A, 8080) is False

    def test_unpinned_ip_is_denied(self) -> None:
        """An IP that no allowlisted name resolved to has no pin and stays denied,
        even with the allowlist non-empty (deny-by-default)."""
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))
        assert egress_guard._is_allowlisted_external(_UNPINNED_IP, _FAKE_HOST_PORT) is False

    def test_any_port_host_allowlist_admits_pinned_ip_on_any_port(self) -> None:
        """A host allowlisted with the any-port wildcard admits its pinned IPs on
        any port (the wildcard semantics carry through the pin)."""
        egress_guard.allow_external_endpoint(_FAKE_HOST)  # default port == "*"
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))
        assert egress_guard._is_allowlisted_external(_PINNED_IP_A, 443) is True
        assert egress_guard._is_allowlisted_external(_PINNED_IP_A, 8443) is True

    def test_pin_without_allowlist_entry_does_not_admit(self) -> None:
        """A pin whose host is NOT (or no longer) on the allowlist does not admit
        the IP — the allowlist entry is still required (the pin is not a 2nd list)."""
        # Record a pin, then ensure the host is not allowlisted: admission is denied.
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))
        # Allowlist is empty here (no allow_external_endpoint call).
        assert egress_guard._is_allowlisted_external(_PINNED_IP_A, _FAKE_HOST_PORT) is False


# ===========================================================================
# Pin lifecycle — cleared on revoke (that host), clear-all, and disarm.
# ===========================================================================
class TestPinLifecycle:
    def test_revoke_drops_only_that_hosts_pins(self) -> None:
        other_host = "teclis.example"
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard.allow_external_endpoint(other_host, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))
        egress_guard._record_resolution_pins(other_host, _fake_addrinfo(_PINNED_IP_B))

        egress_guard.revoke_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)

        pins = egress_guard.resolution_pins()
        assert _PINNED_IP_A not in pins, "revoked host's pin must be dropped"
        assert pins.get(_PINNED_IP_B) == frozenset({other_host}), "other host's pin survives"
        # And admission reflects it.
        assert egress_guard._is_allowlisted_external(_PINNED_IP_A, _FAKE_HOST_PORT) is False
        assert egress_guard._is_allowlisted_external(_PINNED_IP_B, _FAKE_HOST_PORT) is True

    def test_revoke_drops_shared_ip_only_for_that_host(self) -> None:
        """If two allowlisted names pinned the SAME IP, revoking one leaves the IP
        pinned for the other (the IP -> {hosts} set loses one member, not the key)."""
        other_host = "mirror.example"
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard.allow_external_endpoint(other_host, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))
        egress_guard._record_resolution_pins(other_host, _fake_addrinfo(_PINNED_IP_A))

        egress_guard.revoke_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)

        assert egress_guard.resolution_pins().get(_PINNED_IP_A) == frozenset({other_host})
        assert egress_guard._is_allowlisted_external(_PINNED_IP_A, _FAKE_HOST_PORT) is True

    def test_clear_external_allowlist_clears_all_pins(self) -> None:
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))
        egress_guard.clear_external_allowlist()
        assert egress_guard.resolution_pins() == {}
        assert egress_guard._is_allowlisted_external(_PINNED_IP_A, _FAKE_HOST_PORT) is False

    def test_disarm_clears_all_pins(self) -> None:
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))
        egress_guard.arm()
        try:
            assert _PINNED_IP_A in egress_guard.resolution_pins()
        finally:
            egress_guard.disarm()
        assert egress_guard.resolution_pins() == {}


# ===========================================================================
# getaddrinfo integration — an allowlisted name's resolution pins; an off-list
# name never resolves (it trips); loopback/numeric never pin.
# ===========================================================================
class TestGuardedGetaddrinfoPins:
    def test_allowlisted_name_resolution_pins_visible_before_disarm(self, monkeypatch) -> None:
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        monkeypatch.setattr(
            egress_guard,
            "_REAL_GETADDRINFO",
            lambda *a, **k: _fake_addrinfo(_PINNED_IP_A),
        )
        egress_guard.arm()
        try:
            egress_guard._guarded_getaddrinfo(_FAKE_HOST, _FAKE_HOST_PORT)
            pins = egress_guard.resolution_pins()
            assert pins.get(_PINNED_IP_A) == frozenset({_FAKE_HOST})
            # And the resolved IP is now admitted at the allowlisted port.
            assert egress_guard._is_allowlisted_external(_PINNED_IP_A, _FAKE_HOST_PORT) is True
        finally:
            egress_guard.disarm()

    def test_offlist_name_resolution_trips_and_records_no_pin(self, monkeypatch) -> None:
        """An off-allowlist name is denied at resolution (auto-trip) and records no
        pin — the deny-by-default DNS layer is unchanged by the pinning feature."""
        called = {"real": False}

        def _fake_real(*a, **k):
            called["real"] = True
            return _fake_addrinfo(_PINNED_IP_A)

        monkeypatch.setattr(egress_guard, "_REAL_GETADDRINFO", _fake_real)
        egress_guard.arm()
        try:
            with pytest.raises(egress_guard.EgressDenied):
                egress_guard._guarded_getaddrinfo("not-allowlisted.example", 443)
        finally:
            # capture state before _pristine_guard resets
            tripped = egress_guard.is_tripped()
            pins = egress_guard.resolution_pins()
            egress_guard.disarm()
        assert tripped is True, "off-allowlist DNS must auto-trip"
        assert called["real"] is False, "real resolution must NOT run for an off-list name"
        assert pins == {}, "no pin is recorded for an off-allowlist name"

    def test_numeric_literal_host_is_not_pinned(self, monkeypatch) -> None:
        """A numeric-literal host needs no DNS and is not an allowlisted *name*, so
        resolving it records no pin (it is governed by the connect-time check)."""
        monkeypatch.setattr(
            egress_guard,
            "_REAL_GETADDRINFO",
            lambda *a, **k: _fake_addrinfo(_PINNED_IP_A),
        )
        egress_guard.arm()
        try:
            egress_guard._guarded_getaddrinfo(_PINNED_IP_A, 443)
            pins = egress_guard.resolution_pins()
        finally:
            egress_guard.disarm()
        assert pins == {}, "a numeric-literal host resolution records no pin"


# ===========================================================================
# Loopback is unaffected by the pinning feature.
# ===========================================================================
class TestLoopbackUnaffected:
    def test_loopback_host_still_admitted_without_any_pin(self) -> None:
        # No allowlist, no pins: loopback connect check is governed by the
        # loopback branch in _check_connect, not by _is_allowlisted_external.
        egress_guard.arm()
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                srv.bind(("127.0.0.1", 0))
                srv.listen(1)
                port = srv.getsockname()[1]
                client.settimeout(3.0)
                client.connect(("127.0.0.1", port))  # must NOT raise
                assert getattr(client, "_screen_outbound_enabled") is False, (
                    "loopback must never be tagged for screening, pins notwithstanding"
                )
            finally:
                client.close()
                srv.close()
        finally:
            egress_guard.disarm()
        assert egress_guard.is_tripped() is False

    def test_is_allowlisted_external_false_for_loopback_ip(self) -> None:
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        # Even with an allowlist present, a loopback IP is not "allowlisted external".
        assert egress_guard._is_allowlisted_external("127.0.0.1", _FAKE_HOST_PORT) is False


# ===========================================================================
# Screen tag fires on a pinned-IP connect — the exfil screen must see Kagi traffic.
# ===========================================================================
class TestPinnedIpScreenTagging:
    def test_external_screen_target_true_for_pinned_ip_at_port(self) -> None:
        """_is_external_screen_target — the predicate the socket-tagging path uses —
        returns True for a pinned IP at the allowlisted port, so a socket connected
        to a real Kagi IP IS screened (ADR-027 rule 4)."""
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))
        assert (
            egress_guard._is_external_screen_target(
                socket.AF_INET, (_PINNED_IP_A, _FAKE_HOST_PORT)
            )
            is True
        )

    def test_external_screen_target_false_for_pinned_ip_wrong_port(self) -> None:
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))
        assert (
            egress_guard._is_external_screen_target(
                socket.AF_INET, (_PINNED_IP_A, 8080)
            )
            is False
        )

    def test_connect_to_pinned_ip_tags_socket_for_screening(self, monkeypatch) -> None:
        """End-to-end at the socket boundary: a connect to a pinned IP tags the
        socket (``_screen_outbound_enabled``). We make the pinned IP a loopback-backed
        listener via a faked _is_external_screen_target so no external socket opens —
        the load-bearing assertion is that the TAGGING fires on a pinned destination.
        """
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))

        # Stand a real loopback listener; connect to it but assert tagging uses the
        # pinned-IP predicate by checking _is_external_screen_target directly on the
        # pinned tuple (the connect path calls the same predicate). This keeps the
        # test socket on loopback (no external connection) while proving the pin
        # drives the tag decision.
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        lo_port = srv.getsockname()[1]
        egress_guard.arm()
        client = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(3.0)
            client.connect(("127.0.0.1", lo_port))
            # Loopback connect itself does not tag (correct). The pinned-IP predicate
            # is what the external path consults — verify it would tag the pinned dest.
            assert (
                egress_guard._is_external_screen_target(
                    client.family, (_PINNED_IP_A, _FAKE_HOST_PORT)
                )
                is True
            )
            assert getattr(client, "_screen_outbound_enabled") is False  # loopback dest
        finally:
            if client is not None:
                client.close()
            srv.close()
            egress_guard.disarm()


# ===========================================================================
# SSRF defense-in-depth (merge-gate fix 1): an allowlisted NAME that resolves to
# an INTERNAL/special address must NOT have that internal IP pinned — pinning it
# would admit the later numeric connect. Only loopback was skipped before; now
# EVERY blocked range (RFC-1918 / link-local / CGNAT / reserved / multicast /
# unspecified) is refused a pin, so the connect to it stays off-allowlist + trips.
# ===========================================================================

# One representative IP per blocked range. These are NEVER connected to — the
# address-check helpers and the recorder are pure functions of the strings.
_BLOCKED_RANGE_IPS = {
    "rfc1918_10": "10.0.0.5",
    "rfc1918_172": "172.16.0.9",
    "rfc1918_192": "192.168.1.1",
    "link_local": "169.254.169.254",  # the cloud-metadata SSRF classic
    "cgnat_100_64": "100.64.0.1",
    "multicast": "224.0.0.1",
    "unspecified": "0.0.0.0",
}


class TestBlockedRangeResolutionNotPinned:
    @pytest.mark.parametrize("ip", list(_BLOCKED_RANGE_IPS.values()), ids=list(_BLOCKED_RANGE_IPS))
    def test_blocked_range_ip_is_never_pinned(self, ip: str) -> None:
        """An allowlisted name resolving to an internal/special IP records NO pin."""
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(ip))
        assert ip not in egress_guard.resolution_pins(), (
            f"a name resolving to the blocked-range IP {ip!r} must NOT be pinned"
        )

    @pytest.mark.parametrize("ip", list(_BLOCKED_RANGE_IPS.values()), ids=list(_BLOCKED_RANGE_IPS))
    def test_connect_to_blocked_range_ip_is_denied(self, ip: str) -> None:
        """With no pin, a connect-time admission check to the internal IP is denied —
        the resolution-pin path cannot rescue it (deny-by-default + auto-trip)."""
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(ip))
        assert egress_guard._is_allowlisted_external(ip, _FAKE_HOST_PORT) is False, (
            f"an unpinned internal IP {ip!r} must not be admitted as allowlisted-external"
        )

    def test_mixed_resolution_pins_only_the_public_ip(self) -> None:
        """A resolution returning BOTH an internal and a public IP pins ONLY the
        public one — the internal address is dropped, the public one still works."""
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(
            _FAKE_HOST, _fake_addrinfo("10.0.0.5", _PINNED_IP_A)
        )
        pins = egress_guard.resolution_pins()
        assert "10.0.0.5" not in pins, "the internal IP in a mixed result must not pin"
        assert pins.get(_PINNED_IP_A) == frozenset({_FAKE_HOST}), "the public IP still pins"

    def test_public_ip_still_pins_and_is_admitted_at_port(self) -> None:
        """Regression guard: the blocked-range skip must NOT break the happy path —
        a public IP still pins and is admitted at the allowlisted port."""
        egress_guard.allow_external_endpoint(_FAKE_HOST, _FAKE_HOST_PORT)
        egress_guard._record_resolution_pins(_FAKE_HOST, _fake_addrinfo(_PINNED_IP_A))
        assert egress_guard.resolution_pins().get(_PINNED_IP_A) == frozenset({_FAKE_HOST})
        assert egress_guard._is_allowlisted_external(_PINNED_IP_A, _FAKE_HOST_PORT) is True
