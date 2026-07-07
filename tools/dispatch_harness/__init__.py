"""Autonomous-dispatch harness — a HEADLESS GATEWAY DRIVER for the ``/dispatch`` pipeline.

This is a dev/ops tool (NOT a pytest unit test, NOT a BlarAI runtime module). It drives the
SAME ``/dispatch <repo> | <goal>`` → PLAN preview → (Inc-4 clarifying question) →
``/dispatch approve`` → monitor flow the WinUI drives, but without the GUI, so the Dispatch
LA can run autonomous test dispatches across project types (the "sweep") hands-off.

The one-line shape: construct the real :class:`~services.ui_gateway.src.transport.TransportGateway`
(``dev_mode=True``, TCP loopback ``127.0.0.1:5001``, ``fleet_dispatch_enabled=True``, the
agentic-setup/projects roots) and drive its ``handle_dispatch_command`` exactly as the WinUI's
backend dispatcher does. It reuses the coordinator + the IPC + the swap — it is a headless WinUI,
NOT a second implementation. It modifies NO BlarAI runtime module.

The AO must already be running (the live path needs the full launcher for the model swap; v1
connects to a running AO at ``:5001`` and fails clearly if it cannot reach it). A ``--dry-run``
mode exercises the whole flow against a FAKE in-process AO (injected plan/execute fns + a fake
fleet-run dir), so the harness is provable without the GPU.

Monitoring is SMART with stop-doomed-fast: it reads the FLEET orchestrator log (journal.log +
the per-task run-fleet log) + the OVMS out-log mtime + the coder child-process CPU to detect a
DETERMINED-doomed run and stop it FAST (the clean ``/dispatch stop`` path) rather than waiting
out the run-budget breaker. It deliberately does NOT grep the coder agent log for tokens like
"parked"/"CS0246" — that echoes seed documentation and is a false-positive trap.

Public surface (the pure, unit-tested pieces + the live driver):

* :mod:`tools.dispatch_harness.jobs`     — the job-config dataclass + parser.
* :mod:`tools.dispatch_harness.clarify`  — the clarifying-answer → option-number mapping.
* :mod:`tools.dispatch_harness.monitor`  — the doom-detection predicate + outcome classifier
                                            + the live :class:`RunMonitor`.
* :mod:`tools.dispatch_harness.report`   — the structured per-job + sweep report assembly.
* :mod:`tools.dispatch_harness.harness`  — :class:`DispatchHarness`, the gateway driver.
* :mod:`tools.dispatch_harness.config`   — resolve port + fleet roots from the AO config.
"""

from __future__ import annotations

from tools.dispatch_harness.jobs import JobSpec, load_jobs, parse_jobs
from tools.dispatch_harness.clarify import pick_clarify_answer
from tools.dispatch_harness.monitor import (
    DoomVerdict,
    RunSignals,
    classify_outcome,
    classify_run_health,
)
from tools.dispatch_harness.report import JobReport, SweepReport

__all__ = [
    "JobSpec",
    "load_jobs",
    "parse_jobs",
    "pick_clarify_answer",
    "DoomVerdict",
    "RunSignals",
    "classify_outcome",
    "classify_run_health",
    "JobReport",
    "SweepReport",
]
