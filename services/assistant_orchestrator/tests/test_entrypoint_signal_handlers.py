"""AO ``install_signal_handlers`` delegates to the shared drain helper (#812).

Thin delegation tests: the signal-install mechanics live in
``shared/tests/test_service_signals.py``; here we only prove the AO method wires
its OWN ``stop`` and label into the helper. ``__new__`` skips the heavy
``__init__`` — the method never touches instance state beyond the bound
``self.stop``.
"""

from __future__ import annotations

import signal
from unittest.mock import patch

from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)

_HELPER = "services.assistant_orchestrator.src.entrypoint.install_graceful_shutdown"


class TestInstallSignalHandlers:
    def test_delegates_with_own_stop_and_label(self) -> None:
        svc = AssistantOrchestratorService.__new__(AssistantOrchestratorService)
        with patch(_HELPER) as helper:
            helper.return_value = (signal.SIGTERM, signal.SIGINT)
            result = svc.install_signal_handlers()
        helper.assert_called_once()
        assert helper.call_args.args[0] == svc.stop  # drains THIS service
        assert helper.call_args.kwargs["service_name"] == "AssistantOrchestrator"
        assert result == (signal.SIGTERM, signal.SIGINT)

    def test_forwards_explicit_signals(self) -> None:
        svc = AssistantOrchestratorService.__new__(AssistantOrchestratorService)
        with patch(_HELPER) as helper:
            helper.return_value = (signal.SIGTERM,)
            svc.install_signal_handlers(signals=(signal.SIGTERM,))
        assert helper.call_args.kwargs["signals"] == (signal.SIGTERM,)
