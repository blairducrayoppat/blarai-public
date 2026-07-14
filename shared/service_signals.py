"""Graceful-drain signal handlers for the long-lived service entrypoints.

AUDIT-13 (#812): the AO and PA service wrappers
(``AssistantOrchestratorService``, ``PolicyAgentService``) had no independent
graceful-drain on a termination signal — their only shutdown path was the
launcher calling ``.stop()`` (backed by the Job-Object kill-on-close). 12-Factor
IX (disposability) wants a process to catch ``SIGTERM`` and drain its OWN work
rather than depend on an external supervisor to reap it.

This module gives each service that ability WITHOUT coupling it to the launcher:
:func:`install_graceful_shutdown` maps the termination signals to the service's
own ``stop`` callable. It is **opt-in** — the process leader decides to call it —
and **fail-safe**: ``signal.signal`` only works on the main thread of the main
interpreter, so a call from anywhere else (a worker thread, an embedded/test
context) is caught and reported, never raised. A failure to arm degrades to "no
handler"; the launcher's kill-on-close remains the backstop.

Co-residency note: only ONE handler per signal survives in a process. In the
default host topology the AO + PA are co-resident inside the launcher process,
which owns signal disposition and already drains both via ``stop()``; the
intended callers of THIS helper are the process-leader topologies — a future
standalone/headless AO, or the PA running as its own process in the VM guest —
where the service itself receives the signal. Wiring the launcher's own
single-per-process SIGTERM to drain BOTH co-resident services is a separate
decision (ordering + which service owns the disposition), deliberately left to
the launcher rather than self-wired here.
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)

#: The termination signals a long-lived service drains on. ``SIGTERM`` is the
#: 12-Factor IX disposability signal (AUDIT-13); ``SIGINT`` is its interactive
#: sibling (Ctrl-C). Both are defined on Windows and POSIX. A platform that is
#: missing one simply skips it (fail-safe) rather than failing the install.
DEFAULT_SHUTDOWN_SIGNALS: tuple[int, ...] = (signal.SIGTERM, signal.SIGINT)


def install_graceful_shutdown(
    stop: Callable[[], object],
    *,
    service_name: str,
    signals: Iterable[int] | None = None,
) -> tuple[int, ...]:
    """Map termination signals to *stop* for a graceful, self-owned drain.

    Args:
        stop: the service's own graceful-shutdown callable (e.g. ``service.stop``).
            It is invoked from the signal handler, which — in CPython — runs on
            the main thread between bytecodes, so calling ordinary (bounded)
            Python is safe. ``stop`` MUST be idempotent/re-entrant-safe: a second
            signal during a drain will call it again (the AO/PA ``stop()`` methods
            null-check every member and are safe to re-call).
        service_name: human label for the log lines (e.g. ``"PolicyAgent"``).
        signals: the signals to arm; defaults to :data:`DEFAULT_SHUTDOWN_SIGNALS`.

    Returns:
        The tuple of signal numbers for which a handler was actually installed —
        empty if none (called off the main thread, or every requested signal was
        unavailable on this platform). Never raises: a failure to install
        degrades to "no handler armed", it never takes down the caller.
    """
    if threading.current_thread() is not threading.main_thread():
        logger.warning(
            "%s: cannot install signal handlers off the main thread; "
            "graceful-drain-on-signal not armed (the launcher's kill-on-close "
            "remains the backstop).",
            service_name,
        )
        return ()

    requested = tuple(signals) if signals is not None else DEFAULT_SHUTDOWN_SIGNALS
    installed: list[int] = []

    def _handler(signum: int, _frame: object) -> None:
        try:
            name = signal.Signals(signum).name
        except ValueError:  # pragma: no cover - non-enum signum
            name = str(signum)
        logger.info(
            "%s: received %s — draining gracefully (AUDIT-13 disposability).",
            service_name,
            name,
        )
        stop()

    for sig in requested:
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError, RuntimeError) as exc:
            # ValueError: off the main thread, or the signal is unsupported on
            # this platform. OSError/RuntimeError: the platform refused the
            # registration. Any of these → skip THIS signal, keep the others.
            logger.warning(
                "%s: could not install handler for signal %s (%s); skipping.",
                service_name,
                sig,
                exc,
            )
            continue
        installed.append(sig)

    if installed:
        logger.info(
            "%s: graceful-drain handlers armed for signal(s) %s (independent of "
            "the launcher).",
            service_name,
            ", ".join(str(s) for s in installed),
        )
    return tuple(installed)
