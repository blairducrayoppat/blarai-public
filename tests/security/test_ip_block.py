r"""Canonical blocked-IP predicate — the ONE SSRF range check both doors share.

Vikunja #802 / AUDIT-3. :func:`shared.security.ip_block.is_blocked_ip` is the single
source of truth that :mod:`shared.security.egress_guard` (the pin side) and
:mod:`shared.security.guarded_fetch` (the fetch side) both delegate to. Before the
consolidation each door carried its own identical copy; this suite proves (a) the
canonical predicate covers every documented range with its RFC, and (b) the two
per-site wrappers still exist, keep their names/signatures, and delegate to the
canonical one — so the two doors can never silently diverge (the exact bug this
ticket exists to prevent).

NO REAL NETWORK / NO REAL DNS. Every case is a pure ``ip_address``-object (or a
deliberately-malformed object) fed to a pure predicate — no socket, no resolution.
The root ``conftest.py`` redirects ``%LOCALAPPDATA%``; no user data is touched.
"""

from __future__ import annotations

import ipaddress

import pytest

from shared.security import egress_guard, guarded_fetch, ip_block

# ---------------------------------------------------------------------------
# The blocked corpus — one (or more) representative address per documented range,
# each tagged with the range + RFC it exercises. EVERY entry MUST block.
# ---------------------------------------------------------------------------
BLOCKED_IPV4 = {
    "unspecified_0.0.0.0": "0.0.0.0",             # 0.0.0.0            RFC 5735 (is_unspecified)
    "this_network_0/8": "0.1.2.3",                # 0.0.0.0/8          RFC 1122 (is_private)
    "rfc1918_10/8": "10.0.0.5",                   # 10.0.0.0/8         RFC 1918
    "rfc1918_10_broadcast": "10.255.255.255",     # 10.0.0.0/8 edge    RFC 1918
    "cgnat_100.64_low": "100.64.0.0",             # 100.64.0.0/10 low  RFC 6598 (EXPLICIT)
    "cgnat_100.64_mid": "100.64.0.1",             # 100.64.0.0/10      RFC 6598 (EXPLICIT)
    "cgnat_100.64_high": "100.127.255.255",       # 100.64.0.0/10 high RFC 6598 (EXPLICIT)
    "loopback_127/8": "127.0.0.1",                # 127.0.0.0/8        RFC 1122 (is_loopback)
    "link_local_metadata": "169.254.169.254",     # 169.254.0.0/16     RFC 3927 (cloud-metadata SSRF)
    "rfc1918_172/12_low": "172.16.0.9",           # 172.16.0.0/12      RFC 1918
    "rfc1918_172/12_high": "172.31.255.255",      # 172.16.0.0/12 edge RFC 1918
    "ietf_protocol_192.0.0/24": "192.0.0.1",      # 192.0.0.0/24       RFC 6890 (is_private)
    "testnet1_192.0.2/24": "192.0.2.1",           # 192.0.2.0/24       RFC 5737 (is_private)
    "rfc1918_192.168/16": "192.168.1.1",          # 192.168.0.0/16     RFC 1918
    "benchmark_198.18/15": "198.18.0.1",          # 198.18.0.0/15      RFC 2544 (is_private)
    "testnet2_198.51.100/24": "198.51.100.1",     # 198.51.100.0/24    RFC 5737 (is_private)
    "testnet3_203.0.113/24": "203.0.113.1",       # 203.0.113.0/24     RFC 5737 (is_private)
    "multicast_224/4": "224.0.0.1",               # 224.0.0.0/4        RFC 5771 (is_multicast)
    "reserved_240/4": "240.0.0.1",                # 240.0.0.0/4        RFC 1112 (is_reserved)
    "broadcast_255": "255.255.255.255",           # 255.255.255.255/32 RFC 8190 (is_private)
}

BLOCKED_IPV6 = {
    "unspecified_::": "::",                        # ::/128            RFC 4291 (is_unspecified)
    "loopback_::1": "::1",                          # ::1/128           RFC 4291 (is_loopback)
    "ipv4_mapped": "::ffff:10.0.0.1",              # ::ffff:0:0/96     RFC 4291 (is_private)
    "documentation_2001_db8": "2001:db8::1",       # 2001:db8::/32     RFC 3849 (is_private)
    "ula_fc00": "fc00::1",                          # fc00::/7          RFC 4193 (is_private)
    "ula_fd00": "fd00::1",                          # fc00::/7          RFC 4193 (is_private)
    "link_local_fe80": "fe80::1",                  # fe80::/10         RFC 4291 (is_link_local)
    "multicast_ff02": "ff02::1",                   # ff00::/8          RFC 4291 (is_multicast)
}

# Ordinary public global-unicast addresses — EVERY entry MUST be permitted (False).
# Includes the two CGNAT boundary publics: one address BELOW 100.64.0.0 and one
# ABOVE 100.127.255.255, which the explicit /10 bit-check must NOT over-block.
PUBLIC_IPS = {
    "google_dns_v4": "8.8.8.8",
    "cloudflare_dns_v4": "1.1.1.1",
    "example_v4": "93.184.216.34",
    "cgnat_boundary_below": "100.63.255.255",      # one below 100.64.0.0 — public
    "cgnat_boundary_above": "100.128.0.0",         # one above 100.127.255.255 — public
    "cloudflare_dns_v6": "2606:4700:4700::1111",
}


# ===========================================================================
# The canonical predicate — every documented range blocks; every public IP passes.
# ===========================================================================
class TestCanonicalIsBlockedIp:
    @pytest.mark.parametrize("ip", list(BLOCKED_IPV4.values()), ids=list(BLOCKED_IPV4))
    def test_blocked_ipv4_ranges_are_blocked(self, ip: str) -> None:
        assert ip_block.is_blocked_ip(ipaddress.ip_address(ip)) is True, (
            f"{ip!r} is in a documented blocked IPv4 range and must be blocked"
        )

    @pytest.mark.parametrize("ip", list(BLOCKED_IPV6.values()), ids=list(BLOCKED_IPV6))
    def test_blocked_ipv6_ranges_are_blocked(self, ip: str) -> None:
        assert ip_block.is_blocked_ip(ipaddress.ip_address(ip)) is True, (
            f"{ip!r} is in a documented blocked IPv6 range and must be blocked"
        )

    @pytest.mark.parametrize("ip", list(PUBLIC_IPS.values()), ids=list(PUBLIC_IPS))
    def test_public_ips_are_permitted(self, ip: str) -> None:
        assert ip_block.is_blocked_ip(ipaddress.ip_address(ip)) is False, (
            f"{ip!r} is an ordinary public address and must NOT be blocked"
        )


# ===========================================================================
# CGNAT 100.64.0.0/10 (RFC 6598) — the ONE range stdlib does not flag, so its
# boundary correctness is proven exactly (the /10 bit-check must cover the whole
# block and nothing outside it).
# ===========================================================================
class TestCgnatBoundary:
    @pytest.mark.parametrize(
        "ip,blocked",
        [
            ("100.63.255.255", False),  # last address BEFORE the block — public
            ("100.64.0.0", True),       # first address of the block
            ("100.100.50.50", True),    # squarely inside the block
            ("100.127.255.255", True),  # last address of the block
            ("100.128.0.0", False),     # first address AFTER the block — public
        ],
    )
    def test_cgnat_block_boundaries(self, ip: str, blocked: bool) -> None:
        assert ip_block.is_blocked_ip(ipaddress.ip_address(ip)) is blocked


# ===========================================================================
# Fail-Closed — anything that is NOT a parseable address object is treated as
# blocked (the ``is_*`` reads raise AttributeError -> return True). A value the
# predicate cannot classify must never become an open door.
# ===========================================================================
class TestFailClosed:
    @pytest.mark.parametrize(
        "bad",
        [
            "10.0.0.5",   # a raw STRING (not parsed) — has no is_loopback attr
            "8.8.8.8",    # even a would-be-public string fails closed until parsed
            12345,        # an int
            None,         # None
            object(),     # an arbitrary object with no address attributes
            b"\x7f\x00\x00\x01",  # raw bytes
        ],
        ids=["str_private", "str_public", "int", "none", "object", "bytes"],
    )
    def test_non_address_input_fails_closed(self, bad: object) -> None:
        assert ip_block.is_blocked_ip(bad) is True, (  # type: ignore[arg-type]
            "a value that cannot be classified as an address must fail closed (blocked)"
        )


# ===========================================================================
# Anti-divergence lock (the HEART of #802) — both per-site wrappers must delegate
# to the canonical predicate and agree with it on EVERY corpus entry. If someone
# re-forks one copy and changes a range, one of these parity assertions fails.
# ===========================================================================
_ALL_ADDR_STRINGS = (
    list(BLOCKED_IPV4.values())
    + list(BLOCKED_IPV6.values())
    + list(PUBLIC_IPS.values())
)


class TestBothWrappersDelegateToCanonical:
    @pytest.mark.parametrize("ip", _ALL_ADDR_STRINGS)
    def test_egress_guard_pin_wrapper_matches_canonical(self, ip: str) -> None:
        addr = ipaddress.ip_address(ip)
        assert egress_guard._is_blocked_pin_ip(addr) == ip_block.is_blocked_ip(addr)

    @pytest.mark.parametrize("ip", _ALL_ADDR_STRINGS)
    def test_guarded_fetch_wrapper_matches_canonical(self, ip: str) -> None:
        addr = ipaddress.ip_address(ip)
        assert guarded_fetch._is_blocked_ip(addr) == ip_block.is_blocked_ip(addr)

    @pytest.mark.parametrize("ip", _ALL_ADDR_STRINGS)
    def test_both_wrappers_agree_with_each_other(self, ip: str) -> None:
        """The whole point: the pin side and the fetch side give the SAME verdict."""
        addr = ipaddress.ip_address(ip)
        assert egress_guard._is_blocked_pin_ip(addr) == guarded_fetch._is_blocked_ip(addr)

    def test_both_wrappers_fail_closed_identically(self) -> None:
        """A non-address input fails closed (True) through BOTH wrappers and the canonical."""
        for bad in ("not-an-ip", None, object(), 7):
            assert ip_block.is_blocked_ip(bad) is True  # type: ignore[arg-type]
            assert egress_guard._is_blocked_pin_ip(bad) is True  # type: ignore[arg-type]
            assert guarded_fetch._is_blocked_ip(bad) is True
