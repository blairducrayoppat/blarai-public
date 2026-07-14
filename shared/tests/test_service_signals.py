"""Unit tests for the graceful-drain signal helper (AUDIT-13 / #812).

The helper gives the long-lived service wrappers a SIGTERM/SIGINT → ``stop()``
drain that is independent of the launcher. These tests patch ``signal.signal``
so NO real handler is ever installed in the pytest process (installing a real
SIGTERM/SIGINT handler would perturb the test runner) — the mock records the
registration and lets us invoke the captured handler directly.
"""

from __future__ import annotations

import signal
import threading
from unittest.mock import MagicMock, patch

from shared.service_signals import (
    DEFAULT_SHUTDOWN_SIGNALS,
    install_graceful_shutdown,
)


class TestInstallGracefulShutdown:
    def test_default_arms_sigterm_and_sigint(self) -> None:
        stop = MagicMock()
        with patch("shared.service_signals.signal.signal") as sig_signal:
            installed = install_graceful_shutdown(stop, service_name="Svc")
        assert installed == DEFAULT_SHUTDOWN_SIGNALS
        assert signal.SIGTERM in installed
        assert signal.SIGINT in installed
        registered = {c.args[0] for c in sig_signal.call_args_list}
        assert registered == set(DEFAULT_SHUTDOWN_SIGNALS)
        stop.assert_not_called()  # arming must not drain

    def test_explicit_signal_subset(self) -> None:
        stop = MagicMock()
        with patch("shared.service_signals.signal.signal") as sig_signal:
            installed = install_graceful_shutdown(
                stop, service_name="Svc", signals=(signal.SIGTERM,)
            )
        assert installed == (signal.SIGTERM,)
        sig_signal.assert_called_once()
        assert sig_signal.call_args.args[0] == signal.SIGTERM

    def test_handler_invokes_stop_once(self) -> None:
        stop = MagicMock()
        captured: dict[int, object] = {}

        def _record(sig: int, handler: object) -> None:
            captured[sig] = handler

        with patch("shared.service_signals.signal.signal", side_effect=_record):
            install_graceful_shutdown(
                stop, service_name="Svc", signals=(signal.SIGTERM,)
            )
        handler = captured[signal.SIGTERM]
        assert callable(handler)
        handler(int(signal.SIGTERM), None)  # simulate the OS delivering SIGTERM
        stop.assert_called_once_with()

    def test_off_main_thread_arms_nothing(self) -> None:
        stop = MagicMock()
        result: dict[str, object] = {}

        def _worker() -> None:
            with patch("shared.service_signals.signal.signal") as sig_signal:
                result["installed"] = install_graceful_shutdown(
                    stop, service_name="Svc"
                )
                result["signal_calls"] = sig_signal.call_count

        t = threading.Thread(target=_worker, name="svc-signals-offmain")
        t.start()
        t.join(timeout=5.0)
        assert result["installed"] == ()
        assert result["signal_calls"] == 0  # guard returns BEFORE touching signal
        stop.assert_not_called()

    def test_unsupported_signal_is_skipped_others_survive(self) -> None:
        stop = MagicMock()

        def _maybe_fail(sig: int, _handler: object) -> None:
            if sig == signal.SIGINT:
                raise ValueError("unsupported on this platform")

        with patch("shared.service_signals.signal.signal", side_effect=_maybe_fail):
            installed = install_graceful_shutdown(
                stop, service_name="Svc", signals=(signal.SIGTERM, signal.SIGINT)
            )
        # SIGINT raised → skipped; SIGTERM still armed.
        assert installed == (signal.SIGTERM,)

    def test_all_signals_failing_returns_empty(self) -> None:
        stop = MagicMock()
        with patch(
            "shared.service_signals.signal.signal", side_effect=OSError("nope")
        ):
            installed = install_graceful_shutdown(
                stop, service_name="Svc", signals=(signal.SIGTERM,)
            )
        assert installed == ()
        stop.assert_not_called()
