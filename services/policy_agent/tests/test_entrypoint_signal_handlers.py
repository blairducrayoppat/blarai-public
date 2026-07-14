"""PA ``install_signal_handlers`` delegates to the shared drain helper (#812).

Thin delegation tests (the mechanics are covered in
``shared/tests/test_service_signals.py``): prove the PA method wires its OWN
``stop`` and label into the helper. ``__new__`` skips the heavy ``__init__``.
"""

from __future__ import annotations

import signal
from unittest.mock import patch

from services.policy_agent.src.entrypoint import PolicyAgentService

_HELPER = "services.policy_agent.src.entrypoint.install_graceful_shutdown"


class TestInstallSignalHandlers:
    def test_delegates_with_own_stop_and_label(self) -> None:
        svc = PolicyAgentService.__new__(PolicyAgentService)
        with patch(_HELPER) as helper:
            helper.return_value = (signal.SIGTERM, signal.SIGINT)
            result = svc.install_signal_handlers()
        helper.assert_called_once()
        assert helper.call_args.args[0] == svc.stop  # drains THIS service
        assert helper.call_args.kwargs["service_name"] == "PolicyAgent"
        assert result == (signal.SIGTERM, signal.SIGINT)

    def test_forwards_explicit_signals(self) -> None:
        svc = PolicyAgentService.__new__(PolicyAgentService)
        with patch(_HELPER) as helper:
            helper.return_value = (signal.SIGTERM,)
            svc.install_signal_handlers(signals=(signal.SIGTERM,))
        assert helper.call_args.kwargs["signals"] == (signal.SIGTERM,)
