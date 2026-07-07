"""
Parser-Channel Seam — the launcher↔parse-channel integration point (#655 Stage C)
==================================================================================
The UC-003 guest-homed parser's *message types* (the parse/health frames on
``shared/ipc/protocol.py``) are built on a PARALLEL branch.  This module is the
small, deliberate seam that lets the launcher's guest-parser lifecycle
(:mod:`launcher.guest_parser`) reference the health-check frame ABSTRACTLY so
the two branches bind at integration time without either touching the other's
files:

  * The parallel branch (or the integration commit that follows both) imports
    its parse-channel client, wraps a "send HEALTH frame, expect OK" call in a
    :data:`HealthProbe`, and registers it here at launcher startup.
  * :class:`launcher.guest_parser.GuestParserManager` calls
    :func:`get_parser_health_probe` and FAILS CLOSED while no probe is bound —
    an unbound channel means the guest parser can never be reported READY, so
    URL-mode ingest stays refused (ADR-030 §3: silent host-side fallback is the
    named anti-pattern; refusal is the only legal degradation).

Mirrors the registry shape of ``shared.security.escalation_consent``
(register / get / clear-for-tests).  No frame format, no message-type enum,
and no protocol import appears here BY DESIGN — that is the parallel branch's
surface (do-not-touch boundary: ``shared/ipc/protocol.py``,
``services/cleaner/``).

Security:
  - Fail-Closed: unbound probe → guest parser unavailable → ingest URL mode
    refuses.  There is no default probe and no transport-level "good enough"
    substitute for the frame-level health check.
  - No external network calls.  The probe a binder registers talks AF_HYPERV
    vsock to the guest only.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParserEndpoint:
    """Where the guest parser listens — handed to bound probes/signals.

    Carries the Windows AF_HYPERV GUID pair (the #615-validated addressing
    form) plus the AF_VSOCK port the guest side binds, so a bound probe can
    construct its transport without re-reading launcher config.
    """

    vm_id: str
    """Hyper-V VM GUID (``VmId``) — the host targets a specific guest."""

    service_guid: str
    """hv_sock service GUID (``ServiceId``, ``<port_hex>-facb-…`` template)."""

    vsock_port: int
    """AF_VSOCK port the guest parser binds (mapped by ``service_guid``)."""

    timeout_s: float
    """Per-probe timeout budget in seconds."""


HealthProbe = Callable[[ParserEndpoint], bool]
"""Frame-level health check: True ⇢ the guest parser answered a HEALTH frame
correctly.  Must not raise for expected failures (return False); the manager
treats an escaped exception as a failed probe anyway (fail-closed)."""

StopSignal = Callable[[ParserEndpoint], bool]
"""Optional graceful-stop request to the guest parser.  Best-effort: the
authoritative stop remains the #657 VM stop-on-exit policy (the parser dies
with the VM)."""


_lock = threading.Lock()
_health_probe: Optional[HealthProbe] = None
_stop_signal: Optional[StopSignal] = None


def register_parser_health_probe(probe: HealthProbe) -> None:
    """Bind the frame-level health probe (integration-time, launcher startup).

    Last registration wins (a re-bind is logged loudly — the probe is a
    process-wide singleton and silent replacement would mask a double-wire).
    """
    global _health_probe
    with _lock:
        if _health_probe is not None:
            logger.warning(
                "parser-channel seam: health probe REPLACED (%r -> %r) — "
                "double registration is unexpected outside tests.",
                _health_probe,
                probe,
            )
        _health_probe = probe
    logger.info("parser-channel seam: health probe bound (%r)", probe)


def get_parser_health_probe() -> Optional[HealthProbe]:
    """Return the bound health probe, or None (unbound ⇒ fail closed)."""
    with _lock:
        return _health_probe


def register_parser_stop_signal(signal: StopSignal) -> None:
    """Bind the optional graceful-stop signal (integration-time)."""
    global _stop_signal
    with _lock:
        if _stop_signal is not None:
            logger.warning(
                "parser-channel seam: stop signal REPLACED (%r -> %r).",
                _stop_signal,
                signal,
            )
        _stop_signal = signal
    logger.info("parser-channel seam: stop signal bound (%r)", signal)


def get_parser_stop_signal() -> Optional[StopSignal]:
    """Return the bound stop signal, or None (then VM-stop is the stop)."""
    with _lock:
        return _stop_signal


def clear_parser_channel_bindings() -> None:
    """Unbind everything — TEST SEAM ONLY (restores the fail-closed default)."""
    global _health_probe, _stop_signal
    with _lock:
        _health_probe = None
        _stop_signal = None
