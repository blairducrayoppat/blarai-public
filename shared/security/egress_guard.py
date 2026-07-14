r"""Code-enforced network egress kill-switch (fail-closed allowlist). ADR-020 + ADR-027.

Tier-0 security hardening. BlarAI's no-external-network guarantee is, today,
*environmental* — the machine is air-gapped and the source happens not to call
any HTTP library. This module makes the guarantee *code-enforced*: once a process
calls :func:`arm`, the only sockets it can open are the legitimate local IPC
channels the runtime needs. Every other outbound socket — and every
``connect``/``bind``/``sendto`` to a non-loopback address — is refused at
runtime. Fail-Closed: anything not on the allowlist is denied.

Allowlist (the local IPC the runtime legitimately uses):
  - ``AF_HYPERV``       vsock to the Hyper-V guest VM (``shared/ipc/vsock.py``
                        production path). The family is host<->guest only; it
                        cannot route to the internet, so it is permitted
                        unconditionally.
  - ``AF_INET`` / ``AF_INET6``  **loopback only** — ``127.0.0.0/8`` and ``::1``
                        (dev-mode vsock TCP substitute + the launcher's
                        ``127.0.0.1:5001`` Policy-Agent gateway path).

ADR-027 network-facing machinery (Sprint 17 — STAGED/DORMANT)
=============================================================
This module also carries the egress machinery the *network-facing era* needs
(ADR-027), built ahead of #556 and shipped **dormant**: it changes NO external-
egress behavior today — the active allowlist stays loopback + AF_HYPERV, and the
exfil screen / allowlist-widening only matter once a web feature ships post-#556
and adds an external endpoint. The machinery is wired and tested now so that the
#598 air-gap GO/NO-GO is a scripted audit, not a from-scratch build. Three layers
are added here (ADR-027 rules 1, 3, and the trip half of rule 4):

  - **Allowlist-widening mechanism** (rule 1) — :func:`allow_external_endpoint`
    registers ONE named, vetted external ``(host, port)`` at a time, deny-by-
    default. **The live list is NOT widened this sprint** — no external endpoint
    is registered; the mechanism exists, the door stays shut.
  - **Anomaly auto-trip** (rule 3) — :func:`trip` cuts ALL egress (loopback and
    vsock included) and alerts the operator. The guard auto-trips on (a) a
    connect/bind/send to an off-allowlist address, or (b) a positive detection
    from a registered outbound-payload screener. The trip is a **latched kill-
    switch, default-off, that only the Lead Architect can clear** (:func:`rearm`).
  - **Outbound-payload screening seam** (the trip half of rule 4) —
    :func:`register_screener` registers an exfil screener (built by the H-b
    stream / ``exfil_screen`` module) via a **registration pattern** so there is
    no circular import: egress_guard never imports the screener module; the
    screener module imports egress_guard and registers itself at :func:`arm`
    time. **Destination-scoped (ADR-027 rule 4):** the screener is invoked ONLY
    for payloads on a socket connected to a vetted EXTERNAL-allowlisted endpoint —
    never for the internal loopback/AF_HYPERV IPC, whose frames legitimately carry
    the runtime's own capability JWTs and user PII (screening those would trip the
    kill-switch on the first internal message — a self-DoS). A positive detection
    on an external send calls :func:`trip`. With the external allowlist empty (the
    dormant default this sprint) no socket is ever tagged, so a registered screener
    is a behavior-free no-op.

The interface anchor H-b integrates against (exact signatures):
  - ``trip(reason: str) -> None``
  - ``register_screener(screener: OutboundScreener) -> None``
where ``OutboundScreener`` is ``Callable[[bytes], ScreenResult | bool | None]``.

Explicitly NOT in scope (and therefore unaffected):
  - The named pipe ``\\.\pipe\BlarAI`` is a Windows kernel object created via the
    win32 pipe API (``services/ui_backend/src/server.py``), not a socket. The
    guard rebinds only two symbols in the ``socket`` module, so the pipe path is
    untouched (asserted by ``test_egress_guard.test_guard_scope_is_sockets_only``).

Enforcement layers (defence in depth):
  1. ``socket.socket`` construction  — deny address families outside the allowlist.
  2. ``connect`` / ``connect_ex`` / ``bind`` / ``sendto`` / ``sendmsg`` — deny any
     non-loopback address for ``AF_INET``/``AF_INET6`` (``AF_HYPERV`` permitted).
  3. ``socket.getaddrinfo`` — deny resolution of an external *hostname* (a DNS
     query is itself egress, and a vector for exfiltration). Numeric literals and
     the loopback names are allowed; an external numeric IP is permitted to
     *resolve* but is still refused at ``connect`` time by layer 2 — UNLESS the
     name that resolved to it is on the external allowlist, in which case the IP is
     *pinned* to that name (the W4 enabling enhancement, ADR-024 amendment) so a
     standard HTTP client — which connects to the resolved IP, not the name — can
     reach the allowlisted endpoint at the allowlisted port (and only there). An IP
     nobody resolved through an allowlisted name has no pin and stays denied.
     :func:`real_getaddrinfo` is the sanctioned trusted-resolution seam: it exposes
     the pre-arm resolver so an in-runtime SSRF pre-check (``guarded_fetch``'s
     resolve-and-refuse-internal lookup) can resolve a host to INSPECT it WITHOUT
     tripping the armed guard — it is NOT a general egress bypass (the caller must
     still route any actual connection through the guarded path).

Design constraints (match ``tpm_signer.py``):
  - **No external network. No new dependencies** (stdlib ``socket`` + ``ipaddress``).
  - **Importing this module has no side effects** — it does not arm itself. A
    process arms explicitly at its entry point; tests arm/disarm around assertions.
  - **Fail-Closed everywhere:** an unparseable or ambiguous address is denied, not
    allowed. :class:`EgressDenied` subclasses :class:`OSError` so the runtime's
    existing ``except OSError`` fail-closed paths (e.g. ``vsock.VsockTransport``)
    treat a guard denial as an ordinary connection failure rather than crashing.
"""

from __future__ import annotations

import errno
import ipaddress
import logging
import socket
import threading
from dataclasses import dataclass
from typing import Any, Callable, Final, Optional

from shared.security import ip_block

logger = logging.getLogger(__name__)

# Windows AF_HYPERV address family (mirrors shared/ipc/vsock.py:39). getattr keeps
# this importable on platforms where the constant is absent.
AF_HYPERV: Final[int] = int(getattr(socket, "AF_HYPERV", 34))

# Loopback names that resolve locally (no DNS query) and are always permitted.
_LOCAL_NAMES: Final[frozenset[str]] = frozenset({"localhost", ""})


def _allowed_families() -> frozenset[int]:
    fams = {int(socket.AF_INET), AF_HYPERV}
    if hasattr(socket, "AF_INET6"):
        fams.add(int(socket.AF_INET6))
    return frozenset(fams)


_ALLOWED_FAMILIES: Final[frozenset[int]] = _allowed_families()
_INET_FAMILIES: Final[tuple[int, ...]] = (
    (int(socket.AF_INET), int(socket.AF_INET6))
    if hasattr(socket, "AF_INET6")
    else (int(socket.AF_INET),)
)


class EgressDenied(OSError):
    """Raised when the egress guard refuses a socket operation (Fail-Closed).

    Subclasses :class:`OSError` so that callers already written to fail closed on
    ``OSError`` (the vsock transport, ``socket.create_connection``) degrade to a
    refused connection rather than an uncaught exception.
    """


class EgressTripped(EgressDenied):
    """Raised when the kill-switch has tripped — ALL egress is cut (ADR-027 §3).

    Distinct from a plain :class:`EgressDenied` (an allowlist miss): once the
    guard has tripped, *every* outbound operation is refused — even the loopback
    and AF_HYPERV channels that the allowlist would normally permit. The trip is
    latched and only :func:`rearm` (a Lead-Architect-only act) clears it.

    Subclasses :class:`EgressDenied` (hence :class:`OSError`) so the runtime's
    existing fail-closed ``except OSError`` paths treat a tripped kill-switch as
    an ordinary refused connection rather than crashing.
    """


# ---------------------------------------------------------------------------
# ADR-027 machinery — outbound-payload screening (STAGED/DORMANT).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScreenResult:
    """The verdict a registered outbound screener returns for a payload.

    ``detected=True`` means a secret/PII was found and the payload MUST NOT leave
    (ADR-027 rule 4: block-on-detection). ``reason`` is a short, log-safe label
    of *what kind* of thing tripped it — it must NEVER contain the matched secret
    itself. A screener may also return a bare ``bool`` (``True`` == detected),
    ``None``/``False`` (clean), or any object exposing a ``detected``/``blocked``
    attribute (chiefly the H-b ``exfil_screen.Detection`` the real screen
    returns); :func:`_normalise_screen_result` coerces all of those.
    """

    detected: bool
    reason: str = "exfil screener positive detection"


# An outbound-payload screener: given the bytes about to leave, return a
# positive/negative verdict. Registration pattern (no import of the screener
# module from here) keeps egress_guard <-> exfil_screen acyclic. The verdict is
# the rich :class:`ScreenResult`, a bare ``bool``, ``None``, OR any object that
# exposes a ``detected`` (or ``blocked``) attribute — chiefly the H-b
# ``exfil_screen.Detection`` the real screen returns. The attribute is read
# explicitly (NOT truthiness) so a clean ``Detection(blocked=False)`` — which is
# truthy as a dataclass instance — is correctly treated as clean.
OutboundScreener = Callable[[bytes], Any]


def _normalise_screen_result(result: Any) -> Optional[ScreenResult]:
    """Coerce a screener's return into a :class:`ScreenResult`, or ``None`` if clean.

    Accepts, in order:
      * ``None`` / ``False`` — clean;
      * a :class:`ScreenResult` — used as-is (clean iff ``detected`` is False);
      * a bare ``True`` — a positive detection;
      * **any object exposing a ``detected`` or ``blocked`` attribute** — chiefly
        the H-b :class:`exfil_screen.Detection` the canonical screen returns. The
        attribute is read EXPLICITLY rather than by truthiness, because a frozen
        dataclass instance is always truthy: a clean ``Detection(blocked=False)``
        must coerce to ``None`` (clean), not to a false-positive block. A blocked
        result carries its ``reason`` through to the :func:`trip` audit label when
        present (so the real labels survive, not a generic "non-standard" string).

    Fail-Closed: any *other* unexpected truthy value (no recognised verdict
    attribute) is treated as a positive detection rather than silently passed — a
    screener whose contract we cannot read must not become an open door.
    """
    if result is None or result is False:
        return None
    if isinstance(result, ScreenResult):
        return result if result.detected else None
    if result is True:
        return ScreenResult(detected=True)
    # Duck-type the sibling verdict shape (exfil_screen.Detection and anything
    # else exposing a clear detected/blocked flag). Read the flag explicitly so a
    # clean-but-truthy dataclass instance is not mistaken for a detection.
    detected_flag = getattr(result, "detected", None)
    if detected_flag is None:
        detected_flag = getattr(result, "blocked", None)
    if detected_flag is not None:
        if not detected_flag:
            return None
        reason = getattr(result, "reason", "") or "exfil screener positive detection"
        return ScreenResult(detected=True, reason=str(reason))
    # Any other truthy value with no readable verdict -> treat as detection (Fail-Closed).
    return ScreenResult(detected=True, reason="exfil screener returned non-standard truthy verdict")


# ---------------------------------------------------------------------------
# ADR-027 machinery — mutable state (kill-switch + allowlist-widening).
# ---------------------------------------------------------------------------
# All declared here, ahead of the address-check helpers that read them, so the
# checks can consult the trip-state and the widened allowlist on every operation.

# The latched kill-switch (ADR-027 §3). Default-off (not tripped). When True,
# EVERY egress operation is refused until rearm() clears it.
_tripped: bool = False
_trip_reason: Optional[str] = None

# Registered outbound-payload screeners (ADR-027 rule 4). Populated at arm() time
# by the exfil-screen module via register_screener(). Empty == no screening
# (the dormant default this sprint, since no web feature ships).
_screeners: list[OutboundScreener] = []

# The widened external allowlist (ADR-027 §1). deny-by-default: empty this sprint
# (the door stays shut). Each entry is a vetted (host, port) an enabled web
# feature requires; allow_external_endpoint() adds one at a time. The host is
# stored as a normalised numeric-or-name string; "*" port means any port on host.
_ALLOWLIST_ANY_PORT: Final[str] = "*"
_external_allowlist: set[tuple[str, str]] = set()

# Hostname-resolution pinning (the W4 enabling enhancement, ADR-024 amendment
# 2026-06-10). A standard HTTP client resolves a hostname via socket.getaddrinfo
# and then connects to the *numeric IP* it got back. That numeric IP is not the
# literal host string on the allowlist, so without this map a real Kagi connect
# would be off-allowlist and AUTO-TRIP. When _guarded_getaddrinfo successfully
# resolves a host that IS on the external allowlist, it records the resolved IPs
# here, mapping each ``ip -> {hostnames it resolved from}``. _is_allowlisted_external
# then accepts a numeric IP iff some pinned hostname for that IP is allowlisted at
# the requested port. The pin is NOT a second allowlist: an IP is permitted ONLY
# because an allowlisted *name* legitimately resolved to it (deny-by-default holds —
# an IP nobody resolved stays denied + trips), and the PORT must still match the
# allowlisted (host, port) entry. Guarded by a lock because getaddrinfo runs on
# whatever thread the HTTP client uses while connect() runs on another.
_resolution_pins: dict[str, set[str]] = {}
_resolution_pins_lock = threading.Lock()


def _is_blocked_pin_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True iff a resolved IP is in a range a resolution pin must NEVER admit.

    SSRF defense-in-depth (merge-gate fix 1, 2026-06-10). Mirrors the spirit of
    ``guarded_fetch._is_blocked_ip``: an allowlisted *name* that DNS-resolves to an
    internal/special address must NOT have that internal IP pinned, or the later
    numeric connect to it would be admitted (and the screen would tag an internal
    target). Before this, only loopback was skipped — a name resolving to
    10.x / 172.16-31.x / 192.168.x (RFC-1918), 169.254.x (link-local incl. cloud
    metadata 169.254.169.254), 100.64.0.0/10 (CGNAT), reserved, multicast, or the
    unspecified address would be pinned and admitted. Skipping every blocked range
    closes that: an internal IP gets no pin, so the connect to it stays off-
    allowlist and the guard denies + auto-trips. (The defense-in-depth partner is
    ``guarded_fetch``'s pre-fetch resolve-and-recheck, which refuses the whole
    fetch — including a name resolving to loopback, which this layer permits for
    IPC. Together they close the named-host-to-internal SSRF in both layers.)

    Delegates to the ONE canonical blocked-range predicate
    (:func:`shared.security.ip_block.is_blocked_ip`) so this pin-side check and
    ``guarded_fetch``'s fetch-side check can never diverge — a range is added in one
    place and both doors move together (Vikunja #802 / AUDIT-3). This wrapper is
    kept (not inlined) so the pin-context docstring above stays at the call site and
    the ``_is_blocked_pin_ip`` name its caller uses is unchanged.
    """
    return ip_block.is_blocked_ip(addr)


def _record_resolution_pins(host: str, addr_infos: Any) -> None:
    """Pin the IPs ``host`` resolved to, so its later numeric connect is allowed.

    Called by :func:`_guarded_getaddrinfo` ONLY after it has confirmed ``host`` is
    on the external allowlist and the real resolution succeeded. ``addr_infos`` is
    the getaddrinfo return value (a list of 5-tuples); the sockaddr is element 4,
    whose first item is the numeric IP. Each resolved IP is mapped back to ``host``.
    Malformed entries are skipped (fail-closed toward not pinning — an unparseable
    address simply does not get a pin, so it stays denied at connect time).

    An IP in ANY blocked range (loopback / RFC-1918 private / link-local / CGNAT /
    reserved / multicast / unspecified — see :func:`_is_blocked_pin_ip`) is NEVER
    pinned: an allowlisted name that resolves to an internal address must not have
    that internal IP admitted (SSRF defense-in-depth, merge-gate fix 1).
    """
    host_norm = host.lower()
    pinned: list[str] = []
    try:
        for info in addr_infos:
            try:
                sockaddr = info[4]
                ip = sockaddr[0]
            except (IndexError, TypeError):
                continue
            if not isinstance(ip, str) or not ip:
                continue
            try:
                # Only pin genuine numeric IPs (never a name); never pin a blocked-
                # range IP — loopback (already permitted, must never be tagged) NOR
                # any private/link-local/CGNAT/reserved/multicast/unspecified address
                # (a name resolving there is an SSRF attempt; pinning would admit it).
                if _is_blocked_pin_ip(ipaddress.ip_address(ip)):
                    continue
            except ValueError:
                continue
            pinned.append(ip)
    except TypeError:
        return  # addr_infos not iterable — nothing to pin (stays denied)
    if not pinned:
        return
    with _resolution_pins_lock:
        for ip in pinned:
            _resolution_pins.setdefault(ip, set()).add(host_norm)


def _pinned_hosts_for_ip(ip: str) -> frozenset[str]:
    """Hostnames an allowlisted resolution pinned to ``ip`` (empty if none)."""
    with _resolution_pins_lock:
        hosts = _resolution_pins.get(ip)
        return frozenset(hosts) if hosts else frozenset()


def _drop_resolution_pins_for_host(host: str) -> None:
    """Forget every IP pinned for ``host`` (called on revoke of that endpoint)."""
    host_norm = host.lower()
    with _resolution_pins_lock:
        empty_ips = []
        for ip, hosts in _resolution_pins.items():
            hosts.discard(host_norm)
            if not hosts:
                empty_ips.append(ip)
        for ip in empty_ips:
            del _resolution_pins[ip]


def _clear_resolution_pins() -> None:
    """Forget all resolution pins (cleared with the allowlist and on disarm)."""
    with _resolution_pins_lock:
        _resolution_pins.clear()


def _name_allowlisted_at_port(host: str, port_str: str) -> bool:
    """True iff the literal host name is allowlisted at ``port_str`` (or any-port)."""
    return (
        (host, port_str) in _external_allowlist
        or (host, _ALLOWLIST_ANY_PORT) in _external_allowlist
    )


def _name_allowlisted_any_port(host: str) -> bool:
    """True iff the host name appears on the allowlist for ANY port.

    Used by the getaddrinfo (DNS) layer, which carries no port: a name that is
    allowlisted for a specific port (e.g. ``kagi.com:443``) MUST be resolvable, so
    the resolution check is "is this name allowlisted at all", not "at the any-port
    wildcard". The connect-time check (:func:`_is_allowlisted_external`) still
    enforces the exact port.
    """
    return any(entry_host == host for entry_host, _ in _external_allowlist)


def _is_allowlisted_external(host: str | None, port: Any) -> bool:
    """True iff ``(host, port)`` is permitted on the widened external allowlist.

    Two ways a destination is permitted (ADR-027 §1 + the W4 resolution-pin):
      1. the literal ``host`` string is on the allowlist at this port (or any-port);
      2. ``host`` is a numeric IP that an ALLOWLISTED hostname resolved to (a
         resolution pin), AND that hostname is allowlisted at this exact port —
         this is what lets a real HTTP client (which connects to the resolved IP,
         not the name) reach an allowlisted endpoint. The port still must match;
         an IP pinned for ``kagi.com:443`` is NOT admitted on some other port.

    Deny-by-default holds: with an empty allowlist (the dormant baseline) this is
    always False; an IP that nobody resolved has no pin and stays denied (and the
    caller auto-trips it). Comparison is on the exact normalised host string.
    """
    if host is None or host == "":
        return False
    if not _external_allowlist:
        return False
    port_str = str(port) if port is not None else _ALLOWLIST_ANY_PORT
    if _name_allowlisted_at_port(host, port_str):
        return True
    # Resolution-pin path: a numeric IP is admitted iff an allowlisted *name*
    # resolved to it AND that name is allowlisted at this port.
    pinned_hosts = _pinned_hosts_for_ip(host)
    if not pinned_hosts:
        return False
    return any(_name_allowlisted_at_port(h, port_str) for h in pinned_hosts)


def _alert_operator(message: str) -> None:
    """Surface an operator alert for an egress anomaly (ADR-027 §3).

    Today this logs at CRITICAL (the launcher writes the log file the operator
    reads, and the on-screen handler shows CRITICAL). When the network-facing UI
    lands post-#556, this is the seam an operator-facing notification hooks onto.
    Kept deliberately small + dependency-free so it is safe to call from the
    socket hot path.
    """
    logger.critical("EGRESS GUARD ALERT: %s", message)


def trip(reason: str) -> None:
    """Cut ALL network egress and alert the operator — the anomaly kill-switch (ADR-027 §3).

    INTERFACE ANCHOR (H-b integrates against this exact signature). Idempotent:
    if already tripped, the first reason is preserved and this is a no-op beyond
    re-alerting. After a trip, *every* egress operation — loopback and AF_HYPERV
    included, not just external — raises :class:`EgressTripped` until
    :func:`rearm` is called (a Lead-Architect-only act). The latch is the point:
    on a detected anomaly the safe state is "nothing leaves," and clearing it is
    a deliberate human decision, never automatic.

    Called automatically by the guard on (a) an attempt to reach an off-allowlist
    address, and (b) a registered screener's positive detection. May also be
    called directly (e.g. an operator master-off, or a higher layer that detects
    an anomaly).

    :param reason: a short, log-safe description of why egress was cut. MUST NOT
        contain any matched secret/PII (only the *kind* of anomaly).
    """
    global _tripped, _trip_reason
    if _tripped:
        # Already latched — keep the original cause, re-alert for the audit trail.
        _alert_operator(f"egress already tripped ({_trip_reason!r}); new trigger: {reason}")
        return
    _tripped = True
    _trip_reason = reason
    _alert_operator(
        f"KILL-SWITCH TRIPPED — all network egress cut (ADR-027 §3). Reason: {reason}. "
        f"Re-arm is Lead-Architect-only (egress_guard.rearm())."
    )


def is_tripped() -> bool:
    """True iff the kill-switch has tripped and egress is fully cut."""
    return _tripped


def trip_reason() -> Optional[str]:
    """The reason the kill-switch tripped, or ``None`` if it has not tripped."""
    return _trip_reason


def rearm() -> None:
    """Clear a tripped kill-switch and restore the normal allowlist (ADR-027 §3).

    This is the **Lead-Architect-only** re-arm: after the guard auto-trips on an
    anomaly, egress stays fully cut until this is called. It is intentionally a
    bare function (not exposed on any automatic path) — the calling surface is a
    deliberate operator action, never the runtime. Re-arming does NOT widen the
    allowlist or clear registered screeners; it only releases the latch so the
    normal (allowlist-governed) egress checks apply again.

    No-op if not currently tripped.
    """
    global _tripped, _trip_reason
    if not _tripped:
        return
    cleared = _trip_reason
    _tripped = False
    _trip_reason = None
    logger.warning(
        "Egress kill-switch RE-ARMED by operator — normal allowlist enforcement "
        "resumed (previous trip reason: %r)",
        cleared,
    )


def _enforce_not_tripped() -> None:
    """Raise :class:`EgressTripped` if the kill-switch has tripped. Fail-Closed."""
    if _tripped:
        raise EgressTripped(
            f"egress guard: ALL egress cut — kill-switch tripped "
            f"(reason: {_trip_reason!r}; Lead-Architect re-arm required)"
        )


def _host_of(address: Any) -> str | None:
    """Extract the host string from a socket address tuple, or None if unusable."""
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
        if isinstance(host, (bytes, bytearray)):
            try:
                return host.decode("ascii")
            except UnicodeDecodeError:
                return None
        if isinstance(host, str):
            return host
    return None


def _is_loopback_host(host: str | None) -> bool:
    """True iff ``host`` is unambiguously a loopback address (no DNS required)."""
    if host is None:
        return False
    if host in _LOCAL_NAMES:
        # "" (INADDR_ANY) is a wildcard and must NOT be treated as loopback for
        # bind; callers that care (_check_bind) reject "" before reaching here.
        return host == "localhost"
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _requires_external_dns(host: Any) -> bool:
    """True iff resolving ``host`` would require an external DNS query."""
    if host is None:
        return False
    if isinstance(host, (bytes, bytearray)):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return True  # cannot tell -> Fail-Closed
    if not isinstance(host, str):
        return False
    if host in _LOCAL_NAMES:
        return False
    try:
        ipaddress.ip_address(host)  # numeric literal -> no DNS query needed
        return False
    except ValueError:
        return True  # a hostname -> needs external resolution


def _port_of(address: Any) -> Any:
    """Extract the port from a socket address tuple, or ``None`` if unavailable."""
    if isinstance(address, (tuple, list)) and len(address) >= 2:
        return address[1]
    return None


def _check_connect(family: int, address: Any) -> None:
    """Permit a connect/sendto destination, or raise (ADR-020 allowlist + ADR-027 §1/§3).

    Order matters and is Fail-Closed:
      1. If the kill-switch has tripped, ALL egress is refused (ADR-027 §3).
      2. AF_HYPERV and loopback are always permitted (the air-gapped baseline).
      3. An external destination is permitted ONLY if it is on the widened
         allowlist (ADR-027 §1 — empty + dormant this sprint).
      4. Any other external destination AUTO-TRIPS the kill-switch (ADR-027 §3:
         "an attempt to reach an off-allowlist address") and is then refused.
    """
    _enforce_not_tripped()
    if family == AF_HYPERV:
        return  # host<->guest vsock; cannot route off-box.
    if family in _INET_FAMILIES:
        host = _host_of(address)
        if host is not None and host != "" and _is_loopback_host(host):
            return
        # ADR-027 §1: a vetted external endpoint on the widened allowlist passes.
        if _is_allowlisted_external(host, _port_of(address)):
            return
        # ADR-027 §3: an off-allowlist external attempt is an anomaly -> auto-trip.
        trip(f"connect to off-allowlist address {host!r} (Fail-Closed)")
        raise EgressDenied(
            f"egress guard: outbound to non-loopback host {host!r} denied "
            f"(Fail-Closed; allowlist = localhost + Hyper-V + vetted endpoints; "
            f"kill-switch tripped)"
        )
    # ADR-027 §3: an attempt on a disallowed family is also an anomaly.
    trip(f"connect on disallowed socket family {family} (Fail-Closed)")
    raise EgressDenied(
        f"egress guard: outbound on socket family {family} denied (Fail-Closed)"
    )


def _is_external_screen_target(family: int, address: Any) -> bool:
    """True iff a payload to ``address`` MUST be exfil-screened (ADR-027 rule 4).

    Outbound screening fires ONLY for traffic leaving the host to a vetted
    EXTERNAL endpoint — never for the internal IPC the runtime legitimately uses
    (loopback ``127.0.0.0/8`` / ``::1`` and the AF_HYPERV host<->guest vsock).
    Internal frames carry agentic capability tokens (PA<->AO JWTs) and user PII
    (prompts), which the screen flags by design; screening them would trip the
    kill-switch on the first internal message — a self-inflicted denial of
    service. So the screen is scoped to exactly the destinations that can leave
    the box: a non-loopback INET host that is on the widened external allowlist.

    Fail-Closed *toward not screening internal traffic*: anything that is not an
    INET family, or is loopback, or is not explicitly external-allowlisted,
    returns False (not screened). The address allowlist (:func:`_check_connect`)
    independently guarantees a payload can ONLY reach a loopback or an
    allowlisted-external destination, so "external-allowlisted" is the precise
    and only set this screens. With the external allowlist empty (the dormant
    baseline this sprint) this always returns False — screening is a behavior-free
    no-op even when a screener is registered.
    """
    if family not in _INET_FAMILIES:
        return False
    host = _host_of(address)
    if host is None or host == "" or _is_loopback_host(host):
        return False
    return _is_allowlisted_external(host, _port_of(address))


def _check_bind(family: int, address: Any) -> None:
    """Permit a bind address, or raise :class:`EgressDenied`.

    Only loopback binds are allowed — a wildcard ("" / 0.0.0.0) or external bind
    would create a listener reachable beyond the host, which the air-gap forbids
    (ingress stays NONE — SECURITY_ROADMAP §6 Decision-7; ADR-027 governs egress,
    not inbound listeners). A tripped kill-switch refuses every bind; a non-
    loopback bind attempt auto-trips it (ADR-027 §3 anomaly).
    """
    _enforce_not_tripped()
    if family == AF_HYPERV:
        return
    if family in _INET_FAMILIES:
        host = _host_of(address)
        if host is not None and host != "" and _is_loopback_host(host):
            return
        trip(f"bind to externally-reachable host {host!r} (Fail-Closed)")
        raise EgressDenied(
            f"egress guard: bind to non-loopback host {host!r} denied "
            f"(Fail-Closed; no externally reachable listener permitted; "
            f"kill-switch tripped)"
        )
    trip(f"bind on disallowed socket family {family} (Fail-Closed)")
    raise EgressDenied(
        f"egress guard: bind on socket family {family} denied (Fail-Closed)"
    )


def _as_payload_bytes(data: Any) -> Optional[bytes]:
    """Best-effort view of an outbound buffer as ``bytes`` for screening.

    Accepts the buffer types ``socket.send``/``sendall`` accept. Returns ``None``
    when the data cannot be cheaply materialised (the screener is then skipped for
    that frame — screening is the ADR-027 rule-4 layer, defence-in-depth atop the
    address allowlist, not the sole control). Never raises on screening input.
    """
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, memoryview):
        try:
            return data.tobytes()
        except (ValueError, TypeError):
            return None
    return None


def _screen_outbound(data: Any) -> None:
    """Run every registered screener over an outbound payload (ADR-027 rule 4).

    The CALLER decides *whether* to invoke this — it is called only for sends on a
    socket tagged as an external-allowlisted destination (see
    :meth:`_GuardedSocket.send`/:func:`_is_external_screen_target`), so internal
    loopback/vsock frames (which carry the runtime's own JWTs/PII) are never
    screened and cannot self-trip the kill-switch. On a positive detection the
    kill-switch trips (ADR-027 §3: "a secret/PII detected leaving") and the send is
    refused with :class:`EgressTripped`. With no screeners registered (the dormant
    default this sprint) this is a near-free no-op. Fail-Closed: a screener that
    itself raises is treated as a detection rather than silently swallowed — a
    broken screen must not become an open door.
    """
    if not _screeners:
        return
    payload = _as_payload_bytes(data)
    if payload is None:
        return
    for screener in _screeners:
        try:
            verdict = _normalise_screen_result(screener(payload))
        except Exception as exc:  # noqa: BLE001 - a failing screen must fail closed
            trip(f"outbound screener raised ({type(exc).__name__}) — failing closed")
            raise EgressTripped(
                "egress guard: outbound screener errored — egress cut (Fail-Closed)"
            ) from exc
        if verdict is not None:
            trip(f"exfil screen positive detection: {verdict.reason}")
            raise EgressTripped(
                f"egress guard: outbound payload blocked — {verdict.reason} "
                f"(ADR-027 rule 4 block-on-detection; kill-switch tripped)"
            )


# Captured at import, before any arm(), so the guarded subclass and the restore
# path always reference the genuine standard-library objects.
_REAL_SOCKET: Final[type] = socket.socket
_REAL_GETADDRINFO: Final[Any] = socket.getaddrinfo


class _GuardedSocket(_REAL_SOCKET):  # type: ignore[misc,valid-type]
    """``socket.socket`` replacement enforcing the egress allowlist.

    Guards construction (address family) plus every operation that names a remote
    or bind address. Accepted sockets (``accept``) and same-fd duplicates inherit
    the guard but never connect/bind, so they pass through untouched.
    """

    # Per-socket: True iff this socket is connected to an EXTERNAL-allowlisted
    # destination and its outbound payloads must therefore be exfil-screened
    # (ADR-027 rule 4). Default False — loopback and AF_HYPERV sockets are NEVER
    # screened (their frames carry internal JWTs/PII the screen would flag,
    # tripping the kill-switch on the first internal message). Set True only by
    # connect()/connect_ex() after a successful connect to a non-loopback INET
    # host, which — having passed _check_connect — can only be an external
    # endpoint on the widened allowlist. Empty allowlist ⇒ never set ⇒ dormant.
    _screen_outbound_enabled: bool = False

    def __init__(
        self,
        family: int = -1,
        type: int = -1,  # noqa: A002 - match socket.socket signature
        proto: int = -1,
        fileno: Any = None,
    ) -> None:
        # family == -1 means "default" (AF_INET) and is allowed; an explicit
        # family must be on the allowlist. fileno-based construction (accept/dup)
        # passes the originating allowed family.
        if family != -1 and int(family) not in _ALLOWED_FAMILIES:
            raise EgressDenied(
                f"egress guard: socket family {family} denied at construction "
                f"(Fail-Closed; allowed = loopback AF_INET/AF_INET6 + AF_HYPERV)"
            )
        super().__init__(family, type, proto, fileno)
        # Default off. A socket built from a fileno (accept/dup) is an accepted
        # peer or a duplicate that never connects through this guard, so it stays
        # unscreened — consistent with the pre-existing pass-through for those.
        self._screen_outbound_enabled = False

    def _tag_screen_outbound(self, address: Any) -> None:
        """Mark this socket for outbound screening iff ``address`` is external.

        Called after a successful connect(). Scopes screening to exactly the
        sockets whose payloads can leave the box (a non-loopback INET host on the
        widened external allowlist); loopback and AF_HYPERV never tag. With the
        external allowlist empty (the dormant baseline) this never tags.
        """
        if _is_external_screen_target(self.family, address):
            self._screen_outbound_enabled = True

    def connect(self, address: Any) -> None:
        _check_connect(self.family, address)
        super().connect(address)
        # Only after the connect actually succeeds: tag for screening iff the
        # destination is an external-allowlisted endpoint (never loopback/vsock).
        self._tag_screen_outbound(address)

    def connect_ex(self, address: Any) -> int:
        _check_connect(self.family, address)
        rc = super().connect_ex(address)
        # connect_ex returns 0 on success (or EINPROGRESS / EWOULDBLOCK for a
        # non-blocking connect that is under way). Tag on a successful/initiated
        # connect to an external-allowlisted destination so its outbound payloads
        # are screened. A hard failure (other errno) leaves the socket untagged.
        if rc in (0, errno.EINPROGRESS, errno.EWOULDBLOCK):
            self._tag_screen_outbound(address)
        return rc

    def bind(self, address: Any) -> None:
        _check_bind(self.family, address)
        return super().bind(address)

    def send(self, data: Any, *args: Any) -> int:
        # Outbound on the connected peer. The kill-switch is UNCONDITIONAL; the
        # exfil screen fires ONLY for sockets tagged as external-allowlisted
        # (ADR-027 rule 4 — internal loopback/vsock traffic is never screened).
        _enforce_not_tripped()
        if self._screen_outbound_enabled:
            _screen_outbound(data)
        return super().send(data, *args)

    def sendall(self, data: Any, *args: Any) -> None:
        _enforce_not_tripped()
        if self._screen_outbound_enabled:
            _screen_outbound(data)
        return super().sendall(data, *args)

    def sendto(self, data: Any, *args: Any) -> int:
        # sendto(data, address) or sendto(data, flags, address): address is last.
        # The explicit per-call destination governs both the allowlist check and
        # whether the payload is screened (a connectionless socket has no single
        # peer to tag at connect time, so screen iff THIS address is external).
        _enforce_not_tripped()
        if args:
            destination = args[-1]
            _check_connect(self.family, destination)
            if _is_external_screen_target(self.family, destination):
                _screen_outbound(data)
        return super().sendto(data, *args)

    def sendmsg(
        self,
        buffers: Any,
        ancdata: Any = (),
        flags: int = 0,
        address: Any = None,
    ) -> int:
        # address=None targets the connected peer (vetted + possibly tagged at
        # connect()); an explicit address is a per-call destination vetted here.
        _enforce_not_tripped()
        if address is not None:
            _check_connect(self.family, address)
            screen_this = _is_external_screen_target(self.family, address)
        else:
            # Connected peer: screen iff this socket was tagged external at connect.
            screen_this = self._screen_outbound_enabled
        # sendmsg takes an iterable of buffers; screen each constituent buffer.
        if screen_this and _screeners:
            for buf in buffers:
                _screen_outbound(buf)
        return super().sendmsg(buffers, ancdata, flags, address)


def real_getaddrinfo(host, *args, **kwargs):
    """The ORIGINAL socket.getaddrinfo captured before arm() — for a TRUSTED
    in-runtime SSRF pre-check that must resolve a host WITHOUT tripping the armed
    guard. NOT a general egress bypass: the caller MUST immediately validate the
    result and MUST route any actual connection through the guarded path. Used by
    guarded_fetch's pre-fetch resolve-and-recheck (the door resolves to INSPECT
    and REFUSE internal targets; it never connects off-allowlist)."""
    return _REAL_GETADDRINFO(host, *args, **kwargs)


def _guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    _enforce_not_tripped()
    host_is_external_name = _requires_external_dns(host)
    host_str = (
        host.decode("ascii", "replace")
        if isinstance(host, (bytes, bytearray))
        else str(host)
    )
    host_name_allowlisted = host_is_external_name and _name_allowlisted_any_port(host_str)
    if host_is_external_name:
        # A DNS query for an external host is itself egress (and an exfil vector).
        # Unless that host is on the widened allowlist (for ANY port — DNS carries
        # no port), resolving it is an anomaly. The connect-time check still
        # enforces the exact port, so resolving a name allowlisted only for :443
        # does not permit a connect to that host on some other port.
        if not host_name_allowlisted:
            trip(f"DNS resolution of off-allowlist host {host_str!r} (Fail-Closed)")
            raise EgressDenied(
                f"egress guard: DNS resolution of external host {host!r} denied "
                f"(Fail-Closed; localhost + Hyper-V + vetted endpoints; kill-switch tripped)"
            )
    result = _REAL_GETADDRINFO(host, *args, **kwargs)
    # W4 resolution pin (ADR-024 amendment): an allowlisted hostname that just
    # resolved gets its numeric IPs pinned back to the name, so the HTTP client's
    # subsequent connect to one of those IPs is admitted at the allowlisted port
    # (and screened — the pinned IP tags the socket via _is_external_screen_target).
    # Only allowlisted external NAMES are pinned; a numeric-literal host or an
    # off-allowlist name is never pinned (the latter already tripped above).
    if host_name_allowlisted:
        _record_resolution_pins(host_str, result)
    return result


# ---------------------------------------------------------------------------
# ADR-027 public API — screener registration + allowlist-widening mechanism.
# ---------------------------------------------------------------------------


def register_screener(screener: OutboundScreener) -> None:
    """Register an outbound-payload screener on the egress path (ADR-027 rule 4).

    INTERFACE ANCHOR (H-b integrates against this exact signature). The H-b
    ``exfil_screen`` module calls this at :func:`arm` time (a registration
    pattern, so egress_guard never imports the screener module — no circular
    import). Once armed, every outbound payload on a guarded socket is passed to
    each registered screener; a positive detection (a :class:`ScreenResult` with
    ``detected=True``, or a bare ``True``) cuts ALL egress via :func:`trip`
    (ADR-027 §3 + rule 4 block-on-detection).

    Registration is additive and de-duplicating: registering the same callable
    twice keeps a single entry (idempotent at boot). Registering does not by
    itself enable any external egress — the address allowlist still governs
    *where* a payload may go; the screener governs *whether* a permitted payload
    is clean.

    :param screener: ``Callable[[bytes], ScreenResult | bool | None]`` — given the
        outbound bytes, returns a positive/negative verdict. MUST NOT itself
        perform egress; MUST NOT leak the matched secret into its return ``reason``.
    """
    if not callable(screener):
        raise TypeError("register_screener requires a callable screener")
    if screener not in _screeners:
        _screeners.append(screener)
        logger.info(
            "Egress guard: outbound screener registered (%d active)", len(_screeners)
        )


def clear_screeners() -> None:
    """Remove all registered screeners. Intended for tests (arm/disarm symmetry)."""
    _screeners.clear()


def registered_screener_count() -> int:
    """Number of outbound screeners currently registered."""
    return len(_screeners)


def allow_external_endpoint(host: str, port: int | str = _ALLOWLIST_ANY_PORT) -> None:
    """Widen the allowlist by ONE vetted external endpoint (ADR-027 §1).

    Deny-by-default: nothing reaches the internet unless added here, one vetted
    ``(host, port)`` at a time, each added only as the feature that needs it ships
    (ADR-027 §1 — "starts with Kagi and grows one vetted endpoint at a time").

    **STAGED/DORMANT this sprint:** this mechanism EXISTS but the live list is NOT
    widened — no caller invokes it in runtime code, so the active allowlist stays
    loopback + AF_HYPERV only and external egress remains fully denied. The first
    real call lands when W4 Kagi search ships post-#556. (Calling it does not by
    itself open egress: the kill-switch is still default-off, the PA still
    adjudicates per ADR-027 rule 2, and the exfil screen still applies per rule 4.)

    :param host: the external host — a numeric IP or a DNS name. A loopback host is
        rejected (already allowed; an explicit external entry is the point).
    :param port: the TCP port, or ``"*"`` for any port on the host.
    :raises ValueError: if ``host`` is empty or resolves to loopback.
    """
    if not host or not isinstance(host, str):
        raise ValueError("allow_external_endpoint requires a non-empty host string")
    if _is_loopback_host(host):
        raise ValueError(
            f"allow_external_endpoint: {host!r} is loopback — already permitted; "
            f"the widening mechanism is for EXTERNAL endpoints only"
        )
    entry = (host, str(port))
    _external_allowlist.add(entry)
    logger.warning(
        "Egress guard: external endpoint ADDED to allowlist %r (ADR-027 §1; "
        "allowlist now has %d external entr%s)",
        entry,
        len(_external_allowlist),
        "y" if len(_external_allowlist) == 1 else "ies",
    )


def revoke_external_endpoint(host: str, port: int | str = _ALLOWLIST_ANY_PORT) -> None:
    """Remove a previously-added external endpoint from the allowlist (ADR-027 §1).

    Also drops any resolution pins recorded for ``host`` (the W4 enabling
    enhancement, ADR-024 amendment): once the endpoint is revoked, the numeric IPs
    that the host resolved to are no longer admitted — deny-by-default is restored
    for them immediately, not left lingering as stale pins. This is what makes the
    ``allow_external_endpoint(host) -> fetch -> revoke_external_endpoint(host)``
    widen/revoke pair in :mod:`shared.security.guarded_fetch` fully fail-closed:
    after the revoke, the host is denied by name AND by every IP it had resolved to.
    """
    _external_allowlist.discard((host, str(port)))
    _drop_resolution_pins_for_host(host)


def external_allowlist() -> frozenset[tuple[str, str]]:
    """A snapshot of the widened external allowlist (empty == dormant baseline)."""
    return frozenset(_external_allowlist)


def clear_external_allowlist() -> None:
    """Empty the widened external allowlist AND all resolution pins. Intended for tests."""
    _external_allowlist.clear()
    _clear_resolution_pins()


def resolution_pins() -> dict[str, frozenset[str]]:
    """A snapshot of the hostname-resolution pin map (``ip -> {hostnames}``).

    The W4 enabling enhancement (ADR-024 amendment): records which allowlisted
    hostnames each numeric IP was resolved from, so the HTTP client's connect to a
    resolved IP is admitted at the allowlisted port. Empty when no allowlisted host
    has been resolved (the dormant baseline). Intended for tests / introspection.
    """
    with _resolution_pins_lock:
        return {ip: frozenset(hosts) for ip, hosts in _resolution_pins.items()}


def clear_resolution_pins() -> None:
    """Forget all hostname-resolution pins. Intended for tests (symmetry with clear_*)."""
    _clear_resolution_pins()


# ---------------------------------------------------------------------------
# ADR-027 — arm-time setup hooks (the no-circular-import registration seam).
# ---------------------------------------------------------------------------
# A module that must do egress-related setup *at arm() time* — chiefly the H-b
# exfil-screen module wiring its screener via register_screener() — appends a
# zero-arg callable here with register_arm_hook(). arm() runs every hook (once)
# after installing the socket guard. This is the registration pattern that keeps
# egress_guard import-free of the screen module: the screen module imports US and
# registers a hook; we never import it.

ArmHook = Callable[[], None]
_arm_hooks: list[ArmHook] = []


def register_arm_hook(hook: ArmHook) -> None:
    """Register a zero-arg setup callback to run at :func:`arm` time (ADR-027).

    Used by the exfil-screen module to wire its screener via
    :func:`register_screener` exactly when the guard arms — a registration
    pattern that avoids a circular import (the screen module imports egress_guard;
    egress_guard never imports the screen module). De-duplicating. If the guard is
    ALREADY armed when a hook is registered, the hook is run immediately so a
    late-imported screen module still takes effect.
    """
    if not callable(hook):
        raise TypeError("register_arm_hook requires a callable")
    if hook not in _arm_hooks:
        _arm_hooks.append(hook)
        if _armed:
            _run_one_arm_hook(hook)


def clear_arm_hooks() -> None:
    """Remove all registered arm hooks. Intended for tests (arm/disarm symmetry)."""
    _arm_hooks.clear()


def _run_one_arm_hook(hook: ArmHook) -> None:
    """Run a single arm hook, failing closed if it raises (ADR-027 §3).

    A screener-registration hook that errors means the exfil screen would NOT be
    installed — an open door. Fail-Closed: trip the kill-switch so no payload can
    leave through an un-screened path until the operator resolves it.
    """
    try:
        hook()
    except Exception as exc:  # noqa: BLE001 - a failed egress-setup hook fails closed
        trip(f"arm-hook {getattr(hook, '__name__', repr(hook))} raised ({type(exc).__name__}) — failing closed")
        logger.error("Egress guard arm-hook failed; kill-switch tripped", exc_info=True)


def _run_arm_hooks() -> None:
    for hook in list(_arm_hooks):
        _run_one_arm_hook(hook)


_armed: bool = False


def arm() -> None:
    """Install the egress guard process-wide. Idempotent; call once at entry.

    After arming, only loopback and AF_HYPERV sockets may be opened; all other
    egress is denied (and auto-trips the kill-switch — ADR-027 §3). Arming then
    runs every registered arm hook (ADR-027): this is where the exfil-screen
    module wires its screener via :func:`register_screener`, so outbound-payload
    screening (ADR-027 rule 4) is live from the first armed socket onward. Safe to
    call more than once (a second call is a no-op and does NOT re-run hooks).
    """
    global _armed
    if _armed:
        return
    socket.socket = _GuardedSocket  # type: ignore[misc,assignment]
    socket.getaddrinfo = _guarded_getaddrinfo  # type: ignore[assignment]
    _armed = True
    # Run arm hooks AFTER the guard is installed so any setup they do (incl. a
    # screener that opens a loopback resource) runs under the armed allowlist.
    _run_arm_hooks()
    logger.info(
        "Egress guard ARMED (Fail-Closed allowlist: loopback + AF_HYPERV; "
        "all other network egress denied; %d screener(s), %d external allowlist "
        "entr%s)",
        len(_screeners),
        len(_external_allowlist),
        "y" if len(_external_allowlist) == 1 else "ies",
    )


def disarm() -> None:
    """Restore the standard-library socket surface. Idempotent.

    Intended for tests; production processes arm once and never disarm. Clears the
    trip latch (so a tripped guard does not leak into the next test) AND the
    resolution pins (the W4 hostname-resolution map — a pinned IP must never bleed
    into the next test's address checks), but leaves registered screeners /
    arm-hooks / the external allowlist intact — tests that need a pristine machinery
    state call the dedicated ``clear_*`` helpers.
    """
    global _armed
    if not _armed:
        return
    socket.socket = _REAL_SOCKET  # type: ignore[misc,assignment]
    socket.getaddrinfo = _REAL_GETADDRINFO  # type: ignore[assignment]
    _armed = False
    # Releasing the latch on disarm keeps the global trip-state from bleeding
    # across tests; production never disarms, so this has no runtime effect.
    rearm()
    # Drop resolution pins too: a numeric IP pinned in one test must not be
    # treated as allowlisted in the next (the external allowlist is left intact by
    # contract, but the pins are derived live state and are cleared on disarm).
    _clear_resolution_pins()
    logger.info("Egress guard disarmed")


def is_armed() -> bool:
    """True iff the egress guard is currently installed in this process."""
    return _armed
