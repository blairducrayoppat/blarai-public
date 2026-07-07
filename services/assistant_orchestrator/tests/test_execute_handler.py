"""Tests — AO EXECUTE handler + _fire_swap (#670, sub-part 3b).

``_handle_execute_request`` fires the operator-APPROVED dispatch: enqueue + hand off to the
detached swap driver, REPLY, then step the launcher aside. The dangerous live parts (the
launcher actually exiting, the 30B loading + FITTING, the 14B coming back) are Phase-B-only;
these tests bind the unbound methods to a stand-in and inject fakes for the swap + the
step-aside callable, so they assert the WIRING + the ORDERING without ever exiting:

  * the EXECUTE_RESULT reply is sent BEFORE the step-aside (the operator sees the notice
    before the WinUI closes);
  * an enqueue refusal (ok=False) does NOT step aside (the 14B stays up);
  * a missing launcher context fails closed and never steps aside;
  * the approved tasks flow through verbatim;
  * _fire_swap passes old_pid=os.getpid(), gate_gb=the configured safety threshold (never a
    default), and the launcher-captured relaunch.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from services.assistant_orchestrator.src import entrypoint
from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)
from shared.ipc.protocol import MessageFramer
from shared.fleet.swap_ops import SwapDispatchResult


class _FakeTransport:
    def __init__(self, events: list) -> None:
        self.sent: list[bytes] = []
        self._events = events

    def send(self, frame: bytes) -> bool:
        self.sent.append(frame)
        self._events.append("reply")
        return True


class _ExecHarness:
    """Stand-in carrying just what _handle_execute_request reads — _fire_swap is OVERRIDDEN
    to a fake (no real enqueue / driver spawn / swap)."""

    def __init__(self, tmp_path, *, fire_result, step_aside, grace=0.0, enabled=True) -> None:
        self._framer = MessageFramer()
        self._fire_result = fire_result
        self._fire_calls: list[dict] = []
        self._swap_step_aside = step_aside
        self._swap_relaunch_argv = ["py", "-m", "launcher", "--winui"]
        self._swap_relaunch_cwd = "C:/repo"
        self._resolved_config = SimpleNamespace(
            fleet_dispatch_enabled=enabled,
            fleet_dispatch_agentic_setup_dir=str(tmp_path / "agentic"),
            fleet_dispatch_projects_dir=str(tmp_path / "projects"),
            swap_min_free_gb=21.0,
            step_aside_grace_s=grace,
        )
        self._asset_calls: list = []

    def _maybe_generate_dispatch_assets(self, tasks, config, session_id):
        # SEAM A stand-in: record the pre-swap asset call (and how many swaps had fired,
        # proving it runs BEFORE _fire_swap). Real generation is exercised in
        # test_dispatch_asset_generation.py; here we assert only the WIRING/ORDERING.
        self._asset_calls.append({"session_id": session_id, "fires_before": len(self._fire_calls)})

    def _fire_swap(self, run_id, session_id, tasks, config):
        self._fire_calls.append(
            {"run_id": run_id, "session_id": session_id, "tasks": tasks, "config": config}
        )
        return self._fire_result

    _handle_execute_request = AssistantOrchestratorService._handle_execute_request
    fleet_dispatch_enabled = AssistantOrchestratorService.fleet_dispatch_enabled
    fleet_dispatch_agentic_setup_dir = (
        AssistantOrchestratorService.fleet_dispatch_agentic_setup_dir
    )
    fleet_dispatch_projects_dir = AssistantOrchestratorService.fleet_dispatch_projects_dir
    swap_min_free_gb = AssistantOrchestratorService.swap_min_free_gb
    step_aside_grace_s = AssistantOrchestratorService.step_aside_grace_s


def _ok(run_id="RID-DET"):
    return SwapDispatchResult(ok=True, run_id=run_id, tasks=[{"x": 1}], message=f"Dispatching {run_id}…")


def _fail(run_id="RID-DET"):
    return SwapDispatchResult(ok=False, run_id=run_id, message="Could not enqueue — refused.")


def test_execute_ok_replies_then_steps_aside(tmp_path):
    events: list = []
    h = _ExecHarness(tmp_path, fire_result=_ok(), step_aside=lambda: events.append("step_aside"))
    t = _FakeTransport(events)
    assert h._handle_execute_request(t, "rid1", {"session_id": "s", "run_id": "RID-DET",
                                                 "tasks": [{"repo": "R", "task": "a", "prompt": "p"}]})
    payload = h._framer.decode_execute_result(t.sent[0])
    assert payload["ok"] is True and payload["run_id"] == "RID-DET"
    # ORDERING: the reply is sent BEFORE the step-aside (operator sees it before WinUI closes)
    assert events == ["reply", "step_aside"]
    # the approved tasks flowed to the swap verbatim
    assert h._fire_calls[0]["tasks"] == [{"repo": "R", "task": "a", "prompt": "p"}]
    # the progress trail was persisted (restart-surviving)
    from shared.fleet.swap_ops import build_default_config, read_swap_progress
    cfg = build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    trail = read_swap_progress(cfg, "RID-DET")
    assert "stepping aside" in trail.lower() and "driver spawned" in trail.lower()


def test_execute_generates_assets_before_firing_the_swap(tmp_path):
    # SEAM A wiring: the EXECUTE handler generates dispatch assets (14B resident) BEFORE it
    # fires the swap, passing the approved tasks + session id. (Generation itself is dormant
    # + fail-soft; this asserts only that the seam is invoked in the right place/order.)
    events: list = []
    h = _ExecHarness(tmp_path, fire_result=_ok(), step_aside=lambda: events.append("step_aside"))
    t = _FakeTransport(events)
    tasks = [{"repo": "R", "task": "a", "prompt": "p"}]
    h._handle_execute_request(t, "rid", {"session_id": "s", "run_id": "RID-DET", "tasks": tasks})
    assert len(h._asset_calls) == 1
    assert h._asset_calls[0]["session_id"] == "s"
    assert h._asset_calls[0]["fires_before"] == 0     # assets generated BEFORE the swap fired
    assert len(h._fire_calls) == 1                    # ...and the swap still fired


def test_execute_failure_does_not_step_aside(tmp_path):
    # An enqueue refusal -> ok=False reply, and NO step-aside (the 14B stays up).
    events: list = []
    h = _ExecHarness(tmp_path, fire_result=_fail(), step_aside=lambda: events.append("step_aside"))
    t = _FakeTransport(events)
    assert h._handle_execute_request(t, "rid1", {"session_id": "s", "run_id": "RID-DET", "tasks": [{"repo": "R", "task": "a", "prompt": "p"}]})
    payload = h._framer.decode_execute_result(t.sent[0])
    assert payload["ok"] is False
    assert "step_aside" not in events            # NEVER step aside on an enqueue failure
    assert events == ["reply"]


def test_execute_not_launcher_wired_fails_closed(tmp_path):
    # No step-aside callable provisioned -> fail closed, never fire the swap, never step aside.
    events: list = []
    h = _ExecHarness(tmp_path, fire_result=_ok(), step_aside=None)
    t = _FakeTransport(events)
    assert h._handle_execute_request(t, "rid1", {"session_id": "s", "run_id": "RID-DET", "tasks": [{"repo": "R", "task": "a", "prompt": "p"}]})
    payload = h._framer.decode_execute_result(t.sent[0])
    assert payload["ok"] is False and "not wired" in payload["message"].lower()
    assert h._fire_calls == [] and events == ["reply"]


def test_execute_disabled_fails_closed_independent_of_launcher(tmp_path):
    # Dormancy lock (defense-in-depth): even with the launcher's swap context fully wired,
    # a disabled AO ([fleet_dispatch].enabled=false) refuses to swap — never fires, never
    # steps aside. This is the second lock the unconditional set_swap_context would otherwise
    # have dropped (LA finding).
    events: list = []
    h = _ExecHarness(tmp_path, fire_result=_ok(),
                     step_aside=lambda: events.append("step_aside"), enabled=False)
    t = _FakeTransport(events)
    assert h._handle_execute_request(t, "rid1", {"session_id": "s", "run_id": "R",
                                                 "tasks": [{"repo": "R", "task": "a", "prompt": "p"}]})
    payload = h._framer.decode_execute_result(t.sent[0])
    assert payload["ok"] is False and "disabled" in payload["message"].lower()
    assert h._fire_calls == [] and "step_aside" not in events  # never fired, never stepped aside


def test_execute_fire_error_fails_closed_no_step_aside(tmp_path):
    events: list = []
    h = _ExecHarness(tmp_path, fire_result=_ok(), step_aside=lambda: events.append("step_aside"))
    # make _fire_swap raise
    h._fire_swap = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    t = _FakeTransport(events)
    assert h._handle_execute_request(t, "rid1", {"session_id": "s", "run_id": "R", "tasks": []})
    payload = h._framer.decode_execute_result(t.sent[0])
    assert payload["ok"] is False and "step_aside" not in events


# ---- _fire_swap: old_pid / safety gate / launcher relaunch ----------------


def test_fire_swap_passes_pid_safety_gate_and_relaunch(monkeypatch):
    captured = {}

    def _fake_execute(run_id, session_id, tasks, *, config, gate_gb, run_budget_s, old_pid,
                      relaunch_argv, relaunch_cwd):
        captured.update(
            run_id=run_id, tasks=tasks, gate_gb=gate_gb, run_budget_s=run_budget_s,
            old_pid=old_pid, relaunch_argv=relaunch_argv, relaunch_cwd=relaunch_cwd,
        )
        return _ok(run_id)

    monkeypatch.setattr(entrypoint, "execute_swap_dispatch", _fake_execute)
    stub = SimpleNamespace(
        swap_min_free_gb=21.0,
        swap_run_budget_s=5400.0,                          # #670 P2 out-of-band budget
        _swap_relaunch_argv=["py", "-m", "launcher", "--winui"],
        _swap_relaunch_cwd="C:/repo",
    )
    AssistantOrchestratorService._fire_swap(
        stub, "RID", "s", [{"repo": "R", "task": "t", "prompt": "p"}], None
    )
    assert captured["old_pid"] == os.getpid()             # the launcher PID = this process
    assert captured["gate_gb"] == 21.0                    # the CONFIGURED safety threshold
    assert captured["run_budget_s"] == 5400.0             # the CONFIGURED overall-run budget
    assert captured["relaunch_argv"] == ["py", "-m", "launcher", "--winui"]
    assert captured["relaunch_cwd"] == "C:/repo"
    assert captured["tasks"] == [{"repo": "R", "task": "t", "prompt": "p"}]


def test_set_swap_context_stores_relaunch_and_callable():
    # The launcher provides the AO its swap context at startup (the REAL relaunch + the
    # daemon→main step-aside). Unset -> _handle_execute_request fails closed (tested above).
    stub = SimpleNamespace()

    def _sentinel() -> None:
        pass

    AssistantOrchestratorService.set_swap_context(
        stub, relaunch_argv=["py", "-m", "launcher", "--winui"],
        relaunch_cwd="C:/repo", step_aside=_sentinel,
    )
    assert stub._swap_relaunch_argv == ["py", "-m", "launcher", "--winui"]
    assert stub._swap_relaunch_cwd == "C:/repo"
    assert stub._swap_step_aside is _sentinel


def test_swap_run_budget_resolver_clamps_non_positive():
    # The resolver clamps a non-positive / non-numeric configured budget to 0.0 (DISABLED), never
    # an instant-timeout (#670 P2). cfg None (early boot) -> the field default.
    fget = AssistantOrchestratorService.swap_run_budget_s.fget

    def resolved(value):
        return fget(SimpleNamespace(_resolved_config=SimpleNamespace(swap_run_budget_s=value)))

    assert resolved(5400.0) == 5400.0
    assert resolved(-10.0) == 0.0          # negative disables
    assert resolved(0) == 0.0
    assert resolved("bad") == 0.0          # non-numeric disables (never crash the resolver)
    assert fget(SimpleNamespace(_resolved_config=None)) == 5400.0
