r"""The ONE canonical "is this IP off-limits for egress?" predicate (SSRF core).

WHY THIS MODULE EXISTS
======================
Two independent egress doors each need to answer the same question — *"is this
resolved IP address one an outbound fetch / a resolution pin must never touch?"*:

  * :mod:`shared.security.guarded_fetch` — the one PA-gated external-fetch door.
    It refuses a URL whose host is a raw internal-IP literal, and refuses a NAMED
    host that DNS-resolves to an internal/special address (the SSRF
    defense-in-depth resolve-and-recheck).
  * :mod:`shared.security.egress_guard` — the raw-socket kill-switch. It refuses to
    *pin* (and thereby admit) a resolved IP for an allowlisted name when that IP is
    in an internal/special range — a name resolving to ``169.254.169.254`` must not
    get its internal IP pinned.

Before this module those two doors carried **two separate copies** of the same
range check (``guarded_fetch._is_blocked_ip`` and
``egress_guard._is_blocked_pin_ip``). The copies were identical, but on the
security-critical egress layer that is exactly the dangerous shape: the day someone
adds a newly-discovered SSRF range to one copy and forgets the other, the two doors
silently diverge and one of them admits a target the other blocks (Vikunja #802 /
AUDIT-3). This module is the SINGLE source of truth both doors delegate to, so a
range can only ever be added in one place and both doors move together.

Design constraints (match the rest of ``shared/security/``):
  * **Leaf module.** Imports ONLY the stdlib ``ipaddress`` — it imports neither
    ``egress_guard`` nor ``guarded_fetch``, so both may import it with no cycle.
  * **No side effects at import. No new dependencies.**
  * **Fail-Closed.** Anything this cannot classify as safe is treated as blocked.

THE BLOCKED SET (each range with its RFC — the coverage both doors enforce)
==========================================================================
:func:`is_blocked_ip` returns True for an address in ANY of these. Where a range is
already covered by a stdlib ``ipaddress`` property it is named; the ONE range stdlib
does not flag (CGNAT 100.64.0.0/10) is checked explicitly.

IPv4:
  * 0.0.0.0/8          "this host on this network"     (RFC 1122)     — is_private
  * 0.0.0.0            the unspecified address          (RFC 5735)     — is_unspecified
  * 10.0.0.0/8         RFC-1918 private                 (RFC 1918)     — is_private
  * 100.64.0.0/10      Carrier-Grade NAT (CGNAT)        (RFC 6598)     — EXPLICIT
                       *** stdlib is_private does NOT flag CGNAT — this is the one
                           range that needs the explicit bit-check below. ***
  * 127.0.0.0/8        loopback                         (RFC 1122)     — is_loopback
  * 169.254.0.0/16     link-local (incl. the cloud-metadata SSRF classic
                       169.254.169.254)                 (RFC 3927)     — is_link_local
  * 172.16.0.0/12      RFC-1918 private                 (RFC 1918)     — is_private
  * 192.0.0.0/24       IETF protocol assignments        (RFC 6890)     — is_private
  * 192.0.2.0/24       TEST-NET-1 documentation         (RFC 5737)     — is_private
  * 192.168.0.0/16     RFC-1918 private                 (RFC 1918)     — is_private
  * 198.18.0.0/15      benchmarking                     (RFC 2544)     — is_private
  * 198.51.100.0/24    TEST-NET-2 documentation         (RFC 5737)     — is_private
  * 203.0.113.0/24     TEST-NET-3 documentation         (RFC 5737)     — is_private
  * 224.0.0.0/4        multicast                        (RFC 5771)     — is_multicast
  * 240.0.0.0/4        future-use / reserved            (RFC 1112 §4)  — is_reserved
  * 255.255.255.255/32 limited broadcast                (RFC 8190)     — is_private

IPv6:
  * ::/128             the unspecified address          (RFC 4291)     — is_unspecified
  * ::1/128            loopback                         (RFC 4291)     — is_loopback
  * ::ffff:0:0/96      IPv4-mapped                      (RFC 4291)     — is_private
  * 100::/64           discard-only                     (RFC 6666)     — is_private
  * 2001::/23          IETF protocol assignments        (RFC 2928)     — is_private
  * 2001:db8::/32      documentation                    (RFC 3849)     — is_private
  * fc00::/7           unique-local (ULA)               (RFC 4193)     — is_private
  * fe80::/10          link-local                       (RFC 4291)     — is_link_local / is_private
  * ff00::/8           multicast                        (RFC 4291)     — is_multicast
  * (plus the IETF-reserved v6 blocks stdlib flags via is_reserved)

Anything NOT in the blocked set — an ordinary global-unicast public address — is
permitted (returns False). See ``tests/security/test_ip_block.py`` for the full
per-range corpus (block cases + public happy-path + malformed fail-closed).
"""

from __future__ import annotations

import ipaddress

# CGNAT 100.64.0.0/10 (RFC 6598) is the ONE range stdlib ``ipaddress`` does not
# classify as private/reserved. 100.64.0.0/10 fixes the top 10 bits; shifting a
# 32-bit v4 address right by (32 - 10) == 22 keeps exactly those top 10 bits, so
# an address is in the block iff its top-10-bit prefix equals 100.64.0.0's.
_CGNAT_NETWORK_INT: int = int(ipaddress.IPv4Address("100.64.0.0"))
_CGNAT_PREFIX_SHIFT: int = 32 - 10  # 22


def is_blocked_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True iff ``addr`` is in a range that egress must never reach (SSRF core).

    THE single canonical blocked-range check. ``addr`` is an ALREADY-PARSED
    :class:`ipaddress.IPv4Address` / :class:`ipaddress.IPv6Address` (both call sites
    parse the string first, then hand the object here). Returns True for any
    loopback / RFC-1918 private / link-local / reserved / multicast / unspecified /
    CGNAT address (the full set documented in the module docstring, each with its
    RFC), and for IPv6 the stdlib-classified private/reserved/link-local/multicast
    blocks. Returns False for an ordinary public global-unicast address.

    **Fail-Closed:** if ``addr`` cannot be classified (it is not an address object —
    the six ``is_*`` property reads raise :class:`AttributeError`), this returns
    True (blocked), never False. A value the check cannot reason about must not
    become an open door.
    """
    try:
        return bool(
            addr.is_loopback        # 127.0.0.0/8 (RFC 1122) | ::1/128 (RFC 4291)
            or addr.is_private      # RFC-1918 + the broader stdlib private/doc set
            or addr.is_link_local   # 169.254.0.0/16 (RFC 3927) | fe80::/10 (RFC 4291)
            or addr.is_reserved     # 240.0.0.0/4 (RFC 1112) + IETF-reserved v6
            or addr.is_multicast    # 224.0.0.0/4 (RFC 5771) | ff00::/8 (RFC 4291)
            or addr.is_unspecified  # 0.0.0.0 (RFC 5735) | :: (RFC 4291)
            # CGNAT 100.64.0.0/10 (RFC 6598) — NOT flagged by stdlib is_private, so
            # it is checked explicitly by top-10-bit prefix match (v4 only).
            or (
                addr.version == 4
                and int(addr) >> _CGNAT_PREFIX_SHIFT
                == _CGNAT_NETWORK_INT >> _CGNAT_PREFIX_SHIFT
            )
        )
    except AttributeError:
        return True  # cannot classify -> Fail-Closed (block / do not pin)
